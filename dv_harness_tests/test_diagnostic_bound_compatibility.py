"""Tests for dv_harness/diagnostic_bound_compatibility.py -- L5DGVA v17
SS471 "Diagnostic Bound Compatibility"
(L5DGVA/L5_DGVA_Generic_MultiLevel_Verification_Contract_v17_ULTRA_STRICT_Auto_KC_Debug.md,
lines 6396-6403): "If an existing diagnostic triggers after time T, a bound
shorter than T cannot prove it ineffective. When intentionally using it,
choose an evidence-grounded bound allowing trigger, subject to
safety/resource policy."
"""
from __future__ import annotations

from dv_harness.diagnostic_bound_compatibility import (
    BOUND_CAPPED_BELOW_TRIGGER_LATENCY,
    BOUND_COMPATIBILITY_VALUES,
    BOUND_COMPATIBLE,
    BOUND_INSUFFICIENT,
    OBSERVATION_BOUND_UNKNOWN,
    RECOMMENDED_BOUND_WITHIN_POLICY,
    TRIGGER_LATENCY_UNKNOWN,
    classify_candidate_bound_compatibility,
    classify_diagnostic_bound_compatibility,
    filter_bound_compatible_candidates,
    recommend_evidence_grounded_bound,
)


# ---------------------------------------------------------------------------
# classify_diagnostic_bound_compatibility()
# ---------------------------------------------------------------------------

def test_bound_shorter_than_trigger_latency_is_insufficient_never_proves_ineffective():
    # SS471's literal example: watchdog fires at T=500us; a run bounded at
    # 200us cannot prove the watchdog ineffective.
    result = classify_diagnostic_bound_compatibility(trigger_latency=500.0, observation_bound=200.0)
    assert result["compatibility"] == BOUND_INSUFFICIENT
    assert result["can_prove_ineffective"] is False
    assert "500" in result["reason"] and "200" in result["reason"]


def test_bound_at_least_trigger_latency_is_compatible_and_can_prove_ineffective():
    result = classify_diagnostic_bound_compatibility(trigger_latency=500.0, observation_bound=500.0)
    assert result["compatibility"] == BOUND_COMPATIBLE
    assert result["can_prove_ineffective"] is True

    longer = classify_diagnostic_bound_compatibility(trigger_latency=500.0, observation_bound=900.0)
    assert longer["compatibility"] == BOUND_COMPATIBLE
    assert longer["can_prove_ineffective"] is True


def test_margin_extends_the_required_bound():
    # A bound exactly equal to T is compatible with no margin...
    exact = classify_diagnostic_bound_compatibility(trigger_latency=500.0, observation_bound=500.0, margin=0.0)
    assert exact["compatibility"] == BOUND_COMPATIBLE
    # ...but insufficient once a guard-band margin is required.
    with_margin = classify_diagnostic_bound_compatibility(trigger_latency=500.0, observation_bound=500.0, margin=50.0)
    assert with_margin["compatibility"] == BOUND_INSUFFICIENT
    assert with_margin["can_prove_ineffective"] is False


def test_unknown_trigger_latency_never_defaults_to_compatible_or_insufficient():
    result = classify_diagnostic_bound_compatibility(trigger_latency=None, observation_bound=1000.0)
    assert result["compatibility"] == TRIGGER_LATENCY_UNKNOWN
    assert result["can_prove_ineffective"] is False


def test_unknown_observation_bound_never_defaults_to_compatible():
    result = classify_diagnostic_bound_compatibility(trigger_latency=500.0, observation_bound=None)
    assert result["compatibility"] == OBSERVATION_BOUND_UNKNOWN
    assert result["can_prove_ineffective"] is False


def test_negative_margin_is_never_treated_as_shrinking_the_requirement():
    # A caller-declared negative margin must not silently make an
    # otherwise-insufficient bound look compatible.
    result = classify_diagnostic_bound_compatibility(trigger_latency=500.0, observation_bound=500.0, margin=-100.0)
    assert result["compatibility"] == BOUND_COMPATIBLE  # margin clamped to 0, not -100


def test_all_result_values_are_in_the_declared_vocabulary():
    cases = [
        (500.0, 200.0),
        (500.0, 500.0),
        (None, 500.0),
        (500.0, None),
    ]
    for t, b in cases:
        result = classify_diagnostic_bound_compatibility(t, b)
        assert result["compatibility"] in BOUND_COMPATIBILITY_VALUES


# ---------------------------------------------------------------------------
# classify_candidate_bound_compatibility() -- composition with the SS470
# existing-diagnostic-candidate dict shape used by
# fsdb_scope_gap_classifier.existing_diagnostic_mechanism_first() /
# inference.arbitrate_next_best_evidence().
# ---------------------------------------------------------------------------

def test_candidate_shape_reuses_existing_diagnostic_candidate_fields():
    candidate = {"kind": "watchdog", "cost": 1.0, "trigger_latency": 500.0}
    result = classify_candidate_bound_compatibility(candidate, observation_bound=200.0)
    assert result["compatibility"] == BOUND_INSUFFICIENT
    assert result["kind"] == "watchdog"
    assert result["candidate"] is candidate


