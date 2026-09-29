# Excel Role-Based Workbook Requirements

Status: `ROLE_BASED_EXCEL_INTAKE = DEFINED`, not implemented.

## Reuses the existing DE/DV Role-Based HITL model, does not fork it

`DESIGN_AUTHORITY=DE`, `VERIFICATION_AUTHORITY=DV`,
`VERIFICATION_ENVIRONMENT_AUTHORITY=DV`,
`VERIFICATION_SIGNOFF_AUTHORITY=DV` (frozen by this session's own
DE/DV Role-Based HITL reconciliation). Field routing:

- DESIGN: design intent, RTL, clock, reset, register, IRQ, DMA, design
  semantics.
- VERIFICATION: verification architecture, VIP, test, scoreboard,
  assertion, coverage, regression, waiver, signoff.
- SHARED: genuine cross-domain ambiguity only — never a default bucket
  for "didn't classify it yet."

No separate DE/DV Intake engine is created. `QUESTION_OWNER` in
`EXCEL_INTAKE_FIELD_MAPPING.csv` is a rendering of this existing model.

## 8 example workbook views

Filenames are UX examples, not authority — a real implementation may
name them differently as long as the underlying Canonical model each
renders is unchanged.

### 1. Project Intake (`L5DGVA_Project_Intake.xlsx`)

May show: identity, verification level, protocols, DUT/top, spec/RTL
refs, existing environment, VIP availability, tool/execution-profile
refs, constraints, blockers, unresolved fields. **Never exposes
secrets** — any credential/token/password-classed field is excluded by
construction, the same `memory_router.route_memory()` hard-REJECT
discipline this project already applies to memory records.

### 2. Design Clarification (`L5DGVA_Design_Clarification.xlsx`)

DE-oriented. Shows only unresolved DESIGN-routed questions — never a
verification question, never an already-resolved design field
cluttering the view.

### 3. Verification Intake (`L5DGVA_Verification_Intake.xlsx`)

DV-oriented, symmetric to Design Clarification: only unresolved
VERIFICATION-routed questions.

### 4. vPlan (`L5DGVA_vPlan.xlsx`)

May expose: Requirement -> Feature -> Scenario -> Test -> Sequence ->
Checker/Assertion -> Coverage -> Evidence -> Waiver -> Signoff. Canonical
vPlan (M10-owned) remains the authority; this view never computes or
stores its own vPlan state.

### 5. System Topology (`L5DGVA_System_Topology.xlsx`)

May expose: subsystem, instance, interface, protocol, role, source, VIP,
connectivity, address, clock, reset, IRQ, shared-resource, ownership.
Renders the real Canonical topology/IR (e.g. the bind-location /
connectivity infrastructure this project already has —
`connectivity.py`, `phy_boundary.py`) — never invents topology semantics
of its own.

### 6. Coverage Closure (`L5DGVA_Coverage_Closure.xlsx`)

Presentation/round-trip only. `EXCEL_COVERAGE_AUTHORITY = NO` — this
view is never a second coverage database; it reads and re-presents
whatever the real coverage-closure model (M10-owned) already computed.

### 7. Signoff (`L5DGVA_Signoff.xlsx`)

Presentation/round-trip only. `EXCEL_SIGNOFF_AUTHORITY = NO` — DV
remains the sole signoff authority (`VERIFICATION_SIGNOFF_AUTHORITY=DV`,
frozen). Excel cannot mint, approve, or revoke a signoff decision.

### 8. Change Impact (`L5DGVA_Change_Impact.xlsx`)

Integrates conceptually with `MAINTAIN_LIFECYCLE` (M10.5's own 18-stage
model, already frozen by the earlier VELM reconciliation) but does not
implement M10.5 now — this view is a future presentation surface over
M10.5's own eventual authoritative change-impact model, not a
substitute for it.

## Cross-view invariant

Every view is a projection of the SAME Canonical Intake/Field
Resolution/OpenSpec/vPlan/topology/coverage/signoff state — no view
carries state the others cannot also see through the same real engine.
