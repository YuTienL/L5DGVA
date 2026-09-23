# M5.9 — Ownership Reconciliation

Reviews the Cohort-5 reassignment of 10 capabilities
(`CAP-ATL-001/002/003/008`, `CAP-POOL-001/003/004/008/011/012`) from
`M5` to `M6`. Control-plane/ownership reconciliation only —
`PRODUCTION_FILES_MODIFIED = 0`. No M5 final regression, M6, M10.5, or
M14 started.

## Headline finding: the Cohort-5 reassignment was PARTIALLY WRONG

Deeper evidence (git history + direct Parent-source reads, not inferred
from ID/name) shows the 10 items are **not uniform** — they split into
two genuinely different situations:

- The **4 `CAP-ATL-*` items** are correctly M6 material: every
  foundation they'd build on (`AgentTaskStore`, `question_queue.py`,
  `memory_router.py`, `session_snapshot.py`, `agent_checkpoint_check.py`,
  `task_return_model.py`, `models.Status`) is **already real, tested,
  and present in canonical**. The remaining work is wiring/joining/
  threading over those existing foundations, gated on a real caller from
  M6's own dispatch-mechanism decision — the textbook M6 criterion per
  this reconciliation's own rule.
- The **6 `CAP-POOL-*` items are NOT M6 material** — they are real,
  un-migrated Parent CODE (or blocked on a real, un-migrated Parent
  CODE dependency). Moving them to M6 in Cohort 5 was a **mistake**,
  corrected here: per the explicit rule ("If verified source capability
  still requires migration... OWNER should normally remain M5"), all 6
  are reverted to `M5`.

## Section 1-2: per-capability trace (git history + source evidence)

All 10 rows were introduced in a single commit, `b8a573f` ("Master
requirements/capability/remaining-work reconciliation (analysis only)",
2026-09-23, the very first commit creating the master matrix) — **not**
individually investigated at assignment time. The ATL items trace
further back to `.work/phase3-dual-repo-consolidation/M5_PREP_AGENT_TASK_
LIFECYCLE/AGENT_TASK_LIFECYCLE_ANALYSIS.md` (commit `b173722`); the POOL
items trace to `b8a573f`'s own commit message: "4 of 5 pool capabilities
M3's audit assigned to M4... were never actually reviewed by M4...
reassigned to M5/M8" — itself a bulk classification, not per-module
analysis.

### CAP-ATL-001 — AGENT_TASK_LIFECYCLE join/aggregator

| Field | Value |
|---|---|
| `CAPABILITY_CONTRACT` | A thin join/aggregator composing existing real lifecycle-adjacent modules (per `AGENT_TASK_LIFECYCLE_ANALYSIS.md`: "same shape as `irq_debug_readiness_aggregator.py`... **not** a new `agent_task_engine.py`") |
| `ORIGINAL_OWNER` | M5 (per `b173722`'s own "Recommended M5 Action" column) |
| `WHEN_OWNER_ASSIGNED` | 2026-09-23, commit `b173722` |
| `WHY_M5_WAS_ORIGINALLY_SELECTED` | The analysis's own recommendation, written before M5's Cohort scope had crystallized around "N-way code semantic merge only" |
| `DEPENDENCIES` | `AgentTaskStore` (`multi_agent.py`), `make_question_id()`, `agent_checkpoint_check.py` -- **all real, tested, present in canonical** |
| `CURRENT_STATE` | `DEFINED` (join-layer concept only, not built) |
| `CURRENT_IMPLEMENTATION` | None |
| `CURRENT_WIRING` | None |
| `CURRENT_CONSUMERS` | None |
| `CURRENT_TEST_EVIDENCE` | None |
| `REMAINING_WORK_TYPE` | `ORCHESTRATION` (composes existing real modules, adds no new state) |
| `DECISION` | **MOVE_TO_M6** |
| Evidence | Every dependency confirmed present via direct read this session (Cohorts 1-4) and the original analysis's own investigation; a join layer over an undecided dispatch mechanism (`CAP-M6-DISPATCH-001`) cannot be built before that mechanism exists |

### CAP-ATL-002 — TASK_IDENTITY extension

| Field | Value |
|---|---|
| `CAPABILITY_CONTRACT` | Thread a deterministically-derived `task_id` through a governance task's own artifact, reusing `make_question_id()`'s derivation pattern + `agent_checkpoint_check.py`'s resume-artifact convention |
| `ORIGINAL_OWNER` | M5 (`b173722`) |
| `WHY_M5_WAS_ORIGINALLY_SELECTED` | Same as ATL-001 |
| `DEPENDENCIES` | `make_question_id()`, `agent_checkpoint_check.py`, `AgentTaskStore` -- all real, present |
| `CURRENT_STATE` | `DEFINED` (3 composable primitives identified, not joined) |
| `REMAINING_WORK_TYPE` | `WIRING` |
| `DECISION` | **MOVE_TO_M6** |
| Evidence | No real M5-program task ever needed a stable cross-artifact ID this whole program; natural fit alongside M6's own dispatch work, which is what will generate the real caller need |

### CAP-ATL-003 — TASK_STATE_MODEL extension

| Field | Value |
|---|---|
| `CAPABILITY_CONTRACT` | Add `CANCELLED`/`REWORK_REQUIRED` to `models.Status`, explicitly "only when a real caller needs them" (the original analysis's own condition) |
| `ORIGINAL_OWNER` | M5 (`b173722`) |
| `DEPENDENCIES` | `models.Status` -- real, present, unmodified |
| `CURRENT_STATE` | `DEFINED` (2 enum values proposed, not added) |
| `REMAINING_WORK_TYPE` | `WIRING` (trigger-conditioned; the foundation itself is present) |
| `DECISION` | **MOVE_TO_M6** |
| Evidence | No real caller has emerged across this entire M5 program (Cohorts 1-5); the real caller, if any, will come from M6's own dispatch/lifecycle build |

### CAP-ATL-008 — TASK_FAILURE_RECOVERY

| Field | Value |
|---|---|
| `CAPABILITY_CONTRACT` | A new, agent-task-scoped failure taxonomy, reusing `task_return_model.py`'s honesty-rule discipline (no fabricated PASS/FAIL) |
| `ORIGINAL_OWNER` | M5 (`b173722`'s own recommendation text literally says "deferred to M5") |
| `DEPENDENCIES` | `task_return_model.py` -- real, tested, present |
| `CURRENT_STATE` | `DEFINED` (shape identified, taxonomy not authored) |
| `REMAINING_WORK_TYPE` | `SCHEMA_CONTRACT` (new taxonomy design, not a migration -- nothing external to migrate FROM) |
| `DECISION` | **MOVE_TO_M6** |
| Evidence | The original doc's "deferred to M5" phrase predates M5's own Cohort-scope crystallization around N-way *code* semantic merge; this is new schema-contract design work, gated on a real agent-task dispatch caller that only M6's own build will create -- the foundation pattern (`task_return_model.py`) it reuses is already real and present, satisfying the M6 criterion ("foundation already present, remaining work is wiring/dispatch/orchestration") |

### CAP-POOL-001 — engine_maturity_state.py

| Field | Value |
|---|---|
| `CAPABILITY_CONTRACT` | L5DGVA V14 SS340 Universal Engine Maturity State (per Parent's own module docstring, read this session) |
| `ORIGINAL_OWNER` | M4 (M3's own audit assignment) -> M5 (`b8a573f`, "M4_FINAL_REPORT's own FOUNDATION_ITEMS_REVIEWED=18 confirms it was NOT reviewed") |
| `DEPENDENCIES` | `eight_engine_runtime_proof_matrix.py` -- **ABSENT from canonical**, itself a real, separate, un-migrated Parent module |
| `CURRENT_STATE` | `ABSENT` from canonical; real, tested in Parent (276 lines + own test file) |
| `REMAINING_WORK_TYPE` | `MIGRATION`, blocked on a missing foundation dependency (also un-migrated) |
| `DECISION` | **KEEP_M5** (reverted from Cohort 5's M6 reassignment) |
| Evidence | Per the explicit rule: "If verified source capability still requires migration... OWNER should normally remain M5." Checked the absent dependency's own imports (`loop_telemetry` only) -- confirmed NOT coupled to the separately-known-blocked L5DGVA governing-contract document corpus (`M4_M3_DEFERRED_CLOSURE.md`'s own finding); a real but ordinary sequential migration-chain gap, not an architectural scope question |

### CAP-POOL-003 — l5dgva_directive_blackboard_work_queue.py

| Field | Value |
|---|---|
| `CAPABILITY_CONTRACT` | V22 SS649 Blackboard Work Queue (Parent's own module docstring) |
| `ORIGINAL_OWNER` | M4/M5 split (M3) -> fully M5 (`b8a573f`: "M4 half NOT reviewed. Reassigned fully to M5.") |
| `DEPENDENCIES` | `blackboard.py` (PRESENT in canonical) + `l5dgva_directive_registry.py` (**ABSENT**) + `l5dgva_workitem_projection.py` (**ABSENT**) |
| `CURRENT_STATE` | `ABSENT` from canonical; real, tested in Parent (236 lines + own test file) |
| `REMAINING_WORK_TYPE` | `MIGRATION`, blocked on 2 missing foundation dependencies |
| `DECISION` | **KEEP_M5** (reverted) |
| Evidence | Same rule as POOL-001; checked both absent deps' imports -- `l5dgva_directive_registry` depends only on `l5dgva_workitem_projection`, which depends only on `l5dgva_gap_queue` (also absent, see POOL-004) -- a real 3-deep sequential chain, not the corpus-architecture blocker |

### CAP-POOL-004 — l5dgva_kc_extraction.py

| Field | Value |
|---|---|
| `CAPABILITY_CONTRACT` | SS211 KC-from-Closure EXTRACTION half only (Parent's own module docstring notes: "zero real callers until an engine.py trigger wires it" -- dormant even in Parent itself) |
| `ORIGINAL_OWNER` | M4 (M3) -> M5 (`b8a573f`) |
| `DEPENDENCIES` | `l5dgva_gap_queue.py` -- **ABSENT**, no further internal imports of its own (self-contained) |
| `CURRENT_STATE` | `ABSENT` from canonical; real in Parent (248 lines + own test file), but dormant there too |
| `REMAINING_WORK_TYPE` | `MIGRATION`, blocked on one missing foundation dependency; low urgency (dormant even at the source) |
| `DECISION` | **KEEP_M5** (reverted) |
| Evidence | Same rule; explicitly disclosed as low-priority given its own dormant status in Parent -- a real gap, not a false one, but not worth accelerating |

### CAP-POOL-008 — l5dgva_v5_ss84_phase_entry_protocol_schema.py

| Field | Value |
|---|---|
| `CAPABILITY_CONTRACT` | V5 SS84 Mandatory Phase Entry Protocol schema (Parent's own module docstring) |
| `ORIGINAL_OWNER` | M5 unchanged since M3 (`b8a573f`: "Unchanged from M3 assignment") |
| `DEPENDENCIES` | `gates.py` only -- **PRESENT** in canonical |
| `CURRENT_STATE` | `ABSENT` from canonical; real, tested in Parent (295 lines + own test file) |
| `REMAINING_WORK_TYPE` | `MIGRATION` -- genuinely UNBLOCKED, its one real dependency already exists in canonical |
| `DECISION` | **KEEP_M5** |
| Evidence | Confirmed via direct read of its own import block; a real, ready migration candidate for a future dedicated M5 task -- not implemented this reconciliation (control-plane only) |

### CAP-POOL-011 — eight_engine_telemetry_rollup.py

| Field | Value |
|---|---|
| `CAPABILITY_CONTRACT` | V14 SS374 Per-Engine Telemetry Rollup (Parent's own module docstring) |
| `ORIGINAL_OWNER` | M5 (`b8a573f`; NOTES explicitly distinguish it from the already-resolved `loop_telemetry.py` foundation question) |
| `DEPENDENCIES` | `loop_telemetry.py` (**PRESENT** in canonical) + `eight_engine_runtime_proof_matrix.py` (**ABSENT**, same missing dep as POOL-001) |
| `CURRENT_STATE` | `ABSENT` from canonical; real, tested in Parent (254 lines + own test file) |
| `REMAINING_WORK_TYPE` | `MIGRATION`, blocked on one missing foundation dependency (shared with POOL-001 -- migrating `eight_engine_runtime_proof_matrix.py` once would unblock both) |
| `DECISION` | **KEEP_M5** (reverted) |
| Evidence | Same rule as POOL-001/003; the shared-dependency finding is new evidence from this reconciliation, useful for sequencing a future migration task |

### CAP-POOL-012 — rtl_filelist_parser.py

| Field | Value |
|---|---|
| `CAPABILITY_CONTRACT` | Expand a real VCS-style `.f` RTL compile filelist into an ordered file/incdir/define list for `env_manifest.build_dut_facts_rtl()`/`design_architecture_ir.parse_rtl_file()`/`verible_parser.parse_file()` to consume (module's own docstring, "DUT-03" gap numbering -- this project's own DV-infrastructure convention, NOT part of the L5DGVA audit-program module family the other 5 POOL items belong to) |
| `ORIGINAL_OWNER` | Unassigned in M3 -> M5 (`b8a573f`: "assigned M5 here as nearest-fitting N-way-merge wave") |
| `DEPENDENCIES` | `design_architecture_ir.py` (**PRESENT**), `verible_parser.py` (**PRESENT**) -- both real, existing canonical consumers already require pre-expanded `rtl_files`, currently done by hand |
| `CURRENT_STATE` | Not present as a TRACKED file anywhere (Parent, v50, B7B, B8 all lack it) -- exists only as an **UNTRACKED** file in B7A's own worktree (347 lines, discovered incidentally during this session's Cohort 4 source-integrity re-checks), no committed provenance, no test file found in B7A |
| `REMAINING_WORK_TYPE` | `MIGRATION` -- genuinely UNBLOCKED (both real dependencies present), but the source itself carries a real, disclosed provenance caveat (uncommitted in its only source location) |
| `DECISION` | **KEEP_M5** |
| Evidence | Direct read of the untracked B7A file confirms real, substantial, well-documented, self-contained content with a genuine project-specific gap rationale -- a real migration candidate for a future dedicated M5 task, disclosed provenance caveat and all, not implemented this reconciliation |

## Section 5 — POOL relationship classification (CAP-POOL-005 double-counting check)

All 6 POOL items checked against the whole matrix for a duplicate
substantive row elsewhere (the exact `CAP-POOL-005` pattern, which
points to `CAP-M5M6-VLEVEL-001`): **zero matches found** — none of the
6 module names (`engine_maturity_state`,
`l5dgva_directive_blackboard_work_queue`, `l5dgva_kc_extraction`,
`l5dgva_v5_ss84_phase_entry_protocol_schema`,
`eight_engine_telemetry_rollup`, `rtl_filelist_parser`) appears anywhere
else in `MASTER_CAPABILITY_STATUS_MATRIX.csv`. All 6 are classified
`INDEPENDENT_CAPABILITY` (real, distinct, un-migrated code), not
`CROSS_REFERENCE`/`DUPLICATE_REPRESENTATION` — no `CAP-POOL-005`-style
double-counting risk exists for this batch.

## Section 6 — decisions were NOT optimized for `UNRESOLVED_M5_CAPABILITIES = 0`

The honest result of this reconciliation is that 4 of the 6 POOL items
(`CAP-POOL-001/003/004/011`) remain **genuinely OPEN** — real,
un-migrated Parent code, blocked on real, un-migrated dependency
modules. This reconciliation does not force them into a false-resolved
bucket. See Section 7.
