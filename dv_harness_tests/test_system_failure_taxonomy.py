"""Tests for dv_harness/system_failure_taxonomy.py.

Covers all three mechanisms: (a) the 14-value SYSTEM-INTEGRATION failure
taxonomy classifier, (b) root-cause boundary localization over a per-subsystem
I/O correctness map, and (c) the 6-value system coverage-hole taxonomy. Every
positive-path test is paired with real negative controls proving the honest
UNCLASSIFIED/UNDETERMINED fallbacks actually fire rather than a forced guess.
"""
import pytest

from dv_harness.system_failure_taxonomy import (
    BoundaryLocalization,
    COVERAGE_HOLE_CATEGORIES,
    COVERAGE_HOLE_CLASSIFICATION_ORDER,
    CoverageHoleClassification,
    CLASSIFICATION_ORDER,
    FAILURE_CATEGORIES,
    SystemIntegrationFailureClassification,
    UNCLASSIFIED,
    UNCLASSIFIED_COVERAGE_HOLE,
    assert_disjoint_from_command_error_taxonomy,
    assert_disjoint_from_loop_budget_failure_type,
    assert_disjoint_from_verification_verdict_vocabulary,
    classify_system_coverage_hole,
    classify_system_integration_failure,
    localize_failure_boundary,
)


# ---------------------------------------------------------------------------
# Vocabulary shape / disjointness
# ---------------------------------------------------------------------------

def test_fourteen_failure_categories_declared():
    assert len(FAILURE_CATEGORIES) == 14
    assert len(set(FAILURE_CATEGORIES)) == 14
    assert UNCLASSIFIED not in FAILURE_CATEGORIES


def test_classification_order_matches_categories():
    assert set(CLASSIFICATION_ORDER) == set(FAILURE_CATEGORIES)
    assert len(CLASSIFICATION_ORDER) == 14


def test_six_coverage_hole_categories_declared():
    assert len(COVERAGE_HOLE_CATEGORIES) == 6
    assert len(set(COVERAGE_HOLE_CATEGORIES)) == 6
    assert UNCLASSIFIED_COVERAGE_HOLE not in COVERAGE_HOLE_CATEGORIES
    assert set(COVERAGE_HOLE_CLASSIFICATION_ORDER) == set(COVERAGE_HOLE_CATEGORIES)


def test_disjoint_guards_pass_cleanly():
    # These already ran at import time; re-running them proves they are callable
    # and still pass (a regression here would mean this file's own vocabulary
    # collided with one of the two literal transcriptions or with models.Status).
    assert_disjoint_from_command_error_taxonomy()
    assert_disjoint_from_loop_budget_failure_type()
    assert_disjoint_from_verification_verdict_vocabulary()


def test_disjoint_guard_has_real_detection_power():
    import dv_harness.system_failure_taxonomy as m

    original = m.FAILURE_CATEGORIES
    try:
        m.FAILURE_CATEGORIES = original + ("UNKNOWN_COMMAND",)  # a real command_error_taxonomy value
        with pytest.raises(AssertionError):
            m.assert_disjoint_from_command_error_taxonomy()
    finally:
        m.FAILURE_CATEGORIES = original

    try:
        m.FAILURE_CATEGORIES = original + ("DUT",)  # a real loop_budget.FailureType value
        with pytest.raises(AssertionError):
            m.assert_disjoint_from_loop_budget_failure_type()
    finally:
        m.FAILURE_CATEGORIES = original


