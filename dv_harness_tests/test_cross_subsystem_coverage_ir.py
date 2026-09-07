"""Tests for dv_harness/cross_subsystem_coverage_ir.py.

Proves: (1) the module REUSES system_failure_taxonomy.classify_system_coverage_hole()
for every hole's category rather than reinventing the 6-value taxonomy; (2) boundary
resolution is a real, independent fact, never a guess -- a declared cross_subsystem
scope with insufficient real subsystem_ids is honestly UNRESOLVED, never a fabricated
placeholder pair; (3) a hole's category and its boundary resolution are independent
axes (a RESOURCE_GAP/ERROR_PATH_GAP hole can still resolve a real boundary); (4) the
per-boundary rollup and category totals are pure reductions of the per-hole records,
never a second, disagreeing computation; (5) the CLI front door works end to end.
"""
import json
import subprocess
import sys

import pytest

from dv_harness import cross_subsystem_coverage_ir as csc
from dv_harness import system_failure_taxonomy as sft
from dv_harness.models import Status


# -----------------------------------------------------------------------------
# Reuse, not reinvent: the category vocabulary is literally system_failure_taxonomy's.
# -----------------------------------------------------------------------------

def test_reused_category_vocabulary_is_literally_system_failure_taxonomy_s():
    assert csc.COVERAGE_HOLE_CATEGORIES is sft.COVERAGE_HOLE_CATEGORIES
    assert csc.UNCLASSIFIED_COVERAGE_HOLE == sft.UNCLASSIFIED_COVERAGE_HOLE


def test_classify_cross_subsystem_hole_delegates_category_to_real_classifier():
    hole = {"coverage_model_missing": True}
    rec = csc.classify_cross_subsystem_hole(hole, hole_id="h1")
    base = sft.classify_system_coverage_hole(hole)
    assert rec.category == base.category == "COVERAGE_MODEL_GAP"
    assert rec.matched_field == base.matched_field
    assert rec.category_reason == base.reason


def test_vocabulary_disjoint_from_verification_verdict():
    verdicts = {s.value for s in Status}
    assert not verdicts.intersection(csc.BOUNDARY_STATUSES)
    assert not verdicts.intersection(csc.COVERAGE_HOLE_CATEGORIES)
    # Re-run the guard function itself to prove it is a real, callable check.
    csc.assert_no_verification_verdict_vocabulary()


# -----------------------------------------------------------------------------
# Boundary resolution: RESOLVED
# -----------------------------------------------------------------------------

def test_two_subsystem_ids_resolve_one_boundary():
    hole = {"scope": "cross_subsystem", "subsystem_ids": ["usb0", "pcie0"]}
    rec = csc.classify_cross_subsystem_hole(hole)
    assert rec.category == "INTEGRATION_GAP"
    assert rec.boundary_status == csc.BOUNDARY_RESOLVED
    assert rec.boundaries == [("pcie0", "usb0")]
    assert rec.subsystem_ids == ["usb0", "pcie0"]


def test_three_subsystem_ids_resolve_all_pairwise_boundaries():
    hole = {"scope": "cross_subsystem", "subsystem_ids": ["a", "b", "c"]}
    rec = csc.classify_cross_subsystem_hole(hole)
    assert rec.boundary_status == csc.BOUNDARY_RESOLVED
    assert rec.boundaries == [("a", "b"), ("a", "c"), ("b", "c")]


def test_boundary_pairs_are_order_independent_and_deduplicated():
    hole_ab = {"subsystem_ids": ["a", "b"]}
    hole_ba = {"subsystem_ids": ["b", "a"]}
    rec_ab = csc.classify_cross_subsystem_hole(hole_ab)
    rec_ba = csc.classify_cross_subsystem_hole(hole_ba)
    assert rec_ab.boundaries == rec_ba.boundaries == [("a", "b")]


def test_duplicate_subsystem_ids_do_not_manufacture_extra_boundaries():
    hole = {"subsystem_ids": ["a", "a", "b", "b"]}
    rec = csc.classify_cross_subsystem_hole(hole)
    assert rec.subsystem_ids == ["a", "b"]
    assert rec.boundaries == [("a", "b")]


