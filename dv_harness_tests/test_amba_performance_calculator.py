"""Tests for dv_harness/amba_performance_calculator.py.

Fixtures are small, real synthetic transaction-trace samples built directly
in this file (deterministic synthetic transaction traces, per this task's own
instruction) -- never a real project's evidence, and never a live simulator.
"""
from __future__ import annotations

import pytest

from dv_harness.amba_performance_calculator import (
    DEFAULT_PERCENTILES,
    LATENCY_DEFINITION_ISSUE_TO_FIRST_BEAT,
    LATENCY_DEFINITION_ISSUE_TO_LAST_BEAT,
    STATUS_COMPUTED,
    STATUS_NOT_APPLICABLE,
    STATUS_UNKNOWN,
    LatencyDefinitionIR,
    PerformanceCalculatorError,
    PerformanceSampleIR,
    PerformanceWindowIR,
    PerformanceCurveIR,
    aggregate_port_performance,
    bandwidth_utilization,
    compute_bandwidth,
    compute_latency_percentiles,
    compute_outstanding_stats,
    compute_stall_ratio,
    compute_throughput,
    compute_utilization,
    decide_overall_verdict,
    evaluate_against_target,
)
from dv_harness.models import Status


# ---------------------------------------------------------------------------
# LatencyDefinitionIR: never assumed, always caller-declared
# ---------------------------------------------------------------------------


class TestLatencyDefinitionIR:
    def test_accepts_a_real_declared_definition(self):
        ir = LatencyDefinitionIR(definition=LATENCY_DEFINITION_ISSUE_TO_FIRST_BEAT)
        assert ir.definition == "ISSUE_TO_FIRST_BEAT"

    def test_rejects_an_unrecognized_definition(self):
        with pytest.raises(PerformanceCalculatorError):
            LatencyDefinitionIR(definition="SOMETHING_MADE_UP")


# ---------------------------------------------------------------------------
# compute_bandwidth / compute_throughput
# ---------------------------------------------------------------------------


class TestComputeBandwidth:
    def test_real_bandwidth_from_real_numbers(self):
        result = compute_bandwidth(total_bytes=1024.0, duration_seconds=2.0)
        assert result.status == STATUS_COMPUTED
        assert result.value == pytest.approx(512.0)
        assert result.unit == "bytes_per_second"

    def test_missing_total_bytes_is_unknown_never_zero(self):
        result = compute_bandwidth(total_bytes=None, duration_seconds=2.0)
        assert result.status == STATUS_UNKNOWN
        assert result.value is None
        assert result.reason

    def test_missing_duration_is_unknown_never_zero(self):
        result = compute_bandwidth(total_bytes=1024.0, duration_seconds=None)
        assert result.status == STATUS_UNKNOWN
        assert result.value is None

    def test_zero_duration_is_unknown_never_a_crash(self):
        result = compute_bandwidth(total_bytes=1024.0, duration_seconds=0.0)
        assert result.status == STATUS_UNKNOWN
        assert result.value is None

    def test_negative_duration_is_unknown(self):
        result = compute_bandwidth(total_bytes=1024.0, duration_seconds=-1.0)
        assert result.status == STATUS_UNKNOWN

    def test_negative_bytes_is_a_caller_usage_error(self):
        with pytest.raises(PerformanceCalculatorError):
            compute_bandwidth(total_bytes=-5.0, duration_seconds=1.0)


class TestComputeThroughput:
    def test_real_throughput_from_real_numbers(self):
        result = compute_throughput(transaction_count=100, duration_seconds=4.0)
        assert result.status == STATUS_COMPUTED
        assert result.value == pytest.approx(25.0)
        assert result.unit == "transactions_per_second"

    def test_missing_transaction_count_is_unknown(self):
        result = compute_throughput(transaction_count=None, duration_seconds=4.0)
        assert result.status == STATUS_UNKNOWN
        assert result.value is None

    def test_missing_duration_is_unknown(self):
        result = compute_throughput(transaction_count=100, duration_seconds=None)
        assert result.status == STATUS_UNKNOWN


# ---------------------------------------------------------------------------
# compute_latency_percentiles: empty list -> UNKNOWN, never 0/crash;
# latency_definition mandatory -- never assumed
# ---------------------------------------------------------------------------


