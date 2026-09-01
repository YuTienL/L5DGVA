# Dashboard/CLI Rendering of Stage Completion Percent + Entry/Exit Checklists

Closes the visibility gap left by the two immediately-preceding passes
('stage-scoped-completion-percent' and 'expected-evidence-checklist-and-
stage-hooks'): both computed real data (`stage_completion_percent`,
`gates_passed`/`gates_total`, `entry_checklist`/`exit_checklist`), but none of
it was actually rendered anywhere a human would see it -- `dashboard.py`'s
"Why (current stage)" card dumped `describe_stage()`'s dict as an opaque JSON
blob, and `cli.py`'s `explain`/`evidence` printed the same raw JSON with no
human-readable rendering. `entry_checklist`/`exit_checklist` specifically
were not even in `describe_stage()`'s returned dict at all -- they only
existed inside the raw `.dv-harness/telemetry/stages/STAGE-*.json` files a
human would have had to open by hand.

## What was built

### 1. `dv_harness/control_plane.py` -- `describe_stage()` now surfaces the checklists

Added `_latest_stage_checklists(root, stage)`: reads
`StageExecutionProfiler(root).all_stages()`, filters to the given
`stage_id`, and returns the **most recent** attempt's `entry_checklist`/
`exit_checklist` (`all_stages()` is already sorted oldest -> newest by
`start_time_epoch`). `describe_stage()`'s returned dict now includes both
keys alongside the pre-existing `gate_verdict`/`gates_total`/
`stage_completion_percent`/etc.

- **RULING**: a stage with no telemetry record at all (never run this
  attempt) reports `entry_checklist`/`exit_checklist` as `None` -- distinct
  from a real record whose checklist is a genuine zero-item dict (node
  declared no `expected_evidence`/`expected_outputs`, which `_run_checklist()`
  already reports as `{"total_count": 0, ..., "completeness_percent": 100.0}`,
  forwarded as-is). This mirrors `stage_profile.py`'s own
  `begin_stage(entry_checklist=None)` "None means not declared" convention
  and lets both the CLI and dashboard renderers show "not run yet" instead of
  a misleading empty checklist.
- This is the ONE shared read path both `dashboard.py`'s
  `current_stage_detail`/`active_stages_detail` (GET `/api/state`) and
  `cli.py`'s `explain`/`evidence`/the new `checklist` subcommand already go
  through -- no duplicated "read latest telemetry record" logic in either
  consumer.
- A retried stage with more than one `STAGE-*.json` record correctly reflects
  the LATEST attempt, not a stale earlier one (covered by
  `test_describe_stage_picks_the_most_recent_of_multiple_telemetry_attempts`).

### 2. `dv_harness/dashboard.py` -- "Why (current stage)" card renders percent + checklists

- Replaced the plain `<pre id="stageWhy">...textContent = ...` dump with
  `document.getElementById('stageWhy').innerHTML = stageWhyHTML(d)`, where
  `stageWhyHTML()` (new JS function) renders:
  - the pre-existing raw stage/status/attempts/blocking_reason/gate_verdict/
    gate_reasons/human_correction/human_approval/takeover block (unchanged
    content, now inside a nested `<pre>` for the same monospace look),
  - a **stage completion progress bar** (`stage_completion_percent`,
    `gates_passed`/`gates_total`, `stage_completion_note`) reusing the
    existing `.bar`/`.bar>div` CSS classes the whole-run progress bar at the
    top of the page already uses -- no new CSS framework, same convention,
  - one `checklistBlock()` per entry/exit checklist: its own mini progress
    bar, one line per declared item with the SAME `icon('PASS')`/
    `icon('FAIL')` checkmark/x-mark helper the Graph card already uses for
    node status (reused, not reinvented), a missing item rendered
    bold+red via the pre-existing `.err` class, and -- directly satisfying
    the "gaps prompt the user for specific detail" requirement -- an
    explicit `Still needs to be supplied: <item_id, item_id, ...>` line
    naming exactly which item(s) are outstanding.
