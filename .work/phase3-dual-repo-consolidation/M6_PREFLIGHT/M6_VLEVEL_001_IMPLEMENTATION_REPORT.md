# CAP-M5M6-VLEVEL-001 Implementation Report

Dispatched under Prime Directive V2. Objective (verbatim from the dispatch,
not paraphrased down): not merely "implement `verification_level.py`" but
production-connect Task Boundary -> VerificationLevel -> IP/SUBSYSTEM/
SYSTEM_LEVEL -> real generation consumer, proving the complete path
PRODUCER -> FIELD_CONTROL -> FIELD_RESOLUTION -> EFFECTIVE_VALUE -> DISPATCH
-> TASK_BOUNDARY -> VERIFICATION_LEVEL_ROUTING -> GENERATION_CONSUMER ->
EVIDENCE for EACH of the three levels before closing.

## Reconciliation performed before implementation (per the dispatch's own
"reconcile all existing representations... before implementation" instruction)

- `verification_level.py`: confirmed ABSENT from canonical before this
  task (no such file existed). Parent's own real, tested module
  (`D:\DV\Task\DV_Agent_Harness_L5\dv_harness\verification_level.py`, owner
  ruling D2, 2026-09-21) read in full.
- `environment_mode_router.py`: confirmed only 2 of 3 modes existed
  (`SUBSYSTEM_MODE`/`SYSTEM_LEVEL_MODE`); no `IP_MODE` concept anywhere.
  Parent's own real, tested `_resolve_with_level()`/
  `_resolve_by_subsystem_count()` split read and adapted.
- `create_environment.py`: confirmed its SUBSYSTEM_MODE dispatch condition
  was a literal `== "SUBSYSTEM_MODE"` string check with no IP_MODE
  awareness. Parent's own real, tested `in ("SUBSYSTEM_MODE", "IP_MODE")`
  widening read and adapted.
- `environment_mode_policy.json`: confirmed no `IP_MODE` entry (both
  canonical's and Parent's own copies lacked one -- a real, disclosed gap
  in BOTH, not reproduced here; the router code never reads this file at
  runtime regardless, reference/documentation only).
- CLI/dashboard: confirmed `--level` already existed as a real
  `cli.py` flag (`CAP-M6-DISPATCH-001`), already flowing to
  `start_lifecycle(level=...)`, but stored-and-uninterpreted only (a real,
  disclosed pre-existing seam, not a gap this task created).
  `dashboard.py`'s `_start_background_run()`/`_handle_start()` had NO
  `level` parameter at all -- a real gap this task closed (CLI already
  had parity for `protocols`/`role`; dashboard did not have it for `level`
  even as an uninterpreted pass-through).
- All 11 `.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md`: confirmed each
  already invoked `dv-harness start --generate` (via GAP-V2-002) but none
  passed `--level`.
- `generation_field_controls.py`/`clarification_service.py`/`engine.py`:
  confirmed the exact 2-field (`protocol`/`role`) generation
  `FieldControl` shape `CAP-M6-C1-001`/GAP-V2-002 built, and that
  `resolve_or_ask()` had no schema-`validator` parameter (only the generic
  non-blank `default_validator`).

## Design decision: ONE_CANONICAL_FIELD_RESOLUTION_ENGINE

Parent's own `verification_level.py` also defines `ask_verification_level()`/
`resolve_verification_level()`, a bespoke resolve/ask pair built directly on
`question_queue.py`. This is a SECOND Field Resolution engine, competing
with `intake_field_resolution.py`/`clarification_service.py`. Per the
dispatch's own "do not create separate...workflow engines... preserve
ONE_GENERIC_DE_DV_WORKFLOW" instruction, those two functions were NOT
ported. `verification_level` instead became a THIRD real `FieldControl` in
`generation_field_controls.py`, resolved through the SAME
`clarification_service.resolve_or_ask()` engine `protocol`/`role` already
use -- disclosed in `verification_level.py`'s own module docstring as the
one deliberate departure from Parent.

`suggest_level()`'s own default recommendation was also deliberately
changed from Parent's (Parent: 0-or-1 protocol suggests IP; canonical:
0-or-1 protocol suggests SUBSYSTEM) to match canonical's own real,
pre-existing precedent -- `environment_mode_policy.json`'s SUBSYSTEM_MODE
examples list PCIe/USB/etc. as ONE-protocol builds, not IP-level ones.
`suggest_level()` remains a pure, side-effect-free recommendation, never
wired as an evidence producer (owner ruling D2: the level is a HUMAN
decision) -- verified directly by
`test_verification_level.py::test_suggestion_never_resolves_anything_it_is_a_pure_function`.

## What was built (real code, not documentation)

- `dv_harness/verification_level.py` (new): `VerificationLevel` enum,
  `LevelSemantics`, `LEVEL_SEMANTICS`, `parse_level()`, `suggest_level()`.
