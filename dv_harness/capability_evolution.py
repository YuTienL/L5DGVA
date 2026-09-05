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

# The memory `kind` a candidate's audit record carries. It used to reach
# WORKING_MEMORY through route_memory()'s final fallthrough; since 2026-09-04 it
# has a NAMED branch there (memory_router.CAPABILITY_EVOLUTION_KINDS, master
# prompt section 12's memory-governance pass) which routes it to the same tier
# by decision instead of by default -- WORKING_MEMORY, or JOB_MEMORY for a
# record naming a real job_id. The destination for this module's own audit
# record is unchanged, which is why persist_candidate()'s WORKING_MEMORY
# assertion below still holds; what changed is that the tier is now documented
# and test-covered rather than incidental.
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
# THE THREE AUTONOMY LEVELS (master prompt section 61)
#
# This block sits here, immediately above assert_human_approval() and
# assert_no_production_write_authorized(), because those two functions ARE this
# module's LEVEL B -> LEVEL C boundary. A reader who needs to know which side of
# that boundary a piece of work is on should find the answer at the check that
# enforces it, not in a design document filed somewhere else.
#
#   LEVEL A -- RESEARCH AUTONOMY. Fully automatable. Ingest, extract claims,
#     collect and classify evidence, compare prior research, inspect current L5,
#     identify gaps, generate hypotheses, recommend KEEP/ENHANCE/ADD/EXPERIMENT/
#     REJECT, propose benchmarks, update temporary/job-level research state,
#     create architecture proposals, detect contradictions. MUST NOT MODIFY
#     PRODUCTION BEHAVIOR. Everything this module does today is Level A, which is
#     why the module header's "writes nothing outside <root>/.dv-harness/" claim
#     is a Level A statement and not an incidental one.
#
#   LEVEL B -- EXPERIMENT AUTONOMY. May be automated WITHIN existing policy:
#     isolated experiment plans, an experiment/feature branch, bounded reversible
#     changes, static checks, build, controlled simulation, targeted regression,
#     coverage, before/after benchmark, PROMOTE/REVISE/REJECT recommendation.
#     Two constraints, and the second is the one that gets forgotten:
#       (1) changes stay isolated and reversible;
#       (2) execution obeys the EXISTING security, resource, license,
#           remote-execution and repository policies, and NEVER bypasses an
#           existing human-approval requirement for an action current L5 policy
#           already classifies as consequential. Level B is permission to
#           automate work inside the fence, never permission to move the fence.
#
#   LEVEL C -- PRODUCTION PROMOTION. Always human-governed. A passing benchmark
#     is not a promotion: section 61's own closing line is "Never automatically
#     promote experimental capability into production merely because a benchmark
#     passed", which is exactly what assert_no_production_write_authorized()
#     refuses to let a caller do. Its nine named examples, and what really
#     enforces each one today, are LEVEL_C_EXAMPLES / LEVEL_C_ENFORCEMENT below.
#
# WHAT "NONE" MEANS IN LEVEL_C_ENFORCEMENT, stated once so the table is not
# read as more alarming or more reassuring than it is: every item below is
# covered at the LAST mile by the generic PR gate (item 1) once the change has
# to land on main/master, because git_governance.py keys on the destination
# branch and nothing else -- it does not care what the change was. "NONE" means
# there is no ITEM-SPECIFIC enforcement in front of that: nothing refuses the
# edit at the point it is made, nothing marks the touched artifact as
# consequential, and a human reviewing the resulting PR is the only thing
# standing between the change and production. Those items are named as an OPEN
# gap for a separate, dedicated effort. Building new production-safety
# enforcement was deliberately NOT attempted in the same pass that wrote this
# table: a safety mechanism authored by the same pass that decided it was needed
# has had no independent review, which is the failure mode this whole governance
# model exists to prevent.
#
# THE TABLE ITSELF LIVES IN dv_harness/autonomy_levels.py, not here, and the
# reason is a real constraint rather than tidiness: section 61's own example
# wording ("changing signoff policy", "changing regression selection policy used
# for signoff") contains vocabulary this module is forbidden by test to name at
# all. test_capability_evolution_research_architect.py's Acceptance Test E scans
# this file's non-comment source for verdict/signoff tokens, so that an edit
# giving this module verification authority fails before it ships. Writing the
# table here would have meant weakening that guard to accommodate a docstring --
# trading a real, enforced safety property for the convenience of co-locating
# prose with it. autonomy_levels.py is also the more honest home: LEVEL C's
# enforcement is spread across git_governance.py, self_tuning.py, gates.py,
# policy.py and memory_router.py, and belongs to none of them individually.
# Import it for LEVEL_C_EXAMPLES / LEVEL_C_ENFORCEMENT / LEVEL_C_UNENFORCED.

