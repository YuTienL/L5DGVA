# L5DGVA Structured Excel Intake Integration Prompt

## Mission

Perform ROADMAP / REQUIREMENTS / ARCHITECTURE / MASTER-CONTROL-PLANE
reconciliation for **L5DGVA STRUCTURED EXCEL INTAKE**. This is NOT
implementation. Preserve the current M5 gate. Do not start M6, M10.5,
M12, or M14; do not consume Reference USB; do not modify
Parent/v50/b7a/b7b/b8.

## Product Contract

Freeze: - EXCEL_IS_FRONTEND = YES - EXCEL_IS_SOURCE_OF_TRUTH = NO -
ONE_CANONICAL_INTAKE_ENGINE = YES -
ONE_CANONICAL_FIELD_RESOLUTION_ENGINE = YES -
ONE_CANONICAL_OPENSPEC_MODEL = YES - ONE_GENERIC_DE_DV_WORKFLOW = YES

Excel, Native Claude CLI, interactive L5DGVA CLI and Web UI are
frontends to the SAME Canonical Intake → Field Resolution → OpenSpec
model. Never create independent Excel/Claude/Web semantic engines.

## Preflight

Verify Canonical repo identity; record PROCESS_CWD, REPO_ROOT,
CURRENT_BRANCH, CURRENT_HEAD and git status. Read CLAUDE.md, Article 0,
Master Capability/Wave/Blocker/Program/E2E artifacts, OpenSpec Intake,
CAP-ATL-004/007, DE/DV HITL, M6 ClarificationService roadmap, M10/M10.5,
M12 UX, Native Claude Fast Maintenance and current M5 state. Verify
frozen sources unchanged. Wrong repo =\> WRONG_L5_REPOSITORY and STOP.

## Auto-Discovery First

Preserve AUTO_DISCOVERY_FIRST=YES and
MINIMAL_STRUCTURED_CLARIFICATION=YES. Before asking a human, attempt
existing project state, RTL/parameters/defines, UVM/VIP config,
tests/sequences, design docs, vPlan, build/regression scripts,
git/project history, Knowledge Brain, then human clarification. Reuse
existing Canonical evidence hierarchy if more precise. Do not ask users
to re-enter reliably discoverable data.

## OpenSpec Eight-Field Contract

Preserve DeclaredValue, AutoDiscoveredValue, DerivedValue,
EffectiveValue, Confidence, ValidationState, ConfirmationState,
EvidenceRefs. Preserve Confidence != ValidationState !=
ConfirmationState. Excel input maps to
declared/confirmation/correction/comment/authority semantics according
to Canonical policy; it must not silently overwrite
discovered/derived/evidence values.

## Excel Generation

Generate from current Canonical Intake state. Prioritize UNRESOLVED,
NEEDS_CONFIRMATION, CONFLICT, LOW_CONFIDENCE, HUMAN_AUTHORITY_REQUIRED.
Validated known fields may be shown READ_ONLY / NO_ACTION_REQUIRED. Do
not generate a blank questionnaire for all fields.

## Field Presentation

Support equivalent fields: FIELD_ID, CATEGORY, DESCRIPTION,
QUESTION_OWNER, DECLARED_VALUE, AUTO_DISCOVERED_VALUE, DERIVED_VALUE,
EFFECTIVE_VALUE, CONFIDENCE, VALIDATION_STATE, CONFIRMATION_STATE,
EVIDENCE_SUMMARY, USER_ACTION, USER_VALUE, USER_COMMENT, REQUIRED,
BLOCKING, SOURCE_REFERENCE. Reuse Canonical equivalents.

## User Actions

Support concepts: NO_ACTION_REQUIRED, PROVIDE_VALUE, CONFIRM_VALUE,
REJECT_VALUE, CORRECT_VALUE, SELECT_OPTION, REQUEST_EXPLANATION, DEFER,
WAIVE_IF_ALLOWED. Valid actions are policy/authority driven.

## Role-Based Intake

Freeze DESIGN_AUTHORITY=DE, VERIFICATION_AUTHORITY=DV,
VERIFICATION_ENVIRONMENT_AUTHORITY=DV,
VERIFICATION_SIGNOFF_AUTHORITY=DV. Route design
intent/RTL/clock/reset/register/IRQ/DMA/design semantics to DESIGN;
verification
architecture/VIP/test/scoreboard/assertion/coverage/regression/waiver/signoff
to VERIFICATION; genuine cross-domain ambiguity to SHARED. Do not create
separate DE/DV Intake engines.