def test_candidate_accepts_known_trigger_time_fallback_field_name():
    candidate = {"kind": "assertion", "known_trigger_time": 300.0}
    result = classify_candidate_bound_compatibility(candidate, observation_bound=400.0)
    assert result["compatibility"] == BOUND_COMPATIBLE


def test_candidate_missing_trigger_latency_field_is_unknown_not_compatible():
    candidate = {"kind": "sim_log", "cost": 0.0}
    result = classify_candidate_bound_compatibility(candidate, observation_bound=10000.0)
    assert result["compatibility"] == TRIGGER_LATENCY_UNKNOWN
    assert result["can_prove_ineffective"] is False


def test_non_dict_candidate_does_not_raise_and_is_treated_as_empty():
    result = classify_candidate_bound_compatibility(None, observation_bound=1000.0)  # type: ignore[arg-type]
    assert result["compatibility"] == TRIGGER_LATENCY_UNKNOWN
    assert result["kind"] is None


# ---------------------------------------------------------------------------
# filter_bound_compatible_candidates()
# ---------------------------------------------------------------------------

def test_filter_partitions_candidates_by_bound_compatibility():
    candidates = [
        {"kind": "watchdog", "trigger_latency": 500.0},   # bound 400 -> insufficient
        {"kind": "assertion", "trigger_latency": 300.0},  # bound 400 -> compatible
        {"kind": "sim_log"},                              # no T -> unknown
    ]
    partitioned = filter_bound_compatible_candidates(candidates, observation_bound=400.0)
    assert [c["kind"] for c in partitioned["compatible"]] == ["assertion"]
    incompatible_kinds = [c["kind"] for c in partitioned["incompatible"]]
    assert incompatible_kinds == ["watchdog", "sim_log"]
    # every incompatible entry still carries its own real classification
    for entry in partitioned["incompatible"]:
        assert entry["compatibility"] in BOUND_COMPATIBILITY_VALUES
        assert entry["can_prove_ineffective"] is False


def test_filter_preserves_candidate_order_within_each_partition():
    candidates = [
        {"kind": "a", "trigger_latency": 100.0},
        {"kind": "b", "trigger_latency": 50.0},
        {"kind": "c", "trigger_latency": 80.0},
    ]
    partitioned = filter_bound_compatible_candidates(candidates, observation_bound=90.0)
    assert [c["kind"] for c in partitioned["compatible"]] == ["b", "c"]
    assert [c["kind"] for c in partitioned["incompatible"]] == ["a"]


def test_filter_empty_candidate_list_returns_empty_partitions():
    partitioned = filter_bound_compatible_candidates([], observation_bound=1000.0)
    assert partitioned == {"compatible": [], "incompatible": []}


# ---------------------------------------------------------------------------
# recommend_evidence_grounded_bound()
# ---------------------------------------------------------------------------

def test_recommend_bound_with_no_cap_proposes_trigger_latency_plus_margin():
    result = recommend_evidence_grounded_bound(trigger_latency=500.0, margin=50.0)
    assert result["status"] == RECOMMENDED_BOUND_WITHIN_POLICY
    assert result["recommended_bound"] == 550.0


def test_recommend_bound_within_a_sufficient_cap_is_uncapped():
    result = recommend_evidence_grounded_bound(trigger_latency=500.0, safety_resource_cap=1000.0)
    assert result["status"] == RECOMMENDED_BOUND_WITHIN_POLICY
    assert result["recommended_bound"] == 500.0


def test_recommend_bound_never_silently_shrinks_below_trigger_latency_when_capped():
    # A cap shorter than T must be reported, never silently returned as if
    # it were an evidence-grounded recommendation.
    result = recommend_evidence_grounded_bound(trigger_latency=500.0, safety_resource_cap=300.0)
    assert result["status"] == BOUND_CAPPED_BELOW_TRIGGER_LATENCY
    assert result["recommended_bound"] == 300.0  # the cap itself, not a fabricated compatible value
    assert "escalate" in result["reason"].lower()


def test_recommend_bound_cap_exactly_equal_to_requirement_is_within_policy():
    result = recommend_evidence_grounded_bound(trigger_latency=500.0, safety_resource_cap=500.0)
    assert result["status"] == RECOMMENDED_BOUND_WITHIN_POLICY
    assert result["recommended_bound"] == 500.0


def test_recommend_bound_unknown_trigger_latency_recommends_nothing():
    result = recommend_evidence_grounded_bound(trigger_latency=None, safety_resource_cap=1000.0)
    assert result["status"] == TRIGGER_LATENCY_UNKNOWN
    assert result["recommended_bound"] is None


def test_recommend_bound_and_classify_are_consistent_round_trip():
    # A bound recommend_evidence_grounded_bound() proposes when uncapped
    # must itself classify as BOUND_COMPATIBLE.
    recommendation = recommend_evidence_grounded_bound(trigger_latency=750.0, margin=25.0)
    assert recommendation["status"] == RECOMMENDED_BOUND_WITHIN_POLICY
    check = classify_diagnostic_bound_compatibility(
        trigger_latency=750.0, observation_bound=recommendation["recommended_bound"], margin=25.0
    )
    assert check["compatibility"] == BOUND_COMPATIBLE
    assert check["can_prove_ineffective"] is True
