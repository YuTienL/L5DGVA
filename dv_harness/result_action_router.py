"""dv_harness/result_action_router.py -- Prime Directive V2 P6's
Result-to-Action Router, Auto-Remediation Eligibility gate, Loop
Termination/Budget policy, and Evidence Traceability persistence
(`docs/architecture/L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2.md`'s own "P6
--- Result -> Action -> Autonomous Closure" section;
`docs/architecture/canonical_detailed_governance/
L5DGVA_RESULT_DRIVEN_AUTONOMOUS_CLOSED_LOOP_REQUIREMENTS.md`).

Provider-independent by construction (the dispatch's own requirement):
every function here takes a real, caller-supplied `disposition`/
eligibility fact, never a `producer_model` name -- nothing in this
module's control flow branches on "codex" vs "chatgpt" vs any other
target model. A caller (e.g. the per-task Codex/ChatGPT findings table
producer) is responsible for turning a model's own claim into one of
this module's real, closed-form inputs; this module never reads free
text or a model's own confidence/severity language to decide routing.

Budget exhaustion, no-progress, or scope/regression expansion is always
a real, named `HUMAN_ESCALATION_THRESHOLD`-class stop -- never silently
treated as PASS or as "keep looping" (Prime Directive V2 P6's own
`AUTO_PASS_ON_BUDGET_EXHAUSTION=NO` invariant).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# --- Action classes ------------------------------------------------------

ACTION_AUTO_REMEDIATION_ELIGIBLE = "AUTO_REMEDIATION_ELIGIBLE"
ACTION_HUMAN_GATE_REQUIRED = "HUMAN_GATE_REQUIRED"
ACTION_DEFERRED_WITH_OWNER = "DEFERRED_WITH_OWNER"
ACTION_CLOSE_WITH_EVIDENCE = "CLOSE_WITH_EVIDENCE"
ACTION_BLOCKED = "BLOCKED"

ACTION_CLASSES = (
    ACTION_AUTO_REMEDIATION_ELIGIBLE, ACTION_HUMAN_GATE_REQUIRED,
    ACTION_DEFERRED_WITH_OWNER, ACTION_CLOSE_WITH_EVIDENCE, ACTION_BLOCKED,
)

# --- P5 dispositions (reused verbatim from Prime Directive V2 P5 -- never
# a second, competing enum) --------------------------------------------

DISPOSITION_FIX_NOW_CURRENT_SCOPE = "FIX_NOW_CURRENT_SCOPE"
DISPOSITION_FIX_NOW_CORRECTNESS_BLOCKER = "FIX_NOW_CORRECTNESS_BLOCKER"
DISPOSITION_FIX_NOW_CAPABILITY_LOSS = "FIX_NOW_CAPABILITY_LOSS"
DISPOSITION_FIX_NOW_SAFETY_SECURITY = "FIX_NOW_SAFETY_SECURITY"
DISPOSITION_REGISTER_AND_DEFER_WITH_OWNER = "REGISTER_AND_DEFER_WITH_OWNER"
DISPOSITION_SUPERSEDED_WITH_EVIDENCE = "SUPERSEDED_WITH_EVIDENCE"
DISPOSITION_NOT_APPLICABLE_WITH_EVIDENCE = "NOT_APPLICABLE_WITH_EVIDENCE"
DISPOSITION_HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"

DISPOSITIONS = (
    DISPOSITION_FIX_NOW_CURRENT_SCOPE, DISPOSITION_FIX_NOW_CORRECTNESS_BLOCKER,
    DISPOSITION_FIX_NOW_CAPABILITY_LOSS, DISPOSITION_FIX_NOW_SAFETY_SECURITY,
    DISPOSITION_REGISTER_AND_DEFER_WITH_OWNER, DISPOSITION_SUPERSEDED_WITH_EVIDENCE,
    DISPOSITION_NOT_APPLICABLE_WITH_EVIDENCE, DISPOSITION_HUMAN_DECISION_REQUIRED,
)

#: Default auto-remediation-eligible disposition set (dispatch's own
#: default candidates). FIX_NOW_SAFETY_SECURITY is deliberately NOT a
#: default auto candidate -- a safety/security fix routes to a HumanGate
#: by default even though it is a real FIX_NOW disposition.
DEFAULT_AUTO_ELIGIBLE_DISPOSITIONS = frozenset({
    DISPOSITION_FIX_NOW_CURRENT_SCOPE,
    DISPOSITION_FIX_NOW_CORRECTNESS_BLOCKER,
    DISPOSITION_FIX_NOW_CAPABILITY_LOSS,
})

# --- Auto-Remediation reject reasons (dispatch's own list) --------------

REJECT_REQUIRES_HUMAN_AUTHORITY = "REQUIRES_HUMAN_AUTHORITY"
REJECT_PROTECTED_ARCHITECTURE_CHANGE = "PROTECTED_ARCHITECTURE_CHANGE"
REJECT_SCOPE_EXPANSION = "SCOPE_EXPANSION"
REJECT_SECURITY_EXPANSION = "SECURITY_EXPANSION"
REJECT_FROZEN_SOURCE_MODIFICATION = "FROZEN_SOURCE_MODIFICATION"
REJECT_NEW_HUMAN_DECISION = "NEW_HUMAN_DECISION"

REJECT_REASONS = (
    REJECT_REQUIRES_HUMAN_AUTHORITY, REJECT_PROTECTED_ARCHITECTURE_CHANGE,
    REJECT_SCOPE_EXPANSION, REJECT_SECURITY_EXPANSION,
    REJECT_FROZEN_SOURCE_MODIFICATION, REJECT_NEW_HUMAN_DECISION,
)


@dataclass(frozen=True)
class RemediationCandidate:
    """One finding's real, caller-supplied eligibility-relevant facts --
    never inferred by this module from a model's own confidence/severity
    text. A caller sets each boolean from real evidence about the
    SPECIFIC fix the finding needs, not from the finding's prose."""
    finding_id: str
    gap_id: Optional[str]
    disposition: str
    requires_human_authority: bool = False
    is_protected_architecture_change: bool = False
    is_scope_expansion: bool = False
    is_security_expansion: bool = False
    modifies_frozen_source: bool = False
    raises_new_human_decision: bool = False

    def __post_init__(self) -> None:
        if self.disposition not in DISPOSITIONS:
            raise ValueError(f"UNKNOWN_DISPOSITION:{self.disposition}")


