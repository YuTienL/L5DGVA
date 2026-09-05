# LOOP-1 — LoopContract schema + loop state machine extension

**Status: DONE**

**Test summary:** 698 tests passed, 0 failed — `test_loop_contract.py` 50/50
(new), plus every suite over the code this change touches: engine/graph 237,
capability_evolution + blackboard 116, CLI 110, CLAUDE.md-parity
(source_authority / mcp_claude_md_index / context_budget) 146, memory-router +
closure-gate 39.

---

## 1. The gap, independently re-verified before building

Run from `D:/DV/Task/DV_Agent_Harness_L5/v50/` on 2026-09-05, before writing a
line:

```
grep -rniE "loopcontract|loop_contract|LoopState|BUDGET_EXHAUSTED|OSCILLAT|PLATEAU" --include="*.py" .
```

Four hits, all unrelated (`amba_fabric_analysis.py` prose about a
"single-oscillator SoC", `canfd_arbitration_generator.py`'s "DUT/oscillator-
dependent" comment, a register-memory note about a "ring-oscillator done" bit).
Zero hits for `LoopContract`, `loop_contract`, `LoopState`, `BUDGET_EXHAUSTED`,
`PLATEAU`. The gap was real and still open.

The master prompt sections were read at source
(`../CLAUDE_DV_Agent_Harness_L5_ULTIMATE_COMPLETE_LOOP_ENGINEERING.md:3306-3373`)
rather than from the audit's summary — §85's YAML field list and §86's canonical
state chain are implemented field-for-field and state-for-state.

`models.py:74`'s `Status` enum was confirmed to carry exactly the ten members
the audit described, with `WAIT_USER` genuinely covering HUMAN_GATE, and
`engine.py:4617-4621`'s `ss["attempts"] <= max_retry` branch confirmed as the
one place a real budget is spent in this engine.

## 2. What was built

### `dv_harness/loop_contract.py` (new, 1268 lines including reasoning comments)

**§86 — the state machine.** `LoopState` carries all 17 canonical states.
`LEGAL_LOOP_TRANSITIONS` is the explicit edge table derived from §86's own
chain; `assert_legal_loop_transition()` raises `IllegalLoopTransitionError` on
anything else. `TERMINAL_LOOP_STATES` / `RESUMABLE_LOOP_STATES` are data, not
prose.

**The Status bridge, not a Status extension.** `STATUS_TO_LOOP_STATE` is the one
real mapping. `assert_status_mapping_total()` and
`assert_capability_state_mapping_total()` make it TOTAL in both directions — a
new `models.Status` member (or a new `capability_evolution.PROMOTION_STATES`
member) added without deciding its loop meaning fails a test rather than
silently falling through. Rationale for keeping the vocabularies separate is in
the module docstring: `Status` is persisted in every `state.json` and branched
on by `gates.py`/`engine.py`/`dashboard.py`/`commands.py`, and eight of §86's
states are not verdicts at all.

Two mappings that carry real reasoning rather than convenience:
* `PASS -> CONVERGING`, not SUCCESS (SUCCESS is the LOOP's own machine-checkable
  done, `overall_status == CLOSED`; per-stage SUCCESS would claim a closed
  project ~40 times a run).
* `ACCEPTED_RISK -> STOPPED`, not SUCCESS (a human accepted residual risk; the
  machine-checkable done was not met, so SUCCESS would be a false claim).

`derive_loop_state()` has a documented, tested precedence that matches the
engine it describes: takeover (Human Override, checked first exactly as
`loop()` checks it first) > paused > spent retry budget > oscillation fingerprint
> loop-done > the table.

**§85 — the contract.** `LoopContract` plus `LoopBudgets` / `LoopRetryPolicy` /
`LoopConvergence` / `LoopPlateau` / `LoopOscillation` / `LoopTermination`
dataclasses, covering every field §85 lists. `to_yaml()`/`from_yaml()` render
and round-trip §85's own YAML shape.
`dv_harness/schemas/loop_contract.schema.json` (new) is the JSON schema,
following the existing `dv_harness/schemas/*.schema.json` convention.

**Contracts are derived from the drivers, never hand-maintained** — the same
policy `protocol_capability.py`'s registry follows:
* `verification_closure_contract(cfg)` reads `policy.max_stage_retries` and
  `claude.max_turns` off the loaded config.
* `project_learning_contract()` imports `ORGANIZATIONAL_MIN_CONFIRMATIONS` and
  the engineering-admission constants from `memory_router`.
* `capability_evolution_contract()` imports `PROMOTION_STATES`,
  `TERMINAL_STATES`, `PRODUCTION_WRITE_AUTHORIZED_STATES`,
  `HUMAN_APPROVAL_STAGE` and `REPEAT_FAILURE_MIN_OCCURRENCES` from
  `capability_evolution`.

`assert_driver_resolvable()` imports each contract's `driver_module` and
resolves its `driver_entry_point` through the real import system, so a contract
cannot outlive or misname the loop it documents (tested by renaming one and
asserting the refusal). There is deliberately **no `sync`/`set` verb** — a
second, editable copy of a contract on disk would be the parallel mechanism this
project forbids.

**Absent budgets are stated, never implied.** §85 lists eight budgets; this
harness really enforces two (`max_failed_attempts` = `policy.max_stage_retries`;
capability evolution's `max_change_scope` = `run_controlled_experiment()`'s
mutation containment check). Every other field is `None` **and** carries a real
reason in `budget_sources`; `validate_contract()` refuses a contract with a
budget key missing from it. A test asserts no contract claims a bound outside
that enforced set. `loop()` genuinely is an unbounded `while True` over the
graph with no wall-clock deadline, and the contract says exactly that.

**Observers derive state from backend evidence only** (§86: "not Agent prose"):
* `observe_verification_closure_loop()` — from a real `models.HarnessState`, the
  real `ControlPlane` payload, and real Blackboard `debug_loop_history` entries.
* `observe_capability_evolution_loop()` — from a real candidate's
  `current_status`, via `CAPABILITY_STATE_TO_LOOP_STATE`.
* `observe_project_learning_loop()` — from a real
  `memory_router.route_and_store()` result's destination, with an admission
  rejection reported as BLOCKED rather than hidden as "still running".

Each returns a `LoopObservation` carrying the actual field values it read, so a
reader can re-derive the verdict instead of trusting it.

**Oscillation from evidence the engine already persists.**
`detect_oscillation_from_debug_loop_history()` counts repeated
`(failing_stage, target_fail_edge)` pairs in the Blackboard `debug_loop_history`
topic `engine._record_debug_loop_round()` has written since 2026-09-01 — exact
tuple matching on graph node ids the engine wrote for its own reasons, at the
same 2-independent-observations threshold `REPEAT_FAILURE_MIN_OCCURRENCES` and
`ORGANIZATIONAL_MIN_CONFIRMATIONS` already use. No new store, no new writer.

### `dv_harness/engine.py` (+~50 lines, 3 hunks)

`DVHarness._record_loop_state_observation()` writes one real
`LOOP_STATE_OBSERVED` event to `.dv-harness/events.jsonl` (via the existing
`StateStore.event()`, no second audit file), called at the **two** places this
engine actually spends the retry budget:
* `loop()`'s retry-exhaustion branch, `occasion="RETRY_BUDGET_EXHAUSTED"`;
* `_advance_with_fanout()`'s branch-failure branch,
  `occasion="FANOUT_BRANCH_FAILED"`.

Both sit one line after `_record_debug_loop_round()`, which recorded the ROUTING
decision but never the fact that a BUDGET was what ran out. Best-effort,
mirroring every sibling `_record_*`/`_promote_*`: a failure records
`LOOP_STATE_OBSERVE_FAILED` and never turns an already-computed routing decision
into a crash (tested).

### `dv_harness/cli.py` (+~40 lines, 2 hunks)

`dv-harness loop-contract states|list|show <loop_id> [--format yaml]|observe`,
dispatching into the same `loop_contract.execute_verb()`
`python -m dv_harness.loop_contract` uses — one implementation, two front doors,
matching the `harness-deploy` precedent directly above it in the same file.

### `CLAUDE.md`

One new section, "LoopContract + the Canonical Loop State Machine (2026-09-05)",
per the Methodology Consolidation Rule, including the disclosed residual below.

## 3. Tests — `dv_harness_tests/test_loop_contract.py` (50 tests)

Not "an isolated function returns a value". The real-path half:

* **`test_real_loop_reaches_budget_exhausted_and_records_it`** drives the REAL
  `DVHarness.loop()` over the REAL shipped `main_graph.json`, with the REAL
  `tools/verification_flow/command_migration_integrity_gate.py` subprocess
  judging the stage, in an isolated fixture project copy. It asserts the loop
  really spent the budget (`attempts > max_stage_retries`) and that a real
  `LOOP_STATE_OBSERVED` / `BUDGET_EXHAUSTED` event reached
  `.dv-harness/events.jsonl`. Verified out-of-band too: a standalone run prints
  `attempts 3 status PARTIAL` and the event.
* **`test_a_real_gate_pass_observes_as_converging`** is the positive control —
  the same fixture with the migration manifest present, the same real gate,
  reaching a real PASS and observing CONVERGING. Without it, BUDGET_EXHAUSTED
  would only prove the fixture always fails.
* **`test_a_second_identical_failure_is_a_real_oscillation_fingerprint`** runs
  two real retry-exhaustion rounds so two real `debug_loop_history` entries
  exist, and asserts the fingerprint fires on records nothing wrote for the test.
* Real `ControlPlane` pause → STOPPED, real takeover → HUMAN_GATE.
* Real `capability_evolution.transition()` walked one legal governance state at
  a time (no shortcut write): `CREATED → RUNNING → HUMAN_GATE → READY → RUNNING`.
* Real `memory_router.route_and_store()` against a real MemoryStore on disk.
* `test_cli_verb_is_registered_and_dispatches` runs the real argparse tree as a
  subprocess — importable is not the same as reachable.

The boundary half:
* `test_observing_human_gate_authorizes_nothing` — after producing a HUMAN_GATE
  observation, `ce.assert_human_approval()` still raises
  `HumanApprovalRequiredError` and `ce.assert_no_production_write_authorized()`
  still raises `ProductionWriteNotAuthorizedError`.
* Every state reachable from CREATED; terminal states have no outgoing edges;
  illegal and unknown transitions raise; unknown Status/destination/promotion
  state is refused rather than guessed.
* An unbounded budget with no stated reason is refused; a contract naming a
  driver that does not exist is refused; a contract missing a required §85 field
  is refused.

**No production build / regression / LSF submission is possible from any of
this.** COMMAND_PATTERN was chosen as the fixture stage because it is an
`implementation-route` node (no `vcs-build`/`devops-pipeline` skill) *and* has no
FAIL edge in the real graph, so a retry-exhausted `loop()` stops deterministically
instead of walking into BUILD/VERIFY/REGRESSION. The fixture is
`dv_harness_tests/controlled_experiment_fixture.py`, reused rather than
duplicated.

## 4. Human-approval gates: unchanged

Nothing in this change calls, relaxes or bypasses `ControlPlane.approve()`,
`policy.can_signoff()`, `HumanApprovalRequiredError`,
`ProductionWriteNotAuthorizedError`, `question_queue`'s human decision source, or
the PR-only main/master governance. `HUMAN_GATE` is an observation that a human
decision is owed; producing it authorizes nothing, and a test proves the real
gates still fire on an entity observed at HUMAN_GATE.

## 5. Deferred, and why

* **The convergence engine (§88), plateau detection (§89) and the §90
  no-progress response** are NOT built. `observe_*` reports
  `plateau: PLATEAU_NOT_EVALUATED` with the reason, and the engine still routes a
  retry-exhausted stage onto its graph FAIL edge exactly as before. Plateau needs
  a progress-metric series over iterations, whose real producers are
  `trend_analysis.py` / `coverage_analysis.py`; fabricating one here would be the
  exact Evidence-Truth-Rule violation this project forbids, and a detector that
  never ran must not report "no plateau". This is LOOP-2/LOOP-4's ground, which
  is why LOOP-1 was scoped to the contract and the vocabulary they build on.
* **§91's `LOOP_*` event taxonomy** is only partly emitted —
  `LOOP_STATE_OBSERVED` / `LOOP_STATE_OBSERVE_FAILED` are real; the other
  nineteen names have no producer. Emitting names nothing computes would be
  worse than not emitting them.
* **The Project Learning Loop has no project-wide observation.** It is observed
  PER RECORD at a `route_and_store()` result, so `observe_all()` reports it
  `NOT_OBSERVABLE` with that reason rather than inventing an aggregate nothing
  computes.

## 6. Files touched

| File | Change |
|---|---|
| `dv_harness/loop_contract.py` | NEW — schema, state machine, observers, `execute_verb()` |
| `dv_harness/schemas/loop_contract.schema.json` | NEW — §85 JSON schema |
| `dv_harness_tests/test_loop_contract.py` | NEW — 50 tests |
| `dv_harness/engine.py` | +`_record_loop_state_observation()` and its 2 call sites |
| `dv_harness/cli.py` | +`loop-contract` parser and handler |
| `CLAUDE.md` | +1 consolidation section |
| `.dv-harness/events.jsonl` | append-only `CLI_ACCESS` entries from this session's real verb invocations |

## 7. Regression run — all green

| Suite | Result |
|---|---|
| `test_loop_contract.py` (new) | 50 passed, 15.2s |
| `test_engine_gates_and_routing.py`, `test_graph_parallel_dispatch.py`, `test_graph_runtime_removed.py` | 237 passed, exit 0 |
| `test_capability_evolution_{auto_discovery,controlled_experiment,research_architect}.py`, `test_blackboard_{automatic_path_and_concurrency,subsystem_wiring}.py` | 116 passed, 277.9s |
| `test_cli_{blackboard,question_queue,memory_commands,adapter_command_resolution,preflight,git_guard}.py`, `test_harness_deploy.py` | 110 passed, 303.0s |
| `test_source_authority.py`, `test_mcp_claude_md_index.py`, `test_context_budget.py` (the CLAUDE.md-parity suites, run because this change appends a section) | 146 passed, 50.8s |
| `test_engineering_confirmation_accumulation.py`, `test_memory_dedup_write_path.py`, `test_qualified_conclusion_closure_gate.py`, `test_question_queue_digest_auto_trigger.py` | 39 passed, 458.5s |

**698 passed, 0 failed.**
