"""Tests for dv_harness/harness_status_event_wiring.py -- event-driven
HarnessStatusIR recomputation (2026-09-06, Global Status Bar theme,
master-prompt sections 429-431).

The two central negative controls this item's own house style requires:
  * `test_live_event_model_status_reports_unresolvable_in_this_checkout` --
    the real, current state of this repo: no "live_event_model"-themed
    module exists yet, and this module must say so honestly rather than
    pretend to consume one.
  * `test_poll_on_a_bare_project_mints_nothing` -- absence of evidence
    (no `.dv-harness/events.jsonl` at all) must never be silently treated
    as "nothing to do, all clean" in a way that mutates the project.
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from dv_harness import harness_status as hs
from dv_harness import harness_status_event_wiring as hew
from dv_harness import loop_telemetry as lt
from dv_harness.storage import StateStore


# ---------------------------------------------------------------------------
# Rule 431: this module must consume, never build, a transport.
# ---------------------------------------------------------------------------

def test_module_never_builds_a_second_transport():
    # Re-run the same check import already performs -- proves it is a real,
    # callable guard with detection power, not merely "did not raise once".
    hew.assert_consumes_never_builds_a_second_transport()


def test_transport_guard_has_real_detection_power(tmp_path):
    bad = tmp_path / "bad_module.py"
    bad.write_text(
        "from __future__ import annotations\nimport queue\n", encoding="utf-8")
    with pytest.raises(hew.HarnessStatusEventWiringError):
        hew.assert_consumes_never_builds_a_second_transport(bad)


# ---------------------------------------------------------------------------
# live_event_model_status(): an honest probe, never a guess
# ---------------------------------------------------------------------------

def test_live_event_model_status_reports_unresolvable_in_this_checkout():
    report = hew.live_event_model_status()
    assert report["resolvable"] is False
    assert report["resolved_module"] is None
    assert set(report["checked"]) == set(hew.LIVE_EVENT_MODEL_CANDIDATE_MODULES)
    assert all(v is False for v in report["checked"].values())


def test_live_event_model_status_detects_a_real_candidate_once_present():
    name = hew.LIVE_EVENT_MODEL_CANDIDATE_MODULES[0]
    injected = types.ModuleType(name)
    sys.modules[name] = injected
    try:
        report = hew.live_event_model_status()
        assert report["resolvable"] is True
        assert report["resolved_module"] == name
        assert report["checked"][name] is True
    finally:
        del sys.modules[name]


# ---------------------------------------------------------------------------
# event_kind(): duck-typed, honest None on an unrecognizable shape
# ---------------------------------------------------------------------------

def test_event_kind_reads_dict_event_field():
    assert hew.event_kind({"event": "LOOP_STARTED"}) == "LOOP_STARTED"


def test_event_kind_reads_dict_event_type_field():
    assert hew.event_kind({"event_type": "GUI_STAGE_CHANGED"}) == "GUI_STAGE_CHANGED"


def test_event_kind_reads_object_kind_attribute():
    class Ev:
        kind = "SOMETHING"
    assert hew.event_kind(Ev()) == "SOMETHING"


def test_event_kind_priority_prefers_event_over_name():
    assert hew.event_kind({"event": "A", "name": "B"}) == "A"


def test_event_kind_none_on_unrecognizable_shape():
    assert hew.event_kind({}) is None
    assert hew.event_kind(object()) is None
    assert hew.event_kind(42) is None


# ---------------------------------------------------------------------------
# recompute_harness_status_on_event(): calls the REAL HarnessStatusService,
# never a second aggregator
# ---------------------------------------------------------------------------

def _snapshot_files(root: Path):
    return sorted(p.relative_to(root).as_posix()
                  for p in root.rglob("*") if p.is_file())


def test_recompute_refuses_an_event_with_no_kind(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    with pytest.raises(hew.HarnessStatusEventWiringError):
        hew.recompute_harness_status_on_event(root, {})


def test_recompute_calls_the_real_service_and_matches_direct_serve(tmp_path):
    root = tmp_path / "proj"
    dv = root / ".dv-harness"
    dv.mkdir(parents=True)
    (dv / "state.json").write_text(json.dumps({
        "project": "usb3_link_ctrl",
        "current_stage": "VERIFY",
        "stages": {"VERIFY": {"status": "PASS", "attempts": 1}},
    }), encoding="utf-8")

    result = hew.recompute_harness_status_on_event(root, {"event": "LOOP_STARTED"})
    assert result["triggered_by"] == "LOOP_STARTED"

    direct = hs.HarnessStatusService(root).serve()
    # Both paths must agree on the real, derived state -- proving this
    # module reused HarnessStatusService rather than deriving a second,
    # possibly-disagreeing answer.
    assert result["snapshot"]["harness"]["state"] == direct["harness"]["state"]
    assert result["snapshot"]["identity"]["project_name"] == "usb3_link_ctrl"


def test_recompute_with_no_store_never_writes_anything(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    before = _snapshot_files(root)
    hew.recompute_harness_status_on_event(root, {"event": "LOOP_STARTED"})
    after = _snapshot_files(root)
    assert before == after, (
        "recompute_harness_status_on_event() with no store= must never "
        "write to the project it reports on")


def test_recompute_with_a_store_writes_one_real_audit_event(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    store = StateStore(root)  # real StateStore, mkdir()s .dv-harness/ itself

    hew.recompute_harness_status_on_event(
        root, {"event": "LOOP_VERIFY_COMPLETED"}, store=store)

    events_file = root / ".dv-harness" / "events.jsonl"
    lines = [json.loads(l) for l in events_file.read_text(
        encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0]["event"] == "STATUS_RECOMPUTE_TRIGGERED"
    assert lines[0]["triggering_event_kind"] == "LOOP_VERIFY_COMPLETED"
    assert "harness_state" in lines[0]


def test_recompute_audit_write_failure_never_crashes_the_recompute(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()

    class _BoomStore:
        def event(self, record):
            raise RuntimeError("disk full")

    result = hew.recompute_harness_status_on_event(
        root, {"event": "LOOP_STARTED"}, store=_BoomStore())
    assert "snapshot" in result
    assert "RuntimeError" in result.get("audit_write_failed", "")


# ---------------------------------------------------------------------------
# poll_and_recompute_on_new_loop_events(): the interim, real event source
# ---------------------------------------------------------------------------

def test_poll_on_a_bare_project_mints_nothing(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    before = _snapshot_files(root)

    report = hew.poll_and_recompute_on_new_loop_events(root)

    after = _snapshot_files(root)
    assert before == after, (
        "polling a project with no events.jsonl at all must never create "
        "one, or any other file")
    assert report["status"] == hew.POLL_NO_LOOP_TELEMETRY
    assert report["new_event_kinds"] == []


def _emit(store, event, run_id, **kw):
    return lt.emit(store, event, run_id=run_id, **kw)


def test_poll_processes_real_new_events_and_advances_the_watermark(tmp_path):
    root = tmp_path / "proj"
    store = StateStore(root)
    run_id = lt.new_run_id()
    _emit(store, "LOOP_CREATED", run_id)
    _emit(store, "LOOP_STARTED", run_id)

    report1 = hew.poll_and_recompute_on_new_loop_events(root)
    assert report1["status"] == hew.POLL_RECOMPUTED
    assert report1["new_event_kinds"] == ["LOOP_CREATED", "LOOP_STARTED"]
    assert report1["processed_count_before"] == 0
    assert report1["processed_count_after"] == 2
    assert "snapshot" in report1

    watermark_file = (root / ".dv-harness" / "harness_status_event_wiring"
                      / "watermark.json")
    assert watermark_file.is_file()
    assert json.loads(watermark_file.read_text())["processed_count"] == 2

    # Polling again with nothing new must report NO_NEW_EVENTS and must not
    # re-list the two already-processed events.
    report2 = hew.poll_and_recompute_on_new_loop_events(root)
    assert report2["status"] == hew.POLL_NO_NEW_EVENTS
    assert report2["new_event_kinds"] == []
    assert report2["processed_count"] == 2

    # A single genuinely new event must be the ONLY one reported the third
    # time -- proving old events are never reprocessed.
    _emit(store, "LOOP_ITERATION_STARTED", run_id)
    report3 = hew.poll_and_recompute_on_new_loop_events(root)
    assert report3["status"] == hew.POLL_RECOMPUTED
    assert report3["new_event_kinds"] == ["LOOP_ITERATION_STARTED"]
    assert report3["processed_count_before"] == 2
    assert report3["processed_count_after"] == 3


def test_poll_never_double_fires_across_repeated_calls(tmp_path):
    root = tmp_path / "proj"
    store = StateStore(root)
    run_id = lt.new_run_id()
    _emit(store, "LOOP_CREATED", run_id)

    calls = []
    real_publish = hs.HarnessStatusService.publish

    def counting_publish(self, **kw):
        calls.append(1)
        return real_publish(self, **kw)

    import pytest as _pytest  # local import to keep monkeypatch scoped
    from unittest.mock import patch
    with patch.object(hs.HarnessStatusService, "publish", counting_publish):
        hew.poll_and_recompute_on_new_loop_events(root)
        hew.poll_and_recompute_on_new_loop_events(root)
        hew.poll_and_recompute_on_new_loop_events(root)
    assert len(calls) == 1, (
        "a second/third poll with nothing new must never call publish() "
        "again")


def test_poll_with_a_store_writes_one_audit_event_naming_the_batch(tmp_path):
    root = tmp_path / "proj"
    store = StateStore(root)
    run_id = lt.new_run_id()
    _emit(store, "LOOP_CREATED", run_id)
    _emit(store, "LOOP_STARTED", run_id)

    hew.poll_and_recompute_on_new_loop_events(root, store=store)

    events_file = root / ".dv-harness" / "events.jsonl"
    lines = [json.loads(l) for l in events_file.read_text(
        encoding="utf-8").splitlines() if l.strip()]
    triggers = [l for l in lines if l.get("event") == "STATUS_RECOMPUTE_TRIGGERED"]
    assert len(triggers) == 1
    assert triggers[0]["triggering_event_batch_size"] == 2
    assert triggers[0]["triggering_event_kind"] == "LOOP_STARTED"


def test_poll_recovers_honestly_from_a_shrunk_event_log(tmp_path):
    """If a prior watermark points past the current event count (the log
    was rotated/reset), the poller must reprocess from zero rather than
    silently report NO_NEW_EVENTS forever."""
    root = tmp_path / "proj"
    store = StateStore(root)
    run_id = lt.new_run_id()
    _emit(store, "LOOP_CREATED", run_id)
    _emit(store, "LOOP_STARTED", run_id)
    hew.poll_and_recompute_on_new_loop_events(root)  # watermark -> 2

    # Simulate rotation: truncate events.jsonl to one real event.
    events_file = root / ".dv-harness" / "events.jsonl"
    lines = events_file.read_text(encoding="utf-8").splitlines()
    events_file.write_text(lines[0] + "\n", encoding="utf-8")

    report = hew.poll_and_recompute_on_new_loop_events(root)
    assert report["status"] == hew.POLL_RECOMPUTED
    assert report["processed_count_before"] == 0
    assert report["processed_count_after"] == 1


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def test_cli_live_event_model_status_exits_2_when_absent(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.harness_status_event_wiring",
         "live-event-model-status", "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["resolvable"] is False


def test_cli_poll_exits_2_on_a_bare_project(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.harness_status_event_wiring",
         "poll", "--root", str(root), "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["status"] == hew.POLL_NO_LOOP_TELEMETRY


def test_cli_poll_exits_0_after_a_real_recompute(tmp_path):
    root = tmp_path / "proj"
    store = StateStore(root)
    run_id = lt.new_run_id()
    _emit(store, "LOOP_CREATED", run_id)

    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.harness_status_event_wiring",
         "poll", "--root", str(root), "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == hew.POLL_RECOMPUTED
