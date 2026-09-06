"""Tests for dv_harness/amba_performance_classification.py.

Covers all four classifiers (saturation, bottleneck-candidate, anomaly,
regression-delta) plus Jain's fairness index, with real synthetic
deterministic transaction-trace-shaped fixtures built directly in this file
(per this batch's own task instruction). Core positive paths plus negative
controls proving: (1) the module refuses to compute/report a number when
required real input is missing (UNKNOWN/NOT_APPLICABLE rather than a
computed-looking value), and (2) functional-correctness-outranks-performance
via the reused `decide_overall_verdict()` precedence.
"""
from __future__ import annotations

import pytest

from dv_harness import amba_performance_classification as apc
from dv_harness.models import Status


# --- vocabulary hygiene ---------------------------------------------------


def test_status_vocabulary_disjoint_from_models_status():
    # Re-running the module-level assertion directly proves it has real
    # detection power (it already ran at import time without raising).
    apc._assert_status_vocabulary_disjoint_from_models_status()


# --- 1. classify_saturation ------------------------------------------------


def test_saturation_positive_both_metrics_agree():
    result = apc.classify_saturation(
        utilization_value=96.0,
        utilization_max=100.0,
        near_max_ratio_threshold=0.9,
        rising_latency_trend=True,
        latency_trend_evidence="fsdb_report samples t=10..40 show latency rising 12ns->48ns",
    )
    assert result.status == apc.SATURATION_SATURATED
    assert result.near_max_observed is True
    assert result.rising_signal_observed is True
    assert result.utilization_ratio == pytest.approx(0.96)


def test_saturation_positive_via_stall_signal():
    result = apc.classify_saturation(
        utilization_value=91.0,
        utilization_max=100.0,
        near_max_ratio_threshold=0.9,
        rising_stall_trend=True,
        stall_trend_evidence="sim.log stall-cycle counter rose monotonically across window",
    )
    assert result.status == apc.SATURATION_SATURATED


def test_saturation_not_saturated_both_metrics_agree_negative():
    result = apc.classify_saturation(
        utilization_value=40.0,
        utilization_max=100.0,
        near_max_ratio_threshold=0.9,
        rising_latency_trend=False,
        latency_trend_evidence="fsdb_report shows flat latency across window",
    )
    assert result.status == apc.SATURATION_NOT_SATURATED


def test_saturation_indeterminate_when_metrics_disagree():
    # Utilization near max, but no rising signal observed.
    result = apc.classify_saturation(
        utilization_value=97.0,
        utilization_max=100.0,
        near_max_ratio_threshold=0.9,
        rising_latency_trend=False,
        latency_trend_evidence="flat",
    )
    assert result.status == apc.SATURATION_INDETERMINATE


def test_saturation_indeterminate_other_direction():
    # Rising signal observed, but utilization not near max.
    result = apc.classify_saturation(
        utilization_value=20.0,
        utilization_max=100.0,
        near_max_ratio_threshold=0.9,
        rising_latency_trend=True,
        latency_trend_evidence="latency crept up slightly",
    )
    assert result.status == apc.SATURATION_INDETERMINATE


def test_saturation_negative_control_single_metric_never_saturates():
    """NEGATIVE CONTROL: utilization alone (no rising-signal input at all)
    must never classify SATURATED/NOT_SATURATED -- one metric is never
    enough."""
    result = apc.classify_saturation(
        utilization_value=99.0,
        utilization_max=100.0,
        near_max_ratio_threshold=0.9,
    )
    assert result.status == apc.STATUS_UNKNOWN
    assert result.status not in (apc.SATURATION_SATURATED, apc.SATURATION_NOT_SATURATED)


def test_saturation_negative_control_no_declared_ceiling_is_not_applicable():
    """NEGATIVE CONTROL: no caller-declared max/threshold -- never invented."""
    result = apc.classify_saturation(
        utilization_value=99.0,
        utilization_max=None,
        near_max_ratio_threshold=None,
        rising_latency_trend=True,
        latency_trend_evidence="rising",
    )
    assert result.status == apc.STATUS_NOT_APPLICABLE


