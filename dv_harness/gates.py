from __future__ import annotations
import json, re, subprocess, sys, tempfile, time
from pathlib import Path
from typing import Any, Dict
from .config import load_config
from .memory import CornerCaseLibrary
from .control_plane import ControlPlane

TOOLS_DIR = "tools/verification_flow"


# --- multi-flag gate support -------------------------------------------------
# A STAGE_GATES tuple's third element is either a bare str (the original,
# unchanged one-flag contract: cli_flag names the single CLI arg, payload is
# the whole evidence-block dict, JSON-dumped to one temp file) or a
# tuple/list of EvidenceFlag/ContextFlag specs (a multi-flag gate: the same
# single evidence block's JSON body is a dict-of-sub-payloads, one key per
# EvidenceFlag, materialized into multiple CLI args on one script invocation).
class EvidenceFlag:
    """A CLI flag whose value is agent-attested. `key` selects a sub-key out
    of the ONE ```dv-harness-evidence:<gate_id>``` fenced block this gate
    already gets (payload becomes {key: <sub-payload>, ...} for multi-flag
    gates instead of a flat dict) -- no new fence syntax, no regex change.
    kind="file" (default): sub-value must be a dict; JSON-dumped to a temp
      file, `<flag> <tmp_path>` passed (identical mechanics to today).
    kind="raw": sub-value must be a scalar; passed as `<flag> <str(value)>`,
      no temp file -- for scripts whose argparse flag is a scalar, e.g.
      waiver_revalidation_gate's --current-revision."""
    __slots__ = ("flag", "key", "kind")

    def __init__(self, flag, key, kind="file"):
        self.flag, self.key, self.kind = flag, key, kind


class ContextFlag:
    """A CLI flag the HARNESS supplies directly -- never trusted from agent
    text, because the check's own semantics need an independently-known
    truth an agent could otherwise spoof (real repo root; true wall-clock
    time). provider(root) -> value, called fresh every run_gate() call.
    kind mirrors EvidenceFlag's; default 'raw' (both current uses are)."""
    __slots__ = ("flag", "provider", "kind")

    def __init__(self, flag, provider, kind="raw"):
        self.flag, self.provider, self.kind = flag, provider, kind


class _MissingSubpayload(Exception):
    def __init__(self, key):
        super().__init__(key)
        self.key = key


