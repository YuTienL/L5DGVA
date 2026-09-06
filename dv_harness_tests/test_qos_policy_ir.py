"""Tests for dv_harness/qos_policy_ir.py.

Core positive path (build a policy, derive an ordering from real declared priorities,
verify a clean contention window) plus real negative controls: missing evidence,
missing master_id, duplicate master_id, invalid priority/weight types, an unrecognized
priority convention, insufficient-data ordering derivation, a real ordering violation,
tied-priority masters never flagged against each other, unknown masters never forced
into a comparison, and malformed transaction records.
"""
import pytest

from dv_harness.qos_policy_ir import (
    CONTENTION_UNKNOWN,
    CONTENTION_VERIFIED,
    CONTENTION_VIOLATED,
    ENTRY_STATUS_DECLARED,
    ENTRY_STATUS_NO_QOS_FACTS,
    ORDERING_STATUS_DERIVED,
    ORDERING_STATUS_NOT_AVAILABLE,
    PRIORITY_CONVENTION_HIGHER_IS_HIGHER,
    PRIORITY_CONVENTION_LOWER_IS_HIGHER,
    QoSPolicyIRError,
    build_qos_policy_ir,
    derive_priority_ordering,
    verify_qos_contention,
)


# ===========================================================================
# build_qos_policy_ir -- positive path
# ===========================================================================

def test_build_qos_policy_ir_positive_path():
    policy = build_qos_policy_ir(
        [
            {"master_id": "M_CPU", "qos_level": "HIGH", "priority": 3,
             "evidence": "soc_spec.md:120 QoS table row 1"},
            {"master_id": "M_DMA", "qos_level": "MEDIUM", "priority": 2,
             "evidence": "soc_spec.md:121 QoS table row 2"},
            {"master_id": "M_DISPLAY", "qos_level": "LOW", "priority": 1,
             "weight": 0.5, "evidence": "soc_spec.md:122 QoS table row 3"},
        ],
        priority_convention=PRIORITY_CONVENTION_HIGHER_IS_HIGHER,
    )
    assert set(policy.entries) == {"M_CPU", "M_DMA", "M_DISPLAY"}
    assert policy.entries["M_CPU"].status == ENTRY_STATUS_DECLARED
    assert policy.entries["M_CPU"].qos_level == "HIGH"
    assert policy.entries["M_DISPLAY"].weight == 0.5
    assert policy.masters_without_qos_facts() == []
    d = policy.to_dict()
    assert d["priority_convention"] == PRIORITY_CONVENTION_HIGHER_IS_HIGHER
    assert "M_CPU" in d["entries"]


def test_entry_with_no_qos_facts_is_an_honest_absence_not_an_error():
    policy = build_qos_policy_ir([
        {"master_id": "M_UNKNOWN_TIER", "evidence": "spec.md:5 named but no tier assigned yet"},
    ])
    assert policy.entries["M_UNKNOWN_TIER"].status == ENTRY_STATUS_NO_QOS_FACTS
    assert policy.masters_without_qos_facts() == ["M_UNKNOWN_TIER"]


# ===========================================================================
# build_qos_policy_ir -- negative controls
# ===========================================================================

def test_missing_master_id_raises():
    with pytest.raises(QoSPolicyIRError) as exc:
        build_qos_policy_ir([{"evidence": "spec.md:1"}])
    assert exc.value.code == "QOS_ENTRY_MISSING_MASTER_ID"


def test_missing_evidence_raises():
    with pytest.raises(QoSPolicyIRError) as exc:
        build_qos_policy_ir([{"master_id": "M0", "priority": 1}])
    assert exc.value.code == "QOS_ENTRY_MISSING_EVIDENCE"


def test_blank_evidence_raises():
    with pytest.raises(QoSPolicyIRError) as exc:
        build_qos_policy_ir([{"master_id": "M0", "priority": 1, "evidence": "   "}])
    assert exc.value.code == "QOS_ENTRY_MISSING_EVIDENCE"


def test_duplicate_master_id_raises():
    with pytest.raises(QoSPolicyIRError) as exc:
        build_qos_policy_ir([
            {"master_id": "M0", "priority": 1, "evidence": "spec.md:1"},
            {"master_id": "M0", "priority": 2, "evidence": "spec.md:2"},
        ])
    assert exc.value.code == "DUPLICATE_MASTER_ID"


def test_invalid_priority_type_raises():
    with pytest.raises(QoSPolicyIRError) as exc:
        build_qos_policy_ir([{"master_id": "M0", "priority": "high", "evidence": "spec.md:1"}])
    assert exc.value.code == "INVALID_PRIORITY_TYPE"


def test_bool_priority_rejected():
    with pytest.raises(QoSPolicyIRError) as exc:
        build_qos_policy_ir([{"master_id": "M0", "priority": True, "evidence": "spec.md:1"}])
    assert exc.value.code == "INVALID_PRIORITY_TYPE"


