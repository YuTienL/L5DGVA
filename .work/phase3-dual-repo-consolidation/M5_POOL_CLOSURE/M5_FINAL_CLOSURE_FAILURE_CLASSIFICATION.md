# M5 Final Closure Regression — Failure Classification

## Failure identity differential (Section 8)

**No prior full-suite `dv_harness_tests/` regression baseline exists
anywhere in this repo's own evidence** (searched `.work/` and the repo root
for a "known failures"/regression-baseline artifact; none found; no M-wave
final report records a full-suite pass/fail tally). This is, as far as this
repo's own evidence shows, the first captured full `dv_harness_tests/` run.
There is therefore no prior accepted closure baseline to diff test
identities against — disclosed honestly rather than fabricating a "27
before" style comparison the dispatch itself warned against trusting on
count alone.

```
COMMON_FAILURES = 0   (no prior baseline to intersect against)
NEW_FAILURES    = 0   (relative to M5's own change set — see below; not
                        relative to a nonexistent whole-repo baseline)
GONE_FAILURES   = 0   (no prior baseline)
```

In place of a baseline diff, every one of the 40 real failures was
independently investigated: its real error/assertion text read from the
raw log, and `git log -1` run against its own test file to establish
whether ANY M5-era commit (Cohort 0 through this Final Closure Regression
task) ever touched it.

## Every M5-touched file, cross-checked against the 40 failing test files

M5's own full touched-file set, across every cohort and both Pool-Closure
batches: `env_manifest.py`, `vip_capability_extraction.py`,
`uvm_generator/create_environment.py`, `uvm_generator/soc_environment_composer.py`,
`uvm_generator/amba_fabric_generator.py`, `functional_coverage_signoff.py`,
`design_source_inventory.py`, `task_boundary_conformance.py`,
`intake_field_resolution.py`, `l5dgva_v5_ss84_phase_entry_protocol_schema.py`,
`rtl_filelist_parser.py`, `l5dgva_gap_queue.py`, `l5dgva_workitem_projection.py`,
`l5dgva_directive_registry.py`, `eight_engine_runtime_proof_matrix.py`,
`engine_maturity_state.py`, `eight_engine_telemetry_rollup.py`,
`l5dgva_directive_blackboard_work_queue.py`, `l5dgva_kc_extraction.py`, plus
each one's own test file.

**Zero overlap**: none of the 20 distinct files containing the 40 failures
appear in that list. `git log -1` against each of the 20 failing test files
(run directly, not inferred) shows every one's most recent commit predates
the entire M5 program — commit dates 2026-09-02 through 2026-09-08, all
well before M5 Cohort 0's own start (this session's M5-0 checkpoint,
`a5ebbdc`, dated 2026-09-23). `REGRESSION_CAUSED_BY_M5 = 0` by direct,
structural, git-evidenced non-overlap — not an inference from failure
count or theme alone.

## Classification of all 40 failures (Section 9)

### ENVIRONMENT — 28 of 40

Missing external dependency, unconfigured local tool, or a reference fixture
not present in this checkout. None require an M5 code change to resolve.

