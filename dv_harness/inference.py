"""Deterministic Hypothesis -> Evidence -> Confidence -> Gap -> Next-Best-Action
scoring module.

This implements, as real Python, the confidence/gap/next-action math that the
CORE skills (hypothesis-generation, hypothesis-ranking, next-best-action,
inference-confidence-gate) previously only described in prose. The confidence
level strings are intentionally kept to the 3 values gates.py already defines
in REVIEWER_CONFIDENCE_LEVELS ("HIGH", "MEDIUM", "LOW") -- current evidence
(gates.py) wins over any skill prose that mentions a 4th "CONFIRMED" level.

NOT the same thing as the two TIER classifiers (2026-09-04). Two sibling
modules also rank how much a decision can be trusted, and both were built on
2026-09-03, the day BEFORE this module got its first real caller -- so
neither could have reused it and neither does today:
`connectivity.classify_bind_tier()` (T1_ALREADY_DECIDED / T2_STRUCTURAL_MATCH
/ T3_NAMING_HEURISTIC / T4_UNDECIDABLE) and `question_queue.classify_tier()`
(SELF_RESOLVE / SAFE_TO_ASSUME / CANNOT_ASSUME). They are deliberately NOT
folded into score_confidence(), and the reason is semantic, not historical:

  - score_confidence() scores evidence QUANTITY. It counts independent
    sources, adds a verified-refs bonus, subtracts counter-evidence, and
    the result is ordinal and additive -- more corroboration scores higher.
  - Both tier classifiers rank evidence KIND, in strict priority order, and
    the ranking is NOT a function of any count. A single already-existing
    bind (T1) outranks a structural fingerprint match on several signals
    (T2) precisely because of WHERE the evidence came from, not how much of
    it there is; T3's `requires_human_confirmation` is hard-coded True with
    no input that can flip it; and question_queue's Tier 3 is an ESCALATION
    ROUTE ("a human must decide this"), not a low score.

Mapping either onto this module's four counts would lose exactly the
property they exist for. Counting T1's one existing bind as one verified
independent source scores 1*2 + 2 = 4 -> MEDIUM, the same MEDIUM a T2
structural match scores -- so the strict T1 > T2 ordering collapses, and
the highest-trust bind tier in the codebase reports as merely MEDIUM
confidence. The two vocabularies therefore share no token with
CONFIDENCE_LEVELS by design, the same way protocol_capability.py's
`capability_status` deliberately shares none with qualification.py's tier
ladder. `dv_harness_tests/test_confidence_vocabulary_separation.py` holds
that separation, and this rationale, in place so a future auditor finding
"three confidence-ish mechanisms, none consolidated" does not have to
re-derive whether that is a defect.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .human_correction_lesson import has_prior_correction

CONFIDENCE_LEVELS = ["HIGH", "MEDIUM", "LOW"]


def _require_non_negative_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a non-negative int, got {value!r}")
    if value < 0:
        raise ValueError(f"{name} must be a non-negative int, got {value!r}")


def score_confidence(independent_sources_count, evidence_refs_verified, counter_evidence_count,
                      multi_agent_consensus_count):
    """Score confidence per the DV-expert-specified formula.

    base = min(independent_sources_count, 3) * 2
           + (2 if evidence_refs_verified else 0)
           - counter_evidence_count * 3
    if multi_agent_consensus_count >= 2: base += 2
    level = HIGH if base >= 6 else MEDIUM if base >= 3 else LOW

    Safety floor: known unaddressed counter-evidence (counter_evidence_count > 0)
    can never coexist with a reported HIGH level -- it is downgraded to MEDIUM
    and capped_by_counter_evidence is set True.
    """
    _require_non_negative_int(independent_sources_count, "independent_sources_count")
    _require_non_negative_int(counter_evidence_count, "counter_evidence_count")
    _require_non_negative_int(multi_agent_consensus_count, "multi_agent_consensus_count")
    if not isinstance(evidence_refs_verified, bool):
        raise ValueError(
            f"evidence_refs_verified must be a bool, got {evidence_refs_verified!r}"
        )

    base = min(independent_sources_count, 3) * 2
    base += 2 if evidence_refs_verified else 0
    base -= counter_evidence_count * 3
    if multi_agent_consensus_count >= 2:
        base += 2

    level = "HIGH" if base >= 6 else "MEDIUM" if base >= 3 else "LOW"

    capped_by_counter_evidence = False
    if counter_evidence_count > 0 and level == "HIGH":
        level = "MEDIUM"
        capped_by_counter_evidence = True

    return {
        "level": level,
        "score": base,
        "capped_by_counter_evidence": capped_by_counter_evidence,
    }


#: The `mistake_category` this module's own correction-check queries
#: `human_correction_lesson.py` under. A distinct, stable string so a
#: correction filed against a confidence-scoring judgment can never be
#: confused with one filed elsewhere against the same `judgment_key`.
CONFIDENCE_SCORE_MISTAKE_CATEGORY = "confidence_score"


def score_confidence_checked(independent_sources_count, evidence_refs_verified,
                              counter_evidence_count, multi_agent_consensus_count,
                              *, root, judgment_key: str) -> Dict[str, Any]:
    """Additive, opt-in sibling of `score_confidence()` that ALSO checks
    whether a human has already corrected THIS EXACT confidence judgment
    before this function recomputes and re-emits it -- via
    `human_correction_lesson.has_prior_correction()`, reused verbatim, never
    re-derived. `score_confidence()` itself, its exact formula, its 4
    -positional-int signature and every existing caller of it are completely
    UNCHANGED by this function.

    `score_confidence()` is a domain-neutral scoring engine with no notion
    of WHAT is being scored, so unlike a text classifier there is no input
    text to key a correction lookup on. `judgment_key` supplies that missing
    identity -- a caller-chosen, stable string naming the specific fact this
    confidence score is about (e.g. a `"<protocol>/<root_cause>"` pair, or a
    `memory_id`) -- so the exact-match lookup below can never confuse two
    different judgments that merely happen to score the same confidence
    level. The before-claim checked is the exact assertion this call is
    about to re-emit: `"<judgment_key>: confidence=<level>"`.

    Never overrides the recomputed score with a prior correction's own
    free-text `after_claim` -- per `human_correction_lesson.py`'s own stated
    boundary, this module does not decide whether a human's correction is
    itself correct. A real prior correction is surfaced on the returned
    dict's own `prior_human_correction` key instead, so a caller can see
    "this exact confidence judgment was already corrected once" before
    trusting the freshly recomputed score, without this function silently
    substituting an unverified value for its own deterministic math.

    `root` and `judgment_key` are required keyword-only arguments, so this
    checked variant can never be called with the check silently skipped by
    a missing default; a caller with no project root or no stable identity
    for the judgment should call the plain `score_confidence()` instead."""
    result = score_confidence(independent_sources_count, evidence_refs_verified,
                               counter_evidence_count, multi_agent_consensus_count)
    if judgment_key and str(judgment_key).strip():
        before_claim = f"{judgment_key}: confidence={result['level']}"
        report = has_prior_correction(
            root, before_claim=before_claim, mistake_category=CONFIDENCE_SCORE_MISTAKE_CATEGORY,
        )
        if report.get("found"):
            result = dict(result)
            result["prior_human_correction"] = report
    return result


@dataclass(frozen=True)
class DissentingClaim:
    """One agent's cited disagreement inside a ConsensusResult.

    `agent` and `claim` are required, non-empty strings -- an anonymous or
    empty dissent cannot be weighed against the majority. `evidence` is a
    citation for the dissent (a file:line, a log excerpt path, an evidence_id)
    and defaults to "" (not yet cited) rather than raising, since a caller may
    be recording a dissent before its evidence has been collected -- the
    consensus math below never trusts an uncited dissent for anything beyond
    counting it.
    """

    agent: str
    claim: str
    evidence: str = ""

    def __post_init__(self):
        if not isinstance(self.agent, str) or not self.agent.strip():
            raise ValueError(f"DissentingClaim.agent must be a non-empty string, got {self.agent!r}")
        if not isinstance(self.claim, str) or not self.claim.strip():
            raise ValueError(f"DissentingClaim.claim must be a non-empty string, got {self.claim!r}")
        if not isinstance(self.evidence, str):
            raise ValueError(f"DissentingClaim.evidence must be a string, got {self.evidence!r}")


@dataclass(frozen=True)
class ConsensusResult:
    """A typed multi-agent-consensus record -- who agreed, who disagreed, who
    abstained, and (optionally) each dissenter's own cited claim.

    This is the ADDITIVE replacement for score_confidence()'s bare
    `multi_agent_consensus_count` int, which can only ever say "N agents were
    in consensus" and cannot distinguish 5 agents unanimously agreeing from 3
    agreeing and 2 actively disagreeing -- both currently score identically
    (>=2 => the same flat +2 bonus). `score_confidence()` itself, and every
    existing caller's positional/keyword `multi_agent_consensus_count=<int>`
    call, is completely UNCHANGED by this class -- see
    `score_confidence_with_consensus()` below, the new, separate, opt-in path
    that actually consumes it.
    """

    agree_count: int
    disagree_count: int
    abstain_count: int = 0
    dissenting_claims: Tuple[DissentingClaim, ...] = field(default_factory=tuple)

    def __post_init__(self):
        _require_non_negative_int(self.agree_count, "agree_count")
        _require_non_negative_int(self.disagree_count, "disagree_count")
        _require_non_negative_int(self.abstain_count, "abstain_count")
        claims = tuple(self.dissenting_claims)
        for claim in claims:
            if not isinstance(claim, DissentingClaim):
                raise ValueError(
                    f"dissenting_claims entries must be DissentingClaim instances, got {claim!r}"
                )
        if len(claims) > self.disagree_count:
            raise ValueError(
                f"dissenting_claims has {len(claims)} entries but disagree_count is "
                f"{self.disagree_count} -- cannot cite more dissenting claims than dissenting agents"
            )
        # frozen dataclass: bypass __setattr__ once, to normalize the tuple.
        object.__setattr__(self, "dissenting_claims", claims)

    @property
    def total_votes(self):
        return self.agree_count + self.disagree_count + self.abstain_count

    @property
    def is_unanimous(self):
        """True only when >=2 agents voted and every vote agreed."""
        return self.agree_count >= 2 and self.disagree_count == 0

    @property
    def is_split(self):
        """True when the vote carries a real, counted disagreement."""
        return self.agree_count > 0 and self.disagree_count > 0


def score_confidence_with_consensus(independent_sources_count, evidence_refs_verified,
                                     counter_evidence_count, consensus_result):
    """NEW, ADDITIVE, OPT-IN sibling of score_confidence() -- accepts a typed
    ConsensusResult instead of a bare `multi_agent_consensus_count` int, so a
    split vote scores differently from a unanimous one.

    score_confidence() itself, its exact current formula/behavior, its
    4-positional-int signature, and every existing caller of it are completely
    UNCHANGED by this function -- this is a new sibling scoring path, not a
    replacement, and nothing in the codebase is required to switch to it.

    Same base formula as score_confidence() (independent-source count capped
    at 3, doubled; +2 for verified evidence refs; -3 per counter-evidence
    entry; the same HIGH/MEDIUM/LOW thresholds; the same counter-evidence
    safety floor that never lets an unaddressed counter-evidence coexist with
    a reported HIGH). The ONLY thing this function computes differently is the
    multi-agent-consensus bonus, replaced by a consensus-aware term derived
    from `consensus_result` (a ConsensusResult):

      - fewer than 2 total votes, or the disagreements outnumber (or tie) the
        agreements (net_agreement = agree_count - disagree_count <= 0):
        +0 -- no real consensus signal, exactly score_confidence()'s own
        `multi_agent_consensus_count < 2` case.
      - a real UNANIMOUS consensus (>=2 agents, zero disagreement): +2 --
        byte-identical to score_confidence()'s own `>= 2` bonus, so an
        unresolved single-value call site can switch to this function with no
        change in score for its unanimous-agreement case.
      - a real SPLIT vote with a positive net agreement (both agree_count and
        disagree_count > 0, and agree_count > disagree_count): +1 -- a split
        vote is real corroborating signal, but weaker than a unanimous one,
        so it must never score the same.

    Returns the same {"level", "score", "capped_by_counter_evidence"} shape
    score_confidence() returns, plus a "consensus" sub-dict carrying the
    ConsensusResult's own counts, the unanimous/split flags, the bonus that
    was actually applied, and every cited dissenting claim (agent/claim/
    evidence) -- so a caller inspecting a MEDIUM-not-HIGH result can see
    exactly who disagreed and why, not just that some agent did.
    """
    _require_non_negative_int(independent_sources_count, "independent_sources_count")
    _require_non_negative_int(counter_evidence_count, "counter_evidence_count")
    if not isinstance(evidence_refs_verified, bool):
        raise ValueError(
            f"evidence_refs_verified must be a bool, got {evidence_refs_verified!r}"
        )
    if not isinstance(consensus_result, ConsensusResult):
        raise ValueError(
            f"consensus_result must be a dv_harness.inference.ConsensusResult, got {consensus_result!r}"
        )

    base = min(independent_sources_count, 3) * 2
    base += 2 if evidence_refs_verified else 0
    base -= counter_evidence_count * 3

    net_agreement = consensus_result.agree_count - consensus_result.disagree_count
    if consensus_result.total_votes < 2 or net_agreement <= 0:
        consensus_bonus = 0
    elif consensus_result.disagree_count == 0:
        consensus_bonus = 2  # unanimous, >=2 agents -- same magnitude score_confidence() grants
    else:
        consensus_bonus = 1  # a real split vote with a genuine majority -- weaker than unanimous

    base += consensus_bonus

    level = "HIGH" if base >= 6 else "MEDIUM" if base >= 3 else "LOW"

    capped_by_counter_evidence = False
    if counter_evidence_count > 0 and level == "HIGH":
        level = "MEDIUM"
        capped_by_counter_evidence = True

    return {
        "level": level,
        "score": base,
        "capped_by_counter_evidence": capped_by_counter_evidence,
        "consensus": {
            "agree_count": consensus_result.agree_count,
            "disagree_count": consensus_result.disagree_count,
            "abstain_count": consensus_result.abstain_count,
            "total_votes": consensus_result.total_votes,
            "is_unanimous": consensus_result.is_unanimous,
            "is_split": consensus_result.is_split,
            "consensus_bonus_applied": consensus_bonus,
            "dissenting_claims": [
                {"agent": c.agent, "claim": c.claim, "evidence": c.evidence}
                for c in consensus_result.dissenting_claims
            ],
        },
    }


def identify_gap(required_evidence_categories, supplied_evidence_categories):
    """Pure set-difference: required minus supplied, preserving required's order.

    Case-sensitive exact match, no fuzzy matching.
    """
    if not isinstance(required_evidence_categories, list) or not all(
        isinstance(x, str) for x in required_evidence_categories
    ):
        raise ValueError("required_evidence_categories must be a list of strings")
    if not isinstance(supplied_evidence_categories, list) or not all(
        isinstance(x, str) for x in supplied_evidence_categories
    ):
        raise ValueError("supplied_evidence_categories must be a list of strings")

    supplied_set = set(supplied_evidence_categories)
    return [cat for cat in required_evidence_categories if cat not in supplied_set]


URGENCY_BY_CONFIDENCE_LEVEL = {"LOW": 3, "MEDIUM": 2, "HIGH": 1}
"""Weight applied to a hypothesis's current confidence level in
rank_evidence_by_information_value()'s uncertainty term -- a LOW-confidence
hypothesis has the most room left to move, a HIGH-confidence one the least.
An unspecified/None level is treated as MEDIUM (2), the same "we don't know,
assume the middle" convention CONFIDENCE_LEVELS' own HIGH/MEDIUM/LOW ladder
already implies for a caller who has not yet scored a hypothesis."""


def rank_evidence_by_information_value(hypotheses):
    """Rank MISSING evidence categories by how much acquiring each one would
    reduce uncertainty across a set of COMPETING hypotheses -- an autonomous
    agent's own choice of next evidence-gathering ACTION.

    This is deliberately a NEW function alongside identify_gap(), not a
    change to it: identify_gap() itself is completely untouched above, and
    is reused here verbatim (called, never re-derived) to find each
    hypothesis's own missing categories. Every existing identify_gap() call
    site and test is therefore unaffected by this addition.

    Distinct from intake_question_priority.py's already-in-flight ranking,
    on purpose: that module ranks which PENDING QUESTIONS to put in front of
    a HUMAN (gated on confidence/criticality, scored by
    blocking_value*downstream_impact*expected_confidence_gain/user_effort,
    with a do-not-ask policy and batching for a person's attention). This
    function ranks EVIDENCE CATEGORIES nobody has asked about at all yet --
    it never touches a question queue, never gates on criticality, and never
    asks "should a human be interrupted". It answers a narrower, earlier
    question purely from the hypothesis set itself: of everything still
    missing, what would most help an agent tell competing hypotheses apart.

    `hypotheses` is a list of dicts, each:
      - "hypothesis_id": a non-empty string identifying the hypothesis.
      - "required_evidence_categories": a list[str] -- identify_gap()'s own
        first argument for this hypothesis.
      - "supplied_evidence_categories": a list[str] -- identify_gap()'s own
        second argument for this hypothesis.
      - "current_confidence_level": optional, one of CONFIDENCE_LEVELS, or
        omitted/None (treated as MEDIUM per URGENCY_BY_CONFIDENCE_LEVEL).

    For every category that is missing (per identify_gap()) for at least one
    hypothesis, two deterministic, evidence-only factors are combined:

      discrimination = 4 * p * (1 - p), where p = (count of hypotheses
        REQUIRING this category that are currently MISSING it) / (count of
        hypotheses REQUIRING this category at all -- i.e. that DECLARE the
        category applicable to them, whether or not they already have it).
        This is maximal (1.0) when the category is missing for exactly half
        of the hypotheses that need it -- resolving it then genuinely
        discriminates which of them still stand. A category every applicable
        hypothesis already lacks (p=1), or that every applicable hypothesis
        already has (p=0), scores 0: gathering it either helps everyone
        equally (no discrimination between hypotheses) or nobody at all.

      uncertainty_weight = the AVERAGE urgency (URGENCY_BY_CONFIDENCE_LEVEL)
        of only the hypotheses currently missing this category, normalized
        into (0, 1] by dividing by the maximum weight (3). A category that
        matters to hypotheses already near HIGH confidence is worth less
        than the identical category mattering to hypotheses still at LOW.

      voi_score = discrimination * uncertainty_weight, rounded to 4 decimal
        places for a stable, comparable, deterministic ranking.

    Returns {"hypothesis_count": int, "ranked": [...]}, `ranked` sorted by
    voi_score descending, ties broken by category name ascending for
    determinism. Each ranked entry carries "category", "voi_score",
    "discrimination", "uncertainty_weight", "hypotheses_applicable" (ids
    that require this category) and "hypotheses_missing" (ids among those
    that currently lack it) -- so a caller can see exactly which hypotheses
    a gathering action would help discriminate between, not only a bare
    number. An empty `hypotheses` list is not an error (there is nothing to
    discriminate between yet) and returns an empty ranking.
    """
    if not isinstance(hypotheses, list):
        raise ValueError("hypotheses must be a list of dicts")

    parsed = []
    for h in hypotheses:
        if not isinstance(h, dict):
            raise ValueError(f"each hypothesis must be a dict, got {h!r}")
        hypothesis_id = h.get("hypothesis_id")
        if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
            raise ValueError(
                f"hypothesis_id must be a non-empty string, got {hypothesis_id!r}"
            )
        required = h.get("required_evidence_categories")
        supplied = h.get("supplied_evidence_categories")
        # identify_gap() itself validates required/supplied's shape and does
        # the actual set-difference -- reused verbatim, not re-derived.
        gap = identify_gap(required, supplied)
        level = h.get("current_confidence_level")
        if level is not None and level not in CONFIDENCE_LEVELS:
            raise ValueError(
                f"current_confidence_level must be one of {CONFIDENCE_LEVELS} or None, "
                f"got {level!r}"
            )
        parsed.append({
            "hypothesis_id": hypothesis_id,
            "required": set(required),
            "gap": set(gap),
            "urgency": URGENCY_BY_CONFIDENCE_LEVEL.get(level, URGENCY_BY_CONFIDENCE_LEVEL["MEDIUM"]),
        })

    # Preserve first-seen order across hypotheses for a stable pre-sort input,
    # then the final sort below makes the returned order fully deterministic
    # regardless of input order.
    seen_categories = []
    seen_set = set()
    for p in parsed:
        for cat in p["gap"]:
            if cat not in seen_set:
                seen_set.add(cat)
                seen_categories.append(cat)

    ranked = []
    for category in seen_categories:
        applicable = [p for p in parsed if category in p["required"]]
        missing = [p for p in applicable if category in p["gap"]]
        # category came from someone's real gap, so applicable is never empty.
        fraction_missing = len(missing) / len(applicable)
        discrimination = 4 * fraction_missing * (1 - fraction_missing)
        avg_urgency = sum(p["urgency"] for p in missing) / len(missing)
        uncertainty_weight = avg_urgency / URGENCY_BY_CONFIDENCE_LEVEL["LOW"]
        voi_score = discrimination * uncertainty_weight
        ranked.append({
            "category": category,
            "voi_score": round(voi_score, 4),
            "discrimination": round(discrimination, 4),
            "uncertainty_weight": round(uncertainty_weight, 4),
            "hypotheses_applicable": [p["hypothesis_id"] for p in applicable],
            "hypotheses_missing": [p["hypothesis_id"] for p in missing],
        })

    ranked.sort(key=lambda e: (-e["voi_score"], e["category"]))

    return {"hypothesis_count": len(parsed), "ranked": ranked}


# ---------------------------------------------------------------------------
# Hypothesis-generation bias correction from retracted hypotheses
# (2026-09-07, hypothesis_generation_bias_correction)
#
# REUSE OVER REINVENT, checked before writing anything: `dv_harness/memory.py`'s
# `MemoryGC.retract()` already records, per real memory record, that "the
# record was found to be wrong outright" (its own docstring), with a real
# cited `retraction_reason`. `confidence_calibration.py` already reads that
# same real vocabulary back to ask a DIFFERENT question -- does a CONFIDENCE
# TIER's own track record match the ordering this harness acts on. Nothing in
# this codebase asked the question this item names: does the SHAPE of a
# retracted root-cause HYPOTHESIS -- which real evidence categories its own
# citations covered -- predictably correlate with it later being found wrong,
# independent of which confidence tier it was assigned. A repo-wide grep for
# `hypothesis.*bias`/`hypothesis_shape`/`generation_bias` before this was
# written matched nothing.
#
# `engine.ROOT_CAUSE_EVIDENCE_CATEGORIES` and root_cause_evidence_gate.py's own
# `hypothesis_fields` (claim/category/supporting_evidence/counter_evidence/
# missing_evidence/confidence/next_action) are the closest existing
# hypothesis-shape vocabularies in this codebase, and neither is reused
# directly here: both are FIXED, small vocabularies answering "did this
# hypothesis supply the mandatory fields", never "which DOMAIN-SPECIFIC
# evidence categories (a register, a signal, a log source, ...) did it cite,
# and does citing -- or not citing -- one of them predict it was wrong". No
# current real memory-record writer in this repository persists that
# domain-specific per-category citation shape as a structured field --
# confirmed by reading engine.py's real `verified_fix`/`root_cause`/
# `debug_lesson`-kind record construction. What IS real: `_promote_experience_
# knowledge()` (EXPERT_FEEDBACK_LOOP's experience_knowledge_gate PASS) already
# writes the agent's own free-text `evidence` field verbatim onto the stored
# record (`"evidence": block.get("evidence")`), and that gate script enforces
# only that the field is truthy -- never a shape. So a category-keyed
# evidence dict (e.g. `{"symptom_register": "...", "control_register": "..."}`)
# is a real, legal, unenforced value that field can already hold today; this
# module reads it back the same "category name -> truthy citation" way
# engine.py's own root_cause_evidence_gate handling already reads its four
# FIXED categories (`[c for c in categories if block.get(c)]`), generalized
# here to whatever category keys a project's own evidence dict actually
# declares, never a hardcoded vocabulary.
#
# WHAT THIS FUNCTION DELIBERATELY DOES NOT DO
# ---------------------------------------------------------------------------
#   * It never blocks, suppresses, downgrades, or filters a future
#     hypothesis matching a flagged pattern -- it returns a report. Nothing
#     in this module, and nothing this pass wires it into, consults it
#     automatically. Acting on a finding here -- e.g. auto-penalizing a
#     hypothesis whose shape matches a flagged pattern -- would be exactly
#     the kind of production-scoring change CLAUDE.md's Evidence Truth Rule
#     requires be proposed as DATA, through `capability_evolution.py`'s
#     existing controlled-experiment machinery, for a human to approve --
#     never applied directly to production scoring.
#   * It never touches `score_confidence()`'s own formula or constants -- a
#     completely separate, untouched mechanism.
#   * It never invents a category vocabulary. Every category name it reports
#     on is one at least one caller-supplied hypothesis actually cited; the
#     "symptom register vs. control register" example in this item's own
#     title is illustrative, never hardcoded anywhere in this function.
#   * It never fabricates precision from a small sample: a category or exact
#     shape with too few observations in either comparison group is reported
#     as insufficient, never silently folded into a computed rate either way.

#: The smallest comparison-group size at which one record moving a
#: retraction rate by 1/N produces at most a 20-percentage-point swing --
#: the same "derived from the arithmetic, not chosen" resolution-band
#: reasoning `confidence_calibration.MIN_DETERMINATE_OUTCOMES_PER_TIER` uses,
#: independently re-derived here rather than imported (that module already
#: imports FROM this one, so the dependency can only run this direction) at
#: a coarser 0.2 band rather than that module's 0.1: a retracted-HYPOTHESIS
#: corpus is real-world sparser than a whole memory store's tier-outcome
#: corpus, and requiring that module's own 10-per-group bar here would make
#: this analysis report INSUFFICIENT_HISTORY on every real project that has
#: not yet accumulated a large hypothesis history -- an honest, disclosed,
#: coarser choice for a genuinely sparser domain, not an arbitrary one.
HYPOTHESIS_BIAS_RATE_RESOLUTION = 0.2
MIN_HYPOTHESES_PER_COMPARISON_GROUP = 5

#: A margin smaller than one resolution band is noise, not a measured
#: difference -- the same reasoning `confidence_calibration.INVERSION_
#: TOLERANCE` states for reusing its own resolution constant as its margin.
HYPOTHESIS_BIAS_MARGIN = HYPOTHESIS_BIAS_RATE_RESOLUTION

DIRECTION_CITING_CORRELATES = "CITING_CORRELATES_WITH_RETRACTION"
DIRECTION_ABSENCE_CORRELATES = "ABSENCE_CORRELATES_WITH_RETRACTION"

FINDING_EVIDENCE_CATEGORY_BIAS = "EVIDENCE_CATEGORY_BIAS"
FINDING_HYPOTHESIS_SHAPE_BIAS = "HYPOTHESIS_SHAPE_BIAS"

BIAS_STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
BIAS_STATUS_INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
BIAS_STATUS_NO_BIAS_DETECTED = "NO_BIAS_DETECTED"
BIAS_STATUS_BIAS_DETECTED = "BIAS_DETECTED"

HYPOTHESIS_BIAS_DISCLOSURE = (
    "ADVISORY ONLY. This report is descriptive statistics over hypotheses this "
    "project has already recorded and retracted; it never blocks, downgrades, or "
    "filters a future hypothesis matching a flagged pattern, and nothing in "
    "dv_harness/inference.py writes this report's findings into "
    "score_confidence()'s formula or any other production scoring path. A human "
    "or agent reviewing a NEW hypothesis may consult this report; nothing "
    "consults it automatically."
)


def detect_hypothesis_generation_bias(hypotheses,
                                       *,
                                       min_group_size=MIN_HYPOTHESES_PER_COMPARISON_GROUP,
                                       margin=HYPOTHESIS_BIAS_MARGIN):
    """Advisory-only analysis of the SHAPE of this project's own retracted
    (and non-retracted) root-cause hypotheses, surfacing any real correlation
    between which real evidence categories a hypothesis's citations covered
    and whether it was later found wrong -- e.g. the item's own worked
    example, "hypotheses citing only a symptom register and never a control
    register are wrong more often", would surface here as a real, cited
    finding IF this project's own history actually shows that pattern, never
    asserted a priori.

    `hypotheses` is a list of dicts, each:
      - "hypothesis_id": a non-empty string identifying the hypothesis
        (unique across the list).
      - "retracted": a bool -- True iff this hypothesis was later found
        wrong (the real, project-recorded outcome; see
        `hypothesis_shape_from_record()` below for how this is read off a
        real `dv_harness.memory` record's own `status`).
      - "evidence_categories_cited": a list[str] of the real evidence
        category names this hypothesis's own citations covered (may be
        empty -- an honestly uncategorized hypothesis, never guessed at).

    Runs two independent, complementary comparisons, both gated on
    `min_group_size` in EVERY compared group so a rate is never computed --
    in either direction -- from too small a sample:

      1. PER-CATEGORY: for every category cited by at least one hypothesis
         in the corpus, splits the corpus into hypotheses that DID cite it
         and hypotheses that did NOT, and reports a finding
         (FINDING_EVIDENCE_CATEGORY_BIAS) when the two groups' retraction
         rates differ by more than `margin`, naming which direction the
         correlation runs (DIRECTION_CITING_CORRELATES -- citing this
         category correlates with MORE retractions; or
         DIRECTION_ABSENCE_CORRELATES -- NOT citing it does, the shape of
         the item's own worked example).
      2. EXACT-SHAPE: for every distinct exact set of cited categories
         (a hypothesis's whole "shape"), compares that shape's own
         retraction rate against every OTHER hypothesis's, reporting a
         finding (FINDING_HYPOTHESIS_SHAPE_BIAS) when citing EXACTLY that
         combination -- and nothing else -- correlates with more
         retractions than the rest of the corpus.

    A category or exact shape that could not be compared (either group below
    `min_group_size`) is still reported, under `categories_insufficient` /
    `shapes_insufficient`, so a reader can see the whole picture rather than
    a silently narrowed one -- mirroring `confidence_calibration._tier_
    report()`'s own `calibratable`/`insufficient_reason` transparency.

    Four honest statuses:
      NOT_AVAILABLE        `hypotheses` is empty -- there is nothing to
                           analyze yet. Not an error (mirrors
                           `rank_evidence_by_information_value()`'s own "an
                           empty list is not an error" rule).
      INSUFFICIENT_HISTORY hypotheses were supplied, but no category and no
                           exact shape ever reached `min_group_size` in both
                           of its compared groups -- a real, honest answer
                           about this project's own current history, not a
                           failure.
      NO_BIAS_DETECTED     at least one category or shape WAS comparable,
                           and none showed a margin exceeding `margin`.
      BIAS_DETECTED         at least one real finding.
    """
    if not isinstance(hypotheses, list):
        raise ValueError("hypotheses must be a list of dicts")
    if isinstance(min_group_size, bool) or not isinstance(min_group_size, int) or min_group_size < 1:
        raise ValueError(f"min_group_size must be a positive int, got {min_group_size!r}")
    if isinstance(margin, bool) or not isinstance(margin, (int, float)) or not (0 <= margin <= 1):
        raise ValueError(f"margin must be a number in [0, 1], got {margin!r}")

    parsed = []
    seen_ids = set()
    for h in hypotheses:
        if not isinstance(h, dict):
            raise ValueError(f"each hypothesis must be a dict, got {h!r}")
        hid = h.get("hypothesis_id")
        if not isinstance(hid, str) or not hid.strip():
            raise ValueError(f"hypothesis_id must be a non-empty string, got {hid!r}")
        if hid in seen_ids:
            raise ValueError(f"duplicate hypothesis_id {hid!r}")
        seen_ids.add(hid)
        retracted = h.get("retracted")
        if not isinstance(retracted, bool):
            raise ValueError(
                f"hypothesis {hid!r}: retracted must be a bool, got {retracted!r}"
            )
        categories = h.get("evidence_categories_cited")
        if categories is None:
            categories = []
        if not isinstance(categories, list) or not all(
            isinstance(c, str) and c.strip() for c in categories
        ):
            raise ValueError(
                f"hypothesis {hid!r}: evidence_categories_cited must be a list of "
                f"non-empty strings, got {categories!r}"
            )
        parsed.append({
            "hypothesis_id": hid,
            "retracted": retracted,
            "categories": frozenset(categories),
        })

    base = {
        "hypothesis_count": len(parsed),
        "retracted_count": sum(1 for p in parsed if p["retracted"]),
        "min_group_size": min_group_size,
        "margin": margin,
        "disclosure": HYPOTHESIS_BIAS_DISCLOSURE,
    }

    if not parsed:
        return dict(
            base,
            status=BIAS_STATUS_NOT_AVAILABLE,
            reason="NO_HYPOTHESES_SUPPLIED",
            category_findings=[], shape_findings=[],
            categories_insufficient=[], shapes_insufficient=[],
        )

    def _rate(group):
        return sum(1 for p in group if p["retracted"]) / len(group)

    # ---- per-category citing-vs-absence analysis ---------------------
    vocabulary = sorted({c for p in parsed for c in p["categories"]})
    category_findings = []
    categories_insufficient = []
    for category in vocabulary:
        citing = [p for p in parsed if category in p["categories"]]
        absent = [p for p in parsed if category not in p["categories"]]
        if len(citing) < min_group_size or len(absent) < min_group_size:
            categories_insufficient.append({
                "category": category,
                "citing_count": len(citing),
                "absent_count": len(absent),
                "reason": (
                    f"citing_count={len(citing)}, absent_count={len(absent)}; "
                    f"{min_group_size} required in both groups before a "
                    f"comparison has resolution finer than "
                    f"{int(margin * 100)} percentage points"
                ),
            })
            continue
        citing_rate = _rate(citing)
        absent_rate = _rate(absent)
        if absent_rate - citing_rate > margin:
            direction, gap = DIRECTION_ABSENCE_CORRELATES, absent_rate - citing_rate
        elif citing_rate - absent_rate > margin:
            direction, gap = DIRECTION_CITING_CORRELATES, citing_rate - absent_rate
        else:
            continue
        category_findings.append({
            "kind": FINDING_EVIDENCE_CATEGORY_BIAS,
            "category": category,
            "direction": direction,
            "citing_count": len(citing),
            "citing_retraction_rate": round(citing_rate, 4),
            "absent_count": len(absent),
            "absent_retraction_rate": round(absent_rate, 4),
            "margin_observed": round(gap, 4),
            "detail": (
                f"hypotheses citing '{category}' were retracted {citing_rate:.0%} "
                f"of the time ({len(citing)} hypotheses) vs. {absent_rate:.0%} "
                f"for hypotheses that never cited it ({len(absent)} hypotheses)"
                if direction == DIRECTION_CITING_CORRELATES else
                f"hypotheses that never cited '{category}' were retracted "
                f"{absent_rate:.0%} of the time ({len(absent)} hypotheses) vs. "
                f"{citing_rate:.0%} for hypotheses that did cite it "
                f"({len(citing)} hypotheses)"
            ),
        })

    # ---- exact-shape (the whole set of cited categories) analysis ----
    shape_findings = []
    shapes_insufficient = []
    shape_keys = sorted({p["categories"] for p in parsed}, key=sorted)
    for shape in shape_keys:
        matching = [p for p in parsed if p["categories"] == shape]
        other = [p for p in parsed if p["categories"] != shape]
        if len(matching) < min_group_size or len(other) < min_group_size:
            shapes_insufficient.append({
                "evidence_categories_cited": sorted(shape),
                "matching_count": len(matching),
                "other_count": len(other),
                "reason": (
                    f"matching_count={len(matching)}, other_count={len(other)}; "
                    f"{min_group_size} required in both groups"
                ),
            })
            continue
        matching_rate = _rate(matching)
        other_rate = _rate(other)
        if matching_rate - other_rate > margin:
            shape_findings.append({
                "kind": FINDING_HYPOTHESIS_SHAPE_BIAS,
                "evidence_categories_cited": sorted(shape),
                "matching_count": len(matching),
                "matching_retraction_rate": round(matching_rate, 4),
                "other_count": len(other),
                "other_retraction_rate": round(other_rate, 4),
                "margin_observed": round(matching_rate - other_rate, 4),
                "detail": (
                    f"hypotheses citing exactly {sorted(shape)} (and no other "
                    f"category) were retracted {matching_rate:.0%} of the time "
                    f"({len(matching)} hypotheses) vs. {other_rate:.0%} for "
                    f"every other hypothesis ({len(other)} hypotheses)"
                ),
            })

    findings_present = bool(category_findings or shape_findings)
    calibratable = (len(vocabulary) - len(categories_insufficient)
                    + len(shape_keys) - len(shapes_insufficient)) > 0

    if findings_present:
        status, reason = BIAS_STATUS_BIAS_DETECTED, "FINDINGS_PRESENT"
    elif not calibratable:
        status, reason = (
            BIAS_STATUS_INSUFFICIENT_HISTORY,
            "NO_CATEGORY_OR_SHAPE_HAS_ENOUGH_OBSERVATIONS_IN_BOTH_GROUPS",
        )
    else:
        status, reason = BIAS_STATUS_NO_BIAS_DETECTED, "NO_FINDINGS"

    return dict(
        base,
        status=status,
        reason=reason,
        category_findings=category_findings,
        shape_findings=shape_findings,
        categories_insufficient=categories_insufficient,
        shapes_insufficient=shapes_insufficient,
    )


#: The real `kind` values `memory_router.py`'s own `ENGINEERING_REUSABLE_
#: CLAIM_FIELDS` vocabulary already routes to Engineering Memory for a
#: record carrying a reusable root-cause claim (`route_memory()`) -- reused
#: verbatim here, never a separately invented kind list.
HYPOTHESIS_RECORD_KINDS = ("root_cause", "verified_fix", "debug_lesson")

#: `dv_harness.memory.MemoryGC.retract()`'s own persisted `status` literal --
#: see that method's own docstring ("the record was found to be wrong
#: outright"). Deliberately excludes "SUPERSEDED"
#: (`MemoryGC.supersede()`: "a newer, CORRECTED record replaces this one"):
#: being superseded says a better record now exists, not that THIS
#: hypothesis's own evidence shape is what made it wrong, while a retraction
#: is squarely about the claim itself being wrong -- the fact this analysis
#: exists to explain.
HYPOTHESIS_RETRACTED_STATUS = "RETRACTED"


def hypothesis_shape_from_record(record):
    """One real `dv_harness.memory` `MemoryStore` record -> one
    `detect_hypothesis_generation_bias()` input dict.

    `retracted` is read straight off the record's own real, persisted
    `status` (never re-derived or guessed): True iff it equals
    `HYPOTHESIS_RETRACTED_STATUS`, the literal value `MemoryGC.retract()`
    itself writes.

    `evidence_categories_cited` is read from `record["evidence"]` ONLY when
    that field is a real dict -- the same "category name -> truthy citation"
    convention this module's own module-level docstring section explains a
    real production writer (`engine._promote_experience_knowledge()`) can
    already legally populate that field with today. A record whose
    `evidence` is not a dict (free text, a list, absent) reports an
    honestly EMPTY category set, never a guess: this record's shape was
    simply never structured this way, which is a different fact from "it
    cited nothing"."""
    hid = str(record.get("memory_id") or "").strip()
    if not hid:
        raise ValueError(f"record has no memory_id: {record!r}")
    status = str(record.get("status") or "").strip().upper()
    evidence = record.get("evidence")
    categories = (
        sorted(str(k) for k, v in evidence.items() if v)
        if isinstance(evidence, dict) else []
    )
    return {
        "hypothesis_id": hid,
        "retracted": status == HYPOTHESIS_RETRACTED_STATUS,
        "evidence_categories_cited": categories,
    }


def collect_hypothesis_shapes(root, *, store=None):
    """Every real `HYPOTHESIS_RECORD_KINDS` memory record in this project's
    `MemoryStore`, converted through `hypothesis_shape_from_record()`, ready
    to hand straight to `detect_hypothesis_generation_bias()`.

    A pure read: opens nothing for writing. `store` may be supplied by a
    caller that already has one open (the same convention
    `confidence_calibration.calibrate()`'s own `store` parameter uses);
    otherwise one is constructed here via a DEFERRED import -- `memory.py`
    does not import this module, so there is no import cycle, but importing
    it only inside this function (rather than at module load) keeps
    `inference.py` itself dependency-free of the rest of the harness for
    every caller that only ever wants its pure math, exactly as this
    module's own top-of-file import list (json/dataclasses/pathlib/typing
    only) already promises."""
    from .memory import MemoryStore

    store = store if store is not None else MemoryStore(Path(root))
    records = []
    for kind in HYPOTHESIS_RECORD_KINDS:
        records.extend(store.find(None, kind=kind))
    return [
        hypothesis_shape_from_record(r) for r in records if r.get("root_cause")
    ]


def _load_registry(root):
    try:
        return json.loads(
            (Path(root) / ".dv-harness" / "builder" / "protocol_builder_registry.json").read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return None


def _find_protocol_entry(registry, protocol):
    entries = (registry or {}).get("protocols") or {}
    key = str(protocol).strip().lower().replace(" ", "-").replace("_", "-")
    entry = entries.get(key)
    if entry is None:
        for k, v in entries.items():
            if k in key or key in k:
                entry = v
                break
    return entry


def promote_if_high_confidence(kc_client, category, protocol, finding, confidence_result):
    """Promote a finding into the shared, cross-user Knowledge Center
    (KnowledgeCenterClient.add) ONLY when confidence_result (the exact dict
    score_confidence() already returns) has level=="HIGH". The shared store
    is durable, cross-checked knowledge, not per-run noise, so MEDIUM/LOW
    findings are never sent -- and a HIGH finding whose kc_client.add() call
    itself reports failure (its own "ok" key) is never reported as promoted.
    """
    if confidence_result.get("level") != "HIGH":
        return {
            "promoted": False,
            "reason": "CONFIDENCE_NOT_HIGH",
            "level": confidence_result.get("level"),
        }

    kc_result = kc_client.add(category, protocol, finding)
    if not kc_result.get("ok"):
        return {
            "promoted": False,
            "reason": "KC_ADD_FAILED",
            "kc_result": kc_result,
        }

    result = dict(kc_result)
    result["promoted"] = True
    return result


def _next_best_action_from_catalog(gaps, catalog):
    """The catalog branch of next_best_action() -- see its docstring for the
    catalog shape. Kept as a private helper rather than inlined so the
    registry path above stays exactly the code it was."""
    if not isinstance(catalog, dict):
        raise ValueError(f"gap_action_catalog must be a dict, got {type(catalog).__name__}")
    actions = catalog.get("actions")
    if not isinstance(actions, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in actions.items()
    ):
        raise ValueError("gap_action_catalog['actions'] must be a dict of str -> str")
    source = catalog.get("source")
    if not isinstance(source, str) or not source:
        raise ValueError("gap_action_catalog['source'] must be a non-empty string")
    fallback = catalog.get("fallback")
    if not isinstance(fallback, str) or not fallback:
        raise ValueError("gap_action_catalog['fallback'] must be a non-empty string")

    results = []
    for gap in gaps:
        gap_str = str(gap)
        action = actions.get(gap_str)
        if action is None:
            gap_lower = gap_str.lower()
            for key, value in actions.items():
                if gap_lower in key.lower() or key.lower() in gap_lower:
                    action = value
                    break
        if action is not None:
            results.append({"gap": gap, "suggested_action": action, "source": source})
        else:
            results.append({
                "gap": gap,
                "suggested_action": fallback.replace("{gap}", gap_str),
                "source": "generic",
            })
    return results


def next_best_action(protocol, gaps, root, *, gap_action_catalog=None):
    """For each gap, suggest a concrete next step by cross-referencing the
    real per-protocol discover/build lists in protocol_builder_registry.json.

    Mirrors gates.py's _protocol_discover_checklist protocol-name-matching
    logic (normalize to lower-kebab-case, exact key match, then substring
    alias-fallback loop) so behavior stays consistent with the INTAKE-stage
    fix already shipped.

    `gap_action_catalog` (2026-09-04, Research-Capability Evolution Stage 1)
    lets a NON-protocol caller supply its own gap->action lookup instead of the
    protocol builder registry, without duplicating this function's matching
    logic in a second module. Omit it and behavior is byte-identical to before
    -- every existing caller (engine.py's `_react_step_inference` and
    `_score_root_cause_confidence`, dv_harness_tests/e2e_memory_chain_usb3_lfps.py)
    passes the same three positional arguments and is unaffected.

    It exists because the two DV-specific halves of this function are wrong for
    a non-simulation gap, and only those two: the registry it reads, and the
    "inspect current RTL/spec/VIP evidence directly" fallback. The Gap ->
    Next-Best-Action ARCHITECTURE around them is domain-neutral and is what the
    master prompt's section 10 forbids re-implementing ("Do NOT create a
    Research Inference Engine"). A catalog is:

        {"source": "<name recorded in each result's `source` field>",
         "actions": {"<gap key>": "<the concrete next step>", ...},
         "fallback": "<text, may contain {gap}>"}

    Matching is exact key first, then the same substring pass the registry path
    uses, so a caller may key its catalog by gap name or by a distinctive
    fragment of one. An unmatched gap gets `fallback` with {gap} filled in and
    `source` "generic", exactly as the registry path's own miss does.
    """
    if gap_action_catalog is not None:
        return _next_best_action_from_catalog(gaps, gap_action_catalog)

    registry = _load_registry(root)
    entry = _find_protocol_entry(registry, protocol)
    discover = (entry or {}).get("discover") or []
    build = (entry or {}).get("build") or []
    candidates = list(discover) + list(build)

    results = []
    for gap in gaps:
        gap_lower = str(gap).lower()
        match = None
        for item in candidates:
            if gap_lower in item.lower() or item.lower() in gap_lower:
                match = item
                break
        if match is not None:
            results.append(
                {
                    "gap": gap,
                    "suggested_action": f"check registry item '{match}' for protocol '{protocol}'",
                    "source": "protocol_builder_registry",
                }
            )
        else:
            results.append(
                {
                    "gap": gap,
                    "suggested_action": (
                        f"no concrete registry item found for gap '{gap}' -- "
                        "inspect current RTL/spec/VIP evidence directly"
                    ),
                    "source": "generic",
                }
            )
    return results


# ---------------------------------------------------------------------------
# Meta-reasoning: size evidence-gathering effort to question difficulty/stakes
# (2026-09-07, meta_reasoning_effort_sizing)
#
# WHAT THIS ANSWERS. Given a question this harness is about to spend agent
# time answering, how much evidence-gathering effort -- how many independent
# agents, roughly how thorough a pass -- does a question THIS SHAPED
# typically warrant? This is a RECOMMENDATION ONLY: it never dispatches an
# agent, submits a build/regression/LSF job, or writes any state itself.
# Whether -- and how -- to actually act on the recommendation stays a
# caller/Workflow-script decision, exactly like this project's other
# production-behavior choices (CLAUDE.md's Evidence Truth Rule: "A
# weight/threshold change proposal must never be applied directly to
# production scoring").
#
# REUSE OVER REINVENT, checked before writing a line of this. This item's own
# governing instruction names two real, already-built signals to be
# "informed by", and this section adds no third:
#
#   1. `dv_harness.source_authority_order_validation` (this same batch's own
#      standalone item, already real and tested) already answers whether
#      `source_authority.AUTHORITY_ORDER`'s fixed 9-level order actually
#      matches which side a human has picked in practice, over this
#      project's real, answered Tier-3 conflict escalations. Its own
#      `match_rate_percent`/`mismatches` are this project's real
#      CONTENTIOUSNESS history for source-authority-shaped questions: a
#      project where humans keep overriding the fixed order
#      (ORDER_DIVERGES_FROM_PRACTICE) is real evidence that THIS CLASS of
#      question needs more evidence-gathering before committing, not less.
#   2. A per-DOMAIN (protocol) analogue of this file's own
#      `detect_hypothesis_generation_bias()` two-group comparison
#      (documented above): does the domain/protocol a question concerns
#      have a real, elevated WRONG-HYPOTHESIS (retraction) rate against the
#      rest of this project's own hypothesis history. `collect_domain_
#      hypothesis_shapes()`/`domain_wrong_hypothesis_track_record()` below
#      reuse this file's own `HYPOTHESIS_RECORD_KINDS`/
#      `HYPOTHESIS_RETRACTED_STATUS`/`MIN_HYPOTHESES_PER_COMPARISON_GROUP`/
#      `HYPOTHESIS_BIAS_MARGIN` verbatim -- the identical sparse-domain
#      floor and resolution-band margin this file already derived and
#      justified for its own evidence-CATEGORY analysis, applied here along
#      a different, DOMAIN axis instead of re-deriving a second threshold.
#      `collect_domain_hypothesis_shapes()` additionally reuses
#      `cross_project_mining.has_memory_store()` to check a project's memory
#      store already exists BEFORE ever constructing a `MemoryStore` (whose
#      constructor `mkdir()`s the whole tier tree and writes an empty
#      `index.json` -- the same real side effect `confidence_calibration.py`
#      and `cross_project_mining.py` already document and guard against for
#      the identical reason): a pure read for a project's own domain track
#      record must never bring a store into existence merely by asking
#      about it.
#
# WHAT THIS SECTION DELIBERATELY DOES NOT DO.
#   * It never dispatches an agent, never submits a build/regression/LSF
#     job, and never writes any state, memory record, or Blackboard topic --
#     `recommend_evidence_gathering_effort()` is a pure function returning a
#     dict; acting on it is entirely the caller/Workflow-script's decision.
#   * It never proposes changing `score_confidence()`'s own formula, weights,
#     or thresholds, and it is never itself applied to production scoring --
#     per the Evidence Truth Rule, a weight/threshold change proposal must be
#     routed through `capability_evolution.py`'s controlled-experiment
#     machinery for a human to approve, exactly like every other production-
#     behavior change in this project; this section proposes nothing of that
#     kind at all, it only sizes an ADVISORY recommendation.
#   * Absence of a real signal is NEUTRAL, never read as "safe to use fewer
#     agents" -- a project/domain with no real history either way keeps the
#     STANDARD baseline; only a REAL signal (in either direction) can move
#     the recommendation off that baseline, in the same "an absence of proof
#     must never be silently promoted to proof of safety" spirit this
#     project's Evidence Truth Rule already states everywhere else.
#   * `inference.py`'s own stated dependency-free-for-pure-math-callers
#     design goal (see `collect_hypothesis_shapes()`'s own docstring) is
#     preserved: `source_authority_order_validation`, `cross_project_mining`
#     and `memory` are all imported lazily, inside the one function that
#     needs each, never at module load time.

#: The three-value recommended effort ladder, MINIMAL < STANDARD < THOROUGH.
#: Deliberately a DIFFERENT vocabulary from CONFIDENCE_LEVELS (this module's
#: own confidence-scoring vocabulary at the top of this file) and from
#: `dv_harness.models.Status` -- a recommended EFFORT level is neither a
#: confidence score nor a stage verdict, and must never be confusable with
#: either.
EFFORT_LEVELS = ("MINIMAL", "STANDARD", "THOROUGH")
EFFORT_LEVEL_RANK = {"MINIMAL": 0, "STANDARD": 1, "THOROUGH": 2}

#: How many independent agents each effort level recommends AT LEAST --
#: THOROUGH's floor of 3 is this project's own real Core Operating Rule made
#: concrete: "Important DUT/PHY/Register/VIP changes require Multi-Agent
#: evidence acquisition plus independent synthesis" (CLAUDE.md).
EFFORT_LEVEL_MIN_INDEPENDENT_AGENTS = {"MINIMAL": 1, "STANDARD": 2, "THOROUGH": 3}

RECOMMENDATION_DISCLOSURE = (
    "ADVISORY ONLY. This is a recommendation of how many independent agents / how "
    "much evidence-gathering effort a question of this shape likely needs -- it "
    "never itself dispatches an agent, runs a build, submits a job, or writes any "
    "state. Whether, and how, to actually act on this recommendation stays a "
    "caller/Workflow-script decision, exactly like every other production-behavior "
    "choice in this project."
)


def _require_positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive int, got {value!r}")


def _require_unit_margin(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not (0 <= value <= 1):
        raise ValueError(f"{name} must be a number in [0, 1], got {value!r}")


def domain_hypothesis_shape_from_record(record):
    """One real `dv_harness.memory` `MemoryStore` record -> one
    `domain_wrong_hypothesis_track_record()` input dict.

    Reuses `hypothesis_shape_from_record()`'s own real `retracted`
    derivation exactly (`status == HYPOTHESIS_RETRACTED_STATUS`, the literal
    value `MemoryGC.retract()` itself writes) -- never a second definition
    of "was this hypothesis found wrong". The one thing it carries that
    `hypothesis_shape_from_record()` deliberately does not is the record's
    own real `protocol` field: that function strips it because its own
    bias-by-evidence-shape analysis groups by evidence CATEGORY, never by
    domain; this function exists precisely to preserve it for the DOMAIN
    axis instead."""
    hid = str(record.get("memory_id") or "").strip()
    if not hid:
        raise ValueError(f"record has no memory_id: {record!r}")
    status = str(record.get("status") or "").strip().upper()
    protocol = record.get("protocol")
    domain = str(protocol).strip() if protocol else None
    return {
        "hypothesis_id": hid,
        "retracted": status == HYPOTHESIS_RETRACTED_STATUS,
        "domain": domain if domain else None,
    }


def collect_domain_hypothesis_shapes(root, *, store=None):
    """Every real `HYPOTHESIS_RECORD_KINDS` memory record in this project's
    `MemoryStore`, converted through `domain_hypothesis_shape_from_record()`,
    ready to hand straight to `domain_wrong_hypothesis_track_record()`.

    Mirrors `collect_hypothesis_shapes()`'s own real-store-reading shape
    exactly (same kinds, same `if r.get("root_cause")` eligibility filter,
    same deferred `from .memory import MemoryStore` so this module's own
    top-of-file import list stays dependency-free for every caller that only
    ever wants its pure math), with one addition: it never constructs a
    `MemoryStore` for a project that does not already have one on disk --
    that constructor `mkdir()`s the whole tier tree and writes an empty
    `index.json` (the same real side effect `confidence_calibration.py` and
    `cross_project_mining.py` already document and guard against for the
    identical reason), and a pure read for a project's own domain track
    record must never bring a store into existence merely by asking about
    it. `store` may be supplied by a caller that already has one open, the
    same convention `collect_hypothesis_shapes()`'s own `store` parameter
    already uses; only the auto-construct path is guarded."""
    if store is None:
        from .cross_project_mining import has_memory_store
        if not has_memory_store(root):
            return []
        from .memory import MemoryStore
        store = MemoryStore(Path(root))
    records = []
    for kind in HYPOTHESIS_RECORD_KINDS:
        records.extend(store.find(None, kind=kind))
    return [
        domain_hypothesis_shape_from_record(r) for r in records if r.get("root_cause")
    ]


def domain_wrong_hypothesis_track_record(domain_hypotheses, domain, *,
                                          min_group_size=MIN_HYPOTHESES_PER_COMPARISON_GROUP,
                                          margin=HYPOTHESIS_BIAS_MARGIN):
    """Does `domain` (a protocol/domain name) have a real, ELEVATED
    wrong-hypothesis (retraction) rate against the REST of this project's
    own hypothesis history -- the same two-group comparison
    `detect_hypothesis_generation_bias()` already runs for an evidence-
    CATEGORY axis, applied here along the DOMAIN axis instead, and reusing
    that function's own `min_group_size`/`margin` DEFAULTS verbatim (never a
    second, independently-chosen threshold) for the identical resolution-
    band reasoning that module's own module docstring already states.

    `domain_hypotheses` is a list of dicts in `domain_hypothesis_shape_from_
    record()`'s own shape (`hypothesis_id`/`retracted`/`domain`, the last
    possibly `None` for a hypothesis with no recorded protocol at all --
    such a hypothesis contributes to neither comparison group, since it
    names no domain to compare `domain` against).

    Four honest statuses -- reused verbatim from `detect_hypothesis_
    generation_bias()`'s own vocabulary, never a second, parallel one:
      BIAS_STATUS_NOT_AVAILABLE        no hypotheses supplied at all.
      BIAS_STATUS_INSUFFICIENT_HISTORY either comparison group (this domain,
                                       or every other domain combined) has
                                       fewer than `min_group_size` real
                                       hypotheses -- a real, honest answer
                                       about this project's own current
                                       history, never a fabricated rate.
      BIAS_STATUS_NO_BIAS_DETECTED     both groups were comparable, and the
                                       gap between their retraction rates
                                       does not exceed `margin`.
      BIAS_STATUS_BIAS_DETECTED        this domain's own retraction rate
                                       exceeds every OTHER domain's combined
                                       rate by more than `margin`.
    A domain whose OWN rate is LOWER than the rest of the corpus by more
    than `margin` is also `BIAS_STATUS_NO_BIAS_DETECTED` -- this function
    answers one specific, one-directional question ("is this domain worse
    than the rest"), never the reverse claim that a domain scoring better
    than average should reduce recommended effort, which would need
    separate, dedicated justification this function does not attempt.
    """
    if not isinstance(domain_hypotheses, list):
        raise ValueError("domain_hypotheses must be a list of dicts")
    if not isinstance(domain, str) or not domain.strip():
        raise ValueError(f"domain must be a non-empty string, got {domain!r}")
    _require_positive_int(min_group_size, "min_group_size")
    _require_unit_margin(margin, "margin")

    domain_norm = domain.strip().lower()
    parsed = []
    for h in domain_hypotheses:
        if not isinstance(h, dict):
            raise ValueError(f"each domain hypothesis must be a dict, got {h!r}")
        retracted = h.get("retracted")
        if not isinstance(retracted, bool):
            raise ValueError(
                f"domain hypothesis {h.get('hypothesis_id')!r}: retracted must be a bool, "
                f"got {retracted!r}"
            )
        d = h.get("domain")
        parsed.append({
            "retracted": retracted,
            "domain_norm": str(d).strip().lower() if d else None,
        })

    base = {"domain": domain, "min_group_size": min_group_size, "margin": margin}

    if not parsed:
        return dict(
            base, status=BIAS_STATUS_NOT_AVAILABLE, reason="NO_HYPOTHESES_SUPPLIED",
            matching_count=0, other_count=0, matching_wrong_rate=None, other_wrong_rate=None,
        )

    matching = [p for p in parsed if p["domain_norm"] == domain_norm]
    other = [p for p in parsed if p["domain_norm"] is not None and p["domain_norm"] != domain_norm]

    if len(matching) < min_group_size or len(other) < min_group_size:
        return dict(
            base, status=BIAS_STATUS_INSUFFICIENT_HISTORY,
            reason=(
                f"matching_count={len(matching)}, other_count={len(other)}; "
                f"{min_group_size} required in both groups before a comparison has "
                f"resolution finer than {int(margin * 100)} percentage points"
            ),
            matching_count=len(matching), other_count=len(other),
            matching_wrong_rate=None, other_wrong_rate=None,
        )

    def _rate(group):
        return sum(1 for p in group if p["retracted"]) / len(group)

    matching_rate = _rate(matching)
    other_rate = _rate(other)
    gap = matching_rate - other_rate
    if gap > margin:
        status = BIAS_STATUS_BIAS_DETECTED
        reason = (
            f"hypotheses for domain {domain!r} were retracted {matching_rate:.0%} of the "
            f"time ({len(matching)} hypotheses) vs. {other_rate:.0%} for every other domain "
            f"combined ({len(other)} hypotheses)"
        )
    else:
        status = BIAS_STATUS_NO_BIAS_DETECTED
        reason = "NO_ELEVATED_WRONG_HYPOTHESIS_RATE_FOR_THIS_DOMAIN"

    return dict(
        base, status=status, reason=reason,
        matching_count=len(matching), other_count=len(other),
        matching_wrong_rate=round(matching_rate, 4), other_wrong_rate=round(other_rate, 4),
        margin_observed=round(gap, 4),
    )


def _contentiousness_signal_effort(source_authority_report):
    """Map a real `source_authority_order_validation.build_report(...).to_dict()`
    result onto a candidate effort level -- see this section's own module
    comment for the reasoning. Returns `(effort_level, reason)`."""
    if not source_authority_report:
        return "STANDARD", "no source_authority_order_validation report supplied for this question"
    status = source_authority_report.get("status")
    if status == "ORDER_DIVERGES_FROM_PRACTICE":
        return "THOROUGH", (
            f"source_authority_order_validation reports ORDER_DIVERGES_FROM_PRACTICE "
            f"({source_authority_report.get('mismatches')} real mismatch(es) out of "
            f"{source_authority_report.get('evaluable_cases')} evaluable conflict "
            f"escalation(s)) -- this project's own history shows humans repeatedly "
            f"overriding the fixed authority order, a real, cited sign this class of "
            f"question is genuinely contentious"
        )
    if status == "ORDER_MATCHES_PRACTICE":
        return "MINIMAL", (
            f"source_authority_order_validation reports ORDER_MATCHES_PRACTICE over "
            f"{source_authority_report.get('evaluable_cases')} evaluable conflict "
            f"escalation(s) with zero mismatches -- real evidence this project's fixed "
            f"authority order has not been contested in practice"
        )
    return "STANDARD", (
        f"source_authority_order_validation reports {status!r} -- no real evaluable "
        f"conflict-escalation history either way"
    )


def _domain_track_record_signal_effort(domain_track_record):
    """Map a real `domain_wrong_hypothesis_track_record(...)` result onto a
    candidate effort level. Returns `(effort_level, reason)`."""
    if not domain_track_record:
        return "STANDARD", "no domain wrong-hypothesis track record supplied for this question"
    status = domain_track_record.get("status")
    domain = domain_track_record.get("domain")
    if status == BIAS_STATUS_BIAS_DETECTED:
        return "THOROUGH", (
            f"domain {domain!r} shows a real, elevated wrong-hypothesis (retraction) rate "
            f"against this project's own hypothesis history: {domain_track_record.get('reason')}"
        )
    if status == BIAS_STATUS_NO_BIAS_DETECTED:
        return "MINIMAL", (
            f"domain {domain!r} shows no elevated wrong-hypothesis rate against this "
            f"project's own hypothesis history (matching_wrong_rate="
            f"{domain_track_record.get('matching_wrong_rate')}, other_wrong_rate="
            f"{domain_track_record.get('other_wrong_rate')})"
        )
    return "STANDARD", (
        f"domain {domain!r} wrong-hypothesis track record is {status!r} -- "
        f"{domain_track_record.get('reason')}"
    )


def recommend_evidence_gathering_effort(root=None, *, domain=None, store=None,
                                         source_authority_report=None,
                                         domain_track_record=None):
    """Recommend how many independent agents / how much evidence-gathering
    effort a given question likely needs -- informed by the two real
    signals this section's own module comment names. A RECOMMENDATION
    ONLY: it never dispatches an agent, runs a build, submits a job, or
    writes any state itself; whether and how to act on it stays a
    caller/Workflow-script decision.

    Both signals may be supplied pre-computed (`source_authority_report`,
    `domain_track_record` -- e.g. from a caller that already ran
    `source_authority_order_validation.build_report()`/
    `domain_wrong_hypothesis_track_record()` itself, or from a unit test),
    or this function computes them itself from a real project `root` when
    they are omitted:
      - `source_authority_report` is built via `source_authority_order_
        validation.build_report(root)` (a real, read-only project scan --
        see that module's own docstring; it never writes anything).
      - `domain_track_record` is built via `collect_domain_hypothesis_
        shapes(root, store=store)` + `domain_wrong_hypothesis_track_
        record(..., domain)`, and ONLY when `domain` was actually supplied
        -- with no domain named, there is nothing to compare against the
        rest of the corpus, so this signal honestly stays absent rather
        than guessing a domain from `root` alone.
    Omitting `root` (and both pre-computed reports) leaves BOTH signals
    honestly absent, and the recommendation stays at the neutral STANDARD
    baseline -- an absence of real history is never read as license to use
    fewer agents.

    The final recommendation is the WORST-WINS (most cautious) of the two
    signals' own independently-derived effort levels -- MINIMAL < STANDARD
    < THOROUGH -- never averaged: a single real THOROUGH-worthy signal
    outranks an otherwise-clean MINIMAL one, the same worst-wins discipline
    every composite gate in this project already applies.
    """
    if source_authority_report is None and root is not None:
        from . import source_authority_order_validation as _saov
        source_authority_report = _saov.build_report(root).to_dict()

    if domain_track_record is None and root is not None and domain:
        shapes = collect_domain_hypothesis_shapes(root, store=store)
        domain_track_record = domain_wrong_hypothesis_track_record(shapes, domain)

    level_1, reason_1 = _contentiousness_signal_effort(source_authority_report)
    level_2, reason_2 = _domain_track_record_signal_effort(domain_track_record)

    final_level = max((level_1, level_2), key=lambda lvl: EFFORT_LEVEL_RANK[lvl])

    return {
        "recommended_evidence_gathering_effort": final_level,
        "recommended_min_independent_agents": EFFORT_LEVEL_MIN_INDEPENDENT_AGENTS[final_level],
        "reasons": [reason_1, reason_2],
        "signals": {
            "source_authority_contentiousness": {
                "effort_level": level_1, "reason": reason_1, "report": source_authority_report,
            },
            "domain_wrong_hypothesis_track_record": {
                "effort_level": level_2, "reason": reason_2, "report": domain_track_record,
            },
        },
        "disclosure": RECOMMENDATION_DISCLOSURE,
    }


# ---------------------------------------------------------------------------
# Agent self-escalation to more compute (mid-task low-confidence signal)
# (2026-09-07, agent_self_escalation)
#
# WHAT THIS ADDS. A real, AGENT-FACING (never human-facing) signal: when an
# agent's own mid-investigation self-assessment -- reusing score_confidence()'s
# exact {"level", "score", "capped_by_counter_evidence"} shape, the same real
# result dv_harness/engine.py's _react_step_inference()/_score_root_cause_
# confidence() already compute per stage attempt -- lands on LOW, this module
# can build a real, structured "deeper investigation needed" record for a
# caller (dv_harness/engine.py) to persist and for a caller/graph orchestrator
# to later read and decide, on its own, whether to fan out further.
#
# REUSE OVER REINVENT, checked before writing a line of this. score_confidence()
# itself is completely untouched: this section reuses its RESULT (the exact
# dict it already returns), never its formula, weights, or thresholds -- per
# this project's own Evidence Truth Rule, a weight/threshold change proposal
# must never be applied directly to production scoring, routed instead through
# capability_evolution.py's controlled-experiment machinery for a human to
# approve. This section proposes no such change at all; it only reads an
# already-computed confidence level and decides, from that alone, whether a
# "look deeper" signal is warranted.
#
# DISTINCT FROM question_queue.py's 3-tier protocol, by design, not by
# oversight. That module's SELF_RESOLVE/SAFE_TO_ASSUME/CANNOT_ASSUME ladder
# answers "does a HUMAN need to be asked, and if so how urgently" -- every
# record it produces is addressed to a person, sits in a persisted question
# queue, and (at Tier 3) BLOCKS a stage until answered. Nothing here is
# addressed to a human, nothing here blocks anything, and nothing here is a
# question at all: it is a fact about THIS agent's OWN mid-investigation
# confidence, for a caller (a graph orchestrator, a fan-out decision) to read
# and act on -- or not -- entirely on its own initiative.
# assert_escalation_signal_vocabulary_disjoint() below holds the two
# vocabularies apart at import time, the same "checked, not merely claimed"
# discipline several sibling modules in this codebase already apply to their
# own domain vocabularies.
#
# WHAT THIS SECTION DELIBERATELY DOES NOT DO.
#   * It never dispatches an agent, runs a build, submits a job, or forces
#     dv_harness/engine.py to fan out further -- recording the signal is the
#     whole of this item's own scope; ACTING on it (or not) stays entirely a
#     caller/graph-orchestrator decision.
#   * It never files, answers, or otherwise touches a question_queue.py
#     record, and never blocks a stage.
#   * It never recomputes or overrides score_confidence()'s own result -- it
#     only reads the real dict that function already returned.

#: The one recognized signal kind this section ever emits. Deliberately a
#: different WORD and a different WORD FAMILY from CONFIDENCE_LEVELS
#: ("HIGH"/"MEDIUM"/"LOW") and from question_queue.py's own TIER_NAMES
#: ("SELF_RESOLVE"/"SAFE_TO_ASSUME"/"CANNOT_ASSUME") -- checked disjoint from
#: both at import time by assert_escalation_signal_vocabulary_disjoint().
DEEPER_INVESTIGATION_NEEDED_SIGNAL = "DEEPER_INVESTIGATION_NEEDED"

ESCALATION_SIGNAL_DISCLOSURE = (
    "ADVISORY, AGENT-FACING ONLY -- not a question addressed to a human (see "
    "dv_harness.question_queue.py for that separate, human-facing protocol). "
    "This signal records that THIS agent's own mid-investigation "
    "score_confidence() assessment landed LOW, for a caller/graph orchestrator "
    "to read and decide, entirely on its own, whether to fan out additional "
    "agents. Recording it never itself dispatches an agent, runs a build, "
    "submits a job, or forces any further action."
)


def assert_escalation_signal_vocabulary_disjoint():
    """Run at import: DEEPER_INVESTIGATION_NEEDED_SIGNAL must share no token
    with this module's own CONFIDENCE_LEVELS, nor with question_queue.py's
    real TIER_NAMES values. The latter is re-derived as a literal set here
    rather than imported at module load, preserving this module's own stated
    dependency-free-for-pure-math-callers design (see collect_hypothesis_
    shapes()'s own docstring) for this section too."""
    if DEEPER_INVESTIGATION_NEEDED_SIGNAL in CONFIDENCE_LEVELS:
        raise AssertionError(
            "DEEPER_INVESTIGATION_NEEDED_SIGNAL collides with inference.CONFIDENCE_LEVELS"
        )
    _question_queue_tier_tokens = {"SELF_RESOLVE", "SAFE_TO_ASSUME", "CANNOT_ASSUME"}
    if DEEPER_INVESTIGATION_NEEDED_SIGNAL in _question_queue_tier_tokens:
        raise AssertionError(
            "DEEPER_INVESTIGATION_NEEDED_SIGNAL collides with question_queue.py's TIER_NAMES"
        )


assert_escalation_signal_vocabulary_disjoint()


def build_deeper_investigation_signal(confidence_result, *, stage, context_path=None,
                                       gap=None, reason=None):
    """Build a real, structured "deeper investigation needed" signal from an
    ALREADY-COMPUTED score_confidence() result -- the exact
    {"level", "score", "capped_by_counter_evidence"} dict that function (or
    score_confidence_with_consensus()) already returns, never re-derived or
    recomputed here.

    Returns None -- no signal -- unless confidence_result["level"] == "LOW".
    A MEDIUM or HIGH assessment genuinely does not warrant this signal; the
    caller (dv_harness/engine.py) is expected to call this after every real
    per-attempt score_confidence() call and simply do nothing when the result
    is None -- the same "an absent finding is a real answer, not an error"
    convention detect_hypothesis_generation_bias()'s own NO_BIAS_DETECTED
    status already uses one section above.

    `stage` is the real graph-node/stage name this assessment was computed
    for -- required and non-empty, since a signal naming no stage would be
    unusable by any reader trying to decide where to act. `context_path` is
    an optional pointer to where the underlying evidence lives (e.g. a
    Blackboard topic, a react/ iteration file); `gap` is the real
    identify_gap() result for this same attempt, when the caller has one
    (never invented here, and never required); `reason` is an optional
    human-readable one-liner -- when omitted, a real, honest default is used.

    This is a pure function: it performs no I/O, dispatches nothing, and
    writes no state. Persisting the returned dict (or not) is entirely the
    caller's job -- see dv_harness/engine.py's
    _record_agent_escalation_signal() for the one real production caller."""
    if not isinstance(confidence_result, dict) or "level" not in confidence_result:
        raise ValueError(
            f"confidence_result must be a dict carrying score_confidence()'s own "
            f"'level' key, got {confidence_result!r}"
        )
    level = confidence_result["level"]
    if level not in CONFIDENCE_LEVELS:
        raise ValueError(
            f"confidence_result['level'] must be one of {CONFIDENCE_LEVELS}, got {level!r}"
        )
    if not isinstance(stage, str) or not stage.strip():
        raise ValueError(f"stage must be a non-empty string, got {stage!r}")
    if gap is not None and not (
        isinstance(gap, list) and all(isinstance(g, str) for g in gap)
    ):
        raise ValueError(f"gap must be a list of strings or None, got {gap!r}")
    if context_path is not None and not isinstance(context_path, str):
        raise ValueError(f"context_path must be a string or None, got {context_path!r}")
    if reason is not None and not isinstance(reason, str):
        raise ValueError(f"reason must be a string or None, got {reason!r}")

    if level != "LOW":
        return None

    return {
        "signal": DEEPER_INVESTIGATION_NEEDED_SIGNAL,
        "stage": stage,
        "context_path": context_path,
        "confidence_detail": confidence_result,
        "gap": list(gap) if gap else [],
        "reason": reason or (
            "score_confidence() assessed this stage attempt's own evidence as "
            "LOW confidence -- this agent's own mid-investigation self-"
            "assessment, not a claim about what a human should be asked."
        ),
        "disclosure": ESCALATION_SIGNAL_DISCLOSURE,
    }
