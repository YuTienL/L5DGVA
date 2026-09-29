# M5 Pool Closure — Batch 2 — Test Evidence

## Test-first discipline applied

Every one of the 8 Parent test files was read IN FULL before its production
module was migrated or its own test file was ported, to determine whether
any test needed adaptation for canonical's real (sometimes different)
evidence. Two of the 8 needed a change:

- `test_eight_engine_runtime_proof_matrix.py` — read first; confirmed none
  of its 13 tests assert on the 3 memory-promotion signals this batch's
  adaptation drops, so it ported with **zero code changes**.
- `test_eight_engine_telemetry_rollup.py` — one docstring comment corrected
  ("5-Level Memory Engine has 8 distinct signal names" → 5); the 3 signal
  names the test actually asserts on (`EXPERIENCE_KNOWLEDGE_PROMOTED`,
  `VERIFIED_FIX_PROMOTED`, `PROJECT_TOPOLOGY_PROMOTED`) are all in
  canonical's retained 5, so **no assertion changed**.
- The remaining 6 test files ported **byte-for-byte verbatim**.

## Parent's own pre-migration regression (trust-but-verify, before any canonical trust)

All 8 Parent test suites run together, in Parent's own frozen worktree,
before any of the 8 modules were trusted:

```
python -m pytest dv_harness_tests/test_l5dgva_gap_queue.py
  dv_harness_tests/test_eight_engine_runtime_proof_matrix.py
  dv_harness_tests/test_l5dgva_workitem_projection.py
  dv_harness_tests/test_engine_maturity_state.py
  dv_harness_tests/test_eight_engine_telemetry_rollup.py
  dv_harness_tests/test_l5dgva_directive_registry.py
  dv_harness_tests/test_l5dgva_directive_blackboard_work_queue.py
  dv_harness_tests/test_l5dgva_kc_extraction.py -q
=> 107 passed
```

## Canonical per-module regression (after each dependency-ordered commit)

| Module | Test file | Result | Commit |
|---|---|---|---|
| `l5dgva_gap_queue.py` | `test_l5dgva_gap_queue.py` | 11/11 pass | `a55735a` |
| `l5dgva_workitem_projection.py` | `test_l5dgva_workitem_projection.py` | 13/13 pass | `a55735a` |
| `l5dgva_directive_registry.py` | `test_l5dgva_directive_registry.py` | 21/21 pass | `a55735a` |
| (chain B combined) | all 3 above together | 45/45 pass | `a55735a` |
| `eight_engine_runtime_proof_matrix.py` | `test_eight_engine_runtime_proof_matrix.py` | 13/13 pass | `f4f165a` |
| `engine_maturity_state.py` | `test_engine_maturity_state.py` | 12/12 pass | `ec27675` |
| `eight_engine_telemetry_rollup.py` | `test_eight_engine_telemetry_rollup.py` | 11/11 pass | `ec27675` |
| (CAP-POOL-001/011 + chain A combined) | all 3 above together | 34/34 pass | `ec27675` |
| `l5dgva_directive_blackboard_work_queue.py` | `test_l5dgva_directive_blackboard_work_queue.py` | 9/9 pass | `303a58d` |
| (CAP-POOL-003 + chain B preservation) | chain B + this module together | 54/54 pass | `303a58d` |
| `l5dgva_kc_extraction.py` | `test_l5dgva_kc_extraction.py` | 19/19 pass | `dd6b90d` |

## Full Batch-2 regression (all 8 migrated modules' test suites together, final state)

```
python -m pytest
  dv_harness_tests/test_l5dgva_gap_queue.py
  dv_harness_tests/test_l5dgva_workitem_projection.py
  dv_harness_tests/test_l5dgva_directive_registry.py
  dv_harness_tests/test_eight_engine_runtime_proof_matrix.py
  dv_harness_tests/test_engine_maturity_state.py
  dv_harness_tests/test_eight_engine_telemetry_rollup.py
  dv_harness_tests/test_l5dgva_directive_blackboard_work_queue.py
  dv_harness_tests/test_l5dgva_kc_extraction.py -q
=> 107 passed
```

107/107 — the same count as Parent's own pre-migration 8-suite regression,
a strong behavioral-equivalence signal (same number of real assertions
surviving the adaptation, not merely "no crash").

## Constitution/Anti-Drift

`dv_harness.constitution_gate.check_constitution_intact('.')` run after
every one of this batch's 5 commits: `ConstitutionCheckResult(status='PASS', reasons=[])`
every time, 0 reasons.

## Preservation regression (Batch 1's own closed capabilities, not regressed)

`CAP-POOL-008`/`CAP-POOL-012`'s own test files
(`test_l5dgva_v5_ss84_phase_entry_protocol_schema.py`,
`test_rtl_filelist_parser.py`) were not touched by this batch and share no
import with any of the 8 modules this batch migrated (independently
confirmed via `M5_POOL_CLOSURE_CAPABILITY_MAP.csv`'s own dependency list —
neither depends on `l5dgva_gap_queue.py`, `eight_engine_runtime_proof_matrix.py`,
or any other Batch-2 module); no regression risk to re-run against this
batch specifically beyond the full-suite run below.

## Full canonical test suite

A full `dv_harness_tests/` run was launched to catch any indirect
regression beyond this batch's own direct test files. See
`M5_POOL_BATCH2_FINAL_REPORT.md`'s `FULL_SUITE_REGRESSION` field for the
result recorded at report time.
