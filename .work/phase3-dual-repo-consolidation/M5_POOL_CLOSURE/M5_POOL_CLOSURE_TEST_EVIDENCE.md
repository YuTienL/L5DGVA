# M5 Pool Closure — Test Evidence

## Step 0 — Parent-side re-verification (CAP-POOL-008 only; CAP-POOL-012 has no test anywhere)

```
cd D:/DV/Task/DV_Agent_Harness_L5
python -m pytest dv_harness_tests/test_l5dgva_v5_ss84_phase_entry_protocol_schema.py -q
```
Result: **9 passed**.

## Step 1 — canonical-specific STAGE_GATES re-derivation (CAP-POOL-008)

```
cd D:/DV/Task/L5_DGVA
python -c "
from dv_harness import l5dgva_v5_ss84_phase_entry_protocol_schema as m
cov = m.stage_gates_phase_name_coverage()
matched = sum(1 for c in cov.values() if c.status == m.MATCHED)
not_matched = sum(1 for c in cov.values() if c.status == m.NOT_MATCHED)
print('matched=', matched, 'not_matched=', not_matched)
"
```
Result: `matched= 12 not_matched= 3` — identical to Parent's own cited
finding despite canonical's smaller `STAGE_GATES` registry.

## Step 2 — migrated canonical modules, focused suites

```
python -m pytest dv_harness_tests/test_l5dgva_v5_ss84_phase_entry_protocol_schema.py -v
```
Result: **9 passed**.

```
python -m pytest dv_harness_tests/test_rtl_filelist_parser.py -v
```
Result: **28 passed** (brand-new suite, derived from documented behavior,
0 failures on first run).

## Step 3 — caller sweep (both new modules)

```
grep -rln "l5dgva_v5_ss84_phase_entry_protocol_schema\|rtl_filelist_parser" dv_harness dv_harness_tests tools .claude --include="*.py" --include="*.md"
```
Result: each new module name appears only in its own source file and its
own test file — `UNKNOWN_RUNTIME_CALLERS = 0` for both.

## Step 4 — Constitution/Anti-Drift gate

```
python -c "from dv_harness import constitution_gate; print(constitution_gate.check_constitution_intact('.'))"
```
Result: `ConstitutionCheckResult(status='PASS', reasons=[])`.

## Step 5 — Cohort 1-5 + M5.9 preservation regression

```
python -m pytest dv_harness_tests/test_env_manifest_fact_sources.py dv_harness_tests/test_amba_fabric_generator.py dv_harness_tests/test_create_environment_verification_architecture.py dv_harness_tests/test_soc_environment_composer.py dv_harness_tests/test_reference_uvm_dut_top_integration_manifest.py dv_harness_tests/test_vip_capability_extraction.py dv_harness_tests/test_task_boundary_conformance.py dv_harness_tests/test_intake_field_resolution.py dv_harness_tests/test_coverage_analysis.py dv_harness_tests/test_functional_coverage_signoff.py dv_harness_tests/test_functional_coverage_signoff_false_pass_replay.py dv_harness_tests/test_design_source_inventory.py dv_harness_tests/test_contextual_source_precedence.py -q
```
Result: **303 passed** — no cross-capability regression from this task's
two new modules.

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
Result (post-this-task, see `M5_POOL_CLOSURE_FINAL_REPORT.md` for the
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

`REGRESSION_CAUSED_BY_POOL_CLOSURE = 0`. `UNKNOWN_REGRESSION_FAILURES =
0`. Total this task's own regression evidence across all steps: **349
individual test results, 0 failures** (9 Parent re-run + 9+28 canonical
migrated + 303 Cohort 1-5 preservation).
