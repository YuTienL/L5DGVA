# Audit: does the real engine TRACK the data behind the 4 requirements?

Scope: `dv_harness/engine.py`, `dv_harness/control_plane.py`, `dv_harness/gates.py`,
`dv_harness/stage_profile.py`, `dv_harness/stage_profile_report.py`, `dv_harness/multi_agent.py`,
`dv_harness/react_loop.py`, `dv_harness/graph.py`, `.dv-harness/graph/main_graph.json`,
`tools/vplan/intake_readiness.py`. Question asked (per requirement) is strictly about DATA/
TRACKING reality, not about whether any UI renders it.

---

## Requirement 1 — Current stage, pending items, % complete

**Verdict: WIRED_AND_REAL** (with one caveat: "pending items" are gate-level, not literal
evidence-item-level, and there is a second, coarser overall-run percent that is a different
number from the stage-scoped one).

Evidence:

- `dv_harness/control_plane.py:353-406` `describe_stage()` is the single real read path. For a
  given stage it calls `gates.evaluate_stage_evidence_with_completion()` and returns
  `gate_verdict`, `gate_reasons`, `gates_total`, `gates_passed`, `stage_completion_percent`,
  `stage_completion_note`, plus `entry_checklist`/`exit_checklist` (see Req 2/3 below).
- `dv_harness/gates.py:1270-1303` `_stage_completion_from_signatures()` computes a REAL numeric
  percentage: `stage_completion_percent = round(100 * gates_passed / gates_total)`, where
  `gates_total`/`gates_passed` come from the exact same per-gate `signatures` list
  `evaluate_stage_evidence()` already produces (`gates.py:1359-1439`
  `_evaluate_stage_evidence_core()`). A stage with zero registered gates reports 100% with an
  explanatory note (not a fabricated 0% or crash) — `gates.py:1281-1296`.
- "Pending items" = `gate_reasons`, one entry per gate that hasn't passed
  (`gates.py:1393-1432`), e.g. `"{gate_id}: no evidence block supplied"` or the gate's own
  failure detail dict, plus (for `intake_readiness`-shaped failures) a human-readable Traditional
  Chinese question via `INTAKE_FIELD_QUESTIONS` (`gates.py:1196-1218`, applied at
  `gates.py:1413-1430`). This is real and computed, but it is scoped to *gate ids*, not to
  individual named evidence-checklist items inside a gate's payload — a gate with multiple
  required sub-fields fails/passes as one unit unless its own script reports sub-field detail.
- This is genuinely stage-SCOPED (only the gates registered for the one current stage), as
  distinct from `dashboard.py`'s separate `overall_progress_percent` (whole-run, fraction of all
  `Stage` enum values at PASS/CLOSED) — `control_plane.py:361-369` documents this distinction
  explicitly. Both numbers are real, but they answer different questions; a caller must not
  confuse them.
- Real regression coverage: `dv_harness_tests/test_stage_scoped_completion_percent.py`.

**Conclusion**: `run_stage()`/`loop()` (via `describe_stage()`, called at
`engine.py:2337` right after every attempt, and independently by `dv-harness explain`/`evidence`)
does know, at any point, exactly which gates are still failing for the CURRENT stage and a real
computed percentage of gates satisfied. This is a genuine, wired, tested mechanism — not
something a caller would have to derive by hand from raw logs.

---

## Requirement 2 — Required files/materials checklist at stage START + completeness % + "which
items still need detail"

**Verdict: PARTIALLY_REAL.**

What is real and wired:

- `dv_harness/engine.py:368-400` `build_stage_entry_checklist()` is a genuine
  *before-the-LLM-call* readiness check: called at `engine.py:1973` (`entry_checklist =
  build_stage_entry_checklist(node, ...)`), strictly BEFORE `build_stage_prompt()`/
  `adapter.run()` at `engine.py:1986-2018` — i.e. before the stage's own agent turn runs at all.
  This is a real, distinct mechanism from the end-of-stage evidence check (Req 3) — the code
  comment at `engine.py:261-274` explicitly frames the entry/exit pair as symmetric but
  independently timed.
- Each declared item has a `kind` (`blackboard_key` / `file_path` / `evidence_field`) and is
  presence-checked for real: `blackboard_key` via `Blackboard.read()!=None`
  (`engine.py:332-333`), `file_path` via `Path(...).exists()` (`engine.py:334-338`),
  `evidence_field` by digging into a dotted path in a PRIOR stage's actually-submitted evidence
  (`engine.py:339-343`, `297-303`).
