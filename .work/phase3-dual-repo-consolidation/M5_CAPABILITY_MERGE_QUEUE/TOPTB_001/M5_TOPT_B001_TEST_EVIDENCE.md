# CAP-M5-TOPTB-001 -- Test Evidence

## Parent's own tests, run in Parent's own tree (before migration decision)

```
cd /d/DV/Task/DV_Agent_Harness_L5 && python -m pytest \
  dv_harness_tests/test_reference_uvm_dut_top_integration_manifest.py \
  dv_harness_tests/test_soc_environment_composer.py -q
```
Result: **37 passed**. Real evidence, not assumed from the commit message
alone.

## Migrated + ported tests (canonical, after merge)

```
python -m pytest \
  dv_harness_tests/test_soc_environment_composer.py \
  dv_harness_tests/test_reference_uvm_dut_top_integration_manifest.py -q
```
Result: **40 passed** (20 pre-existing composer tests [17 original + 3
CAP-M5-ARCH-002] + 6 new top-TB tests + 14 migrated discovery-module
tests).

## Full caller-regression sweep (Section 18)

```
python -m pytest \
  dv_harness_tests/test_soc_environment_composer.py \
  dv_harness_tests/test_reference_uvm_dut_top_integration_manifest.py \
  dv_harness_tests/test_system_level_soc_composition_wiring.py \
  dv_harness_tests/test_create_environment_verification_architecture.py \
  dv_harness_tests/test_protocol_model_layer_wiring.py \
  dv_harness_tests/test_engine_gates_and_routing.py \
  dv_harness_tests/test_signoff_stage_gate_e2e.py -q
```
Result: **334 passed** (0:05:57) -- covers canonical's own engine.py
gate/routing suite and the full signoff-stage E2E suite, both real
production callers' own regression coverage, not merely Parent's claim
that they were compatible.

## Constitution / Anti-Drift

```
python -c "from dv_harness.constitution_gate import check_constitution_intact; print(check_constitution_intact('.'))"
```
Result: `ConstitutionCheckResult(status='PASS', reasons=[])`

## Source integrity (re-verified after the merge, before commit)

Parent `3e9dd7360f584078ed8f4b04120c9844acabd97b` -- UNCHANGED
v50 `f3fd17326cf3654aca6fd83fad991a3f247e6682` -- UNCHANGED
B7A `7b2a65a4dc2d40d493451b409669c90ed0b3d9a5` -- UNCHANGED
B7B `c7c7fa09e9ee8336ba102b4495f4b8808408fe0b` -- UNCHANGED
B8 `c9cdd06ce586d44f4c0cef00310c10f95ea59f93` -- UNCHANGED

```
UNKNOWN_REGRESSION_FAILURES = 0
SOURCE_CAPABILITY_LOSS = 0 (CAP-M5-ARCH-002's own ARCH-03 wire re-verified
  intact throughout -- test_soc_environment_composer.py's 3 ARCH-03 tests
  still pass, confirming zero conflict with this wave's own changes)
CONSTITUTION_GATE = PASS
```
