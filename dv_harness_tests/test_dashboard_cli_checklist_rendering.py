"""Coverage for the 2026-09-01 runtime-progress-visibility pass.

Context: 'stage-scoped-completion-percent' and 'expected-evidence-checklist-
and-stage-hooks' (the two immediately preceding passes) added REAL numeric/
checklist data -- stage_completion_percent/gates_passed/gates_total (via
gates.evaluate_stage_evidence_with_completion(), threaded through
control_plane.describe_stage()) and entry_checklist/exit_checklist (computed
by engine.build_stage_entry_checklist()/build_stage_exit_checklist(),
persisted into .dv-harness/telemetry/stages/STAGE-*.json by
StageExecutionProfiler) -- but neither was actually rendered anywhere a
human would see it: describe_stage() itself did not even carry
entry_checklist/exit_checklist (only readable by opening the raw telemetry
JSON file by hand), dashboard.py's "Why (current stage)" card only ever
dumped describe_stage()'s dict as an opaque JSON blob, and cli.py's
explain/evidence printed the same raw JSON with no human-readable rendering.

This file proves, in order:
  1. control_plane.describe_stage() now surfaces entry_checklist/
     exit_checklist, sourced from the most recent real telemetry record for
     that stage (None when the stage has no telemetry record at all, as
     opposed to a real zero-item checklist).
  2. cli.render_stage_checklist_report() renders stage_completion_percent/
     gates_passed/gates_total plus a checkmark/x-mark per checklist item and
     an explicit "still needs to be supplied" line naming the exact missing
     item_id(s).
  3. `dv-harness explain --stage` appends that same human-readable rendering
     after its pre-existing JSON block (additive; the JSON block itself is
     untouched).
  4. `dv-harness evidence --stage` is left emitting ONLY the describe_stage()
     JSON (backward-compatible: still parses whole via json.loads(), per the
     pre-existing test_cli_evidence_stage_prints_completion_fields
     contract) -- but that JSON now also carries entry_checklist/
     exit_checklist for a machine reader.
  5. The new `dv-harness checklist --stage` subcommand is the dedicated
     human-readable entry point for the same data `evidence` carries as raw
     JSON.
  6. dashboard.py's served page (source-level check, same pattern
     test_active_stages_read_sites.py's
     test_dashboard_graph_highlight_js_uses_active_stages_not_just_current_stage
     already uses -- JS execution isn't available in this test process)
     computes the new checklist/percent rendering from
     stage_completion_percent/entry_checklist/exit_checklist, not just the
     pre-existing WHY fields.
  7. End-to-end over real HTTP: GET /api/state's current_stage_detail
     actually carries entry_checklist/exit_checklist read back from a real
     telemetry fixture file on disk (same fixture pattern
     test_active_stages_read_sites.py's
     test_dashboard_state_endpoint_includes_active_stages_detail_during_fanout
     uses for state.json).
"""
from __future__ import annotations

import json
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fresh_project() -> Path:
    return Path(tempfile.mkdtemp())


def _write_telemetry_record(root: Path, stage_id: str, entry_checklist, exit_checklist,
                             profile_id: str = "STAGE-TESTFIX1") -> Path:
    """Writes a real .dv-harness/telemetry/stages/STAGE-*.json record by
    hand, in exactly the shape StageExecutionProfiler.begin_stage()/
    end_stage() itself produces (see stage_profile.py) -- a fixture, not a
    call through the profiler, so these tests stay independent of whether a
    real run_stage() attempt happened."""
    stage_dir = root / ".dv-harness" / "telemetry" / "stages"
    stage_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "profile_id": profile_id, "stage_id": stage_id, "stage_name": stage_id,
        "graph_node": stage_id, "start_time_epoch": time.time(), "end_time_epoch": time.time(),
        "stage_wall_clock_sec": 1.0, "aggregate_agent_runtime_sec": 1.0,
        "parallel_saving_sec": 0.0, "parallelism_efficiency": 0.0,
        "input_tokens": None, "output_tokens": None, "cache_read_tokens": None,
        "cache_write_tokens": None, "total_tokens": None,
        "tool_calls": 0, "retries": 0, "finding_count": 0, "closed_finding_count": 0,
        "status": "PASS", "agents": [], "metadata": {},
        "entry_checklist": entry_checklist, "exit_checklist": exit_checklist,
    }
    path = stage_dir / f"{profile_id}.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    return path


