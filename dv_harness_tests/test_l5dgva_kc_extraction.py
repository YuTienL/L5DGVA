"""Tests for dv_harness/l5dgva_kc_extraction.py -- SS211's EXTRACTION half:
classify_kc_scope_class(), build_kc_extraction_record(),
find_newly_closed_rows() and the composed
build_kc_extraction_records_for_newly_closed(). Uses synthetic fixture rows,
same style as test_l5dgva_gap_queue.py, plus a real end-to-end
route_and_store() call against a real tmp memory store to prove the output
shape is genuinely consumable by the real pipeline, not merely dict-shaped.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim --
canonical's real `memory_router.route_and_store(root, record, cfg=None)` and
`protocol_capability.PROTOCOL_CAPABILITIES` were both independently confirmed
compatible before this migration, so no adaptation was needed.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness.l5dgva_gap_queue import ClosureRow, RuntimeStatus
from dv_harness.l5dgva_kc_extraction import (
    KC_SCOPE_CLASSES,
    KCExtractionError,
    build_kc_extraction_record,
    build_kc_extraction_records_for_newly_closed,
    classify_kc_scope_class,
    find_newly_closed_rows,
)
from dv_harness.memory_router import route_and_store


def _row(domain, cluster, ids, status, notes="", evidence="fixture.py:1", confidence="high") -> ClosureRow:
    return ClosureRow(domain=domain, cluster=cluster, requirement_ids=ids, status=status,
                       evidence=evidence, confidence=confidence, notes=notes)


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- classify_kc_scope_class --------------------------------------------------

def test_full_protocol_name_classifies_protocol_specific():
    row = _row("C_reference_de_architecture", "USB VIP scenario reuse", ["X_PASS"],
                RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL,
                notes="reusable pattern for USB_2_3x enumeration scenario reuse")
    assert classify_kc_scope_class(row) == "PROTOCOL_SPECIFIC"


def test_family_root_without_full_name_classifies_protocol_family():
    row = _row("C_reference_de_architecture", "MIPI D-PHY lane bring-up", ["X_PASS"],
                RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL,
                notes="generic MIPI lane low-power/high-speed transition method")
    assert classify_kc_scope_class(row) == "PROTOCOL_FAMILY"


def test_tool_path_token_classifies_tool():
    row = _row("D_irq", "irq extraction reuse", ["X_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL,
                notes="method lives in interrupt_dma_clock_reset_extraction.py, reuse it directly")
    assert classify_kc_scope_class(row) == "TOOL"


def test_project_id_token_classifies_project():
    # evidence deliberately not a *.py/module path -- this test isolates the
    # PROJECT signal (checked after TOOL) from an incidental TOOL match.
    row = _row("D_irq", "usb2 enum verdict conflict debug method", ["X_PASS"],
                RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL,
                notes="method proven on R5-D-ENUM1C, reusable for the next similar project",
                evidence="R5-D-ENUM1C/findings.yaml")
    assert classify_kc_scope_class(row) == "PROJECT"


def test_generic_methodology_domain_with_no_stronger_signal_classifies_generic():
    # evidence deliberately not a *.py/module path or project-ID token -- this
    # test isolates the domain-default GENERIC fallback (checked last).
    row = _row("E_evidence_vplan_coverage_signoff", "coverage hole taxonomy method", ["X_PASS"],
                RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL, notes="general 12-category hole classification",
                evidence="human-reviewed audit note")
    assert classify_kc_scope_class(row) == "GENERIC"


def test_non_generic_domain_with_no_stronger_signal_falls_to_scope_not_generic():
    row = _row("C_reference_de_architecture", "makefile capability parity", ["X_PASS"],
                RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL, notes="8-capability classification rollup",
                evidence="human-reviewed audit note")
    assert classify_kc_scope_class(row) == "SCOPE"


def test_every_classification_is_one_of_the_six_named_values():
    rows = [
        _row("A_orchestration_engines", "x", ["X_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL),
        _row("C_reference_de_architecture", "y", ["Y_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL),
    ]
    for row in rows:
        assert classify_kc_scope_class(row) in KC_SCOPE_CLASSES


# --- build_kc_extraction_record ----------------------------------------------

def test_build_record_refuses_a_row_that_is_not_passing():
    row = _row("A", "still open", ["X_PASS"], RuntimeStatus.NOT_PROVEN)
    with pytest.raises(KCExtractionError):
        build_kc_extraction_record(row)


def test_build_record_refuses_a_row_with_no_evidence():
    row = _row("A", "no citation", ["X_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL, evidence="")
    with pytest.raises(KCExtractionError):
        build_kc_extraction_record(row)


def test_build_record_carries_the_rows_own_real_evidence_and_confidence():
    row = _row("E_evidence_vplan_coverage_signoff", "vplan completeness rollup",
                ["SS209_PASS", "SS210_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL,
                evidence="vplan_artifact.py:analyze_vplan_completeness", confidence="high",
                notes="unanimous across all 4 sub-audits")
    record = build_kc_extraction_record(row)
    assert record["kind"] == "methodology"
    assert record["verified"] is False
    assert record["evidence"] == "vplan_artifact.py:analyze_vplan_completeness"
    assert record["confidence"] == "high"
    assert record["requirement_ids"] == ["SS209_PASS", "SS210_PASS"]
    assert record["source_domain"] == "E_evidence_vplan_coverage_signoff"
    assert "unanimous across all 4 sub-audits" in record["lesson"]
    assert record["kc_scope_class"] in KC_SCOPE_CLASSES


def test_mark_verified_is_explicit_not_a_quiet_default():
    row = _row("A", "x", ["X_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL)
    assert build_kc_extraction_record(row)["verified"] is False
    assert build_kc_extraction_record(row, mark_verified=True)["verified"] is True


def test_not_applicable_with_evidence_is_a_valid_passing_status_to_extract_from():
    row = _row("A", "genuinely n/a", ["X_PASS"], RuntimeStatus.NOT_APPLICABLE_WITH_EVIDENCE,
                evidence="human-confirmed: no security surface declared")
    record = build_kc_extraction_record(row)
    assert record["status"] == "NOT_APPLICABLE_WITH_EVIDENCE"


# --- find_newly_closed_rows ---------------------------------------------------

def test_row_that_was_a_gap_and_is_now_passing_is_newly_closed():
    prev = [_row("A", "x", ["X_PASS"], RuntimeStatus.IMPLEMENTED_NOT_WIRED)]
    curr = [_row("A", "x", ["X_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL)]
    newly = find_newly_closed_rows(prev, curr)
    assert len(newly) == 1
    assert newly[0].cluster == "x"


def test_row_absent_before_and_passing_now_is_newly_closed():
    prev = []
    curr = [_row("A", "brand new", ["X_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL)]
    assert len(find_newly_closed_rows(prev, curr)) == 1


def test_row_passing_in_both_snapshots_is_not_newly_closed():
    prev = [_row("A", "x", ["X_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL)]
    curr = [_row("A", "x", ["X_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL)]
    assert find_newly_closed_rows(prev, curr) == []


def test_row_still_a_gap_now_is_not_newly_closed():
    prev = [_row("A", "x", ["X_PASS"], RuntimeStatus.NOT_PROVEN)]
    curr = [_row("A", "x", ["X_PASS"], RuntimeStatus.DOCUMENTED_NOT_IMPLEMENTED)]
    assert find_newly_closed_rows(prev, curr) == []


def test_row_that_regressed_from_passing_to_gap_is_not_newly_closed():
    prev = [_row("A", "x", ["X_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL)]
    curr = [_row("A", "x", ["X_PASS"], RuntimeStatus.WIRED_NOT_TRIGGERED)]
    assert find_newly_closed_rows(prev, curr) == []


def test_build_kc_extraction_records_for_newly_closed_composes_both_steps():
    prev = [_row("E_evidence_vplan_coverage_signoff", "closure aggregator wiring", ["SS211_PASS"],
                  RuntimeStatus.IMPLEMENTED_NOT_WIRED, evidence="system_closure_aggregator.py")]
    curr = [_row("E_evidence_vplan_coverage_signoff", "closure aggregator wiring", ["SS211_PASS"],
                  RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL, evidence="system_closure_aggregator.py; cli.py:595")]
    records = build_kc_extraction_records_for_newly_closed(prev, curr)
    assert len(records) == 1
    assert records[0]["source_cluster"] == "closure aggregator wiring"
    assert records[0]["evidence"] == "system_closure_aggregator.py; cli.py:595"


# --- end-to-end: the built record is genuinely route_and_store()-shaped ------

def test_record_is_genuinely_consumable_by_route_and_store(root):
    row = _row("E_evidence_vplan_coverage_signoff", "gap queue wiring", ["SS211_PASS"],
                RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL,
                evidence="l5dgva_gap_queue.py; cli.py l5dgva-gap-queue subcommand", confidence="high")
    record = build_kc_extraction_record(row)
    routed = route_and_store(root, record, cfg={})
    # kind="methodology" + verified=False (this function's honest default)
    # falls through route_memory()'s full dispatch chain to WORKING_MEMORY --
    # a real write, not a promotion this single unconfirmed row has not earned.
    assert routed["destination"] == "WORKING_MEMORY"
    assert "memory_id" in routed