## Workbook Views

Support role/task views equivalent to Project Intake, Design
Clarification, Verification Intake, vPlan, System Topology, Coverage
Closure, Signoff, Change Impact. Example filenames may be
L5DGVA_Project_Intake.xlsx, L5DGVA_Design_Clarification.xlsx,
L5DGVA_Verification_Intake.xlsx, L5DGVA_vPlan.xlsx,
L5DGVA_System_Topology.xlsx, L5DGVA_Coverage_Closure.xlsx,
L5DGVA_Signoff.xlsx, L5DGVA_Change_Impact.xlsx. Names are UX examples,
not authority.

Project Intake may show identity, level, protocols, DUT/top, spec/RTL
refs, existing env, VIP availability, tool/execution-profile refs,
constraints, blockers, unresolved fields. Never expose secrets.

Design Clarification is DE-oriented and asks only unresolved design
questions. Verification Intake is DV-oriented and asks only unresolved
verification questions.

vPlan view may expose
Requirement→Feature→Scenario→Test→Sequence→Checker/Assertion→Coverage→Evidence→Waiver→Signoff.
Canonical vPlan remains authority.

Topology view may expose
subsystem/instance/interface/protocol/role/source/VIP/connectivity/address/clock/reset/IRQ/shared
resource/ownership. Render Canonical topology/IR; do not invent
semantics.

Coverage view is presentation/round-trip, not coverage database. Signoff
view is presentation/round-trip; DV remains signoff authority. Change
Impact view integrates with MAINTAIN_LIFECYCLE but does not implement
M10.5 now.

## Excel Import

Define STRUCTURED_EXCEL_INTAKE_IMPORT. Validate workbook
identity/version, schema, field IDs, value types, allowed actions;
detect stale workbook/conflicts; preserve provenance/evidence; route
updates through Canonical Field Resolution. Never directly assign
imported values to EffectiveValue.

## Round-Trip Identity

Workbook identity supports PROJECT_ID, WORKBOOK_ID, WORKBOOK_TYPE,
SCHEMA_VERSION, GENERATION_ID, GENERATED_AT, SOURCE_SNAPSHOT,
FIELD_SET_ID, ROLE_VIEW, optional CHANGE_ID. May use hidden metadata
sheet or safe equivalent. Never rely on filename alone.

## Stale Workbook Detection

If workbook came from S17 but project is S18, detect it. Do not silently
apply stale answers. Support dispositions equivalent to SAFE_TO_APPLY,
REBASE_REQUIRED, CONFLICT, REGENERATE_WORKBOOK, HUMAN_REVIEW_REQUIRED.

## Conflict Detection

If Excel DeclaredValue conflicts with AutoDiscoveredValue, preserve both
candidates and evidence, mark conflict using Canonical ValidationState
semantics, then route through Field Resolution/future
ClarificationService/QuestionOwner. Never silently choose.

## Import Provenance

Retain equivalent provenance: WORKBOOK_ID, SHEET, FIELD_ID, USER_VALUE,
USER_COMMENT, ROLE, IMPORT_TIME, SOURCE_SNAPSHOT, VALIDATION_RESULT,
CONFIRMATION_RESULT.

## Schema / Formula / Macro / Security

Validate sheets, metadata, columns, IDs, types, enums, blanks,
duplicates, unknown fields, malformed workbook, unsupported schema,
formulas/merged cells where relevant, hidden metadata consistency. Fail
safely. Do not depend on macros or execute arbitrary macros. Record
future security acceptance for path safety, resource limits, malformed
XLSX/ZIP, external links, formula injection, macro content, hidden
sheets, unexpected objects, untrusted text, secret leakage. Do not build
a new security subsystem now.

## Native Claude CLI

Native Claude is another frontend to the SAME Intake model. Future flow:
`cd <verification-project>; claude`; user asks to start subsystem
intake; Claude/L5DGVA rehydrates, discovers, derives, validates,
retrieves knowledge, identifies unresolved fields, and asks minimum
questions. If user requests Excel, invoke the Canonical Excel frontend
for unresolved fields. Claude must not invent an ad-hoc spreadsheet
schema.

