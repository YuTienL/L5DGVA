# dv_harness/qualified_conclusion.py -- the missing first-class "Qualified
# Conclusion" verdict type (AI-mechanism architecture audit, 2026-09-01).
#
# Every ingredient this needed already existed as real, wired, tested code
# BEFORE this module: gates.py's evaluate_stage_evidence_with_detail() (via
# react_loop.py, itself factored through gates._evaluate_stage_evidence_core)
# produces a per-stage gate verdict from real run_gate() script invocations,
# and inference.py's score_confidence() independently recomputes a
# confidence level from real citation counts -- NEVER trusting the agent's
# own self-reported `confidence` field (see engine.py's
# _score_root_cause_confidence docstring, and CLAUDE.md's "Any current root
# cause must be revalidated with current evidence"). What was missing was a
# single object that COMPOSES those two already-real facts into one
# auditable "is this conclusion actually qualified to be trusted" verdict,
# instead of leaving each caller to silently re-derive that judgment (or
# never derive it at all) from the two raw pieces separately.
#
# RULING (qualified-conclusion-implementation task, 2026-09-01): a
# QualifiedConclusion is qualified (is_qualified=True) only when BOTH:
#   - the gate verdict is one gates.py's own evaluate_stage_evidence()
#     docstring already names as promotion-worthy (NO_GATE_REQUIRED or
#     PASS -- "Only NO_GATE_REQUIRED/PASS may promote a stage to
#     Status.PASS"), reused here as QUALIFYING_GATE_VERDICTS rather than
#     re-decided independently, and
#   - the independently-recomputed confidence level is not LOW.
# A GATE_FAIL (internally-inconsistent evidence) disqualifies a conclusion
# regardless of how high its confidence score is: the gate verdict is a
# precondition for trusting the confidence number at all, not a separate
# vote to be averaged against it. An is_qualified=False result is not an
# error -- it is a legitimate "AI Opinion": a bare, not-yet-qualified
# conclusion a human should treat as a lead to investigate, not a verified
# finding. See dv_harness/dashboard.py's Hypothesis & Review card for where
# that AI Opinion / Qualified Conclusion distinction is actually surfaced.
#
# ADVERSARIAL REFUTATION PASS (adversarial_refutation_pass task, 2026-09-07,
# purely additive -- every existing call site/test above is unaffected
# because both new parameters default to today's exact behavior). Mirrors
# this session's own ad hoc Workflow-script "adversarial verify" pattern
# (actively try to refute a claim before trusting it, rather than only
# checking it looks internally consistent) as a real, structurally-forced
# option on this CORE composition, instead of a one-off script convention no
# other caller can reuse. See react_loop.attempt_hypothesis_refutation() for
# the real mechanism that produces a `refutation_result`.
#
# Two independent, additive effects, neither reachable unless a caller
# explicitly passes the new `refutation_result`/`require_refutation_pass`
# arguments (both default to values that reproduce the pre-existing formula
# exactly):
#   - A CONFIRMED refutation (refutation_result["attempted"] is True and
#     ["refuted"] is True -- i.e. a real self-critique pass actually ran and
#     found genuine counter-evidence) disqualifies the conclusion
#     UNCONDITIONALLY, the same "regardless of confidence" precedent
#     GATE_FAIL already sets above -- real counter-evidence must never be
#     silently outvoted by a high confidence score, whether or not the
#     caller opted into `require_refutation_pass`.
#   - `require_refutation_pass=True` additionally REQUIRES a genuinely
#     completed, non-refuting attempt (attempted=True, refuted=False) before
#     is_qualified may be True at all -- an omitted refutation_result, or one
#     whose own attempted field is False (the self-critique step was never
#     run, or ran and could not get a parseable verdict), is treated
#     identically to "not yet run": is_qualified=False, never an error and
#     never a guess in either direction. This is what makes the pass
#     STRUCTURALLY FORCED rather than a flag a caller could set to True
#     without ever actually running the step.
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .inference import CONFIDENCE_LEVELS

# Mirrors gates.evaluate_stage_evidence()'s own promotion check byte-for-byte
# ("Only NO_GATE_REQUIRED/PASS may promote a stage to Status.PASS" --
# dv_harness/gates.py). Deliberately NOT imported from gates.py (that
# module has no such exported constant today, only the inline
# `if verdict in ("NO_GATE_REQUIRED", "PASS")` check in engine.py) -- if
# gates.py's promotion rule ever changes, this tuple must be updated to
# match it, same as engine.py's own inline check would need to be.
QUALIFYING_GATE_VERDICTS = ("NO_GATE_REQUIRED", "PASS")

