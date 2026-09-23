# L5DGVA USB Excel Qualification & KC Learning — Architecture

Status: ROADMAP-ONLY reconciliation. `PRODUCTION_IMPLEMENTATION_STARTED
= NO`. Nothing in this reconciliation touches `dv_harness/`,
Parent/v50/b7a/b7b/b8, or Reference USB — `REFERENCE_USB_ENV_CONSUMED`
stays `NO` throughout, including during this document's own authoring
(no protected USB content was inspected, unzipped, or mined to write
it).

## Mission

Integrate USB Excel Generation Qualification + Knowledge Candidate (KC)
Learning + Regeneration Improvement Measurement into the Canonical
roadmap, as a future M11 scenario. Future M11 must prove the full
closed loop:

```
Generate USB Environment -> Excel V1 -> Qualify -> Gap/RCA ->
Experience/KC Candidate -> Applicability/Counterexamples -> Promotion ->
Knowledge Brain -> New Generation -> KC Retrieval -> KC Consumption ->
Excel V2 -> Re-qualify -> V1/V2 Measurement
```

Not executed now. This document defines the requirement; it does not
run the loop.

## Qualification principle (frozen, the whole point of this reconciliation)

```
EXCEL_FILE_GENERATED != EXCEL_QUALIFIED
KC_STORED != CLOSED_LOOP_LEARNING
KC_PROMOTED != KC_CONSUMED
KC_CONSUMED != IMPROVEMENT_PROVEN
```

Closed-loop success requires the full chain: Experience -> KC Candidate
-> Promotion -> Storage -> Retrieval -> Consumption -> Generation
Behavior Change -> Outcome Measurement. Each arrow is a real, checkable
transition (see `CLOSED_LOOP_KNOWLEDGE_LEARNING_QUALIFICATION.md`) — a
gap anywhere in the chain means the loop has not closed, regardless of
how far it got.

## Reuses two existing real systems — no new engines

### 1. Structured Excel Intake (frozen by the prior reconciliation, unchanged here)

`EXCEL_IS_FRONTEND=YES`, `EXCEL_IS_SOURCE_OF_TRUTH=NO`,
`ONE_CANONICAL_INTAKE_ENGINE=YES`,
`ONE_CANONICAL_FIELD_RESOLUTION_ENGINE=YES`,
`ONE_CANONICAL_OPENSPEC_MODEL=YES`, `AUTO_DISCOVERY_FIRST=YES`,
`MINIMAL_STRUCTURED_CLARIFICATION=YES` — all preserved unchanged. USB
qualification TESTS the Canonical Excel frontend
(`intake_field_resolution.py`, real and tested since M5 Cohort 4); it
never creates a USB-specific Excel semantic engine. The 8 workbook
views this qualifies (Project Intake, Design Clarification,
Verification Intake, vPlan, System/Subsystem Topology, Coverage
Closure, Signoff, Change Impact) are the same 8 defined in
`STRUCTURED_EXCEL_INTAKE_ARCHITECTURE.md` — only the applicable subset
for USB is qualified, never a USB-only 9th view.

### 2. Knowledge Brain / 5-tier Memory (real, existing canonical infrastructure)

Confirmed by direct read this reconciliation, not assumed: canonical
already has a real, substantial Knowledge Brain
(`dv_harness/memory.py`, `dv_harness/memory_router.py`,
`dv_harness/memory_vault.py`) implementing:

- **5 memory tiers**: `WorkingMemoryStore`, `JobMemoryStore`,
  `ProjectMemoryStore`, plus `ENGINEERING_MEMORY` and
  `ORGANIZATIONAL_MEMORY` (routed, not separately classed, per
  `memory_router.py`'s own comments — `route_and_store()`,
  `route_memory()`).
- **Real promotion gates**: `engineering_admission_gate()`,
  `organizational_admission_gate()`, `promote_to_organizational()` — the
  organizational gate requires `confirmation_count >= 2` (a SECOND,
  genuinely independent confirmation, not the same evidence counted
  twice) before anything reaches organizational (cross-project) scope.
