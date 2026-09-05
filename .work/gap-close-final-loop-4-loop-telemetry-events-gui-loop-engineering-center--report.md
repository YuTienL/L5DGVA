# LOOP-4 — Loop telemetry events (section 108) + GUI Loop Engineering Center (section 107)

**Status: DONE**

**Test summary:** 1080 passed, 0 failed across every suite that touches what
this change edits — new `test_loop_telemetry.py` 37 and
`test_dashboard_loop_card.py` 8, plus LOOP-1/2/3's own suites 164, all six
dashboard suites 109, engine/graph 263, and two batches (338 + 161) covering
every other suite that references `dashboard`, `.loop(`, `_overall_progress` or
any `loop_*` module.

---

## 1. The gap, independently re-verified before building

Run in this checkout on 2026-09-05, before writing a line — not taken from the
audit:

| Check | Result |
|---|---|
| each of section 108's 19 names as a string literal, `grep -rn "\"<NAME>\"\|'<NAME>'" --include=*.py .` | **0 hits, all nineteen** |
| what `LOOP_*` names DO have producers (`grep -oE "LOOP_[A-Z_]+" dv_harness/*.py`) | `LOOP_STATE_OBSERVED` / `LOOP_STATE_OBSERVE_FAILED` (LOOP-1), `LOOP_BUDGET_SPENT` / `LOOP_BUDGET_SPEND_FAILED` / `LOOP_RETRY_REFUSED` / `LOOP_RETRY_DECISION_FAILED` (LOOP-3) — none of them a section-108 name |
| `grep -ni "loop" dv_harness/dashboard.py` | 11 hits, all the pre-existing single-run/continuous-run Start toggle (`startLoopBtn` line 333, `_start_background_run` ~2576, `POST /api/start` ~3273) — a CONTROL, never an observability table |
| the spec at source (`CLAUDE_DV_Agent_Harness_L5_ULTIMATE_COMPLETE_LOOP_ENGINEERING.md:3597-3615`) | §107's eight columns + fourteen drill-down fields and §108's nineteen names read verbatim, not from the audit's summary |

Better than a stale audit: LOOP-1's own CLAUDE.md section already **declared**
this gap — *"Section 91's `LOOP_*` event taxonomy is also only partly emitted
(`LOOP_STATE_OBSERVED` / `LOOP_STATE_OBSERVE_FAILED`; the other nineteen names
have no producer)."* Gap CONFIRMED real and still open.

LOOP-1 (`17fadbf`), LOOP-2 (`996c5cc`) and LOOP-3 (`805170f`) were all confirmed
landed in `git log` and their reports read before starting, as the task requires.

---

## 2. What was built

### `dv_harness/loop_telemetry.py` (new)

Two halves and nothing else — a WRITER vocabulary and a READER.

* **`LOOP_TELEMETRY_EVENTS`** — section 108's nineteen names in its order,
  checked against a transcription of the specification's own comma-separated
  line by `assert_events_match_section_108()` (a list checked only against
  itself is not checked — the same technique
  `golden_flow_readiness._assert_rows_match_section_47()` uses).
* **`emit(store, event, ...)`** — writes through the existing
  `storage.StateStore.event()` into the one `.dv-harness/events.jsonl`
  every other subsystem writes to. **No second event file, no second
  serializer, no second audit trail.** A name outside the nineteen RAISES
  rather than being written.
* **`LOOP_STATE_TO_EVENT`** — the one bridge to `loop_contract.LoopState`,
  held TOTAL by `assert_loop_state_mapping_total()`. The four states that name
  no section-108 event (`READY`, `VERIFYING`, `CANCELLED`, `STALE`) carry a
  real reason in `LOOP_STATE_WITHOUT_EVENT_REASON`, and the totality check
  REFUSES a `None` with no reason.
* **`read_loop_telemetry()`** — folds the events back into section 107's eight
  columns (`SECTION_107_COLUMNS`) and fourteen drill-down fields
  (`SECTION_107_DRILLDOWN_FIELDS`), both checked against transcriptions of the
  section's own two lines by `assert_columns_match_section_107()`. One row per
  loop SESSION, newest first.
