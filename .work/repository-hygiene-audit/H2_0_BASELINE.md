# H2-0 — Baseline / Governance Check

**Execution mode: LOCAL_ANALYSIS/REMOTE_EXECUTION boundary note** — this batch runs the real local test suite (a local `pytest` invocation, not a remote server/LSF job), so it stays within this session's already-declared LOCAL_ANALYSIS execution posture; no SSH/remote transport was used.

## Git identity at baseline capture

- Working branch for all Phase-2 commits: `repo-hygiene/phase2-h2-migration` (created from `master` at `9abb10f234bc46ea9877982f959cd4e9ae07b365`; **`master` itself is never committed to directly** — per this project's gh CLI + PR-Only Governance Policy, this branch will be proposed as a PR for human review after Phase 2 closes, not merged/pushed by this session).
- Baseline HEAD (branch point from `master`): `9abb10f234bc46ea9877982f959cd4e9ae07b365`.

## Pre-existing working-tree state (must remain unchanged in kind through H2-6; any drift beyond this set is a scope violation to flag, not silently absorb)

```
 M .dv-harness/events.jsonl
 M tools/remote/remote_exec.py
 M tools/remote/remote_relay.py
?? .pytest-tmp-clock-table.tcl
?? .pytest-tmp-gen-clocks-fdc.sh
?? .pytest-tmp-logical-multisource-table.tcl
?? .pytest-tmp-mixed-logical-example.tcl
?? .pytest-tmp-multisource-clock-table.tcl
?? .pytest-tmp-phys-create-clock-table.tcl
?? .pytest-tmp-phys-include-gen-table.tcl
?? .pytest-tmp-physical-all-forms-table.tcl
?? .pytest_tmp/
?? _tmp_selfcheck_big5.txt
?? _tmp_selfcheck_decoded_utf8.md
?? generated/canfd_uvm_env/
?? project_input/04_protocol/canfd_environment_manifest.json
```

These 3 modified + 11 untracked entries are the same set recorded at the original Phase-1 baseline capture (`00_BASELINE.md`) and re-confirmed unchanged at every checkpoint since. The 11 untracked items above correspond exactly to the 11 root-level `UNKNOWN` entries this Phase-2 plan is explicitly forbidden from touching.

## Full regression baseline (real child-process completion marker, not a wrapper exit code)

Command: `python -m pytest dv_harness_tests/ -q`, run to completion in the foreground of its own process (backgrounded only at the tool-call level for this long-running session; the recorded result is the test runner's own final summary line and its own process exit code, not any wrapper's).

**Result: `21 failed, 13694 passed, 15 skipped, 1 warning in 5301.31s (1:28:21)`. Process exit code: `1`.**

Full log: `.work/repository-hygiene-audit/_h2_0_baseline_run.log` (1,215 lines — not reproduced in full here per the Targeted Read Rule / Tier-1 "never load a full log" policy; cite by path).

### The 21 baseline failures (this is the reference set every later batch's regression is diffed against)

```
dv_harness_tests/test_bounded_self_healing.py::test_commands_approval_stage_choices_includes_bounded_self_healing
dv_harness_tests/test_bounded_self_healing.py::test_commands_cmd_approve_accepts_bounded_self_healing_stage
dv_harness_tests/test_cli_pueue.py::TestPueueAddAndStatus::test_wait_reports_success
dv_harness_tests/test_cli_pueue.py::TestPueueChain::test_chain_enqueues_dependent_tasks_in_order
dv_harness_tests/test_git_hooks_e2e.py::TestRepoOwnGateIsActuallyInstalled::test_core_hookspath_points_at_tools_git_hooks
dv_harness_tests/test_harness_status_event_wiring.py::test_live_event_model_status_reports_unresolvable_in_this_checkout
dv_harness_tests/test_harness_status_event_wiring.py::test_cli_live_event_model_status_exits_2_when_absent
dv_harness_tests/test_memory_vault.py::test_detect_obsidian_cli_real_probe_reports_not_installed_on_this_machine
dv_harness_tests/test_obsidian_memory_final_integration.py::test_case_01_no_obsidian_cli_falls_back_to_filesystem_pass
dv_harness_tests/test_pueue_client.py::TestRealPueueIntegration::test_real_add_and_wait_success
dv_harness_tests/test_pueue_client.py::TestRealPueueIntegration::test_real_add_and_wait_failure
dv_harness_tests/test_pueue_client.py::TestRealPueueIntegration::test_real_dependency_chain_success
dv_harness_tests/test_pueue_client.py::TestRealPueueIntegration::test_real_task_env_is_sanitized
dv_harness_tests/test_question_queue_digest_auto_trigger.py::test_digest_fires_after_a_real_gate_verified_stage_pass
dv_harness_tests/test_resource_cost_autonomy.py::test_3b_run_stage_performs_the_escalation_for_the_agent
dv_harness_tests/test_self_tuning.py::test_real_stage_evaluation_actually_uses_effective_stage_gates_overlay
dv_harness_tests/test_stage_instructions_gate_completeness.py::test_every_stage_gates_entry_is_mentioned_in_its_stage_instructions
dv_harness_tests/test_syoscb_phase1_report.py::test_section_four_really_runs_the_not_vendored_scan
dv_harness_tests/test_waveform_dump_scope_human_confirmation.py::test_autonomous_loop_files_the_question_it_parks_on_and_a_human_answer_closes_it
dv_harness_tests/test_waveform_dump_scope_human_confirmation.py::test_a_question_already_waiting_is_not_re_filed_by_a_second_loop_pass
dv_harness_tests/test_waveform_dump_scope_human_confirmation.py::test_nothing_is_filed_when_the_agent_declared_no_scope_or_no_level
```

### First-pass grouping (categorical, not a deep RCA — sufficient to diff later batches against, per this batch's own scope)

- **External-tool/environment dependency (10)**: `test_cli_pueue.py` (2), `test_pueue_client.py::TestRealPueueIntegration` (4) — a real `pueue` daemon is not running/available on this machine; `test_memory_vault.py`/`test_obsidian_memory_final_integration.py` (2) — real Obsidian CLI not installed on this machine (both are tests *of* the "not installed" fallback path, so their failure mode needs its own read, not assumed environment-only); `test_harness_status_event_wiring.py` (2) — likely a similar unresolvable-in-this-checkout live-event dependency.
- **Governance/config gap, independently confirmed (1)**: `test_git_hooks_e2e.py::test_core_hookspath_points_at_tools_git_hooks` — directly corroborates the `core.hooksPath` finding; **this failure is expected to persist unchanged through H2-6**, since enabling `core.hooksPath` is explicitly out of Phase-2 scope by governance decision.
- **Internal logic/engine gaps, unrelated to repository hygiene (10)**: `test_bounded_self_healing.py` (2), `test_question_queue_digest_auto_trigger.py`, `test_resource_cost_autonomy.py`, `test_self_tuning.py`, `test_stage_instructions_gate_completeness.py`, `test_syoscb_phase1_report.py`, `test_waveform_dump_scope_human_confirmation.py` (3) — none of these touch any file this Phase-2 plan will modify (`.gitignore`, `.pytest_tmp/`, the 48 archive candidates, `README.md`, `.claude/INDUSTRIAL_DV_WORKFLOW.md`, the 2 preflight scripts, `main_graph.json`'s one skill string, the 2 LSF banners) — grep-confirmed no overlap between these 10 failing test files and any H2-1..H2-5C candidate file.

All 21 are recorded here as **PRE_EXISTING** relative to Phase 2 (Phase 2 has not modified anything yet at this point in the sequence — H2-0 is read-only by definition). This is the frozen reference set H2-1 through H2-6 diff against; a later batch introducing a failure **not** in this list is a candidate `REGRESSION_CAUSED_BY_PHASE2`, not automatically PRE_EXISTING.

## `core.hooksPath` classification (already reached in the approved plan; reconfirmed here with new corroborating evidence)

**`CURRENT_BUT_DISABLED, and REQUIRED_BY_CLAUDE_POLICY`** — unchanged from the approved `H2_BATCH_PLAN.md`. New evidence found during this batch: `dv_harness_tests/test_git_hooks_e2e.py::TestRepoOwnGateIsActuallyInstalled::test_core_hookspath_points_at_tools_git_hooks` is a real, existing regression test that asserts `core.hooksPath` points at `tools/git-hooks`, and it is currently **failing** in this checkout — independent, code-level confirmation that this is a live, tested requirement, not merely a prose expectation in `CLAUDE.md`. Per explicit governance decision, `core.hooksPath` is **not** enabled by this Phase-2 plan; this specific baseline failure is expected to remain failing, unchanged, through H2-6, and its persistence must not be misclassified as `REGRESSION_CAUSED_BY_PHASE2`.

## Exit criteria for this batch

- [x] Baseline SHA/branch/status recorded.
- [x] Full regression baseline captured with real exit code (`1`) and real summary line (`21 failed, 13694 passed, 15 skipped, 1 warning`).
- [x] `core.hooksPath` classified with corroborating evidence.
- [x] Pre-existing dirty-tree state captured explicitly (3 modified + 11 untracked, matching the 11 UNKNOWN root files this plan must not touch).
