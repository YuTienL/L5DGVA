# Verification Environment Lifecycle Architecture

ROADMAP / REQUIREMENTS / DEPENDENCY reconciliation only. Nothing in this
document is implemented by producing it -- no new engine, service, or
code path exists as a result of this file. Preserves the currently
executing M5 sequence unchanged; does not start M10.5.

## Frozen product requirement

**L5DGVA SHALL support two first-class verification lifecycles:**

```
                    L5DGVA Generic Workflow
                             |
              +--------------+--------------+
              |                             |
       CREATE_LIFECYCLE              MAINTAIN_LIFECYCLE
              |                             |
OpenSpec -> Discovery ->          Existing Qualified Env
vPlan -> Generation ->            -> Reopen/Import ->
Execution -> Regression ->        Semantic Change Detection ->
RCA -> Coverage Closure ->        Change Impact Analysis ->
Signoff ->                        Change Plan ->
Experience Learning               Controlled Modification ->
                                   Safe Incremental Regeneration ->
                                   Semantic Merge ->
                                   Selective Regression ->
                                   Coverage Delta ->
                                   Evidence Invalidation ->
                                   Incremental Re-Signoff ->
                                   Maintenance Experience Learning
```

Both lifecycles are stages **on the same ONE generic L5DGVA workflow**,
exactly the same relationship `DESIGN_AUTHORITY`/`VERIFICATION_AUTHORITY`
have to the one generic DE/DV workflow -- CREATE and MAINTAIN are not two
engines, two Knowledge Brains, or two clarification services. This
document freezes the requirement and reconciles it into the roadmap; it
does not build either lifecycle's MAINTAIN half.

## Capability family: `VERIFICATION_ENVIRONMENT_LIFECYCLE_MANAGEMENT`

17 named capabilities, registered this wave in
`MASTER_CAPABILITY_STATUS_MATRIX.csv` as `CAP-VELM-001`..`CAP-VELM-017`
(see `VERIFICATION_ENVIRONMENT_MAINTENANCE_CAPABILITY_MATRIX.csv` for the
full per-capability table). **Every one of the 17 is `ROADMAP_DEFINED`,
`IMPLEMENTED=NO` this wave** -- registering a name in the matrix is not
implementation, and this document does not claim otherwise anywhere.

## Artifact ownership model

Rather than inventing a schema, this model is derived from real,
already-verified precedent already present in canonical this session:

| Ownership class | Definition | Existing Canonical precedent (real, not invented) |
|---|---|---|
| `L5_MANAGED` | Fully harness-generated; regenerable freely, but only under a real provenance/lifecycle contract (never blind overwrite-and-forget) | Every file `ProtocolEnvGenerator`/`UVMEnvironmentGenerator` emits fresh today, e.g. `_soc_tb_top()`'s own always-fresh output before `CAP-M5-TOPTB-001` |
| `USER_MANAGED` | Human/DE-authored; **must not be automatically overwritten** | `CAP-M5-TOPTB-001`'s own real, just-merged, human-decision-gated (HD-1/V11 SS247) mechanism: `discover_existing_top_tb()` -> `compare_against_generated_top()` -> preserve verbatim unless proven `DIVERGENT`. This is not a hypothetical requirement -- it is the first real, working instance of `USER_MANAGED` semantics in canonical, already qualified |
| `SHARED_MANAGED` | Co-owned; requires a controlled semantic merge (never a blind overwrite, never a blind skip) before regeneration touches it | Not yet instantiated in canonical -- `UVM_SEMANTIC_MERGE` (`CAP-VELM-010`) is the capability that would give this class a real mechanism |
| `GENERATED_REGION` | A marker-delimited sub-file region that stays regenerable even inside an otherwise `USER_MANAGED`/`SHARED_MANAGED` file | Real existing precedent: `bind_mechanism_generator.py`'s own DV_UVM two-hook convention (`` `ifdef DV_UVM `` / `` `include "dv_uvm_hook.svh" ``, which `reference_uvm_dut_top_integration_manifest.py`'s `_find_dv_uvm_hooks()` already detects as a real fact) is exactly a `GENERATED_REGION` marker inside an otherwise `USER_MANAGED` top TB |
| `PROTECTED` | Requires explicit recorded human/authority approval before **any** modification, regardless of nominal owner | Real existing precedent: `.dv-harness/soc-composer/subsystem_environment_registry.json` entries, written only by `engine.py`'s `_persist_subsystem_registry_entry()` on a real SIGNOFF PASS -- already a qualified-snapshot-shaped artifact no ordinary regeneration path may silently rewrite |

