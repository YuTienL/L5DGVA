# Runtime Progress Visibility -- Workflow Final Summary

Branch: `runtime-progress-visibility` (worktree:
`.worktrees/runtime-progress-visibility`). Seven sequential tasks, each
building on the last, all touching some subset of `dv_harness/engine.py`,
`dv_harness/stage_profile.py`, `dv_harness/gates.py`,
`dv_harness/control_plane.py`, `dv_harness/cli.py`, `dv_harness/dashboard.py`,
`dv_harness/react_loop.py`, and `dv_harness/multi_agent.py`. This document is
the final task's consolidation of all 7: what each built, its commit SHA, and
the workflow-wide final test verdict.

## The 7 tasks, in commit order

| # | Task | Commit SHA | Report |
|---|------|-----------|--------|
| 1 | Stage-scoped completion percent | `25e17e71c9ff97475387c1fde39d303329f88954` | `.work/stage-scoped-completion-percent-implementation-report.md` |
| 2 | Expected-evidence entry/exit checklists + stage hooks | `23298b2cf5fbb0db82b802203c04afb2a0d227f1` | `.work/expected-evidence-checklist-and-stage-hooks-implementation-report.md` |
| 3 | Dashboard/CLI rendering of completion percent + checklists | `6f614767fcb577123863aff54db04246881f348d` | `.work/dashboard-cli-checklist-rendering-implementation-report.md` |
| 4 | Stage start/complete visual markers | `5976a53f9ea64b5f193ecd22839ebf61f47219f0` | `.work/stage-start-complete-visual-markers-implementation-report.md` |
| 5 | Per-agent attribution + inner-loop token/runtime accounting | `1103d1245031e50776176ea81862988720c3071d` | `.work/per-agent-attribution-and-inner-loop-accounting-implementation-report.md` |
| 6 | Multi-agent timing reconciliation (AgentTaskStore -> stage_profile) | `216f5d99c6be37461261fd0906e35f639c213b2d` | `.work/multi-agent-timing-reconciliation-implementation-report.md` |
| 7 | Cross-adapter token-tracking tests + final verification (this task) | *committed alongside this report -- see `git log -1` on this branch* | `.work/cross-adapter-token-tracking-tests-and-final-verification-implementation-report.md` |

## What each task built (one paragraph each)

1. **Stage-scoped completion percent** (`gates.py`, `control_plane.py`,
   `react_loop.py`, `cli.py`): added a stage-SCOPED `stage_completion_percent`
   (`gates_passed`/`gates_total`/`stage_completion_note`), computed from the
   same per-gate signature list `_evaluate_stage_evidence_core()` already
   builds, threaded through `describe_stage()` and reachable via `dv-harness
   explain --stage`/`evidence --stage`/`evidence`. Previously the only
   numeric progress signal anywhere was dashboard.py's whole-run
   `overall_progress_percent`. 12 new tests
   (`test_stage_scoped_completion_percent.py`).

2. **Expected-evidence entry/exit checklists + stage hooks** (`graph.py`,
   `main_graph.json`, `engine.py`, `stage_profile.py`): new
   `expected_evidence`/`expected_outputs` node schema fields (populated on 6
   representative stages, every item transcribed from real, pre-existing
   requirements, never invented), plus `build_stage_entry_checklist()`/
   `build_stage_exit_checklist()` -- real, informational-only,
   never-raising presence-checkers wired into `run_stage()` and persisted
   into the SAME `StageExecutionProfiler` telemetry record. 14 new tests
   (`test_stage_evidence_checklists.py`).

3. **Dashboard/CLI rendering of completion percent + checklists**
   (`control_plane.py`, `dashboard.py`, `cli.py`): closed the gap where both
   of the above computed real data but nothing rendered it for a human --
   `describe_stage()` now surfaces `entry_checklist`/`exit_checklist`
   (latest-attempt), dashboard.py's "Why (current stage)" card gained a
   completion progress bar and per-item checklist rendering with an explicit
   "still needs to be supplied" line, and cli.py gained
   `render_stage_checklist_report()` plus a new `checklist --stage`
   subcommand. 11 new tests (`test_dashboard_cli_checklist_rendering.py`).

4. **Stage start/complete visual markers** (`engine.py`, `models.py`,
   `dashboard.py`): `run_stage()` itself now prints
   `[DV-HARNESS-STAGE] ===== STAGE START/DONE: ... =====` markers (sourced
   from `describe_stage()` so they're honest on every exit branch, including
   `ADAPTER_FAIL`), plus a new persisted `HarnessState.last_transition`
   field rendered as an always-visible colored banner at the top of the
   dashboard. 7 new tests (`test_stage_transition_visual_markers.py`).

5. **Per-agent attribution + inner-loop token/runtime accounting**
   (`engine.py`, `react_loop.py`): fixed `run_stage()`'s real
   `add_agent_run()` call site hardcoding the literal `"stage-agent"`
   instead of the actually-resolved agent name, and threaded
   `profiler`/`profile_id`/`agent_name` into `InnerReactLoop` so every real
   reflection/retry `adapter.run()` call it makes is now recorded (was
   previously completely invisible, silently under-reporting stage totals).
   New tests added to `test_engine_gates_and_routing.py` (+1) and
   `test_react_loop.py` (+2).

6. **Multi-agent timing reconciliation** (`multi_agent.py`, `engine.py`):
   `AgentTaskStore.create_task()` gained real `started_at`/`completed_at`/
   `duration_sec` fields plus new `start_task()`/`complete_task()` lifecycle
   methods, wired around `run_stage()`'s real delegated-adapter-call span;
   `add_agent_run()`'s `runtime_sec` now reads this same measured duration
   instead of a second, independently-computed timer -- one source of truth
   for the span, not two. 7 new tests (`test_multi_agent_timing.py`).

