"""dv_harness/amba_performance_calculator.py -- AMBA/AXI-class PERFORMANCE
arithmetic over real, CALLER-SUPPLIED numbers only (2026-09-06).

THIS IS THE HIGHEST FABRICATION-RISK DOMAIN IN THIS PROJECT, AND THE MODULE
IS BUILT AROUND THAT
-----------------------------------------------------------------------------
This harness has no live simulator and no formal tool. Its only real timing
evidence is whatever an already-produced artifact (`fsdb_report.py` output, a
sim.log, or a caller-supplied trace record) already contains. This module
never reads an FSDB/waveform file, never simulates anything, and never
estimates a plausible-looking number when the real input is missing -- every
function here is pure arithmetic/classification over numbers a caller already
extracted from real evidence. Three rules are enforced IN CODE, not left as a
docstring promise:

  (a) a numeric threshold/target is NEVER invented -- it is always
      CALLER-declared (`evaluate_against_target()`'s `target_value`), or the
      result is `NOT_APPLICABLE`. `bandwidth_utilization()` is this rule's
      sharpest instance: it reports `UNKNOWN` whenever no caller-supplied,
      already-proven PEAK bandwidth exists, rather than dividing against an
      assumed or reverse-engineered ceiling.
  (b) an unprovable peak/baseline/metric yields `UNKNOWN`, never a
      computed-looking percentage or number. Every function in this module
      returns a typed result carrying an explicit `status` -- `COMPUTED` /
      `UNKNOWN` / `NOT_APPLICABLE` -- and an empty/missing input never
      silently becomes a zero.
  (c) functional correctness ALWAYS outranks a performance PASS.
      `decide_overall_verdict()` is a hard PRECEDENCE rule, never a weighted
      score: a functional FAIL is the overall verdict regardless of how good
      the performance numbers are, and a performance PASS can never promote a
      functionally-incorrect result to an overall PASS.

REUSE OVER REINVENT
--------------------
This module sits ONE LEVEL ABOVE `fsdb_report.py`'s real FSDB-report parsing
(read only for shape, never imported -- this batch's task is pure arithmetic
over numbers a caller already extracted, never a second FSDB parser). It
imports nothing from `dv_harness` except `models.Status`, used only to name
the two real verification-verdict tokens (`PASS`/`FAIL`) that
`decide_overall_verdict()` accepts as a functional-correctness input --
reusing this project's one real verdict vocabulary rather than minting a
second "pass/fail" spelling. This module's OWN status vocabulary
(`COMPUTED`/`UNKNOWN`/`NOT_APPLICABLE`) is checked disjoint from
`models.Status` at import time, the same discipline several sibling modules
in this project already apply to their own domain vocabularies.

WHAT THIS MODULE DOES NOT DO
-----------------------------
It does not monitor a live signal, parse an FSDB/waveform, generate traffic,
or run a simulation -- all explicitly out of scope for this batch, since this
harness has no live simulator to validate any of that against. It computes
nothing beyond arithmetic/classification over numbers a caller already
supplied, and it decides nothing beyond the one hard precedence rule in (c)
above: no gate, no approval, no build/regression/LSF submission.

DATA SHAPES
-----------
`PerformanceSampleIR` is one real observed transaction/window sample
(counts, byte sizes, start/end timestamps -- all caller-supplied).
`LatencyDefinitionIR` states what "latency" means for a measurement
(issue-to-first-beat / issue-to-last-beat / request-to-response) -- NEVER
assumed, always caller-declared, because different callers mean different
things by "latency" and silently picking one would misrepresent every
percentile computed from it. `PortPerformanceIR`/`PathPerformanceIR` are
per-port/per-path aggregated records built by `aggregate_port_performance()`
over one or more samples. `PerformanceWindowIR` is a time window over which
samples were aggregated. `PerformanceCurveIR` is an ordered series of windows
(e.g. for a future ramp/saturation curve) -- this module only HOLDS that data
shape; it does not generate the ramp itself, and generating one would need a
live simulator this harness does not have.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .models import Status

# --- vocabulary --------------------------------------------------------

#: A value was really computed from real, caller-supplied numbers.
STATUS_COMPUTED = "COMPUTED"
#: The real input needed to compute this metric was missing, empty, or
#: unusable (e.g. a zero/negative duration) -- never silently read as zero.
STATUS_UNKNOWN = "UNKNOWN"
#: The metric genuinely does not apply because no caller-declared
#: threshold/target/definition exists to evaluate against -- distinct from
#: `STATUS_UNKNOWN` (missing observed data) because here the OBSERVATION may
#: be perfectly real; what is missing is the thing to compare it against.
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

_METRIC_STATUSES = (STATUS_COMPUTED, STATUS_UNKNOWN, STATUS_NOT_APPLICABLE)


def _assert_status_vocabulary_disjoint_from_models_status() -> None:
    collision = set(_METRIC_STATUSES) & {member.value for member in Status}
    if collision:
        raise AssertionError(
            "amba_performance_calculator status vocabulary collides with "
            f"dv_harness.models.Status: {sorted(collision)}"
        )


_assert_status_vocabulary_disjoint_from_models_status()

#: What "latency" means for a measurement -- NEVER assumed. A caller must
#: declare one of these; there is deliberately no default.
LATENCY_DEFINITION_ISSUE_TO_FIRST_BEAT = "ISSUE_TO_FIRST_BEAT"
LATENCY_DEFINITION_ISSUE_TO_LAST_BEAT = "ISSUE_TO_LAST_BEAT"
LATENCY_DEFINITION_REQUEST_TO_RESPONSE = "REQUEST_TO_RESPONSE"

LATENCY_DEFINITIONS = (
    LATENCY_DEFINITION_ISSUE_TO_FIRST_BEAT,
    LATENCY_DEFINITION_ISSUE_TO_LAST_BEAT,
    LATENCY_DEFINITION_REQUEST_TO_RESPONSE,
)

DEFAULT_PERCENTILES: Tuple[int, ...] = (50, 90, 95, 99)

_TARGET_COMPARISONS = ("<=", "<", ">=", ">", "==")


class PerformanceCalculatorError(ValueError):
    """A caller-USAGE error -- a malformed argument (an unrecognized latency
    definition, a negative byte count, an unrecognized comparison operator).

    This is distinct from a missing-evidence case, which is never an
    exception: missing/empty real evidence reports `STATUS_UNKNOWN` or
    `STATUS_NOT_APPLICABLE` from the function's return value instead of
    raising, because a caller with an honestly incomplete trace is not making
    a programming error.
    """


# --- caller-declared shape: what does "latency" mean here? -----------------


@dataclass(frozen=True)
class LatencyDefinitionIR:
    """What "latency" means for one measurement. NEVER assumed -- a caller
    must construct one of these naming a real definition before any latency
    percentile is computed, because "issue-to-first-beat" and
    "request-to-response" are different real quantities and conflating them
    would misrepresent whichever one the underlying evidence actually
    measured.
    """

    definition: str
    description: Optional[str] = None

    def __post_init__(self) -> None:
        if self.definition not in LATENCY_DEFINITIONS:
            raise PerformanceCalculatorError(
                f"LatencyDefinitionIR.definition must be one of {LATENCY_DEFINITIONS}, "
                f"got {self.definition!r} -- latency meaning is never assumed, "
                "always caller-declared"
            )


def _resolve_latency_definition(
    latency_definition,
) -> LatencyDefinitionIR:
    """Accepts either a real `LatencyDefinitionIR` or a bare definition
    string (for a caller that has not built the IR object yet) and always
    returns a validated `LatencyDefinitionIR`. Never accepts `None` --
    latency meaning is mandatory, never defaulted.
    """
    if latency_definition is None:
        raise PerformanceCalculatorError(
            "latency_definition is required -- what 'latency' means for this "
            "measurement is never assumed, always caller-declared (pass a "
            "LatencyDefinitionIR or one of "
            f"{LATENCY_DEFINITIONS})"
        )
    if isinstance(latency_definition, LatencyDefinitionIR):
        return latency_definition
    if isinstance(latency_definition, str):
        return LatencyDefinitionIR(definition=latency_definition)
    raise PerformanceCalculatorError(
        "latency_definition must be a LatencyDefinitionIR or a string naming "
        f"one of {LATENCY_DEFINITIONS}, got {type(latency_definition)!r}"
    )


# --- one real observed sample ----------------------------------------------


@dataclass
class PerformanceSampleIR:
    """One real observed transaction/window sample. Every field is a real,
    caller-supplied number pulled from an already-produced artifact
    (fsdb_report.py output, a sim.log, or a caller-supplied trace record) --
    this module never derives one of these itself.
    """

    sample_id: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    byte_count: Optional[float] = None
    transaction_count: Optional[int] = None
    latency: Optional[float] = None
    latency_definition: Optional[str] = None
    outstanding_count: Optional[int] = None
    busy_cycles: Optional[float] = None
    stalled_cycles: Optional[float] = None
    total_cycles: Optional[float] = None
    source_evidence: Optional[str] = None

    def duration_seconds(self) -> Optional[float]:
        """The real observed duration of this sample, or `None` when either
        timestamp is missing or the window is malformed (end before start) --
        never a guessed/clamped value.
        """
        if self.start_time is None or self.end_time is None:
            return None
        if self.end_time < self.start_time:
            return None
        return self.end_time - self.start_time


# --- typed results: every metric carries an explicit status ---------------


@dataclass(frozen=True)
class MetricResult:
    """One scalar metric, always carrying an explicit status. `value` is
    `None` whenever `status` is not `STATUS_COMPUTED` -- a missing/unusable
    input is never silently reported as zero.
    """

    value: Optional[float]
    status: str
    reason: Optional[str] = None
    unit: Optional[str] = None


@dataclass(frozen=True)
class LatencyPercentileReport:
    """p50/p90/p95/p99 (or a caller-declared percentile set) over a real
    list of observed latencies, tied to a real, caller-declared
    `LatencyDefinitionIR`.
    """

    latency_definition: str
    sample_count: int
    percentiles: Dict[str, Optional[float]]
    status: str
    reason: Optional[str] = None


@dataclass(frozen=True)
class OutstandingStatsResult:
    """Average/peak over a real list of observed outstanding-transaction
    counts.
    """

    sample_count: int
    average: Optional[float]
    peak: Optional[int]
    status: str
    reason: Optional[str] = None


@dataclass(frozen=True)
class TargetEvaluationResult:
    """Rule (a) as code: a threshold/target comparison that reports
    `STATUS_NOT_APPLICABLE`, never a fabricated pass/fail, whenever no
    caller-declared `target_value` exists.
    """

    observed_value: Optional[float]
    target_value: Optional[float]
    comparison: str
    meets_target: Optional[bool]
    status: str
    reason: Optional[str] = None


@dataclass(frozen=True)
class OverallVerdictResult:
    """Rule (c) as code: functional correctness always outranks a
    performance PASS. See `decide_overall_verdict()`.
    """

    verdict: str
    functional_verdict: str
    performance_verdict: Optional[str]
    reason: str


# --- per-port / per-path aggregates and window/curve shapes ---------------


@dataclass
class PortPerformanceIR:
    """One AMBA port's aggregated performance, built by
    `aggregate_port_performance()` over one or more real
    `PerformanceSampleIR` records. Every field is a `MetricResult`/report
    carrying its own status -- there is no single collapsed "score".
    """

    port_id: str
    window_start: Optional[float] = None
    window_end: Optional[float] = None
    sample_count: int = 0
    bandwidth: Optional[MetricResult] = None
    throughput: Optional[MetricResult] = None
    latency_report: Optional[LatencyPercentileReport] = None
    outstanding: Optional[OutstandingStatsResult] = None
    stall_ratio: Optional[MetricResult] = None
    utilization: Optional[MetricResult] = None
    bandwidth_utilization: Optional[MetricResult] = None
    source_evidence: List[str] = field(default_factory=list)


@dataclass
class PathPerformanceIR:
    """A source-port -> dest-port PATH's aggregated performance -- the same
    metric shapes as `PortPerformanceIR`, scoped to one traced path rather
    than one port.
    """

    path_id: str
    source_port: str
    dest_port: str
    sample_count: int = 0
    bandwidth: Optional[MetricResult] = None
    throughput: Optional[MetricResult] = None
    latency_report: Optional[LatencyPercentileReport] = None
    source_evidence: List[str] = field(default_factory=list)


@dataclass
class PerformanceWindowIR:
    """A time window over which samples were aggregated. This is a data
    shape only -- it holds the real samples a caller assigned to this
    window; it does not decide window boundaries itself.
    """

    window_id: str
    start_time: float
    end_time: float
    samples: List[PerformanceSampleIR] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.end_time < self.start_time:
            raise PerformanceCalculatorError(
                f"PerformanceWindowIR {self.window_id!r}: end_time "
                f"({self.end_time}) is before start_time ({self.start_time})"
            )


@dataclass
class PerformanceCurveIR:
    """An ORDERED series of windows -- e.g. for a future ramp/saturation
    curve. This module only HOLDS the data shape; it does NOT generate the
    ramp itself (that would need a live traffic generator, explicitly out of
    scope for this batch).
    """

    curve_id: str
    windows: List[PerformanceWindowIR] = field(default_factory=list)
    description: Optional[str] = None


# --- pure functions: bandwidth / throughput --------------------------------


def compute_bandwidth(
    total_bytes: Optional[float], duration_seconds: Optional[float]
) -> MetricResult:
    """bytes/time, over real caller-supplied numbers only."""
    if total_bytes is None:
        return MetricResult(
            None, STATUS_UNKNOWN, reason="no total_bytes supplied", unit="bytes_per_second"
        )
    if duration_seconds is None:
        return MetricResult(
            None,
            STATUS_UNKNOWN,
            reason="no duration_seconds supplied",
            unit="bytes_per_second",
        )
    if duration_seconds <= 0:
        return MetricResult(
            None,
            STATUS_UNKNOWN,
            reason=f"duration_seconds must be > 0 to compute bandwidth, got {duration_seconds}",
            unit="bytes_per_second",
        )
    if total_bytes < 0:
        raise PerformanceCalculatorError(f"total_bytes must be >= 0, got {total_bytes}")
    return MetricResult(
        total_bytes / duration_seconds, STATUS_COMPUTED, unit="bytes_per_second"
    )


def compute_throughput(
    transaction_count: Optional[float], duration_seconds: Optional[float]
) -> MetricResult:
    """transactions/time, over real caller-supplied numbers only."""
    if transaction_count is None:
        return MetricResult(
            None,
            STATUS_UNKNOWN,
            reason="no transaction_count supplied",
            unit="transactions_per_second",
        )
    if duration_seconds is None:
        return MetricResult(
            None,
            STATUS_UNKNOWN,
            reason="no duration_seconds supplied",
            unit="transactions_per_second",
        )
    if duration_seconds <= 0:
        return MetricResult(
            None,
            STATUS_UNKNOWN,
            reason=f"duration_seconds must be > 0 to compute throughput, got {duration_seconds}",
            unit="transactions_per_second",
        )
    if transaction_count < 0:
        raise PerformanceCalculatorError(
            f"transaction_count must be >= 0, got {transaction_count}"
        )
    return MetricResult(
        transaction_count / duration_seconds,
        STATUS_COMPUTED,
        unit="transactions_per_second",
    )


# --- pure functions: latency percentiles -----------------------------------


def _percentile(sorted_values: Sequence[float], percentile: float) -> float:
    """Linear-interpolation percentile over an already-sorted sequence (the
    same method `numpy.percentile`'s default uses) -- no third-party
    dependency needed for this one small piece of arithmetic.
    """
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    rank = (percentile / 100.0) * (n - 1)
    low = int(rank)
    high = min(low + 1, n - 1)
    frac = rank - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac


def compute_latency_percentiles(
    latencies: Optional[Sequence[float]],
    latency_definition,
    percentiles: Sequence[int] = DEFAULT_PERCENTILES,
) -> LatencyPercentileReport:
    """p50/p90/p95/p99 (or a caller-declared percentile set) from a real
    list of observed latencies. `latency_definition` is MANDATORY -- a
    `LatencyDefinitionIR` or a bare definition string -- because a
    percentile computed with no declared meaning could be silently
    misread as whichever one the reader assumes.

    An empty/missing `latencies` list reports `STATUS_UNKNOWN` with every
    percentile `None`, never a fabricated zero and never a crash.
    """
    resolved_definition = _resolve_latency_definition(latency_definition)
    if not percentiles:
        raise PerformanceCalculatorError("percentiles must be a non-empty sequence")
    percentile_keys = [f"p{p}" for p in percentiles]
    if latencies is None or len(latencies) == 0:
        return LatencyPercentileReport(
            latency_definition=resolved_definition.definition,
            sample_count=0,
            percentiles={key: None for key in percentile_keys},
            status=STATUS_UNKNOWN,
            reason="no observed latency samples supplied",
        )
    for value in latencies:
        if value is None:
            raise PerformanceCalculatorError(
                "latencies must not contain None -- omit an unobserved sample "
                "rather than passing a placeholder"
            )
        if value < 0:
            raise PerformanceCalculatorError(f"a latency value must be >= 0, got {value}")
    sorted_latencies = sorted(latencies)
    computed = {
        f"p{p}": _percentile(sorted_latencies, p) for p in percentiles
    }
    return LatencyPercentileReport(
        latency_definition=resolved_definition.definition,
        sample_count=len(latencies),
        percentiles=computed,
        status=STATUS_COMPUTED,
    )


# --- pure functions: outstanding-count average/peak ------------------------


def compute_outstanding_stats(
    outstanding_counts: Optional[Sequence[int]],
) -> OutstandingStatsResult:
    """Average and peak over a real list of observed outstanding-transaction
    counts. An empty/missing list reports `STATUS_UNKNOWN`, never a
    fabricated zero.
    """
    if outstanding_counts is None or len(outstanding_counts) == 0:
        return OutstandingStatsResult(
            sample_count=0,
            average=None,
            peak=None,
            status=STATUS_UNKNOWN,
            reason="no observed outstanding-count samples supplied",
        )
    for value in outstanding_counts:
        if value is None:
            raise PerformanceCalculatorError(
                "outstanding_counts must not contain None -- omit an unobserved "
                "sample rather than passing a placeholder"
            )
        if value < 0:
            raise PerformanceCalculatorError(
                f"an outstanding-count value must be >= 0, got {value}"
            )
    return OutstandingStatsResult(
        sample_count=len(outstanding_counts),
        average=sum(outstanding_counts) / len(outstanding_counts),
        peak=max(outstanding_counts),
        status=STATUS_COMPUTED,
    )


# --- pure functions: stall/backpressure ratio and utilization --------------


def _ratio_metric(
    numerator: Optional[float],
    denominator: Optional[float],
    *,
    numerator_name: str,
    denominator_name: str,
    over_range_reason: str,
) -> MetricResult:
    if numerator is None:
        return MetricResult(
            None, STATUS_UNKNOWN, reason=f"no {numerator_name} supplied", unit="ratio"
        )
    if denominator is None:
        return MetricResult(
            None, STATUS_UNKNOWN, reason=f"no {denominator_name} supplied", unit="ratio"
        )
    if denominator <= 0:
        return MetricResult(
            None,
            STATUS_UNKNOWN,
            reason=f"{denominator_name} must be > 0, got {denominator}",
            unit="ratio",
        )
    if numerator < 0:
        raise PerformanceCalculatorError(f"{numerator_name} must be >= 0, got {numerator}")
    ratio = numerator / denominator
    reason = over_range_reason if ratio > 1 else None
    return MetricResult(ratio, STATUS_COMPUTED, reason=reason, unit="ratio")


def compute_stall_ratio(
    stalled_cycles: Optional[float], total_cycles: Optional[float]
) -> MetricResult:
    """stalled cycles / total cycles, both caller-supplied. A ratio above 1
    is still reported (never clamped or hidden) with a data-quality
    `reason`, since that is real evidence something upstream double-counted
    or mis-measured -- discarding it would hide a defect the caller should
    see.
    """
    return _ratio_metric(
        stalled_cycles,
        total_cycles,
        numerator_name="stalled_cycles",
        denominator_name="total_cycles",
        over_range_reason=(
            "stalled_cycles exceeds total_cycles -- data-quality warning, "
            "value reported as observed"
        ),
    )


def compute_utilization(
    busy_cycles: Optional[float], total_cycles: Optional[float]
) -> MetricResult:
    """busy cycles / total cycles, both caller-supplied."""
    return _ratio_metric(
        busy_cycles,
        total_cycles,
        numerator_name="busy_cycles",
        denominator_name="total_cycles",
        over_range_reason=(
            "busy_cycles exceeds total_cycles -- data-quality warning, "
            "value reported as observed"
        ),
    )


# --- bandwidth utilization: the sharpest instance of rule (a)/(b) ----------


def bandwidth_utilization(
    observed_bandwidth_bytes_per_second: Optional[float],
    peak_bandwidth_bytes_per_second: Optional[float],
) -> MetricResult:
    """observed / peak bandwidth, as a percentage. MUST report `UNKNOWN`
    whenever no caller-supplied, already-proven peak bandwidth value is
    supplied -- this function never computes a percentage against an
    invented or assumed peak, and never silently substitutes the observed
    value's own maximum as a stand-in peak.
    """
    if peak_bandwidth_bytes_per_second is None:
        return MetricResult(
            None,
            STATUS_UNKNOWN,
            reason=(
                "no caller-supplied peak bandwidth was provided -- utilization "
                "is never computed against an invented or assumed peak"
            ),
            unit="percent",
        )
    if peak_bandwidth_bytes_per_second <= 0:
        return MetricResult(
            None,
            STATUS_UNKNOWN,
            reason=(
                "peak_bandwidth_bytes_per_second must be > 0, got "
                f"{peak_bandwidth_bytes_per_second}"
            ),
            unit="percent",
        )
    if observed_bandwidth_bytes_per_second is None:
        return MetricResult(
            None,
            STATUS_UNKNOWN,
            reason="no observed bandwidth was supplied",
            unit="percent",
        )
    if observed_bandwidth_bytes_per_second < 0:
        raise PerformanceCalculatorError(
            "observed_bandwidth_bytes_per_second must be >= 0, got "
            f"{observed_bandwidth_bytes_per_second}"
        )
    value = 100.0 * observed_bandwidth_bytes_per_second / peak_bandwidth_bytes_per_second
    return MetricResult(value, STATUS_COMPUTED, unit="percent")


# --- rule (a) as a reusable, generic check ---------------------------------


def evaluate_against_target(
    observed_value: Optional[float],
    target_value: Optional[float] = None,
    comparison: str = "<=",
) -> TargetEvaluationResult:
    """Rule (a) enforced generically: a threshold/target comparison that is
    `NOT_APPLICABLE`, never a fabricated pass/fail, whenever the caller has
    not declared a real `target_value`. Usable against any metric this
    module computes (a bandwidth, a latency percentile, a utilization) once
    a caller has a real declared target for it.
    """
    if comparison not in _TARGET_COMPARISONS:
        raise PerformanceCalculatorError(
            f"comparison must be one of {_TARGET_COMPARISONS}, got {comparison!r}"
        )
    if observed_value is None:
        return TargetEvaluationResult(
            None,
            target_value,
            comparison,
            None,
            STATUS_UNKNOWN,
            reason="no observed value supplied",
        )
    if target_value is None:
        return TargetEvaluationResult(
            observed_value,
            None,
            comparison,
            None,
            STATUS_NOT_APPLICABLE,
            reason=(
                "no caller-declared target/threshold supplied -- a threshold "
                "is never invented"
            ),
        )
    comparators = {
        "<=": lambda a, b: a <= b,
        "<": lambda a, b: a < b,
        ">=": lambda a, b: a >= b,
        ">": lambda a, b: a > b,
        "==": lambda a, b: a == b,
    }
    meets = comparators[comparison](observed_value, target_value)
    return TargetEvaluationResult(
        observed_value, target_value, comparison, meets, STATUS_COMPUTED
    )


# --- rule (c): functional correctness always outranks performance ---------


def decide_overall_verdict(
    functional_verdict: str,
    performance_verdict: Optional[str] = None,
) -> OverallVerdictResult:
    """Rule (c) as a hard PRECEDENCE, never a weighted score.

    `functional_verdict` must be one of `models.Status.PASS`/`FAIL` -- this
    is where a real scoreboard/checker/protocol-compliance result belongs,
    reused verbatim from the one real verdict vocabulary this project
    already has (see `protocol_compliance_aggregation.py`'s own precedent for
    the same reasoning: a real checker FAIL overrides everything).

    A high-performance but functionally-incorrect transaction is still an
    OVERALL FAIL: a functional FAIL is returned as-is regardless of what
    `performance_verdict` says, including a performance PASS. A functional
    verdict that is neither a real PASS nor a real FAIL (unrecognized,
    absent, still pending) can never be silently treated as a pass, so the
    overall result is `UNKNOWN` rather than an assumed PASS.
    """
    if functional_verdict not in (Status.PASS.value, Status.FAIL.value):
        return OverallVerdictResult(
            verdict=STATUS_UNKNOWN,
            functional_verdict=functional_verdict,
            performance_verdict=performance_verdict,
            reason=(
                "functional_verdict is not a confirmed PASS/FAIL "
                f"(got {functional_verdict!r}); the overall result cannot be "
                "determined without real functional-correctness evidence"
            ),
        )
    if functional_verdict == Status.FAIL.value:
        return OverallVerdictResult(
            verdict=Status.FAIL.value,
            functional_verdict=functional_verdict,
            performance_verdict=performance_verdict,
            reason=(
                "functional correctness FAILed; this always outranks any "
                "performance result, including a performance PASS -- a "
                "high-performance but functionally incorrect transaction is "
                "still an overall FAIL"
            ),
        )
    # functional_verdict == Status.PASS.value from here on.
    if performance_verdict in (None, STATUS_NOT_APPLICABLE, STATUS_UNKNOWN):
        return OverallVerdictResult(
            verdict=Status.PASS.value,
            functional_verdict=functional_verdict,
            performance_verdict=performance_verdict,
            reason=(
                "functional correctness PASSed; no performance verdict was "
                "evaluated against a declared target"
            ),
        )
    if performance_verdict == Status.PASS.value:
        return OverallVerdictResult(
            verdict=Status.PASS.value,
            functional_verdict=functional_verdict,
            performance_verdict=performance_verdict,
            reason="functional correctness and the declared performance target both PASSed",
        )
    if performance_verdict == Status.FAIL.value:
        return OverallVerdictResult(
            verdict=Status.FAIL.value,
            functional_verdict=functional_verdict,
            performance_verdict=performance_verdict,
            reason=(
                "functional correctness PASSed but a declared performance "
                "target FAILed"
            ),
        )
    return OverallVerdictResult(
        verdict=STATUS_UNKNOWN,
        functional_verdict=functional_verdict,
        performance_verdict=performance_verdict,
        reason=f"performance_verdict is not a recognized value (got {performance_verdict!r})",
    )


# --- assembly: a real PortPerformanceIR over real samples ------------------


def aggregate_port_performance(
    port_id: str,
    samples: Sequence[PerformanceSampleIR],
    *,
    latency_definition=None,
    peak_bandwidth_bytes_per_second: Optional[float] = None,
    window_start: Optional[float] = None,
    window_end: Optional[float] = None,
) -> PortPerformanceIR:
    """Builds one `PortPerformanceIR` over real `PerformanceSampleIR`
    records, calling only the pure functions above -- nothing here computes
    a metric a different way than a caller could reproduce by calling those
    functions directly.

    An empty `samples` sequence still returns a real `PortPerformanceIR`,
    with every metric honestly `STATUS_UNKNOWN` (never a crash, never a
    fabricated zero).
    """
    if samples is None:
        samples = []

    total_bytes = None
    byte_counts = [s.byte_count for s in samples if s.byte_count is not None]
    if byte_counts:
        total_bytes = sum(byte_counts)

    total_transactions = None
    transaction_counts = [
        s.transaction_count for s in samples if s.transaction_count is not None
    ]
    if transaction_counts:
        total_transactions = sum(transaction_counts)

    duration_seconds: Optional[float] = None
    if window_start is not None and window_end is not None:
        if window_end >= window_start:
            duration_seconds = window_end - window_start
    else:
        starts = [s.start_time for s in samples if s.start_time is not None]
        ends = [s.end_time for s in samples if s.end_time is not None]
        if starts and ends:
            earliest, latest = min(starts), max(ends)
            if latest >= earliest:
                duration_seconds = latest - earliest

    bandwidth = compute_bandwidth(total_bytes, duration_seconds)
    throughput = compute_throughput(total_transactions, duration_seconds)

    if latency_definition is None:
        latency_report = LatencyPercentileReport(
            latency_definition="UNDECLARED",
            sample_count=0,
            percentiles={},
            status=STATUS_NOT_APPLICABLE,
            reason=(
                "no latency_definition was declared by the caller -- latency "
                "meaning is never assumed"
            ),
        )
    else:
        latencies = [s.latency for s in samples if s.latency is not None]
        latency_report = compute_latency_percentiles(latencies, latency_definition)

    outstanding_counts = [
        s.outstanding_count for s in samples if s.outstanding_count is not None
    ]
    outstanding = compute_outstanding_stats(outstanding_counts)

    stalled_values = [s.stalled_cycles for s in samples if s.stalled_cycles is not None]
    total_cycle_values = [s.total_cycles for s in samples if s.total_cycles is not None]
    stall_ratio = compute_stall_ratio(
        sum(stalled_values) if stalled_values else None,
        sum(total_cycle_values) if total_cycle_values else None,
    )

    busy_values = [s.busy_cycles for s in samples if s.busy_cycles is not None]
    utilization = compute_utilization(
        sum(busy_values) if busy_values else None,
        sum(total_cycle_values) if total_cycle_values else None,
    )

    bw_util = bandwidth_utilization(bandwidth.value, peak_bandwidth_bytes_per_second)

    source_evidence = [s.source_evidence for s in samples if s.source_evidence]

    return PortPerformanceIR(
        port_id=port_id,
        window_start=window_start,
        window_end=window_end,
        sample_count=len(samples),
        bandwidth=bandwidth,
        throughput=throughput,
        latency_report=latency_report,
        outstanding=outstanding,
        stall_ratio=stall_ratio,
        utilization=utilization,
        bandwidth_utilization=bw_util,
        source_evidence=source_evidence,
    )
