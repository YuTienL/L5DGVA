# Memory Engine Schema Completion -- Implementation Report

## Scope

This session's AI-mechanism architecture audit found three specific schema gaps in the
5-Level Memory Pyramid (`dv_harness/memory.py`, `dv_harness/memory_router.py`):

1. Working Memory's claimed hypothesis/evidence/next-action schema actually lives in
   `dv_harness/react.py`'s `ReactRecorder` (persisting to `.dv-harness/react/`), never
   reconciled with `memory.py`'s generic `WorkingMemoryStore`.
2. Job Memory's real record schema is missing `seed` and `FSDB` fields claimed by the
   contract.
3. Project Memory is populated by exactly one gate
   (`project_model_topology_completeness_gate`) -- vPlan content has no separate write
   path.

All three files named in the task (`dv_harness/memory.py`, `dv_harness/memory_router.py`,
`dv_harness/react.py`, `dv_harness/lsf_client.py`'s
`_write_job_tier_memory_on_terminal_reconcile()`) plus `dv_harness/engine.py` and
`dv_harness/gates.py` were read in full before implementing.

## 1. Working Memory <-> ReactRecorder reconciliation

**RULING:** the task offered two options -- teach `MemoryRetriever.search()` to also read
`ReactRecorder`'s files at query time, OR have `ReactRecorder` push a compact record into
the Working Memory tier at write time via `memory_router.route_and_store()`. I chose the
**write-time push** (`dv_harness/react.py`, `ReactRecorder._write_working_memory_tier_record`),
for three reasons:

