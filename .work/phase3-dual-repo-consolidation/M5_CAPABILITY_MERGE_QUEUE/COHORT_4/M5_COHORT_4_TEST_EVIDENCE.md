# M5 Cohort 4 — Test Evidence

## Step 0 — corrected Parent-side evidence (re-run properly scoped, not the earlier unscoped/timed-out background grep)

```
cd D:/DV/Task/DV_Agent_Harness_L5
python -m pytest dv_harness_tests/test_task_boundary_conformance.py -v
```
Result: **19 passed**.

```
python -m pytest dv_harness_tests/test_intake_field_resolution.py -q
```
Result: **24 passed**.

Both re-runs performed BEFORE trusting either Parent module, per the
B8-defect-lesson discipline established across Cohorts 2/3 (never trust a
source's claim merely because it is an "approved" input).

## Step 1 — migrated canonical modules, focused suites

```
cd D:/DV/Task/L5_DGVA
python -m pytest dv_harness_tests/test_task_boundary_conformance.py -v
```
Result: **19 passed** — identical test names, identical pass count to Parent.

```
python -m pytest dv_harness_tests/test_intake_field_resolution.py -v
```
Result: **25 passed** (24 ported from Parent + 1 new canonical-specific
test verifying the `KNOWN_TECHNICAL_GAPS`/`CLOSED_TECHNICAL_GAPS`
re-classification).

## Step 2 — existing canonical intake-system regression (confirm no interference with the parallel, unreconciled `intake_state.py` model)

```
python -m pytest dv_harness_tests/test_intake_state.py dv_harness_tests/test_verification_intake_contract.py dv_harness_tests/test_intake_audit_provenance.py -q
```
Result: **89 passed** — canonical's existing intake-field system is
completely unaffected (as expected: no shared code path, no import from
either side).

## Step 3 — dependency regression (the two canonical modules this Cohort reuses)

```
python -m pytest dv_harness_tests/test_source_authority.py dv_harness_tests/test_source_authority_order_validation.py dv_harness_tests/test_question_queue.py -q
```
Result: **274 passed** — `source_authority.py`/`question_queue.py`
themselves unmodified and unaffected.

## Step 4 — Cohort 1/2/3/TOPTB-001 preservation regression

```
python -m pytest dv_harness_tests/test_env_manifest_fact_sources.py dv_harness_tests/test_amba_fabric_generator.py dv_harness_tests/test_create_environment_verification_architecture.py dv_harness_tests/test_soc_environment_composer.py dv_harness_tests/test_reference_uvm_dut_top_integration_manifest.py dv_harness_tests/test_vip_capability_extraction.py -q
```
Result: **125 passed** — no cross-cohort regression from this Cohort's
two new modules.

## Step 5 — Constitution/Anti-Drift gate

```
python -c "from dv_harness import constitution_gate; print(constitution_gate.check_constitution_intact('.'))"
```
Result: `ConstitutionCheckResult(status='PASS', reasons=[])`.

## Step 6 — Master Capability Matrix structural validation (instruction items 11-13)

```python
import csv
with open(".../MASTER_CAPABILITY_STATUS_MATRIX.csv", encoding="utf-8") as f:
    rows = list(csv.reader(f))
header_len = len(rows[0])
malformed = [(r[0], len(r)) for r in rows[1:] if len(r) != header_len]
ids = [r[0] for r in rows[1:]]
dupes = {i for i in ids if ids.count(i) > 1}
```
Result (post-Cohort-4-update, see `M5_COHORT_4_FINAL_REPORT.md` for the
exact row count): `MASTER_CAPABILITY_MATRIX_MALFORMED_ROWS = 0`,
`MASTER_CAPABILITY_MATRIX_DUPLICATE_IDS = 0` — including a re-check that
`CAP-M5-VIP-001`/`CAP-M5-ARCH-001`/`CAP-M5-ARCH-003` (corrected during the
M14 roadmap task for an unquoted-comma defect) remain well-formed and were
not regressed by this Cohort's own appends.

## Step 7 — source integrity re-check (all 5 frozen sources, before and after)

| Source | HEAD | Verdict |
|---|---|---|
| Parent | `3e9dd736...` | UNCHANGED |
| v50 | `f3fd1732...` | UNCHANGED |
| B7A | `7b2a65a4...` | UNCHANGED |
| B7B | `c7c7fa09...` | UNCHANGED |
| B8 | `c9cdd06c...` | UNCHANGED |

No `Edit`/`Write` tool call in this Cohort targeted any path outside
`D:/DV/Task/L5_DGVA`. `REFERENCE_USB_ENV_CONSUMED = NO` throughout.

## Summary

`REGRESSION_CAUSED_BY_M5_COHORT_4 = 0`. `UNKNOWN_REGRESSION_FAILURES = 0`.
Total this Cohort's own regression evidence across all steps: **555
individual test results, 0 failures** (19+24 Parent re-runs + 19+25
canonical migrated + 89 existing-intake-system + 274 dependency + 125
cross-cohort preservation).
