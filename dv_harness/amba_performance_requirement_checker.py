"""dv_harness/amba_performance_requirement_checker.py -- AMBA/AXI-class PERFORMANCE
REQUIREMENT CHECKING over real, CALLER-SUPPLIED numbers only (2026-09-06).

THIS SITS ONE LEVEL ABOVE `amba_performance_calculator.py`
-----------------------------------------------------------------------------
`amba_performance_calculator.py` (built and tested earlier in this same batch) computes
performance METRICS (bandwidth, throughput, latency percentiles, utilization, ...) from
real caller-supplied samples, and already has one generic threshold-comparison primitive,
`evaluate_against_target()`. This module is the thin REQUIREMENT layer on top of it: it
gives a threshold a real, typed shape -- `PerformanceRequirementIR` -- and a checker that
compares a real MEASURED value (a `PortPerformanceIR`/`PathPerformanceIR`-shaped record, a
`MetricResult`, a plain dict, or a bare number) against that declared requirement, reporting
PASS / FAIL / NOT_APPLICABLE / UNKNOWN. It reuses `evaluate_against_target()` for the actual
comparison arithmetic rather than re-implementing it -- there is exactly one place in this
package that decides "does this number clear this threshold".

The same three rules the calculator enforces in code are enforced here too, at the
requirement layer:

  (a) a numeric threshold/target is NEVER invented -- `PerformanceRequirementIR.target_value`,
      `.comparison` and `.unit` are ALL mandatory, caller/spec-declared fields;
      `PerformanceRequirementIR.__post_init__` refuses to construct an instance missing any
      of them. The case where NO requirement was declared for a metric at all is modeled by
      passing `requirement=None` to `check_against_requirement()`, which reports
      `NOT_APPLICABLE` -- a legitimate, common case, never treated as a failure.
  (b) an unprovable measured value yields `UNKNOWN`, never a computed-looking PASS/FAIL.
      `_resolve_measured_value()` never silently reads a missing/non-COMPUTED
      `MetricResult` as zero, and `evaluate_against_target()`'s own `STATUS_UNKNOWN`
      path is what actually decides "no observed value supplied".
  (c) functional correctness ALWAYS outranks a performance PASS. `check_against_requirement()`
      accepts an optional `functional_verdict` (one of `models.Status.PASS`/`FAIL`, or
      `None` when the caller is not asking this call to consider functional correctness at
      all); a real `FAIL` overrides the performance comparison's own verdict UNCONDITIONALLY
      -- including when that verdict is `NOT_APPLICABLE` or `UNKNOWN` -- because a
      functionally-incorrect transaction is still an overall FAIL no matter how good, absent,
      or unmeasured its performance numbers are. This is a hard PRECEDENCE check in code,
      never a weighted score.

REUSE OVER REINVENT
--------------------
This module imports `amba_performance_calculator`'s own `STATUS_COMPUTED`/`STATUS_UNKNOWN`/
`STATUS_NOT_APPLICABLE` tokens and its `evaluate_against_target()` function rather than
re-typing a second comparison arithmetic. It imports `models.Status` for the same reason the
calculator module does: PASS/FAIL is this project's one real verification-verdict vocabulary,
reused verbatim rather than a second spelling of "pass/fail". This module's own ADDITIONAL
status token beyond PASS/FAIL/NOT_APPLICABLE/UNKNOWN is none -- its whole vocabulary is
already the calculator's plus `models.Status`'s, so there is nothing new here to check
disjoint at import time.

WHAT THIS MODULE DOES NOT DO
-----------------------------
It never reads an FSDB/waveform file, never simulates anything, never parses a sim.log, and
never invents a threshold, unit, or comparison operator a caller/spec did not declare. It
performs no gate, no approval, and no build/regression/LSF action -- it is pure
arithmetic/classification over numbers a caller already extracted (directly, or via the
calculator module).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from .models import Status
from .amba_performance_calculator import (
    STATUS_COMPUTED,
    STATUS_NOT_APPLICABLE,
    STATUS_UNKNOWN,
    evaluate_against_target,
)

_TARGET_COMPARISONS = ("<=", "<", ">=", ">", "==")

#: functional_verdict must be one of these, or None (meaning "this call is not asked to
#: consider functional correctness at all"). Any other value is a caller-usage error.
_FUNCTIONAL_VERDICTS = (Status.PASS.value, Status.FAIL.value)


class PerformanceRequirementCheckerError(ValueError):
    """A caller-USAGE error -- a malformed `PerformanceRequirementIR` (missing target/unit/
    comparison), an unrecognized comparison operator, an unrecognized `functional_verdict`,
    or a measured value this module has no honest way to read a number out of.

    Distinct from a missing-evidence case, which is never an exception: missing/unusable
    real measured evidence reports `models.Status` is NOT reused for this -- it reports
    `STATUS_UNKNOWN`/`STATUS_NOT_APPLICABLE` from the function's return value instead of
    raising, because a caller with an honestly incomplete measurement is not making a
    programming error.
    """


# --- the requirement: ALWAYS caller/spec-declared, NEVER invented ---------------------


@dataclass(frozen=True)
class PerformanceRequirementIR:
    """One caller/spec-declared performance requirement: a target value, a comparison
    operator, and a unit. All three are MANDATORY -- this module never invents or defaults
    any of them. `source` is an optional free-text citation (e.g. a spec section) for a
    human reviewing why this threshold exists; it carries no semantic weight here.

    The case where NO requirement exists for a given metric is modeled by never
    constructing one -- pass `requirement=None` to `check_against_requirement()` instead of
    trying to build a placeholder `PerformanceRequirementIR` with a missing field.
    """

    requirement_id: str
    metric_name: str
    target_value: float
    comparison: str
    unit: str
    source: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.requirement_id:
            raise PerformanceRequirementCheckerError(
                "PerformanceRequirementIR.requirement_id is required"
            )
        if not self.metric_name:
            raise PerformanceRequirementCheckerError(
                "PerformanceRequirementIR.metric_name is required"
            )
        if self.target_value is None:
            raise PerformanceRequirementCheckerError(
                "PerformanceRequirementIR.target_value is required -- a performance "
                "threshold is NEVER invented or defaulted by this module, only ever "
                "declared by the caller/spec. Pass requirement=None to the checker "
                "instead, which reports NOT_APPLICABLE."
            )
        if isinstance(self.target_value, bool) or not isinstance(
            self.target_value, (int, float)
        ):
            raise PerformanceRequirementCheckerError(
                f"PerformanceRequirementIR.target_value must be a real number, got "
                f"{self.target_value!r}"
            )
        if self.comparison not in _TARGET_COMPARISONS:
            raise PerformanceRequirementCheckerError(
                f"PerformanceRequirementIR.comparison must be one of "
                f"{_TARGET_COMPARISONS}, got {self.comparison!r}"
            )
        if not self.unit:
            raise PerformanceRequirementCheckerError(
                "PerformanceRequirementIR.unit is required -- always caller/spec-declared, "
                "never invented by this module"
            )


# --- the result: every check carries an explicit, layered status ----------------------


@dataclass(frozen=True)
class PerformanceRequirementCheckResult:
    """The outcome of comparing one real measured value against one declared requirement,
    with the functional-correctness precedence rule already applied.

    `performance_status` is the comparison's OWN verdict (PASS/FAIL/NOT_APPLICABLE/UNKNOWN),
    computed with zero knowledge of `functional_verdict`. `status` is the OVERALL verdict
    after rule (c)'s hard precedence is applied -- it equals `performance_status` unless
    `functional_verdict` is a real FAIL, in which case `status` is always FAIL regardless of
    what `performance_status` says. Reporting both, rather than only the overall `status`,
    means a reader can always see whether an overall FAIL came from the performance
    comparison itself or from the functional-correctness override.
    """

    requirement_id: Optional[str]
    metric_name: str
    measured_value: Optional[float]
    target_value: Optional[float]
    comparison: Optional[str]
    unit: Optional[str]
    performance_status: str
    status: str
    functional_verdict: Optional[str]
    reason: Optional[str] = None


# --- resolving a real number out of whatever shape the caller supplied -----------------


def _is_metric_result_like(obj: Any) -> bool:
    """True for anything duck-typed like `amba_performance_calculator.MetricResult` --
    carries both a `status` and a `value` attribute. Not restricted to that exact class:
    any object with this shape (including a future sibling module's own result type) is
    accepted.
    """
    return hasattr(obj, "status") and hasattr(obj, "value")


def _extract_from_metric_result(obj: Any) -> Tuple[Optional[float], Optional[str]]:
    """Reads a MetricResult-shaped object honestly: only a real `STATUS_COMPUTED` status
    yields a number. Anything else (STATUS_UNKNOWN, STATUS_NOT_APPLICABLE, or an unrecognized
    status) yields `None` plus that object's own `reason`, never a silently-read-as-zero
    value and never a fabricated computed-looking number.
    """
    status = getattr(obj, "status", None)
    if status == STATUS_COMPUTED:
        value = getattr(obj, "value", None)
        if value is None:
            return None, (
                "measured value's own status is COMPUTED but its value is None -- "
                "treated as UNKNOWN rather than trusted"
            )
        if isinstance(value, bool):
            raise PerformanceRequirementCheckerError(
                "a MetricResult-shaped measured value's .value must not be a bool"
            )
        return float(value), None
    reason = getattr(obj, "reason", None)
    return None, reason or (
        f"measured value's own status is {status!r}, not COMPUTED -- treated as UNKNOWN"
    )


def _resolve_measured_value(
    measured: Any, metric_name: str
) -> Tuple[Optional[float], Optional[str]]:
    """Extracts a real number for `metric_name` out of `measured`, which may be:

      - `None` -- no measured value at all;
      - a bare `int`/`float` -- the number itself, already resolved by the caller;
      - a MetricResult-shaped object (has `.status`/`.value`) -- honored via
        `_extract_from_metric_result()`, never read as a number unless its own status says
        COMPUTED;
      - a dict or any object exposing a `metric_name` field (e.g. a real
        `PortPerformanceIR`/`PathPerformanceIR` and `metric_name="bandwidth"`) -- that
        field is then resolved by the same three rules, one level deep.

    Never estimates or interpolates a value the input does not actually contain. Returns
    `(value_or_None, reason_or_None)` -- `reason` is populated only when `value` is `None`.
    """
    if measured is None:
        return None, "no measured value supplied"
    if isinstance(measured, bool):
        raise PerformanceRequirementCheckerError(
            "measured value must not be a bare bool"
        )
    if isinstance(measured, (int, float)):
        return float(measured), None
    if _is_metric_result_like(measured):
        return _extract_from_metric_result(measured)

    # `measured` is a container: look up the named field on it.
    if isinstance(measured, Mapping):
        if metric_name not in measured:
            return None, f"measured value has no {metric_name!r} field"
        field_value = measured[metric_name]
    elif hasattr(measured, metric_name):
        field_value = getattr(measured, metric_name)
    else:
        raise PerformanceRequirementCheckerError(
            f"measured value of type {type(measured)!r} does not expose a "
            f"{metric_name!r} field and is not itself a number or a MetricResult-shaped "
            "value -- pass a PortPerformanceIR/PathPerformanceIR-shaped record, a dict "
            "carrying this field, a MetricResult, or a bare number"
        )

    if field_value is None:
        return None, f"no measured value recorded for {metric_name!r}"
    if isinstance(field_value, bool):
        raise PerformanceRequirementCheckerError(
            f"measured value's {metric_name!r} field must not be a bare bool"
        )
    if isinstance(field_value, (int, float)):
        return float(field_value), None
    if _is_metric_result_like(field_value):
        return _extract_from_metric_result(field_value)
    raise PerformanceRequirementCheckerError(
        f"measured value's {metric_name!r} field is neither numeric nor "
        f"MetricResult-shaped (got {type(field_value)!r})"
    )


# --- the checker: rule (a)+(b)+(c) enforced together -----------------------------------


def check_against_requirement(
    measured: Any,
    metric_name: str,
    requirement: Optional[PerformanceRequirementIR] = None,
    functional_verdict: Optional[str] = None,
) -> PerformanceRequirementCheckResult:
    """Compares a real measured value against a declared `PerformanceRequirementIR`,
    reporting PASS / FAIL / NOT_APPLICABLE / UNKNOWN, with functional correctness's hard
    precedence over a performance PASS already applied.

    `measured` may be a bare number, a MetricResult-shaped object, a dict, or any
    `PortPerformanceIR`/`PathPerformanceIR`-shaped object exposing `metric_name` --
    `_resolve_measured_value()` decides which. `requirement=None` means "no requirement is
    declared for this metric" and reports `NOT_APPLICABLE` -- a legitimate, common case,
    never treated as a failure. `functional_verdict` is optional; when it IS a real
    `models.Status.FAIL`, the overall `status` is FAIL unconditionally, regardless of what
    the performance comparison found (including NOT_APPLICABLE/UNKNOWN) -- a
    high-performance but functionally-incorrect transaction is still an overall FAIL. When
    `functional_verdict` is `None` (not supplied for this call) or a real
    `models.Status.PASS`, the overall `status` equals the performance comparison's own
    verdict unchanged: a functional PASS never elevates an unmeasured or failing
    performance result into an overall PASS.
    """
    if functional_verdict is not None and functional_verdict not in _FUNCTIONAL_VERDICTS:
        raise PerformanceRequirementCheckerError(
            f"functional_verdict must be one of {_FUNCTIONAL_VERDICTS} or None, got "
            f"{functional_verdict!r}"
        )

    measured_value, measured_reason = _resolve_measured_value(measured, metric_name)

    requirement_id = requirement.requirement_id if requirement is not None else None

    if requirement is None:
        # No requirement was declared for this metric at all -- NOT_APPLICABLE regardless
        # of whether a measured value exists, because the fact that makes this
        # NOT_APPLICABLE is about the requirement, not about the measurement. This is
        # checked BEFORE consulting the measured value on purpose: `evaluate_against_target()`
        # itself would report STATUS_UNKNOWN first when the measured value is also absent,
        # which would misrepresent "nobody declared a threshold" as "we tried to measure
        # something and failed".
        performance_status = STATUS_NOT_APPLICABLE
        reason: Optional[str] = (
            "no caller-declared target/threshold supplied for this metric -- a threshold "
            "is never invented"
        )
        target_value: Optional[float] = None
        comparison: Optional[str] = None
        unit: Optional[str] = None
    else:
        target_value = requirement.target_value
        comparison = requirement.comparison
        unit = requirement.unit
        target_eval = evaluate_against_target(measured_value, target_value, comparison)
        if target_eval.status == STATUS_UNKNOWN:
            performance_status = STATUS_UNKNOWN
            # Prefer this module's own, more specific reason for why the measured value is
            # missing/unusable over evaluate_against_target()'s generic one, when we have it.
            reason = (
                measured_reason
                if measured_value is None and measured_reason
                else target_eval.reason
            )
        else:
            # STATUS_COMPUTED: a real comparison was actually made.
            performance_status = (
                Status.PASS.value if target_eval.meets_target else Status.FAIL.value
            )
            reason = None

    # Rule (c): functional correctness ALWAYS outranks a performance PASS -- enforced as a
    # hard precedence, never a weighted score. A real functional FAIL overrides the
    # performance verdict unconditionally, whatever that verdict is.
    if functional_verdict == Status.FAIL.value:
        overall_status = Status.FAIL.value
        overall_reason = (
            "functional correctness FAILed; this always outranks the performance "
            f"comparison's own verdict ({performance_status!r}), including a performance "
            "PASS -- a high-performance but functionally incorrect transaction is still "
            "an overall FAIL"
        )
    else:
        overall_status = performance_status
        overall_reason = reason

    return PerformanceRequirementCheckResult(
        requirement_id=requirement_id,
        metric_name=metric_name,
        measured_value=measured_value,
        target_value=target_value,
        comparison=comparison,
        unit=unit,
        performance_status=performance_status,
        status=overall_status,
        functional_verdict=functional_verdict,
        reason=overall_reason,
    )
