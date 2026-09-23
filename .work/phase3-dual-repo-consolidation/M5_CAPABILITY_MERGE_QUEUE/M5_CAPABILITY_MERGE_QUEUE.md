# M5 N-Way Capability Semantic Merge -- Capability Merge Queue

Built per the approved M5-0 checkpoint (`a5ebbdc`, `CANONICAL_WORKTREE_READY_FOR_M5=YES`,
`AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT=7`) and the explicit M5-start instruction:
"Create the M5 Capability Merge Queue first. Do NOT begin by copying files."

This document is COHORT 0's own deliverable (M5 prerequisite/dependency revalidation).
No production code is touched by this file.

## 0. Pre-work verification (instruction items 1-6)

| # | Requirement | Result |
|---|---|---|
| 1 | Read Master Capability Status Matrix | Done -- `MASTER_CAPABILITY_STATUS_MATRIX.csv`, 91 rows, 24 `PRIMARY_OWNER_WAVE==M5` |
| 2 | Read M5 prerequisite matrix | Done -- `M4_M5_PREREQUISITE_MATRIX.csv`, 10 target files (3 already CLOSED/RESOLVED in M4: `register_excel_extract.py`/`memory_vault.py`/`loop_telemetry.py`; 7 genuinely open) |
| 3 | Read the approved M5 migration-input registry | **No file of that literal name exists.** The closest real artifact is this session's own M5-0 commit `4f45af5` + `AGENT_TASK_LIFECYCLE_ANALYSIS.md`, which registered `dv_harness/task_boundary_conformance.py` and `dv_harness/intake_field_resolution.py` as Parent-only `SOURCE_EVIDENCE_ONLY` migration inputs (`CAP-ATL-004`/`CAP-ATL-007`). Treated as the registry of record; disclosed rather than silently assumed to exist elsewhere. |
| 4 | Read DE/DV Role-Based HITL architecture | Done -- `DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md` in full. Binding constraint carried into every cohort below: `ONE_GENERIC_DE_DV_WORKFLOW`, no DE/DV engine, `DESIGN_AUTHORITY`/`VERIFICATION_AUTHORITY`/`SHARED_AUTHORITY` as logical roles never derived from identity/host. |
| 5 | Read Article 0 + applicable task-scoped governance | Done -- `CLAUDE.md` lines 49-143 (5 dimensions: `LOCATION_INDEPENDENT`/`EVIDENCE_GROUNDED`/`KNOWLEDGE_DRIVEN`/`CONTINUOUS_EVOLUTION`/`END_TO_END_DV_ALIGNMENT`). Every capability's `ARTICLE_0_COMPLIANCE` field below is graded against these 5. |
| 6 | Verify Parent/v50/b7a/b7b/b8 source integrity | **Byte-exact match, all 5**, re-verified this wave via direct `git rev-parse` in each source tree (not trusted from the doc): Parent `3e9dd736...` (`D:\DV\Task\DV_Agent_Harness_L5`), v50 `f3fd1732...` (`D:\DV\Task\DV_Agent_Harness_L5\v50`, git remote `origin` of this repo), b7a `7b2a65a4...`, b7b `c7c7fa09...`, b8 `c9cdd06c...` (all three as `impl/*` branches of the v50 repo, checked out at worktrees `D:/wt/b7a`, `D:/wt/b7b`, `D:/wt/b8`). All `UNCHANGED` vs. `MASTER_PROGRAM_STATUS.md`'s recorded values. |

## 1. Real open M5 capability inventory (from MASTER_CAPABILITY_STATUS_MATRIX.csv, structural parse)

24 rows carry `PRIMARY_OWNER_WAVE==M5`. Breakdown:

- **1 already CLOSED** this session's prior M4 work: `CAP-M4-001` (RegisterFieldIR.enum_values) -- RESOLVED/ENHANCED/TESTED. Not requeued.
- **8 real shared-file N-way semantic-merge targets** (the actual "M5 N-Way Capability Semantic Merge" work) -- see cohort table below.
- **6 M3-Deferred-Pool new-file candidates** (Parent/B7A-only, `ABSENT from canonical`, all P3) -- lowest priority, Cohort 5.
- **9 remaining Agent-Task-Lifecycle roadmap items** (`CAP-ATL-001/002/003/005/006/008/009/010` -- everything except the two migration-evidence rows already called out by name in the M5-start instruction) -- Cohort 5, since 5 of 9 are already `ALREADY_COVERED` (no merge work) and the rest are roadmap-only `DEFINED`/`DEFERRED`.

## 2. Real sizing evidence (this wave, not assumed)

