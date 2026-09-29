"""Tests for dv_harness/vplan_artifact.py -- vPlan schema + hierarchy + the
nine-dimension completeness analysis + the fifteen-value gap taxonomy, wired
through the real `inference.next_best_action()`.

No mocks: `vplan_artifact.py` is deliberately generic-dict-input (see its own
module docstring for why -- it must not import the sibling, concurrently
-edited `spec_intelligence.py`/`verification_intent_ir.py`), so the "real
fixture" for this module IS a plain dict/list vPlan document -- exactly the
shape any real producer's output would have to reduce to before this module
could read it. Every test therefore builds real vPlan/requirement/intent
dicts and calls the real `analyze_vplan_completeness()`; nothing here patches
or stubs a function inside the module under test.
"""
from __future__ import annotations

import json

import pytest

from dv_harness import vplan_artifact as va
from dv_harness.vplan_artifact import (
    BLOCKED, DIMENSIONS, GAP_DUPLICATE_ROW_ID, GAP_ORPHAN_PARENT_REF,
    GAP_CYCLIC_HIERARCHY, GAP_UNMAPPED_REQUIREMENT, GAP_DANGLING_REQUIREMENT_REF,
    GAP_MISSING_VERIFICATION_METHOD, GAP_UNKNOWN_VERIFICATION_METHOD,
    GAP_MISSING_COVERAGE_LINK, GAP_MISSING_CHECKER_LINK, GAP_MISSING_TEST_LINK,
    GAP_MISSING_OWNER, GAP_MISSING_PRIORITY, GAP_UNREFERENCED_VERIFICATION_INTENT,
    GAP_DANGLING_INTENT_REF, GAP_INTENT_METHOD_CONTRADICTION, GAP_TAXONOMY,
    PARTIAL, READY, UNKNOWN, VPlanArtifactValidationError,
    analyze_vplan_completeness, build_vplan_hierarchy, render_completeness_matrix_markdown,
    validate_vplan_document, validate_vplan_row, vplan_completeness_report_to_dict,
)


# ---------------------------------------------------------------------------
# A small, fully-clean vPlan fixture used as the positive-path baseline.
# Two sections (containers, never leaves), three leaves: one SIMULATION item
# fully linked, one FORMAL item (deliberately carrying no coverage/checker/
# test refs, since dimensions 4-6 must not apply to it), one EMULATION item
# fully linked and citing a verification intent.
# ---------------------------------------------------------------------------
def _clean_vplan():
    return [
        {"id": "SEC-1", "title": "Link Training"},
        {"id": "SEC-2", "title": "Data Path"},
        {
            "id": "ITEM-1", "parent_id": "SEC-1", "title": "LTSSM enters L0",
            "requirement_refs": ["REQ-1"], "verification_method": "SIMULATION",
            "coverage_refs": ["cg_ltssm.l0"], "checker_refs": ["ltssm_scoreboard"],
            "test_refs": ["test_ltssm_l0"], "owner": "alice", "priority": "P0",
        },
        {
            "id": "ITEM-2", "parent_id": "SEC-1", "title": "No illegal state transition",
            "requirement_refs": ["REQ-2"], "verification_method": "FORMAL",
            "owner": "bob", "priority": "P1",
        },
        {
            "id": "ITEM-3", "parent_id": "SEC-2", "title": "TLP round trip",
            "requirement_refs": ["REQ-3"], "verification_method": "EMULATION",
            "coverage_refs": ["cg_tlp.roundtrip"], "checker_refs": ["tlp_checker"],
            "test_refs": ["test_tlp_roundtrip"], "owner": "carol", "priority": "P2",
            "verification_intent_ref": "VI-1",
        },
    ]


def _clean_requirements():
    return [{"id": "REQ-1"}, {"id": "REQ-2"}, {"id": "REQ-3"}]


def _clean_intents():
    return [{"id": "VI-1", "verification_method": "EMULATION"}]


# ===========================================================================
# Positive path
# ===========================================================================

