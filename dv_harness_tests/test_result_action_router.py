"""Tests for dv_harness/result_action_router.py (Prime Directive V2 P6):
Result-to-Action Router, Auto-Remediation Eligibility, Loop
Termination/Budget, Evidence Traceability persistence."""
from __future__ import annotations

from pathlib import Path

import pytest

from dv_harness.result_action_router import (
    RemediationCandidate, EligibilityOutcome,
    evaluate_auto_remediation_eligibility, route_action,
    ACTION_AUTO_REMEDIATION_ELIGIBLE, ACTION_HUMAN_GATE_REQUIRED,
    ACTION_DEFERRED_WITH_OWNER, ACTION_CLOSE_WITH_EVIDENCE,
    DISPOSITION_FIX_NOW_CURRENT_SCOPE, DISPOSITION_FIX_NOW_CORRECTNESS_BLOCKER,
    DISPOSITION_FIX_NOW_CAPABILITY_LOSS, DISPOSITION_FIX_NOW_SAFETY_SECURITY,
    DISPOSITION_REGISTER_AND_DEFER_WITH_OWNER, DISPOSITION_SUPERSEDED_WITH_EVIDENCE,
    DISPOSITION_NOT_APPLICABLE_WITH_EVIDENCE, DISPOSITION_HUMAN_DECISION_REQUIRED,
    LoopBudget, LoopTerminationPolicy, check_loop_termination,
    REASON_BUDGET_OK, REASON_MAX_ITERATIONS_EXCEEDED, REASON_MAX_RETRY_EXCEEDED,
    REASON_REPEATED_FAILURE_SIGNATURE, REASON_REPEATED_FINDING_SIGNATURE,
    REASON_REGRESSION_EXPANSION, REASON_SCOPE_EXPANSION, REASON_EVIDENCE_STAGNATION,
    IterationTrace, append_iteration_trace, read_iteration_traces,
)


def _candidate(**overrides) -> RemediationCandidate:
    base = dict(finding_id="F1", gap_id="GAP-X", disposition=DISPOSITION_FIX_NOW_CURRENT_SCOPE)
    base.update(overrides)
    return RemediationCandidate(**base)


# --- Routing / eligibility ------------------------------------------------

def test_unknown_disposition_is_rejected_at_construction():
    with pytest.raises(ValueError):
        _candidate(disposition="NOT_A_REAL_DISPOSITION")


def test_fix_now_current_scope_with_no_reject_reasons_is_auto_eligible():
    out = route_action(_candidate())
    assert out.eligible is True
    assert out.action_class == ACTION_AUTO_REMEDIATION_ELIGIBLE
    assert out.reject_reasons == ()


@pytest.mark.parametrize("disposition", [
    DISPOSITION_FIX_NOW_CURRENT_SCOPE, DISPOSITION_FIX_NOW_CORRECTNESS_BLOCKER,
    DISPOSITION_FIX_NOW_CAPABILITY_LOSS,
])
def test_all_three_default_auto_dispositions_are_eligible_with_no_reject_reasons(disposition):
    out = route_action(_candidate(disposition=disposition))
    assert out.eligible is True
    assert out.action_class == ACTION_AUTO_REMEDIATION_ELIGIBLE


@pytest.mark.parametrize("flag", [
    "requires_human_authority", "is_protected_architecture_change", "is_scope_expansion",
    "is_security_expansion", "modifies_frozen_source", "raises_new_human_decision",
])
def test_any_single_reject_reason_forces_human_gate(flag):
    out = route_action(_candidate(**{flag: True}))
    assert out.eligible is False
    assert out.action_class == ACTION_HUMAN_GATE_REQUIRED
    assert len(out.reject_reasons) == 1


def test_safety_security_disposition_always_routes_to_human_gate():
    out = route_action(_candidate(disposition=DISPOSITION_FIX_NOW_SAFETY_SECURITY))
    assert out.eligible is False
    assert out.action_class == ACTION_HUMAN_GATE_REQUIRED


def test_human_decision_required_routes_to_human_gate():
    out = route_action(_candidate(disposition=DISPOSITION_HUMAN_DECISION_REQUIRED))
    assert out.action_class == ACTION_HUMAN_GATE_REQUIRED


def test_register_and_defer_routes_to_deferred_with_owner():
    out = route_action(_candidate(disposition=DISPOSITION_REGISTER_AND_DEFER_WITH_OWNER))
    assert out.action_class == ACTION_DEFERRED_WITH_OWNER


@pytest.mark.parametrize("disposition", [
    DISPOSITION_SUPERSEDED_WITH_EVIDENCE, DISPOSITION_NOT_APPLICABLE_WITH_EVIDENCE,
])
def test_superseded_or_not_applicable_routes_to_close_with_evidence(disposition):
    out = route_action(_candidate(disposition=disposition))
    assert out.action_class == ACTION_CLOSE_WITH_EVIDENCE