Preserve NATIVE_CLAUDE_FAST_MAINTENANCE, MINIMUM_SUFFICIENT_EXECUTION,
FAST_PATH_ELIGIBILITY, FAST_PATH_ESCALATION_TO_L5DGVA,
FAST_TO_FULL_CONTEXT_HANDOFF. Excel must not bypass Task Boundary,
artifact ownership, evidence, HumanGate or signoff authority.

## Web UI

Excel, Native Claude CLI, interactive CLI and Web UI must converge on
SAME CANONICAL INTAKE → SAME FIELD RESOLUTION → SAME OPENSPEC.

## Wave Ownership

M6 owns ClarificationService, QuestionOwner routing, Field Resolution
wiring, Task Boundary wiring, HumanGate integration---not polished Excel
UX. M10 owns vPlan/coverage/traceability/waiver/signoff authoritative
models. M10.5 owns
maintenance/change-impact/coverage-delta/evidence-invalidation/incremental-resignoff
authoritative lifecycle behavior. M12 is primary owner of Excel
productization. M14 may later measure clarification time, manual entry,
context re-explanation, intake completion time and error rate; do not
start M14 or claim gains now.

## Capability Matrix

Add/reconcile, reusing equivalents: STRUCTURED_EXCEL_INTAKE;
EXCEL_TEMPLATE_GENERATION; EXCEL_INTAKE_IMPORT; EXCEL_SCHEMA_VALIDATION;
EXCEL_FIELD_CONFLICT_DETECTION; EXCEL_ROUND_TRIP;
ROLE_BASED_EXCEL_INTAKE; EXCEL_STALE_WORKBOOK_DETECTION;
EXCEL_PROVENANCE; EXCEL_VPLAN_VIEW; EXCEL_TOPOLOGY_VIEW;
EXCEL_COVERAGE_CLOSURE_VIEW; EXCEL_SIGNOFF_VIEW;
EXCEL_CHANGE_IMPACT_VIEW.

For each record CURRENT_STATE, PRIMARY_OWNER_WAVE, DEPENDENCIES,
PRIORITY, BLOCKER, EVIDENCE, ARTICLE0_DIMENSION. Do not mark IMPLEMENTED
because openpyxl/CSV/manual spreadsheets exist.

## No Parallel Data Model

Require EXCEL_CANONICAL_MODEL_DUPLICATION=0,
EXCEL_OPENSPEC_DUPLICATION=0, EXCEL_FIELD_RESOLUTION_DUPLICATION=0,
EXCEL_VPLAN_AUTHORITY=NO, EXCEL_COVERAGE_AUTHORITY=NO,
EXCEL_SIGNOFF_AUTHORITY=NO.

## Required Artifacts

Produce/update in approved work area, not repo root: -
STRUCTURED_EXCEL_INTAKE_ARCHITECTURE.md -
EXCEL_INTAKE_FIELD_MAPPING.csv -
EXCEL_ROLE_BASED_WORKBOOK_REQUIREMENTS.md -
EXCEL_ROUND_TRIP_CONTRACT.md -
EXCEL_SCHEMA_AND_VALIDATION_REQUIREMENTS.md -
EXCEL_STALE_CONFLICT_HANDLING.md - EXCEL_SECURITY_REQUIREMENTS.md -
M12_EXCEL_PRODUCTIZATION_REQUIREMENTS.md

Update existing MASTER_CAPABILITY_STATUS_MATRIX,
MASTER_WAVE_OWNERSHIP_MATRIX, MASTER_END_TO_END_DV_STATUS,
MASTER_PROGRAM_STATUS as required. Do not create competing authority.

## Structural Validation

Use real CSV parsing, not grep/text column counting. Require
MALFORMED_ROWS=0, DUPLICATE_CAPABILITY_IDS=0, P0_COUNT_AMBIGUITY=0.

## Validation Gates

