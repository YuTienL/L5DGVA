# M5 Cohort 5 — Complete M5-Owned Capability Inventory

Structurally enumerated via `csv.DictReader` over
`MASTER_CAPABILITY_STATUS_MATRIX.csv` (never grep), filtering
`PRIMARY_OWNER_WAVE == 'M5'`. **25 rows found** — not just the 2 named in
this Cohort's own dispatch instruction. Every row is classified below;
none is silently absorbed into `CAP-M5-COV-001`/`CAP-M5-DSI-001`.

## Classification vocabulary (per instruction)

`CLOSED` / `FOUNDATION_CLOSED` / `DEFERRED_WITH_EXPLICIT_OWNER` /
`SUPERSEDED` / `NOT_APPLICABLE` / `OPEN`.

## Group A — already closed before this Cohort (9)

| ID | Name | Classification | Evidence |
|---|---|---|---|
| `CAP-M4-001` | RegisterFieldIR.enum_values | CLOSED | RESOLVED,ENHANCED,TESTED — M4 work, not requeued by M5 |
| `CAP-M5-ENV-001` | env_manifest.py N-way merge | CLOSED | Cohort 1, commit `a0650f4` |
| `CAP-M5-VIP-001` | vip_capability_extraction.py N-way merge | CLOSED | Cohort 3, commit `f773f47` |
| `CAP-M5-ARCH-001` | create_environment.py ARCH-01 | CLOSED | Cohort 2 |
| `CAP-M5-ARCH-002` | soc_environment_composer.py ARCH-03 | CLOSED | Cohort 2, commit `c91da7c` |
| `CAP-M5-TOPTB-001` | soc_environment_composer.py top-TB preservation | CLOSED | Cohort 2 dedicated task, commit `bd5c560` |
| `CAP-M5-ARCH-003` | amba_fabric_generator.py ARCH-04/12 | CLOSED | Cohort 2 |
| `CAP-ATL-004` | TASK_SCOPE_CONTRACT (task_boundary_conformance.py) | FOUNDATION_CLOSED | Cohort 4, commit `d957c4b` — WIRED=NO, deferred to `CAP-M6-DISPATCH-001` |
| `CAP-ATL-007` | TASK_EVIDENCE_CONTRACT (intake_field_resolution.py) | FOUNDATION_CLOSED | Cohort 4, commit `d957c4b` — WIRED=NO, deferred to `CAP-M6-CLARSVC-001` |

## Group B — this Cohort's named targets (2)

| ID | Name | Classification | Disposition |
|---|---|---|---|
| `CAP-M5-COV-001` | functional_coverage_signoff.py contract judgment call | **CLOSED** (this Cohort) | Real evidence resolved what the original M4 finding called a judgment call — see `M5_COHORT_5_COV001_ANALYSIS.md`. Migrated `coverage_analysis.classify_coverage_kind()` + `functional_coverage_signoff.py`'s consumption of it; wired into all 3 real existing callers automatically (no new wiring needed — they already call `analyze_functional_coverage_signoff()`); 76/76 focused tests + 293/293 caller-regression tests pass |
| `CAP-M5-DSI-001` | design_source_inventory.py contract question | **SUPERSEDED** (this Cohort) | Canonical is already AHEAD of Parent for this file — see `M5_COHORT_5_DSI001_ANALYSIS.md`. No migration performed; nothing to migrate FROM Parent |

## Group C — genuine OPEN M5 obligations found, NOT named in this Cohort's dispatch (10)