def test_clean_vplan_reports_ready_or_honest_unknown_across_all_nine_dimensions():
    report = analyze_vplan_completeness(
        _clean_vplan(), requirements=_clean_requirements(), verification_intents=_clean_intents())
    assert set(report.dimensions) == set(DIMENSIONS)
    assert len(DIMENSIONS) == 9
    for dim, result in report.dimensions.items():
        # Coverage/checker/test-stimulus linkage dims apply to a strict
        # subset of leaves in this fixture, but never fabricate READY over
        # zero applicable rows, and never carry a gap here.
        assert result.gaps == [], f"{dim} unexpectedly carries gaps: {result.gaps}"
        assert result.status in (READY, UNKNOWN), f"{dim} status={result.status}"
    assert report.all_gaps == []
    assert report.next_best_actions == []
    assert report.row_count == 5
    assert report.leaf_count == 3


def test_clean_vplan_hierarchy_shape():
    hierarchy = build_vplan_hierarchy(_clean_vplan())
    assert hierarchy["duplicate_ids"] == []
    assert hierarchy["orphan_ids"] == []
    assert hierarchy["cycle_ids"] == []
    assert sorted(hierarchy["roots"]) == ["SEC-1", "SEC-2"]
    assert sorted(hierarchy["leaves"]) == ["ITEM-1", "ITEM-2", "ITEM-3"]
    assert hierarchy["gaps"] == []


def test_report_to_dict_is_json_serializable():
    report = analyze_vplan_completeness(_clean_vplan())
    payload = vplan_completeness_report_to_dict(report)
    text = json.dumps(payload)
    assert '"schema_version"' in text
    assert "canonical_row" not in payload["hierarchy"]


def test_render_completeness_matrix_markdown_names_every_dimension():
    report = analyze_vplan_completeness(_clean_vplan())
    md = render_completeness_matrix_markdown(report)
    for dim in DIMENSIONS:
        assert dim in md


# ===========================================================================
# Gap taxonomy / dimension totality (self-consistency, structural)
# ===========================================================================

def test_gap_taxonomy_is_exactly_fifteen_values():
    assert len(GAP_TAXONOMY) == 15
    assert len(set(GAP_TAXONOMY)) == 15


def test_dimensions_are_exactly_nine_values():
    assert len(DIMENSIONS) == 9
    assert len(set(DIMENSIONS)) == 9


def test_every_gap_maps_to_a_real_dimension():
    for gap in GAP_TAXONOMY:
        assert va.GAP_TO_DIMENSION[gap] in DIMENSIONS


def test_gap_action_catalog_names_every_gap():
    actions = va.VPLAN_GAP_ACTION_CATALOG["actions"]
    assert set(actions) == set(GAP_TAXONOMY)


# ===========================================================================
# Dimension 1: hierarchy integrity -- three gap codes, each a real negative
# control (a mutated/broken hierarchy must never read as READY/PARTIAL).
# ===========================================================================

def test_duplicate_row_id_blocks_hierarchy_integrity():
    rows = _clean_vplan()
    rows.append({"id": "ITEM-1", "parent_id": "SEC-2", "title": "duplicate of ITEM-1"})
    report = analyze_vplan_completeness(rows)
    dim = report.dimensions[va.DIM_HIERARCHY_INTEGRITY]
    assert dim.status == BLOCKED
    gap_codes = {g["gap"] for g in dim.gaps}
    assert GAP_DUPLICATE_ROW_ID in gap_codes


def test_orphan_parent_ref_blocks_hierarchy_integrity():
    rows = _clean_vplan()
    rows[2] = dict(rows[2], parent_id="NO-SUCH-SECTION")
    report = analyze_vplan_completeness(rows)
    dim = report.dimensions[va.DIM_HIERARCHY_INTEGRITY]
    assert dim.status == BLOCKED
    assert any(g["gap"] == GAP_ORPHAN_PARENT_REF for g in dim.gaps)


