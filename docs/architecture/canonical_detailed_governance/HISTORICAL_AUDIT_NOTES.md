# Historical / Non-Normative Audit Notes

Moved out of CLAUDE.md during **M4.6 — CLAUDE Context Normalization**. Registered as `id: HISTORICAL_AUDIT_NOTES`, `load_policy: EVIDENCE_ON_DEMAND`. These sections are retrospective status/closure markers (`[CLOSED, ...]`, "Audited Already Satisfied", verification-pass narrative), not present-tense normative rules -- preserved here for provenance per the instruction "do not delete evidence merely because it is no longer normative," but never ALWAYS_ON and never preloaded for ordinary task execution.

---

<!-- S195: moved verbatim from CLAUDE.md original lines 11270-11296 (M4.6 CLAUDE Context Normalization) -->
### What is genuinely real, verified independently of the items' own claims

Every code-level claim below was re-confirmed directly (`grep`, file existence, and/or the test
runs above), not taken on the items' word:

- `dv_harness/web_layout.py` exists: four pure, stdlib-only HTML-fragment functions
  (`page_shell`/`render_status_bar_partial`/`render_nav`/`render_card`), proven by
  `test_web_layout.py` (33 tests, passing).
- `dashboard.py` carries a genuinely new, additive `GET /view/dashboard` route
  (`elif self.path == "/view/dashboard":`) built through `web_layout.py`'s functions, rendering
  GUI-13's twelve metrics from already-real producers (`harness_status`, `requirement_contract`,
  `vplan_artifact`, `regression_reporter`, `waiver_store`, `coverage_analysis`) -- confirmed by
  direct grep and by `test_dashboard_executive_view_route.py` (6 tests, passing). The `/` route's
  own markup is untouched.
- `dashboard.py` carries a genuinely new `_external_gui_server_nav_routes(root)` function,
  surfacing real links to `gui_intake_control_plane.py`'s and `gui_intake_wizard.py`'s standalone
  servers from the `/view/dashboard` page's nav -- confirmed by direct grep and by
  `test_dashboard_cross_server_nav_links.py` (5 tests, passing).
- `dashboard.py`'s served `/` page carries a genuinely new, additive `new
  EventSource('/api/events/stream')` call (`initGlobalStatusBarSSE()`), layered on top of the
  pre-existing, unaltered `setInterval(load,3000)` poll loop -- confirmed by direct grep and by
  `test_dashboard_status_bar_sse_wiring.py` (2 tests, passing).
- `gui_intake_wizard.py` and `gui_intake_control_plane.py` both now import `web_layout` and render
  its `render_nav()`/`render_status_bar_partial()` output at a fixed point inside `<body>` --
  confirmed by direct grep; both files' own test suites (`test_gui_intake_wizard.py`,
  `test_gui_intake_control_plane.py`) pass alongside the rest of the 403-test combined run above.


<!-- S196: moved verbatim from CLAUDE.md original lines 11297-11311 (M4.6 CLAUDE Context Normalization) -->
### A real discrepancy this verification pass found and is disclosing rather than silently fixing

Three of this batch's six items (P1-1, P2-1, P2-2) each reported in their own `claude_md_note`
field that they had **already appended** a dedicated CLAUDE.md section documenting their work
("Added a new top-level CLAUDE.md section... appended at end of file"). Independent verification
found **none of those three sections anywhere in this file** (`grep -n -i "web layout\|
view/dashboard\|Executive View\|Cross-Server Nav\|status_bar_sse\|SSE Wire" CLAUDE.md` returned
zero matches before this section was added). The underlying CODE those items describe is real and
verified above; the specific claim that a CLAUDE.md section documenting it had *already* been
written was false for all three. This section is written now, by the independent verification
pass, to close that documentation gap honestly -- it is not evidence the code itself was
fabricated, only that three items' bookkeeping claim about their own CLAUDE.md edit did not match
what actually landed on disk. The other three items (P0-1, P2-3, P1-3) correctly stated they
made no CLAUDE.md edit of their own, and did not.


<!-- S197: moved verbatim from CLAUDE.md original lines 11312-11332 (M4.6 CLAUDE Context Normalization) -->
### What remains genuinely, honestly open

- **STATUS-AT-36 stays skipped, correctly.** Its skip reason (re-verified in the live file) states
  the real, narrower remaining gap plainly: the SSE wiring this batch built is real and tested, but
  no PRODUCTION code path anywhere in this repo (including `engine.py`) ever calls
  `live_event_model.emit()` -- confirmed again independently by grep during this pass. A real
  harness run today produces no GUI_* events for the SSE wiring to react to; the wiring and a real
  emitting producer remain two disconnected halves. This is disclosed, not silently claimed closed.
- **STATUS-AT-03's skip reason is very likely stale but was left untouched by every item in this
  batch.** It still reads "No Web page renders HarnessStatusIR anywhere in this repo yet" and
  "dashboard.py has no reference to harness_status at all" -- both demonstrably false today: the
  new `/view/dashboard` route renders `HarnessStatusIR`-derived metrics, and `dashboard.py` has
  real `harness_status` references throughout. STATUS-AT-26's skip reason ("No Web renderer exists
  at all (see STATUS-AT-03)") inherits the same staleness. Neither was in this batch's declared
  scope and neither was re-verified or re-worded by any of the six items; they are flagged here for
  a future pass to pick up rather than silently left to look current.
- **The `/view/dashboard` status bar is a static shell**, not live-polling like `/`'s -- disclosed
  in P2-2's own work and re-confirmed here: STATUS-AT-04 proves the bar's structural persistence
  across navigation (the literal acceptance criterion), not that its live-data behavior matches `/`
  on that second page.


<!-- S198: moved verbatim from CLAUDE.md original lines 11333-11349 (M4.6 CLAUDE Context Normalization) -->
### Overall honest state of the "no independent GUI/Web layout" gap

