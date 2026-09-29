# L5DGVA Structured Excel Intake — Architecture

Status: ROADMAP-ONLY reconciliation. No Excel functionality
implemented, `PRODUCTION_IMPLEMENTATION_STARTED = NO`. Nothing in this
reconciliation touches `dv_harness/`, Parent/v50/b7a/b7b/b8, or
Reference USB.

## Product contract (frozen)

```
EXCEL_IS_FRONTEND = YES
EXCEL_IS_SOURCE_OF_TRUTH = NO
ONE_CANONICAL_INTAKE_ENGINE = YES
ONE_CANONICAL_FIELD_RESOLUTION_ENGINE = YES
ONE_CANONICAL_OPENSPEC_MODEL = YES
ONE_GENERIC_DE_DV_WORKFLOW = YES
```

Excel, Native Claude CLI, the interactive L5DGVA CLI, and a future Web
UI are four FRONTENDS to the SAME Canonical Intake -> Field Resolution
-> OpenSpec model. This reconciliation never proposes an
independent Excel/Claude/Web semantic engine — every frontend reads and
writes through the one real canonical engine.

## The one real canonical engine this reconciliation builds on

Confirmed by direct read this session (M5 Cohort 4), not assumed:
`dv_harness/intake_field_resolution.py` — the real, tested (25/25),
canonical OpenSpec 8-field resolution engine, migrated from Parent and
adapted for canonical in Cohort 4. It already implements:

- The exact 8-attribute OpenSpec contract this task must preserve:
  `DeclaredValue`, `AutoDiscoveredValue`, `DerivedValue`,
  `EffectiveValue`, `Confidence`, `ValidationState`, `ConfirmationState`,
  `EvidenceRefs` (`OPENSPEC_FIELD_ATTRIBUTES` constant,
  `to_openspec_record()`).
- The real `SourceKind`/`Origin`/`ValidationState`/`ConfirmationState`
  orthogonality this task must preserve
  (`Confidence != ValidationState != ConfirmationState`).
- `AUTO_DISCOVERY_FIRST`: `resolve_field()` always runs registered
  evidence producers before any question is possible;
  `evaluate_question_gate()` refuses to ask about a field whose
  `discovery_ran` is `False`.
- `MINIMAL_STRUCTURED_CLARIFICATION`: `MAX_QUESTION_OPTIONS = 3`,
  `file_clarification()` refuses (never truncates) a conflict with more
  than 3 sides.
- Real conflict semantics: no source-kind precedence, evidence-based
  arbitration via `source_authority.py`'s 9-level order, human-answer
  override only via the distinct `human_answer=` parameter.

**Honest disclosure carried forward from Cohort 4, unchanged by this
reconciliation**: this engine is `FOUNDATION_CLOSED`, `WIRED=NO` — it
has zero canonical callers today, and is not reconciled with canonical's
OWN, separate, existing `intake_state.IntakeFieldRecord`/
`IntakeFieldStatus` model (a single, flatter, combined-status system).
That reconciliation is `CAP-M6-CLARSVC-001`'s job (M6, `ClarificationService`
design+build). Excel intake is a FRONTEND to whichever field-resolution
model M6 ultimately wires as canonical's own live engine — this
reconciliation does not decide that question, and Excel's own
integration inherits it unchanged, whatever M6 decides.

## Four frontends, one engine (target architecture)

```
                    ┌─────────────────────────────┐
                    │  Canonical Intake Engine      │
                    │  (intake_field_resolution.py  │
                    │   reconciled with              │
                    │   intake_state.py by M6)       │
                    │                                │
                    │  Field Resolution              │
                    │  OpenSpec 8-attribute model     │
                    └───────────────┬────────────────┘
                                    │
        ┌───────────────┬──────────┼──────────┬───────────────┐
        │               │          │          │               │
   Structured        Native      Interactive   Web UI
   Excel Intake     Claude CLI      L5DGVA
   (this task,     (existing       CLI
   ROADMAP)         pattern)      (existing)   (future)
```

No frontend ever writes directly to `EffectiveValue`. Every frontend's
input becomes a new `Candidate` (a `DeclaredValue`-kind or
`ClarificationAnswer`-kind entry, per Excel Import below), routed
through the SAME `resolve_field()`/`resolve_recorded()` arbitration —
identical treatment to a value a human typed directly into the
interactive CLI or Native Claude CLI.

## Excel generation (from current Canonical Intake state)

Per the product contract, Excel generation is READ-driven from the
engine's own current `EffectiveValue` state per field, not a blank
questionnaire:

