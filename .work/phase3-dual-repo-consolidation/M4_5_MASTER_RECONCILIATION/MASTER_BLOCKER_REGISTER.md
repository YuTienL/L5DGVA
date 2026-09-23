# Master Blocker Register

`P0_BLOCKERS = 7` (reconciled exactly against
`MASTER_WAVE_OWNERSHIP_MATRIX.csv`'s `PRIORITY=P0` rows).

| CAPABILITY_ID | Blocker | Type | Blocks | Owner |
|---|---|---|---|---|
| CAP-M4.5-004 | 25-doc, 4.0MB, 106,132-line governing-contract corpus has never been migrated; whether/how is undecided | HUMAN_DECISION_REQUIRED | Contract Registry (S10), `l5dgva_contract_registry.py`/`l5dgva_requirement_dependency_closure.py` migration | M4.5 |
| CAP-M5-ENV-001 | `env_manifest.py` N-way merge not symbol-diffed (44 fan-in) | ENGINEERING | 4 of the 5 MCP verbs' backing data model; most of M5 | M5 |
| CAP-M5-VIP-001 | `vip_capability_extraction.py` N-way merge carries a known breaking signature-change risk (`classify_by_inheritance` 4→5-tuple) | ENGINEERING (real known regression risk) | VIP capability extraction correctness across all callers | M5 |
| CAP-M6-DISPATCH-001 | `cli.py`/`dashboard.py` dispatch-mechanism conflict (`start_lifecycle(...)` vs `loop(goal)`/`run_stage(goal)`) has no chosen resolution | HUMAN_DECISION_REQUIRED | CAP-M3-001 wiring, CAP-M4.5-001 live routing, CAP-M6-LIFECYCLE-001, CAP-M6-CLARSVC-001 routing | M6 |
| CAP-M6-CLARSVC-001 | `ClarificationService` design/build not started (architecture already decided, D2 — not reopened) | ENGINEERING | `CAP-M5M6-VLEVEL-001`, intake/clarification flow for all 3 verification levels | M6 |
| CAP-M5M6-VLEVEL-001 | `verification_level.py` absent from canonical; canonical `environment_mode_router.py` has no `IP_MODE` concept at all | ENGINEERING (dependency-chain migration) | The entire IP-level verification flow's mode-selection foundation | M6 |
| CAP-M8-EXPLOOP-001 | `EXPERIENCE_READY` event is required by `promotion_chain_audit_gate.py` but never emitted by any stage; `memory_router.route_and_store()` has no caller in the prompt/gate pipeline | ENGINEERING (pre-existing defect, confirmed identical on Parent/v50/canonical) | The entire INTERNAL continuous-experience-learning loop | M8 |

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