* **`gate_verified_stage_count()`** — the single definition of "which stages
  count as verified"; `dashboard._overall_progress()` now DELEGATES to it.
* **`next_actions_for_states()`** — the REAL `inference.next_best_action()`
  through its `gap_action_catalog` parameter, never a re-implementation
  (section 10 forbids one).
* Front door: `python -m dv_harness.loop_telemetry names|events|rows|show`,
  one shared `execute_verb()`.

### `dv_harness/engine.py` — the producers

Nine best-effort, observe-only methods and their call sites inside the REAL
`loop()`. Not one changes a status, a route, an attempt count or a verdict.

| Event | Real transition point |
|---|---|
| `LOOP_CREATED` | first-ever session for this loop id, decided by READING the append-only log (`previous_session_summary()`), never a flag |
| `LOOP_STARTED` | every `loop()` session start (after the dry-run early return) |
| `LOOP_RESUMED` | a prior session that did NOT reach `LOOP_SUCCESS` |
| `LOOP_ITERATION_STARTED` | top of the `while True` body |
| `LOOP_ACTION_SELECTED` | before `run_stage()`, carrying the graph node's own `route`/`skills` |
| `LOOP_VERIFY_COMPLETED` | after `run_stage()`, carrying `gates.effective_stage_gates()`'s real gate ids (§87's verifier separation, recorded) |
| `LOOP_PROGRESS_UPDATED` | after every iteration, `gate_verified_stages` value/total/delta |
| `LOOP_CONVERGING` / `LOOP_NO_PROGRESS` | per-iteration gain delta > 0 / == 0 (§110 LOOP-AT-26) |
| `LOOP_RETRY_SCHEDULED` | the one `ss["status"] = RETRY` branch |
| `LOOP_BUDGET_WARNING` | that same branch when `attempts_remaining == 0` — the last allowed retry |
| `LOOP_BUDGET_EXHAUSTED` | the retry-exhaustion branch, carrying LOOP-3's ledger payload |
| `LOOP_PLATEAU_DETECTED` / `LOOP_OSCILLATION_DETECTED` / cross-run `LOOP_CONVERGING` / `LOOP_NO_PROGRESS` | the same branch, from a REAL `loop_convergence.classify_loop_convergence()` report |
| `LOOP_BLOCKED` | circuit-breaker open, SIGNOFF gate refusal, stage BLOCKED |
| `LOOP_HUMAN_GATE_REQUIRED` | takeover, stage WAIT_USER |
| `LOOP_STOPPED` | takeover, pause, human gate |
| `LOOP_FAILED` | retries exhausted with no FAIL edge and no reroute hint |
| `LOOP_SUCCESS` | `advance()` ran out of graph → `overall_status = CLOSED` |

**Exactly one terminal event per session** on every one of `loop()`'s eight
return paths, enforced by `_end_loop_telemetry()` clearing the session.

**LOOP-2's classifier is now engine-fired**, which is what gives PLATEAU a
producer at all. `_classify_loop_convergence_for_telemetry()` runs it once per
retry exhaustion (never per iteration) and passes the report into the
`observe_verification_closure_loop(convergence=...)` parameter LOOP-2 had
already built and nothing used — so `LOOP_STATE_OBSERVED`'s `plateau` field now
carries a real verdict instead of `PLATEAU_NOT_EVALUATED` forever. The evidence
database is opened READ-ONLY or (no database) not at all.

### `dv_harness/dashboard.py` — the surface

* `_read_loop_engineering_state()` + `GET /api/loops` (`?run_id=` filter),
  read-only, alongside the other read-only GET branches; an unreadable audit
  trail reports a real reason rather than a 500.
* A **Loop Engineering Center** card following the GUI-09/10/11 convention read
  out of today's `git log` — the eight §107 columns (labels served over the
  wire from `SECTION_107_COLUMNS`, never a hardcoded copy in the page), a
  click-a-row drill-down rendering all fourteen §107 fields in the section's own
  order, an honest empty state naming the file read and the command that would
  populate it, and a `.warn` severity distinct from `.err` so
  `LOOP_BUDGET_WARNING` does not read as a failure.
