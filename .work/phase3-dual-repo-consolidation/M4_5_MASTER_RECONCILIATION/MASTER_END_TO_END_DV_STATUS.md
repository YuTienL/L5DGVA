# Master End-to-End DV Status — IP / SUBSYSTEM / SYSTEM_LEVEL (v4, post-DV-Verification-Environment-Lifecycle-Integration reconciliation)

Per reconciliation instruction section F: 17 named stages, evaluated
separately per verification level, with the exact first non-operational
stage and its owner wave identified for each. Reused evidence only
(M4/M4.5/M4.6 artifacts, `environment_mode_router.py`,
`intake_routing.py`); no new source audit performed. Where no accepted
artifact independently covers a stage at this granularity, it is marked
`NOT_RE-AUDITED_THIS_WAVE` rather than guessed.

**v3 addition (`VERIFICATION_ENVIRONMENT_LIFECYCLE_MANAGEMENT` roadmap
reconciliation)**: the 17-stage table below is `CREATE_LIFECYCLE` --
this was always its real scope (OpenSpec Intake through Experience
Consolidation, a from-scratch generation flow), simply never labeled as
one half of a two-lifecycle model until this wave froze the product
requirement that L5DGVA support both `CREATE_LIFECYCLE` and
`MAINTAIN_LIFECYCLE` as first-class. This addition does not re-audit or
change any `CREATE_LIFECYCLE` value below.

**v4 addition (DV Verification Environment Lifecycle Integration
reconciliation, this wave)**: `MAINTAIN_LIFECYCLE` is extended from the
v3 12-stage table to an 18-stage table (Qualified Environment -> Attach
-> Rehydrate -> Semantic Drift/Change -> Debug/Evidence -> RCA -> Role
Routing -> Impact -> Change Request/Plan -> Ownership -> Change
Workspace -> Controlled Modification/Semantic Merge -> Selective
Regression -> Coverage Delta -> Evidence Invalidation -> Re-Signoff ->
Qualified Snapshot -> Learning), with 3 new columns per-stage:
`FOUNDATION_OR_OPERATIONAL`, `FAST_PATH_ELIGIBLE`, `FULL_L5DGVA_
REQUIRED_CONDITIONS` -- see
`.work/phase3-dual-repo-consolidation/VERIFICATION_ENVIRONMENT_LIFECYCLE_MANAGEMENT/MAINTAIN_LIFECYCLE_E2E_MATRIX.csv`
(superseded in place, not duplicated) and
`.work/phase3-dual-repo-consolidation/VERIFICATION_ENVIRONMENT_LIFECYCLE_MANAGEMENT/DV_VERIFICATION_ENVIRONMENT_LIFECYCLE_ARCHITECTURE.md`
for the full architecture, including the new `VERIFICATION_ENVIRONMENT_
AUTHORITY=DV`/`VERIFICATION_SIGNOFF_AUTHORITY=DV` freeze and the Native
Claude Fast Maintenance dual-execution-mode architecture. Every
`MAINTAIN_LIFECYCLE` stage remains `ROADMAP_DEFINED`/`PARTIAL`/`BLOCKED`
-- none `OPERATIONAL`, primary owner `M10.5` throughout except where a
nearer wave (`M5`/`M6`/`M7`/`M8`/`M9`/`M10`) contributes a named
`FOUNDATION`.

## IP_MODE

**Unblocked (2026-09-24, `CAP-M5M6-VLEVEL-001`)**: `verification_level.py`
now exists and `environment_mode_router.resolve_environment_mode()` now has
a real `IP_MODE` branch (`_resolve_with_level()`); `create_environment()`'s
SUBSYSTEM_MODE dispatch branch widened to `("SUBSYSTEM_MODE", "IP_MODE")`.

