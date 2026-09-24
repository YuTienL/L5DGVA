# M6-TASK-BOUNDARY-PRODUCTION-001 -- Production Path Proof

Every claim below is backed by a real, named, passing test in
`dv_harness_tests/test_m6_task_boundary_production_001.py`, run against a
real git repo (never a mock), through the real `start_lifecycle()`/
`create_environment()` entry points.

## Ordering (dispatch section 13): Task Boundary before VerificationLevel

Confirmed by direct source read of `engine.py`'s `start_lifecycle()`: the
`if task_boundary is not None:` block (the check) runs strictly BEFORE the
`if generation_request is not None:` block that computes `effective_level`
and calls `create_environment()` (VerificationLevel ROUTING happens only
inside `create_environment()`, via `environment_mode_router.
resolve_environment_mode()`). This ordering was already correct before this
task -- this task did not need to (and did not) reorder anything, only add
production entry points to the already-correctly-ordered check. Proven by
`test_task_boundary_violation_blocks_generation_before_verification_level_
routing`: protocol/role/level all resolve cleanly, yet a rejected boundary
still blocks before `create_environment()` ever runs.

## CLI production path

```
CLI_TASK_BOUNDARY_PATH = CONNECTED
```

- PASS: `test_cli_task_boundary_flags_propagate_a_real_taskboundary_into_
  start_lifecycle` -- real argv (`--task-boundary-id/-allow`), a real git
  repo, `TaskBoundary.from_dict()`'s real output asserted directly on the
  object `start_lifecycle()` actually received, and real generated files
  on disk afterward.
- FAIL: `test_cli_task_boundary_violation_blocks_generation_and_exits_1` --
  a real forbidden-file working-tree change, exit code 1, no `out_dir`
  ever created.
- Regression: `test_cli_omitting_all_task_boundary_flags_is_byte_identical_
  to_before` -- `task_boundary=None` when none of the 4 flags are given,
  proving zero behavior change for every pre-existing CLI caller.

## Dashboard production path

```
DASHBOARD_TASK_BOUNDARY_PATH = CONNECTED
```

Same convergence discipline `CAP-M6-C1-001`/GAP-V2-002/`CAP-M5M6-VLEVEL-001`
already established: `_start_background_run()` is the real function
`_handle_start()`'s own POST `/api/start` handler calls with an
already-JSON-parsed body -- the same evidence bar those three prior tasks'
own dashboard tests already used for `protocol`/`role`/`level`.

- PASS: `test_dashboard_task_boundary_pass_reaches_generation`.
- FAIL: `test_dashboard_task_boundary_violation_blocks_generation`.
- JSON-shape conversion: `test_dashboard_handle_start_json_body_shape_
  converts_via_taskboundary_from_dict` -- the exact dict shape
  `_handle_start()`'s own source now reads (`body.get("task_boundary")`)
  round-trips through `TaskBoundary.from_dict()` (CAP-ATL-004, reused
  verbatim) into an identical object.
- Regression: `test_dashboard_omitting_task_boundary_json_field_is_byte_
  identical_to_before`.

## Protocol Builder path

```
PROTOCOL_BUILDER_TASK_BOUNDARY_PATH = CONNECTED
```

`test_protocol_builder_invocation_shape_reaches_task_boundary_and_
generation` uses the EXACT CLI invocation shape all 11
`.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` already use (per GAP-V2-002:
`--protocols`/`--dut-role`/`--level`/`--generate`/`--generate-out`/
`--generate-manifest`), with the new `--task-boundary-*` flags added --
proving the SAME governed entry point every skill already converges on can
reach Task Boundary, without modifying any SKILL.md file (Task Boundary is
optional by design; no skill needs to declare one to keep generating). The
GAP-V2-002 13-caller governance closure itself is re-confirmed unregressed
by `test_gap_v2_002_protocol_builder_convergence.py` (unchanged, still
passing) in the same regression run.

## The 3 levels, each re-proven WITH Task Boundary in the loop

```
IP_PATH           = PRODUCTION_CONNECTED
SUBSYSTEM_PATH    = PRODUCTION_CONNECTED
SYSTEM_LEVEL_PATH = PRODUCTION_CONNECTED
```

Six tests, one PASS + one FAIL per level, all through the real
`start_lifecycle()` -> `create_environment()` entry point:
`test_ip_level_with_task_boundary_pass` /
`test_ip_level_with_task_boundary_fail_blocks_generation`;
`test_subsystem_level_with_task_boundary_pass` /
`test_subsystem_level_with_task_boundary_fail_blocks_generation`;
`test_system_level_with_task_boundary_pass` (real registered USB+PCIe
subsystems, via `engine.py`'s own real `_persist_subsystem_registry_entry()`
writer, same fixture discipline `test_system_level_soc_composition_
wiring.py`/`test_m5m6_vlevel_001_production_connectivity.py` already
established) / `test_system_level_with_task_boundary_fail_blocks_
generation`.

## Bypass classification (dispatch section 12)

```
UNCONTROLLED_BYPASSES = 0
```

| Path | Classification | Evidence |
|---|---|---|
| `start --advanced` | AUTHORIZED_LOW_LEVEL_BYPASS (pre-existing, `CAP-M6-DISPATCH-001`) | `test_advanced_bypass_also_skips_a_declared_task_boundary` -- a declared boundary is ignored under `--advanced`, exactly like every other governed field; recorded as a real `LIFECYCLE_BYPASS` event, same as before |
| `task_boundary=None` (no flags/JSON field given) | Documented default, not a bypass | CAP-ATL-004's own design: "never derived"; proven byte-identical by the two "omitting..." regression tests above |
| Direct `create_environment()` call (`tools/generate_protocol_uvm_environment.py`) | INTERNAL_GENERATION_PRIMITIVE (GAP-V2-002 disposition, unchanged) | never went through `start_lifecycle()` in the first place -- Task Boundary was never claimed to cover this primitive; unchanged by this task |
| Test-only direct calls to `task_boundary_conformance.*` | TEST_ONLY | `test_task_boundary_conformance.py`, this file's own `A0` section -- exercise the module directly by design, never a production path |

No new bypass was created for this task's own convenience.
