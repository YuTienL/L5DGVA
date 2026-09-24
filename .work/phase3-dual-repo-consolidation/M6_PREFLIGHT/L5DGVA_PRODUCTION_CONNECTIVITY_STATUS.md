# L5DGVA Production Connectivity Status

Tracks `STRUCTURAL_CONNECTED_STAGES` and `PRODUCTION_CONNECTED_STAGES`
separately, per V2's own P2/structural-vs-production distinction.
Production-connected requires real supported user/project data flowing
through the capability, from a real supported entry point, with output
consumed by the required next stage — unit/mock/internal-helper
connectivity does not qualify.

## M6 Operational Slice — both metrics

```
M6_VERTICAL_SLICE_TOTAL_REQUIRED_STAGES = 10
M6_VERTICAL_SLICE_CONNECTED_STAGES (STRUCTURAL) = 8   (unchanged this task)
M6_PRODUCTION_CONNECTED_STAGES = 8   (unchanged this task -- re-verified
  fresh, not re-derived; a different stage SET than the structural 8, per
  M6_VERTICAL_SLICE_STATUS.md's own table, reproduced below)
```

| # | Stage | Structural | Production | Supported entry point |
|---|---|---|---|---|
| 1 | Intake | Yes | Yes | CLI `start`, dashboard `/api/start` |
| 2 | Field Resolution | Yes | Yes | CLI `--protocols`/`--generate`, dashboard `generate`/`protocols` JSON |
| 3 | Clarification hand-off | Yes | Yes | same |
| 4 | QuestionOwner | Yes | Yes | same |
| 5 | HumanGate | Yes | Yes | same (block/resume, real CLI/dashboard round-trip tested) |
| 6 | EffectiveValue | Yes | Yes | same, persisted as a real lifecycle fact |
| 7 | Dispatch | Yes | Yes | same |
| 8 | Task Boundary | Yes | **No** | no CLI flag or dashboard JSON field supplies a `TaskBoundary` today |
| 9 | VerificationLevel | No (ABSENT) | No (ABSENT) | explicit seam, unimplemented by design |
| 10 | IP/SUBSYSTEM/SYSTEM_LEVEL | No ("separate, unconnected" before C1) | **Yes** | `create_environment()`'s own internal mode resolution, reached from the same governed call |

## Per-edge evidence (every claimed production-connected edge)

### Edge: CLI argv → start_lifecycle() → Field Resolution/Clarification

```
PRODUCER            = cli.py's `start` subcommand argument parser
REAL DATA            = --protocols/--generate/--generate-out/--generate-manifest,
                       real argv strings and a real JSON manifest file
CONSUMER            = engine.py start_lifecycle()'s field-resolution loop
                       via generation_field_controls.py's protocol_field_control()
NEXT-STAGE CONSUMPTION = the resolved EffectiveValue substituted into
                       request["protocol"] before create_environment() is called
SUPPORTED ENTRY POINT = `dv-harness start --goal "..." --protocols pcie --generate
                       --generate-out <dir> --generate-manifest <file>`
EVIDENCE            = test_m6_c1_golden_path_connectivity.py::
                       test_cli_start_generate_propagates_protocol_and_manifest_into_start_lifecycle
                       -- asserts the EXACT kwargs start_lifecycle() received from a
                       real sys.argv, not merely that it was called
```

### Edge: dashboard HTTP JSON → start_lifecycle() → Field Resolution/Clarification

```
PRODUCER            = dashboard.py's POST /api/start handler (_handle_start)
REAL DATA            = a JSON body: {"protocols": [...], "generate": true,
                       "generation_request": {...}, "generate_out": "..."}
CONSUMER            = _start_background_run()'s new protocols/generation_request/
                       generation_out_dir parameters -> start_lifecycle()
NEXT-STAGE CONSUMPTION = same as the CLI edge above
SUPPORTED ENTRY POINT = POST /api/start with the JSON body shape above
EVIDENCE            = test_m6_c1_golden_path_connectivity.py::
                       test_dashboard_start_background_run_propagates_generation_fields
                       -- a real dashboard-shaped call resolves the field and persists
                       it as a real lifecycle fact (not merely "no exception raised")
```

### Edge: start_lifecycle() → create_environment() (generation dispatch)

```
PRODUCER            = engine.py start_lifecycle()'s generation branch
REAL DATA            = a resolved protocol EffectiveValue + the caller's own
                       generation_request manifest (clocks/resets/smoke_tests/etc.)
CONSUMER            = uvm_generator.create_environment.create_environment(),
                       called directly, exactly once, never recursively
NEXT-STAGE CONSUMPTION = create_environment()'s own real output (generated_files,
                       structural_lint, vip_api_validation, verification_architecture)
SUPPORTED ENTRY POINT = both edges above, once resolved
EVIDENCE            = test_m6_c1_golden_path_connectivity.py::
                       test_generation_dispatch_calls_create_environment_directly_never_recurses
                       (exactly 1 real call, correct request, no lifecycle recursion);
                       ::test_a_rejected_protocol_model_topology_returns_a_real_agent_result_not_an_uncaught_exception
                       (the real failure path, all 10 of create_environment()'s own
                       documented exception classes now caught, GAP-V2-001)
```

## Edges explicitly NOT claimed production-connected

- ~~`tools/generate_protocol_uvm_environment.py` → `create_environment()`:
  a real, live, ungoverned edge~~ -- **CLOSED this wave** (GAP-V2-002,
  `CAP-M6-GAPV2002-001`, `DEC-GAP-V2-002 = OPTION_B`): the script is
  reclassified `INTERNAL_GENERATION_PRIMITIVE`; all 11
  `.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` now converge on
  `start_lifecycle(generation_request=...)`, adding 11 more real
  production entry points onto the same 8 already-counted stages (not a
  new stage; see `M6_VERTICAL_SLICE_STATUS.md`'s own update section).
- Any intake field other than `protocol`/`role` → Field Resolution: zero
  production producer exists (GAP-V2-003, `REGISTER_AND_DEFER_WITH_OWNER`
  -- `role` added this wave alongside `protocol`, derived from all 11
  skills' own discovery lists + real downstream consumer evidence, see
  `GAP_V2_002_FIELD_CONTROL_DERIVATION.md`).
- Task Boundary (stage 8): no CLI flag or dashboard JSON field supplies a
  `TaskBoundary` today — unchanged by this task, honestly excluded from
  the production count.

## Full 24-stage Golden Workflow — beyond the M6 slice

Not re-audited this task (out of the explicitly bounded "current approved
M6 Golden-Workflow scope"). `L5DGVA_GOLDEN_OPERATIONAL_WORKFLOW.md`'s own
per-stage table (from the V1 adoption task) remains the most recent
evidence for stages 11-24 and is unchanged by this task.
