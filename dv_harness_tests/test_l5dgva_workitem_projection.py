"""Tests for dv_harness/l5dgva_workitem_projection.py -- the narrow
"contract->workitem" first-hop projection from a real l5dgva_gap_queue.ClosureRow
onto V22 SS645/SS646's WorkItem vocabulary. Fixture-based: this module's job is
a deterministic, total projection over ClosureRow's real fields, which a
fixture can prove exhaustively without needing a live audit run.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim -- fully
self-contained fixture test, no adaptation needed.
"""
from __future__ import annotations

import pytest

from dv_harness.l5dgva_gap_queue import ClosureRow, RuntimeStatus
from dv_harness.l5dgva_workitem_projection import (
    STATICALLY_REACHABLE_STATES,
    UNAVAILABLE_FIELD_REASON,
    WorkItemState,
    closure_row_to_workitem_stub,
    project_runtime_status_to_workitem_state,
)


def _row(status: RuntimeStatus, **overrides) -> ClosureRow:
    defaults = dict(
        domain="A_orchestration_engines",
        cluster="C26",
        requirement_ids=["642", "643", "644"],
        status=status,
        evidence="dv_harness/l5dgva_contract_registry.py (parser only, no dispatcher)",
        confidence="high",
        notes="",
    )
    defaults.update(overrides)
    return ClosureRow(**defaults)


def test_workitem_state_enum_matches_v22_section_646_verbatim():
    # SS646: "Every work item uses: DISCOVERED READY RUNNING BLOCKED_VALID
    # FAILED_REPAIRABLE REPAIRING VALIDATING PASS." -- exact 8 values, exact order.
    assert [s.value for s in WorkItemState] == [
        "DISCOVERED",
        "READY",
        "RUNNING",
        "BLOCKED_VALID",
        "FAILED_REPAIRABLE",
        "REPAIRING",
        "VALIDATING",
        "PASS",
    ]


def test_no_dropped_state_exists():
    # SS646: "No silent DROPPED state."
    assert "DROPPED" not in [s.value for s in WorkItemState]
    assert "DROPPED" not in WorkItemState.__members__


@pytest.mark.parametrize(
    "status",
    [
        RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL,
        RuntimeStatus.NOT_APPLICABLE_WITH_EVIDENCE,
        RuntimeStatus.WIRED_NOT_TRIGGERED,
    ],
)
def test_passing_statuses_project_to_pass(status):
    # WIRED_NOT_TRIGGERED joined PASSING_STATUSES 2026-09-18 (explicit user
    # policy decision: this audit's scope is implementation-and-integration,
    # not live end-to-end operational proof -- see l5dgva_gap_queue.py's own
    # PASSING_STATUSES comment for the full rationale).
    assert project_runtime_status_to_workitem_state(status) is WorkItemState.PASS


def test_blocked_projects_to_blocked_valid():
    assert project_runtime_status_to_workitem_state(RuntimeStatus.BLOCKED) is WorkItemState.BLOCKED_VALID


@pytest.mark.parametrize(
    "status",
    [
        RuntimeStatus.DOCUMENTED_NOT_IMPLEMENTED,
        RuntimeStatus.NOT_PROVEN,
        RuntimeStatus.WIRED_NOT_REACHABLE,
        RuntimeStatus.TRIGGERED_NO_ARTIFACT,
        RuntimeStatus.REGRESSION_MISSING,
    ]
)
def test_other_gap_statuses_project_to_discovered(status):
    assert project_runtime_status_to_workitem_state(status) is WorkItemState.DISCOVERED


def test_projection_never_emits_a_live_dispatch_state():
    # Exhaustive over every real RuntimeStatus value -- proves the projection can never
    # accidentally claim READY/RUNNING/FAILED_REPAIRABLE/REPAIRING/VALIDATING, none of which
    # a static audit classification has real dispatch evidence to back.
    for status in RuntimeStatus:
        state = project_runtime_status_to_workitem_state(status)
        assert state in STATICALLY_REACHABLE_STATES
    assert STATICALLY_REACHABLE_STATES == {
        WorkItemState.DISCOVERED, WorkItemState.BLOCKED_VALID, WorkItemState.PASS,
    }


def test_closure_row_to_workitem_stub_real_fields_carried_through():
    row = _row(RuntimeStatus.DOCUMENTED_NOT_IMPLEMENTED)
    stub = closure_row_to_workitem_stub(row)
    assert stub["work_item_id"] == "A_orchestration_engines::C26"
    assert stub["work_item_ids"] == ["642", "643", "644"]
    assert stub["execution_state"] == "DISCOVERED"
    assert stub["verdict"] == "DOCUMENTED_NOT_IMPLEMENTED"
    assert stub["evidence_refs"] == ["dv_harness/l5dgva_contract_registry.py (parser only, no dispatcher)"]


def test_closure_row_to_workitem_stub_blocked_row():
    row = _row(RuntimeStatus.BLOCKED, evidence="waiting on human decision Q-42")
    stub = closure_row_to_workitem_stub(row)
    assert stub["execution_state"] == "BLOCKED_VALID"
    assert stub["verdict"] == "BLOCKED"


def test_closure_row_to_workitem_stub_no_evidence_yields_empty_refs_not_fabrication():
    row = _row(RuntimeStatus.NOT_PROVEN, evidence="")
    stub = closure_row_to_workitem_stub(row)
    assert stub["evidence_refs"] == []


def test_closure_row_to_workitem_stub_never_fabricates_ss643_provenance_fields():
    # Every SS643 ExecutableDirectiveRegistry field a ClosureRow cannot honestly answer
    # must be exactly None, with one shared disclosed reason -- never a guessed string.
    row = _row(RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL)
    stub = closure_row_to_workitem_stub(row)
    unavailable_fields = (
        "source_contract", "source_section", "directive_text_ref", "action_type",
        "dependencies", "required_engine", "graph_node", "trigger", "gate",
    )
    for field_name in unavailable_fields:
        assert stub[field_name] is None
    assert stub["unavailable_field_reason"] == UNAVAILABLE_FIELD_REASON
    assert "SS643" in UNAVAILABLE_FIELD_REASON
