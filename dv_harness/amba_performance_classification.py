"""dv_harness/amba_performance_classification.py -- AMBA/AXI-class PERFORMANCE
CLASSIFICATION over real, CALLER-SUPPLIED numbers only (2026-09-06).

THIS IS THE HIGHEST FABRICATION-RISK DOMAIN IN THIS PROJECT, AND THIS MODULE
IS BUILT AROUND THAT -- same three hard rules `amba_performance_calculator.py`
already enforces in code, applied here to CLASSIFICATION rather than raw
arithmetic:

  (a) a numeric threshold/target/baseline is NEVER invented -- it is always
      CALLER-declared, or the result is `NOT_APPLICABLE`.
  (b) an unprovable peak/baseline/metric yields `UNKNOWN`, never a
      computed-looking percentage or number. No function here reads any
      FSDB/waveform file, simulates anything, or estimates a plausible-
      looking number when the real input is missing.
  (c) functional correctness ALWAYS outranks a performance PASS -- this
      module does not reimplement that precedence (see REUSE below); it
      calls `amba_performance_calculator.decide_overall_verdict()` directly.

FOUR CLASSIFIERS, EACH REQUIRING AT LEAST TWO CORRELATED REAL METRICS
----------------------------------------------------------------------
Per this batch's own task rule, no classifier here ever concludes anything
from ONE metric alone -- an insufficient/absent second metric always yields
`UNKNOWN`/`NOT_APPLICABLE`, never a guessed conclusion:

  1. `classify_saturation()` -- utilization near a caller-declared max
     ceiling ALONGSIDE a real rising-latency or rising-stall signal. Either
     metric alone is `UNKNOWN`; the two DISAGREEING is `INDETERMINATE`, never
     silently resolved in either direction.
  2. `identify_bottleneck_candidate()` -- a structured
     Hypothesis -> Evidence -> Confidence -> Gap -> Next-Best-Action record
     (see `inference.py` for the pattern this matches in shape/spirit --
     deliberately NOT imported: that module's `score_confidence()` counts
     generic corroborating evidence for an arbitrary claim, and reusing it
     here would conflate its evidence-quantity vocabulary with this domain's
     own performance-metric-count discipline). NEVER a bare label -- building
     one with fewer than 2 real correlated evidence citations is refused.
  3. `detect_anomaly()` -- a real observed sample compared against a real
     caller-supplied baseline/historical range or distribution. An absent
     baseline is `NOT_APPLICABLE` (rule (a)); an absent observation is
     `UNKNOWN` (rule (b)); this module never fabricates a baseline.
  4. `compute_regression_delta()` -- two real measured samples/periods,
     reported IMPROVED/REGRESSED/UNCHANGED/INCONCLUSIVE. INCONCLUSIVE is
     returned, never a fabricated percentage, whenever the two samples are
     not genuinely comparable (different declared units or measurement
     windows, or an undefined percent-change against a zero baseline).

`compute_jains_fairness_index()` is the real, well-known one-line Jain's
fairness-index formula (`J = (sum(x_i))**2 / (n * sum(x_i**2))`),
included because this batch's source document calls for a fairness/
QoS-inversion check. It REFUSES to compute -- `UNKNOWN`, never a value
silently computed over the requesters that happened to report -- the moment
ANY declared requester's value is missing, per rule (b) applied to a
multi-requester metric.

REUSE OVER REINVENT
--------------------
This module imports `amba_performance_calculator.decide_overall_verdict()`
(and its `STATUS_UNKNOWN`/`STATUS_NOT_APPLICABLE`/`STATUS_COMPUTED` tokens)
directly rather than reimplementing rule (c) a second time --
`decide_overall_performance_verdict()` below is a thin adapter mapping this
module's own regression-delta verdict onto that function's
`performance_verdict` parameter, so there is exactly one place in this
project that decides "does functional correctness outrank a performance
result". It imports nothing else from `dv_harness` -- it does not read any
FSDB/waveform file (that stays `fsdb_report.py`'s job, read only for shape,
never imported), does not import `inference.py` (per this task's own
instruction -- only its Hypothesis/Evidence/Confidence/Gap/Next-Best-Action
SHAPE is matched, independently, since this domain's own confidence
derivation is metric-count-based rather than generic evidence-quantity-based),
and imports no other module from this or any other batch.

WHAT THIS MODULE DOES NOT DO
-----------------------------
It does not monitor a live signal, parse an FSDB/waveform, generate traffic,
or run a simulation -- all explicitly out of scope for this batch (this
harness has no live simulator to validate any of that against; a "live
signal monitor" or "FSDB parser" request against this module reports
`NOT_AVAILABLE` in the caller's own evidence-gathering step, never something
this module attempts). It decides, approves, and arbitrates nothing beyond
its own classification: no gate, no approval, no build/regression/LSF
submission.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

from .amba_performance_calculator import (
    STATUS_COMPUTED as _CALC_STATUS_COMPUTED,
    STATUS_NOT_APPLICABLE as _CALC_STATUS_NOT_APPLICABLE,
    STATUS_UNKNOWN as _CALC_STATUS_UNKNOWN,
    OverallVerdictResult,
    decide_overall_verdict,
)
from .models import Status

# --- errors ----------------------------------------------------------------


class PerformanceClassificationError(ValueError):
    """Caller misuse -- a malformed/contradictory input, never a missing-data
    case (those are always reported as `UNKNOWN`/`NOT_APPLICABLE`, not
    raised).
    """


# --- vocabulary --------------------------------------------------------

#: Shared with `amba_performance_calculator.py`'s own vocabulary (rules
#: (a)/(b) as code): a value was really computed from real, caller-supplied
#: numbers.
STATUS_COMPUTED = _CALC_STATUS_COMPUTED
#: The real input needed was missing, empty, or unusable -- never silently
#: read as zero or as "no anomaly"/"not saturated".
STATUS_UNKNOWN = _CALC_STATUS_UNKNOWN
#: The classification genuinely does not apply because no caller-declared
#: threshold/baseline/max exists to evaluate against.
STATUS_NOT_APPLICABLE = _CALC_STATUS_NOT_APPLICABLE

#: Saturation classification statuses.
SATURATION_SATURATED = "SATURATED"
SATURATION_NOT_SATURATED = "NOT_SATURATED"
#: The two correlated metrics DISAGREE (one signals saturation, the other
#: does not) -- never silently resolved to either SATURATED or NOT_SATURATED.
SATURATION_INDETERMINATE = "INDETERMINATE"

SATURATION_STATUSES = (
    SATURATION_SATURATED,
    SATURATION_NOT_SATURATED,
    SATURATION_INDETERMINATE,
    STATUS_UNKNOWN,
    STATUS_NOT_APPLICABLE,
)

#: Anomaly-detection statuses.
ANOMALY_DETECTED = "ANOMALY_DETECTED"
NO_ANOMALY = "NO_ANOMALY"

ANOMALY_STATUSES = (
    ANOMALY_DETECTED,
    NO_ANOMALY,
    STATUS_UNKNOWN,
    STATUS_NOT_APPLICABLE,
)

#: Regression-delta verdicts.
REGRESSION_IMPROVED = "IMPROVED"
REGRESSION_REGRESSED = "REGRESSED"
REGRESSION_UNCHANGED = "UNCHANGED"
#: The two samples are not genuinely comparable (different measurement
#: windows/units, or an undefined percent-change against a zero baseline) --
#: never a fabricated percentage in this case.
REGRESSION_INCONCLUSIVE = "INCONCLUSIVE"

REGRESSION_VERDICTS = (
    REGRESSION_IMPROVED,
    REGRESSION_REGRESSED,
    REGRESSION_UNCHANGED,
    REGRESSION_INCONCLUSIVE,
    STATUS_UNKNOWN,
)

#: Bottleneck-candidate confidence -- matches `inference.CONFIDENCE_LEVELS`'
#: three-value SPIRIT (HIGH/MEDIUM/LOW), independently derived here from this
#: domain's own correlated-metric-count discipline rather than that module's
#: generic evidence-quantity scoring (see module docstring for why it is not
#: imported).
CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"

CONFIDENCE_LEVELS = (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW)

#: Minimum number of independent, real correlated evidence citations a
#: bottleneck-candidate record may be built from -- "never one metric alone"
#: enforced as a hard construction-time refusal, not merely documented.
MIN_BOTTLENECK_EVIDENCE_COUNT = 2


def _assert_status_vocabulary_disjoint_from_models_status() -> None:
    all_tokens = set(SATURATION_STATUSES)
    all_tokens |= set(ANOMALY_STATUSES)
    all_tokens |= set(REGRESSION_VERDICTS)
    all_tokens |= set(CONFIDENCE_LEVELS)
    collision = all_tokens & {member.value for member in Status}
    if collision:
        raise AssertionError(
            "amba_performance_classification status vocabulary collides "
            f"with dv_harness.models.Status: {sorted(collision)}"
        )


_assert_status_vocabulary_disjoint_from_models_status()


# --- result shapes -----------------------------------------------------


@dataclass(frozen=True)
class SaturationClassificationResult:
    """Rule (b)/task rule as code: `SATURATED` requires BOTH a real
    utilization-near-max signal AND a real rising-latency/rising-stall
    signal -- never one metric alone. See `classify_saturation()`.
    """

    status: str
    utilization_ratio: Optional[float]
    near_max_threshold: Optional[float]
    near_max_observed: Optional[bool]
    rising_signal_observed: Optional[bool]
    reason: str
    evidence: Tuple[str, ...] = ()


@dataclass(frozen=True)
class BottleneckCandidateRecord:
    """A structured Hypothesis -> Evidence -> Confidence -> Gap ->
    Next-Best-Action record -- NEVER a bare label. Built only by
    `identify_bottleneck_candidate()`, which refuses to construct one from
    fewer than `MIN_BOTTLENECK_EVIDENCE_COUNT` real correlated evidence
    citations.
    """

    hypothesis: str
    evidence: Tuple[str, ...]
    confidence: str
    gap: str
    next_best_action: str


@dataclass(frozen=True)
class AnomalyDetectionResult:
    """A real observed sample compared against a real caller-supplied
    baseline. `status` is `NOT_APPLICABLE` whenever no real baseline/
    historical range was supplied -- this module never fabricates one.
    """

    observed_value: Optional[float]
    status: str
    deviation: Optional[float] = None
    reason: Optional[str] = None
    baseline_description: Optional[str] = None


@dataclass(frozen=True)
class RegressionDeltaResult:
    """Two real measured samples/periods, compared. `INCONCLUSIVE` whenever
    the two samples are not genuinely comparable -- never a fabricated
    percentage in that case.
    """

    metric_name: str
    baseline_value: Optional[float]
    current_value: Optional[float]
    percent_change: Optional[float]
    verdict: str
    reason: Optional[str] = None


@dataclass(frozen=True)
class FairnessIndexResult:
    """Jain's fairness index over a real, caller-supplied per-requester
    value map. `status` is `UNKNOWN` the moment any declared requester's
    value is missing -- this module never silently computes over the
    subset that happened to report.
    """

    requester_count: int
    fairness_index: Optional[float]
    status: str
    reason: Optional[str] = None
    missing_requesters: Tuple[str, ...] = ()


# --- 1. saturation classification ---------------------------------------


def classify_saturation(
    utilization_value: Optional[float],
    utilization_max: Optional[float],
    near_max_ratio_threshold: Optional[float],
    *,
    rising_latency_trend: Optional[bool] = None,
    latency_trend_evidence: Optional[str] = None,
    rising_stall_trend: Optional[bool] = None,
    stall_trend_evidence: Optional[str] = None,
) -> SaturationClassificationResult:
    """SATURATED requires TWO real correlated metrics: utilization at or
    above a caller-declared fraction of a caller-declared max, ALONGSIDE a
    real rising-latency or rising-stall trend signal. Neither `utilization_max`
    nor `near_max_ratio_threshold` is ever invented -- both must be supplied
    by the caller (rule (a)), or the result is `NOT_APPLICABLE`.

    A `rising_*_trend` argument of `True` requires its matching `*_evidence`
    citation (a fsdb_report/sim.log-derived description of the real observed
    trend) -- asserting a rising trend with no cited evidence is a caller
    misuse, refused with `PerformanceClassificationError`, never silently
    accepted.
    """
    if utilization_max is None or near_max_ratio_threshold is None:
        return SaturationClassificationResult(
            status=STATUS_NOT_APPLICABLE,
            utilization_ratio=None,
            near_max_threshold=near_max_ratio_threshold,
            near_max_observed=None,
            rising_signal_observed=None,
            reason=(
                "no caller-declared utilization_max/near_max_ratio_threshold "
                "supplied -- a saturation ceiling is never invented"
            ),
        )
    if utilization_max <= 0:
        raise PerformanceClassificationError(
            f"utilization_max must be a positive real number, got {utilization_max!r}"
        )
    if not (0.0 <= near_max_ratio_threshold <= 1.0):
        raise PerformanceClassificationError(
            "near_max_ratio_threshold must be within [0.0, 1.0], got "
            f"{near_max_ratio_threshold!r}"
        )
    if utilization_value is None:
        return SaturationClassificationResult(
            status=STATUS_UNKNOWN,
            utilization_ratio=None,
            near_max_threshold=near_max_ratio_threshold,
            near_max_observed=None,
            rising_signal_observed=None,
            reason="no observed utilization_value supplied",
        )
    if rising_latency_trend is True and not latency_trend_evidence:
        raise PerformanceClassificationError(
            "rising_latency_trend=True requires a real latency_trend_evidence citation"
        )
    if rising_stall_trend is True and not stall_trend_evidence:
        raise PerformanceClassificationError(
            "rising_stall_trend=True requires a real stall_trend_evidence citation"
        )

    evidence: list = []
    ratio = utilization_value / utilization_max
    near_max = ratio >= near_max_ratio_threshold
    evidence.append(
        f"utilization {utilization_value!r}/{utilization_max!r} = {ratio:.4f} "
        f"vs near-max threshold {near_max_ratio_threshold:.4f}"
    )

    if rising_latency_trend is None and rising_stall_trend is None:
        return SaturationClassificationResult(
            status=STATUS_UNKNOWN,
            utilization_ratio=ratio,
            near_max_threshold=near_max_ratio_threshold,
            near_max_observed=near_max,
            rising_signal_observed=None,
            reason=(
                "no rising-latency/rising-stall trend signal supplied -- "
                "saturation classification requires at least two correlated "
                "real metrics, never utilization alone"
            ),
            evidence=tuple(evidence),
        )

    rising = bool(rising_latency_trend) or bool(rising_stall_trend)
    if rising_latency_trend is not None:
        evidence.append(
            f"rising_latency_trend={rising_latency_trend!r}"
            + (f" ({latency_trend_evidence})" if latency_trend_evidence else "")
        )
    if rising_stall_trend is not None:
        evidence.append(
            f"rising_stall_trend={rising_stall_trend!r}"
            + (f" ({stall_trend_evidence})" if stall_trend_evidence else "")
        )

    if near_max and rising:
        return SaturationClassificationResult(
            status=SATURATION_SATURATED,
            utilization_ratio=ratio,
            near_max_threshold=near_max_ratio_threshold,
            near_max_observed=True,
            rising_signal_observed=True,
            reason=(
                "utilization is at/above the declared near-max threshold AND "
                "a real rising-latency/rising-stall signal was observed"
            ),
            evidence=tuple(evidence),
        )
    if (not near_max) and (not rising):
        return SaturationClassificationResult(
            status=SATURATION_NOT_SATURATED,
            utilization_ratio=ratio,
            near_max_threshold=near_max_ratio_threshold,
            near_max_observed=False,
            rising_signal_observed=False,
            reason=(
                "utilization is below the declared near-max threshold AND no "
                "rising-latency/rising-stall signal was observed"
            ),
            evidence=tuple(evidence),
        )
    return SaturationClassificationResult(
        status=SATURATION_INDETERMINATE,
        utilization_ratio=ratio,
        near_max_threshold=near_max_ratio_threshold,
        near_max_observed=near_max,
        rising_signal_observed=rising,
        reason=(
            "the two correlated metrics disagree: utilization "
            f"{'is' if near_max else 'is not'} near the declared max while a "
            f"rising-latency/rising-stall signal {'was' if rising else 'was not'} "
            "observed -- a single metric alone cannot classify saturation, "
            "so this is reported INDETERMINATE rather than resolved either way"
        ),
        evidence=tuple(evidence),
    )


# --- 2. bottleneck-candidate identification -----------------------------


def _derive_bottleneck_confidence(evidence_count: int, has_gap: bool) -> str:
    """Local, domain-specific confidence derivation from a real correlated-
    metric COUNT -- deliberately not `inference.score_confidence()` (see
    module docstring). A real unresolved `gap` caps confidence at MEDIUM: an
    acknowledged unresolved gap can never coexist with HIGH confidence, the
    same "known unaddressed counter-evidence caps confidence" shape
    `inference.score_confidence()`'s own safety floor uses, independently
    re-derived here for this domain's own evidence-count basis.
    """
    if evidence_count >= 3 and not has_gap:
        return CONFIDENCE_HIGH
    return CONFIDENCE_MEDIUM


def identify_bottleneck_candidate(
    hypothesis: str,
    evidence: Sequence[str],
    *,
    gap: Optional[str] = None,
    next_best_action: Optional[str] = None,
) -> BottleneckCandidateRecord:
    """Build a structured bottleneck-CANDIDATE record -- NEVER a bare label.

    `evidence` must carry at least `MIN_BOTTLENECK_EVIDENCE_COUNT` (2) real,
    non-empty, independently-cited correlated metrics (e.g. one utilization
    citation plus one rising-latency citation) -- a hypothesis built on a
    single metric is refused with `PerformanceClassificationError` rather
    than silently reported as a candidate.

    `next_best_action` defaults to a generic "gather more evidence for the
    named gap" fallback (mirroring `inference.next_best_action()`'s own
    generic-fallback convention) when the caller supplies none -- this
    module never invents a concrete DV action.
    """
    if not hypothesis or not hypothesis.strip():
        raise PerformanceClassificationError("hypothesis must be a non-empty string")
    cleaned_evidence = [e for e in evidence if e and e.strip()]
    if len(cleaned_evidence) < MIN_BOTTLENECK_EVIDENCE_COUNT:
        raise PerformanceClassificationError(
            "a bottleneck candidate requires at least "
            f"{MIN_BOTTLENECK_EVIDENCE_COUNT} real, non-empty correlated evidence "
            f"citations (never one metric alone), got {len(cleaned_evidence)}"
        )
    gap_text = gap.strip() if gap and gap.strip() else "no unresolved gap declared"
    has_gap = bool(gap and gap.strip())
    confidence = _derive_bottleneck_confidence(len(cleaned_evidence), has_gap)
    action = (
        next_best_action.strip()
        if next_best_action and next_best_action.strip()
        else (
            "no concrete next-best-action supplied -- gather additional real "
            f"evidence for: {gap_text}"
        )
    )
    return BottleneckCandidateRecord(
        hypothesis=hypothesis.strip(),
        evidence=tuple(cleaned_evidence),
        confidence=confidence,
        gap=gap_text,
        next_best_action=action,
    )


# --- 3. anomaly detection ------------------------------------------------


def detect_anomaly(
    observed_value: Optional[float],
    *,
    baseline_min: Optional[float] = None,
    baseline_max: Optional[float] = None,
    baseline_mean: Optional[float] = None,
    baseline_stddev: Optional[float] = None,
    deviation_threshold_stddev: Optional[float] = None,
) -> AnomalyDetectionResult:
    """A real observed sample compared against a real caller-supplied
    baseline -- either a real historical RANGE (`baseline_min`/
    `baseline_max`) or a real historical DISTRIBUTION
    (`baseline_mean`/`baseline_stddev`/`deviation_threshold_stddev`).

    `observed_value=None` is `UNKNOWN` regardless of baseline availability
    (rule (b), checked first). Absent both baseline forms entirely is
    `NOT_APPLICABLE` (rule (a)) -- this module never fabricates a baseline
    from the observed value alone.
    """
    if observed_value is None:
        return AnomalyDetectionResult(
            observed_value=None,
            status=STATUS_UNKNOWN,
            reason="no observed_value supplied",
        )

    have_range = baseline_min is not None and baseline_max is not None
    have_distribution = (
        baseline_mean is not None
        and baseline_stddev is not None
        and deviation_threshold_stddev is not None
    )
    if not have_range and not have_distribution:
        return AnomalyDetectionResult(
            observed_value=observed_value,
            status=STATUS_NOT_APPLICABLE,
            reason=(
                "no real caller-supplied baseline/historical range or "
                "distribution was supplied -- a baseline is never fabricated"
            ),
        )

    if have_range:
        if baseline_min > baseline_max:  # type: ignore[operator]
            raise PerformanceClassificationError(
                f"baseline_min ({baseline_min!r}) must not exceed baseline_max ({baseline_max!r})"
            )
        in_range = baseline_min <= observed_value <= baseline_max  # type: ignore[operator]
        return AnomalyDetectionResult(
            observed_value=observed_value,
            status=(NO_ANOMALY if in_range else ANOMALY_DETECTED),
            reason=(
                f"observed value {observed_value!r} "
                + ("within" if in_range else "outside")
                + f" the real caller-supplied baseline range [{baseline_min!r}, {baseline_max!r}]"
            ),
            baseline_description=f"range[{baseline_min!r}, {baseline_max!r}]",
        )

    # have_distribution from here on.
    if baseline_stddev < 0:  # type: ignore[operator]
        raise PerformanceClassificationError(
            f"baseline_stddev must be non-negative, got {baseline_stddev!r}"
        )
    if deviation_threshold_stddev <= 0:  # type: ignore[operator]
        raise PerformanceClassificationError(
            f"deviation_threshold_stddev must be positive, got {deviation_threshold_stddev!r}"
        )
    if baseline_stddev == 0:
        anomalous = observed_value != baseline_mean
        return AnomalyDetectionResult(
            observed_value=observed_value,
            status=(ANOMALY_DETECTED if anomalous else NO_ANOMALY),
            deviation=None,
            reason=(
                "baseline stddev is zero (every historical sample equalled "
                f"the mean {baseline_mean!r}); observed value "
                + ("differs" if anomalous else "matches")
            ),
            baseline_description=f"mean={baseline_mean!r}, stddev=0",
        )
    z_score = abs(observed_value - baseline_mean) / baseline_stddev  # type: ignore[operator]
    anomalous = z_score >= deviation_threshold_stddev  # type: ignore[operator]
    return AnomalyDetectionResult(
        observed_value=observed_value,
        status=(ANOMALY_DETECTED if anomalous else NO_ANOMALY),
        deviation=z_score,
        reason=(
            f"observed deviation {z_score:.4f} standard deviations "
            + ("meets/exceeds" if anomalous else "is below")
            + f" the caller-declared threshold {deviation_threshold_stddev!r}"
        ),
        baseline_description=f"mean={baseline_mean!r}, stddev={baseline_stddev!r}",
    )


# --- 4. regression delta -------------------------------------------------


def compute_regression_delta(
    metric_name: str,
    baseline_value: Optional[float],
    current_value: Optional[float],
    *,
    baseline_window: Optional[str] = None,
    current_window: Optional[str] = None,
    baseline_unit: Optional[str] = None,
    current_unit: Optional[str] = None,
    lower_is_better: bool = True,
    improvement_threshold_percent: Optional[float] = None,
) -> RegressionDeltaResult:
    """Compare two real measured samples/periods for one named metric.

    `INCONCLUSIVE` -- never a fabricated percentage -- whenever the two
    samples are not genuinely comparable: declared units differ, declared
    measurement windows differ, or the baseline is zero (percent-change is
    mathematically undefined). `lower_is_better` must be declared by the
    caller (defaults `True`, the common case for latency/stall-cycle
    metrics) -- for a bandwidth/throughput metric a caller must pass
    `lower_is_better=False`.
    """
    if not metric_name or not metric_name.strip():
        raise PerformanceClassificationError("metric_name must be a non-empty string")
    if baseline_value is None or current_value is None:
        return RegressionDeltaResult(
            metric_name=metric_name,
            baseline_value=baseline_value,
            current_value=current_value,
            percent_change=None,
            verdict=STATUS_UNKNOWN,
            reason="one or both real measured samples were not supplied",
        )
    if baseline_unit is not None and current_unit is not None and baseline_unit != current_unit:
        return RegressionDeltaResult(
            metric_name=metric_name,
            baseline_value=baseline_value,
            current_value=current_value,
            percent_change=None,
            verdict=REGRESSION_INCONCLUSIVE,
            reason=(
                "the two samples declare different units "
                f"({baseline_unit!r} vs {current_unit!r}) -- not genuinely comparable"
            ),
        )
    if (
        baseline_window is not None
        and current_window is not None
        and baseline_window != current_window
    ):
        return RegressionDeltaResult(
            metric_name=metric_name,
            baseline_value=baseline_value,
            current_value=current_value,
            percent_change=None,
            verdict=REGRESSION_INCONCLUSIVE,
            reason=(
                "the two samples declare different measurement windows "
                f"({baseline_window!r} vs {current_window!r}) -- not genuinely comparable"
            ),
        )

    if baseline_value == 0:
        if current_value == 0:
            return RegressionDeltaResult(
                metric_name=metric_name,
                baseline_value=baseline_value,
                current_value=current_value,
                percent_change=0.0,
                verdict=REGRESSION_UNCHANGED,
                reason="both samples are zero",
            )
        return RegressionDeltaResult(
            metric_name=metric_name,
            baseline_value=baseline_value,
            current_value=current_value,
            percent_change=None,
            verdict=REGRESSION_INCONCLUSIVE,
            reason=(
                "baseline value is zero; percent-change is mathematically "
                "undefined -- the two samples are not genuinely comparable "
                "on a percentage basis"
            ),
        )

    percent_change = (current_value - baseline_value) / baseline_value * 100.0
    threshold = improvement_threshold_percent if improvement_threshold_percent is not None else 0.0
    if threshold < 0:
        raise PerformanceClassificationError(
            f"improvement_threshold_percent must be non-negative, got {threshold!r}"
        )
    if abs(percent_change) <= threshold:
        return RegressionDeltaResult(
            metric_name=metric_name,
            baseline_value=baseline_value,
            current_value=current_value,
            percent_change=percent_change,
            verdict=REGRESSION_UNCHANGED,
            reason=(
                f"percent change {percent_change:.4f}% does not exceed the "
                f"declared noise-floor threshold {threshold!r}%"
            ),
        )
    if lower_is_better:
        verdict = REGRESSION_IMPROVED if percent_change < 0 else REGRESSION_REGRESSED
    else:
        verdict = REGRESSION_IMPROVED if percent_change > 0 else REGRESSION_REGRESSED
    return RegressionDeltaResult(
        metric_name=metric_name,
        baseline_value=baseline_value,
        current_value=current_value,
        percent_change=percent_change,
        verdict=verdict,
        reason=(
            f"percent change {percent_change:.4f}% "
            f"({'lower' if lower_is_better else 'higher'}-is-better metric)"
        ),
    )


# --- rule (c): functional correctness always outranks performance --------


def decide_overall_performance_verdict(
    functional_verdict: str,
    regression_delta_verdict: Optional[str] = None,
) -> OverallVerdictResult:
    """Rule (c), reused rather than reimplemented: delegates directly to
    `amba_performance_calculator.decide_overall_verdict()`.

    Maps this module's own `compute_regression_delta()` verdict onto that
    function's `performance_verdict` parameter -- IMPROVED/UNCHANGED become a
    performance PASS, REGRESSED becomes a performance FAIL, and
    INCONCLUSIVE/UNKNOWN/None (nothing was genuinely evaluated) are passed
    through as `None` (no performance verdict). A functionally-FAILed but
    performance-IMPROVED result is still an overall FAIL -- see
    `decide_overall_verdict()`'s own docstring for the precedence rule this
    delegates to.
    """
    mapped: Optional[str]
    if regression_delta_verdict in (REGRESSION_IMPROVED, REGRESSION_UNCHANGED):
        mapped = Status.PASS.value
    elif regression_delta_verdict == REGRESSION_REGRESSED:
        mapped = Status.FAIL.value
    else:
        mapped = None
    return decide_overall_verdict(functional_verdict, mapped)


# --- Jain's fairness index ------------------------------------------------


def compute_jains_fairness_index(
    per_requester_values: Mapping[str, Optional[float]],
) -> FairnessIndexResult:
    """Jain's fairness index: `J = (sum(x_i))**2 / (n * sum(x_i**2))`, a
    real, well-known one-line formula over a real per-requester allocation/
    throughput map (Jain, Chiu & Hawe, 1984).

    Refuses to compute -- reports `UNKNOWN`, never a value silently computed
    over the subset that happened to report -- the moment ANY declared
    requester's value is `None` (absent/incomplete per-requester data).
    Requires at least two requesters (`NOT_APPLICABLE` otherwise: fairness
    across a single requester is not a meaningful question) and non-negative
    values (a negative allocation/throughput is a caller error, refused
    rather than silently included).
    """
    if not per_requester_values:
        return FairnessIndexResult(
            requester_count=0,
            fairness_index=None,
            status=STATUS_UNKNOWN,
            reason="no per-requester values supplied",
        )
    missing = sorted(k for k, v in per_requester_values.items() if v is None)
    if missing:
        return FairnessIndexResult(
            requester_count=len(per_requester_values),
            fairness_index=None,
            status=STATUS_UNKNOWN,
            reason=(
                "incomplete per-requester data -- refusing to compute over "
                f"the partial set; missing values for: {missing}"
            ),
            missing_requesters=tuple(missing),
        )
    values = list(per_requester_values.values())  # type: ignore[arg-type]
    if len(values) < 2:
        return FairnessIndexResult(
            requester_count=len(values),
            fairness_index=None,
            status=STATUS_NOT_APPLICABLE,
            reason="fairness index requires at least two requesters",
        )
    if any(v < 0 for v in values):  # type: ignore[operator]
        raise PerformanceClassificationError(
            "per-requester values must be non-negative"
        )
    n = len(values)
    total = sum(values)  # type: ignore[arg-type]
    sum_of_squares = sum(v * v for v in values)  # type: ignore[operator]
    if sum_of_squares == 0:
        return FairnessIndexResult(
            requester_count=n,
            fairness_index=None,
            status=STATUS_UNKNOWN,
            reason="all per-requester values are zero; fairness index is undefined (0/0)",
        )
    j = (total * total) / (n * sum_of_squares)
    return FairnessIndexResult(
        requester_count=n,
        fairness_index=j,
        status=STATUS_COMPUTED,
    )