- `_run_checklist()` (`engine.py:347-365`) computes a REAL
  `completeness_percent = 100 * present_count / total_count` and a REAL `missing_item_ids` list —
  this is the numeric completeness the requirement asks for, and it is genuinely derived from
  presence checks, not hardcoded.
- The result is persisted into the SAME per-attempt telemetry record
  (`stage_profile.py:59-85` `begin_stage(..., entry_checklist=entry_checklist)`), and readable
  back through `control_plane.describe_stage()` (`control_plane.py:331-350`
  `_latest_stage_checklists()`, `control_plane.py:400`).
- Node declarations exist in `.dv-harness/graph/main_graph.json` for `Node.expected_evidence`
  (schema in `dv_harness/graph.py:34-52`).

What is missing / narrower than the requirement implies:

- Verified by reading `.dv-harness/graph/main_graph.json` directly: only **6 of 36** stage nodes
  declare any `expected_evidence` at all — `INTAKE` (1 item), `BUILD` (1), `VERIFY` (1),
  `REGRESSION` (2), `COVERAGE_CLOSURE` (1), `SIGNOFF` (3). The other 30 nodes (DISCOVERY,
  ARCH_DISCOVERY, VPLAN, IMPLEMENT, WAVE_ANALYSIS, RE_AUDIT, PROMOTION_READINESS, etc.) have an
  empty list, which per the documented convention (`engine.py:360-364`) always reports
  `{"items": [], "completeness_percent": 100.0}` — i.e. for the large majority of the pipeline,
  the mechanism exists and runs but structurally has nothing to show; it can never surface a
  real "still missing" prompt there today.
- The specific, rich "what documents/materials do you actually have" content the user is
  picturing (protocol spec / DUT design spec / RTL top-or-interface files / command.txt / VIP
  reference — `tools/vplan/intake_readiness.py:56-80`, human questions in
  `gates.py:1196-1218`) is wired as **INTAKE's own EXIT checklist**
  (`main_graph.json` INTAKE `expected_outputs`: `intake_readiness.required_artifacts.*`,
  confirmed by direct read of the graph file), i.e. it validates what INTAKE itself produced —
  it is NOT wired as an ENTRY checklist for the downstream stage that actually consumes those
  materials (`VPLAN`'s `expected_evidence` is empty, confirmed above). So there is no stage in
  the graph today whose START-of-stage readiness check is "do we have the protocol
  spec/DUT design spec/command.txt/VIP reference yet" — that content only ever appears as a
  gate the INTAKE agent's own self-reported evidence is checked against (via `intake_readiness`
  gate script, `tools/vplan/intake_readiness.py`, run through
  `gates.evaluate_stage_evidence()`), producing a `missing: [...]` list and a
  `NEEDS_USER_INPUT` verdict/question set — real, but it is an INTAKE-stage-internal gate-failure
  path, not a generic pre-stage prerequisite gate reusable by every stage.