- **Real retrieval**: `MemoryRetriever.search()` (`dv_harness/memory.py`).

`M8` owns and this reconciliation REUSES this exact system for KC
Extraction/Applicability/Generalization/Contradiction-Counterexample
handling/Promotion/Retrieval/Consumption evidence and Knowledge Brain
persistence — `ONE_KNOWLEDGE_BRAIN=YES` is preserved: **no USB-only
Knowledge Brain, no second promotion gate, no second retrieval
mechanism is proposed anywhere in this reconciliation.**

## The closed loop, mapped onto real canonical mechanisms

```
Generate USB Environment          -- M11's own generation pipeline (future)
        |
Excel V1                          -- Structured Excel Intake frontend (M12-owned UX, M5-Cohort-4-owned engine)
        |
Qualify (completeness/correctness/
  evidence/auto-discovery/         -- NEW this reconciliation: qualification
  derivation/question-quality/        metrics + gap taxonomy (Sections 5-9)
  schema/round-trip/conflict/
  stale/traceability)
        |
Gap -> RCA (root-cause classified   -- NEW this reconciliation: gap taxonomy +
  BEFORE any KC is proposed)           root-cause taxonomy (Section 9)
        |
Experience/KC Candidate           -- REUSES M8's existing Experience/KC contract shape
        |
Applicability/Counterexamples ->  -- REUSES engineering_admission_gate() /
  Promotion                          organizational_admission_gate() /
                                      promote_to_organizational()
        |
Knowledge Brain                   -- REUSES memory.py / memory_router.py / memory_vault.py, unchanged
        |
New Generation                    -- M11's own generation pipeline, a SECOND independent session
        |
KC Retrieval                      -- REUSES MemoryRetriever.search(), with real, recorded query/context
        |
KC Consumption                    -- NEW evidence requirement: proof the retrieved KC actually
                                      changed generation/planning behavior, not merely was returned
        |
Excel V2                          -- Same Structured Excel Intake frontend, second generation
        |
Re-qualify                        -- Same qualification metrics/gap taxonomy, applied to V2
        |
V1/V2 Measurement                 -- NEW this reconciliation: comparison requirements (Section 13)
```

## Wave ownership (frozen, not reopened)

| Wave | Owns |
|---|---|
| M8 | Experience/KC extraction, applicability/generalization, contradiction/counterexample handling, promotion, retrieval, consumption evidence, Knowledge Brain persistence — all REUSED, not rebuilt, by this reconciliation |
| M11 | The actual USB Golden qualification workload AND the Excel/KC learning qualification defined here — this reconciliation's own capabilities are primarily M11-owned |
| M12 | Polished Structured Excel generation/import/schema/round-trip/role UX (unchanged from the prior reconciliation) |
| M14 | May later consume PRODUCTIVITY metrics (clarification time, manual entry, error rate). **Distinct from M11**: M11 measures FUNCTIONAL quality / learning-loop behavior (did the loop actually close, did quality improve); M14 measures PRODUCTIVITY / expertise amplification (was a human faster/more effective). Never conflated — a V1/V2 quality improvement is not itself a productivity claim, and vice versa. |

## Reference USB boundary (unchanged, re-affirmed)

This reconciliation defines FUTURE USB Golden use — it does not inspect,
read, unzip, or mine `USB_UVM_Handoff` or any other protected Reference
USB content. `REFERENCE_USB_ENV_CONSUMED` remains `NO`. Consumption
begins only when the already-existing, separately-approved USB Golden
gate (M11, quad-scoped: from-scratch generation, maintenance of an
existing qualified environment, Fast-Path-solved bounded defects,
Fast-Path-to-Full-L5DGVA escalation — per
`USB_GOLDEN_MAINTENANCE_QUALIFICATION_REQUIREMENTS.md`) explicitly
permits it.