- No escaping helper was introduced: matches this file's existing convention
  (no HTML-escaping function exists anywhere in `dashboard.py` today; every
  other card interpolates state fields into template literals directly,
  since this data all comes from local project files, not untrusted web
  input).

### 3. `dv_harness/cli.py` -- human-readable rendering + a new `checklist` subcommand

Two new module-level functions:
- `_render_checklist_section(title, checklist)` -- one checklist's percent
  line, `[x]`/`[ ]` per item, and a `>>> STILL NEEDS TO BE SUPPLIED: ...`
  line naming the exact missing `item_id`(s) (empty when nothing is
  missing).
- `render_stage_checklist_report(detail)` -- the stage's gate-completion
  percent/`gates_passed`/`gates_total`/`stage_completion_note` line, then
  both checklist sections (entry, exit).

**RULING -- where this attaches**: the task offered a choice between
extending `explain`/`evidence` directly or adding a new subcommand. Both were
done, split by an actual constraint found while implementing:

- `explain --stage` already mixes prose (the static `get_de_explainer()`
  text) with a JSON block, so appending
  `render_stage_checklist_report(detail)` after the existing
  `describe_stage()` JSON dump is purely additive -- verified by
  `test_cli_explain_stage_appends_human_readable_checklist_after_json`.
- `evidence --stage` was **left emitting only the raw `describe_stage()`
  JSON**, unchanged in shape. Reason: the pre-existing test
  `test_cli_evidence_stage_prints_completion_fields`
  (`test_stage_scoped_completion_percent.py`, from the immediately preceding
  pass) does a bare `json.loads()` over `evidence`'s **entire** stdout --
  appending trailing human-readable text would have broken that contract.
  `evidence`'s JSON payload does now carry `entry_checklist`/
  `exit_checklist` automatically (via `describe_stage()`'s extension above),
  so it is not blind to the new data, just JSON-only. Covered by the new
  `test_cli_evidence_stage_stays_pure_json_but_now_carries_checklists`.
- A new `checklist --stage <stage>` subcommand (mirrors `explain`/
  `evidence`'s `--stage`-optional-with-fan-out-fallback shape via
  `effective_active_stages()`) is the dedicated, JSON-free human-readable
  entry point for exactly the data `evidence` carries as raw JSON --
  `dv-harness checklist --stage VERIFY` prints
  `render_stage_checklist_report(describe_stage(...))` and nothing else.

## Tests

New file `dv_harness_tests/test_dashboard_cli_checklist_rendering.py` (11
tests):

1. `describe_stage()` surfaces `entry_checklist`/`exit_checklist` from the
   latest real telemetry fixture file.
2. `describe_stage()` reports `None`/`None` (not a fabricated checklist) for
   a stage with no telemetry record at all.
3. `describe_stage()` picks the LATEST of two telemetry attempts for the
   same stage (retry case), not a stale earlier one.
4. `render_stage_checklist_report()` unit tests: checkmarks/x-marks per item,
   the exact missing `item_id` named in the "still needs to be supplied"
   line, and the zero-items/no-telemetry degenerate cases render sensible
   text with no false "still needs to be supplied" line.
5. `explain --stage` real CLI dispatch: the human-readable block is appended
   after the still-present JSON block.
6. `evidence --stage` real CLI dispatch: stdout is STILL parseable as one
   whole JSON document (guards the pre-existing test's contract) and now
   contains `entry_checklist`/`exit_checklist`.
7. `checklist --stage` real CLI dispatch (in-process via monkeypatched
   `sys.argv`, AND one real out-of-process `subprocess.run` invocation
   proving the subparser is actually wired into `argparse`): human-readable
   output, never a raw JSON dump.
8. `dashboard.HTML` source-level check (same pattern
   `test_active_stages_read_sites.py`'s
   `test_dashboard_graph_highlight_js_uses_active_stages_not_just_current_stage`
   already uses, since no JS engine runs in this test process): the old
   `.textContent =` dump is gone, `stage_completion_percent`/
   `entry_checklist`/`exit_checklist`/`missing_item_ids` are referenced in
   the served JS, the "still needs to be supplied" text exists, and
   rendering reuses the existing `icon('PASS')`/`icon('FAIL')` helper rather
   than inventing a second status-icon mechanism.
9. End-to-end over a REAL HTTP dashboard instance (`dashboard.serve()` on a
   background thread, matching `test_dashboard_interactive.py`'s /
   `test_active_stages_read_sites.py`'s established pattern): GET
   `/api/state`'s `current_stage_detail` genuinely carries
   `entry_checklist`/`exit_checklist` read back from a real telemetry
   fixture file on disk, not just in a unit-level call.

### Test results

- New file alone: `python -m pytest dv_harness_tests/test_dashboard_cli_checklist_rendering.py -q` -> **11 passed**.
- Together with the directly-related existing files (`test_stage_scoped_completion_percent.py`,
  `test_stage_evidence_checklists.py`, `test_active_stages_read_sites.py`,
  `test_graph_parallel_dispatch.py`): **54 passed**.
- Full suite: `python -m pytest dv_harness_tests -q` -> **1277 passed, 2 failed in 914.79s (0:15:14)**
  (1279 tests total; the two failures are both pre-existing/environment-flaky, confirmed
  independent of this change -- see below).

**Failure analysis (both re-verified against the tree with this change's
files `git stash`-ed out, then restored)**:
- `test_cli_lsf_reconcile_picks_up_existing_job_state_files` -- fails
  identically on the unmodified tree (`assert r.returncode == 1` gets `0`
  instead). This is the SAME pre-existing failure the immediately preceding
  pass's report already documented ("a `bjobs`-not-on-PATH CLI subprocess
  exits 1, and on this machine it exits 0 instead -- an environment/PATH
  difference, not a regression"). Untouched by this change (this pass never
  touches `lsf_client.py`/`lsf-reconcile`).
- `test_engine_dispatches_all_three_branches_concurrently_and_joins`
  (`test_graph_parallel_dispatch.py`) -- a timing-sensitive concurrency
  assertion (`span < SLEEP * 1.8` over real `time.sleep(0.25)` windows across
  threads) that failed once under the CPU contention of the full 1279-test
  run, but passed cleanly 3/3 times in isolation on the UNMODIFIED tree
  (`git stash` with this change's files removed) and again with this
  change's files restored. A pre-existing, load-sensitive flaky test
  unrelated to anything touched here (this pass never touches
  `engine.py`'s dispatch/threading code) -- not a regression.

## Residual concerns

- `evidence --stage`'s human-readable rendering is only reachable via the new
  `checklist` subcommand, not `evidence` itself -- a deliberate ruling (see
  above) to avoid breaking a pre-existing test's exact-JSON contract, not an
  oversight. If that pre-existing test is ever relaxed to a substring check,
  `evidence` could append the same rendering `explain` now does.
- `dashboard.py`'s new rendering is JS-side only (no server-side unit-
  testable render function exists for this card, matching this file's
  existing architecture where all client rendering lives in the embedded
  `HTML` string) -- covered by source-level assertions on `dashboard.HTML`
  plus one real end-to-end HTTP test proving the underlying data reaches the
  browser correctly, per this repo's own established test pattern for this
  exact situation (`test_active_stages_read_sites.py`'s JS-highlight test).
- `.dv-harness/events.jsonl` in this worktree again picked up a handful of
  `CLI_ACCESS self-audit` lines from running the pre-existing test suite
  (an existing test invokes the real CLI against this project's own root) --
  left uncommitted/unstaged, same pre-existing side effect the immediately
  preceding pass's report already noted.
