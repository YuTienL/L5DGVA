"""CapabilityEvolutionCandidate: the harness reasoning about changes to ITSELF.

Research-Capability Evolution master prompt sections 13/14/43/63/70, Stage 1.
This module is the machinery the `research-architect` agent
(.claude/agents/research-architect.md) runs on. It does NOT operate that
machinery on any real external document -- that is Stage 2 -- and it implements
no capability-evolution change to production code -- that is Stage 3, which
needs separate explicit human approval.

WHY A NEW MODULE RATHER THAN AN EXTENSION OF self_tuning.py
-----------------------------------------------------------
The Stage 0 audit compared the two concretely and split the answer, and this
module follows that split rather than re-litigating it:

  * REUSED, not reimplemented: `MemoryStore.add()` underneath
    `record_adjustment()` (reached here through the real
    `memory_router.route_and_store()` router, one level up); the
    index-then-get enumeration those functions hand-roll, now promoted to the
    shared `MemoryStore.find()` this module is the first caller of; and
    self_tuning.py's overall orchestration SHAPE -- assemble evidence, decide
    with a pure classifier, persist the outcome, never let the LLM's own
    say-so be the gate.

  * NOT reused, because they encode assumptions that stop holding here:
    `classify_proposal()` (binary AUTO_APPLY/DEFER, and a rule list keyed to
    hardcoded gate_id/parameter sets), `apply_proposal()` (every change is a
    JSON key write against a `(gate_id[, stage])` pair), and the 4-value
    PENDING/APPLIED/REJECTED/REVERTED status. A gate parameter's "experiment"
    is just letting it run and watching the next slice of gate_history, and
    its rollback is always "restore the prior value". Neither is true of
    "add an Agent" or "write a new Skill", which is exactly why section 70
    specifies eleven governance states where self_tuning has two outcomes.

  * DELIBERATELY NOT COPIED: self_tuning's `classify_proposal()` trusts the
    LLM's own `"confidence": "HIGH"` string verbatim. This module refuses to
    -- `recompute_confidence()` re-derives the level from the stored inputs
    through the real `inference.score_confidence()` and rejects a candidate
    whose stored level disagrees, following `engine._score_root_cause_
    confidence()`'s precedent rather than self_tuning's weaker habit. Master
    prompt section 10 mandates routing this reasoning through the existing
    Autonomous Inference Engine; a self-reported label is not that.

WHAT THIS MODULE CANNOT DO, BY CONSTRUCTION
-------------------------------------------
  * It has no verification authority. Nothing here returns, accepts or
    persists any member of `dv_harness.models.Status` -- the vocabularies in
    RECOMMENDATIONS / PROMOTION_STATES / OVERLAP_STATUSES are disjoint from it
    on purpose, and `assert_no_verification_verdict_vocabulary()` makes that
    checkable rather than a claim in a docstring. An LLM's reasoning cannot
    become a PASS through any code path in this file.
  * It writes nothing outside `<root>/.dv-harness/`. It never opens a file
    under `dv_harness/` or `.claude/` for writing, so running the decision
    logic cannot modify this repo (master prompt section 73's Self-Improvement
    Safety Boundary; CLAUDE.md's Agent-Authored Change Accountability policy).
  * It cannot reach PRODUCTION without a real human. `assert_human_approval()`
    consults the real `ControlPlane` approval on disk; a transition into
    HUMAN_APPROVED without one raises.
  * It never promotes anything to Organizational Memory. `persist_candidate()`
    asserts its routed destination is WORKING_MEMORY and raises otherwise: a
    single design session is not the "repeated, human-approved" evidence
    `memory_router.promote_to_organizational()` requires.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .blackboard import Blackboard
from .inference import identify_gap, next_best_action, score_confidence

_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
CAPABILITY_EVOLUTION_CANDIDATE_SCHEMA_PATH = (
    _SCHEMA_DIR / "capability_evolution_candidate.schema.json"
)

CANDIDATE_SCHEMA_VERSION = "1.0"

# The Blackboard topic this module owns. One topic, one writer
# (persist_candidate), matching the `findings` / `debug_loop_history`
# convention -- section 11 forbids a parallel Research Blackboard.
BLACKBOARD_TOPIC = "capability_evolution_candidates"

# The memory `kind` a candidate's audit record carries. Deliberately NOT added
# to memory_router.route_memory()'s dispatch table: it falls through to that
# function's WORKING_MEMORY default, which is the honest tier for an in-flight,
# undecided state machine, and the Stage 0 audit's explicit recommendation was
# that this needs zero new kind strings.
CANDIDATE_MEMORY_KIND = "capability_evolution_candidate"

# The ControlPlane stage id this module's Human Approval Gate uses.
# `ControlPlane.approve(stage=...)` takes an arbitrary string key, not a
# `models.Stage` member, so this needs no new graph node -- the Stage 0 audit
# confirmed the mechanism is reusable verbatim.
HUMAN_APPROVAL_STAGE = "RESEARCH_CAPABILITY_EVOLUTION"

# Master prompt section 70, verbatim and complete.
PROMOTION_STATES = (
    "DISCOVERED", "EVIDENCE_GATHERING", "PROPOSED", "EXPERIMENT_APPROVED",
    "EXPERIMENTING", "BENCHMARKED", "PROMOTION_CANDIDATE", "HUMAN_APPROVED",
    "PRODUCTION", "REJECTED", "ROLLED_BACK",
)

TERMINAL_STATES = ("PRODUCTION", "REJECTED", "ROLLED_BACK")

# "Do not skip governance states." Every legal edge, explicitly. The one
# forward edge that bypasses the three experiment states -- PROPOSED ->
# PROMOTION_CANDIDATE -- is legal ONLY when the candidate's own
# experiment_required is False, enforced in assert_legal_transition() rather
# than left to this table, because a table cannot see the candidate.
LEGAL_TRANSITIONS: Dict[Optional[str], tuple] = {
    None: ("DISCOVERED",),
    "DISCOVERED": ("EVIDENCE_GATHERING", "REJECTED"),
    "EVIDENCE_GATHERING": ("PROPOSED", "REJECTED"),
    "PROPOSED": ("EXPERIMENT_APPROVED", "PROMOTION_CANDIDATE", "REJECTED"),
    "EXPERIMENT_APPROVED": ("EXPERIMENTING", "REJECTED"),
    "EXPERIMENTING": ("BENCHMARKED", "REJECTED"),
    "BENCHMARKED": ("PROMOTION_CANDIDATE", "REJECTED"),
    "PROMOTION_CANDIDATE": ("HUMAN_APPROVED", "REJECTED"),
    "HUMAN_APPROVED": ("PRODUCTION", "REJECTED"),
    "PRODUCTION": ("ROLLED_BACK",),
    "REJECTED": (),
    "ROLLED_BACK": (),
}

# States from which a production file may legitimately be touched at all.
# Stage 3 work is authorized by HUMAN_APPROVED and nothing weaker.
PRODUCTION_WRITE_AUTHORIZED_STATES = ("HUMAN_APPROVED", "PRODUCTION")

RECOMMENDATIONS = ("KEEP", "ENHANCE", "ADD", "EXPERIMENT", "REJECT", "UNKNOWN")
OVERLAP_STATUSES = ("EXISTS", "PARTIAL_MATCH", "MISSING", "UNKNOWN")

# Master prompt section 14's ten mandatory questions, in order, each keyed by
# the candidate field that answers it. These keys are what identify_gap() is
# fed -- the harness's existing Gap step, not a private set-difference.
L5_CHECK_QUESTIONS = (
    "q1_already_exists",
    "q2_is_it_partial",
    "q3_which_files_implement_it",
    "q4_which_agent_owns_it",
    "q5_which_skill_owns_it",
    "q6_which_graph_node_handles_it",
    "q7_which_state_structure_carries_it",
    "q8_which_memory_layer_stores_it",
    "q9_exact_capability_missing",
    "q10_why_enhance_insufficient",
)

# Which candidate field answers each question. q1/q2 are both answered by
# overlap_status (EXISTS / PARTIAL_MATCH are the two "yes" answers); q10 is
# only owed when the recommendation is ADD.
L5_QUESTION_FIELD = {
    "q1_already_exists": "overlap_status",
    "q2_is_it_partial": "overlap_status",
    "q3_which_files_implement_it": "existing_files",
    "q4_which_agent_owns_it": "existing_agent",
    "q5_which_skill_owns_it": "existing_skill",
    "q6_which_graph_node_handles_it": "existing_graph_node",
    "q7_which_state_structure_carries_it": "existing_state",
    "q8_which_memory_layer_stores_it": "existing_memory",
    "q9_exact_capability_missing": "exact_gap",
    "q10_why_enhance_insufficient": "enhance_insufficient_reason",
}

# The six search slots whose search_conclusive flags together decide whether
# an absence claim is defensible.
L5_SEARCH_SLOTS = (
    "existing_agent", "existing_skill", "existing_graph_node",
    "existing_state", "existing_memory", "existing_files",
)

# The gap -> next-step catalog handed to the EXISTING
# inference.next_best_action() through its `gap_action_catalog` parameter.
# This is the whole reason that parameter was added: the architecture of the
# Gap -> Next-Best-Action step is reused unchanged (section 10 forbids a
# Research Inference Engine), and only the two DV-simulation-specific halves
# -- the protocol builder registry it reads, and its "inspect current RTL/spec/
# VIP evidence directly" fallback -- are replaced with the ones that are
# actually actionable for an unanswered current-L5 question.
RESEARCH_GAP_ACTION_CATALOG = {
    "source": "l5_check_search_plan",
    "fallback": (
        "no search plan is registered for '{gap}' -- name what you searched and "
        "whether it could have found a match, and record search_conclusive honestly"
    ),
    "actions": {
        "q1_already_exists": (
            "complete the six existing_* searches below; overlap_status is derived "
            "from them, never asserted directly"
        ),
        "q2_is_it_partial": (
            "for every non-empty `matches`, read the named asset and record which "
            "part of the capability it already covers in exact_gap"
        ),
        "q3_which_files_implement_it": (
            "grep dv_harness/ and tools/verification_flow/ for the capability's real "
            "vocabulary, then read the hits -- a file name is not evidence a "
            "mechanism exists (dv_harness/doc_extraction.py lists .pdf and parses none)"
        ),
        "q4_which_agent_owns_it": (
            "read .claude/agents/ROSTER.md, including its 'Role-shaped work that is "
            "deliberately NOT an agent' section, then the candidate .claude/agents/*.md "
            "profiles -- NOT_DISPATCHED does not mean the work does not run"
        ),
        "q5_which_skill_owns_it": (
            "grep .claude/skills/**/SKILL.md; then check whether the skill cites real "
            "code, since several CORE skills describe a mechanism no module implements"
        ),
        "q6_which_graph_node_handles_it": (
            "read .dv-harness/graph/main_graph.json's nodes and dv_harness/gates.py's "
            "STAGE_GATES before concluding a new node is needed"
        ),
        "q7_which_state_structure_carries_it": (
            "read dv_harness/blackboard.py's existing topics and their {items}/{entries} "
            "conventions -- a new topic follows them, a new store does not"
        ),
        "q8_which_memory_layer_stores_it": (
            "read dv_harness/memory_router.py's route_memory() dispatch table; prefer an "
            "already-recognized kind over minting a new one"
        ),
        "q9_exact_capability_missing": (
            "state the missing BEHAVIOUR, not a file that does not exist yet; if nothing "
            "is missing, leave it empty and the recommendation is KEEP"
        ),
        "q10_why_enhance_insufficient": (
            "name the specific existing asset and the specific reason extending it fails; "
            "'nothing was found' is not an answer here -- that belongs in search_basis"
        ),
    },
}

# Master prompt section 43: the nine things that must be complete before the
# stop report may be printed, and the exact report text.
STOP_REPORT_PRECONDITIONS = (
    "research_complete",
    "evidence_cards_complete",
    "current_l5_baseline_complete",
    "gap_analysis_complete",
    "architecture_proposal_complete",
    "priority_matrix_complete",
    "implementation_plan_complete",
    "benchmark_plan_complete",
    "risk_rollback_complete",
)

STOP_REPORT_LINES = (
    "RESEARCH COMPLETE",
    "CURRENT L5 BASELINE COMPLETE",
    "RESEARCH-INGESTION OPERATIONAL",
    "RESEARCH-ARCHITECT OPERATIONAL",
    "L5.x PROPOSAL COMPLETE",
    "IMPLEMENTATION NOT STARTED",
    "AWAITING HUMAN APPROVAL",
)


class CapabilityEvolutionCandidateValidationError(ValueError):
    """A candidate fails capability_evolution_candidate.schema.json, or fails
    one of the checks the schema cannot express (a stored confidence level that
    does not re-derive from its own inputs). Raised rather than returned,
    matching every other schema-backed artifact in this package: an invalid
    candidate must never reach the Blackboard, where a later pass would read it
    as a settled proposal."""


class IllegalPromotionTransitionError(ValueError):
    """A promotion-state transition that section 70's policy does not permit --
    typically a skipped governance state. Raised so the skip fails at the write
    rather than being discovered later in a status_history nobody re-read."""


class HumanApprovalRequiredError(PermissionError):
    """A candidate tried to reach HUMAN_APPROVED (or a production write) with no
    real ControlPlane approval on disk for HUMAN_APPROVAL_STAGE. PermissionError
    rather than ValueError because this is an authority failure, not a data
    one: the record may be perfectly well-formed and still not authorized."""


class ProductionWriteNotAuthorizedError(PermissionError):
    """Stage 3 work was attempted from a candidate that has not been approved.
    The counterpart to HumanApprovalRequiredError for the callers that are
    about to touch a file rather than about to change a state."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_schema() -> Dict[str, Any]:
    return json.loads(
        CAPABILITY_EVOLUTION_CANDIDATE_SCHEMA_PATH.read_text(encoding="utf-8")
    )


