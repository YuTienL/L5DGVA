"""Anti-drift tests for dv_harness/execution_contract.py (the L5DGVA
Human Non-Scheduler Execution Contract). Test names match the
requirements doc's/integration prompt's own named anti-drift list
exactly (section 18/"Anti-Drift Tests"); each verifies real behavior via
`can_i_stop()`/`resolve_next_action()`/persistence, not string matching
alone."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dv_harness.execution_contract import (
    WorkflowSignals, StopDecision, can_i_stop, validate_stop_reason,
    InvalidStopReasonError, resolve_next_action, NEXT_ACTION_TABLE,
    persist_stop, read_persisted_stop, signals_from_model_handoff_state,
    human_transport_report, human_authority_report,
    STATUS_AUTO_RUNNING, STATUS_WAITING_FOR_HUMAN_TRANSPORT,
    STATUS_WAITING_FOR_HUMAN_AUTHORITY, STATUS_BLOCKED, STATUS_COMPLETE,
    CANONICAL_STOP_REASONS, INVALID_GENERIC_STOP_REASONS,
)
from dv_harness.model_handoff import build_handoff
from dv_harness.model_handoff_workflow import export_handoff
from dv_harness.task_boundary_conformance import TaskBoundary

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    _run(work, "init", "-q")
    _run(work, "config", "user.email", "test@example.com")
    _run(work, "config", "user.name", "Test")
    (work / "dv_harness").mkdir()
    (work / "dv_harness" / "module_a.py").write_text("# a\n", encoding="utf-8")
    _run(work, "add", "-A")
    _run(work, "commit", "-q", "-m", "initial")
    return work


# --- 1. Auto-actionable never stops for the user ---------------------------

def test_auto_actionable_result_does_not_stop_for_user():
    d = can_i_stop(WorkflowSignals(auto_actionable_pending=True))
    assert d.should_continue is True
    assert d.status == STATUS_AUTO_RUNNING
    assert d.human_action_required == "NO"
    assert d.stop_reason is None


def test_fix_now_correctness_blocker_auto_continues():
    # A FIX_NOW_CORRECTNESS_BLOCKER finding is modeled as real
    # required_remediation_pending work -- it must continue, not stop.
    d = can_i_stop(WorkflowSignals(required_remediation_pending=True))
    assert d.should_continue is True
    assert d.status == STATUS_AUTO_RUNNING


def test_required_validation_auto_continues():
    d = can_i_stop(WorkflowSignals(required_verification_pending=True))
    assert d.should_continue is True
    assert d.status == STATUS_AUTO_RUNNING


def test_required_regression_auto_continues():
    d = can_i_stop(WorkflowSignals(required_regression_pending=True))
    assert d.should_continue is True
    assert d.status == STATUS_AUTO_RUNNING


def test_rereview_preparation_auto_continues():
    d = can_i_stop(WorkflowSignals(required_rereview_preparation_pending=True))
    assert d.should_continue is True
    assert d.status == STATUS_AUTO_RUNNING


# --- 2. Result import auto-resume -------------------------------------------

def test_result_import_auto_resumes():
    # RESULT_CONSUMED must route to real follow-on action, never to a
    # user-scheduling prompt.
    rec = resolve_next_action("RESULT_CONSUMED")
    assert rec.next_action == "AUTO_REMEDIATE_CONFIRMED_FINDINGS"
    assert rec.auto_actionable is True
    assert rec.human_action_required == "NO"
    assert rec.stop_reason is None


def test_next_action_table_matches_all_named_worked_examples():
    assert NEXT_ACTION_TABLE["RESULT_CONSUMED"] == "AUTO_REMEDIATE_CONFIRMED_FINDINGS"
    assert NEXT_ACTION_TABLE["FIX_COMPLETE"] == "RUN_FOCUSED_VALIDATION"
    assert NEXT_ACTION_TABLE["VALIDATION_PASS"] == "RUN_REQUIRED_REGRESSION"
    assert NEXT_ACTION_TABLE["REGRESSION_PASS"] == "PREPARE_REQUIRED_RE_REVIEW"
    assert NEXT_ACTION_TABLE["RE_REVIEW_HANDOFF_READY"] == "HUMAN_TRANSPORT_REQUIRED"


def test_rereview_handoff_ready_routes_to_real_transport_stop():
    rec = resolve_next_action("RE_REVIEW_HANDOFF_READY")
    assert rec.next_action == "HUMAN_TRANSPORT_REQUIRED"
    assert rec.auto_actionable is False
    assert rec.human_action_required == "YES"
    assert rec.next_action_owner == "HUMAN"


def test_unknown_event_is_a_real_error_never_a_guessed_default():
    with pytest.raises(ValueError):
        resolve_next_action("SOME_EVENT_NOT_IN_THE_TABLE")


# --- 3. Real stop gates ------------------------------------------------------

def test_human_transport_requires_stop():
    d = can_i_stop(WorkflowSignals(human_transport_required=True, resume_action="AUTO_RESUME"))
    assert d.should_continue is False
    assert d.status == STATUS_WAITING_FOR_HUMAN_TRANSPORT
    assert d.stop_reason == "HUMAN_TRANSPORT_REQUIRED"
    assert d.human_action_required == "YES"


def test_human_authority_requires_stop():
    d = can_i_stop(WorkflowSignals(human_authority_required=True))
    assert d.should_continue is False
    assert d.status == STATUS_WAITING_FOR_HUMAN_AUTHORITY
    assert d.stop_reason == "HUMAN_AUTHORITY_REQUIRED"


def test_safe_execution_blocked_requires_stop():
    d = can_i_stop(WorkflowSignals(safe_execution_blocked=True))
    assert d.should_continue is False
    assert d.status == STATUS_BLOCKED
    assert d.stop_reason == "SAFE_EXECUTION_BLOCKED"


def test_termination_policy_triggered_requires_stop_never_becomes_pass():
    d = can_i_stop(WorkflowSignals(termination_policy_triggered=True))
    assert d.should_continue is False
    assert d.stop_reason == "TERMINATION_POLICY_TRIGGERED"
    assert d.status != STATUS_COMPLETE  # never silently resolves to PASS/complete


def test_higher_priority_gate_wins_when_multiple_signals_are_true():
    # Human Authority outranks Human Transport outranks the rest, per
    # the exact documented decision order.
    d = can_i_stop(WorkflowSignals(human_authority_required=True, human_transport_required=True))
    assert d.stop_reason == "HUMAN_AUTHORITY_REQUIRED"


# --- 4. Invalid generic stops are rejected, not merely discouraged --------

@pytest.mark.parametrize("reason", INVALID_GENERIC_STOP_REASONS)
def test_waiting_for_review_is_not_valid_stop_reason(reason):
    with pytest.raises(InvalidStopReasonError):
        validate_stop_reason(reason)


def test_waiting_for_continue_is_not_valid_stop_reason():
    with pytest.raises(InvalidStopReasonError):
        validate_stop_reason("WAITING_FOR_USER_TO_CONTINUE")


def test_every_canonical_stop_reason_is_accepted():
    for reason in CANONICAL_STOP_REASONS:
        validate_stop_reason(reason)  # must not raise


def test_stop_decision_construction_rejects_an_invalid_reason_defensively():
    with pytest.raises(InvalidStopReasonError):
        StopDecision(should_continue=False, status=STATUS_BLOCKED,
                    stop_reason="WAITING_FOR_GENERIC_APPROVAL")


# --- 5. Canonical task completion -------------------------------------------

def test_task_complete_rejected_with_pending_auto_actions():
    # canonical_task_complete=True is asserted, but real pending work
    # still outranks it in the decision order -- it must NOT stop.
    d = can_i_stop(WorkflowSignals(canonical_task_complete=True,
                                   required_regression_pending=True))
    assert d.should_continue is True
    assert d.status == STATUS_AUTO_RUNNING


def test_subtask_complete_does_not_equal_canonical_task_complete():
    # No pending work AND no asserted canonical_task_complete -> the
    # safe default is CONTINUE, never a false COMPLETE.
    d = can_i_stop(WorkflowSignals())
    assert d.should_continue is True
    assert d.status == STATUS_AUTO_RUNNING
    assert d.status != STATUS_COMPLETE


def test_canonical_task_complete_asserted_with_zero_pending_work_stops():
    d = can_i_stop(WorkflowSignals(canonical_task_complete=True))
    assert d.should_continue is False
    assert d.status == STATUS_COMPLETE
    assert d.stop_reason == "TASK_COMPLETE"


# --- 6. Transport / persist / resume ----------------------------------------

def test_transport_resume_restores_next_action(tmp_path: Path):
    root = tmp_path
    decision = can_i_stop(WorkflowSignals(
        human_transport_required=True, resume_action="AUTO_RESUME",
        next_required_action="import Codex RESULT_V1.md",
    ))
    persist_stop(root, "T-TRANSPORT", decision)

    restored = read_persisted_stop(root, "T-TRANSPORT")
    assert restored is not None
    assert restored["STATE"] == STATUS_WAITING_FOR_HUMAN_TRANSPORT
    assert restored["STOP_REASON"] == "HUMAN_TRANSPORT_REQUIRED"
    assert restored["RESUME_ACTION"] == "AUTO_RESUME"
    assert restored["NEXT_REQUIRED_ACTION"] == "import Codex RESULT_V1.md"
    # The human did not have to reconstruct any of this from memory --
    # every field the resume path needs came back from one real file.


def test_reading_a_never_persisted_task_is_a_real_none_not_a_crash(tmp_path: Path):
    assert read_persisted_stop(tmp_path, "NEVER-PERSISTED") is None


def test_human_transport_report_never_asks_human_to_decide_next_action():
    report = human_transport_report("T-1", "codex", "HANDOFF_V1.md", "RESULT_V1.md", "import ...")
    assert report["NEXT_ACTION_AFTER_IMPORT"] == "AUTO_RESUME"
    assert report["STOP_REASON"] == "HUMAN_TRANSPORT_REQUIRED"


def test_human_authority_report_carries_a_resume_action_never_a_dead_end():
    report = human_authority_report("DESIGN_AUTHORITY_REQUIRED", "Which schema wins?",
                                    "evidence ref", "blocks GAP-X", "resume after answer")
    assert report["RESUME_ACTION"] == "resume after answer"
    assert report["STOP_REASON"] == "HUMAN_AUTHORITY_REQUIRED"


# --- 7. Reuses model_handoff_workflow's own real state (no second engine) -

def test_signals_from_model_handoff_state_reports_transport_when_waiting(repo: Path):
    h = build_handoff(repo, task_id="T-1", task_type="review-route", target_model="codex",
                      project_id="P", objective="x",
                      scope=TaskBoundary(task_id="T-1", allowed_path_prefixes=("dv_harness/module_a.py",)))
    export_handoff(repo, h)

    signals = signals_from_model_handoff_state(repo, "T-1")
    assert signals.human_transport_required is True
    assert signals.task_id == "T-1"
    assert signals.target_model == "codex"
    assert "HANDOFF_V1.md" in signals.handoff_file
    assert signals.resume_action == "AUTO_RESUME"

    decision = can_i_stop(signals)
    assert decision.status == STATUS_WAITING_FOR_HUMAN_TRANSPORT
    assert decision.stop_reason == "HUMAN_TRANSPORT_REQUIRED"


def test_signals_from_model_handoff_state_defaults_to_caller_supplied_pending_flags_otherwise(repo: Path):
    # No handoff exported for this task_id -> current_state() is None,
    # not WAITING_FOR_HUMAN_TRANSPORT -- the adapter must fall through
    # to the caller-supplied pending-work flags, never fabricate transport.
    signals = signals_from_model_handoff_state(repo, "NEVER-EXPORTED",
                                               required_regression_pending=True)
    assert signals.human_transport_required is False
    assert signals.required_regression_pending is True


# --- 8. Ingestion outcomes persist a machine-actionable NEXT_ACTION (never a
# --- bare "rejected"/"consumed" that waits for someone to schedule the next step)

from dv_harness.execution_contract import event_for_import_outcome, read_next_action  # noqa: E402
from dv_harness.model_handoff_workflow import import_result  # noqa: E402
from dv_harness.model_result import ModelResultV1, to_markdown as _result_md  # noqa: E402


def _exported(repo: Path, task_id: str = "T-1"):
    h = build_handoff(repo, task_id=task_id, task_type="review-route", target_model="codex",
                      project_id="P", objective="x",
                      scope=TaskBoundary(task_id=task_id, allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    export_handoff(repo, h)


def _res(task_id="T-1", **kw) -> ModelResultV1:
    base = dict(result_version="1.0", task_id=task_id, producer_model="codex", task_type="review-route",
                result_status="FAIL", claims=["c"], findings=["f"],
                evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"])
    base.update(kw)
    return ModelResultV1(**base)


def test_consumed_fail_result_persists_auto_remediation_as_next_action(repo: Path):
    _exported(repo)
    rp = repo / "R.md"
    rp.write_text(_result_md(_res()), encoding="utf-8")
    assert import_result(repo, "T-1", rp).consumed
    rec = read_next_action(repo, "T-1")
    assert rec["next_action"] == "AUTO_REMEDIATE_CONFIRMED_FINDINGS"
    assert rec["auto_actionable"] is True and rec["human_action_required"] == "NO"


def test_replay_of_a_consumed_fail_result_keeps_the_same_next_action(repo: Path):
    _exported(repo)
    rp = repo / "R.md"
    rp.write_text(_result_md(_res()), encoding="utf-8")
    import_result(repo, "T-1", rp)
    import_result(repo, "T-1", rp)
    assert read_next_action(repo, "T-1")["next_action"] == "AUTO_REMEDIATE_CONFIRMED_FINDINGS"


def test_scope_rejected_result_persists_an_auto_classification_next_action_not_a_wait(repo: Path):
    _exported(repo)
    rp = repo / "R.md"
    rp.write_text(_result_md(_res(files_referenced=["dv_harness/module_b.py"])), encoding="utf-8")
    assert import_result(repo, "T-1", rp).state == "RESULT_REJECTED"
    rec = read_next_action(repo, "T-1")
    assert rec["next_action"] == "AUTO_CLASSIFY_SCOPE_VIOLATION"
    assert rec["auto_actionable"] is True and rec["stop_reason"] is None
    assert can_i_stop(WorkflowSignals(auto_actionable_pending=rec["auto_actionable"])).should_continue is True


def test_malformed_result_persists_an_auto_correction_request_next_action(repo: Path):
    _exported(repo)
    rp = repo / "R.md"
    rp.write_text("not a result document", encoding="utf-8")
    assert import_result(repo, "T-1", rp).state == "RESULT_REJECTED"
    assert read_next_action(repo, "T-1")["next_action"] == "AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF"


def test_human_decision_result_persists_a_real_authority_stop(repo: Path):
    _exported(repo)
    rp = repo / "R.md"
    rp.write_text(_result_md(_res(result_status="HUMAN_DECISION_REQUIRED", human_decisions_required=["ok?"])),
                  encoding="utf-8")
    import_result(repo, "T-1", rp)
    rec = read_next_action(repo, "T-1")
    assert rec["stop_reason"] == "HUMAN_AUTHORITY_REQUIRED" and rec["human_action_required"] == "YES"


def test_event_mapping_rejects_a_state_with_no_event():
    with pytest.raises(ValueError):
        event_for_import_outcome("RESULT_VALIDATING")