- `tools/vplan/intake_readiness.py`'s `missing` list has NO percentage — only a list; the numeric
  completeness percentage for THAT specific "required artifacts" checklist does not exist
  anywhere. (The generic `entry_checklist.completeness_percent` machinery exists, as above, but
  is not fed by this script's output.)
- The "prompt the user which items need detail" half of Req 2 is real ONLY through the
  `NEEDS_USER_INPUT` verdict path (`gates.py:1436-1439`, `INTAKE_FIELD_QUESTIONS` at
  `gates.py:1196-1218`), which is INTAKE-specific (keyed to `intake_readiness`'s known field
  names) — there is no generic "ask about missing entry-checklist items for any stage" path;
  `entry_checklist.missing_item_ids` is computed but nothing turns those generic ids into a
  human-facing question for an arbitrary stage the way `INTAKE_FIELD_QUESTIONS` does for INTAKE.

**Conclusion**: The generic engine primitive for "what does this stage need BEFORE it runs, and
how much of that is present" is real, wired, timed correctly (pre-LLM-call), and produces a real
percentage (`build_stage_entry_checklist`, `engine.py:368-400`). But it is populated for only 6 of
36 stages, and the specific rich "required documents" checklist implied by the user's wording is
currently wired only as an INTAKE exit-validation / self-report gate, not as a genuine start-of-
stage prerequisite gate for the stage(s) that actually need that material.

---

## Requirement 3 — Output files/materials at stage END, execution time (incl. per-agent), token
count

**Verdict: PARTIALLY_REAL** — execution time and token tracking are real and reasonably
detailed; "per-agent" is real but means "per adapter-call within this stage attempt" (which can
be more than one call, via ReAct-loop retries/reflections), not a breakdown across distinct named
specialist agents in the sense of dv-lead/perf-agent/coverage-agent running concurrently.

Output/materials checklist at exit — REAL:

- `dv_harness/engine.py:403-426` `build_stage_exit_checklist()`, called at `engine.py:2319`
  AFTER the gate verdict is known, reading `node.expected_outputs` and THIS attempt's own
  `evidence_blocks` (not stale/prior data). Same `_run_checklist()` machinery as Req 2 → real
  `completeness_percent`/`missing_item_ids`.
- Persisted into the SAME telemetry record via `stage_profile.py:118-141`
  `end_stage(..., exit_checklist=exit_checklist)`.
- Same population caveat as Req 2: only 6/36 nodes declare `expected_outputs`
  (confirmed by direct read of `main_graph.json`).

Execution time — REAL, confirmed against actual telemetry files on disk:

- Real records exist at `.dv-harness/telemetry/stages/STAGE-*.json` (15 files found, e.g.
  `STAGE-085481A7.json`), each carrying `start_time_epoch`, `end_time_epoch`,
  `stage_wall_clock_sec`, `aggregate_agent_runtime_sec`, `parallel_saving_sec`,
  `parallelism_efficiency` — all computed from real `time.time()`/measured durations in
  `stage_profile.py:118-141` (`end_stage()`), not placeholders.
- Whole-workflow rollup is real too: `stage_profile.py:174-191` `_update_workflow()` sums
  `stage_wall_clock_sec`/`aggregate_agent_runtime_sec` across every non-RUNNING stage record into
  `.dv-harness/telemetry/workflow_profile.json` (confirmed present on disk) — this is the actual
  "total execution time" the requirement asks for, computed automatically on every `end_stage()`
  call, not derived by a caller.

Per-agent breakdown — REAL, but scoped as "per adapter call within a stage attempt":

- `stage_profile.py:87-116` `add_agent_run()` appends one entry per adapter call to the stage
  record's `agents: []` list, with its own `runtime_sec`, `input_tokens`, `output_tokens`,
  `cache_read_tokens`, `cache_write_tokens`, `total_tokens`, `tool_calls`, `retries`, `status`,
  and re-aggregates the stage-level totals as a genuine sum over that list
  (`stage_profile.py:106-114`) — this is a real multi-entry structure, not a single aggregate
  figure hardcoded to one row.
- Real call sites: `engine.py:2043-2059` (once per `run_stage()` attempt, named via
  `route_info["agent"]`, e.g. `"analysis-agent"` — confirmed by
  `dv_harness_tests/test_multi_agent_timing.py:106-160`, an end-to-end test that asserts the same
  measured `duration_sec` reconciles between `AgentTaskStore` and the profiler's `agents[0]`), and
  `react_loop.py:249-272` `_record_agent_run()` — called for EACH extra adapter round-trip the
  inner ReAct loop makes within the same stage attempt (a reflection call, a hallucination
  re-ask, a targeted retry) — so a single stage attempt genuinely CAN accumulate multiple
  `agents[]` entries with independently measured time/tokens. This is a real multi-call
  breakdown, but the "agent" identity is the one resolved role for that stage/route
  (`route_info["agent"]`), not multiple concurrently-running, differently-specialized named
  agents — `MultiAgentOrchestrator.delegate()` (`multi_agent.py:96-98`) creates exactly one task
  per `run_stage()` call.
- Caveat confirmed from real data: in the actual `STAGE-085481A7.json` telemetry file on disk,
  every token field is `null` (`input_tokens/output_tokens/.../total_tokens: null`, top level and
  in the one `agents[]` entry) even though `runtime_sec` is a real measured `8.235537...`. This is
  explained and acknowledged in-code: `stage_profile.py:38-49` `extract_provider_usage()` reads
  `raw["response"]["usage"]` — real for the CLI adapter's `claude -p --output-format json` output,
  but `dv_harness/adapters/sdk.py`'s SDK adapter response never carries that key, so token fields
  are always `None` for any project configured with `"adapter": "sdk"`.
  `stage_profile_report.py:12-49` (`SDK_ADAPTER_TOKEN_NOTE`) explicitly documents this as a known,
  by-design limitation, checked against the project's real `.dv-harness/config.json` `adapter`
  field (not inferred from the null values themselves).
- `dv_harness_tests/test_cross_adapter_token_tracking.py` exists to regression-test this
  adapter-dependent behavior.

**Conclusion**: time and token tracking are real, per-stage-attempt, per-adapter-call, and rolled
up workflow-wide — this is a substantially real mechanism, not a stub. The two real gaps: (1)
token counts are only non-null when the CLI adapter is configured (a documented, acknowledged
limitation, not a bug hidden from the audit); (2) "per agent" in the sense the requirement likely
means (distinct named specialist agents working the same stage) does not exist — what exists is
"per adapter call within one stage attempt by the one resolved agent for that stage."

---

## Requirement 4 — Persisted, human-readable reports of the #2/#3 displays

**Verdict: NOT_IMPLEMENTED** as a start/end-of-stage report artifact; a related but different
report exists for aggregate time/tokens.

What exists:

- `dv_harness/stage_profile_report.py:51-86` `render()` produces a real, human-readable,
  formatted text table across ALL stages (wall-clock, input/output/total tokens, tool calls,
  retries, status per stage, plus workflow-level aggregate agent time / parallel saving /
  parallelism efficiency / tool calls / retries) — this is a genuine report-GENERATION function
  covering much of Req 3's execution-time/token content.
- It is reachable via `dv-harness stage-profile` (`dv_harness/cli.py:734-736`, `elif args.cmd ==
  "stage-profile": ... print(stage_profile_report.render(...))`).

What is missing:

- `render()` only ever `print()`s to stdout (`cli.py:736`) or returns a string for a caller (e.g.
  a dashboard card) to render live — there is no call site anywhere in `dv_harness/*.py` that
  writes this (or any per-stage start/end summary combining banner + checklist + time + tokens)
  to a persisted file. Searched for a reports directory under `.dv-harness/` (`find .dv-harness
  -maxdepth 1 -type d`) — there is a `telemetry/` directory (raw per-attempt JSON, already
  covered under Req 3) but no `reports/` (or equivalent) directory, and no
  `write_text()`/`json.dump()` call in `dv_harness/*.py` that persists a rendered report
  artifact for entry/exit checklist + banner content specifically.
- The stage-start/stage-done "visual markers" (`engine.py:131-156`
  `_emit_stage_start_marker()`/`_emit_stage_done_marker()`, called at `engine.py:1837` and
  `engine.py:2342`) are themselves NOT a "Logo" graphic — they are one line of plain `print()`
  text with a greppable prefix (`[DV-HARNESS-STAGE] ===== STAGE START: X =====` /
  `===== STAGE DONE: X [VERDICT] (NN% gates satisfied) =====`, `engine.py:145-155`), written to
  stdout only, not to any persisted log/report file, and not accompanied in the same print
  statement by the entry/exit checklist content (that lives separately in the telemetry JSON,
  read back only via `describe_stage()`/dashboard, not folded into the marker text itself). Note
  also that the done-marker's percentage is `stage_completion_percent` (gates_passed/gates_total,
  Req 1's number), not the exit_checklist's own `completeness_percent` (Req 3's "output
  materials" completeness) — these are two different numbers and the marker only ever prints one
  of them.
- Nothing composes "banner + entry/exit checklist + time + tokens" into one saved document per
  stage-start/stage-end event. The three pieces of real data (marker text, checklist JSON in
  telemetry, time/token JSON in telemetry) are each real and each retrievable, but never
  assembled and written to disk together as a single human-readable "stage start report" /
  "stage end report" artifact the way `signoff_export.py` does for the final SIGNOFF bundle, or
  the way `regression_reporter.py:311` persists a regression snapshot.

**Conclusion**: the raw data #2/#3 need is genuinely tracked and persisted (telemetry JSON), and
one aggregate report renderer exists (`stage_profile_report.render()`) but is print-only, not
saved. There is no report-generation/persistence mechanism today that produces and saves a
human-readable per-stage start summary or per-stage end summary (banner + checklist +
completeness % + time + tokens combined) as its own artifact.

---

## Summary table

| # | Requirement | Verdict |
|---|---|---|
| 1 | Current stage / pending items / % complete | WIRED_AND_REAL (gate-level granularity; two distinct percent metrics exist, don't conflate them) |
| 2 | Start-of-stage required-materials checklist + % + "what's missing" prompt | PARTIALLY_REAL (generic mechanism real & correctly timed pre-LLM-call, but populated for only 6/36 stages; the rich "required documents" content is wired as INTAKE's own exit-check, not as any downstream stage's entry-check; no percent for `intake_readiness`'s own missing-list) |
| 3 | End-of-stage output checklist + % + time (incl. per-agent) + tokens | PARTIALLY_REAL (checklist same 6/36 coverage as #2; time and token tracking are real, measured, multi-entry, and rolled up workflow-wide; tokens are null whenever the SDK adapter is configured, by documented design; "per-agent" = per adapter-call by the one resolved agent, not multiple concurrent named specialists) |
| 4 | Persisted reports of #2/#3 | NOT_IMPLEMENTED (raw JSON is persisted; one aggregate text report renderer exists but is print-only; nothing saves a combined banner+checklist+time+token report per stage start/end) |
