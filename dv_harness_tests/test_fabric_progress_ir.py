"""Tests for dv_harness/fabric_progress_ir.py."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from dv_harness.fabric_progress_ir import (
    FabricProgressIrError,
    analyze_credit_outstanding,
    analyze_fabric_progress,
    analyze_resource_dependency_cycle,
    assert_no_verification_verdict_vocabulary,
)


# ---------------------------------------------------------------------------
# Resource-dependency circular-wait detection: core positive path.
# ---------------------------------------------------------------------------


def test_no_cycle_detected_over_a_clean_fully_resolved_graph():
    facts = [
        {"resource": "PORT0_GRANT", "held_by": "AGENT_A", "waiting_for": "PORT1_GRANT"},
        {"resource": "PORT1_GRANT", "held_by": "AGENT_B", "waiting_for": None},
    ]
    finding = analyze_resource_dependency_cycle(facts)
    assert finding.status == "NO_CYCLE_DETECTED"
    assert finding.cycle is None
    assert finding.unresolved == []
    assert finding.ambiguous_resources == []


def test_circular_wait_detected_names_the_real_cycle():
    # A holds R1, waits for R2 (held by B). B holds R2, waits for R3 (held by
    # C). C holds R3, waits for R1 (held by A). A real 3-way circular wait.
    facts = [
        {"resource": "R1", "held_by": "A", "waiting_for": "R2"},
        {"resource": "R2", "held_by": "B", "waiting_for": "R3"},
        {"resource": "R3", "held_by": "C", "waiting_for": "R1"},
    ]
    finding = analyze_resource_dependency_cycle(facts)
    assert finding.status == "CIRCULAR_WAIT_DETECTED"
    assert finding.cycle is not None
    # The cycle must actually name all three real holders.
    assert set(finding.cycle) == {"A", "B", "C"}
    # And each hop must cite a real resource/holder pair from the input.
    detail_holders = {(hop["holder"], hop["waiting_for_resource"], hop["held_by"]) for hop in finding.cycle_detail}
    assert ("A", "R2", "B") in detail_holders
    assert ("B", "R3", "C") in detail_holders
    assert ("C", "R1", "A") in detail_holders
    assert "circular wait" in finding.reason.lower()


def test_self_loop_cycle_is_detected():
    # A holds R1 and is waiting for R1 itself (a degenerate but real cycle).
    facts = [{"resource": "R1", "held_by": "A", "waiting_for": "R1"}]
    finding = analyze_resource_dependency_cycle(facts)
    assert finding.status == "CIRCULAR_WAIT_DETECTED"
    assert finding.cycle == ["A", "A"]


def test_multiple_facts_for_same_holder_are_merged_into_one_node():
    # A holds R1 (waits for R2) and also holds R2's sibling info... merge
    # edges from two facts sharing held_by=A.
    facts = [
        {"resource": "R1", "held_by": "A", "waiting_for": "R2"},
        {"resource": "R4", "held_by": "A", "waiting_for": None},
        {"resource": "R2", "held_by": "B", "waiting_for": None},
    ]
    finding = analyze_resource_dependency_cycle(facts)
    assert finding.status == "NO_CYCLE_DETECTED"


# ---------------------------------------------------------------------------
# Resource-dependency: negative controls (the Evidence Truth Rule enforced).
# ---------------------------------------------------------------------------


def test_empty_resource_dependency_facts_is_insufficient_evidence():
    finding = analyze_resource_dependency_cycle([])
    assert finding.status == "INSUFFICIENT_EVIDENCE"
    assert finding.cycle is None


def test_dangling_waiting_for_reference_is_insufficient_evidence_never_no_cycle():
    # A waits for a resource nobody in the graph holds. This must NEVER
    # silently report NO_CYCLE_DETECTED -- the graph is incomplete.
    facts = [{"resource": "R1", "held_by": "A", "waiting_for": "R99_NEVER_DECLARED"}]
    finding = analyze_resource_dependency_cycle(facts)
    assert finding.status == "INSUFFICIENT_EVIDENCE"
    assert len(finding.unresolved) == 1
    assert finding.unresolved[0]["waiting_for_resource"] == "R99_NEVER_DECLARED"
    assert "deadlock-freedom cannot be claimed" in finding.reason


def test_ambiguous_holder_declaration_is_insufficient_evidence():
    # Two facts disagree about who holds R1 -- never arbitrated, never
    # silently resolved to one side.
    facts = [
        {"resource": "R1", "held_by": "A", "waiting_for": None},
        {"resource": "R1", "held_by": "Z", "waiting_for": None},
        {"resource": "R2", "held_by": "B", "waiting_for": "R1"},
    ]
    finding = analyze_resource_dependency_cycle(facts)
    assert finding.status == "INSUFFICIENT_EVIDENCE"
    assert len(finding.ambiguous_resources) == 1
    assert set(finding.ambiguous_resources[0]["conflicting_holders"]) == {"A", "Z"}
    # The dependent edge referencing the ambiguous resource is unresolved too.
    assert any(u["waiting_for_resource"] == "R1" for u in finding.unresolved)


def test_real_cycle_still_reported_despite_an_unrelated_unresolved_edge():
    # A real cycle A<->B exists; C separately waits on a resource nobody
    # holds. The unrelated gap must not suppress the real, provable cycle.
    facts = [
        {"resource": "R1", "held_by": "A", "waiting_for": "R2"},
        {"resource": "R2", "held_by": "B", "waiting_for": "R1"},
        {"resource": "R3", "held_by": "C", "waiting_for": "R_UNKNOWN"},
    ]
    finding = analyze_resource_dependency_cycle(facts)
    assert finding.status == "CIRCULAR_WAIT_DETECTED"
    assert set(finding.cycle) == {"A", "B"}
    # The unrelated gap is still honestly reported, just doesn't change status.
    assert len(finding.unresolved) == 1


def test_missing_resource_field_raises():
    with pytest.raises(FabricProgressIrError):
        analyze_resource_dependency_cycle([{"held_by": "A"}])


def test_missing_held_by_field_raises():
    with pytest.raises(FabricProgressIrError):
        analyze_resource_dependency_cycle([{"resource": "R1"}])


def test_malformed_waiting_for_type_raises():
    with pytest.raises(FabricProgressIrError):
        analyze_resource_dependency_cycle([{"resource": "R1", "held_by": "A", "waiting_for": 5}])


def test_none_facts_raises():
    with pytest.raises(FabricProgressIrError):
        analyze_resource_dependency_cycle(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Credit/outstanding exhaustion: core positive path.
# ---------------------------------------------------------------------------


def test_no_exhaustion_detected_when_all_axes_are_healthy():
    facts = [
        {"resource": "AXI_M0", "credit_available": 4, "credit_max": 8},
        {"resource": "AXI_M1", "outstanding_count": 2, "outstanding_limit": 16},
    ]
    analysis = analyze_credit_outstanding(facts)
    assert analysis.status == "NO_EXHAUSTION_DETECTED"
    assert analysis.findings[0].credit_status == "CREDIT_OK"
    assert analysis.findings[1].outstanding_status == "OUTSTANDING_OK"


def test_credit_exhaustion_detected_at_zero_available():
    facts = [{"resource": "AXI_M0", "credit_available": 0, "credit_max": 8}]
    analysis = analyze_credit_outstanding(facts)
    assert analysis.status == "CREDIT_EXHAUSTION_DETECTED"
    assert analysis.findings[0].credit_status == "CREDIT_EXHAUSTED"


def test_outstanding_exhaustion_detected_at_the_limit():
    facts = [{"resource": "DMA0", "outstanding_count": 16, "outstanding_limit": 16}]
    analysis = analyze_credit_outstanding(facts)
    assert analysis.status == "OUTSTANDING_EXHAUSTION_DETECTED"
    assert analysis.findings[0].outstanding_status == "OUTSTANDING_EXHAUSTED"


def test_both_credit_and_outstanding_exhaustion_reported_together():
    facts = [
        {"resource": "AXI_M0", "credit_available": 0, "credit_max": 8},
        {"resource": "DMA0", "outstanding_count": 16, "outstanding_limit": 16},
    ]
    analysis = analyze_credit_outstanding(facts)
    assert analysis.status == "CREDIT_AND_OUTSTANDING_EXHAUSTION_DETECTED"


# ---------------------------------------------------------------------------
# Credit/outstanding: negative controls.
# ---------------------------------------------------------------------------


def test_empty_credit_outstanding_facts_is_insufficient_evidence():
    analysis = analyze_credit_outstanding([])
    assert analysis.status == "INSUFFICIENT_EVIDENCE"


def test_outstanding_count_with_no_limit_is_insufficient_evidence_never_ok():
    facts = [{"resource": "DMA0", "outstanding_count": 3}]
    analysis = analyze_credit_outstanding(facts)
    assert analysis.status == "INSUFFICIENT_EVIDENCE"
    assert analysis.findings[0].outstanding_status == "INSUFFICIENT_EVIDENCE"


def test_outstanding_limit_with_no_count_is_insufficient_evidence():
    facts = [{"resource": "DMA0", "outstanding_limit": 16}]
    analysis = analyze_credit_outstanding(facts)
    assert analysis.status == "INSUFFICIENT_EVIDENCE"


def test_fact_with_no_credit_or_outstanding_field_raises():
    with pytest.raises(FabricProgressIrError):
        analyze_credit_outstanding([{"resource": "R1"}])


def test_missing_resource_field_in_credit_fact_raises():
    with pytest.raises(FabricProgressIrError):
        analyze_credit_outstanding([{"credit_available": 4}])


def test_malformed_numeric_field_raises():
    with pytest.raises(FabricProgressIrError):
        analyze_credit_outstanding([{"resource": "R1", "credit_available": "plenty"}])


def test_none_facts_raises_for_credit_outstanding():
    with pytest.raises(FabricProgressIrError):
        analyze_credit_outstanding(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Composed FabricProgressIR: worst-wins overall fold.
# ---------------------------------------------------------------------------


def test_overall_no_risk_when_both_axes_clean():
    rd = [{"resource": "R1", "held_by": "A", "waiting_for": None}]
    co = [{"resource": "AXI_M0", "credit_available": 4, "credit_max": 8}]
    report = analyze_fabric_progress(rd, co)
    assert report.overall_status == "NO_RISK_DETECTED"


def test_overall_risk_detected_when_only_credit_axis_is_exhausted():
    rd = [{"resource": "R1", "held_by": "A", "waiting_for": None}]
    co = [{"resource": "AXI_M0", "credit_available": 0, "credit_max": 8}]
    report = analyze_fabric_progress(rd, co)
    assert report.overall_status == "PROGRESS_RISK_DETECTED"
    assert report.resource_dependency.status == "NO_CYCLE_DETECTED"
    assert report.credit_outstanding.status == "CREDIT_EXHAUSTION_DETECTED"


def test_overall_risk_detected_when_only_dependency_axis_has_a_cycle():
    rd = [
        {"resource": "R1", "held_by": "A", "waiting_for": "R2"},
        {"resource": "R2", "held_by": "B", "waiting_for": "R1"},
    ]
    co = [{"resource": "AXI_M0", "credit_available": 4, "credit_max": 8}]
    report = analyze_fabric_progress(rd, co)
    assert report.overall_status == "PROGRESS_RISK_DETECTED"


def test_overall_insufficient_evidence_outranks_a_clean_axis():
    # Dependency axis is genuinely incomplete; credit axis is clean. The
    # overall verdict must never read as NO_RISK_DETECTED.
    rd = [{"resource": "R1", "held_by": "A", "waiting_for": "R_UNKNOWN"}]
    co = [{"resource": "AXI_M0", "credit_available": 4, "credit_max": 8}]
    report = analyze_fabric_progress(rd, co)
    assert report.overall_status == "INSUFFICIENT_EVIDENCE"


def test_overall_risk_outranks_insufficient_evidence():
    # A real cycle on one axis, and a genuine gap on the other -- the real
    # risk must win, not be diluted by the unrelated gap.
    rd = [
        {"resource": "R1", "held_by": "A", "waiting_for": "R2"},
        {"resource": "R2", "held_by": "B", "waiting_for": "R1"},
    ]
    co = [{"resource": "DMA0", "outstanding_count": 3}]  # no limit declared
    report = analyze_fabric_progress(rd, co)
    assert report.overall_status == "PROGRESS_RISK_DETECTED"


def test_to_dict_round_trips_cleanly():
    rd = [{"resource": "R1", "held_by": "A", "waiting_for": None}]
    co = [{"resource": "AXI_M0", "credit_available": 4, "credit_max": 8}]
    report = analyze_fabric_progress(rd, co)
    d = report.to_dict()
    assert d["overall_status"] == "NO_RISK_DETECTED"
    json.dumps(d)  # must be JSON-serializable


# ---------------------------------------------------------------------------
# Vocabulary disjointness.
# ---------------------------------------------------------------------------


def test_vocabulary_disjoint_from_verification_verdict():
    # Must not raise -- proves the guard holds against the real Status enum.
    assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# Real CLI subprocess.
# ---------------------------------------------------------------------------


def test_cli_reports_no_risk_exit_0(tmp_path):
    rd_path = tmp_path / "rd.json"
    co_path = tmp_path / "co.json"
    rd_path.write_text(json.dumps([{"resource": "R1", "held_by": "A", "waiting_for": None}]), encoding="utf-8")
    co_path.write_text(json.dumps([{"resource": "AXI_M0", "credit_available": 4, "credit_max": 8}]), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.fabric_progress_ir",
         "--resource-dependency", str(rd_path), "--credit-outstanding", str(co_path), "--json"],
        capture_output=True, text=True, cwd=str(tmp_path.parent.parent) if False else None,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "NO_RISK_DETECTED"


def test_cli_reports_risk_detected_exit_1(tmp_path):
    rd_path = tmp_path / "rd.json"
    co_path = tmp_path / "co.json"
    rd_path.write_text(json.dumps([
        {"resource": "R1", "held_by": "A", "waiting_for": "R2"},
        {"resource": "R2", "held_by": "B", "waiting_for": "R1"},
    ]), encoding="utf-8")
    co_path.write_text(json.dumps([]), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.fabric_progress_ir",
         "--resource-dependency", str(rd_path), "--credit-outstanding", str(co_path), "--json"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "PROGRESS_RISK_DETECTED"


def test_cli_reports_insufficient_evidence_exit_2_with_no_input(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.fabric_progress_ir", "--json"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "INSUFFICIENT_EVIDENCE"
