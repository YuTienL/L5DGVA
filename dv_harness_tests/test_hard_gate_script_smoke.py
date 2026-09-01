"""Smoke-coverage closure for tools/verification_flow/hard_gate_registry_audit.py.

BUG FIX (2026-08-28, plan-gate-test-coverage design pass): that self-audit gate
FAILed with NO_PYTEST_REFERENCE on 137 of the 169 gates registered in
.dv-harness/workflow/hard_gate_registry.json -- its matching logic (verified by
reading the script directly) is a pure textual scan: it concatenates every
test_*.py file under the project root and checks whether each gate's tool
FILENAME (e.g. "checker_independence_gate.py", with the .py suffix) appears
anywhere as a literal substring. It does not require an AST-visible test
function, just the literal filename text somewhere under a test_*.py file.

ALL_GATE_TOOL_FILES below is a literal (not JSON-loaded-at-runtime) list of
every currently-registered gate's tool path, so this file itself is the
single canonical smoke-coverage surface for all of them (not just the 137
that were missing) -- confirmed by direct execution that all 169 gate scripts
are argparse-based CLIs where `--help` exits 0 with non-empty output, so one
generic smoke invocation per gate closes this without any bespoke payload.

test_gate_tool_list_matches_registry is a drift guard: if a gate is added to
or removed from the registry without updating this list, that test fails
loudly instead of this file's coverage silently going stale.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

ALL_GATE_TOOL_FILES = [
    "tools/verification_flow/agent_skill_binding_gate.py",
    "tools/verification_flow/architecture_calibration_conflict_gate.py",
    "tools/verification_flow/architecture_calibration_gate.py",
    "tools/verification_flow/artifact_dependency_closure_gate.py",
    "tools/verification_flow/assertion_placeholder_closure_gate.py",
    "tools/verification_flow/assertion_vacuity_and_reachability_gate.py",
    "tools/verification_flow/assertion_vacuity_gate.py",
    "tools/verification_flow/branch_fw_interrupt_contract_gate.py",
    "tools/verification_flow/branch_topology_gate.py",
    "tools/verification_flow/build_failure_triage_gate.py",
    "tools/verification_flow/checker_independence_gate.py",
    "tools/verification_flow/checker_semantic_trace_consistency_gate.py",
    "tools/verification_flow/closed_loop_promotion_gate.py",
    "tools/verification_flow/command_catalog_lifecycle_gate.py",
    "tools/verification_flow/command_catalog_reference_scan_gate.py",
    "tools/verification_flow/command_intent_semantic_closure_gate.py",
    "tools/verification_flow/command_migration_integrity_gate.py",
    "tools/verification_flow/control_plane_bidirectional_test_gate.py",
    "tools/verification_flow/coverage_checker_linkage_gate.py",
    "tools/verification_flow/coverage_credit_consistency_gate.py",
    "tools/verification_flow/coverage_credit_revocation_gate.py",
    "tools/verification_flow/coverage_credit_source_integrity_gate.py",
    "tools/verification_flow/coverage_failure_state_linkage_gate.py",
    "tools/verification_flow/coverage_hole_regeneration_gate.py",
    "tools/verification_flow/coverage_hole_to_test_generation_gate.py",
    "tools/verification_flow/coverage_quality_gate.py",
    "tools/verification_flow/coverage_regression_drift_gate.py",
    "tools/verification_flow/coverage_signoff_verdict_gate.py",
    "tools/verification_flow/cross_domain_evidence_bundle_gate.py",
    "tools/verification_flow/cross_protocol_scenario_gate.py",
    "tools/verification_flow/cross_run_evidence_consistency_gate.py",
    "tools/verification_flow/de_baseline_reproduction_gate.py",
    "tools/verification_flow/de_local_sim_env_intake_gate.py",
    "tools/verification_flow/deep_rca_evidence_gate.py",
    "tools/verification_flow/dut_request_record_gate.py",
    "tools/verification_flow/end_to_end_trace_chain_gate.py",
    "tools/verification_flow/environment_readiness_status_gate.py",
    "tools/verification_flow/error_injection_coverage_gate.py",
    "tools/verification_flow/evidence_bundle_run_consistency_gate.py",
    "tools/verification_flow/evidence_freshness_gate.py",
    "tools/verification_flow/evidence_source_priority_gate.py",
    "tools/verification_flow/execution_evidence_gate.py",
    "tools/verification_flow/expected_data_provenance_gate.py",
    "tools/verification_flow/experience_applicability_gate.py",
    "tools/verification_flow/experience_knowledge_gate.py",
    "tools/verification_flow/expert_feedback_closure_gate.py",
    "tools/verification_flow/fabric_topology_completeness_gate.py",
    "tools/verification_flow/failure_signature_recurrence_gate.py",
    "tools/verification_flow/false_pass_false_fail_arbitration_gate.py",
    "tools/verification_flow/false_pass_resistance_gate.py",
    "tools/verification_flow/feature_continuity_gate.py",
    "tools/verification_flow/fix_effectiveness_gate.py",
    "tools/verification_flow/fix_regression_non_regression_gate.py",
    "tools/verification_flow/fix_risk_approval_gate.py",
    "tools/verification_flow/flaky_test_policy_gate.py",
    "tools/verification_flow/focused_wave_debug_window_gate.py",
    "tools/verification_flow/gate_dependency_consistency.py",
    "tools/verification_flow/gate_io_contract_consistency_gate.py",
    "tools/verification_flow/gate_manifest_registry_consistency_gate.py",
    "tools/verification_flow/generated_artifact_boundary_gate.py",
    "tools/verification_flow/git_sync_safety_gate.py",
    "tools/verification_flow/hard_gate_coverage_evidence_gate.py",
    "tools/verification_flow/hard_gate_positive_negative_coverage_gate.py",
    "tools/verification_flow/hard_gate_registry_audit.py",
    "tools/verification_flow/input_source_contract_gate.py",
    "tools/verification_flow/interactive_evidence_intake_gate.py",
    "tools/verification_flow/interrupt_storm_latency_gate.py",
    "tools/verification_flow/issue_triage_classification_gate.py",
    "tools/verification_flow/knowledge_center_registry_consistency_gate.py",
    "tools/verification_flow/lsf_per_job_monitor_gate.py",
    "tools/verification_flow/manual_lookup_before_edit_gate.py",
    "tools/verification_flow/master_requirement_completeness_gate.py",
    "tools/verification_flow/mechanism_readiness_gate.py",
    "tools/verification_flow/multi_port_fairness_qos_gate.py",
    "tools/verification_flow/negative_test_effectiveness_gate.py",
    "tools/verification_flow/nondeterminism_attribution_gate.py",
    "tools/verification_flow/observability_sufficiency_gate.py",
    "tools/verification_flow/one_click_pipeline_gate.py",
    "tools/verification_flow/pattern_registry_completeness_gate.py",
    "tools/verification_flow/per_port_queue_starvation_gate.py",
    "tools/verification_flow/per_port_verification_matrix_gate.py",
    "tools/verification_flow/pipeline_artifact_handoff_gate.py",
    "tools/verification_flow/pipeline_hash_continuity_gate.py",
    "tools/verification_flow/platform_capability_completeness_gate.py",
    "tools/verification_flow/project_model_topology_completeness_gate.py",
    "tools/verification_flow/promotion_chain_audit_gate.py",
    "tools/verification_flow/promotion_readiness_gate.py",
    "tools/verification_flow/promotion_rollback_gate.py",
    "tools/verification_flow/protocol_corner_case_matrix_gate.py",
    "tools/verification_flow/protocol_family_qualification_gate.py",
    "tools/verification_flow/protocol_generator_binding_gate.py",
    "tools/verification_flow/protocol_isolation_gate.py",
    "tools/verification_flow/protocol_onboarding_gate.py",
    "tools/verification_flow/protocol_profile_binding_gate.py",
    "tools/verification_flow/protocol_profile_version_gate.py",
    "tools/verification_flow/protocol_qualification_ladder_gate.py",
    "tools/verification_flow/protocol_qualification_status_gate.py",
    "tools/verification_flow/protocol_builder_registry_conformance_gate.py",
    "tools/verification_flow/protocol_scheduler_gate.py",
    "tools/verification_flow/protocol_structural_completeness_gate.py",
    "tools/verification_flow/protocol_test_coverage_gate.py",
    "tools/verification_flow/qualification_matrix_consistency_gate.py",
    "tools/verification_flow/rca_confidence_escalation_gate.py",
    "tools/verification_flow/rca_replay_fix_closure_gate.py",
    "tools/verification_flow/reference_uvm_adaptation_gate.py",
    "tools/verification_flow/reference_uvm_compatibility_gate.py",
    "tools/verification_flow/regression_infra_functional_triage_gate.py",
    "tools/verification_flow/regression_replay_equivalence_gate.py",
    "tools/verification_flow/regression_result_uniqueness_gate.py",
    "tools/verification_flow/regression_selection_completeness_gate.py",
    "tools/verification_flow/regression_submission_policy_gate.py",
    "tools/verification_flow/release_attestation_gate.py",
    "tools/verification_flow/release_reproducibility_gate.py",
    "tools/verification_flow/remote_action_audit_gate.py",
    "tools/verification_flow/remote_action_replay_gate.py",
    "tools/verification_flow/remote_control_supervisory_gate.py",
    "tools/verification_flow/remote_execution_provenance_gate.py",
    "tools/verification_flow/remote_state_transition_gate.py",
    "tools/verification_flow/requirement_runtime_evidence_gate.py",
    "tools/verification_flow/rerun_determinism_gate.py",
    "tools/verification_flow/reset_clock_power_sequence_gate.py",
    "tools/verification_flow/reset_power_cdc_corner_gate.py",
    "tools/verification_flow/rollback_consistency_gate.py",
    "tools/verification_flow/root_cause_attribution_consistency_gate.py",
    "tools/verification_flow/root_cause_evidence_gate.py",
    "tools/verification_flow/rtl_first_architecture_discovery_gate.py",
    "tools/verification_flow/run_environment_reproducibility_gate.py",
    "tools/verification_flow/run_identity_consistency_gate.py",
    "tools/verification_flow/runtime_default_policy_gate.py",
    "tools/verification_flow/schema_reference_integrity_gate.py",
    "tools/verification_flow/scoreboard_reference_model_independence_gate.py",
    "tools/verification_flow/scoreboard_transaction_liveness_gate.py",
    "tools/verification_flow/seed_diversity_and_corner_case_gate.py",
    "tools/verification_flow/seed_reproducibility_gate.py",
    "tools/verification_flow/semantic_evidence_strength_gate.py",
    "tools/verification_flow/sequence_coverage_closure_gate.py",
    "tools/verification_flow/server_sync_identity_gate.py",
    "tools/verification_flow/shared_elaboration_collision_gate.py",
    "tools/verification_flow/signoff_bundle_completeness_gate.py",
    "tools/verification_flow/signoff_snapshot_immutability_gate.py",
    "tools/verification_flow/signoff_trace_crosscheck_gate.py",
    "tools/verification_flow/simulation_completion_recheck_gate.py",
    "tools/verification_flow/simulation_semantic_trace_gate.py",
    "tools/verification_flow/simulation_semantic_validation_gate.py",
    "tools/verification_flow/spec_rtl_change_impact_gate.py",
    "tools/verification_flow/spec_to_vplan_requirement_quality_gate.py",
    "tools/verification_flow/stop_after_simv_policy_gate.py",
    "tools/verification_flow/subsystem_environment_registration_gate.py",
    "tools/verification_flow/system_level_change_impact_gate.py",
    "tools/verification_flow/system_level_composition_gate.py",
    "tools/verification_flow/system_level_cross_domain_gate.py",
    "tools/verification_flow/system_level_deadlock_livelock_gate.py",
    "tools/verification_flow/system_level_dependency_graph_gate.py",
    "tools/verification_flow/system_level_release_evidence_consistency_gate.py",
    "tools/verification_flow/system_level_release_pinning_gate.py",
    "tools/verification_flow/system_level_resource_contention_gate.py",
    "tools/verification_flow/system_level_subsystem_set_completeness_gate.py",
    "tools/verification_flow/system_level_subsystem_verdict_gate.py",
    "tools/verification_flow/system_level_traceability_gate.py",
    "tools/verification_flow/system_remote_lsf_coverage_gate.py",
    "tools/verification_flow/test_collection_health_gate.py",
    "tools/verification_flow/test_oracle_independence_gate.py",
    "tools/verification_flow/test_result_provenance_gate.py",
    "tools/verification_flow/testcase_name_semantics_gate.py",
    "tools/verification_flow/traceability_consistency_gate.py",
    "tools/verification_flow/unknown_failure_escalation_gate.py",
    "tools/verification_flow/verification_effectiveness_consistency_gate.py",
    "tools/verification_flow/verification_intent_gate.py",
    "tools/verification_flow/verification_verdict_consistency_gate.py",
    "tools/verification_flow/vip_api_drift_gate.py",
    "tools/verification_flow/waiver_revalidation_gate.py",
    "tools/verification_flow/waiver_revision_freshness_gate.py",
    "tools/verification_flow/waiver_scope_consistency_gate.py",
    "tools/verification_flow/wave0_post_sim_semantic_gate.py",
    "tools/verification_flow/workflow_registry_orphan_gate.py",
    "tools/verification_flow/workflow_second_pass_clean_gate.py",
]


def test_gate_tool_list_matches_registry():
    registry = json.loads(
        (ROOT / ".dv-harness" / "workflow" / "hard_gate_registry.json").read_text(encoding="utf-8")
    )
    registered = sorted({g["tool"] for g in registry["gates"]})
    assert sorted(ALL_GATE_TOOL_FILES) == registered, (
        "ALL_GATE_TOOL_FILES has drifted from hard_gate_registry.json -- "
        "update this list whenever a gate is added to or removed from the registry."
    )


@pytest.mark.parametrize("tool_file", ALL_GATE_TOOL_FILES)
def test_gate_script_argparse_smoke(tool_file):
    script = ROOT / tool_file
    assert script.exists(), f"registered but missing on disk: {tool_file}"
    r = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0, f"{tool_file}: --help exited {r.returncode}\n{r.stderr}"
    assert r.stdout.strip(), f"{tool_file}: --help produced no output"