| Root cause | Count | Failing tests |
|---|---|---|
| `ModuleNotFoundError: No module named 'duckdb'` (`dv_harness/evidence_db.py`'s lazy `import duckdb`, package not installed in this Python environment) | 13 | `test_consolidated_kpi_benchmark.py::test_false_pass_count_*` (3), `test_gui_vip_coverage_wizard.py::test_functional_coverage_signoff_real_full_measured_coverage_is_ready` + `test_overall_ready_is_exactly_step_10s_real_signal_NEGATIVE_CONTROL` (2), `test_mcp_claude_md_index.py::test_every_indexed_verb_is_really_callable` (1), `test_system_build_proof.py::test_scoreboard_rung_*` / `test_no_evidence_for_the_job_is_NOT_AVAILABLE` / `test_the_full_ladder_reaches_SYSTEM_READY_only_when_every_rung_really_passes` / `test_removing_one_rungs_evidence_drops_the_verdict_out_of_SYSTEM_READY` (6), `test_web_control_plane_readiness_gate.py::test_evidence_ready_partial_once_a_real_but_empty_evidence_store_exists` (1) |
| `core.hooksPath` not set in this checkout (documented, pre-existing: CLAUDE.md itself names this exact "fresh clone must re-run that one line" gap) | 1 | `test_git_hooks_e2e.py::TestRepoOwnGateIsActuallyInstalled::test_core_hookspath_points_at_tools_git_hooks` |
| Real `pueue` subprocess/daemon behaves differently than the test's assumed machine state (`assert 1==0`, `assert False is True`, unparseable `pueue log` JSON) | 6 | `test_cli_pueue.py::TestPueueAddAndStatus::test_wait_reports_success` + `TestPueueChain::test_chain_enqueues_dependent_tasks_in_order` (2), `test_pueue_client.py::TestRealPueueIntegration::test_real_add_and_wait_success` / `test_real_add_and_wait_failure` / `test_real_dependency_chain_success` / `test_real_task_env_is_sanitized` (4) |
| Obsidian CLI presence/absence on this specific machine does not match the test's assumed state | 2 | `test_memory_vault.py::test_detect_obsidian_cli_real_probe_reports_not_installed_on_this_machine`, `test_obsidian_memory_final_integration.py::test_case_01_no_obsidian_cli_falls_back_to_filesystem_pass` |
| `reference/USB_UVM_Handoff/sim/scripts/Makefile` not present in this checkout | 3 | `test_sim_scripts_makefile_mechanisms.py::test_four_stage_flow_mirrors_reference_structurally` / `test_verdi_pa_mirrors_reference_structurally` / `test_wave_txt_convention_mirrors_reference_structurally` |
| A Parent-sibling master-prompt file (`D:\DV\Task\DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_SystemLevel_AMBA4_SyoSil_CCE_Research.md`) not present at that absolute path in this checkout | 3 | `test_syoscb_result_taxonomy.py::test_the_taxonomy_is_the_documents_own_fourteen_values_in_its_own_order` / `test_every_result_cites_the_document_line_that_names_it` / `test_the_counter_list_is_the_documents_own_thirteen_in_its_own_order` |

### PRE_EXISTING — 12 of 40

Real code/test gaps or content mismatches, confirmed by direct evidence
read; none of the 8 files behind these 12 failures are M5-touched, and each
one's last commit predates M5 entirely.

| Root cause | Count | Failing tests |
|---|---|---|
| `commands.py`'s `APPROVAL_ONLY_STAGES` does not register `BOUNDED_SELF_HEALING`, which the test suite expects | 2 | `test_bounded_self_healing.py::test_commands_approval_stage_choices_includes_bounded_self_healing` / `test_commands_cmd_approve_accepts_bounded_self_healing_stage` |
| `live_event_model` is actually resolvable in this checkout; the test's own negative-control assumption ("unresolvable in this checkout") no longer holds | 2 | `test_harness_status_event_wiring.py::test_live_event_model_status_reports_unresolvable_in_this_checkout` / `test_cli_live_event_model_status_exits_2_when_absent` |
| `question_queue.py`'s digest/filing path produces more question records than the test's own expected count of exactly 1 in a shared scenario shape (same symptom across 3 independent test files) | 5 | `test_question_queue_digest_auto_trigger.py::test_digest_fires_after_a_real_gate_verified_stage_pass`, `test_resource_cost_autonomy.py::test_3b_run_stage_performs_the_escalation_for_the_agent`, `test_waveform_dump_scope_human_confirmation.py::test_autonomous_loop_files_the_question_it_parks_on_and_a_human_answer_closes_it` / `test_a_question_already_waiting_is_not_re_filed_by_a_second_loop_pass` / `test_nothing_is_filed_when_the_agent_declared_no_scope_or_no_level` |
| `gates.py`'s effective-stage-gates overlay evaluation returns `MISSING_EVIDENCE` where the test expects `NO_GATE_REQUIRED` | 1 | `test_self_tuning.py::test_real_stage_evaluation_actually_uses_effective_stage_gates_overlay` |
| `STAGE_INSTRUCTIONS` text genuinely omits 3 `STAGE_GATES`-registered gate names (`command_generation_gate`, `vip_bind_generation_gate`/`scoreboard_generation_gate`/`assertion_generation_gate`, `spec_to_vplan_quality_gate`) | 1 | `test_stage_instructions_gate_completeness.py::test_every_stage_gates_entry_is_mentioned_in_its_stage_instructions` |
| A real, pre-existing SYOSCB-2 governance violation: upstream SyoSCB reference content is vendored into the repo ahead of its own SYOSCB-33 approval gate — the test correctly detects and reports this real condition | 1 | `test_syoscb_phase1_report.py::test_section_four_really_runs_the_not_vendored_scan` |

**Total: 28 + 12 = 40.** No failure fell into `TEST_INFRASTRUCTURE` /
`LOAD_SENSITIVE_FLAKE` / `KNOWN_DEFECT` (as a distinct bucket from
`PRE_EXISTING`) / `EXPECTED_XFAIL` / `SOURCE_BASELINE_BEHAVIOR` / `UNKNOWN` —
every one had a concrete, evidenced root cause in one of the two categories
above.

## Real M5 regression check (Section 11)

```
REGRESSION_CAUSED_BY_M5 = 0
UNKNOWN_REGRESSION_FAILURES = 0
```

No fix is required or attempted for any of the 40 — per this task's own
qualification-only scope, and because none are M5's responsibility to fix
(all pre-date M5, none touch M5's files, all are ENVIRONMENT or PRE_EXISTING
by direct evidence). Per Section 11's own instruction, this section records
findings only; no correction step was taken.
