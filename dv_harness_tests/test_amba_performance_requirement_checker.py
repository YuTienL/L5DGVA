"""Tests for dv_harness/amba_performance_requirement_checker.py.

Real, deterministic synthetic transaction traces only -- no FSDB/waveform reads, no
simulation. Every test constructs its own small, explicit numeric fixture.
"""
from __future__ import annotations

import pytest

from dv_harness.models import Status
from dv_harness.amba_performance_calculator import (
    MetricResult,
    STATUS_COMPUTED,
    STATUS_NOT_APPLICABLE,
    STATUS_UNKNOWN,
    PerformanceSampleIR,
    aggregate_port_performance,
    bandwidth_utilization,
)
from dv_harness.amba_performance_requirement_checker import (
    PerformanceRequirementCheckerError,
    PerformanceRequirementIR,
    check_against_requirement,
)


# --- PerformanceRequirementIR: rule (a) enforced at construction -----------------------


def test_requirement_ir_construction_requires_all_three_mandatory_fields():
    req = PerformanceRequirementIR(
        requirement_id="REQ-BW-1",
        metric_name="bandwidth",
        target_value=1000.0,
        comparison=">=",
        unit="bytes_per_second",
        source="spec section 4.2",
    )
    assert req.target_value == 1000.0
    assert req.comparison == ">="
    assert req.unit == "bytes_per_second"


def test_requirement_ir_refuses_missing_target_value():
    with pytest.raises(PerformanceRequirementCheckerError):
        PerformanceRequirementIR(
            requirement_id="REQ-1",
            metric_name="bandwidth",
            target_value=None,  # type: ignore[arg-type]
            comparison="<=",
            unit="bytes_per_second",
        )


def test_requirement_ir_refuses_missing_unit():
    with pytest.raises(PerformanceRequirementCheckerError):
        PerformanceRequirementIR(
            requirement_id="REQ-1",
            metric_name="bandwidth",
            target_value=1000.0,
            comparison="<=",
            unit="",
        )


def test_requirement_ir_refuses_bad_comparison_operator():
    with pytest.raises(PerformanceRequirementCheckerError):
        PerformanceRequirementIR(
            requirement_id="REQ-1",
            metric_name="bandwidth",
            target_value=1000.0,
            comparison="~=",
            unit="bytes_per_second",
        )


def test_requirement_ir_refuses_boolean_target_value():
    with pytest.raises(PerformanceRequirementCheckerError):
        PerformanceRequirementIR(
            requirement_id="REQ-1",
            metric_name="bandwidth",
            target_value=True,  # type: ignore[arg-type]
            comparison="<=",
            unit="bytes_per_second",
        )


# --- core positive path: real requirement, real measured value ------------------------


def test_checker_reports_pass_when_measured_clears_the_threshold():
    req = PerformanceRequirementIR(
        requirement_id="REQ-LAT-1",
        metric_name="latency_p99",
        target_value=50.0,
        comparison="<=",
        unit="microseconds",
    )
    result = check_against_requirement(42.0, "latency_p99", req)
    assert result.performance_status == Status.PASS.value
    assert result.status == Status.PASS.value
    assert result.measured_value == 42.0
    assert result.target_value == 50.0


def test_checker_reports_fail_when_measured_exceeds_the_threshold():
    req = PerformanceRequirementIR(
        requirement_id="REQ-LAT-1",
        metric_name="latency_p99",
        target_value=50.0,
        comparison="<=",
        unit="microseconds",
    )
    result = check_against_requirement(75.0, "latency_p99", req)
    assert result.performance_status == Status.FAIL.value
    assert result.status == Status.FAIL.value


# --- NOT_APPLICABLE: no requirement declared is NEVER a failure ------------------------


def test_no_requirement_declared_is_not_applicable_never_a_failure():
    result = check_against_requirement(999999.0, "some_metric", requirement=None)
    assert result.status == STATUS_NOT_APPLICABLE
    assert result.status != Status.FAIL.value
    assert result.target_value is None
    assert result.reason


def test_no_requirement_declared_stays_not_applicable_even_with_no_measured_value():
    result = check_against_requirement(None, "some_metric", requirement=None)
    assert result.status == STATUS_NOT_APPLICABLE


