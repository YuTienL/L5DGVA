"""dv_harness/diagnostic_bound_compatibility.py -- L5DGVA v17 (Auto_KC_Debug)
SS471 "Diagnostic Bound Compatibility", the one genuinely new residual this
module closes (a CAP90-wave reconciliation disclosed it as open and
unbuilt; a sibling agent in the same wave separately handles SS476's
KC-operationalization angle -- not touched here).

Primary source, exact quote
(`L5DGVA/L5_DGVA_Generic_MultiLevel_Verification_Contract_v17_ULTRA_STRICT_Auto_KC_Debug.md`,
lines 6396-6403):

    "## 471. Diagnostic Bound Compatibility

    If an existing diagnostic triggers after time T, a bound shorter than T
    cannot prove it ineffective. When intentionally using it, choose an
    evidence-grounded bound allowing trigger, subject to safety/resource
    policy.

    Required: `DiagnosticBoundEvidenceCompatibility_PASS = true`"

What this actually requires, read literally: an existing diagnostic
mechanism (a watchdog, timeout, assertion, or any other mechanism from the
SS470 "Existing Diagnostic Mechanism First" ladder) has some real,
evidence-grounded trigger latency T -- the elapsed time/cycles after which
it fires if its fault condition holds. If the actual OBSERVATION BOUND used
this session (a simulation run-time limit, a log-truncation point, an FSDB
capture window) is shorter than T, then "the diagnostic did not fire within
this bound" is NOT valid evidence that the diagnostic is ineffective or
that its condition never occurred -- it only proves the run stopped before
the diagnostic had a chance to trigger. When a bound is chosen on purpose
to rely on that diagnostic as evidence, it must be an evidence-grounded
bound that allows the trigger (>= T, plus any margin), subject to real
safety/resource policy (wall-clock, license, disk, LSF queue budget) that
may cap how long the bound can practically be.

Disambiguation vs. the already-real neighboring debug-evidence modules
(confirmed by reading each, not merely by section-number adjacency):

- `fsdb_scope_gap_classifier.py` (SS470/472/473) classifies whether a
  REQUIRED SIGNAL is present in the CURRENT FSDB DUMP's scope
  (PRESENT / CURRENT_FSDB_SCOPE_INSUFFICIENT / UNKNOWN) and orders
  candidate evidence SOURCES cheapest-first. It never compares a
  diagnostic's own trigger latency against an observation-time bound --
  its "scope" is signal/hierarchy breadth, not elapsed simulation time.
- `inference.py`'s `arbitrate_next_best_evidence()` (SS477) ranks WHICH
  candidate evidence action to try next by discriminating
  value/cost/runtime/invasiveness. It never asks whether a bound already
  used (or about to be used) was long enough for a specific diagnostic to
  have had a chance to fire -- a cheap-and-highest-ranked candidate under
  SS477 could still be evaluated over a bound too short to trust its
  negative result, and nothing in that module would catch it.
- `reference_wave_config_inherit.py` (SS473) proposes an inherited
  wave/scope DEFAULT from a qualified reference environment's own wave
  configuration. It is about which signals/hierarchy to capture, not
  about whether the chosen capture DURATION is compatible with a
  diagnostic's trigger latency.
- `reference_debug_capability_manifest.py` (SS480) is a static CAPABILITY
  INVENTORY (does a wave.txt/WAVE control/FSDB/fsdbreport/Verdi
  hook/timeout/watchdog/assertion/log-diagnostic mechanism exist at all in
  the reference environment) -- it never evaluates a specific bound
  against a specific trigger latency for a specific debug session.

None of the four sibling modules contains any bound-vs-trigger-latency
comparison, a repo-wide grep for "diagnostic.bound"/"bound.*compat"/
"BoundEvidenceCompatibility" found no prior implementation, and SS471 is
listed in CLAUDE.md's Module Index as a genuinely unbuilt V17 residual.
This module is therefore a real ADD, not a duplicate of any REUSE
candidate -- while still composing with, not re-implementing,
`fsdb_scope_gap_classifier.existing_diagnostic_mechanism_first()`'s and
`inference.arbitrate_next_best_evidence()`'s candidate-dict shape (`kind`,
`cost`, `runtime`, `invasiveness`) so a caller that already tracks
candidates in that shape can hand them to this module unmodified, adding
only the one new field this module needs (`trigger_latency`, with a
`known_trigger_time` fallback name for callers that prefer that spelling).

Scope and honest limits: this module is a pure classification/arithmetic
utility over CALLER-DECLARED numbers. It never measures a diagnostic's
real trigger latency itself (that is real RTL/testbench/spec evidence the
caller must supply, per the Evidence Truth Rule -- inventing T here would
be exactly the false-pass risk SS471 exists to prevent), never runs a
simulation, and never enforces the "safety/resource policy" cap's own
correctness -- it only compares a caller-declared cap against a
caller-declared required bound and reports when they conflict, leaving the
actual policy decision (extend the run, escalate, or accept the gap) to
the caller/human, consistent with `waveform_dump_gate.py`'s existing
"never silently default to full-chip/full-depth" discipline for the
adjacent waveform-scope question.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: classify_diagnostic_bound_compatibility() / classify_candidate_bound_compatibility()
#: result values.
BOUND_COMPATIBLE = "BOUND_COMPATIBLE"
BOUND_INSUFFICIENT = "BOUND_INSUFFICIENT"
TRIGGER_LATENCY_UNKNOWN = "TRIGGER_LATENCY_UNKNOWN"
OBSERVATION_BOUND_UNKNOWN = "OBSERVATION_BOUND_UNKNOWN"

BOUND_COMPATIBILITY_VALUES = frozenset({
    BOUND_COMPATIBLE,
    BOUND_INSUFFICIENT,
    TRIGGER_LATENCY_UNKNOWN,
    OBSERVATION_BOUND_UNKNOWN,
})

#: recommend_evidence_grounded_bound() status values.
RECOMMENDED_BOUND_WITHIN_POLICY = "RECOMMENDED_BOUND_WITHIN_POLICY"
BOUND_CAPPED_BELOW_TRIGGER_LATENCY = "BOUND_CAPPED_BELOW_TRIGGER_LATENCY"


def _as_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def classify_diagnostic_bound_compatibility(trigger_latency: Optional[float],
                                             observation_bound: Optional[float],
                                             *, margin: float = 0.0) -> Dict[str, Any]:
    """The core SS471 classifier: is `observation_bound` (the actual/proposed
    elapsed-time-or-cycles limit a debug session stopped or will stop at --
    a simulation run-time limit, a log-truncation point, an FSDB capture
    window) long enough that "the diagnostic did not trigger within it" is
    valid negative evidence for `trigger_latency` (the diagnostic's own
    real, evidence-grounded elapsed-time-or-cycles-to-fire, in the same
    units as `observation_bound` -- this module compares magnitudes only
    and never invents or converts units itself)?

    Returns a dict:
      - `compatibility`: one of BOUND_COMPATIBILITY_VALUES.
      - `can_prove_ineffective`: True only for BOUND_COMPATIBLE -- every
        other outcome must never be read as "the diagnostic is ineffective
        / the condition did not occur," per SS471's literal text ("a bound
        shorter than T cannot prove it ineffective").
      - `reason`: a short human-readable citation of which SS471 clause
        applied.

    `trigger_latency is None` -> TRIGGER_LATENCY_UNKNOWN: SS471 presupposes
    a real, known T; with no T declared this module refuses to guess one
    (never silently treats "unknown" as "already elapsed" or "never
    elapses"). `observation_bound is None` -> OBSERVATION_BOUND_UNKNOWN,
    the symmetric refusal on the other input. `margin` (>= 0, default 0) is
    an optional caller-declared safety margin added to `trigger_latency`
    before the comparison (e.g. to require the bound clear T by some
    guard-band rather than exactly meet it) -- never invented by this
    function itself.
    """
    t = _as_number(trigger_latency)
    b = _as_number(observation_bound)
    m = _as_number(margin)
    m = m if m is not None and m >= 0 else 0.0

    if t is None:
        return {
            "compatibility": TRIGGER_LATENCY_UNKNOWN,
            "can_prove_ineffective": False,
            "reason": "trigger_latency (T) not declared -- SS471 requires a real, "
                      "evidence-grounded T before any bound can be judged compatible.",
        }
    if b is None:
        return {
            "compatibility": OBSERVATION_BOUND_UNKNOWN,
            "can_prove_ineffective": False,
            "reason": "observation_bound not declared -- cannot compare against T.",
        }
    required = t + m
    if b >= required:
        return {
            "compatibility": BOUND_COMPATIBLE,
            "can_prove_ineffective": True,
            "reason": f"observation_bound ({b}) >= trigger_latency+margin ({required}); "
                      "the diagnostic had a real chance to fire, so a non-trigger result "
                      "is valid negative evidence.",
        }
    return {
        "compatibility": BOUND_INSUFFICIENT,
        "can_prove_ineffective": False,
        "reason": f"observation_bound ({b}) < trigger_latency+margin ({required}); per "
                  "SS471, a bound shorter than T cannot prove the diagnostic ineffective "
                  "-- the run stopped before it could have triggered.",
    }


def _candidate_field(candidate: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in candidate:
            return candidate[name]
    return None


def classify_candidate_bound_compatibility(candidate: Dict[str, Any],
                                            observation_bound: Optional[float],
                                            *, margin: float = 0.0) -> Dict[str, Any]:
    """Same classification as `classify_diagnostic_bound_compatibility()`,
    applied to one candidate dict in the shape already used by
    `fsdb_scope_gap_classifier.existing_diagnostic_mechanism_first()` and
    `inference.arbitrate_next_best_evidence()` (`kind`, `cost`, `runtime`,
    `invasiveness`, ...) -- so a caller relying on an existing diagnostic
    from that SS470 ladder can hand this module the same dict unmodified,
    adding only `trigger_latency` (or, for callers preferring that
    spelling, `known_trigger_time`).

    Returns the same dict `classify_diagnostic_bound_compatibility()`
    returns, plus the original `candidate` and its `kind` (when present)
    echoed back for the caller's own bookkeeping.
    """
    candidate = candidate if isinstance(candidate, dict) else {}
    trigger_latency = _candidate_field(candidate, "trigger_latency", "known_trigger_time")
    result = classify_diagnostic_bound_compatibility(trigger_latency, observation_bound, margin=margin)
    result["candidate"] = candidate
    result["kind"] = candidate.get("kind")
    return result


def filter_bound_compatible_candidates(candidates: Sequence[Dict[str, Any]],
                                        observation_bound: Optional[float],
                                        *, margin: float = 0.0) -> Dict[str, List[Dict[str, Any]]]:
    """Partition a list of existing-diagnostic candidates (SS470 shape) by
    SS471 bound compatibility against one real `observation_bound`.

    Returns `{"compatible": [...], "incompatible": [...]}` -- `compatible`
    holds every candidate `classify_candidate_bound_compatibility()` scored
    BOUND_COMPATIBLE (a non-trigger result from these is valid negative
    evidence); `incompatible` holds every other outcome (BOUND_INSUFFICIENT,
    TRIGGER_LATENCY_UNKNOWN, OBSERVATION_BOUND_UNKNOWN), each still
    annotated with its full classification result so the caller can see
    exactly why. This never drops or reorders candidates beyond the
    two-way split -- ordering by cost/value stays
    `existing_diagnostic_mechanism_first()`'s / `arbitrate_next_best_evidence()`'s
    job, not this module's.
    """
    compatible: List[Dict[str, Any]] = []
    incompatible: List[Dict[str, Any]] = []
    for candidate in candidates:
        result = classify_candidate_bound_compatibility(candidate, observation_bound, margin=margin)
        (compatible if result["compatibility"] == BOUND_COMPATIBLE else incompatible).append(result)
    return {"compatible": compatible, "incompatible": incompatible}


def recommend_evidence_grounded_bound(trigger_latency: Optional[float],
                                       *, safety_resource_cap: Optional[float] = None,
                                       margin: float = 0.0) -> Dict[str, Any]:
    """SS471's second clause: "When intentionally using it, choose an
    evidence-grounded bound allowing trigger, subject to safety/resource
    policy." Given a real, caller-declared `trigger_latency` (T) and an
    optional real `safety_resource_cap` (the largest bound safety/resource
    policy -- wall-clock, license seat time, disk, LSF queue budget --
    actually permits), propose the smallest bound that both allows the
    trigger (>= T + margin) and respects the cap.

    Returns a dict:
      - `status`: TRIGGER_LATENCY_UNKNOWN (T not declared -- nothing to
        recommend), RECOMMENDED_BOUND_WITHIN_POLICY (a compatible bound
        exists at or under the cap, or no cap was declared),
        BOUND_CAPPED_BELOW_TRIGGER_LATENCY (a real cap was declared and it
        is itself shorter than T + margin -- no bound choice can be both
        evidence-grounded and within policy; this is a genuine escalation
        case, never silently resolved by this function).
      - `recommended_bound`: the proposed bound (T + margin, or the cap
        when a cap was declared, whichever the status implies) -- None
        when status is TRIGGER_LATENCY_UNKNOWN.
      - `reason`: short citation of which branch applied.

    This function never widens a bound past what T + margin requires (no
    "just dump everything" default, matching CLAUDE.md's Waveform Dump User
    Gate discipline) and never silently drops the cap conflict -- a capped
    case is reported, not resolved, for a human/caller to decide (extend
    policy, accept the residual gap, or escalate).
    """
    t = _as_number(trigger_latency)
    if t is None:
        return {
            "status": TRIGGER_LATENCY_UNKNOWN,
            "recommended_bound": None,
            "reason": "trigger_latency (T) not declared -- cannot propose an "
                      "evidence-grounded bound without a real T.",
        }
    m = _as_number(margin)
    m = m if m is not None and m >= 0 else 0.0
    required = t + m
    cap = _as_number(safety_resource_cap)
    if cap is not None and cap < required:
        return {
            "status": BOUND_CAPPED_BELOW_TRIGGER_LATENCY,
            "recommended_bound": cap,
            "reason": f"safety_resource_cap ({cap}) is shorter than trigger_latency+margin "
                      f"({required}); no bound can be both evidence-grounded and within "
                      "policy -- escalate rather than silently accepting a non-trigger "
                      "result as proof of ineffectiveness.",
        }
    return {
        "status": RECOMMENDED_BOUND_WITHIN_POLICY,
        "recommended_bound": required,
        "reason": f"recommended_bound = trigger_latency+margin ({required})"
                  + (f", within safety_resource_cap ({cap})" if cap is not None else
                     " (no safety_resource_cap declared)"),
    }
