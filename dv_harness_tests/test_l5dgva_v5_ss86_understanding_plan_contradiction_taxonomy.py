"""Tests for `dv_harness/l5dgva_v5_ss86_understanding_plan_contradiction_
taxonomy.py` -- L5DGVA V5 section 86 "Behavioral Proof of Understanding".
See that module's own docstring for the primary-source quote and scope
decision (taxonomy + classifier + record schema over caller-supplied facts;
the live PASS stays honestly NOT_ATTEMPTED for this codebase's real state)."""
from __future__ import annotations

import pytest

from dv_harness import (
    l5dgva_v5_ss86_understanding_plan_contradiction_taxonomy as m,
)


def test_six_named_patterns_present():
    assert len(m.CONTRADICTION_PATTERNS) == 6
    assert len(m.PATTERN_IDS) == 6
    assert "DE_CPUWRITE_NO_CONTROL_PLANE_VIP" in m.PATTERN_IDS
    assert (
        "CANONICAL_FILESYSTEM_ENTRY_POINTS_RELOCATED_WITHOUT_JUSTIFICATION"
        in m.PATTERN_IDS
    )


def test_classify_with_no_facts_finds_nothing_triggered():
    findings = m.classify_understanding_plan_contradictions({})
    assert len(findings) == 6
    assert all(f.triggered is False for f in findings)


def test_classify_cpuwrite_example_triggers_when_plan_omits_control_plane_vip():
    facts = {"de_cpuwrite_exists": True}  # control_plane_vip_in_plan absent -> False
    findings = m.classify_understanding_plan_contradictions(facts)
    by_id = {f.pattern_id: f for f in findings}
    assert by_id["DE_CPUWRITE_NO_CONTROL_PLANE_VIP"].triggered is True
    # every other pattern's understanding fact is absent -> not triggered
    assert sum(f.triggered for f in findings) == 1


def test_classify_cpuwrite_example_does_not_trigger_when_plan_reflects_it():
    facts = {"de_cpuwrite_exists": True, "control_plane_vip_in_plan": True}
    findings = m.classify_understanding_plan_contradictions(facts)
    by_id = {f.pattern_id: f for f in findings}
    assert by_id["DE_CPUWRITE_NO_CONTROL_PLANE_VIP"].triggered is False


def test_classify_all_six_can_trigger_simultaneously():
    facts = {
        "de_cpuwrite_exists": True,
        "reference_partition_compile_exists": True,
        "reference_has_material_block_bringup": True,
        "external_protocol_requires_top_io": True,
        "qualified_subsystem_environments_exist": True,
        "canonical_reference_filesystem_entry_points_relocated": True,
        # deliberately no *_in_plan / *_preserves_* / *_material / *_at_top_io /
        # *_evaluates_reuse / *_justification_recorded facts supplied
    }
    findings = m.classify_understanding_plan_contradictions(facts)
    assert all(f.triggered for f in findings)


def test_record_rejects_unknown_pattern_id():
    with pytest.raises(ValueError):
        m.UnderstandingPlanContradictionRecord(
            contradiction_id="C-1",
            pattern_id="NOT_A_REAL_PATTERN",
            phase="architecture",
            understanding_evidence_ref="ref-a",
            plan_evidence_ref="ref-b",
        )


def test_gate_with_no_records_is_insufficient_evidence():
    verdict = m.behavioral_proof_of_understanding_gate(())
    assert verdict.pass_ == "INSUFFICIENT_EVIDENCE"


def test_gate_fails_on_unresolved_contradiction():
    record = m.UnderstandingPlanContradictionRecord(
        contradiction_id="C-1",
        pattern_id="DE_CPUWRITE_NO_CONTROL_PLANE_VIP",
        phase="architecture",
        understanding_evidence_ref="ref-a",
        plan_evidence_ref="ref-b",
    )
    verdict = m.behavioral_proof_of_understanding_gate((record,))
    assert verdict.pass_ == "FAIL"
    assert "C-1" in verdict.unresolved_contradiction_ids


def test_gate_passes_only_once_reconciled():
    record = m.UnderstandingPlanContradictionRecord(
        contradiction_id="C-1",
        pattern_id="DE_CPUWRITE_NO_CONTROL_PLANE_VIP",
        phase="architecture",
        understanding_evidence_ref="ref-a",
        plan_evidence_ref="ref-b",
        reconciliation_action="Added control-plane VIP agent to plan.",
        reconciliation_verdict=m.RECONCILED,
    )
    verdict = m.behavioral_proof_of_understanding_gate((record,))
    assert verdict.pass_ == "PASS"
    assert verdict.unresolved_contradiction_ids == ()