# --- UNKNOWN: an unprovable measured value is NEVER computed/reported as a number ------


def test_missing_measured_value_reports_unknown_never_a_fabricated_number():
    req = PerformanceRequirementIR(
        requirement_id="REQ-BW-1",
        metric_name="bandwidth",
        target_value=1000.0,
        comparison=">=",
        unit="bytes_per_second",
    )
    result = check_against_requirement(None, "bandwidth", req)
    assert result.status == STATUS_UNKNOWN
    assert result.measured_value is None
    assert result.reason


def test_metric_result_with_non_computed_status_is_treated_as_unknown_not_zero():
    # bandwidth_utilization() honestly reports STATUS_UNKNOWN when no caller-supplied
    # peak bandwidth exists -- the calculator module's own sharpest instance of this rule.
    metric = bandwidth_utilization(
        observed_bandwidth_bytes_per_second=500.0,
        peak_bandwidth_bytes_per_second=None,
    )
    assert metric.status == STATUS_UNKNOWN

    req = PerformanceRequirementIR(
        requirement_id="REQ-UTIL-1",
        metric_name="bandwidth_utilization",
        target_value=80.0,
        comparison="<=",
        unit="percent",
    )
    result = check_against_requirement(metric, "bandwidth_utilization", req)
    assert result.status == STATUS_UNKNOWN
    assert result.measured_value is None
    # never a computed-looking percentage silently substituted
    assert result.status != Status.PASS.value
    assert result.status != Status.FAIL.value


def test_real_port_performance_ir_bandwidth_is_resolved_and_evaluated():
    samples = [
        PerformanceSampleIR(
            sample_id="s1",
            start_time=0.0,
            end_time=1.0,
            byte_count=2000.0,
            transaction_count=10,
        ),
    ]
    port_perf = aggregate_port_performance("port0", samples)
    assert port_perf.bandwidth.status == STATUS_COMPUTED
    assert port_perf.bandwidth.value == 2000.0  # 2000 bytes / 1 second

    req = PerformanceRequirementIR(
        requirement_id="REQ-BW-2",
        metric_name="bandwidth",
        target_value=1500.0,
        comparison=">=",
        unit="bytes_per_second",
    )
    result = check_against_requirement(port_perf, "bandwidth", req)
    assert result.performance_status == Status.PASS.value
    assert result.measured_value == 2000.0


def test_real_port_performance_ir_with_no_samples_reports_unknown():
    port_perf = aggregate_port_performance("port0", [])
    assert port_perf.bandwidth.status == STATUS_UNKNOWN

    req = PerformanceRequirementIR(
        requirement_id="REQ-BW-3",
        metric_name="bandwidth",
        target_value=1500.0,
        comparison=">=",
        unit="bytes_per_second",
    )
    result = check_against_requirement(port_perf, "bandwidth", req)
    assert result.status == STATUS_UNKNOWN
    assert result.measured_value is None


def test_measured_value_as_plain_dict_is_resolved():
    req = PerformanceRequirementIR(
        requirement_id="REQ-1",
        metric_name="throughput",
        target_value=100.0,
        comparison=">=",
        unit="transactions_per_second",
    )
    result = check_against_requirement({"throughput": 150.0}, "throughput", req)
    assert result.status == Status.PASS.value
    assert result.measured_value == 150.0


def test_measured_value_as_dict_containing_a_nested_metric_result():
    req = PerformanceRequirementIR(
        requirement_id="REQ-1",
        metric_name="throughput",
        target_value=100.0,
        comparison=">=",
        unit="transactions_per_second",
    )
    nested = MetricResult(value=42.0, status=STATUS_COMPUTED, unit="transactions_per_second")
    result = check_against_requirement({"throughput": nested}, "throughput", req)
    assert result.status == Status.FAIL.value
    assert result.measured_value == 42.0


# --- CRITICAL RULE: functional correctness always outranks a performance PASS ----------


