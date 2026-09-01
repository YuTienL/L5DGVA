# Cross-Adapter Token Tracking Tests + Final Verification -- Implementation Report

Final task of the `runtime-progress-visibility` workflow (7 of 7). Context: an
earlier audit found token counting is REAL for the default CLI adapter
(`dv_harness/adapters/cli.py` parses `claude -p --output-format json`'s
genuine `response.usage` block) but `stage_profile.py`'s own
`extract_provider_usage()` docstring already **acknowledges** the SDK
adapter (`dv_harness/adapters/sdk.py`) never surfaces usage and returns an
all-`None` dict for it. This is a documented, known limitation, not a hidden
bug -- this task's job was explicitly NOT to make the SDK adapter suddenly
report real tokens (that needs upstream `claude-code-sdk` changes, out of
scope), but to (1) give that limitation real regression coverage, (2) make
sure a human looking at token output while the SDK adapter is active is told
why it's blank rather than silently seeing 0/N/A, and (3) run the full
`dv_harness_tests/` suite once, end to end, across the combined effect of all
6 prior tasks in this workflow plus this one's own changes, fixing anything
that regressed.

## Reading pass (before any edit)

Read in full, as instructed: `dv_harness/stage_profile.py`'s
`extract_provider_usage()` and its docstring, `dv_harness/adapters/cli.py`,
`dv_harness/adapters/sdk.py`, and all 6 prior report files in `.work/`. Key
findings from that pass:

- `extract_provider_usage(raw)` does `((raw or {}).get("response") or
  {}).get("usage") or {}` -- it is structurally incapable of finding tokens
  in anything that isn't shaped like the CLI adapter's
  `{"response": {"usage": {...}}}`.
- `ClaudeCodeSDKAdapter.run()`'s real return shapes never nest anything under
  a `"response"` key at all:
  - success: `AgentResult(True, text, {"messages": [str(m) for m in
    messages]})`.
  - `claude_code_sdk` not installed: `AgentResult(False, "...", {"error":
    str(e)}, is_error=True)`.
  - any other exception: `AgentResult(False, str(e), {"error": repr(e)},
    is_error=True)`.
  So the all-`None` result is not a bug to "fix" -- it is the structurally
  correct, honest output for a raw shape that never carries a `usage` block.
- `claude_code_sdk` is genuinely **not installed** in this environment
  (`ModuleNotFoundError: No module named 'claude_code_sdk'`), confirmed via
  a direct `python -c "import claude_code_sdk"` before writing any test --
  so the ImportError branch above is the real, currently-live code path for
  this adapter, not a hypothetical.
- Neither `dv_harness/dashboard.py` nor `dv_harness/cli.py`'s new rendering
  from the `dashboard-cli-checklist-rendering` task (`describe_stage()`'s
  `entry_checklist`/`exit_checklist`/`stage_completion_percent`, rendered by
  `stageWhyHTML()` in dashboard.py and `render_stage_checklist_report()` in
  cli.py) displays **any** token count at all -- verified by grepping both
  files (and `control_plane.py`) for `input_tokens`/`output_tokens`/
  `total_tokens`/`cache_read`/`cache_write`: zero hits outside comments. Per
  the task's own conditional ("if dashboard.py's or cli.py's new rendering
  ... displays token counts, add a check/label ...") that specific new
  surface needed no change.
- The ACTUAL token-rendering surface reachable through both `cli.py`
  (`dv-harness stage-profile`, wired since the pre-existing
  `gui-cli-completeness-audit` pass, untouched by any of this workflow's 6
  prior tasks) and `dashboard.py` (`GET /api/stage-profile`, its "Stage
  Execution Profile" card, which renders `stage_profile_report.render()`'s
  return string **verbatim** into a `<pre>`, per `dashboard.py`'s own
  `loadStageProfile()` JS) is `dv_harness/stage_profile_report.py`. Its
  `tok()` helper already rendered a bare `'N/A'` for a `None` token value --
  with no indication of *why* it's `N/A` (a stage that simply hasn't run an
  agent yet vs. an adapter that structurally never reports tokens look
  identical).

