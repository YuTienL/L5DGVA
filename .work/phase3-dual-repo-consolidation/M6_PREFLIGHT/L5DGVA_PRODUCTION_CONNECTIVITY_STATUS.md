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
M6_VERTICAL_SLICE_CONNECTED_STAGES (STRUCTURAL) = 10   (unchanged since
  CAP-M5M6-VLEVEL-001; stage 8, Task Boundary, was ALREADY structurally
  connected before M6-TASK-BOUNDARY-PRODUCTION-001 -- the mechanism itself
  was real, only its production entry point was missing)
M6_PRODUCTION_CONNECTED_STAGES = 10   (M6-TASK-BOUNDARY-PRODUCTION-001,
  2026-09-24: stage 8 closed -- CLI --task-boundary-*/dashboard task_boundary
  JSON field now construct a real TaskBoundary and reach the same,
  already-real check_working_tree_conformance() call. All 10 M6 Operational
  Slice stages are now BOTH structurally and production connected.)
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
| 8 | Task Boundary | Yes | **Yes** (was No) | CLI `--task-boundary-id/-allow/-forbid/-new-file-only`, dashboard `task_boundary` JSON -> `TaskBoundary.from_dict()` (CAP-ATL-004, reused verbatim) -> `start_lifecycle()`'s own, already-real check |
| 9 | VerificationLevel | Yes | Yes | CLI `--level`/dashboard `level` JSON -> `generation_field_controls.verification_level_field_control()` -> `clarification_service.resolve_or_ask()` -> `request["verification_level"]` |
| 10 | IP/SUBSYSTEM/SYSTEM_LEVEL | Yes | Yes | `environment_mode_router.resolve_environment_mode()`'s real `_resolve_with_level()` branch, reached from the same governed call |

### M6-TASK-BOUNDARY-PRODUCTION-001 (2026-09-24) — stage 8 closed

IMPORTANT DESIGN FACT: unlike `protocol`/`role`/`verification_level`,
`TaskBoundary` is NOT a required generation field -- CAP-ATL-004's own
module docstring is explicit that a `TaskBoundary` is "a plain,
caller-declared input... never derived." Omitting it (`task_boundary=None`,
the pre-existing default, unchanged) is the module's own documented,
correct "nothing declared, nothing checked" behavior, not a residual gap.
Production connectivity for this closure means: WHEN a real caller
supplies one through a real supported entry point, the result genuinely
gates the downstream path -- proven for CLI, dashboard, and the
PROTOCOL_BUILDERS invocation shape, for both PASS and FAIL, for all three
levels. See `M6_TASK_BOUNDARY_PRODUCTION_001_ANALYSIS.md`/`_PATH_PROOF.md`/
`_TEST_EVIDENCE.md`/`_FINAL_REPORT.md` for the full record.

A real current-scope defect (GAP-V2-008) was found and fixed during this
closure: `start_lifecycle()`'s own `.dv-harness/` bookkeeping writes
(`lifecycle.json`, `state.json`, `events.jsonl`, `agents/...`), which
happen earlier in the SAME call, always spuriously VIOLATED a real
declared boundary -- invisible before this task because the only prior
Task Boundary test inside `start_lifecycle()` exercised the FAIL path
only, never a genuine PASS path with real evidence present. Fixed via an
additive `exempt_path_prefixes=` parameter on `task_boundary_conformance.
check_working_tree_conformance()`/`check_committed_range_conformance()`
(default `()`, true no-op for every pre-existing caller); `engine.py`'s
own call site passes `exempt_path_prefixes=(".dv-harness",)`.

### CAP-M5M6-VLEVEL-001 (2026-09-24) — stages 9 and 10 closed

