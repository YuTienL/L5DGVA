"""Tests for dv_harness/amba_readiness_gates.py -- the 9 named AMBA composite
readiness gates transcribed from sections 71-80 of the AMBA M x N golden-flow
source document. Real fixtures throughout; no mocks (the module under test has
no external dependency to mock -- it is a pure function over caller-supplied
condition records)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.amba_readiness_gates import (
    GATE_NAMES,
    GATE_REQUIRED_CONDITIONS,
    GATE_READY,
    GATE_NOT_READY,
    GATE_INCOMPLETE_EVIDENCE,
    CONDITION_STATUSES,
    AmbaReadinessGatesError,
    evaluate_gate,
    evaluate_amba_readiness_gates,
    render_readiness_report,
    _assert_no_verification_verdict_vocabulary,
    _assert_gate_table_well_formed,
)


def _condition(name, status, reason=None):
    record = {"condition_name": name, "status": status}
    if reason is not None:
        record["reason"] = reason
    return record


def _all_leaf_condition_names():
    """Every AND-term across all 9 gates that is NOT itself a sub-gate name --
    the real leaf evidence a caller would have to supply for every gate to have
    a chance at READY."""
    leaves = []
    for gate_name in GATE_NAMES:
        for term in GATE_REQUIRED_CONDITIONS[gate_name]:
            if term not in GATE_NAMES and term not in leaves:
                leaves.append(term)
    return leaves


def _all_met_conditions():
    return [_condition(name, "MET") for name in _all_leaf_condition_names()]


# --------------------------------------------------------------------------
# Structural / vocabulary sanity
# --------------------------------------------------------------------------


def test_the_9_gate_names_match_the_source_document_verbatim():
    assert GATE_NAMES == (
        "L3_REFERENCE_READY",
        "AMBA_PORT_REGISTRY_READY",
        "AMBA_CONSTRAINT_READY",
        "AMBA_CONNECTIVITY_READY",
        "AMBA_VIP_BIND_READY",
        "AMBA_SCOREBOARD_READY",
        "AMBA_COVERAGE_READY",
        "AMBA_TEST_GENERATION_READY",
        "AMBA_SIGNOFF_READY",
    )


def test_l3_reference_ready_conditions_match_section_72():
    assert GATE_REQUIRED_CONDITIONS["L3_REFERENCE_READY"] == (
        "L3_Source_Found",
        "L3_Inventory_Complete",
        "L3_Baseline_Preserved",
        "Required_Build_Run_Context_Discovered",
        "Critical_UNKNOWN",
    )


def test_amba_signoff_ready_conditions_match_section_80():
    assert GATE_REQUIRED_CONDITIONS["AMBA_SIGNOFF_READY"] == (
        "Required_vPlan_Items_Closed",
        "Required_Legal_Connectivity_Edges_Closed",
        "Required_Functional_Coverage_Items_Closed",
        "Required_Regression_PASS",
        "VIP_Protocol_Evidence_Valid",
        "SyoSil_Scoreboard_Evidence_Valid",
        "Critical_Unresolved_Failure",
        "Critical_UNKNOWN",
        "Traceability_Complete",
        "Evidence_Complete",
    )


def test_amba_test_generation_ready_references_three_sub_gates_per_section_79():
    terms = GATE_REQUIRED_CONDITIONS["AMBA_TEST_GENERATION_READY"]
    assert "AMBA_CONSTRAINT_READY" in terms
    assert "AMBA_CONNECTIVITY_READY" in terms
    assert "AMBA_VIP_BIND_READY" in terms


def test_vocabulary_does_not_collide_with_models_status():
    # Raises AssertionError on collision; must not raise here.
    _assert_no_verification_verdict_vocabulary()


def test_gate_table_is_well_formed():
    # Raises AssertionError if malformed; must not raise here.
    _assert_gate_table_well_formed()


# --------------------------------------------------------------------------
# Core positive path
# --------------------------------------------------------------------------


def test_all_conditions_met_makes_every_gate_ready_including_derived_sub_gates():
    conditions = _all_met_conditions()
    report = evaluate_amba_readiness_gates(conditions)
    for gate_name in GATE_NAMES:
        assert report.verdict_for(gate_name) == GATE_READY, gate_name
    assert report.worst_verdict() == GATE_READY
    # The 3 sub-gate references inside AMBA_TEST_GENERATION_READY were never
    # supplied directly -- they must have been DERIVED from the already-
    # computed sub-gate verdicts, not silently ignored.
    tgr = report.gates["AMBA_TEST_GENERATION_READY"]
    derived = {c.condition_name: c for c in tgr.conditions if c.is_sub_gate_reference}
    assert set(derived) == {
        "AMBA_CONSTRAINT_READY",
        "AMBA_CONNECTIVITY_READY",
        "AMBA_VIP_BIND_READY",
    }
    for cond in derived.values():
        assert cond.status == "MET"
        assert cond.source == "derived_from_sub_gate"


# --------------------------------------------------------------------------
# Worst-wins, no-averaging negative controls
# --------------------------------------------------------------------------


def test_a_single_unmet_condition_blocks_the_whole_gate_regardless_of_others():
    conditions = [
        _condition("Required_Master_Slave_Edges_Resolved", "MET"),
        _condition("Required_Memory_Map_Resolved", "MET"),
        _condition("RTL_Spec_Address_Correlation_Complete", "MET"),
        _condition("Critical_Address_Conflict", "UNMET", reason="1 real address overlap found"),
        _condition("Critical_Connectivity_Conflict", "MET"),
        _condition("Critical_UNKNOWN", "MET"),
    ]
    gate = evaluate_gate("AMBA_CONNECTIVITY_READY", conditions)
    assert gate.verdict == GATE_NOT_READY
    assert gate.blocking_conditions == ["Critical_Address_Conflict"]
    assert gate.incomplete_conditions == []


def test_unknown_condition_is_incomplete_evidence_not_ready_not_blocked():
    conditions = [
        _condition("L3_Source_Found", "MET"),
        _condition("L3_Inventory_Complete", "MET"),
        _condition("L3_Baseline_Preserved", "UNKNOWN", reason="no baseline snapshot recorded yet"),
        _condition("Required_Build_Run_Context_Discovered", "MET"),
        _condition("Critical_UNKNOWN", "MET"),
    ]
    gate = evaluate_gate("L3_REFERENCE_READY", conditions)
    assert gate.verdict == GATE_INCOMPLETE_EVIDENCE
    assert gate.blocking_conditions == []
    assert gate.incomplete_conditions == ["L3_Baseline_Preserved"]


def test_not_available_condition_is_also_incomplete_evidence():
    conditions = [
        _condition("L3_Source_Found", "MET"),
        _condition("L3_Inventory_Complete", "MET"),
        _condition("L3_Baseline_Preserved", "MET"),
        _condition(
            "Required_Build_Run_Context_Discovered",
            "NOT_AVAILABLE",
            reason="no Makefile/regression.list found on disk",
        ),
        _condition("Critical_UNKNOWN", "MET"),
    ]
    gate = evaluate_gate("L3_REFERENCE_READY", conditions)
    assert gate.verdict == GATE_INCOMPLETE_EVIDENCE
    assert gate.incomplete_conditions == ["Required_Build_Run_Context_Discovered"]


def test_a_condition_never_supplied_reads_as_incomplete_evidence_never_silent_ready():
    # Only 4 of L3_REFERENCE_READY's 5 conditions are supplied.
    conditions = [
        _condition("L3_Source_Found", "MET"),
        _condition("L3_Inventory_Complete", "MET"),
        _condition("L3_Baseline_Preserved", "MET"),
        _condition("Required_Build_Run_Context_Discovered", "MET"),
        # Critical_UNKNOWN is simply absent from the caller's list.
    ]
    gate = evaluate_gate("L3_REFERENCE_READY", conditions)
    assert gate.verdict == GATE_INCOMPLETE_EVIDENCE
    assert gate.incomplete_conditions == ["Critical_UNKNOWN"]
    missing = [c for c in gate.conditions if c.condition_name == "Critical_UNKNOWN"][0]
    assert missing.status == "UNKNOWN"
    assert missing.source == "not_supplied"


def test_unmet_outranks_unknown_on_the_same_gate():
    conditions = [
        _condition("Required_Fabric_Ports_Discovered", "UNMET", reason="2 masters undiscovered"),
        _condition("Required_Roles_Resolved", "UNKNOWN"),
        _condition("Required_Hierarchy_Trace_Complete", "MET"),
        _condition("Required_Clock_Reset_Resolved", "MET"),
        _condition("Critical_UNKNOWN", "MET"),
    ]
    gate = evaluate_gate("AMBA_PORT_REGISTRY_READY", conditions)
    assert gate.verdict == GATE_NOT_READY
    assert gate.blocking_conditions == ["Required_Fabric_Ports_Discovered"]
    # Both facts are still reported, worst-wins does not hide the lesser one.
    assert gate.incomplete_conditions == ["Required_Roles_Resolved"]


# --------------------------------------------------------------------------
# Cross-gate propagation (AMBA_TEST_GENERATION_READY's sub-gate references)
# --------------------------------------------------------------------------


def test_an_unmet_sub_gate_condition_propagates_to_block_test_generation_ready():
    conditions = _all_met_conditions()
    # Break one of AMBA_CONSTRAINT_READY's own leaf conditions.
    for record in conditions:
        if record["condition_name"] == "Required_Ordering_Resolved":
            record["status"] = "UNMET"
            record["reason"] = "ordering policy not resolved for M2"

    report = evaluate_amba_readiness_gates(conditions)
    assert report.verdict_for("AMBA_CONSTRAINT_READY") == GATE_NOT_READY
    tgr = report.gates["AMBA_TEST_GENERATION_READY"]
    assert tgr.verdict == GATE_NOT_READY
    assert "AMBA_CONSTRAINT_READY" in tgr.blocking_conditions
    # Sibling sub-gates untouched by the mutation still resolve READY.
    assert report.verdict_for("AMBA_CONNECTIVITY_READY") == GATE_READY
    assert report.verdict_for("AMBA_VIP_BIND_READY") == GATE_READY


def test_caller_supplied_sub_gate_override_wins_over_derived_verdict():
    conditions = _all_met_conditions()
    # AMBA_CONSTRAINT_READY's own leaves would compute NOT_READY...
    for record in conditions:
        if record["condition_name"] == "Required_Ordering_Resolved":
            record["status"] = "UNMET"
    # ...but the caller explicitly asserts the sub-gate condition itself as MET
    # (e.g. a human override / an already-recorded prior evaluation).
    conditions.append(
        _condition("AMBA_CONSTRAINT_READY", "MET", reason="human-reviewed override")
    )

    report = evaluate_amba_readiness_gates(conditions)
    # The sub-gate's OWN evaluation still honestly reports NOT_READY...
    assert report.verdict_for("AMBA_CONSTRAINT_READY") == GATE_NOT_READY
    # ...but AMBA_TEST_GENERATION_READY consumed the explicit override, not the
    # derived value, for its own AMBA_CONSTRAINT_READY term.
    tgr = report.gates["AMBA_TEST_GENERATION_READY"]
    override = [c for c in tgr.conditions if c.condition_name == "AMBA_CONSTRAINT_READY"][0]
    assert override.status == "MET"
    assert override.source == "caller_supplied"
    assert tgr.verdict == GATE_READY


# --------------------------------------------------------------------------
# Malformed-input negative controls
# --------------------------------------------------------------------------


def test_non_list_conditions_raises():
    with pytest.raises(AmbaReadinessGatesError):
        evaluate_amba_readiness_gates({"not": "a list"})


def test_missing_condition_name_raises():
    with pytest.raises(AmbaReadinessGatesError):
        evaluate_amba_readiness_gates([{"status": "MET"}])


def test_unrecognized_status_raises():
    with pytest.raises(AmbaReadinessGatesError):
        evaluate_amba_readiness_gates(
            [{"condition_name": "L3_Source_Found", "status": "PROBABLY_FINE"}]
        )


def test_duplicate_condition_name_raises():
    with pytest.raises(AmbaReadinessGatesError):
        evaluate_amba_readiness_gates(
            [
                _condition("L3_Source_Found", "MET"),
                _condition("L3_Source_Found", "UNMET"),
            ]
        )


def test_unknown_gate_name_raises():
    with pytest.raises(AmbaReadinessGatesError):
        evaluate_gate("NOT_A_REAL_GATE", [])


def test_non_string_reason_raises():
    with pytest.raises(AmbaReadinessGatesError):
        evaluate_amba_readiness_gates(
            [{"condition_name": "L3_Source_Found", "status": "MET", "reason": 12345}]
        )


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def test_render_readiness_report_names_every_gate_and_its_verdict():
    report = evaluate_amba_readiness_gates(_all_met_conditions())
    text = render_readiness_report(report)
    for gate_name in GATE_NAMES:
        assert gate_name in text
    assert "Worst verdict across all 9 gates: READY" in text


# --------------------------------------------------------------------------
# CLI (real subprocesses)
# --------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(args, cwd=_REPO_ROOT):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.amba_readiness_gates"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_cli_gates_verb_lists_all_9_names():
    result = _run_cli(["gates", "--json"])
    assert result.returncode == 0
    assert json.loads(result.stdout) == list(GATE_NAMES)


def test_cli_conditions_verb_lists_one_gates_terms():
    result = _run_cli(["conditions", "--gate", "AMBA_SCOREBOARD_READY", "--json"])
    assert result.returncode == 0
    assert json.loads(result.stdout) == list(
        GATE_REQUIRED_CONDITIONS["AMBA_SCOREBOARD_READY"]
    )


def test_cli_evaluate_verb_all_met_exits_zero(tmp_path):
    conditions_file = tmp_path / "conditions.json"
    conditions_file.write_text(json.dumps(_all_met_conditions()), encoding="utf-8")
    result = _run_cli(["evaluate", "--conditions", str(conditions_file), "--json"])
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["AMBA_SIGNOFF_READY"]["verdict"] == GATE_READY


def test_cli_evaluate_verb_with_a_blocker_exits_nonzero(tmp_path):
    conditions = _all_met_conditions()
    for record in conditions:
        if record["condition_name"] == "Required_Regression_PASS":
            record["status"] = "UNMET"
    conditions_file = tmp_path / "conditions.json"
    conditions_file.write_text(json.dumps(conditions), encoding="utf-8")
    result = _run_cli(["evaluate", "--conditions", str(conditions_file), "--json"])
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["AMBA_SIGNOFF_READY"]["verdict"] == GATE_NOT_READY


def test_cli_evaluate_verb_missing_file_exits_not_available(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    result = _run_cli(["evaluate", "--conditions", str(missing)])
    assert result.returncode == 2
