# Gap-close: stage progress display (banner / checklist / percentage / reports)

Status: **DONE**
Date: 2026-09-04
Tests: `dv_harness_tests/test_stage_progress_display.py` — **26 passed**;
related-suite sweep (`stage_progress or stage_profile or profile_report or blackboard_subsystem`)
— **52 passed**; broad engine/gate sweep (`engine or run_stage or gate or waveform or qualified or
signoff`) — **946 passed, 1 failed** (`real pueued did not come up`, infrastructure, unrelated).
See "Regression triage" below — no failure anywhere is attributable to this work, and that was
established by re-running against a pristine `HEAD` worktree rather than assumed.

## What the user asked for

Four requirements, in the user's own words:

1. 執行過程要能顯示目前所在階段和目前該階段還有哪些待完成項目及距離完成的百分比.
2. 每個階段**開始**用明顯的 Logo（使用者澄清：文字/ASCII art，非圖檔）顯示，同時顯示所需要的
   文件、檔案和相關資料清單和完整度百分比，並提醒使用者哪些項目需要再提供詳細資料.
3. 每個階段**結束**用明顯的 Logo 顯示，同時顯示輸出的檔案和相關資料清單和完整度百分比，
   並顯示總執行時間（含各個 Agents）和所耗掉的 token 數量.
4. 儲存 2、3 顯示的內容為 reports.

## State found at dispatch (important — this was not a clean start)

The dispatch note said `engine.py` should be clean/committed. It was not. `git status` showed
`engine.py` and `stage_profile_report.py` modified, plus untracked
`dv_harness/stage_progress_display.py` and `dv_harness_tests/test_stage_progress_display.py` —
i.e. a substantially complete prior attempt at *this same feature*, uncommitted.

Stranger still, the **CLI half was already committed**: `dv-harness stage-report` exists in
`HEAD:dv_harness/cli.py`, swept into commit `6fe388b`
("research(stage-1): route research intent…") by a concurrent workstream that did not own it.
So the feature was split across a committed CLI front door and an uncommitted implementation —
a state in which `dv-harness stage-report` was reachable from a clean checkout but would have
raised `ModuleNotFoundError`.

I verified the uncommitted work was real (not scaffolding), ran it, found and fixed three real
defects, and added tests. I did not rewrite it.

## Requirement-by-requirement, against real sources

| Req | Where | Real source it reads |
|---|---|---|
| 1 stage + outstanding + % | `render_stage_start_display` / `render_stage_done_display` | `policy.ORDER` for `STEP : n/39`; checklist `completeness_percent`; pre-existing `stage_completion_percent` |
| 2 start banner + input checklist + reminder | `build_stage_input_checklist`, `build_detail_requests` | `node.blackboard_read`, `node.expected_evidence`, `gates.effective_stage_gates()`, `gates.INTAKE_FIELD_QUESTIONS` |
| 3 done banner + output checklist + time/tokens | `build_stage_output_checklist`, `stage_time_and_token_summary` | `node.blackboard_write`, `node.expected_outputs`, `STAGE_GATES`, `StageExecutionProfiler` records |
| 4 persisted reports | `save_stage_report` | the exact rendered string, embedded verbatim |

No parallel checklist source was invented. `test_input_checklist_items_are_exactly_the_real_declared_sources`
asserts the item-id set **equals** the union of those real declarations — nothing extra, nothing missing.

### Wiring (extends, does not replace)

`_emit_stage_start_marker` / `_emit_stage_done_marker` are untouched and still emit their
one-line greppable `[DV-HARNESS-STAGE]` markers, so any existing log scraper is unaffected
(asserted by a test). Two **sibling** functions, `_emit_stage_start_display` /
`_emit_stage_done_display`, run alongside them in `run_stage()`, each wrapped in `try/except`:
observability must never turn a stage that really ran into a failed one
(`test_display_failure_never_fails_a_real_stage`).

