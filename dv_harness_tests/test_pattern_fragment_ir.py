"""Tests for dv_harness/pattern_fragment_ir.py.

Covers: the core positive path (a real pattern-shaped command list, a
declared sub-range extracted into a PatternFragmentIR with correctly
derived resources_used/produced_events/consumed_events/preconditions/
postconditions), the marker-based selection path, the fragment-chain
readiness composition helper, plus negative controls that must raise an
honest `PatternFragmentIrError` or report a distinct NOT_AVAILABLE/whole-
source status -- never a silent guess -- per this repo's Evidence Truth
Rule.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dv_harness import pattern_fragment_ir as pfi


# ===========================================================================
# Fixtures: a real, small pattern-shaped command list
# ===========================================================================

def _real_pattern_source():
    """A real, small command.txt-shaped pattern: a global prologue, a
    reusable PHY-bringup portion (the fragment under test), and a trailing
    verdict command -- so the fragment tests cut a genuine PORTION, not the
    whole pattern."""
    return {
        "pattern_id": "USB3_PORT_ENUM_BASE",
        "commands": [
            {"text": "STAGE0_WAIT_BRIDGE_READY", "produces_event": "BRIDGE_READY"},
            {
                "text": "PORT0_PHY_BRINGUP",
                "resource": "phy_agent0",
                "consumes_event": "BRIDGE_READY",
                "produces_event": "PHY0_LINK_UP",
            },
            {
                "text": "PORT0_HOST_ENUM_SEQ",
                "resources": ["usb_host_agent0"],
                "consumes_event": "PHY0_LINK_UP",
                "produces_event": "PORT0_ENUM_DONE",
            },
            {"text": "FINAL_CHECK_PORT0_ENUM_DONE", "consumes_event": "PORT0_ENUM_DONE"},
        ],
    }


# ===========================================================================
# Positive path: explicit index range, a genuine portion
# ===========================================================================

def test_positive_path_explicit_range_extracts_portion_with_derived_conditions():
    src = _real_pattern_source()

    frag = pfi.extract_pattern_fragment(src, fragment_range=(1, 3))

    assert frag.source_pattern_id == "USB3_PORT_ENUM_BASE"
    assert frag.selection_status == pfi.SELECTION_EXPLICIT_RANGE
    assert frag.covers_entire_source is False
    assert frag.source_command_count == 4
    assert frag.fragment_command_count == 2
    assert frag.status == pfi.STATUS_COMPLETE

    assert frag.resources_used == ["phy_agent0", "usb_host_agent0"]
    assert frag.resource_evidence_status == pfi.EVIDENCE_DERIVED

    assert frag.produced_events == ["PHY0_LINK_UP", "PORT0_ENUM_DONE"]
    assert frag.consumed_events == ["BRIDGE_READY", "PHY0_LINK_UP"]
    assert frag.event_evidence_status == pfi.EVIDENCE_DERIVED

    # BRIDGE_READY is consumed but not produced within this fragment -> precondition
    precond_events = {p["event"] for p in frag.preconditions}
    assert precond_events == {"BRIDGE_READY"}
    assert frag.preconditions[0]["source"] == pfi.COND_SOURCE_DERIVED_UNRESOLVED_CONSUMED

    # PORT0_ENUM_DONE is produced but not consumed within this fragment -> postcondition
    # (PHY0_LINK_UP is both produced and consumed inside the fragment, so it is internal)
    postcond_events = {p["event"] for p in frag.postconditions}
    assert postcond_events == {"PORT0_ENUM_DONE"}
    assert frag.postconditions[0]["source"] == pfi.COND_SOURCE_DERIVED_UNCONSUMED_PRODUCED


def test_declared_preconditions_and_postconditions_are_kept_and_tagged():
    src = _real_pattern_source()

    frag = pfi.extract_pattern_fragment(
        src,
        fragment_range=(1, 3),
        declared_preconditions=["RESET_DEASSERTED"],
        declared_postconditions=[{"event": "PORT0_LINK_TRAINED"}],
    )

    declared_pre = [p for p in frag.preconditions if p["source"] == pfi.COND_SOURCE_DECLARED]
    declared_post = [p for p in frag.postconditions if p["source"] == pfi.COND_SOURCE_DECLARED]
    assert declared_pre == [{"event": "RESET_DEASSERTED", "source": pfi.COND_SOURCE_DECLARED}]
    assert declared_post == [{"event": "PORT0_LINK_TRAINED", "source": pfi.COND_SOURCE_DECLARED}]
    # derived facts are still present alongside the declared ones
    assert any(p["source"] == pfi.COND_SOURCE_DERIVED_UNRESOLVED_CONSUMED for p in frag.preconditions)


def test_marker_based_selection_matches_explicit_range():
    src = _real_pattern_source()

    frag = pfi.extract_pattern_fragment(
        src, start_marker="PORT0_PHY_BRINGUP", end_marker="PORT0_HOST_ENUM_SEQ"
    )

    assert frag.selection_status == pfi.SELECTION_MARKER_RANGE
    assert frag.fragment_command_count == 2
    assert frag.resources_used == ["phy_agent0", "usb_host_agent0"]


def test_whole_source_used_when_no_selection_declared_is_honestly_flagged():
    src = _real_pattern_source()

    frag = pfi.extract_pattern_fragment(src)

    assert frag.selection_status == pfi.SELECTION_WHOLE_SOURCE
    assert frag.covers_entire_source is True
    assert frag.fragment_command_count == frag.source_command_count == 4


def test_no_event_fields_reports_not_available_not_computed_empty():
    src = {
        "pattern_id": "NO_EVENT_PATTERN",
        "commands": [
            {"text": "STEP_A", "resource": "agentX"},
            {"text": "STEP_B", "resource": "agentY"},
        ],
    }

    frag = pfi.extract_pattern_fragment(src, fragment_range=(0, 2))

    assert frag.produced_events == []
    assert frag.consumed_events == []
    assert frag.event_evidence_status == pfi.EVIDENCE_NOT_AVAILABLE
    # resources ARE declared here, so that evidence status differs
    assert frag.resource_evidence_status == pfi.EVIDENCE_DERIVED


def test_unclassified_command_without_text_downgrades_status():
    src = {
        "pattern_id": "P",
        "commands": [
            {"text": "STEP_A"},
            {"resource": "agentZ"},  # no text field at all
        ],
    }

    frag = pfi.extract_pattern_fragment(src, fragment_range=(0, 2))

    assert len(frag.unclassified_commands) == 1
    assert frag.status == pfi.STATUS_PARTIAL_TEXT_EVIDENCE


# ===========================================================================
# Negative controls
# ===========================================================================

def test_negative_source_without_commands_list_raises():
    try:
        pfi.extract_pattern_fragment({"pattern_id": "X", "commands": "not-a-list"})
        assert False, "expected PatternFragmentIrError"
    except pfi.PatternFragmentIrError as exc:
        assert exc.reason == "SOURCE_COMMANDS_NOT_LIST"


def test_negative_invalid_fragment_range_start_ge_end_raises():
    src = _real_pattern_source()
    try:
        pfi.extract_pattern_fragment(src, fragment_range=(3, 1))
        assert False, "expected PatternFragmentIrError"
    except pfi.PatternFragmentIrError as exc:
        assert exc.reason == "INVALID_FRAGMENT_RANGE"


def test_negative_fragment_range_out_of_bounds_raises():
    src = _real_pattern_source()
    try:
        pfi.extract_pattern_fragment(src, fragment_range=(0, 99))
        assert False, "expected PatternFragmentIrError"
    except pfi.PatternFragmentIrError as exc:
        assert exc.reason == "INVALID_FRAGMENT_RANGE"


def test_negative_marker_pair_incomplete_raises():
    src = _real_pattern_source()
    try:
        pfi.extract_pattern_fragment(src, start_marker="PORT0_PHY_BRINGUP")
        assert False, "expected PatternFragmentIrError"
    except pfi.PatternFragmentIrError as exc:
        assert exc.reason == "MARKER_PAIR_INCOMPLETE"


def test_negative_start_marker_not_found_raises():
    src = _real_pattern_source()
    try:
        pfi.extract_pattern_fragment(
            src, start_marker="DOES_NOT_EXIST", end_marker="PORT0_HOST_ENUM_SEQ"
        )
        assert False, "expected PatternFragmentIrError"
    except pfi.PatternFragmentIrError as exc:
        assert exc.reason == "START_MARKER_NOT_FOUND"


def test_negative_end_marker_not_found_raises():
    src = _real_pattern_source()
    try:
        pfi.extract_pattern_fragment(
            src, start_marker="PORT0_PHY_BRINGUP", end_marker="DOES_NOT_EXIST"
        )
        assert False, "expected PatternFragmentIrError"
    except pfi.PatternFragmentIrError as exc:
        assert exc.reason == "END_MARKER_NOT_FOUND"


# ===========================================================================
# Fragment-chain readiness (composition-facing)
# ===========================================================================

def _fragments_for_chain():
    src = _real_pattern_source()
    bringup = pfi.extract_pattern_fragment(
        src, fragment_range=(0, 2), fragment_id="F_BRINGUP"
    )
    enum = pfi.extract_pattern_fragment(
        src, fragment_range=(2, 4), fragment_id="F_ENUM"
    )
    return bringup, enum


def test_chain_readiness_all_covered_in_correct_order():
    bringup, enum = _fragments_for_chain()

    results = pfi.check_fragment_chain_readiness([bringup, enum])

    by_id = {r["fragment_id"]: r for r in results}
    assert by_id["F_BRINGUP"]["chain_status"] == pfi.CHAIN_STATUS_NO_PRECONDITIONS
    assert by_id["F_ENUM"]["chain_status"] == pfi.CHAIN_STATUS_ALL_COVERED


def test_chain_readiness_uncovered_when_producer_missing():
    _, enum = _fragments_for_chain()

    results = pfi.check_fragment_chain_readiness([enum])

    assert results[0]["chain_status"] == pfi.CHAIN_STATUS_HAS_UNCOVERED
    assert results[0]["precondition_status"][0]["status"] == pfi.CHAIN_UNCOVERED


def test_negative_chain_readiness_empty_list_raises():
    try:
        pfi.check_fragment_chain_readiness([])
        assert False, "expected PatternFragmentIrError"
    except pfi.PatternFragmentIrError as exc:
        assert exc.reason == "EMPTY_FRAGMENT_LIST"


def test_negative_chain_readiness_order_mismatch_raises():
    bringup, enum = _fragments_for_chain()
    try:
        pfi.check_fragment_chain_readiness([bringup, enum], order=["F_BRINGUP", "F_UNKNOWN"])
        assert False, "expected PatternFragmentIrError"
    except pfi.PatternFragmentIrError as exc:
        assert exc.reason == "ORDER_MISMATCH"