No duplicate schema was created -- `L5_MANAGED`/`USER_MANAGED` map onto
mechanisms that already exist and are already tested; `SHARED_MANAGED`/
`GENERATED_REGION` (as a formalized, reusable concept)/`PROTECTED` (as a
formalized, reusable concept) are the genuinely new roadmap surface this
family adds.

## Frozen safety principles

```
USER_MANAGED artifacts must not be automatically overwritten.
PROTECTED artifacts require explicit authority before modification.
L5_MANAGED artifacts may be regenerated only under provenance and
  lifecycle contracts.
SHARED_MANAGED artifacts require controlled semantic merge.
Regeneration must not mean whole-environment overwrite.
```

The last line is itself already evidenced: `CAP-M5-TOPTB-001`'s own
preservation is whole-**file**-atomic (never partial merge within one
file), but critically, it is not whole-**environment** overwrite either
-- `compose_soc_environment()` regenerates `soc_virtual_sequencer.sv` and
`soc_composition_manifest.json` fresh on every run while independently
deciding `soc_tb_top.sv`'s own fate file-by-file. `SAFE_INCREMENTAL_
REGENERATION` (`CAP-VELM-009`) generalizes this file-by-file granularity
across a whole environment, not just the one file this wave's M5 work
happened to touch.

## Roadmap ownership (frozen)

```
M5    = semantic-merge and top-TB-preservation FOUNDATIONS only
        (CAP-M5-ARCH-002's ARCH-03 evidence-annotation wire, CAP-M5-
        TOPTB-001's whole-file preservation mechanism -- both real,
        already merged, neither claims to BE UVM_SEMANTIC_MERGE or
        SAFE_INCREMENTAL_REGENERATION as OPERATIONAL_LIFECYCLE_
        CAPABILITY; see the FOUNDATION-vs-OPERATIONAL distinction below)
M8    = MAINTENANCE_EXPERIENCE_LEARNING / CHANGE_IMPACT_PREDICTION_
        LEARNING FOUNDATIONS (Knowledge Brain / Continuous Capability
        Evolution infrastructure this family's own experience-learning
        capabilities would plug into)
M9    = VERIFICATION_ENVIRONMENT_IR FOUNDATION where appropriate (generic
        IP/Subsystem/System-Level representation)
M10   = vPlan / Coverage / Traceability / Signoff FOUNDATIONS this
        family's COVERAGE_DELTA_ANALYSIS/INCREMENTAL_RESIGNOFF capabilities
        would extend
M10.5 = PRIMARY OWNER of VERIFICATION_ENVIRONMENT_LIFECYCLE_MANAGEMENT as
        an OPERATIONAL_LIFECYCLE_CAPABILITY family
M11   = USB Golden must qualify BOTH (A) from-scratch generation and
        (B) maintenance of an existing qualified environment after RTL/
        spec change while preserving user customization -- see
        USB_GOLDEN_MAINTENANCE_QUALIFICATION_REQUIREMENTS.md
M12   = productization / UX of the maintenance workflow
M13   = strict-superset/final qualification must include lifecycle-
        management capability
```

## FOUNDATION vs. OPERATIONAL_LIFECYCLE_CAPABILITY -- explicit distinction

A capability is `FOUNDATION` when a real, already-merged mechanism
provides evidence the concept is buildable and partially demonstrated,
but does not itself constitute the general, callable, MAINTAIN_LIFECYCLE-
integrated capability. A capability is `OPERATIONAL_LIFECYCLE_CAPABILITY`
only once it is wired into the actual MAINTAIN_LIFECYCLE stage sequence,
consumed by a real caller in that role, and evidenced end-to-end.

**No capability in this family is `OPERATIONAL_LIFECYCLE_CAPABILITY`
this wave.** `CAP-M5-ARCH-002`/`CAP-M5-TOPTB-001` are cited as
`FOUNDATION` evidence for `UVM_SEMANTIC_MERGE`/`ARTIFACT_OWNERSHIP_
MODEL`/`SAFE_INCREMENTAL_REGENERATION` specifically (see their own
`DEPENDENCIES` column in the capability matrix) -- not marked
implemented for the family as a whole. This is the explicit,
instruction-mandated distinction, not a default assumption.

## DE/DV HITL integration

Reuses the existing, frozen `DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md`
model verbatim -- no second maintenance-specific HITL model created:

```
Design-intent changes            -> may escalate to DESIGN_AUTHORITY/DE
Verification strategy/coverage/
  waiver/signoff decisions       -> may escalate to VERIFICATION_
                                     AUTHORITY/DV
