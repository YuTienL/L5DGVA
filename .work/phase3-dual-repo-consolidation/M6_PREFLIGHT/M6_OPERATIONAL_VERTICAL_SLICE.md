# M6 Operational Vertical Slice

The requested chain: **Intake → Field Resolution → Clarification (when
unresolved) → QuestionOwner → HumanGate (when required) → EffectiveValue →
Dispatch → Task Boundary → VerificationLevel → IP / SUBSYSTEM / SYSTEM_LEVEL**.

This is the concrete answer to why M6 matters: every one of these 10 stages
has *some* real artifact behind it today, but no two adjacent stages are
actually wired to consume each other's output yet. That is the literal gap
between "an architecturally complete platform" and "a platform DV/DE can
use end to end" — the pieces exist; the pipe connecting them does not.

Taxonomy used (never collapsing `FOUNDATION` into `OPERATIONAL`):
`ABSENT` / `ROADMAP_DEFINED` / `FOUNDATION` / `IMPLEMENTED` / `WIRED` /
`TRIGGERED` / `CONSUMED` / `OPERATIONAL`.

| # | Stage | Real artifact | Classification | Evidence |
|---|---|---|---|---|
| 1 | **Intake** | `dv_harness/intake_routing.py` (`INTAKE_ROUTING` deterministic node: verification-level + protocol routing, parks at `USER_INPUT_REQUIRED`) | `FOUNDATION` | Module is real; grep for `intake_routing.` in `engine.py`/`cli.py` returns **zero** call sites — the node is never invoked from the actual dispatch path. |
| 2 | **Field Resolution** | `dv_harness/intake_field_resolution.py` (M5 Cohort 4 migration: `resolve_field()`, `AUTO_DISCOVERY_FIRST`, `MINIMAL_STRUCTURED_CLARIFICATION`) | `FOUNDATION` | Real, 0-signature-change port with 19/19 (Cohort-4-era) tests passing; **0 real canonical callers** (confirmed at migration time and unchanged since — no file added after Cohort 4 imports it). |
| 3 | **Clarification** | `ClarificationService` (target name, M-1 D2) | `ROADMAP_DEFINED` | D2 fixes the *target shape* only ("one service... preserves the maximum verified capability from both"); no `ClarificationService` file exists in canonical. The two real predecessor mechanisms exist independently and un-reconciled: `question_queue.py` (present, live callers, but per `CAP-M5M6-VLEVEL-001`'s own blocker text "diverged, M3-excluded") and `intake_clarification.py` (absent from canonical entirely — Parent-only). |
| 4 | **QuestionOwner** | `CAP-HITL-005` / `QUESTION_OWNER_ROUTING.md` | `ROADMAP_DEFINED` | Schema + flow defined in the named doc; `CANONICAL_STATE` in the Master matrix reads verbatim "schema + flow defined, not built." |
| 5 | **HumanGate** | `CAP-HITL-006` / `HUMAN_GATE_CONTRACT.md` | `ROADMAP_DEFINED` | Same pattern: schema defined, not built. |
| 6 | **EffectiveValue** | `intake_field_resolution.py`'s own `OPENSPEC_FIELD_ATTRIBUTES` / `resolve_field()` output field | `FOUNDATION` | Lives inside the same Field-Resolution module (#2) — real and computable, but reachable only by calling that module directly; no dispatch-time caller resolves an `EffectiveValue` for any real intake field today. |
| 7 | **Dispatch** | `DVHarness.loop()` / `DVHarness.run_stage()` | `OPERATIONAL` (as a general-purpose stage runner) **but not `CONSUMED`** in this vertical-slice's own sense | `loop()`/`run_stage()` are real, heavily tested (this session's own M5 Final Closure Regression exercised them across roughly a third of 13,318 passing tests), and are the live dispatch surface for both `cli.py` and `dashboard.py` (direct read, confirmed). But neither method reads an `EffectiveValue`, a `ClarificationService` outcome, or a `VerificationLevel` as a precondition before running a stage — dispatch is real and operational as a mechanism, while remaining functionally disconnected from every stage upstream of it in this slice. This is the literal "Dispatch" half of `CAP-M6-DISPATCH-001`'s open decision (see `M6_DISPATCH_001_HUMAN_DECISION.md`). |
| 8 | **Task Boundary** | `dv_harness/task_boundary_conformance.py` (`CAP-ATL-004`) | `FOUNDATION` | Real, 330 lines, 19/19 tests, migrated Cohort 4. **Disclosed correction to `M5_TO_M6_HANDOFF.md`'s own prior wording** ("CAP-ATL-004's CLI verb exists in canonical"): re-checked directly this preflight — `grep "task-boundary-conformance" dv_harness/cli.py` returns **zero** matches in canonical. The wired CLI verb (`task-boundary-conformance`) exists only in **Parent**; canonical's own copy is import-only, `WIRED = NO`, exactly as `CAP-ATL-004`'s own `CANONICAL_STATE` field already says ("Canonical cli.py wiring deliberately deferred to CAP-M6-DISPATCH-001... module lands as a tested, importable FOUNDATION, WIRED=NO") — the earlier handoff doc's summary sentence overstated it; the underlying capability-matrix row itself was correct throughout. |
| 9 | **VerificationLevel** | `dv_harness/verification_level.py` | `ABSENT` | Confirmed: no such file anywhere in canonical (`find` returns nothing). Real, working prior art exists in Parent only (`VerificationLevel(IP/SUBSYSTEM/SYSTEM_LEVEL)`, `LEVEL_SEMANTICS`, `resolve_verification_level()`). |
| 10 | **IP / SUBSYSTEM / SYSTEM_LEVEL** | `dv_harness/environment_mode_router.py` + `uvm_generator/create_environment.py` | `OPERATIONAL` for 2 of 3 modes, `ABSENT` for the 3rd | Canonical's own CLAUDE.md documents this as "Dispatched in code at the generation entry point (2026-09-04)" for `SUBSYSTEM_MODE`/`SYSTEM_LEVEL_MODE` — real, wired, consumed, with its own end-to-end test (`test_system_level_soc_composition_wiring.py`). `IP_MODE` has no branch anywhere in `environment_mode_router.py` (confirmed by grep) — the file only ever compares one-subsystem-vs-many, never a bare-IP case. |

