"""Tests for dv_harness/debug_evidence_behavioral_firewall_gate.py -- L5DGVA
V17 SS475 ("GUI Escalation") and SS489 ("Debug Behavioral Firewall")."""
from __future__ import annotations

from dv_harness.debug_evidence_behavioral_firewall_gate import (
    CHECKLIST_ITEM_NAMES,
    DebugEvidenceChecklist,
    evaluate_debug_behavioral_firewall,
)


def _full_checklist(**overrides) -> DebugEvidenceChecklist:
    base = dict(
        existing_diagnostics_checked=True,
        logs_checked=True,
        current_fsdb_scope_gap_only=True,
        reference_wave_config_studied=True,
        targeted_scope_extension_possible=True,
        fsdbreport_attempted_after_scope_exists=True,
        gui_truly_next_best=True,
    )
    base.update(overrides)
    return DebugEvidenceChecklist(**base)


def test_checklist_has_seven_items_in_contract_order():
    assert CHECKLIST_ITEM_NAMES == (
        "existing_diagnostics_checked",
        "logs_checked",
        "current_fsdb_scope_gap_only",
        "reference_wave_config_studied",
        "targeted_scope_extension_possible",
        "fsdbreport_attempted_after_scope_exists",
        "gui_truly_next_best",
    )


def test_vacuous_pass_when_nothing_declared():
    """No debug-path-unavailable declaration and no GUI escalation ->
    nothing to gate; both flags PASS even with an entirely empty checklist."""
    checklist = DebugEvidenceChecklist()
    result = evaluate_debug_behavioral_firewall(checklist)
    assert result.DebugBehavioralFirewall_PASS is True
    assert result.NoPrematureGUIDebugEscalation_PASS is True
    assert result.violations == ()


def test_firewall_pass_when_all_items_satisfied_and_path_declared_unavailable():
    checklist = _full_checklist(debug_path_declared_unavailable=True)
    result = evaluate_debug_behavioral_firewall(checklist)
    assert result.DebugBehavioralFirewall_PASS is True
    assert result.unevaluated_items == ()
    assert result.failed_items == ()


def test_firewall_fails_on_declared_unavailable_with_missing_item():
    checklist = _full_checklist(
        debug_path_declared_unavailable=True,
        reference_wave_config_studied=None,
    )
    result = evaluate_debug_behavioral_firewall(checklist)
    assert result.DebugBehavioralFirewall_PASS is False
    assert "reference_wave_config_studied" in result.unevaluated_items
    assert any("SS489" in v for v in result.violations)


def test_firewall_fails_on_declared_unavailable_with_explicit_false_item():
    checklist = _full_checklist(
        debug_path_declared_unavailable=True,
        logs_checked=False,
    )
    result = evaluate_debug_behavioral_firewall(checklist)
    assert result.DebugBehavioralFirewall_PASS is False
    assert "logs_checked" in result.failed_items


def test_gui_escalation_pass_when_prerequisites_satisfied():
    checklist = _full_checklist(gui_escalation_declared=True)
    result = evaluate_debug_behavioral_firewall(checklist)
    assert result.NoPrematureGUIDebugEscalation_PASS is True


def test_premature_gui_escalation_detected_when_prerequisite_missing():
    """The canonical SS475 violation: concluding GUI is required merely
    because current FSDB lacks a signal, without having checked logs or
    existing diagnostics first."""
    checklist = DebugEvidenceChecklist(
        gui_escalation_declared=True,
        current_fsdb_scope_gap_only=True,
        # existing_diagnostics_checked / logs_checked left None (not done)
    )
    result = evaluate_debug_behavioral_firewall(checklist)
    assert result.NoPrematureGUIDebugEscalation_PASS is False
    assert any("SS475" in v for v in result.violations)
    # gui_truly_next_best is the ONLY item excluded from the GUI-prerequisite
    # check (it IS the GUI conclusion itself), so it must never appear in a
    # SS475 violation's own "bad" list.
    ss475_violation = next(v for v in result.violations if "SS475" in v)
    assert "gui_truly_next_best" not in ss475_violation


def test_premature_gui_escalation_independent_of_debug_path_declaration():
    """GUI escalation can be declared premature even if the caller never
    separately declared the whole debug path unavailable -- SS475 and SS489
    are judged independently."""
    checklist = DebugEvidenceChecklist(
        debug_path_declared_unavailable=False,
        gui_escalation_declared=True,
    )
    result = evaluate_debug_behavioral_firewall(checklist)
    assert result.DebugBehavioralFirewall_PASS is True  # nothing declared unavailable
    assert result.NoPrematureGUIDebugEscalation_PASS is False  # but GUI was premature


def test_to_dict_round_trip_shape():
    checklist = _full_checklist(debug_path_declared_unavailable=True, gui_escalation_declared=True)
    result = evaluate_debug_behavioral_firewall(checklist)
    d = result.to_dict()
    assert d["DebugBehavioralFirewall_PASS"] is True
    assert d["NoPrematureGUIDebugEscalation_PASS"] is True
    assert d["violations"] == []
