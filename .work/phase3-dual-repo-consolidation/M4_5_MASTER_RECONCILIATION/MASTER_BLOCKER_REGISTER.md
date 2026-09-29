# Master Blocker Register (v9, post-M5-Pool-Closure-batch-1)

**v9 update (M5 Capability Pool Closure, 2026-09-23)**: closure-debt
recovery discovered by M5.9, not a new roadmap cohort. `CAP-POOL-008`
(`l5dgva_v5_ss84_phase_entry_protocol_schema.py`) and `CAP-POOL-012`
(`rtl_filelist_parser.py`) migrated and CLOSED this task -- both
confirmed genuinely unblocked (their real dependencies already present
in canonical), migrated verbatim/adapted, tested (9/9 + 28/28, the
latter a brand-new suite since no test ever existed for that module
anywhere). `P0_BLOCKERS` **unchanged at 5**. The remaining 4
(`CAP-POOL-001/003/004/011`) stay `M5`-owned `OPEN` -- their real
dependencies (`eight_engine_runtime_proof_matrix.py`,
`l5dgva_gap_queue.py`, `l5dgva_workitem_projection.py`,
`l5dgva_directive_registry.py`) are themselves un-migrated Parent
modules outside this task's registered 6-item scope; migrating them was
explicitly out of bounds ("do not absorb unrelated Parent modules"). New
evidence this task: `CAP-POOL-001`/`CAP-POOL-011` share one blocker,
`CAP-POOL-003`/`CAP-POOL-004` share another -- a future task scoped to
include those 4 missing dependency modules could close all 4 remaining
items together. `M5_CAPABILITIES_OPEN` drops from 6 to **4**;
`M5_READY_FOR_FINAL_CLOSURE_REGRESSION` remains **NO**. See
`M5_POOL_CLOSURE/M5_POOL_CLOSURE_FINAL_REPORT.md`.

**v8 update (M5.9 Ownership Reconciliation, 2026-09-23)**: reviewed
Cohort 5's 10-item `M5` -> `M6` reassignment and found it **partially
wrong**. The 4 `CAP-ATL-001/002/003/008` items are correctly `M6`
(every foundation they build on -- `AgentTaskStore`, `question_queue.py`,
`memory_router.py`, `session_snapshot.py`, `agent_checkpoint_check.py`,
`task_return_model.py`, `models.Status` -- is already real and present
in canonical; remaining work is wiring/dispatch-conditioned). The 6
`CAP-POOL-001/003/004/008/011/012` items are **reverted M6 -> M5**: they
are real, un-migrated Parent code (or blocked on a real, un-migrated
Parent dependency), which the explicit ownership rule keeps M5-owned
regardless of Cohort scheduling. `P0_BLOCKERS` **unchanged at 5** (none
of the 10 items was ever P0). Honest result, not optimized for a clean
number: `M5_CAPABILITIES_OPEN = 6` (the 6 reverted POOL items, all
genuinely un-migrated) -- **`M5_READY_FOR_FINAL_CLOSURE_REGRESSION =
NO`** until those 6 are resolved or given a different disposition by a
future dedicated task. See
`M5_9_OWNERSHIP_RECONCILIATION/M5_9_OWNERSHIP_RECONCILIATION.md`.

