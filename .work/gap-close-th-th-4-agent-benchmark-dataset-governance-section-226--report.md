# TH-4 — Agent Benchmark Dataset Governance (spec section 226)

**Status: DONE**

**Test summary:** 24 new tests pass, and every suite around what I touched passes with
them: `test_benchmark_dataset_governance.py` + `test_capability_evolution_controlled_experiment.py`
+ `test_capability_evolution_shadow_validation.py` → **71 passed** (559s), and
`test_cli_blackboard/question_queue/preflight.py` + `test_golden_scenario.py` →
**43 passed** (218s), covering the `cli.py` subparser addition and the adjacent
`execute_verb` convention it copies.

---

## 1. Gap re-verified independently (not taken from the audit)

- `grep -rn "eval_corpus|benchmark_dataset|BenchmarkDataset|dataset_version|leakage" --include=*.py .`
  → the only `leakage` hits are `memory_security`/`memory_doctor`'s **secret**-leakage
  detector and one comment in `remote_relay.py`. No eval-corpus code anywhere.
- `capability_evolution.run_controlled_experiment()` (read in full, lines 2541-2639) is
  per-CANDIDATE execution: it walks ONE candidate `EXPERIMENT_APPROVED → EXPERIMENTING →
  BENCHMARKED` over ONE fixture with ONE mutation. `benchmark_plan` is per-candidate free
  text; `benchmark_result` is that single measurement. Nothing versioned, nothing
  multi-case, no notion of a case having been used for tuning.
- Confirmed **NEVER_BUILT**. Spec text read at
  `CLAUDE_L5_SPEC_TO_SYSTEM_UVM_TARGETED_HARDENING.md:7533-7556`.

## 2. What was built

**`dv_harness/benchmark_dataset.py`** (new, 1188 lines) + CLI verb + CLAUDE.md section.

### Registry (versioned, content-addressed)
Immutable JSON versions at `<root>/.dv-harness/benchmark_datasets/<id>/versions/vN.json`.
Every section 226 tracked field is required and validated on every case: `case_id`,
`source`, `protocol`, `project_coverage`, `difficulty`, `expected_result`,
`known_ambiguity`, `owner`, `qualification`, `provenance` — plus the execution fields
`fixture_ref`, `stages`, `mutation`.

Four refusals, each because the alternative destroys the meaning of a version number:
re-registering a version with different content (bump instead); a bump whose cases are
identical to the previous version; back-dating below the latest version; and
re-registering *over* a version whose file on disk has drifted (which a naive idempotence
check would have blessed — that hole was found and closed while writing the tests).
`verify_dataset_integrity()` recomputes off disk → `CONTENT_DRIFT` naming the drifted
cases. `diff_dataset_versions()` names added/removed/modified.

### Runner — reused, not reinvented
Each case is executed by **`capability_evolution._prepare_shadow_run()` +
`_execute_shadow_run()`** — the same isolated two-arm machinery
`run_controlled_experiment()` uses: fixture fingerprinted before and after, copied twice,
the REAL `DVHarness.run_stage()` driven in each arm, both measured through the REAL
`control_plane.describe_stage()`. A case's `expected_result` is one of that module's own
`BENCHMARK_OUTCOMES`. There is still exactly one shadow-run implementation in the package.

### Leakage — two digests, deliberately
- `case_record_digest()` = every tracked field → dataset-version **integrity**.
- `case_question_digest()` = only what the case ASKS (`expected_result`, `fixture_ref`,
  `stages`, `mutation`) → **leakage identity**, matched across EVERY version of the
  dataset through an append-only `tuning_ledger.jsonl`.

So renaming or re-owning a case cannot launder its tuning history, while changing what it
asks makes it genuinely another case. An eval reports the full score AND the held-out
score, judges `MET`/`NOT_MET` on the held-out set only, and reports `INADMISSIBLE` when
every case was used for tuning — section 226's "do not evaluate a capability only on
examples used to tune it" as a status, not a sentence. Related-but-different subject
versions are reported as `related_tuning_use_case_ids` and never folded into the score.

### Result record
Identifies the subject (`subject_id`/`subject_version`/`subject_kind`) and the environment
(python, platform, harness root, real `change_impact.resolve_sha(root, "HEAD")`), per
section 226's "benchmark results must identify Agent/Skill version and environment".

