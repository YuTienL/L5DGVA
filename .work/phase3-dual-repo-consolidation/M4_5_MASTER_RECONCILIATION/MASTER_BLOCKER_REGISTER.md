# Master Blocker Register (v3, post-M4.5-Governing-Contract-Authority-closure + POOL-005 dedup)

**Disclosed correction (M5-0 P0-drift reconciliation, 2026-09-23)**: this
file had gone stale after the M4.5 Governing Contract Authority Closure
committed (`83cd4ba`/`a844b9c`) — it still carried `CAP-M4.5-004` as an
open P0 `HUMAN_DECISION_REQUIRED` blocker, even though that closure's own
final report and `MASTER_CAPABILITY_STATUS_MATRIX.csv`/
`MASTER_WAVE_OWNERSHIP_MATRIX.csv` had already downgraded it to `P2`
(`CLOSED_AS_EVIDENCE_ONLY` — the human decision is made and executed
against; residual work is refinement, not a blocker). `MASTER_PROGRAM_
STATUS.md` was corrected for this at the time (its own v3); this register
was not, and stayed wrong until now. This v3 fixes that.

`P0_BLOCKERS = 7`, structurally reconciled against `MASTER_WAVE_
OWNERSHIP_MATRIX.csv`'s `PRIORITY=P0` rows (7, exact ID match) and
`MASTER_CAPABILITY_STATUS_MATRIX.csv`'s `PRIORITY=='P0'` rows (also 7,
after this same reconciliation qualified `CAP-POOL-005`'s PRIORITY value
so it is no longer literally the bare string `P0` — that row has been a
documented, non-counted cross-reference to `CAP-M5M6-VLEVEL-001` since
its very first commit (`b8a573f`'s own NOTES: "Cross-referenced, not
double-counted"); it was never a real 8th blocker, just a value a naive
`PRIORITY==P0` parse would over-count).

| CAPABILITY_ID | Blocker | Type | Blocks | Owner |
|---|---|---|---|---|
| CAP-M5-ENV-001 | `env_manifest.py` N-way merge not symbol-diffed (44 fan-in) | ENGINEERING | 4 of the 5 MCP verbs' backing data model; most of M5 | M5 |
| CAP-M5-VIP-001 | `vip_capability_extraction.py` N-way merge carries a known breaking signature-change risk (`classify_by_inheritance` 4→5-tuple) | ENGINEERING (real known regression risk) | VIP capability extraction correctness across all callers | M5 |
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
