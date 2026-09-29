# M11 — USB Excel & KC Qualification Requirements

Status: registration for future M11. `M11_STARTED = NO`.
`USB_EXCEL_KC_LEARNING_QUALIFICATION` added as a scenario alongside
M11's existing quad-scope (per
`USB_GOLDEN_MAINTENANCE_QUALIFICATION_REQUIREMENTS.md`: (A) from-scratch
generation, (B) maintenance of an existing qualified environment, (C) a
bounded maintenance defect solved through Native Claude Fast Path, (D) a
Fast Path task correctly escalating to Full L5DGVA) — a fifth named
scenario, not a replacement for the other four.

## M11 scenario definition

`USB_EXCEL_KC_LEARNING_QUALIFICATION` must cover, end to end:

```
USB Golden inputs -> Canonical Intake/Discovery/Field Resolution ->
USB environment generation -> Excel V1 -> qualification -> gaps ->
KC pipeline -> new independent generation -> KC retrieval/consumption ->
Excel V2 -> V1/V2 comparison
```

Not executed now — this document defines the scenario's own required
shape for whenever M11 actually runs it.

## Scope of Excel views qualified

Only the APPLICABLE subset of the 8 Structured Excel Intake views for a
USB SUBSYSTEM/SYSTEM_LEVEL environment: Project Intake, Design
Clarification, Verification Intake, vPlan, System/Subsystem Topology,
Coverage Closure, Signoff, Change Impact — per
`STRUCTURED_EXCEL_INTAKE_ARCHITECTURE.md`'s own 8-view definition,
unchanged. No USB-specific 9th view is introduced.

## Required inputs from other reconciliations (dependency, not duplication)

- `intake_field_resolution.py`'s real OpenSpec 8-field engine (M5
  Cohort 4) — the engine being qualified.
- `CAP-M6-CLARSVC-001`'s eventual `ClarificationService`/Field
  Resolution wiring (M6) — Excel cannot integrate live before this
  exists; this M11 scenario is correspondingly blocked on the same
  dependency every `CAP-EXCEL-*` capability already cites.
- `memory.py`/`memory_router.py`/`memory_vault.py`'s real Knowledge
  Brain (M8) — the KC storage/promotion/retrieval mechanism this
  scenario reuses, unchanged.
- `USB_GOLDEN_MAINTENANCE_QUALIFICATION_REQUIREMENTS.md`'s own
  quad-scope — this scenario runs AFTER at minimum scope (A)
  (from-scratch generation) is itself operational, since Excel V1
  qualifies output from a real generation run.

## Required artifacts this M11 scenario produces (when it actually runs — not produced now)

A qualification report satisfying every metric in
`USB_EXCEL_QUALIFICATION_METRICS.md`, a gap/RCA log per
`USB_EXCEL_GAP_TAXONOMY.md`, Experience/KC Candidates per
`USB_EXCEL_KC_EXTRACTION_CONTRACT.md`, the V1/V2 generation-and-retrieval
record per `USB_EXCEL_KC_REGENERATION_CONTRACT.md`, the comparison
report per `USB_EXCEL_V1_V2_COMPARISON_REQUIREMENTS.md`, and a
`CLOSED_LOOP_KNOWLEDGE_LEARNING_QUALIFICATION.md`-gate verdict.

## Explicit non-goal now

This document does not run any part of the scenario, does not inspect
Reference USB content, and does not produce a real qualification report
— it registers the scenario's own required shape for M11's future work.