# The full verdict vocabulary gates.evaluate_stage_evidence()/
# evaluate_stage_evidence_with_detail() may return (see that function's own
# docstring in gates.py). Used only to reject a caller passing something
# that isn't a real gate verdict at all -- never to add a 4th qualifying
# value beyond QUALIFYING_GATE_VERDICTS above.
KNOWN_GATE_VERDICTS = (
    "NO_GATE_REQUIRED", "PASS", "MISSING_EVIDENCE",
    "NEEDS_USER_INPUT", "DV_REVIEW_PENDING", "GATE_FAIL",
)


class InvalidGateVerdictError(ValueError):
    """Raised by build_qualified_conclusion when gate_result is not one of
    KNOWN_GATE_VERDICTS. Follows the CircularDependencyError/
    UnknownDependencyError typed-error convention from
    dv_harness/uvm_generator/generator.py: a short SCREAMING_SNAKE_CASE
    `reason` code plus a concrete `detail` dict -- never a silently-accepted
    unknown verdict string."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class InvalidConfidenceResultError(ValueError):
    """Raised by build_qualified_conclusion when confidence_result is not a
    dict carrying a "level" key from inference.CONFIDENCE_LEVELS -- the
    exact shape inference.score_confidence() always returns. Same typed-
    error convention as InvalidGateVerdictError above."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class InvalidExecutionEvidenceError(ValueError):
    """Raised by build_qualified_conclusion when execution_evidence is not a
    dict -- it must be the same evidence-block dict engine.py's run_stage()
    already extracted via gates.extract_evidence_blocks() and the gate
    already validated, never a placeholder. Same typed-error convention as
    InvalidGateVerdictError above."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class InvalidRefutationResultError(ValueError):
    """Raised by build_qualified_conclusion when the optional
    refutation_result argument is supplied but is not the shape
    react_loop.attempt_hypothesis_refutation() always returns (or an
    equivalent RefutationAttempt) -- a dict/RefutationAttempt carrying real
    boolean `attempted` and `refuted` fields. A caller that omits
    refutation_result entirely (every existing caller, and any new one not
    opting into the refutation pass) never reaches this check at all. Same
    typed-error convention as InvalidGateVerdictError above."""
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass
class RefutationAttempt:
    """Structured record of one adversarial refutation self-critique attempt
    against a specific hypothesis. react_loop.attempt_hypothesis_refutation()
    is the real mechanism that produces one (as a plain dict of these same
    fields, so it composes directly with build_qualified_conclusion()'s
    refutation_result parameter with no adapter/asdict step needed); this
    dataclass exists so a caller building one directly (a test, or a future
    non-react_loop producer) gets the same field set typed and documented,
    and build_qualified_conclusion() accepts either shape interchangeably.

    attempted: True only when a real refutation self-critique call actually
      produced a parseable, structured verdict -- never True merely because a
      caller constructed this object; see attempt_hypothesis_refutation()'s
      own docstring for how it decides this. False means the step was
      skipped, the adapter call failed, or the reply was unparseable -- an
      honest "we tried and could not get a real answer", never conflated with
      "the hypothesis was not refuted" (refuted=False with attempted=False is
      NOT sufficient to satisfy build_qualified_conclusion()'s
      require_refutation_pass option -- see that function's own docstring).
    refuted: True when the self-critique step found genuine, cited
      counter-evidence that undermines the hypothesis. A CONFIRMED refutation
      (attempted=True and refuted=True) disqualifies a conclusion
      unconditionally -- see build_qualified_conclusion()'s own docstring.
    counter_evidence: citations the refutation attempt found (typically empty
      when refuted is False).
    rationale: short factual statement from the self-critique step, never
      free-form chain-of-thought.
    """
    attempted: bool = False
    refuted: bool = False
    counter_evidence: List[str] = field(default_factory=list)
    rationale: str = ""

    def as_dict(self) -> Dict[str, Any]:
        """Plain-dict form -- the same shape
        react_loop.attempt_hypothesis_refutation() returns directly, so
        build_qualified_conclusion() never has to special-case which one it
        was handed."""
        return asdict(self)


def _citations(value: Any) -> List[str]:
    """Normalizes one evidence-block citation field (root_cause_evidence_gate's
    supporting_evidence/causal_chain shape: a list, a dict, a bare truthy
    scalar, or absent) into a flat list of string citations. Mirrors
    engine.py's _score_root_cause_confidence._cite_count() counting rule
    exactly (list/dict length, 1/0 for a bare scalar) but returns the actual
    refs rather than only a count, since QualifiedConclusion.evidence_refs
    needs the citations themselves, not a tally."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, dict):
        return [str(v) for v in value.values()]
    if value:
        return [str(value)]
    return []


@dataclass
class QualifiedConclusion:
    """The first-class AI-conclusion verdict type this harness previously
    had no representation for at all (see module docstring). Every field is
    sourced from an already-real, already-computed upstream fact -- this
    dataclass adds no new inference of its own, only the composition and the
    explicit is_qualified boolean.

    hypothesis: the selected root-cause/finding claim (e.g.
      root_cause_evidence_gate's own `root_cause` field).
    evidence_refs: flat list of citation strings backing the hypothesis
      (supporting_evidence + causal_chain from the same evidence block).
    execution_result: the full evidence-block dict the gate actually
      validated (traceability -- never a summary that could drift from what
      was really checked).
    gate_verdict: gates.py's own per-stage verdict string (one of
      KNOWN_GATE_VERDICTS) for the stage that produced this conclusion.
    inference_confidence: inference.score_confidence()'s own returned dict
      ({"level", "score", "capped_by_counter_evidence"}) -- independently
      recomputed, never the agent's self-reported confidence field.
    is_qualified: True only when gate_verdict is promotion-worthy AND
      inference_confidence["level"] != "LOW" -- see QUALIFYING_GATE_VERDICTS
      and this module's docstring RULING. False means "AI Opinion": a bare,
      not-yet-qualified conclusion. When a caller opted into the adversarial
      refutation pass (see build_qualified_conclusion()'s
      require_refutation_pass parameter), is_qualified additionally reflects
      that outcome -- see the module docstring's "ADVERSARIAL REFUTATION
      PASS" section.
    refutation: the refutation_result this conclusion was composed with, as a
      plain dict, or None when no refutation pass was supplied at all (the
      default for every existing caller). Never itself required to be
      present for is_qualified to be True -- only require_refutation_pass=True
      makes that requirement, and this field simply carries through whatever
      real refutation evidence (or its absence) actually informed the
      composition above.
    """
    hypothesis: str
    evidence_refs: List[str] = field(default_factory=list)
    execution_result: Dict[str, Any] = field(default_factory=dict)
    gate_verdict: str = ""
    inference_confidence: Dict[str, Any] = field(default_factory=dict)
    is_qualified: bool = False
    refutation: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        """Plain-dict form for Blackboard.write()'s JSON-serialized value --
        thin wrapper over dataclasses.asdict so call sites never need to
        import dataclasses themselves just to persist this."""
        return asdict(self)


def build_qualified_conclusion(gate_result: str, confidence_result: Dict[str, Any],
                                execution_evidence: Dict[str, Any],
                                refutation_result: Optional[Any] = None,
                                require_refutation_pass: bool = False) -> QualifiedConclusion:
    """Pure function composing three ALREADY-REAL inputs into one
    QualifiedConclusion:
      - gate_result: the stage-level verdict string
        gates.evaluate_stage_evidence()/react_loop.evaluate_stage_evidence_with_detail()
        already computed for this stage attempt (one of KNOWN_GATE_VERDICTS).
      - confidence_result: the dict inference.score_confidence() already
        computed for this same attempt ({"level", "score",
        "capped_by_counter_evidence"}).
      - execution_evidence: the evidence-block dict
        gates.extract_evidence_blocks() already extracted from the agent's
        response and the gate already validated (e.g.
        root_cause_evidence_gate's payload) -- the real record of what was
        actually executed/claimed, never a placeholder.

    No new computation happens here beyond field extraction/normalization
    and the is_qualified boolean described in this module's docstring
    RULING. Raises only on a genuinely malformed caller input (wrong type,
    unknown verdict string, missing/invalid confidence level) -- a
    legitimate GATE_FAIL or LOW-confidence input is an ordinary, expected
    result (is_qualified=False), never an error.

    refutation_result / require_refutation_pass (adversarial_refutation_pass
    task, 2026-09-07, PURELY ADDITIVE -- both default to values that
    reproduce the pre-existing formula exactly, so every caller above this
    docstring, and every caller that does not pass either argument, is
    completely unaffected):

      refutation_result: optional. The real output of
        react_loop.attempt_hypothesis_refutation() (a plain dict), or an
        equivalent qualified_conclusion.RefutationAttempt -- either shape is
        accepted interchangeably. When supplied, it MUST carry real boolean
        `attempted`/`refuted` fields (raises InvalidRefutationResultError
        otherwise, the same "never silently accept a malformed input" rule
        every other parameter here already follows); `counter_evidence`/
        `rationale` are informational and never validated. Omitting it
        entirely (the default, None) is never an error -- it means "no
        refutation pass was run for this conclusion", the same legitimate,
        expected state as an omitted gate/confidence field being absent from
        execution_evidence.

      require_refutation_pass: optional, default False (today's exact
        behavior -- no refutation pass considered at all). When True,
        is_qualified additionally requires refutation_result to report a
        REAL, COMPLETED, non-refuting attempt (attempted=True AND
        refuted=False) -- an omitted refutation_result, or one whose own
        attempted field is False, is treated identically: is_qualified=False,
        never an error and never a guess. This is what makes the pass
        STRUCTURALLY FORCED: a caller cannot satisfy this requirement by
        merely setting require_refutation_pass=True without also supplying
        evidence that a real self-critique attempt actually completed.

      Independent of require_refutation_pass, a CONFIRMED refutation
      (attempted=True AND refuted=True -- i.e. a real self-critique pass
      actually ran and found genuine counter-evidence) disqualifies the
      conclusion UNCONDITIONALLY, mirroring the GATE_FAIL precedent above:
      real counter-evidence must never be silently outvoted by a high
      confidence score just because the caller never set
      require_refutation_pass=True."""
    if not isinstance(gate_result, str) or gate_result not in KNOWN_GATE_VERDICTS:
        raise InvalidGateVerdictError("UNKNOWN_GATE_VERDICT", {
            "gate_result": gate_result, "known_verdicts": list(KNOWN_GATE_VERDICTS),
        })
    if not isinstance(confidence_result, dict) or confidence_result.get("level") not in CONFIDENCE_LEVELS:
        raise InvalidConfidenceResultError("MALFORMED_CONFIDENCE_RESULT", {
            "confidence_result": confidence_result, "known_levels": list(CONFIDENCE_LEVELS),
        })
    if not isinstance(execution_evidence, dict):
        raise InvalidExecutionEvidenceError("EXECUTION_EVIDENCE_NOT_A_DICT", {
            "execution_evidence": execution_evidence,
        })

    if isinstance(refutation_result, RefutationAttempt):
        refutation_result = refutation_result.as_dict()
    if refutation_result is not None:
        if (not isinstance(refutation_result, dict)
                or not isinstance(refutation_result.get("attempted"), bool)
                or not isinstance(refutation_result.get("refuted"), bool)):
            raise InvalidRefutationResultError("MALFORMED_REFUTATION_RESULT", {
                "refutation_result": refutation_result,
            })

    hypothesis = execution_evidence.get("root_cause")
    if hypothesis is None:
        hypothesis = execution_evidence.get("hypothesis")
    evidence_refs = (
        _citations(execution_evidence.get("supporting_evidence"))
        + _citations(execution_evidence.get("causal_chain"))
    )

    refutation_confirmed_ok = (
        isinstance(refutation_result, dict)
        and refutation_result.get("attempted") is True
        and refutation_result.get("refuted") is False
    )
    refutation_confirmed_refuted = (
        isinstance(refutation_result, dict)
        and refutation_result.get("attempted") is True
        and refutation_result.get("refuted") is True
    )

    is_qualified = (
        gate_result in QUALIFYING_GATE_VERDICTS
        and confidence_result.get("level") != "LOW"
        and not refutation_confirmed_refuted
    )
    if require_refutation_pass:
        is_qualified = is_qualified and refutation_confirmed_ok

    return QualifiedConclusion(
        hypothesis=str(hypothesis) if hypothesis is not None else "",
        evidence_refs=evidence_refs,
        execution_result=dict(execution_evidence),
        gate_verdict=gate_result,
        inference_confidence=dict(confidence_result),
        is_qualified=is_qualified,
        refutation=dict(refutation_result) if isinstance(refutation_result, dict) else None,
    )