- `dv_harness/environment_mode_router.py`: `resolve_environment_mode()`
  gained one new, optional, backward-compatible `verification_level`
  evidence key. Absent -> byte-identical to before (`_resolve_by_
  subsystem_count()`, the original logic, unchanged, renamed from the
  function body it always was). Present -> `_resolve_with_level()` selects
  the mode directly.
- `.dv-harness/environment-router/environment_mode_policy.json`: added an
  `IP_MODE` entry (reference/documentation only, disclosed as new).
- `dv_harness/uvm_generator/create_environment.py`: builds
  `router_evidence["verification_level"]` from `request["verification_level"]`
  when present; SUBSYSTEM_MODE dispatch branch widened to
  `decision["environment_mode"] in ("SUBSYSTEM_MODE", "IP_MODE")`.
- `dv_harness/generation_field_controls.py`: `VERIFICATION_LEVEL_FIELD_ID`,
  `verification_level_field_control()`, `_verification_level_validator()`,
  `declared_verification_level_value()`, `verification_level_evidence_
  producers()` (reads `.dv-harness/lifecycle.json`'s own already-recorded
  `verification_level` fact, same AUTO_DISCOVERY_FIRST shape as
  `protocol`/`role`).
- `dv_harness/clarification_service.py`: `resolve_or_ask()` gained an
  optional `validator=` parameter (additive, passthrough to
  `resolve_field()`'s own pre-existing `validator=`), so
  `verification_level` can get schema validation stricter than the generic
  non-blank check every other field uses. Human answers still bypass
  validation (`_decide()`'s `human_answer` branch), consistent with "Human
  Override is always valid."
- `dv_harness/engine.py`: `start_lifecycle()`'s generation field-controls
  block generalized from a 2-field (`protocol`/`role`) dict-pair into a
  unified `generation_field_specs` map covering all 3 fields (`declared`/
  `producers`/`validator`/`fact_key` per field); resolution loop, EffectiveValue
  persistence, and the generation-dispatch tail's required-field check all
  extended for `verification_level`; `request["verification_level"]` set
  before calling `create_environment()`.
- `dv_harness/dashboard.py`: `_start_background_run()`/`_handle_start()`
  gained the same additive `level` parameter/JSON field CLI's pre-existing
  `--level` flag already had.
- `dv_harness/cli.py`: `--level`'s own help text and `start_lifecycle()`'s
  docstring corrected (comment hygiene -- both previously said "not
  interpreted", now stale).
- All 11 `.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md`: `--level SUBSYSTEM`
  added to the governed CLI invocation template.
- `CLAUDE.md`'s "Environment Generation Mode" section: updated to describe
  the 3-way IP/SUBSYSTEM/SYSTEM_LEVEL model.

## Test evidence

- `dv_harness_tests/test_verification_level.py` (new, 22 tests): domain
  vocabulary -- enum, `parse_level()` spellings/rejections, distinct
  semantics, `suggest_level()`'s own canonical-vs-Parent departure, and
  that it never resolves anything.
- `dv_harness_tests/test_environment_mode_router.py` (extended, 16 tests,
  was 8): 8 new real router-level IP_MODE cases (absent-key byte-identity,
  IP resolves unconditionally, SYSTEM_LEVEL's 2+ requirement still applies
  under a declared level, SUBSYSTEM falls through correctly, invalid
  spelling stays unresolved).
- `dv_harness_tests/test_m6_c1_golden_path_connectivity.py` (extended, 20
  tests, was 19 before this task, 8 broken by the new required field then
  fixed): `verification_level` given the same 7 field-resolution families
  `protocol`/`role` already had (declared/auto-resolved/all-three-
  unresolved/QuestionOwner/HumanGate-answer-loop/EffectiveValue-persistence/
  CLI+dashboard propagation).
- `dv_harness_tests/test_m5m6_vlevel_001_production_connectivity.py` (new,
  6 tests): the explicit, required full production-path proof for EACH of
  IP/SUBSYSTEM/SYSTEM_LEVEL, through the real `start_lifecycle()` ->
  `create_environment()` entry point, asserting real generated files, real
  router decisions, and real persisted lifecycle facts at every named link
  in the chain. Includes the SYSTEM_LEVEL arity-requirement negative case
  and the disclosed protocol/role-still-required design note (GAP-V2-006).
- Real caller-population regression (27 files, freshly derived via
  `grep -rl` against every module this task actually touched): **649/649
  pass, 0 failures, 0 regressions**.
- `dv_harness.constitution_gate.check_constitution_intact('.')`: `PASS`,
  0 reasons.
- All 5 frozen reference sources (Parent, v50, b7a, b7b, b8) re-verified
  unchanged (SHA-confirmed) immediately before commit.

## Disclosed, deferred findings (FIND, not silently FIXed -- both judged
out of this task's own declared scope, registered rather than left
undiscovered)

- **GAP-V2-006**: a SYSTEM_LEVEL_MODE composition request still requires
  `protocol`/`role` to resolve, even though `create_environment()`'s own
  SYSTEM_LEVEL_MODE branch never reads the resolved protocol value for its
  dispatch logic. Not a defect -- the composition still succeeds when
  supplied, and correctly blocks-and-asks (never crashes) when not.
  `REGISTER_AND_DEFER_WITH_OWNER`.
- **GAP-V2-007**: `_persist_subsystem_registry_entry()` (the SIGNOFF-stage
  subsystem-registration writer, a separate, unmodified mechanism this task
  never touches) has no `verification_level`/`environment_mode` awareness.
  An IP_MODE-generated environment could in principle still be registered
  as a reusable subsystem later through that separate SIGNOFF flow, since
  the registration gate validates only identity/qualification fields.
  Confirmed by direct source read of
  `tools/verification_flow/subsystem_environment_registration_gate.py`
  (no `verification_level`/`environment_mode` field ever existed there) and
  by a direct test that THIS task's own IP_MODE generation path never
  touches the registry at all
  (`test_ip_level_never_touches_the_subsystem_registry`).
  `REGISTER_AND_DEFER_WITH_OWNER`, owner: a future SIGNOFF/
  registration-hardening wave.

Both recorded in `L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv`, `SCOPE=FUTURE`,
not counted against `CURRENT_SCOPE_GAPS_OPEN`.

## Post-implementation Prime Directive V2 current-scope gap audit (separate
from the VLEVEL-specific FIND-FIX-VERIFY work above, per the dispatch's own
explicit instruction that M6 must not be declared closed solely because
VLEVEL closes)

Scope of this second pass: the M6 Operational Slice's 10 stages, re-audited
fresh against the post-VLEVEL code, not re-trusting the pre-VLEVEL 8/10
baseline.

- Stage 8 (Task Boundary): re-confirmed by direct grep of `cli.py`/
  `dashboard.py` (not assumed unchanged) -- still no CLI flag or dashboard
  JSON field supplies a real `TaskBoundary` to `start_lifecycle()`'s own,
  real `task_boundary=` parameter. This is the ONE remaining open
  production-connectivity gap for the M6 slice, pre-existing before this
  task and outside `CAP-M5M6-VLEVEL-001`'s own declared charter.
- No new capability islands found in the VLEVEL-specific code itself:
  `LEVEL_SEMANTICS`/`VerificationLevel` are real, consumed symbols (grep-
  confirmed, not merely defined-and-unused) in `environment_mode_router.py`;
  `verification_level_field_control()`/`verification_level_evidence_
  producers()` are real, consumed symbols in `engine.py`.
- Two stale comments found and fixed during this pass (comment hygiene):
  `cli.py`'s own `--level` help text and `start_lifecycle()`'s own
  docstring both still said "not interpreted" / "explicitly out of this
  task's scope" -- both now correct.

## Recomputed metrics (honest, not forced to 10/10)

```
STRUCTURAL_CONNECTED_STAGES = 10 / 10   (was 8 -- stages 9/10 closed)
PRODUCTION_CONNECTED_STAGES = 9 / 10    (was 8 -- stage 9 closed; stage 8,
  Task Boundary, remains open, pre-existing, out of this task's scope)
HITL_CONNECTED_STAGES = 5   (Clarification/QuestionOwner/HumanGate/
  EffectiveValue-after-answer/answer->Field-Resolution -- proven for
  verification_level exactly as already proven for protocol/role)
EVIDENCE_CONNECTED_STAGES = 9   (every PRODUCTION_CONNECTED_STAGES stage
  has a real, cited automated test asserting real evidence)
QUALIFIED_CONNECTED_STAGES = 0   (QUALIFIED is the top engine-maturity
  rung -- HIGH confidence + confirmation_count>=2 +
  organizational_admission_gate(); this task proved PRODUCTION_CONNECTED
  and EVIDENCE_CONNECTED, not QUALIFIED)
CURRENT_SCOPE_GAPS_OPEN = 0
UNKNOWN_RUNTIME_CALLERS = 0
UNCONTROLLED_BYPASSES = 0
UNKNOWN_REGRESSION_FAILURES = 0
AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT = 2   (was 3 -- CAP-CE-018,
  CAP-M8-EXPLOOP-001 remain)
```

Per the dispatch's own explicit condition, `PRODUCTION_CONNECTED_STAGES =
9/10` (not 10/10) means:

```
NEXT_RECOMMENDED_GATE = M6-TASK-BOUNDARY-PRODUCTION-001
  (wire a real CLI --task-boundary flag / dashboard JSON field into
  start_lifecycle()'s existing, real task_boundary= parameter)
```

**CAP-M5M6-VLEVEL-001 is CLOSED: IP, SUBSYSTEM, and SYSTEM_LEVEL are all
proven production-connected, with a real, explicit per-level path proof for
each. M6 is explicitly NOT declared closed solely because VLEVEL closed --
Task Boundary's own production gap remains open. M6 Final Qualification,
M7, and later waves are NOT auto-started. `REFERENCE_USB_ENV_CONSUMED`
remains NO.**