def test_functional_fail_overrides_a_performance_pass():
    req = PerformanceRequirementIR(
        requirement_id="REQ-LAT-1",
        metric_name="latency_p99",
        target_value=50.0,
        comparison="<=",
        unit="microseconds",
    )
    # Performance is excellent (10us against a 50us cap) -- clearly a performance PASS.
    result = check_against_requirement(
        10.0, "latency_p99", req, functional_verdict=Status.FAIL.value
    )
    assert result.performance_status == Status.PASS.value  # the raw comparison did PASS
    assert result.status == Status.FAIL.value  # but the overall verdict is FAIL
    assert "functional" in result.reason.lower()


def test_functional_fail_overrides_even_when_no_requirement_was_declared():
    # NOT_APPLICABLE performance (no requirement at all) must still yield overall FAIL
    # when functional correctness failed -- the precedence is unconditional.
    result = check_against_requirement(
        123.0, "some_metric", requirement=None, functional_verdict=Status.FAIL.value
    )
    assert result.performance_status == STATUS_NOT_APPLICABLE
    assert result.status == Status.FAIL.value


def test_functional_fail_overrides_even_an_unknown_performance_result():
    req = PerformanceRequirementIR(
        requirement_id="REQ-1",
        metric_name="bandwidth",
        target_value=1000.0,
        comparison=">=",
        unit="bytes_per_second",
    )
    result = check_against_requirement(
        None, "bandwidth", req, functional_verdict=Status.FAIL.value
    )
    assert result.performance_status == STATUS_UNKNOWN
    assert result.status == Status.FAIL.value


def test_functional_pass_never_elevates_a_performance_fail():
    req = PerformanceRequirementIR(
        requirement_id="REQ-LAT-1",
        metric_name="latency_p99",
        target_value=50.0,
        comparison="<=",
        unit="microseconds",
    )
    result = check_against_requirement(
        999.0, "latency_p99", req, functional_verdict=Status.PASS.value
    )
    assert result.performance_status == Status.FAIL.value
    assert result.status == Status.FAIL.value  # never elevated to PASS


def test_omitted_functional_verdict_leaves_performance_status_unchanged():
    req = PerformanceRequirementIR(
        requirement_id="REQ-LAT-1",
        metric_name="latency_p99",
        target_value=50.0,
        comparison="<=",
        unit="microseconds",
    )
    result = check_against_requirement(10.0, "latency_p99", req, functional_verdict=None)
    assert result.status == result.performance_status == Status.PASS.value


# --- negative controls: malformed caller usage always raises, never silently repairs ---


def test_invalid_functional_verdict_string_raises():
    req = PerformanceRequirementIR(
        requirement_id="REQ-1",
        metric_name="bandwidth",
        target_value=1000.0,
        comparison=">=",
        unit="bytes_per_second",
    )
    with pytest.raises(PerformanceRequirementCheckerError):
        check_against_requirement(500.0, "bandwidth", req, functional_verdict="MAYBE")


def test_unresolvable_measured_value_shape_raises_rather_than_guesses():
    req = PerformanceRequirementIR(
        requirement_id="REQ-1",
        metric_name="bandwidth",
        target_value=1000.0,
        comparison=">=",
        unit="bytes_per_second",
    )
    with pytest.raises(PerformanceRequirementCheckerError):
        # a bare list exposes no "bandwidth" field and is not itself numeric/MetricResult
        check_against_requirement([1, 2, 3], "bandwidth", req)


def test_bool_measured_value_is_refused():
    req = PerformanceRequirementIR(
        requirement_id="REQ-1",
        metric_name="bandwidth",
        target_value=1000.0,
        comparison=">=",
        unit="bytes_per_second",
    )
    with pytest.raises(PerformanceRequirementCheckerError):
        check_against_requirement(True, "bandwidth", req)


def test_dict_missing_the_named_field_reports_unknown_not_a_raise():
    req = PerformanceRequirementIR(
        requirement_id="REQ-1",
        metric_name="bandwidth",
        target_value=1000.0,
        comparison=">=",
        unit="bytes_per_second",
    )
    result = check_against_requirement({"throughput": 50.0}, "bandwidth", req)
    assert result.status == STATUS_UNKNOWN
    assert result.measured_value is None