# ---------------------------------------------------------------------------
# (a) classify_system_integration_failure -- one positive test per category
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected_category",
    [
        (
            "System build FAILED: address map disagreement -- base address 0x1000 "
            "overlaps declared region for subsystem usb0",
            "ADDRESS_MAP_FAILURE",
        ),
        (
            "Elaboration error: clock domain crossing violation between core_clk "
            "and phy_clk, CDC violation reported by lint",
            "CLOCK_RESET_FAILURE",
        ),
        (
            "Connectivity check found two active VIP agents drive the same port: "
            "duplicate active VIP instance on chip.core.usb0",
            "VIP_DEDUP_FAILURE",
        ),
        (
            "Monitor at subsystem eth0 reports a transaction was misrouted -- "
            "delivered to the wrong destination port",
            "ROUTING_FAILURE",
        ),
        (
            "Shared resource contention: arbitration failure on the AXI fabric, "
            "deadlock detected between two masters",
            "RESOURCE_CONTENTION_FAILURE",
        ),
        (
            "System merge aborted: command name collision -- command.txt merge "
            "reports incompatible command CPUWRITE1B across two subsystems",
            "COMMAND_COMPATIBILITY_FAILURE",
        ),
        (
            "system_build_proof: duplicate module declaration 'tb_top' across "
            "usb_env and pcie_env, merge collision",
            "BUILD_COMPOSITION_FAILURE",
        ),
        (
            "End-to-end scoreboard mismatch reported across the composed system "
            "scoreboard after subsystem A completed its own transfer",
            "SCOREBOARD_COMPOSITION_FAILURE",
        ),
        (
            "Root-cause note: the DUT error was not propagated across the "
            "subsystem boundary and was masked by the wrapper logic",
            "ERROR_PROPAGATION_FAILURE",
        ),
        (
            "Static timing report: a setup violation was found on the cross-"
            "subsystem handoff register, plus a suspected race condition",
            "TIMING_FAILURE",
        ),
        (
            "Configuration mismatch across subsystem boundaries: incompatible "
            "configuration between usb0's declared mode and pcie0's",
            "CONFIGURATION_FAILURE",
        ),
        (
            "After the injected fault, the system failed to recover -- recovery "
            "path did not complete within the expected window",
            "RECOVERY_FAILURE",
        ),
        (
            "Integration test failure: subsystems disagree about the shared "
            "control-plane state after the composed run",
            "INTEGRATION_FAILURE",
        ),
        (
            "subsystem usb0 failed internally, isolated failure confined to that "
            "subsystem's own internal check",
            "SUBSYSTEM_FAILURE",
        ),
    ],
)
def test_each_category_has_a_real_positive_match(text, expected_category):
    result = classify_system_integration_failure(text)
    assert isinstance(result, SystemIntegrationFailureClassification)
    assert result.category == expected_category
    assert result.matched_evidence
    assert result.matched_evidence.lower() in text.lower()


def test_unclassified_when_no_rule_matches():
    result = classify_system_integration_failure("The regression completed with no anomalies noted.")
    assert result.category == UNCLASSIFIED
    assert result.matched_evidence == ""
    assert result.rule_id == "no_rule_matched"


def test_unclassified_on_empty_text():
    result = classify_system_integration_failure("   ")
    assert result.category == UNCLASSIFIED
    assert result.rule_id == "empty_text"


def test_classify_rejects_none():
    with pytest.raises(ValueError):
        classify_system_integration_failure(None)


def test_classify_rejects_non_string():
    with pytest.raises(ValueError):
        classify_system_integration_failure(12345)  # type: ignore[arg-type]


def test_matched_line_reported_for_multiline_text():
    text = "line one is fine\nline two is fine too\nsetup violation found on the handoff register\nline four"
    result = classify_system_integration_failure(text)
    assert result.category == "TIMING_FAILURE"
    assert result.matched_line == 3


def test_priority_address_map_before_generic_integration():
    # Text carries BOTH an address-map marker and a generic cross-subsystem
    # integration marker -- the more structurally specific ADDRESS_MAP_FAILURE
    # must win, proving CLASSIFICATION_ORDER is actually honoured rather than
    # merely documented.
    text = (
        "Integration test failure: subsystems disagree, and separately the "
        "address map disagreement was traced to an overlapping address region"
    )
    result = classify_system_integration_failure(text)
    assert result.category == "ADDRESS_MAP_FAILURE"


def test_priority_resource_contention_before_generic_integration():
    text = (
        "Integration test failure: subsystems disagree about ownership; "
        "arbitration failure and deadlock detected on the shared bus"
    )
    result = classify_system_integration_failure(text)
    assert result.category == "RESOURCE_CONTENTION_FAILURE"


def test_to_dict_shape():
    result = classify_system_integration_failure("deadlock detected on shared resource")
    d = result.to_dict()
    assert set(d) == {"category", "matched_evidence", "rule_id", "matched_line"}
    assert d["category"] == "RESOURCE_CONTENTION_FAILURE"


# ---------------------------------------------------------------------------
# (b) localize_failure_boundary
# ---------------------------------------------------------------------------