def candidate_required_fields() -> List[str]:
    """The schema's own `required` list, read from the schema file rather than
    duplicated here, so this module cannot drift from the contract it builds
    against."""
    return list(_load_schema()["required"])


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's three decision vocabularies must share no token with
    `dv_harness.models.Status`, the harness's verification verdict vocabulary.

    Master prompt Stage-1 acceptance test E in code: an agent reasoning about
    research must never be able to emit something a reader, a log grep or a
    string comparison could take for a verification result. Making the
    disjointness checkable here (rather than asserting it in a docstring) is
    what keeps it true after a later edit adds a state.
    """
    from .models import Status

    verdicts = {s.value for s in Status}
    for name, vocabulary in (
        ("RECOMMENDATIONS", RECOMMENDATIONS),
        ("PROMOTION_STATES", PROMOTION_STATES),
        ("OVERLAP_STATUSES", OVERLAP_STATUSES),
    ):
        collision = verdicts.intersection(vocabulary)
        if collision:
            raise CapabilityEvolutionCandidateValidationError(
                f"{name} collides with dv_harness.models.Status on {sorted(collision)} -- "
                "a capability-evolution decision must never be confusable with a "
                "verification verdict"
            )


def validate_candidate(candidate: Dict[str, Any]) -> None:
    """Validate `candidate` against capability_evolution_candidate.schema.json.

    Raises CapabilityEvolutionCandidateValidationError listing every violation
    with its JSON path. The schema carries the REUSE-before-ADD rule itself (an
    ADD with an empty enhance_insufficient_reason does not validate) and the
    UNKNOWN-vs-MISSING honesty rule (a MISSING whose searches were not all
    conclusive does not validate), so those are enforced here rather than being
    checks a caller has to remember.
    """
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise CapabilityEvolutionCandidateValidationError(
            "jsonschema package is not installed; cannot validate against "
            f"{CAPABILITY_EVOLUTION_CANDIDATE_SCHEMA_PATH.name}. Install it rather "
            "than skipping validation."
        ) from exc
    validator = jsonschema.Draft202012Validator(
        _load_schema(), format_checker=jsonschema.FormatChecker()
    )
    errors = sorted(validator.iter_errors(candidate), key=lambda e: list(e.path))
    if errors:
        lines = [
            f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in errors
        ]
        raise CapabilityEvolutionCandidateValidationError(
            f"{CAPABILITY_EVOLUTION_CANDIDATE_SCHEMA_PATH.name} validation failed:\n"
            + "\n".join(lines)
        )


def mint_candidate_id(affected_capability: str, hypothesis: str, proposed_action: str) -> str:
    """CEC-<12 hex> derived from the proposal's own content.

    Content-derived rather than sequential or random specifically so a
    candidate re-derived in a LATER review cycle lands on the SAME record and
    accumulates evidence across cycles. This is the one capability the Stage 0
    audit found self_tuning.py has no counterpart for: its cycles are stateless
    with respect to "have I proposed this before", so an identical proposal
    forks a fresh, unrelated record every time.
    """
    for name, value in (
        ("affected_capability", affected_capability),
        ("hypothesis", hypothesis),
        ("proposed_action", proposed_action),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string to mint a candidate_id")
    payload = "\x1f".join(
        v.strip() for v in (affected_capability, hypothesis, proposed_action)
    )
    return "CEC-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _slot_answered(slot: Dict[str, Any]) -> bool:
    """A search slot answers its question when a real search was recorded --
    `search_basis` present -- regardless of whether it found anything. An empty
    `matches` is a legitimate answer; a missing search_basis is not."""
    return isinstance(slot, dict) and bool(str(slot.get("search_basis", "")).strip())


def answered_l5_check_questions(candidate: Dict[str, Any]) -> List[str]:
    """Which of section 14's ten questions this candidate actually answers.

    q9 (exact_gap) counts as answered whenever the KEY IS PRESENT, because an
    empty string is the real answer "nothing is missing" and is what a KEEP
    rests on. q10 is owed only when the recommendation is ADD -- for any other
    recommendation it is answered by being correctly empty.
    """
    answered: List[str] = []
    for question in L5_CHECK_QUESTIONS:
        field = L5_QUESTION_FIELD[question]
        if question in ("q1_already_exists", "q2_is_it_partial"):
            # Both are answered by the six searches, not by asserting a status.
            if all(_slot_answered(candidate.get(s)) for s in L5_SEARCH_SLOTS):
                answered.append(question)
        elif field in L5_SEARCH_SLOTS:
            if _slot_answered(candidate.get(field)):
                answered.append(question)
        elif question == "q9_exact_capability_missing":
            if "exact_gap" in candidate and isinstance(candidate["exact_gap"], str):
                answered.append(question)
        elif question == "q10_why_enhance_insufficient":
            if candidate.get("recommendation") == "ADD":
                if str(candidate.get("enhance_insufficient_reason", "")).strip():
                    answered.append(question)
            else:
                answered.append(question)
    return answered


def unanswered_l5_check_questions(candidate: Dict[str, Any]) -> List[str]:
    """The mandatory-current-L5-check worklist, in section 14's own order.

    Reuses dv_harness.inference.identify_gap() -- the harness's existing Gap
    step -- rather than a private set difference, per master prompt section
    10's instruction to route research reasoning through the existing
    Autonomous Inference Engine.
    """
    return identify_gap(list(L5_CHECK_QUESTIONS), answered_l5_check_questions(candidate))


def next_actions_for_unanswered(candidate: Dict[str, Any], root=None) -> List[Dict[str, Any]]:
    """The Next-Best-Action step for whatever the L5 check still owes.

    Calls the real inference.next_best_action() with RESEARCH_GAP_ACTION_CATALOG
    rather than the protocol builder registry. `root` is accepted and passed
    through only to keep this call the same shape as every other
    next_best_action() call site; the catalog branch reads no file, so a None
    root is fine.
    """
    gaps = unanswered_l5_check_questions(candidate)
    if not gaps:
        return []
    return next_best_action(
        "capability_evolution", gaps, root, gap_action_catalog=RESEARCH_GAP_ACTION_CATALOG
    )


def recompute_confidence(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Re-derive the candidate's confidence from its own recorded inputs.

    Runs the real inference.score_confidence() over
    candidate["confidence"]["inputs"] and returns its exact result dict. This
    is the deliberate divergence from self_tuning.classify_proposal(), which
    trusts an LLM's self-reported `"confidence": "HIGH"` string verbatim -- a
    real design defect the Stage 0 audit named and told this module not to
    copy. The precedent followed instead is engine._score_root_cause_
    confidence(), which independently recomputes rather than believing
    RE_AUDIT's own label.
    """
    block = candidate.get("confidence")
    if not isinstance(block, dict) or not isinstance(block.get("inputs"), dict):
        raise CapabilityEvolutionCandidateValidationError(
            "candidate['confidence']['inputs'] is missing -- a confidence level with no "
            "recorded inputs cannot be recomputed, and an unrecomputable level is a "
            "self-reported one"
        )
    return score_confidence(**block["inputs"])


