# CAP-M5-ARCH-001 -- Test Evidence

## Schema-violation empirical proof (before deciding the merge strategy)

```python
doc = assemble_verification_architecture()
payload = {k: v for k, v in doc.items() if k != '_irs'}
payload['status'] = 'ASSEMBLED'
validate_verification_architecture(payload)
```
Result: `VerificationArchitectureValidationError: ... Additional properties
are not allowed ('status' was unexpected)` -- confirms B8's own synthetic
key would break schema compliance. Not merged.

## New tests (this wave; B8 shipped none)

```
python -m pytest dv_harness_tests/test_create_environment_verification_architecture.py -q
```
Result: **6 passed**.

## Existing direct-caller regression (must stay byte-identical)

```
python -m pytest \
  dv_harness_tests/test_protocol_model_layer_wiring.py \
  dv_harness_tests/test_system_level_soc_composition_wiring.py \
  dv_harness_tests/test_uvm_structural_lint.py \
  dv_harness_tests/test_vip_api_card.py -q
```
Result: **102 passed**.

## Full focused sweep (new + existing create_environment callers + VA module + CAP-M5-ENV-001/ARCH-003 preservation)

```
python -m pytest \
  dv_harness_tests/test_create_environment_verification_architecture.py \
  dv_harness_tests/test_protocol_model_layer_wiring.py \
  dv_harness_tests/test_system_level_soc_composition_wiring.py \
  dv_harness_tests/test_uvm_structural_lint.py \
  dv_harness_tests/test_vip_api_card.py \
  dv_harness_tests/test_verification_architecture.py \
  dv_harness_tests/test_subsystem_maturity_gate.py \
  dv_harness_tests/test_system_level_track_b_gate_crosscheck.py \
  dv_harness_tests/test_env_manifest_fact_sources.py \
  dv_harness_tests/test_amba_fabric_generator.py -q
```
Result: **291 passed** (includes CAP-M5-ENV-001's `test_env_manifest_fact_
sources.py` and CAP-M5-ARCH-003's `test_amba_fabric_generator.py` --
both still green, confirming Cohort 1/2-so-far are preserved).

## Full-suite keyword sweep

```
python -m pytest dv_harness_tests/ -q -k "create_environment"
```
Result: **19 passed, 13918 deselected**.

## Location/root gates

```
python -m pytest dv_harness_tests/ -q -k "root_hygiene or l5dgva_repo or execution_profile"
```
Result: **45 passed, 13892 deselected**.

## DE/DV HITL governance tests

No code-level test exists to run -- the DE/DV Role-Based HITL roadmap
(commit `9d76dd1`) is explicitly roadmap/governance-only, zero engines or
gates implemented. Compatibility verified by design review (Section 8 of
`M5_COHORT_2_ARCH001_SEMANTIC_MERGE_PLAN.md`), not by a test run, since no
test exists to run. Disclosed rather than fabricated.

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
REGRESSION_CAUSED_BY_CAP_M5_ARCH_001 = 0
UNKNOWN_REGRESSION_FAILURES = 0
SOURCE_CAPABILITY_LOSS = 0
CANONICAL_PREVIOUS_BEHAVIOR_LOSS = 0
PARENT_VERIFIED_BEHAVIOR_LOSS = 0
V50_VERIFIED_BEHAVIOR_LOSS = 0
B8_VERIFIED_BEHAVIOR_LOSS = 0
CONSTITUTION_GATE = PASS
```
