"""dv_harness.live_event_model -- the GUI Live Event Model (data model + emit/read only).

WHAT THESE TESTS ARE FOR. Not "the vocabulary tuple has eleven strings in it" -- the failure
modes that actually matter for a fixed-vocabulary event model plus a reader over a REAL,
already-shared `.dv-harness/events.jsonl` trail:

  1. A vocabulary that silently widens/narrows/duplicates, or collides with `models.Status` --
     each import-time guard is proven to have real detection power via a direct mutation, not
     merely asserted to pass once.
  2. `emit()` writing anywhere OTHER than the real `storage.StateStore.event()` trail -- proven
     by round-tripping through a REAL `StateStore` and reading the REAL `events.jsonl` bytes
     back, and by proving a section-108 `loop_telemetry` event lands in the SAME file and the
     SAME shared reader sees both, never two separate audit trails.
  3. The reader FABRICATING a clean/empty result when nothing has ever been emitted -- the
     mandatory negative control: a bare project must report `available: False` naming the real
     file and the real reason, never a silently-empty "everything is fine".
  4. `read_events()` being a second, independently-written events.jsonl parser rather than a
     real re-export of `loop_telemetry.read_events` -- proven by monkeypatching THAT module's
     own function and observing this module's call site pick up the patch.
  5. `emit()` accepting a name outside the fixed eleven, or a non-serializable payload, without
     refusing -- both are hard requirements a mis-typed event name or a bad payload must never
     silently slip past.

Nothing here runs a build, a regression, an LSF submission, or touches any approval mechanism.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import live_event_model as lem
from dv_harness import loop_telemetry as lt
from dv_harness.models import Status
from dv_harness.storage import StateStore


# --------------------------------------------------------------------------
# Vocabulary hygiene
# --------------------------------------------------------------------------
def test_vocabulary_is_exactly_eleven_unique_names():
    assert len(lem.GUI_LIVE_EVENTS) == 11
    assert len(set(lem.GUI_LIVE_EVENTS)) == 11
    assert all(isinstance(n, str) and n for n in lem.GUI_LIVE_EVENTS)


def test_vocabulary_shares_no_token_with_models_status():
    status_values = {s.value for s in Status}
    assert not (set(lem.GUI_LIVE_EVENTS) & status_values)


def test_totality_guard_has_real_detection_power_on_wrong_count():
    original = lem.GUI_LIVE_EVENTS
    try:
        lem.GUI_LIVE_EVENTS = original[:-1]  # ten names
        with pytest.raises(AssertionError, match="exactly 11"):
            lem.assert_gui_live_events_total()
    finally:
        lem.GUI_LIVE_EVENTS = original


def test_totality_guard_has_real_detection_power_on_duplicate():
    original = lem.GUI_LIVE_EVENTS
    try:
        lem.GUI_LIVE_EVENTS = original[:-1] + (original[0],)  # still 11, but a duplicate
        with pytest.raises(AssertionError, match="duplicate"):
            lem.assert_gui_live_events_total()
    finally:
        lem.GUI_LIVE_EVENTS = original


def test_vocabulary_collision_guard_has_real_detection_power():
    original = lem.GUI_LIVE_EVENTS
    try:
        lem.GUI_LIVE_EVENTS = original[:-1] + (Status.PASS.value,)
        with pytest.raises(AssertionError, match="collides"):
            lem.assert_no_verification_verdict_vocabulary()
    finally:
        lem.GUI_LIVE_EVENTS = original


# --------------------------------------------------------------------------
# emit() -- the writer half
# --------------------------------------------------------------------------
def test_emit_refuses_a_name_outside_the_eleven(tmp_path):
    store = StateStore(tmp_path)
    with pytest.raises(lem.GuiLiveEventError, match="not one of the eleven"):
        lem.emit(store, "GUI_TOTALLY_MADE_UP_EVENT")


def test_emit_refuses_a_non_serializable_payload(tmp_path):
    store = StateStore(tmp_path)

    class Unserializable:
        pass

    with pytest.raises(lem.GuiLiveEventError, match="not JSON-serializable"):
        lem.emit(store, "GUI_STAGE_STATUS_CHANGED", weird=Unserializable())


def test_emit_writes_through_the_real_state_store_events_file(tmp_path):
    store = StateStore(tmp_path)
    record = lem.emit(store, "GUI_APPROVAL_RECORDED", source="control_plane.approve",
                      stage="SIGNOFF", reviewer_id="alice")

    events_file = tmp_path / ".dv-harness" / "events.jsonl"
    assert events_file.exists()
    lines = [json.loads(l) for l in events_file.read_text(encoding="utf-8").splitlines() if l]
    assert len(lines) == 1
    assert lines[0]["event"] == "GUI_APPROVAL_RECORDED"
    assert lines[0]["source"] == "control_plane.approve"
    assert lines[0]["stage"] == "SIGNOFF"
    assert lines[0]["reviewer_id"] == "alice"
    assert "ts" in lines[0]
    # emit() returns the exact record it wrote.
    assert record == lines[0]


def test_emit_never_writes_a_second_audit_file(tmp_path):
    store = StateStore(tmp_path)
    lem.emit(store, "GUI_COVERAGE_SAMPLE_INGESTED", source="evidence_db.insert_coverage_sample")
    dv_dir = tmp_path / ".dv-harness"
    files = sorted(p.name for p in dv_dir.iterdir())
    # state.json (from StateStore.__init__) plus events.jsonl -- nothing named for this module.
    assert "events.jsonl" in files
    assert not any("live_event" in f or "gui_event" in f for f in files)


def test_gui_events_and_loop_telemetry_events_share_one_file_one_reader(tmp_path):
    """A section-108 loop event and a GUI live event land in the SAME events.jsonl, and the
    SHARED reader (loop_telemetry.read_events, which this module re-exports) sees both -- there
    is no second, GUI-only audit trail."""
    store = StateStore(tmp_path)
    lt.emit(store, "LOOP_STARTED", run_id="verification_closure_loop:20260101T000000Z:1")
    lem.emit(store, "GUI_LOOP_TELEMETRY_EMITTED", source="loop_telemetry.emit",
             bridged_event="LOOP_STARTED")

    entries, scanned, truncated = lem.read_events(tmp_path)
    names = [e.get("event") for e in entries]
    assert "LOOP_STARTED" in names
    assert "GUI_LOOP_TELEMETRY_EMITTED" in names
    assert scanned == 2
    assert truncated is False


# --------------------------------------------------------------------------
# read_events() -- proven to be a real re-export, not a second parser
# --------------------------------------------------------------------------
def test_read_events_is_a_real_delegation_to_loop_telemetry(tmp_path, monkeypatch):
    sentinel = (["SENTINEL"], 999, True)
    monkeypatch.setattr(lt, "read_events", lambda root, scan_lines=0: sentinel)
    assert lem.read_events(tmp_path) == sentinel


def test_default_scan_lines_matches_loop_telemetry():
    assert lem.DEFAULT_EVENT_SCAN_LINES == lt.DEFAULT_EVENT_SCAN_LINES


# --------------------------------------------------------------------------
# gui_live_events() -- filtering by name
# --------------------------------------------------------------------------
def test_gui_live_events_filters_to_requested_names(tmp_path):
    store = StateStore(tmp_path)
    lem.emit(store, "GUI_STAGE_STATUS_CHANGED", source="engine.run_stage")
    lem.emit(store, "GUI_WAIVER_STATUS_CHANGED", source="waiver_store.record_waiver")

    picked, stats = lem.gui_live_events(tmp_path, event_names=("GUI_WAIVER_STATUS_CHANGED",))
    assert [e["event"] for e in picked] == ["GUI_WAIVER_STATUS_CHANGED"]
    assert stats["gui_live_events"] == 1


def test_gui_live_events_refuses_an_unrecognized_name(tmp_path):
    with pytest.raises(lem.GuiLiveEventError, match="outside the eleven"):
        lem.gui_live_events(tmp_path, event_names=("GUI_NOT_REAL",))


# --------------------------------------------------------------------------
# list_gui_live_events() -- the mandatory negative control, then real filtering
# --------------------------------------------------------------------------
def test_list_on_a_bare_project_reports_available_false_honestly(tmp_path):
    """The mandatory negative control: nothing has ever emitted a GUI live event (true of every
    real project today, since the transport/dispatch layer is a separate, later item) -- the
    reader must report an honest empty state naming the real file and the real reason, never a
    fabricated 'everything is clean'."""
    payload = lem.list_gui_live_events(tmp_path)
    assert payload["available"] is False
    assert payload["events"] == []
    assert str(tmp_path) in payload["events_file"]
    assert ".dv-harness" in payload["events_file"] and "events.jsonl" in payload["events_file"]
    assert lem.NO_GUI_LIVE_EVENTS in payload["reason"]
    assert payload["event_names"] == list(lem.GUI_LIVE_EVENTS)
    # Reading must not itself create the project tree it is asked about.
    assert not (tmp_path / ".dv-harness").exists()


def test_list_reports_available_true_once_something_is_recorded(tmp_path):
    store = StateStore(tmp_path)
    lem.emit(store, "GUI_CONTROL_COMMAND_EXECUTED", source="dashboard.control_command",
             command="pause")
    payload = lem.list_gui_live_events(tmp_path)
    assert payload["available"] is True
    assert len(payload["events"]) == 1
    assert payload["events"][0]["command"] == "pause"


def test_list_filters_by_single_event(tmp_path):
    store = StateStore(tmp_path)
    lem.emit(store, "GUI_STAGE_STATUS_CHANGED", source="a")
    lem.emit(store, "GUI_GATE_VERDICT_RECORDED", source="b")
    payload = lem.list_gui_live_events(tmp_path, event="GUI_GATE_VERDICT_RECORDED")
    assert [e["event"] for e in payload["events"]] == ["GUI_GATE_VERDICT_RECORDED"]


def test_list_filters_by_event_set(tmp_path):
    store = StateStore(tmp_path)
    lem.emit(store, "GUI_STAGE_STATUS_CHANGED")
    lem.emit(store, "GUI_GATE_VERDICT_RECORDED")
    lem.emit(store, "GUI_WAIVER_STATUS_CHANGED")
    payload = lem.list_gui_live_events(
        tmp_path, events=("GUI_STAGE_STATUS_CHANGED", "GUI_WAIVER_STATUS_CHANGED"))
    names = {e["event"] for e in payload["events"]}
    assert names == {"GUI_STAGE_STATUS_CHANGED", "GUI_WAIVER_STATUS_CHANGED"}


def test_list_refuses_event_and_events_together(tmp_path):
    with pytest.raises(lem.GuiLiveEventError, match="never both"):
        lem.list_gui_live_events(tmp_path, event="GUI_STAGE_STATUS_CHANGED",
                                 events=("GUI_GATE_VERDICT_RECORDED",))


def test_list_filters_by_source(tmp_path):
    store = StateStore(tmp_path)
    lem.emit(store, "GUI_LSF_JOB_STATUS_CHANGED", source="lsf_client.reconcile", job_id="J1")
    lem.emit(store, "GUI_LSF_JOB_STATUS_CHANGED", source="dashboard.manual_poll", job_id="J2")
    payload = lem.list_gui_live_events(tmp_path, source="lsf_client.reconcile")
    assert [e["job_id"] for e in payload["events"]] == ["J1"]


def test_list_filters_by_since_ts(tmp_path):
    store = StateStore(tmp_path)
    lem.emit(store, "GUI_STAGE_TRANSITIONED", stage="A")
    early_ts = "2020-01-01T00:00:00+00:00"
    late_ts = "2099-01-01T00:00:00+00:00"
    all_events = lem.list_gui_live_events(tmp_path, since_ts=early_ts)["events"]
    assert len(all_events) == 1
    none_events = lem.list_gui_live_events(tmp_path, since_ts=late_ts)["events"]
    assert none_events == []


def test_list_respects_limit_keeping_the_most_recent(tmp_path):
    store = StateStore(tmp_path)
    for i in range(5):
        lem.emit(store, "GUI_HUMAN_GATE_OPENED", seq=i)
    payload = lem.list_gui_live_events(tmp_path, event="GUI_HUMAN_GATE_OPENED", limit=2)
    assert [e["seq"] for e in payload["events"]] == [3, 4]


# --------------------------------------------------------------------------
# execute_verb() / CLI front door
# --------------------------------------------------------------------------
def test_execute_verb_names():
    code, payload = lem.execute_verb(Path("."), "names")
    assert code == 0
    assert payload["event_names"] == list(lem.GUI_LIVE_EVENTS)


def test_execute_verb_events_on_bare_project_exits_2(tmp_path):
    code, payload = lem.execute_verb(tmp_path, "events")
    assert code == 2
    assert payload["available"] is False


def test_execute_verb_list_after_emit_exits_0(tmp_path):
    store = StateStore(tmp_path)
    lem.emit(store, "GUI_APPROVAL_RECORDED")
    code, payload = lem.execute_verb(tmp_path, "list")
    assert code == 0
    assert payload["available"] is True


def test_execute_verb_unknown_verb():
    code, payload = lem.execute_verb(Path("."), "bogus")
    assert code == 1
    assert payload["error"] == "UNKNOWN_VERB"


def test_real_cli_subprocess_names(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.live_event_model", "names",
         "--project-root", str(tmp_path)],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["event_names"] == list(lem.GUI_LIVE_EVENTS)


def test_real_cli_subprocess_events_bare_project_exits_2(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.live_event_model", "events",
         "--project-root", str(tmp_path)],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["available"] is False


def test_real_cli_subprocess_list_with_filters(tmp_path):
    store = StateStore(tmp_path)
    lem.emit(store, "GUI_WAIVER_STATUS_CHANGED", source="waiver_store.record_waiver")
    lem.emit(store, "GUI_STAGE_STATUS_CHANGED", source="engine.run_stage")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.live_event_model", "list",
         "--project-root", str(tmp_path), "--event", "GUI_WAIVER_STATUS_CHANGED"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [e["event"] for e in payload["events"]] == ["GUI_WAIVER_STATUS_CHANGED"]