def test_router_never_branches_on_producer_model_it_never_receives_one():
    # RemediationCandidate has no producer_model/target_model field at
    # all -- this module cannot special-case a specific target model
    # because it structurally never sees one.
    assert not hasattr(RemediationCandidate, "producer_model")
    assert not hasattr(RemediationCandidate, "target_model")


# --- Loop termination / budget --------------------------------------------

def test_budget_ok_continues_by_default():
    r = check_loop_termination(LoopBudget(), LoopTerminationPolicy())
    assert r.should_continue is True
    assert r.reason == REASON_BUDGET_OK
    assert r.requires_human_escalation is False


def test_max_iterations_exceeded_stops_and_escalates():
    budget = LoopBudget(iteration_count=10)
    r = check_loop_termination(budget, LoopTerminationPolicy(max_remediation_iterations=10))
    assert r.should_continue is False
    assert r.reason == REASON_MAX_ITERATIONS_EXCEEDED
    assert r.requires_human_escalation is True


def test_max_retry_per_finding_exceeded_stops_and_escalates():
    r = check_loop_termination(LoopBudget(), LoopTerminationPolicy(max_retry_per_finding=3),
                               retry_count_for_current_finding=3)
    assert r.should_continue is False
    assert r.reason == REASON_MAX_RETRY_EXCEEDED


def test_repeated_failure_signature_stops_and_escalates():
    r = check_loop_termination(LoopBudget(), LoopTerminationPolicy(),
                               failure_signatures=["sig-A", "sig-A"])
    assert r.should_continue is False
    assert r.reason == REASON_REPEATED_FAILURE_SIGNATURE


def test_different_failure_signatures_do_not_trip_repeated_check():
    r = check_loop_termination(LoopBudget(), LoopTerminationPolicy(),
                               failure_signatures=["sig-A", "sig-B"])
    assert r.should_continue is True


def test_repeated_finding_signature_stops_and_escalates():
    r = check_loop_termination(LoopBudget(), LoopTerminationPolicy(),
                               finding_signatures=["F1", "F1"])
    assert r.reason == REASON_REPEATED_FINDING_SIGNATURE


def test_regression_expansion_stops_and_escalates():
    r = check_loop_termination(LoopBudget(), LoopTerminationPolicy(),
                               regression_failure_count_delta=1)
    assert r.reason == REASON_REGRESSION_EXPANSION


def test_scope_expansion_stops_and_escalates():
    r = check_loop_termination(LoopBudget(), LoopTerminationPolicy(),
                               scope_touched_outside_declared=True)
    assert r.reason == REASON_SCOPE_EXPANSION


def test_evidence_stagnation_stops_and_escalates():
    r = check_loop_termination(LoopBudget(), LoopTerminationPolicy(),
                               evidence_unchanged_since_last_iteration=True)
    assert r.reason == REASON_EVIDENCE_STAGNATION


def test_no_signatures_supplied_never_falsely_triggers_repeated_checks():
    r = check_loop_termination(LoopBudget(), LoopTerminationPolicy())
    assert r.should_continue is True


# --- Evidence traceability -------------------------------------------------

def _trace(**overrides) -> IterationTrace:
    base = dict(
        source_result_id="M7-V1-CODEX-REVIEW-001", finding_id="F1", gap_id="GAP-V2-009",
        action_classification=ACTION_AUTO_REMEDIATION_ELIGIBLE,
        eligibility_decision="ELIGIBLE", root_cause="weak schema check",
        files_changed=["dv_harness/model_result.py"], tests_run=["test_x"],
        regression_signature="sha:abc", evidence_refs=["dv_harness/model_result.py:354"],
        re_review_task_id=None, iteration_number=1, final_disposition="CLOSED",
    )
    base.update(overrides)
    return IterationTrace(**base)


def test_iteration_trace_round_trips_through_real_append_only_persistence(tmp_path: Path):
    root = tmp_path
    append_iteration_trace(root, "T-1", _trace(iteration_number=1))
    append_iteration_trace(root, "T-1", _trace(iteration_number=2, finding_id="F2"))
    traces = read_iteration_traces(root, "T-1")
    assert len(traces) == 2
    assert traces[0]["iteration_number"] == 1
    assert traces[1]["finding_id"] == "F2"


def test_reading_traces_for_a_task_with_no_recorded_iterations_is_a_real_empty_list(tmp_path: Path):
    assert read_iteration_traces(tmp_path, "NEVER-TRACED") == []


def test_appended_traces_are_never_overwritten(tmp_path: Path):
    root = tmp_path
    for i in range(5):
        append_iteration_trace(root, "T-1", _trace(iteration_number=i))
    traces = read_iteration_traces(root, "T-1")
    assert [t["iteration_number"] for t in traces] == [0, 1, 2, 3, 4]