## The connectivity gap, stated plainly

Reading the row-by-row evidence together: stages #1, #2, #6 are real code
with **zero real callers** (`FOUNDATION`, not `WIRED`). Stages #3, #4, #5
are **not built at all** (`ROADMAP_DEFINED`). Stage #7 is the one piece
that is genuinely `OPERATIONAL` — but only as a bare stage-runner, not as a
consumer of anything from #1–#6. Stage #8 is real but disconnected the
same way as #1/#2/#6. Stage #9 does not exist. Stage #10 is `OPERATIONAL`
for 2 of its 3 modes, structurally incapable of the 3rd.

**No stage in this slice reaches `CONSUMED` by the stage after it.** That is
the precise, evidenced version of the goal stated for this task: M6 is
where these become one real executable path, not ten separate real
artifacts each waiting for a caller. `CAP-M6-DISPATCH-001`'s own decision
(stage #7) is the first joint in that chain a human needs to fix before the
rest can be wired in a stable order — which is why 7 of the other 19
M6-owned capability rows already name it as their own dependency (see
`M6_PREFLIGHT_STATUS.md`).

## Vertical-slice status

```
M6_VERTICAL_SLICE_DEFINED = YES
STAGES_OPERATIONAL_END_TO_END = 0 of 10
STAGES_FOUNDATION_ONLY = 4  (Intake, Field Resolution, EffectiveValue, Task Boundary)
STAGES_ROADMAP_DEFINED_ONLY = 3  (Clarification, QuestionOwner, HumanGate)
STAGES_ABSENT = 1  (VerificationLevel)
STAGES_PARTIALLY_OPERATIONAL = 2  (Dispatch, IP/SUBSYSTEM/SYSTEM_LEVEL --
  each real and used for its own narrow duty, neither consuming/consumed by
  its slice neighbors)
```