@dataclass(frozen=True)
class EligibilityOutcome:
    finding_id: str
    eligible: bool
    action_class: str
    reject_reasons: Sequence[str] = ()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_auto_remediation_eligibility(
    candidate: RemediationCandidate,
    auto_eligible_dispositions: frozenset = DEFAULT_AUTO_ELIGIBLE_DISPOSITIONS,
) -> EligibilityOutcome:
    """The real Auto-Remediation Eligibility gate. A finding is
    AUTO_REMEDIATION_ELIGIBLE only when its disposition is in the
    caller's real auto-eligible set AND none of the six reject-reason
    booleans is set -- any single reject reason forces a HumanGate
    regardless of disposition."""
    reasons: List[str] = []
    if candidate.requires_human_authority:
        reasons.append(REJECT_REQUIRES_HUMAN_AUTHORITY)
    if candidate.is_protected_architecture_change:
        reasons.append(REJECT_PROTECTED_ARCHITECTURE_CHANGE)
    if candidate.is_scope_expansion:
        reasons.append(REJECT_SCOPE_EXPANSION)
    if candidate.is_security_expansion:
        reasons.append(REJECT_SECURITY_EXPANSION)
    if candidate.modifies_frozen_source:
        reasons.append(REJECT_FROZEN_SOURCE_MODIFICATION)
    if candidate.raises_new_human_decision:
        reasons.append(REJECT_NEW_HUMAN_DECISION)

    disposition_ok = candidate.disposition in auto_eligible_dispositions
    eligible = disposition_ok and not reasons
    return EligibilityOutcome(
        finding_id=candidate.finding_id,
        eligible=eligible,
        action_class=ACTION_AUTO_REMEDIATION_ELIGIBLE if eligible else ACTION_HUMAN_GATE_REQUIRED,
        reject_reasons=tuple(reasons),
    )


