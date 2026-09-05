# Gap 2 — Real controlled-experiment execution in `capability_evolution.py`

**Status: DONE**

**Test summary:** `test_capability_evolution_controlled_experiment.py` **24 passed**;
capability-evolution / research / dashboard-research suites **238 passed**; whole
`dv_harness_tests/` suite (5283 tests, run in three parts) **zero failures attributable to this
change** — the only F/E marks are the 11 pre-existing `pueued`-daemon environment ones already
attributed in `.work/gap-close-3loop-gap-1-report.md`.

---

## The gap, restated from the code

`capability_evolution.py`'s `benchmark_plan` (schema string) and
`STOP_REPORT_PRECONDITIONS`' `benchmark_plan_complete` (agent-set boolean) were both TEXT: they
say what WOULD be measured. A search for a benchmark-execution function found none, so
`EXPERIMENTING -> BENCHMARKED` was an edge crossed by writing `reason="before/after measured"`
into `transition()` — no before, no after, no artifact. The repo's own existing test
`test_a_successful_experiment_does_not_imply_human_approved` walked exactly that edge with that
exact string, which is how the gap survived.

## What was built

### 1. `capability_evolution.run_controlled_experiment()` — the execution

Drives the **existing** `engine.DVHarness.run_stage()` twice over the SAME stages against two
copies of an isolated fixture project (`baseline` untouched, `treatment` carrying the candidate's
bounded change), and reads both arms back through the **existing**
`control_plane.describe_stage()` — already the one shared read path `dv-harness explain` and the
dashboard use for a stage's gate outcome. No second stage runner, no second gate evaluator, no
second measurement definition.

Supporting pure functions: `compare_experiment_arms()` (orders on gate satisfaction first, stage
completion second; reserves `INCONCLUSIVE` for "neither arm had a gate to measure" so it can never
read as a real `UNCHANGED`), `_measure_stage()`, `_arm_totals()`, `_apply_mutation()`,
`_tree_digest()`, `experiments_dir()`.

`mutation` is either a list of `{"path", "content"}` writes (the auditable form, carried into the
record) or a callable returning the paths it wrote. Both forms are containment-checked per path.

### 2. The evidence requirement — what actually closes the gap

`transition()` now refuses `-> BENCHMARKED` unless `assert_benchmark_measured()` clears, and every
check there **re-reads disk**:

| check | refuses |
|---|---|
| `benchmark_result` is a dict | a candidate carrying only a `benchmark_plan` |
| `produced_by == BENCHMARK_PRODUCER` (schema `const`) | a hand-written result claiming provenance |
| `record_path` under `<root>/.dv-harness/experiments/` | a record from anywhere else |
| record still exists | evidence deleted after the fact |
| `sha256(record_text) == record_digest` | a record edited after it was produced |
| record's `candidate_id` / `run_id` match | another candidate's or another run's record |

`build_candidate()` additionally refuses a caller-supplied `benchmark_result` — a candidate is born
four governance states before any experiment may run, so one arriving there measured nothing.

### 3. Schema

`capability_evolution_candidate.schema.json` gains `benchmark_result` (nullable, not in `required`,
so pre-existing candidates still validate) plus `$defs` `benchmark_result` / `benchmark_arm` /
`benchmark_stage_measurement`. `benchmark_plan` is unchanged and still required — it is the plan,
and it is now only the plan.

## The four isolation properties (each enforced in code, each tested)

1. **Everything written lives under `<root>/.dv-harness/experiments/<candidate_id>/<run_id>/`.**
   Each harness is constructed rooted inside an arm of that workspace, and that is re-checked
   against the harness object actually returned — an injected `harness_factory` returning one
   rooted at the live project is refused *before any stage runs*.
2. **The source fixture is content-fingerprinted before and after.** A changed digest means the run
   was not isolated and the measurement is discarded.
3. **An execution-layer stage is refused by default**, keyed on the same `vcs-build` /
   `devops-pipeline` node-skill discriminator `engine._execution_preflight_gate()` already uses.
   This is the guard that makes item 4 of the task structural rather than a promise:
   `allow_execution_stages=True` is the explicit opt-in and was never used here.
4. **A fixture containing the live project root is refused**, so the experiment cannot copy the live
   project into its own workspace.

**No real production build or regression was triggered anywhere in this pass.** Every experiment
ran against `dv_harness_tests/controlled_experiment_fixture.py`'s synthetic project on the
non-execution-layer `COMMAND_PATTERN` stage, and the only mocked thing is the agent adapter
(the real one dispatches a `claude -p` subprocess).

## Human-approval boundary: unchanged, and now asserted

Section 61's LEVEL B ends at BENCHMARKED. `run_controlled_experiment()` asserts its own terminal
state before returning — a real, IMPROVED measurement is exactly the circumstance under which
someone would be tempted to carry the candidate one more step. `PROMOTION_CANDIDATE` remains a
human's move; `assert_human_approval()`'s real `ControlPlane` check is untouched;
`assert_no_production_write_authorized()` still refuses a BENCHMARKED candidate. Both are asserted
directly in `test_an_experiment_never_advances_past_benchmarked`. The record states
`acceptance_criteria_machine_evaluated: false` explicitly: the criteria are free text, this code
does not judge them, and deciding whether the measurement meets them stays with the human.

## No verification verdict token reaches the candidate or the record

