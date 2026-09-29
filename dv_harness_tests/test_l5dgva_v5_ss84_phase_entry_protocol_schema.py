"""Tests for `dv_harness/l5dgva_v5_ss84_phase_entry_protocol_schema.py` --
L5DGVA V5 section 84 "Mandatory Phase Entry Protocol" schema + real
`gates.STAGE_GATES` name-coverage scan. See that module's own docstring for
the primary-source quote and scope decision (schema-only; PASS stays
honestly unreachable without a live phase boundary).

Ported from Parent (M5 Capability Pool Closure, CAP-POOL-008), 9/9
independently re-run and confirmed passing in Parent's own tree before
being trusted. The coverage-count assertions (test_stage_gates_
coverage_count_matches_disclosed_honest_finding and the specific
MATCHED/NOT_MATCHED phase assertions) were independently re-verified
against canonical's own real (smaller) `gates.STAGE_GATES` registry
before porting -- the result is identical to Parent's, so no adaptation
was needed.
"""
from __future__ import annotations

from dv_harness import l5dgva_v5_ss84_phase_entry_protocol_schema as m


def test_fourteen_steps_present_in_order():
    assert len(m.PHASE_ENTRY_STEPS) == 14
    ids = [step_id for step_id, _ in m.PHASE_ENTRY_STEPS]
    assert ids == list(range(1, 15))
    # Spot-check verbatim text of first/last steps against the primary quote.
    assert m.PHASE_ENTRY_STEPS[0][1] == "identify phase/scope/profile"
    assert m.PHASE_ENTRY_STEPS[-1][1] == "execute only after PASS"


def test_fifteen_material_phases_present():
    assert len(m.MATERIAL_PHASES) == 15
    assert "intake" in m.MATERIAL_PHASES
    assert "external-resolution resume" in m.MATERIAL_PHASES


def test_evaluate_with_no_evidence_reports_all_fourteen_missing():
    record = m.build_phase_entry_record("intake", evidence=None)
    verdict = m.evaluate_mandatory_phase_entry_protocol(record)
    assert verdict.pass_ is False
    assert verdict.missing_step_ids == tuple(range(1, 15))


def test_evaluate_with_partial_evidence_reports_only_missing_steps():
    evidence = {i: f"evidence-for-step-{i}" for i in range(1, 14)}  # steps 1..13
    record = m.build_phase_entry_record("build", evidence=evidence)
    verdict = m.evaluate_mandatory_phase_entry_protocol(record)
    assert verdict.pass_ is False
    assert verdict.missing_step_ids == (14,)


def test_evaluate_with_full_evidence_passes():
    evidence = {i: f"evidence-for-step-{i}" for i in range(1, 15)}
    record = m.build_phase_entry_record("signoff", evidence=evidence)
    verdict = m.evaluate_mandatory_phase_entry_protocol(record)
    assert verdict.pass_ is True
    assert verdict.missing_step_ids == ()


def test_empty_string_evidence_ref_does_not_count_as_satisfied():
    record = m.build_phase_entry_record("debug", evidence={1: ""})
    verdict = m.evaluate_mandatory_phase_entry_protocol(record)
    assert 1 in verdict.missing_step_ids


def test_stage_gates_phase_name_coverage_is_a_real_static_fact():
    """Re-derived fresh against the real `dv_harness.gates.STAGE_GATES`
    dict -- this is not a hand-typed expectation of what SHOULD be true, it
    is the module's own honest finding, re-confirmed here as a regression."""
    coverage = m.stage_gates_phase_name_coverage()
    assert set(coverage.keys()) == set(m.MATERIAL_PHASES)

    assert coverage["intake"].status == m.MATCHED
    assert "INTAKE" in coverage["intake"].matched_stage_keys

    assert coverage["vPlan"].status == m.MATCHED
    assert "VPLAN" in coverage["vPlan"].matched_stage_keys

    assert coverage["build"].status == m.MATCHED
    assert coverage["signoff"].status == m.MATCHED
    assert coverage["change impact"].status == m.MATCHED

    # Disclosed real gaps: no STAGE_GATES key's name contains any of these.
    assert coverage["elaboration"].status == m.NOT_MATCHED
    assert coverage["smoke"].status == m.NOT_MATCHED
    assert coverage["external-resolution resume"].status == m.NOT_MATCHED


def test_stage_gates_phase_name_coverage_reads_real_gates_module():
    """Cross-check against `dv_harness.gates.STAGE_GATES` directly -- proves
    this module has no second, hand-maintained copy of the stage list that
    could silently drift."""
    from dv_harness import gates as real_gates

    coverage = m.stage_gates_phase_name_coverage()
    all_matched_keys = {
        key
        for c in coverage.values()
        for key in c.matched_stage_keys
    }
    assert all_matched_keys <= set(real_gates.STAGE_GATES.keys())


def test_stage_gates_coverage_count_matches_disclosed_honest_finding():
    coverage = m.stage_gates_phase_name_coverage()
    matched = [p for p, c in coverage.items() if c.status == m.MATCHED]
    not_matched = [p for p, c in coverage.items() if c.status == m.NOT_MATCHED]
    assert len(matched) == 12
    assert len(not_matched) == 3