def assert_confidence_recomputed(candidate: Dict[str, Any]) -> None:
    """Raise unless the stored confidence result is exactly what
    score_confidence() produces from the stored inputs."""
    recomputed = recompute_confidence(candidate)
    stored = candidate["confidence"]
    mismatched = {
        key: (stored.get(key), recomputed[key])
        for key in ("level", "score", "capped_by_counter_evidence")
        if stored.get(key) != recomputed[key]
    }
    if mismatched:
        raise CapabilityEvolutionCandidateValidationError(
            "stored confidence disagrees with inference.score_confidence() over the "
            f"candidate's own inputs (stored, recomputed): {mismatched}. The recorded "
            "level is not a claim this module accepts on trust."
        )


def derive_overlap_status(candidate: Dict[str, Any]) -> str:
    """Section 14 questions 1 and 2, DERIVED from the six searches rather than
    asserted.

    UNKNOWN wins over everything: one inconclusive search means absence is not
    established, so MISSING would be a fabrication. This is the rule Stage-1
    acceptance test C exists to hold -- "UNKNOWN remains UNKNOWN when evidence
    is insufficient" (CLAUDE.md's own evidence discipline), not a convenient
    MISSING that would license an ADD.
    """
    slots = [candidate.get(name) for name in L5_SEARCH_SLOTS]
    if not all(_slot_answered(s) for s in slots):
        return "UNKNOWN"
    if not all(bool(s.get("search_conclusive")) for s in slots):
        return "UNKNOWN"
    matched = [s for s in slots if s.get("matches")]
    if not matched:
        return "MISSING"
    if len(matched) == len(slots):
        return "EXISTS"
    return "PARTIAL_MATCH"