def test_cyclic_hierarchy_blocks_hierarchy_integrity():
    rows = [
        {"id": "A", "parent_id": "C"},
        {"id": "B", "parent_id": "A"},
        {"id": "C", "parent_id": "B"},
    ]
    report = analyze_vplan_completeness(rows)
    dim = report.dimensions[va.DIM_HIERARCHY_INTEGRITY]
    assert dim.status == BLOCKED
    cycle_gaps = {g["row_id"] for g in dim.gaps if g["gap"] == GAP_CYCLIC_HIERARCHY}
    assert cycle_gaps == {"A", "B", "C"}


def test_empty_vplan_reports_unknown_never_a_fabricated_ready():
    report = analyze_vplan_completeness([])
    dim = report.dimensions[va.DIM_HIERARCHY_INTEGRITY]
    assert dim.status == UNKNOWN
    assert dim.applicable_count == 0
    # Every dimension must be present even over an empty document -- never
    # collapsed away, never silently omitted.
    assert set(report.dimensions) == set(DIMENSIONS)
    for result in report.dimensions.values():
        assert result.status == UNKNOWN


# ===========================================================================
# Dimension 2: requirement coverage
# ===========================================================================

def test_requirement_coverage_unknown_when_requirements_not_supplied():
    report = analyze_vplan_completeness(_clean_vplan())
    dim = report.dimensions[va.DIM_REQUIREMENT_COVERAGE]
    assert dim.status == UNKNOWN
    assert dim.gaps == []


def test_unmapped_requirement_is_partial_not_blocked():
    reqs = _clean_requirements() + [{"id": "REQ-99-NEVER-PLANNED"}]
    report = analyze_vplan_completeness(_clean_vplan(), requirements=reqs)
    dim = report.dimensions[va.DIM_REQUIREMENT_COVERAGE]
    assert dim.status == PARTIAL
    assert any(g["gap"] == GAP_UNMAPPED_REQUIREMENT and g["requirement_id"] == "REQ-99-NEVER-PLANNED"
               for g in dim.gaps)


def test_dangling_requirement_ref_blocks_requirement_coverage():
    rows = _clean_vplan()
    rows[2] = dict(rows[2], requirement_refs=["REQ-FABRICATED"])
    report = analyze_vplan_completeness(rows, requirements=_clean_requirements())
    dim = report.dimensions[va.DIM_REQUIREMENT_COVERAGE]
    assert dim.status == BLOCKED
    assert any(g["gap"] == GAP_DANGLING_REQUIREMENT_REF for g in dim.gaps)


# ===========================================================================
# Dimension 3: verification method assignment
# ===========================================================================

def test_missing_verification_method_is_partial():
    rows = _clean_vplan()
    rows[2] = dict(rows[2]); del rows[2]["verification_method"]
    report = analyze_vplan_completeness(rows)
    dim = report.dimensions[va.DIM_VERIFICATION_METHOD_ASSIGNMENT]
    assert dim.status == PARTIAL
    assert any(g["gap"] == GAP_MISSING_VERIFICATION_METHOD for g in dim.gaps)


def test_unknown_verification_method_blocks():
    rows = _clean_vplan()
    rows[2] = dict(rows[2], verification_method="MAGIC_INSPECTION")
    report = analyze_vplan_completeness(rows)
    dim = report.dimensions[va.DIM_VERIFICATION_METHOD_ASSIGNMENT]
    assert dim.status == BLOCKED
    assert any(g["gap"] == GAP_UNKNOWN_VERIFICATION_METHOD for g in dim.gaps)


# ===========================================================================
# Dimensions 4-6: coverage/checker/test-stimulus linkage, and the FORMAL
# exclusion (a real negative AND positive control at once).
# ===========================================================================

def test_missing_coverage_link_on_a_simulation_leaf_is_partial():
    rows = _clean_vplan()
    rows[2] = dict(rows[2]); del rows[2]["coverage_refs"]
    report = analyze_vplan_completeness(rows)
    dim = report.dimensions[va.DIM_COVERAGE_MODEL_LINKAGE]
    assert dim.status == PARTIAL
    assert any(g["gap"] == GAP_MISSING_COVERAGE_LINK and g["row_id"] == "ITEM-1" for g in dim.gaps)