- Fields in `UNRESOLVED` / `NEEDS_CONFIRMATION` / `CONFLICT` /
  `LOW_CONFIDENCE` / `HUMAN_AUTHORITY_REQUIRED` states are prioritized
  for real user attention.
- Fields already `VALID`/`CONFIRMED` may render `READ_ONLY` /
  `NO_ACTION_REQUIRED` — visible for context, not re-asked.
- This directly operationalizes `AUTO_DISCOVERY_FIRST`: since
  `resolve_field()` already ran discovery before Excel generation, the
  generated workbook reflects real discovery results, never a blank
  slate a human must fill by hand.

## Role-based intake (reuses DE/DV HITL, does not fork it)

Reuses the already-frozen role model (this session's own DE/DV
Role-Based HITL architecture, `.work/phase3-dual-repo-consolidation/M4_5_DE_DV_ROLE_BASED_HITL/`):

```
DESIGN_AUTHORITY = DE
VERIFICATION_AUTHORITY = DV
VERIFICATION_ENVIRONMENT_AUTHORITY = DV
VERIFICATION_SIGNOFF_AUTHORITY = DV
```

Design intent/RTL/clock/reset/register/IRQ/DMA/design-semantics fields
route to DESIGN; verification architecture/VIP/test/scoreboard/
assertion/coverage/regression/waiver/signoff fields route to
VERIFICATION; genuine cross-domain ambiguity routes to SHARED. Excel's
own `QUESTION_OWNER` field presentation is a rendering of this existing
role model, never a second one — no `ExcelRole` enum is proposed.

## Workbook views (presentation only, never a second authority)

8 example role/task views (`L5DGVA_Project_Intake.xlsx`,
`L5DGVA_Design_Clarification.xlsx`, `L5DGVA_Verification_Intake.xlsx`,
`L5DGVA_vPlan.xlsx`, `L5DGVA_System_Topology.xlsx`,
`L5DGVA_Coverage_Closure.xlsx`, `L5DGVA_Signoff.xlsx`,
`L5DGVA_Change_Impact.xlsx` — filenames are UX examples, not authority).
Each renders a real Canonical model, never invents one:

| View | Renders | Authority stays with |
|---|---|---|
| Project Intake | identity/level/protocols/DUT/spec/RTL refs/existing env/VIP availability/tool refs/constraints/blockers/unresolved fields | Canonical Intake |
| Design Clarification | unresolved DESIGN-routed questions only | Canonical Intake + DE role |
| Verification Intake | unresolved VERIFICATION-routed questions only | Canonical Intake + DV role |
| vPlan | Requirement->Feature->Scenario->Test->Sequence->Checker/Assertion->Coverage->Evidence->Waiver->Signoff | Canonical vPlan (M10) |
| System Topology | subsystem/instance/interface/protocol/role/source/VIP/connectivity/address/clock/reset/IRQ/shared-resource/ownership | Canonical topology/IR |
| Coverage Closure | presentation/round-trip | Canonical coverage database (M10), never a second coverage store |
| Signoff | presentation/round-trip | DV signoff authority (M10), Excel never signs off |
| Change Impact | integrates with `MAINTAIN_LIFECYCLE` presentation | M10.5's own authoritative change-impact model, not implemented now |

## Excel import (never a silent write to EffectiveValue)

`STRUCTURED_EXCEL_INTAKE_IMPORT` validates workbook identity/version,
schema, field IDs, value types, and allowed actions; detects stale
workbook/conflicts; preserves provenance/evidence; and routes every
update through the SAME Canonical Field Resolution engine
(`intake_field_resolution.resolve_recorded()`/`resolve_field()` shape)
— an imported Excel value becomes a new `DECLARED`-kind (or
`CLARIFICATION_ANSWER`-kind, when it answers a filed question)
`Candidate`, never a direct `EffectiveValue` assignment. This is the
same non-precedence arbitration already proven in Cohort 4's own test
suite (`test_a_declared_value_has_no_authority_rank_so_it_can_only_be_
resolved_by_a_human`): an Excel-declared value that conflicts with
stronger evidence does not silently win just because a human typed it
into a cell.

## Round-trip identity (never filename-based)

A workbook's own identity is carried in structured metadata (a hidden
metadata sheet, or a safe equivalent), never inferred from its
filename:

```
PROJECT_ID, WORKBOOK_ID, WORKBOOK_TYPE, SCHEMA_VERSION, GENERATION_ID,
GENERATED_AT, SOURCE_SNAPSHOT, FIELD_SET_ID, ROLE_VIEW, CHANGE_ID (optional)
```

