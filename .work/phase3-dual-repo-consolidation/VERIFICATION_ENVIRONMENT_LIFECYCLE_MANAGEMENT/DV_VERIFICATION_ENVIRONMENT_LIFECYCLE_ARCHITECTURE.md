# DV Verification Environment Lifecycle Architecture

ROADMAP / REQUIREMENTS / ARCHITECTURE reconciliation only. No production
code implements this document. Does not start M10.5. Does not interrupt
or replace the currently approved M5 execution sequence.

This document extends, and does not compete with,
`VERIFICATION_ENVIRONMENT_LIFECYCLE_ARCHITECTURE.md` (the prior wave's
own architecture doc, commit `f09e386`) -- that document froze
`CREATE_LIFECYCLE`/`MAINTAIN_LIFECYCLE` and the 5-class artifact
ownership model; this one adds the DV authority freeze and the Native
Claude Fast Maintenance dual-mode architecture on top of it, without
restating what is already frozen there.

## Frozen product principles (Section 0)

```
1. L5DGVA-generated verification environments are lifecycle-managed DV
   assets, not disposable outputs.
2. DE owns Design Intent and Design Fix.
3. DV owns Verification Architecture, Verification Environment,
   maintenance, closure and Verification Signoff.
4. Native Claude CLI is a lightweight interaction/execution path, not a
   second product, authority model, Knowledge Brain or verification
   engine.
5. Fast Path and Full L5DGVA share project identity, evidence,
   ownership, provenance, change, validation and signoff contracts.
6. MINIMUM_SUFFICIENT_EXECUTION: the lightest safe mechanism with
   sufficient evidence.
7. Fast means less orchestration overhead, not weaker governance.
```

## Authority model (Section 3, frozen)

```
DESIGN_AUTHORITY                    = DE
VERIFICATION_AUTHORITY              = DV
VERIFICATION_ENVIRONMENT_AUTHORITY  = DV   (new this wave -- explicitly
                                       distinct from the general
                                       VERIFICATION_AUTHORITY, naming DV
                                       as the owner of the ENVIRONMENT
                                       artifact itself, not just
                                       verification strategy)
VERIFICATION_SIGNOFF_AUTHORITY      = DV   (new this wave -- explicit)
SHARED_AUTHORITY                    = DE+DV, genuine cross-domain only
```

Native Claude CLI and L5DGVA agents are **execution mechanisms, never
human authorities** -- this is the same "the agent is a tool, not an
accountable party" principle CLAUDE.md's own "Agent-Authored Change
Accountability" section already establishes, applied explicitly to the
Fast Path.

## Design-Defect Invariant (Section 4, frozen)

Neither Fast Path nor Full L5DGVA may alter the verification environment
merely to hide defective DUT behavior. A real DUT/RTL/design defect
routes:

```
RCA -> DESIGN -> DE -> RTL/Spec fix -> new design revision -> change
impact -> DV environment update -> regression/coverage/re-signoff
```

A temporary workaround requires an explicit waiver with provenance,
scope, a removal condition, and disclosed signoff impact -- never a
silent environment edit that makes a real defect stop showing up.

## CREATE_LIFECYCLE / MAINTAIN_LIFECYCLE (Sections 5-6, reconciled with the prior wave)

`CREATE_LIFECYCLE` (unchanged, already the 17-stage table in
`MASTER_END_TO_END_DV_STATUS.md`):

```
OpenSpec -> Discovery -> Knowledge -> Clarification -> Verification
Architecture -> vPlan -> Generation -> Execution -> Regression -> RCA ->
Coverage Closure -> Traceability/Waiver -> Signoff -> Learning
```

`MAINTAIN_LIFECYCLE` -- **this wave replaces the prior wave's 12-stage
version with a more detailed 18-stage version**, reconciled (not
duplicated) in `MAINTAIN_LIFECYCLE_E2E_MATRIX.csv`:

