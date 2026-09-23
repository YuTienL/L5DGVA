"""Tests for dv_harness/l5dgva_gap_queue.py -- the Phase-3 aggregation logic
(priority assignment, coverage arithmetic, closure-matrix rendering) that
consumes the L5DGVA domain-audit ClosureRow records. Uses synthetic fixture
rows, not live audit results -- this module's job is the mechanical
aggregation, and that is exactly what a fixture can prove deterministically.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim --
this module is fully self-contained and the ported production module's
public API is identical, so no test adaptation was needed.
"""
from __future__ import annotations

import pytest

from dv_harness.l5dgva_gap_queue import (
    ClosureRow,
    Priority,
    RuntimeStatus,
    build_gap_queue,
    compute_coverage,
    render_closure_matrix,
    rows_from_json,
)


def _row(domain, cluster, ids, status, notes="", evidence="fixture.py:1", confidence="high") -> ClosureRow:
    return ClosureRow(domain=domain, cluster=cluster, requirement_ids=ids, status=status, evidence=evidence, confidence=confidence, notes=notes)


def test_coverage_is_zero_percent_with_no_passing_rows():
    rows = [_row("C_reference_de_architecture", "x", ["A_PASS", "B_PASS"], RuntimeStatus.DOCUMENTED_NOT_IMPLEMENTED)]
    m = compute_coverage(rows)
    assert m.total_requirements == 2
    assert m.passing_requirements == 0
    assert m.coverage_percent == 0.0


def test_coverage_counts_at_requirement_granularity_not_cluster_granularity():
    rows = [
        _row("A", "big cluster", [f"R{i}_PASS" for i in range(40)], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL),
        _row("A", "small cluster", ["S_PASS"], RuntimeStatus.NOT_PROVEN),
    ]
    m = compute_coverage(rows)
    assert m.total_requirements == 41
    assert m.passing_requirements == 40
    assert m.coverage_percent == round(100 * 40 / 41, 2)


def test_not_applicable_with_evidence_counts_as_passing():
    rows = [_row("A", "x", ["X_PASS"], RuntimeStatus.NOT_APPLICABLE_WITH_EVIDENCE)]
    m = compute_coverage(rows)
    assert m.passing_requirements == 1
    assert m.coverage_percent == 100.0


def test_100_percent_requires_every_row_to_actually_pass():
    rows = [
        _row("A", "x", ["X_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL),
        _row("A", "y", ["Y_PASS"], RuntimeStatus.NOT_PROVEN),
    ]
    m = compute_coverage(rows)
    assert m.coverage_percent < 100.0


# --- priority assignment -----------------------------------------------------

def test_domain_default_priority_applies():
    row = _row("E_evidence_vplan_coverage_signoff", "vplan closure", ["X_PASS"], RuntimeStatus.NOT_PROVEN)
    assert row.priority() == Priority.P0_VERIFICATION_TRUTH

    row2 = _row("C_reference_de_architecture", "makefile parity", ["X_PASS"], RuntimeStatus.NOT_PROVEN)
    assert row2.priority() == Priority.P2_DE_REFERENCE_BUILD_DEBUG_COVERAGE


def test_signoff_keyword_escalates_to_p0_regardless_of_domain():
    row = _row("D_irq", "IRQ signoff false pass guard", ["X_PASS"], RuntimeStatus.NOT_PROVEN, notes="risk of false signoff")
    assert row.priority() == Priority.P0_VERIFICATION_TRUTH


def test_gap_queue_excludes_passing_rows():
    rows = [
        _row("A", "ok", ["X_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL),
        _row("A", "gap", ["Y_PASS"], RuntimeStatus.IMPLEMENTED_NOT_WIRED),
    ]
    queue = build_gap_queue(rows)
    all_gaps = [r for bucket in queue.values() for r in bucket]
    assert len(all_gaps) == 1
    assert all_gaps[0].cluster == "gap"


def test_gap_queue_buckets_by_priority():
    rows = [
        _row("F_contract_as_code_meta", "codex review", ["X_PASS"], RuntimeStatus.BLOCKED),
        _row("C_reference_de_architecture", "makefile", ["Y_PASS"], RuntimeStatus.DOCUMENTED_NOT_IMPLEMENTED),
    ]
    queue = build_gap_queue(rows)
    assert queue[Priority.P0_VERIFICATION_TRUTH][0].cluster == "codex review"
    assert queue[Priority.P2_DE_REFERENCE_BUILD_DEBUG_COVERAGE][0].cluster == "makefile"


def test_rows_from_json_round_trips_real_shape():
    records = [
        {"domain": "A", "cluster": "x", "requirement_ids": ["X_PASS", "X2_PASS"],
         "status": "implemented_and_operational", "evidence": "foo.py:1", "confidence": "high", "notes": "n"},
    ]
    rows = rows_from_json(records)
    assert len(rows) == 1
    assert rows[0].status == RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL
    assert rows[0].requirement_ids == ["X_PASS", "X2_PASS"]


def test_rows_from_json_rejects_unrecognized_status_rather_than_defaulting():
    records = [{"domain": "A", "cluster": "x", "requirement_ids": ["X_PASS"], "status": "TOTALLY_MADE_UP"}]
    with pytest.raises(ValueError):
        rows_from_json(records)


def test_render_closure_matrix_includes_coverage_and_every_row():
    rows = [
        _row("A", "engine x", ["X_PASS", "X2_PASS"], RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL),
        _row("B", "kc y", ["Y_PASS"], RuntimeStatus.NOT_PROVEN, notes="needs deeper check"),
    ]
    md = render_closure_matrix(rows)
    assert "ContractRuntimeCoverage" in md
    assert "engine x" in md
    assert "kc y" in md
    assert "needs deeper check" in md
