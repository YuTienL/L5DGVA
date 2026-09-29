"""Tests for dv_harness/l5dgva_directive_registry.py -- V22 SS643
`ExecutableDirectiveRegistry` schema + the one real worked example (SS645, over V21 SS638)
this contract chain actually supplies. Real, deterministic fixture-based checks: this
module's job is a total, evidence-cited seeding over literal transcribed primary text, which
a fixture can prove exhaustively without needing a live audit run.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim -- no adaptation needed.
"""
from __future__ import annotations

import pytest

from dv_harness.l5dgva_directive_registry import (
    FIELD_NOT_YET_ASSIGNED_REASON,
    V21_SS638_STEP_TEXTS,
    V21_SS638_TRIGGER,
    V22_SS645_WORKITEM_LABELS,
    DirectiveRecord,
    ExecutableDirectiveRegistry,
    WorkItemDescriptor,
    seed_registry,
    seed_v21_exec_workitem_descriptors,
    seed_v21_ss638_directive,
    verify_ordinal_alignment,
)
from dv_harness.l5dgva_workitem_projection import WorkItemState


# ---------------------------------------------------------------------------
# Primary-text transcription fixtures (pin the literal quotes this module's docstring
# cites -- if the source files ever change, these regressions catch the drift).
# ---------------------------------------------------------------------------


def test_v21_ss638_step_texts_count_and_first_last_item():
    assert len(V21_SS638_STEP_TEXTS) == 21
    assert V21_SS638_STEP_TEXTS[0] == "Locate ALL configured governing contract Markdown files."
    assert V21_SS638_STEP_TEXTS[-1] == (
        "Stop only at genuine Human/Authority/External boundary and request only the "
        "minimum required input."
    )


def test_v22_ss645_workitem_labels_count_and_ids_are_v21_exec_001_through_021():
    assert len(V22_SS645_WORKITEM_LABELS) == 21
    ids = [work_item_id for work_item_id, _label in V22_SS645_WORKITEM_LABELS]
    assert ids == [f"V21-EXEC-{n:03d}" for n in range(1, 22)]
    assert V22_SS645_WORKITEM_LABELS[0] == ("V21-EXEC-001", "contract discovery")
    assert V22_SS645_WORKITEM_LABELS[-1] == ("V21-EXEC-021", "genuine boundary handling")


def test_verify_ordinal_alignment_lines_up_both_transcriptions():
    aligned = verify_ordinal_alignment()
    assert len(aligned) == 21
    # Position 10 in both sources: SS645 label "auto implementation" <-> SS638 step 10 text.
    ordinal, work_item_id, step_text = aligned[9]
    assert ordinal == 10
    assert work_item_id == "V21-EXEC-010"
    assert step_text == "Automatically implement/repair every internally resolvable gap."


def test_verify_ordinal_alignment_raises_on_length_drift(monkeypatch):
    import dv_harness.l5dgva_directive_registry as mod

    monkeypatch.setattr(mod, "V21_SS638_STEP_TEXTS", mod.V21_SS638_STEP_TEXTS[:-1])
    with pytest.raises(ValueError, match="drifted"):
        mod.verify_ordinal_alignment()


# ---------------------------------------------------------------------------
# DirectiveRecord / WorkItemDescriptor schema
# ---------------------------------------------------------------------------


def test_directive_record_requires_real_identity_fields():
    with pytest.raises(ValueError):
        DirectiveRecord(directive_id="", source_contract="V21", source_section="638", directive_text_ref="x")
    with pytest.raises(ValueError):
        DirectiveRecord(directive_id="X", source_contract="", source_section="638", directive_text_ref="x")


def test_directive_record_unassigned_fields_default_none_not_guessed():
    record = DirectiveRecord(
        directive_id="X", source_contract="V21", source_section="638", directive_text_ref="ref"
    )
    assert record.action_type is None
    assert record.required_engine is None
    assert record.graph_node is None
    assert record.gate is None
    assert record.trigger is None
    assert record.dependencies == ()
    assert record.work_item_ids == ()
    assert record.evidence_refs == ()
    assert record.verdict is None
    # execution_state reuses WorkItemState verbatim, never a locally-invented enum.
    assert record.execution_state is WorkItemState.DISCOVERED


def test_work_item_descriptor_requires_real_fields():
    with pytest.raises(ValueError):
        WorkItemDescriptor(work_item_id="", label="x", source_step_number=1, source_step_text="y")
    with pytest.raises(ValueError):
        WorkItemDescriptor(work_item_id="X", label="x", source_step_number=0, source_step_text="y")