def test_saturation_negative_control_missing_observation_is_unknown():
    result = apc.classify_saturation(
        utilization_value=None,
        utilization_max=100.0,
        near_max_ratio_threshold=0.9,
        rising_latency_trend=True,
        latency_trend_evidence="rising",
    )
    assert result.status == apc.STATUS_UNKNOWN


def test_saturation_refuses_true_trend_with_no_evidence():
    """NEGATIVE CONTROL: asserting a rising trend with no cited evidence is
    a fabrication risk and must be refused, not silently accepted."""
    with pytest.raises(apc.PerformanceClassificationError):
        apc.classify_saturation(
            utilization_value=99.0,
            utilization_max=100.0,
            near_max_ratio_threshold=0.9,
            rising_latency_trend=True,
        )


def test_saturation_rejects_invalid_max():
    with pytest.raises(apc.PerformanceClassificationError):
        apc.classify_saturation(50.0, 0.0, 0.9)


def test_saturation_rejects_out_of_range_threshold():
    with pytest.raises(apc.PerformanceClassificationError):
        apc.classify_saturation(50.0, 100.0, 1.5)


# --- 2. identify_bottleneck_candidate --------------------------------------


def test_bottleneck_candidate_positive_structured_record():
    candidate = apc.identify_bottleneck_candidate(
        hypothesis="Port P3 is the fabric bottleneck under the current traffic mix",
        evidence=[
            "port P3 utilization 92% vs declared max 95% (fsdb_report window t=100..500)",
            "port P3 rising latency trend confirmed: 20ns->85ns over same window",
            "no comparable rising trend on sibling ports P0/P1/P2",
        ],
        gap="root cause (arbitration policy vs downstream slave latency) not yet isolated",
        next_best_action="rerun with targeted waveform on P3's arbiter grant signal",
    )
    assert candidate.hypothesis.startswith("Port P3")
    assert len(candidate.evidence) == 3
    assert candidate.confidence == apc.CONFIDENCE_MEDIUM  # gap present caps at MEDIUM
    assert "arbitration policy" in candidate.gap
    assert "arbiter grant signal" in candidate.next_best_action


def test_bottleneck_candidate_high_confidence_with_three_metrics_and_no_gap():
    candidate = apc.identify_bottleneck_candidate(
        hypothesis="Shared APB slave is the bottleneck",
        evidence=[
            "utilization 98% vs max 100%",
            "rising stall trend confirmed via sim.log",
            "cross-port correlation: all masters sharing this slave show identical stall onset",
        ],
    )
    assert candidate.confidence == apc.CONFIDENCE_HIGH
    assert candidate.gap == "no unresolved gap declared"
    # default next_best_action fallback is generated, never left empty
    assert candidate.next_best_action


def test_bottleneck_candidate_never_a_bare_label():
    candidate = apc.identify_bottleneck_candidate(
        hypothesis="H",
        evidence=["metric one", "metric two"],
    )
    # Must be the full structured record, not a bare string.
    assert isinstance(candidate, apc.BottleneckCandidateRecord)
    for attr in ("hypothesis", "evidence", "confidence", "gap", "next_best_action"):
        assert getattr(candidate, attr)


def test_bottleneck_candidate_refuses_single_metric_evidence():
    """NEGATIVE CONTROL: a hypothesis built on ONE metric alone must be
    refused, never silently reported as a candidate."""
    with pytest.raises(apc.PerformanceClassificationError):
        apc.identify_bottleneck_candidate(
            hypothesis="Port P3 is slow",
            evidence=["utilization 92% vs max 95%"],
        )


def test_bottleneck_candidate_refuses_no_evidence():
    with pytest.raises(apc.PerformanceClassificationError):
        apc.identify_bottleneck_candidate(hypothesis="Something is wrong", evidence=[])