The DONE display is placed **after** `profiler.end_stage()` so the telemetry it reads back is the
completed record — wall clock and per-agent totals are only final once `end_stage()` has run.

### "including all sub-agents" — checked, and it is genuinely real

The dispatch asked me to verify whether the token/time numbers actually aggregate sub-agent
dispatches or only the main session. They do aggregate. `StageExecutionProfiler.add_agent_run()`
has three real production call sites:

- `engine.py:3205` — the main stage dispatch;
- `react_loop.py:407` — the ReAct reflection sub-agent;
- `react_loop.py:554` — the targeted-retry / re-ask sub-agent.

`rec['input_tokens']/['output_tokens']/['total_tokens']/['aggregate_agent_runtime_sec']` are
already sums across that whole `agents` list. So the *data* was never the gap. The real gap was
that **nothing rendered it** — no surface anywhere showed the per-agent rows, so "does this number
include the sub-agents?" was unanswerable without opening raw telemetry JSON.
`render_stage_time_and_tokens()` is that missing surface: one row per agent run, plus an explicit
`ALL AGENTS RUNTIME (incl. sub-agents)` line. It also surfaces cache_read/cache_write tokens,
which `render()` never showed and which are real tokens consumed.

`token_data_available` stays an explicit flag rather than being inferred from a zero: zero tokens
and "this adapter never reports tokens" (the SDK adapter, by design) are different facts.

## Three real defects found and fixed

**1. Section-rule width drift (cosmetic, but exactly what the code warned about).**
`stage_profile_report.py` built its own rule as `'-- EXECUTION TIME AND TOKENS ' + '-' * 50` = **79**
chars, while every checklist rule came from `_rule()` at **80** — so the one section rendered by the
other module sat a character short of the banner above it. `_rule`'s own docstring already warned
"every caller previously hardcoded its own subtraction constant, and one of them was wrong"; that
caller was still wrong. Fixed by promoting it to a public `section_rule()` and having
`stage_profile_report` import it (lazily, so neither module can make the other unimportable) rather
than copying the constant. A corrected constant would only have been correct until the next title
changed length. Locked by `test_every_section_rule_is_the_same_width_as_the_banner`.

**2. Report listing ordered by filename, so `latest` returned the wrong file.**
`list_stage_reports` documented "oldest first" but sorted raw filenames — and `"done"` sorts before
`"start"`, so **every DONE report was reported as older than every START report regardless of when
either was written**. User-visible consequence: `dv-harness stage-report INTAKE` printed the banner
for the *beginning* of a stage that had already finished. Fixed by sorting on the embedded
timestamp, with a phase tiebreak so a start/done pair written in the same second still reads in the
order it really happened.

**3. Stage filter was a name prefix, so it leaked other stages' reports.**
The filter was `name.startswith(stage + "_")`. The real `policy.ORDER` contains **BUILD alongside
BUILD_DEBUG**, and **REGRESSION alongside REGRESSION_SELECT and REGRESSION_MONITOR** — so asking for
`BUILD`'s reports returned `BUILD_DEBUG`'s too, under `BUILD`'s name. Fixed with a structural
`_parse_report_name()` that splits from the **right** (phase and timestamp never contain `_`;
stage names do) and matches the stage exactly. A stray hand-dropped `.md` now parses to `None` and
is skipped rather than being listed as a stage report with a garbage stage name.

Defects 2 and 3 were both found by actually exercising the CLI, not by reading the code.