class TestComputeLatencyPercentiles:
    def test_real_percentiles_from_a_real_synthetic_trace(self):
        # a real synthetic list of 100 observed request-to-response latencies,
        # 1..100 ns, so p50/p90/p95/p99 are independently checkable by hand.
        latencies = [float(n) for n in range(1, 101)]
        report = compute_latency_percentiles(
            latencies,
            LatencyDefinitionIR(definition=LATENCY_DEFINITION_ISSUE_TO_LAST_BEAT),
        )
        assert report.status == STATUS_COMPUTED
        assert report.sample_count == 100
        assert report.latency_definition == "ISSUE_TO_LAST_BEAT"
        assert report.percentiles["p50"] == pytest.approx(50.5, abs=0.51)
        assert report.percentiles["p99"] > report.percentiles["p95"] > report.percentiles["p90"]

    def test_accepts_a_bare_definition_string(self):
        report = compute_latency_percentiles(
            [1.0, 2.0, 3.0], LATENCY_DEFINITION_ISSUE_TO_FIRST_BEAT
        )
        assert report.status == STATUS_COMPUTED
        assert report.latency_definition == "ISSUE_TO_FIRST_BEAT"

    def test_empty_latency_list_reports_unknown_never_zero_or_crash(self):
        report = compute_latency_percentiles(
            [], LatencyDefinitionIR(definition=LATENCY_DEFINITION_ISSUE_TO_FIRST_BEAT)
        )
        assert report.status == STATUS_UNKNOWN
        assert report.sample_count == 0
        assert all(v is None for v in report.percentiles.values())
        assert report.reason

    def test_none_latency_list_reports_unknown_never_zero_or_crash(self):
        report = compute_latency_percentiles(
            None, LatencyDefinitionIR(definition=LATENCY_DEFINITION_ISSUE_TO_FIRST_BEAT)
        )
        assert report.status == STATUS_UNKNOWN
        assert report.percentiles

    def test_missing_latency_definition_is_a_hard_refusal_never_a_guess(self):
        with pytest.raises(PerformanceCalculatorError):
            compute_latency_percentiles([1.0, 2.0, 3.0], None)

    def test_unrecognized_latency_definition_string_is_refused(self):
        with pytest.raises(PerformanceCalculatorError):
            compute_latency_percentiles([1.0], "MADE_UP_DEFINITION")

    def test_negative_latency_value_is_a_caller_usage_error(self):
        with pytest.raises(PerformanceCalculatorError):
            compute_latency_percentiles(
                [1.0, -2.0],
                LatencyDefinitionIR(definition=LATENCY_DEFINITION_ISSUE_TO_FIRST_BEAT),
            )


# ---------------------------------------------------------------------------
# compute_outstanding_stats
# ---------------------------------------------------------------------------


class TestComputeOutstandingStats:
    def test_real_average_and_peak_from_a_real_trace(self):
        result = compute_outstanding_stats([2, 4, 6, 8])
        assert result.status == STATUS_COMPUTED
        assert result.average == pytest.approx(5.0)
        assert result.peak == 8
        assert result.sample_count == 4

    def test_empty_list_is_unknown_never_zero_or_crash(self):
        result = compute_outstanding_stats([])
        assert result.status == STATUS_UNKNOWN
        assert result.average is None
        assert result.peak is None
        assert result.reason

    def test_none_is_unknown_never_a_crash(self):
        result = compute_outstanding_stats(None)
        assert result.status == STATUS_UNKNOWN

    def test_negative_count_is_a_caller_usage_error(self):
        with pytest.raises(PerformanceCalculatorError):
            compute_outstanding_stats([1, -1])


# ---------------------------------------------------------------------------
# compute_stall_ratio / compute_utilization
# ---------------------------------------------------------------------------


class TestComputeStallRatio:
    def test_real_ratio_from_real_numbers(self):
        result = compute_stall_ratio(stalled_cycles=25, total_cycles=100)
        assert result.status == STATUS_COMPUTED
        assert result.value == pytest.approx(0.25)
        assert result.reason is None

    def test_missing_stalled_cycles_is_unknown(self):
        result = compute_stall_ratio(stalled_cycles=None, total_cycles=100)
        assert result.status == STATUS_UNKNOWN

    def test_missing_total_cycles_is_unknown(self):
        result = compute_stall_ratio(stalled_cycles=25, total_cycles=None)
        assert result.status == STATUS_UNKNOWN

    def test_zero_total_cycles_is_unknown_never_a_divide_by_zero_crash(self):
        result = compute_stall_ratio(stalled_cycles=25, total_cycles=0)
        assert result.status == STATUS_UNKNOWN

    def test_over_range_ratio_is_reported_with_a_data_quality_reason(self):
        result = compute_stall_ratio(stalled_cycles=150, total_cycles=100)
        assert result.status == STATUS_COMPUTED
        assert result.value == pytest.approx(1.5)
        assert "data-quality" in result.reason


class TestComputeUtilization:
    def test_real_utilization_from_real_numbers(self):
        result = compute_utilization(busy_cycles=80, total_cycles=100)
        assert result.status == STATUS_COMPUTED
        assert result.value == pytest.approx(0.80)

    def test_missing_busy_cycles_is_unknown(self):
        result = compute_utilization(busy_cycles=None, total_cycles=100)
        assert result.status == STATUS_UNKNOWN