_ENTRY_CHECKLIST = {
    "items": [
        {"item_id": "environment", "description": "ENV_CHECK readiness topic", "present": True},
        {"item_id": "required_artifacts.protocol_spec", "description": "protocol spec on disk", "present": False},
    ],
    "present_count": 1, "total_count": 2, "completeness_percent": 50.0,
    "missing_item_ids": ["required_artifacts.protocol_spec"],
}
_EXIT_CHECKLIST = {
    "items": [
        {"item_id": "intake_readiness.mode", "description": "mode field", "present": True},
    ],
    "present_count": 1, "total_count": 1, "completeness_percent": 100.0,
    "missing_item_ids": [],
}


# --- item 1: control_plane.describe_stage() surfaces entry_checklist/exit_checklist ---

def test_describe_stage_surfaces_latest_telemetry_checklists():
    from dv_harness.control_plane import describe_stage
    from dv_harness.models import HarnessState

    tmp = _fresh_project()
    try:
        _write_telemetry_record(tmp, "INTAKE", _ENTRY_CHECKLIST, _EXIT_CHECKLIST)
        state = HarnessState()
        state.stages["INTAKE"] = {"status": "PASS", "attempts": 1, "last_message": ""}
        out = describe_stage(tmp, state, "INTAKE")
        assert out["entry_checklist"] == _ENTRY_CHECKLIST
        assert out["exit_checklist"] == _EXIT_CHECKLIST
        # Pre-existing fields untouched.
        assert out["stage"] == "INTAKE"
        assert "stage_completion_percent" in out
    finally:
        shutil.rmtree(tmp)


def test_describe_stage_never_run_stage_reports_none_not_a_fabricated_checklist():
    from dv_harness.control_plane import describe_stage
    from dv_harness.models import HarnessState

    tmp = _fresh_project()
    try:
        state = HarnessState()
        state.stages["INTAKE"] = {"status": "NOT_STARTED", "attempts": 0, "last_message": ""}
        out = describe_stage(tmp, state, "INTAKE")
        assert out["entry_checklist"] is None
        assert out["exit_checklist"] is None
    finally:
        shutil.rmtree(tmp)


def test_describe_stage_picks_the_most_recent_of_multiple_telemetry_attempts():
    """A retried stage has more than one STAGE-*.json record; describe_stage()
    must reflect the LATEST attempt's checklist, not an earlier/stale one."""
    from dv_harness.control_plane import describe_stage
    from dv_harness.models import HarnessState

    tmp = _fresh_project()
    try:
        stale = {"items": [{"item_id": "x", "description": "", "present": False}],
                  "present_count": 0, "total_count": 1, "completeness_percent": 0.0,
                  "missing_item_ids": ["x"]}
        fresh = {"items": [{"item_id": "x", "description": "", "present": True}],
                  "present_count": 1, "total_count": 1, "completeness_percent": 100.0,
                  "missing_item_ids": []}
        p1 = _write_telemetry_record(tmp, "INTAKE", stale, stale, profile_id="STAGE-ATTEMPT1")
        # Force a distinct, strictly later start_time_epoch than the first record.
        rec1 = json.loads(p1.read_text(encoding="utf-8"))
        rec2 = dict(rec1)
        rec2["profile_id"] = "STAGE-ATTEMPT2"
        rec2["start_time_epoch"] = rec1["start_time_epoch"] + 100
        rec2["entry_checklist"] = fresh
        rec2["exit_checklist"] = fresh
        (tmp / ".dv-harness" / "telemetry" / "stages" / "STAGE-ATTEMPT2.json").write_text(
            json.dumps(rec2), encoding="utf-8")

        state = HarnessState()
        state.stages["INTAKE"] = {"status": "PASS", "attempts": 2, "last_message": ""}
        out = describe_stage(tmp, state, "INTAKE")
        assert out["entry_checklist"] == fresh
        assert out["exit_checklist"] == fresh
    finally:
        shutil.rmtree(tmp)


