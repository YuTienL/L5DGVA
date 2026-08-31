"""Interactive dashboard tests -- POST /api/setup, /api/start, /api/control.

Starts dv_harness.dashboard.serve() for real, on a background daemon thread,
bound to a free local port, against a temp project (mirroring the
_fresh_harness()/_mk_smoke_project() pattern in test_engine_gates_and_routing.py),
and issues REAL HTTP requests against it (stdlib urllib only -- no new
dependency). This proves the dashboard's HTTP surface actually drives the
same control_plane.py/engine.py mechanisms the CLI does, not a parallel
reimplementation:

  - /api/setup persists project_meta.json and /api/state reflects it
  - /api/start refuses (400 NOT_CONFIGURED) before setup, launches a real
    DVHarness.loop()/run_stage() on a background thread otherwise (proven via
    an injected fake adapter -- see the adapter_factory seam in
    dashboard.serve()/_start_background_run(), which exists so this test
    suite never has to spawn a real `claude` CLI subprocess), and refuses a
    second concurrent start (409 ALREADY_RUNNING)
  - /api/control dispatches to the exact same dv_harness.commands functions
    cli.py's subcommands call -- verified here by reading control.json/
    events.jsonl/plans/*.json directly afterward, the same way
    test_engine_gates_and_routing.py's *_cli_* tests verify the CLI
  - malformed requests (bad Content-Type, invalid JSON, unknown command) get
    clean 4xx JSON, never a stack trace or a dropped connection, and the
    server keeps serving requests afterward
"""
from __future__ import annotations