# ---------------------------------------------------------------------------
# ExecutableDirectiveRegistry: create/reconcile semantics (SS643's own verb)
# ---------------------------------------------------------------------------


def _record(directive_id="X", **overrides):
    defaults = dict(
        directive_id=directive_id, source_contract="V21", source_section="638", directive_text_ref="ref"
    )
    defaults.update(overrides)
    return DirectiveRecord(**defaults)


def test_register_then_get_and_all():
    registry = ExecutableDirectiveRegistry()
    record = _record()
    registry.register(record)
    assert registry.get("X") == record
    assert registry.all() == (record,)
    assert len(registry) == 1


def test_register_identical_record_twice_is_idempotent_reconcile():
    registry = ExecutableDirectiveRegistry()
    record = _record()
    registry.register(record)
    registry.register(record)  # same content -> real reconcile, not a duplicate
    assert len(registry) == 1


def test_register_conflicting_record_same_id_raises():
    registry = ExecutableDirectiveRegistry()
    registry.register(_record(directive_id="X", source_section="638"))
    with pytest.raises(ValueError, match="conflicting"):
        registry.register(_record(directive_id="X", source_section="639"))


def test_reconcile_bulk_registers_multiple_records():
    registry = ExecutableDirectiveRegistry()
    registry.reconcile((_record(directive_id="A"), _record(directive_id="B")))
    assert len(registry) == 2
    assert {r.directive_id for r in registry.all()} == {"A", "B"}


def test_get_missing_directive_returns_none():
    registry = ExecutableDirectiveRegistry()
    assert registry.get("does-not-exist") is None


# ---------------------------------------------------------------------------
# The real worked-example seeding (SS645 over V21 SS638)
# ---------------------------------------------------------------------------


def test_seed_v21_ss638_directive_real_fields():
    directive = seed_v21_ss638_directive()
    assert directive.directive_id == "V21-SS638-IMMEDIATE-EXECUTION"
    assert "V21" in directive.source_contract
    assert directive.source_section == "638"
    assert "638" in directive.directive_text_ref
    assert directive.trigger == V21_SS638_TRIGGER
    assert directive.work_item_ids == tuple(f"V21-EXEC-{n:03d}" for n in range(1, 22))
    assert directive.execution_state is WorkItemState.DISCOVERED


def test_seed_v21_ss638_directive_never_fabricates_unassignable_fields():
    directive = seed_v21_ss638_directive()
    assert directive.action_type is None
    assert directive.required_engine is None
    assert directive.graph_node is None
    assert directive.gate is None
    assert directive.dependencies == ()
    assert directive.evidence_refs == ()
    assert directive.verdict is None
    assert FIELD_NOT_YET_ASSIGNED_REASON  # non-empty, real, shared (not per-field) sentence


def test_seed_v21_exec_workitem_descriptors_count_and_identity():
    descriptors = seed_v21_exec_workitem_descriptors()
    assert len(descriptors) == 21
    ids = [d.work_item_id for d in descriptors]
    assert ids == [f"V21-EXEC-{n:03d}" for n in range(1, 22)]
    first = descriptors[0]
    assert first.label == "contract discovery"
    assert first.source_step_number == 1
    assert first.source_step_text == "Locate ALL configured governing contract Markdown files."
    assert first.execution_state is WorkItemState.DISCOVERED
    assert first.verdict is None


def test_seed_v21_exec_workitem_descriptors_last_item():
    descriptors = seed_v21_exec_workitem_descriptors()
    last = descriptors[-1]
    assert last.work_item_id == "V21-EXEC-021"
    assert last.label == "genuine boundary handling"
    assert last.source_step_number == 21
    assert last.source_step_text == (
        "Stop only at genuine Human/Authority/External boundary and request only the "
        "minimum required input."
    )


def test_seed_registry_returns_one_directive_and_21_workitems():
    registry, descriptors = seed_registry()
    assert len(registry) == 1
    directive = registry.get("V21-SS638-IMMEDIATE-EXECUTION")
    assert directive is not None
    assert len(descriptors) == 21
    # The directive's own work_item_ids must be exactly the descriptor catalog's ids, in order.
    assert directive.work_item_ids == tuple(d.work_item_id for d in descriptors)


def test_seed_registry_is_idempotent_when_called_twice_into_same_registry():
    registry, _ = seed_registry()
    # Re-registering the same real seed must not raise (identical content -> reconcile).
    registry.register(seed_v21_ss638_directive())
    assert len(registry) == 1