# --- item 2: cli.render_stage_checklist_report() pure rendering -------------

def test_render_stage_checklist_report_shows_checkmarks_and_missing_note():
    from dv_harness.cli import render_stage_checklist_report

    detail = {
        "stage": "INTAKE", "stage_completion_percent": 33, "gates_passed": 1, "gates_total": 3,
        "stage_completion_note": None,
        "entry_checklist": _ENTRY_CHECKLIST, "exit_checklist": _EXIT_CHECKLIST,
    }
    out = render_stage_checklist_report(detail)
    assert "INTAKE" in out
    assert "33%" in out and "1/3 gates passed" in out
    # present item -> checkmark, missing item -> x-mark, both real item ids present verbatim.
    assert "[x] environment" in out
    assert "[ ] required_artifacts.protocol_spec" in out
    assert "STILL NEEDS TO BE SUPPLIED" in out
    assert "required_artifacts.protocol_spec" in out.split("STILL NEEDS TO BE SUPPLIED")[1]
    # Exit checklist, fully satisfied -> no "still needs to be supplied" line for it.
    assert out.count("STILL NEEDS TO BE SUPPLIED") == 1


def test_render_stage_checklist_report_handles_no_telemetry_and_zero_items():
    from dv_harness.cli import render_stage_checklist_report

    detail = {
        "stage": "DISCOVERY", "stage_completion_percent": 100, "gates_passed": 0, "gates_total": 0,
        "stage_completion_note": "stage has no registered gates; treated as fully complete",
        "entry_checklist": None,
        "exit_checklist": {"items": [], "present_count": 0, "total_count": 0,
                            "completeness_percent": 100.0, "missing_item_ids": []},
    }
    out = render_stage_checklist_report(detail)
    assert "not run" in out.lower() or "no telemetry" in out.lower()
    assert "no items declared" in out.lower()
    assert "STILL NEEDS TO BE SUPPLIED" not in out


# --- items 3-5: real CLI dispatch --------------------------------------------

def _run_cli(monkeypatch, capsys, argv):
    from dv_harness import cli
    monkeypatch.setattr(sys, "argv", ["dv-harness"] + argv)
    cli.main()
    return capsys.readouterr().out


def test_cli_explain_stage_appends_human_readable_checklist_after_json(monkeypatch, capsys):
    tmp = _fresh_project()
    try:
        _write_telemetry_record(tmp, "INTAKE", _ENTRY_CHECKLIST, _EXIT_CHECKLIST)
        out = _run_cli(monkeypatch, capsys, ["--project-root", str(tmp), "explain", "--stage", "INTAKE"])
        assert "--- Stage completion checklist (human-readable) ---" in out
        assert "[x] environment" in out
        assert "[ ] required_artifacts.protocol_spec" in out
        assert "STILL NEEDS TO BE SUPPLIED" in out
        # The pre-existing raw JSON block is still there, unmodified in shape.
        assert '"entry_checklist"' in out
    finally:
        shutil.rmtree(tmp)


def test_cli_evidence_stage_stays_pure_json_but_now_carries_checklists(monkeypatch, capsys):
    """Backward-compat guard for the pre-existing
    test_cli_evidence_stage_prints_completion_fields contract (a bare
    json.loads() over evidence's ENTIRE stdout) -- appending human-readable
    text to `evidence` would break that; this proves it still parses whole
    while the checklist data rides along inside the JSON."""
    tmp = _fresh_project()
    try:
        _write_telemetry_record(tmp, "INTAKE", _ENTRY_CHECKLIST, _EXIT_CHECKLIST)
        out = _run_cli(monkeypatch, capsys, ["--project-root", str(tmp), "evidence", "--stage", "INTAKE"])
        data = json.loads(out)  # must be the WHOLE stdout, not a substring
        assert data["stage"] == "INTAKE"
        assert data["entry_checklist"] == _ENTRY_CHECKLIST
        assert data["exit_checklist"] == _EXIT_CHECKLIST
    finally:
        shutil.rmtree(tmp)


