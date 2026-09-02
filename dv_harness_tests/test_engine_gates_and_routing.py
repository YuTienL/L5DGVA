import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from dv_harness.policy import graph_next
from dv_harness.gates import evaluate_stage_evidence
from dv_harness.stage_profile import StageExecutionProfiler, extract_provider_usage
from dv_harness.memory_router import route_and_store, route_memory
from dv_harness.memory import MemoryStore, MemoryRetriever, CornerCaseLibrary, CornerCaseLibraryConsolidator
from dv_harness.prompts import build_stage_prompt, get_de_explainer, STAGE_DE_EXPLAINER, STAGE_INSTRUCTIONS
from dv_harness.models import Stage as _Stage, Status
from dv_harness.dashboard import (
    _lsf_summary, _graph_with_status, _first_failure, _execution_mode,
    _overall_progress, _coverage_credit, _failure_attribution,
    _environment_mode_selected, _qualification_tier_reached,
)
from dv_harness.agent_profile import load_agent_profile
from dv_harness.adapters.cli import ClaudeCLIAdapter
from dv_harness import self_audit

ROOT = Path(__file__).resolve().parents[1]

# --- Evidence-block fixtures for gates wired in the 2026-08-28 mass-wiring
# pass (see gates.py's 'Mass-wiring pass' comment) -- each payload below was
# independently verified by execution (exit 0) against the real gate script
# during the cataloging workflow, then re-verified via evaluate_stage_evidence()
# before being spliced into the tests below. Concatenate onto an existing
# stage's 'complete' evidence text so tests keep demonstrating PASS instead of
# tripping MISSING_EVIDENCE on the newly-mandatory gates.
_VERIFY_EXTRA_GATES = (
    '```dv-harness-evidence:checker_semantic_trace_consistency_gate\n{"items": [{"expectation_id": "e1", "semantic_status": "MATCH", "checker_status": "PASS", "testcase_id": "t1", "vplan_ids": ["v1"], "checker_expectation_id": "e1"}]}\n```\n'
    '```dv-harness-evidence:command_intent_semantic_closure_gate\n{"command_id": "cmd1", "command_hash": "h1", "expected_semantics": "X_DONE", "observed_semantics": "X_DONE", "sim_log_hash": "sh1", "simulation_result": "PASSED"}\n```\n'
    '```dv-harness-evidence:expected_data_provenance_gate\n{"scoreboards": [{"scoreboard_id": "SB1", "expected_source": "REFERENCE_MODEL", "expected_source_hash": "H1", "prediction_method": "PREDICT_BEFORE_DRIVE"}]}\n```\n'
    '```dv-harness-evidence:false_pass_false_fail_arbitration_gate\n{"simulation_status": "PASS", "semantic_status": "TRUE_PASS", "checker_status": "PASS", "fatal_or_uvm_error": false}\n```\n'
    '```dv-harness-evidence:interrupt_storm_latency_gate\n{"sources": [{"source_id": "irq0", "max_ack_latency_cycles": 100, "observed_max_ack_latency_cycles": 50, "storm_rate": null, "lost_interrupts": 0}]}\n```\n'
    '```dv-harness-evidence:multi_port_fairness_qos_gate\n{"ports": [{"port_id": "p0", "min_service_share_percent": 10, "observed_service_share_percent": 20, "qos_enabled": false}]}\n```\n'
    '```dv-harness-evidence:negative_test_effectiveness_gate\n{"checks": [{"id": "c1", "positive_passed": true, "negative_mutation_applied": true, "negative_control_result": "FAIL"}]}\n```\n'
    '```dv-harness-evidence:per_port_queue_starvation_gate\n{"ports": [{"port_id": "p0", "independent_queue": true, "max_wait_cycles": 100, "observed_wait_cycles": 50, "forward_progress_evidence": "log.txt"}]}\n```\n'
    '```dv-harness-evidence:remote_execution_provenance_gate\n{"transcript_path": "/tmp/verify.txt", "claimed_exit_code": 0}\n```\n'
    '```dv-harness-evidence:rerun_determinism_gate\n{"runs": [{"input_fingerprint": "fp1", "semantic_verdict": "TRUE_PASS", "critical_checker_hash": "ck1"}, {"input_fingerprint": "fp1", "semantic_verdict": "TRUE_PASS", "critical_checker_hash": "ck1"}]}\n```\n'
    '```dv-harness-evidence:run_environment_reproducibility_gate\n{"rtl_hash": "abc", "testbench_hash": "def", "simulator_version": "vcs-2023", "vip_version": "1.0", "compile_options_hash": "co1", "runtime_options_hash": "ro1", "env_hash": "e1", "final_verdict": "PASS", "replay_command": "make replay"}\n```\n'
    '```dv-harness-evidence:scoreboard_transaction_liveness_gate\n{"missing_expected_transactions": 0, "missing_actual_transactions": 0, "duplicate_transactions": 0, "max_transaction_latency": 100, "observed_max_transaction_latency": 50}\n```\n'
    '```dv-harness-evidence:semantic_evidence_strength_gate\n{"minimum_rank": 2, "expectations": [{"expectation_id": "e1", "evidence": [{"type": "ASSERTION", "contradicted": false}]}]}\n```\n'
    '```dv-harness-evidence:simulation_completion_recheck_gate\n{"simulation_ended": true, "semantic_workflow_started": true}\n```\n'
    '```dv-harness-evidence:simulation_semantic_trace_gate\n{"final_state": "TRUE_PASS", "signoff_credit_allowed": true, "results": [{"expectation_id": "E1", "status": "MATCH", "source_line": 12, "evidence_source": "sim.log"}]}\n```\n'
    '```dv-harness-evidence:test_oracle_independence_gate\n{"oracles": [{"oracle_id": "O1", "shares_prediction_source_with_dut": false, "shares_bug_prone_algorithm_with_stimulus": false, "reference_basis": "spec_model", "oracle_hash": "abc123"}]}\n```\n'
    '```dv-harness-evidence:wave0_post_sim_semantic_gate\n{"wave_mode": 0, "command_hash": "h1", "sim_log_hash": "h2", "command_intent": "X", "observed_semantics": "X", "simulation_ended": true, "uvm_error_count": 0, "uvm_fatal_count": 0}\n```\n'
)
_COVERAGE_CLOSURE_EXTRA_GATES = (
    '```dv-harness-evidence:assertion_vacuity_and_reachability_gate\n{"assertions": [{"id": "as1", "signoff_credit": true, "antecedent_reached": true, "attempt_count": 5, "negative_control_failed": true}]}\n```\n'
    '```dv-harness-evidence:assertion_vacuity_gate\n{"assertions": [{"assertion_id": "as1", "enabled": true, "antecedent_attempts": 3, "unknown_xz_masked_without_justification": false}]}\n```\n'
    '```dv-harness-evidence:coverage_checker_linkage_gate\n{"items": [{"coverage_id": "cov1", "credit": true, "active_checker_ids": ["chk1"]}, {"coverage_id": "cov2", "credit": true, "waived": true, "waiver_approved": true, "waiver_evidence": "ev1"}]}\n```\n'
    '```dv-harness-evidence:coverage_credit_revocation_gate\n{"items": [{"coverage_id": "cov1", "credit": true, "revocation_triggers": []}]}\n```\n'
    '```dv-harness-evidence:coverage_credit_source_integrity_gate\n{"items": [{"coverage_id": "cov1", "credit": true, "source": {"type": "TEST", "source_id": "t1", "evidence_hash": "h1"}}]}\n```\n'
    '```dv-harness-evidence:coverage_failure_state_linkage_gate\n{"active_failure_ids": ["f1"], "coverage_items": [{"coverage_id": "cov1", "credit": true, "linked_failure_ids": []}]}\n```\n'
    '```dv-harness-evidence:coverage_regression_drift_gate\n{"allowed_drop_percent": 5, "items": [{"coverage_id": "cov1", "previous_credit": 90, "current_credit": 88}]}\n```\n'
    '```dv-harness-evidence:protocol_corner_case_matrix_gate\n{"required_corner_cases": ["C1", "C2"], "cases": [{"corner_id": "C1", "covered": true, "evidence": "e1"}, {"corner_id": "C2", "covered": true, "evidence": "e2"}]}\n```\n'
    '```dv-harness-evidence:sequence_coverage_closure_gate\n{"required_sequences": ["seqA", "seqB"], "hit_sequences": ["seqA", "seqB"], "waivers": []}\n```\n'
    '```dv-harness-evidence:verification_effectiveness_consistency_gate\n{"final_verdict": "PASS", "semantic_status": "TRUE_PASS", "checker_status": "PASS", "negative_test_effective": true, "assertion_effective": true, "scoreboard_independent": true}\n```\n'
)
_VERIFICATION_ARCHITECTURE_EXTRA_GATES = (
    '```dv-harness-evidence:branch_fw_interrupt_contract_gate\n{"interrupt_driven": true, "interrupt_map": {"irq0": "handler0"}, "acknowledge_path": true, "polling_primary": false}\n```\n'
    '```dv-harness-evidence:branch_topology_gate\n{"dut_port_count": 1, "vip_port_count": 1, "branches": ["block", "branch_fw", "branch_a0", "branch_b0"], "branch_fw_interrupt_driven": true}\n```\n'
    '```dv-harness-evidence:error_injection_coverage_gate\n{"required_error_classes": ["CRC_ERROR", "TIMEOUT"], "tests": [{"testcase_id": "T1", "checker_ids": ["CHK1"], "error_classes": ["CRC_ERROR"]}, {"testcase_id": "T2", "assertion_ids": ["A1"], "error_classes": ["TIMEOUT"]}]}\n```\n'
    '```dv-harness-evidence:observability_sufficiency_gate\n{"requirements": [{"requirement_id": "R1", "status": "OPEN", "observability": [{"type": "CHECKER", "evidence_point": "scoreboard.match"}]}]}\n```\n'
    '```dv-harness-evidence:assertion_placeholder_closure_gate\n{"assertion_entries": [{"target_id": "obs_001", "classification": "PROTOCOL_STATE_MACHINE_LEGALITY", "generation_method": "state_machine_checks_dsl:valid_transition_table"}]}\n```\n'
    '```dv-harness-evidence:per_port_verification_matrix_gate\n{"required_feature_combinations": ["A", "B"], "ports": [{"port_id": "p0", "scoreboard": true, "checker": true, "performance_calculator": true, "coverage_collector": true, "covered_feature_combinations": ["A", "B"]}]}\n```\n'
    '```dv-harness-evidence:protocol_scheduler_gate\n{"protocol": "APB", "mode": "N_TO_1_SERIAL", "cross_port_global_lock": false}\n```\n'
    '```dv-harness-evidence:reference_uvm_adaptation_gate\n{"reference_uvm_hash": "h1", "new_dut_architecture_hash": "h2", "gap_analysis_hash": "h3", "adaptation_plan_hash": "h4", "blind_copy": false, "dut_specific_changes": "reworked scoreboard for new register map"}\n```\n'
    '```dv-harness-evidence:reference_uvm_compatibility_gate\n{"reference_name": "ref_usb_uvm", "reference_revision": "r12", "reference_hash": "abc123", "compatibility_analysis": {"protocol_role": "HOST", "interface_mapping": "mapped", "config_mapping": "mapped", "sequence_reuse": "partial", "scoreboard_checker_reuse": "full"}, "reuse_decision": "REUSE", "adaptation_plan": "plan.md"}\n```\n'
    '```dv-harness-evidence:reset_clock_power_sequence_gate\n{"events": [{"event": "reset_deassert"}, {"event": "clock_stable"}, {"event": "power_up"}], "ordering_rules": [{"before": "reset_deassert", "after": "clock_stable"}], "power_aware_design": false}\n```\n'
    '```dv-harness-evidence:scoreboard_reference_model_independence_gate\n{"shares_dut_implementation_code": false, "shared_algorithm_source_hash": "", "dut_algorithm_source_hash": "xyz", "independent_oracle_basis": "spec-derived C model", "negative_control_detected": true}\n```\n'
)
_FAILURE_RECOVERY_EXTRA_GATES = (
    '```dv-harness-evidence:failure_signature_recurrence_gate\n{"failures": [{"failure_id": "F1", "signature": "SIG_A"}, {"failure_id": "F2", "signature": "SIG_A", "linked_to_existing_failure": "F1"}]}\n```\n'
    '```dv-harness-evidence:issue_triage_classification_gate\n{"classification": "KNOWN", "classification_reason": "matches prior waiver", "evidence_hash": "abc123", "known_issue_id": "K-1"}\n```\n'
    '```dv-harness-evidence:unknown_failure_escalation_gate\n{"classification": "ENV_ISSUE"}\n```\n'
    # ADDED (targeted-wave-debug-window-recovery-wiring, 2026-09-02):
    # focused_wave_debug_window_gate is now also mandatory for
    # FAILURE_RECOVERY (see gates.py STAGE_GATES) -- the "not needed this
    # round" escape hatch (deep_debug_required:false +
    # deep_debug_not_required_reason) is the realistic default for this
    # fixture since none of the other FAILURE_RECOVERY tests below claim a
    # real waveform rerun happened.
    '```dv-harness-evidence:focused_wave_debug_window_gate\n{"deep_debug_required": false, "deep_debug_not_required_reason": "sim.log UVM_ERROR text alone identified the mismatch"}\n```\n'
)
_REGRESSION_MONITOR_EXTRA_GATES = (
    '```dv-harness-evidence:cross_run_evidence_consistency_gate\n{"runs": [{"run_id": "r1", "rtl_revision": "rev1", "tb_revision": "tb1", "vip_version": "v1", "config_hash": "c1", "testlist_hash": "t1", "evidence_bundle_hash": "e1"}, {"run_id": "r2", "rtl_revision": "rev1", "tb_revision": "tb1", "vip_version": "v1", "config_hash": "c1", "testlist_hash": "t1", "evidence_bundle_hash": "e2"}]}\n```\n'
    '```dv-harness-evidence:flaky_test_policy_gate\n{"tests": [{"testcase_id": "t1", "failure_rate_percent": 0}]}\n```\n'
    '```dv-harness-evidence:seed_diversity_and_corner_case_gate\n{"random_corner_case_claim": true, "seeds": [1, 2, 3], "config_hashes": ["c1"], "minimum_unique_seeds": 2, "minimum_unique_configs": 1, "corner_case_bins_exercised": ["bin_a", "bin_b"]}\n```\n'
    '```dv-harness-evidence:seed_reproducibility_gate\n{"runs": [{"run_id": "r1", "randomized": true, "seed": 123, "failure": false}, {"run_id": "r2", "randomized": false, "failure": true, "reproducer_command": "make repro r2"}]}\n```\n'
)
_SOC_SCENARIO_PLANNER_EXTRA_GATES = (
    '```dv-harness-evidence:reset_power_cdc_corner_gate\n{"corner_items": [{"corner_id": "c1", "domain": "RESET", "requirement_ids": ["R1"], "mechanism_ids": ["M1"], "testcase_ids": ["T1"], "async_or_partial_reset_covered": true}, {"corner_id": "c2", "domain": "CLOCK", "requirement_ids": ["R2"], "mechanism_ids": ["M2"], "testcase_ids": ["T2"]}, {"corner_id": "c3", "domain": "CDC", "requirement_ids": ["R3"], "mechanism_ids": ["M3"], "testcase_ids": ["T3"], "cdc_observation_or_assertion": true}], "power_aware_design": false}\n```\n'
)
_INTAKE_EXTRA_GATES = (
    '```dv-harness-evidence:generated_artifact_boundary_gate\n{"artifacts": [{"class": "BUILD", "required_from_user": false, "owner": "HARNESS"}]}\n```\n'
    '```dv-harness-evidence:interactive_evidence_intake_gate\n{"questions_asked_in_batch": 1, "evidence_answer_available": false, "asked_user_anyway": false, "confidence": "HIGH", "asked_user_for_same_fact": false, "status": "READY"}\n```\n'
    # NEW (2026-09-01, de-local-sim-env-intake design pass): additive 4th
    # INTAKE gate -- "{}" is its own documented no-op PASS for a project
    # with no pre-existing DE-local simulation environment to intake.
    '```dv-harness-evidence:de_local_sim_env_intake_gate\n{}\n```\n'
)
_DISCOVERY_EXTRA_GATES = (
    '```dv-harness-evidence:evidence_source_priority_gate\n{"attempted_sources": ["EXISTING_PROJECT_FILES", "RTL_PARAMETERS_DEFINES", "DESIGN_DOCS"], "higher_priority_sources_exhausted": true}\n```\n'
    '```dv-harness-evidence:input_source_contract_gate\n{"provided_source_classes": ["SPEC", "COMMAND_TXT", "PRIMARY_PROTOCOL_REFERENCE", "RTL_SOURCE", "DE_LOCAL_SIM"], "protocol_input_kind": "PUBLIC_STANDARD_SPEC", "forbidden_user_prerequisites": []}\n```\n'
)

# --- Evidence-block fixture for the multi-flag gate wired into
# EXPERT_FEEDBACK_LOOP (see gates.py's EvidenceFlag/ContextFlag extension,
# 2026-08-28). experience_applicability_gate's single fenced block carries a
# dict-of-sub-payloads {"knowledge": {...}, "context": {...}} -- one key per
# EvidenceFlag -- instead of a flat dict, exactly matching what
# tools/verification_flow/experience_applicability_gate.py's --knowledge/
# --context flags each expect verbatim. Reused by every EXPERT_FEEDBACK_LOOP
# test below that needs an overall PASS, now that this gate is mandatory for
# that stage (mirrors the _VERIFY_EXTRA_GATES / _COVERAGE_CLOSURE_EXTRA_GATES
# fixture-append pattern already used above for prior mass-wiring passes).
_EXPERIENCE_APPLICABILITY_GATE_PASS = (
    '```dv-harness-evidence:experience_applicability_gate\n'
    '{"knowledge": {"expert_approved": true, "evidence": "ev1", '
    '"applicability_constraints": {"protocol": "USB"}}, '
    '"context": {"protocol": "USB"}}\n```\n'
)


def test_extract_provider_usage_and_profiler_round_trip():
    # Regression test: engine.py previously imported extract_provider_usage
    # from stage_profile (which didn't exist) and called add_agent_run with
    # keyword args that didn't match its signature -- the CLI crashed on
    # import before ever running a single stage. Both are fixed; this
    # exercises the same call shape engine.py now uses.
    raw = {
        "returncode": 0, "stderr": "",
        "response": {
            "model": "claude-x",
            "usage": {"input_tokens": 10, "output_tokens": 5,
                      "cache_read_input_tokens": 2, "cache_creation_input_tokens": 1},
        },
    }
    usage = extract_provider_usage(raw)
    assert usage == {"input_tokens": 10, "output_tokens": 5,
                      "cache_read_tokens": 2, "cache_write_tokens": 1}

    tmp = Path(tempfile.mkdtemp())
    try:
        profiler = StageExecutionProfiler(tmp)
        rec = profiler.begin_stage("S1", "S1")
        profiler.add_agent_run(rec["profile_id"], "stage-agent", 1.23,
                                usage=usage, model="claude-x", status="PASS")
        ended = profiler.end_stage(rec["profile_id"], status="PASS")
        assert ended["input_tokens"] == 10
        assert ended["output_tokens"] == 5
    finally:
        shutil.rmtree(tmp)


def test_run_stage_records_add_agent_run_with_real_resolved_agent_name_not_stage_agent():
    # Per-agent-attribution audit fix regression test: run_stage()'s real
    # add_agent_run() call site previously hardcoded the literal string
    # "stage-agent" no matter which real agent the router actually resolved.
    # DISCOVERY's real main_graph.json node declares agent=analysis-agent
    # (see test_run_stage_wires_plan_blackboard_react_and_agent_dispatch_on_pass
    # above, which already asserts this same resolved name reaches the
    # adapter_profile/prompt/task -- this test asserts the SAME real resolved
    # name also reaches the stage profiler, not a hardcoded placeholder).
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness
        from dv_harness.adapters.base import AgentResult

        class FakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(
                    ok=True, text="analysis done.\n" + _DISCOVERY_EXTRA_GATES,
                    raw={"response": {"model": "claude-x",
                                      "usage": {"input_tokens": 10, "output_tokens": 5}}},
                    session_id="sess-1")

        h = DVHarness(tmp)
        h.adapter = FakeAdapter()
        h.blackboard.write("project", {"target_name": "usb_dev"}, source="INTAKE")
        h.set_stage("DISCOVERY")
        h.run_stage("verify the USB device controller")

        assert h.state.stages["DISCOVERY"]["status"] == "PASS"

        recs = h.profiler.all_stages()
        assert len(recs) == 1
        agents = recs[0]["agents"]
        assert len(agents) == 1
        assert agents[0]["agent"] == "analysis-agent"
        assert agents[0]["agent"] != "stage-agent"
        assert agents[0]["input_tokens"] == 10
        assert agents[0]["output_tokens"] == 5
    finally:
        shutil.rmtree(tmp)


def test_graph_next_passes_through_synthetic_join():
    assert graph_next("INFRASTRUCTURE_AUDIT", "PASS", ROOT) == "VPLAN"


def test_graph_next_routes_fail_to_failure_recovery():
    assert graph_next("VERIFY", "FAIL", ROOT) == "FAILURE_RECOVERY"
    assert graph_next("BUILD_DEBUG", "FAIL", ROOT) == "FAILURE_RECOVERY"
    assert graph_next("INFRA_RECOVERY", "FAIL", ROOT) == "FAILURE_RECOVERY"


def test_graph_next_build_and_regression_triage_before_failure_recovery():
    # BUILD/REGRESSION_MONITOR failures triage through a lightweight stage
    # first (compile-error / infra-vs-functional check) rather than jumping
    # straight to full RCA in FAILURE_RECOVERY.
    assert graph_next("BUILD", "FAIL", ROOT) == "BUILD_DEBUG"
    assert graph_next("BUILD_DEBUG", "PASS", ROOT) == "CHANGE_IMPACT"
    assert graph_next("REGRESSION_MONITOR", "FAIL", ROOT) == "INFRA_RECOVERY"
    assert graph_next("INFRA_RECOVERY", "PASS", ROOT) == "REGRESSION_SELECT"


def test_graph_next_re_audit_branches():
    assert graph_next("RE_AUDIT", "FAIL", ROOT) == "IMPLEMENT"
    assert graph_next("RE_AUDIT", "PASS", ROOT) == "SYSTEM_LEVEL"


def test_graph_next_walks_full_mechanism_first_pipeline():
    # Regression test: the Stage enum / main_graph.json were extended to the
    # full mechanism-first pipeline (2026-08-27) -- every stage except the
    # FAIL-only branches (FAILURE_RECOVERY, BUILD_DEBUG, INFRA_RECOVERY) must
    # appear exactly once on the PASS walk.
    #
    # UPDATED (2026-08-29, graph-level parallel fan-out/join fix): this
    # walk uses graph_next()/next_for(), which only ever returns ONE target
    # per node -- a single-hop sequential walker. Before this fix,
    # PROTOCOL_CAPABILITY -> REQUIREMENTS_TRACEABILITY -> SOC_SCENARIO_PLANNER
    # -> INFRASTRUCTURE_AUDIT -> ANALYSIS_JOIN was (incorrectly) wired as one
    # strictly linear chain, so a single-hop walk happened to still visit
    # all three ANALYSIS_G1 nodes -- that linear wiring directly contradicted
    # their own parallel_group="ANALYSIS_G1"/join_group="ANALYSIS_G1"
    # metadata, which always declared them as a 3-way fan-out/join, not a
    # chain. Now that main_graph.json's edges actually match that metadata
    # (PROTOCOL_CAPABILITY fans out to all 3 directly; each fans back in to
    # ANALYSIS_JOIN directly), a single-hop walk can only ever follow ONE of
    # the 3 parallel edges out of PROTOCOL_CAPABILITY (REQUIREMENTS_
    # TRACEABILITY, first by edge order) straight to ANALYSIS_JOIN -- by
    # construction, a single-target-per-step walker can never visit every
    # branch of a real fan-out. test_graph_parallel_dispatch.py's
    # next_frontier()-based regression test is what proves ALL 3 branches
    # are still real, reachable graph targets.
    from dv_harness.policy import ORDER
    visited = ["ENV_CHECK", "INTAKE"]
    cur = "INTAKE"
    for _ in range(50):
        nxt = graph_next(cur, "PASS", ROOT)
        if not nxt:
            break
        visited.append(nxt)
        cur = nxt
    assert visited[-1] == "SIGNOFF"
    assert set(ORDER) - set(visited) == {
        "FAILURE_RECOVERY", "BUILD_DEBUG", "INFRA_RECOVERY",
        "SOC_SCENARIO_PLANNER", "INFRASTRUCTURE_AUDIT",
    }
    assert len(visited) == len(set(visited))


def test_graph_next_terminal_stage_has_no_target():
    assert graph_next("SIGNOFF", "PASS", ROOT) is None


def test_stage_without_mapped_gate_is_unaffected():
    # Every real Stage enum value now has a STAGE_GATES entry as of the
    # 2026-08-28 7-ungated-stage closure pass (PROJECT_MODEL, previously used
    # here as the "no mapped gate" example, gained project_model_topology_
    # completeness_gate in that pass -- see gates.py's header comment). The
    # "stage has no mapped gate" code path in evaluate_stage_evidence() itself
    # doesn't care whether the stage string is a real Stage enum member, so a
    # placeholder name unambiguously not in STAGE_GATES still exercises it.
    verdict, reasons = evaluate_stage_evidence(ROOT, "__NO_SUCH_STAGE__", "anything at all")
    assert verdict == "NO_GATE_REQUIRED"
    assert reasons == []


def test_verify_stage_without_evidence_cannot_pass():
    verdict, reasons = evaluate_stage_evidence(ROOT, "VERIFY", "I verified it, trust me.")
    assert verdict == "MISSING_EVIDENCE"
    assert reasons


def test_verify_stage_with_matching_evidence_passes():
    # 16 more gates were wired into VERIFY in the 2026-08-28 mass-wiring pass
    # (see gates.py's "Mass-wiring pass" comment) -- _VERIFY_EXTRA_GATES below
    # supplies verified-PASS evidence for all of them so this test still
    # demonstrates the original 3-gate behavior without silently ignoring
    # the 16 new mandatory gates.
    tmp = Path(tempfile.mkdtemp())
    try:
        transcript_path = tmp / "verify.txt"
        transcript_path.write_text("REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\nVerification passed\n")
        # Build VERIFY_EXTRA_GATES with real transcript path
        verify_extra_with_transcript = _VERIFY_EXTRA_GATES.replace(
            '```dv-harness-evidence:remote_execution_provenance_gate\n{"transcript_path": "/tmp/verify.txt", "claimed_exit_code": 0}\n```\n',
            '```dv-harness-evidence:remote_execution_provenance_gate\n' + json.dumps({"transcript_path": str(transcript_path), "claimed_exit_code": 0}) + '\n```\n'
        )
        text = (
            "```dv-harness-evidence:simulation_semantic_validation_gate\n"
            '{"simulation_passed": true, "sim_log": "UVM_INFO enum PASS", '
            '"command_expectations": [{"expectation_id": "e1", "required": true, '
            '"evidence_requirements": [{"pattern": "enum PASS", "match_mode": "SUBSTRING"}]}]}\n'
            "```\n"
            "```dv-harness-evidence:test_result_provenance_gate\n"
            '{"results": [{"testcase_id": "t1", "run_id": "r1", "rtl_revision": "a", '
            '"tb_revision": "b", "vip_version": "c", "tool_version": "d", "seed": "1", '
            '"config_hash": "h", "result": "PASS", "log_hash": "lh", "evidence_bundle_hash": "eh"}]}\n'
            "```\n"
            "```dv-harness-evidence:false_pass_resistance_gate\n"
            '{"positive_test_pass": true, "negative_test_detects_fault": true, '
            '"checker_detects_injected_fault": true, "semantic_log_match": true, '
            '"oracle_independent": true, "proof_bundle_hash": "h1"}\n'
            "```\n"
            + verify_extra_with_transcript
        )
        verdict, reasons = evaluate_stage_evidence(ROOT, "VERIFY", text)
        assert verdict == "PASS", reasons
        assert reasons == []
    finally:
        shutil.rmtree(tmp)


def test_memory_router_was_previously_dead_code_now_wired():
    # Regression test: route_memory() existed but was never called anywhere
    # in the codebase (memory_cli.py and MemoryConsolidator both bypassed it
    # with hardcoded levels). route_and_store() is the missing entry point.
    tmp = Path(tempfile.mkdtemp())
    try:
        engineering = route_and_store(tmp, {"kind": "root_cause", "verified": True, "title": "t"})
        assert engineering["destination"] == "ENGINEERING_MEMORY"
        assert engineering["level"] == "engineering"

        job = route_and_store(tmp, {"kind": "job_result", "job_id": 1})
        assert job["destination"] == "JOB_MEMORY"

        blackboard = route_and_store(tmp, {"kind": "current_state", "value": {"x": 1}})
        assert blackboard["destination"] == "BLACKBOARD"

        claude_mem = route_and_store(tmp, {"kind": "project_instruction", "value": "always do X"})
        assert claude_mem["destination"] == "CLAUDE_PROJECT_MEMORY"
        assert claude_mem["action"] == "SURFACE_TO_CLAUDE_PROJECT_MEMORY"

        try:
            route_and_store(tmp, {"kind": "password", "value": "hunter2"})
            assert False, "credential-like record must be rejected, not persisted"
        except ValueError:
            pass
    finally:
        shutil.rmtree(tmp)


def test_dashboard_lsf_summary_counts_real_fields():
    jobs = [
        {"lsf_status": "RUN"},
        {"lsf_status": "DONE", "dv_analysis_status": "PASS"},
        {"lsf_status": "EXIT", "dv_analysis_status": "FAIL"},
        {"lsf_status": "DONE", "early_kill": True},
    ]
    summary = _lsf_summary(jobs)
    assert summary["total"] == 4
    assert summary["RUN"] == 1
    assert summary["DONE"] == 2
    assert summary["EXIT"] == 1
    assert summary["pass_confirmed"] == 1
    assert summary["fail_confirmed"] == 1
    assert summary["early_kill"] == 1


def test_env_check_execution_mode_validator_wired():
    ok = '''```dv-harness-evidence:execution_mode_validator
{"execution_mode": "PURE_LOCAL_READ_ANALYSIS", "actions": ["read RTL"]}
```'''
    verdict, _ = evaluate_stage_evidence(ROOT, "ENV_CHECK", ok)
    assert verdict == "PASS"

    conflict = '''```dv-harness-evidence:execution_mode_validator
{"execution_mode": "PURE_LOCAL_READ_ANALYSIS", "actions": ["run vcs simulation"]}
```'''
    verdict, reasons = evaluate_stage_evidence(ROOT, "ENV_CHECK", conflict)
    assert verdict == "GATE_FAIL"
    assert reasons


def _vplan_writer_validation_extra_gate_text(tmp: Path) -> str:
    # NEW (2026-09-01, vplan-doc-and-wiring-fix): vplan_writer_validation_gate
    # (STAGE_GATES["VPLAN"]'s second gate) calls the real dv_harness.
    # vplan_writer.build_evidence_context()/validate_items() against REAL
    # files on disk -- unlike every other _EXTRA_GATES constant above, its
    # evidence cannot be a static JSON string; it needs a real pattern file,
    # dispatcher file, and task-declaration source to exist at test time.
    pattern_dir = tmp / "patterns"
    pattern_dir.mkdir()
    (pattern_dir / "USB2_bulkin.txt").write_text("bulkin pattern", encoding="utf-8")
    dispatcher_file = tmp / "dv_uvm_pattern_pool.svh"
    dispatcher_file.write_text(
        'case (pattern_name)\n  "USB2_bulkin": run_bulkin();\nendcase\n', encoding="utf-8",
    )
    tests_dir = tmp / "tests"
    tests_dir.mkdir()
    (tests_dir / "usb_bulkin_test.sv").write_text(
        "task automatic usb_bulkin_test();\nendtask\n", encoding="utf-8",
    )
    payload = {
        "items": [{
            "req_id": "R1", "feature_area": "Bulk Transfers",
            "verification_item": "Bulk IN transfer completes",
            "pattern_name": "USB2_bulkin", "task_name": "usb_bulkin_test",
            "suite": "USB2_sanity", "covered_by": "covered",
            "description": "Directed bulk-in transfer test", "spec_section": "TBD-spec",
            "constraint_items": [], "random_or_directed": "directed", "mode_speed": "HS",
            "instance": "N/A", "checkers_active": ["sb_bulk_data_match"], "notes": "",
            "blocked_on": None, "blocked_reason": None,
        }],
        "pattern_dir": str(pattern_dir),
        "dispatcher_file": str(dispatcher_file),
        "task_declaration_sources": [str(tests_dir / "*.sv")],
    }
    return "```dv-harness-evidence:vplan_writer_validation_gate\n" + json.dumps(payload) + "\n```\n"


def test_newly_wired_orphan_gates_pass_with_valid_evidence():
    # SOC_SCENARIO_PLANNER and FAILURE_RECOVERY each gained more mandatory
    # gates in the 2026-08-28 mass-wiring pass -- their _EXTRA_GATES const
    # supplies verified-PASS evidence for those too, INTAKE unaffected. VPLAN
    # gained a second mandatory gate (vplan_writer_validation_gate) in the
    # 2026-09-01 vplan-doc-and-wiring-fix pass -- see
    # _vplan_writer_validation_extra_gate_text above for why its evidence
    # needs a real tmp fixture rather than a static JSON string.
    tmp = Path(tempfile.mkdtemp())
    try:
        cases = {
            "INTAKE": ("intake_readiness",
                '{"mode": "SUBSYSTEM", "target_name": "usb_dev", "protocols": ["USB"], '
                '"required_artifacts": {"protocol_spec": true, "dut_design_spec": true, '
                '"rtl_top_or_interface_files": true, '
                # command_txt/vip_reference (2026-09-01, commandtxt-vip-intake-
                # gate-implementation): now-mandatory required_artifacts keys --
                # gate checks these paths for real existence relative to cwd
                # (evaluate_stage_evidence(ROOT, ...) below runs the gate with
                # cwd=ROOT), so these must name files that really exist in ROOT.
                '"command_txt": ["CLAUDE.md"], "vip_reference": ["dv_harness/gates.py"]}}',
                _INTAKE_EXTRA_GATES),
            "VPLAN": ("spec_coverage_audit", '{"requirements": [{"req_id": "R1", "status": "VERIFIED"}]}',
                _vplan_writer_validation_extra_gate_text(tmp)),
            "SOC_SCENARIO_PLANNER": ("corner_risk_rank",
                '{"cases": [{"corner_id": "c1", "risk_factors": ["reset", "cdc"]}]}',
                _SOC_SCENARIO_PLANNER_EXTRA_GATES),
            "FAILURE_RECOVERY": ("failure_attribution",
                '{"boundary_trace": [{"stage": "SEQUENCE", "expected": 1, "observed": 1}, '
                '{"stage": "DUT_INTERNAL", "expected": 1, "observed": 0}]}',
                _FAILURE_RECOVERY_EXTRA_GATES),
        }
        for stage, (gate_id, body, extra) in cases.items():
            text = f"```dv-harness-evidence:{gate_id}\n{body}\n```\n" + extra
            verdict, reasons = evaluate_stage_evidence(ROOT, stage, text)
            assert verdict == "PASS", f"{stage}/{gate_id}: {reasons}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_dashboard_overall_progress_uses_full_stage_enum_as_denominator():
    # Regression test: an on-disk state.json can predate later Stage enum
    # additions (it happened for real -- 24 stale entries vs 35 real stages).
    # The denominator must be len(Stage), not len(state["stages"]).
    from dv_harness.models import Stage
    state = {"stages": {"ENV_CHECK": {"status": "PASS"}, "INTAKE": {"status": "PASS"}}}
    assert _overall_progress(state) == round(100 * 2 / len(Stage))
    assert _overall_progress({"stages": {}}) == 0


def test_dashboard_coverage_credit_reads_real_evidence_only():
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / ".dv-harness").mkdir()
        state = {"stages": {"COVERAGE_CLOSURE": {"last_message": (
            "```dv-harness-evidence:coverage_signoff_verdict_gate\n"
            '{"signoff_requested": true, "coverage_credit_percent": 82.4}\n'
            "```\n"
        )}}}
        (tmp / ".dv-harness" / "state.json").write_text(json.dumps(state))
        assert _coverage_credit(tmp) == 82.4
    finally:
        shutil.rmtree(tmp)
    assert _coverage_credit(Path(tempfile.mkdtemp())) is None


def _mk_attribution_state(tmp, boundary_trace):
    (tmp / ".dv-harness").mkdir(exist_ok=True)
    payload = {"boundary_trace": boundary_trace,
               # Deliberately wrong on purpose in every test below -- proves
               # _failure_attribution() re-derives the verdict from
               # boundary_trace itself rather than trusting this field,
               # exactly like tools/senior_dv/failure_attribution.py's own
               # gate logic does.
               "classification": "THIS_FIELD_MUST_BE_IGNORED"}
    state = {"stages": {"FAILURE_RECOVERY": {"last_message": (
        "```dv-harness-evidence:failure_attribution\n"
        f"{json.dumps(payload)}\n"
        "```\n"
    )}}}
    (tmp / ".dv-harness" / "state.json").write_text(json.dumps(state))


def test_dashboard_failure_attribution_derives_dut_bug_from_boundary_trace():
    tmp = Path(tempfile.mkdtemp())
    try:
        _mk_attribution_state(tmp, [
            {"stage": "SEQUENCE", "expected": "a", "observed": "a"},
            {"stage": "DRIVER", "expected": "b", "observed": "b"},
            {"stage": "DUT_INTERNAL", "expected": "1", "observed": "0"},
        ])
        result = _failure_attribution(tmp)
        assert result["verdict"] == "DUT_BUG"
        assert result["first_bad_event"]["stage"] == "DUT_INTERNAL"
    finally:
        shutil.rmtree(tmp)


def test_dashboard_failure_attribution_derives_tb_bug_from_boundary_trace():
    tmp = Path(tempfile.mkdtemp())
    try:
        _mk_attribution_state(tmp, [
            {"stage": "SEQUENCE", "expected": "a", "observed": "z"},
        ])
        result = _failure_attribution(tmp)
        assert result["verdict"] == "TB_BUG"
    finally:
        shutil.rmtree(tmp)


def test_dashboard_failure_attribution_unknown_when_no_mismatch_or_unresolved_stage():
    tmp = Path(tempfile.mkdtemp())
    try:
        # INTERFACE_IN is a real stage name but not in either DUT_BUG or
        # TB_BUG's list -- must fall through to UNKNOWN, matching the gate.
        _mk_attribution_state(tmp, [
            {"stage": "INTERFACE_IN", "expected": "x", "observed": "y"},
        ])
        assert _failure_attribution(tmp)["verdict"] == "UNKNOWN"
    finally:
        shutil.rmtree(tmp)

    tmp2 = Path(tempfile.mkdtemp())
    try:
        # No mismatch anywhere in boundary_trace -> no first_bad_event -> UNKNOWN.
        _mk_attribution_state(tmp2, [{"stage": "SEQUENCE", "expected": "a", "observed": "a"}])
        result = _failure_attribution(tmp2)
        assert result["verdict"] == "UNKNOWN"
        assert result["first_bad_event"] is None
    finally:
        shutil.rmtree(tmp2)


def test_dashboard_failure_attribution_none_before_stage_runs():
    assert _failure_attribution(Path(tempfile.mkdtemp())) is None


def test_dashboard_first_failure_picks_earliest_real_failure():
    jobs = [
        {"job_id": 103151, "lsf_status": "RUN", "last_change_time": "2026-08-28T01:00:00Z"},
        {"job_id": 103162, "lsf_status": "EXIT", "uvm_fatal_count": 0, "last_change_time": "2026-08-28T00:42:31Z"},
        {"job_id": 103170, "lsf_status": "DONE", "uvm_fatal_count": 1, "last_change_time": "2026-08-28T00:50:00Z"},
    ]
    ff = _first_failure(jobs)
    assert ff == {"job_id": 103162, "timestamp": "2026-08-28T00:42:31Z"}
    assert _first_failure([{"job_id": 1, "lsf_status": "RUN"}]) is None


def test_dashboard_execution_mode_reads_env_check_evidence():
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / ".dv-harness").mkdir()
        state = {"stages": {"ENV_CHECK": {"last_message": (
            "```dv-harness-evidence:execution_mode_validator\n"
            '{"execution_mode": "PURE_LOCAL_READ_ANALYSIS", "actions": []}\n'
            "```\n"
        )}}}
        (tmp / ".dv-harness" / "state.json").write_text(json.dumps(state))
        assert _execution_mode(tmp) == "PURE_LOCAL_READ_ANALYSIS"
    finally:
        shutil.rmtree(tmp)
    assert _execution_mode(Path(tempfile.mkdtemp())) is None


def test_dashboard_environment_mode_selected_reads_evidence_from_any_stage():
    # Mirrors test_dashboard_execution_mode_reads_env_check_evidence() above
    # exactly, for _environment_mode_selected()'s environment_mode_selection
    # block -- except unlike execution_mode_validator (always ENV_CHECK-only),
    # no single canonical stage is nailed down for this evidence block yet,
    # so the scan covers every stage (same scan-all-stages shape
    # _dv_review_pending() already uses), proven here by putting it on a
    # stage other than ENV_CHECK.
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / ".dv-harness").mkdir()
        state = {"stages": {"DISCOVERY": {"last_message": (
            "```dv-harness-evidence:environment_mode_selection\n"
            '{"environment_mode": "SUBSYSTEM_MODE"}\n'
            "```\n"
        )}}}
        (tmp / ".dv-harness" / "state.json").write_text(json.dumps(state))
        assert _environment_mode_selected(tmp) == "SUBSYSTEM_MODE"
    finally:
        shutil.rmtree(tmp)
    assert _environment_mode_selected(Path(tempfile.mkdtemp())) is None


def test_dashboard_qualification_tier_reached_derives_highest_from_protocol_registry():
    # _qualification_tier_reached() is the real per-run counterpart to
    # _qualification_tiers()'s static ladder: the highest CANONICAL_LADDER
    # tier actually reached by any protocol in this project's real
    # protocol_capability_registry.json.
    tmp = Path(tempfile.mkdtemp())
    try:
        registry_dir = tmp / ".dv-harness" / "qualification"
        registry_dir.mkdir(parents=True)
        (registry_dir / "protocol_capability_registry.json").write_text(json.dumps({
            "protocols": {
                "USB": {"qualification_status": "ENV_GENERATED"},
                "PCIe": {"qualification_status": "SMOKE_QUALIFIED"},
            }
        }))
        assert _qualification_tier_reached(tmp) == "SMOKE_QUALIFIED"
    finally:
        shutil.rmtree(tmp)
    # No registry at all -> honest None, never a fabricated tier.
    assert _qualification_tier_reached(Path(tempfile.mkdtemp())) is None


def test_dashboard_graph_reflects_real_stage_status():
    g = _graph_with_status(ROOT, "DISCOVERY")
    ids = {n["id"] for n in g["nodes"]}
    assert "ENV_CHECK" in ids and "SIGNOFF" in ids
    assert "ANALYSIS_JOIN" in ids  # synthetic join node still surfaced
    discovery = next(n for n in g["nodes"] if n["id"] == "DISCOVERY")
    assert discovery["agent"] == "analysis-agent"


def test_simulation_gate_reads_sim_log_from_real_file_path():
    # Evidence Collection automation: an agent-supplied 'sim_log_path' must be
    # read from a real file rather than trusted as inline pasted text.
    tmp = Path(tempfile.mkdtemp())
    try:
        log_path = tmp / "sim.log"
        log_path.write_text("UVM_INFO enum PASS at time 100")
        transcript_path = tmp / "verify.txt"
        transcript_path.write_text("REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\nVerification passed\n")
        # Build VERIFY_EXTRA_GATES with real transcript path
        verify_extra_with_transcript = _VERIFY_EXTRA_GATES.replace(
            '```dv-harness-evidence:remote_execution_provenance_gate\n{"transcript_path": "/tmp/verify.txt", "claimed_exit_code": 0}\n```\n',
            '```dv-harness-evidence:remote_execution_provenance_gate\n' + json.dumps({"transcript_path": str(transcript_path), "claimed_exit_code": 0}) + '\n```\n'
        )
        text = (
            "```dv-harness-evidence:simulation_semantic_validation_gate\n"
            + json.dumps({
                "simulation_passed": True,
                "sim_log_path": str(log_path),
                "command_expectations": [{
                    "expectation_id": "e1", "required": True,
                    "evidence_requirements": [{"pattern": "enum PASS", "match_mode": "SUBSTRING"}],
                }],
            })
            + "\n```\n"
            + "```dv-harness-evidence:test_result_provenance_gate\n"
            '{"results": [{"testcase_id": "t1", "run_id": "r1", "rtl_revision": "a", '
            '"tb_revision": "b", "vip_version": "c", "tool_version": "d", "seed": "1", '
            '"config_hash": "h", "result": "PASS", "log_hash": "lh", "evidence_bundle_hash": "eh"}]}\n'
            "```\n"
            "```dv-harness-evidence:false_pass_resistance_gate\n"
            '{"positive_test_pass": true, "negative_test_detects_fault": true, '
            '"checker_detects_injected_fault": true, "semantic_log_match": true, '
            '"oracle_independent": true, "proof_bundle_hash": "h1"}\n'
            "```\n"
            + verify_extra_with_transcript
        )
        verdict, reasons = evaluate_stage_evidence(ROOT, "VERIFY", text)
        assert verdict == "PASS", reasons
    finally:
        shutil.rmtree(tmp)


def test_simulation_gate_fails_closed_on_missing_sim_log_path():
    # A path that doesn't resolve to a real file must fail closed
    # (INSUFFICIENT_EVIDENCE), not silently fall back to an empty log.
    tmp = Path(tempfile.mkdtemp())
    try:
        text = (
            "```dv-harness-evidence:simulation_semantic_validation_gate\n"
            + json.dumps({
                "simulation_passed": True,
                "sim_log_path": str(tmp / "does_not_exist.log"),
                "command_expectations": [{
                    "expectation_id": "e1", "required": True,
                    "evidence_requirements": [{"pattern": "enum PASS", "match_mode": "SUBSTRING"}],
                }],
            })
            + "\n```\n"
        )
        verdict, reasons = evaluate_stage_evidence(ROOT, "VERIFY", text)
        assert verdict == "GATE_FAIL"
        assert any("SIM_LOG_PATH_NOT_FOUND" in r for r in reasons)
    finally:
        shutil.rmtree(tmp)


def test_coverage_closure_requires_hole_regeneration_and_test_generation_gates():
    # Coverage Hole Analysis: a coverage hole with no waiver must be
    # classified and, for the regenerable classes, have a regenerated
    # testcase + rerun evidence -- not just get waived through.
    base = {
        "signoff_requested": True, "true_pass": True, "active_failure_count": 0,
        "coverage_credit_percent": 100, "waived_items": 0, "approved_waivers": True,
    }
    credit = {"active_failure_ids": [], "items": [
        {"coverage_id": "c1", "credit": True, "active_checker_ids": ["chk1"],
         "waived": False, "linked_failure_ids": []}]}
    quality = {"coverage_items": [
        {"coverage_id": "c1", "requirement_ids": ["r1"], "hit": True, "credit": True,
         "checker_ids": ["chk1"], "execution_evidence": ["ev1"]}]}

    incomplete_hole = {"coverage_holes": [
        {"coverage_id": "c1", "waived": False, "root_cause_classification": "MISSING_TEST"}]}
    incomplete_item = {"items": [
        {"id": "c1", "covered": False, "generated_test_ids": ["t1"], "closure_owner": "alice"}]}
    text_incomplete = (
        f"```dv-harness-evidence:coverage_signoff_verdict_gate\n{json.dumps(base)}\n```\n"
        f"```dv-harness-evidence:coverage_credit_consistency_gate\n{json.dumps(credit)}\n```\n"
        f"```dv-harness-evidence:coverage_quality_gate\n{json.dumps(quality)}\n```\n"
        f"```dv-harness-evidence:coverage_hole_regeneration_gate\n{json.dumps(incomplete_hole)}\n```\n"
        f"```dv-harness-evidence:coverage_hole_to_test_generation_gate\n{json.dumps(incomplete_item)}\n```\n"
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "COVERAGE_CLOSURE", text_incomplete)
    assert verdict == "GATE_FAIL", reasons

    complete_hole = {"coverage_holes": [
        {"coverage_id": "c1", "waived": False, "root_cause_classification": "MISSING_TEST",
         "regenerated_testcase_ids": ["t1"], "rerun_evidence": "rerun-ev-1"}]}
    complete_item = {"items": [
        {"id": "c1", "covered": False, "generated_test_ids": ["t1"], "closure_owner": "alice",
         "trace_to_vplan": "vplan-item-1"}]}
    text_complete = (
        f"```dv-harness-evidence:coverage_signoff_verdict_gate\n{json.dumps(base)}\n```\n"
        f"```dv-harness-evidence:coverage_credit_consistency_gate\n{json.dumps(credit)}\n```\n"
        f"```dv-harness-evidence:coverage_quality_gate\n{json.dumps(quality)}\n```\n"
        f"```dv-harness-evidence:coverage_hole_regeneration_gate\n{json.dumps(complete_hole)}\n```\n"
        f"```dv-harness-evidence:coverage_hole_to_test_generation_gate\n{json.dumps(complete_item)}\n```\n"
        + _COVERAGE_CLOSURE_EXTRA_GATES
    )
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "COVERAGE_CLOSURE", text_complete)
    assert verdict2 == "PASS", reasons2


def test_run_stage_appends_real_coverage_history_sample_on_coverage_closure_pass():
    # Task 6 (poster-gap-closing round 2): dashboard.append_coverage_history_sample()
    # was real, tested rendering/storage logic whose own docstring admitted "not
    # currently called by any engine stage yet". A real COVERAGE_CLOSURE PASS
    # must now grow .dv-harness/coverage/history.json with the actual
    # coverage_signoff_verdict_gate-reported coverage_credit_percent (the one
    # COVERAGE_CLOSURE gate whose evidence carries a real coverage percent --
    # see coverage_signoff_verdict_gate.py's own `coverage_credit_percent`
    # field) -- not a placeholder -- mirroring _promote_experience_knowledge's
    # exact "helper method, gated on STAGE_GATES, called from the PASS branch"
    # pattern.
    from dv_harness.engine import DVHarness
    from dv_harness.adapters.base import AgentResult

    tmp = _mk_smoke_project()
    try:
        base = {
            "signoff_requested": True, "true_pass": True, "active_failure_count": 0,
            "coverage_credit_percent": 87, "waived_items": 0, "approved_waivers": True,
        }
        credit = {"active_failure_ids": [], "items": [
            {"coverage_id": "c1", "credit": True, "active_checker_ids": ["chk1"],
             "waived": False, "linked_failure_ids": []}]}
        quality = {"coverage_items": [
            {"coverage_id": "c1", "requirement_ids": ["r1"], "hit": True, "credit": True,
             "checker_ids": ["chk1"], "execution_evidence": ["ev1"]}]}
        complete_hole = {"coverage_holes": [
            {"coverage_id": "c1", "waived": False, "root_cause_classification": "MISSING_TEST",
             "regenerated_testcase_ids": ["t1"], "rerun_evidence": "rerun-ev-1"}]}
        complete_item = {"items": [
            {"id": "c1", "covered": False, "generated_test_ids": ["t1"], "closure_owner": "alice",
             "trace_to_vplan": "vplan-item-1"}]}
        text = (
            f"```dv-harness-evidence:coverage_signoff_verdict_gate\n{json.dumps(base)}\n```\n"
            f"```dv-harness-evidence:coverage_credit_consistency_gate\n{json.dumps(credit)}\n```\n"
            f"```dv-harness-evidence:coverage_quality_gate\n{json.dumps(quality)}\n```\n"
            f"```dv-harness-evidence:coverage_hole_regeneration_gate\n{json.dumps(complete_hole)}\n```\n"
            f"```dv-harness-evidence:coverage_hole_to_test_generation_gate\n{json.dumps(complete_item)}\n```\n"
            + _COVERAGE_CLOSURE_EXTRA_GATES
        )

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        h = DVHarness(tmp)
        h.adapter = _PassAdapter()
        h.set_stage("COVERAGE_CLOSURE")

        history_path = tmp / ".dv-harness" / "coverage" / "history.json"
        assert not history_path.exists()

        h.run_stage("goal")
        assert h.state.stages["COVERAGE_CLOSURE"]["status"] == Status.PASS.value

        history = json.loads(history_path.read_text(encoding="utf-8"))
        assert len(history) == 1
        assert history[0]["percent"] == 87
        assert "timestamp" in history[0]
    finally:
        shutil.rmtree(tmp)


def test_run_stage_promotes_project_topology_to_project_memory_on_pass():
    # Task 9 (poster-gap-closing round 2): PROJECT_MODEL's
    # project_model_topology_completeness_gate already structurally verifies
    # a complete verification-boundary/VIP-topology/block-classification
    # model (real subprocess-verified evidence) on PASS, but nothing
    # persisted it as reusable Project-tier memory -- mirrors
    # _promote_experience_knowledge's exact "helper method, gated on
    # STAGE_GATES, called from the PASS branch" pattern.
    from dv_harness.engine import DVHarness
    from dv_harness.adapters.base import AgentResult
    from dv_harness.memory import ProjectMemoryStore

    tmp, h = _fresh_harness()
    try:
        gate_dir = tmp / "tools" / "verification_flow"
        gate_dir.mkdir(parents=True)
        shutil.copy(ROOT / "tools" / "verification_flow" / "project_model_topology_completeness_gate.py",
                    gate_dir / "project_model_topology_completeness_gate.py")
        # ADDED (2026-09-01, route-skill-resolver-dynamic-implementation
        # task): PROJECT_MODEL now also mandates environment_mode_selection_
        # gate -- see gates.STAGE_GATES["PROJECT_MODEL"].
        shutil.copy(ROOT / "tools" / "verification_flow" / "environment_mode_selection_gate.py",
                    gate_dir / "environment_mode_selection_gate.py")
        h.set_stage("PROJECT_MODEL")

        complete = {"verification_boundary": "top.usb_dev",
                    "vip_topology": [{"vip_id": "usb_vip", "bound_interface": "usb_if0"}],
                    "blocks": [{"block_id": "b1", "branch": "BLOCK"}],
                    "model_confidence": "HIGH", "confidence_basis": "cross-checked with RTL arch discovery",
                    "dv_readiness": "READY", "dv_readiness_basis": "all boundary items resolved",
                    "architecture_evidence_db_ref": "arch-db-v3"}
        env_mode = {"environment_mode": "SUBSYSTEM_MODE", "requested_subsystems": ["usb"]}
        text = (
            f"```dv-harness-evidence:project_model_topology_completeness_gate\n{json.dumps(complete)}\n```\n"
            f"```dv-harness-evidence:environment_mode_selection\n{json.dumps(env_mode)}\n```\n"
        )

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        h.adapter = _PassAdapter()
        h.run_stage("goal")
        assert h.state.stages["PROJECT_MODEL"]["status"] == Status.PASS.value

        proj_store = ProjectMemoryStore(tmp)
        rows = [r for r in proj_store.store._index() if r.get("level") == "project"]
        assert rows, f"no Project Memory record written: {proj_store.store._index()}"
        rec = proj_store.get(rows[0]["memory_id"])
        assert rec is not None
        assert rec["verification_boundary"] == "top.usb_dev"
        assert rec["dv_readiness"] == "READY"
        assert rec["level"] == "project"

        events = (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
        promo_events = [json.loads(e) for e in events if json.loads(e).get("event") == "PROJECT_TOPOLOGY_PROMOTED"]
        assert promo_events and promo_events[0]["promotion"]["memory_id"] == rec["memory_id"]
    finally:
        shutil.rmtree(tmp)


def test_run_stage_promotes_vplan_summary_to_project_memory_on_pass():
    # memory-engine-schema-completion audit (2026-09-01): Project Memory was
    # populated by exactly ONE gate (project_model_topology_completeness_gate,
    # tested above) -- vPlan content had no separate write path at all. This
    # proves the second real gate-triggered writer: a PASS on VPLAN's
    # vplan_writer_validation_gate (gates.py, vplan-doc-and-wiring-fix) now
    # also persists a vPlan summary as Project-tier memory.
    import os
    from dv_harness.engine import DVHarness
    from dv_harness.adapters.base import AgentResult
    from dv_harness.memory import ProjectMemoryStore

    tmp, h = _fresh_harness()
    try:
        gate_dir = tmp / "tools" / "vplan"
        gate_dir.mkdir(parents=True)
        shutil.copy(ROOT / "tools" / "vplan" / "spec_coverage_audit.py",
                    gate_dir / "spec_coverage_audit.py")
        shutil.copy(ROOT / "tools" / "vplan" / "vplan_writer_validation_gate.py",
                    gate_dir / "vplan_writer_validation_gate.py")
        h.set_stage("VPLAN")

        # Real on-disk evidence vplan_writer_validation_gate's real
        # dv_harness.vplan_writer.validate_items() actually checks against --
        # same fixture shape as
        # dv_harness_tests/test_vplan_writer_validation_gate.py's _make_fake_env.
        pattern_dir = tmp / "patterns"
        pattern_dir.mkdir()
        (pattern_dir / "USB2_bulkin.txt").write_text("bulkin pattern", encoding="utf-8")
        dispatcher_file = tmp / "dv_uvm_pattern_pool.svh"
        dispatcher_file.write_text(
            'case (pattern_name)\n  "USB2_bulkin": run_bulkin();\nendcase\n', encoding="utf-8",
        )
        tests_dir = tmp / "tests"
        tests_dir.mkdir()
        (tests_dir / "usb_bulkin_test.sv").write_text(
            "task automatic usb_bulkin_test();\nendtask\n", encoding="utf-8",
        )
        items = [
            {"req_id": "USB2-BULK-001", "feature_area": "Bulk Transfers",
             "verification_item": "Bulk IN transfer completes",
             "pattern_name": "USB2_bulkin", "task_name": "usb_bulkin_test",
             "suite": "USB2_sanity", "covered_by": "covered",
             "description": "Directed bulk-in transfer test", "spec_section": "TBD-spec",
             "constraint_items": [], "random_or_directed": "directed", "mode_speed": "HS",
             "instance": "N/A", "checkers_active": ["sb_bulk_data_match"], "notes": "",
             "blocked_on": None, "blocked_reason": None},
        ]
        vplan_validation_payload = {
            "items": items,
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        }
        spec_coverage_payload = {"requirements": [{"req_id": "USB2-BULK-001", "status": "VERIFIED"}]}
        text = (
            f"```dv-harness-evidence:spec_coverage_audit\n{json.dumps(spec_coverage_payload)}\n```\n"
            f"```dv-harness-evidence:vplan_writer_validation_gate\n{json.dumps(vplan_validation_payload)}\n```\n"
        )

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        h.adapter = _PassAdapter()
        # vplan_writer_validation_gate.py imports dv_harness.vplan_writer --
        # its own sys.path.insert(0, ...) resolves to the copied script's
        # location (tmp), not the real package, so the subprocess needs the
        # real project root on PYTHONPATH to find dv_harness at all (see
        # this file's own confirmed-empirically note in the implementation
        # report for memory-engine-schema-completion).
        env_patch = dict(os.environ)
        env_patch["PYTHONPATH"] = str(ROOT) + os.pathsep + env_patch.get("PYTHONPATH", "")
        with patch.dict(os.environ, env_patch):
            h.run_stage("goal")
        assert h.state.stages["VPLAN"]["status"] == Status.PASS.value

        proj_store = ProjectMemoryStore(tmp)
        rows = [r for r in proj_store.store._index() if r.get("level") == "project"]
        assert rows, f"no Project Memory record written for VPLAN: {proj_store.store._index()}"
        rec = proj_store.get(rows[0]["memory_id"])
        assert rec is not None
        assert rec["level"] == "project"
        assert rec["vplan_item_count"] == 1
        assert rec["vplan_feature_areas"] == ["Bulk Transfers"]
        assert rec["vplan_req_ids"] == ["USB2-BULK-001"]
        assert rec["vplan_suites"] == ["USB2_sanity"]

        events = (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
        promo_events = [json.loads(e) for e in events if json.loads(e).get("event") == "VPLAN_SUMMARY_PROMOTED"]
        assert promo_events and promo_events[0]["promotion"]["memory_id"] == rec["memory_id"]
    finally:
        shutil.rmtree(tmp)


def test_run_stage_does_not_promote_project_topology_when_gate_fails():
    # No spurious Project Memory record when the gate rejects the evidence
    # (a block missing its branch classification) -- PARTIAL, not PASS.
    from dv_harness.adapters.base import AgentResult
    from dv_harness.memory import ProjectMemoryStore

    tmp, h = _fresh_harness()
    try:
        gate_dir = tmp / "tools" / "verification_flow"
        gate_dir.mkdir(parents=True)
        shutil.copy(ROOT / "tools" / "verification_flow" / "project_model_topology_completeness_gate.py",
                    gate_dir / "project_model_topology_completeness_gate.py")
        h.set_stage("PROJECT_MODEL")

        no_branch = {"verification_boundary": "top.usb_dev",
                     "vip_topology": [{"vip_id": "usb_vip", "bound_interface": "usb_if0"}],
                     "blocks": [{"block_id": "b1"}],
                     "model_confidence": "HIGH", "confidence_basis": "x",
                     "dv_readiness": "READY", "dv_readiness_basis": "x",
                     "architecture_evidence_db_ref": "db1"}
        text = f"```dv-harness-evidence:project_model_topology_completeness_gate\n{json.dumps(no_branch)}\n```\n"

        class _PartialAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        h.adapter = _PartialAdapter()
        h.run_stage("goal")
        assert h.state.stages["PROJECT_MODEL"]["status"] != Status.PASS.value

        # No spurious PROJECT-tier record -- but a WORKING-tier record from
        # ReactRecorder.record() (memory-engine-schema-completion, 2026-09-01)
        # is now expected on EVERY stage attempt regardless of verdict, since
        # that tier is exactly the provisional hypothesis/evidence/next-action
        # bookkeeping this stage attempt genuinely produced -- see
        # dv_harness/react.py's ReactRecorder module-header RULING comment.
        proj_store = ProjectMemoryStore(tmp)
        assert [r for r in proj_store.store._index() if r.get("level") == "project"] == []
    finally:
        shutil.rmtree(tmp)


def test_run_stage_retrieves_relevant_memory_into_the_prompt():
    # Task 9: MemoryRetriever.search() had zero callers anywhere in the real
    # engine flow before this -- a stage's prompt was never actually
    # informed by prior memory, only by the Blackboard snapshot. Seed a
    # Project-tier record relevant to the fixture goal and confirm its
    # title actually reaches the prompt handed to the adapter.
    from dv_harness.engine import DVHarness
    from dv_harness.adapters.base import AgentResult
    from dv_harness.memory import MemoryStore

    tmp, h = _fresh_harness()
    try:
        marker = "MEMORY_MARKER_USB2_SCOREBOARD_PITFALL_ABCDE"
        goal = "investigate scoreboard port ownership issues in the usb2 subsystem"
        assert marker not in goal  # sanity: the marker must come from memory, not be echoed from the goal itself
        MemoryStore(tmp).add("project", {
            "title": marker,
            "protocol": "USB2", "scope": "subsystem",
            "root_cause": "usb2 scoreboard port ownership global expected queue shared across ports",
        })

        calls = []

        class FakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                calls.append(prompt)
                return AgentResult(ok=True, text="ok", raw={}, session_id=None)

        h.adapter = FakeAdapter()
        h.set_stage("DISCOVERY")
        h.run_stage(goal)

        assert calls, "adapter was never called"
        assert marker not in goal
        assert marker in calls[0]
    finally:
        shutil.rmtree(tmp)


def test_run_stage_with_no_relevant_memory_is_a_pure_no_op():
    # No seeded memory anywhere -- MemoryRetriever.search() must return no
    # hits, and build_stage_prompt() must be called with a falsy
    # relevant_memory (None or []), which prompts.build_stage_prompt's own
    # additive-kwargs contract guarantees reproduces the exact same prompt
    # as if relevant_memory had never been threaded in at all -- proven here
    # by actually calling the real build_stage_prompt both ways and
    # comparing, not merely asserting "no crash".
    import dv_harness.engine as engine_mod
    from dv_harness.adapters.base import AgentResult

    tmp, h = _fresh_harness()
    try:
        calls = []
        captured = {}
        real_build_stage_prompt = engine_mod.build_stage_prompt

        def _spy(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = dict(kwargs)
            return real_build_stage_prompt(*args, **kwargs)

        class FakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                calls.append(prompt)
                return AgentResult(ok=True, text="ok", raw={}, session_id=None)

        h.adapter = FakeAdapter()
        h.set_stage("DISCOVERY")
        with patch.object(engine_mod, "build_stage_prompt", side_effect=_spy):
            h.run_stage("a goal with nothing seeded in memory")

        assert calls, "adapter was never called"
        assert "kwargs" in captured
        assert not captured["kwargs"].get("relevant_memory")  # None or [] -- genuinely empty

        with_kwarg = real_build_stage_prompt(*captured["args"], **captured["kwargs"])
        without_memory_kwarg = real_build_stage_prompt(
            *captured["args"],
            **{k: v for k, v in captured["kwargs"].items() if k != "relevant_memory"})
        assert with_kwarg == without_memory_kwarg
    finally:
        shutil.rmtree(tmp)


def test_run_stage_with_only_irrelevant_memory_is_a_pure_no_op():
    # Finding I2 (2026-08-31 fix wave): the ORIGINAL no-op test above only
    # proved "empty store" is a no-op -- it never proved "irrelevant record"
    # is a no-op. MemoryRetriever.search() had an always-positive recency
    # component (plus a confidence component independent of the query), so
    # once ANY memory record exists -- guaranteed in normal operation by
    # Task 9's own write sites (_promote_experience_knowledge,
    # _promote_project_topology_knowledge, job-tier writes) -- a completely
    # unrelated record could still be returned as "relevant" and leak into
    # every stage's prompt. Seed one genuinely irrelevant record (unrelated
    # protocol/scope/symptoms/text -- an ethernet/LSF record, matching the
    # reviewer's own empirical repro) and confirm run_stage() is STILL a
    # pure no-op: relevant_memory stays falsy and the prompt is byte-for-byte
    # identical to the no-memory-kwarg prompt.
    import dv_harness.engine as engine_mod
    from dv_harness.adapters.base import AgentResult
    from dv_harness.memory import MemoryStore

    tmp, h = _fresh_harness()
    try:
        MemoryStore(tmp).add("project", {
            "title": "Ethernet MAC LSF job stuck in PEND due to license checkout failure",
            "protocol": "Ethernet", "scope": "lsf_infra",
            "symptoms": ["lsf_pend", "license_checkout_failure"],
            "root_cause": "LSF license server exhausted synopsys_vcs tokens during peak batch window",
            "confidence": "CONFIRMED",
        })

        calls = []
        captured = {}
        real_build_stage_prompt = engine_mod.build_stage_prompt

        def _spy(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = dict(kwargs)
            return real_build_stage_prompt(*args, **kwargs)

        class FakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                calls.append(prompt)
                return AgentResult(ok=True, text="ok", raw={}, session_id=None)

        h.adapter = FakeAdapter()
        h.set_stage("DISCOVERY")
        with patch.object(engine_mod, "build_stage_prompt", side_effect=_spy):
            h.run_stage("investigate usb3 coverage closure holes in the scoreboard")

        assert calls, "adapter was never called"
        assert "kwargs" in captured
        assert not captured["kwargs"].get("relevant_memory"), (
            "an unrelated ethernet/LSF record leaked into an unrelated USB "
            "coverage query's relevant_memory")
        assert "Ethernet MAC LSF job" not in calls[0]

        with_kwarg = real_build_stage_prompt(*captured["args"], **captured["kwargs"])
        without_memory_kwarg = real_build_stage_prompt(
            *captured["args"],
            **{k: v for k, v in captured["kwargs"].items() if k != "relevant_memory"})
        assert with_kwarg == without_memory_kwarg
    finally:
        shutil.rmtree(tmp)


def test_memory_retriever_search_excludes_pure_recency_match():
    # Unit-level companion to the run_stage-level no-op test above: directly
    # exercises MemoryRetriever.search() (not through the engine) with the
    # reviewer's exact empirical repro shape -- an unrelated ethernet/LSF
    # record searched against an unrelated USB coverage query -- and proves
    # it is excluded, not merely returned with a low score. Before the I2
    # fix this returned the record at score 1.0 (pure recency, since the
    # record's confidence defaults to "UNKNOWN" which contributes 0).
    tmp = Path(tempfile.mkdtemp())
    try:
        store = MemoryStore(tmp)
        store.add("project", {
            "title": "Ethernet MAC LSF job stuck in PEND",
            "protocol": "Ethernet", "scope": "lsf_infra",
            "symptoms": ["lsf_pend"],
            "root_cause": "LSF license server exhausted tokens",
        })
        hits = MemoryRetriever(store).search({"text": "usb3 coverage closure scoreboard"})
        assert hits == []
    finally:
        shutil.rmtree(tmp)


def test_run_stage_failure_recovery_queries_knowledge_center_when_configured():
    # Real gap (knowledge-center-pre-stage-read audit follow-up, 2026-09-02):
    # KnowledgeCenterClient.search() (dv_harness/knowledge_center.py) had
    # exactly two real callers -- the manual 'dv-harness knowledge search'
    # CLI subcommand and the dashboard GUI -- never the real engine flow.
    # The ONE automatic pre-stage memory read that DID exist (the
    # relevant_memory tests directly above) queries the purely LOCAL
    # per-project MemoryStore, a different store than the shared, cross-user
    # Knowledge Center this proves is now actually consulted (and surfaced
    # into the built prompt) before FAILURE_RECOVERY. A fake client is
    # patched in so no real relay/network call is ever attempted.
    import dv_harness.engine as engine_mod
    from dv_harness.adapters.base import AgentResult

    tmp, h = _fresh_harness()
    try:
        h.cfg["knowledge_center"] = {
            "enabled": True, "remote_root": "/srv/dvhkc", "vchost": "vchost-a", "vchop": "host-a",
        }
        marker = "KC_MARKER_STUCK_FIFO_UNDERFLOW_ROOT_CAUSE_XYZ"
        calls = []

        class FakeKCClient:
            def __init__(self, cfg, root):
                calls.append(("init", cfg, root))

            def configured(self):
                return True

            def search(self, category="", protocol="", text="", limit=8):
                calls.append(("search", category, protocol, text, limit))
                return {"ok": True, "count": 1, "records": [
                    {"memory_id": "KC-DEADBEEF0001", "symptom": marker,
                     "root_cause": "fifo pointer wraps one cycle early under back-to-back writes"},
                ]}

        class FakeAdapter:
            def __init__(self):
                self.prompts = []

            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                self.prompts.append(prompt)
                return AgentResult(ok=True, text="ok", raw={}, session_id=None)

        h.adapter = FakeAdapter()
        h.set_stage("FAILURE_RECOVERY")
        with patch.object(engine_mod, "KnowledgeCenterClient", FakeKCClient):
            h.run_stage("debug the recurring fifo underflow failure")

        assert any(c[0] == "search" for c in calls), "KnowledgeCenterClient.search() was never called"
        assert h.adapter.prompts, "adapter was never called"
        assert marker in h.adapter.prompts[0], "KC search result never reached the built prompt"
        assert "KC-DEADBEEF0001" in h.adapter.prompts[0]
    finally:
        shutil.rmtree(tmp)


def test_run_stage_failure_recovery_skips_knowledge_center_when_not_configured():
    # Companion no-op proof: when the shared Knowledge Center is not
    # configured (the real default -- see config.py's knowledge_center
    # block, "Deliberately OFF and EMPTY by default"), search() must never
    # even be attempted, and the stage must run exactly as before this gap
    # was closed -- no exception, no dead-client instantiation surprise.
    import dv_harness.engine as engine_mod
    from dv_harness.adapters.base import AgentResult

    tmp, h = _fresh_harness()
    try:
        assert h.cfg.get("knowledge_center", {}).get("enabled") is not True

        calls = []

        class ExplodingKCClient:
            def __init__(self, cfg, root):
                pass

            def configured(self):
                return False

            def search(self, *a, **k):
                calls.append("search")
                raise AssertionError("search() must not be called when the KC is not configured")

        class FakeAdapter:
            def __init__(self):
                self.prompts = []

            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                self.prompts.append(prompt)
                return AgentResult(ok=True, text="ok", raw={}, session_id=None)

        h.adapter = FakeAdapter()
        h.set_stage("FAILURE_RECOVERY")
        with patch.object(engine_mod, "KnowledgeCenterClient", ExplodingKCClient):
            h.run_stage("debug a one-off failure with no prior shared record")

        assert not calls, "search() was called despite the shared Knowledge Center being unconfigured"
        assert h.adapter.prompts, "adapter was never called"
    finally:
        shutil.rmtree(tmp)


def test_wave_analysis_requires_confirmed_dump_scope():
    # CLAUDE.md "Waveform Dump User Gate": found by the 2026-08-28 GUI/CLI
    # end-to-end confirmation audit to have a governance policy file
    # (.dv-harness/governance/waveform_dump_policy.json) but literally no
    # enforcing gate anywhere -- an agent could open full-depth waveform
    # dumping without ever asking the user, and nothing would catch it.
    base = {"deep_debug_required": True, "wave_mode": 1, "fsdb_start_us": 0,
            "first_error_time_us": 100, "fsdb_stop_us": 300.0,
            "simulation_stopped_at_fsdb_stop": True, "job_killed_or_terminated": True,
            "identity_preserved": True, "waveform_or_fsdbreport_evidence_hash": "h1"}

    text_no_confirmation = f"```dv-harness-evidence:focused_wave_debug_window_gate\n{json.dumps(base)}\n```\n"
    verdict, reasons = evaluate_stage_evidence(ROOT, "WAVE_ANALYSIS", text_no_confirmation)
    assert verdict == "GATE_FAIL", reasons
    assert any("WAVEFORM_DUMP_SCOPE_NOT_CONFIRMED" in str(r) for r in reasons)

    incomplete = dict(base, dump_scope_confirmed={"scope": "top.usb_dev"})
    text_incomplete = f"```dv-harness-evidence:focused_wave_debug_window_gate\n{json.dumps(incomplete)}\n```\n"
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "WAVE_ANALYSIS", text_incomplete)
    assert verdict2 == "GATE_FAIL", reasons2
    assert any("WAVEFORM_DUMP_SCOPE_CONFIRMATION_INCOMPLETE" in str(r) for r in reasons2)

    complete = dict(base, dump_scope_confirmed={
        "scope": "top.usb_dev.ctrl", "level_or_depth": "signal-level, block-scoped",
        "confirmed_by": "user"})
    text_complete = f"```dv-harness-evidence:focused_wave_debug_window_gate\n{json.dumps(complete)}\n```\n"
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "WAVE_ANALYSIS", text_complete)
    assert verdict3 == "PASS", reasons3


def test_regression_monitor_requires_run_identity_consistency():
    # 12-claim re-audit (2026-08-28): CLAUDE.md's "same regression batch must
    # use the same source/build/config identity" rule had a correct gate
    # script (run_identity_consistency_gate.py) that was registered but never
    # wired into STAGE_GATES -- so cross-run evidence could silently pass.
    jobs = {"jobs": [{"job_id": "j1", "agent_id": "a1", "sim_log": "log text",
                      "uvm_error_detected": False, "fatal_detected": False,
                      "evidence_captured": True, "kill_requested": False}]}
    results = {"results": [{"testcase_id": "t1", "run_id": "R1", "result": "PASS",
                            "log_hash": "h1", "evidence_bundle_hash": "b1"}]}

    cross_run_identity = {"canonical_run_id": "R1", "canonical_build_hash": "B1",
                          "evidence": [{"evidence_id": "e1", "run_id": "R2", "build_hash": "B1"}]}
    text_cross_run = (
        f"```dv-harness-evidence:lsf_per_job_monitor_gate\n{json.dumps(jobs)}\n```\n"
        f"```dv-harness-evidence:regression_result_uniqueness_gate\n{json.dumps(results)}\n```\n"
        f"```dv-harness-evidence:run_identity_consistency_gate\n{json.dumps(cross_run_identity)}\n```\n"
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "REGRESSION_MONITOR", text_cross_run)
    assert verdict == "GATE_FAIL", reasons

    consistent_identity = {"canonical_run_id": "R1", "canonical_build_hash": "B1",
                           "evidence": [{"evidence_id": "e1", "run_id": "R1", "build_hash": "B1"}]}
    text_consistent = (
        f"```dv-harness-evidence:lsf_per_job_monitor_gate\n{json.dumps(jobs)}\n```\n"
        f"```dv-harness-evidence:regression_result_uniqueness_gate\n{json.dumps(results)}\n```\n"
        f"```dv-harness-evidence:run_identity_consistency_gate\n{json.dumps(consistent_identity)}\n```\n"
        + _REGRESSION_MONITOR_EXTRA_GATES
    )
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "REGRESSION_MONITOR", text_consistent)
    assert verdict2 == "PASS", reasons2


# --- Multi-flag gate extension (2026-08-28): run_gate()/STAGE_GATES gained
# EvidenceFlag/ContextFlag support so a single gate can take 2-3 real JSON/
# scalar CLI args instead of exactly one. The four tests below each drive a
# genuinely multi-flag gate through the real evaluate_stage_evidence() ->
# run_gate() -> subprocess path (no mocking of the gate scripts themselves),
# proving both the extension mechanism (EvidenceFlag sub-key extraction,
# ContextFlag harness-supplied values, MISSING_EVIDENCE_SUBPAYLOAD) and each
# gate's own real PASS/FAIL branches.

def test_requirement_closure_traceability_audit_two_evidence_flags():
    # traceability_audit.py needs --vplan and --tests together (two separate
    # JSON files) -- the first gate wired via the multi-flag EvidenceFlag
    # extension. Full REQUIREMENT_CLOSURE stage evidence is supplied for all
    # 5 mapped gates so the PASS case demonstrates a genuine stage PASS, not
    # just an isolated gate call.
    req_ids = [
        "STEP_BY_STEP_INTERACTIVE", "FIVE_CORE_INPUTS", "SPEC", "COMMAND_TXT",
        "PROTOCOL_STANDARD_REFERENCE", "REFERENCE_UVM", "RTL_FIRST_ARCH_DISCOVERY",
        "DE_LOCAL_SIM_BASELINE", "VPLAN_FIRST", "VERIFICATION_ARCHITECTURE",
        "SCOREBOARD_CHECKER_ASSERTION", "TEST_GENERATION", "NEGATIVE_TEST",
        "LOCAL_SIM", "COMMAND_SIMLOG_SEMANTIC", "FALSE_PASS_DEFENSE",
        "DUT_TB_BUG_CLASSIFICATION", "WAVEFORM_RCA", "PROTOCOL_CORNER_CASE",
        "LSF_REGRESSION", "PER_JOB_MONITOR", "REMOTE", "COVERAGE_CLOSURE",
        "SYSTEM_LEVEL", "EXPERT_FEEDBACK", "SIGNOFF", "FEATURE_CONTINUITY",
        "EVIDENCE_PROVENANCE",
    ]
    matrix = {"requirements": [{"requirement_id": r, "implemented": True,
                                "pytest_evidence": True, "hard_gate": True} for r in req_ids]}
    runtime_trace = {"requirements": [{"requirement_id": "R1", "testcase_id": "tc1",
                                       "run_id": "run1", "runtime_evidence_hash": "h1",
                                       "semantic_verdict": "TRUE_PASS"}]}
    closure = {"requirements": [{"req_id": "R1", "status": "VERIFIED",
                                 "execution_evidence": ["e1"], "mechanism_ids": ["m1"]}]}
    e2e = {"requirements": [{"req_id": "R1"}], "mechanisms": [{"mechanism_id": "m1"}],
           "tests": [{"testcase_id": "tc1"}], "coverage": [{"coverage_id": "c1"}],
           "results": [{"result_id": "res1", "result": "PASS"}],
           "links": [{"req_id": "R1", "mechanism_id": "m1", "testcase_id": "tc1",
                     "coverage_id": "c1", "result_id": "res1"}]}
    vplan = {"requirements": [{"req_id": "R1"}]}

    def build(tests_block):
        return (
            f"```dv-harness-evidence:master_requirement_completeness_gate\n{json.dumps(matrix)}\n```\n"
            f"```dv-harness-evidence:requirement_runtime_evidence_gate\n{json.dumps(runtime_trace)}\n```\n"
            f"```dv-harness-evidence:execution_evidence_gate\n{json.dumps(closure)}\n```\n"
            f"```dv-harness-evidence:end_to_end_trace_chain_gate\n{json.dumps(e2e)}\n```\n"
            f"```dv-harness-evidence:traceability_audit\n"
            f'{json.dumps({"vplan": vplan, "tests": tests_block})}\n```\n'
        )

    # FAIL: testcase references a requirement id that does not exist in vplan.
    tests_orphan = {"testcases": [{"testcase_id": "tc1", "vplan_requirement_ids": ["R99"]}]}
    verdict, reasons = evaluate_stage_evidence(ROOT, "REQUIREMENT_CLOSURE", build(tests_orphan))
    assert verdict == "GATE_FAIL", reasons
    assert any("traceability_audit" in r and "unknown R99" in r for r in reasons), reasons

    # PASS: every requirement's traceability_audit sub-payload resolves cleanly.
    tests_ok = {"testcases": [{"testcase_id": "tc1", "vplan_requirement_ids": ["R1"]}]}
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "REQUIREMENT_CLOSURE", build(tests_ok))
    assert verdict2 == "PASS", reasons2

    # Extension mechanism: an EvidenceFlag sub-key entirely missing from the
    # block (not just empty) must fail MISSING_EVIDENCE_SUBPAYLOAD, not crash
    # or silently pass.
    text_missing_tests = (
        f"```dv-harness-evidence:master_requirement_completeness_gate\n{json.dumps(matrix)}\n```\n"
        f"```dv-harness-evidence:requirement_runtime_evidence_gate\n{json.dumps(runtime_trace)}\n```\n"
        f"```dv-harness-evidence:execution_evidence_gate\n{json.dumps(closure)}\n```\n"
        f"```dv-harness-evidence:end_to_end_trace_chain_gate\n{json.dumps(e2e)}\n```\n"
        f"```dv-harness-evidence:traceability_audit\n{json.dumps({'vplan': vplan})}\n```\n"
    )
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "REQUIREMENT_CLOSURE", text_missing_tests)
    assert verdict3 == "GATE_FAIL", reasons3
    assert any("MISSING_EVIDENCE_SUBPAYLOAD" in r and "'tests'" in r for r in reasons3), reasons3


def test_requirements_traceability_waiver_revalidation_gate_three_flags():
    # waiver_revalidation_gate.py needs --waivers (JSON file), --now (a raw
    # scalar, not a JSON path), and --current-revision (also a raw scalar) --
    # the mixed file+raw multi-flag shape. --now is a ContextFlag: the real
    # wall-clock time is supplied by the harness and is never read from the
    # agent's payload, so a waiver's expiry can't be dodged by lying about
    # the current time (see gates.py's ContextFlag docstring / CLAUDE.md's
    # SSH-time-integrity concern this mirrors).
    quality = {"requirements": [{"req_id": "r1", "spec_ref": "s", "feature": "f",
                                 "expected_behavior": "e", "verification_method": "m",
                                 "coverage_goal": "g"}]}
    scope = {"waivers": []}
    freshness = {"waivers": [], "current": {}}

    def build(revalidation_block):
        return (
            f"```dv-harness-evidence:spec_to_vplan_requirement_quality_gate\n{json.dumps(quality)}\n```\n"
            f"```dv-harness-evidence:waiver_scope_consistency_gate\n{json.dumps(scope)}\n```\n"
            f"```dv-harness-evidence:waiver_revision_freshness_gate\n{json.dumps(freshness)}\n```\n"
            f"```dv-harness-evidence:waiver_revalidation_gate\n{json.dumps(revalidation_block)}\n```\n"
        )

    # FAIL: waiver's revision doesn't match current_revision and was never
    # revalidated for it -> WAIVER_REVISION_STALE.
    stale = {"waivers": {"waivers": [{"waiver_id": "W2", "approved": True,
                                      "evidence": "e2", "revision": "REV3"}]},
             "current_revision": "REV5"}
    verdict, reasons = evaluate_stage_evidence(ROOT, "REQUIREMENTS_TRACEABILITY", build(stale))
    assert verdict == "GATE_FAIL", reasons
    assert any("WAIVER_REVISION_STALE" in r for r in reasons), reasons

    # PASS: revision matches current_revision; --now/--current-revision are
    # supplied correctly by the multi-flag path (ContextFlag + raw EvidenceFlag).
    fresh = {"waivers": {"waivers": [{"waiver_id": "W1", "approved": True,
                                      "evidence": "e1", "revision": "REV5"}]},
             "current_revision": "REV5"}
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "REQUIREMENTS_TRACEABILITY", build(fresh))
    assert verdict2 == "PASS", reasons2

    # ContextFlag integrity: the agent never supplies --now at all, yet a
    # waiver expired years ago (relative to the REAL current time, 2026) is
    # still correctly caught -- proving the harness's own wall-clock value is
    # what's actually used, not something read out of the evidence block.
    expired = {"waivers": {"waivers": [{"waiver_id": "W3", "approved": True,
                                        "evidence": "e3", "revision": "REV5",
                                        "expires_at": "2020-01-01T00:00:00+00:00"}]},
               "current_revision": "REV5"}
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "REQUIREMENTS_TRACEABILITY", build(expired))
    assert verdict3 == "GATE_FAIL", reasons3
    assert any("WAIVER_EXPIRED" in r for r in reasons3), reasons3


def test_promotion_readiness_feature_continuity_gate_context_and_evidence_flag():
    # feature_continuity_gate.py mixes a ContextFlag (--root: the real repo
    # root, supplied by the harness so an agent can't point the check
    # somewhere it would trivially pass) with an EvidenceFlag (--required:
    # the agent-attested list of paths that must still exist this revision).
    readiness = {"critical_dimensions": {"coverage": "READY"}, "active_failure_count": 0,
                 "signoff_bundle_complete": True, "evidence_fresh": True}
    chain = {"failure_detected": False, "events": [
        {"stage": "INTAKE_READY", "evidence": "e"},
        {"stage": "VPLAN_READY", "evidence": "e"},
        {"stage": "ARCHITECTURE_READY", "evidence": "e"},
        {"stage": "MECHANISM_READY", "evidence": "e"},
        {"stage": "TESTS_READY", "evidence": "e"},
        {"stage": "TRACEABILITY_READY", "evidence": "e"},
        {"stage": "EXECUTION_EVIDENCE_READY", "evidence": "e"},
        {"stage": "COVERAGE_QUALITY_READY", "evidence": "e"},
        {"stage": "EXPERT_REVIEW_READY", "evidence": "e"},
        {"stage": "EXPERIENCE_READY", "evidence": "e"},
        {"stage": "PROMOTABLE", "evidence": "e"},
    ]}
    closed_loop = {"passed_stages": ["INTAKE_READY", "VPLAN_READY", "ARCHITECTURE_READY",
                                     "MECHANISM_READY", "TESTS_READY", "EXECUTION_EVIDENCE_READY",
                                     "COVERAGE_QUALITY_READY"],
                   "failure_detected": False, "expert_feedback_reviewed": True,
                   "experience_capture_status": "NOT_APPLICABLE"}
    release = {"rtl_revision": "r1", "tb_revision": "t1", "vip_version": "v1",
              "tool_versions": "vcs2023", "config_hash": "c1", "testlist_hash": "tl1",
              "seed_policy": "random", "evidence_bundle_hash": "e1"}

    def build(required_block):
        return (
            f"```dv-harness-evidence:promotion_readiness_gate\n{json.dumps(readiness)}\n```\n"
            f"```dv-harness-evidence:promotion_chain_audit_gate\n{json.dumps(chain)}\n```\n"
            f"```dv-harness-evidence:closed_loop_promotion_gate\n{json.dumps(closed_loop)}\n```\n"
            f"```dv-harness-evidence:promotion_rollback_gate\n{{}}\n```\n"
            f"```dv-harness-evidence:qualification_matrix_consistency_gate\n"
            f'{json.dumps({"protocols": []})}\n```\n'
            f"```dv-harness-evidence:release_reproducibility_gate\n{json.dumps(release)}\n```\n"
            f"```dv-harness-evidence:rollback_consistency_gate\n{{}}\n```\n"
            f"```dv-harness-evidence:feature_continuity_gate\n{json.dumps(required_block)}\n```\n"
        )

    # PASS: a real file that genuinely exists under this repo's root -- the
    # harness-supplied --root (not an agent-supplied one) is what makes this
    # resolve correctly.
    ok = {"required": {"required_paths": ["dv_harness/gates.py"]}}
    verdict, reasons = evaluate_stage_evidence(ROOT, "PROMOTION_READINESS", build(ok))
    assert verdict == "PASS", reasons

    # FAIL: a path that does not exist under the real repo root.
    bad = {"required": {"required_paths": ["dv_harness/gates.py", "does/not/exist.py"]}}
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "PROMOTION_READINESS", build(bad))
    assert verdict2 == "GATE_FAIL", reasons2
    assert any("FEATURE_CONTINUITY_REGRESSION" in r for r in reasons2), reasons2


def test_expert_feedback_loop_requires_experience_knowledge_gate():
    # Experience Learning Loop: EXPERIENCE_READY was previously a dangling
    # reference -- no stage actually produced it. experience_knowledge_gate
    # now enforces the fields needed before promotion to Verification Memory.
    feedback = {"items": [{"feedback_id": "f1", "disposition": "ACCEPTED", "expert_id": "e1",
                           "rationale": "r", "action_id": "a1", "closure_evidence_hash": "h1"}]}

    incomplete_knowledge = {"knowledge_id": "k1", "title": "t", "pattern": "p",
                            "root_cause": "rc", "evidence": "ev",
                            "applicability_constraints": "ac", "expert_approved": False}
    text_incomplete = (
        f"```dv-harness-evidence:expert_feedback_closure_gate\n{json.dumps(feedback)}\n```\n"
        f"```dv-harness-evidence:experience_knowledge_gate\n{json.dumps(incomplete_knowledge)}\n```\n"
        + _EXPERIENCE_APPLICABILITY_GATE_PASS
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "EXPERT_FEEDBACK_LOOP", text_incomplete)
    assert verdict == "GATE_FAIL", reasons

    complete_knowledge = dict(incomplete_knowledge, expert_approved=True)
    text_complete = (
        f"```dv-harness-evidence:expert_feedback_closure_gate\n{json.dumps(feedback)}\n```\n"
        f"```dv-harness-evidence:experience_knowledge_gate\n{json.dumps(complete_knowledge)}\n```\n"
        + _EXPERIENCE_APPLICABILITY_GATE_PASS
    )
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "EXPERT_FEEDBACK_LOOP", text_complete)
    assert verdict2 == "PASS", reasons2


def test_expert_feedback_loop_experience_applicability_gate_pass_fail_branches():
    # experience_applicability_gate.py is the second gate wired via the
    # multi-flag EvidenceFlag extension -- two EvidenceFlags (--knowledge,
    # --context), both dicts, no ContextFlag. Exercises all three of the
    # script's real exit branches (APPLICABLE/0, NOT_APPLICABLE/3,
    # KNOWLEDGE_NOT_QUALIFIED/2) through evaluate_stage_evidence().
    feedback = {"items": [{"feedback_id": "f1", "disposition": "ACCEPTED", "expert_id": "e1",
                           "rationale": "r", "action_id": "a1", "closure_evidence_hash": "h1"}]}
    knowledge_gate_payload = {"knowledge_id": "k1", "title": "t", "pattern": "p",
                              "root_cause": "rc", "evidence": "ev",
                              "applicability_constraints": "ac", "expert_approved": True}

    def build(applicability_block):
        return (
            f"```dv-harness-evidence:expert_feedback_closure_gate\n{json.dumps(feedback)}\n```\n"
            f"```dv-harness-evidence:experience_knowledge_gate\n{json.dumps(knowledge_gate_payload)}\n```\n"
            f"```dv-harness-evidence:experience_applicability_gate\n{json.dumps(applicability_block)}\n```\n"
        )

    # NOT_APPLICABLE: knowledge's applicability_constraints don't match context.
    mismatched = {"knowledge": {"expert_approved": True, "evidence": "ev1",
                                "applicability_constraints": {"protocol": "USB"}},
                  "context": {"protocol": "PCIe"}}
    verdict, reasons = evaluate_stage_evidence(ROOT, "EXPERT_FEEDBACK_LOOP", build(mismatched))
    assert verdict == "GATE_FAIL", reasons
    assert any("NOT_APPLICABLE" in r for r in reasons), reasons

    # KNOWLEDGE_NOT_QUALIFIED: the reused knowledge record itself was never
    # expert-approved / carries no evidence.
    unqualified = {"knowledge": {"expert_approved": False, "evidence": "",
                                 "applicability_constraints": {}},
                   "context": {}}
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "EXPERT_FEEDBACK_LOOP", build(unqualified))
    assert verdict2 == "GATE_FAIL", reasons2
    assert any("KNOWLEDGE_NOT_QUALIFIED" in r for r in reasons2), reasons2

    # APPLICABLE: constraints match context, knowledge is qualified.
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "EXPERT_FEEDBACK_LOOP",
                                                  build({"knowledge": {"expert_approved": True,
                                                                       "evidence": "ev1",
                                                                       "applicability_constraints": {"protocol": "USB"}},
                                                         "context": {"protocol": "USB"}}))
    assert verdict3 == "PASS", reasons3


def test_run_stage_promotes_experience_knowledge_to_engineering_memory_on_pass():
    # Closed-Loop Experience Learning wiring (w4qxjh0iq, 2026-08-28):
    # experience_knowledge_gate previously only printed PROMOTABLE_TO_EXPERIENCE_DB
    # and persisted nothing. A real PASS on EXPERT_FEEDBACK_LOOP (both its
    # mapped gates) must now actually write an Engineering Memory record.
    from dv_harness.memory import MemoryStore
    tmp, h = _fresh_harness()
    try:
        from dv_harness.adapters.base import AgentResult
        gate_dir = tmp / "tools" / "verification_flow"
        gate_dir.mkdir(parents=True)
        for name in ("expert_feedback_closure_gate.py", "experience_knowledge_gate.py",
                     "experience_applicability_gate.py"):
            shutil.copy(ROOT / "tools" / "verification_flow" / name, gate_dir / name)
        h.set_stage("EXPERT_FEEDBACK_LOOP")

        feedback = {"items": [{"feedback_id": "f1", "disposition": "ACCEPTED", "expert_id": "e1",
                               "rationale": "r", "action_id": "a1", "closure_evidence_hash": "h1"}]}
        knowledge = {"knowledge_id": "K-TEST-001", "title": "t", "pattern": "p",
                     "root_cause": "rc", "evidence": "ev",
                     "applicability_constraints": "ac", "expert_approved": True}
        text = (
            f"```dv-harness-evidence:expert_feedback_closure_gate\n{json.dumps(feedback)}\n```\n"
            f"```dv-harness-evidence:experience_knowledge_gate\n{json.dumps(knowledge)}\n```\n"
            + _EXPERIENCE_APPLICABILITY_GATE_PASS
        )

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        h.adapter = _PassAdapter()
        h.run_stage("goal")
        assert h.state.stages["EXPERT_FEEDBACK_LOOP"]["status"] == Status.PASS.value

        mem = MemoryStore(tmp)
        index_row = next((m for m in mem._index() if m.get("root_cause") == "rc"), None)
        assert index_row, f"no Engineering Memory index row for the promoted record: {mem._index()}"
        rec = mem.get(index_row["memory_id"])
        assert rec["source_knowledge_id"] == "K-TEST-001"
        assert rec["level"] == "engineering"
        assert rec["verified"] is True
        assert rec["root_cause"] == "rc"

        events = (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
        promo_events = [json.loads(e) for e in events if json.loads(e).get("event") == "EXPERIENCE_KNOWLEDGE_PROMOTED"]
        assert promo_events and promo_events[0]["promotion"]["memory_id"] == rec["memory_id"]
    finally:
        shutil.rmtree(tmp)


def test_evaluate_stage_evidence_returns_needs_user_input_for_intake_gate_miss():
    # BUG FIX (2026-08-28, plan-interactive-intake-completeness design pass):
    # a stalled INTAKE where the agent genuinely needs info from a human
    # (intake_readiness.py's "missing": [...] shape) must be distinguishable
    # from GATE_FAIL (agent supplied wrong/invalid evidence).
    text = (
        '```dv-harness-evidence:intake_readiness\n'
        '{"mode": "SUBSYSTEM", "required_artifacts": {}}\n```\n'
        '```dv-harness-evidence:generated_artifact_boundary_gate\n'
        '{"artifacts": []}\n```\n'
        '```dv-harness-evidence:interactive_evidence_intake_gate\n'
        '{"status": "PARTIAL", "confidence": "LOW", "ask_user": true}\n```\n'
        # "{}" is de_local_sim_env_intake_gate's own no-op PASS -- see
        # _INTAKE_EXTRA_GATES above.
        '```dv-harness-evidence:de_local_sim_env_intake_gate\n{}\n```\n'
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "INTAKE", text)
    assert verdict == "NEEDS_USER_INPUT"
    # reasons are human questions (gates.INTAKE_FIELD_QUESTIONS), not raw
    # gate-reason strings -- must not contain the literal Python dict repr
    # a GATE_FAIL would produce.
    assert not any("intake_readiness:" in r for r in reasons)
    assert any("目標名稱" in r for r in reasons)


def test_evaluate_stage_evidence_stays_gate_fail_when_other_gate_also_missing():
    # If a DIFFERENT INTAKE gate has no evidence block at all, that's a real
    # GATE_FAIL, not "just needs user input" -- the agent skipped a
    # required gate entirely, which is a genuine problem independent of
    # intake_readiness's own missing-fields signal.
    text = (
        '```dv-harness-evidence:intake_readiness\n'
        '{"mode": "SUBSYSTEM", "required_artifacts": {}}\n```\n'
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "INTAKE", text)
    assert verdict == "GATE_FAIL"


# BUG FIX (2026-08-29, poster-compliance-audit "INTAKE 問得太籠統" finding):
# these two prove _protocol_discover_checklist() genuinely reads
# .dv-harness/builder/protocol_builder_registry.json's real per-protocol
# `discover` list for TWO DIFFERENT real protocols -- not a hardcoded
# single-protocol string -- and that the checklist only appears once the
# agent's own intake_readiness payload has actually named a protocol.
def _intake_needs_input_text(protocols=None, mode="SUBSYSTEM"):
    intake = {"mode": mode, "required_artifacts": {}}
    if protocols is not None:
        intake["protocols"] = protocols
    return (
        '```dv-harness-evidence:intake_readiness\n' + json.dumps(intake) + '\n```\n'
        '```dv-harness-evidence:generated_artifact_boundary_gate\n{"artifacts": []}\n```\n'
        '```dv-harness-evidence:interactive_evidence_intake_gate\n'
        '{"status": "PARTIAL", "confidence": "LOW", "ask_user": true}\n```\n'
        # "{}" is de_local_sim_env_intake_gate's own no-op PASS -- see
        # _INTAKE_EXTRA_GATES above.
        '```dv-harness-evidence:de_local_sim_env_intake_gate\n{}\n```\n'
    )


def test_needs_user_input_asks_protocol_first_before_any_checklist_when_protocol_unknown():
    # Very first INTAKE exchange: the agent does not yet know the protocol
    # (payload carries no "protocols" key at all) -- intake_readiness's own
    # "missing" list therefore includes "protocols" itself, and none of the
    # per-protocol technical questions may carry a checklist yet (there is
    # nothing real to build one from). Protocol identification must be the
    # first thing asked, not a generic "do you have spec docs?" question.
    verdict, reasons = evaluate_stage_evidence(ROOT, "INTAKE", _intake_needs_input_text(protocols=None))
    assert verdict == "NEEDS_USER_INPUT"
    joined = "\n".join(reasons)
    assert "協定有哪些" in joined  # gates.INTAKE_FIELD_QUESTIONS["protocols"]
    # No protocol-specific checklist content should leak in before a protocol
    # is actually named -- these are real per-protocol discover-list strings
    # from the registry, so their presence here would mean a checklist was
    # fabricated/guessed rather than derived from a named protocol.
    assert "Host/Device role" not in joined
    assert "RC/EP/Switch role" not in joined


def test_needs_user_input_surfaces_usb_checklist_immediately_once_protocol_named():
    # USB named (even in this same first exchange, alongside other missing
    # fields) -- the concrete per-protocol checklist from the real registry
    # must appear as a follow-up on the technical-material questions right
    # here in INTAKE, not deferred to PROTOCOL_CAPABILITY.
    verdict, reasons = evaluate_stage_evidence(ROOT, "INTAKE", _intake_needs_input_text(protocols=["USB"]))
    assert verdict == "NEEDS_USER_INPUT"
    joined = "\n".join(reasons)
    assert "Host/Device role" in joined
    assert "USB2/USB3 mode" in joined
    assert "port topology" in joined
    assert "PHY/controller boundary" in joined
    # protocols itself is no longer missing, so its generic question must not
    # reappear here.
    assert "協定有哪些" not in joined
    # Proves it is genuinely protocol-driven, not hardcoded to USB: a
    # different real protocol's checklist strings must NOT leak in.
    assert "RC/EP/Switch role" not in joined


def test_needs_user_input_surfaces_pcie_checklist_immediately_once_protocol_named():
    # Same as above for a second, different real protocol (PCIe) -- proves
    # the checklist is derived from protocol_builder_registry.json's actual
    # per-protocol content, not copy-pasted USB text.
    verdict, reasons = evaluate_stage_evidence(ROOT, "INTAKE", _intake_needs_input_text(protocols=["PCIe"]))
    assert verdict == "NEEDS_USER_INPUT"
    joined = "\n".join(reasons)
    assert "RC/EP/Switch role" in joined
    assert "Gen2-Gen6" in joined
    assert "lane width" in joined
    assert "Serial/PIPE/controller boundary" in joined
    assert "Host/Device role" not in joined


def test_needs_user_input_surfaces_checklist_for_multiple_named_protocols_at_once():
    # A project naming several protocols in the very first exchange (e.g.
    # "USB and PCIe") must get both real per-protocol checklists, not just
    # the first one matched.
    verdict, reasons = evaluate_stage_evidence(
        ROOT, "INTAKE", _intake_needs_input_text(protocols=["USB", "PCIe"])
    )
    assert verdict == "NEEDS_USER_INPUT"
    joined = "\n".join(reasons)
    assert "Host/Device role" in joined
    assert "RC/EP/Switch role" in joined


def test_run_stage_maps_needs_user_input_to_wait_user_status():
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        vplan_dir = tmp / "tools" / "vplan"
        vplan_dir.mkdir(parents=True)
        shutil.copy(ROOT / "tools" / "vplan" / "intake_readiness.py", vplan_dir / "intake_readiness.py")
        vf_dir = tmp / "tools" / "verification_flow"
        vf_dir.mkdir(parents=True)
        for name in ("generated_artifact_boundary_gate.py", "interactive_evidence_intake_gate.py",
                     "de_local_sim_env_intake_gate.py"):
            shutil.copy(ROOT / "tools" / "verification_flow" / name, vf_dir / name)
        h.set_stage("INTAKE")

        text = (
            '```dv-harness-evidence:intake_readiness\n'
            '{"mode": "SUBSYSTEM", "required_artifacts": {}}\n```\n'
            '```dv-harness-evidence:generated_artifact_boundary_gate\n'
            '{"artifacts": []}\n```\n'
            '```dv-harness-evidence:interactive_evidence_intake_gate\n'
            '{"status": "PARTIAL", "confidence": "LOW", "ask_user": true}\n```\n'
            # "{}" is de_local_sim_env_intake_gate's own no-op PASS -- see
            # _INTAKE_EXTRA_GATES above.
            '```dv-harness-evidence:de_local_sim_env_intake_gate\n{}\n```\n'
        )

        class _NeedsInputAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        h.adapter = _NeedsInputAdapter()
        h.run_stage("verify the USB device controller")
        ss = h.state.stages["INTAKE"]
        assert ss["status"] == Status.WAIT_USER.value
        assert ss["blocking_reason"].startswith("NEEDS_USER_INPUT:")
        assert "intake_readiness:" not in ss["blocking_reason"]  # human question, not a raw dict repr
    finally:
        shutil.rmtree(tmp)


def test_run_stage_does_not_promote_experience_knowledge_when_gate_fails():
    # No spurious promotion when the gate itself rejects the evidence
    # (expert_approved: False) -- PARTIAL, not PASS.
    tmp, h = _fresh_harness()
    try:
        from dv_harness.adapters.base import AgentResult
        gate_dir = tmp / "tools" / "verification_flow"
        gate_dir.mkdir(parents=True)
        for name in ("expert_feedback_closure_gate.py", "experience_knowledge_gate.py"):
            shutil.copy(ROOT / "tools" / "verification_flow" / name, gate_dir / name)
        h.set_stage("EXPERT_FEEDBACK_LOOP")

        feedback = {"items": [{"feedback_id": "f1", "disposition": "ACCEPTED", "expert_id": "e1",
                               "rationale": "r", "action_id": "a1", "closure_evidence_hash": "h1"}]}
        knowledge = {"knowledge_id": "K-TEST-002", "title": "t", "pattern": "p",
                     "root_cause": "rc", "evidence": "ev",
                     "applicability_constraints": "ac", "expert_approved": False}
        text = (
            f"```dv-harness-evidence:expert_feedback_closure_gate\n{json.dumps(feedback)}\n```\n"
            f"```dv-harness-evidence:experience_knowledge_gate\n{json.dumps(knowledge)}\n```\n"
        )

        class _PartialAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        h.adapter = _PartialAdapter()
        h.run_stage("goal")
        assert h.state.stages["EXPERT_FEEDBACK_LOOP"]["status"] == Status.PARTIAL.value

        # No spurious ENGINEERING-tier promotion -- but a WORKING-tier record
        # from ReactRecorder.record() (memory-engine-schema-completion,
        # 2026-09-01) is now expected on EVERY stage attempt regardless of
        # verdict; see dv_harness/react.py's ReactRecorder module-header
        # RULING comment.
        from dv_harness.memory import MemoryStore
        mem = MemoryStore(tmp)
        assert [r for r in mem._index() if r.get("level") == "engineering"] == []
    finally:
        shutil.rmtree(tmp)


def test_corner_case_library_add_get_search_reuse_and_deprecate():
    tmp = Path(tempfile.mkdtemp())
    try:
        lib = CornerCaseLibrary(tmp)
        rec = lib.add({
            "corner_id": "cc1", "protocol": "AXI4", "category": "ordering",
            "risk_tier": "P0", "description": "out-of-order response across two masters",
        })
        ccl_id = rec["ccl_id"]
        assert lib.get(ccl_id)["protocol"] == "AXI4"

        hits = lib.search({"protocol": "AXI4", "category": "ordering"})
        assert any(h["corner_case"]["ccl_id"] == ccl_id for h in hits)

        lib.mark_reused(ccl_id)
        assert lib.get(ccl_id)["reuse_count"] == 1

        assert lib.deprecate(ccl_id, "superseded") is True
        assert lib.get(ccl_id)["status"] == "DEPRECATED"
        assert not any(h["corner_case"]["ccl_id"] == ccl_id
                       for h in lib.search({"protocol": "AXI4"}))

        try:
            lib.add({"corner_id": "bad", "protocol": "AXI4", "category": "not_a_real_category",
                      "risk_tier": "P0"})
            assert False, "invalid category must be rejected"
        except ValueError:
            pass
    finally:
        shutil.rmtree(tmp)


def test_corner_case_library_consolidator_requires_real_resolution_evidence():
    tmp = Path(tempfile.mkdtemp())
    try:
        consolidator = CornerCaseLibraryConsolidator(CornerCaseLibrary(tmp))
        corner_case = {"corner_id": "cc2", "protocol": "USB", "category": "reset_power", "risk_tier": "P1"}
        try:
            consolidator.from_resolved_corner_case(corner_case, {})
            assert False, "empty resolution must be rejected"
        except ValueError:
            pass

        rec = consolidator.from_resolved_corner_case(corner_case, {
            "test_mapping": "usb_reset_during_enum_seq",
            "semantic_verdict": "TRUE_PASS",
            "runtime_evidence_hash": "abc123",
        })
        assert rec["confidence"] == "VALIDATED"
        assert rec["evidence"]["semantic_verdict"] == "TRUE_PASS"
    finally:
        shutil.rmtree(tmp)


def test_route_memory_and_route_and_store_wire_corner_case_library():
    tmp = Path(tempfile.mkdtemp())
    try:
        assert route_memory({"kind": "corner_case", "verified": True}) == "CORNER_CASE_LIBRARY"
        assert route_memory({"kind": "corner_case", "verified": False}) == "WORKING_MEMORY"

        result = route_and_store(tmp, {
            "kind": "corner_case", "verified": True,
            "corner_case": {"corner_id": "cc3", "protocol": "PCIe", "category": "cdc_timing", "risk_tier": "P2"},
            "resolution": {"test_mapping": "pcie_ltssm_cdc_seq", "semantic_verdict": "TRUE_FAIL",
                           "runtime_evidence_hash": "deadbeef"},
        })
        assert result["destination"] == "CORNER_CASE_LIBRARY"
        assert CornerCaseLibrary(tmp).get(result["ccl_id"])["protocol"] == "PCIe"
    finally:
        shutil.rmtree(tmp)


def test_verification_architecture_requires_fabric_topology_completeness_gate():
    mech = {"vplan_requirement_ids": ["r1"], "architecture_nodes": ["n1"],
            "verification_mechanisms": [{"mechanism_id": "m1", "type": "SCOREBOARD"}],
            "planned_testcases": [{"testcase_id": "t1", "mechanism_ids": ["m1"]}]}

    not_applicable = {"topology_applicable": False, "topology_not_applicable_reason": "point-to-point USB, no fabric"}
    # protocol_structural_completeness_gate (added 2026-08-28) is a THIRD
    # mandatory tuple on this stage -- every flow, fabric or not, must also
    # supply this escape hatch (or real evidence) alongside fabric's.
    psc_na = {"protocol_completeness_applicable": False,
              "protocol_completeness_not_applicable_reason": "not one of the 10 covered protocols in this test"}
    text_na = (
        f"```dv-harness-evidence:mechanism_readiness_gate\n{json.dumps(mech)}\n```\n"
        f"```dv-harness-evidence:fabric_topology_completeness_gate\n{json.dumps(not_applicable)}\n```\n"
        f"```dv-harness-evidence:protocol_structural_completeness_gate\n{json.dumps(psc_na)}\n```\n"
        + _VERIFICATION_ARCHITECTURE_EXTRA_GATES
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "VERIFICATION_ARCHITECTURE", text_na)
    assert verdict == "PASS", reasons

    complete = {
        "topology_applicable": True,
        "masters": ["M0", "M1"], "slaves": ["S0", "S1"],
        "scoreboard_matrix": [
            {"master_id": "M0", "slave_id": "S0", "status": "IMPLEMENTED"},
            {"master_id": "M0", "slave_id": "S1", "status": "IMPLEMENTED"},
            {"master_id": "M1", "slave_id": "S0", "status": "IMPLEMENTED"},
            {"master_id": "M1", "slave_id": "S1", "status": "IMPLEMENTED"},
        ],
        "address_map": [
            {"owner": "S0", "start_addr": "0x0", "end_addr": "0x1000"},
            {"owner": "S1", "start_addr": "0x1000", "end_addr": "0x2000"},
        ],
    }
    text_complete = (
        f"```dv-harness-evidence:mechanism_readiness_gate\n{json.dumps(mech)}\n```\n"
        f"```dv-harness-evidence:fabric_topology_completeness_gate\n{json.dumps(complete)}\n```\n"
        f"```dv-harness-evidence:protocol_structural_completeness_gate\n{json.dumps(psc_na)}\n```\n"
        + _VERIFICATION_ARCHITECTURE_EXTRA_GATES
    )
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "VERIFICATION_ARCHITECTURE", text_complete)
    assert verdict2 == "PASS", reasons2

    missing_pair = dict(complete, scoreboard_matrix=complete["scoreboard_matrix"][:-1])
    text_missing = (
        f"```dv-harness-evidence:mechanism_readiness_gate\n{json.dumps(mech)}\n```\n"
        f"```dv-harness-evidence:fabric_topology_completeness_gate\n{json.dumps(missing_pair)}\n```\n"
        f"```dv-harness-evidence:protocol_structural_completeness_gate\n{json.dumps(psc_na)}\n```\n"
    )
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "VERIFICATION_ARCHITECTURE", text_missing)
    assert verdict3 == "GATE_FAIL", reasons3

    gapped = dict(complete, address_map=[
        {"owner": "S0", "start_addr": "0x0", "end_addr": "0x1000"},
        {"owner": "S1", "start_addr": "0x2000", "end_addr": "0x3000"},
    ])
    text_gap = (
        f"```dv-harness-evidence:mechanism_readiness_gate\n{json.dumps(mech)}\n```\n"
        f"```dv-harness-evidence:fabric_topology_completeness_gate\n{json.dumps(gapped)}\n```\n"
        f"```dv-harness-evidence:protocol_structural_completeness_gate\n{json.dumps(psc_na)}\n```\n"
    )
    verdict4, reasons4 = evaluate_stage_evidence(ROOT, "VERIFICATION_ARCHITECTURE", text_gap)
    assert verdict4 == "GATE_FAIL", reasons4

    # Regression test: supplying only the pre-existing mechanism_readiness_gate
    # block (old-style response, predating this gate) must no longer PASS --
    # the new tuple is a protocol-agnostic mandatory requirement.
    text_old_only = f"```dv-harness-evidence:mechanism_readiness_gate\n{json.dumps(mech)}\n```\n"
    verdict5, reasons5 = evaluate_stage_evidence(ROOT, "VERIFICATION_ARCHITECTURE", text_old_only)
    assert verdict5 == "GATE_FAIL", reasons5
    assert any("fabric_topology_completeness_gate" in r for r in reasons5)


def _run_gate_script(rel_path, flag, payload):
    import subprocess, sys
    tmp = Path(tempfile.mkdtemp())
    try:
        infile = tmp / "in.json"
        infile.write_text(json.dumps(payload), encoding="utf-8")
        script = ROOT / "tools" / rel_path
        r = subprocess.run(
            [sys.executable, str(script), flag, str(infile)],
            capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        shutil.rmtree(tmp)


def test_execution_mode_validator_derives_mode_bidirectionally():
    rc, out = _run_gate_script("real_env/execution_mode_validator.py", "--request",
                                {"execution_mode": "PURE_LOCAL_READ_ANALYSIS", "actions": ["read RTL"]})
    assert rc == 0 and out["mode"] == "PURE_LOCAL_READ_ANALYSIS"

    rc, out = _run_gate_script("real_env/execution_mode_validator.py", "--request",
                                {"execution_mode": "PURE_LOCAL_READ_ANALYSIS", "actions": ["run vcs simulation"]})
    assert rc != 0 and out["status"] == "CONFLICT" and out["derived_mode"] == "REMOTE_EXECUTION_REQUIRED"

    # Regression test: previously only PURE_LOCAL_READ_ANALYSIS declarations
    # were cross-checked against actions -- an over-declared REMOTE mode with
    # no remote-sounding action now must also fail closed.
    rc, out = _run_gate_script("real_env/execution_mode_validator.py", "--request",
                                {"execution_mode": "REMOTE_EXECUTION_REQUIRED", "actions": ["read RTL"]})
    assert rc != 0 and out["status"] == "CONFLICT" and out["derived_mode"] == "PURE_LOCAL_READ_ANALYSIS"


def test_execution_mode_validator_requires_ssh_connection_intake_and_blocks_password():
    # CLAUDE.md "SSH/Remote Transport Connection Intake": a REMOTE_EXECUTION_REQUIRED
    # declaration whose actions need SSH/network transport must supply
    # account/vc_machine/ssh_machine/working_path, and must never carry a password.
    rc, out = _run_gate_script("real_env/execution_mode_validator.py", "--request",
                                {"execution_mode": "REMOTE_EXECUTION_REQUIRED",
                                 "actions": ["ssh to server", "run vcs regression"]})
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "MISSING_REMOTE_CONNECTION_INFO"

    rc, out = _run_gate_script("real_env/execution_mode_validator.py", "--request",
                                {"execution_mode": "REMOTE_EXECUTION_REQUIRED",
                                 "actions": ["ssh to server", "run vcs regression"],
                                 "remote_connection": {"account": "u1", "vc_machine": "vchost-b",
                                                        "ssh_machine": "host-b"}})
    assert rc != 0 and out["reason"] == "MISSING_REMOTE_CONNECTION_INFO" and out["missing_fields"] == ["working_path"]

    rc, out = _run_gate_script("real_env/execution_mode_validator.py", "--request",
                                {"execution_mode": "REMOTE_EXECUTION_REQUIRED",
                                 "actions": ["ssh to server", "run vcs regression"],
                                 "remote_connection": {"account": "u1", "vc_machine": "vchost-b",
                                                        "ssh_machine": "host-b",
                                                        "working_path": "/home/u1/proj"}})
    assert rc == 0 and out["status"] == "PASS" and out["mode"] == "REMOTE_EXECUTION_REQUIRED"

    # A password anywhere in the payload (top-level or nested inside
    # remote_connection) must hard-fail rather than pass through into evidence.
    rc, out = _run_gate_script("real_env/execution_mode_validator.py", "--request",
                                {"execution_mode": "REMOTE_EXECUTION_REQUIRED",
                                 "actions": ["ssh to server"],
                                 "remote_connection": {"account": "u1", "vc_machine": "vchost-b",
                                                        "ssh_machine": "host-b",
                                                        "working_path": "/x", "password": "hunter2"}})
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "CREDENTIAL_IN_EVIDENCE_BLOCKED"

    rc, out = _run_gate_script("real_env/execution_mode_validator.py", "--request",
                                {"execution_mode": "PURE_LOCAL_READ_ANALYSIS",
                                 "actions": ["read RTL"], "password": "leak"})
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "CREDENTIAL_IN_EVIDENCE_BLOCKED"

    # PURE_LOCAL_READ_ANALYSIS with no ssh-sounding action does not need
    # remote_connection at all.
    rc, out = _run_gate_script("real_env/execution_mode_validator.py", "--request",
                                {"execution_mode": "PURE_LOCAL_READ_ANALYSIS", "actions": ["read RTL"]})
    assert rc == 0 and out["status"] == "PASS"


def test_architecture_calibration_gate_derives_deltas_from_snapshots():
    before = {"masters": 2}
    after = {"masters": 4}
    rc, out = _run_gate_script("verification_flow/architecture_calibration_gate.py", "--calibration", {
        "architecture_before": before, "architecture_after": after,
        "detected_deltas": ["masters changed"],
        "impact_analysis_completed": True, "affected_artifacts_updated": True, "rerun_evidence": "ev1",
    })
    assert rc == 0 and out["delta_count"] == 1

    # Fabricated delta: agent claims a delta but the two snapshots are identical.
    rc, out = _run_gate_script("verification_flow/architecture_calibration_gate.py", "--calibration", {
        "architecture_before": before, "architecture_after": dict(before),
        "detected_deltas": ["masters changed"],
    })
    assert rc != 0 and out["reason"] == "DETECTED_DELTAS_NOT_SUBSTANTIATED_BY_SNAPSHOTS"


def test_spec_to_vplan_requirement_quality_gate_no_longer_requires_waiver_candidate_flag():
    req = {"req_id": "r1", "spec_ref": "s", "feature": "f", "expected_behavior": "e",
           "verification_method": "m", "coverage_goal": "g",
           "support_status": "UNSUPPORTED_BY_DUT", "design_evidence": "ev1"}
    rc, out = _run_gate_script("verification_flow/spec_to_vplan_requirement_quality_gate.py",
                                "--requirements", {"requirements": [req]})
    assert rc == 0 and out["status"] == "PASS"

    rc, out = _run_gate_script("verification_flow/spec_to_vplan_requirement_quality_gate.py",
                                "--requirements", {"requirements": [dict(req, design_evidence=None)]})
    assert rc != 0 and out["reason"] == "UNSUPPORTED_WITHOUT_DESIGN_EVIDENCE"


def test_coverage_credit_consistency_gate_flags_stated_derived_mismatch():
    rc, out = _run_gate_script("verification_flow/coverage_credit_consistency_gate.py", "--coverage", {
        "active_failure_ids": [], "items": [
            {"coverage_id": "c1", "credit": True, "active_checker_ids": ["chk1"],
             "waived": False, "linked_failure_ids": []}]})
    assert rc == 0 and out["status"] == "PASS"

    # credit=True stated but no checker/waiver actually present -> derived False -> mismatch path
    # (still caught by the pre-existing CREDIT_WITHOUT_CHECK_OR_WAIVER check first)
    rc, out = _run_gate_script("verification_flow/coverage_credit_consistency_gate.py", "--coverage", {
        "active_failure_ids": [], "items": [
            {"coverage_id": "c2", "credit": False, "active_checker_ids": ["chk1"],
             "waived": False, "linked_failure_ids": []}]})
    assert rc == 0 and out["status"] == "PASS"  # under-declaring is not hard-failed


def test_coverage_quality_gate_requires_credit_implies_hit():
    rc, out = _run_gate_script("verification_flow/coverage_quality_gate.py", "--coverage", {
        "coverage_items": [{"coverage_id": "c1", "requirement_ids": ["r1"], "hit": False, "credit": True,
                            "checker_ids": ["chk1"], "execution_evidence": ["ev1"]}]})
    assert rc != 0
    assert any(b["reason"] == "CREDIT_WITHOUT_HIT" for b in out["bad"])


def test_system_level_subsystem_verdict_gate_exposes_derived_verdict():
    rc, out = _run_gate_script("verification_flow/system_level_subsystem_verdict_gate.py", "--system", {
        "system_verdict": "PASS", "subsystems": [{"name": "usb", "verdict": "PASS"}]})
    assert rc == 0 and out["derived_verdict"] == "PASS"

    rc, out = _run_gate_script("verification_flow/system_level_subsystem_verdict_gate.py", "--system", {
        "system_verdict": "PASS", "subsystems": [{"name": "usb", "verdict": "FAIL"}]})
    assert rc != 0 and out["reason"] == "SYSTEM_PASS_MASKS_SUBSYSTEM_FAILURE"


def test_execution_evidence_gate_flags_status_evidence_mismatch():
    # Declared VERIFIED but only a valid waiver was actually populated.
    req = {"req_id": "r1", "status": "VERIFIED",
           "support_status": "UNSUPPORTED_BY_DUT",
           "waiver": {"approved": True, "evidence": "ev1"}}
    rc, out = _run_gate_script("verification_flow/execution_evidence_gate.py", "--closure", {"requirements": [req]})
    assert rc != 0
    assert any(f["reason"] == "STATUS_EVIDENCE_MISMATCH" for f in out["failures"])

    good = {"req_id": "r2", "status": "VERIFIED", "execution_evidence": ["ev1"], "mechanism_ids": ["m1"]}
    rc, out = _run_gate_script("verification_flow/execution_evidence_gate.py", "--closure", {"requirements": [good]})
    assert rc == 0 and out["status"] == "READY_FOR_CLOSURE"


def test_lsf_per_job_monitor_gate_flags_undeclared_sim_log_error():
    rc, out = _run_gate_script("verification_flow/lsf_per_job_monitor_gate.py", "--jobs", {
        "jobs": [{"job_id": 1, "agent_id": "a1", "sim_log": "UVM_ERROR: mismatch at t=100",
                  "uvm_error_detected": False}]})
    assert rc != 0 and out["reason"] == "SIM_LOG_ERROR_UNDECLARED"

    rc, out = _run_gate_script("verification_flow/lsf_per_job_monitor_gate.py", "--jobs", {
        "jobs": [{"job_id": 1, "agent_id": "a1", "sim_log": "UVM_ERROR: mismatch at t=100",
                  "uvm_error_detected": True, "evidence_captured": True}]})
    assert rc == 0 and out["status"] == "PASS"


def test_failure_attribution_gates_on_unresolved_unknown_classification():
    # Tier 3: previously this script always exited 0 regardless of the
    # computed classification -- now UNKNOWN must fail closed, forcing the
    # agent to extend the boundary_trace rather than let an unresolved RCA
    # silently pass FAILURE_RECOVERY.
    rc, out = _run_gate_script("senior_dv/failure_attribution.py", "--trace", {
        "boundary_trace": [{"stage": "SEQUENCE", "expected": 1, "observed": 1}]})
    assert rc != 0 and out["classification"] == "UNKNOWN"
    assert out["reason"] == "ATTRIBUTION_UNRESOLVED_EXTEND_BOUNDARY_TRACE"

    rc, out = _run_gate_script("senior_dv/failure_attribution.py", "--trace", {
        "boundary_trace": [{"stage": "SEQUENCE", "expected": 1, "observed": 1},
                           {"stage": "DUT_INTERNAL", "expected": 1, "observed": 0}]})
    assert rc == 0 and out["classification"] == "DUT_BUG"


def test_failure_recovery_stage_now_fails_on_unknown_attribution():
    unresolved = '''```dv-harness-evidence:failure_attribution
{"boundary_trace": [{"stage": "SEQUENCE", "expected": 1, "observed": 1}]}
```'''
    verdict, reasons = evaluate_stage_evidence(ROOT, "FAILURE_RECOVERY", unresolved)
    assert verdict == "GATE_FAIL"
    assert any("ATTRIBUTION_UNRESOLVED_EXTEND_BOUNDARY_TRACE" in str(r) for r in reasons)

    resolved = ('''```dv-harness-evidence:failure_attribution
{"boundary_trace": [{"stage": "SEQUENCE", "expected": 1, "observed": 1},
  {"stage": "DUT_INTERNAL", "expected": 1, "observed": 0}]}
```''' + "\n" + _FAILURE_RECOVERY_EXTRA_GATES)
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "FAILURE_RECOVERY", resolved)
    assert verdict2 == "PASS", reasons2


def test_failure_recovery_requires_focused_wave_debug_window_gate():
    # BUG FIX regression test (targeted-wave-debug-window-recovery-wiring,
    # 2026-09-02): focused_wave_debug_window_gate.py is the one gate that
    # precisely enforces CLAUDE.md's "First-Failure Waveform Rerun"
    # (targeted, minimal window, cut near first failure) but was wired ONLY
    # to WAVE_ANALYSIS -- reachable only from VERIFY's PASS edge in
    # main_graph.json, never from the real post-batch-failure debug path
    # (FAILURE_RECOVERY). Now mandatory there too, same script, plus a real
    # escape hatch (deep_debug_required:false + a non-empty
    # deep_debug_not_required_reason) so the many FAILURE_RECOVERY responses
    # that never need a waveform at all (CLAUDE.md's own "low-cost evidence
    # first" rule) can still legitimately pass without faking a rerun.
    attribution = ('```dv-harness-evidence:failure_attribution\n'
                   '{"boundary_trace": [{"stage": "SEQUENCE", "expected": 1, "observed": 1}, '
                   '{"stage": "DUT_INTERNAL", "expected": 1, "observed": 0}]}\n```\n')
    other_three = (
        '```dv-harness-evidence:failure_signature_recurrence_gate\n{"failures": [{"failure_id": "F1", "signature": "SIG_A"}]}\n```\n'
        '```dv-harness-evidence:issue_triage_classification_gate\n{"classification": "KNOWN", "classification_reason": "matches prior waiver", "evidence_hash": "abc123", "known_issue_id": "K-1"}\n```\n'
        '```dv-harness-evidence:unknown_failure_escalation_gate\n{"classification": "ENV_ISSUE"}\n```\n'
    )

    # No focused_wave_debug_window_gate block at all -> the stage can no
    # longer silently PASS without ever declaring whether a targeted
    # waveform rerun happened.
    verdict, reasons = evaluate_stage_evidence(ROOT, "FAILURE_RECOVERY", attribution + other_three)
    assert verdict == "GATE_FAIL", reasons
    assert any("focused_wave_debug_window_gate" in str(r) for r in reasons)

    # deep_debug_required:false with no justification -> FAIL, not a silent
    # skip.
    no_reason = ('```dv-harness-evidence:focused_wave_debug_window_gate\n'
                 '{"deep_debug_required": false}\n```\n')
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "FAILURE_RECOVERY", attribution + other_three + no_reason)
    assert verdict2 == "GATE_FAIL", reasons2
    assert any("DEEP_DEBUG_NOT_REQUIRED_WITHOUT_REASON" in str(r) for r in reasons2)

    # deep_debug_required:false WITH a real justification -> PASS, low-cost
    # evidence was genuinely enough this round.
    with_reason = ('```dv-harness-evidence:focused_wave_debug_window_gate\n'
                   '{"deep_debug_required": false, '
                   '"deep_debug_not_required_reason": "UVM_ERROR text alone was conclusive"}\n```\n')
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "FAILURE_RECOVERY", attribution + other_three + with_reason)
    assert verdict3 == "PASS", reasons3

    # A real targeted rerun still gets the exact same precise window/scope
    # check WAVE_ANALYSIS already enforced -- an out-of-window stop still
    # FAILs here too, proving this is the same gate, not a weaker copy.
    bad_window = ('```dv-harness-evidence:focused_wave_debug_window_gate\n'
                  '{"deep_debug_required": true, "dump_scope_confirmed": '
                  '{"scope": "top.usb_dev.ctrl", "level_or_depth": "signal-level", "confirmed_by": "user"}, '
                  '"wave_mode": 1, "fsdb_start_us": 0, "first_error_time_us": 100, '
                  '"fsdb_stop_us": 5000, "simulation_stopped_at_fsdb_stop": true, '
                  '"job_killed_or_terminated": true, "identity_preserved": true, '
                  '"waveform_or_fsdbreport_evidence_hash": "h1"}\n```\n')
    verdict4, reasons4 = evaluate_stage_evidence(ROOT, "FAILURE_RECOVERY", attribution + other_three + bad_window)
    assert verdict4 == "GATE_FAIL", reasons4
    assert any("INVALID_FOCUSED_FSDB_STOP_WINDOW" in str(r) for r in reasons4)


def test_rca_replay_fix_closure_gate_cross_checks_boundary_trace():
    base = {"rca_id": "r1", "reproducer_hash": "h1", "fix_commit_hash": "c1", "rerun_evidence_hash": "e1",
            "replay_equivalent": True, "pre_fix_result": "FAIL", "post_fix_result": "PASS",
            "attribution_confidence": "HIGH"}

    # No boundary_trace: behavior identical to before this change.
    rc, out = _run_gate_script("verification_flow/rca_replay_fix_closure_gate.py", "--closure",
                                dict(base, attribution="DUT_BUG"))
    assert rc == 0 and out["status"] == "PASS"

    # boundary_trace present and consistent with stated attribution.
    rc, out = _run_gate_script("verification_flow/rca_replay_fix_closure_gate.py", "--closure", dict(
        base, attribution="DUT_BUG",
        boundary_trace=[{"stage": "SEQUENCE", "expected": 1, "observed": 1},
                        {"stage": "DUT_INTERNAL", "expected": 1, "observed": 0}]))
    assert rc == 0 and out["status"] == "PASS"

    # boundary_trace present but CONTRADICTS the stated attribution.
    rc, out = _run_gate_script("verification_flow/rca_replay_fix_closure_gate.py", "--closure", dict(
        base, attribution="TB_BUG",
        boundary_trace=[{"stage": "SEQUENCE", "expected": 1, "observed": 1},
                        {"stage": "DUT_INTERNAL", "expected": 1, "observed": 0}]))
    assert rc != 0 and out["reason"] == "ATTRIBUTION_CONTRADICTS_BOUNDARY_TRACE"
    assert out["derived_classification"] == "DUT_BUG" and out["stated_attribution"] == "TB_BUG"

    # boundary_trace derives UNKNOWN: attribution is unconstrained (e.g. VIP_ISSUE).
    rc, out = _run_gate_script("verification_flow/rca_replay_fix_closure_gate.py", "--closure", dict(
        base, attribution="VIP_ISSUE",
        boundary_trace=[{"stage": "SEQUENCE", "expected": 1, "observed": 1}]))
    assert rc == 0 and out["status"] == "PASS"


def _cosign_enabled():
    # Tier 5 is opt-in (policy.require_dv_review_cosign) -- patch load_config
    # rather than writing to the real project's .dv-harness/config.json, so
    # these tests never mutate shared repo state.
    return patch("dv_harness.gates.load_config",
                 return_value={"policy": {"require_dv_review_cosign": True}})


def test_dv_review_cosign_defaults_off_bare_judgment_fields_still_pass():
    # Tier 5 must be byte-identical to pre-Tier-5 behavior by default -- this
    # is the same payload test_newly_wired_orphan_gates_pass_with_valid_evidence
    # already exercises; it must keep passing with the bare (unwrapped) value.
    text = '''```dv-harness-evidence:corner_risk_rank
{"cases": [{"corner_id": "c1", "risk_factors": ["reset", "cdc"]}]}
```''' + "\n" + _SOC_SCENARIO_PLANNER_EXTRA_GATES
    verdict, reasons = evaluate_stage_evidence(ROOT, "SOC_SCENARIO_PLANNER", text)
    assert verdict == "PASS", reasons


def test_dv_review_cosign_enabled_blocks_bare_judgment_field():
    text = ('''```dv-harness-evidence:corner_risk_rank
{"cases": [{"corner_id": "c1", "risk_factors": ["reset", "cdc"]}]}
```''' + "\n" + _SOC_SCENARIO_PLANNER_EXTRA_GATES)
    with _cosign_enabled():
        verdict, reasons = evaluate_stage_evidence(ROOT, "SOC_SCENARIO_PLANNER", text)
    assert verdict == "DV_REVIEW_PENDING", reasons
    assert any("risk_factors" in str(r) for r in reasons)


def test_dv_review_cosign_enabled_accepts_properly_wrapped_field():
    text = ('''```dv-harness-evidence:corner_risk_rank
{"cases": [{"corner_id": "c1", "risk_factors": {"value": ["reset", "cdc"],
  "reviewer_id": "alice", "reviewer_confidence": "HIGH"}}]}
```''' + "\n" + _SOC_SCENARIO_PLANNER_EXTRA_GATES)
    with _cosign_enabled():
        verdict, reasons = evaluate_stage_evidence(ROOT, "SOC_SCENARIO_PLANNER", text)
    assert verdict == "PASS", reasons


def test_dv_review_cosign_enabled_ccl_reuse_bypasses_wrapping():
    # BUG FIX regression test (2026-08-28): a claimed "REUSED_CCL:<id>" must
    # be independently verified (record exists, ACTIVE, real runtime
    # evidence) before it bypasses co-sign -- not just string-matched.
    # Gate scripts only resolve under the real ROOT, so the CCL record is
    # written there too and cleaned up afterward rather than under an
    # isolated tmp dir (which has no tools/ tree for run_gate to find).
    lib = CornerCaseLibrary(ROOT)
    consolidator = CornerCaseLibraryConsolidator(lib)
    rec = consolidator.from_resolved_corner_case(
        {"corner_id": "c1", "protocol": "USB", "category": "reset_power", "risk_tier": "P1"},
        {"test_mapping": "usb_reset_seq", "semantic_verdict": "TRUE_PASS", "runtime_evidence_hash": "abc123"},
    )
    ccl_id = rec["ccl_id"]
    try:
        text = f'''```dv-harness-evidence:corner_risk_rank
{{"cases": [{{"corner_id": "c1", "risk_factors": ["reset", "cdc"],
  "classification_basis": "REUSED_CCL:{ccl_id}"}}]}}
```''' + "\n" + _SOC_SCENARIO_PLANNER_EXTRA_GATES
        with _cosign_enabled():
            verdict, reasons = evaluate_stage_evidence(ROOT, "SOC_SCENARIO_PLANNER", text)
        assert verdict == "PASS", reasons
    finally:
        (lib.dir / f"{ccl_id}.json").unlink(missing_ok=True)
        rows = [r for r in lib._index() if r.get("ccl_id") != ccl_id]
        lib._save_index(rows)


def test_dv_review_cosign_enabled_ccl_reuse_rejects_unverified_claim():
    # The fix: a classification_basis claiming a REUSED_CCL id that doesn't
    # exist (or isn't ACTIVE/verified) must NOT bypass co-sign -- it must
    # fall through to the normal wrapping requirement instead of being
    # silently trusted on the agent's say-so.
    text = ('''```dv-harness-evidence:corner_risk_rank
{"cases": [{"corner_id": "c1", "risk_factors": ["reset", "cdc"],
  "classification_basis": "REUSED_CCL:CCL-DOES-NOT-EXIST"}]}
```''' + "\n" + _SOC_SCENARIO_PLANNER_EXTRA_GATES)
    with _cosign_enabled():
        verdict, reasons = evaluate_stage_evidence(ROOT, "SOC_SCENARIO_PLANNER", text)
    assert verdict == "DV_REVIEW_PENDING", reasons
    assert any("CCL-DOES-NOT-EXIST" in str(r) for r in reasons)


def test_dv_review_cosign_enabled_still_reports_genuine_gate_fail():
    # A judgment field that's wrapped correctly but the underlying gate
    # script's own checks still fail must remain GATE_FAIL, not
    # DV_REVIEW_PENDING (co-sign presence doesn't excuse real content failure).
    text = ('''```dv-harness-evidence:corner_risk_rank
{"cases": [{"corner_id": "c1", "risk_factors": {"value": ["not_a_real_factor"],
  "reviewer_id": "alice", "reviewer_confidence": "HIGH"}}]}
```''' + "\n" + _SOC_SCENARIO_PLANNER_EXTRA_GATES)
    with _cosign_enabled():
        verdict, reasons = evaluate_stage_evidence(ROOT, "SOC_SCENARIO_PLANNER", text)
    # corner_risk_rank.py itself has no semantic validation of risk_factors
    # values (documented caveat in gates.py), so this actually still passes --
    # confirms the wrapped value is correctly unwrapped before the script runs.
    assert verdict == "PASS", reasons


def test_loop_does_not_silently_advance_a_partial_stage_as_if_it_passed():
    # BUG FIX regression test (2026-08-28, confirmed by architecture audit):
    # loop() previously only special-cased Status.FAIL -- a PARTIAL result
    # (adapter said ok=True, but evaluate_stage_evidence rejected the
    # evidence) fell through to the unconditional self.advance(), which
    # calls graph_next(..., Status.PASS.value, ...) -- i.e. a gate-rejected
    # stage was silently routed along the graph's PASS edge. ENV_CHECK has
    # no FAIL edge in main_graph.json (only PASS and BLOCKED), so the
    # correct fixed behavior is: after retries exhaust, the loop stops with
    # current_stage still ENV_CHECK -- it must NOT reach INTAKE.
    from dv_harness.engine import DVHarness
    from dv_harness.adapters.base import AgentResult

    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / ".dv-harness" / "graph").mkdir(parents=True)
        graph_src = ROOT / ".dv-harness" / "graph" / "main_graph.json"
        (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
            graph_src.read_text(encoding="utf-8"), encoding="utf-8")

        h = DVHarness(tmp)
        h.cfg["policy"]["max_stage_retries"] = 0  # exhaust retries on first PARTIAL

        class _FakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                # ok=True with no evidence block at all -> MISSING_EVIDENCE -> PARTIAL,
                # since ENV_CHECK has a mapped gate (execution_mode_validator).
                return AgentResult(ok=True, text="no evidence supplied", raw={}, session_id=None)

        h.adapter = _FakeAdapter()
        assert h.state.current_stage == "ENV_CHECK"

        h.loop("test goal")

        assert h.state.current_stage == "ENV_CHECK", (
            "loop() must not advance past a stage whose evidence gate rejected it; "
            f"current_stage={h.state.current_stage!r}"
        )
        assert h.state.stages["ENV_CHECK"]["status"] == Status.PARTIAL.value
    finally:
        shutil.rmtree(tmp)


def test_de_explainer_is_additive_and_does_not_change_agent_prompt():
    # Tier 1 DE-onboarding fix: STAGE_DE_EXPLAINER/get_de_explainer must be a
    # side channel that provably cannot alter what the DV agent is actually
    # instructed to do.
    assert set(STAGE_DE_EXPLAINER) <= {s.value for s in _Stage}
    for stage in ("VPLAN", "COVERAGE_CLOSURE", "DISCOVERY", "SIGNOFF"):
        before = STAGE_INSTRUCTIONS.get(stage, "")
        prompt = build_stage_prompt(stage, "state", "goal")
        assert STAGE_INSTRUCTIONS.get(stage, "") == before
        assert prompt.endswith(before)

    assert "coverage_signoff_verdict_gate" not in get_de_explainer("COVERAGE_CLOSURE")
    # DISCOVERY was the original example of an uncovered stage when this test
    # was written; it now has a real explainer (added together with the other
    # 26 previously-missing stages -- see
    # test_all_35_stages_have_real_de_explainer_entries below). The
    # fallback-text contract itself is still exercised here via a stage name
    # guaranteed not to exist in STAGE_DE_EXPLAINER.
    assert get_de_explainer("DISCOVERY") != (
        "（尚未提供這個 stage 的白話說明；請參考 STAGE_INSTRUCTIONS 或詢問 DV owner。）"
    )
    assert get_de_explainer("NOT_A_REAL_STAGE_XYZ") == (
        "（尚未提供這個 stage 的白話說明；請參考 STAGE_INSTRUCTIONS 或詢問 DV owner。）"
    )


def test_all_35_stages_have_real_de_explainer_entries():
    # DE onboarding gap fix: originally only 8/35 stages had a
    # STAGE_DE_EXPLAINER entry, and the fallback text explicitly tells the DE
    # to "ask the DV owner" -- which is the opposite of useful for a DE with
    # no DV owner to ask, and previously covered the exact stages (ENV_CHECK/
    # INTAKE/DISCOVERY) a first-week DE hits first. Every declared Stage must
    # now have a real, non-fallback, non-trivial explainer.
    fallback = "（尚未提供這個 stage 的白話說明；請參考 STAGE_INSTRUCTIONS 或詢問 DV owner。）"
    all_stages = {s.value for s in _Stage}
    assert set(STAGE_DE_EXPLAINER) == all_stages
    for stage in sorted(all_stages):
        text = get_de_explainer(stage)
        assert text != fallback, f"{stage} still falls back to the generic DE explainer"
        assert "【白話說明】" in text, f"{stage} explainer missing the expected 白話說明 marker"
        assert len(text.strip()) >= 80, f"{stage} explainer looks too short to be useful"


def test_cli_explain_subcommand_prints_de_explainer(tmp_path=None):
    import subprocess, sys
    tmp = Path(tempfile.mkdtemp())
    try:
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "explain", "--stage", "COVERAGE_CLOSURE"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
            encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr
        assert get_de_explainer("COVERAGE_CLOSURE").strip() in r.stdout
    finally:
        shutil.rmtree(tmp)


def test_cli_lsf_submit_reports_lsf_unavailable_cleanly_when_bsub_missing():
    # BUG FIX (2026-08-28, gui-cli-completeness-audit): lsf_client.py had no
    # CLI entry point at all. This exercises the real dispatch path end to
    # end; the test/CI environment has no real `bsub` on PATH, which is
    # itself the deterministic, OS-independent condition being asserted --
    # a clean JSON error + exit 1, never a raw traceback.
    import subprocess, sys
    tmp = Path(tempfile.mkdtemp())
    try:
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "lsf-submit", "echo hi", "--queue", "normal"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
        )
        assert r.returncode == 1
        payload = json.loads(r.stdout)
        assert payload["error"] == "LSF_UNAVAILABLE"
    finally:
        shutil.rmtree(tmp)


def test_cli_lsf_kill_reports_lsf_unavailable_cleanly_when_bkill_missing():
    import subprocess, sys
    tmp = Path(tempfile.mkdtemp())
    try:
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "lsf-kill", "123"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
        )
        assert r.returncode == 1
        payload = json.loads(r.stdout)
        assert payload["error"] == "LSF_UNAVAILABLE"
    finally:
        shutil.rmtree(tmp)


def test_cli_lsf_reconcile_all_with_no_known_jobs_is_a_clean_noop():
    import subprocess, sys
    tmp = Path(tempfile.mkdtemp())
    try:
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "lsf-reconcile", "--all"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert payload["reconciled"] == []
    finally:
        shutil.rmtree(tmp)


def test_cli_lsf_reconcile_picks_up_existing_job_state_files():
    # Uses the real lsf_client.save_job_state to seed a job file, then drives
    # lsf-reconcile --all through the real CLI subprocess; bjobs is not on
    # PATH so it must surface LSF_UNAVAILABLE (proving --all actually found
    # and tried to reconcile the seeded job id, not silently no-op'd).
    import subprocess, sys
    from dv_harness import lsf_client
    tmp = Path(tempfile.mkdtemp())
    try:
        lsf_client.save_job_state(tmp, lsf_client.JobState(job_id=4242, lsf_status="PEND"))
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "lsf-reconcile", "--all"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
        )
        assert r.returncode == 1
        payload = json.loads(r.stdout)
        assert payload["error"] == "LSF_UNAVAILABLE"
    finally:
        shutil.rmtree(tmp)


def test_cli_stage_profile_reports_real_collected_data():
    # BUG FIX (2026-08-28, gui-cli-completeness-audit): stage_profile_report.py
    # had no CLI entry point despite engine.py always collecting this data
    # live. Verify `dv-harness stage-profile` actually renders profiler
    # state written by a real StageExecutionProfiler run, not just an empty
    # skeleton.
    import subprocess, sys
    tmp = Path(tempfile.mkdtemp())
    try:
        profiler = StageExecutionProfiler(tmp)
        rec = profiler.begin_stage("DISCOVERY", "DISCOVERY")
        profiler.end_stage(rec["profile_id"], status="PASS")
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), "stage-profile"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr
        assert "Stage Execution Profile" in r.stdout
        assert "DISCOVERY" in r.stdout
        assert "PASS" in r.stdout
    finally:
        shutil.rmtree(tmp)


def test_protocol_structural_completeness_gate_dispatches_by_protocol_field():
    usb_pass = {
        "protocol": "USB", "declared_speeds": ["HS", "FS"], "dual_speed": True,
        "usb3_capable": False, "lpm_capable": False, "num_configurations_declared": 1,
        "transfer_type_matrix": [
            {"transfer_type": t, "speed": s, "status": "IMPLEMENTED"}
            for t in ("CONTROL", "BULK", "INTERRUPT", "ISOCHRONOUS") for s in ("HS", "FS")
        ],
        "descriptor_requests": [
            {"descriptor_type": "DEVICE", "index": 0, "status": "IMPLEMENTED"},
            {"descriptor_type": "CONFIGURATION", "index": 0, "status": "IMPLEMENTED"},
            {"descriptor_type": "DEVICE_QUALIFIER", "index": 0, "status": "IMPLEMENTED"},
            {"descriptor_type": "OTHER_SPEED_CONFIGURATION", "index": 0, "status": "IMPLEMENTED"},
        ],
    }
    rc, out = _run_gate_script("verification_flow/protocol_structural_completeness_gate.py",
                                "--protocol-topology", usb_pass)
    assert rc == 0 and out["status"] == "PASS"

    rc, out = _run_gate_script("verification_flow/protocol_structural_completeness_gate.py",
                                "--protocol-topology", {
        "protocol_completeness_applicable": False,
        "protocol_completeness_not_applicable_reason": "AMBA4 fabric, covered elsewhere"})
    assert rc == 0 and out["status"] == "SKIPPED_NOT_APPLICABLE"

    rc, out = _run_gate_script("verification_flow/protocol_structural_completeness_gate.py",
                                "--protocol-topology", {"protocol": "I2C"})
    assert rc != 0 and out["reason"] == "UNKNOWN_OR_UNSUPPORTED_PROTOCOL"

    # A structurally incomplete USB payload (missing transfer-speed pairs) must FAIL.
    rc, out = _run_gate_script("verification_flow/protocol_structural_completeness_gate.py",
                                "--protocol-topology", dict(usb_pass, transfer_type_matrix=usb_pass["transfer_type_matrix"][:-1]))
    assert rc != 0 and out["reason"] == "MISSING_TRANSFER_SPEED_PAIRS"


def test_system_level_subsystem_set_completeness_gate_catches_silent_omission():
    base = {
        "required_subsystems": ["USB", "PCIE", "ETHERNET", "CANFD"],
        "selected_subsystems": ["USB", "PCIE", "ETHERNET", "CANFD"],
        "subsystem_waivers": [],
        "subsystem_scenario_participation": [
            {"scenario_id": "SC1", "participating_subsystems": ["USB", "PCIE"]},
            {"scenario_id": "SC2", "participating_subsystems": ["ETHERNET", "PCIE"]},
            {"scenario_id": "SC3", "participating_subsystems": ["CANFD", "USB"]},
        ],
    }
    rc, out = _run_gate_script("verification_flow/system_level_subsystem_set_completeness_gate.py",
                                "--subsystem-set", base)
    assert rc == 0 and out["status"] == "PASS"

    # A required subsystem entirely missing from selected_subsystems -- the
    # exact silent-omission bug this gate exists to catch, which none of the
    # 3 pre-existing SYSTEM_LEVEL gates would notice.
    omitted = dict(base, selected_subsystems=["USB", "PCIE", "ETHERNET"])
    rc, out = _run_gate_script("verification_flow/system_level_subsystem_set_completeness_gate.py",
                                "--subsystem-set", omitted)
    assert rc != 0 and out["reason"] == "SUBSYSTEM_OMITTED_FROM_SELECTION"
    assert out["subsystems"] == ["CANFD"]

    # Selected and listed, but never actually exercised in any scenario.
    unparticipating = dict(base, subsystem_scenario_participation=[
        {"scenario_id": "SC1", "participating_subsystems": ["USB", "PCIE"]},
        {"scenario_id": "SC2", "participating_subsystems": ["ETHERNET", "PCIE"]},
    ])
    rc, out = _run_gate_script("verification_flow/system_level_subsystem_set_completeness_gate.py",
                                "--subsystem-set", unparticipating)
    assert rc != 0 and out["reason"] == "SUBSYSTEM_MISSING_SCENARIO_PARTICIPATION"
    assert out["subsystems"] == ["CANFD"]

    # Waived subsystem is exempt from both the selection and participation checks.
    waived = dict(base, selected_subsystems=["USB", "PCIE", "ETHERNET"],
                  subsystem_waivers=[{"subsystem": "CANFD", "status": "WAIVED",
                                     "waiver_approved": True, "waiver_evidence": "not populated on this SKU"}],
                  subsystem_scenario_participation=[
                      {"scenario_id": "SC1", "participating_subsystems": ["USB", "PCIE"]},
                      {"scenario_id": "SC2", "participating_subsystems": ["ETHERNET", "PCIE"]},
                  ])
    rc, out = _run_gate_script("verification_flow/system_level_subsystem_set_completeness_gate.py",
                                "--subsystem-set", waived)
    assert rc == 0 and out["status"] == "PASS"

    # Not-applicable escape hatch (pure IP-level project, no real system-level composition).
    rc, out = _run_gate_script("verification_flow/system_level_subsystem_set_completeness_gate.py",
                                "--subsystem-set", {"system_level_applicable": False,
                                                    "system_level_not_applicable_reason": "IP-level only"})
    assert rc == 0 and out["status"] == "SKIPPED_NOT_APPLICABLE"


def test_system_level_traceability_and_validator_gates_gained_escape_hatch():
    # Both previously had no way for a pure IP-level (non-multi-subsystem)
    # flow to legitimately decline -- they always demanded real content.
    rc, out = _run_gate_script("verification_flow/system_level_traceability_gate.py", "--trace",
                                {"system_level_applicable": False,
                                 "system_level_not_applicable_reason": "IP-level only"})
    assert rc == 0 and out["status"] == "SKIPPED_NOT_APPLICABLE"

    rc, out = _run_gate_script("verification_flow/system_level_traceability_gate.py", "--trace",
                                {"system_level_applicable": False})
    assert rc != 0 and out["reason"] == "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"

    # Existing behavior (no escape hatch declared) must be unchanged.
    rc, out = _run_gate_script("verification_flow/system_level_traceability_gate.py", "--trace",
                                {"selected_subsystems": ["USB"]})
    assert rc != 0 and out["reason"] == "INSUFFICIENT_SELECTED_SUBSYSTEMS"

    rc, out = _run_gate_script("real_env/system_level_validator.py", "--registry",
                                {"system_level_applicable": False,
                                 "system_level_not_applicable_reason": "IP-level only"})
    assert rc == 0 and out["status"] == "SKIPPED_NOT_APPLICABLE"

    rc, out = _run_gate_script("real_env/system_level_validator.py", "--registry",
                                {"system_level_applicable": False})
    assert rc != 0 and out["reason"] == "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"

    rc, out = _run_gate_script("real_env/system_level_validator.py", "--registry", {"subsystems": []})
    assert rc != 0 and out["reason"] == "NO_SUBSYSTEMS"


def _run_gate_script_2flag(rel_path, flag1, payload1, flag2, value2):
    # Same shape as _run_gate_script but for a script taking a second,
    # already-a-string flag (e.g. --registered <path>, not JSON-serialized).
    import subprocess, sys
    tmp = Path(tempfile.mkdtemp())
    try:
        infile = tmp / "in.json"
        infile.write_text(json.dumps(payload1), encoding="utf-8")
        script = ROOT / "tools" / rel_path
        args = [sys.executable, str(script), flag1, str(infile)]
        if value2 is not None:
            args += [flag2, str(value2)]
        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        shutil.rmtree(tmp)


def test_subsystem_environment_registration_gate_validates_entry():
    valid = {"name": "USB", "environment_manifest": "generated/usb/environment_manifest.json",
             "release_sha": "abc123", "qualification_state": "PRODUCTION_QUALIFIED",
             "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}
    rc, out = _run_gate_script("verification_flow/subsystem_environment_registration_gate.py",
                                "--entry", valid)
    assert rc == 0 and out["status"] == "PASS" and out["name"] == "USB"

    missing = dict(valid); del missing["release_sha"]
    rc, out = _run_gate_script("verification_flow/subsystem_environment_registration_gate.py",
                                "--entry", missing)
    assert rc != 0 and out["reason"] == "MISSING_REQUIRED_FIELDS" and "release_sha" in out["missing"]

    bad_state = dict(valid, qualification_state="ENV_GENERATED")
    rc, out = _run_gate_script("verification_flow/subsystem_environment_registration_gate.py",
                                "--entry", bad_state)
    assert rc != 0 and out["reason"] == "INVALID_QUALIFICATION_STATE"

    bad_iface = dict(valid, interface_compatibility="FAIL")
    rc, out = _run_gate_script("verification_flow/subsystem_environment_registration_gate.py",
                                "--entry", bad_iface)
    assert rc != 0 and out["reason"] == "INTERFACE_COMPATIBILITY_NOT_PASS"

    bad_clock = dict(valid, clock_reset_compatibility="FAIL")
    rc, out = _run_gate_script("verification_flow/subsystem_environment_registration_gate.py",
                                "--entry", bad_clock)
    assert rc != 0 and out["reason"] == "CLOCK_RESET_COMPATIBILITY_NOT_PASS"


def test_subsystem_environment_registration_gate_escape_hatch():
    rc, out = _run_gate_script("verification_flow/subsystem_environment_registration_gate.py",
                                "--entry", {"registration_applicable": False,
                                            "registration_not_applicable_reason": "full-SoC signoff, no new subsystem"})
    assert rc == 0 and out["status"] == "SKIPPED_NOT_APPLICABLE"

    rc, out = _run_gate_script("verification_flow/subsystem_environment_registration_gate.py",
                                "--entry", {"registration_applicable": False})
    assert rc != 0 and out["reason"] == "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"


def test_system_level_validator_cross_checks_against_persisted_registry():
    tmp = Path(tempfile.mkdtemp())
    try:
        registered_path = tmp / "subsystem_environment_registry.json"
        registered_path.write_text(json.dumps({"subsystems": [
            {"name": "USB", "release_sha": "sha-REAL"},
        ]}), encoding="utf-8")

        valid_entry = {"name": "USB", "environment_manifest": "m.json", "release_sha": "sha-REAL",
                        "qualification_state": "PRODUCTION_QUALIFIED",
                        "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}

        # Matching name + release_sha against the real registry -> PASS.
        rc, out = _run_gate_script_2flag("real_env/system_level_validator.py",
                                          "--registry", {"subsystems": [valid_entry]},
                                          "--registered", registered_path)
        assert rc == 0 and out["status"] == "PASS"

        # Claiming a subsystem that was never actually registered.
        unregistered = dict(valid_entry, name="PCIE")
        rc, out = _run_gate_script_2flag("real_env/system_level_validator.py",
                                          "--registry", {"subsystems": [unregistered]},
                                          "--registered", registered_path)
        assert rc != 0 and out["reason"] == "SUBSYSTEM_NOT_REGISTERED" and "PCIE" in out["names"]

        # Claiming a registered name but with a release_sha that was never actually signed off.
        stale_sha = dict(valid_entry, release_sha="sha-STALE")
        rc, out = _run_gate_script_2flag("real_env/system_level_validator.py",
                                          "--registry", {"subsystems": [stale_sha]},
                                          "--registered", registered_path)
        assert rc != 0 and out["reason"] == "SUBSYSTEM_RELEASE_SHA_MISMATCH"
        assert out["mismatches"][0]["name"] == "USB"

        # Without --registered at all (back-compat), no cross-check happens --
        # existing direct-script callers/tests are unaffected.
        rc, out = _run_gate_script("real_env/system_level_validator.py", "--registry",
                                    {"subsystems": [unregistered]})
        assert rc == 0 and out["status"] == "PASS"
    finally:
        shutil.rmtree(tmp)


def test_spec_rtl_change_impact_gate_no_change_passes_without_command_txt_check():
    tmp = Path(tempfile.mkdtemp())
    try:
        rc, out = _run_gate_script_2flag(
            "verification_flow/spec_rtl_change_impact_gate.py",
            "--impact", {"changed_items": []},
            "--command-txt-root", tmp)
        assert rc == 0 and out["reason"] == "NO_CHANGE"
    finally:
        shutil.rmtree(tmp)


def test_spec_rtl_change_impact_gate_fails_on_untriaged_command_txt():
    # BUG FIX (2026-08-28, audit-impact-arbitration-naming): the gate now
    # cross-checks against a REAL, harness-globbed command.txt enumeration
    # (--command-txt-root), not an agent-self-reported list -- an agent
    # narrowing its own impact scope must not be able to silently omit an
    # actually-existing command.txt from triage.
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "testA").mkdir()
        (tmp / "testA" / "command.txt").write_text("run usb_smoke")
        (tmp / "testB").mkdir()
        (tmp / "testB" / "command.txt").write_text("run usb_enum")
        payload = {"changed_items": ["rtl/usb_ctrl.v"],
                   "command_txt_impact_verdict": {
                       "testA/command.txt": {"status": "IMPACTED", "reason": "shares the changed module"},
                   }}
        rc, out = _run_gate_script_2flag(
            "verification_flow/spec_rtl_change_impact_gate.py",
            "--impact", payload, "--command-txt-root", tmp)
        assert rc != 0
        assert out["reason"] == "COMMAND_TXT_NOT_TRIAGED"
        assert out["missing"] == ["testB/command.txt"]
    finally:
        shutil.rmtree(tmp)


def test_spec_rtl_change_impact_gate_passes_when_all_command_txt_triaged():
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "testA").mkdir()
        (tmp / "testA" / "command.txt").write_text("run usb_smoke")
        (tmp / "testB").mkdir()
        (tmp / "testB" / "command.txt").write_text("run usb_enum")
        payload = {"changed_items": ["rtl/usb_ctrl.v"],
                   "command_txt_impact_verdict": {
                       "testA/command.txt": {"status": "IMPACTED", "reason": "shares the changed module"},
                       "testB/command.txt": {"status": "NOT_IMPACTED", "reason": "unrelated interface"},
                   }}
        rc, out = _run_gate_script_2flag(
            "verification_flow/spec_rtl_change_impact_gate.py",
            "--impact", payload, "--command-txt-root", tmp)
        assert rc == 0, out
    finally:
        shutil.rmtree(tmp)


def test_spec_rtl_change_impact_gate_fails_on_invalid_verdict_status():
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "testA").mkdir()
        (tmp / "testA" / "command.txt").write_text("run usb_smoke")
        payload = {"changed_items": ["rtl/usb_ctrl.v"],
                   "command_txt_impact_verdict": {
                       "testA/command.txt": {"status": "MAYBE", "reason": "unsure"},
                   }}
        rc, out = _run_gate_script_2flag(
            "verification_flow/spec_rtl_change_impact_gate.py",
            "--impact", payload, "--command-txt-root", tmp)
        assert rc != 0
        assert out["reason"] == "INVALID_COMMAND_TXT_VERDICT"
    finally:
        shutil.rmtree(tmp)


def test_spec_rtl_change_impact_gate_no_command_txt_in_project_skips_triage():
    tmp = Path(tempfile.mkdtemp())
    try:
        payload = {"changed_items": ["rtl/usb_ctrl.v"]}
        rc, out = _run_gate_script_2flag(
            "verification_flow/spec_rtl_change_impact_gate.py",
            "--impact", payload, "--command-txt-root", tmp)
        assert rc == 0, out
    finally:
        shutil.rmtree(tmp)


def test_engine_persists_subsystem_registry_entry_on_signoff_pass():
    # Unit-tests _persist_subsystem_registry_entry directly (rather than
    # driving a full run_stage() SIGNOFF PASS, which would require
    # constructing valid payloads for all 9 real SIGNOFF gates unrelated to
    # this feature) -- the one-line call site in run_stage()
    # (`if verdict == "PASS": ... self._persist_subsystem_registry_entry(...)`)
    # mirrors the already-tested _promote_experience_knowledge call
    # immediately above it byte-for-byte in structure, so its wiring is
    # covered by code symmetry; this test verifies the new method's own
    # behavior: insert, update-by-name, and the skip path.
    tmp, h = _fresh_harness()
    try:
        entry = {"name": "USB", "environment_manifest": "generated/usb/environment_manifest.json",
                  "release_sha": "sha-1", "qualification_state": "PRODUCTION_QUALIFIED",
                  "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}
        h._persist_subsystem_registry_entry("SIGNOFF", {"subsystem_environment_registration_gate": entry})

        reg_path = tmp / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json"
        registry = json.loads(reg_path.read_text(encoding="utf-8"))
        assert len(registry["subsystems"]) == 1
        stored = registry["subsystems"][0]
        assert stored["name"] == "USB" and stored["release_sha"] == "sha-1"
        assert stored["registered_from_git_sha"] == h.state.git_sha
        assert "registered_at" in stored

        bb = h.blackboard.read("subsystem_registry")
        assert bb["value"]["entry"]["name"] == "USB"

        events = (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
        reg_events = [json.loads(e) for e in events if json.loads(e).get("event") == "SUBSYSTEM_ENVIRONMENT_REGISTERED"]
        assert reg_events and reg_events[0]["name"] == "USB"

        # A later SIGNOFF for the SAME subsystem replaces, not duplicates.
        updated = dict(entry, release_sha="sha-2")
        h._persist_subsystem_registry_entry("SIGNOFF", {"subsystem_environment_registration_gate": updated})
        registry2 = json.loads(reg_path.read_text(encoding="utf-8"))
        assert len(registry2["subsystems"]) == 1
        assert registry2["subsystems"][0]["release_sha"] == "sha-2"

        # A different subsystem is a real second entry, not a replacement.
        pcie_entry = dict(entry, name="PCIE", release_sha="sha-pcie-1")
        h._persist_subsystem_registry_entry("SIGNOFF", {"subsystem_environment_registration_gate": pcie_entry})
        registry3 = json.loads(reg_path.read_text(encoding="utf-8"))
        assert {s["name"] for s in registry3["subsystems"]} == {"USB", "PCIE"}

        # registration_applicable: false -> nothing persisted (no new write).
        h2_tmp, h2 = _fresh_harness()
        try:
            h2._persist_subsystem_registry_entry("SIGNOFF", {"subsystem_environment_registration_gate":
                {"registration_applicable": False, "registration_not_applicable_reason": "full-SoC signoff"}})
            assert not (h2_tmp / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json").exists()
        finally:
            shutil.rmtree(h2_tmp)

        # A stage without this gate in STAGE_GATES is a no-op (defensive --
        # should never happen in practice since only SIGNOFF has this gate).
        h3_tmp, h3 = _fresh_harness()
        try:
            h3._persist_subsystem_registry_entry("VERIFY", {"subsystem_environment_registration_gate": entry})
            assert not (h3_tmp / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json").exists()
        finally:
            shutil.rmtree(h3_tmp)
    finally:
        shutil.rmtree(tmp)


def test_engine_composes_soc_environment_on_system_level_pass():
    # Unit-tests _compose_soc_environment_files directly (same rationale as
    # test_engine_persists_subsystem_registry_entry_on_signoff_pass
    # immediately above: driving a full run_stage() SYSTEM_LEVEL PASS would
    # require constructing valid payloads for every real SYSTEM_LEVEL gate
    # unrelated to this feature). Verifies the real wiring: system_level_
    # validator's multi-flag evidence shape ({"registry": {"subsystems": [...]}})
    # is what _compose_soc_environment_files actually reads, and that a real
    # SYSTEM_LEVEL PASS writes real soc_tb_top.sv/soc_virtual_sequencer.sv
    # files under generated/soc_composition/<soc_name>/.
    tmp, h = _fresh_harness()
    try:
        usb = {"name": "USB", "environment_manifest": "generated/usb/environment_manifest.json",
               "release_sha": "sha-usb-1", "qualification_state": "PRODUCTION_QUALIFIED",
               "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}
        pcie = {"name": "PCIE", "environment_manifest": "generated/pcie/environment_manifest.json",
                "release_sha": "sha-pcie-1", "qualification_state": "REGRESSION_QUALIFIED",
                "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}
        evidence_blocks = {
            "system_level_validator": {"registry": {
                "soc_name": "demo_soc", "subsystems": [usb, pcie],
                "cross_subsystem_scenarios": [], "end_to_end_scoreboards": [], "system_coverage": [],
            }},
        }
        h._compose_soc_environment_files("SYSTEM_LEVEL", evidence_blocks)

        out_dir = tmp / "generated" / "soc_composition" / "demo_soc"
        assert (out_dir / "soc_tb_top.sv").exists()
        assert (out_dir / "soc_virtual_sequencer.sv").exists()
        assert (out_dir / "soc_composition_manifest.json").exists()
        tb = (out_dir / "soc_tb_top.sv").read_text(encoding="utf-8")
        assert "usb_env usb_env_inst;" in tb and "pcie_env pcie_env_inst;" in tb

        bb = h.blackboard.read("soc_composition")
        assert bb["value"]["soc_name"] == "demo_soc"
        assert set(bb["value"]["generated_files"]) == {
            "soc_tb_top.sv", "soc_virtual_sequencer.sv", "soc_composition_manifest.json",
        }

        events = (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
        composed_events = [json.loads(e) for e in events if json.loads(e).get("event") == "SOC_ENVIRONMENT_COMPOSED"]
        assert composed_events and composed_events[0]["soc_name"] == "demo_soc"

        # A stage without system_level_validator in STAGE_GATES is a no-op.
        h2_tmp, h2 = _fresh_harness()
        try:
            h2._compose_soc_environment_files("SIGNOFF", evidence_blocks)
            assert not (h2_tmp / "generated" / "soc_composition").exists()
        finally:
            shutil.rmtree(h2_tmp)

        # The escape hatch (system_level_applicable: false) composes nothing.
        h3_tmp, h3 = _fresh_harness()
        try:
            h3._compose_soc_environment_files("SYSTEM_LEVEL", {"system_level_validator": {"registry": {
                "system_level_applicable": False, "system_level_not_applicable_reason": "pure IP-level flow",
            }}})
            assert not (h3_tmp / "generated" / "soc_composition").exists()
        finally:
            shutil.rmtree(h3_tmp)

        # manifest requesting genuinely-unimplemented cross_subsystem_scenarios
        # content logs SOC_COMPOSITION_NOT_IMPLEMENTED and writes nothing --
        # never a fabricated placeholder, never a downgraded stage PASS.
        h4_tmp, h4 = _fresh_harness()
        try:
            h4._compose_soc_environment_files("SYSTEM_LEVEL", {"system_level_validator": {"registry": {
                "soc_name": "demo_soc2", "subsystems": [usb, pcie],
                "cross_subsystem_scenarios": [{"scenario_id": "s1"}],
            }}})
            assert not (h4_tmp / "generated" / "soc_composition").exists()
            events4 = (h4_tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
            ni_events = [json.loads(e) for e in events4 if json.loads(e).get("event") == "SOC_COMPOSITION_NOT_IMPLEMENTED"]
            assert ni_events
        finally:
            shutil.rmtree(h4_tmp)
    finally:
        shutil.rmtree(tmp)


def test_verify_stage_with_mismatched_log_fails_not_passes():
    text = (
        "```dv-harness-evidence:simulation_semantic_validation_gate\n"
        '{"simulation_passed": true, "sim_log": "UVM_INFO nothing relevant here", '
        '"command_expectations": [{"expectation_id": "e1", "required": true, '
        '"evidence_requirements": [{"pattern": "enum PASS", "match_mode": "SUBSTRING"}]}]}\n'
        "```\n"
        "```dv-harness-evidence:test_result_provenance_gate\n"
        '{"results": [{"testcase_id": "t1", "run_id": "r1", "rtl_revision": "a", '
        '"tb_revision": "b", "vip_version": "c", "tool_version": "d", "seed": "1", '
        '"config_hash": "h", "result": "PASS", "log_hash": "lh", "evidence_bundle_hash": "eh"}]}\n'
        "```\n"
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "VERIFY", text)
    assert verdict == "GATE_FAIL"
    assert reasons


# --- Plan-and-Execute / Multi-Agent / Blackboard / ReAct wiring tests -------
# (2026-08-28) planner.py/react.py/router.py/multi_agent.py/blackboard.py/
# skill_resolver.py were confirmed orphaned by the architecture audit; the
# tests below cover the engine.py wiring that makes them actually run during
# run_stage(), plus the real per-agent adapter dispatch (agent_profile.py +
# adapters/cli.py's --agent/--allowedTools/--disallowedTools).

def test_agent_profile_parses_core_agent_frontmatter():
    ap = load_agent_profile(ROOT, "build-agent")
    assert ap.found is True
    # BUG FIX (2026-08-28, gui-cli-completeness-audit): build-agent is also
    # VERIFY's stage agent, whose gates need the command.txt/sim.log semantic
    # cross-check simulation-semantic-validation-agent/post-sim-command-log-
    # validation-agent already exist for -- build-agent had no Agent tool to
    # delegate with, so it's granted here.
    assert ap.tools == ["Read", "Grep", "Glob", "PowerShell", "Skill", "Agent"]
    assert ap.disallowed_tools == ["Edit", "Write"]
    assert "Build Agent" in ap.system_prefix


def test_agent_profile_specialist_agent_has_no_explicit_tools():
    # The 3 senior-DV specialist agents main_graph.json names as node.agent
    # (waveform-root-cause-agent, failure-triage-attribution-agent,
    # protocol-corner-case-intelligence-agent) declare no tools:/
    # disallowedTools: frontmatter at all -- tools must stay None (not []),
    # so the adapter correctly falls back to the harness global default
    # instead of treating the agent as deny-all.
    ap = load_agent_profile(ROOT, "waveform-root-cause-agent")
    assert ap.found is True
    assert ap.tools is None
    assert ap.disallowed_tools == []


def test_agent_profile_missing_agent_file_is_not_found_not_a_crash():
    ap = load_agent_profile(ROOT, "no-such-agent")
    assert ap.found is False
    assert ap.tools is None

    assert load_agent_profile(ROOT, None) is None


def test_cli_adapter_threads_agent_profile_into_real_command():
    # The load-bearing assertion for item 2 of the design: the resolved
    # agent is threaded into the actual `claude` command line (--agent) and
    # that agent's own frontmatter-declared tool scope replaces the harness
    # global default (--allowedTools/--disallowedTools), not just appended
    # as a string into the prompt text.
    from unittest.mock import patch, MagicMock

    adapter = ClaudeCLIAdapter({"claude": {"command": "claude", "max_turns": 40,
                                            "permission_mode": "dangerously-skip-permissions",
                                            "output_format": "json", "allowed_tools": []}})
    ap = load_agent_profile(ROOT, "build-agent")
    captured = {}

    def fake_run(cmd, cwd, text, capture_output, encoding=None, errors=None, input=None):
        captured["cmd"] = cmd
        return MagicMock(stdout='{"result":"ok","session_id":"s1"}', stderr="", returncode=0)

    with patch("subprocess.run", side_effect=fake_run):
        adapter.run(prompt="do the thing", cwd=".", agent_profile=ap)

    cmd = captured["cmd"]
    assert cmd[cmd.index("--agent") + 1] == "build-agent"
    allowed = [cmd[i + 1] for i, x in enumerate(cmd) if x == "--allowedTools"]
    disallowed = [cmd[i + 1] for i, x in enumerate(cmd) if x == "--disallowedTools"]
    assert allowed == ["Read", "Grep", "Glob", "PowerShell", "Skill", "Agent"]  # see build-agent.md's Agent tool grant
    assert disallowed == ["Edit", "Write"]


def test_cli_adapter_without_agent_profile_matches_prior_behavior():
    # Regression test: an unresolved/absent agent_profile (e.g. no graph
    # node for this stage id) must reproduce the pre-wiring command exactly
    # -- no --agent flag, global (empty) allowed_tools list unchanged.
    from unittest.mock import patch, MagicMock

    adapter = ClaudeCLIAdapter({"claude": {"command": "claude", "max_turns": 40,
                                            "permission_mode": "dangerously-skip-permissions",
                                            "output_format": "json", "allowed_tools": []}})
    captured = {}

    def fake_run(cmd, cwd, text, capture_output, encoding=None, errors=None, input=None):
        captured["cmd"] = cmd
        return MagicMock(stdout='{"result":"ok"}', stderr="", returncode=0)

    with patch("subprocess.run", side_effect=fake_run):
        adapter.run(prompt="x", cwd=".", agent_profile=None)

    assert "--agent" not in captured["cmd"]
    assert "--allowedTools" not in captured["cmd"]
    assert "--disallowedTools" not in captured["cmd"]


def _mk_smoke_project():
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        (ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copytree(ROOT / ".claude" / "agents", tmp / ".claude" / "agents")
    # Real gate scripts, so any stage's STAGE_GATES-mapped gates (e.g. the
    # DISCOVERY gates added in the 2026-08-28 mass-wiring pass) can actually
    # subprocess-run here, not just stages that were gateless when this
    # fixture was first written.
    shutil.copytree(ROOT / "tools", tmp / "tools")
    return tmp


def test_run_stage_wires_plan_blackboard_react_and_agent_dispatch_on_pass():
    # End-to-end: DISCOVERY declares agent=analysis-agent,
    # blackboard_read=["project"], blackboard_write=["hierarchy",
    # "protocol_inventory"] in main_graph.json. DISCOVERY gained 2 mandatory
    # gates (evidence_source_priority_gate, input_source_contract_gate) in
    # the 2026-08-28 mass-wiring pass, so the fake adapter's response now
    # includes verified-PASS evidence for both (_DISCOVERY_EXTRA_GATES)
    # instead of relying on NO_GATE_REQUIRED.
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness
        from dv_harness.adapters.base import AgentResult

        calls = []

        class FakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                calls.append({"prompt": prompt, "agent_profile": agent_profile})
                return AgentResult(ok=True, text="analysis done.\n" + _DISCOVERY_EXTRA_GATES,
                                    raw={}, session_id="sess-1")

        h = DVHarness(tmp)
        h.adapter = FakeAdapter()
        h.blackboard.write("project", {"target_name": "usb_dev"}, source="INTAKE")
        h.set_stage("DISCOVERY")

        h.run_stage("verify the USB device controller")
        ss = h.state.stages["DISCOVERY"]
        assert ss["status"] == "PASS"

        # Multi-agent dispatch reached the adapter, not just the prompt text.
        ap = calls[0]["agent_profile"]
        assert ap.name == "analysis-agent"
        assert ap.tools == ["Read", "Grep", "Glob", "PowerShell", "Skill"]
        assert ap.disallowed_tools == ["Edit", "Write"]

        # Plan-and-Execute: resolved plan/route/skills folded into the prompt.
        assert "[Harness Plan-and-Execute" in calls[0]["prompt"]
        assert "analysis-agent" in calls[0]["prompt"]
        # Blackboard read: the pre-seeded prior shows up in the prompt.
        assert '"target_name": "usb_dev"' in calls[0]["prompt"]

        plan_files = list((tmp / ".dv-harness" / "plans").glob("PLAN-*.json"))
        assert len(plan_files) == 1
        plan_doc = json.loads(plan_files[0].read_text())
        assert plan_doc["node_id"] == "DISCOVERY"

        react_files = list((tmp / ".dv-harness" / "react" / "DISCOVERY").glob("iteration_*.json"))
        assert len(react_files) == 1
        react_doc = json.loads(react_files[0].read_text())
        assert react_doc["iteration"] == 1
        assert react_doc["confidence"] == "HIGH"
        assert "analysis-agent" in react_doc["reason_summary"]

        # Blackboard write: sourced from this stage's own evidence/text, on PASS.
        bb = json.loads((tmp / ".dv-harness" / "blackboard" / "hierarchy.json").read_text())
        assert bb["source"] == "DISCOVERY"
        assert "analysis done" in bb["value"]["summary"]

        tasks = json.loads((tmp / ".dv-harness" / "agents" / "tasks.json").read_text())
        assert len(tasks) == 1
        assert tasks[0]["agent"] == "analysis-agent"
        assert tasks[0]["parent_plan"] == plan_doc["plan_id"]
    finally:
        shutil.rmtree(tmp)


def test_run_stage_replans_and_reuses_same_plan_across_retries_on_partial():
    # VERIFY has a mapped gate (STAGE_GATES) -- an ok=True response with no
    # evidence block is MISSING_EVIDENCE -> PARTIAL, which must trigger a
    # real PlanStore.replan() call (not a fresh unrelated plan) and must NOT
    # write any VERIFY blackboard topic (blackboard writes are PASS-only).
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness
        from dv_harness.adapters.base import AgentResult

        class FakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text="I verified it, trust me.", raw={}, session_id="s")

        h = DVHarness(tmp)
        h.adapter = FakeAdapter()
        h.set_stage("VERIFY")

        h.run_stage("goal")
        ss = h.state.stages["VERIFY"]
        assert ss["status"] == "PARTIAL"
        assert not (tmp / ".dv-harness" / "blackboard" / "verification_state.json").exists()

        plan_files = [p for p in (tmp / ".dv-harness" / "plans").glob("PLAN-*.json")
                      if json.loads(p.read_text())["node_id"] == "VERIFY"]
        assert len(plan_files) == 1  # one plan, replanned in place -- not a new plan per attempt
        plan_after_1 = json.loads(plan_files[0].read_text())
        assert plan_after_1["revision"] == 2
        assert plan_after_1["steps"][0]["status"] == "RETRY_PENDING"

        h.run_stage("goal")  # second attempt, same stage
        plan_after_2 = json.loads(plan_files[0].read_text())
        assert plan_after_2["plan_id"] == plan_after_1["plan_id"]
        assert plan_after_2["revision"] == 3  # replanned again, same plan record

        replans = (tmp / ".dv-harness" / "plans" / "replans.jsonl").read_text().strip().splitlines()
        assert len(replans) == 2
        assert all("VERIFY" in r for r in replans)
    finally:
        shutil.rmtree(tmp)


# --- Human Control Plane (control_plane.py) --------------------------------
# Real, minimal implementations of PAUSE/RESUME/TAKEOVER/REDIRECT/APPROVE/
# EVIDENCE/CORRECT/CONSTRAINT/WHY/REPLAN, persisted to .dv-harness/control.json
# and actually read/respected by engine.py's loop()/run_stage() -- not a file
# a human can edit that nothing consults. See control_plane.py's module
# docstring for the overall design.

def _fresh_harness(with_graph=True):
    """A DVHarness rooted at a fresh temp dir, optionally with the real
    project's main_graph.json copied in (needed for graph_next()-driven
    routing tests). Caller is responsible for shutil.rmtree(tmp)."""
    from dv_harness.engine import DVHarness
    tmp = Path(tempfile.mkdtemp())
    if with_graph:
        (tmp / ".dv-harness" / "graph").mkdir(parents=True)
        graph_src = ROOT / ".dv-harness" / "graph" / "main_graph.json"
        (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
            graph_src.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp, DVHarness(tmp)


def test_control_plane_pause_resume_round_trip():
    from dv_harness.control_plane import ControlPlane
    tmp = Path(tempfile.mkdtemp())
    try:
        cp = ControlPlane(tmp)
        assert cp.is_paused() is False
        cp.pause("investigating a flaky VIP config")
        data = cp.load()
        assert data["paused"] is True
        assert data["paused_reason"] == "investigating a flaky VIP config"
        assert data["paused_at"]
        assert cp.is_paused() is True

        cp.resume()
        data = cp.load()
        assert data["paused"] is False
        assert data["paused_reason"] == ""
        assert data["paused_at"] is None
    finally:
        shutil.rmtree(tmp)


def test_control_plane_approve_rejects_invalid_reviewer_confidence():
    # Regression for the GUI/CLI end-to-end confirmation audit (2026-08-28):
    # only the CLI's argparse choices=[...] rejected an invalid
    # reviewer_confidence -- dashboard.py's HTTP path had no equivalent
    # check and would silently persist a garbage value into control.json,
    # corrupting gates.py's Tier-5 REVIEWER_CONFIDENCE_LEVELS assumption.
    # Validating inside ControlPlane.approve() itself protects every caller.
    from dv_harness.control_plane import ControlPlane
    tmp = Path(tempfile.mkdtemp())
    try:
        cp = ControlPlane(tmp)
        try:
            cp.approve("SIGNOFF", reviewer_confidence="SUPER_SURE")
            assert False, "must reject an invalid reviewer_confidence"
        except ValueError as e:
            assert "SUPER_SURE" in str(e)
        assert cp.get_approval("SIGNOFF") is None  # nothing persisted
    finally:
        shutil.rmtree(tmp)


def test_approve_archives_prior_approval_instead_of_silently_overwriting():
    # Regression for the multi-persona interaction review (2026-08-28): DE
    # Manager/DV Manager independently found approve() silently overwrote a
    # prior reviewer's record with no trace anywhere on disk. A second
    # APPROVE for the same stage must archive the first into
    # approval_history rather than destroy it.
    from dv_harness.control_plane import ControlPlane
    tmp = Path(tempfile.mkdtemp())
    try:
        cp = ControlPlane(tmp)
        cp.approve("SIGNOFF", note="first review", reviewer_id="alice", reviewer_confidence="HIGH")
        cp.approve("SIGNOFF", note="second review", reviewer_id="bob", reviewer_confidence="MEDIUM")

        current = cp.get_approval("SIGNOFF")
        assert current["reviewer_id"] == "bob"

        history = cp.get_approval_history("SIGNOFF")
        assert len(history) == 1
        assert history[0]["reviewer_id"] == "alice"
        assert history[0]["outcome"] == "OVERWRITTEN_BY_NEW_APPROVAL"
        assert history[0]["outcome_at"]
    finally:
        shutil.rmtree(tmp)


def test_clear_approval_archives_instead_of_deleting_with_no_trace():
    # Regression: clear_approval() (added earlier this session to make
    # APPROVE single-use) previously deleted the record outright -- "the one
    # human-authored SIGNOFF record vanishes with no trace anywhere on disk"
    # (DV Manager finding). Consuming an approval must archive it first.
    from dv_harness.control_plane import ControlPlane
    tmp = Path(tempfile.mkdtemp())
    try:
        cp = ControlPlane(tmp)
        cp.approve("SIGNOFF", note="reviewed", reviewer_id="alice")
        cp.clear_approval("SIGNOFF")

        assert cp.get_approval("SIGNOFF") is None
        history = cp.get_approval_history("SIGNOFF")
        assert len(history) == 1
        assert history[0]["reviewer_id"] == "alice"
        assert history[0]["outcome"] == "CONSUMED_BY_PASS"
    finally:
        shutil.rmtree(tmp)


def test_control_plane_cli_verbs_are_all_logged_to_events():
    # Regression: DE Manager/DV Manager independently found only `correct`
    # wrote to events.jsonl -- pause/resume/takeover/release-takeover/
    # constraint silently mutated control.json with no audit trail.
    import subprocess, sys
    tmp, _h = _fresh_harness(with_graph=False)
    try:
        def run_cli(*args):
            r = subprocess.run(
                [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
                cwd=str(ROOT), capture_output=True, text=True, timeout=30,
            )
            assert r.returncode == 0, r.stderr
            return r

        run_cli("pause", "--reason", "debugging")
        run_cli("resume")
        run_cli("takeover", "--message", "manual review")
        run_cli("release-takeover")
        run_cli("constraint", "--add", "do not force push")
        run_cli("approve", "SIGNOFF", "--note", "ok", "--reviewer-id", "alice")

        events = [json.loads(l) for l in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()]
        cmds = [e.get("cmd") for e in events]
        for expected in ("pause", "resume", "takeover", "release-takeover", "constraint", "approve"):
            assert expected in cmds, f"{expected} missing from logged events: {cmds}"
    finally:
        shutil.rmtree(tmp)


def test_mark_and_set_stage_and_advance_are_logged_and_tagged_ungated():
    # Regression: DV Engineer found mark/set-stage/advance "silently bypass
    # all gates AND the event log ... visually indistinguishable from a
    # genuine gate-verified PASS."
    import subprocess, sys
    tmp, _h = _fresh_harness()
    try:
        def run_cli(*args):
            r = subprocess.run(
                [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
                cwd=str(ROOT), capture_output=True, text=True, timeout=30,
            )
            assert r.returncode == 0, r.stderr
            return r

        run_cli("mark", "PASS", "--message", "manually marking PASS")
        run_cli("set-stage", "DISCOVERY")
        run_cli("advance")

        events = [json.loads(l) for l in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()]
        cmds = {e.get("cmd"): e for e in events}
        for expected in ("mark", "set-stage", "advance"):
            assert expected in cmds, f"{expected} missing from logged events: {list(cmds)}"
            assert cmds[expected]["ungated"] is True

        from dv_harness.engine import DVHarness
        h2 = DVHarness(tmp)
        assert h2.state.stages["ENV_CHECK"]["ungated"] is True
    finally:
        shutil.rmtree(tmp)


def test_summary_surfaces_control_plane_and_dv_review_cosign_state():
    # Regression: DV Engineer/Project Lead/DE Manager found `status` alone
    # never showed PAUSE/TAKEOVER/constraint state or whether the DV-review
    # co-sign policy is even enforced.
    from dv_harness.control_plane import ControlPlane
    tmp, h = _fresh_harness()
    try:
        base = json.loads(h.summary())
        assert base["paused"] is False
        assert base["takeover_active"] is False
        assert base["active_constraint_count"] == 0
        assert base["dv_review_cosign_enforced"] is False

        cp = ControlPlane(tmp)
        cp.pause("investigating")
        cp.takeover("VERIFY", "manual review", taken_by="alice")
        cp.add_constraint("do not force push")

        after = json.loads(h.summary())
        assert after["paused"] is True
        assert after["paused_reason"] == "investigating"
        assert after["takeover_active"] is True
        assert after["takeover_stage"] == "VERIFY"
        assert after["active_constraint_count"] == 1
    finally:
        shutil.rmtree(tmp)


def test_loop_stops_cleanly_when_paused_before_running_any_stage(capsys):
    # PAUSE is checked at the very top of loop(), before run_stage() is ever
    # called -- the adapter must never be invoked.
    from dv_harness.control_plane import ControlPlane
    tmp, h = _fresh_harness()
    try:
        ControlPlane(tmp).pause("lunch")

        class _BoomAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                raise AssertionError("adapter must not run while PAUSED")

        h.adapter = _BoomAdapter()
        start_stage = h.state.current_stage
        h.loop("goal")  # must return cleanly, not raise, not busy-wait
        assert h.state.current_stage == start_stage
        out = capsys.readouterr().out
        assert "PAUSED" in out
        assert "lunch" in out
    finally:
        shutil.rmtree(tmp)


def test_takeover_blocks_run_stage_directly_without_calling_adapter():
    # Strongest override: TAKEOVER must be honored even when run_stage() is
    # called directly, bypassing loop()'s own check -- no adapter call at all.
    from dv_harness.control_plane import ControlPlane
    tmp, h = _fresh_harness()
    try:
        stage = h.state.current_stage
        ControlPlane(tmp).takeover(stage, "manual review of ENV_CHECK")

        class _BoomAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                raise AssertionError("adapter must not run while TAKEOVER is active")

        h.adapter = _BoomAdapter()
        before_attempts = h.state.stages[stage]["attempts"]
        result = h.run_stage("goal")
        assert result.ok is False
        assert "TAKEOVER" in result.text
        # No state mutation beyond the refusal -- attempts must not have
        # been incremented (that would consume a retry for a run that never
        # happened).
        assert h.state.stages[stage]["attempts"] == before_attempts
    finally:
        shutil.rmtree(tmp)


def test_loop_stops_cleanly_under_takeover_and_marks_wait_user():
    from dv_harness.control_plane import ControlPlane
    tmp, h = _fresh_harness()
    try:
        stage = h.state.current_stage
        ControlPlane(tmp).takeover(stage, "holding for design review")

        class _BoomAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                raise AssertionError("adapter must not run while TAKEOVER is active")

        h.adapter = _BoomAdapter()
        h.loop("goal")
        assert h.state.current_stage == stage
        assert h.state.stages[stage]["status"] == Status.WAIT_USER.value
        assert "TAKEOVER" in h.state.stages[stage]["blocking_reason"]
    finally:
        shutil.rmtree(tmp)


def test_takeover_blocks_run_stage_even_on_a_different_stage_than_it_was_taken_on():
    # Regression for the wq5whmpdv adversarial-verify finding: TAKEOVER used
    # to require tk["stage"] == the stage run_stage()/loop() was about to
    # execute. Since the harness only ever tracks one current_stage, a human
    # taking over a stage name that the pipeline has since moved past got
    # silent non-enforcement -- the "strongest override" enforced nothing.
    # TAKEOVER must now halt regardless of which stage it names.
    from dv_harness.control_plane import ControlPlane
    tmp, h = _fresh_harness()
    try:
        stage = h.state.current_stage  # ENV_CHECK
        ControlPlane(tmp).takeover("SOME_OTHER_STAGE_ENTIRELY", "taken against a stale status read")

        class _BoomAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                raise AssertionError("adapter must not run while ANY takeover is active")

        h.adapter = _BoomAdapter()
        result = h.run_stage("goal")
        assert result.ok is False
        assert "TAKEOVER" in result.text
        assert result.raw["takeover_stage"] == "SOME_OTHER_STAGE_ENTIRELY"

        h.loop("goal")
        assert h.state.current_stage == stage
        assert h.state.stages[stage]["status"] == Status.WAIT_USER.value
        assert "TAKEOVER" in h.state.stages[stage]["blocking_reason"]
    finally:
        shutil.rmtree(tmp)


def test_approve_is_single_use_and_does_not_authorize_a_later_unreviewed_pass():
    # Regression for the wq5whmpdv adversarial-verify finding: an APPROVE
    # record previously never expired -- approving once let every future PASS
    # at that stage close automatically, even against completely different,
    # never-reviewed evidence from a later re-run. APPROVE must now be
    # consumed by the PASS it authorizes.
    from dv_harness.control_plane import ControlPlane
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.set_stage("SIGNOFF")
        ControlPlane(tmp).approve("SIGNOFF", note="looks good", reviewer_id="alice")

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text="evidence v1", raw={}, session_id=None)

        h.adapter = _PassAdapter()
        h.run_stage("goal")
        assert h.state.stages["SIGNOFF"]["status"] == Status.PASS.value
        assert ControlPlane(tmp).get_approval("SIGNOFF") is None  # consumed

        # A second, later re-run of the same stage against DIFFERENT
        # (never-reviewed) evidence must NOT close automatically off the
        # stale approval -- it must go back to WAIT_USER pending a fresh
        # `dv-harness approve`.
        h.adapter = type("_PassAdapter2", (), {
            "run": lambda self, prompt, cwd, resume_session=None, agent_profile=None:
                AgentResult(ok=True, text="completely different unreviewed evidence v2", raw={}, session_id=None)
        })()
        h.run_stage("goal")
        assert h.state.stages["SIGNOFF"]["status"] == Status.WAIT_USER.value
        assert "HUMAN_APPROVAL_REQUIRED" in h.state.stages["SIGNOFF"]["blocking_reason"]
    finally:
        shutil.rmtree(tmp)


def test_human_redirect_tags_event_distinct_from_automatic_graph_routing():
    tmp, h = _fresh_harness()
    try:
        from_stage = h.state.current_stage
        h.state.stages[from_stage]["blocking_reason"] = "was stuck here"
        h.human_redirect("VPLAN", reason="already validated manually, skip ahead")
        assert h.state.current_stage == "VPLAN"
        # Leaving the FROM stage's blocking_reason cleared -- the human's
        # decision to move on is itself the resolution.
        assert h.state.stages[from_stage]["blocking_reason"] == ""

        events = [json.loads(l) for l in (tmp / ".dv-harness" / "events.jsonl").read_text(
            encoding="utf-8").splitlines()]
        last = events[-1]
        assert last["human_redirect"] is True
        assert last["from_stage"] == from_stage
        assert last["to_stage"] == "VPLAN"
        assert last["reason"] == "already validated manually, skip ahead"
    finally:
        shutil.rmtree(tmp)


def test_human_redirect_refused_while_takeover_active_on_another_stage():
    from dv_harness.control_plane import ControlPlane
    tmp, h = _fresh_harness()
    try:
        stage = h.state.current_stage
        ControlPlane(tmp).takeover(stage, "holding this stage")
        try:
            h.human_redirect("VPLAN", reason="try to route around the takeover")
            assert False, "redirect must be refused while a different stage is under takeover"
        except RuntimeError as e:
            assert "TAKEOVER" in str(e)
        assert h.state.current_stage == stage  # unchanged

        # Redirecting TO the same stage the takeover holds is not refused --
        # there's no override conflict, it's a no-op-ish confirmation.
        h.human_redirect(stage, reason="reaffirm current stage")
        assert h.state.current_stage == stage
    finally:
        shutil.rmtree(tmp)


def test_constraint_and_correction_are_folded_into_next_stage_prompt():
    from dv_harness.control_plane import ControlPlane
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        cp = ControlPlane(tmp)
        cp.add_constraint("never touch the RTL top module directly")
        stage = h.state.current_stage
        cp.set_correction(stage, "the sim_log path you used was wrong; check tools/output/")

        seen = {}

        class _CaptureAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                seen["prompt"] = prompt
                return AgentResult(ok=True, text="fine", raw={}, session_id=None)

        h.adapter = _CaptureAdapter()
        h.run_stage("goal")
        assert "never touch the RTL top module directly" in seen["prompt"]
        assert "sim_log path you used was wrong" in seen["prompt"]

        # Correction is consumed once the stage reaches PASS -- must not be
        # folded into the NEXT stage's prompt for a different stage/attempt.
        assert cp.get_active_correction(stage) is None
    finally:
        shutil.rmtree(tmp)


def test_correction_stays_active_until_stage_actually_passes():
    # Patches evaluate_stage_evidence at the exact boundary engine.run_stage()
    # calls, rather than relying on any particular stage's live STAGE_GATES
    # mapping in gates.py (which other in-flight work in this codebase may be
    # actively extending) -- this test is about control_plane's own
    # consume-on-PASS-only logic, not about gates.py's current stage mapping.
    from dv_harness.control_plane import ControlPlane
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        stage = h.state.current_stage
        ControlPlane(tmp).set_correction(stage, "try harder next time")

        class _AnyAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text="irrelevant for this test",
                                    raw={}, session_id=None)

        h.adapter = _AnyAdapter()
        with patch("dv_harness.engine.evaluate_stage_evidence",
                   return_value=("GATE_FAIL", ["forced for test"])):
            h.run_stage("goal")
        assert h.state.stages[stage]["status"] == Status.PARTIAL.value
        # Correction must still be active -- the human's guidance has not
        # yet been addressed by a passing gate.
        assert ControlPlane(tmp).get_active_correction(stage) is not None
    finally:
        shutil.rmtree(tmp)


def test_approve_gates_promotion_readiness_and_signoff_but_not_other_stages():
    from dv_harness.control_plane import ControlPlane
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text="fine", raw={}, session_id=None)

        h.adapter = _PassAdapter()

        # A stage with no approval requirement (e.g. DISCOVERY) passes clean.
        h.set_stage("DISCOVERY")
        h.run_stage("goal")
        assert h.state.stages["DISCOVERY"]["status"] == Status.PASS.value

        # PROMOTION_READINESS/SIGNOFF need a recorded APPROVE even though the
        # gate itself (bypassed here) would have accepted -- an agent-graded
        # PASS is not the same as a human sign-off.
        h.set_stage("PROMOTION_READINESS")
        h.run_stage("goal")
        assert h.state.stages["PROMOTION_READINESS"]["status"] == Status.WAIT_USER.value
        assert "HUMAN_APPROVAL_REQUIRED" in h.state.stages["PROMOTION_READINESS"]["blocking_reason"]

        ControlPlane(tmp).approve("PROMOTION_READINESS", note="reviewed", reviewer_id="alice")
        h.run_stage("goal")
        assert h.state.stages["PROMOTION_READINESS"]["status"] == Status.PASS.value
    finally:
        shutil.rmtree(tmp)


def _re_audit_evidence_text(**fix_risk_overrides):
    plan = {
        "root_cause_id": "RCA-1", "fix_plan": "add prefetch guard in ep0 fifo ctrl",
        "risk_assessment": "contained to ep0 datapath", "affected_scope": "usb_dev.ep0",
        "regression_plan": "rerun ep0 test suite", "rollback_plan": "revert commit c1",
        "root_cause_confidence": "HIGH", "risk_level": "LOW", "approved_for_modify": True,
    }
    plan.update(fix_risk_overrides)
    return "```dv-harness-evidence:fix_risk_approval_gate\n" + json.dumps(plan) + "\n```\n"


def test_re_audit_dut_bug_fix_requires_real_control_plane_approval():
    # Confirmed gap (2026-09-02, RE_AUDIT/FAILURE_RECOVERY approval-gate
    # audit): unlike PROMOTION_READINESS/SIGNOFF above, RE_AUDIT previously
    # had NO engine-level human-approval hard-stop at all -- a DUT_BUG/
    # high-risk fix could close purely off the agent's own self-declared
    # "approved_for_modify" boolean, in the same reply that proposed the
    # fix. This must now behave exactly like PROMOTION_READINESS/SIGNOFF:
    # gate evidence passing is not enough, a real `dv-harness approve
    # RE_AUDIT` is required.
    from dv_harness.control_plane import ControlPlane
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.set_stage("RE_AUDIT")

        text = _re_audit_evidence_text(classification="DUT_BUG", risk_level="LOW")

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        h.adapter = _PassAdapter()
        h.run_stage("goal")
        assert h.state.stages["RE_AUDIT"]["status"] == Status.WAIT_USER.value
        assert "HUMAN_APPROVAL_REQUIRED" in h.state.stages["RE_AUDIT"]["blocking_reason"]

        # A real approve() call (the SAME ControlPlane mechanism
        # PROMOTION_READINESS/SIGNOFF already use) unblocks it.
        ControlPlane(tmp).approve("RE_AUDIT", note="reviewed", reviewer_id="alice")
        h.run_stage("goal")
        assert h.state.stages["RE_AUDIT"]["status"] == Status.PASS.value
    finally:
        shutil.rmtree(tmp)


def test_re_audit_high_risk_fix_requires_real_control_plane_approval():
    from dv_harness.control_plane import ControlPlane
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.set_stage("RE_AUDIT")

        text = _re_audit_evidence_text(classification="TB_BUG", risk_level="HIGH")

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        h.adapter = _PassAdapter()
        h.run_stage("goal")
        assert h.state.stages["RE_AUDIT"]["status"] == Status.WAIT_USER.value
        assert "HUMAN_APPROVAL_REQUIRED" in h.state.stages["RE_AUDIT"]["blocking_reason"]

        ControlPlane(tmp).approve("RE_AUDIT", note="reviewed", reviewer_id="alice")
        h.run_stage("goal")
        assert h.state.stages["RE_AUDIT"]["status"] == Status.PASS.value
    finally:
        shutil.rmtree(tmp)


def test_re_audit_tb_bug_low_risk_fix_needs_no_human_approval():
    # Scoped narrowly on purpose: a routine TB_BUG/low-risk RE_AUDIT closure
    # must NOT require a human `dv-harness approve` call -- that would make
    # every routine testbench fix require a human, which is disproportionate
    # and not what this hardening pass targets.
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.set_stage("RE_AUDIT")

        text = _re_audit_evidence_text(classification="TB_BUG", risk_level="LOW")

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        h.adapter = _PassAdapter()
        h.run_stage("goal")
        assert h.state.stages["RE_AUDIT"]["status"] == Status.PASS.value
    finally:
        shutil.rmtree(tmp)


def test_evidence_and_why_report_real_current_run_state_not_generic_text():
    from dv_harness.control_plane import describe_stage
    tmp, h = _fresh_harness()
    try:
        stage = "VERIFY"
        h.state.stages[stage]["last_message"] = (
            "```dv-harness-evidence:simulation_semantic_validation_gate\n"
            '{"simulation_passed": true, "sim_log": "UVM_INFO enum PASS", '
            '"command_expectations": [{"expectation_id": "e1", "required": true, '
            '"evidence_requirements": [{"pattern": "enum PASS", "match_mode": "SUBSTRING"}]}]}\n'
            "```\n"
        )
        h.state.stages[stage]["blocking_reason"] = "waiting on false_pass_resistance_gate"
        desc = describe_stage(tmp, h.state, stage)
        assert desc["blocking_reason"] == "waiting on false_pass_resistance_gate"
        assert "simulation_semantic_validation_gate" in desc["evidence_blocks"]
        # simulation_semantic_validation_gate on its own is not sufficient for
        # VERIFY to PASS (test_result_provenance_gate/false_pass_resistance_gate
        # are also mapped) -- this must reflect the real, current gate verdict,
        # not just echo back "PASS" because the agent said so.
        assert desc["gate_verdict"] not in ("PASS", "NO_GATE_REQUIRED")
    finally:
        shutil.rmtree(tmp)


def test_replan_is_actually_invoked_on_retry_exhaustion_not_orphaned():
    # planner.PlanStore.replan was previously correct but never called by any
    # executing code path. loop()'s retry-exhaustion branch now calls
    # control_plane.replan_stage with the stage's real attempts/blocking_reason.
    #
    # Forces GATE_FAIL via evaluate_stage_evidence directly (rather than
    # relying on any particular stage's live STAGE_GATES mapping) so this
    # test is deterministic regardless of which stages gates.py currently
    # maps -- and reads the exhausted stage back from h.state.current_stage
    # AFTER loop() returns, rather than assuming it is still whatever stage
    # the harness started on (loop()'s graph-FAIL-edge routing is a separate
    # concern this test does not need to pin down).
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["max_stage_retries"] = 0

        class _AnyAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text="irrelevant for this test", raw={}, session_id=None)

        h.adapter = _AnyAdapter()
        with patch("dv_harness.engine.evaluate_stage_evidence",
                   return_value=("GATE_FAIL", ["forced for test"])):
            h.loop("goal")
        # Whichever stage loop() is left sitting on when it stops (its own
        # graph FAIL-edge routing is not this test's concern) must be the
        # one it just exhausted retries on -- it must never have advanced
        # past a GATE_FAIL stage as if it had passed.
        exhausted_stage = h.state.current_stage
        assert h.state.stages[exhausted_stage]["status"] in (Status.PARTIAL.value, Status.FAIL.value)

        plans_dir = tmp / ".dv-harness" / "plans"
        plan_files = list(plans_dir.glob("PLAN-*.json"))
        assert plan_files, "loop() must have created/updated a plan for the exhausted stage"
        matching = [json.loads(f.read_text(encoding="utf-8")) for f in plan_files]
        plan = next((p for p in matching if p["node_id"] == exhausted_stage), None)
        assert plan is not None, f"no plan recorded for {exhausted_stage}: {matching}"
        assert plan["revision"] >= 2  # create() -> revision 1, replan() -> >=2

        replans = (plans_dir / "replans.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert replans, "replans.jsonl must record the retry-exhaustion replan"
        last = json.loads(replans[-1])
        assert last["plan_id"] == plan["plan_id"]
        assert "exhausted retries" in last["reason"] or exhausted_stage in last["reason"]
        assert last["evidence"]["stage"] == exhausted_stage
    finally:
        shutil.rmtree(tmp)


def test_correct_cli_writes_correction_resets_attempts_and_calls_replan():
    import subprocess, sys
    tmp, h = _fresh_harness(with_graph=False)
    try:
        stage = h.state.current_stage
        h.state.stages[stage]["attempts"] = 3
        h.state.stages[stage]["blocking_reason"] = "GATE_FAIL: some prior reason"
        h.store.save(h.state)

        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "correct", stage, "--note", "use the cached env report instead", "--reset-attempts"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stderr

        from dv_harness.control_plane import ControlPlane
        cp = ControlPlane(tmp)
        entry = cp.get_active_correction(stage)
        assert entry is not None
        assert entry["note"] == "use the cached env report instead"

        reloaded = h.store.load()
        assert reloaded.stages[stage]["attempts"] == 0

        plans_dir = tmp / ".dv-harness" / "plans"
        plan_files = list(plans_dir.glob("PLAN-*.json"))
        assert plan_files
        plan = json.loads(plan_files[0].read_text(encoding="utf-8"))
        assert plan["node_id"] == stage
        assert plan["goal"] == "use the cached env report instead"
    finally:
        shutil.rmtree(tmp)


def test_constraint_cli_add_list_remove_round_trip():
    import subprocess, sys

    def run_cli(tmp, *args):
        return subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )

    tmp, _h = _fresh_harness(with_graph=False)
    try:
        r = run_cli(tmp, "constraint", "--add", "do not force push")
        assert r.returncode == 0
        added = json.loads(r.stdout)
        cid = added["id"]

        r = run_cli(tmp, "constraint", "--list")
        assert r.returncode == 0
        listed = json.loads(r.stdout)
        assert any(c["id"] == cid for c in listed)

        r = run_cli(tmp, "constraint", "--remove", cid)
        assert r.returncode == 0
        assert "REMOVED" in r.stdout

        r = run_cli(tmp, "constraint", "--list")
        listed_after = json.loads(r.stdout)
        assert not any(c["id"] == cid for c in listed_after)
    finally:
        shutil.rmtree(tmp)


def test_pause_resume_takeover_cli_subcommands_round_trip():
    import subprocess, sys

    def run_cli(tmp, *args):
        return subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )

    tmp, _h = _fresh_harness(with_graph=False)
    try:
        from dv_harness.control_plane import ControlPlane
        cp = ControlPlane(tmp)

        r = run_cli(tmp, "pause", "--reason", "debugging")
        assert r.returncode == 0
        assert cp.is_paused() is True

        r = run_cli(tmp, "resume")
        assert r.returncode == 0
        assert cp.is_paused() is False

        r = run_cli(tmp, "takeover", "--message", "manual review")
        assert r.returncode == 0
        assert cp.is_takeover_active_for("ENV_CHECK") is True

        r = run_cli(tmp, "release-takeover")
        assert r.returncode == 0
        assert cp.takeover_status()["active"] is False
    finally:
        shutil.rmtree(tmp)


def test_approve_cli_writes_reviewer_wrapper_fields():
    import subprocess, sys
    tmp, _h = _fresh_harness(with_graph=False)
    try:
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "approve", "SIGNOFF", "--note", "final review done", "--reviewer-id", "bob",
             "--reviewer-confidence", "HIGH"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stderr
        from dv_harness.control_plane import ControlPlane
        entry = ControlPlane(tmp).get_approval("SIGNOFF")
        assert entry["reviewer_id"] == "bob"
        assert entry["reviewer_confidence"] == "HIGH"
        assert entry["note"] == "final review done"
    finally:
        shutil.rmtree(tmp)


def test_dv_review_cosign_enabled_accepts_durable_cosign_without_inline_wrapper():
    # Item 2 (DV-review co-sign direct-submit action, 2026-08-28 GUI/CLI
    # gap-closure pass): gates._check_judgment_fields must accept an
    # UNWRAPPED judgment field when a durable ControlPlane cosign record
    # (commands.cmd_cosign / ControlPlane.add_cosign -- CLI `dv-harness
    # cosign` / dashboard COSIGN control) exists for (stage,
    # "<gate_id>/<loc>") whose stored value EXACTLY matches the bare value
    # found here. This is the real, gate-affecting half of the mechanism --
    # not merely a visibility record. Patches gates.ControlPlane rather than
    # writing to the real project's control.json, mirroring
    # _cosign_enabled()'s "never mutate shared repo state" discipline above.
    text = ('''```dv-harness-evidence:corner_risk_rank
{"cases": [{"corner_id": "c1", "risk_factors": ["reset", "cdc"]}]}
```''' + "\n" + _SOC_SCENARIO_PLANNER_EXTRA_GATES)

    class _FakeControlPlane:
        def __init__(self, root):
            pass

        def list_cosigns(self, stage):
            assert stage == "SOC_SCENARIO_PLANNER"
            return {"corner_risk_rank/cases[0].risk_factors":
                    {"value": ["reset", "cdc"], "reviewer_id": "alice",
                     "reviewer_confidence": "HIGH"}}

    with _cosign_enabled(), patch("dv_harness.gates.ControlPlane", _FakeControlPlane):
        verdict, reasons = evaluate_stage_evidence(ROOT, "SOC_SCENARIO_PLANNER", text)
    assert verdict == "PASS", reasons


def test_dv_review_cosign_stale_record_does_not_cover_a_changed_value():
    # A stored cosign covers only the EXACT value it was written for -- a
    # different bare value at the same field-site (e.g. the agent's next
    # attempt revised the content) must NOT be silently accepted by a stale
    # cosign; it still needs either an inline wrapper or a fresh co-sign.
    text = ('''```dv-harness-evidence:corner_risk_rank
{"cases": [{"corner_id": "c1", "risk_factors": ["reset", "cdc", "power"]}]}
```''' + "\n" + _SOC_SCENARIO_PLANNER_EXTRA_GATES)

    class _FakeControlPlane:
        def __init__(self, root):
            pass

        def list_cosigns(self, stage):
            return {"corner_risk_rank/cases[0].risk_factors":
                    {"value": ["reset", "cdc"], "reviewer_id": "alice",
                     "reviewer_confidence": "HIGH"}}

    with _cosign_enabled(), patch("dv_harness.gates.ControlPlane", _FakeControlPlane):
        verdict, reasons = evaluate_stage_evidence(ROOT, "SOC_SCENARIO_PLANNER", text)
    assert verdict == "DV_REVIEW_PENDING", reasons
    assert any("risk_factors" in str(r) for r in reasons)


def test_control_plane_add_cosign_round_trip_and_validation():
    from dv_harness.control_plane import ControlPlane
    tmp = Path(tempfile.mkdtemp())
    try:
        cp = ControlPlane(tmp)
        entry = cp.add_cosign("SOC_SCENARIO_PLANNER", "corner_risk_rank/cases[0].risk_factors",
                               ["reset", "cdc"], reviewer_id="alice", reviewer_confidence="HIGH")
        assert entry["value"] == ["reset", "cdc"]
        assert cp.get_cosign("SOC_SCENARIO_PLANNER", "corner_risk_rank/cases[0].risk_factors")["reviewer_id"] == "alice"
        assert "corner_risk_rank/cases[0].risk_factors" in cp.list_cosigns("SOC_SCENARIO_PLANNER")

        try:
            cp.add_cosign("SOC_SCENARIO_PLANNER", "gate/loc", "x", reviewer_id="alice",
                           reviewer_confidence="SUPER_SURE")
            assert False, "must reject an invalid reviewer_confidence"
        except ValueError as e:
            assert "SUPER_SURE" in str(e)

        try:
            cp.add_cosign("SOC_SCENARIO_PLANNER", "gate/loc", "x", reviewer_id="")
            assert False, "must reject a missing reviewer_id"
        except ValueError:
            pass
    finally:
        shutil.rmtree(tmp)


def test_cosign_cli_persists_record_and_logs_event():
    import subprocess, sys
    tmp, _h = _fresh_harness(with_graph=False)
    try:
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "cosign", "SOC_SCENARIO_PLANNER", "corner_risk_rank/cases[0].risk_factors",
             "--value", '["reset", "cdc"]', "--reviewer-id", "alice", "--reviewer-confidence", "HIGH"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stderr

        from dv_harness.control_plane import ControlPlane
        entry = ControlPlane(tmp).get_cosign("SOC_SCENARIO_PLANNER", "corner_risk_rank/cases[0].risk_factors")
        assert entry["value"] == ["reset", "cdc"]
        assert entry["reviewer_id"] == "alice"

        events = [json.loads(l) for l in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()]
        assert any(e.get("cmd") == "cosign" for e in events)
    finally:
        shutil.rmtree(tmp)


def test_config_cli_set_and_get_require_dv_review_cosign():
    import subprocess, sys
    tmp, _h = _fresh_harness(with_graph=False)
    try:
        def run_cli(*args):
            r = subprocess.run(
                [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
                cwd=str(ROOT), capture_output=True, text=True, timeout=30,
            )
            assert r.returncode == 0, r.stderr
            return r

        r = run_cli("config", "get")
        assert json.loads(r.stdout)["require_dv_review_cosign"] is False

        r = run_cli("config", "set", "require_dv_review_cosign", "true")
        assert json.loads(r.stdout) == {"require_dv_review_cosign": True}

        from dv_harness.config import load_config
        assert load_config(tmp)["policy"]["require_dv_review_cosign"] is True

        r = run_cli("config", "get")
        assert json.loads(r.stdout)["require_dv_review_cosign"] is True
    finally:
        shutil.rmtree(tmp)


def test_lsf_cli_list_and_single_job_and_not_found():
    import subprocess, sys
    tmp, _h = _fresh_harness(with_graph=False)
    try:
        jobs_dir = tmp / ".dv-harness" / "lsf" / "jobs"
        jobs_dir.mkdir(parents=True)
        (jobs_dir / "j1.json").write_text(json.dumps({"job_id": "1", "lsf_status": "DONE",
                                                        "dv_analysis_status": "PASS"}), encoding="utf-8")
        (jobs_dir / "j2.json").write_text(json.dumps({"job_id": "2", "lsf_status": "RUN"}), encoding="utf-8")

        def run_cli(*args):
            return subprocess.run(
                [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
                cwd=str(ROOT), capture_output=True, text=True, timeout=30,
            )

        r = run_cli("lsf", "--list")
        assert r.returncode == 0, r.stderr
        listed = json.loads(r.stdout)
        assert {j["job_id"] for j in listed} == {"1", "2"}

        r = run_cli("lsf", "1")
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["dv_analysis_status"] == "PASS"

        r = run_cli("lsf", "does-not-exist")
        assert r.returncode == 1
        assert json.loads(r.stdout)["error"] == "NOT_FOUND"
    finally:
        shutil.rmtree(tmp)


def test_regression_reporter_get_job_helper():
    from dv_harness.regression_reporter import get_job
    tmp = Path(tempfile.mkdtemp())
    try:
        jobs_dir = tmp / ".dv-harness" / "lsf" / "jobs"
        jobs_dir.mkdir(parents=True)
        (jobs_dir / "j1.json").write_text(json.dumps({"job_id": 7, "lsf_status": "DONE"}), encoding="utf-8")
        assert get_job(tmp, "7")["lsf_status"] == "DONE"
        assert get_job(tmp, 7)["lsf_status"] == "DONE"  # int/str job_id both match
        assert get_job(tmp, "999") is None
    finally:
        shutil.rmtree(tmp)


def test_audit_cli_reports_events_and_control_state():
    import subprocess, sys
    tmp, _h = _fresh_harness(with_graph=False)
    try:
        def run_cli(*args):
            r = subprocess.run(
                [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
                cwd=str(ROOT), capture_output=True, text=True, timeout=30,
            )
            assert r.returncode == 0, r.stderr
            return r

        run_cli("constraint", "--add", "do not force push")
        run_cli("approve", "SIGNOFF", "--note", "ok", "--reviewer-id", "alice")

        r = run_cli("audit", "--limit", "10")
        data = json.loads(r.stdout)
        assert data["limit"] == 10
        cmds = [e.get("cmd") for e in data["events"]]
        assert "constraint" in cmds and "approve" in cmds
        assert "SIGNOFF" in data["approvals"]
        assert data["approvals"]["SIGNOFF"]["reviewer_id"] == "alice"
    finally:
        shutil.rmtree(tmp)


def test_build_stage_prompt_constraint_correction_approval_are_additive():
    # None-default path must reproduce the pre-control-plane prompt exactly
    # (already covered by test_de_explainer_is_additive_and_does_not_change_agent_prompt);
    # this covers the opt-in path actually appending the expected sections.
    base = build_stage_prompt("VPLAN", "state", "goal")
    with_constraint = build_stage_prompt("VPLAN", "state", "goal",
                                          constraints=["never force push"])
    assert with_constraint.startswith(base)
    assert "never force push" in with_constraint

    with_correction = build_stage_prompt("VPLAN", "state", "goal",
                                          correction_note="check the other log file")
    assert with_correction.startswith(base)
    assert "check the other log file" in with_correction

    with_approval = build_stage_prompt("VPLAN", "state", "goal",
                                        human_approval={"reviewer_id": "alice",
                                                         "reviewer_confidence": "HIGH"})
    assert with_approval.startswith(base)
    assert "alice" in with_approval and "HIGH" in with_approval


# --- 7-ungated-stage closure pass (2026-08-28): BUILD_DEBUG, GIT_SYNC,
# INFRA_RECOVERY, PROJECT_MODEL, REGRESSION, REGRESSION_SELECT, SERVER_SYNC
# were the only 7 Stage enum values with zero STAGE_GATES entry. Each below
# drives the real evaluate_stage_evidence() -> run_gate() -> subprocess path
# against the newly-added gate script (no mocking), covering: no evidence
# block at all (MISSING_EVIDENCE), a genuinely broken payload (GATE_FAIL, with
# the specific reason asserted), and a well-formed payload (PASS).

def test_build_debug_requires_triage_classification():
    # tools/verification_flow/build_failure_triage_gate.py
    text_missing = "no evidence block here"
    verdict, reasons = evaluate_stage_evidence(ROOT, "BUILD_DEBUG", text_missing)
    assert verdict == "MISSING_EVIDENCE", reasons

    quick_fix_incomplete = {"build_log_excerpt": "missing file foo.sv",
                             "classification": "QUICK_FIX", "classification_reason": "missing filelist entry"}
    text_incomplete = f"```dv-harness-evidence:build_failure_triage_gate\n{json.dumps(quick_fix_incomplete)}\n```\n"
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "BUILD_DEBUG", text_incomplete)
    assert verdict2 == "GATE_FAIL", reasons2
    assert any("QUICK_FIX_INCOMPLETE" in str(r) for r in reasons2)

    design_issue = {"build_log_excerpt": "elab error in fifo.sv", "classification": "DESIGN_ISSUE",
                     "classification_reason": "structural elaboration mismatch",
                     "routed_to_failure_recovery": True, "failure_recovery_finding_id": "F-101"}
    text_pass = f"```dv-harness-evidence:build_failure_triage_gate\n{json.dumps(design_issue)}\n```\n"
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "BUILD_DEBUG", text_pass)
    assert verdict3 == "PASS", reasons3


def test_git_sync_requires_safe_sync_with_accounted_dirty_paths():
    # tools/verification_flow/git_sync_safety_gate.py
    verdict, reasons = evaluate_stage_evidence(ROOT, "GIT_SYNC", "nothing")
    assert verdict == "MISSING_EVIDENCE", reasons

    unaccounted = {"fetch_output": "up to date", "sync_strategy": "FAST_FORWARD",
                   "pre_sync_dirty_paths": ["a.txt", "b.txt"],
                   "accounted_paths": {"stashed": ["a.txt"]}}
    text_fail = f"```dv-harness-evidence:git_sync_safety_gate\n{json.dumps(unaccounted)}\n```\n"
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "GIT_SYNC", text_fail)
    assert verdict2 == "GATE_FAIL", reasons2
    assert any("UNRELATED_CHANGE_UNACCOUNTED" in str(r) for r in reasons2)

    destructive = {"fetch_output": "ok", "sync_strategy": "MERGE", "destructive_command_used": True}
    text_destructive = f"```dv-harness-evidence:git_sync_safety_gate\n{json.dumps(destructive)}\n```\n"
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "GIT_SYNC", text_destructive)
    assert verdict3 == "GATE_FAIL", reasons3
    assert any("DESTRUCTIVE_GIT_COMMAND_USED" in str(r) for r in reasons3)

    clean = {"fetch_output": "up to date", "sync_strategy": "REBASE",
             "pre_sync_dirty_paths": ["a.txt"], "accounted_paths": {"preserved_untouched": ["a.txt"]}}
    text_pass = f"```dv-harness-evidence:git_sync_safety_gate\n{json.dumps(clean)}\n```\n"
    verdict4, reasons4 = evaluate_stage_evidence(ROOT, "GIT_SYNC", text_pass)
    assert verdict4 == "PASS", reasons4


def test_infra_recovery_triage_routes_infra_vs_functional():
    # tools/verification_flow/regression_infra_functional_triage_gate.py
    verdict, reasons = evaluate_stage_evidence(ROOT, "INFRA_RECOVERY", "nothing")
    assert verdict == "MISSING_EVIDENCE", reasons

    bad_symptom = {"classification": "INFRASTRUCTURE", "classification_reason": "queue down",
                   "evidence_hash": "h1", "infra_symptom": "NETWORK"}
    text_fail = f"```dv-harness-evidence:regression_infra_functional_triage_gate\n{json.dumps(bad_symptom)}\n```\n"
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "INFRA_RECOVERY", text_fail)
    assert verdict2 == "GATE_FAIL", reasons2
    assert any("INVALID_INFRA_SYMPTOM" in str(r) for r in reasons2)

    functional_not_routed = {"classification": "FUNCTIONAL", "classification_reason": "real mismatch",
                              "evidence_hash": "h2"}
    text_fail2 = f"```dv-harness-evidence:regression_infra_functional_triage_gate\n{json.dumps(functional_not_routed)}\n```\n"
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "INFRA_RECOVERY", text_fail2)
    assert verdict3 == "GATE_FAIL", reasons3
    assert any("FUNCTIONAL_NOT_ROUTED" in str(r) for r in reasons3)

    infra_ok = {"classification": "INFRASTRUCTURE", "classification_reason": "LSF queue down",
                "evidence_hash": "h1", "infra_symptom": "LSF", "infra_fix_applied": True,
                "infra_fix_description": "resubmitted after queue recovery",
                "rerun_target_stage": "REGRESSION_SELECT"}
    text_pass = f"```dv-harness-evidence:regression_infra_functional_triage_gate\n{json.dumps(infra_ok)}\n```\n"
    verdict4, reasons4 = evaluate_stage_evidence(ROOT, "INFRA_RECOVERY", text_pass)
    assert verdict4 == "PASS", reasons4


def test_project_model_requires_topology_completeness():
    # tools/verification_flow/project_model_topology_completeness_gate.py
    verdict, reasons = evaluate_stage_evidence(ROOT, "PROJECT_MODEL", "nothing")
    assert verdict == "MISSING_EVIDENCE", reasons

    no_branch = {"verification_boundary": "top.usb_dev",
                 "vip_topology": [{"vip_id": "usb_vip", "bound_interface": "usb_if0"}],
                 "blocks": [{"block_id": "b1"}],
                 "model_confidence": "HIGH", "confidence_basis": "x",
                 "dv_readiness": "READY", "dv_readiness_basis": "x",
                 "architecture_evidence_db_ref": "db1"}
    text_fail = f"```dv-harness-evidence:project_model_topology_completeness_gate\n{json.dumps(no_branch)}\n```\n"
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "PROJECT_MODEL", text_fail)
    assert verdict2 == "GATE_FAIL", reasons2
    assert any("BLOCK_WITHOUT_BRANCH_CLASSIFICATION" in str(r) for r in reasons2)

    complete = {"verification_boundary": "top.usb_dev",
                "vip_topology": [{"vip_id": "usb_vip", "bound_interface": "usb_if0"}],
                "blocks": [{"block_id": "b1", "branch": "BLOCK"}],
                "model_confidence": "HIGH", "confidence_basis": "cross-checked with RTL arch discovery",
                "dv_readiness": "READY", "dv_readiness_basis": "all boundary items resolved",
                "architecture_evidence_db_ref": "arch-db-v3"}
    # ADDED (2026-09-01, route-skill-resolver-dynamic-implementation task):
    # PROJECT_MODEL now also mandates environment_mode_selection -- see
    # gates.STAGE_GATES["PROJECT_MODEL"]. A single subsystem stays
    # SUBSYSTEM_MODE regardless of whether it's registered yet (this test
    # runs against the real ROOT, whose real subsystem registry is empty).
    env_mode_evidence = (
        '```dv-harness-evidence:environment_mode_selection\n'
        '{"environment_mode": "SUBSYSTEM_MODE", "requested_subsystems": ["usb"]}\n```\n'
    )
    text_pass = (
        f"```dv-harness-evidence:project_model_topology_completeness_gate\n{json.dumps(complete)}\n```\n"
        + env_mode_evidence
    )
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "PROJECT_MODEL", text_pass)
    assert verdict3 == "PASS", reasons3

    no_vip_escape_hatch = {"verification_boundary": "top.usb_dev",
                            "vip_topology_not_applicable_reason": "no external VIP in this env",
                            "blocks": [{"block_id": "b1", "branch": "BLOCK"}],
                            "model_confidence": "MEDIUM", "confidence_basis": "partial cross-check",
                            "dv_readiness": "PARTIAL", "dv_readiness_basis": "pending calibration",
                            "architecture_evidence_db_ref": "arch-db-v3"}
    text_pass2 = (
        f"```dv-harness-evidence:project_model_topology_completeness_gate\n{json.dumps(no_vip_escape_hatch)}\n```\n"
        + env_mode_evidence
    )
    verdict4, reasons4 = evaluate_stage_evidence(ROOT, "PROJECT_MODEL", text_pass2)
    assert verdict4 == "PASS", reasons4


def test_regression_select_requires_four_categories_or_reason():
    # tools/verification_flow/regression_selection_completeness_gate.py
    verdict, reasons = evaluate_stage_evidence(ROOT, "REGRESSION_SELECT", "nothing")
    assert verdict == "MISSING_EVIDENCE", reasons

    empty_no_reason = {"targeted_tests": ["t1"], "dependency_tests": ["t2"], "safety_tests": ["t3"],
                        "mandatory_signoff_tests": [],
                        "selection_source": {"change_impact_evidence_id": "ci1"}}
    text_fail = f"```dv-harness-evidence:regression_selection_completeness_gate\n{json.dumps(empty_no_reason)}\n```\n"
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "REGRESSION_SELECT", text_fail)
    assert verdict2 == "GATE_FAIL", reasons2
    assert any("EMPTY_SELECTION_CATEGORY_WITHOUT_REASON" in str(r) for r in reasons2)

    missing_link = {"targeted_tests": ["t1"], "dependency_tests": ["t2"], "safety_tests": ["t3"],
                     "mandatory_signoff_tests": ["t4"]}
    text_fail2 = f"```dv-harness-evidence:regression_selection_completeness_gate\n{json.dumps(missing_link)}\n```\n"
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "REGRESSION_SELECT", text_fail2)
    assert verdict3 == "GATE_FAIL", reasons3
    assert any("MISSING_CHANGE_IMPACT_LINK" in str(r) for r in reasons3)

    complete = {"targeted_tests": ["t1"], "dependency_tests": ["t2"], "safety_tests": ["t3"],
                "mandatory_signoff_tests": ["t4"], "selection_source": {"change_impact_evidence_id": "ci1"}}
    text_pass = f"```dv-harness-evidence:regression_selection_completeness_gate\n{json.dumps(complete)}\n```\n"
    verdict4, reasons4 = evaluate_stage_evidence(ROOT, "REGRESSION_SELECT", text_pass)
    assert verdict4 == "PASS", reasons4


def test_regression_select_requires_single_test_reverify_when_following_fix_cycle():
    # tools/verification_flow/regression_selection_completeness_gate.py
    # RE_AUDIT-precondition audit follow-up (2026-09-02): the real single-test
    # FAIL-before/PASS-after proof (same shape fix_regression_non_regression_gate
    # checks) previously only ran POST-HOC at RE_AUDIT, after a full regression
    # had already been submitted and counted. fix_cycle_id now makes it a real
    # precondition at REGRESSION_SELECT, the stage immediately before REGRESSION
    # submits jobs -- additive, does not replace the RE_AUDIT gate.
    base = {"targeted_tests": ["t1"], "dependency_tests": ["t2"], "safety_tests": ["t3"],
            "mandatory_signoff_tests": ["t4"], "selection_source": {"change_impact_evidence_id": "ci1"}}

    # No fix_cycle_id at all -> unaffected, still PASS (ordinary regression
    # selection with no preceding fix cycle never needs this evidence).
    text_no_cycle = f"```dv-harness-evidence:regression_selection_completeness_gate\n{json.dumps(base)}\n```\n"
    verdict0, reasons0 = evaluate_stage_evidence(ROOT, "REGRESSION_SELECT", text_no_cycle)
    assert verdict0 == "PASS", reasons0

    # fix_cycle_id set but no single_test_reverify_evidence at all -> FAIL.
    with_cycle_no_evidence = {**base, "fix_cycle_id": "FC-1"}
    text_missing = f"```dv-harness-evidence:regression_selection_completeness_gate\n{json.dumps(with_cycle_no_evidence)}\n```\n"
    verdict1, reasons1 = evaluate_stage_evidence(ROOT, "REGRESSION_SELECT", text_missing)
    assert verdict1 == "GATE_FAIL", reasons1
    assert any("SINGLE_TEST_REVERIFY_MISSING_BEFORE_FULL_REGRESSION" in str(r) for r in reasons1)

    # fix_cycle_id set, evidence present but wrong shape (target didn't
    # actually FAIL before / PASS after) -> still FAIL, same reason.
    with_cycle_wrong_shape = {**base, "fix_cycle_id": "FC-1",
                               "single_test_reverify_evidence": {
                                   "target_pre_fix_result": "PASS", "target_post_fix_result": "PASS"}}
    text_wrong = f"```dv-harness-evidence:regression_selection_completeness_gate\n{json.dumps(with_cycle_wrong_shape)}\n```\n"
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "REGRESSION_SELECT", text_wrong)
    assert verdict2 == "GATE_FAIL", reasons2
    assert any("SINGLE_TEST_REVERIFY_MISSING_BEFORE_FULL_REGRESSION" in str(r) for r in reasons2)

    # fix_cycle_id set with a real FAIL-before/PASS-after reverify block -> PASS.
    with_cycle_ok = {**base, "fix_cycle_id": "FC-1",
                      "single_test_reverify_evidence": {
                          "target_pre_fix_result": "FAIL", "target_post_fix_result": "PASS"}}
    text_ok = f"```dv-harness-evidence:regression_selection_completeness_gate\n{json.dumps(with_cycle_ok)}\n```\n"
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "REGRESSION_SELECT", text_ok)
    assert verdict3 == "PASS", reasons3


def test_regression_submission_enforces_agent_isolation_and_wave_pa_coverage_defaults():
    # tools/verification_flow/regression_submission_policy_gate.py
    # CLAUDE.md Core Operating Rules "One submitted LSF job = one isolated Job
    # Agent context" and the WAVE=0/PA=0/Coverage=OFF regression default, both
    # previously unenforced by any gate anywhere in the pipeline.
    verdict, reasons = evaluate_stage_evidence(ROOT, "REGRESSION", "nothing")
    assert verdict == "MISSING_EVIDENCE", reasons

    shared_agent = {"jobs": [
        {"job_id": "j1", "agent_id": "a1", "wave": 0, "pa": 0, "coverage": False},
        {"job_id": "j2", "agent_id": "a1", "wave": 0, "pa": 0, "coverage": False}]}
    text_fail = f"```dv-harness-evidence:regression_submission_policy_gate\n{json.dumps(shared_agent)}\n```\n"
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "REGRESSION", text_fail)
    assert verdict2 == "GATE_FAIL", reasons2
    assert any("AGENT_CONTEXT_NOT_ISOLATED" in str(r) for r in reasons2)

    wave_violation = {"jobs": [{"job_id": "j1", "agent_id": "a1", "wave": 1, "pa": 0, "coverage": False}]}
    text_fail2 = f"```dv-harness-evidence:regression_submission_policy_gate\n{json.dumps(wave_violation)}\n```\n"
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "REGRESSION", text_fail2)
    assert verdict3 == "GATE_FAIL", reasons3
    assert any("WAVE_DEFAULT_VIOLATION" in str(r) for r in reasons3)

    defaults_ok = {"jobs": [
        {"job_id": "j1", "agent_id": "a1", "wave": 0, "pa": 0, "coverage": False},
        {"job_id": "j2", "agent_id": "a2", "wave": 0, "pa": 0, "coverage": False}]}
    text_pass = f"```dv-harness-evidence:regression_submission_policy_gate\n{json.dumps(defaults_ok)}\n```\n"
    verdict4, reasons4 = evaluate_stage_evidence(ROOT, "REGRESSION", text_pass)
    assert verdict4 == "PASS", reasons4


def _run_regression_submission_gate_with_cwd(cwd, payload):
    # Like _run_gate_script above, but with an explicit cwd -- exercises the
    # exact same trust boundary run_gate() gives every gate script
    # (subprocess.run(..., cwd=str(root))) so a fabricated .dv-harness
    # fixture under a throwaway tmp dir can stand in for the real project's
    # blackboard/lsf-jobs state without ever touching it. The gate script
    # itself still lives under the real ROOT/tools/verification_flow/, only
    # its reads of .dv-harness/... are relative to `cwd`.
    import subprocess, sys
    infile_dir = Path(tempfile.mkdtemp())
    try:
        infile = infile_dir / "in.json"
        infile.write_text(json.dumps(payload), encoding="utf-8")
        script = ROOT / "tools" / "verification_flow" / "regression_submission_policy_gate.py"
        r = subprocess.run(
            [sys.executable, str(script), "--jobs", str(infile)],
            cwd=str(cwd), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        shutil.rmtree(infile_dir, ignore_errors=True)


def test_regression_submission_wave_override_requires_real_prior_failure_link():
    # BUG FIX regression test (regression-submission-override-linkage-gap,
    # 2026-09-02): override_reason alone used to be enough to bypass the
    # WAVE/PA/Coverage default -- ANY non-empty free-text string, with zero
    # correlation to a real prior failure. Now a non-empty override_reason
    # also requires "prior_failure_ref" (testcase_id + a finding_id/job_id
    # that this gate resolves against real on-disk evidence).
    tmp = Path(tempfile.mkdtemp())
    try:
        # override_reason present but no prior_failure_ref at all -> FAIL.
        override_no_ref = {"jobs": [{"job_id": "j1", "agent_id": "a1", "wave": 1, "pa": 0,
                                      "coverage": False,
                                      "override_reason": "representative testcase needs signal evidence"}]}
        rc, out = _run_regression_submission_gate_with_cwd(tmp, override_no_ref)
        assert rc != 0 and out["reason"] == "WAVE_OVERRIDE_NOT_LINKED_TO_FAILURE"

        # prior_failure_ref present but pointing at nothing real (no
        # blackboard finding, no job-state record on disk) -> still FAIL.
        override_fake_ref = {"jobs": [{"job_id": "j1", "agent_id": "a1", "wave": 1, "pa": 0,
                                        "coverage": False,
                                        "override_reason": "representative testcase needs signal evidence",
                                        "prior_failure_ref": {"testcase_id": "usb_bulkin_test",
                                                               "finding_id": "does-not-exist"}}]}
        rc2, out2 = _run_regression_submission_gate_with_cwd(tmp, override_fake_ref)
        assert rc2 != 0 and out2["reason"] == "WAVE_OVERRIDE_NOT_LINKED_TO_FAILURE"

        # A real blackboard finding (REGRESSION_MONITOR's own findings
        # registry -- dv_harness/blackboard.py's Blackboard.upsert_finding)
        # makes finding_id resolve -> PASS.
        bb_dir = tmp / ".dv-harness" / "blackboard"
        bb_dir.mkdir(parents=True)
        (bb_dir / "findings.json").write_text(json.dumps({
            "topic": "findings",
            "value": {"items": {"F-usb-bulkin-mismatch": {"status": "open"}}},
        }), encoding="utf-8")
        override_real_finding = {"jobs": [{"job_id": "j1", "agent_id": "a1", "wave": 1, "pa": 0,
                                            "coverage": False,
                                            "override_reason": "representative testcase needs signal evidence",
                                            "prior_failure_ref": {"testcase_id": "usb_bulkin_test",
                                                                   "finding_id": "F-usb-bulkin-mismatch"}}]}
        rc3, out3 = _run_regression_submission_gate_with_cwd(tmp, override_real_finding)
        assert rc3 == 0 and out3["status"] == "PASS"

        # A real prior JobState record showing an actual failure
        # (dv_harness/lsf_client.py, one file per submitted LSF job) makes
        # job_id resolve -> also PASS.
        jobs_dir = tmp / ".dv-harness" / "lsf" / "jobs"
        jobs_dir.mkdir(parents=True)
        (jobs_dir / "998877.json").write_text(json.dumps({
            "job_id": 998877, "sim_status": "FAIL", "uvm_error_count": 1,
        }), encoding="utf-8")
        override_real_job = {"jobs": [{"job_id": "j2", "agent_id": "a2", "wave": 0, "pa": 1,
                                        "coverage": False,
                                        "override_reason": "prior LSF failure needs PA rerun",
                                        "prior_failure_ref": {"testcase_id": "usb_bulkin_test",
                                                               "job_id": "998877"}}]}
        rc4, out4 = _run_regression_submission_gate_with_cwd(tmp, override_real_job)
        assert rc4 == 0 and out4["status"] == "PASS"

        # A job-state record that exists but never actually failed must not
        # count as a real prior failure -- still FAIL.
        (jobs_dir / "111222.json").write_text(json.dumps({
            "job_id": 111222, "sim_status": "PASS", "uvm_error_count": 0,
        }), encoding="utf-8")
        override_passing_job = {"jobs": [{"job_id": "j3", "agent_id": "a3", "wave": 1, "pa": 0,
                                           "coverage": False,
                                           "override_reason": "unrelated claim",
                                           "prior_failure_ref": {"testcase_id": "usb_bulkin_test",
                                                                  "job_id": "111222"}}]}
        rc5, out5 = _run_regression_submission_gate_with_cwd(tmp, override_passing_job)
        assert rc5 != 0 and out5["reason"] == "WAVE_OVERRIDE_NOT_LINKED_TO_FAILURE"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_fix_regression_non_regression_gate_with_cwd(cwd, payload):
    # Same cwd-relative pattern as _run_regression_submission_gate_with_cwd
    # above -- exercises fix_regression_non_regression_gate.py's real read of
    # .dv-harness/lsf/jobs/<job_id>.json against a throwaway tmp fixture.
    import subprocess, sys
    infile_dir = Path(tempfile.mkdtemp())
    try:
        infile = infile_dir / "in.json"
        infile.write_text(json.dumps(payload), encoding="utf-8")
        script = ROOT / "tools" / "verification_flow" / "fix_regression_non_regression_gate.py"
        r = subprocess.run(
            [sys.executable, str(script), "--closure", str(infile)],
            cwd=str(cwd), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        shutil.rmtree(infile_dir)


def test_fix_regression_non_regression_gate_cross_checks_job_registry():
    # tools/verification_flow/fix_regression_non_regression_gate.py
    # RE_AUDIT-precondition audit follow-up (2026-09-02): target_pre_fix_result/
    # target_post_fix_result used to be pure self-attested strings, never
    # cross-checked against REGRESSION_MONITOR's real per-job record
    # (.dv-harness/lsf/jobs/<job_id>.json, dv_harness/lsf_client.py JobState,
    # sim_status advanced by dv_harness/regression_reporter.py's real analysis
    # cycle). target_pre_fix_job_id/target_post_fix_job_id are optional: when
    # absent, behavior is unchanged (self-attestation only, still PASS).
    tmp = Path(tempfile.mkdtemp())
    try:
        base = {"target_pre_fix_result": "FAIL", "target_post_fix_result": "PASS",
                "replay_equivalent": True, "critical_non_regression_tests": [],
                "fix_commit_hash": "c1", "rerun_bundle_hash": "b1"}

        # No job_id refs at all -> unchanged self-attestation-only behavior, PASS.
        rc0, out0 = _run_fix_regression_non_regression_gate_with_cwd(tmp, base)
        assert rc0 == 0 and out0["status"] == "PASS", out0

        # job_id refs supplied but no such JobState record exists on disk -> FAIL.
        no_record = {**base, "target_pre_fix_job_id": "555001", "target_post_fix_job_id": "555002"}
        rc1, out1 = _run_fix_regression_non_regression_gate_with_cwd(tmp, no_record)
        assert rc1 != 0 and out1["reason"] == "TARGET_RESULT_JOB_REF_UNRESOLVED", out1

        jobs_dir = tmp / ".dv-harness" / "lsf" / "jobs"
        jobs_dir.mkdir(parents=True)
        # Real prior job really did FAIL, real post-fix job really did PASS,
        # both referencing the same testcase pattern -> claims match, PASS.
        (jobs_dir / "555001.json").write_text(json.dumps({
            "job_id": 555001, "sim_status": "FAIL", "pattern": "usb_bulkin_test",
        }), encoding="utf-8")
        (jobs_dir / "555002.json").write_text(json.dumps({
            "job_id": 555002, "sim_status": "PASS", "pattern": "usb_bulkin_test",
        }), encoding="utf-8")
        matching = {**base, "target_pre_fix_job_id": "555001", "target_post_fix_job_id": "555002",
                    "target_testcase_id": "usb_bulkin_test"}
        rc2, out2 = _run_fix_regression_non_regression_gate_with_cwd(tmp, matching)
        assert rc2 == 0 and out2["status"] == "PASS", out2

        # Claimed PASS but the real recorded post-fix job actually still shows
        # FAIL -- the agent's self-attestation disagrees with real ground
        # truth -> FAIL TARGET_RESULT_CLAIM_MISMATCH.
        (jobs_dir / "555003.json").write_text(json.dumps({
            "job_id": 555003, "sim_status": "FAIL", "pattern": "usb_bulkin_test",
        }), encoding="utf-8")
        mismatched = {**base, "target_pre_fix_job_id": "555001", "target_post_fix_job_id": "555003"}
        rc3, out3 = _run_fix_regression_non_regression_gate_with_cwd(tmp, mismatched)
        assert rc3 != 0 and out3["reason"] == "TARGET_RESULT_CLAIM_MISMATCH", out3

        # Real job resolves and its sim_status matches, but it was actually a
        # run of a DIFFERENT testcase -- claimed target_testcase_id disagrees
        # with the real job's recorded pattern -> still FAIL, same reason.
        (jobs_dir / "555004.json").write_text(json.dumps({
            "job_id": 555004, "sim_status": "PASS", "pattern": "usb_bulkout_test",
        }), encoding="utf-8")
        wrong_testcase = {**base, "target_pre_fix_job_id": "555001", "target_post_fix_job_id": "555004",
                           "target_testcase_id": "usb_bulkin_test"}
        rc4, out4 = _run_fix_regression_non_regression_gate_with_cwd(tmp, wrong_testcase)
        assert rc4 != 0 and out4["reason"] == "TARGET_RESULT_CLAIM_MISMATCH", out4
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_server_sync_requires_head_and_submodule_sha_identity():
    # tools/verification_flow/server_sync_identity_gate.py
    verdict, reasons = evaluate_stage_evidence(ROOT, "SERVER_SYNC", "nothing")
    assert verdict == "MISSING_EVIDENCE", reasons

    mismatch = {"expected_sha": "abc123", "server_head_sha": "def456"}
    text_fail = f"```dv-harness-evidence:server_sync_identity_gate\n{json.dumps(mismatch)}\n```\n"
    verdict2, reasons2 = evaluate_stage_evidence(ROOT, "SERVER_SYNC", text_fail)
    assert verdict2 == "GATE_FAIL", reasons2
    assert any("SERVER_HEAD_SHA_MISMATCH" in str(r) for r in reasons2)

    submodule_mismatch = {"expected_sha": "abc123", "server_head_sha": "abc123",
                           "submodules": [{"name": "vip_lib", "expected_sha": "s1", "server_sha": "s2"}]}
    text_fail2 = f"```dv-harness-evidence:server_sync_identity_gate\n{json.dumps(submodule_mismatch)}\n```\n"
    verdict3, reasons3 = evaluate_stage_evidence(ROOT, "SERVER_SYNC", text_fail2)
    assert verdict3 == "GATE_FAIL", reasons3
    assert any("SUBMODULE_SHA_MISMATCH" in str(r) for r in reasons3)

    identity_ok = {"expected_sha": "abc123", "server_head_sha": "abc123",
                   "submodules": [{"name": "vip_lib", "expected_sha": "s1", "server_sha": "s1"}]}
    text_pass = f"```dv-harness-evidence:server_sync_identity_gate\n{json.dumps(identity_ok)}\n```\n"
    verdict4, reasons4 = evaluate_stage_evidence(ROOT, "SERVER_SYNC", text_pass)
    assert verdict4 == "PASS", reasons4


# --- Harness self-audit (dv_harness/self_audit.py) --------------------------
# Runs the 22 self-audit gates against THIS repo's own real, current state --
# not constructed evidence. Every assertion below reflects a result
# independently confirmed by direct script execution during the self-audit
# feature's design/build (see self_audit.py's module docstring): 2 ROOT_GATES
# genuinely FAIL against this real repo today (skill frontmatter gaps,
# missing pytest references), 1 more (gate_manifest_registry_consistency_gate)
# now also genuinely fails (newly-wired gates not yet reflected in
# verification_flow_v13.json), and of the 16 JSON_GATES only
# platform_capability_completeness_gate has a real matching source file.
def test_self_audit_all_gate_ids_are_real_registered_scripts():
    # Every one of the 23 ids must resolve to an actual file under
    # tools/verification_flow/ -- the self-audit battery is not allowed to
    # silently drift from the scripts it claims to run.
    assert len(self_audit.ALL_GATE_IDS) == 23
    for gate_id in self_audit.ROOT_GATES:
        assert (ROOT / self_audit.TOOLS_DIR / f"{gate_id}.py").exists(), gate_id
    for gate_id, (script_name, _flag) in self_audit.JSON_GATES.items():
        assert (ROOT / self_audit.TOOLS_DIR / script_name).exists(), gate_id


def test_self_audit_against_real_repo_reports_real_current_findings():
    result = self_audit.run_self_audit(ROOT)
    assert result["unknown_gate_ids"] == []
    assert result["summary"]["total"] == 23
    by_id = {g["gate_id"]: g for g in result["gates"]}

    # BUG FIX (2026-08-28, gui-cli-completeness-audit): agent_skill_binding_gate
    # used to FAIL on 31 skill files whose real frontmatter was preceded by an
    # HTML NOTICE comment, so it never started at byte 0 -- fixed by moving
    # the NOTICE after the frontmatter's closing "---" in every one of those
    # files (content unchanged, just reordered). Confirmed PASS by direct
    # execution after the fix.
    assert by_id["agent_skill_binding_gate"]["status"] == "PASS"
    assert by_id["agent_skill_binding_gate"]["mode"] == "ROOT_SCAN"
    # BUG FIX (2026-08-28, plan-gate-test-coverage design pass): this used to
    # be a genuine, still-open FAIL (~150 gates with no pytest reference by
    # name) -- closed by dv_harness_tests/test_hard_gate_script_smoke.py's
    # literal ALL_GATE_TOOL_FILES list + parametrized --help smoke test,
    # which gives every registered gate's tool filename a real textual
    # occurrence under a test_*.py file (this gate's exact matching rule).
    assert by_id["hard_gate_registry_audit"]["status"] == "PASS"

    # Real, currently-PASSing ROOT_SCAN gates.
    assert by_id["schema_reference_integrity_gate"]["status"] == "PASS"
    assert by_id["test_collection_health_gate"]["status"] == "PASS"
    assert by_id["workflow_registry_orphan_gate"]["status"] == "PASS"

    # The one JSON_GATES entry with a real matching source file
    # (.dv-harness/workflow/platform_capability_catalog.json) -- SOURCED PASS
    # against genuine current state, not a constructed payload.
    assert by_id["platform_capability_completeness_gate"]["status"] == "PASS"
    assert by_id["platform_capability_completeness_gate"]["mode"] == "SOURCED"

    # Every other JSON_GATES entry has no real harness-maintained source file
    # today -- reported honestly, never a fabricated PASS.
    for gate_id in self_audit.JSON_GATES:
        if gate_id == "platform_capability_completeness_gate":
            continue
        assert by_id[gate_id]["status"] == "NO_SOURCE_DATA", gate_id
        assert by_id[gate_id]["mode"] == "SOURCED"

    s = result["summary"]
    assert s["pass"] + s["fail"] + s["no_source_data"] + s["tool_missing"] == s["total"]
    assert s["pass"] == sum(1 for g in result["gates"] if g["status"] == "PASS")
    # Both previously-real FAILs are now fixed (see notes above) -- self-audit
    # is fully clean against the real current repo: 7 PASS / 0 FAIL / 16 NO_SOURCE_DATA.
    assert s["fail"] == 0
    assert s["pass"] == 7
    assert s["no_source_data"] == 16


def test_self_audit_smoke_mode_proves_scripts_work_without_faking_real_state():
    result = self_audit.run_self_audit(ROOT, smoke=True)
    by_id = {g["gate_id"]: g for g in result["gates"]}

    # The one genuinely-sourced gate is NOT smoke-tested even with smoke=True
    # -- real state takes precedence over a constructed payload.
    assert by_id["platform_capability_completeness_gate"]["status"] == "PASS"
    assert by_id["platform_capability_completeness_gate"]["mode"] == "SOURCED"

    # Every other JSON_GATES entry (no real source) now runs its constructed
    # SMOKE_PAYLOADS entry and PASSes -- a script health-check, distinct from
    # a real PASS/FAIL/NO_SOURCE_DATA verdict on current harness state.
    smoked = [g for g in self_audit.JSON_GATES if g != "platform_capability_completeness_gate"]
    assert smoked, "expected at least one non-sourced JSON gate"
    for gate_id in smoked:
        assert by_id[gate_id]["status"] == "SCRIPT_SMOKE_PASS", (gate_id, by_id[gate_id])
        assert by_id[gate_id]["mode"] == "SMOKE"

    assert result["summary"]["smoke_pass"] == len(smoked)
    assert result["summary"]["no_source_data"] == 0
    # ROOT_SCAN gates are unaffected by smoke=True.
    assert by_id["agent_skill_binding_gate"]["status"] == "PASS"  # see fix note above
    assert by_id["schema_reference_integrity_gate"]["status"] == "PASS"


def test_self_audit_smoke_payload_regresses_to_gate_own_fail_branch():
    # A deliberately-broken smoke payload (real gate script, DUPLICATE_COMMAND_ID)
    # must still surface SCRIPT_SMOKE_FAIL, proving the smoke path does not
    # silently launder a genuine script failure into a pass.
    broken = dict(self_audit.SMOKE_PAYLOADS["command_catalog_lifecycle_gate"])
    broken["commands"] = broken["commands"] + broken["commands"]  # duplicate command_id
    orig = self_audit.SMOKE_PAYLOADS["command_catalog_lifecycle_gate"]
    self_audit.SMOKE_PAYLOADS["command_catalog_lifecycle_gate"] = broken
    try:
        result = self_audit.run_self_audit(ROOT, gate_ids=["command_catalog_lifecycle_gate"], smoke=True)
    finally:
        self_audit.SMOKE_PAYLOADS["command_catalog_lifecycle_gate"] = orig
    g = result["gates"][0]
    assert g["status"] == "SCRIPT_SMOKE_FAIL"
    assert g["detail"].get("reason") == "DUPLICATE_COMMAND_ID"
    assert result["summary"]["smoke_fail"] == 1


def test_self_audit_gate_id_filtering_and_unknown_ids_reported_not_run():
    result = self_audit.run_self_audit(
        ROOT, gate_ids=["schema_reference_integrity_gate", "not_a_real_gate"])
    assert result["unknown_gate_ids"] == ["not_a_real_gate"]
    assert result["summary"]["total"] == 1
    assert result["gates"][0]["gate_id"] == "schema_reference_integrity_gate"
    assert result["gates"][0]["status"] == "PASS"


def test_self_audit_reports_tool_missing_when_scripts_absent():
    tmp = Path(tempfile.mkdtemp())
    try:
        # No tools/verification_flow/ under tmp at all -- every gate must
        # report GATE_TOOL_MISSING, not crash or silently pass.
        result = self_audit.run_self_audit(
            tmp, gate_ids=["schema_reference_integrity_gate", "platform_capability_completeness_gate"])
        by_id = {g["gate_id"]: g for g in result["gates"]}
        assert by_id["schema_reference_integrity_gate"]["status"] == "GATE_TOOL_MISSING"
        assert by_id["platform_capability_completeness_gate"]["status"] == "GATE_TOOL_MISSING"
        assert result["summary"]["tool_missing"] == 2
    finally:
        shutil.rmtree(tmp)


def test_self_audit_cli_subcommand_against_real_repo():
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", ".", "self-audit", "--all"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )
    # Real repo self-audit is now fully clean (see test above) -> exit 0, not
    # a crash and not a false FAIL either.
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["summary"]["total"] == 23
    by_id = {g["gate_id"]: g for g in data["gates"]}
    assert by_id["agent_skill_binding_gate"]["status"] == "PASS"  # see fix note above
    assert by_id["hard_gate_registry_audit"]["status"] == "PASS"  # see fix note above
    assert by_id["platform_capability_completeness_gate"]["status"] == "PASS"


def test_self_audit_cli_gate_filter_and_smoke_flags():
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", ".", "self-audit",
         "--gate", "command_catalog_lifecycle_gate", "--smoke"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, r.stderr  # this one gate SMOKE_PASSes, nothing else ran
    data = json.loads(r.stdout)
    assert data["summary"]["total"] == 1


def test_branch_topology_gate_single_dut_port_skips_arbitration_check():
    # dut_port_count<=1 -> no concurrent DUT-side branches -> no arbitration
    # model required regardless of protocol.
    rc, out = _run_gate_script(
        "verification_flow/branch_topology_gate.py", "--topology",
        {"dut_port_count": 1, "vip_port_count": 1,
         "branches": ["block", "branch_fw", "branch_a0", "branch_b0"],
         "branch_fw_interrupt_driven": True, "protocol": "AMBA4-AXI"},
    )
    assert rc == 0 and out["status"] == "PASS"


def test_branch_topology_gate_non_amba_multi_port_skips_arbitration_check():
    # Multiple DUT-side branches but a non-AMBA protocol -> the bus-contention
    # concern (Policy 2: APB/AXI transactions arbitrated across block/branch_a*)
    # does not apply.
    rc, out = _run_gate_script(
        "verification_flow/branch_topology_gate.py", "--topology",
        {"dut_port_count": 2, "vip_port_count": 2,
         "branches": ["block", "branch_fw", "branch_a0", "branch_a1", "branch_b0", "branch_b1"],
         "branch_fw_interrupt_driven": True, "protocol": "USB3.2"},
    )
    assert rc == 0 and out["status"] == "PASS"


def test_branch_topology_gate_amba_multi_port_requires_arbitration_model():
    # BUG FIX regression (audit-impact-arbitration-naming, Policy 2): block +
    # branch_a0 + branch_a1 running concurrently on a shared AMBA bus must
    # declare a cross-branch bus contention/arbitration model, else nothing
    # stops an agent from generating each branch as if it had silent,
    # uncontended, exclusive bus access.
    rc, out = _run_gate_script(
        "verification_flow/branch_topology_gate.py", "--topology",
        {"dut_port_count": 2, "vip_port_count": 2,
         "branches": ["block", "branch_fw", "branch_a0", "branch_a1", "branch_b0", "branch_b1"],
         "branch_fw_interrupt_driven": True, "protocol": "AMBA4-AXI"},
    )
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "MULTI_BRANCH_BUS_ARBITRATION_UNMODELED"


def test_branch_topology_gate_amba_multi_port_passes_with_arbitration_model():
    rc, out = _run_gate_script(
        "verification_flow/branch_topology_gate.py", "--topology",
        {"dut_port_count": 2, "vip_port_count": 2,
         "branches": ["block", "branch_fw", "branch_a0", "branch_a1", "branch_b0", "branch_b1"],
         "branch_fw_interrupt_driven": True, "protocol": "AMBA4-AXI",
         "cross_branch_bus_model": {
             "shared_resources": ["axi_interconnect_m0"],
             "arbitration_policy": "fixed_priority: block > branch_a0 > branch_a1",
         }},
    )
    assert rc == 0 and out["status"] == "PASS"


def test_manual_lookup_gate_block_edit_is_a_no_op():
    rc, out = _run_gate_script(
        "verification_flow/manual_lookup_before_edit_gate.py", "--edit",
        {"branch": "block"},
    )
    assert rc == 0 and out["status"] == "PASS"


def test_manual_lookup_gate_vip_side_requires_all_four_reference_sources():
    rc, out = _run_gate_script(
        "verification_flow/manual_lookup_before_edit_gate.py", "--edit",
        {"branch": "branch_b0", "vip_examples_checked": True, "vip_manual_checked": True},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "VIP_EDIT_WITHOUT_REFERENCE_LOOKUP"
    assert set(out["missing"]) == {"vip_source_checked", "vip_class_reference_checked"}


# Real, stable file+quote used across these tests as a valid evidence ref --
# path is relative to project root, matching run_gate()'s subprocess cwd.
_REAL_REF = {"path": "CLAUDE.md", "quote": "Evidence Truth Rule"}


def test_manual_lookup_gate_vip_side_passes_with_all_four_sources():
    rc, out = _run_gate_script(
        "verification_flow/manual_lookup_before_edit_gate.py", "--edit",
        {"branch": "branch_b1", "vip_examples_checked": True, "vip_manual_checked": True,
         "vip_source_checked": True, "vip_class_reference_checked": True,
         "vip_evidence_refs": [_REAL_REF]},
    )
    assert rc == 0 and out["status"] == "PASS"


def test_manual_lookup_gate_vip_side_rejects_evidence_ref_with_fabricated_file():
    # BUG regression: a claim naming a file that doesn't exist must FAIL, not
    # be trusted just because the 4 boolean flags are all true.
    rc, out = _run_gate_script(
        "verification_flow/manual_lookup_before_edit_gate.py", "--edit",
        {"branch": "branch_b1", "vip_examples_checked": True, "vip_manual_checked": True,
         "vip_source_checked": True, "vip_class_reference_checked": True,
         "vip_evidence_refs": [{"path": "no_such_file_anywhere.sv", "quote": "x"}]},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "EVIDENCE_FILE_NOT_FOUND"


def test_manual_lookup_gate_vip_side_rejects_evidence_ref_with_fabricated_quote():
    # A real file, but a quote that never appears in it -- a real file name
    # paired with fabricated content must FAIL too.
    rc, out = _run_gate_script(
        "verification_flow/manual_lookup_before_edit_gate.py", "--edit",
        {"branch": "branch_b1", "vip_examples_checked": True, "vip_manual_checked": True,
         "vip_source_checked": True, "vip_class_reference_checked": True,
         "vip_evidence_refs": [{"path": "CLAUDE.md", "quote": "this exact sentence does not exist in CLAUDE.md"}]},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "EVIDENCE_QUOTE_NOT_FOUND_IN_FILE"


def test_manual_lookup_gate_vip_side_rejects_missing_evidence_refs():
    # All 4 booleans true but no evidence_refs at all -- must still FAIL;
    # booleans alone are never sufficient.
    rc, out = _run_gate_script(
        "verification_flow/manual_lookup_before_edit_gate.py", "--edit",
        {"branch": "branch_b1", "vip_examples_checked": True, "vip_manual_checked": True,
         "vip_source_checked": True, "vip_class_reference_checked": True},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "EVIDENCE_REFS_MISSING_OR_EMPTY"


def test_manual_lookup_gate_dut_side_requires_rtl_checked():
    rc, out = _run_gate_script(
        "verification_flow/manual_lookup_before_edit_gate.py", "--edit",
        {"branch": "branch_fw", "programming_guide_checked": True},
    )
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "DUT_SIDE_EDIT_WITHOUT_DUT_REFERENCE_LOOKUP"


def test_manual_lookup_gate_dut_side_requires_rtl_evidence_refs():
    rc, out = _run_gate_script(
        "verification_flow/manual_lookup_before_edit_gate.py", "--edit",
        {"branch": "branch_a1", "dut_rtl_checked": True, "phy_documents_checked": True},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "EVIDENCE_REFS_MISSING_OR_EMPTY"


def test_manual_lookup_gate_dut_side_requires_phy_or_programming_guide_or_escape():
    rc, out = _run_gate_script(
        "verification_flow/manual_lookup_before_edit_gate.py", "--edit",
        {"branch": "branch_a1", "dut_rtl_checked": True, "dut_rtl_evidence_refs": [_REAL_REF]},
    )
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "DUT_SIDE_EDIT_WITHOUT_PHY_OR_PROGRAMMING_GUIDE_LOOKUP"


def test_manual_lookup_gate_dut_side_passes_with_explicit_not_applicable_reason():
    rc, out = _run_gate_script(
        "verification_flow/manual_lookup_before_edit_gate.py", "--edit",
        {"branch": "branch_a0", "dut_rtl_checked": True, "dut_rtl_evidence_refs": [_REAL_REF],
         "phy_programming_guide_not_applicable_reason": "register-name-only rename, no PHY/behavior change"},
    )
    assert rc == 0 and out["status"] == "PASS"


def test_manual_lookup_gate_dut_side_passes_with_rtl_plus_one_source():
    rc, out = _run_gate_script(
        "verification_flow/manual_lookup_before_edit_gate.py", "--edit",
        {"branch": "branch_fw", "dut_rtl_checked": True, "dut_rtl_evidence_refs": [_REAL_REF],
         "phy_documents_checked": True},
    )
    assert rc == 0 and out["status"] == "PASS"


def test_manual_lookup_gate_vip_side_rejects_forbidden_reference_tree_citation():
    # Regression test for the 2026-08-31 final-review Critical finding: B1's
    # forbidden-tree barrier used to live ONLY in protocol_isolation_gate.py's
    # own, agent-optional evidence block -- an agent could cite
    # USB_UVM_Handoff content right in THIS gate's real vip_evidence_refs
    # (the block it is actually forced to supply) and still pass, as long as
    # it left the separate isolation-gate block empty. This must now FAIL
    # here, directly, independent of protocol_isolation_gate.py.
    rc, out = _run_gate_script(
        "verification_flow/manual_lookup_before_edit_gate.py", "--edit",
        {"branch": "branch_b1", "vip_examples_checked": True, "vip_manual_checked": True,
         "vip_source_checked": True, "vip_class_reference_checked": True,
         "vip_evidence_refs": [{"path": "USB_UVM_Handoff/some_file.sv", "quote": "x"}]},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "REFERENCE_TREE_CITATION_FORBIDDEN"
    assert out["forbidden_tree"] == "USB_UVM_Handoff"


def test_manual_lookup_gate_dut_side_rejects_forbidden_reference_tree_citation():
    # Same Critical-finding regression, DUT side (dut_rtl_evidence_refs).
    rc, out = _run_gate_script(
        "verification_flow/manual_lookup_before_edit_gate.py", "--edit",
        {"branch": "branch_a1", "dut_rtl_checked": True,
         "dut_rtl_evidence_refs": [{"path": "USB_UVM_Handoff/some_dut_file.sv", "quote": "x"}]},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "REFERENCE_TREE_CITATION_FORBIDDEN"
    assert out["forbidden_tree"] == "USB_UVM_Handoff"


def test_protocol_isolation_gate_blocks_forbidden_reference_citation():
    rc, out = _run_gate_script(
        "verification_flow/protocol_isolation_gate.py", "--edit",
        {"branch": "branch_b0",
         "vip_evidence_refs": [{"path": "USB_UVM_Handoff/some_file.sv", "quote": "x"}]},
    )
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "REFERENCE_TREE_CITATION_FORBIDDEN"


def test_protocol_isolation_gate_allows_real_source_citation():
    rc, out = _run_gate_script(
        "verification_flow/protocol_isolation_gate.py", "--edit",
        {"branch": "branch_b1", "vip_evidence_refs": [_REAL_REF]},
    )
    assert rc == 0 and out["status"] == "PASS"


def _write_rtl_protection_config(project_root, protected_paths):
    dv_dir = project_root / ".dv-harness"
    dv_dir.mkdir(parents=True, exist_ok=True)
    (dv_dir / "config.json").write_text(
        json.dumps({"rtl_protection": {"protected_paths": [str(p) for p in protected_paths]}}),
        encoding="utf-8",
    )


def test_rtl_write_scope_guard_gate_blocks_dut_root_touch(tmp_path):
    # The one confirmed real gap this gate closes (2026-09-02): the only
    # thing that ever stopped the harness writing DUT/VIP RTL was a
    # hand-added .claude/settings.json Edit-tool deny rule -- nothing in
    # dv_harness itself checked what an IMPLEMENT edit actually touched.
    dut_root = tmp_path / "DUT"
    _write_rtl_protection_config(tmp_path, [dut_root, tmp_path / "VIP"])
    rc, out = _run_gate_script_2flag(
        "verification_flow/rtl_write_scope_guard_gate.py", "--edit",
        {"touched_paths": [str(dut_root / "RTLCAT" / "top.v")]},
        "--root", str(tmp_path),
    )
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "RTL_WRITE_SCOPE_VIOLATION"
    assert out["violations"][0]["path"] == str(dut_root / "RTLCAT" / "top.v")


def test_rtl_write_scope_guard_gate_allows_uvm_touch_outside_protected_roots(tmp_path):
    _write_rtl_protection_config(tmp_path, [tmp_path / "DUT", tmp_path / "VIP"])
    rc, out = _run_gate_script_2flag(
        "verification_flow/rtl_write_scope_guard_gate.py", "--edit",
        {"touched_paths": [str(tmp_path / "uvm" / "tb" / "scoreboard.sv")]},
        "--root", str(tmp_path),
    )
    assert rc == 0 and out["status"] == "PASS"


def test_rtl_write_scope_guard_gate_honest_pass_when_unconfigured(tmp_path):
    # No rtl_protection.protected_paths declared for this project yet -- an
    # honest no-op PASS (never a fabricated block), matching the gate's own
    # module docstring on what still requires real config to bite.
    _write_rtl_protection_config(tmp_path, [])
    rc, out = _run_gate_script_2flag(
        "verification_flow/rtl_write_scope_guard_gate.py", "--edit",
        {"touched_paths": [str(tmp_path / "DUT" / "RTLCAT" / "top.v")]},
        "--root", str(tmp_path),
    )
    assert rc == 0 and out["status"] == "PASS" and out["reason"] == "NO_PROTECTED_PATHS_CONFIGURED"


def test_rtl_write_scope_guard_gate_requires_touched_paths_list(tmp_path):
    _write_rtl_protection_config(tmp_path, [tmp_path / "DUT"])
    rc, out = _run_gate_script_2flag(
        "verification_flow/rtl_write_scope_guard_gate.py", "--edit",
        {}, "--root", str(tmp_path),
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "TOUCHED_PATHS_MISSING_OR_INVALID"


def test_protocol_profile_binding_gate_requires_usb_profile_and_vip_lookup():
    rc, out = _run_gate_script(
        "verification_flow/protocol_profile_binding_gate.py", "--binding",
        {"protocols": [{"protocol": "usb", "profile_skills_consulted": []}]},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "PROFILE_SKILL_NOT_CONSULTED"


def test_protocol_profile_binding_gate_passes_when_fully_consulted():
    rc, out = _run_gate_script(
        "verification_flow/protocol_profile_binding_gate.py", "--binding",
        {"protocols": [{"protocol": "usb",
                        "profile_skills_consulted": ["USB/usb-profile", "USB/usb-vip-lookup"]}]},
    )
    assert rc == 0 and out["status"] == "PASS"


def test_pattern_registry_completeness_gate_passes_consistent_registry():
    rc, out = _run_gate_script(
        "verification_flow/pattern_registry_completeness_gate.py", "--registry",
        {"patterns": [
            {"name": "usb2_enum", "suite": "enumeration", "dir": "tb/patterns/enumeration"},
            {"name": "usb_dual_port", "suite": "transfer", "dir": "tb/patterns/transfer"},
         ],
         "suite_names": ["enumeration", "transfer"]},
    )
    assert rc == 0 and out["status"] == "PASS" and out["pattern_count"] == 2


def test_pattern_registry_completeness_gate_detects_duplicate_name():
    rc, out = _run_gate_script(
        "verification_flow/pattern_registry_completeness_gate.py", "--registry",
        {"patterns": [
            {"name": "usb2_enum", "suite": "enumeration", "dir": "tb/patterns/enumeration"},
            {"name": "usb2_enum", "suite": "link", "dir": "tb/patterns/link"},
         ],
         "suite_names": ["enumeration", "link"]},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "DUPLICATE_PATTERN_NAME"


def test_pattern_registry_completeness_gate_detects_missing_suite_or_dir():
    rc, out = _run_gate_script(
        "verification_flow/pattern_registry_completeness_gate.py", "--registry",
        {"patterns": [{"name": "usb2_enum", "dir": "tb/patterns/enumeration"}], "suite_names": []},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "MISSING_SUITE_DIR"


def test_pattern_registry_completeness_gate_detects_suite_names_drift():
    # BUG regression: a hand-edited/stale suite_names field (e.g. carried
    # forward from before a pattern was deleted) must FAIL, not silently pass.
    rc, out = _run_gate_script(
        "verification_flow/pattern_registry_completeness_gate.py", "--registry",
        {"patterns": [{"name": "usb2_enum", "suite": "enumeration", "dir": "tb/patterns/enumeration"}],
         "suite_names": ["enumeration", "power"]},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "SUITE_NAMES_DRIFT"
    assert out["recomputed"] == ["enumeration"] and out["stored"] == ["enumeration", "power"]


def test_pattern_registry_completeness_gate_detects_declared_suite_with_zero_patterns():
    rc, out = _run_gate_script(
        "verification_flow/pattern_registry_completeness_gate.py", "--registry",
        {"patterns": [{"name": "usb2_enum", "suite": "enumeration", "dir": "tb/patterns/enumeration"}],
         "suite_names": ["enumeration"], "declared_suites": ["enumeration", "power"]},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "SUITE_WITH_ZERO_PATTERNS"
    assert out["suites"] == ["power"]


def test_branch_topology_gate_amba_multi_port_incomplete_model_still_fails():
    # A dict with only one of the two required keys must still FAIL --
    # this guards against an agent satisfying the schema shape without
    # actually supplying a usable arbitration policy.
    rc, out = _run_gate_script(
        "verification_flow/branch_topology_gate.py", "--topology",
        {"dut_port_count": 2, "vip_port_count": 2,
         "branches": ["block", "branch_fw", "branch_a0", "branch_a1", "branch_b0", "branch_b1"],
         "branch_fw_interrupt_driven": True, "protocol": "AMBA4-AXI",
         "cross_branch_bus_model": {"shared_resources": ["axi_interconnect_m0"]}},
    )
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "MULTI_BRANCH_BUS_ARBITRATION_UNMODELED"


# --- Findings/project blackboard <-> state reconciliation (2026-08-29) -----
# Prior to this pass, state.findings_total/open/closed (models.py) were a
# dataclass field never assigned by ANY code path (confirmed by grepping the
# whole repo for an assignment site -- none existed outside the 0 default),
# while a SEPARATE blackboard "findings" topic existed and was overwritten
# wholesale by every INFRASTRUCTURE_AUDIT/FAILURE_RECOVERY PASS. The two
# could never have agreed, by construction. These tests prove the fix: the
# blackboard "findings" registry (Blackboard.upsert_finding/findings_counts)
# is now the one real source, and DVHarness.record_finding/close_finding/
# _sync_findings_state keep state.findings_* an exact mirror of it -- a
# finding opened/closed through the engine API is reflected in BOTH records
# identically, every time, with no way for them to diverge.

def test_findings_recorded_and_closed_via_engine_stay_in_sync_with_blackboard():
    tmp, h = _fresh_harness()
    try:
        assert (h.state.findings_total, h.state.findings_open, h.state.findings_closed) == (0, 0, 0)

        h.record_finding("F-COVERAGE-HOLE-1", title="uncovered DMA burst length corner case")
        assert h.state.findings_total == 1
        assert h.state.findings_open == 1
        assert h.state.findings_closed == 0
        # The blackboard registry itself agrees -- not just a re-derivation
        # of the same in-memory number.
        assert h.blackboard.findings_counts() == {
            "total": h.state.findings_total, "open": h.state.findings_open,
            "closed": h.state.findings_closed,
        }
        item = h.blackboard.read_findings()["items"]["F-COVERAGE-HOLE-1"]
        assert item["status"] == "open" and item["title"] == "uncovered DMA burst length corner case"

        h.record_finding("F-CHECKER-GAP-2", title="missing scoreboard check on port1")
        assert (h.state.findings_total, h.state.findings_open, h.state.findings_closed) == (2, 2, 0)

        # Close ONE finding via the engine's other verb -- the counts must
        # move together, in the SAME transaction, on both records.
        h.close_finding("F-COVERAGE-HOLE-1", resolution="added directed test + coverage bin")
        assert h.state.findings_total == 2
        assert h.state.findings_open == 1
        assert h.state.findings_closed == 1
        assert h.blackboard.findings_counts() == {
            "total": h.state.findings_total, "open": h.state.findings_open,
            "closed": h.state.findings_closed,
        }
        closed_item = h.blackboard.read_findings()["items"]["F-COVERAGE-HOLE-1"]
        assert closed_item["status"] == "closed"
        assert closed_item["resolution"] == "added directed test + coverage bin"
        # The still-open finding is untouched by the merge (proves
        # upsert_finding updates by finding_id, never wipes the registry).
        assert h.blackboard.read_findings()["items"]["F-CHECKER-GAP-2"]["status"] == "open"

        # Reloading a fresh DVHarness over the SAME root re-syncs state from
        # the blackboard on construction -- proving state is a derived view,
        # not an independently-persisted number that happened to match once.
        h2 = h.__class__(tmp)
        assert (h2.state.findings_total, h2.state.findings_open, h2.state.findings_closed) == (2, 1, 1)
    finally:
        shutil.rmtree(tmp)


def test_infrastructure_audit_findings_write_merges_not_overwrites_registry():
    # Regression for the exact bug this pass closes: an
    # INFRASTRUCTURE_AUDIT/FAILURE_RECOVERY PASS's blackboard_write:
    # ["findings"] previously went through _bb_generic_fallback, which wrote
    # {"evidence":...,"summary":text} as the ENTIRE topic value -- silently
    # discarding any findings already recorded. The fix must preserve the
    # existing items registry and only add stage narrative as contextual
    # last_report, keeping state.findings_* in sync with what's actually
    # still there afterward.
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        h.record_finding("F-PRE-EXISTING", title="found before this stage ran")
        assert h.state.findings_total == 1

        node = h.graph.nodes["INFRASTRUCTURE_AUDIT"]
        assert node.blackboard_write == ["findings"]
        fake_result = AgentResult(ok=True, text="infra audit narrative, no structured findings block",
                                   raw={}, session_id=None)
        h._write_blackboard_from_evidence(node, "INFRASTRUCTURE_AUDIT", {}, fake_result)

        registry = h.blackboard.read_findings()
        assert registry["items"]["F-PRE-EXISTING"]["status"] == "open"  # not wiped
        assert registry["last_report"]["stage"] == "INFRASTRUCTURE_AUDIT"
        assert "narrative" in registry["last_report"]["summary"]
        assert h.state.findings_total == 1 and h.state.findings_open == 1
        assert h.blackboard.findings_counts() == {
            "total": h.state.findings_total, "open": h.state.findings_open,
            "closed": h.state.findings_closed,
        }
    finally:
        shutil.rmtree(tmp)


# "project" reconciliation (2026-08-29): state.project / blackboard
# "project" / blackboard "project_model" are NOT three copies of one thing --
# reading gates.py's own required-field lists for intake_readiness (mode/
# target_name/protocols/required_artifacts) versus
# project_model_topology_completeness_gate (verification_boundary/
# vip_topology/blocks/model_confidence/dv_readiness) confirms genuinely
# different shapes serving different stages. The real duplicate was
# state.project: a bare display string bootstrapped once to the project
# directory name and never refreshed thereafter. These tests prove it is now
# a read-only derived view of blackboard "project".target_name, and that
# "project_model" deliberately does NOT feed it (proving the separation is
# intentional, not an oversight).

def test_intake_blackboard_write_syncs_state_project_as_derived_view():
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        bootstrap_project = h.state.project
        assert bootstrap_project == tmp.name  # storage.py's StateStore.load() bootstrap default

        node = h.graph.nodes["INTAKE"]
        assert node.blackboard_write == ["project"]
        evidence = {"intake_readiness": {
            "mode": "SUBSYSTEM", "target_name": "USB_HOST_SUBSYSTEM",
            "protocols": ["USB3"], "required_artifacts": {"protocol_spec": True},
        }}
        fake_result = AgentResult(ok=True, text="intake complete", raw={}, session_id=None)
        h._write_blackboard_from_evidence(node, "INTAKE", evidence, fake_result)

        # Blackboard "project" holds INTAKE's own structured identity record.
        bb_project = h.blackboard.read("project")["value"]
        assert bb_project["target_name"] == "USB_HOST_SUBSYSTEM"
        assert bb_project["mode"] == "SUBSYSTEM"
        assert bb_project["protocols"] == ["USB3"]

        # state.project is derived FROM it, replacing the bootstrap default.
        assert h.state.project == "USB_HOST_SUBSYSTEM"

        # Reload proves it is a synced view, not a one-off assignment: a
        # fresh DVHarness must arrive at the same value straight from disk.
        h2 = h.__class__(tmp)
        assert h2.state.project == "USB_HOST_SUBSYSTEM"
    finally:
        shutil.rmtree(tmp)


def test_project_model_topic_is_a_different_shape_and_does_not_feed_state_project():
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        # Establish a real state.project via INTAKE first, exactly as above.
        intake_node = h.graph.nodes["INTAKE"]
        h._write_blackboard_from_evidence(
            intake_node, "INTAKE",
            {"intake_readiness": {"mode": "SUBSYSTEM", "target_name": "USB_HOST_SUBSYSTEM",
                                   "protocols": ["USB3"], "required_artifacts": {}}},
            AgentResult(ok=True, text="", raw={}, session_id=None),
        )
        assert h.state.project == "USB_HOST_SUBSYSTEM"

        # PROJECT_MODEL writes a topology record of a genuinely different
        # shape (no target_name at all) via the generic fallback path.
        pm_node = h.graph.nodes["PROJECT_MODEL"]
        assert pm_node.blackboard_write == ["project_model"]
        pm_evidence = {"project_model_topology_completeness_gate": {
            "verification_boundary": "USB host subsystem top", "vip_topology": [],
            "vip_topology_not_applicable_reason": "no VIP in this scope",
            "blocks": [{"block_id": "usb_ctrl", "branch": "BLOCK"}],
            "model_confidence": "HIGH", "confidence_basis": "RTL-confirmed topology",
            "dv_readiness": "READY", "dv_readiness_basis": "all blocks classified",
            "architecture_evidence_db_ref": "arch-evidence-1",
        }}
        h._write_blackboard_from_evidence(
            pm_node, "PROJECT_MODEL", pm_evidence,
            AgentResult(ok=True, text="project model built", raw={}, session_id=None),
        )

        # No dedicated writer maps PROJECT_MODEL yet, so this goes through
        # _bb_generic_fallback -- an honest {"evidence": ..., "summary": ...}
        # wrapper of the stage's own gate evidence, never a target_name (the
        # concrete proof the two topics are structurally different records).
        bb_project_model = h.blackboard.read("project_model")["value"]
        assert "target_name" not in bb_project_model
        pm_block = bb_project_model["evidence"]["project_model_topology_completeness_gate"]
        assert pm_block["verification_boundary"] == "USB host subsystem top"

        # state.project is untouched by this write -- "project" and
        # "project_model" are genuinely independent topics, confirmed here
        # (not merely asserted in a comment).
        assert h.state.project == "USB_HOST_SUBSYSTEM"
    finally:
        shutil.rmtree(tmp)


# dut_version/tb_version (session-snapshot-extension, 2026-09-01): a
# read-only derived view of blackboard "verification_state".results[],
# mirroring state.project's own _sync_project_from_blackboard() pattern
# above. Real source: VERIFY's test_result_provenance_gate evidence, which
# REQUIRES non-empty rtl_revision/tb_revision per result
# (tools/verification_flow/test_result_provenance_gate.py) -- so this is
# always gate-validated evidence, never fabricated by the sync itself.

def test_verify_blackboard_write_syncs_dut_and_tb_version_as_derived_view():
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        assert h.state.dut_version is None
        assert h.state.tb_version is None

        node = h.graph.nodes["VERIFY"]
        assert node.blackboard_write == ["verification_state"]
        evidence = {
            "simulation_semantic_validation_gate": {"simulation_passed": True},
            "test_result_provenance_gate": {"results": [
                {"testcase_id": "t1", "run_id": "r1", "rtl_revision": "rtl-v7",
                 "tb_revision": "tb-v3", "result": "PASS"},
            ]},
            "false_pass_resistance_gate": {"oracle_independent": True},
        }
        fake_result = AgentResult(ok=True, text="verify complete", raw={}, session_id=None)
        h._write_blackboard_from_evidence(node, "VERIFY", evidence, fake_result)

        # Blackboard "verification_state" holds VERIFY's own results record.
        bb_verify = h.blackboard.read("verification_state")["value"]
        assert bb_verify["results"][0]["rtl_revision"] == "rtl-v7"

        # state.dut_version/tb_version are derived FROM it.
        assert h.state.dut_version == "rtl-v7"
        assert h.state.tb_version == "tb-v3"

        # Reload proves it is a synced, persisted view, not a one-off
        # in-memory assignment.
        h2 = h.__class__(tmp)
        assert h2.state.dut_version == "rtl-v7"
        assert h2.state.tb_version == "tb-v3"
    finally:
        shutil.rmtree(tmp)


def test_dut_tb_version_takes_last_result_and_never_blanks_a_known_value():
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        node = h.graph.nodes["VERIFY"]
        fake_result = AgentResult(ok=True, text="", raw={}, session_id=None)

        h._write_blackboard_from_evidence(node, "VERIFY", {
            "test_result_provenance_gate": {"results": [
                {"testcase_id": "t1", "run_id": "r1", "rtl_revision": "rtl-v1", "tb_revision": "tb-v1"},
                {"testcase_id": "t2", "run_id": "r2", "rtl_revision": "rtl-v2", "tb_revision": "tb-v2"},
            ]},
        }, fake_result)
        assert h.state.dut_version == "rtl-v2"
        assert h.state.tb_version == "tb-v2"

        # A later write whose latest result carries an empty rtl_revision
        # must never blank out the already-known value -- same "never
        # regress a known value with an unknown one" rule
        # _sync_project_from_blackboard() already follows.
        h._write_blackboard_from_evidence(node, "VERIFY", {
            "test_result_provenance_gate": {"results": [
                {"testcase_id": "t3", "run_id": "r3", "rtl_revision": "", "tb_revision": None},
            ]},
        }, fake_result)
        assert h.state.dut_version == "rtl-v2"
        assert h.state.tb_version == "tb-v2"
    finally:
        shutil.rmtree(tmp)


def test_protocol_router_evidence_reads_the_topic_verify_actually_writes():
    # BUG FIX (session-snapshot-extension, 2026-09-01): _protocol_router_
    # evidence() used to read blackboard topic "verify", which nothing ever
    # writes (VERIFY's real topic is "verification_state") -- failing_test_
    # name was silently always None. Confirms the fix: a real VERIFY write
    # with a non-PASS result is now actually visible to protocol_router.
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        node = h.graph.nodes["VERIFY"]
        h._write_blackboard_from_evidence(node, "VERIFY", {
            "test_result_provenance_gate": {"results": [
                {"testcase_id": "test_pcie_ltssm_gen4_link_train", "run_id": "r1",
                 "rtl_revision": "a", "tb_revision": "b", "result": "FAIL"},
            ]},
        }, AgentResult(ok=True, text="", raw={}, session_id=None))

        ev = h._protocol_router_evidence("investigate the failure")
        assert ev["failing_test_name"] == "test_pcie_ltssm_gen4_link_train"
    finally:
        shutil.rmtree(tmp)


def test_remote_execution_provenance_gate_blocks_exit_code_mismatch_at_build(tmp_path):
    transcript = tmp_path / "build_transcript.txt"
    transcript.write_text("REMOTE_HOST=host-b\nEXIT_CODE=2\nSTATUS=FAIL\ncompile error\n", encoding="utf-8")
    rc, out = _run_gate_script(
        "verification_flow/remote_execution_provenance_gate.py", "--provenance",
        {"transcript_path": str(transcript), "claimed_exit_code": 0},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "EXIT_CODE_MISMATCH"


def test_remote_execution_provenance_gate_passes_at_verify_with_real_transcript(tmp_path):
    transcript = tmp_path / "verify_transcript.txt"
    transcript.write_text("REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\nUVM_INFO ... TEST PASSED\n", encoding="utf-8")
    rc, out = _run_gate_script(
        "verification_flow/remote_execution_provenance_gate.py", "--provenance",
        {"transcript_path": str(transcript), "claimed_exit_code": 0},
    )
    assert rc == 0 and out["status"] == "PASS"


def test_remote_execution_provenance_gate_not_applicable_escape_hatch_passes_with_reason():
    # I4 (2026-08-31 final review): unlike fabric_topology_completeness_gate
    # and its siblings, this gate had no not-applicable escape hatch at all
    # -- every BUILD/VERIFY response was forced to supply a real transcript
    # even when no remote_exec.py invocation was ever made. Same convention
    # as the precedent gates: a reason is mandatory, not a bare boolean.
    rc, out = _run_gate_script(
        "verification_flow/remote_execution_provenance_gate.py", "--provenance",
        {"provenance_applicable": False,
         "provenance_not_applicable_reason": "local-only static lint pass, no remote execution performed"},
    )
    assert rc == 0 and out["status"] == "SKIPPED_NOT_APPLICABLE"
    assert "no remote execution" in out["reason"]


def test_remote_execution_provenance_gate_not_applicable_without_reason_fails():
    rc, out = _run_gate_script(
        "verification_flow/remote_execution_provenance_gate.py", "--provenance",
        {"provenance_applicable": False},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"


# --- I3 (2026-08-31 final whole-branch review): the plan's Task 2/3/5
# "run_stage()-level integration tests" all used _run_gate_script, a bare
# subprocess call to the gate script alone that never touches STAGE_GATES or
# evaluate_stage_evidence() -- proving nothing about real stage wiring. These
# 4 tests call evaluate_stage_evidence(ROOT, "<STAGE>", text) directly (same
# real signature/usage as test_verify_stage_with_matching_evidence_passes and
# the many other full-stage tests above), with evidence for every OTHER gate
# in that stage supplied as a genuine PASS so exactly ONE of the 3 new gates
# fails and the resulting GATE_FAIL is unambiguously attributable to it.

def test_protocol_isolation_gate_blocks_implement_stage_via_evaluate_stage_evidence():
    text = (
        '```dv-harness-evidence:traceability_consistency_gate\n'
        '{"vplan_requirement_ids": ["R1"], "architecture_nodes": ["A1"], '
        '"verification_mechanisms": [{"mechanism_id": "M1", "vplan_requirement_ids": ["R1"]}], '
        '"planned_testcases": [{"testcase_id": "T1", "vplan_requirement_ids": ["R1"], '
        '"mechanism_ids": ["M1"], "coverage_ids": ["C1"]}], "coverage_ids": ["C1"]}\n```\n'
        '```dv-harness-evidence:checker_independence_gate\n{"checkers": []}\n```\n'
        '```dv-harness-evidence:testcase_name_semantics_gate\n'
        '{"tests": [{"testcase_id": "T1", "name": "usb_reset_recovery_test"}]}\n```\n'
        '```dv-harness-evidence:verification_intent_gate\n'
        '{"requirements": [{"req_id": "R1"}], "mechanisms": [{"mechanism_id": "M1"}], '
        '"coverage": [{"coverage_id": "C1"}], "tests": [{"testcase_id": "T1", '
        '"requirement_ids": ["R1"], "mechanism_ids": ["M1"], "coverage_ids": ["C1"]}]}\n```\n'
        '```dv-harness-evidence:pattern_registry_completeness_gate\n'
        '{"patterns": [{"name": "usb2_enum", "suite": "enumeration", "dir": "tb/patterns/enumeration"}], '
        '"suite_names": ["enumeration"]}\n```\n'
        '```dv-harness-evidence:manual_lookup_before_edit_gate\n{"branch": "block"}\n```\n'
        '```dv-harness-evidence:protocol_isolation_gate\n'
        '{"branch": "branch_b0", "vip_evidence_refs": '
        '[{"path": "USB_UVM_Handoff/some_file.sv", "quote": "x"}]}\n```\n'
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "IMPLEMENT", text)
    assert verdict == "GATE_FAIL"
    assert any("protocol_isolation_gate" in r and "REFERENCE_TREE_CITATION_FORBIDDEN" in r for r in reasons)


_IMPLEMENT_BASE_GATES_PASS_TEXT = (
    '```dv-harness-evidence:traceability_consistency_gate\n'
    '{"vplan_requirement_ids": ["R1"], "architecture_nodes": ["A1"], '
    '"verification_mechanisms": [{"mechanism_id": "M1", "vplan_requirement_ids": ["R1"]}], '
    '"planned_testcases": [{"testcase_id": "T1", "vplan_requirement_ids": ["R1"], '
    '"mechanism_ids": ["M1"], "coverage_ids": ["C1"]}], "coverage_ids": ["C1"]}\n```\n'
    '```dv-harness-evidence:checker_independence_gate\n{"checkers": []}\n```\n'
    '```dv-harness-evidence:testcase_name_semantics_gate\n'
    '{"tests": [{"testcase_id": "T1", "name": "usb_reset_recovery_test"}]}\n```\n'
    '```dv-harness-evidence:verification_intent_gate\n'
    '{"requirements": [{"req_id": "R1"}], "mechanisms": [{"mechanism_id": "M1"}], '
    '"coverage": [{"coverage_id": "C1"}], "tests": [{"testcase_id": "T1", '
    '"requirement_ids": ["R1"], "mechanism_ids": ["M1"], "coverage_ids": ["C1"]}]}\n```\n'
    '```dv-harness-evidence:pattern_registry_completeness_gate\n'
    '{"patterns": [{"name": "usb2_enum", "suite": "enumeration", "dir": "tb/patterns/enumeration"}], '
    '"suite_names": ["enumeration"]}\n```\n'
    '```dv-harness-evidence:manual_lookup_before_edit_gate\n{"branch": "block"}\n```\n'
    '```dv-harness-evidence:protocol_isolation_gate\n'
    '{"vip_evidence_refs": [], "dut_rtl_evidence_refs": []}\n```\n'
)


def test_rtl_write_scope_guard_gate_blocks_implement_stage_via_evaluate_stage_evidence():
    # Wiring proof: this repo's OWN real .dv-harness/config.json now declares
    # rtl_protection.protected_paths for the real project this harness
    # deployment governs (see .claude/settings.json's matching Edit/Write
    # deny rules for the same two paths) -- so this exercises the real,
    # currently-configured enforcement boundary, not a synthetic one.
    text = _IMPLEMENT_BASE_GATES_PASS_TEXT + (
        '```dv-harness-evidence:rtl_write_scope_guard_gate\n'
        '{"edit": {"touched_paths": ["D:/DV/Task/USB/DUT/RTLCAT/top.v"]}}\n```\n'
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "IMPLEMENT", text)
    assert verdict == "GATE_FAIL"
    assert any("rtl_write_scope_guard_gate" in r and "RTL_WRITE_SCOPE_VIOLATION" in r for r in reasons), reasons


def test_rtl_write_scope_guard_gate_passes_implement_stage_for_uvm_only_touch():
    text = _IMPLEMENT_BASE_GATES_PASS_TEXT + (
        '```dv-harness-evidence:rtl_write_scope_guard_gate\n'
        '{"edit": {"touched_paths": ["uvm/tb/scoreboard.sv"]}}\n```\n'
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "IMPLEMENT", text)
    assert verdict == "PASS", reasons


def test_protocol_profile_binding_gate_blocks_protocol_capability_stage_via_evaluate_stage_evidence():
    text = (
        '```dv-harness-evidence:protocol_generator_binding_gate\n{"protocols": []}\n```\n'
        '```dv-harness-evidence:protocol_profile_binding_gate\n'
        '{"protocols": [{"protocol": "usb", "profile_skills_consulted": []}]}\n```\n'
        '```dv-harness-evidence:protocol_onboarding_gate\n'
        '{"protocol_name": "usb", "spec_sources": ["usb_spec.pdf"], "dut_mapping": "usb_dut.sv", '
        '"vip_strategy": "synopsys usb vip", "state_model": "link state model", '
        '"transaction_model": "transaction model", "error_recovery_model": "error recovery model", '
        '"verification_mechanism_plan": "mechanism plan", "vplan_mapping": "vplan mapping", '
        '"test_generation_strategy": "test gen strategy", "coverage_model": "coverage model", '
        '"qualification_plan": "qualification plan", "evidence_refs": ["ev1"]}\n```\n'
        '```dv-harness-evidence:protocol_profile_version_gate\n'
        '{"protocol_name": "usb", "profile_version": "1.0", "spec_revision": "r1", '
        '"profile_hash": "h1", "qualification_state": "DRAFT"}\n```\n'
        '```dv-harness-evidence:protocol_qualification_status_gate\n{"protocols": []}\n```\n'
        '```dv-harness-evidence:protocol_builder_registry_conformance_gate\n'
        '{"registry_applicable": false, '
        '"registry_not_applicable_reason": "stage-level regression test, not exercising checklist conformance"}\n```\n'
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "PROTOCOL_CAPABILITY", text)
    assert verdict == "GATE_FAIL"
    assert any("protocol_profile_binding_gate" in r and "PROFILE_SKILL_NOT_CONSULTED" in r for r in reasons)


def test_remote_execution_provenance_gate_blocks_build_stage_via_evaluate_stage_evidence():
    text = (
        '```dv-harness-evidence:shared_elaboration_collision_gate\n{"build_owner_count": 1}\n```\n'
        '```dv-harness-evidence:stop_after_simv_policy_gate\n'
        '{"build_fingerprint": "fp1", "simv_completion_marker": "m1", '
        '"simv_completion_marker_build_fingerprint": "fp1"}\n```\n'
        '```dv-harness-evidence:remote_execution_provenance_gate\n'
        '{"transcript_path": "/no/such/build_transcript.txt", "claimed_exit_code": 0}\n```\n'
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "BUILD", text)
    assert verdict == "GATE_FAIL"
    assert any("remote_execution_provenance_gate" in r and "TRANSCRIPT_FILE_NOT_FOUND" in r for r in reasons)


def test_remote_execution_provenance_gate_blocks_verify_stage_via_evaluate_stage_evidence():
    # Reuses _VERIFY_EXTRA_GATES WITHOUT substituting a real transcript path
    # for remote_execution_provenance_gate (unlike
    # test_verify_stage_with_matching_evidence_passes above) -- every other
    # VERIFY gate gets real, valid evidence, so the resulting GATE_FAIL is
    # unambiguously this one gate's TRANSCRIPT_FILE_NOT_FOUND.
    text = (
        "```dv-harness-evidence:simulation_semantic_validation_gate\n"
        '{"simulation_passed": true, "sim_log": "UVM_INFO enum PASS", '
        '"command_expectations": [{"expectation_id": "e1", "required": true, '
        '"evidence_requirements": [{"pattern": "enum PASS", "match_mode": "SUBSTRING"}]}]}\n'
        "```\n"
        "```dv-harness-evidence:test_result_provenance_gate\n"
        '{"results": [{"testcase_id": "t1", "run_id": "r1", "rtl_revision": "a", '
        '"tb_revision": "b", "vip_version": "c", "tool_version": "d", "seed": "1", '
        '"config_hash": "h", "result": "PASS", "log_hash": "lh", "evidence_bundle_hash": "eh"}]}\n'
        "```\n"
        "```dv-harness-evidence:false_pass_resistance_gate\n"
        '{"positive_test_pass": true, "negative_test_detects_fault": true, '
        '"checker_detects_injected_fault": true, "semantic_log_match": true, '
        '"oracle_independent": true, "proof_bundle_hash": "h1"}\n'
        "```\n"
        + _VERIFY_EXTRA_GATES
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "VERIFY", text)
    assert verdict == "GATE_FAIL"
    assert any("remote_execution_provenance_gate" in r and "TRANSCRIPT_FILE_NOT_FOUND" in r for r in reasons)


# --- Cross-cycle debug-loop counter + Health Monitor dispatch (2026-09-01,
# ai-debug-closed-loop-counter-implementation task) --------------------------
# Blackboard.append_debug_loop_round()/read_debug_loop_history()/
# debug_loop_round_count() are the real, persisted, cross-cycle record this
# task adds (see blackboard.py's own docstring); DVHarness.
# _record_debug_loop_round()/_health_monitor_check() are engine.py's real,
# wired call sites into it -- exercised end to end below via loop() itself,
# not just as standalone units.

def test_blackboard_debug_loop_history_round_trip_and_cross_cycle_query():
    from dv_harness.blackboard import Blackboard
    tmp = Path(tempfile.mkdtemp())
    try:
        bb = Blackboard(tmp)
        assert bb.read_debug_loop_history() == {"entries": []}
        assert bb.debug_loop_round_count() == 0

        for i in range(2):
            bb.append_debug_loop_round({
                "timestamp": f"t{i}", "failing_stage": "VERIFY",
                "target_fail_edge": "FAILURE_RECOVERY", "attempt_number": 1,
                "node_route": "build-route", "health_monitor_check": None,
            }, source="VERIFY")
        bb.append_debug_loop_round({
            "timestamp": "t3", "failing_stage": "REGRESSION_MONITOR",
            "target_fail_edge": "INFRA_RECOVERY", "attempt_number": 1,
            "node_route": "regression-route", "health_monitor_check": None,
        }, source="REGRESSION_MONITOR")

        history = bb.read_debug_loop_history()
        assert [e["round_number"] for e in history["entries"]] == [1, 2, 3]
        # This is the real query an "how many full fix/push/rebuild passes
        # has this failure gone through" question is answered from --
        # uncapped and whole-run, unlike a per-node ss['attempts'] counter.
        assert bb.debug_loop_round_count() == 3
        assert bb.debug_loop_round_count("VERIFY") == 2
        assert bb.debug_loop_round_count("REGRESSION_MONITOR") == 1
        assert bb.debug_loop_round_count("NEVER_FAILED_STAGE") == 0
    finally:
        shutil.rmtree(tmp)


def test_remote_lsf_routes_ruling_matches_documented_build_and_regression_nodes():
    # Regression-locks the RULING made in engine.py's module-level comment
    # above REMOTE_LSF_ROUTES: real graph node.route values (main_graph.json)
    # for every node that actually submits/monitors a VCS build or LSF
    # regression job, no more and no less.
    import dv_harness.engine as engine_mod
    tmp, h = _fresh_harness()
    try:
        remote_ids = {n.id for n in h.graph.nodes.values() if n.route in engine_mod.REMOTE_LSF_ROUTES}
        assert remote_ids == {
            "DE_BASELINE_REPRODUCTION", "SERVER_SYNC", "BUILD", "BUILD_DEBUG", "VERIFY",
            "REGRESSION_SELECT", "REGRESSION", "REGRESSION_MONITOR", "COVERAGE_CLOSURE", "INFRA_RECOVERY",
        }
    finally:
        shutil.rmtree(tmp)


def test_record_debug_loop_round_only_health_checks_remote_lsf_route_stages():
    # FAILURE_RECOVERY (debug-route) never submits a build/regression job
    # itself -- health_monitor_check must stay None, never a fabricated
    # check. VERIFY (build-route) really does -- a real subprocess call to
    # `dv-harness lsf-watch-status` (equivalent to the documented protocol
    # command) must run and its real result must land in the entry.
    tmp, h = _fresh_harness()
    try:
        registry = h._record_debug_loop_round("FAILURE_RECOVERY", None)
        entry = registry["entries"][-1]
        assert entry["round_number"] == 1
        assert entry["failing_stage"] == "FAILURE_RECOVERY"
        assert entry["target_fail_edge"] is None
        assert entry["node_route"] == "debug-route"
        assert entry["health_monitor_check"] is None

        registry2 = h._record_debug_loop_round("VERIFY", "FAILURE_RECOVERY")
        entry2 = registry2["entries"][-1]
        assert entry2["round_number"] == 2
        assert entry2["node_route"] == "build-route"
        assert entry2["target_fail_edge"] == "FAILURE_RECOVERY"
        hc = entry2["health_monitor_check"]
        assert hc is not None, "VERIFY is a build-route stage -- a real Health Monitor check must have run"
        assert hc["ok"] is True, hc
        assert hc["result"] == {"running": False, "pid": None}
        assert "lsf-watch-status" in hc["command"]
        # The Telnet/SSH remote hop and watcher START are a deliberate,
        # policy-mandated human/agent step per CLAUDE.md -- this must never
        # be what the engine's own FAIL-edge health check invokes.
        assert "lsf-watch-start" not in hc["command"]

        assert h.blackboard.debug_loop_round_count() == 2
        assert h.blackboard.debug_loop_round_count("VERIFY") == 1
        assert h.blackboard.debug_loop_round_count("FAILURE_RECOVERY") == 1
    finally:
        shutil.rmtree(tmp)


def test_loop_records_debug_loop_history_across_a_full_fail_edge_pass():
    # Full end-to-end wiring test: VERIFY (build-route) fails via
    # ADAPTER_FAIL, retries exhausted immediately (max_stage_retries=0),
    # loop() routes via the graph's real FAIL edge (VERIFY ->
    # FAILURE_RECOVERY per main_graph.json) -- which itself then also fails
    # and exhausts (FAILURE_RECOVERY has no FAIL edge in main_graph.json,
    # only PASS/BLOCKED, so loop() stops there). Two real, persisted
    # debug_loop_history rounds must result, only the first (a build-route
    # stage) carrying a real Health Monitor check.
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["max_stage_retries"] = 0
        h.set_stage("VERIFY")

        class _AlwaysAdapterFail:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=False, text="", raw={"stderr": "boom"}, session_id=None)

        h.adapter = _AlwaysAdapterFail()
        h.loop("goal")

        entries = h.blackboard.read_debug_loop_history()["entries"]
        assert [e["failing_stage"] for e in entries] == ["VERIFY", "FAILURE_RECOVERY"]

        assert entries[0]["target_fail_edge"] == "FAILURE_RECOVERY"
        assert entries[0]["node_route"] == "build-route"
        assert entries[0]["health_monitor_check"]["ok"] is True
        assert entries[0]["health_monitor_check"]["result"] == {"running": False, "pid": None}

        assert entries[1]["target_fail_edge"] is None
        assert entries[1]["node_route"] == "debug-route"
        assert entries[1]["health_monitor_check"] is None

        assert h.blackboard.debug_loop_round_count() == 2
        assert h.state.current_stage == "FAILURE_RECOVERY"
    finally:
        shutil.rmtree(tmp)


def test_stage_profiler_read_retries_transient_windows_permission_error():
    # PRE-EXISTING BUG fixed while testing this task (found via a real full
    # `dv_harness_tests/` suite run, not manufactured): StageExecutionProfiler.
    # all_stages()/_load() had no equivalent of storage.py's _atomic_replace()
    # retry-on-PermissionError -- a real ThreadPoolExecutor fan-out run hit a
    # bare PermissionError racing a concurrent writer's atomic os.replace().
    # stage_profile._read_json_retrying() now retries transient PermissionErrors
    # briefly before giving up.
    from dv_harness.stage_profile import StageExecutionProfiler
    tmp = Path(tempfile.mkdtemp())
    try:
        profiler = StageExecutionProfiler(tmp)
        rec = profiler.begin_stage("S1", "S1")

        real_read_text = Path.read_text
        calls = {"n": 0}

        def flaky_read_text(self, *a, **k):
            if self.name.startswith("STAGE-") and calls["n"] < 2:
                calls["n"] += 1
                raise PermissionError(13, "simulated concurrent-replace race")
            return real_read_text(self, *a, **k)

        with patch("pathlib.Path.read_text", flaky_read_text):
            stages = profiler.all_stages()
        assert len(stages) == 1
        assert stages[0]["profile_id"] == rec["profile_id"]
        assert calls["n"] == 2  # actually retried past 2 real failures, not a lucky first try
    finally:
        shutil.rmtree(tmp)


def test_stage_profiler_read_eventually_raises_on_persistent_permission_error():
    # A genuinely, persistently locked file (not a transient race) must
    # still surface as a real PermissionError after retries are exhausted --
    # never silently swallowed or fabricated as an empty result.
    from dv_harness.stage_profile import StageExecutionProfiler
    tmp = Path(tempfile.mkdtemp())
    try:
        profiler = StageExecutionProfiler(tmp)
        profiler.begin_stage("S1", "S1")

        def always_denied(self, *a, **k):
            if self.name.startswith("STAGE-"):
                raise PermissionError(13, "persistently locked")
            return Path.read_text(self, *a, **k)

        with patch("pathlib.Path.read_text", always_denied):
            try:
                profiler.all_stages()
                assert False, "persistent PermissionError must still be raised, not swallowed"
            except PermissionError:
                pass
    finally:
        shutil.rmtree(tmp)


def test_health_monitor_check_records_real_failure_when_subprocess_errors():
    # A subprocess failure (bad python executable) must be recorded as real
    # negative evidence, never fabricated as a pass, and must never raise
    # out of _health_monitor_check() itself (it is a best-effort side
    # effect that must never block FAIL-edge routing).
    tmp, h = _fresh_harness()
    try:
        node = h.graph.nodes["VERIFY"]
        with patch("dv_harness.engine.sys") as fake_sys:
            fake_sys.executable = str(tmp / "no_such_python_binary_xyz.exe")
            result = h._health_monitor_check(node)
        assert result is not None
        assert result["ok"] is False
        assert "error" in result
    finally:
        shutil.rmtree(tmp)


# --- Task 5 (2026-09-02 autonomous-gate-self-tuning-mechanism design):
# DVHarness._maybe_run_self_tuning_review() -- the review-cycle orchestration
# wired into run_stage()'s single real terminal exit point (see engine.py's
# "Step 7" comment right before `return result`). These tests call
# _maybe_run_self_tuning_review() directly (no main_graph.json/stage setup
# needed) against a bare `DVHarness(tmp)` with `h.adapter` replaced by a fake
# implementing the same run(prompt, cwd, resume_session=None,
# agent_profile=None) -> AgentResult contract as the real adapter (same
# pattern used throughout this file, e.g. FakeAdapter above).
from dv_harness import self_tuning as _self_tuning_module
from dv_harness.adapters.base import AgentResult as _SelfTuningAgentResult


class _FakeSelfTuningAdapter:
    def __init__(self, text=None, ok=True, raises=None):
        self.text = text
        self.ok = ok
        self.raises = raises
        self.calls = 0

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        self.calls += 1
        if self.raises:
            raise self.raises
        return _SelfTuningAgentResult(ok=self.ok, text=self.text or "", raw={}, session_id="s")


def _self_tuning_proposal_block(gate_id="unprotected_gate", confidence="HIGH", risk_level="LOW", to=2):
    return (
        "```dv-harness-evidence:self_tuning_proposal\n"
        + json.dumps({"proposals": [{
            "gate_id": gate_id, "change": {"param": "threshold", "from": 1, "to": to},
            "rationale": "observed pattern", "confidence": confidence, "risk_level": risk_level,
        }]})
        + "\n```"
    )


def _mk_self_tuning_project():
    # run_gate() (dv_harness/gates.py) resolves gate scripts as
    # root/tools/verification_flow/<script>.py -- a plain tempfile.mkdtemp()
    # has no such tree, so self_tuning_proposal_gate.py would resolve to
    # GATE_TOOL_MISSING and gate_result.ok would be False regardless of the
    # proposal content, making these tests pass for the wrong reason. Copy
    # the real tools/ tree in, same as _mk_smoke_project() above, so the
    # proposal gate genuinely executes.
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(ROOT / "tools", tmp / "tools")
    return tmp


def _self_tuning_proposal_gate_env():
    # self_tuning_proposal_gate.py (tools/verification_flow/) does `from
    # dv_harness.self_tuning import PROTECTED_REMOVALS`, resolving its own
    # import root as Path(__file__).resolve().parents[2] -- correct when the
    # script lives at the REAL dv_harness repo's tools/verification_flow/
    # (parents[2] == the repo root, which contains the dv_harness package),
    # but wrong for a copy under an isolated tempfile.mkdtemp() project (its
    # parents[2] is just the empty tmp dir, no dv_harness package there).
    # dv_harness itself is not pip-installed in this dev environment (no
    # sdist/egg-info), so it is only importable via this repo's own root
    # being on sys.path. run_gate()'s subprocess.run() inherits the calling
    # process's environment unmodified, so putting the real ROOT on
    # PYTHONPATH here lets the copied script's `from dv_harness...` import
    # succeed the same way it would for a real pip-installed deployment,
    # without changing any engine.py/gates.py production code.
    existing = os.environ.get("PYTHONPATH", "")
    return {"PYTHONPATH": (str(ROOT) + os.pathsep + existing) if existing else str(ROOT)}


def test_self_tuning_review_triggers_after_n_executions_and_auto_applies():
    tmp = _mk_self_tuning_project()
    try:
        from dv_harness.engine import DVHarness
        h = DVHarness(tmp)
        h.cfg["self_tuning"] = {"enabled": True, "review_every_n_executions": 2}
        fake = _FakeSelfTuningAdapter(text=_self_tuning_proposal_block())
        h.adapter = fake

        with patch.dict(os.environ, _self_tuning_proposal_gate_env()):
            _self_tuning_module.increment_execution_counter(h.root)  # 1st of 2
            h._maybe_run_self_tuning_review()
            assert fake.calls == 0

            _self_tuning_module.increment_execution_counter(h.root)  # 2nd of 2 -- triggers
            h._maybe_run_self_tuning_review()
        assert fake.calls == 1

        assert _self_tuning_module.get_param(h.root, "unprotected_gate", "threshold", None) == 2
        assert _self_tuning_module.read_execution_state(h.root)["executions_since_last_review"] == 0
    finally:
        shutil.rmtree(tmp)


def test_self_tuning_review_defers_low_confidence_proposal():
    tmp = _mk_self_tuning_project()
    try:
        from dv_harness.engine import DVHarness
        h = DVHarness(tmp)
        h.cfg["self_tuning"] = {"enabled": True, "review_every_n_executions": 1}
        h.adapter = _FakeSelfTuningAdapter(text=_self_tuning_proposal_block(confidence="LOW"))

        with patch.dict(os.environ, _self_tuning_proposal_gate_env()):
            _self_tuning_module.increment_execution_counter(h.root)
            h._maybe_run_self_tuning_review()

        assert _self_tuning_module.get_param(h.root, "unprotected_gate", "threshold", None) is None
    finally:
        shutil.rmtree(tmp)


def test_self_tuning_review_disabled_by_default_config():
    tmp = Path(tempfile.mkdtemp())
    try:
        from dv_harness.engine import DVHarness
        h = DVHarness(tmp)
        # no h.cfg["self_tuning"] override -- DEFAULT_CONFIG's own default applies
        fake = _FakeSelfTuningAdapter(text=_self_tuning_proposal_block())
        h.adapter = fake
        for _ in range(100):
            _self_tuning_module.increment_execution_counter(h.root)
        h._maybe_run_self_tuning_review()
        assert fake.calls == 0
    finally:
        shutil.rmtree(tmp)


def test_self_tuning_review_adapter_failure_does_not_reset_counter_or_raise():
    tmp = Path(tempfile.mkdtemp())
    try:
        from dv_harness.engine import DVHarness
        h = DVHarness(tmp)
        h.cfg["self_tuning"] = {"enabled": True, "review_every_n_executions": 1}
        h.adapter = _FakeSelfTuningAdapter(raises=RuntimeError("boom"))

        _self_tuning_module.increment_execution_counter(h.root)
        h._maybe_run_self_tuning_review()  # must not raise

        assert _self_tuning_module.read_execution_state(h.root)["executions_since_last_review"] == 1
    finally:
        shutil.rmtree(tmp)


def test_self_tuning_review_run_stage_increments_counter_on_every_terminal_verdict():
    # run_stage() must increment the execution counter on EVERY terminal
    # verdict, not only PASS -- exercised here via an ADAPTER_FAIL (result.ok
    # is False) and a GATE_FAIL/PARTIAL (result.ok True, no evidence block),
    # both of which are real terminal run_stage() results that fall through
    # to the single `return result` this task wired the counter/review call
    # onto. self_tuning stays disabled (DEFAULT_CONFIG default) so this test
    # is purely about the counter increment, not the review firing.
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness

        class _AdapterFailAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return _SelfTuningAgentResult(ok=False, text="", raw={"stderr": "boom"}, session_id=None)

        h = DVHarness(tmp)
        h.adapter = _AdapterFailAdapter()
        h.set_stage("VERIFY")

        assert _self_tuning_module.read_execution_state(h.root)["executions_since_last_review"] == 0
        h.run_stage("goal")
        ss = h.state.stages["VERIFY"]
        assert ss["status"] == "FAIL"
        assert _self_tuning_module.read_execution_state(h.root)["executions_since_last_review"] == 1

        class _PartialAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                # Same ok=True/no-evidence text as
                # test_run_stage_replans_and_reuses_same_plan_across_retries_on_partial
                # above (a known-good MISSING_EVIDENCE -> PARTIAL fixture for
                # VERIFY), reused here rather than inventing a new string.
                return _SelfTuningAgentResult(ok=True, text="I verified it, trust me.", raw={}, session_id="s")

        h.adapter = _PartialAdapter()
        h.run_stage("goal")
        ss = h.state.stages["VERIFY"]
        assert ss["status"] == "PARTIAL"
        assert _self_tuning_module.read_execution_state(h.root)["executions_since_last_review"] == 2
    finally:
        shutil.rmtree(tmp)


# --- Task 5 code-review fixes (2026-09-02): 3 findings against the
# self-tuning review-cycle wiring above --
#   Finding 1 (Critical): the increment_execution_counter() call at
#     run_stage()'s single terminal return point had no try/except -- a real
#     I/O failure there (disk full/permission/transient Windows file-lock
#     race) would propagate out of run_stage() and destroy the
#     already-computed real stage result.
#   Finding 2 (Important): run_gate() raising (e.g. its own
#     subprocess.TimeoutExpired, uncaught inside gates.py) fell through to
#     _maybe_run_self_tuning_review()'s OUTER blanket except -- which does
#     NOT reset the counter, wrongly giving an internal gate failure the
#     same non-reset treatment as a genuine adapter failure.
#   Finding 3 (Important): read_gate_history_since(root, 0) always re-sent
#     the ENTIRE cumulative gate_history.jsonl log every review cycle,
#     never scoped to "since the last successful review".

def test_run_stage_survives_increment_execution_counter_raising():
    # Finding 1 regression: simulate the real I/O call raising and confirm
    # run_stage() still returns its real, already-computed result rather
    # than propagating the exception.
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness

        class _AdapterFailAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return _SelfTuningAgentResult(ok=False, text="", raw={"stderr": "boom"}, session_id=None)

        h = DVHarness(tmp)
        h.adapter = _AdapterFailAdapter()
        h.set_stage("VERIFY")

        with patch("dv_harness.self_tuning.increment_execution_counter",
                   side_effect=RuntimeError("simulated disk-full/permission failure")):
            result = h.run_stage("goal")

        # The real stage result must still come back, unaltered by the
        # simulated counter-write failure.
        assert result is not None
        assert result.ok is False
        ss = h.state.stages["VERIFY"]
        assert ss["status"] == "FAIL"
    finally:
        shutil.rmtree(tmp)


def test_self_tuning_review_run_gate_exception_resets_counter_unlike_adapter_failure():
    # Finding 2 regression: run_gate() raising (not just returning
    # ok=False) must get the SAME internal-failure "reset the counter"
    # treatment as gate_result.ok is False already gets -- distinct from a
    # genuine adapter failure, which must NOT reset (see
    # test_self_tuning_review_adapter_failure_does_not_reset_counter_or_raise
    # above). Also confirms the reset here does NOT advance
    # last_reviewed_gate_history_index (only a successful cycle's
    # completion should).
    tmp = Path(tempfile.mkdtemp())
    try:
        from dv_harness.engine import DVHarness
        h = DVHarness(tmp)
        h.cfg["self_tuning"] = {"enabled": True, "review_every_n_executions": 1}
        h.adapter = _FakeSelfTuningAdapter(text=_self_tuning_proposal_block())

        _self_tuning_module.increment_execution_counter(h.root)
        with patch("dv_harness.gates.run_gate", side_effect=RuntimeError("simulated gate subprocess timeout")):
            h._maybe_run_self_tuning_review()  # must not raise

        assert _self_tuning_module.read_execution_state(h.root)["executions_since_last_review"] == 0
        assert _self_tuning_module.read_last_reviewed_index(h.root) == 0
    finally:
        shutil.rmtree(tmp)


def test_self_tuning_review_scopes_gate_history_to_last_reviewed_index():
    # Finding 3 regression: two consecutive SUCCESSFUL review cycles must
    # each see only the history entries appended since the previous cycle,
    # not the full cumulative gate_history.jsonl log both times.
    from dv_harness.gates import GateResult
    tmp = Path(tempfile.mkdtemp())
    try:
        from dv_harness.engine import DVHarness
        h = DVHarness(tmp)
        h.cfg["self_tuning"] = {"enabled": True, "review_every_n_executions": 1}

        prompts = []

        class _RecordingAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                prompts.append(prompt)
                return _SelfTuningAgentResult(
                    ok=True, text=_self_tuning_proposal_block(), raw={}, session_id="s")

        h.adapter = _RecordingAdapter()

        # run_gate() is mocked here (rather than exercising the real
        # self_tuning_proposal_gate.py subprocess, as the earlier
        # auto-apply/defer tests do via _mk_self_tuning_project()) so this
        # test stays focused purely on the history-scoping behavior, with
        # no extra gate_history.jsonl entries appended as a side effect of
        # the mechanical proposal-gate call itself.
        ok_empty_gate_result = GateResult(
            "self_tuning_proposal_gate", True, {"surviving_proposals": [], "stripped": []})

        # Cycle 1: 2 pre-existing history entries, nothing reviewed yet
        # (last_reviewed_index defaults to 0) -- both must be visible.
        _self_tuning_module.append_gate_history(h.root, "gate_a", "IMPLEMENT", True, "PASS", 1.0)
        _self_tuning_module.append_gate_history(h.root, "gate_b", "IMPLEMENT", False, "GATE_FAIL", 2.0)
        _self_tuning_module.increment_execution_counter(h.root)
        with patch("dv_harness.gates.run_gate", return_value=ok_empty_gate_result):
            h._maybe_run_self_tuning_review()

        assert len(prompts) == 1
        assert "most recent 2 gate invocations" in prompts[0]
        assert _self_tuning_module.read_last_reviewed_index(h.root) == 2
        assert _self_tuning_module.read_execution_state(h.root)["executions_since_last_review"] == 0

        # Cycle 2: one NEW entry appended after cycle 1 completed -- only
        # this one entry should appear, not the 2 from cycle 1 again.
        _self_tuning_module.append_gate_history(h.root, "gate_c", "VERIFY", True, "PASS", 3.0)
        _self_tuning_module.increment_execution_counter(h.root)
        with patch("dv_harness.gates.run_gate", return_value=ok_empty_gate_result):
            h._maybe_run_self_tuning_review()

        assert len(prompts) == 2
        assert "most recent 1 gate invocations" in prompts[1]
        assert _self_tuning_module.read_last_reviewed_index(h.root) == 3
    finally:
        shutil.rmtree(tmp)


# --- Finding I6 fix (2026-09-02 final-review fix wave): run_gate()'s
# gate-history logging is also reached by non-stage-evaluation callers
# (dv_harness/self_audit.py's smoke-testing, dv_harness/remote_control.py's
# supervisory/audit gates) with no real `stage` -- these must never pollute
# gate_history.jsonl with fabricated entries the self-tuning LLM would
# otherwise treat as real accumulated execution history.

def test_run_gate_with_no_stage_does_not_append_to_gate_history():
    from dv_harness import gates as gates_mod
    tmp = _mk_self_tuning_project()
    try:
        history_path = tmp / ".dv-harness" / "self_tuning" / "gate_history.jsonl"
        with patch.dict(os.environ, _self_tuning_proposal_gate_env()):
            gr = gates_mod.run_gate(tmp, "self_tuning_proposal_gate.py", "--proposal", {"proposals": []})
        assert gr.ok is True
        assert not history_path.exists()
    finally:
        shutil.rmtree(tmp)


def test_run_gate_with_empty_string_stage_does_not_append_to_gate_history():
    from dv_harness import gates as gates_mod
    tmp = _mk_self_tuning_project()
    try:
        history_path = tmp / ".dv-harness" / "self_tuning" / "gate_history.jsonl"
        with patch.dict(os.environ, _self_tuning_proposal_gate_env()):
            gr = gates_mod.run_gate(tmp, "self_tuning_proposal_gate.py", "--proposal", {"proposals": []}, stage="")
        assert gr.ok is True
        assert not history_path.exists()
    finally:
        shutil.rmtree(tmp)


def test_run_gate_with_real_stage_does_append_to_gate_history():
    from dv_harness import gates as gates_mod
    tmp = _mk_self_tuning_project()
    try:
        history_path = tmp / ".dv-harness" / "self_tuning" / "gate_history.jsonl"
        with patch.dict(os.environ, _self_tuning_proposal_gate_env()):
            gr = gates_mod.run_gate(tmp, "self_tuning_proposal_gate.py", "--proposal", {"proposals": []},
                                     stage="IMPLEMENT")
        assert gr.ok is True
        assert history_path.exists()
        entries = _self_tuning_module.read_gate_history_since(tmp, 0)
        assert len(entries) == 1
        assert entries[0]["stage"] == "IMPLEMENT"
        assert entries[0]["gate_id"] == "self_tuning_proposal_gate"
    finally:
        shutil.rmtree(tmp)