def route_action(
    candidate: RemediationCandidate,
    auto_eligible_dispositions: frozenset = DEFAULT_AUTO_ELIGIBLE_DISPOSITIONS,
) -> EligibilityOutcome:
    """The real Result-to-Action Router. Maps a finding's disposition +
    eligibility facts to exactly one action class -- never a
    Codex-specific/ChatGPT-specific branch."""
    if candidate.disposition == DISPOSITION_HUMAN_DECISION_REQUIRED:
        return EligibilityOutcome(candidate.finding_id, False, ACTION_HUMAN_GATE_REQUIRED)
    if candidate.disposition == DISPOSITION_REGISTER_AND_DEFER_WITH_OWNER:
        return EligibilityOutcome(candidate.finding_id, False, ACTION_DEFERRED_WITH_OWNER)
    if candidate.disposition in (DISPOSITION_SUPERSEDED_WITH_EVIDENCE,
                                  DISPOSITION_NOT_APPLICABLE_WITH_EVIDENCE):
        return EligibilityOutcome(candidate.finding_id, False, ACTION_CLOSE_WITH_EVIDENCE)
    if candidate.disposition == DISPOSITION_FIX_NOW_SAFETY_SECURITY:
        # A real safety/security fix is always routed to a HumanGate by
        # this module -- it is never a default auto-eligible disposition
        # regardless of what auto_eligible_dispositions the caller passed.
        return EligibilityOutcome(candidate.finding_id, False, ACTION_HUMAN_GATE_REQUIRED)
    if candidate.disposition in (DISPOSITION_FIX_NOW_CURRENT_SCOPE,
                                  DISPOSITION_FIX_NOW_CORRECTNESS_BLOCKER,
                                  DISPOSITION_FIX_NOW_CAPABILITY_LOSS):
        return evaluate_auto_remediation_eligibility(candidate, auto_eligible_dispositions)
    # Unreachable given __post_init__'s DISPOSITIONS membership check --
    # kept as a real, named fallback rather than an assert, so a future
    # disposition added to DISPOSITIONS without a matching branch here
    # fails safe (BLOCKED) instead of falling through silently.
    return EligibilityOutcome(candidate.finding_id, False, ACTION_BLOCKED,
                              reject_reasons=("UNROUTABLE_DISPOSITION",))


# --- Loop Termination / Budget -------------------------------------------

@dataclass
class LoopBudget:
    """Measured, real counters for one autonomous remediation loop.
    `token_usage` stays `None` when the caller cannot measure it --
    never fabricated as 0 (0 would falsely read as "measured and free")."""
    iteration_count: int = 0
    model_invocations: int = 0
    test_run_count: int = 0
    regression_run_count: int = 0
    wall_time_seconds: float = 0.0
    context_bytes: int = 0
    token_usage: Optional[int] = None
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LoopTerminationPolicy:
    """Configurable, evidence-backed thresholds -- never arbitrary
    constants added merely to claim completion (Prime Directive V2's own
    "no arbitrary constants" discipline). Defaults are conservative
    starting points a caller is expected to override with a real,
    documented rationale for its own task class."""
    max_remediation_iterations: int = 10
    max_retry_per_finding: int = 3
    max_wall_time_seconds: float = 3600.0
    max_context_bytes: Optional[int] = None


REASON_BUDGET_OK = "BUDGET_OK"
REASON_MAX_ITERATIONS_EXCEEDED = "MAX_REMEDIATION_ITERATIONS_EXCEEDED"
REASON_MAX_RETRY_EXCEEDED = "MAX_RETRY_PER_FINDING_EXCEEDED"
REASON_WALL_TIME_EXCEEDED = "WALL_TIME_EXCEEDED"
REASON_CONTEXT_BUDGET_EXCEEDED = "CONTEXT_BUDGET_EXCEEDED"
REASON_NO_PROGRESS = "NO_PROGRESS_DETECTED"
REASON_REPEATED_FAILURE_SIGNATURE = "REPEATED_FAILURE_SIGNATURE"
REASON_REPEATED_FINDING_SIGNATURE = "REPEATED_FINDING_SIGNATURE"
REASON_REGRESSION_EXPANSION = "REGRESSION_EXPANSION_DETECTED"
REASON_SCOPE_EXPANSION = "SCOPE_EXPANSION_DETECTED"
REASON_EVIDENCE_STAGNATION = "EVIDENCE_STAGNATION"