def test_cli_checklist_subcommand_prints_human_readable_rendering(monkeypatch, capsys):
    tmp = _fresh_project()
    try:
        _write_telemetry_record(tmp, "INTAKE", _ENTRY_CHECKLIST, _EXIT_CHECKLIST)
        out = _run_cli(monkeypatch, capsys, ["--project-root", str(tmp), "checklist", "--stage", "INTAKE"])
        assert "Stage: INTAKE" in out
        assert "[x] environment" in out
        assert "[ ] required_artifacts.protocol_spec" in out
        assert "STILL NEEDS TO BE SUPPLIED: required_artifacts.protocol_spec" in out
        # Never raw JSON here -- this subcommand's whole point is a
        # human-readable rendering instead of a dict dump.
        assert not out.strip().startswith("{")
    finally:
        shutil.rmtree(tmp)


def test_cli_checklist_subcommand_real_subprocess_invocation():
    """One real, out-of-process invocation (matching test_cli_lsf_watch.py's/
    test_stage_scoped_completion_percent.py's own real-subprocess and
    in-process conventions) proving the new subparser is actually wired into
    argparse, not just reachable via a monkeypatched sys.argv."""
    import subprocess
    tmp = _fresh_project()
    try:
        _write_telemetry_record(tmp, "INTAKE", _ENTRY_CHECKLIST, _EXIT_CHECKLIST)
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), "checklist", "--stage", "INTAKE"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr
        assert "STILL NEEDS TO BE SUPPLIED" in r.stdout
    finally:
        shutil.rmtree(tmp)


# --- item 6: dashboard JS source-level check (same pattern as
#             test_dashboard_graph_highlight_js_uses_active_stages_not_just_current_stage) ---

def test_dashboard_js_renders_stage_completion_percent_and_checklists():
    from dv_harness import dashboard
    html = dashboard.HTML
    # The old plain textContent dump of describe_stage() is gone in favor of
    # a real rendering function.
    assert "getElementById('stageWhy').textContent" not in html
    assert "getElementById('stageWhy').innerHTML" in html
    assert "stage_completion_percent" in html
    assert "entry_checklist" in html and "exit_checklist" in html
    assert "missing_item_ids" in html
    # Missing items must prompt the user for the specific item still needed.
    assert "still needs to be supplied" in html.lower()
    # Present/missing render via the same checkmark/x-mark icon() helper the
    # Graph card already uses, not a bespoke second mechanism.
    assert "icon('PASS')" in html and "icon('FAIL')" in html


# --- item 7: end-to-end over real HTTP --------------------------------------

def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_dashboard(tmp: Path) -> threading.Thread:
    from dv_harness import dashboard
    t = threading.Thread(target=dashboard.serve, args=(tmp,), daemon=True)
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
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def test_dashboard_state_endpoint_current_stage_detail_carries_checklists():
    port = _free_port()
    tmp = _fresh_project()
    try:
        (tmp / ".dv-harness").mkdir(parents=True, exist_ok=True)
        cfg = {"dashboard": {"host": "127.0.0.1", "port": port},
               "policy": {"require_stage_gate_evidence": False, "max_stage_retries": 0}}
        (tmp / ".dv-harness" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        state = {"current_stage": "INTAKE"}
        (tmp / ".dv-harness" / "state.json").write_text(json.dumps(state), encoding="utf-8")
        _write_telemetry_record(tmp, "INTAKE", _ENTRY_CHECKLIST, _EXIT_CHECKLIST)

        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/state")
        assert status == 200
        detail = data["current_stage_detail"]
        assert detail["stage"] == "INTAKE"
        assert detail["entry_checklist"] == _ENTRY_CHECKLIST
        assert detail["exit_checklist"] == _EXIT_CHECKLIST
        assert "stage_completion_percent" in detail
    finally:
        shutil.rmtree(tmp)