def decide_recommendation(candidate: Dict[str, Any], root=None) -> Dict[str, Any]:
    """The KEEP / ENHANCE / ADD / EXPERIMENT / REJECT / UNKNOWN decision.

    A PURE FUNCTION over the candidate's own recorded evidence -- it reads no
    file, writes no file, and calls no model. The agent supplies the searches
    and the evidence counts; this code makes the decision from them, which is
    what keeps "REUSE before EXTEND before ADD" an enforced rule rather than an
    instruction an LLM is trusted to follow each run.

    Rule order, and why each rule is where it is:

      1. UNKNOWN, whenever the ten-question check is incomplete or any of the
         six searches was inconclusive. Deciding anything else here would be
         deciding from evidence that does not exist.
      2. KEEP, when a real overlap exists and exact_gap is empty. Checked
         before REJECT because there is nothing to reject: the proposal is to
         change nothing.
      3. REJECT, when unrefuted counter-evidence coexists with a LOW recomputed
         confidence. Both halves come from the real score_confidence() result,
         never from a self-reported label.
      4. ENHANCE, whenever ANY existing asset was found and something is still
         missing. This is the default and the master prompt's stated preference;
         ADD is not reachable from here at all.
      5. ADD, only from a MISSING overlap -- every one of the six searches
         conclusive and empty -- AND a stated reason ENHANCE is insufficient
         AND HIGH recomputed confidence AND evidence_strength >= 3. Any one of
         those short falls back to EXPERIMENT, which is a proposal to go get
         the missing evidence, not a proposal to build.
    """
    unanswered = unanswered_l5_check_questions(candidate)
    overlap = derive_overlap_status(candidate)
    confidence = recompute_confidence(candidate)
    strength = int((candidate.get("evidence_strength") or {}).get("scale") or 0)
    counter = int(
        (candidate.get("confidence") or {}).get("inputs", {}).get("counter_evidence_count") or 0
    )
    gap = str(candidate.get("exact_gap", "")).strip()
    enhance_insufficient = str(candidate.get("enhance_insufficient_reason", "")).strip()

    def result(recommendation, overlap_status, rationale):
        return {
            "recommendation": recommendation,
            "overlap_status": overlap_status,
            "rationale": rationale,
            "confidence": confidence,
            "unanswered_l5_check_questions": unanswered,
            "next_best_action": next_actions_for_unanswered(candidate, root),
        }

    if unanswered or overlap == "UNKNOWN":
        return result(
            "UNKNOWN", "UNKNOWN",
            "the current-L5 check is not complete: "
            + (f"unanswered questions {unanswered}; " if unanswered else "")
            + "at least one of the six existing_* searches did not establish whether a "
              "match exists, so absence is not a finding. UNKNOWN is the answer, not MISSING.",
        )

    if overlap in ("EXISTS", "PARTIAL_MATCH") and not gap:
        return result(
            "KEEP", overlap,
            "a real existing asset already covers this and exact_gap names nothing "
            "missing -- the proposal is to change nothing.",
        )

    if counter > 0 and confidence["level"] == "LOW":
        return result(
            "REJECT", overlap,
            f"{counter} unrefuted counter-evidence entries coexist with a recomputed "
            "LOW confidence; the proposal is not supportable on its own evidence.",
        )

    if overlap in ("EXISTS", "PARTIAL_MATCH"):
        return result(
            "ENHANCE", overlap,
            "a real existing asset was found and exact_gap names what it does not yet "
            "cover, so the change belongs in that asset. ADD is unreachable while any "
            "search returned a match (master prompt sections 2.2 / 14).",
        )

    # overlap == "MISSING": every search was conclusive and found nothing.
    if enhance_insufficient and confidence["level"] == "HIGH" and strength >= 3:
        return result(
            "ADD", overlap,
            "all six searches were conclusive and empty, ENHANCE is explicitly ruled "
            f"out ({enhance_insufficient[:120]}), recomputed confidence is HIGH and "
            f"evidence_strength is {strength}.",
        )
    missing_preconditions = []
    if not enhance_insufficient:
        missing_preconditions.append("no stated reason ENHANCE is insufficient")
    if confidence["level"] != "HIGH":
        missing_preconditions.append(f"recomputed confidence is {confidence['level']}, not HIGH")
    if strength < 3:
        missing_preconditions.append(f"evidence_strength is {strength}, below 3")
    return result(
        "EXPERIMENT", overlap,
        "nothing existing was found, but ADD's preconditions are not met ("
        + "; ".join(missing_preconditions)
        + ") -- the next step is to go get that evidence, not to build.",
    )