@dataclass(frozen=True)
class TerminationCheckResult:
    should_continue: bool
    reason: str
    requires_human_escalation: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def check_loop_termination(
    budget: LoopBudget,
    policy: LoopTerminationPolicy,
    retry_count_for_current_finding: int = 0,
    failure_signatures: Sequence[str] = (),
    finding_signatures: Sequence[str] = (),
    regression_failure_count_delta: int = 0,
    scope_touched_outside_declared: bool = False,
    evidence_unchanged_since_last_iteration: bool = False,
) -> TerminationCheckResult:
    """Real, evidence-backed loop-termination check. Budget exhaustion
    NEVER becomes a silent PASS -- every stop path here is a named,
    human-escalatable reason, never a bare `False`. A caller supplies
    real signatures/deltas it actually observed this iteration; this
    function never guesses "no progress" from a missing argument (an
    empty `failure_signatures`/`finding_signatures` never triggers the
    repeated-signature checks)."""
    if budget.iteration_count >= policy.max_remediation_iterations:
        return TerminationCheckResult(False, REASON_MAX_ITERATIONS_EXCEEDED, True)
    if retry_count_for_current_finding >= policy.max_retry_per_finding:
        return TerminationCheckResult(False, REASON_MAX_RETRY_EXCEEDED, True)
    if budget.wall_time_seconds >= policy.max_wall_time_seconds:
        return TerminationCheckResult(False, REASON_WALL_TIME_EXCEEDED, True)
    if policy.max_context_bytes is not None and budget.context_bytes >= policy.max_context_bytes:
        return TerminationCheckResult(False, REASON_CONTEXT_BUDGET_EXCEEDED, True)
    if len(failure_signatures) >= 2 and len(set(failure_signatures[-2:])) == 1:
        return TerminationCheckResult(False, REASON_REPEATED_FAILURE_SIGNATURE, True)
    if len(finding_signatures) >= 2 and len(set(finding_signatures[-2:])) == 1:
        return TerminationCheckResult(False, REASON_REPEATED_FINDING_SIGNATURE, True)
    if regression_failure_count_delta > 0:
        return TerminationCheckResult(False, REASON_REGRESSION_EXPANSION, True)
    if scope_touched_outside_declared:
        return TerminationCheckResult(False, REASON_SCOPE_EXPANSION, True)
    if evidence_unchanged_since_last_iteration:
        return TerminationCheckResult(False, REASON_EVIDENCE_STAGNATION, True)
    return TerminationCheckResult(True, REASON_BUDGET_OK, False)


# --- Evidence Traceability ------------------------------------------------

@dataclass(frozen=True)
class IterationTrace:
    """One autonomous-remediation iteration's full traceability record
    (dispatch's own named field list). Persisted append-only -- an
    iteration's trace is never overwritten or rewritten by a later one."""
    source_result_id: str
    finding_id: str
    gap_id: Optional[str]
    action_classification: str
    eligibility_decision: str
    root_cause: str
    files_changed: Sequence[str]
    tests_run: Sequence[str]
    regression_signature: Optional[str]
    evidence_refs: Sequence[str]
    re_review_task_id: Optional[str]
    iteration_number: int
    final_disposition: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _trace_path(root: Path, task_id: str) -> Path:
    return Path(root) / ".dv-harness" / "model_handoffs" / task_id / "loop_evidence_trace.jsonl"


def append_iteration_trace(root: Path, task_id: str, trace: IterationTrace) -> Path:
    """Real, append-only JSONL persistence -- one line per autonomous
    iteration, never overwritten ("Evidence Traceability... for every
    autonomous iteration")."""
    out_path = _trace_path(root, task_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(trace.to_dict(), sort_keys=True) + "\n")
    return out_path


def read_iteration_traces(root: Path, task_id: str) -> List[Dict[str, Any]]:
    """Real read-back of every persisted iteration trace for `task_id`,
    in append order. An empty/never-written trace file is a real empty
    list, never a fabricated record."""
    path = _trace_path(root, task_id)
    if not path.is_file():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out