import json
import shutil
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _mk_dashboard_project(port: int, policy_overrides: dict | None = None) -> Path:
    """A temp project with just enough on disk for DVHarness()/dashboard.serve()
    to run: a .dv-harness/config.json pinning the dashboard to a free local
    port and (by default) turning off the require_stage_gate_evidence hard
    gate + retries, so a FakeAdapter's plain ok=True response is enough to
    PASS a stage without needing real tools/*.py gate scripts on disk --
    mirrors _fresh_harness(with_graph=False) in test_engine_gates_and_routing.py.
    No main_graph.json is copied in: none of these tests need graph-driven
    routing, and DVHarness/advance()/human_redirect() all degrade cleanly
    (linear Stage-enum ORDER fallback) without one."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness").mkdir(parents=True, exist_ok=True)
    policy = {"require_stage_gate_evidence": False, "max_stage_retries": 0}
    if policy_overrides:
        policy.update(policy_overrides)
    cfg = {"dashboard": {"host": "127.0.0.1", "port": port}, "policy": policy}
    (tmp / ".dv-harness" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return tmp


def _start_dashboard(tmp: Path, adapter_factory=None) -> threading.Thread:
    from dv_harness import dashboard
    t = threading.Thread(target=dashboard.serve, args=(tmp,),
                          kwargs={"adapter_factory": adapter_factory}, daemon=True)
    t.start()
    return t


def _wait_ready(base: str, timeout: float = 10) -> None:
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            _get(base, "/api/state")
            return
        except Exception as e:
            last_exc = e
            time.sleep(0.05)
    raise AssertionError(f"dashboard at {base} never became ready: {last_exc}")


def _get(base: str, path: str):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Item 1 (per-job LSF drill-down) needs a real 404 JSON body back
        # from a GET, unlike every pre-existing _get() caller (always 200)
        # -- mirrors _post()'s existing HTTPError handling below.
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def _post(base: str, path: str, body, content_type: str = "application/json"):
    data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base + path, data=data,
                                  headers={"Content-Type": content_type}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def _fake_adapter_factory(text: str = "fine"):
    def factory():
        from dv_harness.adapters.base import AgentResult

        class FakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        return FakeAdapter()
    return factory


# --- /api/setup + /api/state gating -----------------------------------------

def test_setup_persists_and_unlocks_state():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/state")
        assert status == 200
        assert data["configured"] is False
        assert data["db_path"] is None
        assert data["working_path"] is None

        status, data = _post(base, "/api/setup", {"db_path": "/linux/db/usb", "working_path": "/linux/work/usb"})
        assert status == 200
        assert data["saved"] is True
        assert data["configured"] is True

        status, data = _get(base, "/api/state")
        assert status == 200
        assert data["configured"] is True
        assert data["db_path"] == "/linux/db/usb"
        assert data["working_path"] == "/linux/work/usb"
        assert data["configured_at"]

        on_disk = json.loads((tmp / ".dv-harness" / "project_meta.json").read_text(encoding="utf-8"))
        assert on_disk["db_path"] == "/linux/db/usb"
        assert on_disk["working_path"] == "/linux/work/usb"
    finally:
        shutil.rmtree(tmp)


def test_setup_missing_field_returns_400():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/setup", {"db_path": "/only/db"})
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
        status, data = _get(base, "/api/state")
        assert data["configured"] is False
    finally:
        shutil.rmtree(tmp)


# --- /api/start --------------------------------------------------------------

def test_start_refused_before_setup():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/start", {"goal": "verify usb", "loop": False})
        assert status == 400
        assert data["error"] == "NOT_CONFIGURED"
    finally:
        shutil.rmtree(tmp)


def test_start_single_stage_runs_in_background_via_injected_adapter():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp, adapter_factory=_fake_adapter_factory())
        _wait_ready(base)
        _post(base, "/api/setup", {"db_path": "/db", "working_path": "/work"})

        status, data = _post(base, "/api/start", {"goal": "verify usb", "loop": False})
        assert status == 200
        assert data["started"] is True

        state = None
        deadline = time.time() + 10
        while time.time() < deadline:
            _, state = _get(base, "/api/state")
            if not state.get("running"):
                break
            time.sleep(0.05)
        assert state is not None and state["running"] is False

        on_disk = json.loads((tmp / ".dv-harness" / "state.json").read_text(encoding="utf-8"))
        assert on_disk["stages"]["ENV_CHECK"]["status"] == "PASS"
        # run_stage(), not loop(): current_stage must NOT have auto-advanced.
        assert on_disk["current_stage"] == "ENV_CHECK"
    finally:
        shutil.rmtree(tmp)


def test_start_loop_true_advances_through_multiple_stages_in_background():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp, adapter_factory=_fake_adapter_factory())
        _wait_ready(base)
        _post(base, "/api/setup", {"db_path": "/db", "working_path": "/work"})

        status, data = _post(base, "/api/start", {"goal": "verify usb", "loop": True})
        assert status == 200
        assert data["started"] is True
        assert data["loop"] is True

        state = None
        deadline = time.time() + 20
        while time.time() < deadline:
            _, state = _get(base, "/api/state")
            if not state.get("running"):
                break
            time.sleep(0.1)
        assert state is not None and state["running"] is False
        # PROMOTION_READINESS is the first stage that hard-requires a human
        # APPROVE (engine.py) -- with none granted, loop() must have run
        # every stage up to there (proving multiple real run_stage() calls
        # happened, not just one) and then stopped cleanly at WAIT_USER.
        assert state["current_stage"] == "PROMOTION_READINESS"
        assert state["overall_status"] == "WAIT_USER"
    finally:
        shutil.rmtree(tmp)


def test_start_refuses_concurrent_run_with_409():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        entered = threading.Event()
        release = threading.Event()

        def factory():
            from dv_harness.adapters.base import AgentResult

            class SlowAdapter:
                def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                    entered.set()
                    release.wait(timeout=10)
                    return AgentResult(ok=True, text="fine", raw={}, session_id=None)

            return SlowAdapter()

        _start_dashboard(tmp, adapter_factory=factory)
        _wait_ready(base)
        _post(base, "/api/setup", {"db_path": "/db", "working_path": "/work"})

        status, data = _post(base, "/api/start", {"goal": "g1", "loop": False})
        assert status == 200
        assert entered.wait(timeout=5), "background run never started"

        status2, data2 = _post(base, "/api/start", {"goal": "g2", "loop": False})
        assert status2 == 409
        assert data2["error"] == "ALREADY_RUNNING"

        release.set()
        deadline = time.time() + 5
        state = {"running": True}
        while time.time() < deadline and state.get("running"):
            _, state = _get(base, "/api/state")
            time.sleep(0.05)
        assert state["running"] is False
    finally:
        shutil.rmtree(tmp)


# --- /api/control: same real effect as the CLI subcommands -----------------

def test_control_pause_resume_matches_control_json_and_events():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.control_plane import ControlPlane
        cp = ControlPlane(tmp)

        status, data = _post(base, "/api/control", {"command": "PAUSE", "reason": "debugging via dashboard"})
        assert status == 200
        assert cp.is_paused() is True
        assert cp.load()["paused_reason"] == "debugging via dashboard"

        status, data = _post(base, "/api/control", {"command": "RESUME"})
        assert status == 200
        assert cp.is_paused() is False

        events = [json.loads(l) for l in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()]
        cmds = [e.get("cmd") for e in events]
        assert "pause" in cmds and "resume" in cmds
    finally:
        shutil.rmtree(tmp)


def test_control_takeover_and_release_matches_cli_semantics():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.control_plane import ControlPlane
        cp = ControlPlane(tmp)

        status, data = _post(base, "/api/control", {"command": "TAKEOVER", "message": "manual review"})
        assert status == 200
        assert cp.is_takeover_active_for("ENV_CHECK") is True  # default current_stage

        status, data = _post(base, "/api/control", {"command": "RELEASE_TAKEOVER"})
        assert status == 200
        assert cp.takeover_status()["active"] is False
    finally:
        shutil.rmtree(tmp)


def test_control_redirect_refused_while_cross_stage_takeover_returns_409_with_real_message():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, _ = _post(base, "/api/control", {"command": "TAKEOVER", "message": "holding ENV_CHECK"})
        assert status == 200

        status, data = _post(base, "/api/control", {"command": "REDIRECT", "stage": "VPLAN",
                                                      "reason": "try to route around the takeover"})
        assert status == 409
        assert "TAKEOVER" in data.get("message", "")  # real human_redirect() RuntimeError text, not swallowed

        state = json.loads((tmp / ".dv-harness" / "state.json").read_text(encoding="utf-8"))
        assert state["current_stage"] == "ENV_CHECK"  # unchanged
    finally:
        shutil.rmtree(tmp)


def test_control_redirect_unknown_stage_returns_400():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/control", {"command": "REDIRECT", "stage": "NOT_A_REAL_STAGE"})
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
    finally:
        shutil.rmtree(tmp)


def test_control_approve_archives_prior_approval_same_as_control_plane_directly():
    # Requirement: the dashboard must call ControlPlane.approve() (with its
    # _archive_approval behavior), not bypass it through some other path.
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, _ = _post(base, "/api/control", {"command": "APPROVE", "stage": "SIGNOFF", "note": "first review",
                                                   "reviewer_id": "alice", "reviewer_confidence": "HIGH"})
        assert status == 200
        status, data = _post(base, "/api/control", {"command": "APPROVE", "stage": "SIGNOFF", "note": "second review",
                                                      "reviewer_id": "bob", "reviewer_confidence": "MEDIUM"})
        assert status == 200
        assert data["result"]["reviewer_id"] == "bob"

        from dv_harness.control_plane import ControlPlane
        cp = ControlPlane(tmp)
        assert cp.get_approval("SIGNOFF")["reviewer_id"] == "bob"
        history = cp.get_approval_history("SIGNOFF")
        assert len(history) == 1
        assert history[0]["reviewer_id"] == "alice"
        assert history[0]["outcome"] == "OVERWRITTEN_BY_NEW_APPROVAL"
    finally:
        shutil.rmtree(tmp)


def test_control_correct_writes_correction_resets_attempts_and_replans():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.storage import StateStore
        store = StateStore(tmp)
        state = store.load()
        state.stages["ENV_CHECK"]["attempts"] = 3
        store.save(state)

        status, data = _post(base, "/api/control", {"command": "CORRECT", "stage": "ENV_CHECK",
                                                      "note": "use the cached env report instead",
                                                      "reset_attempts": True})
        assert status == 200

        from dv_harness.control_plane import ControlPlane
        entry = ControlPlane(tmp).get_active_correction("ENV_CHECK")
        assert entry["note"] == "use the cached env report instead"

        reloaded = StateStore(tmp).load()
        assert reloaded.stages["ENV_CHECK"]["attempts"] == 0

        plan_files = list((tmp / ".dv-harness" / "plans").glob("PLAN-*.json"))
        assert plan_files
        plan = json.loads(plan_files[0].read_text(encoding="utf-8"))
        assert plan["node_id"] == "ENV_CHECK"
    finally:
        shutil.rmtree(tmp)


def test_control_correct_missing_note_returns_400():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/control", {"command": "CORRECT", "stage": "ENV_CHECK"})
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
    finally:
        shutil.rmtree(tmp)


def test_control_constraint_add_and_remove_round_trip():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/control", {"command": "CONSTRAINT_ADD", "text": "do not force push"})
        assert status == 200
        cid = data["result"]["id"]

        from dv_harness.control_plane import ControlPlane
        cp = ControlPlane(tmp)
        assert any(c["id"] == cid for c in cp.list_constraints())

        status, data = _post(base, "/api/control", {"command": "CONSTRAINT_REMOVE", "constraint_id": cid})
        assert status == 200
        assert data["result"]["removed"] is True
        assert not any(c["id"] == cid for c in cp.list_constraints())
    finally:
        shutil.rmtree(tmp)


def test_control_unknown_command_returns_400():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/control", {"command": "NOT_A_REAL_COMMAND"})
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
    finally:
        shutil.rmtree(tmp)


# --- Malformed requests: clean 4xx JSON, never a crash/reset ---------------

def test_malformed_json_body_returns_400_and_server_stays_alive():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/control", b"{this is not json", "application/json")
        assert status == 400
        assert data["error"] == "BAD_REQUEST"

        # server must still be serving requests afterward
        status, data = _get(base, "/api/state")
        assert status == 200
    finally:
        shutil.rmtree(tmp)


def test_wrong_content_type_returns_400():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/control", b'{"command":"RESUME"}', "text/plain")
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
    finally:
        shutil.rmtree(tmp)


def test_unknown_post_path_returns_404_json():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/does-not-exist", {})
        assert status == 404
        assert data["error"] == "NOT_FOUND"
    finally:
        shutil.rmtree(tmp)


# --- Item 1: per-job LSF drill-down (/api/lsf/jobs[/<job_id>]) -------------

def test_lsf_jobs_list_and_single_job_and_404():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        jobs_dir = tmp / ".dv-harness" / "lsf" / "jobs"
        jobs_dir.mkdir(parents=True)
        (jobs_dir / "j1.json").write_text(json.dumps({"job_id": "1", "lsf_status": "DONE",
                                                        "dv_analysis_status": "PASS"}), encoding="utf-8")
        (jobs_dir / "j2.json").write_text(json.dumps({"job_id": "2", "lsf_status": "RUN"}), encoding="utf-8")

        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/lsf/jobs")
        assert status == 200
        assert {j["job_id"] for j in data} == {"1", "2"}

        status, data = _get(base, "/api/lsf/jobs/1")
        assert status == 200
        assert data["dv_analysis_status"] == "PASS"

        status, data = _get(base, "/api/lsf/jobs/does-not-exist")
        assert status == 404
        assert data["error"] == "NOT_FOUND"

        # The full aggregate /api/lsf must be unaffected by adding drill-down.
        status, data = _get(base, "/api/lsf")
        assert status == 200
        assert data["total"] == 2
    finally:
        shutil.rmtree(tmp)


# --- Item 2: DV-review co-sign direct-submit action + policy toggle --------

def test_control_cosign_persists_to_control_json_and_events():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/control", {
            "command": "COSIGN", "stage": "SOC_SCENARIO_PLANNER",
            "field_path": "corner_risk_rank/cases[0].risk_factors", "value": ["reset", "cdc"],
            "reviewer_id": "alice", "reviewer_confidence": "HIGH",
        })
        assert status == 200
        assert data["result"]["value"] == ["reset", "cdc"]

        from dv_harness.control_plane import ControlPlane
        entry = ControlPlane(tmp).get_cosign("SOC_SCENARIO_PLANNER", "corner_risk_rank/cases[0].risk_factors")
        assert entry["reviewer_id"] == "alice"

        events = [json.loads(l) for l in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()]
        assert any(e.get("cmd") == "cosign" for e in events)

        status, data = _get(base, "/api/state")
        assert status == 200
        assert data["cosigns"]["SOC_SCENARIO_PLANNER"]["corner_risk_rank/cases[0].risk_factors"]["reviewer_id"] == "alice"
    finally:
        shutil.rmtree(tmp)


def test_control_cosign_missing_fields_return_400():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/control", {"command": "COSIGN", "field_path": "g/loc", "value": 1})
        assert status == 400 and data["error"] == "BAD_REQUEST"  # missing stage

        status, data = _post(base, "/api/control", {"command": "COSIGN", "stage": "SIGNOFF", "value": 1})
        assert status == 400 and data["error"] == "BAD_REQUEST"  # missing field_path

        status, data = _post(base, "/api/control", {"command": "COSIGN", "stage": "SIGNOFF", "field_path": "g/loc"})
        assert status == 400 and data["error"] == "BAD_REQUEST"  # missing value
    finally:
        shutil.rmtree(tmp)


def test_config_toggle_require_dv_review_cosign_reflected_in_state():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/state")
        assert data["dv_review_cosign_enforced"] is False

        status, data = _post(base, "/api/config", {"key": "require_dv_review_cosign", "value": True})
        assert status == 200
        assert data["saved"] is True
        assert data["policy"]["require_dv_review_cosign"] is True

        status, data = _get(base, "/api/state")
        assert data["dv_review_cosign_enforced"] is True

        from dv_harness.config import load_config
        assert load_config(tmp)["policy"]["require_dv_review_cosign"] is True

        # Toggle back off.
        status, data = _post(base, "/api/config", {"key": "require_dv_review_cosign", "value": False})
        assert status == 200
        status, data = _get(base, "/api/state")
        assert data["dv_review_cosign_enforced"] is False
    finally:
        shutil.rmtree(tmp)


def test_config_unknown_key_and_missing_value_return_400():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/config", {"key": "not_a_real_policy_key", "value": True})
        assert status == 400 and data["error"] == "BAD_REQUEST"

        status, data = _post(base, "/api/config", {"key": "require_dv_review_cosign"})
        assert status == 400 and data["error"] == "BAD_REQUEST"
    finally:
        shutil.rmtree(tmp)


# --- Item 3: audit-trail endpoint -------------------------------------------

def test_audit_endpoint_reports_events_and_control_state_with_limit():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _post(base, "/api/control", {"command": "CONSTRAINT_ADD", "text": "do not force push"})
        _post(base, "/api/control", {"command": "APPROVE", "stage": "SIGNOFF", "note": "ok",
                                      "reviewer_id": "alice", "reviewer_confidence": "HIGH"})

        status, data = _get(base, "/api/audit")
        assert status == 200
        assert data["limit"] == 50
        cmds = [e.get("cmd") for e in data["events"]]
        assert "constraint" in cmds and "approve" in cmds
        assert data["approvals"]["SIGNOFF"]["reviewer_id"] == "alice"

        status, data = _get(base, "/api/audit?limit=1")
        assert status == 200
        assert data["limit"] == 1
        assert len(data["events"]) == 1
        assert data["events"][0]["cmd"] == "approve"  # most recent
    finally:
        shutil.rmtree(tmp)


def test_audit_endpoint_empty_project_returns_empty_events():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/audit")
        assert status == 200
        assert data["events"] == []
    finally:
        shutil.rmtree(tmp)


# --- Item 4: ungated-CLI-only-verbs note is present in the GUI -------------

def test_dashboard_html_labels_ungated_cli_only_admin_verbs():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert "CLI-only" in html
        assert "mark" in html and "set-stage" in html and "advance" in html
        assert "not exposed as buttons" in html or "does not expose" in html
    finally:
        shutil.rmtree(tmp)


# --- GET /api/self-audit (dv_harness/self_audit.py) -------------------------
# Real HTTP requests against a real dashboard.serve() thread, same as every
# other test in this file. self_audit.run_self_audit() itself (including its
# results against THIS repo's real current state) is exercised directly, not
# through HTTP, in dv_harness_tests/test_engine_gates_and_routing.py -- these
# tests instead confirm the HTTP layer (GET routing, query-string handling,
# JSON response shape) is genuinely wired to that same shared implementation.

def test_self_audit_endpoint_returns_all_23_and_flags_missing_tools():
    # The tmp project has no tools/verification_flow/ at all -- every one of
    # the 23 gates must report GATE_TOOL_MISSING via real HTTP, not crash or
    # silently report something else.
    from dv_harness.self_audit import ALL_GATE_IDS as _ALL_IDS
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/self-audit")
        assert status == 200
        assert data["summary"]["total"] == len(_ALL_IDS)
        assert data["summary"]["tool_missing"] == len(_ALL_IDS)
        assert data["unknown_gate_ids"] == []
        assert all(g["status"] == "GATE_TOOL_MISSING" for g in data["gates"])
        from dv_harness.self_audit import ALL_GATE_IDS
        assert {g["gate_id"] for g in data["gates"]} == set(ALL_GATE_IDS)
    finally:
        shutil.rmtree(tmp)


def test_self_audit_endpoint_repeated_gate_query_param_and_unknown_id():
    # parse_qs (not the plain dict-split every other GET handler in this
    # module uses) so a repeated ?gate=x&gate=y actually selects both.
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/self-audit?gate=schema_reference_integrity_gate"
                                   "&gate=agent_skill_binding_gate&gate=not_a_real_gate")
        assert status == 200
        assert data["summary"]["total"] == 2
        assert {g["gate_id"] for g in data["gates"]} == {
            "schema_reference_integrity_gate", "agent_skill_binding_gate"}
        assert data["unknown_gate_ids"] == ["not_a_real_gate"]
    finally:
        shutil.rmtree(tmp)


def test_self_audit_endpoint_runs_real_gate_scripts_against_real_state():
    # Copies a small, real slice of THIS repo's own tools/verification_flow/
    # (not the whole repo -- keeps the fixture cheap) into the tmp project so
    # the HTTP round trip exercises an actual gate subprocess, actual PASS
    # and actual NO_SOURCE_DATA/GATE_TOOL_MISSING outcomes, not just plumbing.
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        flow_dir = tmp / "tools" / "verification_flow"
        flow_dir.mkdir(parents=True, exist_ok=True)
        for name in ("schema_reference_integrity_gate.py", "command_catalog_lifecycle_gate.py"):
            shutil.copy(ROOT / "tools" / "verification_flow" / name, flow_dir / name)
        (tmp / ".dv-harness" / "workflow").mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / ".dv-harness" / "workflow" / "verification_flow_v13.json",
                    tmp / ".dv-harness" / "workflow" / "verification_flow_v13.json")
        shutil.copy(ROOT / "WORKFLOW_MANIFEST.json", tmp / "WORKFLOW_MANIFEST.json")

        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        # ROOT_SCAN gate present with its real inputs -> genuine PASS.
        status, data = _get(base, "/api/self-audit?gate=schema_reference_integrity_gate")
        assert status == 200
        g = data["gates"][0]
        assert g["status"] == "PASS", g
        assert g["mode"] == "ROOT_SCAN"
        assert g["detail"]["schemas"] == 0  # no *.schema.json copied into the fixture

        # JSON_GATES gate present but with no real state-file source ->
        # honest NO_SOURCE_DATA by default.
        status, data = _get(base, "/api/self-audit?gate=command_catalog_lifecycle_gate")
        assert data["gates"][0]["status"] == "NO_SOURCE_DATA"

        # Same gate with smoke=1 -> the script actually runs against a
        # constructed representative payload and PASSes.
        status, data = _get(base, "/api/self-audit?gate=command_catalog_lifecycle_gate&smoke=1")
        assert status == 200
        g = data["gates"][0]
        assert g["status"] == "SCRIPT_SMOKE_PASS", g
        assert g["mode"] == "SMOKE"

        # A gate whose script was NOT copied into this fixture still reports
        # GATE_TOOL_MISSING, not a crash.
        status, data = _get(base, "/api/self-audit?gate=hard_gate_registry_audit")
        assert data["gates"][0]["status"] == "GATE_TOOL_MISSING"
    finally:
        shutil.rmtree(tmp)


def test_knowledge_status_endpoint_reports_disabled_by_default():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/knowledge/status")
        assert status == 200
        assert data["config"]["enabled"] is False
        assert data["config"]["remote_root"] == ""
        assert "ping" not in data  # never pings when not configured
    finally:
        shutil.rmtree(tmp)


def test_knowledge_status_endpoint_pings_when_enabled():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        from dv_harness.config import load_config, save_config
        cfg = load_config(tmp)
        cfg["knowledge_center"]["enabled"] = True
        cfg["knowledge_center"]["remote_root"] = "/srv/kc"
        cfg["knowledge_center"]["hop_script"] = "/nonexistent/remote_hop.py"
        save_config(tmp, cfg)

        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/knowledge/status")
        assert status == 200
        assert data["config"]["enabled"] is True
        assert "ping" in data
        assert data["ping"]["ok"] is False  # no real server reachable in this test
        assert data["ping"]["error"] == "REMOTE_HOP_NOT_FOUND"
    finally:
        shutil.rmtree(tmp)


def test_state_endpoint_includes_failure_attribution_verdict():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        state = {"stages": {"FAILURE_RECOVERY": {"last_message": (
            "```dv-harness-evidence:failure_attribution\n"
            '{"boundary_trace": [{"stage": "DUT_INTERNAL", "expected": "1", "observed": "0"}]}\n'
            "```\n"
        )}}}
        (tmp / ".dv-harness" / "state.json").write_text(json.dumps(state), encoding="utf-8")

        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/state")
        assert status == 200
        assert data["failure_attribution"]["verdict"] == "DUT_BUG"
    finally:
        shutil.rmtree(tmp)


def test_state_endpoint_failure_attribution_none_before_stage_runs():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/state")
        assert status == 200
        assert data["failure_attribution"] is None
    finally:
        shutil.rmtree(tmp)


# --- Task 3: real interactivity for protocol/env-mode/iron-rules tiles -----
# Mirrors test_state_endpoint_includes_failure_attribution_verdict/
# test_state_endpoint_failure_attribution_none_before_stage_runs above exactly
# -- environment_mode_selected() is the same scan-stage-evidence-block shape
# as _failure_attribution()/_execution_mode(), just under a different gate id
# (environment_mode_selection) and field name (environment_mode).

def test_environment_mode_reflects_current_run_when_declared():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        state = {"stages": {"DISCOVERY": {"last_message": (
            "```dv-harness-evidence:environment_mode_selection\n"
            '{"environment_mode": "SYSTEM_LEVEL_MODE"}\n'
            "```\n"
        )}}}
        (tmp / ".dv-harness" / "state.json").write_text(json.dumps(state), encoding="utf-8")

        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/state")
        assert status == 200
        assert data["environment_mode_selected"] == "SYSTEM_LEVEL_MODE"
    finally:
        shutil.rmtree(tmp)


def test_environment_mode_selected_none_before_declared():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/state")
        assert status == 200
        assert data["environment_mode_selected"] is None
    finally:
        shutil.rmtree(tmp)


def test_protocol_tiles_are_clickable_elements():
    # The rendered protocoltiles JS must attach a real click handler that
    # wires each tile to the exact field POST /api/start already reads for
    # scope (`goal`, submitted from #goalInput by doStart() -- see val('goalInput')
    # a few lines above in dashboard.py) -- not a static, inert <div>.
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")

        assert 'onclick="selectProtocol(' in html
        import re
        m = re.search(r"function selectProtocol\([^)]*\)\s*\{([^}]*)\}", html, re.S)
        assert m, "selectProtocol() click handler function not found in served HTML"
        body = m.group(1)
        assert "goalInput" in body and ".value" in body
    finally:
        shutil.rmtree(tmp)


def test_iron_rules_tile_uses_tier_driven_css_class():
    # ironrulestiles must render CSS classes derived from real qualification
    # tier data (qualification_tier_reached, from the live
    # protocol_capability_registry.json), with real corresponding CSS rules
    # in the page's <style> block -- not a flat unstyled tile.
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")

        assert "tier-reached" in html
        assert "tier-unreached" in html
        style_block = html.split("<style>")[1].split("</style>")[0]
        assert ".tier-reached" in style_block
        assert ".tier-unreached" in style_block
    finally:
        shutil.rmtree(tmp)


# --- POST /api/signoff-export (dv_harness/signoff_export.py) ---------------
# Real HTTP requests against a real dashboard.serve() thread, same as every
# other test in this file. collect_signoff_bundle() itself is exercised
# directly (not through HTTP) in dv_harness_tests/test_signoff_export.py --
# these tests confirm the HTTP layer (routing, default out_dir, custom
# out_dir, JSON response shape) is genuinely wired to that same
# implementation, called in-process (no subprocess), matching
# _handle_session_save's direct-call-to-session_snapshot.save_session()
# pattern.

def test_signoff_export_with_real_artifacts_present_bundles_them():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        # A real blackboard topic file and a real vplan directory -- the
        # bundle must actually copy these, not fabricate a placeholder.
        bb_dir = tmp / ".dv-harness" / "blackboard"
        bb_dir.mkdir(parents=True, exist_ok=True)
        (bb_dir / "findings.json").write_text(json.dumps({"open": []}), encoding="utf-8")
        vplan_dir = tmp / ".dv-harness" / "vplan"
        vplan_dir.mkdir(parents=True, exist_ok=True)
        (vplan_dir / "vplan.md").write_text("# vPlan\n", encoding="utf-8")

        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        out_dir = tmp / "custom_export_dir"
        status, data = _post(base, "/api/signoff-export", {"out_dir": str(out_dir)})
        assert status == 200
        assert data["status"] == "OK"
        assert data["out_dir"] == str(out_dir.resolve())
        assert data["missing_count"] >= 1  # e.g. pattern_registry never existed in this fixture

        present = {m["artifact"] for m in data["manifest"] if m["present"]}
        assert "blackboard/findings.json" in present
        assert "vplan" in present
        assert "self_audit_result" in present  # always freshly generated

        # Real files actually landed on disk under out_dir, matching the
        # manifest's bundled_path entries -- not just a JSON claim.
        assert (out_dir / "blackboard" / "findings.json").exists()
        assert (out_dir / "vplan" / "vplan.md").exists()
        assert (out_dir / "self_audit_result.json").exists()
        assert (out_dir / "manifest.json").exists()
    finally:
        shutil.rmtree(tmp)


def test_signoff_export_with_no_artifacts_reports_all_absent_honestly():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        out_dir = tmp / "empty_export"
        status, data = _post(base, "/api/signoff-export", {"out_dir": str(out_dir)})
        assert status == 200
        assert data["status"] == "OK"

        by_artifact = {m["artifact"]: m for m in data["manifest"]}
        # Nothing was ever created in this fresh project -- every copyable
        # candidate must honestly report absent, never a fabricated
        # placeholder (CLAUDE.md Evidence Truth Rule).
        assert by_artifact["blackboard/findings.json"]["present"] is False
        assert by_artifact["blackboard/findings.json"]["bundled_path"] is None
        assert by_artifact["vplan"]["present"] is False
        assert by_artifact["pattern_registry"]["present"] is False
        # self_audit_result is always generated fresh, even with nothing else present.
        assert by_artifact["self_audit_result"]["present"] is True
        assert data["bundled_count"] == 1
        assert (out_dir / "self_audit_result.json").exists()
        assert not (out_dir / "vplan").exists()
    finally:
        shutil.rmtree(tmp)


def test_signoff_export_default_out_dir_when_omitted():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/signoff-export", {})
        assert status == 200
        assert data["status"] == "OK"
        # Default lands under .dv-harness/signoff-export/<timestamp>/, never
        # outside the project root, and real files exist there.
        out_dir = Path(data["out_dir"])
        assert (tmp / ".dv-harness" / "signoff-export").resolve() in out_dir.parents
        assert (out_dir / "manifest.json").exists()
    finally:
        shutil.rmtree(tmp)


# --- /api/coverage -------------------------------------------------------------
# Wires coverage_analysis.py's real parse_coverage_summary()/identify_holes()/
# compute_coverage_trend()/render_coverage_trend_svg() up to a real
# .dv-harness/coverage/summary.json + history.json on disk (that module had
# zero callers in dv_harness/ before this -- only the standalone
# tools/analyze_coverage.py CLI used it).

def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_coverage_reports_honest_absent_state_when_no_summary_exists():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/coverage")
        assert status == 200
        assert data["available"] is False
        # honest absent state names the path it looked for -- never a
        # fabricated percent/holes/trend.
        assert data["summary_path"].endswith(str(Path(".dv-harness") / "coverage" / "summary.json"))
    finally:
        shutil.rmtree(tmp)


def test_coverage_reports_categories_and_holes_sorted_worst_first():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_json(tmp / ".dv-harness" / "coverage" / "summary.json", {
            "categories": [
                {"name": "line", "percent": 100.0, "bins_total": 500, "bins_hit": 500},
                {"name": "branch", "percent": 87.5, "bins_total": 200, "bins_hit": 175},
                {"name": "fsm_state", "percent": 60.0, "bins_total": 10, "bins_hit": 6},
            ]
        })

        status, data = _get(base, "/api/coverage")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        assert len(data["categories"]) == 3
        # worst-first: fsm_state (60%) before branch (87.5%); line (100%) is not a hole
        assert [h["name"] for h in data["holes"]] == ["fsm_state", "branch"]
        assert data["holes"][0]["bins_missing"] == 4
        # no history.json yet -> no trend, no chart
        assert data["history"] is None
        assert data["trend"] is None
        assert data["trend_svg"] is None
    finally:
        shutil.rmtree(tmp)


def test_coverage_reports_malformed_summary_as_honest_error_not_500():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_json(tmp / ".dv-harness" / "coverage" / "summary.json", {"categories": []})

        status, data = _get(base, "/api/coverage")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_CATEGORY"
        assert data["categories"] is None
    finally:
        shutil.rmtree(tmp)


def test_coverage_reports_trend_and_structural_svg_when_history_has_two_plus_samples():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_json(tmp / ".dv-harness" / "coverage" / "summary.json", {
            "categories": [{"name": "line", "percent": 90.0, "bins_total": 100, "bins_hit": 90}]
        })
        # Synthetic example history feeding this round's chart -- see the
        # separate real-append-path test below for the production write path.
        history = [
            {"timestamp": 1, "percent": 70.0},
            {"timestamp": 2, "percent": 82.5},
            {"timestamp": 3, "percent": 90.0},
        ]
        _write_json(tmp / ".dv-harness" / "coverage" / "history.json", history)

        status, data = _get(base, "/api/coverage")
        assert status == 200
        assert data["trend"]["trend"] == "IMPROVING"
        assert data["trend"]["first_percent"] == 70.0
        assert data["trend"]["last_percent"] == 90.0
        # structural SVG check -- one <circle> per history sample, one <polyline>
        svg = data["trend_svg"]
        assert svg.count("<circle") == len(history)
        assert svg.count("<polyline") == 1
        assert "<svg" in svg
    finally:
        shutil.rmtree(tmp)


def test_coverage_history_with_single_sample_omits_trend_without_erroring():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_json(tmp / ".dv-harness" / "coverage" / "summary.json", {
            "categories": [{"name": "line", "percent": 90.0, "bins_total": 100, "bins_hit": 90}]
        })
        _write_json(tmp / ".dv-harness" / "coverage" / "history.json", [{"timestamp": 1, "percent": 70.0}])

        status, data = _get(base, "/api/coverage")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        assert data["history"] == [{"timestamp": 1, "percent": 70.0}]
        assert data["trend"] is None
        assert data["trend_svg"] is None
    finally:
        shutil.rmtree(tmp)


def test_coverage_accepts_path_overrides_via_query_params():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        alt_summary = tmp / "alt" / "my_summary.json"
        _write_json(alt_summary, {
            "categories": [{"name": "line", "percent": 55.0, "bins_total": 20, "bins_hit": 11}]
        })

        import urllib.parse
        status, data = _get(base, "/api/coverage?summary=" + urllib.parse.quote(str(alt_summary)))
        assert status == 200
        assert data["available"] is True
        assert data["categories"][0]["name"] == "line"
        assert data["summary_path"] == str(alt_summary)
    finally:
        shutil.rmtree(tmp)


# --- POST /api/waiver (dv_harness/waiver_store.py) -------------------------
# Real HTTP requests against a real dashboard.serve() thread, same as every
# other test in this file. waiver_store.append_waiver()/read_waivers()
# themselves are exercised directly (not through HTTP) in
# dv_harness_tests/test_waiver_store.py -- these tests confirm the HTTP layer
# (routing, body-parsing, error-response convention) is genuinely wired to
# that same implementation, called in-process (no subprocess), matching
# _handle_signoff_export's direct-call-to-signoff_export pattern.

def test_waiver_submit_valid_body_persists_and_reads_back():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/waiver", {
            "gate_id": "coverage_hole_regeneration_gate",
            "item_id": "cov-hole-42",
            "approved": True,
            "evidence": "manually reviewed against spec section 4.2",
        })
        assert status == 200
        assert data["status"] == "OK"
        assert data["waiver"]["gate_id"] == "coverage_hole_regeneration_gate"
        assert "recorded_at" in data["waiver"]

        from dv_harness.waiver_store import read_waivers
        waivers = read_waivers(tmp)
        assert len(waivers) == 1
        assert waivers[0]["item_id"] == "cov-hole-42"
    finally:
        shutil.rmtree(tmp)


def test_waiver_submit_missing_evidence_returns_400_and_does_not_persist():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/waiver", {
            "gate_id": "sequence_coverage_closure_gate",
            "item_id": "seq-1",
            "approved": True,
            # evidence deliberately omitted
        })
        assert status == 400
        assert data["error"] == "BAD_REQUEST"

        from dv_harness.waiver_store import read_waivers
        assert read_waivers(tmp) == []
    finally:
        shutil.rmtree(tmp)


def test_waiver_form_present_in_dashboard_html():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'doWaiverSubmit()' in html
        assert "waiverGateId" in html and "waiverItemId" in html and "waiverEvidence" in html
        assert "coverage_hole_regeneration_gate" in html
    finally:
        shutil.rmtree(tmp)


def test_append_coverage_history_sample_is_the_real_production_write_path():
    """The real code path a future coverage-producing step calls (not just a
    synthetic file dropped in by a test) -- proves append_coverage_history_sample()
    writes to the exact file GET /api/coverage reads, and that after two real
    appends the endpoint's trend/chart come alive from that real growth."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.dashboard import append_coverage_history_sample

        _write_json(tmp / ".dv-harness" / "coverage" / "summary.json", {
            "categories": [{"name": "line", "percent": 95.0, "bins_total": 100, "bins_hit": 95}]
        })

        status, data = _get(base, "/api/coverage")
        assert data["trend"] is None  # no history.json written yet at all

        append_coverage_history_sample(tmp, 80.0, timestamp=1)
        append_coverage_history_sample(tmp, 95.0, timestamp=2)

        history_path = tmp / ".dv-harness" / "coverage" / "history.json"
        assert history_path.exists()
        on_disk = json.loads(history_path.read_text(encoding="utf-8"))
        assert on_disk == [{"timestamp": 1, "percent": 80.0}, {"timestamp": 2, "percent": 95.0}]

        status, data = _get(base, "/api/coverage")
        assert status == 200
        assert data["trend"]["trend"] == "IMPROVING"
        assert data["trend_svg"].count("<circle") == 2
    finally:
        shutil.rmtree(tmp)