def test_bottleneck_candidate_refuses_blank_evidence_entries():
    """Blank/whitespace-only entries do not count toward the real evidence
    minimum."""
    with pytest.raises(apc.PerformanceClassificationError):
        apc.identify_bottleneck_candidate(
            hypothesis="Something is wrong",
            evidence=["real metric one", "   ", ""],
        )


def test_bottleneck_candidate_refuses_blank_hypothesis():
    with pytest.raises(apc.PerformanceClassificationError):
        apc.identify_bottleneck_candidate(hypothesis="  ", evidence=["a", "b"])


# --- 3. detect_anomaly ------------------------------------------------------


def test_anomaly_range_mode_positive_detected():
    result = apc.detect_anomaly(150.0, baseline_min=80.0, baseline_max=120.0)
    assert result.status == apc.ANOMALY_DETECTED


def test_anomaly_range_mode_no_anomaly():
    result = apc.detect_anomaly(100.0, baseline_min=80.0, baseline_max=120.0)
    assert result.status == apc.NO_ANOMALY


def test_anomaly_distribution_mode_positive_detected():
    result = apc.detect_anomaly(
        200.0,
        baseline_mean=100.0,
        baseline_stddev=10.0,
        deviation_threshold_stddev=3.0,
    )
    assert result.status == apc.ANOMALY_DETECTED
    assert result.deviation == pytest.approx(10.0)


def test_anomaly_distribution_mode_no_anomaly():
    result = apc.detect_anomaly(
        105.0,
        baseline_mean=100.0,
        baseline_stddev=10.0,
        deviation_threshold_stddev=3.0,
    )
    assert result.status == apc.NO_ANOMALY


def test_anomaly_zero_stddev_exact_match_no_anomaly():
    result = apc.detect_anomaly(
        100.0,
        baseline_mean=100.0,
        baseline_stddev=0.0,
        deviation_threshold_stddev=3.0,
    )
    assert result.status == apc.NO_ANOMALY


def test_anomaly_zero_stddev_mismatch_detected():
    result = apc.detect_anomaly(
        101.0,
        baseline_mean=100.0,
        baseline_stddev=0.0,
        deviation_threshold_stddev=3.0,
    )
    assert result.status == apc.ANOMALY_DETECTED


def test_anomaly_negative_control_no_baseline_supplied_is_not_applicable():
    """NEGATIVE CONTROL: no real caller-supplied baseline -- never fabricated."""
    result = apc.detect_anomaly(150.0)
    assert result.status == apc.STATUS_NOT_APPLICABLE


def test_anomaly_negative_control_missing_observation_is_unknown():
    result = apc.detect_anomaly(None, baseline_min=80.0, baseline_max=120.0)
    assert result.status == apc.STATUS_UNKNOWN
    # Missing observation is UNKNOWN even though a real baseline exists.
    assert result.status != apc.STATUS_NOT_APPLICABLE


def test_anomaly_rejects_inverted_range():
    with pytest.raises(apc.PerformanceClassificationError):
        apc.detect_anomaly(100.0, baseline_min=200.0, baseline_max=100.0)


def test_anomaly_rejects_negative_stddev():
    with pytest.raises(apc.PerformanceClassificationError):
        apc.detect_anomaly(
            100.0, baseline_mean=100.0, baseline_stddev=-1.0, deviation_threshold_stddev=3.0
        )


# --- 4. compute_regression_delta -------------------------------------------


def test_regression_delta_improved_lower_is_better():
    result = apc.compute_regression_delta(
        "p99_latency_ns", baseline_value=100.0, current_value=60.0, lower_is_better=True
    )
    assert result.verdict == apc.REGRESSION_IMPROVED
    assert result.percent_change == pytest.approx(-40.0)


def test_regression_delta_regressed_lower_is_better():
    result = apc.compute_regression_delta(
        "p99_latency_ns", baseline_value=100.0, current_value=150.0, lower_is_better=True
    )
    assert result.verdict == apc.REGRESSION_REGRESSED