def test_invalid_weight_type_raises():
    with pytest.raises(QoSPolicyIRError) as exc:
        build_qos_policy_ir([{"master_id": "M0", "weight": "big", "evidence": "spec.md:1"}])
    assert exc.value.code == "INVALID_WEIGHT_TYPE"


def test_unrecognized_priority_convention_raises():
    with pytest.raises(QoSPolicyIRError) as exc:
        build_qos_policy_ir([], priority_convention="BIGGER_NUMBER_WINS")
    assert exc.value.code == "UNRECOGNIZED_PRIORITY_CONVENTION"


# ===========================================================================
# derive_priority_ordering
# ===========================================================================

def test_derive_priority_ordering_positive():
    policy = build_qos_policy_ir(
        [
            {"master_id": "M_HI", "priority": 10, "evidence": "spec.md:1"},
            {"master_id": "M_MID", "priority": 5, "evidence": "spec.md:2"},
            {"master_id": "M_LOW", "priority": 1, "evidence": "spec.md:3"},
        ],
        priority_convention=PRIORITY_CONVENTION_HIGHER_IS_HIGHER,
    )
    result = derive_priority_ordering(policy)
    assert result["status"] == ORDERING_STATUS_DERIVED
    assert result["ordering"] == [["M_HI"], ["M_MID"], ["M_LOW"]]


def test_derive_priority_ordering_lower_is_higher_convention_reverses_order():
    policy = build_qos_policy_ir(
        [
            {"master_id": "M_A", "priority": 0, "evidence": "spec.md:1"},
            {"master_id": "M_B", "priority": 3, "evidence": "spec.md:2"},
        ],
        priority_convention=PRIORITY_CONVENTION_LOWER_IS_HIGHER,
    )
    result = derive_priority_ordering(policy)
    assert result["ordering"] == [["M_A"], ["M_B"]]


def test_derive_priority_ordering_groups_ties():
    policy = build_qos_policy_ir(
        [
            {"master_id": "M_A", "priority": 5, "evidence": "spec.md:1"},
            {"master_id": "M_B", "priority": 5, "evidence": "spec.md:2"},
            {"master_id": "M_C", "priority": 1, "evidence": "spec.md:3"},
        ],
        priority_convention=PRIORITY_CONVENTION_HIGHER_IS_HIGHER,
    )
    result = derive_priority_ordering(policy)
    assert result["ordering"] == [["M_A", "M_B"], ["M_C"]]


def test_derive_priority_ordering_not_available_without_declared_convention():
    policy = build_qos_policy_ir([
        {"master_id": "M_A", "priority": 5, "evidence": "spec.md:1"},
        {"master_id": "M_B", "priority": 1, "evidence": "spec.md:2"},
    ])
    result = derive_priority_ordering(policy)
    assert result["status"] == ORDERING_STATUS_NOT_AVAILABLE
    assert result["ordering"] is None
    assert "priority_convention" in result["reason"]


def test_derive_priority_ordering_not_available_with_fewer_than_two_priorities():
    policy = build_qos_policy_ir(
        [{"master_id": "M_A", "priority": 5, "evidence": "spec.md:1"},
         {"master_id": "M_B", "qos_level": "LOW", "evidence": "spec.md:2"}],
        priority_convention=PRIORITY_CONVENTION_HIGHER_IS_HIGHER,
    )
    result = derive_priority_ordering(policy)
    assert result["status"] == ORDERING_STATUS_NOT_AVAILABLE
    assert result["excluded_no_priority"] == ["M_B"]


# ===========================================================================
# verify_qos_contention -- positive path
# ===========================================================================

def test_verify_qos_contention_verified_when_ordering_observed():
    ordering = ["M_HI", "M_MID", "M_LOW"]
    transactions = [
        {"master_id": "M_HI", "position": 1, "window_id": "w1"},
        {"master_id": "M_MID", "position": 2, "window_id": "w1"},
        {"master_id": "M_LOW", "position": 3, "window_id": "w1"},
    ]
    report = verify_qos_contention(ordering, transactions)
    assert report["verdict"] == CONTENTION_VERIFIED
    assert report["windows"][0]["violations"] == []


def test_verify_qos_contention_violated_when_priority_inverted():
    ordering = ["M_HI", "M_LOW"]
    transactions = [
        {"master_id": "M_LOW", "position": 1, "window_id": "w1"},
        {"master_id": "M_HI", "position": 2, "window_id": "w1"},
    ]
    report = verify_qos_contention(ordering, transactions)
    assert report["verdict"] == CONTENTION_VIOLATED
    window = report["windows"][0]
    assert window["status"] == CONTENTION_VIOLATED
    v = window["violations"][0]
    assert v["higher_priority_master"] == "M_HI"
    assert v["lower_priority_master"] == "M_LOW"


