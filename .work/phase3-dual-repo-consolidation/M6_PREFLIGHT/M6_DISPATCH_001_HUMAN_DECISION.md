# CAP-M6-DISPATCH-001 — Human Decision Packet

No option is chosen here. This packet exists so a human can choose one.

## Classification (Section 7 of the dispatch)

```
ARCHITECTURE_ALREADY_DECIDED = NO for this specific question -- confirmed by
  direct read of the M-1 Architecture Decision Freeze (D1-D10): dispatch
  mechanism is not named in any of the 10 frozen decisions. (Contrast with
  CAP-M6-CLARSVC-001, whose target shape IS already decided at D2 -- not
  reopened here, not part of this packet.)
IMPLEMENTATION_DECISION = NO -- this is not merely "how do we build X",
  because canonical currently has TWO real candidate shapes (adopt Parent's
  proven start_lifecycle() pattern, or keep canonical's current direct
  loop()/run_stage() surface and extend it differently) with different
  external behavior, not one agreed target with only build details open.
HUMAN_POLICY_DECISION = YES -- this is the live question this packet asks.
UNKNOWN = N/A
```

---

```
DECISION_ID = DEC-M6-DISPATCH-001

DECISION_REQUIRED =
  Should canonical adopt Parent's already-built start_lifecycle() pattern --
  one unifying dispatch entry point, called by both cli.py's "start" and
  dashboard.py's launcher, that creates/resumes a Standard-Flow lifecycle
  record and (optionally) refuses a post-intake stage until that lifecycle
  reaches INTAKE_READY -- or keep canonical's current direct loop()/
  run_stage() dispatch surface and integrate Standard-Flow lifecycle
  tracking a different way?

WHY_REQUIRED_NOW =
  7 of the other 19 M6-owned capability rows (CAP-M3-001, CAP-M4.5-001,
  CAP-M6-LIFECYCLE-001, CAP-ATL-001, CAP-ATL-002, CAP-ATL-003, CAP-ATL-008)
  name this exact decision as their own SECONDARY_DEPENDENCY in the Master
  Capability Matrix -- more than either of the other two P0 blockers. It is
  also stage #7 of the 10-stage operational vertical slice this preflight
  mapped (see M6_OPERATIONAL_VERTICAL_SLICE.md): the first real joint
  everything from Task Boundary through IP/SUBSYSTEM/SYSTEM_LEVEL needs a
  stable answer from before it can be soundly wired.
```

## EXISTING_PRIOR_ART

- **Parent's real, working code** (`D:\DV\Task\DV_Agent_Harness_L5\dv_harness\engine.py`,
  read-only reference): `DVHarness.start_lifecycle(user_goal, *, loop=False,
  dry_run=False, level=None, protocols=(), advanced=False)` (~lines 8956–9028).
  Decides CREATE / ADOPT_LEGACY / RESUME via `_lifecycle_entry_plan()`,
  writes real `lifecycle.py` transitions, threads a `--level` flag straight
  into the lifecycle's own facts (`verification_level=declared_level.value`),
  supports `advanced=True` as a declared, recorded bypass
  (`LIFECYCLE_BYPASS`), and delegates the actual stage execution to a
  private `_start_dispatch()` helper that is a two-line wrapper over the
  same `loop()`/`run_stage()` canonical already has. A companion
  `_intake_first_guard(stage)` (~line 9030) is called from *inside*
  `run_stage()`'s own body (~line 9231) and refuses any post-INTAKE stage
  until the lifecycle reaches `INTAKE_READY` — **unless no lifecycle file
  exists yet, in which case the guard is a structural no-op** (`if not
  lc.exists(): return None`), making it backward-compatible by
  construction for any caller that never opts in.
- **Canonical's own `dv_harness/lifecycle.py`** (real, present, tested) —
  the Standard-Flow 16-milestone model itself is ALREADY canonical's
  accepted target (this is not part of the open question); its own module
  docstring already uses the identical "intake-first gate"/`LIFECYCLE_BYPASS`
  vocabulary Parent's dispatch code uses. What is open is only whether
  anything calls it as a gate.