# ---------------------------------------------------------------------------
# Human Approval Gate -- the LEVEL B -> LEVEL C boundary in this module.
# Reuses dv_harness/control_plane.py's real ControlPlane
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
        # BUG FIX (2026-09-04, research-intent-routing pass): this string used
        # to read `approve --stage <STAGE>`, which is wrong twice and was
        # never run before being published -- `stage` is a POSITIONAL argument
        # on `dv-harness approve`, and its argparse `choices` admitted only
        # models.Stage members, so argparse rejected this stage key before
        # ControlPlane (which happily accepts any string) was ever reached.
        # The gate was therefore un-operable by the human it instructs.
        # commands.APPROVAL_ONLY_STAGES now admits HUMAN_APPROVAL_STAGE on the
        # `approve` verb only, and the form below is the one that really runs
        # (test_research_intent_routing.py executes it as a real subprocess).
        "approve_command": (
            f"dv-harness approve {HUMAN_APPROVAL_STAGE} "
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

    LEVEL C (see THE THREE AUTONOMY LEVELS above). Everything up to and including
    BENCHMARKED is Level A/B work this module may do unattended; crossing into
    HUMAN_APPROVED is not, no matter how the benchmark came out.
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

    LEVEL C (see THE THREE AUTONOMY LEVELS above). This is the only function in
    this module a Level B experiment path can call and be told "no": Level B may
    automate freely inside the existing fence, and this check is where the fence
    is. It authorizes touching a production file AT ALL. It does NOT by itself
    satisfy any of the nine item-specific LEVEL C rows in
    `autonomy_levels.LEVEL_C_ENFORCEMENT` -- five of which
    (`autonomy_levels.LEVEL_C_UNENFORCED`) have no item-specific enforcement to
    satisfy today, so a caller that clears this check is at the START of the
    LEVEL C obligations rather than the end of them.
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
        WORKING_MEMORY -- since 2026-09-04 through a named branch in
        route_memory() (memory_router.CAPABILITY_EVOLUTION_KINDS) rather than
        through its fallthrough, same destination either way.

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


# ---------------------------------------------------------------------------
# Master prompt section 28's cross-document comparison, and Stage-1 acceptance
# test G ("a new paper overlapping an existing Evidence Card -> overlap / new /
# contradiction status identified and linked").
#
# WHY IT LIVES HERE AND NOT IN doc_extraction.py / research-ingestion
# -------------------------------------------------------------------
# Section 27 forbids `research-ingestion` from looking at any other document
# while it writes a card -- independent convergence is the only thing in this
# tree that legitimately raises confidence, and it stops meaning anything the
# moment card #2 was written while reading card #1. So the comparator cannot be
# part of ingestion. Section 28 assigns cross-document synthesis to
# `research-architect`, and this module is that agent's machinery, so the
# comparator is an extension of it rather than a third research module.
#
# WHAT IT DELIBERATELY DOES NOT DO
# --------------------------------
#   * It never edits a card. A card is `research-ingestion`'s output and the
#     record of what ONE document says on its own; `related_prior_research` on a
#     card records what THAT DOCUMENT asserts about other work (the schema says
#     so), not what a later architect concluded about it. Writing an
#     architect-derived link back into that field would quietly destroy the
#     distinction section 27 exists to protect. The comparison is persisted as
#     its own Working Memory record instead.
#   * It never invents a relation vocabulary. The seven labels come from the
#     card schema itself via `doc_extraction.prior_research_relations()`; this
#     module holds no tuple of its own to drift from it.
#   * It never derives SUPPORTS or SUPERSEDES. Deciding that one document
#     corroborates or replaces another is a reading judgement, not something set
#     intersection can establish; those two are reachable only when a document
#     itself declares them, and a comparator that guessed them would fabricate
#     exactly the kind of agreement section 28 warns about.

EVIDENCE_CARD_DIR = ("research", "evidence_cards")
EVIDENCE_CARD_SUFFIX = ".card.json"

# The `kind` a cross-card comparison is stored under. An EXISTING
# memory_router.RESEARCH_EVIDENCE_KINDS member, not a new one: a comparison is a
# research-origin claim about two documents, it carries no job_id, and it
# therefore routes to WORKING_MEMORY through the same named branch every other
# research record uses. Section 12 forbids a sixth memory tier; adding a kind
# nothing else routes would be the same mistake one size down.
PRIOR_RESEARCH_LINK_MEMORY_KIND = "research_claim"

# The three relations that mean "these two documents do NOT stand together":
# CONTRADICTS is tracked on its own because it must never be read as
# convergence, and the other two are the outcomes of a comparison that found
# nothing to relate. Everything ELSE in the schema's enum is an overlap, which
# is why this is stated as the exclusion rather than as a second list of the
# overlap labels -- a copy of four of the seven would be a second vocabulary,
# and a relation added to the schema later would silently fall out of it.
_NON_OVERLAP_RELATIONS = ("CONTRADICTS", "UNRELATED", "INSUFFICIENT_EVIDENCE")


def prior_research_relations() -> List[str]:
    """Section 28's seven relation labels, read from the card schema."""
    from .doc_extraction import prior_research_relations as _relations

    return _relations()


def _norm_terms(values: Any) -> List[str]:
    """Lowercased, whitespace-collapsed strings from a card list field."""
    out: List[str] = []
    for value in values or []:
        if isinstance(value, str) and value.strip():
            out.append(" ".join(value.strip().lower().split()))
    return sorted(set(out))


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _declared_relation(new_card: Dict[str, Any], prior_document_id: str) -> Optional[str]:
    """What the NEW document itself says about the prior one, if anything.

    A document that names another work and labels the relation has already
    answered the question with more authority than any set operation here can,
    so a declaration wins over derivation -- except for CONTRADICTS, which is
    checked first and from more sources than the declaration alone.
    """
    for entry in new_card.get("related_prior_research") or []:
        if isinstance(entry, dict) and entry.get("document_id") == prior_document_id:
            relation = entry.get("relation")
            if relation in prior_research_relations():
                return relation
    return None


def _contradiction_signals(new_card: Dict[str, Any], prior_card: Dict[str, Any]) -> List[str]:
    """Every concrete reason to call this pair CONTRADICTS, named individually.

    Three sources, in increasing order of independence from the reader:
      1. the new card declares CONTRADICTS for this document_id;
      2. one of the new card's own `contradictions[].against` entries names the
         prior document by id or by title;
      3. both cards report a quantitative result for the SAME metric with
         DIFFERENT values -- the one contradiction two independently-written
         cards can establish without either card mentioning the other.
    A relation is never CONTRADICTS with this list empty, so "these disagree" is
    always traceable to something written on one of the two cards.
    """
    signals: List[str] = []
    prior_id = str(prior_card.get("document_id") or "")
    prior_title = _norm_text(prior_card.get("title"))

    if _declared_relation(new_card, prior_id) == "CONTRADICTS":
        signals.append(f"DECLARED_CONTRADICTS:{prior_id}")

    for entry in new_card.get("contradictions") or []:
        against = _norm_text((entry or {}).get("against"))
        if not against:
            continue
        if prior_id and prior_id.lower() in against:
            signals.append(f"AGAINST_DOCUMENT_ID:{prior_id}")
        elif prior_title and prior_title in against:
            signals.append(f"AGAINST_TITLE:{prior_card.get('title')}")

    prior_metrics: Dict[str, set] = {}
    for result in prior_card.get("quantitative_results") or []:
        metric = _norm_text((result or {}).get("metric"))
        value = _norm_text((result or {}).get("value"))
        if metric and value:
            prior_metrics.setdefault(metric, set()).add(value)
    for result in new_card.get("quantitative_results") or []:
        metric = _norm_text((result or {}).get("metric"))
        value = _norm_text((result or {}).get("value"))
        if not metric or not value or metric not in prior_metrics:
            continue
        if value not in prior_metrics[metric]:
            signals.append(
                f"METRIC_VALUE_CONFLICT:{metric}:{value}!={sorted(prior_metrics[metric])}"
            )
    return signals


def compare_evidence_cards(new_card: Dict[str, Any], prior_card: Dict[str, Any]) -> Dict[str, Any]:
    """One new card against ONE prior card -> a section-28 relation plus its basis.

    A pure function: reads no file, writes no file, calls no model, mutates
    neither card. Rule order, first match wins, and every rule records what it
    matched on so the relation can be re-derived by hand:

      1. INSUFFICIENT_EVIDENCE when either card states neither key_mechanisms
         nor verification_domain. There is nothing to compare, and UNRELATED
         would be a claim ("we checked, they are unrelated") the inputs do not
         support -- the same UNKNOWN-over-convenient-MISSING discipline
         derive_overlap_status() applies.
      2. OVERLAPS when the two cards carry the same document_sha256. Identical
         bytes ingested twice, flagged in the note as NOT independent
         corroboration, because counting a re-ingestion as convergence is
         exactly what section 28's "repeated vendor marketing is not
         convergence" line is about.
      3. CONTRADICTS on any signal from _contradiction_signals().
      4. Whatever the new document itself declared, when it declared something.
      5. EXTENDS when the shared mechanisms are ALL of the prior card's and the
         new card adds more; OVERLAPS when mechanisms are shared either way.
      6. OVERLAPS on a shared verification_domain with no shared mechanism.
      7. UNRELATED otherwise.
    """
    relations = prior_research_relations()
    new_mech = _norm_terms(new_card.get("key_mechanisms"))
    prior_mech = _norm_terms(prior_card.get("key_mechanisms"))
    new_domain = _norm_terms(new_card.get("verification_domain"))
    prior_domain = _norm_terms(prior_card.get("verification_domain"))
    shared_mech = sorted(set(new_mech) & set(prior_mech))
    new_only_mech = sorted(set(new_mech) - set(prior_mech))
    prior_only_mech = sorted(set(prior_mech) - set(new_mech))
    shared_domain = sorted(set(new_domain) & set(prior_domain))
    prior_id = str(prior_card.get("document_id") or "")
    identical = bool(
        new_card.get("document_sha256")
        and new_card.get("document_sha256") == prior_card.get("document_sha256")
    )
    declared = _declared_relation(new_card, prior_id)
    signals = _contradiction_signals(new_card, prior_card)

    if not (new_mech or new_domain) or not (prior_mech or prior_domain):
        relation = "INSUFFICIENT_EVIDENCE"
        note = (
            "One of the two cards states neither key_mechanisms nor "
            "verification_domain, so there is nothing to compare. Not UNRELATED: "
            "that would claim a comparison that did not happen."
        )
    elif identical:
        relation = "OVERLAPS"
        note = (
            f"Identical document bytes (sha256 {str(new_card.get('document_sha256'))[:12]}...) "
            "already ingested as this card. This is a re-ingestion, NOT a second "
            "independent source, and must not be counted as convergence."
        )
    elif signals:
        relation = "CONTRADICTS"
        note = "Contradiction signals: " + "; ".join(signals)
    elif declared is not None:
        relation = declared
        note = (
            f"Declared by the new document itself in related_prior_research for {prior_id}. "
            "A document's own statement about another work outranks anything derived here."
        )
    elif shared_mech and not prior_only_mech and new_only_mech:
        relation = "EXTENDS"
        note = (
            f"Covers every mechanism the prior card records ({', '.join(shared_mech)}) "
            f"and adds {', '.join(new_only_mech)}."
        )
    elif shared_mech:
        relation = "OVERLAPS"
        note = f"Shared mechanisms: {', '.join(shared_mech)}."
    elif shared_domain:
        relation = "OVERLAPS"
        note = (
            f"Shared verification domain ({', '.join(shared_domain)}) with no shared "
            "mechanism -- same problem area, different method."
        )
    else:
        relation = "UNRELATED"
        note = (
            "No shared mechanism and no shared verification domain, and the new "
            "document declares no relation to this one."
        )

    if relation not in relations:  # pragma: no cover - guards schema/code drift
        raise CapabilityEvolutionCandidateValidationError(
            f"{relation!r} is not one of the card schema's prior_research_link relations "
            f"{relations}; the comparator and the schema have drifted apart."
        )

    return {
        "document_id": prior_id,
        "relation": relation,
        "note": note,
        "basis": {
            "shared_mechanisms": shared_mech,
            "new_only_mechanisms": new_only_mech,
            "prior_only_mechanisms": prior_only_mech,
            "shared_verification_domain": shared_domain,
            "identical_document": identical,
            "declared_relation": declared,
            "contradiction_signals": signals,
        },
    }


def prior_research_link(comparison: Dict[str, Any]) -> Dict[str, Any]:
    """The comparison reduced to the card schema's own `prior_research_link`
    shape -- exactly document_id / relation / note, because that $def sets
    additionalProperties false. The full `basis` stays on the comparison and on
    the persisted memory record."""
    return {
        "document_id": comparison["document_id"],
        "relation": comparison["relation"],
        "note": comparison["note"],
    }


def read_evidence_cards(root, *, exclude_document_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every filed card under `research/evidence_cards/`, sorted by document_id.

    Only `*.card.json`: that directory's README documents an optional `<stem>.md`
    rendering beside each card, and reading that as evidence would treat a
    convenience copy as the canonical artifact.
    """
    directory = Path(root).joinpath(*EVIDENCE_CARD_DIR)
    cards: List[Dict[str, Any]] = []
    if not directory.is_dir():
        return cards
    for path in sorted(directory.glob(f"*{EVIDENCE_CARD_SUFFIX}")):
        card = json.loads(path.read_text(encoding="utf-8"))
        if exclude_document_id and card.get("document_id") == exclude_document_id:
            continue
        cards.append(card)
    cards.sort(key=lambda c: str(c.get("document_id") or ""))
    return cards


def link_prior_research(new_card: Dict[str, Any],
                        prior_cards: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Acceptance test G, whole: compare one new card against every prior card
    and report the overlap / new / contradiction status, linked by document_id.

    The three words in test G's own expectation are the three DERIVED booleans
    below, computed from the section-28 relation of each comparison. They are
    deliberately not a fourth status vocabulary: `has_overlap`,
    `has_contradiction` and `is_new` are projections of the seven relation
    labels the card schema already owns, so nothing here can disagree with a
    card's own `related_prior_research` about what OVERLAPS means.

    `is_new` means "every comparison came back UNRELATED or
    INSUFFICIENT_EVIDENCE", which includes the no-prior-cards case: a first
    document is trivially new.
    """
    new_id = str(new_card.get("document_id") or "")
    comparisons = [
        compare_evidence_cards(new_card, prior)
        for prior in prior_cards
        if str(prior.get("document_id") or "") != new_id
    ]
    relations = [c["relation"] for c in comparisons]
    has_contradiction = "CONTRADICTS" in relations
    has_overlap = any(r not in _NON_OVERLAP_RELATIONS for r in relations)
    return {
        "document_id": new_id,
        "compared_against": [c["document_id"] for c in comparisons],
        "comparisons": comparisons,
        "links": [prior_research_link(c) for c in comparisons],
        "relations": sorted(set(relations)),
        "has_overlap": has_overlap,
        "has_contradiction": has_contradiction,
        "is_new": not (has_overlap or has_contradiction),
    }


def persist_prior_research_links(root, summary: Dict[str, Any], *,
                                 source: str = "research-architect",
                                 cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Write one Working Memory record per comparison, through the real router.

    Same two disciplines persist_candidate() follows, for the same reasons: the
    write goes through `memory_router.route_and_store()` rather than straight at
    a tier, and the routed destination is ASSERTED to be WORKING_MEMORY. One
    architect's reading of two external documents in one session is not verified
    engineering knowledge about any DUT, and it must not be able to reach the
    Engineering or Organizational tier even by a later editing accident.

    Nothing here edits either card. `research/evidence_cards/` is never opened
    for writing anywhere in this module.
    """
    from .memory_router import route_and_store

    written: List[Dict[str, Any]] = []
    for comparison in summary.get("comparisons", []):
        record = {
            "kind": PRIOR_RESEARCH_LINK_MEMORY_KIND,
            "document_id": summary["document_id"],
            "prior_document_id": comparison["document_id"],
            "relation": comparison["relation"],
            "note": comparison["note"],
            "basis": comparison["basis"],
            "source": source,
            # Deliberately NOT `verified`, and deliberately carrying no
            # `confidence`: a relation between two external documents is not a
            # confidence-scored finding about this project, and putting a number
            # here would hand the engineering admission gate one nothing
            # measured.
        }
        routed = route_and_store(Path(root), record, cfg={} if cfg is None else cfg)
        if routed.get("destination") != "WORKING_MEMORY":
            raise CapabilityEvolutionCandidateValidationError(
                f"a cross-card research comparison routed to {routed.get('destination')!r}; "
                "it must land in WORKING_MEMORY. One session's reading of two external "
                "documents is not verified engineering knowledge."
            )
        written.append(routed)
    return written


# ---------------------------------------------------------------------------
# CROSS-LOOP COUPLING (2026-09-05): the Verification Closure Loop raising a
# candidate in the Capability Evolution Loop, automatically.
#
# THE GAP THIS CLOSES. All three loops were individually real and firing --
# verification closure through engine.run_stage()'s gates, project learning
# through memory_router's tier promotions, capability evolution through this
# module's state machine -- and the COUPLING between the first and the third
# was not. A repo-wide grep confirmed router.resolve_intent() (the research
# route) has no caller in engine.py, so this module was reachable only by a
# human typing `dv-harness research <doc>`. Repeated verification evidence --
# the same real failure recurring across independent runs and never being
# closed -- could accumulate in Job Memory forever without ever raising a
# question about the harness's own capability. That is the DORMANT shape the
# Methodology Consolidation Rule warns about, one level up: not an unwired
# module, but two wired loops with no edge between them.
#
# WHAT IS AUTOMATED AND WHAT IS EMPHATICALLY NOT. Only DISCOVERY. This code
# files a candidate at DISCOVERED and can reach no further state, for three
# independent reasons, each of which alone would be sufficient:
#
#   1. file_repeated_failure_candidate() refuses to persist anything whose
#      current_status is not DISCOVERED, and never calls transition().
#   2. An auto-filed candidate has performed NO repository search, and says so
#      -- all six existing_* slots carry search_conclusive false with an honest
#      search_basis. derive_overlap_status() therefore returns UNKNOWN and
#      decide_recommendation() returns UNKNOWN, and the candidate schema's own
#      allOf then pins current_status to DISCOVERED/EVIDENCE_GATHERING/REJECTED.
#      Reaching PROPOSED requires six conclusive searches that only a real
#      research-architect pass can produce. The wall is structural, not a
#      policy this function is trusted to respect.
#   3. Every gate above EVIDENCE_GATHERING is untouched: assert_legal_transition()
#      still forbids skipping states, assert_human_approval() still consults the
#      real ControlPlane, and HumanApprovalRequiredError /
#      ProductionWriteNotAuthorizedError are not weakened by one line here.
#
# WHY IT REUSES rather than adds. The evidence is read through the SAME
# MemoryStore.find() the rest of this module already uses; the failure identity
# is evidence_db.signature_key() -- the stable hash the evidence store already
# accumulates occurrence_count on, never a second definition of "the same
# failure"; the candidate is assembled by build_candidate() and written by
# persist_candidate(), so it lands on the one Blackboard topic and the one
# Working Memory audit trail every other candidate uses. Nothing here is a
# parallel mechanism.

# How many INDEPENDENT runs must record the same failure signature before the
# recurrence is treated as evidence about the harness rather than about one
# run. Two, matching memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS' reasoning
# for the same reason it uses that number: a second independent run re-deriving
# the same thing is the smallest observation that cannot be one run reported
# twice.
REPEAT_FAILURE_MIN_OCCURRENCES = 2

# The Job Memory kind engine._record_debug_attempt_job_memory() and
# lsf_client._write_job_tier_memory_on_terminal_reconcile() actually write, and
# the only kind that carries a real build_failure_signature() dict.
REPEAT_FAILURE_JOB_MEMORY_KIND = "job_failure"

# The Engineering Memory kind that means "this failure was closed". Deliberately
# only verified_fix: engine._promote_verified_fix_knowledge() writes it exactly
# once, on a RE_AUDIT verdict whose fix_effectiveness_gate and
# fix_regression_non_regression_gate both cleared, so its presence is a
# gate-verified closure rather than an agent's report of one. A bare root_cause
# or debug_lesson record is an explanation, not a closure, and counting either
# would let an unfixed failure look resolved.
RESOLVING_ENGINEERING_MEMORY_KIND = "verified_fix"

# Master prompt section 64's gap-detection source this coupling supplies.
AUTO_DISCOVERY_TRIGGER_TYPE = "FAILURE_PATTERN"

# Recorded in status_history.by and as the Blackboard write's source, so a
# human reading the candidate can tell an auto-filed one from a
# research-architect one without inferring it from the field contents.
AUTO_DISCOVERY_BY = "verification-closure-loop"

# The bucket a job_failure record with neither job_id nor git_sha falls into.
# Such records are grouped TOGETHER and contribute ZERO independent runs, never
# one each: two records that cannot be told apart as separate runs are not
# evidence of two runs, and treating them as such is exactly how a single bad
# session would manufacture its own capability proposal.
UNIDENTIFIED_RUN = "<no-run-identity-recorded>"

# Which of section 14's ten questions each of the six search slots answers,
# inverted from the existing L5_QUESTION_FIELD map rather than retyped, so the
# auto-filed search_basis can quote that question's real next-best-action text
# out of RESEARCH_GAP_ACTION_CATALOG instead of inventing a parallel one.
_SLOT_QUESTION = {
    L5_QUESTION_FIELD[q]: q
    for q in L5_CHECK_QUESTIONS
    if L5_QUESTION_FIELD[q] in L5_SEARCH_SLOTS
}


def failure_resolution_claims(failure_signature: Optional[Dict[str, Any]]) -> List[str]:
    """The normalized claim texts a verified_fix record would have to name for
    this failure signature to count as closed.

    Exactly the signature's own `symptom` and `root_cause_hint`, and matching is
    exact equality after whitespace/case normalization -- never substring, never
    scoring. That is not a shortcut: those two fields are sourced by
    engine._gather_stage_context() from the Blackboard `findings` topic's
    last_report (`symptom`, and `root_cause` falling back to
    `failure_signature_before`), and engine._promote_verified_fix_knowledge()
    sources a verified_fix record's `root_cause`/`symptoms` from the SAME
    evidence blocks that topic is written from. The two really are the same
    strings on the real path, so an exact join is a real join. A fuzzy one would
    quietly mark unrelated failures resolved, which is the more expensive error:
    it would suppress a candidate rather than raise a spurious one.
    """
    claims = []
    for field in ("symptom", "root_cause_hint"):
        text = _norm_text((failure_signature or {}).get(field))
        if text:
            claims.append(text)
    return sorted(set(claims))


def resolved_failure_claim_texts(root) -> List[str]:
    """Every normalized claim text an Engineering Memory verified_fix record
    names, through the shared MemoryStore.find() this module already uses."""
    from .memory import MemoryStore

    texts = set()
    for record in MemoryStore(Path(root)).find(
        "engineering", kind=RESOLVING_ENGINEERING_MEMORY_KIND
    ):
        candidates = [record.get("root_cause")] + list(record.get("symptoms") or [])
        for value in candidates:
            text = _norm_text(value)
            if text:
                texts.add(text)
    return sorted(texts)


def _run_identity(record: Dict[str, Any]) -> str:
    """What makes two job_failure records INDEPENDENT evidence.

    The run, and only the run -- a real job_id, else the commit the attempt ran
    against. Deliberately NOT the stage or the attempt number: engine.py writes
    one of these records per failed attempt, so a single stage retrying three
    times against one commit would otherwise present itself as three
    independent confirmations of a harness-level gap. Same discipline
    memory_router's confirmation counting applies to the Engineering tier.
    """
    for field in ("job_id", "git_sha"):
        value = str(record.get(field) or "").strip()
        if value:
            return f"{field}:{value}"
    return UNIDENTIFIED_RUN


def repeated_unresolved_failure_patterns(
    root, *, min_occurrences: int = REPEAT_FAILURE_MIN_OCCURRENCES
) -> List[Dict[str, Any]]:
    """Every failure signature that `min_occurrences` INDEPENDENT runs recorded
    in Job Memory and that no Engineering Memory verified_fix record closes.

    A pure read: opens no file for writing and files nothing. The returned dicts
    carry the whole basis of the finding -- the signature itself, the
    contributing memory_ids, the run identities that made them independent, and
    the resolution claims that were checked -- so a reader can re-derive the
    decision by hand rather than trusting the count.
    """
    from .evidence_db import signature_key
    from .memory import MemoryStore

    min_occurrences = int(min_occurrences)
    if min_occurrences < 2:
        raise ValueError(
            f"min_occurrences must be at least 2, got {min_occurrences}: a single "
            "occurrence is one run's circumstances, not a repeated pattern, and "
            "filing a capability proposal from it is what section 64 forbids"
        )

    resolved = set(resolved_failure_claim_texts(root))
    groups: Dict[str, Dict[str, Any]] = {}
    for record in MemoryStore(Path(root)).find(
        "job", kind=REPEAT_FAILURE_JOB_MEMORY_KIND
    ):
        signature = record.get("failure_signature")
        if not isinstance(signature, dict):
            continue
        key = signature_key(signature)
        group = groups.setdefault(key, {
            "signature_key": key,
            "failure_signature": signature,
            "memory_ids": [],
            "run_identities": [],
        })
        memory_id = str(record.get("memory_id") or "").strip()
        if memory_id and memory_id not in group["memory_ids"]:
            group["memory_ids"].append(memory_id)
        run = _run_identity(record)
        if run != UNIDENTIFIED_RUN and run not in group["run_identities"]:
            group["run_identities"].append(run)

    patterns: List[Dict[str, Any]] = []
    for key in sorted(groups):
        group = groups[key]
        group["memory_ids"] = sorted(group["memory_ids"])
        group["run_identities"] = sorted(group["run_identities"])
        group["occurrence_count"] = len(group["memory_ids"])
        group["independent_run_count"] = len(group["run_identities"])
        group["resolution_claims"] = failure_resolution_claims(group["failure_signature"])
        group["resolved_by_verified_fix"] = sorted(
            set(group["resolution_claims"]) & resolved
        )
        group["min_occurrences"] = min_occurrences
        if group["resolved_by_verified_fix"]:
            continue
        if group["independent_run_count"] < min_occurrences:
            continue
        patterns.append(group)
    return patterns


def _auto_filed_search_slot(slot: str) -> Dict[str, Any]:
    """A search slot that honestly records that no search happened.

    `matches` empty with `search_conclusive` FALSE is the whole point: an empty
    conclusive search would be a claim of absence this code has no basis for,
    and MISSING is what licenses an ADD. The basis text quotes the real
    next-best-action RESEARCH_GAP_ACTION_CATALOG already holds for that
    question, so the slot names the search someone must actually run.
    """
    return {
        "matches": [],
        "search_basis": (
            "NOT SEARCHED -- filed automatically by the verification closure loop from "
            "repeated Job Memory evidence, with no repository search performed, so "
            "absence is not established and this candidate cannot leave "
            "EVIDENCE_GATHERING. Run: "
            + RESEARCH_GAP_ACTION_CATALOG["actions"][_SLOT_QUESTION[slot]]
        ),
        "search_conclusive": False,
    }


def _failure_signature_summary(signature: Dict[str, Any]) -> str:
    """A stable, human-readable digest of a failure signature.

    Stable is the requirement, not pretty: this text is part of `hypothesis`,
    which is part of candidate_id's hash input, so it must depend only on the
    signature itself and never on how many times it has been seen. That is what
    makes a recurrence in a later cycle land on the SAME candidate record and
    accumulate evidence instead of forking a duplicate.
    """
    parts = []
    for field in ("protocol", "pattern", "symptom", "root_cause_hint",
                  "terminal_signature", "lsf_status"):
        value = _norm_text(signature.get(field))
        if value:
            parts.append(f"{field}={value}")
    for flag in ("assertion_failure", "simulator_crash", "abnormal_termination"):
        if signature.get(flag):
            parts.append(f"{flag}=true")
    for counter in ("uvm_error_count", "uvm_fatal_count"):
        value = signature.get(counter)
        if isinstance(value, int) and value > 0:
            parts.append(f"{counter}={value}")
    return "; ".join(parts)[:400] or "no descriptive field recorded on the signature"


def build_repeated_failure_candidate(
    root, pattern: Dict[str, Any], *,
    status_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assemble the DISCOVERED candidate for one repeated unresolved failure.

    Goes through the ordinary build_candidate(), so the recommendation is
    DERIVED (it comes out UNKNOWN, because no search was performed), the
    confidence is recomputed through the real inference.score_confidence(), and
    the whole thing is schema-validated before it exists. Nothing here is a
    second candidate constructor.

    `independent_sources_count` is the INDEPENDENT RUN count, never the record
    count -- three retries of one stage against one commit are one source.
    `evidence_refs_verified` is true because every memory_id in evidence_refs
    was read off disk by repeated_unresolved_failure_patterns() a moment ago,
    which is what that flag means; it is not a claim about the failure's cause.
    `evidence_strength` is 2 (a real observation, not a controlled experiment),
    which by itself keeps ADD unreachable even if every search later came back
    conclusive and empty.
    """
    from .doc_extraction import evidence_ref

    signature = pattern["failure_signature"]
    key = pattern["signature_key"]
    summary = _failure_signature_summary(signature)
    memory_ids = list(pattern["memory_ids"])
    job_dir = Path(root) / ".dv-harness" / "memory" / "job"

    fields: Dict[str, Any] = {
        "trigger_source": f"job_memory:failure_signature:{key}",
        "trigger_type": AUTO_DISCOVERY_TRIGGER_TYPE,
        "source_provenance": [
            evidence_ref(
                document=str(job_dir / f"{memory_id}.json"),
                version=key[:12],
                page="",
                section=f"kind={REPEAT_FAILURE_JOB_MEMORY_KIND} failure_signature",
                location=memory_id,
            )
            for memory_id in memory_ids
        ],
        "evidence_refs": memory_ids,
        "affected_capability": "automated-failure-resolution",
        "hypothesis": (
            f"Failure signature {key[:12]} ({summary}) recurs across independent runs "
            "and the harness's automated failure-resolution loop closes none of them: "
            "no Engineering Memory verified_fix record names its symptom or its root "
            "cause. The recurrence is evidence about a capability this harness does "
            "not have, not about one run's circumstances."
        ),
        "proposed_action": (
            "No production change is proposed. Run the mandatory current-L5 check over "
            "this failure class -- the six existing_* searches this candidate filed as "
            "NOT SEARCHED -- and let decide_recommendation() derive KEEP/ENHANCE/ADD/"
            "EXPERIMENT from the real result. `dv-harness research` is the human entry "
            "point that operates that machinery."
        ),
        "exact_gap": "",
        "expected_verification_benefit": (
            "Failures matching this signature stop consuming repeated debug cycles that "
            "end without a verified fix: triage time per recurrence drops, and the "
            "recurrence stops being visible only inside one job's memory."
        ),
        "evidence_strength": {
            "scale": 2,
            "rationale": (
                f"{pattern['independent_run_count']} independent runs recorded this exact "
                f"signature ({pattern['occurrence_count']} Job Memory records) and none "
                "was closed by a gate-verified fix. That is a real repeated observation, "
                "not a controlled experiment comparing a change against a baseline."
            ),
        },
        "confidence": {
            "inputs": {
                "independent_sources_count": int(pattern["independent_run_count"]),
                "evidence_refs_verified": True,
                "counter_evidence_count": 0,
                "multi_agent_consensus_count": 0,
            }
        },
        "implementation_difficulty": "UNKNOWN",
        "integration_risk": "UNKNOWN",
        "maintenance_cost": "UNKNOWN",
        "experiment_required": False,
        "experiment_plan": "",
        "benchmark_plan": "",
        "acceptance_criteria": [
            "All six existing_* searches are re-run with search_conclusive true, so "
            "overlap_status stops being UNKNOWN.",
            f"Either a verified_fix record closing failure signature {key[:12]} exists, "
            "or a named harness capability is shown to be the thing that is missing.",
            "The recommendation is derived by decide_recommendation() from those "
            "searches, never asserted by an agent.",
        ],
        "rollback_plan": (
            f"Filing applies nothing: one Blackboard entry under '{BLACKBOARD_TOPIC}' and "
            "one Working Memory audit record, no production file touched. The undo is a "
            "REJECTED transition, which is legal directly from DISCOVERED. Any concrete "
            "change a later architect proposes must author its own rollback_plan before "
            "it may leave EVIDENCE_GATHERING."
        ),
        "approval_level": "HUMAN_APPROVAL_REQUIRED",
        "discovered_by": AUTO_DISCOVERY_BY,
    }
    for slot in L5_SEARCH_SLOTS:
        fields[slot] = _auto_filed_search_slot(slot)
    if status_history is not None:
        fields["status_history"] = [dict(entry) for entry in status_history]

    candidate = build_candidate(**fields)
    if candidate["current_status"] != "DISCOVERED":
        raise IllegalPromotionTransitionError(
            f"an auto-filed candidate was assembled at {candidate['current_status']!r}; "
            "the verification closure loop may only ever file at DISCOVERED"
        )
    return candidate


def file_repeated_failure_candidate(root, pattern: Dict[str, Any], *,
                                    cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """File (or refresh) ONE candidate for a repeated unresolved failure.

    Never transitions. Three outcomes, and the first two write nothing:

      * ALREADY_BEYOND_DISCOVERED -- a human or a research-architect has already
        moved this candidate on. Re-filing would drag it backwards and overwrite
        their work, so this returns instead. This is the one branch that makes
        "auto-file at DISCOVERED only" true across cycles rather than only on
        the first one.
      * ALREADY_ON_FILE_UNCHANGED -- same candidate, same contributing records.
        Re-persisting would append a duplicate Working Memory audit record on
        every failed stage attempt for no new information.
      * filed -- new, or the same candidate with genuinely new contributing
        records. The existing status_history is carried forward untouched: no
        state changed, so no transition entry is owed and none is invented.
    """
    candidate = build_repeated_failure_candidate(root, pattern)
    candidate_id = candidate["candidate_id"]
    existing = read_candidate(root, candidate_id)

    if existing is not None:
        current = existing.get("current_status")
        if current != "DISCOVERED":
            return {
                "filed": False, "reason": "ALREADY_BEYOND_DISCOVERED",
                "candidate_id": candidate_id, "current_status": current,
                "signature_key": pattern["signature_key"],
            }
        if list(existing.get("evidence_refs") or []) == candidate["evidence_refs"]:
            return {
                "filed": False, "reason": "ALREADY_ON_FILE_UNCHANGED",
                "candidate_id": candidate_id, "current_status": current,
                "signature_key": pattern["signature_key"],
            }
        candidate = build_repeated_failure_candidate(
            root, pattern, status_history=list(existing.get("status_history") or [])
        )

    persisted = persist_candidate(root, candidate, source=AUTO_DISCOVERY_BY, cfg=cfg)
    return {
        "filed": True,
        "reason": "NEW_EVIDENCE" if existing is not None else "DISCOVERED",
        "candidate_id": candidate_id,
        "current_status": candidate["current_status"],
        "signature_key": pattern["signature_key"],
        "independent_run_count": pattern["independent_run_count"],
        "evidence_refs": list(candidate["evidence_refs"]),
        "persisted": persisted,
    }


def file_candidates_for_repeated_failures(
    root, *, min_occurrences: int = REPEAT_FAILURE_MIN_OCCURRENCES,
    cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """The whole coupling, as one call an engine hook can make.

    Detect every repeated unresolved failure pattern, file a DISCOVERED
    candidate for each, and report what happened to every one -- including the
    ones deliberately left alone. Raises nothing it can help; its engine caller
    treats any failure as best-effort, because a capability-evolution
    bookkeeping problem must never turn an already-computed stage result into a
    crash.
    """
    return [
        file_repeated_failure_candidate(root, pattern, cfg=cfg)
        for pattern in repeated_unresolved_failure_patterns(
            root, min_occurrences=min_occurrences
        )
    ]
