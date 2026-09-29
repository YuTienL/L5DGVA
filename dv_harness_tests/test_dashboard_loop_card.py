"""GET /api/loops -- the GUI Loop Engineering Center card (LOOP-4, section 107).

Before this, `dashboard.py`'s only "loop" surface was the single-run/
continuous-run Start toggle -- a CONTROL, not observability. Section 107
requires the GUI to expose WHY a loop is running: state, iteration, verified
gain, budget, plateau, oscillation, next action, with a drill-down. Nothing on
the page could answer any of those.

Every fixture here is produced by a REAL `DVHarness.loop()` over the REAL
shipped `main_graph.json` with the REAL `command_migration_integrity_gate.py`
subprocess judging the stage -- never by writing events.jsonl lines by hand. A
card proven against hand-written events would prove the renderer and nothing
about whether the engine ever emits them. The real dashboard server is started
on a free local port and driven over real HTTP, reusing
test_dashboard_interactive.py's own harness helpers, the same convention
test_dashboard_memory_card.py and test_dashboard_amba_card.py follow.

Nothing here runs a build, a regression or an LSF submission.
"""
from __future__ import annotations

import json
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _post,
    _start_dashboard,
    _wait_ready,
)
from dv_harness_tests.controlled_experiment_fixture import (
    FIXTURE_STAGE,
    harness_factory,
    make_fixture_project,
)


def _dashboard_project(tmp: Path, port: int) -> Path:
    """The real fixture project, plus the one config block `serve()` needs.

    Only `dashboard.host`/`port` is written: `load_config()` merges its own
    defaults for everything else, so this project's retry budget and gate
    policy are the REAL shipped defaults the loop below actually spends."""
    project = make_fixture_project(tmp)
    (project / ".dv-harness").mkdir(parents=True, exist_ok=True)
    (project / ".dv-harness" / "config.json").write_text(
        json.dumps({"dashboard": {"host": "127.0.0.1", "port": port}}),
        encoding="utf-8")
    return project


def _run_real_loop(project: Path):
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("verify the command pattern migration")
    return h


def _serve(project: Path, port: int) -> str:
    base = f"http://127.0.0.1:{port}"
    _start_dashboard(project)
    _wait_ready(base)
    return base


def test_the_endpoint_reports_an_honest_empty_state_before_any_loop_ran(tmp_path):
    """A project whose loops never emitted a section-108 event must say so, and
    say what would populate it -- never render a fabricated row."""
    port = _free_port()
    project = _dashboard_project(tmp_path / "p", port)
    base = _serve(project, port)

    code, body = _get(base, "/api/loops")
    assert code == 200
    assert body["available"] is False
    assert body["rows"] == []
    assert "NO_LOOP_TELEMETRY_EVENTS" in body["reason"]
    assert "dv-harness start --loop" in body["reason"]
    # The eight section-107 columns are served even when there is no data, so
    # the table renders its header rather than collapsing to nothing.
    assert [c["label"] for c in body["columns"]] == [
        "Loop", "State", "Iteration", "Verified Gain", "Budget", "Plateau",
        "Oscillation", "Next Action"]


def test_a_real_loop_run_fills_section_107s_eight_columns(tmp_path):
    port = _free_port()
    project = _dashboard_project(tmp_path / "p", port)
    h = _run_real_loop(project)
    base = _serve(project, port)

    code, body = _get(base, "/api/loops")
    assert code == 200 and body["available"] is True
    assert len(body["rows"]) == 1
    row = body["rows"][0]

    assert row["loop"] == "verification_closure"
    assert row["state"] == "FAILED"
    assert row["iteration"] >= 2
    # The numbers are the ones the engine really spent, not a rendering.
    assert row["budget"]["attempts"] == h.state.stages[FIXTURE_STAGE]["attempts"]
    assert row["budget"]["max_stage_retries"] == h.cfg["policy"]["max_stage_retries"]
    assert row["verified_gain"]["metric"] == "gate_verified_stages"
    assert row["plateau"] == "NOT_EVALUATED"      # no evidence database here
    assert row["oscillation"] == "NOT_EVALUATED"
    assert row["next_action"], "section 107's Next Action column must not be blank"
    assert row["terminal_event"] == "LOOP_FAILED"