def test_regression_delta_improved_higher_is_better():
    result = apc.compute_regression_delta(
        "bandwidth_MBps", baseline_value=1000.0, current_value=1500.0, lower_is_better=False
    )
    assert result.verdict == apc.REGRESSION_IMPROVED


def test_regression_delta_unchanged_within_noise_floor():
    result = apc.compute_regression_delta(
        "p99_latency_ns",
        baseline_value=100.0,
        current_value=101.0,
        improvement_threshold_percent=2.0,
    )
    assert result.verdict == apc.REGRESSION_UNCHANGED


def test_regression_delta_inconclusive_different_units():
    result = apc.compute_regression_delta(
        "throughput",
        baseline_value=100.0,
        current_value=90000.0,
        baseline_unit="MBps",
        current_unit="Bps",
    )
    assert result.verdict == apc.REGRESSION_INCONCLUSIVE


def test_regression_delta_inconclusive_different_windows():
    result = apc.compute_regression_delta(
        "p99_latency_ns",
        baseline_value=100.0,
        current_value=90.0,
        baseline_window="regression_run_42",
        current_window="regression_run_99_partial",
    )
    assert result.verdict == apc.REGRESSION_INCONCLUSIVE


def test_regression_delta_inconclusive_zero_baseline_nonzero_current():
    """NEGATIVE CONTROL: division by an unsupplied/zero baseline must never
    silently produce a computed-looking percentage."""
    result = apc.compute_regression_delta(
        "stall_cycles", baseline_value=0.0, current_value=5.0
    )
    assert result.verdict == apc.REGRESSION_INCONCLUSIVE
    assert result.percent_change is None


def test_regression_delta_both_zero_is_unchanged():
    result = apc.compute_regression_delta("stall_cycles", baseline_value=0.0, current_value=0.0)
    assert result.verdict == apc.REGRESSION_UNCHANGED
    assert result.percent_change == 0.0


def test_regression_delta_negative_control_missing_sample_is_unknown():
    """NEGATIVE CONTROL: a missing measured sample is UNKNOWN, never a
    guessed verdict."""
    result = apc.compute_regression_delta("p99_latency_ns", baseline_value=100.0, current_value=None)
    assert result.verdict == apc.STATUS_UNKNOWN


def test_regression_delta_rejects_negative_threshold():
    with pytest.raises(apc.PerformanceClassificationError):
        apc.compute_regression_delta(
            "m", baseline_value=1.0, current_value=1.0, improvement_threshold_percent=-1.0
        )


def test_regression_delta_rejects_blank_metric_name():
    with pytest.raises(apc.PerformanceClassificationError):
        apc.compute_regression_delta("  ", baseline_value=1.0, current_value=2.0)


# --- rule (c): functional correctness always outranks performance ----------


def test_functional_fail_outranks_performance_improved():
    """The headline rule this batch requires: a high-performance
    (IMPROVED) but functionally-incorrect transaction is still an overall
    FAIL."""
    delta = apc.compute_regression_delta(
        "p99_latency_ns", baseline_value=200.0, current_value=50.0, lower_is_better=True
    )
    assert delta.verdict == apc.REGRESSION_IMPROVED

    overall = apc.decide_overall_performance_verdict(Status.FAIL.value, delta.verdict)
    assert overall.verdict == Status.FAIL.value
    assert overall.functional_verdict == Status.FAIL.value


def test_functional_pass_and_performance_regressed_is_overall_fail():
    delta = apc.compute_regression_delta(
        "p99_latency_ns", baseline_value=100.0, current_value=300.0, lower_is_better=True
    )
    assert delta.verdict == apc.REGRESSION_REGRESSED
    overall = apc.decide_overall_performance_verdict(Status.PASS.value, delta.verdict)
    assert overall.verdict == Status.FAIL.value