# Every (gate_id, script, cli_flag) below is an EXISTING, already-registered
# script under tools/verification_flow/ (see .dv-harness/workflow/hard_gate_registry.json).
# They were never invoked by the engine before this module -- this is the
# missing wire, not a new validator. Each gate only checks internal
# consistency/completeness of the JSON the agent supplies; it cannot itself
# prove the JSON is truthful. Closing that requires the agent to have done
# real Read/Grep/PowerShell evidence-gathering before it writes the block.
STAGE_GATES = {
    "ENV_CHECK": [
        ("execution_mode_validator", "../real_env/execution_mode_validator.py", "--request"),
    ],
    "INTAKE": [
        ("intake_readiness", "../vplan/intake_readiness.py", "--intake"),
        ("generated_artifact_boundary_gate", "generated_artifact_boundary_gate.py", "--inventory"),
        ("interactive_evidence_intake_gate", "interactive_evidence_intake_gate.py", "--state"),
        # NEW (2026-09-01, de-local-sim-env-intake design pass): additive --
        # closes the previously-zero schema/code gap for DE-local-simulation-
        # environment intake (compile/run/filelist/env-setup scripts a
        # project may already have). OPTIONAL/non-blocking -- see the
        # script's own module docstring RULING for why the agent must always
        # emit this evidence block (using "{}" when not applicable) and how
        # that stays a genuine no-op PASS for projects with no pre-existing
        # DE-local environment.
        ("de_local_sim_env_intake_gate", "de_local_sim_env_intake_gate.py", "--intake"),
    ],
    "DE_BASELINE_REPRODUCTION": [
        ("de_baseline_reproduction_gate", "de_baseline_reproduction_gate.py", "--baseline"),
    ],
    "ARCH_DISCOVERY": [
        ("rtl_first_architecture_discovery_gate", "rtl_first_architecture_discovery_gate.py", "--state"),
    ],
    "ARCH_CALIBRATION": [
        ("architecture_calibration_gate", "architecture_calibration_gate.py", "--calibration"),
        ("architecture_calibration_conflict_gate", "architecture_calibration_conflict_gate.py", "--calibration"),
        ("vip_api_drift_gate", "vip_api_drift_gate.py", "--vip"),
    ],
    "REQUIREMENTS_TRACEABILITY": [
        ("spec_to_vplan_requirement_quality_gate", "spec_to_vplan_requirement_quality_gate.py", "--requirements"),
        ("waiver_scope_consistency_gate", "waiver_scope_consistency_gate.py", "--waivers"),
        ("waiver_revision_freshness_gate", "waiver_revision_freshness_gate.py", "--state"),
        ("waiver_revalidation_gate", "waiver_revalidation_gate.py", (
            EvidenceFlag("--waivers", "waivers"),
            ContextFlag("--now", lambda root: __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat()),
            EvidenceFlag("--current-revision", "current_revision", kind="raw"),
        )),
    ],
    "SOC_SCENARIO_PLANNER": [
        ("corner_risk_rank", "../senior_dv/corner_risk_rank.py", "--cases"),
        ("reset_power_cdc_corner_gate", "reset_power_cdc_corner_gate.py", "--plan"),
    ],
    "VPLAN": [
        ("spec_coverage_audit", "../vplan/spec_coverage_audit.py", "--vplan"),
        # NEW (2026-09-01, vplan-doc-and-wiring-fix): spec_coverage_audit above
        # checks a structurally different, incompatible JSON schema
        # (requirements[] with VERIFIED/WAIVED/NOT_APPLICABLE status) and never
        # calls the real dv_harness.vplan_writer.validate_items(). This second
        # gate closes that gap by calling validate_items()/build_evidence_
        # context() directly against real pattern-dir/dispatcher-file/task-
        # declaration-source evidence on disk -- the same real evidence
        # discipline `dv-harness vplan-export` itself uses. See
        # tools/vplan/vplan_writer_validation_gate.py's header for the full
        # rationale and why its JSON payload shape is not an invented schema.
        ("vplan_writer_validation_gate", "../vplan/vplan_writer_validation_gate.py", "--vplan-validation"),
    ],
    "VERIFICATION_ARCHITECTURE": [
        ("mechanism_readiness_gate", "mechanism_readiness_gate.py", "--plan"),
        ("fabric_topology_completeness_gate", "fabric_topology_completeness_gate.py", "--topology"),
        ("protocol_structural_completeness_gate", "protocol_structural_completeness_gate.py", "--protocol-topology"),
        ("branch_fw_interrupt_contract_gate", "branch_fw_interrupt_contract_gate.py", "--fw"),
        ("branch_topology_gate", "branch_topology_gate.py", "--topology"),
        ("error_injection_coverage_gate", "error_injection_coverage_gate.py", "--plan"),
        ("observability_sufficiency_gate", "observability_sufficiency_gate.py", "--plan"),
        # NEW (2026-09-01, checker-sva-generator task): observability_sufficiency_gate
        # above only requires a requirement to NAME an ASSERTION/CHECKER
        # evidence_point -- it cannot tell a real, DSL-generated assertion
        # apart from one still carrying the ASSERTION branch's own
        # `1'b1; // TODO` placeholder (tools/observability/
        # generate_observability_plan.py, before this task's
        # state_machine_checks DSL wiring). This gate closes that one
        # specific remaining gap -- see
        # tools/verification_flow/assertion_placeholder_closure_gate.py's
        # own header for the full rationale and its deliberately narrow
        # scope (only requirements the planner itself classified
        # PROTOCOL_STATE_MACHINE_LEGALITY are checked; hand-authored
        # INTERRUPT_RESPONSE_SEMANTIC/CROSS_CYCLE_TEMPORAL_INVARIANT
        # assertions are untouched, per .work/checker-sva-generator-design-
        # report.md's own scope boundary). Placed in this same
        # VERIFICATION_ARCHITECTURE stage as observability_sufficiency_gate
        # per that design report's own ruling (keep the two adjacent).
        ("assertion_placeholder_closure_gate", "assertion_placeholder_closure_gate.py", "--implementation"),
        ("per_port_verification_matrix_gate", "per_port_verification_matrix_gate.py", "--matrix"),
        ("protocol_scheduler_gate", "protocol_scheduler_gate.py", "--scheduler"),
        ("reference_uvm_adaptation_gate", "reference_uvm_adaptation_gate.py", "--adaptation"),
        ("reference_uvm_compatibility_gate", "reference_uvm_compatibility_gate.py", "--reference"),
        ("reset_clock_power_sequence_gate", "reset_clock_power_sequence_gate.py", "--sequence"),
        ("scoreboard_reference_model_independence_gate", "scoreboard_reference_model_independence_gate.py", "--model"),
    ],
    "IMPLEMENT": [
        ("traceability_consistency_gate", "traceability_consistency_gate.py", "--trace"),
        ("checker_independence_gate", "checker_independence_gate.py", "--checking"),
        ("testcase_name_semantics_gate", "testcase_name_semantics_gate.py", "--tests"),
        ("verification_intent_gate", "verification_intent_gate.py", "--intent"),
        ("pattern_registry_completeness_gate", "pattern_registry_completeness_gate.py", "--registry"),
        ("manual_lookup_before_edit_gate", "manual_lookup_before_edit_gate.py", "--edit"),
        ("protocol_isolation_gate", "protocol_isolation_gate.py", "--edit"),
        # ADDED (2026-09-02, RTL-write-scope-guard gap-closure pass): the
        # only real enforcement that ever stopped the harness from writing
        # DUT/VIP RTL was a hand-added .claude/settings.json Edit-tool deny
        # rule for one project's hardcoded paths -- nothing in dv_harness
        # itself checked what an IMPLEMENT edit actually touched. This gate
        # reads the agent-attested `touched_paths` list (every file path the
        # edit touched) against the real project's rtl_protection.
        # protected_paths (dv_harness/config.py) and FAILs
        # RTL_WRITE_SCOPE_VIOLATION if any of them lands under a protected
        # DUT/VIP root. --root is a ContextFlag (harness-supplied real
        # project root), same convention as feature_continuity_gate/
        # deep_rca_evidence_gate above -- an agent cannot point the check at
        # a fabricated root to dodge it.
        ("rtl_write_scope_guard_gate", "rtl_write_scope_guard_gate.py", (
            EvidenceFlag("--edit", "edit"),
            ContextFlag("--root", lambda root: str(root)),
        )),
    ],
    "VERIFY": [
        ("simulation_semantic_validation_gate", "simulation_semantic_validation_gate.py", "--input"),
        ("test_result_provenance_gate", "test_result_provenance_gate.py", "--results"),
        ("false_pass_resistance_gate", "false_pass_resistance_gate.py", "--proof"),
        ("checker_semantic_trace_consistency_gate", "checker_semantic_trace_consistency_gate.py", "--trace"),
        ("command_intent_semantic_closure_gate", "command_intent_semantic_closure_gate.py", "--closure"),
        ("expected_data_provenance_gate", "expected_data_provenance_gate.py", "--scoreboards"),
        ("false_pass_false_fail_arbitration_gate", "false_pass_false_fail_arbitration_gate.py", "--input"),
        ("interrupt_storm_latency_gate", "interrupt_storm_latency_gate.py", "--interrupts"),
        ("multi_port_fairness_qos_gate", "multi_port_fairness_qos_gate.py", "--ports"),
        ("negative_test_effectiveness_gate", "negative_test_effectiveness_gate.py", "--evidence"),
        ("per_port_queue_starvation_gate", "per_port_queue_starvation_gate.py", "--queues"),
        ("remote_execution_provenance_gate", "remote_execution_provenance_gate.py", "--provenance"),
        ("rerun_determinism_gate", "rerun_determinism_gate.py", "--reruns"),
        ("run_environment_reproducibility_gate", "run_environment_reproducibility_gate.py", "--run"),
        ("scoreboard_transaction_liveness_gate", "scoreboard_transaction_liveness_gate.py", "--scoreboard"),
        ("semantic_evidence_strength_gate", "semantic_evidence_strength_gate.py", "--evidence"),
        ("simulation_completion_recheck_gate", "simulation_completion_recheck_gate.py", "--state"),
        ("simulation_semantic_trace_gate", "simulation_semantic_trace_gate.py", "--result"),
        ("test_oracle_independence_gate", "test_oracle_independence_gate.py", "--oracles"),
        ("wave0_post_sim_semantic_gate", "wave0_post_sim_semantic_gate.py", "--result"),
    ],
    "REGRESSION_MONITOR": [
        ("lsf_per_job_monitor_gate", "lsf_per_job_monitor_gate.py", "--jobs"),
        ("regression_result_uniqueness_gate", "regression_result_uniqueness_gate.py", "--results"),
        ("run_identity_consistency_gate", "run_identity_consistency_gate.py", "--bundle"),
        ("cross_run_evidence_consistency_gate", "cross_run_evidence_consistency_gate.py", "--runs"),
        ("flaky_test_policy_gate", "flaky_test_policy_gate.py", "--flaky"),
        ("seed_diversity_and_corner_case_gate", "seed_diversity_and_corner_case_gate.py", "--campaign"),
        ("seed_reproducibility_gate", "seed_reproducibility_gate.py", "--runs"),
    ],
    "FAILURE_RECOVERY": [
        ("failure_attribution", "../senior_dv/failure_attribution.py", "--trace"),
        ("failure_signature_recurrence_gate", "failure_signature_recurrence_gate.py", "--failures"),
        ("issue_triage_classification_gate", "issue_triage_classification_gate.py", "--issue"),
        ("unknown_failure_escalation_gate", "unknown_failure_escalation_gate.py", "--failure"),
        # ADDED (targeted-wave-debug-window-recovery-wiring, 2026-09-02):
        # focused_wave_debug_window_gate was the one gate that precisely
        # enforces CLAUDE.md's "First-Failure Waveform Rerun" (targeted,
        # minimal-window waveform cut near the first failure, user-confirmed
        # dump scope) but was wired ONLY to WAVE_ANALYSIS -- reachable only
        # from VERIFY's PASS edge in main_graph.json, a pre-batch
        # representative-testcase flow. FAILURE_RECOVERY is the real
        # post-batch-failure debug path (VERIFY/BUILD_DEBUG/INFRA_RECOVERY's
        # FAIL edges all land here) and had NO gate at all checking a
        # targeted waveform rerun performed during failure debugging --
        # added here so that path is validated by the same precise
        # window/scope check regardless of which graph edge led into it.
        # Made this genuinely usable as an always-mandatory FAILURE_RECOVERY
        # gate (unlike WAVE_ANALYSIS, not every failure here needs a
        # waveform -- CLAUDE.md's own "escalate evidence cost gradually,
        # don't jump to FSDB" rule) by adding a real escape hatch to the
        # script itself: an explicit deep_debug_required=false PASSes when
        # paired with a non-empty deep_debug_not_required_reason, same
        # "<x>_applicable:false + reason" shape already used by
        # fabric_topology_completeness_gate and friends.
        ("focused_wave_debug_window_gate", "focused_wave_debug_window_gate.py", "--rerun"),
    ],
    "COVERAGE_CLOSURE": [
        ("coverage_signoff_verdict_gate", "coverage_signoff_verdict_gate.py", "--state"),
        ("coverage_credit_consistency_gate", "coverage_credit_consistency_gate.py", "--coverage"),
        ("coverage_quality_gate", "coverage_quality_gate.py", "--coverage"),
        ("coverage_hole_regeneration_gate", "coverage_hole_regeneration_gate.py", "--holes"),
        ("coverage_hole_to_test_generation_gate", "coverage_hole_to_test_generation_gate.py", "--holes"),
        ("assertion_vacuity_and_reachability_gate", "assertion_vacuity_and_reachability_gate.py", "--assertions"),
        ("assertion_vacuity_gate", "assertion_vacuity_gate.py", "--assertions"),
        ("coverage_checker_linkage_gate", "coverage_checker_linkage_gate.py", "--coverage"),
        ("coverage_credit_revocation_gate", "coverage_credit_revocation_gate.py", "--coverage"),
        ("coverage_credit_source_integrity_gate", "coverage_credit_source_integrity_gate.py", "--coverage"),
        ("coverage_failure_state_linkage_gate", "coverage_failure_state_linkage_gate.py", "--state"),
        ("coverage_regression_drift_gate", "coverage_regression_drift_gate.py", "--coverage"),
        ("protocol_corner_case_matrix_gate", "protocol_corner_case_matrix_gate.py", "--matrix"),
        ("sequence_coverage_closure_gate", "sequence_coverage_closure_gate.py", "--coverage"),
        ("verification_effectiveness_consistency_gate", "verification_effectiveness_consistency_gate.py", "--state"),
    ],
    "RE_AUDIT": [
        ("root_cause_evidence_gate", "root_cause_evidence_gate.py", "--root-cause"),
        ("rca_replay_fix_closure_gate", "rca_replay_fix_closure_gate.py", "--closure"),
        ("deep_rca_evidence_gate", "deep_rca_evidence_gate.py", (
            EvidenceFlag("--rca", "rca"),
            # Harness-supplied real project root (2026-09-02, RE_AUDIT
            # evidence-gate audit follow-up) -- never agent-attested, so an
            # agent's evidence_sources[].evidence_path can't be pointed at a
            # fabricated tree. Same ContextFlag("--root", ...) convention as
            # feature_continuity_gate/protocol_builder_registry_conformance_gate.
            ContextFlag("--root", lambda root: str(root)),
        )),
        ("dut_request_record_gate", "dut_request_record_gate.py", "--record"),
        ("fix_effectiveness_gate", "fix_effectiveness_gate.py", "--fix"),
        ("fix_regression_non_regression_gate", "fix_regression_non_regression_gate.py", "--closure"),
        ("fix_risk_approval_gate", "fix_risk_approval_gate.py", "--plan"),
        ("nondeterminism_attribution_gate", "nondeterminism_attribution_gate.py", "--analysis"),
        ("rca_confidence_escalation_gate", "rca_confidence_escalation_gate.py", "--rca"),
        ("regression_replay_equivalence_gate", "regression_replay_equivalence_gate.py", "--replay"),
        ("root_cause_attribution_consistency_gate", "root_cause_attribution_consistency_gate.py", "--rca"),
    ],
    "SYSTEM_LEVEL": [
        ("system_level_subsystem_verdict_gate", "system_level_subsystem_verdict_gate.py", "--system"),
        ("system_level_traceability_gate", "system_level_traceability_gate.py", "--trace"),
        ("system_level_validator", "../real_env/system_level_validator.py", (
            EvidenceFlag("--registry", "registry"),
            # BUG FIX (2026-08-28, plan-subsystem-registry design pass): the
            # real persisted subsystem registry (written by
            # engine.py's _persist_subsystem_registry_entry on a real
            # SIGNOFF PASS) -- harness-supplied, never agent-attested, so an
            # agent cannot spoof "this subsystem was already registered".
            # Converted from single-flag to multi-flag ONLY to add this
            # ContextFlag; the agent-supplied payload shape for the
            # "registry" sub-key is otherwise byte-identical to what
            # --registry used to receive directly.
            ContextFlag("--registered", lambda root: str(
                root / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json")),
        )),
        ("system_level_subsystem_set_completeness_gate", "system_level_subsystem_set_completeness_gate.py", "--subsystem-set"),
        ("cross_domain_evidence_bundle_gate", "cross_domain_evidence_bundle_gate.py", "--bundle"),
        ("cross_protocol_scenario_gate", "cross_protocol_scenario_gate.py", "--scenarios"),
        ("system_level_change_impact_gate", "system_level_change_impact_gate.py", "--impact"),
        ("system_level_composition_gate", "system_level_composition_gate.py", "--composition"),
        ("system_level_cross_domain_gate", "system_level_cross_domain_gate.py", "--plan"),
        ("system_level_deadlock_livelock_gate", "system_level_deadlock_livelock_gate.py", "--analysis"),
        ("system_level_dependency_graph_gate", "system_level_dependency_graph_gate.py", "--graph"),
        ("system_level_release_evidence_consistency_gate", "system_level_release_evidence_consistency_gate.py", "--system"),
        ("system_level_release_pinning_gate", "system_level_release_pinning_gate.py", "--composition"),
        ("system_level_resource_contention_gate", "system_level_resource_contention_gate.py", "--plan"),
    ],
    "EXPERT_FEEDBACK_LOOP": [
        ("expert_feedback_closure_gate", "expert_feedback_closure_gate.py", "--feedback"),
        ("experience_knowledge_gate", "experience_knowledge_gate.py", "--knowledge"),
        ("experience_applicability_gate", "experience_applicability_gate.py", (
            EvidenceFlag("--knowledge", "knowledge"),
            EvidenceFlag("--context", "context"),
        )),
    ],
    "REQUIREMENT_CLOSURE": [
        ("master_requirement_completeness_gate", "master_requirement_completeness_gate.py", "--matrix"),
        ("requirement_runtime_evidence_gate", "requirement_runtime_evidence_gate.py", "--trace"),
        ("execution_evidence_gate", "execution_evidence_gate.py", "--closure"),
        ("end_to_end_trace_chain_gate", "end_to_end_trace_chain_gate.py", "--trace"),
        ("traceability_audit", "../vplan/traceability_audit.py", (
            EvidenceFlag("--vplan", "vplan"),
            EvidenceFlag("--tests", "tests"),
        )),
    ],
    "PROMOTION_READINESS": [
        ("promotion_readiness_gate", "promotion_readiness_gate.py", "--state"),
        ("promotion_chain_audit_gate", "promotion_chain_audit_gate.py", "--audit"),
        ("closed_loop_promotion_gate", "closed_loop_promotion_gate.py", "--state"),
        ("promotion_rollback_gate", "promotion_rollback_gate.py", "--state"),
        ("qualification_matrix_consistency_gate", "qualification_matrix_consistency_gate.py", "--matrix"),
        ("release_reproducibility_gate", "release_reproducibility_gate.py", "--release"),
        ("rollback_consistency_gate", "rollback_consistency_gate.py", "--state"),
        ("feature_continuity_gate", "feature_continuity_gate.py", (
            ContextFlag("--root", lambda root: str(root)),
            EvidenceFlag("--required", "required"),
        )),
    ],
    "SIGNOFF": [
        ("false_pass_resistance_gate", "false_pass_resistance_gate.py", "--proof"),
        ("signoff_bundle_completeness_gate", "signoff_bundle_completeness_gate.py", "--bundle"),
        ("evidence_bundle_run_consistency_gate", "evidence_bundle_run_consistency_gate.py", "--bundle"),
        ("evidence_freshness_gate", "evidence_freshness_gate.py", "--evidence"),
        ("release_attestation_gate", "release_attestation_gate.py", "--attestation"),
        ("signoff_snapshot_immutability_gate", "signoff_snapshot_immutability_gate.py", "--snapshot"),
        ("signoff_trace_crosscheck_gate", "signoff_trace_crosscheck_gate.py", "--signoff"),
        ("verification_verdict_consistency_gate", "verification_verdict_consistency_gate.py", "--verdict"),
        ("subsystem_environment_registration_gate", "subsystem_environment_registration_gate.py", "--entry"),
    ],
    # --- Mass-wiring pass (2026-08-28, unwired-hard-gate catalog workflow):
    # 96 of 122 registered-but-never-invoked gate scripts under
    # tools/verification_flow/ were independently read, executed against
    # constructed pass/fail payloads, and stage-classified by 11 parallel
    # cataloging agents (see .dv-harness/workflow/hard_gate_registry.json
    # for the full original registry). All entries below were verified by
    # actual execution, not just read. 1 of the 97 originally-verified
    # candidates (runtime_default_policy_gate) was deliberately excluded --
    # its PASS branch requires WAVE=1/full-depth FSDB dumping by default,
    # the literal opposite of CLAUDE.md's 'Simulation Observability
    # Default: FSDB OFF' rule; it needs human reconciliation with that
    # policy before it can be wired, not a silent placement decision. 9
    # more (agent_skill_binding_gate and 8 similar) need a run_gate()
    # extension for multi-input/non-JSON-evidence contracts and were not
    # attempted here. 16 more were judged not stage-appropriate (pure
    # meta/registry-consistency checks, e.g. gate_manifest_registry_
    # consistency_gate) and were left out of STAGE_GATES entirely.
    "BUILD": [
        ("shared_elaboration_collision_gate", "shared_elaboration_collision_gate.py", "--state"),
        ("stop_after_simv_policy_gate", "stop_after_simv_policy_gate.py", "--build"),
        ("remote_execution_provenance_gate", "remote_execution_provenance_gate.py", "--provenance"),
    ],
    "CHANGE_IMPACT": [
        ("artifact_dependency_closure_gate", "artifact_dependency_closure_gate.py", "--graph"),
        ("spec_rtl_change_impact_gate", "spec_rtl_change_impact_gate.py", (
            EvidenceFlag("--impact", "impact"),
            # BUG FIX (2026-08-28, audit-impact-arbitration-naming): a real,
            # harness-globbed enumeration of every command.txt under the
            # project -- never agent-attested -- so an agent's own impact
            # analysis cannot silently omit one from the triage set.
            ContextFlag("--command-txt-root", lambda root: str(root)),
        )),
    ],
    "COMMAND_PATTERN": [
        ("command_migration_integrity_gate", "command_migration_integrity_gate.py", "--migration"),
    ],
    "DISCOVERY": [
        ("evidence_source_priority_gate", "evidence_source_priority_gate.py", "--trace"),
        ("input_source_contract_gate", "input_source_contract_gate.py", "--contract"),
    ],
    "GIT_PUSH": [
        ("workflow_second_pass_clean_gate", "workflow_second_pass_clean_gate.py", "--closure"),
    ],
    "INFRASTRUCTURE_AUDIT": [
        ("environment_readiness_status_gate", "environment_readiness_status_gate.py", "--readiness"),
    ],
    "PROTOCOL_CAPABILITY": [
        ("protocol_generator_binding_gate", "protocol_generator_binding_gate.py", "--binding"),
        ("protocol_profile_binding_gate", "protocol_profile_binding_gate.py", "--binding"),
        ("protocol_onboarding_gate", "protocol_onboarding_gate.py", "--profile"),
        ("protocol_profile_version_gate", "protocol_profile_version_gate.py", "--profile"),
        ("protocol_qualification_status_gate", "protocol_qualification_status_gate.py", "--status"),
        # BUG FIX (2026-08-28, plan-protocol-registry-crosscheck design pass):
        # .dv-harness/builder/protocol_builder_registry.json's per-protocol
        # discover/build checklists were real content agents were meant to
        # read and follow, but nothing ever cross-checked whether they
        # actually did -- this closes that. --registry-root is
        # harness-supplied (never agent-attested) so an agent cannot spoof
        # its own checklist by pointing the gate at a fabricated registry.
        ("protocol_builder_registry_conformance_gate", "protocol_builder_registry_conformance_gate.py", (
            ContextFlag("--registry-root", lambda root: str(root)),
            EvidenceFlag("--profile", "profile"),
        )),
    ],
    "WAVE_ANALYSIS": [
        ("focused_wave_debug_window_gate", "focused_wave_debug_window_gate.py", "--rerun"),
    ],
    # --- 7-ungated-stage closure pass (2026-08-28, hard-gate-wiring investigation
    # follow-up): STAGE_GATES had exactly 7 Stage enum values with no entry at
    # all (BUILD_DEBUG, GIT_SYNC, INFRA_RECOVERY, PROJECT_MODEL, REGRESSION,
    # REGRESSION_SELECT, SERVER_SYNC) -- unlike every gap documented elsewhere in
    # this file, none of them had a prior "leave ungated, reason X" decision
    # anywhere in this header. All 30 registered-but-unwired gates in
    # .dv-harness/workflow/hard_gate_registry.json were checked against these 7
    # stages first; none fit (they are all harness-self-audit/meta-consistency,
    # remote-control-mode, or protocol-catalog concerns for other stages) so all
    # 7 below are net-new scripts, each independently executed against
    # constructed PASS/FAIL payloads before being wired here.
    "BUILD_DEBUG": [
        ("build_failure_triage_gate", "build_failure_triage_gate.py", "--triage"),
    ],
    "GIT_SYNC": [
        ("git_sync_safety_gate", "git_sync_safety_gate.py", "--sync"),
    ],
    "INFRA_RECOVERY": [
        ("regression_infra_functional_triage_gate", "regression_infra_functional_triage_gate.py", "--triage"),
    ],
    "PROJECT_MODEL": [
        ("project_model_topology_completeness_gate", "project_model_topology_completeness_gate.py", "--model"),
        # ADDED (2026-09-01, route-skill-resolver-dynamic-implementation
        # task): closes dashboard.py's own documented
        # "no stage, no gate, no writer" gap for the environment_mode_
        # selection evidence block -- see environment_mode_selection_gate.py's
        # own header for the RULING on placing it here (PROJECT_MODEL
        # already establishes verification_boundary/topology, one stage
        # before PROTOCOL_CAPABILITY's per-protocol discovery) and why the
        # gate re-derives its check independently rather than importing
        # dv_harness.environment_mode_router. Deliberately single-flag (like
        # execution_mode_validator.py), not a ContextFlag-carrying multi-flag
        # gate: dashboard.py's _environment_mode_selected() reads
        # payload.get("environment_mode") directly off this SAME evidence
        # block with no sub-key nesting, so the agent-supplied JSON must stay
        # flat -- the gate instead reads the real subsystem registry itself,
        # relative to its own cwd (run_gate() always subprocess.run()s with
        # cwd=str(root), harness-controlled, never agent-attested, the exact
        # same trust boundary a ContextFlag would give it).
        #
        # gate_id is "environment_mode_selection" (NOT "..._gate", unlike
        # every other entry in this table where gate_id == script filename
        # stem) deliberately: this is the ONE evidence-block fence label
        # dashboard.py's pre-existing _environment_mode_selected() already
        # scans for (payload.get("environment_mode") on a block keyed
        # exactly "environment_mode_selection") -- gate_id doubles as the
        # evidence-block lookup key in _evaluate_stage_evidence_core() below,
        # so it must match that consumer's contract exactly, independent of
        # this script's own filename.
        ("environment_mode_selection", "environment_mode_selection_gate.py", "--state"),
    ],
    "REGRESSION_SELECT": [
        ("regression_selection_completeness_gate", "regression_selection_completeness_gate.py", "--selection"),
    ],
    "REGRESSION": [
        ("regression_submission_policy_gate", "regression_submission_policy_gate.py", "--jobs"),
    ],
    "SERVER_SYNC": [
        ("server_sync_identity_gate", "server_sync_identity_gate.py", "--sync"),
    ],
}

# --- Content-driven inner ReAct loop support (2026-08-29, evidence-grounded-
# react design pass): GATE_FAILURE_REROUTE is the ONE new, deliberately small,
# human-curated table this feature adds to gates.py. It is consulted by
# dv_harness/react_loop.py's build_menu() as the highest-priority source of a
# REROUTE menu option -- a per-gate-id hint that a given gate's failure is
# best addressed by re-running an UPSTREAM stage (whose stale/wrong fact
# caused the failure) rather than blindly retrying the stage that failed.
# Same spirit as STAGE_GATES itself: real engineering knowledge an agent must
# never be allowed to invent at runtime, only ever consult. Extend this table
# per-gate as content-driven reroute targets are confirmed by real
# investigation -- never let react_loop.py's reflection call synthesize a
# reroute target itself.
GATE_FAILURE_REROUTE = {
    "vip_api_drift_gate": "ARCH_DISCOVERY",
    "architecture_calibration_conflict_gate": "ARCH_DISCOVERY",
}


# (Both items formerly logged here as "identified but not wired, unverified
# contract" are resolved: observability_sufficiency_gate is wired above in
# VERIFICATION_ARCHITECTURE. protocol_family_qualification_gate -- along with
# its two siblings protocol_qualification_ladder_gate and
# protocol_test_coverage_gate -- was investigated during the harness
# self-audit design pass (2026-08-28) and deliberately NOT moved into
# PROTOCOL_CAPABILITY's STAGE_GATES: all three hardcode a REQUIRED set of 10
# protocol families and fail unless every one has complete qualification
# evidence in the SAME payload -- whole-platform-catalog bookkeeping, not one
# DUT run's per-protocol PROTOCOL_CAPABILITY evidence (a single protocol
# builder run, e.g. USB-only, structurally cannot supply the other 9
# families' state). Same shape as platform_capability_completeness_gate and
# system_remote_lsf_coverage_gate, both already self-audit-only. All three
# run instead via dv_harness/self_audit.py -- see ALL_GATE_IDS there.)
#
# execution_mode_validator and system_level_validator were found during the
# industrial-grade deep audit (2026-08-28): both declared "hard_gate": true
# in their own policy JSON (.dv-harness/execution/mode_declaration_policy.json,
# .dv-harness/system-level/composition_policy.json) but were never wired
# anywhere -- unlike the two gates above, these looked overlooked rather than
# deliberately deferred, so they are now wired (ENV_CHECK, SYSTEM_LEVEL).
#
# intake_readiness (INTAKE), spec_coverage_audit (VPLAN), corner_risk_rank
# (SOC_SCENARIO_PLANNER), and failure_attribution (FAILURE_RECOVERY) were
# found orphaned during the orphan-integration research pass (2026-08-28) and
# wired in following the same tuple pattern. CAVEAT specific to corner_risk_rank:
# this script has no semantic pass/fail branch -- it always exits 0 on any
# structurally valid input regardless of the computed risk tier, so as wired
# it only enforces that the agent supplied well-formed evidence, not that the
# ranking itself was good. failure_attribution no longer shares this caveat
# (Tier 3 fix, 2026-08-28): it now exits 2 when the derived classification is
# UNKNOWN, so a FAILURE_RECOVERY response can no longer silently pass with an
# unresolved root cause -- see the NOTICE at the top of
# tools/senior_dv/failure_attribution.py for detail.
# coverage_hole_regeneration_gate / coverage_hole_to_test_generation_gate
# (COVERAGE_CLOSURE) and experience_knowledge_gate (EXPERT_FEEDBACK_LOOP) were
# found already implemented but unwired during the genuine-capability-gap pass
# (2026-08-28): closing "Coverage Hole Analysis" and "Experience Learning
# Loop" reused these existing scripts rather than writing new ones.
#
# traceability_audit (REQUIREMENT_CLOSURE), experience_applicability_gate
# (EXPERT_FEEDBACK_LOOP), feature_continuity_gate (PROMOTION_READINESS), and
# waiver_revalidation_gate (REQUIREMENTS_TRACEABILITY) were the four gates
# needing more than one JSON input (--vplan+--tests, --knowledge+--context,
# --root+--required, --waivers+--now+--current-revision) that the original
# one-flag run_gate() could not express. Wired 2026-08-28 via the
# EvidenceFlag/ContextFlag multi-flag extension above (see run_gate()):
# EvidenceFlag pulls a sub-key out of the gate's own single evidence block
# (payload becomes {key: <sub-payload>, ...} instead of a flat dict);
# ContextFlag supplies a harness-known value (real root path, true UTC time)
# that is never trusted from agent-authored text, closing the integrity gap
# where an agent could otherwise spoof --root or dodge WAIVER_EXPIRED by
# lying about --now. feature_continuity_gate's --required sub-payload and
# waiver_revalidation_gate's --waivers sub-payload/--current-revision are
# still agent-supplied like any other evidence field.
#
# fabric_topology_completeness_gate (VERIFICATION_ARCHITECTURE) was added
# 2026-08-28 during the AMBA4 skill-consolidation pass: no existing gate
# checked M x N scoreboard-matrix or address-map completeness for fabric-style
# (multi-master x multi-slave) environments -- mechanism_readiness_gate only
# checks that testcases reference a mechanism of a valid type, never a
# cross-product. Because VERIFICATION_ARCHITECTURE is protocol-agnostic (every
# protocol builder passes through it, not just AMBA4), this gate is a
# mandatory tuple for ALL protocols -- non-fabric flows (USB, PCIe, ...) must
# supply {"topology_applicable": false, "topology_not_applicable_reason": "..."}
# rather than silently skipping the block. See prompts.py's
# VERIFICATION_ARCHITECTURE stage text for the escape-hatch instruction.
#
# protocol_structural_completeness_gate (VERIFICATION_ARCHITECTURE) was added
# 2026-08-28 to close the same gap fabric_topology_completeness_gate closed
# for AMBA4, but for 10 more protocols (PCIe, MIPI DSI/CSI-2, Ethernet, CAN-FD,
# SD/SDIO, eMMC, eDP, UCIe, USB) at once. Each protocol's deterministic
# structural-completeness rules (LTSSM/TLP-completion/config-space for PCIe,
# VC x DT matrices for MIPI, descriptor-ring/frame-matrix for Ethernet, CAN
# arbitration/frame-format/confinement-state for CAN-FD, command x response
# tables for SD/SDIO/eMMC, link-training/AUX for eDP, LTSM/protocol-stack for
# UCIe, transfer-type x speed for USB) were each independently designed then
# adversarially verified against constructed counterexamples -- 8 of the 10
# needed a fix round after the first verify pass found real bugs, all since
# resolved and re-verified GO. Deliberately implemented as ONE dispatcher
# script keyed on a "protocol" field (CHECKERS map), not one gate per
# protocol: this stage is mandatory for every protocol builder, so N separate
# gates would force every flow to supply N-1 irrelevant escape-hatch blocks --
# the exact duplication/bloat pattern this whole audit pass has been fixing
# at the skill-file level. Non-covered protocols (or AMBA4 fabric, already
# covered by fabric_topology_completeness_gate) supply
# {"protocol_completeness_applicable": false, "protocol_completeness_not_applicable_reason": "..."}.
#
# system_level_subsystem_set_completeness_gate (SYSTEM_LEVEL) was added
# 2026-08-28: none of the three pre-existing SYSTEM_LEVEL gates (verdict-mask
# check, scenario-internal traceability, per-subsystem metadata) ever check
# whether the SET of subsystems selected for system-level composition is
# itself complete -- a subsystem the SoC actually contains could be silently
# left out of selected_subsystems entirely (never registered, never
# scenario'd) and none of the three would notice. This is the same shape as
# fabric_topology_completeness_gate's "every declared slave must own an
# address range" check, applied one level up (subsystem-set completeness
# instead of master x slave / address-map completeness). Deliberately its
# own single-purpose gate, not folded into a dispatcher: SYSTEM_LEVEL is not
# a mandatory-for-every-flow stage the way VERIFICATION_ARCHITECTURE is, so
# the escape-hatch-stacking concern that justified the protocol dispatcher
# does not apply here. Non-multi-subsystem flows (pure IP-level, never
# reaching real SYSTEM_LEVEL composition) supply
# {"system_level_applicable": false, "system_level_not_applicable_reason": "..."}.
#
# run_identity_consistency_gate (REGRESSION_MONITOR) was found registered in
# .dv-harness/workflow/hard_gate_registry.json / verification_flow_v13.json /
# feature_continuity_required.json but absent from STAGE_GATES during the
# 2026-08-28 12-claim re-audit's "CLAUDE.md core rules enforced by real gate
# code" check -- it already correctly implements the "same regression batch
# must use the same source/build/config identity" Core Operating Rule
# (checks canonical_run_id/canonical_build_hash consistency across evidence,
# fails CROSS_RUN_EVIDENCE_WITHOUT_APPROVED_MERGE), it just wasn't invoked.
# Single-input (--bundle), no run_gate extension needed -- wired directly.
#
# BUILD_DEBUG, GIT_SYNC, INFRA_RECOVERY, PROJECT_MODEL, REGRESSION,
# REGRESSION_SELECT, SERVER_SYNC (2026-08-28, 7-ungated-stage closure pass):
# these were the only 7 Stage enum values with zero STAGE_GATES entry, found
# during a dedicated investigation that cross-referenced all 157 gates in
# .dv-harness/workflow/hard_gate_registry.json against them -- none of the 30
# registered-but-unwired gates at investigation time fit any of the 7 (all
# were harness-self-audit/meta-consistency/remote-control-mode/protocol-
# catalog concerns for other stages), and none of the 7 had a prior "leave
# ungated" decision recorded anywhere in this header, so this was genuinely
# unexplored territory rather than a documented omission. Each stage's
# dv_harness/prompts.py instruction text names a concrete, checkable evidence
# shape (build-failure quick-fix-vs-design-issue triage; safe git fetch/sync
# that accounts for every pre-existing dirty path; regression infra-vs-
# functional triage; project model's verification boundary/VIP topology/
# block-branch classification/confidence/DV-readiness; regression selection's
# four TARGETED/DEPENDENCY/SAFETY/mandatory-signoff categories; regression
# submission's one-LSF-job-one-agent-context + WAVE/PA/Coverage-default Core
# Operating Rules; server sync's exact HEAD-SHA-plus-submodule-SHA identity
# check) -- none is free-form/administrative, so all 7 got a purpose-built new
# gate script (added to tools/verification_flow/ and registered in
# hard_gate_registry.json) rather than being left ungated. Each script was
# independently executed against constructed PASS and FAIL payloads before
# being wired below, matching the verification bar this whole file's mass-
# wiring passes have used throughout.

# --- Tier 5: DV_REVIEW_REQUIRED co-sign gate --------------------------------
# Built from the DV_JUDGMENT bucket in a gate-field audit (every gate
# script's own pass/fail branches were read to confirm exact field nesting --
# several differ from the illustrative JSON in prompts.py, e.g.
# mechanism_readiness_gate/traceability_consistency_gate's
# approved_alternate_verification_method lives under planned_testcases[],
# not top-level). expert_feedback_closure_gate and waiver_scope_consistency_gate
# are intentionally absent: they already carry a human's own identity
# attestation (expert_id/approval_id) with no wrapping needed.
#
# NOTICE (2026-08-28): an adversarial verify pass on the original draft found
# that enforcing this unconditionally would demote most of the pipeline's
# currently-passing stages to DV_REVIEW_PENDING, because prompts.py has never
# been updated to tell agents to emit the required {"value","reviewer_id",
# "reviewer_confidence"} wrapper for any JUDGMENT_FIELDS entry -- there is no
# migration path yet. Rather than ship a change that breaks the existing
# pipeline by default, this mechanism is OPT-IN: it only takes effect when
# .dv-harness/config.json's policy.require_dv_review_cosign is explicitly set
# true (see load_config() in run_gate/evaluate_stage_evidence below). Default
# behavior (flag absent/false) is byte-for-byte identical to pre-Tier-5.
# Follow-up needed before flipping the default: migrate prompts.py's stage
# instructions to the wrapped format for every JUDGMENT_FIELDS entry, and
# update the test suite to match, stage by stage -- not all at once.
REVIEWER_CONFIDENCE_LEVELS = ["HIGH", "MEDIUM", "LOW"]


class _DictValues:
    """JUDGMENT_FIELDS path sentinel: marks a leaf whose container is a
    dict-of-scalars (every value is itself the judgment content), unlike
    the far more common list-of-dicts leaf (a named field inside each
    item). Needed for promotion_readiness_gate's critical_dimensions,
    e.g. {"COVERAGE": "READY", "REGRESSION": "BLOCKED", ...}."""
    def __repr__(self):
        return "DICT_VALUES"


DICT_VALUES = _DictValues()

# gate_id -> list of field-path specs. A spec is either:
#   - a bare field name (str)                 -> top-level scalar field.
#   - a tuple (*list_keys, leaf)               -> navigate list_keys as
#     nested lists-of-dicts (one level per key), then apply leaf:
#       * leaf is a field name (str)  -> that field inside the innermost item.
#       * leaf is DICT_VALUES          -> the innermost container IS a dict
#         of scalars; every key/value pair in it is a judgment site.
JUDGMENT_FIELDS = {
    "rtl_first_architecture_discovery_gate": [
        ("unknown_items", "confidence"),
        ("unknown_items", "next_action"),
    ],
    "architecture_calibration_gate": [
        "impact_analysis_completed",
        "affected_artifacts_updated",
        "rerun_evidence",
    ],
    "architecture_calibration_conflict_gate": [
        ("conflicts", "resolved"),
    ],
    "spec_to_vplan_requirement_quality_gate": [
        ("requirements", "expected_behavior"),
        ("requirements", "verification_method"),
        ("requirements", "coverage_goal"),
        ("requirements", "ambiguity"),
        ("requirements", "ambiguity_resolution_or_question"),
        ("requirements", "support_status"),
    ],
    "corner_risk_rank": [
        ("cases", "risk_factors"),  # CCL-skippable, see CCL_SKIPPABLE below
    ],
    "spec_coverage_audit": [
        ("requirements", "status"),
        ("requirements", "support_status"),
    ],
    "mechanism_readiness_gate": [
        ("verification_mechanisms", "type"),
        ("planned_testcases", "approved_alternate_verification_method"),
    ],
    "traceability_consistency_gate": [
        ("planned_testcases", "approved_alternate_verification_method"),
    ],
    "simulation_semantic_validation_gate": [
        ("command_expectations", "required"),
        ("command_expectations", "evidence_requirements", "pattern"),
        ("command_expectations", "evidence_requirements", "match_mode"),
        ("command_expectations", "contradiction_requirements", "pattern"),
    ],
    "false_pass_resistance_gate": [
        "oracle_independent",
    ],
    "lsf_per_job_monitor_gate": [
        ("jobs", "kill_reason"),
    ],
    "coverage_hole_regeneration_gate": [
        ("coverage_holes", "root_cause_classification"),  # CCL-skippable
    ],
    "root_cause_evidence_gate": [
        "first_bad_event", "causal_chain", "root_cause",
        "supporting_evidence", "counter_evidence", "confidence",
    ],
    # NOTE (2026-08-28): root_cause_evidence_gate.py was extended the same day
    # to require a >=2-entry "hypotheses" array (per-entry fields sourced at
    # runtime from .dv-harness/inference/inference_policy.json, never
    # hardcoded here) for any non-"trivial_finding" claim, structurally
    # proving the selected root_cause matches one array entry and >=1 OTHER
    # entry carries recorded counter_evidence -- closing the gap where a lone,
    # never-refuted hypothesis could PASS RE_AUDIT. No STAGE_GATES change was
    # needed (the gate is already wired above by script name) and the
    # field-path list right above this comment is intentionally left as-is:
    # it only gates Tier-5 co-sign wrapping, a separate opt-in concern the
    # fix does not touch. hypotheses[].confidence / hypotheses[].claim are
    # NOT (yet) individually co-signable via JUDGMENT_FIELDS -- doing so
    # would be a legitimate future Tier-5 extension (co-sign each candidate
    # hypothesis, not just the selected root_cause), left as a follow-up
    # rather than bundled into this fix.
    "rca_replay_fix_closure_gate": [
        "attribution", "attribution_confidence",
    ],
    "system_level_validator": [
        ("subsystems", "qualification_state"),
        ("subsystems", "interface_compatibility"),
        ("subsystems", "clock_reset_compatibility"),
    ],
    "experience_knowledge_gate": [
        "pattern", "root_cause", "evidence", "applicability_constraints",
    ],
    "execution_evidence_gate": [
        ("requirements", "support_status"),
        ("requirements", "approved_alternate_verification_method"),
    ],
    "promotion_readiness_gate": [
        ("critical_dimensions", DICT_VALUES),
        "evidence_fresh",
    ],
    "signoff_bundle_completeness_gate": [
        "final_verdict",
    ],
}

# Field-sites where a sibling "classification_basis":"REUSED_CCL:<id>" in the
# SAME list item (per dv_harness/memory.py's CornerCaseLibrary +
# prompts.py's SOC_SCENARIO_PLANNER/COVERAGE_CLOSURE stage text) makes the
# bare, unwrapped value acceptable -- an already runtime-verified precedent
# needs no fresh co-sign. This convention exists ONLY for these two
# field-sites today; every other JUDGMENT_FIELDS entry always requires the
# reviewer wrapper regardless of any classification_basis value.
CCL_SKIPPABLE = {
    ("corner_risk_rank", ("cases", "risk_factors")),
    ("coverage_hole_regeneration_gate", ("coverage_holes", "root_cause_classification")),
}


def _iter_judgment_targets(payload, path):
    """Yields (container, key, location_label) for every concrete field-site
    inside `payload` that a JUDGMENT_FIELDS path spec resolves to -- the
    judgment value at that site is container[key]. See JUDGMENT_FIELDS'
    docstring above for what `path` may be."""
    if isinstance(path, str):
        if isinstance(payload, dict) and path in payload:
            yield payload, path, path
        return

    def _walk(container, keys, label):
        if not isinstance(container, dict):
            return
        if len(keys) == 1:
            leaf = keys[0]
            if leaf is DICT_VALUES:
                for k in list(container.keys()):
                    yield container, k, f"{label}.{k}"
            elif leaf in container:
                yield container, leaf, f"{label}.{leaf}"
            return
        key, rest = keys[0], keys[1:]
        val = container.get(key)
        nxt_label = f"{label}.{key}" if label else key
        if isinstance(val, list):
            for idx, item in enumerate(val):
                yield from _walk(item, rest, f"{nxt_label}[{idx}]")
        elif isinstance(val, dict):
            yield from _walk(val, rest, nxt_label)

    yield from _walk(payload, list(path), "")


def _ccl_reuse_verified(root: Path, ccl_id: str) -> bool:
    """Actually verify a claimed 'REUSED_CCL:<id>' precedent, rather than
    trusting the agent's self-reported prefix string. BUG FIX (2026-08-28,
    confirmed by architecture audit): the original implementation only
    string-matched the "REUSED_CCL:" prefix and never called
    CornerCaseLibrary.get() -- an agent could type that prefix in front of
    ANY id (even one that doesn't exist, or a DEPRECATED record) and the
    judgment field would be silently exempted from co-sign. This mirrors the
    "high confidence" bar dv_harness/prompts.py's SOC_SCENARIO_PLANNER/
    COVERAGE_CLOSURE stage text already documents for agents: status must be
    ACTIVE, and the record must carry a real runtime_evidence_hash plus a
    semantic_verdict of TRUE_PASS/TRUE_FAIL -- not merely exist."""
    rec = CornerCaseLibrary(root).get(ccl_id)
    if not rec or rec.get("status") != "ACTIVE":
        return False
    # Shared-knowledge-center staleness gate (2026-08-28): a record that has
    # aged past its `revalidate_by` timestamp without being re-confirmed is
    # no longer reuse-eligible even though its status is still ACTIVE --
    # CLAUDE.md's "memory is prior knowledge, not current evidence" applies
    # to age, not only to explicit retraction. `revalidate_by` is None for
    # any record with no configured expiry (e.g. every pre-existing local
    # record, or one written with knowledge_center disabled), so this is a
    # no-op unless the shared knowledge-center feature actually set it.
    revalidate_by = rec.get("revalidate_by")
    if revalidate_by is not None:
        try:
            if time.time() > float(revalidate_by):
                return False
        except (TypeError, ValueError):
            pass
    evidence = rec.get("evidence") or {}
    return (
        bool(evidence.get("runtime_evidence_hash"))
        and evidence.get("semantic_verdict") in ("TRUE_PASS", "TRUE_FAIL")
    )


def _check_judgment_fields(root: Path, gate_id: str, payload: dict, stage=None):
    """Tier 5 co-sign check. For every JUDGMENT_FIELDS[gate_id] path present
    in `payload`, requires the value to arrive wrapped as
    {"value": <original>, "reviewer_id": "...", "reviewer_confidence": "HIGH|MEDIUM|LOW"}
    -- UNLESS the field-site is in CCL_SKIPPABLE, the same list item's
    sibling "classification_basis" is "REUSED_CCL:<id>" (C1), AND that id
    actually resolves to a verified Corner-case Library record (see
    _ccl_reuse_verified) -- in which case the bare unwrapped value is
    accepted exactly as before this feature. A claimed id that doesn't
    resolve, isn't ACTIVE, or lacks real runtime evidence falls through to
    the normal co-sign requirement rather than being silently exempted.

    `stage` (2026-08-28, DV-review co-sign direct-submit action): when
    given, an unwrapped field is ALSO accepted if a durable co-sign record
    exists for (stage, "<gate_id>/<loc>") -- written out-of-band by a human
    via commands.cmd_cosign / ControlPlane.add_cosign (CLI `dv-harness
    cosign` / dashboard COSIGN control) -- AND that record's stored value is
    EXACTLY EQUAL to the bare value found here. This is the real mechanism
    that lets a human satisfy the Tier-5 wrapper requirement directly,
    instead of only ever via the agent re-emitting the wrapper inline.
    Matching is deliberately exact-value, not merely exact-location: if the
    agent's next attempt supplies a different value at the same field-site
    (or the site's own location shifts, e.g. a reordered list index), the
    prior co-sign no longer covers it -- a fresh co-sign (or an inline
    wrapper) is required again rather than silently trusting stale content.
    When stage is None (a caller that predates this feature, or one that
    genuinely has no stage context), cosigns are not consulted at all --
    behavior is then identical to before this feature existed.

    Returns (clean_payload, unresolved): `clean_payload` is a deep copy of
    `payload` with every judgment field unwrapped back to its bare `value`
    (the underlying gate script's existing pass/fail logic is completely
    unchanged -- it never sees the reviewer wrapper); `unresolved` lists
    "location: reason" strings for every field-site still needing a human
    co-sign. A field the agent never supplied at all is NOT flagged here --
    that stays the underlying gate script's own MISSING_FIELDS-style
    problem, unchanged from before this feature."""
    specs = JUDGMENT_FIELDS.get(gate_id)
    if not specs:
        return payload, []
    clean = json.loads(json.dumps(payload))  # deep copy; never mutate caller's dict
    unresolved = []
    cosigns = ControlPlane(root).list_cosigns(stage) if stage else {}
    for path in specs:
        skippable = (gate_id, path) in CCL_SKIPPABLE
        for container, key, loc in _iter_judgment_targets(clean, path):
            v = container.get(key)
            if skippable:
                basis = container.get("classification_basis")
                if isinstance(basis, str) and basis.startswith("REUSED_CCL:"):
                    ccl_id = basis.split(":", 1)[1].strip()
                    if ccl_id and _ccl_reuse_verified(root, ccl_id):
                        if isinstance(v, dict) and "value" in v:
                            container[key] = v["value"]  # already wrapped anyway; unwrap
                        continue  # bare value accepted, no co-sign required -- verified above
                    unresolved.append(f"{loc}: classification_basis claims REUSED_CCL:{ccl_id} "
                                       f"but that record is missing, not ACTIVE, or lacks verified evidence")
                    continue
            if not isinstance(v, dict) or "value" not in v:
                cosign = cosigns.get(f"{gate_id}/{loc}")
                if cosign is not None and cosign.get("value") == v:
                    continue  # durable out-of-band human co-sign covers this exact value
                unresolved.append(f"{loc}: not wrapped for DV review")
                continue
            rid = v.get("reviewer_id")
            conf = v.get("reviewer_confidence")
            if not rid or not str(rid).strip():
                unresolved.append(f"{loc}: missing reviewer_id")
            if conf not in REVIEWER_CONFIDENCE_LEVELS:
                unresolved.append(f"{loc}: missing/invalid reviewer_confidence")
            container[key] = v["value"]  # unwrap in place for the underlying script
    return clean, unresolved


EVIDENCE_BLOCK_RE = re.compile(
    r"```dv-harness-evidence:(?P<gate_id>[a-z0-9_]+)\s*\n(?P<body>.*?)```",
    re.DOTALL,
)


class GateResult:
    def __init__(self, gate_id: str, ok: bool, detail: dict):
        self.gate_id = gate_id
        self.ok = ok
        self.detail = detail


def extract_evidence_blocks(text: str) -> dict:
    """Parses fenced ```dv-harness-evidence:<gate_id> ... ``` blocks out of
    an agent's stage response. Malformed JSON is dropped -- treated as
    absent evidence, never coerced into a pass."""
    out = {}
    for m in EVIDENCE_BLOCK_RE.finditer(text or ""):
        try:
            out[m.group("gate_id")] = json.loads(m.group("body"))
        except Exception:
            continue
    return out


def _materialize_flag(root, gate_id, spec, payload, tmp_paths, enforce_dv_review, stage):
    """Resolves one EvidenceFlag/ContextFlag spec into a (flag, value) CLI
    arg pair for the multi-flag run_gate() path. Returns (flag, value_str,
    unresolved) where unresolved is the (possibly empty) Tier-5 co-sign list
    for that sub-payload. Raises _MissingSubpayload if an EvidenceFlag's key
    is absent from the agent-supplied payload dict."""
    if isinstance(spec, ContextFlag):
        value = spec.provider(root)
        if spec.kind == "file":
            tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
            json.dump(value, tmp)
            tmp.close()
            tmp_paths.append(tmp.name)
            return spec.flag, tmp.name, []
        return spec.flag, str(value), []
    # EvidenceFlag: value is agent-attested, sourced from the sub-payload.
    if not isinstance(payload, dict) or spec.key not in payload:
        raise _MissingSubpayload(spec.key)
    value = payload[spec.key]
    if spec.kind == "raw":
        return spec.flag, str(value), []
    clean, unresolved = (
        _check_judgment_fields(root, gate_id, value, stage=stage) if enforce_dv_review else (value, [])
    )
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(clean, tmp)
    tmp.close()
    tmp_paths.append(tmp.name)
    return spec.flag, tmp.name, unresolved


def run_gate(root: Path, script_name: str, cli_flag, payload: dict,
             enforce_dv_review: bool = False, stage=None) -> GateResult:
    # Path(...).stem (not script_name[:-3]) so cross-directory entries like
    # "../senior_dv/corner_risk_rank.py" resolve to the same friendly gate_id
    # STAGE_GATES/JUDGMENT_FIELDS use ("corner_risk_rank"), not a path-prefixed
    # string. Harmless before Tier 5 (only affected internal detail strings);
    # now load-bearing since JUDGMENT_FIELDS keys on this id.
    gate_id = Path(script_name).stem
    script = root / TOOLS_DIR / script_name
    if not script.exists():
        return GateResult(gate_id, False, {"status": "FAIL", "reason": "GATE_TOOL_MISSING", "tool": str(script)})

    tmp_paths = []
    unresolved = []
    try:
        if isinstance(cli_flag, (tuple, list)):
            # --- multi-flag path: cli_flag is a sequence of EvidenceFlag/
            # ContextFlag specs. The single evidence block's JSON body is a
            # dict-of-sub-payloads (one per EvidenceFlag key); each spec
            # contributes one `<flag> <value>` pair to one script invocation.
            args = [sys.executable, str(script)]
            try:
                for spec in cli_flag:
                    flag, value, u = _materialize_flag(
                        root, gate_id, spec, payload, tmp_paths, enforce_dv_review, stage
                    )
                    args += [flag, value]
                    unresolved += u
            except _MissingSubpayload as e:
                return GateResult(gate_id, False, {
                    "status": "FAIL", "reason": "MISSING_EVIDENCE_SUBPAYLOAD", "missing": e.key,
                })
            proc = subprocess.run(
                args, cwd=str(root), capture_output=True, text=True, timeout=30,
            )
        else:
            # --- unchanged one-flag path: byte-identical behavior/temp-file
            # lifecycle to before multi-flag gates existed.
            run_payload, unresolved = (
                _check_judgment_fields(root, gate_id, payload, stage=stage) if enforce_dv_review else (payload, [])
            )
            tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
            json.dump(run_payload, tmp)
            tmp.close()
            tmp_paths.append(tmp.name)
            proc = subprocess.run(
                [sys.executable, str(script), cli_flag, tmp.name],
                cwd=str(root), capture_output=True, text=True, timeout=30,
            )
    finally:
        for p in tmp_paths:
            # REAL COMPAT BUG (found deploying to the real remote server,
            # Python 3.7): Path.unlink()'s missing_ok kwarg was only added
            # in Python 3.8. This single call site runs on EVERY real gate
            # execution (run_gate() is the shared subprocess-cleanup path
            # every STAGE_GATES script goes through), so this one line
            # alone caused 142 of 200 real test failures on the actual
            # remote deployment -- the single highest-leverage fix found in
            # that compatibility pass. try/except degrades identically on
            # every Python version (unlink() already only raises
            # FileNotFoundError for "doesn't exist", never something this
            # should mask).
            try:
                Path(p).unlink()
            except FileNotFoundError:
                pass
    try:
        detail = json.loads((proc.stdout or "").strip() or "{}")
    except Exception:
        detail = {"status": "FAIL", "reason": "GATE_OUTPUT_UNPARSEABLE", "raw": (proc.stdout or "")[-500:]}
    # Exit code, not the "status" string, is the reliable success signal:
    # every gate script sys.exit()s nonzero on any failure branch, but the
    # success-status value itself varies across scripts (PASS,
    # READY_FOR_TEST_GENERATION, READY_FOR_CLOSURE, TRUE_PASS-nested, ...).
    script_ok = proc.returncode == 0

    if unresolved:
        # The script already ran above against the unwrapped (bare-value)
        # payload -- script_ok tells us whether it would have passed on the
        # merits. Only report DV_REVIEW_REQUIRED (co-sign-pending, not a
        # content failure) when the script itself found nothing wrong; a
        # script that still fails on the unwrapped values is a genuine
        # GATE_FAIL, independent of and in addition to the missing co-sign.
        detail = dict(detail)
        detail["dv_review_unresolved_fields"] = unresolved
        if script_ok:
            detail["reason"] = "DV_REVIEW_REQUIRED"
        return GateResult(gate_id, False, detail)

    return GateResult(gate_id, script_ok, detail)


# BUG FIX (2026-08-28, plan-interactive-intake-completeness design pass):
# human-readable questions for tools/vplan/intake_readiness.py's known field
# names, rendered into blocking_reason when evaluate_stage_evidence returns
# NEEDS_USER_INPUT -- so a stalled INTAKE shows an actual question, not a
# bare field-name list a human has to already know how to interpret.
INTAKE_FIELD_QUESTIONS = {
    "target_name": "這次驗證的目標名稱是什麼？（DUT/SoC 或 subsystem 的名字）",
    "protocols": "這次要驗證的協定有哪些？（例如 USB、PCIe...）",
    "protocol_spec": "有沒有現成的協定 spec 文件可以參考？請提供路徑或說明來源。",
    "dut_design_spec": "有沒有 DUT 的設計規格文件？請提供路徑或說明來源。",
    "rtl_top_or_interface_files": "有沒有 RTL top-level 或介面檔案可以參考？",
    "clock_reset_spec": "clock/reset 的規格資訊在哪裡？",
    "phy_interface_spec": "PHY 介面規格在哪裡？",
    "interface_or_clock_reset_evidence": "需要下列其中一種資訊：clock/reset 規格、PHY 介面規格、或 RTL top/介面檔案，目前都沒有提供，至少給一種。",
    "selected_subsystems": "System-Level 驗證要包含哪些 subsystem？",
    "system_level_use_cases": "這次 System-Level 驗證要涵蓋哪些使用情境（use case）？",
    "subsystem_identity_or_manifest": "有沒有既有的 UVM 環境或 manifest 可以參考已完成的 subsystem？",
    "valid_mode": "這次是要建立單一 subsystem 環境（SUBSYSTEM）還是 system-level 環境（SYSTEM_LEVEL）？",
    "fabric_topology_evidence": "有沒有 AMBA fabric/topology 的規格文件（例如 master/slave 拓撲、互連架構）可以參考？請提供路徑或說明來源。",
    "uhs_tuning_evidence": "有沒有 SD/SDIO UHS tuning 的規格文件（例如 tuning 流程、時序參數）可以參考？請提供路徑或說明來源。",
    # BUG FIX (2026-09-01, commandtxt-vip-intake-gate-implementation): these
    # two keys were never checked by tools/vplan/intake_readiness.py before
    # this fix -- see that script's own header for the full rationale.
    "command_txt": "有沒有既有的 command.txt pattern 檔案可以參考？請提供實際存在於磁碟上的檔案路徑（可多筆）。",
    "command_txt_path_not_found": "提供的 command.txt 路徑目前在磁碟上找不到，請確認路徑是否正確、檔案是否真的存在。",
    "vip_reference": "有沒有 VIP Reference 資料（VIP 文件/範例/Reference UVM）可以參考？請提供實際存在於磁碟上的檔案路徑（可多筆）。",
    "vip_reference_path_not_found": "提供的 VIP Reference 路徑目前在磁碟上找不到，請確認路徑是否正確、檔案是否真的存在。",
}

# BUG FIX (2026-08-29, poster-compliance-audit "INTAKE 問得太籠統" finding):
# these fields are all "what technical material do you actually have" asks --
# once the agent's own intake_readiness payload already names a `protocols`
# list, escalate the generic question into a concrete, per-protocol checklist
# pulled from .dv-harness/builder/protocol_builder_registry.json's real
# `discover` list (the same registry protocol_builder_registry_conformance_gate
# already enforces downstream at PROTOCOL_CAPABILITY) -- so a human is told
# "for PCIe: RC/EP/Switch role, Gen2-Gen6, lane width, ..." at the very FIRST
# stall point, not only several stages later. Never fabricates a checklist for
# an unrecognized protocol name; falls back to the generic question as-is.
_PROTOCOL_TECHNICAL_INTAKE_FIELDS = {
    "protocol_spec", "dut_design_spec", "rtl_top_or_interface_files",
    "clock_reset_spec", "phy_interface_spec", "interface_or_clock_reset_evidence",
    # command_txt/vip_reference (2026-09-01, commandtxt-vip-intake-gate-
    # implementation): same "what technical material do you actually have"
    # shape as the fields above -- worth escalating into the same
    # per-protocol checklist when one is available.
    "command_txt", "vip_reference",
}


def _protocol_discover_checklist(root: Path, protocols):
    """Looks up each named protocol in the real protocol_builder_registry.json
    and returns a human-readable Traditional Chinese checklist string built
    from its actual `discover` list, or None if nothing matched (never
    invents checklist content for a protocol the registry doesn't know)."""
    try:
        registry = json.loads(
            (root / ".dv-harness" / "builder" / "protocol_builder_registry.json").read_text(encoding="utf-8")
        )
    except Exception:
        return None
    entries = registry.get("protocols") or {}
    lines = []
    for name in protocols or []:
        key = str(name).strip().lower().replace(" ", "-").replace("_", "-")
        entry = entries.get(key)
        if entry is None:
            for k, v in entries.items():
                if k in key or key in k:
                    entry = v
                    break
        if not entry:
            continue
        discover = entry.get("discover") or []
        if discover:
            lines.append(f"針對 {entry.get('display_name', name)}，具體需要：" + "、".join(discover) + "。")
    return "\n".join(lines) if lines else None


def _stage_completion_from_signatures(gates, signatures) -> Dict[str, Any]:
    """Stage-scoped completion fraction derived from the exact per-gate
    signatures list _evaluate_stage_evidence_core() already builds (one
    entry per gate registered for the stage in STAGE_GATES, including a
    synthetic FAIL entry for a gate the agent supplied no evidence for --
    see that function's docstring). This is deliberately narrower than
    dashboard.py's `_overall_progress()` (percent of ALL Stage enum values
    at PASS/CLOSED across the whole run) -- this one is scoped to the
    gates configured for a SINGLE stage, so it stays meaningful mid-stage,
    before that stage itself has reached a terminal PASS/CLOSED verdict.

    RULING (2026-09-01): a stage with zero registered gates in
    STAGE_GATES (i.e. `gates` is falsy) has nothing to be "incomplete"
    about -- there is no per-gate signature list to divide by, and
    NO_GATE_REQUIRED already means the stage's own gate-evidence
    requirement is fully satisfied trivially. Reporting 0% here would
    read as "nothing done" for a stage that in fact has no gate blocking
    it at all, so this reports 100% complete with an explanatory note
    instead of a ZeroDivisionError or an arbitrary 0%."""
    gates_total = len(gates) if gates else 0
    if gates_total == 0:
        return {
            "gates_total": 0,
            "gates_passed": 0,
            "stage_completion_percent": 100,
            "stage_completion_note": "stage has no registered gates; treated as fully complete",
        }
    gates_passed = sum(1 for _gate_id, ok, _detail in signatures if ok)
    return {
        "gates_total": gates_total,
        "gates_passed": gates_passed,
        "stage_completion_percent": round(100 * gates_passed / gates_total),
        "stage_completion_note": None,
    }


def evaluate_stage_evidence(root: Path, stage: str, agent_text: str):
    """Returns (verdict, reasons). verdict is one of:
    NO_GATE_REQUIRED  -> stage has no mapped gate, behaves as before.
    PASS              -> every mapped gate ran, passed its own script
                         checks, AND (Tier 5, only when
                         policy.require_dv_review_cosign is true) every
                         DV_JUDGMENT-tagged evidence field it carried was
                         already co-signed.
    MISSING_EVIDENCE  -> stage has mapped gate(s) but the agent's response
                         contained no matching evidence block.
    NEEDS_USER_INPUT  -> (2026-08-28) every gate that ran failed, and every
                         one of those failures was intake_readiness.py's
                         "missing": [...] shape -- the agent isn't wrong,
                         it genuinely needs information from a human before
                         it can proceed. `reasons` for this verdict are
                         already human-readable questions (INTAKE_FIELD_QUESTIONS
                         above), not raw gate-reason strings. engine.run_stage
                         maps this to Status.WAIT_USER, not PARTIAL -- a
                         "waiting for you to answer" state, not a
                         retry-worthy failure.
    DV_REVIEW_PENDING -> (Tier 5, opt-in only) every gate that ran would
                         otherwise have passed its own script's checks, but
                         at least one DV_JUDGMENT field (gates.JUDGMENT_FIELDS)
                         was supplied unwrapped/uncosigned.
    GATE_FAIL         -> at least one mapped gate genuinely failed its own
                         script checks, independent of any co-sign gap.

    Only NO_GATE_REQUIRED/PASS may promote a stage to Status.PASS; the
    caller (engine.run_stage) downgrades any other verdict string (including
    DV_REVIEW_PENDING) to PARTIAL via its existing
    `if verdict in ("NO_GATE_REQUIRED", "PASS")` check -- NEEDS_USER_INPUT is
    the one exception, mapped to WAIT_USER instead (see engine.py). Tier 5
    enforcement defaults OFF (see the NOTICE above JUDGMENT_FIELDS): unless
    .dv-harness/config.json's policy.require_dv_review_cosign is explicitly
    true, this function's behavior is otherwise byte-for-byte identical to
    before Tier 5 existed."""
    verdict, reasons, _signatures, _completion = _evaluate_stage_evidence_core(root, stage, agent_text)
    return verdict, reasons


def evaluate_stage_evidence_with_completion(root: Path, stage: str, agent_text: str):
    """Same verdict/reasons contract as evaluate_stage_evidence() above, plus
    the stage-scoped completion dict (see _stage_completion_from_signatures())
    -- gates_total, gates_passed, stage_completion_percent,
    stage_completion_note. Added for control_plane.describe_stage() (WHY +
    "how close is this stage to done", not just why it's blocked) without
    touching evaluate_stage_evidence()'s or react_loop.evaluate_stage_evidence_
    with_detail()'s existing fixed-arity tuple contracts, both of which have
    real callers/tests that unpack them at their current arity."""
    verdict, reasons, _signatures, completion = _evaluate_stage_evidence_core(root, stage, agent_text)
    return verdict, reasons, completion


def _evaluate_stage_evidence_core(root: Path, stage: str, agent_text: str):
    """Shared implementation behind evaluate_stage_evidence() (verdict,
    reasons -- the pre-existing 2-tuple contract, untouched),
    evaluate_stage_evidence_with_completion() (verdict, reasons, completion),
    and dv_harness/react_loop.py's evaluate_stage_evidence_with_detail()
    (which wraps the third element into GateSignature objects). Single
    source of truth so all call sites can never see divergent gate
    results -- the exact per-gate run_gate() loop runs ONCE per call, not
    once per caller.

    Returns (verdict, reasons, signatures, completion):
      - signatures is a list of (gate_id, ok, detail) plain tuples, one per
        gate NAMED in STAGE_GATES[stage] (not only the ones that actually
        ran) -- a gate the agent supplied no evidence block for still gets a
        synthetic ('NO_EVIDENCE_BLOCK_SUPPLIED', False, {...}) entry so
        react_loop.py's build_menu() always has one real signature per
        configured gate to reason over, never a silent gap.
      - completion is the dict _stage_completion_from_signatures() derives
        from that same signatures list (gates_total, gates_passed,
        stage_completion_percent, stage_completion_note) -- a stage-SCOPED
        completion fraction, distinct from dashboard.py's whole-run
        overall_progress_percent."""
    gates = STAGE_GATES.get(stage)
    if not gates:
        return "NO_GATE_REQUIRED", [], [], _stage_completion_from_signatures(gates, [])
    enforce_dv_review = bool(load_config(root).get("policy", {}).get("require_dv_review_cosign", False))
    blocks = extract_evidence_blocks(agent_text)
    reasons = []
    signatures = []
    gate_fail = False
    ran_any = False
    review_pending = []
    needs_user_input_questions = []
    all_failures_are_missing_input = True
    for gate_id, script_name, cli_flag in gates:
        payload = blocks.get(gate_id)
        if payload is None:
            gate_fail = True
            reasons.append(f"{gate_id}: no evidence block supplied")
            all_failures_are_missing_input = False
            signatures.append((gate_id, False, {"status": "FAIL", "reason": "NO_EVIDENCE_BLOCK_SUPPLIED"}))
            continue
        ran_any = True
        gr = run_gate(root, script_name, cli_flag, payload, enforce_dv_review=enforce_dv_review, stage=stage)
        signatures.append((gr.gate_id, gr.ok, gr.detail))
        if gr.ok:
            continue
        if gr.detail.get("reason") == "DV_REVIEW_REQUIRED":
            fields = gr.detail.get("dv_review_unresolved_fields", [])
            review_pending.extend(fields)
            reasons.append(f"{gate_id}: DV_REVIEW_REQUIRED -> {fields}")
        else:
            gate_fail = True
            reasons.append(f"{gate_id}: {gr.detail}")
            # BUG FIX (2026-08-28, plan-interactive-intake-completeness
            # design pass): tools/vplan/intake_readiness.py's exact failure
            # shape ({"missing": [...]})  means "the agent hasn't hit a real
            # error, it genuinely needs information from the human before it
            # can continue" -- previously indistinguishable from any other
            # GATE_FAIL. Scoped narrowly to this one gate's known shape
            # (not any gate script that happens to have a "missing" key) so
            # this doesn't silently reinterpret an unrelated gate's failure.
            missing = gr.detail.get("missing") if gate_id == "intake_readiness" else None
            if isinstance(missing, list) and missing:
                protocols_hint = payload.get("protocols") if isinstance(payload, dict) else None
                checklist = _protocol_discover_checklist(root, protocols_hint) if protocols_hint else None
                for f in missing:
                    base_q = INTAKE_FIELD_QUESTIONS.get(f, f"缺少必要資訊：{f}")
                    if checklist and f in _PROTOCOL_TECHNICAL_INTAKE_FIELDS:
                        needs_user_input_questions.append(base_q + "\n" + checklist)
                    else:
                        needs_user_input_questions.append(base_q)
            else:
                all_failures_are_missing_input = False
    completion = _stage_completion_from_signatures(gates, signatures)
    if not ran_any:
        return "MISSING_EVIDENCE", reasons, signatures, completion
    if gate_fail:
        if needs_user_input_questions and all_failures_are_missing_input:
            return "NEEDS_USER_INPUT", needs_user_input_questions, signatures, completion
        return "GATE_FAIL", reasons, signatures, completion
    if review_pending:
        return "DV_REVIEW_PENDING", reasons, signatures, completion
    return "PASS", reasons, signatures, completion