**Substantially closed, not fully closed, and the boundary is real rather than cosmetic.** A
genuinely separate, smaller HTML document (`/view/dashboard`) now exists, built through a real,
independently-tested, stdlib-only module (`web_layout.py`) that is completely decoupled from
`dashboard.py`'s existing `/` route -- the `/` route's own ~8,600-line HTML/CSS/JS string was
never touched by any of this batch's six items, confirmed directly. That second page is REACHED
(a human or script can navigate to it today) but not fully WIRED into the main `/` page's own nav
(deliberately, to avoid risking `/`'s working markup). Two previously-standalone GUI servers
(`gui_intake_wizard.py`, `gui_intake_control_plane.py`) now share real markup fragments with the
main dashboard and are cross-linked from `/view/dashboard`. Three real STATUS-AT acceptance items
(02, 04, 18) that depended on this layer existing are now genuinely, verifiably passing where they
were honestly skipped before. What remains open is disclosed above rather than folded into an
overstated "fully closed" claim: STATUS-AT-36's producer-side gap, STATUS-AT-03/26's stale skip
text, and the static-vs-live status-bar distinction on the new page.



<!-- S205: moved verbatim from CLAUDE.md original lines 11576-11585 (M4.6 CLAUDE Context Normalization) -->
### A real, pre-existing concurrency defect found and fixed along the way (`storage.py`)

Writing the tests above (driving the real `ThreadPoolExecutor` fan-out with no artificial per-branch sleep) reproduced a genuine, pre-existing race in `storage.StateStore.event()`: `engine._advance_with_fanout()` runs every `parallel_group` branch (RCA_G1 and ANALYSIS_G1 both) via `ex.submit(self._run_branch_to_terminal, ...)` on the SAME `DVHarness` instance, so every branch thread's `run_stage()` calls `self.store.event(...)` concurrently against one shared `StateStore`. `event()` was a plain, unretried, unlocked `events_file.open("a", ...)` -- unlike `state.json` (`StateStore.save()`, via `_atomic_replace()`) and every Blackboard topic (`blackboard.py`'s `write()`), which already retry the identical transient Windows `PermissionError` (WinError 5). This produced two real, independently-reproduced failures: a `PermissionError` from the `open()` call itself, and -- confirmed separately under real concurrent-thread stress -- a genuinely LOST event line with no exception raised at all (Windows' CRT-level text-mode append is a seek-to-end-then-write, not POSIX `O_APPEND`'s atomic single write, so two interleaved writer threads can each seek to the same offset and one silently overwrite the other).

Fixed minimally and additively: `StateStore.__init__` gained one `threading.Lock` instance attribute, and `event()` now serializes its write under that lock (closing the real in-process race the fan-out actually produces, since every branch thread shares one `StateStore` object) plus keeps the same short retry-on-`PermissionError` backoff `_atomic_replace()` already uses as a second, independent safety net for a genuinely external/cross-process case. No signature changed, no return value changed, no behavior changed on the non-racing path.

Proven by a new `dv_harness_tests/test_storage_event_retry.py` (4 tests): normal append behavior is unchanged; a transient `PermissionError` is retried and the line still lands; a persistent `PermissionError` still raises after the retry budget (the same honest failure mode `_atomic_replace()` already keeps -- an event line is never silently dropped); and a real multi-threaded stress test (8 threads x 15 writes) independently recounts every line rather than trusting this module's own bookkeeping -- run 25/25 times with zero loss after the fix, against 5/15 real, reproduced failures (both the `PermissionError` and the silent-loss shape) before it. The previously-flaky new contradiction-detection test above was 20/20 stable after this fix, against a real ~1-in-8 failure rate before it.

**Regression discipline.** `dv_harness_tests/test_rca_multi_agent_fanout.py` + `test_workflow_rca_multi_agent_fusion.py` + `test_cli_blackboard.py` (the RCA fan-out's own real test suite) ran 22/22 green before any change and 36/36 green after (11 in the fan-out file: 7 original + 4 new, plus the 4 new storage tests and the untouched `test_graph_parallel_dispatch.py`'s 6 for the sibling ANALYSIS_G1 fan-out this same fix also protects). `dv_harness_tests/test_engine_gates_and_routing.py` reported 238 passed / 1 failed both before and after this change, byte-identically -- the one failure (`test_verification_architecture_requires_fabric_topology_completeness_gate`) is a confirmed, disclosed, pre-existing residual from `STAGE_GATES["VERIFICATION_ARCHITECTURE"]`'s gate registration (a separate, concurrently-running body of work this same session), independently reproducible in total isolation with none of this change's edits present, and never touches RCA_JOIN, the Blackboard, or `storage.py`. Zero regressions were introduced by either edit.


<!-- S240: moved verbatim from CLAUDE.md original lines 14086-14155 (M4.6 CLAUDE Context Normalization) -->
## Stage-End Banner: Real Per-Stage Wall-Clock Time + Honest Token Consumption -- Audited Already Satisfied (2026-09-07)