# ---------------------------------------------------------------------------
# bandwidth_utilization: MUST be UNKNOWN with no peak supplied
# ---------------------------------------------------------------------------


class TestBandwidthUtilization:
    def test_real_utilization_percentage_from_a_real_declared_peak(self):
        result = bandwidth_utilization(
            observed_bandwidth_bytes_per_second=2_000_000_000.0,
            peak_bandwidth_bytes_per_second=4_000_000_000.0,
        )
        assert result.status == STATUS_COMPUTED
        assert result.value == pytest.approx(50.0)
        assert result.unit == "percent"

    def test_no_peak_supplied_is_unknown_never_a_computed_percentage(self):
        result = bandwidth_utilization(
            observed_bandwidth_bytes_per_second=2_000_000_000.0,
            peak_bandwidth_bytes_per_second=None,
        )
        assert result.status == STATUS_UNKNOWN
        assert result.value is None
        assert "peak" in result.reason.lower()

    def test_zero_or_negative_peak_is_unknown_never_a_divide_by_zero(self):
        result = bandwidth_utilization(
            observed_bandwidth_bytes_per_second=100.0,
            peak_bandwidth_bytes_per_second=0.0,
        )
        assert result.status == STATUS_UNKNOWN

    def test_no_observed_bandwidth_is_unknown(self):
        result = bandwidth_utilization(
            observed_bandwidth_bytes_per_second=None,
            peak_bandwidth_bytes_per_second=4_000_000_000.0,
        )
        assert result.status == STATUS_UNKNOWN


# ---------------------------------------------------------------------------
# evaluate_against_target: rule (a), a threshold is never invented
# ---------------------------------------------------------------------------


class TestEvaluateAgainstTarget:
    def test_meets_a_real_caller_declared_target(self):
        result = evaluate_against_target(observed_value=80.0, target_value=100.0, comparison="<=")
        assert result.status == STATUS_COMPUTED
        assert result.meets_target is True

    def test_misses_a_real_caller_declared_target(self):
        result = evaluate_against_target(observed_value=120.0, target_value=100.0, comparison="<=")
        assert result.status == STATUS_COMPUTED
        assert result.meets_target is False

    def test_no_target_supplied_is_not_applicable_never_a_fabricated_verdict(self):
        result = evaluate_against_target(observed_value=80.0, target_value=None)
        assert result.status == STATUS_NOT_APPLICABLE
        assert result.meets_target is None
        assert "never" in result.reason.lower() or "not" in result.reason.lower()

    def test_no_observed_value_is_unknown(self):
        result = evaluate_against_target(observed_value=None, target_value=100.0)
        assert result.status == STATUS_UNKNOWN
        assert result.meets_target is None

    def test_unrecognized_comparison_is_a_caller_usage_error(self):
        with pytest.raises(PerformanceCalculatorError):
            evaluate_against_target(observed_value=1.0, target_value=2.0, comparison="~=")


# ---------------------------------------------------------------------------
# decide_overall_verdict: functional correctness ALWAYS outranks performance
# ---------------------------------------------------------------------------


class TestDecideOverallVerdict:
    def test_functional_fail_outranks_a_performance_pass(self):
        # A high-performance but functionally incorrect transaction is still
        # an overall FAIL -- the headline rule this module must enforce.
        result = decide_overall_verdict(
            functional_verdict=Status.FAIL.value, performance_verdict=Status.PASS.value
        )
        assert result.verdict == Status.FAIL.value
        assert "outrank" in result.reason.lower()

    def test_functional_pass_and_performance_pass_is_overall_pass(self):
        result = decide_overall_verdict(
            functional_verdict=Status.PASS.value, performance_verdict=Status.PASS.value
        )
        assert result.verdict == Status.PASS.value

    def test_functional_pass_with_no_performance_verdict_is_overall_pass(self):
        result = decide_overall_verdict(functional_verdict=Status.PASS.value)
        assert result.verdict == Status.PASS.value

    def test_functional_pass_but_performance_fail_is_overall_fail(self):
        result = decide_overall_verdict(
            functional_verdict=Status.PASS.value, performance_verdict=Status.FAIL.value
        )
        assert result.verdict == Status.FAIL.value

    def test_unresolved_functional_verdict_is_unknown_never_an_assumed_pass(self):
        result = decide_overall_verdict(
            functional_verdict=STATUS_UNKNOWN, performance_verdict=Status.PASS.value
        )
        assert result.verdict == STATUS_UNKNOWN
        # Even a great performance number must never promote an unresolved
        # functional result to PASS.
        assert result.verdict != Status.PASS.value

    def test_functional_fail_outranks_performance_even_when_performance_is_unknown(self):
        result = decide_overall_verdict(
            functional_verdict=Status.FAIL.value, performance_verdict=STATUS_UNKNOWN
        )
        assert result.verdict == Status.FAIL.value


