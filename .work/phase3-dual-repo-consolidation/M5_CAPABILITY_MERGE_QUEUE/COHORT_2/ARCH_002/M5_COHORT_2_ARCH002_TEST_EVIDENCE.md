# CAP-M5-ARCH-002 -- Test Evidence

## B8's own tests, run in B8's own frozen worktree (before merge decision)

```
cd /d/wt/b8 && python -m pytest dv_harness_tests/test_soc_environment_composer.py -q
```
Result: **20 passed** (including the 3 new ARCH-03 tests). Unlike
CAP-M5-ARCH-003/CAP-M5-ARCH-001, B8 shipped real, passing test coverage
for this capability -- verified empirically rather than assumed.

## Ported tests + full existing suite (canonical, after merge)

```
python -m pytest dv_harness_tests/test_soc_environment_composer.py -q
```
Result: **20 passed** (17 pre-existing + 3 ported from B8).

## Full focused validation sweep (Section 24 -- all Cohort 2 capabilities' preservation)

```
python -m pytest \
  dv_harness_tests/test_soc_environment_composer.py \
  dv_harness_tests/test_system_level_soc_composition_wiring.py \
  dv_harness_tests/test_create_environment_verification_architecture.py \
  dv_harness_tests/test_protocol_model_layer_wiring.py \
  dv_harness_tests/test_uvm_structural_lint.py \
  dv_harness_tests/test_vip_api_card.py \
  dv_harness_tests/test_verification_architecture.py \
  dv_harness_tests/test_env_manifest_fact_sources.py \
  dv_harness_tests/test_amba_fabric_generator.py \
  dv_harness_tests/test_subsystem_maturity_gate.py \
  dv_harness_tests/test_system_level_track_b_gate_crosscheck.py -q
```
Result: **311 passed** (0:02:57) -- includes CAP-M5-ENV-001's, CAP-M5-
ARCH-003's, and CAP-M5-ARCH-001's own regression suites, all still green.

## Keyword sweep + location/root gates

```
python -m pytest dv_harness_tests/ -q -k "soc_environment_composer or root_hygiene or l5dgva_repo"
```
Result: **45 passed, 13895 deselected**.

## Constitution / Anti-Drift

```
python -c "from dv_harness.constitution_gate import check_constitution_intact; print(check_constitution_intact('.'))"
```
Result: `ConstitutionCheckResult(status='PASS', reasons=[])`

## System virtual sequencer preservation (Section 18)

`system_virtual_sequencer.py` itself not modified this wave -- no
dedicated re-run needed beyond the above (which already exercises its
`build_subsystem_composition()` real call path through the 2 new ARCH-03
positive-case tests).

## Source integrity (re-verified after the merge, before commit)

Parent `3e9dd7360f584078ed8f4b04120c9844acabd97b` -- UNCHANGED
v50 `f3fd17326cf3654aca6fd83fad991a3f247e6682` -- UNCHANGED
B7A `7b2a65a4dc2d40d493451b409669c90ed0b3d9a5` -- UNCHANGED
B7B `c7c7fa09e9ee8336ba102b4495f4b8808408fe0b` -- UNCHANGED
B8 `c9cdd06ce586d44f4c0cef00310c10f95ea59f93` -- UNCHANGED

```
REGRESSION_CAUSED_BY_CAP_M5_ARCH_002 = 0
UNKNOWN_REGRESSION_FAILURES = 0
SOURCE_CAPABILITY_LOSS = 0
CANONICAL_PREVIOUS_BEHAVIOR_LOSS = 0
PARENT_VERIFIED_BEHAVIOR_LOSS = 0 (top-TB feature deferred, not lost --
  registered as a migration input for a future wave)
B8_VERIFIED_BEHAVIOR_LOSS = 0
V50_VERIFIED_BEHAVIOR_LOSS = 0 (no relevant v50-only behavior found)
CONSTITUTION_GATE = PASS
```