def assert_legal_transition(from_status: Optional[str], to_status: str,
                            candidate: Optional[Dict[str, Any]] = None) -> None:
    """Section 70's "Do not skip governance states", enforced.

    The one forward edge that bypasses EXPERIMENT_APPROVED/EXPERIMENTING/
    BENCHMARKED -- PROPOSED -> PROMOTION_CANDIDATE -- is legal only for a
    candidate whose own experiment_required is False. That is not a loophole in
    the policy: those three states exist to hold an EXPERIMENT-class candidate,
    and a candidate that declares it needs one may not then walk around them.
    It shortens nothing on the human-approval half of the path.
    """
    if to_status not in PROMOTION_STATES:
        raise IllegalPromotionTransitionError(
            f"unknown promotion state {to_status!r}; must be one of {list(PROMOTION_STATES)}"
        )
    if from_status is not None and from_status not in PROMOTION_STATES:
        raise IllegalPromotionTransitionError(
            f"unknown current promotion state {from_status!r}"
        )
    allowed = LEGAL_TRANSITIONS.get(from_status, ())
    if to_status not in allowed:
        raise IllegalPromotionTransitionError(
            f"{from_status} -> {to_status} is not a legal transition. Legal from "
            f"{from_status}: {list(allowed)}. Master prompt section 70 forbids skipping "
            "governance states."
        )
    if from_status == "PROPOSED" and to_status == "PROMOTION_CANDIDATE":
        if candidate is None or candidate.get("experiment_required") is not False:
            raise IllegalPromotionTransitionError(
                "PROPOSED -> PROMOTION_CANDIDATE requires the candidate's own "
                "experiment_required to be False; a candidate that declares it needs an "
                "experiment must go through EXPERIMENT_APPROVED -> EXPERIMENTING -> "
                "BENCHMARKED"
            )