- **The M-1 Architecture Decision Freeze (D1–D10)**, read directly
  (`D:\DV\Task\DV_Agent_Harness_L5\.work\phase3-dual-repo-consolidation\
  M_MINUS_1_ARCHITECTURE_DECISIONS.md`, read-only reference, never created
  in canonical): confirms dispatch mechanism is genuinely not one of the 10
  frozen decisions — this is not a case of reopening settled ground.
- **D8 (Maximum Verified Capability Union)**, the one D1–D10 decision that
  does bear indirectly on this choice: "`NEW_CANONICAL_L5_DGVA = MAXIMUM
  VERIFIED CAPABILITY UNION (PARENT, V50)`... No verified capability from
  either source may be lost without an explicit documented decision." A
  real, working, already-tested Parent mechanism exists for exactly this
  problem; D8 does not force adopting it, but it does mean *not* adopting
  it needs its own explicit, documented reason.

## EXISTING_CANONICAL_CONSTRAINTS

- `lifecycle.py`'s forward-only transition rule: intake cannot be skipped
  on the way to generation; any earlier-milestone move is always a REWIND.
- `EVENT_BYPASS = "LIFECYCLE_BYPASS"` is already defined and unused —
  ready to be emitted by whichever option is chosen.
- Roughly 13,000+ existing `dv_harness_tests/` call sites construct
  `DVHarness` directly and call `.loop()`/`.run_stage()` without ever
  creating a lifecycle file. Whatever is chosen must not require touching
  this test population (Parent's own design already satisfies this).
- `environment_mode_router.py`'s real, wired, tested two-mode dispatch
  (`SUBSYSTEM_MODE`/`SYSTEM_LEVEL_MODE`) must not need reworking regardless
  of outcome.

---

## OPTION_A — Adopt Parent's pattern (migrate `start_lifecycle()` + the intake-first guard)

Migrate `start_lifecycle()`, `_intake_first_guard()`, `_run_intake_routing_stage()`/
`ROUTING_STAGE` into canonical's `engine.py`; make `cli.py`'s `start` and
`dashboard.py`'s launcher both call the migrated `start_lifecycle()`;
`run-stage`/direct `.loop()`/`.run_stage()` calls remain available as an
explicit, `LIFECYCLE_BYPASS`-recorded path.

- Proven design, already built and exercised in a real, related codebase.
- Backward-compatible by construction — the guard is a no-op wherever no
  lifecycle file exists (all current tests, all current non-Standard-Flow
  projects).
- Immediately gives the 7 dependent capabilities a concrete target shape.
- Real engineering cost: a genuine `run_stage()` integration point,
  `ROUTING_STAGE` handling, and new test coverage for the gated path.
- Introduces a real behavior CHANGE the moment a project's lifecycle does
  exist and is not yet `INTAKE_READY` — a stage that used to just run now
  parks at `WAIT_USER`.

## OPTION_B — Keep direct dispatch; wire lifecycle tracking as advisory only

No new top-level entry point. `cli.py`/`dashboard.py` keep calling
`loop()`/`run_stage()` directly, exactly as today. `lifecycle.py`'s
milestone tracking is wired as a lightweight, non-blocking hook called
from inside `run_stage()`/`loop()` purely to RECORD milestone transitions
as they naturally occur — never to refuse a stage.

- Minimal engineering footprint; zero behavior change for any existing
  caller, ever.
- Does not require adopting Parent's exact function shape if canonical
  prefers a smaller diff.
- Gives no real INTAKE_FIRST guarantee — a caller can still skip intake
  silently; weaker enforcement than Option A.
- Does not obviously satisfy `CAP-M6-LIFECYCLE-001`'s own stated need
  ("wiring-point identification") as cleanly — that capability's own
  framing implies a real gate is wanted, not only telemetry.
- Diverges further from Parent's already-verified capability (a real,
  documented tension with D8, though not a violation of it).

## OPTION_C — A unifying entry point, without the hard gate

Build one canonical entry point (functionally `start_lifecycle()`-shaped:
creates/resumes the lifecycle record, threads `--level`/`--protocols`
through it, single call site for both `cli.py` and `dashboard.py`) but
**without** porting `_intake_first_guard()`'s hard refusal. `run_stage()`
never blocks for lifecycle reasons; enforcement (if wanted at all) stays a
UX-layer warning/banner, not a `WAIT_USER` block.

- Gets the "one true front door" benefit both A and the dependent
  capabilities actually need (a single place `--level`/`--protocols`/
  intake-creation logic lives) without importing A's stricter, higher-risk
  blocking behavior.
- Genuinely distinct from both A (no hard gate) and B (still centralizes
  into one entry point rather than two direct, independent callers).
- Weaker than A on the actual INTAKE_FIRST guarantee CLAUDE.md's own
  (Parent-side) description names as the point of the mechanism — a
  caller could still reach a stage with an incomplete intake, just with a
  visible warning instead of a real refusal.
- Still real engineering cost (the entry point itself, `ROUTING_STAGE`
  handling for a non-blocking routing pass), smaller than A's but nonzero.

---

## Impact fields (every viable option, per the dispatch's own required list)

```
COMPATIBILITY_IMPACT:
  A: additive signature (cli.py `start` already has room for --level/
     --advanced-style flags); zero impact on the ~13k tests that never
     create a lifecycle file; real, new WAIT_USER behavior only for a
     project that HAS a lifecycle and is pre-INTAKE_READY.
  B: zero compatibility impact of any kind -- pure additive telemetry.
  C: same additive shape as A, but with no new refusal path anywhere --
     strictly lower behavioral risk than A.

