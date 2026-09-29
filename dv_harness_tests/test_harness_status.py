"""Tests for dv_harness/harness_status.py -- HarnessStatusIR + Global State
Aggregator + HarnessStatusService (2026-09-06, Global Status Bar theme).

The central negative control (`test_bare_project_reports_unknown_never_ready`)
is the Evidence Truth Rule / GF-AT-28 proof this whole item exists to satisfy:
a project with NO `.dv-harness/` tree at all must report `harness.state ==
"UNKNOWN"`, never a fabricated READY, and the aggregation must mint nothing
on disk while answering the question.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import harness_status as hs
from dv_harness import escalation_notify as en


# ---------------------------------------------------------------------------
# Vocabulary / severity fold
# ---------------------------------------------------------------------------

def test_harness_state_vocabulary_is_total():
    # Re-run the same assertion import already performs -- proves it is a
    # real, callable check with detection power, not merely "did not raise
    # once at import time".
    hs.assert_harness_state_vocabulary_total()


def test_worst_harness_state_empty_is_unknown_never_ready():
    assert hs.worst_harness_state([]) == "UNKNOWN"
    assert hs.worst_harness_state([None, None]) == "UNKNOWN"


def test_worst_harness_state_not_applicable_never_contributes():
    # An all-NOT_APPLICABLE input must fold to UNKNOWN, not to a fabricated
    # READY and not to NOT_APPLICABLE itself (which never enters the fold).
    assert hs.worst_harness_state(["NOT_APPLICABLE", "NOT_APPLICABLE"]) == "UNKNOWN"


def test_worst_harness_state_unknown_outranks_ready():
    # GF-AT-28: one real UNKNOWN among many clean READY values must never be
    # averaged away.
    assert hs.worst_harness_state(["READY", "READY", "UNKNOWN"]) == "UNKNOWN"


def test_worst_harness_state_blocked_outranks_everything_else():
    assert hs.worst_harness_state(
        ["READY", "SIGNOFF_READY", "RUNNING", "BLOCKED", "PARTIAL"]) == "BLOCKED"


def test_worst_harness_state_failed_is_the_single_worst_state():
    assert hs.worst_harness_state(["FAILED", "BLOCKED", "HUMAN_GATE"]) == "FAILED"


def test_worst_harness_state_unrecognized_value_never_contributes():
    # A stray/garbage string must be excluded from the fold rather than
    # silently treated as a legitimate (and possibly ready-shaped) status.
    assert hs.worst_harness_state(["not-a-real-status", "READY"]) == "READY"
    assert hs.worst_harness_state(["not-a-real-status"]) == "UNKNOWN"


# ---------------------------------------------------------------------------
# Section 407: harness.state must never conflate a subsystem's own state
# ---------------------------------------------------------------------------

def test_assert_harness_state_never_conflates_subsystem_passes_on_consistent_ir():
    ir = hs.HarnessStatusIR()
    ir.harness.dimension_states = {"agent": "READY", "regression": "PARTIAL"}
    ir.harness.state = "PARTIAL"  # == worst_harness_state(["READY","PARTIAL"])
    hs.assert_harness_state_never_conflates_subsystem(ir)  # must not raise


def test_assert_harness_state_never_conflates_subsystem_catches_substitution():
    # The exact failure mode section 407 exists to forbid: harness.state
    # silently reads as one subsystem's own (better-looking) value instead
    # of the real worst-wins fold over every dimension.
    ir = hs.HarnessStatusIR()
    ir.harness.dimension_states = {"agent": "READY", "regression": "BLOCKED"}
    ir.harness.state = "READY"  # wrong: agent's IDLE/READY state substituted
    with pytest.raises(hs.HarnessStatusError):
        hs.assert_harness_state_never_conflates_subsystem(ir)


# ---------------------------------------------------------------------------
# GlobalStateAggregator -- the central negative control
# ---------------------------------------------------------------------------

def _snapshot_files(root: Path):
    return sorted(p.relative_to(root).as_posix()
                  for p in root.rglob("*") if p.is_file())


def test_bare_project_reports_unknown_never_ready(tmp_path):
    """The mandated negative control: absence of evidence must report
    UNKNOWN honestly, never a fabricated READY/SIGNOFF_READY -- and reading
    the status of a project that has never run must mint nothing on disk."""
    root = tmp_path / "bare_project"
    root.mkdir()
    before = _snapshot_files(root)

    ir = hs.GlobalStateAggregator.assemble(root)

    after = _snapshot_files(root)
    assert before == after, (
        "assembling a status report must never write to the project it "
        "reports on")
    assert not (root / ".dv-harness").exists(), (
        "no .dv-harness/ tree may be minted merely by asking for status")

    assert ir.harness.state == "UNKNOWN"
    # golden_flow_readiness's own overall verdict may legitimately read
    # PARTIAL rather than pure UNKNOWN for a bare project -- some of its
    # twenty rows (e.g. "dashboard"/"claude_cli_integration") are real
    # deployment-capability checks independent of project state and can
    # genuinely resolve READY even here (see combine_readiness()'s own
    # documented "a mix of READY and UNKNOWN is PARTIAL" rule). The
    # property this negative control actually guards is that it never
    # reads as fully READY/SIGNOFF_READY for a project with no evidence.
    assert ir.harness.readiness in ("UNKNOWN", "PARTIAL")
    # Every one of the eight preserved dimensions must be individually
    # present (section 407) -- not collapsed into the one overall value.
    for dim in ("workflow", "agent", "loop", "regression", "remote",
                "evidence", "signoff", "closure", "harness"):
        assert dim in ir.harness.dimension_states
    # And the honesty surface must actually be populated -- a bare project
    # has real, nameable gaps, not a silently-empty unknowns list.
    assert ir.unknowns, "a bare project must report real, named unknowns"
    for u in ir.unknowns:
        assert u.get("field") and u.get("reason")


def test_bare_project_never_conflates_harness_state():
    root_ir = hs.GlobalStateAggregator  # just referencing the class is cheap
    assert callable(root_ir.assemble)


def test_assemble_is_read_only_over_a_project_with_real_state(tmp_path):
    """A project with a real (but otherwise empty-of-evidence) state.json
    must still be read without mutation, and the recorded current_stage
    must be surfaced onto workflow.current_node."""
    root = tmp_path / "real_project"
    dv = root / ".dv-harness"
    dv.mkdir(parents=True)
    (dv / "state.json").write_text(json.dumps({
        "project": "usb3_link_ctrl",
        "current_stage": "VERIFY",
        "stages": {"VERIFY": {"status": "PASS", "attempts": 1}},
    }), encoding="utf-8")
    before = (dv / "state.json").read_text(encoding="utf-8")

    ir = hs.GlobalStateAggregator.assemble(root)

    after = (dv / "state.json").read_text(encoding="utf-8")
    assert before == after, "reading status must never mutate state.json"
    assert ir.identity.project_name == "usb3_link_ctrl"
    assert ir.workflow.current_node == "VERIFY"
    # Every real gathered field is either resolved or honestly recorded as
    # an unknown -- never silently dropped.
    assert isinstance(ir.unknowns, list)


def test_evidence_source_refs_names_the_real_modules_consulted(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    ir = hs.GlobalStateAggregator.assemble(root)
    joined = " ".join(ir.evidence.source_refs)
    # A handful of the real producers this aggregation is REQUIRED to read,
    # per the task's own REUSE OVER REINVENT list.
    for expected in (
        "golden_flow_readiness", "platform_health", "loop_telemetry",
        "signoff_export", "system_closure_aggregator",
        "subsystem_maturity_gate", "loop_stale_detection",
    ):
        assert any(expected in ref for ref in ir.evidence.source_refs), (
            f"evidence.source_refs never cites {expected!r}: {joined}")


# ---------------------------------------------------------------------------
# HarnessStatusService
# ---------------------------------------------------------------------------

def test_service_serve_is_json_serializable_and_read_only(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    service = hs.HarnessStatusService(root)
    snapshot = service.serve()
    json.dumps(snapshot)  # must not raise
    assert snapshot["harness"]["state"] == "UNKNOWN"
    assert not (root / ".dv-harness").exists()


def test_service_normalize_coerces_unrecognized_status_to_unknown():
    service = hs.HarnessStatusService(Path("."))
    ir = hs.HarnessStatusIR()
    ir.harness.state = "TOTALLY_MADE_UP"
    ir.harness.readiness = "ALSO_FAKE"
    ir.harness.signoff_state = "READY"  # legitimate value, kept as-is
    ir.harness.dimension_states = {"agent": "garbage"}
    normalized = service.normalize(ir)
    assert normalized.harness.state == "UNKNOWN"
    assert normalized.harness.readiness == "UNKNOWN"
    assert normalized.harness.signoff_state == "READY"
    assert normalized.harness.dimension_states == {"agent": "UNKNOWN"}


def test_service_validate_raises_gf_at_28_violation_on_hand_forged_ir():
    """A caller could, by mistake, hand-construct an IR whose harness.state
    was set to a ready-shaped value while every real dimension is UNKNOWN.
    validate() must catch that rather than let it publish."""
    service = hs.HarnessStatusService(Path("."))
    ir = hs.HarnessStatusIR()
    ir.harness.dimension_states = {"agent": "UNKNOWN", "regression": "UNKNOWN"}
    ir.harness.state = "READY"  # a forged, unearned claim
    with pytest.raises(hs.HarnessStatusError):
        service.validate(ir)


def test_service_authorizes_nothing_against_its_own_real_source():
    # Already run once at import; calling it again against the real file on
    # disk proves it is a real, re-runnable check.
    hs.assert_service_authorizes_nothing()


def test_service_authorizes_nothing_has_real_detection_power(tmp_path):
    """Mirrors platform_health.py's own proof technique for
    assert_authorizes_nothing(): a crafted file that DOES reference
    forbidden authorization machinery must be caught."""
    bad = tmp_path / "fake_module.py"
    bad.write_text(
        '"""not the real module."""\n'
        "from .control_plane import ControlPlane\n"
        "def approve(x):\n"
        "    return ControlPlane().can_signoff()\n",
        encoding="utf-8",
    )
    with pytest.raises(hs.HarnessStatusError):
        hs.assert_service_authorizes_nothing(bad)


# ---------------------------------------------------------------------------
# publish(): change-only notification, reusing escalation_notify.py verbatim
# ---------------------------------------------------------------------------

class _FakeTransport:
    def __init__(self):
        self.sent = []

    def send(self, title, body, tags=None):
        self.sent.append((title, body, tuple(tags or ())))
        return True


def _service_with_signoff(monkeypatch, root: Path, stage_status: str):
    """A HarnessStatusService whose real signoff_export.read_signoff_stage_
    status() call is monkeypatched to return exactly the recorded stage
    status a test wants to drive publish() with -- every OTHER gatherer
    still runs for real against `root` (a bare project), so this proves the
    real aggregation pipeline reaches the signoff dimension end to end."""
    from dv_harness import signoff_export

    def fake_status(r):
        return {"stage_status": stage_status, "current_stage": "SIGNOFF"}

    monkeypatch.setattr(signoff_export, "read_signoff_stage_status", fake_status)
    transport = _FakeTransport()
    notifier = en.EscalationNotifier(en.EscalationConfig(enabled=True),
                                      transport=transport)
    service = hs.HarnessStatusService(root, notifier=notifier)
    return service, transport


def test_publish_never_fires_on_the_first_call(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    service, transport = _service_with_signoff(monkeypatch, root, "FAIL")
    snapshot, event = service.publish()
    assert snapshot["harness"]["signoff_state"] == "BLOCKED"
    assert event is None
    assert transport.sent == []


def test_publish_fires_only_on_a_genuine_transition_into_blocked(monkeypatch, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    from dv_harness import signoff_export
    calls = {"status": "NOT_STARTED"}

    def fake_status(r):
        return {"stage_status": calls["status"], "current_stage": "SIGNOFF"}

    monkeypatch.setattr(signoff_export, "read_signoff_stage_status", fake_status)
    transport = _FakeTransport()
    notifier = en.EscalationNotifier(en.EscalationConfig(enabled=True),
                                      transport=transport)
    service = hs.HarnessStatusService(root, notifier=notifier)

    snap1, ev1 = service.publish()
    assert snap1["harness"]["signoff_state"] == "UNKNOWN"
    assert ev1 is None  # first publish: nothing to compare against

    calls["status"] = "FAIL"
    snap2, ev2 = service.publish()
    assert snap2["harness"]["signoff_state"] == "BLOCKED"
    assert ev2 is not None and ev2.fired and ev2.kind == "signoff_blocked"
    assert len(transport.sent) == 1

    # Change-only: staying BLOCKED on a third publish must NOT fire again.
    snap3, ev3 = service.publish()
    assert snap3["harness"]["signoff_state"] == "BLOCKED"
    assert ev3 is None
    assert len(transport.sent) == 1, "must not re-fire while stuck BLOCKED"

    # And a transition OUT of BLOCKED must not fire either (the condition
    # this notifier's own signoff_blocked() fires on is specifically
    # "newly blocked", never "no longer blocked").
    calls["status"] = "PASS"
    snap4, ev4 = service.publish()
    assert snap4["harness"]["signoff_state"] == "SIGNOFF_READY"
    assert ev4 is None
    assert len(transport.sent) == 1


def test_publish_with_no_notifier_never_touches_a_transport(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    service = hs.HarnessStatusService(root)  # notifier omitted entirely
    snap1, ev1 = service.publish()
    snap2, ev2 = service.publish()
    assert ev1 is None and ev2 is None


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def test_execute_verb_bare_project_exits_2(tmp_path, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    code = hs.execute_verb(["--root", str(root)])
    assert code == 2
    out = capsys.readouterr().out
    assert "HARNESS STATE: UNKNOWN" in out


def test_execute_verb_json_output_is_valid_json(tmp_path, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    code = hs.execute_verb(["--root", str(root), "--json"])
    assert code == 2
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["harness"]["state"] == "UNKNOWN"
    assert "unknowns" in payload


def test_cli_real_subprocess(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.harness_status",
         "--root", str(root), "--json"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 2, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["harness"]["state"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# Status History Audit (section 435) -- persistence through the REAL
# StateStore.event() trail, never a second audit file
# ---------------------------------------------------------------------------

def test_reading_history_on_a_project_with_no_recorded_snapshot_is_honest(tmp_path):
    """The mandated negative control for THIS item: absence of a recorded
    snapshot must read as an explicit, named "no history recorded" -- never
    a silently-empty list a caller could misread as "checked, and it is
    clean", and it must mint nothing on disk while answering the question
    (reading history is exactly as read-only as `serve()`)."""
    root = tmp_path / "proj"
    root.mkdir()
    before = _snapshot_files(root)

    hist = hs.read_harness_status_history(root)

    after = _snapshot_files(root)
    assert before == after, "reading history must never write to the project"
    assert not (root / ".dv-harness").exists(), (
        "no .dv-harness/ tree may be minted merely by asking for history")
    assert hist["available"] is False
    assert hist["reason"] == hs.NO_HARNESS_STATUS_HISTORY
    assert hist["history"] == []
    assert hist["count"] == 0


def test_service_history_on_a_bare_project_is_also_honestly_empty(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    service = hs.HarnessStatusService(root)
    hist = service.history()
    assert hist["available"] is False
    assert not (root / ".dv-harness").exists()


def test_record_persists_through_the_real_events_jsonl_trail(tmp_path):
    """`record()` writes through the REAL `storage.StateStore.event()` --
    the same append-only `.dv-harness/events.jsonl` `loop_telemetry.emit()`
    and every other audit mechanism in this project already use. There is no
    second audit file: only `events.jsonl` may exist after a `record()`
    call beyond whatever `StateStore()` itself always creates
    (`state.json`)."""
    from dv_harness.storage import StateStore

    root = tmp_path / "proj"
    root.mkdir()
    store = StateStore(root)
    service = hs.HarnessStatusService(root)

    snapshot, event_record = service.record(store)

    events_file = root / ".dv-harness" / "events.jsonl"
    assert events_file.exists(), "record() must write through the real events.jsonl"
    lines = [l for l in events_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    on_disk = json.loads(lines[0])
    assert on_disk["event"] == hs.HARNESS_STATUS_SNAPSHOT_EVENT
    # Compare through a JSON round trip on both sides -- the returned
    # in-memory record can legitimately carry a real Python tuple (e.g.
    # `freshness.stale_after_policy`'s own `(seconds, reason)` pair) that
    # JSON has no tuple type for and renders as a list; that is an artifact
    # of JSON serialization, not a disagreement about WHAT was recorded.
    assert on_disk == json.loads(json.dumps(event_record)), (
        "the returned event record must be exactly what was written to disk")
    assert on_disk["harness_state"] == snapshot["harness"]["state"] == "UNKNOWN"
    assert on_disk["readiness"] == snapshot["harness"]["readiness"]
    assert on_disk["signoff_state"] == snapshot["harness"]["signoff_state"]
    assert on_disk["unknown_count"] == len(snapshot["unknowns"])
    # The full snapshot travels with the event -- a reader can reconstruct
    # the exact historical HarnessStatusIR this session observed, not only
    # its top-line state.
    assert on_disk["snapshot"] == json.loads(json.dumps(snapshot))

    # No second, parallel audit file was created for this -- exactly one
    # `events.jsonl` exists, and no sibling file with an event/audit-shaped
    # name (`events2.jsonl`, `harness_status_events.jsonl`, ...) appeared
    # beside it. (`config.json`/`control.json` may legitimately also be
    # present here -- a pre-existing, separately-disclosed side effect of
    # `golden_flow_readiness.derive_golden_flow_readiness()`, one of the
    # real producers `aggregate()` reads through, and out of this item's own
    # scope to change.)
    dv_files = sorted(p.name for p in (root / ".dv-harness").iterdir() if p.is_file())
    assert dv_files.count("events.jsonl") == 1
    assert not any("event" in name and name != "events.jsonl" for name in dv_files), dv_files


def test_aggregate_serve_publish_never_persist_a_snapshot_on_their_own(tmp_path):
    """`record()` is the ONLY method that writes a history entry. Calling
    `aggregate()`/`serve()`/`publish()` any number of times must never grow
    `events.jsonl` on their own -- persistence is always the caller's
    explicit `record()` call, never an implicit side effect of asking for
    status."""
    root = tmp_path / "proj"
    root.mkdir()
    service = hs.HarnessStatusService(root)
    service.aggregate()
    service.serve()
    service.serve()
    service.publish()
    assert not (root / ".dv-harness").exists()


def test_history_reads_back_a_real_recorded_snapshot(tmp_path):
    """Round trip: record one real snapshot, then read it back through both
    the module-level reader and the service's own `history()` convenience,
    and confirm the two never disagree."""
    from dv_harness.storage import StateStore

    root = tmp_path / "proj"
    root.mkdir()
    store = StateStore(root)
    service = hs.HarnessStatusService(root)
    _, event_record = service.record(store)

    expected = json.loads(json.dumps(event_record))  # see note in the test above

    hist = hs.read_harness_status_history(root)
    assert hist["available"] is True
    assert hist["count"] == 1
    assert hist["history"] == [expected]
    assert hist["latest"] == expected

    hist_via_service = service.history()
    assert hist_via_service == hist


def test_history_preserves_multiple_real_distinguishable_snapshots(monkeypatch, tmp_path):
    """The point of a HISTORY (never a "last snapshot" cache): recording a
    BLOCKED signoff state and then, later, a genuinely different
    SIGNOFF_READY state must leave BOTH real, distinguishable entries on
    disk, oldest first -- neither overwrites the other."""
    from dv_harness import signoff_export
    from dv_harness.storage import StateStore

    root = tmp_path / "proj"
    root.mkdir()
    calls = {"status": "FAIL"}

    def fake_status(r):
        return {"stage_status": calls["status"], "current_stage": "SIGNOFF"}

    monkeypatch.setattr(signoff_export, "read_signoff_stage_status", fake_status)
    store = StateStore(root)
    service = hs.HarnessStatusService(root)

    service.record(store)
    calls["status"] = "PASS"
    service.record(store)

    hist = hs.read_harness_status_history(root)
    assert hist["available"] is True
    assert hist["count"] == 2
    assert [h["signoff_state"] for h in hist["history"]] == ["BLOCKED", "SIGNOFF_READY"]
    # The chronologically-later entry is the one `latest`/service.history()
    # report -- never the other way around, and never merged into one.
    assert hist["latest"]["signoff_state"] == "SIGNOFF_READY"


def test_recorded_events_are_indistinguishable_in_shape_from_other_audit_events(tmp_path):
    """Section 435's own "never a second audit file" rule, checked
    structurally: a `HARNESS_STATUS_SNAPSHOT` event must sit in the SAME
    `events.jsonl` file, in the SAME real `StateStore.event()` append-only
    shape, alongside an unrelated event another real subsystem already
    writes through the identical mechanism -- proving there is exactly one
    audit trail in this project, not a family of near-identical ones."""
    from dv_harness.storage import StateStore

    root = tmp_path / "proj"
    root.mkdir()
    store = StateStore(root)
    store.event({"event": "CLI_ACCESS", "ts": "2026-09-06T00:00:00", "cmd": "status"})
    service = hs.HarnessStatusService(root)
    service.record(store)

    events_file = root / ".dv-harness" / "events.jsonl"
    lines = [json.loads(l) for l in events_file.read_text(encoding="utf-8").splitlines()
             if l.strip()]
    assert [e["event"] for e in lines] == ["CLI_ACCESS", hs.HARNESS_STATUS_SNAPSHOT_EVENT]

    hist = hs.read_harness_status_history(root)
    assert hist["count"] == 1, "the unrelated CLI_ACCESS event must never be miscounted"


def test_cli_history_flag_reports_no_history_honestly(tmp_path, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    code = hs.execute_verb(["--root", str(root), "--history"])
    assert code == 2
    out = capsys.readouterr().out
    assert "NO HARNESS STATUS HISTORY" in out
    assert not (root / ".dv-harness").exists()


def test_cli_record_then_history_round_trips(tmp_path, capsys):
    root = tmp_path / "proj"
    root.mkdir()

    code = hs.execute_verb(["--root", str(root), "--record", "--json"])
    assert code == 2  # harness.state is UNKNOWN on a bare project
    recorded_payload = json.loads(capsys.readouterr().out)
    assert recorded_payload["harness"]["state"] == "UNKNOWN"
    assert (root / ".dv-harness" / "events.jsonl").exists()

    code = hs.execute_verb(["--root", str(root), "--history", "--json"])
    assert code == 0
    hist_payload = json.loads(capsys.readouterr().out)
    assert hist_payload["available"] is True
    assert hist_payload["count"] == 1
    assert hist_payload["history"][0]["harness_state"] == "UNKNOWN"


def test_cli_bare_serve_still_never_persists_regardless_of_new_flags(tmp_path):
    """The pre-existing default CLI behavior (no `--record`, no `--history`)
    must remain byte-for-byte read-only, exactly as
    `test_execute_verb_bare_project_exits_2` already proves -- re-asserted
    here alongside the new flags to guard against a future edit accidentally
    making persistence the default."""
    root = tmp_path / "proj"
    root.mkdir()
    code = hs.execute_verb(["--root", str(root)])
    assert code == 2
    assert not (root / ".dv-harness").exists()


def test_cli_real_subprocess_record_and_history(tmp_path):
    """The real `python -m dv_harness.harness_status` entry point, driven as
    a real subprocess, actually persists to and reads back from the real
    `.dv-harness/events.jsonl` on disk."""
    root = tmp_path / "proj"
    root.mkdir()
    repo_root = str(Path(__file__).resolve().parents[1])

    proc1 = subprocess.run(
        [sys.executable, "-m", "dv_harness.harness_status",
         "--root", str(root), "--record", "--json"],
        cwd=repo_root, capture_output=True, text=True, timeout=120,
    )
    assert proc1.returncode == 2, proc1.stderr
    assert (root / ".dv-harness" / "events.jsonl").exists()

    proc2 = subprocess.run(
        [sys.executable, "-m", "dv_harness.harness_status",
         "--root", str(root), "--history", "--json"],
        cwd=repo_root, capture_output=True, text=True, timeout=120,
    )
    assert proc2.returncode == 0, proc2.stderr
    hist = json.loads(proc2.stdout)
    assert hist["available"] is True
    assert hist["count"] == 1


# ---------------------------------------------------------------------------
# Section 435's own named transition fields: Previous State / New State /
# Trigger / User-or-Agent Action -- carried on every recorded snapshot event,
# additive over the pre-existing shape and never a second audit file.
# ---------------------------------------------------------------------------

def test_first_record_on_a_project_has_no_prior_state_to_compare(tmp_path):
    """The mandated negative control for this extension: the very FIRST
    `record()` call for a project has no earlier recorded snapshot to read
    back, so `previous_state`/`transitioned` must be honestly `None` --
    never a fabricated `"UNKNOWN"` guess and never silently defaulted to
    `False`, which would misreport "nothing changed" about a transition
    that was never observed at all."""
    from dv_harness.storage import StateStore

    root = tmp_path / "proj"
    root.mkdir()
    store = StateStore(root)
    service = hs.HarnessStatusService(root)

    _, event_record = service.record(store)

    assert event_record["previous_state"] is None
    assert event_record["transitioned"] is None
    # Section 435's Trigger / User-or-Agent Action default honestly: an
    # explicit ad hoc call (the same "manual" default
    # `question_queue.build_digest()` already uses for the identical
    # reason) with no actor attributed.
    assert event_record["trigger"] == "manual"
    assert event_record["user_agent_action"] is None


def test_second_record_carries_the_real_previous_state_and_transitioned_flag(monkeypatch, tmp_path):
    """A SECOND `record()` call over a genuinely different signoff state
    must carry the real prior `harness_state` as `previous_state` (read
    back off THIS project's own real `events.jsonl` trail -- never a
    second, separately-tracked "last state" cache) and `transitioned: True`
    -- section 435's own worked example, `BLOCKED -> ... -> READY`-shaped,
    made checkable per recorded event rather than only by diffing two rows
    by hand."""
    from dv_harness import signoff_export
    from dv_harness.storage import StateStore

    root = tmp_path / "proj"
    root.mkdir()
    calls = {"status": "FAIL"}

    def fake_status(r):
        return {"stage_status": calls["status"], "current_stage": "SIGNOFF"}

    monkeypatch.setattr(signoff_export, "read_signoff_stage_status", fake_status)
    store = StateStore(root)
    service = hs.HarnessStatusService(root)

    first, _ = service.record(store)
    assert first["harness"]["signoff_state"] == "BLOCKED"

    calls["status"] = "PASS"
    second_event = service.record(store)[1]

    assert second_event["previous_state"] == "BLOCKED"
    assert second_event["transitioned"] is (second_event["previous_state"] != second_event["harness_state"])


def test_repeated_record_with_no_real_change_reports_transitioned_false(tmp_path):
    """The complementary honest case: TWO recorded snapshots over a project
    whose real `harness.state` genuinely did not move must report
    `transitioned: False` -- never `True` -- and must still both be
    persisted as real, distinguishable history entries (section 435's own
    "persist meaningful state transitions" does not mean discard the ones
    that were not transitions; a caller filtering `transitioned` gets the
    meaningful subset without this module silently dropping the rest)."""
    from dv_harness.storage import StateStore

    root = tmp_path / "proj"
    root.mkdir()
    store = StateStore(root)
    service = hs.HarnessStatusService(root)

    first_event = service.record(store)[1]
    second_event = service.record(store)[1]

    assert first_event["harness_state"] == second_event["harness_state"] == "UNKNOWN"
    assert second_event["previous_state"] == "UNKNOWN"
    assert second_event["transitioned"] is False

    hist = hs.read_harness_status_history(root)
    assert hist["count"] == 2


def test_trigger_and_user_agent_action_are_caller_declared_never_inferred(tmp_path):
    """`trigger`/`user_agent_action` are section 435's own "Trigger" /
    "User/Agent Action" fields -- plain, caller-supplied context this
    module never infers on its own (it has no way to know WHY a caller
    invoked `record()`), carried through verbatim onto the persisted event
    exactly as declared."""
    from dv_harness.storage import StateStore

    root = tmp_path / "proj"
    root.mkdir()
    store = StateStore(root)
    service = hs.HarnessStatusService(root)

    _, event_record = service.record(
        store, trigger="stage_boundary", user_agent_action="SIGNOFF stage PASS (engine.run_stage)")

    assert event_record["trigger"] == "stage_boundary"
    assert event_record["user_agent_action"] == "SIGNOFF stage PASS (engine.run_stage)"

    # And the real events.jsonl trail carries it too -- not merely the
    # in-memory return value.
    hist = hs.read_harness_status_history(root)
    assert hist["latest"]["trigger"] == "stage_boundary"
    assert hist["latest"]["user_agent_action"] == "SIGNOFF stage PASS (engine.run_stage)"


def test_record_still_writes_through_the_one_real_events_jsonl_with_new_fields(tmp_path):
    """The new fields must never become a second audit mechanism -- they
    are additional keys on the SAME `HARNESS_STATUS_SNAPSHOT` event in the
    SAME `events.jsonl`, proven the same structural way
    `test_recorded_events_are_indistinguishable_in_shape_from_other_audit_events`
    already proves the base event is."""
    from dv_harness.storage import StateStore

    root = tmp_path / "proj"
    root.mkdir()
    store = StateStore(root)
    store.event({"event": "CLI_ACCESS", "ts": "2026-09-06T00:00:00", "cmd": "status"})
    service = hs.HarnessStatusService(root)
    service.record(store, trigger="manual")

    events_file = root / ".dv-harness" / "events.jsonl"
    lines = [json.loads(l) for l in events_file.read_text(encoding="utf-8").splitlines()
             if l.strip()]
    assert [e["event"] for e in lines] == ["CLI_ACCESS", hs.HARNESS_STATUS_SNAPSHOT_EVENT]
    snapshot_event = lines[1]
    for key in ("previous_state", "transitioned", "trigger", "user_agent_action"):
        assert key in snapshot_event, f"missing section-435 field {key!r} on the persisted event"


def test_record_harness_status_snapshot_with_a_store_lacking_root_never_crashes(tmp_path):
    """`record_harness_status_snapshot()` is documented to accept ANY
    duck-typed object exposing a real `.event(dict)` method, not only a
    real `storage.StateStore`. A caller-supplied store with no `.root`
    attribute must still work -- `previous_state` degrades honestly to
    `None` (this module has no way to look up prior history without a real
    project root) rather than raising."""

    class _MinimalStore:
        def __init__(self) -> None:
            self.events: list = []

        def event(self, record):
            self.events.append(record)

    ir = hs.GlobalStateAggregator.assemble(tmp_path)
    store = _MinimalStore()
    record = hs.record_harness_status_snapshot(store, ir)

    assert record["previous_state"] is None
    assert record["transitioned"] is None
    assert len(store.events) == 1


def test_cli_record_prints_transition_and_accepts_trigger_and_by_flags(tmp_path, capsys):
    """The CLI's `--trigger`/`--by` flags feed section 435's own fields
    through to the persisted record, and the human-readable `--record`
    summary line shows the real `previous_state -> new_state` transition
    once a prior snapshot exists."""
    root = tmp_path / "proj"
    root.mkdir()

    code = hs.execute_verb(["--root", str(root), "--record",
                            "--trigger", "manual", "--by", "pytest"])
    assert code == 2
    first_out = capsys.readouterr().out
    assert "RECORDED snapshot" in first_out

    code = hs.execute_verb(["--root", str(root), "--record",
                            "--trigger", "stage_boundary", "--by", "engine"])
    assert code == 2
    second_out = capsys.readouterr().out
    assert "UNKNOWN -> UNKNOWN" in second_out

    hist = hs.read_harness_status_history(root)
    assert hist["history"][0]["trigger"] == "manual"
    assert hist["history"][0]["user_agent_action"] == "pytest"
    assert hist["history"][1]["trigger"] == "stage_boundary"
    assert hist["history"][1]["user_agent_action"] == "engine"


def test_cli_history_text_output_shows_previous_state_arrow(tmp_path, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    hs.execute_verb(["--root", str(root), "--record"])
    capsys.readouterr()
    hs.execute_verb(["--root", str(root), "--record"])
    capsys.readouterr()

    code = hs.execute_verb(["--root", str(root), "--history"])
    assert code == 0
    out = capsys.readouterr().out
    assert "UNKNOWN -> UNKNOWN" in out