# ---------------------------------------------------------------------------
# Human Approval Gate. Reuses dv_harness/control_plane.py's real ControlPlane
# verbatim -- the Stage 0 audit confirmed it is genuinely wired (engine.loop()
# re-loads it every iteration) and that its `stage` key is an arbitrary string,
# not a models.Stage member, so this needs no new graph node and no parallel
# approval mechanism.


def human_approval_status(root) -> Dict[str, Any]:
    """The real approval state for HUMAN_APPROVAL_STAGE, read off
    .dv-harness/control.json through the real ControlPlane."""
    from .control_plane import ControlPlane

    cp = ControlPlane(Path(root))
    approval = cp.get_approval(HUMAN_APPROVAL_STAGE)
    return {
        "stage": HUMAN_APPROVAL_STAGE,
        "approved": approval is not None,
        "approval": approval,
        "history": cp.get_approval_history(HUMAN_APPROVAL_STAGE),
        "paused": cp.is_paused(),
        "takeover_active": cp.is_takeover_active_for(HUMAN_APPROVAL_STAGE),
        "approve_command": (
            f"dv-harness approve --stage {HUMAN_APPROVAL_STAGE} "
            "--note '<what you are approving>' --reviewer-id <you> "
            "--reviewer-confidence HIGH|MEDIUM|LOW"
        ),
    }