```
Qualified Environment -> Attach -> Rehydrate -> Semantic Drift/Change ->
Debug/Evidence -> RCA -> Role Routing -> Impact -> Change Request/Plan
-> Ownership -> Change Workspace -> Controlled Modification/Semantic
Merge -> Selective Regression -> Coverage Delta -> Evidence
Invalidation -> Re-Signoff -> Qualified Snapshot -> Learning
```

The prior wave's 12-stage version is superseded by this 18-stage
version, which is strictly more granular over the same real span (it
splits "Reopen/Import" into "Attach"+"Rehydrate", adds explicit
"Debug/Evidence"+"RCA"+"Role Routing" stages before Impact, and adds
"Ownership"+"Qualified Snapshot" as their own stages) -- no capability
this reconciles is removed, every `CAP-VELM-001..017` row from the prior
wave keeps its own real evidence and disposition unchanged.

## Dual Maintenance Modes (Section 7)

```
FAST_MAINTENANCE_MODE      = Native Claude CLI inside the DV project,
                              for bounded/local debug, small sequence/
                              test/checker/scoreboard/config fixes,
                              evidence inspection, focused validation
FULL_L5DGVA_MAINTENANCE_MODE = full orchestration for architecture/
                              topology changes, multi-subsystem impact,
                              unclear ownership, low confidence, complex
                              RCA, broad regeneration, coverage closure,
                              protected artifacts, broad evidence
                              invalidation, signoff-critical work
```

These are **two execution modes of ONE maintenance architecture** --
not two products. See `NATIVE_CLAUDE_FAST_MAINTENANCE_ARCHITECTURE.md`
for the Fast Path's own detail.

## CAP-M5-TOPTB-001 relationship (Section 15, review only)

Per this task's own explicit instruction, `CAP-M5-TOPTB-001`'s M5
disposition and implementation (`CLOSED`, `MIGRATE_WITH_ADAPTATION`,
commit `bd5c560`) are unchanged. It is mapped this wave as possible
`FOUNDATION` for:

```
ARTIFACT_OWNERSHIP_MODEL (CAP-VELM-004)             = YES (unchanged
  from prior wave)
USER_MODIFICATION_PRESERVATION (CAP-VELM-032)       = YES -- the
  strongest real, working, already-tested precedent in this entire
  family for exactly this capability (for one artifact type: a top TB)
SAFE_INCREMENTAL_REGENERATION (CAP-VELM-009)        = YES (unchanged
  from prior wave)
UVM_SEMANTIC_MERGE (CAP-VELM-010)                   = NO (unchanged
  from prior wave -- whole-file preserve-or-replace is not a merge)
CONTROLLED_ENVIRONMENT_MODIFICATION (CAP-VELM-031)  = PARTIAL -- its
  read-only-discovery/never-mutate-original-in-place discipline is real
  safety-mechanism precedent, but CONTROLLED_ENVIRONMENT_MODIFICATION
  itself requires an actual EDIT-with-rollback mechanism CAP-M5-TOPTB-001
  does not provide (it only ever decides whether to reuse a file, never
  edits one)
```

`FOUNDATION != OPERATIONAL_LIFECYCLE_CAPABILITY` throughout -- no
capability in this document is claimed operational because a related
foundation exists.

## Validation

```
CREATE_LIFECYCLE_DEFINED          = YES
MAINTAIN_LIFECYCLE_DEFINED        = YES
DV_OWNS_VERIFICATION_ENVIRONMENT  = YES
M4_6_CONTEXT_ARCHITECTURE_PRESERVED = YES (nothing in this document is
  added to CLAUDE.md's ALWAYS_ON core; all detail stays TASK_SCOPED in
  this work-area tree, per this task's own Section 1/2 instruction)
CURRENT_M5_GATE_PRESERVED         = YES
PRODUCTION_IMPLEMENTATION_STARTED = NO
REFERENCE_USB_ENV_CONSUMED        = NO
```