`verification_level.py` (new, adapted from Parent's real, tested module --
one deliberate departure, see that module's own docstring) supplies the
domain vocabulary (`VerificationLevel`, `LEVEL_SEMANTICS`, `parse_level()`,
`suggest_level()`). `generation_field_controls.
verification_level_field_control()` is a THIRD real generation `FieldControl`
(alongside `protocol`/`role`), resolved through the exact same
`clarification_service.resolve_or_ask()` engine, with its own stricter
schema validator (`_verification_level_validator()`: IP/SUBSYSTEM/
SYSTEM_LEVEL only, never a bare non-blank check).
`environment_mode_router.resolve_environment_mode()` gained one new,
optional, backward-compatible evidence key (`verification_level`) --
absent, byte-identical to before (`_resolve_by_subsystem_count()`,
unchanged); present, `_resolve_with_level()` selects the mode directly,
adding the one mode the subsystem-count-only decision could never produce:
`IP_MODE`. `create_environment()` now builds `router_evidence[
"verification_level"]` from `request["verification_level"]` when present,
and its SUBSYSTEM_MODE dispatch branch condition widened to
`decision["environment_mode"] in ("SUBSYSTEM_MODE", "IP_MODE")` -- the SAME
`ProtocolEnvGenerator` code path for both.

Full, explicit per-level (IP/SUBSYSTEM/SYSTEM_LEVEL) production-path proof,
through the real `start_lifecycle()` -> `create_environment()` entry point,
asserting real generated files/lifecycle facts/router decisions at every
named link (PRODUCER -> FIELD_CONTROL -> FIELD_RESOLUTION -> EFFECTIVE_VALUE
-> DISPATCH -> TASK_BOUNDARY -> VERIFICATION_LEVEL_ROUTING ->
GENERATION_CONSUMER -> EVIDENCE):
`dv_harness_tests/test_m5m6_vlevel_001_production_connectivity.py` (6/6).
Field-resolution-family parity with protocol/role (declared/auto-resolved/
unresolved/QuestionOwner/HumanGate/answer-loop/EffectiveValue-persistence):
`dv_harness_tests/test_m6_c1_golden_path_connectivity.py` (20/20, extended).
Domain vocabulary: `dv_harness_tests/test_verification_level.py` (22/22,
new). Router-level IP_MODE cases: `dv_harness_tests/
test_environment_mode_router.py` (16/16, extended). All 11
`.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` now pass `--level SUBSYSTEM`
(this project's own established precedent -- `environment_mode_policy.json`'s
SUBSYSTEM_MODE examples list PCIe/USB/etc. as one-protocol builds).
`dashboard.py`'s `_start_background_run()`/`_handle_start()` gained the same
additive `level` parameter/JSON field CLI's `--level` already had.

DISCLOSED, deferred (not a defect, see Gap Register GAP-V2-006): a
SYSTEM_LEVEL_MODE composition request still needs `protocol`/`role` to
resolve, even though `create_environment()`'s own SYSTEM_LEVEL_MODE branch
never reads the resolved protocol value for its own dispatch logic (the
composition's real subsystem set comes from the manifest's own
`requested_subsystems`/`soc_name`). DISCLOSED, deferred (not a defect, see
Gap Register GAP-V2-007): `_persist_subsystem_registry_entry()` (the SIGNOFF-
stage subsystem-registration writer, a separate mechanism this task did not
modify) has no awareness of `verification_level`/`environment_mode` -- an
IP_MODE-generated environment could in principle still be registered into
the subsystem registry later via that separate flow, since the registration
gate validates only identity/qualification fields, not the mode the
environment was actually built under.

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
- Any intake field other than `protocol`/`role`/`verification_level` →
  Field Resolution: zero production producer exists (GAP-V2-003,
  `REGISTER_AND_DEFER_WITH_OWNER` -- `role` added by GAP-V2-002,
  `verification_level` added by CAP-M5M6-VLEVEL-001 this wave, each derived
  from real discovery/consumer evidence, never assumed).
- ~~Task Boundary (stage 8): no CLI flag or dashboard JSON field supplies a
  `TaskBoundary`~~ -- **CLOSED this wave** (`M6-TASK-BOUNDARY-PRODUCTION-001`):
  `cli.py`'s `--task-boundary-*` flags and `dashboard.py`'s `task_boundary`
  JSON field both now construct a real `TaskBoundary` and reach the same,
  already-real `check_working_tree_conformance()` call. `M6_PRODUCTION_
  CONNECTED_STAGES` is now 10/10.
- SYSTEM_LEVEL_MODE composition still requiring `protocol`/`role` to
  resolve even though its own dispatch logic never reads them
  (GAP-V2-006, `REGISTER_AND_DEFER_WITH_OWNER` -- not a defect, the
  composition still succeeds; a design refinement for a future wave).
- `_persist_subsystem_registry_entry()` (SIGNOFF-stage writer, a separate,
  unmodified mechanism) having no `verification_level`/`environment_mode`
  awareness (GAP-V2-007, `REGISTER_AND_DEFER_WITH_OWNER` -- a real,
  disclosed risk that an IP_MODE-generated environment could later be
  registered as a reusable subsystem through that separate flow; requires
  a SIGNOFF/registration-hardening wave to close, out of CAP-M5M6-VLEVEL-001's
  own declared scope).

## Full 24-stage Golden Workflow — beyond the M6 slice

Not re-audited this task (out of the explicitly bounded "current approved
M6 Golden-Workflow scope"). `L5DGVA_GOLDEN_OPERATIONAL_WORKFLOW.md`'s own
per-stage table (from the V1 adoption task) remains the most recent
evidence for stages 11-24 and is unchanged by this task.