Require: STRUCTURED_EXCEL_INTAKE=ROADMAP_DEFINED EXCEL_IS_FRONTEND=YES
EXCEL_IS_SOURCE_OF_TRUTH=NO ONE_CANONICAL_INTAKE_ENGINE=YES
ONE_CANONICAL_FIELD_RESOLUTION_ENGINE=YES
ONE_CANONICAL_OPENSPEC_MODEL=YES OPENSPEC_8_FIELD_MODEL_PRESERVED=YES
AUTO_DISCOVERY_FIRST=YES MINIMAL_STRUCTURED_CLARIFICATION=YES
ROLE_BASED_EXCEL_INTAKE=DEFINED EXCEL_ROUND_TRIP=DEFINED
EXCEL_SCHEMA_VALIDATION=DEFINED EXCEL_STALE_WORKBOOK_DETECTION=DEFINED
EXCEL_CONFLICT_DETECTION=DEFINED EXCEL_PROVENANCE=DEFINED
USER_REENTRY_OF_DISCOVERED_FIELDS_REQUIRED=NO
NATIVE_CLAUDE_USES_SAME_INTAKE_MODEL=YES
WEB_UI_USES_SAME_INTAKE_MODEL=YES EXCEL_CANONICAL_MODEL_DUPLICATION=0
EXCEL_OPENSPEC_DUPLICATION=0 EXCEL_FIELD_RESOLUTION_DUPLICATION=0
EXCEL_VPLAN_AUTHORITY=NO EXCEL_COVERAGE_AUTHORITY=NO
EXCEL_SIGNOFF_AUTHORITY=NO M5_CURRENT_EXECUTION_GATE_PRESERVED=YES
M6_STARTED=NO M10_5_STARTED=NO M12_STARTED=NO M14_STARTED=NO
REFERENCE_USB_ENV_CONSUMED=NO PRODUCTION_IMPLEMENTATION_STARTED=NO

Run applicable Constitution/Anti-Drift, governance/reference-graph and
Master control-plane consistency tests. Do not run full product
regression unless current governance requires it for roadmap-only
changes.

## Final Report

Report:

EXCEL_INTAKE_ROADMAP_STATUS = READY_FOR_APPROVAL / PARTIAL / BLOCKED
STRUCTURED_EXCEL_INTAKE = `<status>`{=html} EXCEL_TEMPLATE_GENERATION =
`<status>`{=html} EXCEL_INTAKE_IMPORT = `<status>`{=html}
EXCEL_SCHEMA_VALIDATION = `<status>`{=html}
EXCEL_FIELD_CONFLICT_DETECTION = `<status>`{=html} EXCEL_ROUND_TRIP =
`<status>`{=html} ROLE_BASED_EXCEL_INTAKE = `<status>`{=html}
EXCEL_STALE_WORKBOOK_DETECTION = `<status>`{=html} EXCEL_PROVENANCE =
`<status>`{=html} EXCEL_IS_FRONTEND = YES EXCEL_IS_SOURCE_OF_TRUTH = NO
ONE_CANONICAL_INTAKE_ENGINE = YES ONE_CANONICAL_FIELD_RESOLUTION_ENGINE
= YES ONE_CANONICAL_OPENSPEC_MODEL = YES
OPENSPEC_8_FIELD_MODEL_PRESERVED = YES / NO AUTO_DISCOVERY_FIRST = YES /
NO MINIMAL_STRUCTURED_CLARIFICATION = YES / NO
USER_REENTRY_OF_DISCOVERED_FIELDS_REQUIRED = NO / YES
NATIVE_CLAUDE_USES_SAME_INTAKE_MODEL = YES / NO
WEB_UI_USES_SAME_INTAKE_MODEL = YES / NO
EXCEL_CAPABILITIES_ADDED_OR_RECONCILED = `<count>`{=html}
MASTER_CAPABILITY_MATRIX_ROWS = `<count>`{=html}
MASTER_CAPABILITY_MATRIX_MALFORMED_ROWS = `<count>`{=html}
MASTER_CAPABILITY_MATRIX_DUPLICATE_IDS = `<count>`{=html}
AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT = `<count>`{=html}
CURRENT_PROGRAM_POSITION = `<position>`{=html} CURRENT_M5_GATE_PRESERVED
= YES / NO NEXT_RECOMMENDED_GATE = `<current M5 gate>`{=html} M6_STARTED
= NO M10_5_STARTED = NO M12_STARTED = NO M14_STARTED = NO
REFERENCE_USB_ENV_CONSUMED = NO PRODUCTION_IMPLEMENTATION_STARTED = NO

## STOP

After roadmap/control-plane artifacts are reconciled and validated,
STOP.

Do not implement Excel functionality. Do not start M6. Do not start
M10.5. Do not start M12. Do not start M14. Do not consume Reference USB.
Resume the currently approved M5 execution sequence only after explicit
review.