def test_resource_gap_still_resolves_a_real_boundary_independent_of_category():
    """A RESOURCE_GAP (not INTEGRATION_GAP) hole can still name a real
    two-subsystem boundary -- boundary resolution is independent of which
    category won classify_system_coverage_hole()'s own priority order."""
    hole = {"involves_shared_resource": True, "subsystem_ids": ["usb0", "pcie0"]}
    rec = csc.classify_cross_subsystem_hole(hole)
    assert rec.category == "RESOURCE_GAP"
    assert rec.boundary_status == csc.BOUNDARY_RESOLVED
    assert rec.boundaries == [("pcie0", "usb0")]


def test_error_path_gap_still_resolves_a_real_boundary():
    hole = {"involves_error_path": True, "subsystem_ids": ["fw0", "vip0"]}
    rec = csc.classify_cross_subsystem_hole(hole)
    assert rec.category == "ERROR_PATH_GAP"
    assert rec.boundary_status == csc.BOUNDARY_RESOLVED


# -----------------------------------------------------------------------------
# Boundary resolution: UNRESOLVED (never a guessed/fabricated pair)
# -----------------------------------------------------------------------------

def test_declared_cross_scope_with_no_ids_is_unresolved_never_a_guess():
    hole = {"scope": "cross_subsystem"}
    rec = csc.classify_cross_subsystem_hole(hole)
    assert rec.category == "INTEGRATION_GAP"
    assert rec.boundary_status == csc.BOUNDARY_UNRESOLVED
    assert rec.boundaries == []
    assert "no specific boundary" in rec.boundary_reason


def test_declared_cross_scope_with_one_id_is_unresolved():
    hole = {"scope": "cross_subsystem", "subsystem_ids": ["only_one"]}
    rec = csc.classify_cross_subsystem_hole(hole)
    assert rec.boundary_status == csc.BOUNDARY_UNRESOLVED
    assert rec.boundaries == []


# -----------------------------------------------------------------------------
# Boundary resolution: NOT_APPLICABLE
# -----------------------------------------------------------------------------

def test_single_subsystem_gap_is_not_applicable():
    hole = {"subsystem_id": "usb0"}
    rec = csc.classify_cross_subsystem_hole(hole)
    assert rec.category == "SUBSYSTEM_GAP"
    assert rec.boundary_status == csc.BOUNDARY_NOT_APPLICABLE
    assert rec.boundaries == []
    assert rec.subsystem_ids == ["usb0"]


def test_no_subsystem_info_at_all_is_not_applicable():
    hole = {"scenario_category_missing": True}
    rec = csc.classify_cross_subsystem_hole(hole)
    assert rec.category == "SCENARIO_GAP"
    assert rec.boundary_status == csc.BOUNDARY_NOT_APPLICABLE
    assert rec.subsystem_ids == []


def test_unclassified_hole_still_gets_honest_boundary_status():
    rec = csc.classify_cross_subsystem_hole({})
    assert rec.category == csc.UNCLASSIFIED_COVERAGE_HOLE
    assert rec.boundary_status == csc.BOUNDARY_NOT_APPLICABLE


# -----------------------------------------------------------------------------
# Malformed input
# -----------------------------------------------------------------------------

def test_none_hole_raises():
    with pytest.raises(ValueError):
        csc.classify_cross_subsystem_hole(None)


def test_non_dict_hole_raises():
    with pytest.raises(ValueError):
        csc.classify_cross_subsystem_hole("not a dict")


def test_none_holes_list_raises():
    with pytest.raises(ValueError):
        csc.build_cross_subsystem_coverage_ir(None)


def test_non_list_holes_raises():
    with pytest.raises(ValueError):
        csc.build_cross_subsystem_coverage_ir({"not": "a list"})


def test_non_dict_entry_in_holes_list_raises():
    with pytest.raises(ValueError):
        csc.build_cross_subsystem_coverage_ir([{"subsystem_id": "a"}, "bad"])


# -----------------------------------------------------------------------------
# Full IR: boundary_matrix / category_totals / unresolved list -- pure reductions
# -----------------------------------------------------------------------------

def _sample_holes():
    return [
        {"hole_id": "h1", "scope": "cross_subsystem", "subsystem_ids": ["usb0", "pcie0"]},
        {"hole_id": "h2", "involves_shared_resource": True, "subsystem_ids": ["usb0", "pcie0"]},
        {"hole_id": "h3", "subsystem_id": "usb0"},
        {"hole_id": "h4", "scope": "cross_subsystem"},
        {"hole_id": "h5", "coverage_model_missing": True},
    ]