`self_check_list.md` #34 (a stage-end banner naming output files produced, a real completeness
percentage, TOTAL WALL-CLOCK TIME across all agent dispatches in that stage, and TOKEN CONSUMPTION for
that stage IF the underlying adapter genuinely exposes it -- honestly `NOT_AVAILABLE` otherwise, never
estimated) was assigned to this session as `stage_time_token_tracking`, explicitly instructed to run
AFTER `stage_entry_exit_banner` (see this file's own "Stage Progress Displays: #32 Real-Time Progress +
#33 Stage-Entry Banner" section immediately above) and build additively on its real `engine.py`
changes. Auditing `engine.py`'s `run_stage()` and `dv_harness/adapters/cli.py` FIRST, per house style
and per this item's own explicit first-check instruction, found the gap already closed -- by the same
concurrent-batch work that built `stage_entry_exit_banner`'s own display layer, evidently one commit
earlier in that same session (`dv_harness/stage_profile.py`/`stage_profile_report.py` predate
`stage_progress_display.py`, which imports both). No code change was made here; this section is the
missing CLAUDE.md record for work that already landed with real, passing tests, exactly the outcome
`stage_entry_exit_banner`'s own audit section above documented for its sibling gap.

**The first-check instruction's own question, answered from the real code.**
`dv_harness/adapters/cli.py`'s `ClaudeCLIAdapter.run()` invokes the real `claude -p --output-format
json` subprocess and parses its stdout as JSON into `raw["response"]` (the CLI's own real envelope,
which DOES carry a `usage` block -- `input_tokens`/`output_tokens`/`cache_creation_input_tokens`/
`cache_read_input_tokens`, confirmed by reading `stage_profile.extract_provider_usage()`, which reads
exactly those four keys off exactly that path). So the CLI adapter's own JSON envelope genuinely
DOES return usage data, as this item's own instruction anticipated ("many CLI tools of this shape
do") -- and the harness already REUSES that real data rather than building new instrumentation, per
the item's own REUSE OVER REINVENT instruction: `add_agent_run()` (`stage_profile.py`) is called with
that `usage` dict at every real adapter dispatch (both `engine.run_stage()`'s own main stage call and
`react_loop._record_agent_run()`'s sub-agent calls), and sums it per stage.

**What is real and wired, confirmed by reading the code rather than trusting a docstring.**
`_emit_stage_done_display()` (`engine.py` ~199-220), called from the real stage-exit path immediately
after `_emit_stage_done_marker()` (~4798-4814, wrapped in `try/except` so a display failure can never
turn a real PASS/FAIL into something else), calls `stage_profile_report.stage_time_and_token_summary()`
and renders it via `stage_progress_display.render_stage_done_display()` ->
`stage_profile_report.render_stage_time_and_tokens()`. That render function prints, per real
`StageExecutionProfiler` telemetry (never re-derived, never estimated): **output files produced** (via
`spd.build_stage_output_checklist()`, the real presence-checked checklist `stage_entry_exit_banner`
built); **real completeness percentage** (the gate-derived `stage_completion_percent` passed straight
through); **TOTAL WALL-CLOCK TIME across all agent dispatches** -- `STAGE WALL CLOCK` (the stage's own
elapsed time) AND, separately and explicitly labelled, `ALL AGENTS RUNTIME (incl. sub-agents)` (the
real summed `aggregate_agent_runtime_sec` across every one of that attempt's real agent/sub-agent
dispatches, `agent_run_count` named alongside it) plus a `STAGE TOTAL (all N attempt(s))` roll-up
across every retry -- always measurable and always shown, exactly the item's own "build this even if
token data is not" requirement; and **token consumption, honestly gated on real availability** -- a
`token_data_available` flag computed from whether ANY real agent run in the stage actually reported a
`total_tokens` value (never inferred from a zero), rendered per-agent and per-stage as `N/A` (this
project's own existing spelling for the identical "we did not fabricate this number" concept the item's
`NOT_AVAILABLE` wording names) whenever that flag is `False` -- and, going further than the item asked,
an explicit `SDK_ADAPTER_TOKEN_NOTE` naming the REAL, DISCLOSED reason for the specific case where the
configured adapter is `sdk` (whose own `run()` never surfaces a `usage` block at all, per
`adapters/sdk.py` and `extract_provider_usage()`'s own docstring), so a viewer can never mistake a
genuine adapter limitation for a broken measurement or an untouched stage.

**Verification performed by this audit.** `python -m pytest dv_harness_tests/
test_stage_progress_display.py -q` -> 34 passed, including
`test_time_and_token_summary_includes_every_sub_agent_run` (asserts `token_data_available is True` and
every per-agent row renders with real numbers), `test_time_and_token_summary_distinguishes_no_usage_
from_zero_usage` (asserts `token_data_available is False` and `"N/A"` appears in the render -- the
negative control proving the module refuses to fabricate a token count when the adapter did not supply
one), and `test_time_and_token_summary_handles_a_stage_that_never_ran` (a stage with no telemetry record
at all reports "no telemetry record for stage ... yet" rather than a fabricated zero). Confirmed wired
into the real stage-exit path (not merely defined) by direct grep: `_emit_stage_done_display` is called
from `run_stage()` at line ~4808, one line after `_emit_stage_done_marker()`.

**Deliberately bounded, and stated rather than implied closed.** This audit made no edit to `engine.py`,
`stage_profile.py`, `stage_profile_report.py`, or `stage_progress_display.py` -- the mechanism, its
wiring, and its test coverage were already complete and correct against this item's own governing
instruction (first check the adapter, reuse rather than rebuild, always show wall-clock time, never
fabricate token consumption). Nothing here runs a build, a regression, or an LSF job; the banner is
informational and print-only, matching `stage_entry_exit_banner`'s own disclosed scope.


<!-- S242: moved verbatim from CLAUDE.md original lines 14253-14334 (M4.6 CLAUDE Context Normalization) -->
## Persisted Stage Banner/Timing Reports: #35, Last in the Sequential Phase -- Audited Already Satisfied (2026-09-07)

`self_check_list.md` #35 ("同時儲存 #33,#34 顯示 reports") was assigned to this session as
`persist_stage_banner_reports`, explicitly scoped to run LAST in this sequential phase, after both
sibling banner items (#33's stage-ENTRY banner, this file's `stage_entry_exit_banner` gap-close, and
#34's stage-END banner/timing summary, this file's `stage_time_token_tracking` audit immediately
above) -- with an explicit instruction to read those two siblings' real output SHAPE first and persist
exactly that, never invent a different one. Per house style and this item's own instruction, that
audit was done FIRST, before writing anything: both `_emit_stage_start_display()` and
`_emit_stage_done_display()` (`dv_harness/engine.py`) were read in full, and so was every function
either one calls in `dv_harness/stage_progress_display.py`.

**The gap was already closed** -- by the same prior work in this batch that built #33/#34's own
display layer, not by this session. `stage_progress_display.py` already carries a real persistence
half (`STAGE_REPORT_SUBDIR = Path(".dv-harness") / "stage_reports"`, `save_stage_report()`,
`list_stage_reports()`, `latest_stage_report()`), and both real call sites already use it: RIGHT AFTER
rendering and printing the stage-START display, `_emit_stage_start_display()` calls
`spd.save_stage_report(root, stage, "start", text, payload={...})`; RIGHT AFTER rendering and
printing the stage-DONE display (including its real time/token summary), `_emit_stage_done_display()`
calls `spd.save_stage_report(root, stage, "done", text, payload={...})`. Each call persists to
`.dv-harness/stage_reports/<stage>_<phase>_<timestamp>.md` -- a real, queryable, per-project location
following this project's own `.dv-harness/` convention for every other per-stage artifact
(`connectivity_check_report.md`, `benchmark_datasets/`, `experiments/`, `signoff/freezes/`, ...), so a
later session or the dashboard can read a stage's banner history back without re-running anything.

**It persists EXACTLY the shape the two sibling items produce, never a re-derived or narrower one** --
confirmed by reading, not assumed. The persisted file's body is the SAME `text` string that was just
printed to the terminal, embedded verbatim inside a FOUR-backtick fenced block (`` ```` ``, deliberately
not three -- the checklist text a banner embeds cites three-backtick evidence fences like
`` ```dv-harness-evidence:<gate_id>``` ``, and a three-backtick wrapper would be closed early by its
own content, a defect `save_stage_report()`'s own docstring says was "found by a real test, not
predicted"), so the file and the terminal can never disagree because there is only one rendered
string and both consume it. A `payload` dict of the SAME structured data that shape was rendered
from -- the real input/output checklist, the real detail-requests/outstanding list, and (stage-DONE
only) the real `stage_time_and_token_summary()` result -- is appended as a second fenced JSON block,
so a later reader (or the dashboard) can read the underlying numbers back without re-parsing the
ASCII banner. Nothing here re-derives a number or re-checks a file a second, possibly-disagreeing way:
both call sites hand `save_stage_report()` the exact `text` and `payload` already computed for the
print, and `save_stage_report()` itself performs no additional computation on them beyond writing.

**Persisted, never fabricated: the resilience and honesty rules the two sibling banners already
established survive intact into the persisted copy, because it is the identical write path.** Both
call sites are wrapped in `try/except` at `run_stage()` (`# observability must never fail a real
stage`), so a `save_stage_report()` failure -- disk full, a permissions error, a malformed payload --
can never turn a stage that genuinely PASSED/FAILED into something else; it only prints
`stage start/done display unavailable: <exc>` and the run continues. A stage that never actually
started (a takeover, or `dry_run=True`) emits no banner and therefore saves no report file at all --
proven directly (`test_takeover_and_dry_run_never_emit_a_stage_start_display` asserts
`spd.list_stage_reports(tmp) == []`), so a persisted report can never claim a stage ran when it did
not. The stage-DONE payload's `time_token_summary` carries #34's own `token_data_available` honesty
flag and `N/A` rendering unchanged -- persisting the banner never upgrades an honestly-unmeasured
token count into a fabricated one; it is the SAME dict, saved.

**Verification performed by this audit.** `python -m pytest
dv_harness_tests/test_stage_progress_display.py -q` -> 34 passed (re-run fresh by this audit, not
merely cited from a prior report), including the full persistence suite:
`test_saved_report_content_matches_what_was_displayed` (the file and the terminal embed the identical
string), `test_report_fences_survive_the_evidence_fences_the_display_itself_names` (the real
four-backtick-vs-three-backtick regression this module's own docstring cites),
`test_report_listing_filters_by_stage_and_phase`,
`test_reports_are_ordered_by_timestamp_not_by_filename`,
`test_stage_filter_is_exact_not_a_name_prefix` (three more real, named regressions this file's own
comments document), a real end-to-end `run_stage()`-driven test asserting a real saved stage-start AND
stage-done report both exist and their payloads carry the real checklist/gate/time-token data (lines
772-824), and the two negative controls described above
(`test_display_failure_never_fails_a_real_stage`,
`test_takeover_and_dry_run_never_emit_a_stage_start_display`). Confirmed wired into the real
stage-boundary path (not merely defined) by direct grep of `dv_harness/engine.py`: both
`_emit_stage_start_display()` (called at line ~4260, inside `run_stage()`'s stage-START section) and
`_emit_stage_done_display()` (called at line ~4808, one line after `_emit_stage_done_marker()`) call
`spd.save_stage_report()` on every real invocation, printing the saved path
(`{STAGE_MARKER_PREFIX} stage {start,done} report saved: {path}`) so the persisted location is itself
observable in the terminal/log.

**Deliberately bounded, and stated rather than implied closed.** This audit made no edit to
`engine.py` or `stage_progress_display.py` -- the persistence mechanism, its wiring at both real
call sites, and its real test coverage (including both required resilience/honesty negative
controls) were already complete and correct against this item's own governing instruction (persist
exactly the two siblings' real output shape, under `.dv-harness/`, queryable by a later session).
Nothing here runs a build, a regression, or an LSF job; persistence is a plain markdown-file write,
matching #33/#34's own disclosed print-only/informational scope.


<!-- S245: moved verbatim from CLAUDE.md original lines 14455-14503 (M4.6 CLAUDE Context Normalization) -->
## Sim-Script Mechanisms: 4-Stage VCS Partition Compile + Verdi PA + wave.txt-Style FSDB Dump -- Audited Already Satisfied (2026-09-06, self_check_list.md #22-24)

`self_check_list.md` #22-24 ask this project's generated sim scripts to adopt three real mechanisms
named directly from `D:\DV\Task\USB_UVM_Handoff\sim\scripts\Makefile`: (a) the 4-stage VCS
compilation flow plus partition compilation, (b) VIP/Verdi PA (protocol analyzer), and (c) an
fsdb-dump mechanism keyed on a `wave.txt`-style dump list. This item's own upstream agent report for
this session's batch carried placeholder text (`"real_evidence_summary": "test"`,
`"claude_md_section_markdown": "test section"`) rather than real findings, so this integration pass
independently re-audited the real template Makefile and its real test before writing this section.

**All three mechanisms are genuinely present**, confirmed by direct inspection of
`dv_harness/uvm_generator/templates/sim_scripts/Makefile` -- a real, now-genericized copy of
`USB_UVM_Handoff/sim/scripts/Makefile` (`usb_` -> `$(IP_PREFIX)`, `USB` -> `$(TARGET_IP)`), closed as
part of the 2026-09-03 "Makefile/sim-scripts migration gap" already documented in this file's own
Engineering Discipline Rules section:

- **(a) 4-stage VCS partition-compilation flow**: Stage 1a `vlogan` analyses the UVM library, Stage
  1b `vlogan` analyses the DUT (+VIP+TB), Stage 1c `vlogan` analyses the testbench, Stage 2 `vcs`
  elaborates and produces `simv` with `-partcomp -fastpartcomp=j$(NPROC)` autopartitioning
  (`PARTCOMP_EN ?= 1`), matching the Makefile's own documented `[1a]`/`[1b]`/`[1c]`/`[2]` echo
  banners.
- **(b) Verdi PA (protocol analyzer)**: `VIP_PA ?= 1` gates `PA_DEFINES`
  (`+define+SVT_FSDB_ENABLE +define+WAVES_FSDB +define+WAVES="fsdb"`) and
  `PA_RUN_OPTS := +svt_enable_pa=fsdb +$(IP_PREFIX)pa`, itself gated on `VERDI_HOME` being set (a
  machine without Verdi is not silently given a broken PA invocation).
- **(c) wave.txt-style FSDB dump**: `FSDBDIR`, a `WAVES_SETUP` Verdi signal-setup Tcl script, and the
  real `+fsdb_off`/`+fsdb_full`/`+fsdb_file=`/`+fsdb_start=`/`+fsdb_stop=` run-time waveform-scope
  plusargs the Makefile's own extensive commentary documents (including two real, cited production
  incidents this project's own history records: an empty `+fsdb_file=` silently falling back to
  `novas.fsdb`, and a stale `wave.txt` dumping the whole SoC before the DV_UVM version was installed).

**A real regression test already exists for exactly this**, `dv_harness_tests/
test_sim_scripts_makefile_mechanisms.py` -- its own docstring states it was written by a prior
2026-09-06 audit of this same self_check_list item, confirming all three mechanisms "already
genuinely implemented -- not stubbed" and built purely as regression protection (`ALREADY_SATISFIED_
NO_CHANGE`) against a future edit silently dropping one. Every positive assertion in it carries a
negative control (matched against a deliberately stripped copy of the same text), proving the
marker set has real detection power rather than merely matching well-formed prose. Re-run fresh by
this integration pass: `python -m pytest dv_harness_tests/test_sim_scripts_makefile_mechanisms.py -q`
-> 10 passed.

**Deliberately bounded, and stated rather than implied closed.** This is a template/generation-time
guarantee, not a runtime one: nothing here runs a live VCS build or a real simulation to confirm the
generated Makefile actually compiles/dumps correctly for a specific project's own DUT -- that
verification happens the first time a real project builds from this template. No code was changed in
this integration pass (the gap was already closed on 2026-09-03/2026-09-06); this section only
records the closure and its test in CLAUDE.md, since the upstream agent report handed to this
integration pass carried no real content to append.


<!-- S246: moved verbatim from CLAUDE.md original lines 14504-14551 (M4.6 CLAUDE Context Normalization) -->
## Question Routing: VIP/DUT/env 3-Role Owner Routing + Options-Not-Open-Ended -- Audited Already Satisfied (2026-09-06, self_check_list.md #12)

`self_check_list.md` #12 (三個設計要點: give 2-3 options rather than an open-ended question; route by
owner -- VIP問題給你或Synopsys AE, DUT問題給designer, env問題給DV owner; batch into a digest rather
than real-time pings) was assigned to this session as `question_routing_role_audit`. Its own upstream
agent report carried placeholder text (`"real_evidence_summary": "test"`,
`"claude_md_section_markdown": "test"`, no module/test paths at all) rather than real findings, so
this integration pass independently audited `dv_harness/question_queue.py` directly before writing
this section.

**All three design points are genuinely implemented**, confirmed by direct inspection:

- **Owner routing, the literal 3-role table.** `DOMAIN_OWNER_ROUTING = {"vip":
  "DV-owner/Synopsys-AE", "dut": "designer", "env": "DV-owner"}` and `route_owner(domain)` -- matching
  #12's own three lines verbatim. An unrecognized domain raises `ValueError` rather than silently
  defaulting to some owner ("an unrouted question must never silently default to some owner, it must
  fail loudly at add_question time", per the function's own docstring).
- **Options, never open-ended, 2-3 candidates with a recommendation.**
  `dv_harness/schemas/question.schema.json`'s `options` field is schema-constrained to
  `minItems: 2, maxItems: 3` -- exactly #12's "提出 2-3 個候選與建議" -- and `validate_question()`
  cross-checks that a question's `recommendation` names one of the offered `options[].label` values
  (never a recommendation for an option that was not actually offered), enforced at
  `add_question()`-time via `QuestionValidationError`.
- **Batched into a digest, never real-time.** `build_digest()`/`compute_metrics()` batch every
  never-yet-digested question into one digest at `DIGEST_BOUNDARY_STAGES`
  (`REGRESSION_MONITOR`/`COVERAGE_CLOSURE`/`RE_AUDIT`/`SIGNOFF`) -- matching #12's "批次成 digest,
  ... 不要即時 ping" -- and this file's own "Question-Queue Digest: Auto-Fired at Regression-Cycle
  Boundaries" section above already documents this as auto-fired from `engine.DVHarness.advance()`
  on every real stage-completion transition, not merely a hand-typed CLI verb.
- **Answers sediment**, per #13 (the item immediately following #12 in the same source list):
  `QuestionQueueStore` persists every decision to `.dv-harness/question_queue/decisions.json` plus a
  generated `decisions.md`, and `find_decision()`/`DoNotAskError` ensure the same question is never
  asked twice once a real human decision is on file.

Proven by `dv_harness_tests/test_question_queue.py` (78 tests, all passing, re-verified fresh by this
integration pass: `python -m pytest dv_harness_tests/test_question_queue.py -q` -> 78 passed),
covering the 3-tier classification, owner routing (including the unrouted-domain refusal), the
options/recommendation schema cross-check, digest batching and auto-trigger, do-not-ask enforcement,
and the N-option `build_multiple_choice_question()` generalization documented elsewhere in this file.

**Deliberately bounded, and stated rather than implied closed.** No code was changed in this
integration pass -- the three design points were already real, tested, and wired before this session
began; this section only records the closure in CLAUDE.md, since the upstream agent report handed to
this integration pass carried no real content to append. This audit does not verify that every real
project's own question-routing UI/CLI surface actually presents options in the 2-3-candidate form to
a human reader -- it verifies the underlying schema/store enforces that shape, which every caller
(CLI, dashboard, or a future GUI) must go through.


<!-- S247: moved verbatim from CLAUDE.md original lines 14552-14614 (M4.6 CLAUDE Context Normalization) -->
## Stage Progress Displays: #32 Real-Time Progress + #33 Stage-Entry Banner -- Audited Already Satisfied (2026-09-06/07)

`self_check_list.md` #32/#33 (a real-time current-stage/remaining-items/%-complete display, and a
stage-START banner naming required documents/files/materials with a completeness % and a "needs your
detail" reminder) were assigned to this session as `stage_entry_exit_banner`. Auditing `engine.py`'s
`run_stage()` FIRST, per house style, found self_check_list.md #32/#33 already closed in this same
session by `dv_harness/stage_progress_display.py` (its own docstring section is literally titled
"STAGE-ENTRY BANNER EVIDENCE, WIDENED (2026-09-06, stage_entry_exit_banner gap-close;
self_check_list.md #33)") plus pre-existing `engine.py` wiring. Confirmed real, not just claimed:

- `engine.py` `run_stage()` calls `_emit_stage_start_display()` right after
  `_emit_stage_start_marker()`, before the attempts++ mutation (~line 4253-4265), and
  `_emit_stage_done_display()` right after the stage-exit `last_transition` write /
  `_emit_stage_done_marker()` (~line 4798-4814) -- both are the PROACTIVE auto-trigger at real stage
  transitions the task asked for (not a new on-demand-only path), and both are wrapped in
  try/except so a display failure can never turn a real stage result into something else.
- #32 (real-time current-stage/remaining-items/%-complete) reuses the pre-existing dv-harness
  checklist/explain/stage-report/stage-profile query machinery (`gates.STAGE_GATES`, graph node
  `blackboard_read`/`blackboard_write`/`expected_evidence`/`expected_outputs`,
  `stage_profile_report.stage_time_and_token_summary`) as its data source -- adding only the
  proactive trigger, not a new data source.
- #33 (stage-start banner + required-materials checklist + completeness % + "needs your detail"
  reminder) is rendered by `stage_progress_display.render_stage_start_display()`/`render_banner()`,
  sourced from THREE existing graph/gate declarations PLUS two modules named in the task:
  `build_env_manifest_checklist_items()` (reuses `env_manifest.default_manifest_path()`/
  `load_env_manifest()`/`summarize_for_blackboard()`, one item per real env.manifest.json layer,
  presence from that layer's own status field) and `build_target_conditioned_checklist_items()`
  (maps a stage via `STAGE_ARTIFACT_TARGET` onto
  `target_conditioned_missing_artifact_detector.detect_missing_artifacts()`, reusing its real
  per-category reason text). Both are additive/honest-by-omission, proven by real negative-control
  tests (no manifest on disk, malformed manifest, unmapped stage all report zero extra items, never
  fabricated).

No code was changed by this integration pass. Verification run:
`python -m pytest dv_harness_tests/test_stage_progress_display.py
dv_harness_tests/test_target_conditioned_missing_artifact_detector.py
dv_harness_tests/test_stage_evidence_checklists.py
dv_harness_tests/test_dashboard_cli_checklist_rendering.py -q` -> 84 passed. The full relevant engine
suite `dv_harness_tests/test_engine_gates_and_routing.py` (239 tests, drives real
`DVHarness.run_stage()` over the real graph) was also run in full and produced the identical result
the upstream agent report described: 236 passed, 3 failed
(`test_newly_wired_orphan_gates_pass_with_valid_evidence`,
`test_run_stage_promotes_vplan_summary_to_project_memory_on_pass`,
`test_verification_architecture_requires_fabric_topology_completeness_gate`). Read the real
tracebacks: all three fail on a GATE_FAIL/PARTIAL verdict because `gates.py`'s `STAGE_GATES` now
requires an evidence block these older fixtures never supply
(`spec_to_vplan_quality_gate` on VPLAN; `vip_bind_generation_gate`/`scoreboard_generation_gate`/
`assertion_generation_gate` on VERIFICATION_ARCHITECTURE) -- a `gates.py`/`STAGE_GATES` registration
fact wholly unrelated to and untouched by `stage_progress_display.py`'s display-only,
try/except-wrapped code (which never participates in gate evaluation). Both gates' own authoring
CLAUDE.md sections explicitly say they were left "not yet wired"/"not registered in gates.py" for a
separate integrator step, so this is a real, disclosed residual belonging to whichever concurrent
task owns `gates.py`'s `STAGE_GATES` table next, not a regression caused by this item and not
something this integration pass's own scope (test/CLAUDE.md verification, not `gates.py` edits)
permits fixing here.

**Disclosed residual, restated from `stage_progress_display.py`'s own module docstring.** The
env-manifest/target-conditioned widening covers only the four `env.manifest.json` layers and four
`STAGE_ARTIFACT_TARGET`-mapped stages named above; a stage outside that table, or a project with no
manifest yet, still gets the pre-existing graph-declared checklist unchanged -- never a guessed
requirement. Nothing here runs a build, a regression, or an LSF job; both displays are informational
and print-only.


<!-- S254: moved verbatim from CLAUDE.md original lines 14917-14945 (M4.6 CLAUDE Context Normalization) -->
## SYOSCB-11 AXI Logical Transaction Reconstruction: Verify-First Confirms ALREADY_SATISFIED (2026-09-07)

Assigned item syoscb11_axi_txn_reconstruction (reconstructing a full logical AXI transaction from
split beats/responses as ONE record) asked, per its own instruction, to first read
`dv_harness/transaction_correlation_ir.py` in full and check whether its existing response-correlation/
data-beat-association mechanisms already substantially satisfy this, extending additively only if a
genuine gap remained.

That read confirmed the module already fully satisfies the item: it was already extended for SYOSCB-11
(see this file's own Transaction Correlation IR section above, dated 2026-09-06) with a fourth
mechanism, `reconstruct_logical_transactions(transaction_records, response_entries, data_report,
burst_linkage_by_ref=None)`, producing one `LogicalAxiTransactionIR` record per declared transaction by
JOINING the already-computed outputs of `correlate_responses()`/`associate_data_beats()`/(optionally)
`link_burst_split_merge()` -- exactly the composition gap this item names, and nothing more: it
re-derives no correlation decision of its own and never claims a transaction is complete on a
dimension it was not handed real, already-computed evidence for.

No code change was made. `python -m pytest dv_harness_tests/test_transaction_correlation_ir.py -v`
-> 45 passed, including the 15-test `TestLogicalTransactionReconstruction` class covering the
complete/pending/ambiguous/partial/unknown-length/excess-data/burst-linkage-confirmed/burst-linkage-
unconfirmed/parent-ref-mismatch paths, both required insufficient-evidence negative controls (no
response-correlation entry; no data-association entry -- both honestly `LOGICAL_TXN_INSUFFICIENT_
EVIDENCE`, never a fabricated COMPLETE/PENDING guess), duplicate/missing-evidence refusals, report
rendering, and a real CLI subprocess round trip. No duplicate or parallel module exists anywhere in
the repo for this item.

Per house rule 4 (REUSE OVER REINVENT): this is reported as ALREADY_SATISFIED_NO_CHANGE rather than
papered over with a redundant parallel module.


<!-- S296: moved verbatim from CLAUDE.md original lines 17622-17644 (M4.6 CLAUDE Context Normalization) -->
## Timing Requirement Extraction: Re-Verified, No Change (2026-09-07)

**Status check on an already-closed item.** Section 289 (`timing_requirement_extraction`) was
assigned again this session. It was already fully built in a prior pass (see the existing section
above, "Timing Requirement Extraction: Documented Setup/Hold/Latency Bounds From Text, Never A
Measured Value (2026-09-06, section 289)") -- `dv_harness/timing_requirement_extraction.py` plus
`dv_harness_tests/test_timing_requirement_extraction.py` and its three synthetic fixtures. Rather
than trust the prior doc entry at face value, this pass independently re-ran the evidence:
`python -m pytest dv_harness_tests/test_timing_requirement_extraction.py -v` -> 19/19 passed fresh;
the CLI (`python -m dv_harness.timing_requirement_extraction extract --sources ... --json`) was
invoked directly against both the positive fixture (returns four correctly-cited SETUP/HOLD/LATENCY
bounds) and the `no_timing_requirements.txt` fixture (returns honest `NOT_AVAILABLE` at every level
with exit code 2, never a fabricated bound); and the two reuse-analysis siblings
(`system_failure_taxonomy.py`, `interrupt_dma_clock_reset_extraction.py`) were confirmed to still
exist so the prior module's documented reuse rationale is not a dangling reference.

**No change made.** The module already fully satisfies this item's requirement (documented, cited
setup/hold/latency bounds from text, structurally distinct from and never conflated with the
live-simulator-dependent AMBA performance-verification modules) with real passing tests including
the required negative control on fabrication-refusal. No new module, no edit to the existing one, no
CLI/gates.py wiring change. This entry exists only to record that the re-check happened and to avoid
a future pass re-doing the same "grep found nothing" cycle without first checking this timestamp.


<!-- S297: moved verbatim from CLAUDE.md original lines 17645-17669 (M4.6 CLAUDE Context Normalization) -->
## design_usage_recipes: Confirmed Already Satisfied by Usage Recipe Catalog (2026-09-07)

Batch item `design_usage_recipes` ("assemble documented step-by-step usage
recipes -- a named recipe = an ordered set of `programming_sequence_ir.py`
steps plus its documented purpose/citation -- as a distinct, higher-level
artifact over that module's per-sequence facts") is a verbatim restatement of
the existing **Usage Recipe Catalog** module documented above
(`dv_harness/usage_recipe_catalog.py`, built 2026-09-06, one day prior).
REUSE OVER REINVENT applies at the strongest level: no new module was
written, since the existing one already covers the assigned scope in full
(`UsageRecipe` assembly from both a raw dict and a real sequence slice, both
required `purpose`/`citation`, delegated ordering validation via
`programming_sequence_ir.validate_step_ordering()`, worst-wins
`UsageRecipeCatalog` rollup, and a standalone `python -m
dv_harness.usage_recipe_catalog {catalog,validate}` CLI front door).

Re-verified rather than re-built: re-ran `dv_harness_tests/test_usage_recipe_catalog.py`
standalone (`python -m pytest dv_harness_tests/test_usage_recipe_catalog.py -q`
-> 37 passed) and re-invoked `python -m dv_harness.usage_recipe_catalog --help`
to confirm the documented CLI surface is actually live on disk, not just
described. No code, tests, or CLAUDE.md content were changed by this pass --
this section exists solely to record that the item was checked against real
evidence and found already closed, per house rule 4 (report honestly rather
than duplicate).


<!-- S319: moved verbatim from CLAUDE.md original lines 19303-19314 (M4.6 CLAUDE Context Normalization) -->
## [CLOSED, 2026-09-08] VIP Callback/Hook Extension-Point Classification

Was recorded, earlier the same day, as genuinely open ("Remains Open") because the
item-implementation agent for that batch produced no real output and no matching file existed on
disk at the time of that entry. Closed later the same day (confirmed still real and passing on
2026-09-08 re-verification: `python -m pytest dv_harness_tests/test_vip_callback_hook_extraction.py
-q` -> `18 passed`) by `dv_harness/vip_callback_hook_extraction.py` -- the exact sixth capability IR
(`VIPCallbackHookIR`) this entry's own closing paragraph named as the real starting point. See "## VIP
Callback/Hook Extraction: the Sixth Capability IR, VIPCallbackHookIR (2026-09-07)" below for the full
closure record. This header is left as a short cross-reference (per this file's own convention for a
superseded gap-claim) rather than deleted outright.


<!-- S325: moved verbatim from CLAUDE.md original lines 19735-19745 (M4.6 CLAUDE Context Normalization) -->
## [CLOSED, 2026-09-08] "Why Am I Being Asked This" Grounding

Was recorded as remaining open, distinct from the two real sibling mechanisms it reused
(`request_clarification()`, `build_escalation_package()`), because no dedicated module named
"why grounding" existed yet. Closed by `dv_harness/question_why_grounding.py` exactly as this
entry's own closing paragraph specified -- a thin, explicitly-named wrapper over those two
functions, never a third, independently-derived explanation mechanism. See "## Question 'Why Am I
Being Asked This' Grounding: Closing the Disclosed Residual (2026-09-08)" below for the full
closure record. This header is left as a short cross-reference (per this file's own convention for
a superseded gap-claim) rather than deleted outright.


<!-- S330: moved verbatim from CLAUDE.md original lines 20046-20056 (M4.6 CLAUDE Context Normalization) -->
## [CLOSED, 2026-09-07] Clock/Reset Dependency Graph (incl. multi-die/partition topology)

Was disclosed open (dut_discovery batch, 2026-09-07: no `clock_reset_dependency_graph` module
existed, and `holistic_clock_reset_power_consistency.py` explicitly did not cover it -- see that
module's own CLAUDE.md section for the original gap analysis). Closed the same day by
`dv_harness/clock_reset_dependency_graph.py` -- a standalone, queryable clock<->reset<->power-domain
graph, including the multi-die/partition-topology dimension via an explicit, caller-declared (never
inferred) `partition_assignment` map. See "## Clock/Reset Dependency Graph: a Standalone Queryable
Object, Closing the Open Item (2026-09-07)" below for the full closure record. Re-verified in this
pass: `dv_harness_tests/test_clock_reset_dependency_graph.py` -> 38 passed.


<!-- S331: moved verbatim from CLAUDE.md original lines 20057-20068 (M4.6 CLAUDE Context Normalization) -->
## [CLOSED, 2026-09-07] Legal Parameter-Combination Extraction from RTL

Was disclosed open (dut_discovery batch, 2026-09-07: no extractor existed for which parameter
COMBINATIONS a `generate if`/elaboration-time `$error` guard proves legal or illegal). Closed the
same day by `dv_harness/legal_param_combination_extraction.py`, reusing `verible_parser.py`'s real
front end (never a second SystemVerilog parser) and `param_define_extraction.py`'s real declared-
parameter list to ground which conditions genuinely reference two or more of a module's own real
parameters. See "## Legal Parameter-Combination Extraction from RTL (2026-09-07,
legal_param_combination_extraction) -- CLOSES the prior open item" below for the full closure
record. Re-verified in this pass: `dv_harness_tests/test_legal_param_combination_extraction.py` ->
25 passed.


<!-- S345: moved verbatim from CLAUDE.md original lines 21051-21093 (M4.6 CLAUDE Context Normalization) -->
## AMBA Path Explorer Card (dashboard_amba_path_explorer_ui) -- verified ALREADY_SATISFIED (2026-09-07)

Re-checked before appending, per this workflow's own "check whether a route/card matching your own
assigned item already exists" instruction: `GET /api/amba-path-explorer` and the
`ambaPathExplorerCard` GUI were already fully implemented and wired in `dv_harness/dashboard.py`
(added by an earlier pass in this same project's history, alongside the sibling AMBA Connectivity
Matrix card). No new code was written for this item; this is the missing CLAUDE.md record for
already-real, already-tested code.

- `_read_amba_path_explorer_state(root, master=None, slave=None, graph_path=None)`
  (`dashboard.py`) reads the same `.dv-harness/amba/amba_fabric_graph.json` document the
  connectivity-matrix card reads, widened with an optional `"routes"` list carrying
  `amba_fabric_graph_ir.build_amba_path_ir()`'s own `RouteFact` shape
  (`route_id`/`master_id`/`slave_id`/`hops`/`evidence`). It calls the real, already-shipped
  `amba_fabric_graph_ir.build_amba_fabric_graph()` / `build_amba_path_ir()` -- never a second,
  dashboard-local route-enumeration or graph-consistency engine -- so this card's picker lists every
  declared `(master, slave)` pair and, once a pair is selected, shows EVERY distinct declared route
  for it (never collapsed to one) with that route's own `CONSISTENT_WITH_GRAPH`/
  `INCONSISTENT_WITH_GRAPH`/`CONSISTENCY_NOT_CHECKED` verdict and findings. A pair nobody declared a
  route for reports zero paths, honestly, rather than an error or a fabricated route (the negative
  control this project's house style requires).
- `GET /api/amba-path-explorer` dispatches to that function, following the identical pattern the
  sibling `/api/amba-connectivity-matrix` route uses one block above it, including the same
  `?graph=` override convention.
- The `ambaPathExplorerCard` renders a master/slave `<select>` picker, a tile summary, and a
  results table; `loadAmbaPathExplorer()` / `onAmbaPathMasterChange()` /
  `loadAmbaPathExplorerRoutes()` drive it over `fetch()`, and `await loadAmbaPathExplorer();` is
  already wired into the page's real `load()` sequence, so the card is not an orphan endpoint
  nothing calls.

Proven by the pre-existing `dv_harness_tests/test_dashboard_amba_path_explorer_card.py` (9 tests,
re-run fresh for this verification: `python -m pytest
dv_harness_tests/test_dashboard_amba_path_explorer_card.py -q` -> `9 passed`), driving the real
dashboard server over real HTTP: an honest empty state when no fabric graph exists yet; both real
declared routes for one pair preserved with correct `CONSISTENT_WITH_GRAPH`/
`INCONSISTENT_WITH_GRAPH` verdicts; the required negative control (an undeclared pair reports zero
paths, never an error or a fabricated route); `CONSISTENCY_NOT_CHECKED` when routes are declared with
no graph to check them against; a real `AMBAFabricGraphError` (an ungrounded reconfigurable claim)
surfaced as a named reason/detail rather than a 500 or a blank picker; a malformed graph file
likewise surfaced honestly; the `?graph=` path-override convention; a page-load assertion that the
card exists in the served HTML, is wired into `load()`, and is labeled "Read-only"; and a check that
neither the card's HTML nor its JSON payload ever renders a `bind` statement.


<!-- S356: moved verbatim from CLAUDE.md original lines 21696-21739 (M4.6 CLAUDE Context Normalization) -->
## AMBA Connectivity Matrix UI (dashboard_amba_connectivity_matrix_ui) -- Audited Already Satisfied (2026-09-07)

Assigned item: a new `/api/amba-connectivity-matrix` route + dashboard card rendering
`amba_fabric_graph_ir.py`'s real node/edge data as a matrix table, reusing the existing
`render_markdown_table()`-equivalent HTML table pattern an existing dashboard card already uses.

Per this workflow's own "check whether a route/card matching your OWN assigned item already exists"
instruction, `dv_harness/dashboard.py` was read fresh (not from any cached view) before making any
edit. The item is **already fully implemented, wired, and tested** -- no code change was made.

**What already exists, cited by real line numbers in the current `dv_harness/dashboard.py`:**
- The card: `<div class="card" id="ambaConnectivityMatrixCard">` at line 206, titled "AMBA Fabric
  Connectivity Matrix", documenting the real `/api/amba-connectivity-matrix` route and
  `.dv-harness/amba/amba_fabric_graph.json` source, with two rendered tables (`ambaConnectivityMatrixNodesTable`,
  `ambaConnectivityMatrixEdgesTable`) at lines 219-227 -- the same tiles+table HTML pattern the
  neighboring AMBA-22 registry card (`ambaFabricCard`, line 180) and AMBA Bottleneck card
  (`ambaBottleneckCard`, line 251) already use, reused rather than reinvented.
- The client JS: `loadAmbaConnectivityMatrix()`/`renderAmbaConnectivityMatrix()` at lines 1139-1183,
  fetch-once-and-render, wired into the page's `load()` sequence (confirmed by the real test
  `test_amba_connectivity_matrix_card_is_served_and_wired_into_the_page_load`).
- The route handler: `_default_amba_fabric_graph_path()` / `_read_amba_fabric_graph_state()` starting
  at line 2654, with a detailed header comment (lines 2631-2653) explaining the design: it calls
  `amba_fabric_graph_ir.build_amba_fabric_graph()` directly -- never a dashboard-local re-derivation
  of node-kind legality, evidence-citation requirements, or the module's own
  `assert_no_ungrounded_reconfigurable_claim()` check -- reports the honest empty state when no graph
  has been declared, and surfaces the module's real `AMBAFabricGraphError` code/detail (e.g.
  `RECONFIGURABLE_CLAIM_WITHOUT_GROUNDED_EVIDENCE`) rather than a generic 500 or a fabricated
  malformed-file result.
- The dispatch entry: `elif self.path == "/api/amba-connectivity-matrix" or self.path.startswith(...)`
  at line 4072, in the real route-dispatch table alongside every other GET endpoint.

**Verification performed by this audit** (no source edit made, re-confirmed fresh in this
integration pass): `python -m pytest
dv_harness_tests/test_dashboard_amba_connectivity_matrix_card.py -q` -> `7 passed`, covering the
honest-empty-state negative control (no graph declared), a real graph built through the real
`amba_fabric_graph_ir.build_amba_fabric_graph()` and cross-checked node-for-node/edge-for-edge and
reconfigurable-flag-for-flag against that module's own direct output, the ungrounded-reconfigurable-
claim error surfaced by reason/detail (never a 500), a malformed-JSON-file negative control, a
`?graph=` path-override test, the page-wiring test, and a test proving neither the HTML nor the JSON
payload ever renders an emittable `bind` statement.

No `dv_harness_tests/test_dashboard_*.py` files were modified or added by this session, since no
source change was needed.


<!-- S357: moved verbatim from CLAUDE.md original lines 21740-21792 (M4.6 CLAUDE Context Normalization) -->
## AMBA Bottleneck Analysis UI (dashboard_amba_bottleneck_analysis_ui) -- Audited Already Satisfied (2026-09-07)

Assigned item: a route + card surfacing `amba_performance_classification.
identify_bottleneck_candidate()`'s real Hypothesis -> Evidence -> Confidence -> Gap ->
Next-Best-Action bottleneck record. This item's own upstream agent report claimed the capability was
already documented by a pre-existing CLAUDE.md section titled "AMBA Bottleneck Analysis IR:
Structured Hypothesis->Evidence->Confidence->Gap->Next-Best-Action, Never a Bare Label" -- that claim
was checked, not trusted, by this integration pass: a direct grep of the live CLAUDE.md for that
exact heading (and for "AMBA Bottleneck Analysis IR" more broadly) returned **zero hits**. The
underlying CODE is real and correct; the referenced pre-existing DOCUMENTATION for it was not. This
section is the honest record that the upstream report's own house style requires, written from the
real `dashboard.py` source and the real, passing test file rather than trusted from that inaccurate
citation.

**What already exists in `dv_harness/dashboard.py`**, confirmed by direct reading immediately before
writing this section: a card shell `<div class="card" id="ambaBottleneckCard"><h3>AMBA Bottleneck
Analysis</h3>` with its tiles/table/note DOM elements, following the exact same pattern as the three
sibling AMBA cards (`ambaFabricCard`, `ambaConnectivityMatrixCard`, `ambaPathExplorerCard`)
immediately above it; JS wiring (`_ambaBottleneckData`, `loadAmbaBottleneck()` fetching
`/api/amba-bottleneck`, and `renderAmbaBottleneck()` populating tiles/table/rejected-note) matching
the fetch-once-then-render convention every other AMBA card uses; a backend module-doc block
"--- AMBA Bottleneck Analysis (GET /api/amba-bottleneck) ---" with
`_default_amba_bottleneck_candidates_path()` and `_read_amba_bottleneck_state()`, which imports and
calls `amba_performance_classification.identify_bottleneck_candidate()` directly -- reusing the real
Hypothesis->Evidence->Confidence->Gap->Next-Best-Action builder rather than a second dashboard-local
re-derivation, refusing (via that function's own `PerformanceClassificationError`) any declaration
built from fewer than `MIN_BOTTLENECK_EVIDENCE_COUNT` (2) real evidence citations and surfacing such
refusals as per-candidate `rejected` entries rather than a generic 500 or a silently dropped
candidate; and route dispatch `elif self.path == "/api/amba-bottleneck" or
self.path.startswith("/api/amba-bottleneck?")` in `do_GET`, following the exact same GET-route
pattern as the three sibling AMBA endpoints registered immediately above/below it. The route is
read-only by design. No duplicate/competing route or card exists elsewhere in `dashboard.py` for
this item.

**Verification performed by this audit**, re-confirmed fresh: `python -m pytest
dv_harness_tests/test_dashboard_amba_bottleneck_card.py -q` -> `7 passed`, with real
negative-control coverage present and passing: an honest empty state when no
`.dv-harness/amba/bottleneck_candidates.json` exists on disk (never a fabricated value); a
candidate built from only 1 evidence citation reported under `rejected` with the real
`PerformanceClassificationError` text, never silently promoted to a fabricated candidate -- the
required absence-of-evidence-reports-honestly negative control; a malformed-candidates-file
negative control reporting rather than a bare 500; a real record proven built via the real
classification module, including its real confidence derivation from evidence count plus the
presence of a declared gap; a `?candidates=` path-override test; a page-load wiring test proving
the served HTML actually contains the card id and its JS/fetch wiring, not just that the backend
function exists standalone; and a test proving the card never renders a `bind` statement.

Per this workflow's own instruction to check whether the assigned route/card already exists before
adding a duplicate: it does, is real, reuses the mandated backend module
(`amba_performance_classification.py`) rather than inventing a new analysis engine, and has real
passing tests including the mandated negative control -- so no code change was made and no
duplicate was added. No source or test file was edited by this session.