* Joined to `load()`'s 3s poll (like the AMBA/Research cards, unlike the Memory
  card): a running loop's state is exactly what must not be minutes stale on a
  control plane, and reading it is a tail of a log plus one catalog lookup.
* `_overall_progress()` delegates to `loop_telemetry.gate_verified_stage_count()`
  and the now-unused `from .models import Stage` import was removed.

### `CLAUDE.md`

One new section, "Loop Telemetry Events + the GUI Loop Engineering Center
(2026-09-05)", per the Methodology Consolidation Rule, including the disclosed
residual below.

---

## 3. Tests — 45 new, all against real paths

`dv_harness_tests/test_loop_telemetry.py` (37) and
`test_dashboard_loop_card.py` (8). Every event is driven out of a REAL
`DVHarness.loop()` over the REAL shipped `main_graph.json` with the REAL
`command_migration_integrity_gate.py` subprocess — **never** by writing an
events.jsonl line by hand. The only test that calls `emit()` directly is the
one asserting it REFUSES an unknown name.

The negative controls, which are what give them detection power:

* a real gate PASS is the positive control for `LOOP_CONVERGING` against the
  failing fixture's `LOOP_NO_PROGRESS` — otherwise "no progress" would only
  prove the fixture always fails;
* a real four-day flat coverage curve, written by the REAL
  `dashboard.append_coverage_history_sample()` into a REAL DuckDB evidence
  store (reusing LOOP-2's own `_coverage_days` helper, not a copy), produces
  `LOOP_PLATEAU_DETECTED`; a real RISING curve produces none;
* a project with NO evidence database emits no plateau verdict at all and the
  row reads `NOT_EVALUATED` — the fabrication guard;
* a loop that really CLOSED is not reported as `LOOP_RESUMED` by the next
  session;
* a `run_stage()` and a `--dry-run` loop open no session and emit nothing;
* a torn/foreign `events.jsonl` line is skipped, not fatal;
* `LOOP_TELEMETRY_EMIT_FAILED` is recorded and the loop still spends its real
  retry budget when `emit()` is made to raise.

`LOOP_SUCCESS` is reached through a real `overall_status == CLOSED` via a real
SIGNOFF whose human-approval requirement is **satisfied through the real
`ControlPlane.approve()`**, and the approval's per-PASS consumption is asserted
(the second session needs a second approval) rather than worked around.

Nothing in either file runs a build, a regression or an LSF submission:
COMMAND_PATTERN is an `implementation-route` node with no FAIL edge, and the
fixture is `dv_harness_tests/controlled_experiment_fixture.py`, reused rather
than duplicated.

---

## 4. Human-approval gates: unchanged

Not one gate was weakened. `loop_telemetry.py` does not reference
`ControlPlane`, `can_signoff`, `assert_human_approval`, `approve(`,
`HumanApprovalRequiredError` or `ProductionWriteNotAuthorizedError` **at all** —
asserted against the module's own source by
`test_the_telemetry_module_never_reaches_for_an_approval_gate`.
`LOOP_HUMAN_GATE_REQUIRED` records that a human decision is OWED and authorizes
nothing: `test_emitting_a_human_gate_event_authorizes_nothing` produces one and
then asserts `ce.assert_human_approval()` and
`ce.assert_no_production_write_authorized()` both still raise and no approval
was minted. `GET /api/loops` is read-only and there is deliberately no
loop-specific write endpoint — starting/stopping a loop already has one behind
GUI-19's token gate, asserted by `test_the_card_offers_no_write_endpoint_of_its_own`.
Reading writes nothing (mtime-fingerprint assertions on both the module and the
HTTP path).

`dv_harness/golden_flow_readiness.py` was never touched.

---

## 5. Deferred, and why

* **Only the Verification Closure loop emits telemetry.** The Project Learning
  and Capability Evolution loops emit no section-108 event — the first is
  observed PER RECORD at a `route_and_store()` result (`observe_all()` already
  reports it `NOT_OBSERVABLE`), and the second is driven by human
  `dv-harness research` / governance transitions rather than by an iterating
  driver, so a `run_id`-scoped SESSION does not exist for either. Minting one
  would be inventing a loop instance nothing runs.
* **`CANCELLED` and `STALE` have no producer**, and say so in
  `LOOP_STATE_WITHOUT_EVENT_REASON`: `derive_loop_state()` never returns
  CANCELLED, and section 97's stale detection is not built.
* **No `dv-harness` CLI verb.** `cli.py` was being edited concurrently by
  another close-pass in this same sequential loop, and the GUI-09/10/11
  convention this gap follows adds a card + endpoint without one. The two front
  doors are `GET /api/loops` and `python -m dv_harness.loop_telemetry`, sharing
  one `execute_verb()` so a CLI verb is a two-line addition later.
* **Sections 88–90's RESPONSE half is still not built** (unchanged from LOOP-2's
  own residual): a `LOOP_PLATEAU_DETECTED` event is now produced and shown, but
  `loop()` still routes a retry-exhausted stage onto its graph FAIL edge exactly
  as before. This gap closed the OBSERVABILITY, not the reaction.