The arms really do produce gate verdicts. What is stored is the numeric gate counts plus a **hash**
of the verdict string, so a before/after CHANGE is detectable while the module keeps its "nothing
here persists a member of `models.Status`" guarantee. `BENCHMARK_OUTCOMES`
(IMPROVED/UNCHANGED/DEGRADED/INCONCLUSIVE) was added to
`assert_no_verification_verdict_vocabulary()`'s checked set, and Stage-1 Acceptance Test E's source
scan (no `"PASS"`/`"FAIL"`/`run_gate`/`evaluate_stage_evidence`/`signoff` in non-comment source)
still passes over the 600 new lines. `test_no_verdict_token_reaches_the_candidate_or_the_record`
asserts no `models.Status` value appears in either JSON blob, *and* that the two arms' digests
differ — so the guard has detection power rather than being satisfied by nothing having happened.

## The end-to-end proof is genuinely end to end

`test_controlled_experiment_measures_a_real_before_and_after` asserts a **measured movement**, not
a mocked one:

```
baseline arm : gates_total 1, gates_satisfied 0, stage_completion   0.0%
treatment arm: gates_total 1, gates_satisfied 1, stage_completion 100.0%
delta        : +1 gate satisfied, +100.0%, outcome IMPROVED
```

Both numbers come from the REAL `command_migration_integrity_gate.py` subprocess (copied
byte-for-byte from this repo's `tools/verification_flow/`) run by the REAL `gates.py` over the REAL
shipped `main_graph.json`, inside two REAL `DVHarness.run_stage()` calls.
`test_the_measurement_came_from_a_real_stage_run_in_each_arm` then re-opens each arm workspace's own
`state.json` and confirms the stage really executed there and that only the treatment copy carries
the mutated file.

## Files

- `dv_harness/capability_evolution.py` — +600 lines: the experiment block,
  `assert_benchmark_measured()` wired into `transition()`, `build_candidate()` refusal,
  `BENCHMARK_OUTCOMES` added to the vocabulary guard
- `dv_harness/schemas/capability_evolution_candidate.schema.json` — `benchmark_result` + 3 `$defs`
- `dv_harness_tests/controlled_experiment_fixture.py` — the synthetic fixture project (new)
- `dv_harness_tests/test_capability_evolution_controlled_experiment.py` — 24 tests (new)
- `dv_harness_tests/test_capability_evolution_research_architect.py` — the section-70 test now walks
  a REAL experiment instead of typing "before/after measured"
- `dv_harness_tests/test_dashboard_research_card.py` — `_walk_to()` likewise
- `.claude/agents/research-architect.md` — "Running the controlled experiment" section
- `CLAUDE.md` — "Controlled Experiments Are Executed, Not Attested (2026-09-05)"

**Deliberately NOT touched**: `dv_harness/cli.py`, `dv_harness/engine.py`, `dv_harness/router.py`,
`dv_harness/dashboard.py` — all under concurrent edit by other passes this session.

## Test evidence

| run | result |
|---|---|
| `test_capability_evolution_controlled_experiment.py` | **24 passed** in 84.9s |
| `test_capability_evolution_research_architect.py` | **30 passed** |
| `test_dashboard_research_card.py` | **14 passed** |
| `test_capability_evolution_auto_discovery` + `test_confidence_vocabulary_separation` + `test_research_intent_routing` + `test_research_memory_governance` + `test_research_stage1_acceptance_a_g` + `test_stats_snapshot` | **194 passed** |
| full suite files 1–134 (~3286 tests, from the interrupted whole-suite run that reached 74%) | 11 F/E marks, all `pueued` |
| full suite files 135–175 (895 tests) | **889 passed, 6 errors** (`test_pueue_client.py::TestRealPueueIntegration` — "real pueued did not come up") |
| full suite files 176–216 (1102 tests) | **1102 passed** |
| `test_knowledge_center.py` (the store-hygiene canary from the Gap 1 pass) | **30 passed** |

Every failure/error is the pre-existing `pueued`-daemon absence on this machine, identical to the
baseline recorded in `.work/gap-close-3loop-gap-1-report.md`. Nothing in this change touches
`pueue_client.py` or the `pueue` CLI verbs.

*Note on the whole-suite run:* a single 5283-test run exceeds this harness's background-task
budget (it was killed at 74%), so it was completed as three parts, the same way the Gap 1 pass
did. The three parts together cover all 216 test files.

## Commit

`e0a3002 capability_evolution: real controlled-experiment execution + harness-deploy mechanism`

**Disclosed process problem, not hidden:** this commit is broader than it should be. A concurrent
gap-close pass running in the same working tree ran a broad `git add` and swept my seven files in
together with its own `harness_deploy` work, `.dv-harness/events.jsonl`/`state.json` runtime state,
and other passes' `.work` reports. All seven of my files are present and complete in it (verified:
`git diff HEAD` over them is empty). I did not rewrite the shared history to re-scope it, because
other passes are actively committing on top of it — that would have been the more destructive
choice. The hand-scoped patch technique was used for everything under my control; the scoping was
lost to a concurrent writer, not to a broad `git add` of my own.

## Disclosed residual (honest scope)

- **No CLI verb, and nothing engine-fired.** `run_controlled_experiment()` is called by the
  `research-architect` path (documented in that agent's own profile) and by its tests — a REACHED
  capability, not a WIRED one. A CLI verb was deliberately not added because `cli.py` was under
  concurrent edit by another pass this session and because a CLI-shaped experiment spec is a
  larger design surface than this gap.
- **The mutation is still authored by whoever runs the experiment.** Nothing derives a candidate's
  bounded change from its own `proposed_action` text, so `experiment_plan` remains a plan a human
  or an agent enacts — in the same sense `benchmark_plan` used to be one for the benchmark. What is
  closed is that BENCHMARKED can no longer be reached without a real, isolated, re-readable
  before/after run.
- **Acceptance criteria are not machine-evaluated**, and the record says so in a `const false`
  field rather than leaving it to be assumed.