def test_single_narrowed_candidate():
    io_map = {
        "usb0": {"input_status": "CORRECT", "output_status": "CORRECT"},
        "bridge0": {"input_status": "CORRECT", "output_status": "INCORRECT"},
        "pcie0": {"input_status": "INCORRECT", "output_status": "INCORRECT"},
    }
    result = localize_failure_boundary(io_map)
    assert isinstance(result, BoundaryLocalization)
    assert result.status == "NARROWED"
    assert result.boundary == "bridge0"
    assert result.candidates == ["bridge0"]
    assert "bridge0" in result.reason


def test_bool_shaped_input_accepted():
    io_map = {
        "a": {"input_correct": True, "output_correct": False},
        "b": {"input_correct": True, "output_correct": True},
    }
    result = localize_failure_boundary(io_map)
    assert result.status == "NARROWED"
    assert result.boundary == "a"


def test_zero_candidates_no_unknown_reports_undetermined():
    io_map = {
        "a": {"input_status": "CORRECT", "output_status": "CORRECT"},
        "b": {"input_status": "INCORRECT", "output_status": "INCORRECT"},
    }
    result = localize_failure_boundary(io_map)
    assert result.status == "UNDETERMINED"
    assert result.boundary is None
    assert result.candidates == []
    assert "does not localize" in result.reason


def test_zero_candidates_but_unknown_present_names_it():
    io_map = {
        "a": {"input_status": "CORRECT", "output_status": "CORRECT"},
        "b": {"input_status": "UNKNOWN", "output_status": "UNKNOWN"},
    }
    result = localize_failure_boundary(io_map)
    assert result.status == "UNDETERMINED"
    assert result.boundary is None
    assert "b" in result.reason
    assert "UNKNOWN" in result.reason


def test_multiple_independent_candidates_undetermined():
    io_map = {
        "a": {"input_status": "CORRECT", "output_status": "INCORRECT"},
        "b": {"input_status": "CORRECT", "output_status": "INCORRECT"},
        "c": {"input_status": "CORRECT", "output_status": "CORRECT"},
    }
    result = localize_failure_boundary(io_map)
    assert result.status == "UNDETERMINED"
    assert result.boundary is None
    assert result.candidates == ["a", "b"]


def test_contradictory_evidence_across_declared_connection_is_undetermined():
    io_map = {
        "upstream": {"input_status": "CORRECT", "output_status": "CORRECT"},
        "downstream": {"input_status": "INCORRECT", "output_status": "INCORRECT"},
    }
    connections = [{"upstream": "upstream", "downstream": "downstream"}]
    result = localize_failure_boundary(io_map, connections=connections)
    assert result.status == "UNDETERMINED"
    assert result.boundary is None
    assert "contradictory" in result.reason.lower()
    assert "upstream" in result.candidates and "downstream" in result.candidates


def test_connection_naming_unknown_subsystem_is_ignored_not_assumed():
    io_map = {
        "a": {"input_status": "CORRECT", "output_status": "INCORRECT"},
    }
    connections = [("a", "ghost_subsystem_not_in_map")]
    result = localize_failure_boundary(io_map, connections=connections)
    # The unresolvable connection contributes nothing; the real single candidate
    # still narrows cleanly.
    assert result.status == "NARROWED"
    assert result.boundary == "a"


def test_tuple_shaped_connection_accepted():
    io_map = {
        "upstream": {"input_status": "CORRECT", "output_status": "CORRECT"},
        "downstream": {"input_status": "INCORRECT", "output_status": "INCORRECT"},
    }
    result = localize_failure_boundary(io_map, connections=[("upstream", "downstream")])
    assert result.status == "UNDETERMINED"


def test_empty_map_raises():
    with pytest.raises(ValueError):
        localize_failure_boundary({})


def test_non_dict_map_raises():
    with pytest.raises(ValueError):
        localize_failure_boundary(["not", "a", "dict"])  # type: ignore[arg-type]


def test_bad_status_string_raises():
    with pytest.raises(ValueError):
        localize_failure_boundary({"a": {"input_status": "MAYBE", "output_status": "CORRECT"}})


def test_missing_io_fields_raises():
    with pytest.raises(ValueError):
        localize_failure_boundary({"a": {"unrelated_field": True}})


def test_both_shapes_declared_raises():
    with pytest.raises(ValueError):
        localize_failure_boundary(
            {"a": {"input_status": "CORRECT", "input_correct": True, "output_status": "CORRECT"}}
        )