| File | Canonical | Parent | v50 | B7x | Finding |
|---|---|---|---|---|---|
| `env_manifest.py` | 1952 | 1952 (byte-identical) | 1952 (byte-identical) | B7B: 2070 | Real merge target is a 2-way diff: canonical/Parent/v50 baseline vs. B7B's +118 lines (VIP-01/VIP-02). Not a fan-out 3-4-way merge. 44-caller fan-in (M4's own finding) is the real complexity driver, not diff size. |
| `vip_capability_extraction.py` | 686 | 686 (byte-identical) | 686 (byte-identical) | B7B: 778 | Same shape: 2-way diff vs. B7B's +92 lines (VIP-04/05/18). Carries the KNOWN RISK `classify_by_inheritance()` 4-to-5-tuple signature break (M0.5 finding) -- every caller must be found before merge, not merely the diff read. |
| `functional_coverage_signoff.py` | 630 | 663 (+33) | 630 (byte-identical to canonical) | -- | Parent carries real extra content canonical/v50 lack. HUMAN_DECISION_REQUIRED-flavored (DV-domain judgment call on which return-value contract is correct), not a pure engineering merge -- see CAP-M5-COV-001. |
| `design_source_inventory.py` | 491 | 441 (-50) | 491 (byte-identical to canonical) | -- | Parent is SMALLER -- contract-question direction (which source's `authority_order_used`/rank-expression claim is current-evidence-correct), not a missing-content merge. |
| `create_environment.py` | 426 | 430 (+4) | 426 (byte-identical) | B8: 544 (+118) | Small Parent delta; real size is in B8's ARCH-01 addition. M1's own known-defect disposition already documents the contract shape. |
| `soc_environment_composer.py` | 557 | 649 (+92) | 557 (byte-identical) | B8: 614 (+57) | Two independent deltas (Parent +92, B8 +57) against the same canonical/v50 baseline -- genuinely 3-way, not 2-way. |
| `amba_fabric_generator.py` | 422 | 422 (byte-identical) | 422 (byte-identical) | B8: 516 (+94) | Clean 2-way diff vs. B8 only. |

## 3. Cohort assignment

**COHORT 0 -- M5 prerequisite/dependency revalidation.** CLOSED this pass (Section 0 above).

**COHORT 1 -- M6-unblocking capability inputs.**
- `CAP-M5-ENV-001` (`env_manifest.py` N-way merge) -- named directly in `CAP-M5M6-VLEVEL-001`'s (M6, P0) own `SECONDARY_DEPENDENCY` field. Highest-priority M5 item overall (P0 + only real M6-blocking dependency).

**COHORT 2 -- Environment semantic union.**
- `CAP-M5-ARCH-001` (`create_environment.py`, B8 ARCH-01)
- `CAP-M5-ARCH-002` (`soc_environment_composer.py`, Parent + B8 ARCH-03, genuinely 3-way)
- `CAP-M5-ARCH-003` (`amba_fabric_generator.py`, B8 ARCH-04/12)

**COHORT 3 -- VIP / multi-vendor semantic union.**
- `CAP-M5-VIP-001` (`vip_capability_extraction.py`, B7B VIP-04/05/18, KNOWN RISK signature break)

**COHORT 4 -- Contract / Intake semantic union.**
- `CAP-ATL-004` (`TASK_SCOPE_CONTRACT` -- migrate `task_boundary_conformance.py`, Parent-only, `SOURCE_EVIDENCE_ONLY` until merged, explicitly named this wave)
- `CAP-ATL-007` (`TASK_EVIDENCE_CONTRACT` -- clause-level admission of `intake_field_resolution.py`'s `DeclaredValue`/`AutoDiscoveredValue`/`DerivedValue`/`EffectiveValue`/`ValidationState`/`ConfirmationState` split, Parent-only, `SOURCE_EVIDENCE_ONLY` until merged, explicitly named this wave)
- `CAP-M5-COV-001` (`functional_coverage_signoff.py` contract judgment call)
- `CAP-M5-DSI-001` (`design_source_inventory.py` contract question)

**COHORT 5 -- Remaining shared-file / roadmap semantic targets.**
- 6 M3-Deferred-Pool candidates: `CAP-POOL-001/003/004/008/011/012` (all P3, `ABSENT from canonical`)
- 7 remaining ATL roadmap items: `CAP-ATL-001/002/003/005/006/008/009/010` (5 of 7 already `ALREADY_COVERED` -- no merge action; 2 `DEFINED`-only roadmap concepts)

## 4. Explicit constraints carried into every cohort (per this wave's instruction)

- Capability/symbol/behavior/contract-level semantic merge only. **Whole-file winner strategies are prohibited.**
- `ONE_GENERIC_DE_DV_WORKFLOW=YES` preserved; no separate DE/DV engines; M5 must not implement M6 Role-Based HITL prematurely (`VerificationLevel`/`HumanRole`/`QuestionOwner`/`ClarificationService`/`HumanGate` are M6-owned -- M5 may not create foundation architecture that conflicts with their still-pending design, and must not build them early).
- `DeclaredValue`/`AutoDiscoveredValue`/`DerivedValue`/`EffectiveValue`/`Confidence`/`ValidationState`/`ConfirmationState`/`EvidenceRefs` preserved where verified (Cohort 4).
- After each cohort: focused tests, Constitution/Anti-Drift, provenance update, Master Capability Status Matrix update, `SOURCE_CAPABILITY_LOSS=0` check, no new mandatory UNKNOWN, Parent/v50/b7a/b7b/b8 unchanged re-check. Full regression deferred to M5 closure only.

STATUS: COHORT 0 CLOSED. COHORT 1 next.