def test_verify_qos_contention_unknown_when_no_real_contention():
    ordering = ["M_HI", "M_LOW"]
    # Only one master ever appears per window -- nothing genuinely contended.
    transactions = [
        {"master_id": "M_HI", "position": 1, "window_id": "w1"},
        {"master_id": "M_HI", "position": 2, "window_id": "w2"},
    ]
    report = verify_qos_contention(ordering, transactions)
    assert report["verdict"] == CONTENTION_UNKNOWN


def test_verify_qos_contention_unknown_with_no_transactions_at_all():
    report = verify_qos_contention(["M_HI", "M_LOW"], [])
    assert report["verdict"] == CONTENTION_UNKNOWN


def test_verify_qos_contention_tied_masters_never_flagged_against_each_other():
    ordering = [["M_A", "M_B"], ["M_C"]]
    transactions = [
        {"master_id": "M_B", "position": 1, "window_id": "w1"},
        {"master_id": "M_A", "position": 2, "window_id": "w1"},  # A after B, but tied -> fine
        {"master_id": "M_C", "position": 3, "window_id": "w1"},
    ]
    report = verify_qos_contention(ordering, transactions)
    assert report["verdict"] == CONTENTION_VERIFIED


def test_verify_qos_contention_unknown_masters_excluded_not_forced_into_comparison():
    ordering = ["M_HI"]
    transactions = [
        {"master_id": "M_HI", "position": 2, "window_id": "w1"},
        {"master_id": "M_MYSTERY", "position": 1, "window_id": "w1"},
    ]
    report = verify_qos_contention(ordering, transactions)
    # M_MYSTERY is not in the declared ordering, so it can never be compared, and only
    # one KNOWN master appears in this window -- nothing to check.
    assert report["verdict"] == CONTENTION_UNKNOWN
    assert report["windows"][0]["unknown_masters"] == ["M_MYSTERY"]


def test_verify_qos_contention_default_window_groups_records_with_no_window_id():
    ordering = ["M_HI", "M_LOW"]
    transactions = [
        {"master_id": "M_LOW", "position": 1},
        {"master_id": "M_HI", "position": 2},
    ]
    report = verify_qos_contention(ordering, transactions)
    assert report["verdict"] == CONTENTION_VIOLATED
    assert len(report["windows"]) == 1


def test_verify_qos_contention_multiple_windows_isolated_from_each_other():
    ordering = ["M_HI", "M_LOW"]
    transactions = [
        # w1: correct ordering
        {"master_id": "M_HI", "position": 1, "window_id": "w1"},
        {"master_id": "M_LOW", "position": 2, "window_id": "w1"},
        # w2: inverted ordering
        {"master_id": "M_LOW", "position": 1, "window_id": "w2"},
        {"master_id": "M_HI", "position": 2, "window_id": "w2"},
    ]
    report = verify_qos_contention(ordering, transactions)
    assert report["verdict"] == CONTENTION_VIOLATED
    by_window = {w["window_id"]: w for w in report["windows"]}
    assert by_window["w1"]["status"] == CONTENTION_VERIFIED
    assert by_window["w2"]["status"] == CONTENTION_VIOLATED


# ===========================================================================
# verify_qos_contention -- negative controls (malformed ordering / records)
# ===========================================================================

def test_empty_ordering_raises():
    with pytest.raises(QoSPolicyIRError) as exc:
        verify_qos_contention([], [{"master_id": "M0", "position": 1}])
    assert exc.value.code == "EMPTY_ORDERING"


def test_duplicate_master_in_ordering_raises():
    with pytest.raises(QoSPolicyIRError) as exc:
        verify_qos_contention(["M0", "M0"], [])
    assert exc.value.code == "DUPLICATE_MASTER_IN_ORDERING"


def test_transaction_record_missing_master_id_raises():
    with pytest.raises(QoSPolicyIRError) as exc:
        verify_qos_contention(["M0"], [{"position": 1}])
    assert exc.value.code == "TRANSACTION_RECORD_MISSING_MASTER_ID"


def test_transaction_record_invalid_position_raises():
    with pytest.raises(QoSPolicyIRError) as exc:
        verify_qos_contention(["M0"], [{"master_id": "M0", "position": "first"}])
    assert exc.value.code == "TRANSACTION_RECORD_INVALID_POSITION"


def test_transaction_record_bool_position_raises():
    with pytest.raises(QoSPolicyIRError) as exc:
        verify_qos_contention(["M0"], [{"master_id": "M0", "position": True}])
    assert exc.value.code == "TRANSACTION_RECORD_INVALID_POSITION"


def test_transaction_record_invalid_window_id_raises():
    with pytest.raises(QoSPolicyIRError) as exc:
        verify_qos_contention(["M0"], [{"master_id": "M0", "position": 1, "window_id": 5}])
    assert exc.value.code == "TRANSACTION_RECORD_INVALID_WINDOW_ID"