# ---------------------------------------------------------------------------
# aggregate_port_performance: assembles a real PortPerformanceIR
# ---------------------------------------------------------------------------


class TestAggregatePortPerformance:
    def _real_samples(self):
        return [
            PerformanceSampleIR(
                sample_id="txn-0",
                start_time=0.0,
                end_time=1.0,
                byte_count=1024.0,
                transaction_count=10,
                latency=5.0,
                outstanding_count=2,
                busy_cycles=80.0,
                stalled_cycles=20.0,
                total_cycles=100.0,
                source_evidence="fsdb_report.py:trace#0",
            ),
            PerformanceSampleIR(
                sample_id="txn-1",
                start_time=1.0,
                end_time=2.0,
                byte_count=2048.0,
                transaction_count=20,
                latency=7.0,
                outstanding_count=4,
                busy_cycles=90.0,
                stalled_cycles=10.0,
                total_cycles=100.0,
                source_evidence="fsdb_report.py:trace#1",
            ),
        ]

    def test_real_port_performance_from_real_samples(self):
        ir = aggregate_port_performance(
            "M0",
            self._real_samples(),
            latency_definition=LatencyDefinitionIR(
                definition=LATENCY_DEFINITION_ISSUE_TO_FIRST_BEAT
            ),
            peak_bandwidth_bytes_per_second=4096.0,
        )
        assert ir.port_id == "M0"
        assert ir.sample_count == 2
        assert ir.bandwidth.status == STATUS_COMPUTED
        assert ir.bandwidth.value == pytest.approx((1024.0 + 2048.0) / 2.0)
        assert ir.throughput.status == STATUS_COMPUTED
        assert ir.throughput.value == pytest.approx(15.0)
        assert ir.latency_report.status == STATUS_COMPUTED
        assert ir.latency_report.sample_count == 2
        assert ir.outstanding.status == STATUS_COMPUTED
        assert ir.outstanding.peak == 4
        assert ir.stall_ratio.status == STATUS_COMPUTED
        assert ir.stall_ratio.value == pytest.approx(30.0 / 200.0)
        assert ir.utilization.status == STATUS_COMPUTED
        assert ir.bandwidth_utilization.status == STATUS_COMPUTED
        assert len(ir.source_evidence) == 2

    def test_no_latency_definition_declared_is_not_applicable_never_a_guess(self):
        ir = aggregate_port_performance("M0", self._real_samples())
        assert ir.latency_report.status == STATUS_NOT_APPLICABLE

    def test_no_peak_declared_makes_bandwidth_utilization_unknown(self):
        ir = aggregate_port_performance("M0", self._real_samples())
        assert ir.bandwidth_utilization.status == STATUS_UNKNOWN

    def test_empty_sample_list_reports_every_metric_as_unknown_never_a_crash(self):
        ir = aggregate_port_performance("M0", [])
        assert ir.sample_count == 0
        assert ir.bandwidth.status == STATUS_UNKNOWN
        assert ir.throughput.status == STATUS_UNKNOWN
        assert ir.outstanding.status == STATUS_UNKNOWN
        assert ir.stall_ratio.status == STATUS_UNKNOWN
        assert ir.utilization.status == STATUS_UNKNOWN
        assert ir.bandwidth_utilization.status == STATUS_UNKNOWN


# ---------------------------------------------------------------------------
# PerformanceWindowIR / PerformanceCurveIR: data shapes only
# ---------------------------------------------------------------------------


class TestWindowAndCurveShapes:
    def test_window_holds_real_samples(self):
        window = PerformanceWindowIR(
            window_id="W0",
            start_time=0.0,
            end_time=10.0,
            samples=[PerformanceSampleIR(sample_id="txn-0")],
        )
        assert len(window.samples) == 1

    def test_window_rejects_end_before_start(self):
        with pytest.raises(PerformanceCalculatorError):
            PerformanceWindowIR(window_id="W0", start_time=10.0, end_time=0.0)

    def test_curve_is_an_ordered_series_of_windows_and_generates_nothing(self):
        w0 = PerformanceWindowIR(window_id="W0", start_time=0.0, end_time=1.0)
        w1 = PerformanceWindowIR(window_id="W1", start_time=1.0, end_time=2.0)
        curve = PerformanceCurveIR(curve_id="ramp-0", windows=[w0, w1])
        assert curve.windows == [w0, w1]
        # This module only holds the shape -- it never invents a third window.
        assert len(curve.windows) == 2