Cross-domain changes             -> may use SHARED_AUTHORITY/DE+DV
```

`ONE_GENERIC_MAINTENANCE_WORKFLOW = YES`. No `DE-specific maintenance
engine` or `DV-specific maintenance engine` is created or implied
anywhere in this document -- `MAINTAIN_LIFECYCLE`'s 12 stages are one
generic sequence; role/authority is an overlay, identical in shape to
how `DE_DV_E2E_ROLE_MATRIX.csv` already overlays the 17-stage
`CREATE_LIFECYCLE` table without duplicating it.

## Continuous Capability Evolution integration

```
maintenance decision -> actual modification outcome -> regression
outcome -> coverage delta -> re-signoff outcome -> Experience Candidate
-> applicability/generalization -> Knowledge Promotion -> improved
future change-impact prediction and maintenance generation
```

This is the SAME internal learning loop Article 0's P4
`CONTINUOUS_EVOLUTION` dimension and the existing Engineering Memory
Policy already define (`Hypothesis -> Evidence -> Confidence ->
Validation -> Action`, `memory_router.py`'s admission gates) --
`MAINTENANCE_EXPERIENCE_LEARNING`/`CHANGE_IMPACT_PREDICTION_LEARNING`/
`SEMANTIC_MERGE_EXPERIENCE_LEARNING` are new INSTANCES of that one loop
applied to maintenance-shaped experience, not a second loop or a second
Knowledge Brain.

## CAP-M5-TOPTB-001 roadmap/dependency relationship (Section: review only)

Per this task's own explicit instruction, `CAP-M5-TOPTB-001`'s M5
disposition and implementation (`MIGRATE_WITH_ADAPTATION`, `CLOSED`,
commit `bd5c560`) are **not** changed by this reconciliation. Its
relationship to this new family:

```
CAP-M5-TOPTB-001 is a FOUNDATION dependency for:
  ARTIFACT_OWNERSHIP_MODEL (CAP-VELM-004)        = YES -- the real,
    working USER_MANAGED precedent this whole ownership model is
    grounded in (see the ownership-model table above)
  SAFE_INCREMENTAL_REGENERATION (CAP-VELM-009)   = YES -- proves
    file-by-file (not whole-environment) regeneration granularity is
    achievable in this codebase today
  UVM_SEMANTIC_MERGE (CAP-VELM-010)              = NO -- CAP-M5-TOPTB-001
    is whole-file preserve-or-replace, never a merge; it demonstrates
    the ADJACENT problem (recognizing something must not be silently
    replaced) but contributes no merge mechanism itself
```

## Validation (Section: this document's own required checks)

```
CREATE_LIFECYCLE_DEFINED               = YES
MAINTAIN_LIFECYCLE_DEFINED             = YES
ONE_GENERIC_MAINTENANCE_WORKFLOW       = YES
SEPARATE_DE_DV_MAINTENANCE_ENGINES     = NO
ARTIFACT_OWNERSHIP_MODEL               = ROADMAP_DEFINED
USER_MANAGED_OVERWRITE_ALLOWED         = NO
SAFE_INCREMENTAL_REGENERATION          = ROADMAP_DEFINED
UVM_SEMANTIC_MERGE                     = ROADMAP_DEFINED
SELECTIVE_REGRESSION                   = ROADMAP_DEFINED
COVERAGE_DELTA                         = ROADMAP_DEFINED
EVIDENCE_INVALIDATION                  = ROADMAP_DEFINED
INCREMENTAL_RESIGNOFF                  = ROADMAP_DEFINED
MAINTENANCE_EXPERIENCE_LEARNING        = ROADMAP_DEFINED
M5_CURRENT_EXECUTION_GATE_PRESERVED    = YES (unchanged: Cohort 3 /
                                          CAP-M5-VIP-001)
REFERENCE_USB_ENV_CONSUMED             = NO
PRODUCTION_IMPLEMENTATION_STARTED      = NO
```