OPENSPEC_IMPACT:
  A/C: --level/--protocols flow through the SAME entry point OpenSpec's
     own field-resolution model will eventually need to read from --
     structurally consistent with ONE_CANONICAL_OPENSPEC_MODEL.
  B: does not advance OpenSpec integration at all (no new entry point to
     carry it through); the eventual integration point stays undesigned.

DE_DV_HITL_IMPACT:
  A/B/C: none differentiate dispatch by DE/DV role -- all three remain
     consistent with ONE_GENERIC_DE_DV_WORKFLOW. A/C's single choke point
     is structurally easier to extend later with role-based question
     routing (CAP-HITL-005/007) than B's more diffuse advisory hook.

TASK_BOUNDARY_IMPACT:
  A/C: the natural wiring point for CAP-ATL-004's own conformance check
     becomes this same entry point (checked alongside the intake gate).
  B: task-boundary checking would need an entirely separate hook inside
     run_stage(), a second integration point rather than reusing one.

CLARIFICATION_SERVICE_IMPACT:
  None of A/B/C build ClarificationService (correctly out of this task's
  scope). A/C's INTAKE_ROUTING/USER_INPUT_REQUIRED parking point is a more
  natural future landing spot for a real Clarification escalation
  (matching lifecycle.py's own milestone vocabulary) than B's advisory-only
  hook, which has no natural "pause and ask" moment built in.

VERIFICATION_LEVEL_IMPACT:
  A/C: Parent's own start_lifecycle() ALREADY threads --level into the
     lifecycle's facts at this exact entry point -- CAP-M5M6-VLEVEL-001's
     future migration has a proven integration point to land in.
  B: leaves that integration point undesigned; VerificationLevel would need
     its own, separately invented wiring point.

VELM_IMPACT (DV Verification Environment Lifecycle Management -- frozen,
  not reopened): none of A/B/C touch VELM's own CAP-VELM-* roadmap scope or
  operationalize any of it. This decision is strictly upstream of VELM.

NATIVE_CLAUDE_FAST_PATH_IMPACT (frozen, not reopened): a real, disclosable
  trade-off. Under A, a Fast Path session would need to declare itself an
  explicit LIFECYCLE_BYPASS (matching Parent's own `advanced=True`
  semantics) to avoid being blocked by the intake-first guard on a project
  that already has a lifecycle -- not yet scoped anywhere. Under C, the
  same concern applies only to the (optional, non-blocking) UX warning, a
  much lower-stakes integration. Under B, Fast Path is entirely unaffected
  (nothing ever blocks).

EXCEL_INTAKE_IMPACT (Structured Excel Intake -- frozen, not reopened):
  under A, a workbook-driven intake would need its own way to satisfy/
  declare the lifecycle gate before dispatch proceeds -- real, unscoped
  integration work. Under B, Excel intake is unaffected (no gate exists to
  satisfy). Under C, only the advisory warning is at stake, not a hard
  block.

IP_SUBSYSTEM_SYSTEM_IMPACT: under A/C, VerificationLevel (once built) and
  environment_mode would flow through the same entry point -- a single
  path, matching D8. Under B, VerificationLevel's future wiring to
  environment_mode_router.py needs an entirely separate integration hook
  from whatever Option B builds for lifecycle telemetry.
```

## EVIDENCE_REFS

- `dv_harness/cli.py` (canonical) — `elif args.cmd == "start":` handler,
  read directly this task.
- `dv_harness/dashboard.py` (canonical) — `_start_background_run()`, read
  directly this task.
- `dv_harness/lifecycle.py` (canonical) — full module docstring + `Milestone`
  enum, read directly this task.
- `dv_harness/environment_mode_router.py` (canonical), `CLAUDE.md` line 967
  ("Environment Generation Mode") — read directly this task.
- Parent `dv_harness/engine.py` lines ~8950–9075 (`_start_dispatch`,
  `start_lifecycle`, `_intake_first_guard`, `_run_intake_routing_stage`),
  Parent `dv_harness/verification_level.py` header — read-only reference,
  read directly this task.
- `D:\DV\Task\DV_Agent_Harness_L5\.work\phase3-dual-repo-consolidation\
  M_MINUS_1_ARCHITECTURE_DECISIONS.md` (D1–D10) — read-only reference, read
  directly this task.
- `MASTER_CAPABILITY_STATUS_MATRIX.csv` rows: `CAP-M6-DISPATCH-001`,
  `CAP-M3-001`, `CAP-M4.5-001`, `CAP-M6-LIFECYCLE-001`, `CAP-ATL-001/002/003/008`.
- This task's own `M6_CORE_BLOCKER_MAP.md`, `M6_OPERATIONAL_VERTICAL_SLICE.md`.

---

## Constraint preservation check (Section 10 of the dispatch)

All three options are pure dispatch/entry-point mechanisms — none introduce
a second intake engine, a second field-resolution engine, a second OpenSpec
model, a DE-specific or DV-specific pipeline, a hardcoded host/path, or any
change to DV Verification Environment Authority. Checked individually:

```
                                    Option A   Option B   Option C
ONE_GENERIC_DE_DV_WORKFLOW = YES       YES        YES        YES
ONE_CANONICAL_INTAKE_ENGINE = YES      YES        YES        YES
ONE_CANONICAL_FIELD_RESOLUTION_ENGINE  YES        YES        YES
  = YES
ONE_CANONICAL_OPENSPEC_MODEL = YES     YES        YES        YES
AUTO_DISCOVERY_FIRST = YES             YES        YES        YES
MINIMAL_STRUCTURED_CLARIFICATION = YES YES        YES        YES
LOCATION_INDEPENDENT = YES             YES        YES        YES
DV_VERIFICATION_ENVIRONMENT_AUTHORITY  PRESERVED  PRESERVED  PRESERVED
  = PRESERVED
```

All three are viable on constraint-preservation grounds alone; the real
difference between them is engineering cost vs. enforcement strength vs.
fidelity to Parent's already-verified design, as detailed above. **No
option is selected here.**