Reported per instruction ("If another legitimate OPEN M5 obligation
exists, report it. Do not silently absorb it into COV-001 or DSI-001").
Per instruction item 3 (No New Architecture Family) and item 18
(`DEFERRED_WITH_EXPLICIT_FUTURE_OWNER` counts as resolved-for-M5), all 10
are **REGISTERED + OWNER_ASSIGNED + DEFERRED** this Cohort — reassigned
from `PRIMARY_OWNER_WAVE=M5` to `M6`, rather than left as bare `M5 OPEN`
or implemented unrequested (which would blow Cohort 5's own
closure-oriented scope far past what was asked).

### C1 — 4 Agent Task Lifecycle roadmap items (`DEFINED`, never built)

| ID | Real name (from `AGENT_TASK_LIFECYCLE_ANALYSIS.md`) | Why M6 |
|---|---|---|
| `CAP-ATL-001` | `AGENT_TASK_LIFECYCLE` join/aggregator | Naturally sequenced after `TASK_IDENTITY`/`TASK_STATE_MODEL` and coupled to `CAP-M6-DISPATCH-001`'s own dispatch-mechanism decision — a join layer over an undecided dispatch mechanism cannot be built first |
| `CAP-ATL-002` | `TASK_IDENTITY` extension (thread a deterministic `task_id` through governance artifacts) | Same coupling — no real M5 caller ever needed this; natural fit alongside M6's dispatch work |
| `CAP-ATL-003` | `TASK_STATE_MODEL` extension (`CANCELLED`/`REWORK_REQUIRED` on `models.Status`) | Its own original recommendation was explicitly conditional: "only when a real caller needs them" — no real caller has emerged in this entire M5 program; naturally arises when M6's dispatch/lifecycle work creates one |
| `CAP-ATL-008` | `TASK_FAILURE_RECOVERY` (agent-task-scoped failure taxonomy) | Same coupling — needs `TASK_STATE_MODEL`/dispatch decided first |

### C2 — 6 M3-Deferred-Pool candidates (`ABSENT` from canonical)

| ID | Real module name | Why M6 (not implemented this Cohort) |
|---|---|---|
| `CAP-POOL-001` | `engine_maturity_state.py` | Real, substantial L5DGVA audit-program module (per its own NOTES: "M3 assigned this to M4; M4_FINAL_REPORT's own FOUNDATION_ITEMS_REVIEWED=18 confirms it was NOT reviewed. Reassigned M4->M5.") — never named in any M5 Cohort 0-5 dispatch; migrating it was never actually scoped into a specific cohort's work, only provisionally bucketed |
| `CAP-POOL-003` | `l5dgva_directive_blackboard_work_queue.py` | Same pattern — provisionally reassigned M4->M5, never actually dispatched |
| `CAP-POOL-004` | `l5dgva_kc_extraction.py` | Same pattern |
| `CAP-POOL-008` | `l5dgva_v5_ss84_phase_entry_protocol_schema.py` | Unchanged from original M3 assignment, never dispatched |
| `CAP-POOL-011` | `eight_engine_telemetry_rollup.py` | Its own NOTES explicitly distinguish it from the already-resolved `loop_telemetry.py` foundation question — a real, separate, un-investigated blocker |
| `CAP-POOL-012` | `rtl_filelist_parser.py` | Its own NOTES: "Unassigned in M3; assigned M5 here as nearest-fitting N-way-merge wave" — an explicitly provisional assignment, not a firm commitment. (Incidentally: B7A's own worktree carries an untracked `dv_harness/rtl_filelist_parser.py` file, observed during this session's Cohort 4 source-integrity re-checks — real evidence this module may already have Parent-side prior art, not yet investigated) |

**Disposition for all 10**: `PRIMARY_OWNER_WAVE` reassigned `M5` -> `M6` in
both master CSVs, `SECONDARY_DEPENDENCY` naming the coupling reason,
`CANONICAL_STATE`/`NOTES` updated to disclose this Cohort's reassignment
explicitly (never silently reworded to look pre-existing). This is a
disclosed SCOPE judgment call by this Cohort, not a unilateral technical
merge decision — flagged for review alongside this report.

## Group D — already-covered items requiring no further action (4)

| ID | Real name | Classification |
|---|---|---|
| `CAP-ATL-005` | `TASK_PREFLIGHT_GATE` | CLOSED (`ALREADY_COVERED` at process level, proven 5+ consecutive waves this session) |
| `CAP-ATL-006` | `TASK_APPROVAL_GATE` | CLOSED (`ALREADY_COVERED` — `question_queue.py`'s `HUMAN_DECISION_SOURCE` model, exercised live throughout this entire M5 program) |
| `CAP-ATL-010` | `TASK_KNOWLEDGE_PROMOTION_GATE` | CLOSED (`ALREADY_COVERED` — `memory_router.py`'s admission gates) |
| `CAP-ATL-009` | `TASK_RESUME_REPLAY` | `DEFERRED_WITH_EXPLICIT_FUTURE_OWNER` (pre-existing disposition, unchanged) — `ALREADY_COVERED` for 2 of its 3 scopes (run-level via `session_snapshot.py`, dispatched-subagent via `agent_checkpoint_check.py`); the 3rd scope (cross-provider governance-task resume) is explicitly trigger-deferred ("M5+ candidate only if a real cross-provider incident occurs") in its own original analysis — not a wave number, a real-incident trigger, already a valid `DEFERRED_WITH_EXPLICIT_FUTURE_OWNER` disposition, left unchanged |

## Totals

```
M5_CAPABILITIES_TOTAL = 25
Group A (CLOSED/FOUNDATION_CLOSED before this Cohort) = 9
Group B (resolved this Cohort: CLOSED + SUPERSEDED)   = 2
Group C (DEFERRED_WITH_EXPLICIT_OWNER, this Cohort)   = 10
Group D (CLOSED/DEFERRED_WITH_EXPLICIT_FUTURE_OWNER, pre-existing) = 4
UNRESOLVED_M5_CAPABILITIES = 0
```

Every one of the 25 M5-owned rows now carries a disposition in
{`CLOSED`, `FOUNDATION_CLOSED`, `SUPERSEDED`, `DEFERRED_WITH_EXPLICIT_
OWNER`, `DEFERRED_WITH_EXPLICIT_FUTURE_OWNER`} — none remain bare `OPEN`,
`UNKNOWN`, or `UNASSIGNED`.
