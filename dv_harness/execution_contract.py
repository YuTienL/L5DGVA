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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

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