def test_missing_checker_link_on_a_simulation_leaf_is_partial():
    rows = _clean_vplan()
    rows[2] = dict(rows[2]); del rows[2]["checker_refs"]
    report = analyze_vplan_completeness(rows)
    dim = report.dimensions[va.DIM_CHECKER_LINKAGE]
    assert dim.status == PARTIAL
    assert any(g["gap"] == GAP_MISSING_CHECKER_LINK for g in dim.gaps)


def test_missing_test_link_on_an_emulation_leaf_is_partial():
    rows = _clean_vplan()
    rows[4] = dict(rows[4]); del rows[4]["test_refs"]
    report = analyze_vplan_completeness(rows)
    dim = report.dimensions[va.DIM_TEST_STIMULUS_LINKAGE]
    assert dim.status == PARTIAL
    assert any(g["gap"] == GAP_MISSING_TEST_LINK and g["row_id"] == "ITEM-3" for g in dim.gaps)


def test_formal_only_leaves_report_honest_unknown_for_coverage_checker_test_dims():
    # A vPlan whose only leaf is FORMAL must never be scored PARTIAL/BLOCKED
    # against coverage/checker/test linkage kinds that method does not use --
    # nor fabricated READY over zero applicable rows.
    rows = [
        {"id": "SEC-1"},
        {"id": "ITEM-1", "parent_id": "SEC-1", "verification_method": "FORMAL",
         "owner": "dave", "priority": "P0"},
    ]
    report = analyze_vplan_completeness(rows)
    for dim_id in (va.DIM_COVERAGE_MODEL_LINKAGE, va.DIM_CHECKER_LINKAGE, va.DIM_TEST_STIMULUS_LINKAGE):
        dim = report.dimensions[dim_id]
        assert dim.status == UNKNOWN, f"{dim_id} should be UNKNOWN over an all-FORMAL vPlan, got {dim.status}"
        assert dim.applicable_count == 0
        assert dim.gaps == []


# ===========================================================================
# Dimension 7 & 8: ownership / priority
# ===========================================================================

def test_missing_owner_is_partial():
    rows = _clean_vplan()
    rows[2] = dict(rows[2]); del rows[2]["owner"]
    report = analyze_vplan_completeness(rows)
    dim = report.dimensions[va.DIM_OWNERSHIP_ASSIGNMENT]
    assert dim.status == PARTIAL
    assert any(g["gap"] == GAP_MISSING_OWNER for g in dim.gaps)


def test_missing_priority_is_partial():
    rows = _clean_vplan()
    rows[2] = dict(rows[2]); del rows[2]["priority"]
    report = analyze_vplan_completeness(rows)
    dim = report.dimensions[va.DIM_PRIORITY_ASSIGNMENT]
    assert dim.status == PARTIAL
    assert any(g["gap"] == GAP_MISSING_PRIORITY for g in dim.gaps)


def test_unrecognized_priority_value_also_reads_as_missing_priority():
    rows = _clean_vplan()
    rows[2] = dict(rows[2], priority="URGENT")  # not P0..P3
    report = analyze_vplan_completeness(rows)
    dim = report.dimensions[va.DIM_PRIORITY_ASSIGNMENT]
    assert dim.status == PARTIAL
    assert any(g["gap"] == GAP_MISSING_PRIORITY and g["row_id"] == "ITEM-1" for g in dim.gaps)


# ===========================================================================
# Dimension 9: intent cross-consistency
# ===========================================================================

def test_intent_cross_consistency_unknown_when_intents_not_supplied():
    report = analyze_vplan_completeness(_clean_vplan())
    dim = report.dimensions[va.DIM_INTENT_CROSS_CONSISTENCY]
    assert dim.status == UNKNOWN
    assert dim.gaps == []


def test_unreferenced_verification_intent_is_partial():
    intents = _clean_intents() + [{"id": "VI-99-NEVER-PLANNED", "verification_method": "SIMULATION"}]
    report = analyze_vplan_completeness(_clean_vplan(), verification_intents=intents)
    dim = report.dimensions[va.DIM_INTENT_CROSS_CONSISTENCY]
    assert dim.status == PARTIAL
    assert any(g["gap"] == GAP_UNREFERENCED_VERIFICATION_INTENT and g["intent_id"] == "VI-99-NEVER-PLANNED"
               for g in dim.gaps)


