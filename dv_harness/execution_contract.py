"""dv_harness/execution_contract.py -- the L5DGVA Human Non-Scheduler
Execution Contract as real, runtime-enforced code
(`docs/architecture/canonical_detailed_governance/
L5DGVA_HUMAN_NON_SCHEDULER_EXECUTION_CONTRACT.md`), extending Prime
Directive V2 P6.

`HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES`, `HUMAN_IS_WORKFLOW_SCHEDULER=NO`:
this module is the one real, importable place that decides whether
autonomous execution may continue or must stop, so that invariant is
enforced by code a test can call, not merely stated in prose. It reuses
`dv_harness/model_handoff_workflow.py`'s own real state machine and
`dv_harness/result_action_router.py`'s own action classification --
`signals_from_model_handoff_state()` TRANSLATES their real state into
this module's canonical vocabulary; it never shadows, re-implements, or
competes with either as a second state/lifecycle authority.

Five canonical stop reasons only (`CANONICAL_STOP_REASONS`); a long list
of generic-sounding stop strings is explicitly REJECTED
(`INVALID_GENERIC_STOP_REASONS`) by `validate_stop_reason()`, which every
real stop path in `can_i_stop()` runs through -- a caller cannot persist
"waiting for review" as if it were a real stop reason even by accident.

`canonical_task_complete` is always a caller-asserted fact, never
inferred from "no known pending work" -- the Can-I-Stop Gate's own final
`ELSE: CONTINUE` fallback means the safe default, when completeness has
not been independently established, is to keep going, not to stop.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .task_boundary_conformance import TaskBoundary

# --- Canonical vocabulary --------------------------------------------------

CANONICAL_STOP_REASONS = (
    "HUMAN_AUTHORITY_REQUIRED",
    "HUMAN_TRANSPORT_REQUIRED",
    "SAFE_EXECUTION_BLOCKED",
    "TERMINATION_POLICY_TRIGGERED",
    "TASK_COMPLETE",
)

#: Named generic stops the contract explicitly forbids treating as a real
#: stop reason by themselves (dispatch section 5 / requirements doc
#: "Invalid Generic Stops"). Subtask/cohort/import/fix/test/regression/
#: report completion is real progress, not a licence to stop.
INVALID_GENERIC_STOP_REASONS = (
    "WAITING_FOR_USER_TO_CONTINUE",
    "WAITING_FOR_USER_TO_IMPORT",
    "WAITING_FOR_GENERIC_REVIEW",
    "WAITING_FOR_GENERIC_APPROVAL",
    "ASK_USER_IF_SHOULD_FIX",
    "ASK_USER_IF_SHOULD_TEST",
    "ASK_USER_IF_SHOULD_RERUN",
    "ASK_USER_IF_SHOULD_PROCEED",
    "COHORT_COMPLETED",
    "SUBTASK_COMPLETED",
    "RESULT_IMPORTED",
    "RESULT_CONSUMED",
    "FIX_COMPLETED",
    "TEST_COMPLETED",
    "REGRESSION_COMPLETED",
    "REPORT_COMPLETED",
)

STATUS_AUTO_RUNNING = "AUTO_RUNNING"
STATUS_WAITING_FOR_HUMAN_TRANSPORT = "WAITING_FOR_HUMAN_TRANSPORT"
STATUS_WAITING_FOR_HUMAN_AUTHORITY = "WAITING_FOR_HUMAN_AUTHORITY"
STATUS_BLOCKED = "BLOCKED"
STATUS_COMPLETE = "COMPLETE"

STATUS_VALUES = (
    STATUS_AUTO_RUNNING, STATUS_WAITING_FOR_HUMAN_TRANSPORT,
    STATUS_WAITING_FOR_HUMAN_AUTHORITY, STATUS_BLOCKED, STATUS_COMPLETE,
)


class InvalidStopReasonError(ValueError):
    def __init__(self, reason: str):
        super().__init__(f"INVALID_STOP_REASON:{reason}")
        self.reason = reason


def validate_stop_reason(reason: str) -> None:
    """Raises `InvalidStopReasonError` for any of the named generic
    stops, or for any string that is not one of the 5 canonical
    reasons. Every real stop path in `can_i_stop()` runs through this --
    it is not merely advisory."""
    if reason in INVALID_GENERIC_STOP_REASONS:
        raise InvalidStopReasonError(reason)
    if reason not in CANONICAL_STOP_REASONS:
        raise InvalidStopReasonError(reason)


# --- Workflow signals (real, caller-supplied facts) -------------------------

@dataclass(frozen=True)
class WorkflowSignals:
    """Real, caller-supplied facts about the current task's pending
    work -- never inferred by this module. A caller (e.g. an adapter
    reading model_handoff_workflow's own state, or a remediation loop
    tracking result_action_router's own ACTION_* classifications) is
    responsible for setting each field from real evidence."""
    human_authority_required: bool = False
    human_transport_required: bool = False
    safe_execution_blocked: bool = False
    termination_policy_triggered: bool = False
    auto_actionable_pending: bool = False
    required_remediation_pending: bool = False
    required_verification_pending: bool = False
    required_regression_pending: bool = False
    required_rereview_preparation_pending: bool = False
    #: Never inferred from "no known pending work" -- only True when a
    #: caller has independently established real Canonical completion.
    canonical_task_complete: bool = False

    stop_evidence: str = ""
    next_required_action: str = ""
    resume_action: str = ""

    # Human Transport Gate detail (dispatch section 10)
    task_id: Optional[str] = None
    target_model: Optional[str] = None
    handoff_file: Optional[str] = None
    expected_result_file: Optional[str] = None
    import_command: Optional[str] = None

    # Human Authority Gate detail (dispatch section 11)
    authority_type: Optional[str] = None
    question: Optional[str] = None
    options: Sequence[str] = ()
    evidence: Optional[str] = None
    impact: Optional[str] = None


@dataclass(frozen=True)
class StopDecision:
    should_continue: bool
    status: str
    stop_reason: Optional[str] = None
    stop_evidence: str = ""
    next_required_action: str = ""
    human_action_required: str = "NO"
    resume_action: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUS_VALUES:
            raise ValueError(f"INVALID_STATUS:{self.status}")
        if self.stop_reason is not None:
            validate_stop_reason(self.stop_reason)
        if self.should_continue and self.stop_reason is not None:
            raise ValueError("CONTINUE_DECISION_MUST_NOT_CARRY_A_STOP_REASON")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "STATE": self.status,
            "STOP_REASON": self.stop_reason,
            "STOP_EVIDENCE": self.stop_evidence,
            "NEXT_REQUIRED_ACTION": self.next_required_action,
            "HUMAN_ACTION_REQUIRED": self.human_action_required,
            "RESUME_ACTION": self.resume_action,
        }


#: TASK_COMPLETE needs nothing further from anyone -- unlike the other 4
#: canonical stop reasons, it never sets HUMAN_ACTION_REQUIRED=YES (a real
#: defect found and fixed this task: a completed REVIEW-003 task was
#: reporting HUMAN_ACTION_REQUIRED=YES in status_report()).
_NO_HUMAN_ACTION_REASONS = frozenset({"TASK_COMPLETE"})


def _stop(signals: WorkflowSignals, status: str, reason: str) -> StopDecision:
    return StopDecision(
        should_continue=False, status=status, stop_reason=reason,
        stop_evidence=signals.stop_evidence,
        next_required_action=signals.next_required_action,
        human_action_required=("NO" if reason in _NO_HUMAN_ACTION_REASONS else "YES"),
        resume_action=signals.resume_action,
    )


def can_i_stop(signals: WorkflowSignals) -> StopDecision:
    """The real Can-I-Stop Gate -- the exact decision order both the
    requirements doc and the integration prompt specify, run against
    real `WorkflowSignals`, never prose heuristics. `AUTO_RUNNING` always
    carries `HUMAN_ACTION_REQUIRED=NO` (`test_auto_actionable_result_
    does_not_stop_for_user` and siblings check this directly)."""
    if signals.human_authority_required:
        return _stop(signals, STATUS_WAITING_FOR_HUMAN_AUTHORITY, "HUMAN_AUTHORITY_REQUIRED")
    if signals.human_transport_required:
        return _stop(signals, STATUS_WAITING_FOR_HUMAN_TRANSPORT, "HUMAN_TRANSPORT_REQUIRED")
    if signals.safe_execution_blocked:
        return _stop(signals, STATUS_BLOCKED, "SAFE_EXECUTION_BLOCKED")
    if signals.termination_policy_triggered:
        return _stop(signals, STATUS_BLOCKED, "TERMINATION_POLICY_TRIGGERED")
    if (signals.auto_actionable_pending or signals.required_remediation_pending
            or signals.required_verification_pending or signals.required_regression_pending
            or signals.required_rereview_preparation_pending):
        return StopDecision(True, STATUS_AUTO_RUNNING, None, "",
                            signals.next_required_action, "NO", "")
    if signals.canonical_task_complete:
        return _stop(signals, STATUS_COMPLETE, "TASK_COMPLETE")
    return StopDecision(True, STATUS_AUTO_RUNNING, None, "",
                        signals.next_required_action, "NO", "")


# --- Gate reports (dispatch sections 10/11) --------------------------------

def human_transport_report(task_id: str, target_model: str, handoff_file: str,
                            expected_result_file: str,
                            result_watcher: str = "ACTIVE_OR_RECOVERABLE") -> Dict[str, str]:
    """Exact required report (Automatic External Result Ingestion contract).
    The human ONLY transports the artifact across a boundary L5DGVA cannot
    cross itself: no import command, no "continue", no next-action choice is
    part of the report. Once RESULT_V1 appears at EXPECTED_RESULT_FILE,
    L5DGVA detects, imports, validates, consumes/rejects and resumes."""
    return {
        "STATE": STATUS_WAITING_FOR_HUMAN_TRANSPORT,
        "STOP_REASON": "HUMAN_TRANSPORT_REQUIRED",
        "TASK_ID": task_id,
        "TARGET_MODEL": target_model,
        "HANDOFF_FILE": handoff_file,
        "EXPECTED_RESULT_FILE": expected_result_file,
        "HUMAN_ACTION_REQUIRED": "Transport HANDOFF and ensure returned RESULT_V1 is placed at EXPECTED_RESULT_FILE",
        "RESULT_WATCHER": result_watcher,
        "AUTO_IMPORT": "ENABLED",
        "AUTO_RESUME": "ENABLED",
    }


def human_authority_report(authority_type: str, question: str, evidence: str, impact: str,
                            resume_action: str, options: Sequence[str] = ()) -> Dict[str, Any]:
    return {
        "STATE": STATUS_WAITING_FOR_HUMAN_AUTHORITY,
        "STOP_REASON": "HUMAN_AUTHORITY_REQUIRED",
        "AUTHORITY_TYPE": authority_type,
        "QUESTION": question,
        "OPTIONS": list(options),
        "EVIDENCE": evidence,
        "IMPACT": impact,
        "RESUME_ACTION": resume_action,
    }


# --- Next Action Resolver (dispatch section 8, provider-independent) ------

#: The exact worked examples both the requirements doc and the
#: integration prompt name. Provider-independent: keyed only by an
#: abstract event name, never by which model/tool produced the event.
NEXT_ACTION_TABLE: Dict[str, str] = {
    "RESULT_CONSUMED": "AUTO_REMEDIATE_CONFIRMED_FINDINGS",
    "RESULT_CONSUMED_CLEAN": "EVALUATE_CANONICAL_TASK_COMPLETION",
    "RESULT_CONSUMED_HUMAN_DECISION": "HUMAN_AUTHORITY_REQUIRED",
    # A REJECTED result is never a stop waiting for someone to schedule the
    # next step: the cause determines a machine-actionable next action.
    "RESULT_REJECTED_SCOPE_VIOLATION": "AUTO_CLASSIFY_SCOPE_VIOLATION",
    "RESULT_REJECTED_VALIDATION": "AUTO_DIAGNOSE_VALIDATION_FAILURE",
    "RESULT_REJECTED_MALFORMED": "AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF",
    # An exception part-way through consumption leaves an inspectable partial state;
    # the machine-actionable next step is the idempotent retry, never a wait.
    "IMPORT_INTERRUPTED": "AUTO_RETRY_INTERRUPTED_IMPORT",
    "FIX_COMPLETE": "RUN_FOCUSED_VALIDATION",
    "VALIDATION_PASS": "RUN_REQUIRED_REGRESSION",
    "REGRESSION_PASS": "PREPARE_REQUIRED_RE_REVIEW",
    "RE_REVIEW_HANDOFF_READY": "HUMAN_TRANSPORT_REQUIRED",

    # Autonomous Agent Execution Backend events (a real Claude worker run's
    # own outcome, never a second Next Action Resolver -- same table).
    "AGENT_RUN_SUCCEEDED": "PREPARE_REQUIRED_RE_REVIEW",
    "AGENT_RUN_FAILED_RETRY_ELIGIBLE": "AUTO_RETRY_AGENT_RUN",
    "AGENT_RUN_FAILED_ESCALATE": "HUMAN_AUTHORITY_REQUIRED",
    "AGENT_RUN_HUMAN_DECISION_REQUIRED": "HUMAN_AUTHORITY_REQUIRED",
    "AGENT_RUN_TIMEOUT_RETRY_ELIGIBLE": "AUTO_RETRY_AGENT_RUN",
    "AGENT_RUN_TIMEOUT_ESCALATE": "HUMAN_AUTHORITY_REQUIRED",
}

#: Next actions that are themselves one of the canonical stop reasons.
_STOP_ACTIONS = ("HUMAN_TRANSPORT_REQUIRED", "HUMAN_AUTHORITY_REQUIRED")


@dataclass(frozen=True)
class NextActionRecord:
    event: str
    next_action: str
    next_action_reason: str
    next_action_owner: str
    auto_actionable: bool
    human_action_required: str
    stop_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def resolve_next_action(event: str) -> NextActionRecord:
    """Real, table-driven resolution -- an unrecognized event is a real
    `ValueError`, never a silently-guessed default next action."""
    if event not in NEXT_ACTION_TABLE:
        raise ValueError(f"UNKNOWN_EVENT:{event}")
    next_action = NEXT_ACTION_TABLE[event]
    is_stop = next_action in _STOP_ACTIONS
    return NextActionRecord(
        event=event,
        next_action=next_action,
        next_action_reason=f"provider-independent routing table: {event} -> {next_action}",
        next_action_owner="HUMAN" if is_stop else "L5DGVA",
        auto_actionable=not is_stop,
        human_action_required="YES" if is_stop else "NO",
        stop_reason=next_action if is_stop else None,
    )


def classify_scope_violation(validation: Any) -> Dict[str, Any]:
    """`AUTO_CLASSIFY_SCOPE_VIOLATION`'s real executor -- ChatGPT REVIEW-001
    (M7-V1-CHATGPT-ARCHITECTURE-REVIEW-001) CG-1 found this action had no
    production executor anywhere in the codebase. Purely mechanical:
    `ValidationOutcome.scope_violations` is ALREADY a real, structured list
    (`{"field", "path", "classification"}` per violation), computed by
    `model_result.py`'s own `validate_result()` -- this function formats it
    as the action's real, callable output. No new judgment is added; a
    caller with a real `RESULT_REJECTED_SCOPE_VIOLATION` outcome in hand
    calls this immediately with its own `.validation`."""
    violations = list(getattr(validation, "scope_violations", None) or [])
    return {
        "classification": "SCOPE_VIOLATION" if violations else "NO_SCOPE_VIOLATION",
        "violation_count": len(violations),
        "violations": violations,
    }


def diagnose_validation_failure(validation: Any) -> Dict[str, Any]:
    """`AUTO_DIAGNOSE_VALIDATION_FAILURE`'s real executor -- same reasoning
    as `classify_scope_violation()` above: `ValidationOutcome`'s own
    per-check booleans and `findings` are already real, computed facts;
    this function structures WHICH checks failed, adding no new
    judgment."""
    checks = {
        "task_id_validated": bool(getattr(validation, "task_id_validated", True)),
        "producer_validated": bool(getattr(validation, "producer_validated", True)),
        "task_type_validated": bool(getattr(validation, "task_type_validated", True)),
        "scope_validated": bool(getattr(validation, "scope_validated", True)),
        "schema_validated": bool(getattr(validation, "schema_validated", True)),
        "evidence_validated": bool(getattr(validation, "evidence_validated", True)),
        "governance_validated": bool(getattr(validation, "governance_validated", True)),
    }
    failed_checks = [name for name, ok in checks.items() if not ok]
    return {
        "failed_checks": failed_checks,
        "findings": list(getattr(validation, "findings", None) or []),
        "governance_validation_status": getattr(validation, "governance_validation_status", "NOT_APPLICABLE"),
    }


# --- Action Dispatcher (ChatGPT REVIEW-001 CG-1/CG-2 gap-close) -------------
# NEXT_ACTION_TABLE resolves and persists an action, but nothing in
# production code actually consumed next_action.json and routed to a real
# executor -- confirmed live: M7-V1-CHATGPT-ARCHITECTURE-REVIEW-001 itself
# consumed with next_action=AUTO_REMEDIATE_CONFIRMED_FINDINGS and NO
# downstream execution occurred. This is the real, minimal Action
# Dispatcher -- never a second orchestration engine: for actions with a
# real, callable executor it invokes them directly; for actions requiring
# code-authorship/test-running judgment it resolves the EXECUTION BACKEND
# (agent_execution_backend.resolve_execution_backend()'s first genuine
# production call site -- CG-2's own specific finding) rather than
# performing that judgment itself.

#: Actions this dispatcher can invoke directly from persisted state alone
#: (root + task_id) -- their real executor needs no additional
#: caller-supplied context.
_DISPATCH_STATE_ONLY_EXECUTORS = (
    "EVALUATE_CANONICAL_TASK_COMPLETION",
    "AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF",
)

#: Actions that inherently require code-authorship or test-running
#: judgment -- this dispatcher never performs these itself (that would be
#: a second, competing autonomous code-fixing engine). It resolves the
#: real execution backend for them instead.
_DISPATCH_CURRENT_SESSION_EXECUTOR_ACTIONS = (
    "AUTO_REMEDIATE_CONFIRMED_FINDINGS", "RUN_FOCUSED_VALIDATION",
    "RUN_REQUIRED_REGRESSION", "PREPARE_REQUIRED_RE_REVIEW",
)

DISPATCH_EXECUTED = "EXECUTED"
DISPATCH_BACKEND_RESOLVED = "BACKEND_RESOLVED"
DISPATCH_REQUIRES_CALLER_CONTEXT = "REQUIRES_CALLER_CONTEXT"
DISPATCH_GATE = "GATE"


@dataclass(frozen=True)
class DispatchOutcome:
    task_id: str
    next_action: str
    dispatch_status: str
    detail: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"task_id": self.task_id, "next_action": self.next_action,
                "dispatch_status": self.dispatch_status, "detail": self.detail}


def dispatch_next_action(root: Path, task_id: str) -> DispatchOutcome:
    """Reads the real persisted next-action record for `task_id` and
    routes it: a `_DISPATCH_STATE_ONLY_EXECUTORS` action is invoked
    directly, its real output persisted where that executor already
    persists it. A `_DISPATCH_CURRENT_SESSION_EXECUTOR_ACTIONS` action
    resolves the real execution backend and reports the result -- never
    silently represented as executed. A real gate
    (`HUMAN_AUTHORITY_REQUIRED`/`HUMAN_TRANSPORT_REQUIRED`/etc.) is
    reported as a gate. Anything else (an action needing caller-supplied
    context this function cannot derive from persisted state alone, e.g.
    `AUTO_CLASSIFY_SCOPE_VIOLATION`, which needs the real `ValidationOutcome`
    only the ingestion call site has in hand) is reported honestly as
    `REQUIRES_CALLER_CONTEXT`, never silently skipped or claimed done."""
    root = Path(root)
    record = read_next_action(root, task_id)
    if record is None:
        raise ValueError(f"NO_PERSISTED_NEXT_ACTION:{task_id}")
    action = record["next_action"]

    if action in CANONICAL_STOP_REASONS:
        return DispatchOutcome(task_id, action, DISPATCH_GATE, {"stop_reason": action})

    if action == "EVALUATE_CANONICAL_TASK_COMPLETION":
        evaluation = evaluate_canonical_task_completion(root, task_id)
        persist_completion_evaluation(root, task_id, evaluation)
        # Close THIS action's own loop automatically -- the real gap found
        # live for M7-V1-CODEX-REVIEW-007 (this action's own output was
        # persisted, but its next_action.json was left stale, indistinguishable
        # from "never executed"). Never left to a manual follow-up call again.
        record_completion_evaluation_next_action(root, task_id, evaluation)
        return DispatchOutcome(task_id, action, DISPATCH_EXECUTED, evaluation.to_dict())

    if action == "AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF":
        from . import model_handoff_workflow as _wf
        from .model_handoff import HandoffBuildError
        try:
            correction = _wf.build_correction_request_handoff(root, task_id)
        except HandoffBuildError as exc:
            if exc.reason == "NOT_REJECTED":
                # Idempotency: a duplicate dispatch (e.g. a repeated watcher
                # poll/resume) after this action already ran once -- the task
                # has already moved on (export_handoff() transitions it to
                # WAITING_FOR_HUMAN_TRANSPORT). Never a second correction
                # handoff, never an unhandled exception surfacing to the caller.
                return DispatchOutcome(task_id, action, DISPATCH_EXECUTED,
                                      {"already_dispatched": True, "current_state": _wf.current_state(root, task_id)})
            raise
        path = _wf.export_handoff(root, correction)
        # Close THIS action's own loop automatically -- the same class of gap
        # found live for EVALUATE_CANONICAL_TASK_COMPLETION above: the source
        # task's own next_action.json was otherwise left showing the
        # pre-dispatch AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF/
        # auto_actionable=true record forever, indistinguishable from "never
        # executed" to any reader of that one file (confirmed live against
        # the real M7-V1-CHATGPT-ARCHITECTURE-REVIEW-002 state: state.json
        # correctly advanced to WAITING_FOR_HUMAN_TRANSPORT but next_action.json
        # did not). export_handoff() already transitioned the real workflow
        # state to WAITING_FOR_HUMAN_TRANSPORT -- this only makes that outcome
        # legible from next_action.json too, it never re-decides anything.
        persist_next_action(root, task_id, NextActionRecord(
            event="AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF",
            next_action="EXECUTED:WAITING_FOR_HUMAN_TRANSPORT",
            next_action_reason=(
                f"correction request handoff exported to {path}; real workflow state "
                "advanced to WAITING_FOR_HUMAN_TRANSPORT via export_handoff()"
            ),
            next_action_owner="HUMAN",
            auto_actionable=False,
            human_action_required="YES",
            stop_reason="HUMAN_TRANSPORT_REQUIRED",
        ))
        return DispatchOutcome(task_id, action, DISPATCH_EXECUTED, {"handoff_path": str(path)})

    if action in _DISPATCH_CURRENT_SESSION_EXECUTOR_ACTIONS:
        from . import agent_execution_backend as _aeb
        resolution = _aeb.resolve_execution_backend(
            same_task=True, same_scope=True, equivalent_task_boundary=True,
            equivalent_safe_tool_profile=True, equivalent_evidence_contract=True,
            human_authority_decision_required=False,
        )
        detail = resolution.to_dict()
        # CURRENT_SESSION_EXECUTOR activation gap-close: BACKEND_RESOLVED
        # alone gave no production mechanism for a /loop wakeup to
        # discover, claim and execute the work -- only a human manually
        # reading this report and doing it by hand. When the fallback is
        # genuinely authorized, a real, persisted, claimable Canonical
        # assignment is created here (never executed here -- see
        # create_execution_assignment()'s own docstring for why
        # BACKEND_RESOLVED still != EXECUTED).
        if resolution.selected_backend == _aeb.CURRENT_SESSION_EXECUTOR and resolution.fallback_authorized:
            assignment = create_execution_assignment(root, task_id, action)
            detail["assignment_id"] = assignment.assignment_id
            detail["claim_state"] = assignment.claim_state
        return DispatchOutcome(task_id, action, DISPATCH_BACKEND_RESOLVED, detail)

    return DispatchOutcome(task_id, action, DISPATCH_REQUIRES_CALLER_CONTEXT, {
        "reason": "this action needs real caller-supplied context (e.g. a ValidationOutcome or "
                  "AgentRunRequest) not derivable from persisted next_action state alone",
    })


# --- Current-Session Execution Assignment (CURRENT_SESSION_EXECUTOR activation gap-close) ---
#
# The real live gap ChatGPT's own REVIEW-002 re-review (M7-V1-CHATGPT-
# ARCHITECTURE-REVIEW-002, third corrected result, RESULT_SHA256=
# d681587f...) exposed: dispatch_next_action() correctly reports
# BACKEND_RESOLVED/CURRENT_SESSION_EXECUTOR for a code-authorship action,
# but nothing let a /loop wakeup -- a genuinely separate, timer-fired
# invocation, not a human typing continue -- discover that assignment and
# claim it. This closes that gap the SAME way the two prior production-
# caller gaps were closed: a real, persisted, atomically-claimable
# Canonical record, never a second scheduler and never terminal/keystroke
# injection of any kind.
#
# Reuses, never reinvents: `agent_execution_backend.AgentRunRequest`/
# `build_agent_run_request()` (the work-order shape), `agent_execution_
# backend.acquire_mutation_lease()`/`release_mutation_lease()` (the SAME
# SINGLE_CANONICAL_MUTATION_LEASE a detached worker run already holds --
# so a current-session claim and a detached worker can never both mutate
# the repo at once), `model_handoff_workflow._acquire_lock()`/
# `_release_lock()` (the claim race's own atomicity primitive, the exact
# one `result_ingestion._task_lock()`/the watcher role lock already
# reuse), and `agent_execution_backend.AgentRunResult`'s own shape for the
# persisted execution outcome (never a second result schema).
#
# IMPORTANT: a finding in a consumed RESULT_V1.md is PRIOR CLAIM, never
# CURRENT EVIDENCE (the Evidence Truth Rule this entire program is built
# on). REVIEW-002's own real CG2-1/CG2-2 findings ("no production caller
# of dispatch_next_action is established") were independently re-verified
# against current evidence before this module was written and found to be
# STALE: `git show 6083ae6:dv_harness/result_ingestion.py` already
# contained the real `_ec.dispatch_next_action(root, task_id)` call inside
# `resume_after_import()` at that exact CURRENT_HEAD -- the finding is an
# artifact of an incomplete INPUT_EVIDENCE_REFS list (result_ingestion.py
# was never included), not a real current code gap. `_build_remediation_
# objective()` below therefore REQUIRES independent re-verification of
# every finding against current evidence before any change is made -- a
# claiming session must never blindly implement a stale claim.

ASSIGNMENT_READY = "ASSIGNMENT_READY"
ASSIGNMENT_CLAIMED = "ASSIGNMENT_CLAIMED"
ASSIGNMENT_EXECUTING = "EXECUTING"
ASSIGNMENT_EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
ASSIGNMENT_EXECUTION_FAILED = "EXECUTION_FAILED"


class ExecutionAssignmentError(ValueError):
    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


@dataclass(frozen=True)
class ExecutionAssignment:
    assignment_id: str
    task_id: str
    action_id: str
    next_action: str
    selected_backend: str
    repo_root_identity: str
    repo_root_matched: bool
    source_head_at_creation: str
    runtime_generation_at_creation: Optional[int]
    claim_state: str
    created_at: str
    agent_run_request: Dict[str, Any]
    claimed_at: Optional[str] = None
    claimed_by: Optional[str] = None
    lease_id: Optional[str] = None
    execution_outcome: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assignment_path(root: Path, task_id: str) -> Path:
    from . import model_handoff_workflow as _wf
    return _wf._task_dir(Path(root), task_id) / "execution_assignment.json"


def _assignment_lock_path(root: Path, task_id: str) -> Path:
    return _assignment_path(root, task_id).with_name("execution_assignment.lock")


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _current_watcher_generation(root: Path) -> Optional[int]:
    """Best-effort: the result watcher's own current `runtime_generation`,
    if a watcher heartbeat file exists at all. `None` when no watcher has
    ever run in this repo -- not itself an error."""
    from . import result_ingestion as _ri
    rec = _ri._read_json(_ri._watcher_file(Path(root)))
    return rec.get("runtime_generation") if rec else None


def _build_remediation_objective(root: Path, task_id: str, action: str) -> Sequence[str]:
    """The real objective text for a CURRENT_SESSION_EXECUTOR assignment,
    derived from the task's own real, consumed RESULT_V1.md when one
    exists -- never invented findings. Every FINDINGS/RECOMMENDED_ACTIONS
    line is quoted verbatim so a claiming session works from the real
    claim text, but is explicitly instructed to re-verify each one against
    CURRENT evidence before changing anything (see this section's own
    module-level docstring for the real, confirmed-stale CG2-1/CG2-2
    precedent this instruction exists because of)."""
    from . import model_handoff_workflow as _wf
    result_path = _wf._task_dir(root, task_id) / "RESULT_V1.md"
    findings: Sequence[str] = ()
    recommended: Sequence[str] = ()
    if action == "AUTO_REMEDIATE_CONFIRMED_FINDINGS" and result_path.is_file():
        try:
            from . import model_result as _result_mod
            result = _result_mod.from_markdown(result_path.read_text(encoding="utf-8"))
            findings = result.findings
            recommended = result.recommended_actions
        except Exception:
            pass
    lines = [
        f"CURRENT_SESSION_EXECUTOR assignment for {task_id}, action={action}.",
        "MANDATORY FIRST STEP: independently re-verify EVERY finding below against the CURRENT "
        "codebase before making any change -- a finding is a prior claim, never current evidence. "
        "A finding that does not reproduce against current evidence (already fixed, evidence "
        "incomplete when it was made, or otherwise stale) must be reported as NOT_REPRODUCIBLE with "
        "the exact current evidence that shows so -- never blindly implemented. Only a finding that "
        "genuinely reproduces against current evidence gets a real code fix, with tests and a commit.",
    ]
    if findings:
        lines.append("FINDINGS (verbatim from the real consumed result):")
        lines.extend(f"- {f}" for f in findings)
    if recommended:
        lines.append("RECOMMENDED_ACTIONS (verbatim from the real consumed result):")
        lines.extend(f"- {r}" for r in recommended)
    return lines


def create_execution_assignment(root: Path, task_id: str, action: str) -> ExecutionAssignment:
    """The real, persisted, claimable Canonical work order a CURRENT_
    SESSION_EXECUTOR backend resolution creates. BACKEND_RESOLVED still
    != EXECUTED: this only makes the resolved work order discoverable and
    claimable -- it never performs the code-authorship work itself (that
    would be a second, competing autonomous code-fixing engine, exactly
    what `dispatch_next_action()`'s own docstring already forbids)."""
    from . import agent_execution_backend as _aeb
    from . import controlled_process_executor as _cpe
    from . import model_handoff_workflow as _wf
    root = Path(root)
    identity = _cpe.verify_canonical_repository_identity(root)
    handoff = _wf._load_handoff(root, task_id)
    scope = handoff.scope if handoff is not None else TaskBoundary(task_id=task_id, allowed_path_prefixes=())
    evidence_refs = handoff.input_evidence_refs if handoff is not None else ()
    objective = "\n".join(_build_remediation_objective(root, task_id, action))
    request = _aeb.build_agent_run_request(
        root, task_id=task_id, parent_workflow_id=task_id, action_id=f"A:{task_id}:{action}",
        action_type=action, role="implementation", objective=objective, scope=scope,
        input_evidence_refs=evidence_refs, expected_output="code fix + tests + regression evidence, "
        "or a NOT_REPRODUCIBLE report with current evidence",
    )
    assignment = ExecutionAssignment(
        assignment_id=str(uuid.uuid4()), task_id=task_id, action_id=request.action_id, next_action=action,
        selected_backend=_aeb.CURRENT_SESSION_EXECUTOR, repo_root_identity=identity.resolved_root,
        repo_root_matched=identity.matched, source_head_at_creation=identity.head or "",
        runtime_generation_at_creation=_current_watcher_generation(root),
        claim_state=ASSIGNMENT_READY, created_at=_now_iso(), agent_run_request=request.to_dict(),
    )
    _atomic_write_json(_assignment_path(root, task_id), assignment.to_dict())
    return assignment


def read_execution_assignment(root: Path, task_id: str) -> Optional[ExecutionAssignment]:
    rec = _read_json(_assignment_path(Path(root), task_id))
    return ExecutionAssignment(**rec) if rec else None


def discover_eligible_current_session_assignments(root: Path) -> List[ExecutionAssignment]:
    """What a /loop wakeup calls to inspect the Canonical assignment
    queue/state -- read-only, never claims anything itself. A Human
    Authority/Transport gate task never appears here: an assignment is
    only ever created inside `dispatch_next_action()`'s CURRENT_SESSION_
    EXECUTOR branch, a code path a gate action (`DISPATCH_GATE`) never
    reaches at all."""
    from . import result_ingestion as _ri
    root = Path(root)
    out = []
    for t in _ri._registered_task_ids(root):
        a = read_execution_assignment(root, t)
        if a is not None and a.claim_state == ASSIGNMENT_READY:
            out.append(a)
    return out


def claim_execution_assignment(root: Path, task_id: str, claimant_id: str) -> ExecutionAssignment:
    """Atomic claim: at-most-one active claimant. Reuses `model_handoff_
    workflow._acquire_lock()`'s O_EXCL primitive for the claim race itself,
    AND `agent_execution_backend.acquire_mutation_lease()` -- the SAME
    Canonical Mutation Lease a detached worker run already holds -- so a
    current-session claim and a detached worker can never both mutate the
    repo at once. Fails closed on: assignment not found; not READY
    (already claimed/executing/done -- no double-claim); repo identity no
    longer matches (a wrong-repo claim, e.g. a nested throwaway probe
    dir); or a STALE runtime generation (the watcher has restarted --
    meaning the control plane may have changed -- since this assignment
    was created; the caller must let a fresh `resume_after_import()`
    re-create a current assignment rather than act on a possibly-outdated
    one)."""
    from . import agent_execution_backend as _aeb
    from . import controlled_process_executor as _cpe
    from . import model_handoff_workflow as _wf
    root = Path(root)
    lock = _assignment_lock_path(root, task_id)
    token = _wf._acquire_lock(lock, 60.0)
    if token is None:
        raise ExecutionAssignmentError("CLAIM_IN_PROGRESS", {"task_id": task_id})
    try:
        assignment = read_execution_assignment(root, task_id)
        if assignment is None:
            raise ExecutionAssignmentError("NOT_FOUND", {"task_id": task_id})
        if assignment.claim_state != ASSIGNMENT_READY:
            raise ExecutionAssignmentError("NOT_READY", {"task_id": task_id, "claim_state": assignment.claim_state})
        identity = _cpe.verify_canonical_repository_identity(root)
        if not identity.matched or identity.resolved_root != assignment.repo_root_identity:
            raise ExecutionAssignmentError("REPO_IDENTITY_MISMATCH", {
                "task_id": task_id, "assignment_repo": assignment.repo_root_identity,
                "current_repo": identity.resolved_root})
        current_gen = _current_watcher_generation(root)
        if (assignment.runtime_generation_at_creation is not None and current_gen is not None
                and current_gen > assignment.runtime_generation_at_creation):
            raise ExecutionAssignmentError("STALE_RUNTIME_GENERATION", {
                "task_id": task_id, "assignment_generation": assignment.runtime_generation_at_creation,
                "current_generation": current_gen})
        lease = _aeb.acquire_mutation_lease(root, task_id, assignment.agent_run_request["agent_run_id"])
        if not lease.acquired:
            raise ExecutionAssignmentError("MUTATION_LEASE_BUSY",
                                          {"task_id": task_id, "owner": lease.owner_agent_run_id})
        claimed = ExecutionAssignment(**{**assignment.to_dict(), "claim_state": ASSIGNMENT_CLAIMED,
                                        "claimed_at": _now_iso(), "claimed_by": claimant_id,
                                        "lease_id": lease.lease_id})
        _atomic_write_json(_assignment_path(root, task_id), claimed.to_dict())
        return claimed
    finally:
        _wf._release_lock(lock, token)


def loop_wakeup_check_and_claim(root: Path, claimant_id: str) -> Optional[ExecutionAssignment]:
    """The single entry point a normal /loop wakeup calls (never terminal
    injection, never SendKeys, never clipboard automation -- purely
    Canonical-state-based, per this dispatch's own explicit prohibition):
    discovers eligible CURRENT_SESSION_EXECUTOR assignments and claims the
    first one atomically. Returns `None` -- remains quiet, no side effect
    at all -- when nothing is eligible, so a wakeup with no assigned work
    never invents any."""
    root = Path(root)
    eligible = discover_eligible_current_session_assignments(root)
    if not eligible:
        return None
    return claim_execution_assignment(root, eligible[0].task_id, claimant_id)


def mark_execution_assignment_executing(root: Path, task_id: str) -> ExecutionAssignment:
    root = Path(root)
    assignment = read_execution_assignment(root, task_id)
    if assignment is None or assignment.claim_state != ASSIGNMENT_CLAIMED:
        raise ExecutionAssignmentError("NOT_CLAIMED", {"task_id": task_id})
    updated = ExecutionAssignment(**{**assignment.to_dict(), "claim_state": ASSIGNMENT_EXECUTING})
    _atomic_write_json(_assignment_path(root, task_id), updated.to_dict())
    return updated


def complete_execution_assignment(root: Path, task_id: str, outcome: Dict[str, Any], *,
                                  success: bool) -> ExecutionAssignment:
    """Persists the real execution outcome (an `agent_execution_backend.
    AgentRunResult`-shaped dict -- the SAME shape a detached worker run
    produces, never a second result schema), releases the Canonical
    Mutation Lease this claim was holding, and closes the Canonical
    next-action loop (the same OUTPUT_UNCONSUMED class of gap already
    closed for `EVALUATE_CANONICAL_TASK_COMPLETION`/`AUTO_GENERATE_
    CORRECTION_REQUEST_HANDOFF` -- never left for a manual follow-up
    call)."""
    from . import agent_execution_backend as _aeb
    root = Path(root)
    assignment = read_execution_assignment(root, task_id)
    if assignment is None or assignment.claim_state not in (ASSIGNMENT_CLAIMED, ASSIGNMENT_EXECUTING):
        raise ExecutionAssignmentError("NOT_CLAIMED", {"task_id": task_id})
    if assignment.lease_id:
        _aeb.release_mutation_lease(root, assignment.lease_id)
    final_state = ASSIGNMENT_EXECUTION_COMPLETED if success else ASSIGNMENT_EXECUTION_FAILED
    updated = ExecutionAssignment(**{**assignment.to_dict(), "claim_state": final_state,
                                    "execution_outcome": outcome})
    _atomic_write_json(_assignment_path(root, task_id), updated.to_dict())
    persist_next_action(root, task_id, NextActionRecord(
        event=assignment.next_action,
        next_action=f"EXECUTED:{final_state}",
        next_action_reason=(f"current-session execution {final_state.lower()}; outcome persisted to "
                            "execution_assignment.json"),
        next_action_owner="L5DGVA", auto_actionable=False, human_action_required="NO", stop_reason=None,
    ))
    return updated


def event_for_import_outcome(state: str, result_status: Optional[str] = None,
                             findings: Sequence[str] = (), parse_error: Optional[str] = None) -> str:
    """Maps a real `model_handoff_workflow.import_result()` outcome onto
    this table's provider-independent events. `state` is the workflow's own
    state string; `findings` are `ValidationOutcome.findings`."""
    if state == "RESULT_CONSUMED":
        if result_status == "HUMAN_DECISION_REQUIRED":
            return "RESULT_CONSUMED_HUMAN_DECISION"
        if result_status in ("FAIL", "PARTIAL"):
            return "RESULT_CONSUMED"
        return "RESULT_CONSUMED_CLEAN"
    if state == "RESULT_REJECTED":
        if parse_error and not findings:
            return "RESULT_REJECTED_MALFORMED"
        if "SCOPE_VIOLATION" in findings:
            return "RESULT_REJECTED_SCOPE_VIOLATION"
        return "RESULT_REJECTED_VALIDATION"
    raise ValueError(f"NO_EVENT_FOR_STATE:{state}")


def _next_action_path(root: Path, task_id: str) -> Path:
    return Path(root) / ".dv-harness" / "model_handoffs" / task_id / "next_action.json"


def persist_next_action(root: Path, task_id: str, record: NextActionRecord) -> Path:
    """After every state-changing operation the next action is persisted, so
    nobody has to reconstruct or schedule it."""
    path = _next_action_path(root, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def read_next_action(root: Path, task_id: str) -> Optional[Dict[str, Any]]:
    path = _next_action_path(root, task_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# --- Persist / Resume (dispatch section 16) --------------------------------

def _contract_state_path(root: Path, task_id: str) -> Path:
    # Same per-task directory model_handoff_workflow.py already owns
    # (`.dv-harness/model_handoffs/<task_id>/`) -- this file is additive
    # (records only this module's own stop decisions), never a
    # replacement for that module's own state.json.
    return Path(root) / ".dv-harness" / "model_handoffs" / task_id / "execution_contract_state.json"


def persist_stop(root: Path, task_id: str, decision: StopDecision) -> Path:
    """The human must not reconstruct workflow state: every stop is
    written to a real file a resuming caller can read back exactly."""
    path = _contract_state_path(root, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decision.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def read_persisted_stop(root: Path, task_id: str) -> Optional[Dict[str, Any]]:
    path = _contract_state_path(root, task_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# --- Canonical Task Completion Evaluator (P3/P4/P6 gap-close) ---------------
# EVALUATE_CANONICAL_TASK_COMPLETION was a named target in NEXT_ACTION_TABLE
# (RESULT_CONSUMED_CLEAN's own route) with no producer anywhere in the
# codebase -- found live when M7-V1-CODEX-REVIEW-007 consumed cleanly
# (PASS, zero findings) and nothing evaluated what that actually meant for
# the Codex branch or the wider M7 program. Read-only: never itself
# generates a handoff or files a question -- a caller (the current-session
# executor) acts on `next_approved_gate`, the same evaluate/act separation
# `model_handoff_workflow.build_correction_request_handoff()` (GAP-V2-016)
# already established.

TASK_COMPLETE = "TASK_COMPLETE"
TASK_FAILED_REMEDIATION_PENDING = "TASK_FAILED_REMEDIATION_PENDING"
TASK_STATUS_UNKNOWN = "TASK_STATUS_UNKNOWN"

BRANCH_READY_FOR_CLOSURE = "BRANCH_READY_FOR_CLOSURE"
BRANCH_NOT_READY = "BRANCH_NOT_READY"

GATE_GENERATE_CHATGPT_HANDOFF = "GENERATE_CHATGPT_ARCHITECTURE_GOVERNANCE_HANDOFF"
GATE_AWAIT_CHATGPT_RESULT = "AWAIT_CHATGPT_RESULT"
GATE_REMEDIATE_FINDINGS = "AUTO_REMEDIATE_CONFIRMED_FINDINGS"
GATE_M7_FULL_CLOSURE_REVIEW_REQUIRED = "M7_FULL_CLOSURE_REVIEW_REQUIRED"


@dataclass(frozen=True)
class CanonicalCompletionEvaluation:
    task_id: str
    #: This ONE task's own review outcome -- never conflated with program completion.
    task_completion: str
    #: Is the Codex review BRANCH (the current round of findings) settled.
    branch_closure_readiness: str
    #: Real, currently-OPEN question_queue ids -- e.g. R005-2/R006-4's
    #: HumanGate. Outstanding does not necessarily mean BLOCKING (a caller
    #: cross-checks against its own disposition record for that).
    outstanding_human_authority_items: Sequence[str]
    #: M7 program-level completion. NEVER "M7_COMPLETE" merely because one
    #: task passed -- requires the ChatGPT round trip too, at minimum.
    program_completion: str
    next_approved_gate: str
    evidence_refs: Sequence[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id, "task_completion": self.task_completion,
            "branch_closure_readiness": self.branch_closure_readiness,
            "outstanding_human_authority_items": list(self.outstanding_human_authority_items),
            "program_completion": self.program_completion,
            "next_approved_gate": self.next_approved_gate,
            "evidence_refs": list(self.evidence_refs),
        }


def _chatgpt_round_trip_consumed(root: Path) -> bool:
    """Real scan of every registered task's own persisted state.json --
    never a hardcoded task_id -- for ANY chatgpt-target task that reached
    RESULT_CONSUMED."""
    from . import model_handoff_workflow as _wf
    base = Path(root) / _wf._HANDOFF_DIR
    if not base.is_dir():
        return False
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        state = _wf._load_state(root, d.name)
        if state and state.get("target_model") == "chatgpt" and state.get("state") == _wf.STATE_RESULT_CONSUMED:
            return True
    return False


def evaluate_canonical_task_completion(root: Path, task_id: str) -> CanonicalCompletionEvaluation:
    """The real, previously-missing executor for
    `EVALUATE_CANONICAL_TASK_COMPLETION`. Every field is derived from real
    persisted Canonical state (this task's own consumed result, the real
    question_queue store, a real scan for a consumed ChatGPT round trip)
    -- never guessed, never inferred from "no known pending work"."""
    root = Path(root)
    from . import model_handoff_workflow as _wf
    from . import model_result as _result_mod
    from .question_queue import QuestionQueueStore

    state = _wf._load_state(root, task_id)
    if state is None or state.get("state") != _wf.STATE_RESULT_CONSUMED:
        raise ValueError(f"NOT_CONSUMED:{task_id}:{state.get('state') if state else 'NO_STATE'}")

    result_status = state.get("result_status")
    result_path = _wf._task_dir(root, task_id) / "RESULT_V1.md"
    findings: Sequence[str] = ()
    try:
        findings = _result_mod.from_markdown(result_path.read_text(encoding="utf-8")).findings
    except Exception:
        pass  # an unparseable-now result still has a real persisted result_status to fall back on

    if result_status == "PASS" and not findings:
        task_completion = TASK_COMPLETE
        branch = BRANCH_READY_FOR_CLOSURE
    elif findings or result_status in ("FAIL", "PARTIAL"):
        task_completion = TASK_FAILED_REMEDIATION_PENDING
        branch = BRANCH_NOT_READY
    else:
        task_completion = TASK_STATUS_UNKNOWN
        branch = BRANCH_NOT_READY

    store = QuestionQueueStore(root)
    outstanding = tuple(q["id"] for q in store.list_questions(status="OPEN"))
    chatgpt_done = _chatgpt_round_trip_consumed(root)

    if branch != BRANCH_READY_FOR_CLOSURE:
        next_gate = GATE_REMEDIATE_FINDINGS
        program = "M7_NOT_COMPLETE:CODEX_BRANCH_NOT_READY"
    elif not chatgpt_done:
        next_gate = GATE_GENERATE_CHATGPT_HANDOFF
        program = "M7_NOT_COMPLETE:CHATGPT_ROUND_TRIP_NOT_CONSUMED"
    else:
        next_gate = GATE_M7_FULL_CLOSURE_REVIEW_REQUIRED
        program = "M7_NOT_COMPLETE:FULL_CLOSURE_CRITERIA_REVIEW_REQUIRED"

    return CanonicalCompletionEvaluation(
        task_id=task_id, task_completion=task_completion, branch_closure_readiness=branch,
        outstanding_human_authority_items=outstanding, program_completion=program,
        next_approved_gate=next_gate,
        evidence_refs=(str(result_path), f"question_queue_open_count={len(outstanding)}",
                      f"chatgpt_round_trip_consumed={chatgpt_done}"),
    )


def _completion_evaluation_path(root: Path, task_id: str) -> Path:
    return Path(root) / ".dv-harness" / "model_handoffs" / task_id / "canonical_completion_evaluation.json"


def persist_completion_evaluation(root: Path, task_id: str, evaluation: CanonicalCompletionEvaluation) -> Path:
    """Real persisted evidence -- P3 CLOSE THE LOOP: an evaluation that
    only ever lived in a return value would be exactly the kind of
    unconsumed/unpersisted output this same gap-close is meant to stop
    happening again."""
    path = _completion_evaluation_path(root, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evaluation.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def read_persisted_completion_evaluation(root: Path, task_id: str) -> Optional[Dict[str, Any]]:
    path = _completion_evaluation_path(root, task_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def record_completion_evaluation_next_action(
    root: Path, task_id: str, evaluation: CanonicalCompletionEvaluation, *,
    downstream_task_id: Optional[str] = None,
) -> Path:
    """P3 CLOSE THE LOOP fix, found live: after this session first shipped
    `evaluate_canonical_task_completion()` and acted on its recommendation
    for `M7-V1-CODEX-REVIEW-007`, `persist_completion_evaluation()` wrote
    the real evaluation -- but `task_id`'s OWN `next_action.json` was left
    exactly as `resolve_next_action()` had originally written it
    (`next_action=EVALUATE_CANONICAL_TASK_COMPLETION`,
    `auto_actionable=true`), stale and indistinguishable from "not yet
    executed" to a later reader. This persists a real, terminal
    `NextActionRecord` for the SOURCE task showing the action WAS
    executed and what it resolved to -- closing the exact gap this
    module's own `EVALUATE_CANONICAL_TASK_COMPLETION` fix was built to
    stop happening again, applied to its own output this time."""
    record = NextActionRecord(
        event="EVALUATE_CANONICAL_TASK_COMPLETION",
        next_action=f"EXECUTED:{evaluation.next_approved_gate}",
        next_action_reason=(
            f"canonical_completion_evaluation persisted ({evaluation.task_completion}, "
            f"{evaluation.branch_closure_readiness}); acted on next_approved_gate="
            f"{evaluation.next_approved_gate}"
            + (f"; downstream_task_id={downstream_task_id}" if downstream_task_id else "")
        ),
        next_action_owner="L5DGVA",
        auto_actionable=False,
        human_action_required="NO",
        stop_reason=None,
    )
    return persist_next_action(root, task_id, record)


# --- Adapter: derive real signals from model_handoff_workflow's own state -

def signals_from_model_handoff_state(
    root: Path, task_id: str, *,
    auto_actionable_pending: bool = False,
    required_remediation_pending: bool = False,
    required_verification_pending: bool = False,
    required_regression_pending: bool = False,
    required_rereview_preparation_pending: bool = False,
    canonical_task_complete: bool = False,
) -> WorkflowSignals:
    """Translates `model_handoff_workflow`'s own real, persisted state
    for `task_id` into this module's canonical `WorkflowSignals` -- the
    ONE real state authority for a handoff/result task; this function
    never re-implements or shadows it. When that state is
    `WAITING_FOR_HUMAN_TRANSPORT`, every Human Transport Gate field is
    filled from the real, currently-persisted `HANDOFF_V1.md`. The five
    `*_PENDING` / `canonical_task_complete` keyword args describe
    follow-on work model_handoff_workflow itself does not track (e.g.
    whether an accepted result's findings still have open remediation)
    -- a caller supplies them from real evidence; this function never
    fabricates them from state alone."""
    from . import model_handoff_workflow as _wf

    state = _wf.current_state(root, task_id)
    if state == _wf.STATE_WAITING_FOR_HUMAN_TRANSPORT:
        handoff = _wf._load_handoff(root, task_id)
        task_dir = _wf._task_dir(root, task_id)
        return WorkflowSignals(
            human_transport_required=True,
            task_id=task_id,
            target_model=handoff.target_model if handoff is not None else None,
            handoff_file=str(task_dir / "HANDOFF_V1.md"),
            expected_result_file=str(task_dir / "RESULT_V1.md"),
            import_command=(
                f"python -m dv_harness.model_handoff_workflow import "
                f"--task-id {task_id} --result-file "
                f"{task_dir / 'RESULT_V1.md'} --root {root}"
            ),
            resume_action="AUTO_RESUME",
        )
    return WorkflowSignals(
        auto_actionable_pending=auto_actionable_pending,
        required_remediation_pending=required_remediation_pending,
        required_verification_pending=required_verification_pending,
        required_regression_pending=required_regression_pending,
        required_rereview_preparation_pending=required_rereview_preparation_pending,
        canonical_task_complete=canonical_task_complete,
    )
