# DE/DV Role-Based Human-in-the-Loop (HITL) Architecture

ROADMAP / ARCHITECTURE / GOVERNANCE reconciliation only. Nothing in
this document is implemented by producing it — no new engine, service,
or code path exists as a result of this file.

## Highest architecture decision (frozen)

> **L5DGVA has ONE Generic Verification Workflow. DE and DV are not
> separate pipelines; they are human authority roles participating in
> the same end-to-end lifecycle.**

```
                  L5DGVA Generic Workflow
                           |
                    Human Decision?
                           |
              +------------+------------+
              |            |            |
           DESIGN      VERIFICATION    SHARED
              |            |            |
              v            v            v
             DE            DV         DE + DV
```

`ROLE_BASED_HUMAN_IN_THE_LOOP` — no existing equivalently-named
capability was found in `MASTER_CAPABILITY_STATUS_MATRIX.csv` prior to
this reconciliation (checked before adding a new row, per instruction
Section 3's "preserving an existing equivalent name if present").

**Explicitly prohibited by this architecture** (Section 3): a
DE-specific orchestration engine, a DV-specific orchestration engine,
duplicated role-specific verification pipelines, duplicated Knowledge
Brains, or duplicated per-level (IP/Subsystem/System) engines. This
reconciliation adds **zero** new engines — every artifact below is a
routing/classification layer over the existing single generic workflow,
`engine.py`/`graph.py`, and the single Knowledge Brain.

## One common DE/DV lifecycle (Section 4)

```
Create/Open Project -> Select IP/Subsystem/System-Level -> Provide Inputs
-> OpenSpec Intake -> Automatic Discovery -> Evidence/Confidence/Gap
-> Minimal Clarification -> Knowledge Retrieval -> Verification Architecture
-> vPlan -> Human Review when justified -> VIP/UVM Generation
-> Test/Sequence/Scenario/Firmware -> Checker/Scoreboard/Assertion/Coverage
-> Build/Smoke/Execution -> Regression -> RCA/Fix/Rerun -> Coverage Closure
-> Requirements/Evidence Traceability -> Waiver -> Signoff
-> Experience Consolidation -> Knowledge Promotion -> Next Project Improvement
```

DE and DV differences are **authority/gate/escalation/learning**
differences overlaid on this one lifecycle — never a second workflow.
This reconciles directly onto the existing 17-stage E2E flow already
tracked in `MASTER_END_TO_END_DV_STATUS.md` (see
`DE_DV_E2E_ROLE_MATRIX.csv` for the stage-by-stage role overlay).

## Human Authority Model (Section 5)

### `DESIGN_AUTHORITY` (primary role: DE)

Intended DUT behavior, register semantics, reset/IRQ/clock intent,
legal states, firmware programming intent, undocumented behavior,
design limitations, protocol-mode design configuration, RTL/spec
discrepancy from a design-intent perspective, implementation
constraints affecting expected behavior.

### `VERIFICATION_AUTHORITY` (primary role: DV)

Verification architecture, vPlan, feature mapping,
scenario/test/sequence/constraint strategy, checker/scoreboard/assertion
strategy, coverage model/closure, verification waiver, verification risk
acceptance, verification signoff.

### `SHARED_AUTHORITY` (role: DE + DV)

Reserved for genuine cross-domain decisions only: Spec/RTL
contradiction, feature interpretation affecting closure, a design
limitation requiring a verification waiver, requirement interpretation
affecting signoff. **`SHARED` is never a fallback for poor
classification** — a question that is really `DESIGN` or
`VERIFICATION` must be classified as such, not defaulted to `SHARED` to
avoid the classification decision.

## Roles are logical, not user identity (Section 6)

`DESIGN`/`VERIFICATION`/`SHARED` are logical authority roles. They must
never be derived from username, OS account, workstation, repository
path, gateway host, or remote EDA host — consistent with Article 0's
`LOCATION_INDEPENDENT` dimension. A future project configuration layer
may map real people to these roles; the architecture itself never
special-cases a person or machine.

## Article 0 alignment (Section 24)

```
LOCATION_INDEPENDENT      = roles are logical, never tied to
                             username/host (Section 6, directly enforced
                             by this architecture's own design)
EVIDENCE_GROUNDED         = every escalation (HumanGate, Question) must
                             carry EVIDENCE_REFS + CONFIDENCE -- no
                             role-based escalation is evidence-free
KNOWLEDGE_DRIVEN          = Knowledge Retrieval precedes Clarification
                             in the one common lifecycle -- retrieve
                             before asking, never ask blind
CONTINUOUS_EVOLUTION      = DE/DV interactions become
                             ROLE_AWARE_EXPERIENCE records -- role
                             information is preserved through to the
                             learning loop, not discarded after the
                             decision is made
END_TO_END_DV_ALIGNMENT   = the same role model spans Intake -> Signoff,
                             with no level-specific or stage-specific
                             re-derivation
```

## What this reconciliation does NOT do

Per Section 0/32: does not implement `ClarificationService`,
`HumanGate`, `QuestionOwner` routing, `RoleAwareExperienceRecord`, or
any dashboard. Does not start M5–M13. Does not modify
Parent/v50/b7a/b7b/b8. Does not consume Reference USB. Does not create a
second Knowledge Brain, a second Master Capability Matrix, or a second
E2E status document — every artifact here extends an existing one.