def test_dangling_intent_ref_blocks_intent_cross_consistency():
    rows = _clean_vplan()
    rows[4] = dict(rows[4], verification_intent_ref="VI-FABRICATED")
    report = analyze_vplan_completeness(rows, verification_intents=_clean_intents())
    dim = report.dimensions[va.DIM_INTENT_CROSS_CONSISTENCY]
    assert dim.status == BLOCKED
    assert any(g["gap"] == GAP_DANGLING_INTENT_REF for g in dim.gaps)


def test_intent_method_contradiction_blocks_intent_cross_consistency():
    rows = _clean_vplan()
    rows[4] = dict(rows[4], verification_method="SIMULATION")  # intent VI-1 declares EMULATION
    report = analyze_vplan_completeness(rows, verification_intents=_clean_intents())
    dim = report.dimensions[va.DIM_INTENT_CROSS_CONSISTENCY]
    assert dim.status == BLOCKED
    contradiction = [g for g in dim.gaps if g["gap"] == GAP_INTENT_METHOD_CONTRADICTION]
    assert len(contradiction) == 1
    assert contradiction[0]["row_id"] == "ITEM-3"


# ===========================================================================
# Next-best-action wiring through the real inference.next_best_action()
# ===========================================================================

def test_next_best_action_returned_for_every_present_gap_type_and_never_generic():
    rows = _clean_vplan()
    rows[2] = dict(rows[2]); del rows[2]["owner"]
    rows[3] = dict(rows[3], verification_method="MAGIC_INSPECTION")
    report = analyze_vplan_completeness(rows)
    present_gap_codes = {g["gap"] for g in report.all_gaps}
    assert present_gap_codes == {GAP_MISSING_OWNER, GAP_UNKNOWN_VERIFICATION_METHOD}
    actioned_gaps = {a["gap"] for a in report.next_best_actions}
    assert actioned_gaps == present_gap_codes
    for action in report.next_best_actions:
        assert action["source"] == "vplan_artifact"
        assert action["suggested_action"]


def test_next_best_action_empty_when_no_gaps():
    report = analyze_vplan_completeness(_clean_vplan())
    assert report.next_best_actions == []


def test_next_best_action_never_touches_filesystem_when_root_omitted():
    # root defaults to None -> "." ; the catalog branch of
    # inference.next_best_action() returns before reading anything, so this
    # must succeed even when no real project root exists.
    rows = _clean_vplan()
    rows[2] = dict(rows[2]); del rows[2]["owner"]
    report = analyze_vplan_completeness(rows, root="/this/path/does/not/exist/anywhere")
    assert len(report.next_best_actions) == 1
    assert report.next_best_actions[0]["gap"] == GAP_MISSING_OWNER


# ===========================================================================
# Schema validation (structural) -- fail-closed, never a silent False/None.
# ===========================================================================

def test_validate_vplan_row_accepts_a_clean_row():
    validate_vplan_row(_clean_vplan()[2])


def test_validate_vplan_row_rejects_non_mapping():
    with pytest.raises(VPlanArtifactValidationError):
        validate_vplan_row(["not", "a", "mapping"])


def test_validate_vplan_row_rejects_missing_id():
    with pytest.raises(VPlanArtifactValidationError):
        validate_vplan_row({"title": "no id here"})


def test_validate_vplan_row_rejects_non_string_list_field():
    with pytest.raises(VPlanArtifactValidationError):
        validate_vplan_row({"id": "X", "requirement_refs": "REQ-1"})  # must be a list


def test_validate_vplan_document_rejects_non_list():
    with pytest.raises(VPlanArtifactValidationError):
        validate_vplan_document({"id": "X"})


def test_analyze_vplan_completeness_raises_on_structurally_malformed_row():
    with pytest.raises(VPlanArtifactValidationError):
        analyze_vplan_completeness([{"title": "no id"}])