def test_functional_pass_and_performance_improved_is_overall_pass():
    delta = apc.compute_regression_delta(
        "p99_latency_ns", baseline_value=200.0, current_value=50.0, lower_is_better=True
    )
    overall = apc.decide_overall_performance_verdict(Status.PASS.value, delta.verdict)
    assert overall.verdict == Status.PASS.value


def test_functional_pass_and_inconclusive_performance_is_overall_pass():
    """INCONCLUSIVE performance must never be treated as a FAIL -- it maps
    to "no performance verdict evaluated", per the reused precedence rule."""
    overall = apc.decide_overall_performance_verdict(
        Status.PASS.value, apc.REGRESSION_INCONCLUSIVE
    )
    assert overall.verdict == Status.PASS.value
    assert overall.performance_verdict is None


def test_decide_overall_performance_verdict_reuses_calculator_module():
    """Reuse proof: this module's own function returns the exact
    OverallVerdictResult type from amba_performance_calculator, never a
    reimplemented parallel type."""
    from dv_harness.amba_performance_calculator import OverallVerdictResult

    overall = apc.decide_overall_performance_verdict(Status.PASS.value, None)
    assert isinstance(overall, OverallVerdictResult)


# --- Jain's fairness index --------------------------------------------------


def test_jains_fairness_index_perfectly_fair():
    result = apc.compute_jains_fairness_index({"m0": 100.0, "m1": 100.0, "m2": 100.0, "m3": 100.0})
    assert result.status == apc.STATUS_COMPUTED
    assert result.fairness_index == pytest.approx(1.0)


def test_jains_fairness_index_unfair_allocation():
    # One requester gets everything, three get nothing -> J = 1/n = 0.25
    result = apc.compute_jains_fairness_index({"m0": 400.0, "m1": 0.0, "m2": 0.0, "m3": 0.0})
    assert result.status == apc.STATUS_COMPUTED
    assert result.fairness_index == pytest.approx(0.25)


def test_jains_fairness_index_two_requesters_partial_unfairness():
    result = apc.compute_jains_fairness_index({"m0": 75.0, "m1": 25.0})
    assert result.status == apc.STATUS_COMPUTED
    # J = (75+25)^2 / (2*(75^2+25^2)) = 10000 / (2*6250) = 0.8
    assert result.fairness_index == pytest.approx(0.8)


def test_jains_fairness_index_refuses_incomplete_per_requester_data():
    """THE headline negative control this task requires: absent/incomplete
    per-requester data must report UNKNOWN, never silently compute over the
    partial set."""
    result = apc.compute_jains_fairness_index({"m0": 100.0, "m1": None, "m2": 50.0})
    assert result.status == apc.STATUS_UNKNOWN
    assert result.fairness_index is None
    assert "m1" in result.missing_requesters


def test_jains_fairness_index_refuses_when_all_missing():
    result = apc.compute_jains_fairness_index({"m0": None, "m1": None})
    assert result.status == apc.STATUS_UNKNOWN
    assert result.fairness_index is None


def test_jains_fairness_index_empty_map_is_unknown():
    result = apc.compute_jains_fairness_index({})
    assert result.status == apc.STATUS_UNKNOWN


def test_jains_fairness_index_single_requester_not_applicable():
    result = apc.compute_jains_fairness_index({"m0": 100.0})
    assert result.status == apc.STATUS_NOT_APPLICABLE


def test_jains_fairness_index_all_zero_is_unknown_not_a_fabricated_one():
    """0/0 is mathematically undefined -- must never be silently reported
    as a perfect J=1.0."""
    result = apc.compute_jains_fairness_index({"m0": 0.0, "m1": 0.0})
    assert result.status == apc.STATUS_UNKNOWN
    assert result.fairness_index is None


def test_jains_fairness_index_rejects_negative_value():
    with pytest.raises(apc.PerformanceClassificationError):
        apc.compute_jains_fairness_index({"m0": 100.0, "m1": -5.0})