### CLI
`dv-harness benchmark-dataset register|list|verify|diff|record-tuning-use|leakage|runs`
and `python -m dv_harness.benchmark_dataset` share one `execute_verb` (same convention as
`power-intent`/`golden-scenario`). Exit 0 fine / 1 a real finding / 2 nothing to report.

### Fixtures
`dv_harness_tests/fixtures/benchmark_datasets/command_pattern_evidence_v{1,2}.json` —
clearly labelled synthetic corpora whose own `notes` field states they are fixtures
derived from no real project. v2 = v1's three cases plus one harder held-back case.

## 3. Governance boundaries preserved (all verified by tests)

- **No human-approval gate touched.** This module makes no `transition()`, persists no
  candidate, approves and promotes nothing.
- Records carry `produced_by = "benchmark_dataset.run_benchmark_eval"`, which is NOT in
  `capability_evolution.SHADOW_RUN_PRODUCERS` — a benchmark record is *refused* by
  `_read_pinned_run()` and can never enter a stability window or satisfy
  `assert_benchmark_measured()`. Test drives that refusal for real.
- `allow_execution_stages=False` is **hard-wired**, not a parameter: a stored corpus can
  never drive a build/regression/LSF submission. A case naming an execution-layer stage
  raises `BenchmarkEvalIsolationError` (tested with `stages: ["BUILD"]`).
- Case/run/leakage/integrity vocabularies share no token with `dv_harness.models.Status`
  (`assert_no_verification_verdict_vocabulary()` — same rule and reason as
  `capability_evolution`'s). `MATCHED` is not a DV `PASS`.
- Nothing ran against production: everything is temp-dir fixtures and local subprocesses.

## 4. Tests (24 new, all real)

Central test — `test_two_dataset_versions_produce_two_distinguishable_results`: ONE
subject, evaluated against v1 then v2 through **7 real two-arm shadow runs** (real engine
stage runner, real `command_migration_integrity_gate.py` subprocess, real arm workspaces
with real `.dv-harness` state on disk). Asserts the two results differ on **status**
(MET vs NOT_MET), **score** (3/3 vs 3/4 held out), **which case failed**, and the
**dataset content digest** each cites; and re-reads each case's `experiment.json` to
assert the IMPROVED case really went 0→1 gates satisfied across the two arms.

Also: version bump detection and naming; in-place edit → CONTENT_DRIFT; immutability;
pointless-bump and back-date refusals; register-over-drift refusal; 11 validation
refusals; leakage across versions incl. rename-does-not-launder and
rewritten-does-not-inherit; related-version use; FULLY_LEAKED → INADMISSIBLE though every
case matched; drifted corpus refuses to be evaluated; unresolvable fixture → ERRORED (not
matched) with the reason recorded; the two governance-boundary tests above; and both CLI
entry points driven as **real subprocesses** with exit codes asserted. One latent bug was found and
fixed while testing (`list_datasets()` raised IndexError on a dataset directory left behind
by an interrupted register) — committed separately with its own test.

## 5. Deliberately NOT built (deferred, stated not implied closed)

1. **Case shape is the two-arm shadow run** the reused runner measures. Pure
   prompt/response agent evals and generated-file-diff cases are unsupported — they need
   a different runner, and building one would be the parallel mechanism this project
   forbids.
2. **No `eval` CLI verb.** An eval must name the subject via a `harness_factory`;
   defaulting it would dispatch real `claude -p` subprocesses per case from a typed
   command line. Running an eval is a Python call.
3. **No stage gate**, for the reason `golden_scenario`/`power_intent` already state: a
   gate passing on a benchmark nobody reviewed would be worse than none.
4. `difficulty` / `qualification` are declared metadata; nothing judges whether a case is
   as hard as it claims.
5. No dashboard surface for eval runs (`read_eval_runs()` exists; nothing renders it).

## 6. Files

- `dv_harness/benchmark_dataset.py` (new)
- `dv_harness_tests/test_benchmark_dataset_governance.py` (new, 24 tests)
- `dv_harness_tests/fixtures/benchmark_datasets/command_pattern_evidence_v1.json` (new)
- `dv_harness_tests/fixtures/benchmark_datasets/command_pattern_evidence_v2.json` (new)
- `dv_harness/cli.py` (+49 lines — hand-scoped patch; a concurrent pass was adding
  `system-smoke-proof` to the same two hunks and its lines were excluded from my commit)
- `CLAUDE.md` (+74 lines, new "Agent Benchmark Dataset Governance (2026-09-06)" section —
  same hand-scoped treatment)