**v7 update (M5 Cohort 5, 2026-09-23)**: `CAP-M5-COV-001` resolved
CLOSED and `CAP-M5-DSI-001` resolved SUPERSEDED this wave -- neither was
ever P0 (P1/P2), so `P0_BLOCKERS` is **unchanged at 5**. Full M5-owned
capability reconciliation performed (`csv.DictReader`, not grep): 25
rows found (not just the 2 named in this Cohort's own dispatch), all
classified; 10 (`CAP-ATL-001/002/003/008`,
`CAP-POOL-001/003/004/008/011/012`) reassigned `PRIMARY_OWNER_WAVE`
`M5` -> `M6` (disclosed scope-closure decision, none was ever
implemented by any M5 Cohort 0-5 dispatch). `UNRESOLVED_M5_CAPABILITIES
= 0` for the 15 rows remaining M5-owned after reassignment. `M5_STATUS`
remains `IN_PROGRESS` (a final closure regression against a stable
qualified checkpoint has not run). See
`M5_CAPABILITY_MERGE_QUEUE/COHORT_5/M5_COHORT_5_FINAL_REPORT.md` and
`M5_PRE_CLOSURE_CAPABILITY_RECONCILIATION.md`.

**v6 update (M5 Cohort 4, 2026-09-23)**: `CAP-ATL-004`
(`TASK_SCOPE_CONTRACT`) and `CAP-ATL-007` (`TASK_EVIDENCE_CONTRACT`)
resolved this wave -- `task_boundary_conformance.py` and
`intake_field_resolution.py` migrated (adapted, not blind-copied) from
Parent as canonical FOUNDATION modules, 19/19 + 25/25 tests passing,
Constitution PASS. Neither was ever a P0 blocker (P1/P2), so
`P0_BLOCKERS` is **unchanged at 5** this wave. Per this Cohort's own
instruction ("do not close an M6 blocker merely because its M5
foundation is now available"), none of the three M6-owned P0 rows below
(`CAP-M6-DISPATCH-001`, `CAP-M6-CLARSVC-001`, `CAP-M5M6-VLEVEL-001`) are
touched -- both new FOUNDATION modules are real, disclosed DEPENDENCIES
those M6 items can now build on (CLI/gate wiring for the former,
`ClarificationService` reconciliation for the latter), not a closure of
either blocker. See
`M5_CAPABILITY_MERGE_QUEUE/COHORT_4/M5_COHORT_4_FINAL_REPORT.md`.

**v5 update (M5 Cohort 3, 2026-09-23)**: `CAP-M5-VIP-001` resolved this
wave -- `vip_capability_extraction.py`'s VIP-04 ("transfer" naming
suffix) + VIP-05/VIP-18 (`_VENDOR_BASE_LIBRARY_MARKER_TO_CATEGORY`
vendor-base-class fallback) semantically merged from B7B, the known
`classify_by_inheritance()` 4-to-5-tuple signature-break risk resolved
with 0 real external callers found (full caller sweep performed first),
17/17 focused tests + 53/53 downstream-caller tests + 108/108
Cohort-1/2/TOPTB-001-preservation tests pass, Constitution PASS,
downgraded to `P2`. Removed from the P0 blocker table below. See
`M5_CAPABILITY_MERGE_QUEUE/COHORT_3/M5_COHORT_3_FINAL_REPORT.md`.
`P0_BLOCKERS` drops from 6 to **5** (structurally reconciled the same
way as every prior wave: raw `PRIORITY=='P0'` row count in both master
CSVs, minus `CAP-POOL-005`'s documented non-counted cross-reference to
`CAP-M5M6-VLEVEL-001`).

**Disclosed correction (M5-0 P0-drift reconciliation, 2026-09-23)**: this
file had gone stale after the M4.5 Governing Contract Authority Closure
committed (`83cd4ba`/`a844b9c`) — it still carried `CAP-M4.5-004` as an
open P0 `HUMAN_DECISION_REQUIRED` blocker, even though that closure's own
final report and `MASTER_CAPABILITY_STATUS_MATRIX.csv`/
`MASTER_WAVE_OWNERSHIP_MATRIX.csv` had already downgraded it to `P2`
(`CLOSED_AS_EVIDENCE_ONLY` — the human decision is made and executed
against; residual work is refinement, not a blocker). `MASTER_PROGRAM_
STATUS.md` was corrected for this at the time (its own v3); this register
was not, and stayed wrong until then (v3 fixed it).

**v4 update (M5 Cohort 1, 2026-09-23)**: `CAP-M5-ENV-001` resolved this
wave -- `env_manifest.py`'s VIP-01 (multi-vendor CDNS_VIP_HOME/
MGC_VIP_HOME fallback) + VIP-02 (flat project-local VIP layout detection)
semantically merged from B7B, schema (`env_manifest.schema.json`) updated
in lockstep, 73/73 focused tests + 169/169 suite-wide keyword sweep pass,
Constitution PASS, downgraded to `P2`. See
`M5_CAPABILITY_MERGE_QUEUE/M5_CAPABILITY_MERGE_QUEUE.md`.

