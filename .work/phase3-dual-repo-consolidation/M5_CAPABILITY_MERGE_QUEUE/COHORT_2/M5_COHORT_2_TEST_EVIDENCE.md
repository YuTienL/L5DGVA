# M5 Cohort 2 -- Test Evidence

## B8 defect reproduction (before any canonical change)

```
cd /d/wt/b8 && python -m pytest dv_harness_tests/test_amba_fabric_generator.py -q
```
Result: **4 failed, 11 passed**. All 4 failures:
`TypeError: AMBAFabricGenerator.env() takes 3 positional arguments but 4 were given`
at `dv_harness/uvm_generator/amba_fabric_generator.py:295` (B8's own line
number). This is B8's own, unmodified source -- never touched by this
wave -- run read-only to obtain real runtime evidence of the defect
before deciding the merge strategy.

## Focused tests after the Cohort-2 merge (canonical, this wave)

```
python -m pytest dv_harness_tests/test_amba_fabric_generator.py -q
```
Result: **20 passed** (15 pre-existing + 5 new this wave).

```
python -m pytest dv_harness_tests/test_amba_fabric_analysis.py \
  dv_harness_tests/test_amba_port_registry.py \
  dv_harness_tests/test_amba_route_transform_predictor.py -q
```
Result: **192 passed**.

```
python -m pytest dv_harness_tests/ -q -k \
  "amba_fabric or amba_port or address_map_integrity or system_resource_inventory"
```
Result: **262 passed, 13669 deselected**.

## Constitution / Anti-Drift

```
python -c "from dv_harness.constitution_gate import check_constitution_intact; \
print(check_constitution_intact('.'))"
```
Result: `ConstitutionCheckResult(status='PASS', reasons=[])`

## Source integrity (re-verified after the merge, before commit)

Parent `3e9dd7360f584078ed8f4b04120c9844acabd97b` -- UNCHANGED
v50 `f3fd17326cf3654aca6fd83fad991a3f247e6682` -- UNCHANGED
B7A `7b2a65a4dc2d40d493451b409669c90ed0b3d9a5` -- UNCHANGED
B7B `c7c7fa09e9ee8336ba102b4495f4b8808408fe0b` -- UNCHANGED
B8 `c9cdd06ce586d44f4c0cef00310c10f95ea59f93` -- UNCHANGED

REGRESSION_CAUSED_BY_M5_COHORT_2 = 0
UNKNOWN_REGRESSION_FAILURES = 0
SOURCE_CAPABILITY_LOSS = 0
MANDATORY_UNKNOWN = 0