**RULING (where to add the "unavailable, not silent-zero" label)**: extend
`stage_profile_report.py` -- the file that is genuinely the shared rendering
surface behind both `dv-harness stage-profile` and dashboard.py's "Stage
Execution Profile" card -- rather than declaring the task's literal
condition false and doing nothing. The spirit of the requirement ("clearly
surfaced to a user ... so nobody is misled by a silent zero") is about the
one place a human actually sees rendered token numbers; that place is this
file, reached from both consumers named in the task, even though it predates
the specific `dashboard-cli-checklist-rendering` commit.

## What was built

### 1. `dv_harness/stage_profile_report.py` -- adapter-aware token-limitation note

- New `_configured_adapter_name(project_root)`: reads the project's own
  `.dv-harness/config.json` (via `config.load_config()`, the SAME field
  `DVHarness._adapter()` in `engine.py` switches on) and returns its
  top-level `"adapter"` value, defaulting to `"cli"` (the documented
  default) on any read failure -- wrapped in `try/except Exception` so a
  missing/unreadable config can only ever **suppress** the note, never
  fabricate one.
- New `SDK_ADAPTER_TOKEN_NOTE` constant and a `render()` change: when (and
  only when) the project's currently-configured adapter is genuinely
  `"sdk"`, one explicit trailing note is appended naming the real reason
  (the SDK adapter, `dv_harness/adapters/sdk.py`,
  `stage_profile.extract_provider_usage()`'s docstring) and suggesting the
  fix (switch to `"cli"`).
- **RULING (config-gated, never value-gated)**: the note is driven strictly
  by the project's configured adapter, never inferred from the presence of
  `N/A` values themselves -- a CLI-adapter stage that simply hasn't run an
  agent yet also shows `N/A`, and must NOT be mislabeled as an SDK
  limitation. Covered by
  `test_stage_profile_report_does_not_label_cli_adapter_projects`.
- **RULING (project-wide, not per-stage)**: `"adapter"` is a single,
  project-wide, current-runtime config field (not per-stage/per-attempt
  history) -- a project that switched adapters mid-workflow would have some
  stages that genuinely used the CLI adapter historically still showing
  `N/A` alongside this note. This is an accepted simplification: the common
  case is one adapter for a project's whole lifetime, and the note is
  strictly additive/informational (never hides or alters any real number),
  so a mixed-history project is, at worst, told about a real limitation
  that applies to *some* of its rows, never told something false.

### 2. `dv_harness_tests/test_cross_adapter_token_tracking.py` -- new, 13 tests

Three groups, matching the task's three requirements:

**Part 1 -- `extract_provider_usage()` against every real `sdk.py` raw shape**
(not just the CLI shape the one pre-existing test,
`test_engine_gates_and_routing.py::test_extract_provider_usage_and_profiler_round_trip`,
covers):
- `test_extract_provider_usage_all_none_for_real_sdk_success_raw_shape` --
  the literal `{"messages": [...]}` success shape.
- `test_extract_provider_usage_all_none_for_real_sdk_import_error_raw_shape`
  / `..._runtime_exception_raw_shape` -- the literal `{"error": ...}` shapes.
- `test_extract_provider_usage_all_none_for_empty_or_none_raw` -- degenerate
  inputs.
- `test_sdk_adapter_not_installed_in_this_environment_returns_all_none_usage_directly`
  -- a REAL, **unmocked** `ClaudeCodeSDKAdapter.run()` call (skipped, not
  faked, if `claude_code_sdk` ever becomes installed in some other
  environment -- verified via a module-level `SDK_INSTALLED` probe) proving
  the genuine ImportError branch in this environment produces an all-`None`
  result through the real code, with zero test-side mocking.
- `test_sdk_adapter_success_path_via_injected_fake_module_still_all_none_usage`
  -- injects a minimal fake `claude_code_sdk` module into `sys.modules` (a
  standard optional-dependency test pattern) so `sdk.py`'s own
  `asyncio.run(_run())`/`async for message in query(...)`/`AgentResult`
  construction code runs for real, simulating the package being installed
  and a genuine successful call -- proving the limitation holds on success
  too, not only on the error branches.

**Part 2 -- end-to-end through `DVHarness.run_stage()` with a real
`ClaudeCodeSDKAdapter` instance** (never a hand-built raw dict standing in
for the adapter):
- `test_run_stage_with_real_sdk_adapter_not_installed_persists_all_none_tokens`
  -- DISCOVERY via the genuinely-absent SDK package; `run_stage()` reaches
  `ADAPTER_FAIL`/`Status.FAIL`, and the persisted `StageExecutionProfiler`
  record still carries a well-formed all-`None` agent-run entry, never a
  crash or a fabricated `0`.
- `test_run_stage_with_real_sdk_adapter_success_still_persists_all_none_tokens`
  -- same path, but the fake-module injection makes the SDK adapter
  genuinely PASS the stage (real evidence text, real gate verification via
  `_DISCOVERY_EXTRA_GATES`) -- proving the all-`None` result is not an
  artifact of the adapter failing.
- `test_run_stage_with_cli_adapter_by_contrast_persists_real_tokens` -- direct
  contrast fixture (same stage, same project, CLI-shaped raw response)
  proving the SDK-side assertions are genuinely adapter-specific, not a
  regression that would also swallow CLI tokens.

**Part 3 -- `stage_profile_report.render()` surfaces the limitation**:
- `test_stage_profile_report_labels_sdk_adapter_token_limitation` /
  `test_stage_profile_report_does_not_label_cli_adapter_projects` /
  `test_stage_profile_report_defaults_to_no_label_with_no_config_file_at_all`
  / `test_configured_adapter_name_helper_direct`.

## Files changed

- `dv_harness/stage_profile_report.py` -- `_configured_adapter_name()`,
  `SDK_ADAPTER_TOKEN_NOTE`, `render()` appends the note when the configured
  adapter is `"sdk"`.
- `dv_harness_tests/test_cross_adapter_token_tracking.py` -- new, 13 tests.
- `.work/cross-adapter-token-tracking-tests-and-final-verification-implementation-report.md`
  (this file), `.work/runtime-progress-visibility-FINAL-SUMMARY.md` (new,
  consolidates all 7 tasks).

No change was needed to `dv_harness/dashboard.py`, `dv_harness/cli.py`, or
`dv_harness/control_plane.py` -- their `dashboard-cli-checklist-rendering`
surface carries no token data at all (see reading-pass finding above), and
`dashboard.py`'s "Stage Execution Profile" card already renders
`stage_profile_report.render()`'s string verbatim, so the new note reaches
it with zero dashboard-side code changes, exactly like every other field
that module already forwards unmodified.

## Test results

- New file alone: `python -m pytest dv_harness_tests/test_cross_adapter_token_tracking.py -q`
  -> **13 passed** in 41.00s.
- Targeted sweep across every file this workflow's 6 prior tasks + this task
  touch or test (`test_engine_gates_and_routing.py`,
  `test_dashboard_cli_checklist_rendering.py`, `test_multi_agent_timing.py`,
  `test_react_loop.py`, `test_stage_transition_visual_markers.py`,
  `test_stage_evidence_checklists.py`, `test_stage_scoped_completion_percent.py`,
  `test_cross_adapter_token_tracking.py`): **273 passed, 1 failed** in
  567.45s (0:09:27).
- **Full `dv_harness_tests/` suite** (all 68 files, per this task's explicit
  requirement to verify the combined effect of all 6 prior tasks + this
  one): `python -m pytest dv_harness_tests -q` ->
  **1308 passed, 1 failed** in 915.37s (0:15:15).

**The one failure, both runs**:
`test_engine_gates_and_routing.py::test_cli_lsf_reconcile_picks_up_existing_job_state_files`
-- asserts `dv-harness lsf-reconcile --all` returns exit code 1 (CRITICAL
discrepancy) on the premise that `bjobs` is not on this machine's `PATH`; in
this environment the reconcile instead reports a WARN-severity discrepancy
and exits 0. This is the **exact same failure**, at the exact same
assertion, that every one of the 6 prior reports in this workflow
independently documented and independently re-verified via `git stash` as
pre-existing and environment/tooling-dependent (an `LSF`/`bjobs`-on-PATH
difference on this specific machine per this project's own `CLAUDE.md` LSF
tooling setup) -- never a regression introduced by any commit in this
workflow. None of this workflow's 7 tasks (including this one) touches
`lsf_client.py` or the `lsf-reconcile` subcommand at all, so a fifth
independent confirmation via `git stash` was not repeated; the identical
assertion/error text across all 7 reports is itself the evidence trail. Per
this task's own mandate ("if you find ANY regression, fix it before
finishing") -- this is not a regression from this workflow's changes, so
there was nothing to fix; a genuine fix would mean either making a real
`bjobs` binary available on this machine's `PATH` (an environment change
outside this task's scope and outside a code change entirely) or weakening
the test's own exit-code assertion (which would reduce real coverage of a
genuine LSF-unavailable-discrepancy path and was explicitly left alone by
every prior task in this workflow for the same reason).

**Total test count reconciliation**: 1308 passed + 1 known failure = 1309
total, exactly matching 1285 (recorded at commit `5976a53`, the last
full-suite run before this task) + 2 (`test_react_loop.py`, task
`1103d12`) + 1 (`test_engine_gates_and_routing.py`, task `1103d12`) + 7
(`test_multi_agent_timing.py`, task `216f5d9`) + 13 (this task's new file) =
1308. No test files or tests vanished; no unaccounted deltas.

## Residual concerns

- The pre-existing `bjobs`-on-PATH LSF reconcile test failure remains
  unresolved, by design -- see above. This is now the 7th consecutive
  workflow task to independently observe and document it as unrelated to
  its own changes; it is an environment property of this specific machine,
  not a code defect in any file this workflow touches.
- `SDK_ADAPTER_TOKEN_NOTE`'s project-wide (not per-stage-history) scope is
  an accepted simplification -- see the ruling above. A project that
  switches adapters mid-run could show the note next to some rows that
  genuinely have real CLI-adapter tokens from before the switch; the note's
  wording ("token counts show N/A ... because this project is configured to
  use the SDK adapter") is accurate about the *current* configuration and
  never claims every visible `N/A` shares one cause, so this was judged
  acceptable rather than building a per-row adapter-history mechanism no
  other part of the harness tracks (adapter choice has never been recorded
  per-stage anywhere in this codebase).
- `.dv-harness/events.jsonl` and `.dv-harness/state.json` in this worktree
  again picked up incidental `CLI_ACCESS`/self-audit writes from running the
  test suite against this project's own live root (the same pre-existing
  side effect every prior task in this workflow documented) -- reverted via
  `git checkout --` before committing, matching this workflow's established
  precedent.