def assert_human_approval(root, candidate: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Raise HumanApprovalRequiredError unless a real human approval for
    HUMAN_APPROVAL_STAGE exists on disk. Returns the approval record.

    This is what makes PROMOTION_CANDIDATE -> HUMAN_APPROVED a real gate rather
    than a state an agent can write for itself: section 70's "a successful
    experiment does not automatically imply HUMAN_APPROVED", enforced.
    """
    status = human_approval_status(root)
    if not status["approved"]:
        cid = (candidate or {}).get("candidate_id", "<candidate>")
        raise HumanApprovalRequiredError(
            f"{cid}: no human approval recorded for stage {HUMAN_APPROVAL_STAGE}. "
            f"A human must run: {status['approve_command']}"
        )
    return status["approval"]


def assert_no_production_write_authorized(root, candidate: Dict[str, Any]) -> None:
    """The Stage 2/Stage 3 boundary as a callable check.

    Any caller about to touch a production file on a candidate's behalf calls
    this first. It raises unless the candidate is HUMAN_APPROVED or already in
    PRODUCTION *and* a real ControlPlane approval backs that. Nothing in this
    module ever writes a production file itself -- this exists so that a future
    Stage 3 caller cannot do so without passing the same gate.
    """
    current = candidate.get("current_status")
    if current not in PRODUCTION_WRITE_AUTHORIZED_STATES:
        raise ProductionWriteNotAuthorizedError(
            f"{candidate.get('candidate_id', '<candidate>')} is {current}; a production "
            f"file may only be touched from {list(PRODUCTION_WRITE_AUTHORIZED_STATES)}. "
            "Stage 3 requires separate explicit human approval."
        )
    assert_human_approval(root, candidate)


# ---------------------------------------------------------------------------
# Persistence. Blackboard for the live state machine, Working Memory for the
# per-transition audit trail -- both through the real existing mechanisms.


def build_candidate(**fields: Any) -> Dict[str, Any]:
    """Assemble a schema-valid candidate in its DISCOVERED state.

    Fills only what is mechanical -- schema_version, a content-derived
    candidate_id, the recomputed confidence result, the first status_history
    entry -- and validates. Everything analytical is the caller's, exactly as
    build_research_evidence_card_skeleton() splits the same way one layer up.
    """
    candidate = dict(fields)
    candidate.setdefault("schema_version", CANDIDATE_SCHEMA_VERSION)
    candidate.setdefault("current_status", "DISCOVERED")
    candidate.setdefault("promotion_status", candidate["current_status"])
    candidate.setdefault("final_decision", "PENDING")
    candidate.setdefault("enhance_insufficient_reason", "")
    candidate.setdefault("exact_gap", "")
    candidate.setdefault("experiment_plan", "")
    candidate.setdefault("benchmark_plan", "")

    if "candidate_id" not in candidate:
        candidate["candidate_id"] = mint_candidate_id(
            candidate.get("affected_capability", ""),
            candidate.get("hypothesis", ""),
            candidate.get("proposed_action", ""),
        )

    inputs = (candidate.get("confidence") or {}).get("inputs")
    if isinstance(inputs, dict):
        scored = score_confidence(**inputs)
        candidate["confidence"] = {**scored, "inputs": dict(inputs)}

    # The recommendation is DERIVED, never accepted. A caller may state what it
    # expects, and a disagreement is an error rather than an override: the agent
    # supplies the searches and the evidence counts, and this code makes the
    # decision from them. That is what keeps REUSE-before-EXTEND-before-ADD an
    # enforced rule instead of an instruction an LLM is trusted to follow.
    decision = decide_recommendation(candidate)
    for field, decided in (("recommendation", decision["recommendation"]),
                           ("overlap_status", decision["overlap_status"])):
        stated = candidate.get(field)
        if stated is not None and stated != decided:
            raise CapabilityEvolutionCandidateValidationError(
                f"caller stated {field}={stated!r} but this candidate's own evidence "
                f"decides {decided!r}: {decision['rationale']}"
            )
        candidate[field] = decided
    candidate["decision_rationale"] = decision["rationale"]

    if "status_history" not in candidate:
        candidate["status_history"] = [{
            "from_status": None,
            "to_status": candidate["current_status"],
            "at": _now(),
            "by": candidate.get("discovered_by") or "research-architect",
            "reason": candidate.get("hypothesis", "candidate discovered"),
        }]
    candidate.pop("discovered_by", None)

    validate_candidate(candidate)
    assert_confidence_recomputed(candidate)
    return candidate


def persist_candidate(root, candidate: Dict[str, Any], *, source: str = "research-architect",
                      cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Write the candidate to the ONE Blackboard topic that carries it, plus a
    Working Memory audit record through the real memory router.

    A decision is real, persisted state or it is nothing -- an agent's
    conversational output is not a record. Two writes, both through mechanisms
    that already existed:

      * Blackboard `capability_evolution_candidates`, the live state machine.
        Section 11 forbids a parallel Research Blackboard, and route_memory()
        already routes live-state kinds (`active_hypothesis`, `plan_state`)
        there, so this is the tier the existing router's own logic points at.
      * memory_router.route_and_store(), which routes CANDIDATE_MEMORY_KIND to
        WORKING_MEMORY through its existing fallthrough -- no new `kind` string
        was added to route_memory()'s dispatch table, per the Stage 0 audit's
        explicit recommendation.

    The routed destination is ASSERTED to be WORKING_MEMORY. That guard is the
    global constraint made mechanical: a single design/build session is not the
    "repeated, human-approved" evidence Engineering or Organizational tier
    requires, and this pass must not be able to promote anything there even by
    a later editing accident.

    Writes only under `<root>/.dv-harness/`. Nothing under `dv_harness/` or
    `.claude/` is opened for writing anywhere in this module.
    """
    from .memory_router import route_and_store

    validate_candidate(candidate)
    assert_confidence_recomputed(candidate)

    root = Path(root)
    Blackboard(root).upsert_capability_evolution_candidate(
        candidate["candidate_id"], candidate, source=source
    )

    record = {
        "kind": CANDIDATE_MEMORY_KIND,
        "candidate_id": candidate["candidate_id"],
        "affected_capability": candidate["affected_capability"],
        "current_status": candidate["current_status"],
        "recommendation": candidate["recommendation"],
        "overlap_status": candidate["overlap_status"],
        "confidence": candidate["confidence"]["level"],
        "hypothesis": candidate["hypothesis"],
        "proposed_action": candidate["proposed_action"],
        "evidence": list(candidate["evidence_refs"]),
        "blackboard_topic": BLACKBOARD_TOPIC,
        # Deliberately NOT `verified`. A candidate is a proposal about this
        # harness, never a verified engineering fact about a DUT, and
        # memory_router's engineering/organizational admission gates must never
        # see a truthy `verified` on one of these.
    }
    routed = route_and_store(root, record, cfg={} if cfg is None else cfg)
    if routed.get("destination") != "WORKING_MEMORY":
        raise CapabilityEvolutionCandidateValidationError(
            f"a capability-evolution candidate routed to {routed.get('destination')!r}; "
            "it must land in WORKING_MEMORY. A proposal from one design session is not "
            "verified engineering knowledge and must never reach the Engineering or "
            "Organizational tier."
        )
    return {"blackboard_topic": BLACKBOARD_TOPIC, "memory": routed}


def read_candidates(root) -> Dict[str, Any]:
    """Every live candidate, keyed by candidate_id."""
    return Blackboard(Path(root)).read_capability_evolution_candidates()["items"]


def read_candidate(root, candidate_id: str) -> Optional[Dict[str, Any]]:
    return read_candidates(root).get(candidate_id)


def candidate_audit_records(root, candidate_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The Working Memory audit trail, newest first, through the shared
    MemoryStore.find() this module is the first caller of."""
    from .memory import MemoryStore

    filters: Dict[str, Any] = {"kind": CANDIDATE_MEMORY_KIND}
    if candidate_id is not None:
        filters["candidate_id"] = candidate_id
    return MemoryStore(Path(root)).find("working", **filters)


def transition(root, candidate: Dict[str, Any], to_status: str, *, by: str, reason: str,
               cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Advance a candidate one governance state and persist the result.

    Returns the NEW candidate dict; the input is not mutated. A transition into
    HUMAN_APPROVED additionally requires a real ControlPlane approval on disk
    and copies that approval record into the status_history entry, so the
    candidate carries its own evidence that a human acted.
    """
    assert_legal_transition(candidate.get("current_status"), to_status, candidate)

    entry = {
        "from_status": candidate.get("current_status"),
        "to_status": to_status,
        "at": _now(),
        "by": by,
        "reason": reason,
    }
    if to_status == "HUMAN_APPROVED":
        entry["approval_ref"] = dict(assert_human_approval(root, candidate))

    updated = dict(candidate)
    updated["current_status"] = to_status
    updated["promotion_status"] = to_status
    updated["status_history"] = list(candidate.get("status_history", [])) + [entry]
    persist_candidate(root, updated, cfg=cfg)
    return updated


# ---------------------------------------------------------------------------
# Master prompt section 43's mandatory stop.


def stop_report_blockers(checklist: Dict[str, Any]) -> List[str]:
    """Which of section 43's nine preconditions are not complete, in order.

    Reuses inference.identify_gap() for the same reason
    unanswered_l5_check_questions() does.
    """
    complete = [k for k in STOP_REPORT_PRECONDITIONS if checklist.get(k) is True]
    return identify_gap(list(STOP_REPORT_PRECONDITIONS), complete)


def render_stop_report(checklist: Dict[str, Any]) -> str:
    """Section 43's report, EXACTLY -- seven lines then a blank line then STOP.

    Refuses to render while any of the nine preconditions is incomplete.
    Printing "L5.x PROPOSAL COMPLETE" over an incomplete proposal is a false
    claim to a human who is about to decide whether to approve it, which is the
    single most expensive kind of wrong output this whole pipeline can produce.
    The refusal names what is missing.
    """
    blockers = stop_report_blockers(checklist)
    if blockers:
        raise CapabilityEvolutionCandidateValidationError(
            "section 43's stop report may not be rendered while these preconditions are "
            f"incomplete: {blockers}"
        )
    return "\n".join(STOP_REPORT_LINES) + "\n\nSTOP."