def test_the_drilldown_is_served_for_the_row_and_carries_all_fourteen_fields(tmp_path):
    port = _free_port()
    project = _dashboard_project(tmp_path / "p", port)
    _run_real_loop(project)
    base = _serve(project, port)

    _, body = _get(base, "/api/loops")
    run_id = body["rows"][0]["run_id"]
    detail = body["sessions"][run_id]
    for field in body["drilldown_fields"]:
        assert field["key"] in detail, f"drill-down field {field['key']} not served"
    assert detail["goal"] == "verify the command pattern migration"
    assert detail["verifier"]["gate_ids"]
    assert detail["stop_reason"]
    assert detail["iteration_history"][0]["event"] == "LOOP_CREATED"


def test_the_run_id_filter_narrows_to_one_session(tmp_path):
    port = _free_port()
    project = _dashboard_project(tmp_path / "p", port)
    h = _run_real_loop(project)
    h.state.stages[FIXTURE_STAGE]["attempts"] = 0
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("second round")
    base = _serve(project, port)

    _, everything = _get(base, "/api/loops")
    assert len(everything["rows"]) == 2
    wanted = everything["rows"][1]["run_id"]

    import urllib.parse
    _, one = _get(base, "/api/loops?run_id=" + urllib.parse.quote(wanted))
    assert len(one["rows"]) == 1
    assert one["rows"][0]["run_id"] == wanted


def test_polling_the_card_writes_nothing_and_approves_nothing(tmp_path):
    """Reading a loop's state must not be a mutating act -- and must certainly
    not mint an approval in the project's real audit trail."""
    port = _free_port()
    project = _dashboard_project(tmp_path / "p", port)
    _run_real_loop(project)
    base = _serve(project, port)

    before = {p: p.stat().st_mtime_ns
              for p in (project / ".dv-harness").rglob("*") if p.is_file()}
    for _ in range(5):
        _get(base, "/api/loops")
    after = {p: p.stat().st_mtime_ns
             for p in (project / ".dv-harness").rglob("*") if p.is_file()}
    assert before == after

    from dv_harness.control_plane import ControlPlane
    assert not ControlPlane(project).load().get("approvals")


def test_the_card_offers_no_write_endpoint_of_its_own(tmp_path):
    """Starting/stopping a loop already has a front door (POST /api/start and
    the control-plane verbs, both behind GUI-19's token gate). A loop-specific
    write endpoint would be a second way to do something that already has one."""
    port = _free_port()
    project = _dashboard_project(tmp_path / "p", port)
    base = _serve(project, port)

    code, body = _post(base, "/api/loops", {"action": "stop"})
    assert code == 404
    assert body["error"] == "NOT_FOUND"


def test_the_card_and_its_javascript_are_really_wired_into_the_page(tmp_path):
    """An endpoint nothing on the page calls is not a GUI card."""
    port = _free_port()
    project = _dashboard_project(tmp_path / "p", port)
    base = _serve(project, port)

    import urllib.request
    with urllib.request.urlopen(base + "/", timeout=10) as resp:
        html = resp.read().decode("utf-8")
    assert 'id="loopCenterCard"' in html
    assert "Loop Engineering Center" in html
    assert "/api/loops" in html
    assert "loadLoopCenter()" in html
    assert "showLoopDetail(" in html
    # Joined to the 3s poll: a running loop's state is exactly the thing that
    # must not be minutes stale on a control plane.
    assert "await loadLoopCenter();" in html


def test_an_unreadable_audit_trail_reports_a_reason_rather_than_a_500(tmp_path,
                                                                     monkeypatch):
    """Same contract every other read-only GET on this server holds to."""
    from dv_harness import dashboard, loop_telemetry

    def boom(*a, **k):
        raise OSError("events.jsonl is unreadable")
    monkeypatch.setattr(loop_telemetry, "read_loop_telemetry", boom)

    payload = dashboard._read_loop_engineering_state(tmp_path)
    assert payload["available"] is False
    assert "LOOP_TELEMETRY_UNREADABLE" in payload["reason"]
    assert len(payload["columns"]) == 8