`P0_BLOCKERS = 5`, structurally reconciled against `MASTER_WAVE_
OWNERSHIP_MATRIX.csv`'s `PRIORITY=P0` rows (6, exact ID match) and
`MASTER_CAPABILITY_STATUS_MATRIX.csv`'s `PRIORITY=='P0'` rows (also 6),
re-run this wave via `csv.DictReader` (never grep, to avoid
embedded-comma double-counting). `CAP-POOL-005` remains a documented,
non-counted cross-reference to `CAP-M5M6-VLEVEL-001` (since its very
first commit `b8a573f`'s own NOTES: "Cross-referenced, not
double-counted") -- never a real independent blocker, just a value a
naive `PRIORITY==P0` parse would over-count. 6 raw rows − 1 cross-ref = 5
real independent P0 blockers.

| CAPABILITY_ID | Blocker | Type | Blocks | Owner |
|---|---|---|---|---|
| CAP-M6-DISPATCH-001 | `cli.py`/`dashboard.py` dispatch-mechanism conflict (`start_lifecycle(...)` vs `loop(goal)`/`run_stage(goal)`) has no chosen resolution | HUMAN_DECISION_REQUIRED | CAP-M3-001 wiring, CAP-M4.5-001 live routing, CAP-M6-LIFECYCLE-001, CAP-M6-CLARSVC-001 routing | M6 |
| CAP-M6-CLARSVC-001 | `ClarificationService` design/build not started (architecture already decided, D2 — not reopened) | ENGINEERING | `CAP-M5M6-VLEVEL-001`, intake/clarification flow for all 3 verification levels | M6 |
| CAP-M5M6-VLEVEL-001 | `verification_level.py` absent from canonical; canonical `environment_mode_router.py` has no `IP_MODE` concept at all | ENGINEERING (dependency-chain migration) | The entire IP-level verification flow's mode-selection foundation | M6 |
| CAP-M8-EXPLOOP-001 | `EXPERIENCE_READY` event is required by `promotion_chain_audit_gate.py` but never emitted by any stage; `memory_router.route_and_store()` has no caller in the prompt/gate pipeline | ENGINEERING (pre-existing defect, confirmed identical on Parent/v50/canonical) | The entire INTERNAL continuous-experience-learning loop | M8 |
| CAP-CE-018 | `CONTINUOUS_PROJECT_EXPERIENCE_LEARNING` composite cannot be OPERATIONAL while its own required event-wiring (CAP-M8-EXPLOOP-001) is confirmed broken, plus 3 of 9 named stages (CLARIFICATION_LEARNING/GENERATION_EXPERIENCE_LEARNING/SIGNOFF_EXPERIENCE_CONSOLIDATION) confirmed fully absent | ENGINEERING (same root cause as CAP-M8-EXPLOOP-001, tracked as its own named capability per instruction section E) | Article 0's own CONTINUOUS_EVOLUTION dimension (currently PARTIAL) | M8 |

## Non-P0 items worth flagging explicitly

- **CAP-PLATFORM-000** (`P1`, process): no accepted prior artifact defines
  Platform `P1`–`P6` wave content. This reconciliation did not invent
  that scoping (would violate the no-fabrication instruction); it is
  named here as a real, disclosed process gap for a human to schedule.
- **CAP-M5-COV-001** (`P1`, human decision): `functional_coverage_signoff.py`'s
  contract fork requires a DV-domain judgment call, not an engineering
  merge decision — flagged so it isn't silently resolved by an engineer's
  own preference during M5.

No blocker in this register was created by fabricating a gap; every row
cites the specific evidence file that already established it (M4/M4.5
work), re-confirmed still current by this reconciliation's targeted
checks (repo identity, frozen-source SHAs, git log, Constitution gate).
