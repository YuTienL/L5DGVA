# Role-Aware Experience Learning Requirements (Sections 13-16)

Not implemented this wave — future M8 requirements, extending the
existing (and, per `MASTER_CONTINUOUS_EVOLUTION_STATUS.md`, partly
**confirmed-broken**) internal continuous-experience-learning loop.

## M8 scope (Section 13)

M8 must include: Knowledge Brain operationalization, Continuous
Research Evolution (already real — `CAP-CE-017`), Continuous Project
Experience Learning (confirmed `PARTIAL`/`ABSENT` — `CAP-CE-018`,
`P0`), **Role-Aware Experience Learning** (this document),
DE/DV interaction learning, clarification learning, RCA role-aware
learning, coverage/signoff learning, and Knowledge Domain
Classification.

**Use ONE Knowledge Brain.** This reconciliation adds role-awareness as
metadata on top of the single existing 5-tier Memory system
(`memory.py`/`memory_router.py`/`memory_vault.py`) — it does not
propose a second knowledge store for DE vs. DV.

## Knowledge Domain Classification (Section 14)

```
KNOWLEDGE_DOMAIN = DESIGN | VERIFICATION | SHARED
```

- **DESIGN examples**: register side effects, reset sequence, IRQ
  behavior, clocks, FW requirements, design limitations.
- **VERIFICATION examples**: architecture, stimulus/sequence/constraint
  patterns, scoreboard/checker/assertion, RCA, coverage closure,
  waiver/signoff lessons.
- **SHARED examples**: Spec/RTL resolution, feature interpretation,
  design limitation + verification strategy combined.

This is **applicability metadata on existing memory records**, not a
separate storage tier — a `KNOWLEDGE_DOMAIN` field added to the existing
Memory/Obsidian schema, never a fourth or fifth memory system alongside
the existing 5 tiers.

## Role-Aware Experience Record (Section 15)

Future schema (extends the existing Experience-record concept already
named in `CANONICAL_CAPABILITY_SUPERSET_MATRIX.md`'s
`PROJECT_EXPERIENCE_EXTRACTION` row, `CAP-CE-008`, itself confirmed
`PARTIAL` — no unified Experience record type exists anywhere yet):

```
EXPERIENCE_ID
SOURCE_PROJECT
VERIFICATION_LEVEL
PROTOCOL
KNOWLEDGE_DOMAIN        -- DESIGN | VERIFICATION | SHARED
HUMAN_ROLE              -- who was actually involved in the decision
WORKFLOW_STAGE          -- one of the 17 stages
OBSERVATION
QUESTION_OR_DECISION
EVIDENCE_REFS
DECISION
OUTCOME
CONFIDENCE
APPLICABILITY_SCOPE
COUNTEREXAMPLES
GENERALIZATION_STATE
PROMOTION_STATE
```

Reuse existing schema fields wherever the pre-existing (unbuilt)
Experience-record concept already names an equivalent field — this is
an extension, not a rewrite.

## Role-Aware RCA Learning (Section 16)

```
Regression Failure -> Automatic RCA -> DESIGN/VERIFICATION/SHARED
  classification (RCA_ROLE_ROUTING.md) -> human escalation if needed
  -> validated root cause -> fix -> rerun -> experience extraction
  -> knowledge promotion -> future RCA improvement
```

Promotion requires real evidence and applicability analysis — **one
project's result does not automatically become a universal lesson**,
consistent with the existing `memory_router.promote_to_organizational()`
gate's `confirmation_count >= 2` discipline.

## Not implemented during this task

`CAP-M8-EXPLOOP-001` (the confirmed-broken `EXPERIENCE_READY` event
wiring) remains the real, pre-existing blocker for the entire internal
learning loop, role-aware or not — adding role-awareness to a broken
pipe does not make it flow. This document records the future schema
only; it fixes nothing.
