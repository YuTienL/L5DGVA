# Expected-Evidence Checklist and Stage Entry/Exit Hooks

Closes the audit finding that main_graph.json's node schema had no field
declaring what evidence/files a stage requires at entry or should produce at
exit, and that prompts.py's `STAGE_INSTRUCTIONS` "required_artifacts"-style
prose was only ever self-reported by the agent, never a harness-computed,
presence-checked checklist.

## What was built

### 1. `expected_evidence` / `expected_outputs` node schema (additive)

- `dv_harness/graph.py`'s `Node` dataclass gained two new optional fields,
  both defaulting to `[]`: `expected_evidence` (checked at stage entry) and
  `expected_outputs` (checked at stage exit). Each entry is
  `{"item_id": str, "description": str, "kind": "file_path"|"blackboard_key"|"evidence_field"}`.
  `GraphDefinition.load()`'s `Node(**n)` already tolerates missing keys via
  these defaults, so every node that does not opt in (the large majority)
  is completely untouched — verified by
  `test_real_main_graph_declares_expected_fields_on_the_six_representative_stages`
  asserting `DISCOVERY` (an un-opted-in node) still has empty lists.
- `.dv-harness/graph/main_graph.json` now populates both fields on the six
  requested representative stages: `INTAKE`, `BUILD`, `VERIFY`,
  `REGRESSION`, `COVERAGE_CLOSURE`, `SIGNOFF`. Every item was **transcribed**
  from real, already-existing requirements, never invented:
  - `INTAKE`: entry = the `environment` blackboard topic (`node.blackboard_read`,
    ENV_CHECK's readiness record). Exit = the exact fields
    `prompts.STAGE_INSTRUCTIONS[INTAKE]`'s `intake_readiness` evidence fence
    already asks for (`mode`, `target_name`, `protocols`,
    `required_artifacts.{protocol_spec,dut_design_spec,rtl_top_or_interface_files}`).
  - `VERIFY`: entry = `command.txt` (the file STAGE_INSTRUCTIONS explicitly
    names in "command.txt ↔ sim.log Semantic Verification"). Exit = fields
    from the three named fences (`simulation_semantic_validation_gate`,
    `test_result_provenance_gate`, `false_pass_resistance_gate`).
  - `REGRESSION`: entry = `REGRESSION_SELECT`'s own last-submitted
    `regression_selection_completeness_gate.{targeted_tests,mandatory_signoff_tests}`
    — a genuine cross-stage reference (see the `evidence_field` "STAGE_ID:"
    prefix below), because `REGRESSION_SELECT.blackboard_write` is `[]` in
    the real graph, so its selection is not otherwise observable via the
    Blackboard. Exit = the `regression_submission_policy_gate` fence
    STAGE_INSTRUCTIONS names.
  - `COVERAGE_CLOSURE`: entry = the `regression_state` blackboard topic
    (`node.blackboard_read`). Exit = fields from the
    `coverage_signoff_verdict_gate`/`coverage_credit_consistency_gate`/
    `coverage_quality_gate` fences STAGE_INSTRUCTIONS names.
  - `SIGNOFF`: entry = the `promotion`/`reaudit`/`regression_state`
    blackboard topics (`node.blackboard_read`). Exit = fields from the
    `false_pass_resistance_gate`/`signoff_bundle_completeness_gate`/
    `subsystem_environment_registration_gate` fences STAGE_INSTRUCTIONS names.
  - `BUILD`: entry = the `server_state` blackboard topic (`node.blackboard_read`,
    grounded in the BASE prompt's "Server build 前確認 exact pushed Git SHA").
    **RULING**: `STAGE_INSTRUCTIONS[BUILD]`'s own prose ("依 project
    canonical flow 執行 build。Coverage 預設 OFF。保存 evidence。") names no
    evidence fence at all — unlike every other representative stage. Rather
    than inventing a field name, BUILD's `expected_outputs` uses the real,
    already-registered gate ids `gates.STAGE_GATES["BUILD"]` requires
    (`shared_elaboration_collision_gate`, `stop_after_simv_policy_gate`) plus
    the `build_state` blackboard topic that "保存 evidence" concretely
    resolves to (`node.blackboard_write`). This is documented inline in
    main_graph.json's own `description` fields for these two items.

### 2. `build_stage_entry_checklist` / `build_stage_exit_checklist` (`dv_harness/engine.py`)

Both are real, informational-only functions (never raise, never influence
`ss["status"]`) sharing one internal `_run_checklist()` core and one
`_checklist_item_present()`/`_dig_evidence_field()` presence resolver:

- `kind="blackboard_key"` → `Blackboard.read(item_id) is not None`.
- `kind="file_path"` → `Path.exists()` (relative to `root`, or absolute).
- `kind="evidence_field"` → dotted-path navigation into an evidence-block
  dict; present iff every segment resolves and the final value is truthy
  (so `required_artifacts.dut_design_spec: false` is correctly reported
  **absent**, not "present but false" — see
  `test_checklist_treats_falsy_required_artifact_value_as_absent_not_present`).
  An unknown `kind` is reported absent, never raises.

**RULING — where "evidence_field" data comes from, entry vs. exit**: the
task's evidence_field source ("the current state's last-submitted evidence")
is genuinely different at entry vs. exit, so the two functions resolve it
differently, both documented in their own docstrings:
- `build_stage_entry_checklist(node, blackboard, root, stage_history=...)`
  resolves against `stage_history` (i.e. `self.state.stages`) — specifically
  each stage's own `last_evidence_blocks` (see below), because entry-time
  there is no "this attempt's evidence" yet. A bare `item_id` defaults to
  the current node's own last attempt (useful on a retry); an
  `"OTHER_STAGE:field.path"` prefix looks at a *different* stage's last
  submission — the real mechanism `REGRESSION`'s entry checklist needs.
- `build_stage_exit_checklist(node, blackboard, root, evidence_blocks=...)`
  resolves against `evidence_blocks` — the SAME dict `run_stage()` already
  computed this attempt via `gates.extract_evidence_blocks()`, passed
  straight through with no re-parsing. Any `"STAGE_ID:"` prefix on an
  `expected_outputs` item is deliberately ignored at exit (documented) since
  an exit check only ever has this one attempt's own output to inspect.

**RULING — zero items declared**: `completeness_percent` is `100.0` (not
`0.0`) when a stage declares no checklist at all — "nothing required, so
nothing outstanding" rather than a misleading "totally missing evidence"
reading. Covered by
`test_entry_checklist_zero_items_declared_is_100_percent_and_empty`.

### 3. Wiring into `run_stage()`

- `build_stage_entry_checklist()` is called immediately before
  `self.profiler.begin_stage(...)` (itself immediately before
  `build_stage_prompt`/`adapter.run`), using `self.state.stages` as
  `stage_history` — genuinely before any part of this attempt exists.
- `build_stage_exit_checklist()` is called right after the gate verdict is
  known and the stage's evidence has settled (after the `NEEDS_USER_INPUT`/
  `InnerReactLoop`/`PARTIAL`/`FAIL` branching), immediately before
  `self.profiler.end_stage(...)`.
- `ss["last_evidence_blocks"]` (new additive field on `models.StageState`,
  default `{}`) is set to this attempt's `evidence_blocks` whenever it is
  non-empty (never cleared to `{}` by an attempt that produced none, e.g. an
  `ADAPTER_FAIL`) — this is what a later attempt's entry checklist reads.
- Neither call can change `ss["status"]`, `verdict`, or block anything —
  verified by `test_run_stage_checklist_is_informational_only_and_does_not_block_a_partial_stage`
  (VERIFY genuinely goes PARTIAL on missing gate evidence; the checklist
  just reports the same gap descriptively) and by every PASS-path
  integration test still reaching `Status.PASS`.

### 4. Persistence into the SAME telemetry record (`dv_harness/stage_profile.py`)

- `StageExecutionProfiler.begin_stage(..., entry_checklist=None)` now stores
  it under the `entry_checklist` key of the same `STAGE-*.json` record it
  already writes, alongside a `exit_checklist: None` placeholder.
- `StageExecutionProfiler.end_stage(..., exit_checklist=None)` overwrites
  `exit_checklist` only when a caller actually passes one (so a pre-existing
  caller round-trips byte-identical JSON otherwise).
- No second report file, no new format — same
  `.dv-harness/telemetry/stages/STAGE-*.json` record `dashboard.py`'s
  `stage_profile_report.render()` already reads via `.get(...)` (never exact
  key sets), so the new keys are safely ignored by every pre-existing
  consumer.

## Tests

New file `dv_harness_tests/test_stage_evidence_checklists.py` (14 tests):

- Node schema: default-empty-lists, and the real main_graph.json's six
  representative stages actually declaring well-formed items while
  `DISCOVERY` stays untouched.
- `build_stage_entry_checklist`/`build_stage_exit_checklist` unit tests:
  zero-items-declared (100%), `node=None` (harness has no graph), real
  `blackboard_key`/`file_path` presence/absence, cross-stage
  `evidence_field` prefix resolution including an unknown-stage-ref/missing-
  field no-crash case, exit-side same-attempt resolution with the
  documented STAGE_ID-prefix-ignored behavior, the falsy-required-field
  case, and an unknown `kind` reporting absent without raising.
- `StageExecutionProfiler` round-trip: `begin_stage`/`end_stage` with
  checklists persist and re-load byte-identical from the on-disk
  `STAGE-*.json`, and omitting them stays compatible with every
  pre-existing caller (`entry_checklist`/`exit_checklist` read back as
  `None`).
- Full `run_stage()` integration: a real INTAKE PASS run (with
  `require_stage_gate_evidence=False` to avoid needing the real gate
  subprocess scripts in a synthetic tmp project) produces exactly the
  expected entry/exit checklist numbers in the persisted telemetry file and
  the correct `last_evidence_blocks` mirror on `state.json`; a real VERIFY
  run with incomplete evidence proves the checklist is descriptive only
  (never blocks); a `DISCOVERY` run (no `expected_evidence`/`expected_outputs`
  declared) proves both checklists degrade to the trivial zero-item shape.

### Full suite result

`python -m pytest dv_harness_tests -q` → **1267 passed, 1 failed** in 845s.
The new 14-test file (`test_stage_evidence_checklists.py`) passes cleanly on
its own (`14 passed`). The one failure,
`test_cli_lsf_reconcile_picks_up_existing_job_state_files`, is **pre-existing
and unrelated**: it asserts a `bjobs`-not-on-PATH CLI subprocess exits 1, and
on this machine it exits 0 instead — confirmed by `git stash`-ing every
change in this pass and re-running that single test in isolation, which
fails identically on the unmodified tree (an environment/PATH difference,
not a regression from this work).

## Residual concerns

- `BUILD`'s `expected_outputs` had to fall back to `gates.STAGE_GATES`
  (rather than `STAGE_INSTRUCTIONS` prose, which names nothing) — see the
  RULING above. If `STAGE_INSTRUCTIONS[BUILD]` is later given a real
  evidence fence, `main_graph.json`'s BUILD node should be revisited to
  match it.
- Only the six requested stages were populated, per the task's stated
  minimum; the schema and both checklist functions work for any node, so
  extending coverage to more stages later is purely a `main_graph.json`
  data change, no further code change needed.
- `.dv-harness/events.jsonl` in this worktree picked up two unrelated
  `CLI_ACCESS self-audit` lines from running the pre-existing test suite
  (an existing test invokes the real CLI against this project's own root) —
  left uncommitted/unstaged since it is a pre-existing side effect of the
  test suite, not part of this change.