---

## 6. Files touched

| File | Change |
|---|---|
| `dv_harness/loop_telemetry.py` | NEW — §108 vocabulary, `emit()`, §107 reader, `execute_verb()` |
| `dv_harness_tests/test_loop_telemetry.py` | NEW — 37 tests |
| `dv_harness_tests/test_dashboard_loop_card.py` | NEW — 8 tests |
| `dv_harness/engine.py` | + the nine telemetry methods and their `loop()` call sites; `_record_loop_state_observation(convergence=...)` |
| `dv_harness/dashboard.py` | + the card, `GET /api/loops`, `_read_loop_engineering_state()`, `.warn`; `_overall_progress()` delegates |
| `CLAUDE.md` | +1 consolidation section |

**Shared-file discipline.** `engine.py` and `dashboard.py` were clean in
`git status` before and after (no other pass had touched them). `CLAUDE.md`
carried another pass's STAGED mid-file hunk (the lsf-watch cadence paragraph):
my section is a pure append, so the commit was built from `HEAD:CLAUDE.md` +
my section only (verified `127 insertions(+), 0 deletions`), and their hunk was
restored to the worktree and re-staged afterwards, byte-identical.
`dv_harness/cli.py`, `regression_reporter.py`, `DV_REGRESSION_SNAPSHOT.ps1`,
`.dv-harness/events.jsonl` and the other pass's `.work/` reports were left
untouched and unstaged-by-me; the commit used an explicit pathspec so none of
them could be swept in.

---

## 7. Regression run — all green

| Suite | Result |
|---|---|
| `test_loop_telemetry.py` (new) | 37 passed |
| `test_dashboard_loop_card.py` (new) | 8 passed |
| `test_loop_contract.py`, `test_loop_convergence.py`, `test_loop_budget.py` (LOOP-1/2/3, unchanged) | 164 passed |
| all six `test_dashboard_*.py` | 109 passed |
| `test_engine_gates_and_routing.py`, `test_graph_parallel_dispatch.py`, `test_graph_runtime_removed.py`, `test_inference_engine_wiring.py` | 263 passed |
| batch 1: the 15-suite set of everything else referencing `dashboard` / `.loop(` / `_overall_progress` / any `loop_*` module | 338 passed |
| batch 2: `test_blackboard_automatic_path_and_concurrency`, `test_harness_deploy`, `test_memory_write_guard_and_job_evidence`, `test_protocol_and_environment_mode_engine_wiring`, `test_protocol_capability`, `test_qualified_conclusion_closure_gate`, `test_signoff_stage_gate_e2e`, `test_waveform_dump_scope_human_confirmation` | 161 passed |

**1080 passed, 0 failed.**

**One honest note on batch 2.** Its first run reported `1 failed, 160 passed`:
`test_harness_deploy.py::test_cli_apply_to_a_synthetic_target_then_plan_is_clean`
reported `different: ['CLAUDE.md']`. That is a race with THIS pass, not a
regression — that test copies the whole harness tree to a synthetic target and
then re-plans, and my CLAUDE.md scoping surgery (rewriting the file to
`HEAD` + my section) landed between its apply and its plan. Re-run against a
settled tree immediately afterwards: **1 passed**. Nothing in this change
touches `harness_deploy.py`.
