# M5 Cohort 5 — Test Evidence

## Step 0 — Parent-side re-verification (before trusting either module)

```
cd D:/DV/Task/DV_Agent_Harness_L5
python -m pytest dv_harness_tests/test_functional_coverage_signoff.py dv_harness_tests/test_functional_coverage_signoff_false_pass_replay.py -q
```
Result: **17 passed**.

```
python -m pytest dv_harness_tests/test_coverage_analysis.py -k "classify_coverage_kind or code_coverage" -q
```
Result: **14 passed, 45 deselected**.

## Step 1 — migrated canonical modules, focused suites

```
cd D:/DV/Task/L5_DGVA
python -m pytest dv_harness_tests/test_coverage_analysis.py dv_harness_tests/test_functional_coverage_signoff.py dv_harness_tests/test_functional_coverage_signoff_false_pass_replay.py -q
```
Result: **76 passed**.

## Step 2 — real-caller regression (CAP-M5-COV-001)

```
python -m pytest dv_harness_tests/test_exec_eng_dashboard.py dv_harness_tests/test_gui_vip_coverage_wizard.py dv_harness_tests/test_signoff_blocker_list.py dv_harness_tests/test_spec_vplan_readiness_gate.py dv_harness_tests/test_question_queue.py -q
```
Result: **293 passed** — the 3 real production callers
(`exec_eng_dashboard.py`, `gui_vip_coverage_wizard.py`,
`signoff_blocker_list.py`) plus 2 related suites, zero regressions.

## Step 3 — DSI-001 existing-health re-confirmation (no code changed)

```
python -m pytest dv_harness_tests/test_design_source_inventory.py dv_harness_tests/test_contextual_source_precedence.py -q
```
Result: **58 passed** — confirms canonical's superseding capability is
itself healthy and unaffected by this Cohort's (absence of) changes.

## Step 4 — Constitution/Anti-Drift gate

```
python -c "from dv_harness import constitution_gate; print(constitution_gate.check_constitution_intact('.'))"
```
Result: `ConstitutionCheckResult(status='PASS', reasons=[])`.

## Step 5 — Cohort 1-4 preservation regression

```
python -m pytest dv_harness_tests/test_env_manifest_fact_sources.py dv_harness_tests/test_amba_fabric_generator.py dv_harness_tests/test_create_environment_verification_architecture.py dv_harness_tests/test_soc_environment_composer.py dv_harness_tests/test_reference_uvm_dut_top_integration_manifest.py dv_harness_tests/test_vip_capability_extraction.py dv_harness_tests/test_task_boundary_conformance.py dv_harness_tests/test_intake_field_resolution.py -q
```
Result: **169 passed** — no cross-cohort regression from this Cohort's
own changes.

## Step 6 — Master Capability Matrix structural validation

```python
import csv
with open(".../MASTER_CAPABILITY_STATUS_MATRIX.csv", encoding="utf-8") as f:
    rows = list(csv.reader(f))
header_len = len(rows[0])
malformed = [(r[0], len(r)) for r in rows[1:] if len(r) != header_len]
ids = [r[0] for r in rows[1:]]
dupes = {i for i in ids if ids.count(i) > 1}
```
Result (post-Cohort-5-update, see `M5_COHORT_5_FINAL_REPORT.md` for the
exact row count): `MASTER_CAPABILITY_MATRIX_MALFORMED_ROWS = 0`,
`MASTER_CAPABILITY_MATRIX_DUPLICATE_IDS = 0`.

## Step 7 — source integrity re-check (all 5 frozen sources, before and after)

| Source | HEAD | Verdict |
|---|---|---|
| Parent | `3e9dd736...` | UNCHANGED |
| v50 | `f3fd1732...` | UNCHANGED |
| B7A | `7b2a65a4...` | UNCHANGED |
| B7B | `c7c7fa09...` | UNCHANGED |
| B8 | `c9cdd06c...` | UNCHANGED |

`REFERENCE_USB_ENV_CONSUMED = NO` throughout.

## Summary

`REGRESSION_CAUSED_BY_M5_COHORT_5 = 0`. `UNKNOWN_REGRESSION_FAILURES = 0`.
Total this Cohort's own regression evidence across all steps: **627
individual test results, 0 failures** (17+14 Parent re-runs + 76
canonical migrated + 293 real-caller regression + 58 DSI-001 health
re-confirmation + 169 Cohort 1-4 preservation).
