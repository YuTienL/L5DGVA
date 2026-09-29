"""Tests for dv_harness/gui_audit_log.py.

Covers: the 7-field record constructor and its required-field refusals; the
real StateStore.event()-backed writer (record_gui_action) proving it appends
to the SAME .dv-harness/events.jsonl file the generic audit trail already
uses, never a second store; capture_control_scope()'s passive, non-minting
reads (including the mandatory negative control -- an absent control.json/
state.json/candidate is reported with an honest _scope_status reason, never
a fabricated snapshot); extract_who()'s real fallback chain; extract_approval()
scoping approval to only the 3 real approval-granting commands; wrap_dispatch()
driven against the REAL dashboard._dispatch_control() (never a stub) on both
its success and its raising path; read_gui_audit_log()'s type/action
filtering and tolerance of a malformed line; and both the module's own
execute_verb() and a real `python -m dv_harness.gui_audit_log` subprocess.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.control_plane import ControlPlane
from dv_harness.engine import DVHarness
from dv_harness.gui_audit_log import (
    GUI_AUDIT_FIELDS,
    GUI_AUDIT_RECORD_TYPE,
    GuiAuditLogError,
    RESULT_ERROR,
    RESULT_OK,
    build_gui_audit_record,
    capture_control_scope,
    execute_verb,
    extract_approval,
    extract_who,
    read_gui_audit_log,
    record_gui_action,
    wrap_dispatch,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# build_gui_audit_record
# ---------------------------------------------------------------------------

def test_build_gui_audit_record_carries_exactly_the_7_named_fields():
    rec = build_gui_audit_record(
        who="alice", when="2026-09-06T00:00:00+00:00", action="PAUSE",
        before={"paused": False}, after={"paused": True},
        evidence={"command": "PAUSE", "reason": "lunch"},
        approval=None, result={"status": RESULT_OK, "value": {"paused": True}},
    )
    for field in GUI_AUDIT_FIELDS:
        assert field in rec
    assert rec["type"] == GUI_AUDIT_RECORD_TYPE
    assert rec["action"] == "PAUSE"
    assert rec["who"] == "alice"
    assert rec["before"] == {"paused": False}
    assert rec["after"] == {"paused": True}
    assert rec["approval"] is None
    assert rec["result"]["status"] == RESULT_OK


@pytest.mark.parametrize("field", ["who", "when", "action"])
def test_build_gui_audit_record_refuses_blank_required_string(field):
    kwargs = dict(who="alice", when="2026-09-06T00:00:00+00:00", action="PAUSE",
                  before=None, after=None, evidence=None, approval=None,
                  result={"status": RESULT_OK})
    kwargs[field] = "   "
    with pytest.raises(GuiAuditLogError):
        build_gui_audit_record(**kwargs)


def test_build_gui_audit_record_refuses_missing_result_status_key():
    with pytest.raises(GuiAuditLogError):
        build_gui_audit_record(who="alice", when="2026-09-06T00:00:00+00:00",
                                action="PAUSE", before=None, after=None,
                                evidence=None, approval=None, result={})


def test_build_gui_audit_record_refuses_non_dict_result():
    with pytest.raises(GuiAuditLogError):
        build_gui_audit_record(who="alice", when="2026-09-06T00:00:00+00:00",
                                action="PAUSE", before=None, after=None,
                                evidence=None, approval=None, result="OK")


def test_build_gui_audit_record_refuses_unrecognized_result_status():
    with pytest.raises(GuiAuditLogError):
        build_gui_audit_record(who="alice", when="2026-09-06T00:00:00+00:00",
                                action="PAUSE", before=None, after=None,
                                evidence=None, approval=None,
                                result={"status": "MAYBE"})


def test_build_gui_audit_record_accepts_none_before_after_approval_as_honest_absence():
    # None is legal evidence (nothing to snapshot, no approval granted) --
    # never refused the way a missing who/when/action/result IS refused.
    rec = build_gui_audit_record(who="alice", when="2026-09-06T00:00:00+00:00",
                                  action="RESUME", before=None, after=None,
                                  evidence=None, approval=None,
                                  result={"status": RESULT_OK})
    assert rec["before"] is None
    assert rec["after"] is None
    assert rec["approval"] is None


# ---------------------------------------------------------------------------
# record_gui_action -- writes through the REAL StateStore.event(), same file
# ---------------------------------------------------------------------------

def test_record_gui_action_appends_to_the_same_events_jsonl_generic_trail_uses(tmp_path):
    h = DVHarness(tmp_path)
    # A generic event first, exactly as commands.cmd_pause() would write.
    h.store.event({"ts": "2026-09-06T00:00:00+00:00", "cmd": "pause", "reason": ""})
    record_gui_action(tmp_path, who="alice", action="PAUSE",
                       before={"paused": False}, after={"paused": True},
                       evidence={"command": "PAUSE"}, approval=None,
                       result={"status": RESULT_OK, "value": {"paused": True}})
    events_file = tmp_path / ".dv-harness" / "events.jsonl"
    lines = [json.loads(l) for l in events_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2
    assert lines[0]["cmd"] == "pause"  # the generic record, untouched
    assert lines[1]["type"] == GUI_AUDIT_RECORD_TYPE
    assert lines[1]["who"] == "alice"


def test_record_gui_action_defaults_when_to_a_real_timestamp(tmp_path):
    h = DVHarness(tmp_path)
    rec = record_gui_action(tmp_path, who="alice", action="RESUME",
                             before=None, after=None, evidence=None,
                             approval=None, result={"status": RESULT_OK})
    assert rec["when"]
    assert isinstance(rec["when"], str)


# ---------------------------------------------------------------------------
# capture_control_scope -- passive reads, honest absence, never fabricated
# ---------------------------------------------------------------------------

def test_capture_control_scope_reports_honest_absence_on_a_bare_project(tmp_path):
    # Mandatory negative control: no .dv-harness tree exists at all yet.
    # capture_control_scope() must NEVER mint control.json/state.json to
    # answer this (that would make "asking" a mutating act), and must never
    # fabricate a plausible-looking empty snapshot.
    scope = capture_control_scope(tmp_path, "PAUSE", {})
    assert scope["_scope_status"] == "NO_CONTROL_FILE_YET"
    assert not (tmp_path / ".dv-harness").exists()

    scope2 = capture_control_scope(tmp_path, "REDIRECT", {})
    assert scope2["_scope_status"] == "NO_STATE_FILE_YET"
    assert not (tmp_path / ".dv-harness").exists()


def test_capture_control_scope_pause_resume_real_before_after(tmp_path):
    cp = ControlPlane(tmp_path)
    cp.load()  # materializes a real control.json, exactly as ControlPlane always does
    before = capture_control_scope(tmp_path, "PAUSE", {})
    assert before["_scope_status"] == "CAPTURED"
    assert before["paused"] is False
    cp.pause("lunch")
    after = capture_control_scope(tmp_path, "PAUSE", {})
    assert after["paused"] is True
    assert after["paused_reason"] == "lunch"


def test_capture_control_scope_approve_scopes_to_one_stage_only(tmp_path):
    cp = ControlPlane(tmp_path)
    cp.approve("INTAKE", note="looks good", reviewer_id="bob", reviewer_confidence="HIGH")
    cp.approve("DISCOVERY", note="also fine", reviewer_id="carol", reviewer_confidence="HIGH")
    scope = capture_control_scope(tmp_path, "APPROVE", {"stage": "INTAKE"})
    assert scope["_scope_status"] == "CAPTURED"
    assert scope["approval"]["reviewer_id"] == "bob"
    # The OTHER stage's approval must never leak into this record.
    assert "DISCOVERY" not in json.dumps(scope)


def test_capture_control_scope_redirect_reads_current_stage_from_state_json(tmp_path):
    h = DVHarness(tmp_path)
    scope = capture_control_scope(tmp_path, "REDIRECT", {})
    assert scope["_scope_status"] == "CAPTURED"
    assert scope["current_stage"] == h.state.current_stage


def test_capture_control_scope_research_reject_unknown_candidate_is_honest(tmp_path):
    DVHarness(tmp_path)
    scope = capture_control_scope(tmp_path, "RESEARCH_REJECT", {"candidate_id": "does-not-exist"})
    assert scope["_scope_status"] == "CANDIDATE_NOT_FOUND"
    scope2 = capture_control_scope(tmp_path, "RESEARCH_REJECT", {})
    assert scope2["_scope_status"] == "NO_CANDIDATE_ID"


def test_capture_control_scope_unknown_action_reports_named_reason(tmp_path):
    DVHarness(tmp_path)
    scope = capture_control_scope(tmp_path, "SOMETHING_NEW", {})
    assert scope["_scope_status"].startswith("NO_SCOPE_MAPPING_FOR_ACTION")


# ---------------------------------------------------------------------------
# extract_who / extract_approval
# ---------------------------------------------------------------------------

def test_extract_who_prefers_reviewer_id_then_corrected_by_then_taken_by():
    assert extract_who({"reviewer_id": "bob"}) == "bob"
    assert extract_who({"corrected_by": "carol"}) == "carol"
    assert extract_who({"taken_by": "dave"}) == "dave"
    assert extract_who({"reviewer_id": "bob", "taken_by": "dave"}) == "bob"


def test_extract_who_falls_back_to_real_os_user_never_a_placeholder():
    from dv_harness.control_plane import _default_user
    assert extract_who({}) == _default_user()
    assert extract_who({"reviewer_id": "   "}) == _default_user()


def test_extract_approval_only_for_the_3_real_approval_granting_commands():
    approve_result = {"stage": "INTAKE", "reviewer_id": "bob",
                       "reviewer_confidence": "HIGH", "note": "ok", "approved_at": "t"}
    approval = extract_approval("APPROVE", approve_result)
    assert approval["reviewer_id"] == "bob"
    assert approval["approved_at"] == "t"

    cosign_result = {"stage": "INTAKE", "field_path": "gate/loc", "value": 3,
                      "reviewer_id": "carol", "reviewer_confidence": "HIGH",
                      "cosigned_at": "t2"}
    cosign_approval = extract_approval("COSIGN", cosign_result)
    assert cosign_approval["field_path"] == "gate/loc"
    assert cosign_approval["value"] == 3

    research_result = {"candidate_id": "X", "approval": {"reviewer_id": "dave"}}
    research_approval = extract_approval("RESEARCH_APPROVE", research_result)
    assert research_approval == {"reviewer_id": "dave"}


def test_extract_approval_is_none_for_every_non_approval_command():
    # A PAUSE is not an approval action -- must never copy in some OTHER
    # stage's currently-active approval just to make the field look populated.
    assert extract_approval("PAUSE", {"paused": True}) is None
    assert extract_approval("REDIRECT", {"redirected_to": "X"}) is None
    assert extract_approval("APPROVE", "not-a-dict") is None
    assert extract_approval("RESEARCH_APPROVE", {"approval": "not-a-dict"}) is None


# ---------------------------------------------------------------------------
# wrap_dispatch -- against the REAL dashboard._dispatch_control()
# ---------------------------------------------------------------------------

def test_wrap_dispatch_success_writes_one_ok_record_with_real_before_after(tmp_path):
    from dv_harness.dashboard import _dispatch_control

    DVHarness(tmp_path)
    result = wrap_dispatch(tmp_path, {"command": "PAUSE", "reason": "coffee"}, _dispatch_control)
    assert result == {"paused": True, "reason": "coffee"}
    assert ControlPlane(tmp_path).is_paused()

    records = read_gui_audit_log(tmp_path)
    assert len(records) == 1
    rec = records[0]
    assert rec["action"] == "PAUSE"
    assert rec["result"]["status"] == RESULT_OK
    # No control.json existed before this dispatch (DVHarness() only mints
    # state.json) -- the honest "before" is NO_CONTROL_FILE_YET, never a
    # fabricated paused:False.
    assert rec["before"]["_scope_status"] == "NO_CONTROL_FILE_YET"
    assert rec["after"]["paused"] is True
    assert rec["evidence"]["reason"] == "coffee"


def test_wrap_dispatch_error_path_writes_error_record_and_still_raises(tmp_path):
    from dv_harness.dashboard import _dispatch_control

    DVHarness(tmp_path)
    # APPROVE with no stage -> _dispatch_control raises ValueError("stage is required...")
    with pytest.raises(ValueError):
        wrap_dispatch(tmp_path, {"command": "APPROVE", "note": "x"}, _dispatch_control)

    records = read_gui_audit_log(tmp_path)
    assert len(records) == 1
    rec = records[0]
    assert rec["action"] == "APPROVE"
    assert rec["result"]["status"] == RESULT_ERROR
    assert "stage" in rec["result"]["message"]
    assert rec["approval"] is None


def test_wrap_dispatch_approve_records_the_real_granted_approval(tmp_path):
    from dv_harness.dashboard import _dispatch_control

    DVHarness(tmp_path)
    body = {"command": "APPROVE", "stage": "INTAKE", "note": "clean",
            "reviewer_id": "bob", "reviewer_confidence": "HIGH"}
    wrap_dispatch(tmp_path, body, _dispatch_control)
    rec = read_gui_audit_log(tmp_path, action="APPROVE")[0]
    assert rec["who"] == "bob"
    assert rec["before"]["_scope_status"] == "NO_CONTROL_FILE_YET"
    assert rec["after"]["approval"]["reviewer_id"] == "bob"
    assert rec["approval"]["reviewer_id"] == "bob"
    assert rec["approval"]["note"] == "clean"


def test_wrap_dispatch_unknown_command_still_produces_an_error_record(tmp_path):
    from dv_harness.dashboard import _dispatch_control

    DVHarness(tmp_path)
    with pytest.raises(ValueError):
        wrap_dispatch(tmp_path, {"command": "NOT_A_REAL_COMMAND"}, _dispatch_control)
    rec = read_gui_audit_log(tmp_path)[0]
    assert rec["action"] == "NOT_A_REAL_COMMAND"
    assert rec["result"]["status"] == RESULT_ERROR
    assert rec["before"]["_scope_status"].startswith("NO_SCOPE_MAPPING_FOR_ACTION")


def test_wrap_dispatch_never_writes_a_record_when_the_dispatcher_itself_is_not_called_yet(tmp_path):
    # Sanity: an untouched project has no structured GUI audit records at all.
    assert read_gui_audit_log(tmp_path) == []


# ---------------------------------------------------------------------------
# read_gui_audit_log -- filtering, ordering, tolerance
# ---------------------------------------------------------------------------

def test_read_gui_audit_log_filters_generic_events_and_narrows_by_action(tmp_path):
    h = DVHarness(tmp_path)
    h.store.event({"ts": "t", "cmd": "pause"})  # generic -- must never be returned
    record_gui_action(tmp_path, who="a", action="PAUSE", before=None, after=None,
                       evidence=None, approval=None, result={"status": RESULT_OK})
    record_gui_action(tmp_path, who="a", action="RESUME", before=None, after=None,
                       evidence=None, approval=None, result={"status": RESULT_OK})
    all_records = read_gui_audit_log(tmp_path)
    assert len(all_records) == 2
    assert all(r["type"] == GUI_AUDIT_RECORD_TYPE for r in all_records)
    only_pause = read_gui_audit_log(tmp_path, action="PAUSE")
    assert len(only_pause) == 1
    assert only_pause[0]["action"] == "PAUSE"


def test_read_gui_audit_log_respects_limit_keeping_the_most_recent(tmp_path):
    DVHarness(tmp_path)
    for i in range(5):
        record_gui_action(tmp_path, who="a", action=f"ACT{i}", before=None, after=None,
                           evidence=None, approval=None, result={"status": RESULT_OK})
    limited = read_gui_audit_log(tmp_path, limit=2)
    assert [r["action"] for r in limited] == ["ACT3", "ACT4"]


def test_read_gui_audit_log_skips_a_malformed_line_without_failing(tmp_path):
    DVHarness(tmp_path)
    record_gui_action(tmp_path, who="a", action="PAUSE", before=None, after=None,
                       evidence=None, approval=None, result={"status": RESULT_OK})
    events_file = tmp_path / ".dv-harness" / "events.jsonl"
    with events_file.open("a", encoding="utf-8") as f:
        f.write("{not valid json\n")
    records = read_gui_audit_log(tmp_path)
    assert len(records) == 1


def test_read_gui_audit_log_on_a_bare_project_is_honestly_empty(tmp_path):
    assert read_gui_audit_log(tmp_path) == []


# ---------------------------------------------------------------------------
# dashboard.py wiring: GET /api/audit and _audit_trail carry the structured
# log too, without disturbing the generic `events`/`corrections`/etc keys.
# ---------------------------------------------------------------------------

def test_audit_trail_carries_gui_audit_log_key_without_disturbing_existing_keys(tmp_path):
    from dv_harness.dashboard import _audit_trail, _dispatch_control

    DVHarness(tmp_path)
    wrap_dispatch(tmp_path, {"command": "PAUSE", "reason": "x"}, _dispatch_control)
    trail = _audit_trail(tmp_path, limit=10)
    assert "gui_audit_log" in trail
    assert len(trail["gui_audit_log"]) == 1
    assert trail["gui_audit_log"][0]["action"] == "PAUSE"
    # Existing generic shape untouched.
    for key in ("limit", "events", "corrections", "approvals", "approval_history", "cosigns"):
        assert key in trail


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def test_execute_verb_show_json(tmp_path, capsys):
    DVHarness(tmp_path)
    record_gui_action(tmp_path, who="alice", action="PAUSE", before=None, after=None,
                       evidence=None, approval=None, result={"status": RESULT_OK})
    rc = execute_verb(["show", "--root", str(tmp_path), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out) == 1
    assert out[0]["who"] == "alice"


def test_execute_verb_show_empty_project_text_mode(tmp_path, capsys):
    rc = execute_verb(["show", "--root", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "No structured GUI audit records found." in out


def test_real_subprocess_cli(tmp_path):
    DVHarness(tmp_path)
    ControlPlane(tmp_path).pause("test")
    record_gui_action(tmp_path, who="alice", action="PAUSE", before=None, after=None,
                       evidence=None, approval=None, result={"status": RESULT_OK})
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.gui_audit_log", "show",
         "--root", str(tmp_path), "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert len(out) == 1
    assert out[0]["action"] == "PAUSE"