def test_bad_connection_edge_shape_raises():
    io_map = {"a": {"input_status": "CORRECT", "output_status": "INCORRECT"}}
    with pytest.raises(ValueError):
        localize_failure_boundary(io_map, connections=["not-a-valid-edge"])  # type: ignore[list-item]


def test_boundary_localization_to_dict_shape():
    io_map = {"a": {"input_status": "CORRECT", "output_status": "INCORRECT"}}
    result = localize_failure_boundary(io_map)
    d = result.to_dict()
    assert set(d) == {"status", "boundary", "candidates", "reason", "evidence"}
    assert d["evidence"]["a"] == {"input": "CORRECT", "output": "INCORRECT"}


# ---------------------------------------------------------------------------
# (c) classify_system_coverage_hole -- one positive test per category
# ---------------------------------------------------------------------------

def test_coverage_model_gap():
    result = classify_system_coverage_hole({"coverage_model_missing": True})
    assert isinstance(result, CoverageHoleClassification)
    assert result.category == "COVERAGE_MODEL_GAP"
    assert result.matched_field == "coverage_model_missing"


def test_resource_gap():
    result = classify_system_coverage_hole({"involves_shared_resource": True})
    assert result.category == "RESOURCE_GAP"


def test_error_path_gap():
    result = classify_system_coverage_hole({"involves_error_path": True})
    assert result.category == "ERROR_PATH_GAP"


def test_integration_gap_via_scope():
    result = classify_system_coverage_hole({"scope": "cross_subsystem"})
    assert result.category == "INTEGRATION_GAP"


def test_integration_gap_via_subsystem_ids_list():
    result = classify_system_coverage_hole({"subsystem_ids": ["usb0", "pcie0"]})
    assert result.category == "INTEGRATION_GAP"


def test_subsystem_gap_via_scope():
    result = classify_system_coverage_hole({"scope": "single_subsystem", "subsystem_id": "usb0"})
    assert result.category == "SUBSYSTEM_GAP"


def test_subsystem_gap_via_bare_subsystem_id():
    result = classify_system_coverage_hole({"subsystem_id": "usb0"})
    assert result.category == "SUBSYSTEM_GAP"


def test_subsystem_gap_via_single_element_list():
    result = classify_system_coverage_hole({"subsystem_ids": ["usb0"]})
    assert result.category == "SUBSYSTEM_GAP"


def test_scenario_gap():
    result = classify_system_coverage_hole({"scenario_category_missing": True})
    assert result.category == "SCENARIO_GAP"


def test_unclassified_coverage_hole_on_no_recognised_field():
    result = classify_system_coverage_hole({"some_other_field": "irrelevant"})
    assert result.category == UNCLASSIFIED_COVERAGE_HOLE
    assert result.matched_field is None


def test_unclassified_coverage_hole_on_empty_dict():
    result = classify_system_coverage_hole({})
    assert result.category == UNCLASSIFIED_COVERAGE_HOLE


def test_coverage_model_gap_outranks_resource_gap():
    result = classify_system_coverage_hole(
        {"coverage_model_missing": True, "involves_shared_resource": True}
    )
    assert result.category == "COVERAGE_MODEL_GAP"


def test_integration_gap_outranks_subsystem_gap_on_conflicting_declaration():
    # scope says cross_subsystem but a single subsystem_id is also present --
    # the ordering resolves toward the broader INTEGRATION_GAP reading rather
    # than the narrower SUBSYSTEM_GAP one.
    result = classify_system_coverage_hole({"scope": "cross_subsystem", "subsystem_id": "usb0"})
    assert result.category == "INTEGRATION_GAP"


def test_classify_coverage_hole_rejects_none():
    with pytest.raises(ValueError):
        classify_system_coverage_hole(None)  # type: ignore[arg-type]


def test_classify_coverage_hole_rejects_non_dict():
    with pytest.raises(ValueError):
        classify_system_coverage_hole(["not", "a", "dict"])  # type: ignore[arg-type]


def test_coverage_hole_to_dict_shape():
    result = classify_system_coverage_hole({"scenario_category_missing": True})
    d = result.to_dict()
    assert set(d) == {"category", "matched_field", "reason"}
    assert d["category"] == "SCENARIO_GAP"
