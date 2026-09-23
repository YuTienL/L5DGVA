# Canonical Capability Superset Matrix

Authoritative, cumulative record of every capability migrated into the
canonical repository, started at M3. Extended (never rewritten) by every
future migration wave. During M3, the final strict-superset verdict remains
`NOT_YET_QUALIFIED` for every row and for the matrix as a whole — this is
expected, not a defect; `CANONICAL_CAPABILITY_STRICT_SUPERSET = PASS` is a
final-qualification-only claim (`FINAL_CAPABILITY_GATE`), never asserted
during M3.

| CAPABILITY_ID | Name | PARENT_STATUS | V50_STATUS | WORKTREE_STATUS | CANONICAL_STATUS | Disposition | EVIDENCE | TEST | FINAL_VERDICT |
|---|---|---|---|---|---|---|---|---|---|
| CAP-M3-001 | `lifecycle.py` (Standard Flow project lifecycle) | IMPLEMENTED, TESTED | ABSENT | N/A | IMPLEMENTED, TESTED (not wired) | NEW | `M3_CAPABILITY_MIGRATION_RECORDS.md` | `test_lifecycle.py` real pass | NOT_YET_QUALIFIED |
| CAP-M3-002 | `debug_evidence_behavioral_firewall_gate.py` | IMPLEMENTED, TESTED | ABSENT | N/A | IMPLEMENTED, TESTED (not wired) | NEW | `M3_CAPABILITY_MIGRATION_RECORDS.md` | `test_debug_evidence_behavioral_firewall_gate.py` real pass | NOT_YET_QUALIFIED |
| CAP-M3-003 | `l5dgva_v5_ss86_understanding_plan_contradiction_taxonomy.py` | IMPLEMENTED, TESTED | ABSENT | N/A | IMPLEMENTED, TESTED (not wired) | NEW | `M3_CAPABILITY_MIGRATION_RECORDS.md` | `test_l5dgva_v5_ss86_understanding_plan_contradiction_taxonomy.py` real pass | NOT_YET_QUALIFIED |
| CAP-M3-004 | `diagnostic_bound_compatibility.py` | IMPLEMENTED, TESTED | ABSENT | N/A | IMPLEMENTED, TESTED (not wired) | NEW | `M3_CAPABILITY_MIGRATION_RECORDS.md` | `test_diagnostic_bound_compatibility.py` real pass | NOT_YET_QUALIFIED |

## Investigated-but-not-migrated this cohort (recorded for traceability, not silence)

| Candidate | PARENT_STATUS | V50_STATUS | WORKTREE_STATUS | Real gap found | Assigned |
|---|---|---|---|---|---|
| `ipxact_register_import.py` | IMPLEMENTED, TESTED | ABSENT | IMPLEMENTED, TESTED (b7a, DUT-04) | `register_excel_extract.RegisterFieldIR` missing `enum_values` (pre-DUT-10 API gap) | M5 |
| `reference_irq_event_to_service_flow_discovery.py` | IMPLEMENTED, TESTED | ABSENT | N/A | Test requires `USB_UVM_Handoff/` at repo root (Parent's layout, `REFERENCE_USB_ENV_CONSUMED` policy blocks resolving this before M11) | M11 |
| `l5dgva_requirement_dependency_closure.py` | IMPLEMENTED, TESTED | ABSENT | N/A | 2 tests need `l5dgva_contract_registry.py` (not yet migrated) | M4 |
| `verification_level.py` | IMPLEMENTED | ABSENT | N/A | depends on `question_queue.py` (diverged, M3-excluded) | M5/M6 |
| `autonomous_resume_next_action_arbitration.py`, `independent_work_continuation.py` | IMPLEMENTED | ABSENT | N/A | depend on `inference.arbitrate_next_best_evidence`, absent from this repo's diverged `inference.py` | M7 |
| `coverage_hole_generation_candidate_queue.py` | IMPLEMENTED | ABSENT | N/A | depends on `coverage_analysis.py` (diverged) | M5 |
| `engine_maturity_state.py` | IMPLEMENTED | ABSENT | N/A | depends on `eight_engine_runtime_proof_matrix.py` (parent-only, unmigrated) | M4 |
| `l5dgva_v5_ss84_phase_entry_protocol_schema.py` | IMPLEMENTED | ABSENT | N/A | depends on `gates.py` (diverged, 42 fan-in) | M5 |
| `irq_contradiction_change_impact.py` | IMPLEMENTED | ABSENT | N/A | depends on `question_queue.py` (excluded) | M5/M6 |
| `l5dgva_ss570_claude_verdict_truth.py` | IMPLEMENTED | ABSENT | N/A | depends on `l5dgva_pre_codex_review_truth.py` (parent-only, unmigrated) | M4 |
| `l5dgva_directive_blackboard_work_queue.py` | IMPLEMENTED | ABSENT | N/A | depends on `blackboard.py` (diverged) + 2 unmigrated parent-only files | M4/M5 |
| `falsified_hypothesis_ledger.py` | IMPLEMENTED | ABSENT | N/A | depends on `memory.py`/`memory_router.py` (diverged, high fan-in, Knowledge-Brain-adjacent) | M5/M8 |
| `l5dgva_kc_extraction.py` | IMPLEMENTED | ABSENT | N/A | depends on `l5dgva_gap_queue.py` (parent-only, unmigrated) | M4 |
| `eight_engine_telemetry_rollup.py` | IMPLEMENTED | ABSENT | N/A | depends on `loop_telemetry.py` (explicitly M3-excluded) | M5 |
| `rtl_filelist_parser.py` | N/A | ABSENT | IMPLEMENTED, dormancy/coverage question open (b7a, DUT-03) | open dormancy question, `M0_5_B7A_CAPABILITY_AUDIT.md` | unassigned (blocked on that question) |

**Scope disclosure**: this cohort investigated ~20 of the 177 `MIGRATE_REQUIRED_DIRECT`/`MIGRATE_REQUIRED_TRANSITIVE` parent-only closure members (the smallest-LOC, tested subset), per the instruction's "prefer a conservative batch" guidance — not an exhaustive triage of all 177. The remaining ~157 are not yet individually classified; they remain in the general M3/M4 pool for future cohorts.