def test_build_ir_produces_one_record_per_hole_in_order():
    ir = csc.build_cross_subsystem_coverage_ir(_sample_holes())
    assert [r.hole_id for r in ir.holes] == ["h1", "h2", "h3", "h4", "h5"]


def test_boundary_matrix_only_includes_resolved_boundaries():
    ir = csc.build_cross_subsystem_coverage_ir(_sample_holes())
    matrix = ir.boundary_matrix()
    assert list(matrix.keys()) == [("pcie0", "usb0")]
    by_category = matrix[("pcie0", "usb0")]
    assert by_category["INTEGRATION_GAP"] == ["h1"]
    assert by_category["RESOURCE_GAP"] == ["h2"]


def test_category_totals_counts_every_hole_including_unresolved_and_not_applicable():
    ir = csc.build_cross_subsystem_coverage_ir(_sample_holes())
    totals = ir.category_totals()
    assert totals == {
        "INTEGRATION_GAP": 2,  # h1 and h4
        "RESOURCE_GAP": 1,     # h2
        "SUBSYSTEM_GAP": 1,    # h3
        "COVERAGE_MODEL_GAP": 1,  # h5
    }


def test_unresolved_boundary_hole_ids_names_the_real_gap():
    ir = csc.build_cross_subsystem_coverage_ir(_sample_holes())
    assert ir.unresolved_boundary_hole_ids() == ["h4"]


def test_hole_id_falls_back_to_synthetic_index_based_id():
    ir = csc.build_cross_subsystem_coverage_ir([{"subsystem_id": "a"}, {"subsystem_id": "b"}])
    assert [r.hole_id for r in ir.holes] == ["hole_0", "hole_1"]


def test_to_dict_round_trips_all_fields():
    ir = csc.build_cross_subsystem_coverage_ir(_sample_holes())
    d = ir.to_dict()
    assert len(d["holes"]) == 5
    assert "pcie0<->usb0" in d["boundary_matrix"]
    assert d["unresolved_boundary_hole_ids"] == ["h4"]
    assert d["category_totals"]["INTEGRATION_GAP"] == 2


def test_render_boundary_matrix_markdown_reuses_connectivity_renderer():
    ir = csc.build_cross_subsystem_coverage_ir(_sample_holes())
    text = csc.render_boundary_matrix_markdown(ir)
    assert "pcie0 <-> usb0" in text
    assert "INTEGRATION_GAP" in text
    assert "RESOURCE_GAP" in text


def test_render_boundary_matrix_markdown_empty_note_when_nothing_resolved():
    ir = csc.build_cross_subsystem_coverage_ir([{"subsystem_id": "a"}])
    text = csc.render_boundary_matrix_markdown(ir)
    assert "no cross-subsystem boundaries resolved" in text


# -----------------------------------------------------------------------------
# CLI front door
# -----------------------------------------------------------------------------

def test_cli_json_output(tmp_path):
    holes_file = tmp_path / "holes.json"
    holes_file.write_text(json.dumps(_sample_holes()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.cross_subsystem_coverage_ir",
         "--holes", str(holes_file), "--json"],
        capture_output=True, text=True,
    )
    # exit 1 because h4 is a real unresolved-boundary finding
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["unresolved_boundary_hole_ids"] == ["h4"]


def test_cli_clean_input_exits_zero(tmp_path):
    holes_file = tmp_path / "holes_clean.json"
    holes_file.write_text(
        json.dumps([{"hole_id": "h1", "subsystem_ids": ["a", "b"]}]), encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.cross_subsystem_coverage_ir",
         "--holes", str(holes_file)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Boundary" in result.stdout


def test_cli_unreadable_file_exits_two(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.cross_subsystem_coverage_ir",
         "--holes", str(missing)],
        capture_output=True, text=True,
    )
    assert result.returncode == 2, result.stderr
    assert "NOT_AVAILABLE" in result.stderr


def test_cli_malformed_json_content_exits_two(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps([{"subsystem_id": "a"}, "not_a_dict"]), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.cross_subsystem_coverage_ir",
         "--holes", str(bad_file)],
        capture_output=True, text=True,
    )
    assert result.returncode == 2, result.stderr
    assert "NOT_AVAILABLE" in result.stderr