7. **Cross-adapter token-tracking tests + final verification** (this task):
   added 13 tests proving `extract_provider_usage()` genuinely returns an
   all-`None` dict for every real raw-response shape
   `dv_harness/adapters/sdk.py`'s `ClaudeCodeSDKAdapter` produces (success,
   import-error, runtime-exception), exercised both via the real,
   currently-uninstalled `claude_code_sdk` package and via a `sys.modules`-
   injected fake simulating a successful installed SDK, and end-to-end
   through a real `DVHarness.run_stage()` call. Extended
   `stage_profile_report.py` (the actual token-rendering surface behind both
   `dv-harness stage-profile` and dashboard.py's "Stage Execution Profile"
   card -- neither of which the `dashboard-cli-checklist-rendering` task's
   own new rendering touches, since that surface carries no token data at
   all) to append an explicit "token data unavailable -- SDK adapter"-style
   note, config-gated (never value-gated) so a CLI-adapter project's genuine
   "hasn't run yet" `N/A` is never mislabeled. Ran the full
   `dv_harness_tests/` suite once as the final regression gate across the
   combined effect of all 7 tasks.

## Cross-cutting rulings worth noting at the workflow level

- Every task that touched a genuinely public function signature (2-tuple/
  3-tuple `evaluate_stage_evidence`/`evaluate_stage_evidence_with_detail`)
  preserved that exact external arity and added new data only via new
  functions or by extending a private/internal helper with no external
  contract -- verified by dedicated regression tests in task 1's report.
- Every informational/reporting addition (checklists, completion percent,
  stage markers, the SDK-adapter note) is additive-only and never gates,
  blocks, or changes a stage's actual `PASS`/`FAIL`/`PARTIAL` verdict --
  each task's own report documents a specific test proving this.
- Every new persisted field on `HarnessState`/`StageExecutionProfiler`'s
  telemetry record defaults to `None`/absent-safe so a `state.json`/
  `STAGE-*.json` file written before that field existed degrades cleanly
  rather than raising `KeyError`.

## Final full-suite verification (this task)

Ran, in order:
1. New file alone (`test_cross_adapter_token_tracking.py`): **13 passed**.
2. Targeted sweep across every file touched or exercised by any of the 7
   tasks (`test_engine_gates_and_routing.py`,
   `test_dashboard_cli_checklist_rendering.py`, `test_multi_agent_timing.py`,
   `test_react_loop.py`, `test_stage_transition_visual_markers.py`,
   `test_stage_evidence_checklists.py`, `test_stage_scoped_completion_percent.py`,
   `test_cross_adapter_token_tracking.py`): **273 passed, 1 failed** in 567s.
3. **The entire `dv_harness_tests/` suite (all 68 files)**:

   ```
   python -m pytest dv_harness_tests -q
   1308 passed, 1 failed in 915.37s (0:15:15)
   ```

**Final verdict: 1308 passed, 1 failed, zero regressions.**

The single failure --
`test_engine_gates_and_routing.py::test_cli_lsf_reconcile_picks_up_existing_job_state_files`
-- is the same pre-existing, environment/tooling-dependent failure (a
`bjobs`-on-`PATH` availability difference on this machine, unrelated to LSF
functionality this workflow never touches) independently documented and
`git stash`-verified by 4 of the 6 prior tasks in this workflow (tasks 1, 2,
4, and 5's reports all reproduce the identical assertion/error text against
their own commit's tree). This task's own full run reproduces it identically
a 5th+ time. No file this workflow's 7 tasks touch (`engine.py`,
`stage_profile.py`, `gates.py`, `control_plane.py`, `cli.py`, `dashboard.py`,
`react_loop.py`, `multi_agent.py`, `graph.py`, `models.py`,
`stage_profile_report.py`) has anything to do with `lsf_client.py` or the
`lsf-reconcile` subcommand this test exercises -- there was nothing in this
workflow's scope to fix, per this task's own mandate to fix genuine
regressions (this is not one).

**Test count reconciliation**: 1285 (last full-suite baseline, recorded in
task 4's report at commit `5976a53`) + 2 (`test_react_loop.py`, task 5) + 1
(`test_engine_gates_and_routing.py`, task 5) + 7 (`test_multi_agent_timing.py`,
task 6, new file) + 13 (`test_cross_adapter_token_tracking.py`, task 7, new
file) = **1308**. Every added test across tasks 5-7 is accounted for; no
unexplained deltas.

## Workflow-wide residual concerns (carried forward, none blocking)

- The pre-existing LSF-reconcile test failure (above) remains open by
  design -- fixing it would mean making a real `bjobs` binary reachable on
  this machine's `PATH` (an environment change, not a code change) or
  weakening the test's own exit-code assertion (rejected by every task that
  encountered it, for the same reason: it would reduce real coverage of a
  genuine LSF-unavailable-discrepancy path).
- Task 3's own residual note stands: `evidence --stage`'s human-readable
  rendering is reachable only via the new `checklist` subcommand, not
  `evidence` itself (a deliberate ruling to avoid breaking a pre-existing
  exact-JSON-output test contract).
- Task 7's `SDK_ADAPTER_TOKEN_NOTE` is gated on the project's currently
  configured adapter (project-wide), not a per-stage adapter-history record
  (which nothing in this codebase tracks) -- see that task's own report for
  the full ruling.
- `.dv-harness/events.jsonl`/`.dv-harness/state.json` in this worktree
  repeatedly pick up incidental `CLI_ACCESS`/self-audit writes from running
  the test suite against this project's own live root -- every task in this
  workflow reverted these via `git checkout --` before committing; this is
  a pre-existing property of several tests in this suite (they invoke the
  real CLI against this project's own root), not a defect introduced by any
  task here.