- Every existing reconciliation of this exact shape in the codebase
  (`engine.py`'s `_promote_experience_knowledge`, `_promote_project_topology_knowledge`,
  `lsf_client.py`'s `_write_job_tier_memory_on_terminal_reconcile`) is already a write-time
  push through the same `route_and_store()` entry point, not a read-time cross-store
  search -- this keeps the pattern uniform.
- A read-time reconciliation would require `memory.py` (a generic, protocol-agnostic
  five-tier store) to learn `react.py`'s private directory/filename layout
  (`.dv-harness/react/<node>/iteration_NNN.json`), coupling a general module to one
  specific producer's on-disk shape.
- No circular-import risk: `memory_router.py` imports `.memory` and `.blackboard` only;
  neither imports `react.py`, so `react.py` importing `memory_router` (via a local,
  try/except-guarded import, matching every other best-effort call site) is safe.

`ReactRecorder.record()` (called once per outer stage attempt from `engine.py`'s
`run_stage()`) now also calls `_write_working_memory_tier_record()`, which builds a
`{kind: "react_reasoning_step", node, iteration, hypothesis, evidence, next_action,
confidence}` record and routes it through `route_and_store()`. `memory_router.route_memory()`
gained an explicit branch for `kind == "react_reasoning_step"` -> `WORKING_MEMORY` (rather
than relying on the generic fallthrough), deliberately distinct from the pre-existing
`active_hypothesis` kind (which routes to `BLACKBOARD` -- current-run truth, not durable
working memory). `memory_id` is deterministic on `(node, iteration)` so a repeat call for
the same stage attempt upserts in place instead of duplicating (mirrors the Job Memory
idempotency rationale). The write is best-effort (local import + bare `try/except`): a
persistence failure never breaks an already-completed `record()` call. `record_reflection()`
(the inner ReAct-loop turns) was deliberately left untouched -- its
signatures/menu/decision shape is not a hypothesis/evidence/next-action record, so it stays
real, inspectable evidence under `react/` only, not duplicated into the working tier.

**Regression found and fixed:** two pre-existing tests
(`test_run_stage_does_not_promote_project_topology_when_gate_fails`,
`test_run_stage_does_not_promote_experience_knowledge_when_gate_fails`) asserted the
*entire* memory index was empty after a PARTIAL/gate-fail `run_stage()` call. Since
`ReactRecorder.record()` fires unconditionally on every stage attempt (regardless of
verdict) -- and that is exactly the intended behavior, Working Memory is meant to capture
provisional reasoning whether or not the stage passes -- those assertions are now stale.
Both were narrowed to check only the tier the test actually cares about (`project` /
`engineering` respectively), not the whole index.

## 2. Job Memory: `seed` / `fsdb_path` fields

Read `JobState` (`dv_harness/lsf_client.py`) and `.dv-harness/lsf/job_state_schema.json`
in full: **neither has a dedicated seed or FSDB field**, and neither `bsub_submit()` nor
the `dv-harness lsf-submit` CLI accept them as structured arguments. The only real field
that can ever carry this information is `JobState.options` -- a free-text string a caller
passes straight through to the underlying `bsub`/simulator invocation (e.g.
`+ntb_random_seed=1234 +fsdb_file=/path/run.fsdb`).

Added `_extract_seed_from_options()` / `_extract_fsdb_path_from_options()` (regex-based,
mirroring `gates.py`'s own log-scrubbing seed-marker vocabulary and the
`uvm_generator` Makefile template's `+fsdb_file=$(PAT_FSDB)` convention). In
`_write_job_tier_memory_on_terminal_reconcile()`, `seed`/`fsdb_path` are added to the
record **only when extraction actually finds a marker** in `state.options`.

**Honest residual gap (documented in code, not papered over):** for the common case --
`register_external_job()`-registered jobs, or `lsf-submit` invoked without an explicit
`+ntb_random_seed=`/`+fsdb_file=` in `--options` -- neither key is genuinely available at
this call site. Rather than writing `"seed": None` / `"fsdb_path": None` (a null
placeholder that would look like the schema captured this data when it did not), the keys
are **omitted from the record entirely** in that case. Fully closing this gap would require
adding real `seed`/`fsdb_path` fields to `JobState`/`job_state_schema.json` and threading
them through `bsub_submit()`/the `lsf-submit` CLI as first-class structured arguments --
out of scope for this change and left as a residual, explicitly-commented gap.

## 3. Project Memory: second gate-triggered writer (vPlan)

Read `dv_harness/gates.py`'s `STAGE_GATES["VPLAN"]` and
`tools/vplan/vplan_writer_validation_gate.py` (added earlier this session,
`vplan-doc-and-wiring-fix`): a PASS on that gate means
`evidence_blocks["vplan_writer_validation_gate"]` (the agent-supplied payload `run_gate()`
already fed the gate script -- read here without re-parsing agent text a second time, same
pattern as every sibling `_promote_*` method) genuinely holds a gate-validated vPlan item
list (`req_id`/`feature_area`/`pattern_name`/`task_name`/`suite`/...), because the gate
calls the real `dv_harness.vplan_writer.build_evidence_context()`/`validate_items()`
against real on-disk pattern-dir/dispatcher-file/task-declaration evidence.

Added `DVHarness._promote_vplan_summary_knowledge()` (`dv_harness/engine.py`), called
alongside the existing `_promote_*` methods on a VPLAN-stage PASS. It summarizes the
validated item list (`vplan_item_count`, `vplan_feature_areas`, `vplan_req_ids`,
`vplan_suites`, `vplan_pattern_dir`, `vplan_dispatcher_file`) into a
`kind="project_fact", verified=True` record and routes it through `route_and_store()` --
`route_memory()` already sends `project_fact` (verified) to `PROJECT_MEMORY`, no router
change needed. This is the second real gate-triggered Project Memory writer requested,
alongside the pre-existing `project_model_topology_completeness_gate` one.

## Tests added

- `dv_harness_tests/test_react_working_memory_bridge.py` (new): proves `ReactRecorder.record()`
  writes both the pre-existing `react/` file and a new `WorkingMemoryStore` record with the
  same hypothesis/evidence/next-action content; proves deterministic-id idempotency; proves
  a `route_and_store()` failure never raises out of `record()`; proves
  `route_memory({"kind": "react_reasoning_step"})` routes to `WORKING_MEMORY` explicitly
  (and stays distinct from `active_hypothesis` -> `BLACKBOARD`).
- `dv_harness_tests/test_memory_tier_completion.py` (extended): seed/fsdb_path extracted
  and written to the Job Memory record when present in `options` (both a combined marker
  string and a bare `seed=` marker); omitted entirely (not `null`) when absent; direct unit
  tests of the two extraction helpers.
- `dv_harness_tests/test_engine_gates_and_routing.py` (extended): a full `DVHarness.run_stage()`
  on VPLAN with real gate scripts copied into a temp root and real on-disk pattern/dispatcher/
  task fixtures (mirroring `test_vplan_writer_validation_gate.py`'s fixture shape) proves a
  PASS writes the expected Project Memory summary record and a `VPLAN_SUMMARY_PROMOTED`
  event. (Confirmed empirically that `vplan_writer_validation_gate.py`, when copied into an
  isolated temp root, needs the real project root on `PYTHONPATH` for its
  `dv_harness.vplan_writer` import to resolve -- the test sets that explicitly.) Also fixed
  the two now-stale gate-fail tests noted above.

## Test results

- Targeted files (`test_engine_gates_and_routing.py`, `test_memory_tier_completion.py`,
  `test_react_working_memory_bridge.py`, `test_react_loop.py`, `test_lsf_client.py`,
  `test_vplan_writer_validation_gate.py`): all pass after the two stale-assertion fixes
  above (314 passed).
- Full `dv_harness_tests/` suite: **1579 passed**, 0 failed, in 657.51s -- confirming zero
  regressions from all three changes (including the two stale-assertion fixes above).

## Concerns / residual gaps

- Job Memory's `seed`/`fsdb_path` remain genuinely absent for the majority of real jobs
  today (no structured submit-time field exists anywhere in the pipeline) -- this is
  intentionally surfaced as a gap, not hidden behind a null placeholder. Closing it fully
  needs a `JobState`/`job_state_schema.json` schema change plus CLI wiring, which was out
  of scope here.
- The two pre-existing "no memory record on gate failure" tests were narrowed rather than
  left broken; this reflects a genuine, intentional behavior change (Working Memory now
  records every stage attempt, not just successful ones), not a bug being swept under the
  rug -- flagged here explicitly per the Evidence Truth Rule.