| # | Stage | Status | Notes |
|---|---|---|---|
| 1 | OpenSpec Intake | **WIRED for all real production callers** | `dv-harness start --level IP --generate ...` (CLI) / dashboard `level:"IP"` JSON resolve `verification_level` through the SAME `ClarificationService`/Field-Resolution engine `protocol`/`role` already use, then `environment_mode_router.resolve_environment_mode()` selects `IP_MODE` directly. Full per-level production-path proof: `dv_harness_tests/test_m5m6_vlevel_001_production_connectivity.py::test_ip_level_full_production_path` |
| 2 | Knowledge Retrieval | NOT_RE-AUDITED_THIS_WAVE | out of `CAP-M5M6-VLEVEL-001`'s own declared scope (Task Boundary -> VerificationLevel -> IP/SUBSYSTEM/SYSTEM_LEVEL -> generation consumer, ending at `create_environment()`'s own output) |
| 3 | Discovery | NOT_RE-AUDITED_THIS_WAVE | same |
| 4 | Clarification | **WIRED, same mechanism as stage 1** | `verification_level_field_control()`'s own resolution IS the Clarification stage for this field -- proven jointly with stage 1 |
| 5 | vPlan | PARTIAL (downstream of #4, same as SUBSYSTEM_MODE) | |
| 6 | VIP/UVM Generation | **WIRED** | `create_environment()` dispatches IP_MODE to the SAME `ProtocolEnvGenerator` SUBSYSTEM_MODE uses -- real generated files confirmed, `test_ip_level_full_production_path` |
| 7–17 | Sequence/Scenario/FW … Experience Consolidation | NOT_RE-AUDITED_THIS_WAVE except where already tracked for SUBSYSTEM_MODE (same generator, same disclosed boundaries) | |

```
IP_MODE_FIRST_NON_OPERATIONAL_STAGE = UNKNOWN_PENDING_STAGE_2_3_RE_AUDIT
  (no longer "1. OpenSpec Intake" -- that stage's real router/Field-
  Resolution entry point now exists and is production-connected,
  CAP-M5M6-VLEVEL-001; stages 2-3 have never been re-audited with real
  evidence, same disclosed unknown SUBSYSTEM_MODE/SYSTEM_LEVEL_MODE
  already carry, not claimed OPERATIONAL by omission)
IP_MODE_OWNER_WAVE = M6 (CAP-M5M6-VLEVEL-001 -- CLOSED; the next real work
  here is auditing stages 2-3, same as the other two modes)
```

## SUBSYSTEM_MODE

| # | Stage | Status | Notes |
|---|---|---|---|
| 1 | OpenSpec Intake | WIRED | `intake_routing.py` + `environment_mode_router.py` real dispatch confirmed |
| 2 | Knowledge Retrieval | NOT_RE-AUDITED_THIS_WAVE | |
| 3 | Discovery | NOT_RE-AUDITED_THIS_WAVE | |
| 4 | Clarification | **WIRED for all real production callers (updated this wave, `CAP-M6-C1-001` + `GAP-V2-002`)** | `ClarificationService` is real (`CAP-M6-CLARSVC-001`) AND now production-reachable from every real caller of generation: `start_lifecycle(generation_request=...)` resolves real `protocol`/`role` `FieldControl`s (`generation_field_controls.py`) through it, then calls `create_environment.create_environment()` directly -- CLI (`start --generate`), dashboard (`/api/start`), AND all 11 `.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` now converge on this one governed path (`GAP_V2_002_IMPLEMENTATION_REPORT.md`). `tools/generate_protocol_uvm_environment.py` reclassified `INTERNAL_GENERATION_PRIMITIVE`, no longer an independent workflow entry -- `CAPABILITY_ISLAND = NO` for this edge, closed. Not claimed `OPERATIONAL` end-to-end, for one remaining disclosed reason: stages 2-3 above this one remain `NOT_RE-AUDITED_THIS_WAVE`, so this table cannot yet claim stage 4 is the true first-reachable point of an audited chain |
| 5 | vPlan | PARTIAL (downstream of #4, but `VPLAN_COVERAGE_TRACEABILITY_FOUNDATION = READY` per M4) | |
| 6 | VIP/UVM Generation | WIRED, 1 latent defect | `create_environment.py` -> `ProtocolEnvGenerator`; `KNOWN_SOURCE_B_DEFECT` re-confirmed unchanged (CAP-M5-ARCH-001); now also reachable from the governed path above, not only `tools/generate_protocol_uvm_environment.py` |
| 7–17 | Sequence/Scenario/FW … Experience Consolidation | NOT_RE-AUDITED_THIS_WAVE except where already tracked (Coverage Closure PARTIAL per CAP-M5-COV-001; Experience Consolidation ABSENT per CAP-CE-014) | |

```
SUBSYSTEM_MODE_FIRST_NON_OPERATIONAL_STAGE = UNKNOWN_PENDING_STAGE_2_3_RE_AUDIT
  (no longer honestly "4. Clarification" -- that stage's governed closure path is now real,
  CAP-M6-C1-001 -- but stages 2-3 have never been re-audited with real evidence to move the
  claim there either, so this is reported as unknown rather than guessed)
SUBSYSTEM_MODE_OWNER_WAVE = M6 (CAP-M6-CLARSVC-001, CAP-M6-C1-001 -- both CLOSED; the next
  real work here is auditing stages 2-3, not Clarification)
```

## SYSTEM_LEVEL_MODE

| # | Stage | Status | Notes |
|---|---|---|---|
| 1 | OpenSpec Intake | WIRED | same router dispatch as SUBSYSTEM_MODE |
| 2 | Knowledge Retrieval | NOT_RE-AUDITED_THIS_WAVE | |
| 3 | Discovery | NOT_RE-AUDITED_THIS_WAVE | |
| 4 | Clarification | **WIRED for all real production callers (updated this wave, `CAP-M6-C1-001` + `GAP-V2-002`)** | same as `SUBSYSTEM_MODE` row above — `create_environment()` itself resolves `SYSTEM_LEVEL_MODE` internally from the same governed request, so both closures cover both modes identically |
| 5 | vPlan | PARTIAL | |
| 6 | VIP/UVM Generation | WIRED, 1 unresolved foundation contract | `compose_soc_environment()` real registered-subsystem-registry check + cross-subsystem pre-check; `soc_environment_composer.py`'s ARCH-03 contract UNRESOLVED (CAP-M5-ARCH-002) |
| 7 | Sequence/Scenario/FW | PARTIAL, disclosed scope boundary | cross-subsystem behavioral scenario content is explicitly `NotImplementedError` by design (No Golden-Reference Content Mining rule), not a defect |
| 8 | Checker/Scoreboard/Assertion | PARTIAL, same disclosed boundary | |
| 9–17 | Execution … Experience Consolidation | NOT_RE-AUDITED_THIS_WAVE except where already tracked (Coverage Closure PARTIAL; Experience Consolidation ABSENT) | |

```
SYSTEM_LEVEL_MODE_FIRST_NON_OPERATIONAL_STAGE = UNKNOWN_PENDING_STAGE_2_3_RE_AUDIT (same
  reasoning as SUBSYSTEM_MODE above)
SYSTEM_LEVEL_MODE_OWNER_WAVE = M6 (CAP-M6-CLARSVC-001, CAP-M6-C1-001 -- both CLOSED)
```

## Cross-level reading

**Updated 2026-09-24 (`CAP-M5M6-VLEVEL-001`, CLOSED)**: `IP_MODE`'s prior
first-stage block (no router entry point at all) is resolved -- all three
modes now reach the identical real intake/Field-Resolution/Clarification
dispatch before stage 2, and each has its own real per-level production-path
proof (`dv_harness_tests/test_m5m6_vlevel_001_production_connectivity.py`).
All three modes now share the SAME first honestly-unknown point (stages 2-3,
Knowledge Retrieval/Discovery, `NOT_RE-AUDITED_THIS_WAVE`) rather than
`IP_MODE` being a strictly earlier, more severe gap than the other two.

**Second disclosed correction (M6 Golden-Path Connectivity Closure C1,
this wave)**: the Integration Prime Directive adoption reconciliation's
own prior correction (above the code blocks) found `CAP-M6-CLARSVC-001`
closing alone did NOT unblock stage 4, because `create_environment.py`'s
generation dispatch never reached `start_lifecycle()`. `CAP-M6-C1-001`
closed exactly that governed connection for the CLI (`start --generate`)
and dashboard (`/api/start`) entry points, disclosing at the time that
`tools/generate_protocol_uvm_environment.py` still called
`create_environment()` directly and ungoverned — a real, disclosed,
then-still-open second entry point.

**Third update (GAP-V2-002 remediation, this wave)**: that disclosed gap
is now closed. `DEC-GAP-V2-002 = OPTION_B` (approved): the script is
reclassified `INTERNAL_GENERATION_PRIMITIVE`, and all 11
`.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` — the real, derived field
set (`protocol` + the newly-added `role`, see
`GAP_V2_002_FIELD_CONTROL_DERIVATION.md`) — now converge on the same
governed path. `CAPABILITY_ISLAND = NO` for the generation edge, for
every one of the 13 real production/test callers this task traced.
The one thing this closure does **not** claim: stages 2-3
(Knowledge Retrieval, Discovery) remain `NOT_RE-AUDITED_THIS_WAVE`, so
this table cannot yet claim any stage `OPERATIONAL` end-to-end, and the
"first non-operational stage" claim for both `SUBSYSTEM_MODE` and
`SYSTEM_LEVEL_MODE` is honestly `UNKNOWN_PENDING_STAGE_2_3_RE_AUDIT`
rather than moved to a stage nobody has re-checked.

**Fourth update (`CAP-M5M6-VLEVEL-001`, 2026-09-24)**: `IP_MODE`'s own
first-stage block is now closed (see the updated `## IP_MODE` table and
`## Cross-level reading` above) -- all three modes reach the identical real
dispatch point before stage 2. No stage at any level is claimed
`OPERATIONAL` end-to-end — consistent with
`CANONICAL_CAPABILITY_STRICT_SUPERSET = NOT_YET_QUALIFIED`.

## DE/DV Role-Based HITL overlay (added by the DE/DV roadmap reconciliation)

The 17-stage table above is extended with per-stage
`AUTOMATION_OWNER`/`HUMAN_ROLE`/`HUMAN_GATE_REQUIRED`/`QUESTION_OWNER`
columns in
`.work/phase3-dual-repo-consolidation/M4_5_DE_DV_ROLE_BASED_HITL/DE_DV_E2E_ROLE_MATRIX.csv`
(51 rows = 17 stages × 3 levels) — a genuinely one, generic role model
applied identically across `IP_MODE`/`SUBSYSTEM_MODE`/`SYSTEM_LEVEL_MODE`,
per the frozen architecture decision "DE and DV are not separate
pipelines; they are human authority roles participating in the same
end-to-end lifecycle" (`DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md`). Only 3
of the 17 stages (`Clarification`, `Waiver`, `Signoff`) carry
`HUMAN_GATE_REQUIRED=YES` — role presence at a stage never implies a
mandatory gate.

This overlay does **not** change any `CURRENT_STATUS`/`BLOCKER`/
`PRIMARY_OWNER_WAVE` value in the table above — it is a role/authority
classification layered on top of the same evidence, not a re-audit. The
`Clarification` stage's existing blocker (`CAP-M6-CLARSVC-001`) is now
additionally the stage where `ROLE_BASED_HUMAN_IN_THE_LOOP`,
`QUESTION_OWNER_ROUTING`, and `HUMAN_GATE_CONTRACT` (all owner M6, all
new capability rows from this reconciliation) converge — reinforcing,
not changing, M6's status as the load-bearing near-term wave.

## M14 cross-reference (added by the M14 Productivity & Expertise Amplification Benchmark reconciliation)

Neither the 17-stage `CREATE_LIFECYCLE` table above nor the 18-stage
`MAINTAIN_LIFECYCLE` table (`MAINTAIN_LIFECYCLE_E2E_MATRIX.csv`) is
modified by this reconciliation — M14 is a benchmark PROGRAM that
measures both lifecycles' real end-to-end performance and quality once
they operate, not a new stage within either. `M14`'s 4 qualification
levels (`IP`/`SUBSYSTEM`/`SYSTEM_LEVEL` map to `CREATE_LIFECYCLE`;
`EXISTING_VERIFICATION_ENVIRONMENT_MAINTENANCE` maps to
`MAINTAIN_LIFECYCLE`) are registered in
`.work/phase3-dual-repo-consolidation/M14_PRODUCTIVITY_BENCHMARK/M14_BENCHMARK_MATRIX.csv`,
`ROADMAP_DEFINED`, `NOT STARTED`. M14 starts only after M13 completes —
it does not change any stage's `CURRENT_STATUS` or `BLOCKER` in either
table above, and no stage at any level becomes `OPERATIONAL` by virtue
of this reconciliation.

## Structured Excel Intake cross-reference (added by the L5DGVA Structured Excel Intake Integration reconciliation)

Excel is a FRONTEND to the same Canonical Intake -> Field Resolution ->
OpenSpec engine every stage's own `Clarification` row already depends
on (`intake_field_resolution.py`, `FOUNDATION_CLOSED` since M5 Cohort
4) — it does not change any stage's `CURRENT_STATUS`/`BLOCKER` in the
tables above, and does not become `OPERATIONAL` by virtue of this
reconciliation. `Clarification`'s blocker is now the `create_environment.py`
dispatch-path capability island described above (`CAP-M6-CLARSVC-001`
itself CLOSED) — Excel cannot integrate live before that wiring exists,
at any verification level. See
`.work/phase3-dual-repo-consolidation/STRUCTURED_EXCEL_INTAKE/
STRUCTURED_EXCEL_INTAKE_ARCHITECTURE.md`, `ROADMAP_DEFINED`, `NOT
STARTED`, `PRODUCTION_IMPLEMENTATION_STARTED = NO`.

## USB Excel Qualification & KC Learning cross-reference (added by the USB Excel Qualification & KC Learning Integration reconciliation)

A fifth M11 scenario (`USB_EXCEL_KC_LEARNING_QUALIFICATION`) qualifies
the Structured Excel Intake frontend against real USB Golden generation
output and closes a real Experience -> KC -> Promotion -> Retrieval ->
Consumption -> Re-generation -> Measurement loop, reusing M8's real
Knowledge Brain unchanged (`ONE_KNOWLEDGE_BRAIN = YES`). Like the Excel
cross-reference above, this does not change any stage's
`CURRENT_STATUS`/`BLOCKER` in either lifecycle table and does not make
any stage `OPERATIONAL`. See
`.work/phase3-dual-repo-consolidation/USB_EXCEL_KC_LEARNING/
USB_EXCEL_KC_LEARNING_QUALIFICATION_ARCHITECTURE.md`, `ROADMAP_DEFINED`,
`NOT STARTED`, `PRODUCTION_IMPLEMENTATION_STARTED = NO`,
`REFERENCE_USB_ENV_CONSUMED = NO`.

## Integration Prime Directive adoption cross-reference (added this wave)

`docs/architecture/L5DGVA_INTEGRATION_PRIME_DIRECTIVE.md` was adopted this
wave (governance/roadmap reconciliation only, `CAP-M6-CLARSVC-001` and
`CAP-M6-DISPATCH-001` both preserved CLOSED, no M6 production code
changed). Two `Clarification` row corrections above are this adoption's
direct, disclosed by-product: `CAP-M6-CLARSVC-001` closing did **not**
unblock stage 4 as this document previously (incorrectly, before this
wave) predicted it would once closed — the real blocker is a capability
island between `start_lifecycle()`'s dispatch and `create_environment.py`'s
own generation dispatch, not a missing `ClarificationService`. Full
classification: `L5DGVA_GOLDEN_OPERATIONAL_WORKFLOW.md` and
`L5DGVA_CAPABILITY_MATURITY_AND_ISLAND_POLICY.md`
(`.work/phase3-dual-repo-consolidation/M6_PREFLIGHT/`). No other row in
either lifecycle table was changed by this wave.