**4. `.dv-harness/stage_reports/` was not gitignored.** Two markdown files are written per stage
*attempt*, so one real run over the 39-stage order leaves dozens of new files and every retry adds
two more. That is precisely the per-run runtime-state class `.gitignore`'s existing block was
written to exclude ("rewritten continuously by a live session… belongs to the machine it was
produced on"), and leaving it out left a careless `git add -A` free to sweep a run's worth of
reports into an unrelated commit — the exact failure that block already documents having happened
once with `watcher.pid`. Added, with the reasoning recorded alongside the neighbouring entries.

## Verification

Real `DVHarness.run_stage("INTAKE")` against the **real shipped graph**
(`.dv-harness/graph/main_graph.json`) with a real gate battery, asserting:

- both banners reach the terminal, START before DONE;
- `COMPLETENESS:` matches the checklist's own `[x]`/`[ ]` line count, for **every stage the real
  graph can produce** (`test_completeness_percent_always_matches_the_checklists_own_item_count`);
- the saved report's embedded display is byte-identical to what was printed (`display in out`);
- the DONE report's time/token block carries the real agent run with the adapter's real usage
  (`total_tokens == 1020`);
- a dry run emits no START display and leaves no report file behind.

The percentage cannot drift from the checklist because there is exactly one render: both the
terminal and the report file consume the same string.

Two earlier regressions are also locked by tests, both found by real runs rather than predicted:
INTAKE's `expected_evidence` entry *is* its `blackboard_read` topic `environment` restated, and its
`expected_outputs` entry *is* the `STAGE_GATES` gate id — counting each twice inflated the
denominator and printed the same reminder line twice, so `_dedupe()` merges them while recording
every declaration that asked. And the report's fences are **four** backticks, because the checklist
text it embeds names the three-backtick evidence fences it is asking for; a three-backtick wrapper
was closed early by its own content.

## Regression triage — every failure run down to a cause, none of them mine

A `-k "stage_progress or engine or run_stage"` sweep reported **6 failed, 341 passed**. Rather than
wave those off, I built a **pristine `HEAD` worktree** (containing none of this work) and re-ran the
failing tests there. Results:

| Failure | Verdict |
|---|---|
| `test_graph_parallel_dispatch::test_engine_dispatches_all_three_branches_concurrently_and_joins` | **Fails at pristine HEAD too** — pre-existing wall-clock/concurrency flake, not mine |
| `test_engineering_confirmation_accumulation.py` (4) | The file **does not exist at HEAD** — another workstream's uncommitted work. All **12 pass in isolation** |
| `test_engine_gates_and_routing::test_self_audit_against_real_repo_reports_real_current_findings` | **Passes at HEAD**, and **passes in isolation**, and **passes when run together with all 26 of my tests** (27/27) |

So every failure is either pre-existing or **cross-suite interference** between concurrently-developed
test files that all pass on their own. This work cannot be the cause: all 26 of its tests are
`tempfile.mkdtemp()`-scoped (verified — 8 call sites, and the real repo has no
`.dv-harness/stage_reports/` after a full run), so they write nothing into the shared real-repo
state that the interference is happening through.

**Worth flagging to whoever integrates this**: several suites in this repo audit or mutate the
*real* repo's `.dv-harness/` and therefore fail when run together while passing individually. That
is a real latent problem in the test suite — independent of this change, but it will keep producing
misleading red runs until those suites are isolated.

## Known limitation, stated rather than implied closed

The display fires at stage **boundaries**. Requirement #1 read literally ("執行過程要能顯示目前
所在階段") could also mean a continuously-updating mid-stage progress indicator; that is not what
this builds, and there is no engine hook for it — `run_stage()` blocks on a single adapter dispatch
with no intermediate progress callback. What exists is: a full outstanding-items view at every
stage start, the same at every stage done, and `dv-harness stage-report <stage>` to re-render the
last saved one at any time in between. A true mid-stage live indicator would need a progress
callback threaded through the adapter layer first.

## Files

- `dv_harness/stage_progress_display.py` — new module (banner, checklists, reminder, reports)
- `dv_harness/stage_profile_report.py` — added `stage_time_and_token_summary()` /
  `render_stage_time_and_tokens()`; now shares `section_rule()`
- `dv_harness/engine.py` — two sibling emit functions + two guarded `run_stage()` call sites
- `dv_harness/cli.py` — `dv-harness stage-report [stage] [--phase start|done] [--list]`
  (already committed in `6fe388b`)
- `dv_harness_tests/test_stage_progress_display.py` — 26 tests
