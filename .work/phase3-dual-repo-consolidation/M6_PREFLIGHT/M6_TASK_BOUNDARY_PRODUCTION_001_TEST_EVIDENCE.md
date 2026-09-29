# M6-TASK-BOUNDARY-PRODUCTION-001 -- Test Evidence

## New/extended test files

- `dv_harness_tests/test_m6_task_boundary_production_001.py` (new): 22/22
  pass. Sections A0 (`exempt_path_prefixes` unit tests, 4), A (core
  mechanism PASS/FAIL against real git evidence, 3), B (CLI production
  path, 3), C (dashboard production path, 4), D (Protocol Builder
  invocation shape, 1), E (all 3 levels re-proven with Task Boundary, 6
  -- PASS+FAIL per level), F (bypass classification, 1).
- `dv_harness/task_boundary_conformance.py`: `exempt_path_prefixes=`
  parameter added to `check_working_tree_conformance()`/`check_committed_
  range_conformance()`; module docstring's stale "NOT wired into cli.py"
  claim corrected.

## Regression: real caller-population sweep

Freshly derived via `grep -rl "task_boundary_conformance|TaskBoundary"
dv_harness_tests/*.py`, UNIONED with `CAP-M5M6-VLEVEL-001`'s own real
caller-population set (since this task re-touches `engine.py`/`cli.py`/
`dashboard.py`) plus this task's own new test file -- 29 files total:

```
dv_harness_tests/test_clarification_service.py
dv_harness_tests/test_create_environment_verification_architecture.py
dv_harness_tests/test_dashboard_interactive.py
dv_harness_tests/test_dashboard_subsystem_system_verification_center.py
dv_harness_tests/test_environment_mode_router.py
dv_harness_tests/test_gap_v2_002_protocol_builder_convergence.py
dv_harness_tests/test_generation_readiness.py
dv_harness_tests/test_global_status_ready_gate.py
dv_harness_tests/test_gui_intake_wizard.py
dv_harness_tests/test_lifecycle.py
dv_harness_tests/test_m5m6_vlevel_001_production_connectivity.py
dv_harness_tests/test_m6_c1_golden_path_connectivity.py
dv_harness_tests/test_m6_task_boundary_production_001.py
dv_harness_tests/test_protocol_and_environment_mode_engine_wiring.py
dv_harness_tests/test_protocol_model_layer_wiring.py
dv_harness_tests/test_signoff_stage_gate_e2e.py
dv_harness_tests/test_start_lifecycle_dispatch.py
dv_harness_tests/test_subsystem_contract.py
dv_harness_tests/test_subsystem_discovery.py
dv_harness_tests/test_subsystem_maturity_gate.py
dv_harness_tests/test_system_level_soc_composition_wiring.py
dv_harness_tests/test_system_level_track_b_gate_crosscheck.py
dv_harness_tests/test_task_boundary_conformance.py
dv_harness_tests/test_uvm_structural_lint.py
dv_harness_tests/test_verification_level.py
dv_harness_tests/test_verification_strategy.py
dv_harness_tests/test_vip_api_card.py
dv_harness_tests/test_vip_version_drift_detection.py
dv_harness_tests/test_web_control_plane_readiness_gate.py
```

```
python -m pytest <29 files above> -q
690 passed in 440.73s (0:07:20)
```

**REGRESSION_CAUSED_BY_TASK_BOUNDARY = 0. UNKNOWN_REGRESSION_FAILURES = 0.**
Zero failures across the entire run -- every one of `test_task_boundary_
conformance.py`'s pre-existing 19 tests, `test_start_lifecycle_dispatch.py`'s
pre-existing Task Boundary tests, and every VLEVEL-era test remained green
after both the CLI/dashboard wiring and the `exempt_path_prefixes` fix.

## Constitution gate

```
ConstitutionCheckResult(status='PASS', reasons=[])
```

## Frozen reference sources (re-verified unchanged immediately before commit)

```
Parent = 3e9dd7360f584078ed8f4b04120c9844acabd97b
v50    = f3fd17326cf3654aca6fd83fad991a3f247e6682
b7a    = 7b2a65a4dc2d40d493451b409669c90ed0b3d9a5
b7b    = c7c7fa09e9ee8336ba102b4495f4b8808408fe0b
b8     = c9cdd06ce586d44f4c0cef00310c10f95ea59f93
```