## Stale workbook + conflict detection

A workbook generated against `SOURCE_SNAPSHOT` S17, imported when the
project is now at S18, must be detected, not silently applied.
Dispositions: `SAFE_TO_APPLY`, `REBASE_REQUIRED`, `CONFLICT`,
`REGENERATE_WORKBOOK`, `HUMAN_REVIEW_REQUIRED`.

A cell's `DeclaredValue` conflicting with the engine's own
`AutoDiscoveredValue` preserves BOTH candidates and their evidence,
marks the conflict via the real `ValidationState.CONTRADICTED`/
`ConfirmationState.CONFLICT` semantics already in
`intake_field_resolution.py`, and routes to Field Resolution / the
future `ClarificationService` / `QuestionOwner` — never a silent choice,
identical to how `_decide()` already handles a `DECLARED` vs.
`AUTO_DISCOVERED` disagreement today (Cohort 4's own
`test_declared_versus_discovered_conflict_is_contradicted_never_
silently_overwritten`).

## Import provenance

```
WORKBOOK_ID, SHEET, FIELD_ID, USER_VALUE, USER_COMMENT, ROLE,
IMPORT_TIME, SOURCE_SNAPSHOT, VALIDATION_RESULT, CONFIRMATION_RESULT
```

## Native Claude CLI as a frontend (future flow, not implemented)

`cd <verification-project>; claude` -> the user asks to start subsystem
intake -> Claude/L5DGVA rehydrates, discovers, derives, validates,
retrieves Knowledge Brain evidence, identifies unresolved fields, asks
the minimum questions. If the user requests Excel, Claude invokes the
SAME Canonical Excel frontend for the unresolved fields — Claude never
invents an ad-hoc spreadsheet schema of its own. Native Claude Fast
Maintenance / `MINIMUM_SUFFICIENT_EXECUTION` / `FAST_PATH_ELIGIBILITY` /
`FAST_PATH_ESCALATION_TO_L5DGVA` / `FAST_TO_FULL_CONTEXT_HANDOFF` (all
frozen by the earlier VERIFICATION_ENVIRONMENT_LIFECYCLE_MANAGEMENT
reconciliation) are preserved unchanged — Excel must not bypass Task
Boundary, artifact ownership, evidence, `HumanGate`, or signoff
authority.

## Web UI

Not built. Frozen requirement only: whenever a Web UI exists, it must
converge on the SAME Canonical Intake -> SAME Field Resolution -> SAME
OpenSpec chain, exactly like Excel and Native Claude CLI.

## No parallel data model (hard requirement, not aspirational)

```
EXCEL_CANONICAL_MODEL_DUPLICATION = 0
EXCEL_OPENSPEC_DUPLICATION = 0
EXCEL_FIELD_RESOLUTION_DUPLICATION = 0
EXCEL_VPLAN_AUTHORITY = NO
EXCEL_COVERAGE_AUTHORITY = NO
EXCEL_SIGNOFF_AUTHORITY = NO
```

No Excel-specific reimplementation of the 8-field OpenSpec model, the
field-resolution arbitration algorithm, vPlan structure, coverage
computation, or signoff decision logic is proposed anywhere in this
reconciliation or its sibling artifacts.

## Wave ownership (frozen, not reopened by this reconciliation)

| Wave | Owns |
|---|---|
| M6 | `ClarificationService`, `QuestionOwner` routing, Field Resolution wiring (reconciling `intake_field_resolution.py` with `intake_state.py`), Task Boundary wiring, `HumanGate` integration — **not** polished Excel UX |
| M10 | vPlan/coverage/traceability/waiver/signoff authoritative models |
| M10.5 | maintenance/change-impact/coverage-delta/evidence-invalidation/incremental-resignoff authoritative lifecycle behavior |
| M12 | primary owner of Excel PRODUCTIZATION (already the roadmap's own "Canonical Cutover/Productization + Role-Based Action Dashboard" wave, per `MASTER_PROGRAM_STATUS.md`) |
| M14 | may later measure clarification time, manual entry, context re-explanation, intake completion time, error rate — not started, no gains claimed now |

Excel's own FOUNDATION work (this reconciliation's own scope: the
architecture, field mapping, round-trip contract, schema/validation
requirements, stale/conflict handling, security requirements) has no
single owner wave assigned here beyond "not yet started" — see
`M12_EXCEL_PRODUCTIZATION_REQUIREMENTS.md` for the M12-owned
productization slice specifically.
