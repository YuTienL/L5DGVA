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
| CAP-M3-005 | `coverage_hole_generation_candidate_queue.py` (COVERAGE_CLOSURE_LEARNING: detection/ranking join for autonomous hole-driven test generation, V9 SS205) | IMPLEMENTED, TESTED | ABSENT | N/A | IMPLEMENTED, TESTED (not wired) | NEW | `M3_CAPABILITY_MIGRATION_RECORDS.md` §Cohort 2 | `test_coverage_hole_generation_candidate_queue.py` real pass (12/12) | NOT_YET_QUALIFIED |
| CAP-M4-001 | `RegisterFieldIR.enum_values` schema field (register_excel_extract.py) — SCHEMA foundation closure, not a standalone capability import | N/A (no enum_values field on either HEAD at audit time) | N/A | b7a HAS it (DUT-10 lineage) | IMPLEMENTED, TESTED (pure additive dataclass + JSON-schema field; 44/44 + 121/121 downstream-consumer tests unaffected) | ENHANCED (an existing canonical module's schema, not a new file) | `M4_SCHEMA_CLOSURE.md` | `test_register_excel_extract.py` (2 new tests) | NOT_YET_QUALIFIED |
| CAP-M4-002 | `ipxact_register_import.py` (DUT-04, b7a) | IMPLEMENTED, TESTED | ABSENT | IMPLEMENTED, TESTED (source) | IMPLEMENTED, TESTED (not wired) | NEW | `M4_SCHEMA_CLOSURE.md` | `test_ipxact_register_import.py` real pass (10/10) | NOT_YET_QUALIFIED |

## M4 finding: `l5dgva_contract_registry.py` requires an unmigrated document corpus

Investigated as the formal M3→M4 deferred item
(`l5dgva_requirement_dependency_closure.py` → `l5dgva_contract_registry.py`).
Real finding, not previously known: `l5dgva_contract_registry.py` depends on
a real `L5DGVA/` directory (`DEFAULT_L5DGVA_DIR = ROOT / "L5DGVA"`) holding
~20+ dated governing-contract `.md` files (V1–V23), absent from canonical
entirely. This is a genuinely new, larger-than-M4 architectural scope
question (whether/how to migrate the corpus), not a schema/contract gap —
recorded as **unscheduled**, not defaulted into M5. Both
`l5dgva_contract_registry.py` and `l5dgva_requirement_dependency_closure.py`
remain unmigrated. Full detail: `M4_M3_DEFERRED_CLOSURE.md`.

## Capability families per the Research/Experience-Learning preservation addendum

Real audit evidence (background investigation across Parent, v50/Canonical,
worktrees — see `M3_CAPABILITY_MIGRATION_RECORDS.md` §Cohort 2 for the full
citation trail). **Headline finding: canonical (cloned from v50) already had
the overwhelming majority of both families' real implementation** — v50 was
materially ahead of Parent here, not behind it. The migration risk runs the
OTHER direction from what the addendum anticipated: Parent has 2 modules
canonical lacks (both investigated above; 1 migrated as CAP-M3-005, 1
deferred), not the reverse.

| Capability ID | PARENT_STATUS | V50_STATUS | WORKTREE_STATUS | CANONICAL_STATUS | Real module(s) | Notes |
|---|---|---|---|---|---|---|
| RESEARCH_INGESTION | IMPLEMENTED,WIRED,TESTED | IMPLEMENTED,WIRED,TESTED | same as v50 (v50-lineage checkouts) | IMPLEMENTED,WIRED,TESTED | `router.py` (`resolve_research_intent`), `cli.py`'s `research` subparser, `.claude/skills/research-ingestion/SKILL.md` (byte-identical both sides), `.claude/agents/research-architect.md` | Already present via v50 bootstrap; both sides identical |
| DV_PAPER_DISTILLATION | (part of research-ingestion skill's doc-extraction pipeline) | same | same | same | `research-ingestion` SKILL.md's claim-classification pipeline | No separate module; folded into RESEARCH_INGESTION |
| NEW_TECHNOLOGY_EXTRACTION | (same skill) | same | same | same | same | No separate module found on either side |
| RESEARCH_PROVENANCE | IMPLEMENTED,TESTED | IMPLEMENTED,TESTED | same | IMPLEMENTED,TESTED | `capability_evolution.compare_evidence_cards()`/`link_prior_research()` | Present, real (section 28 CONTRADICTS/overlap detection) |
| RESEARCH_APPLICABILITY | IMPLEMENTED,TESTED | IMPLEMENTED,TESTED | same | IMPLEMENTED,TESTED | `capability_evolution.decide_recommendation()` | Real KEEP/ENHANCE/ADD/EXPERIMENT/REJECT/UNKNOWN classifier |
| RESEARCH_TO_CAPABILITY_PROPOSAL | IMPLEMENTED,WIRED,TRIGGERED,TESTED | IMPLEMENTED,WIRED,TRIGGERED,TESTED | same | IMPLEMENTED,WIRED,TRIGGERED,TESTED | `capability_evolution.build_candidate()`/`persist_candidate()`, real caller `engine.py::_file_capability_evolution_candidates_from_repeated_failures()` | Confirmed real engine.py call site on all sides |
| CAPABILITY_EXPERIMENT_VALIDATION | IMPLEMENTED,TESTED | IMPLEMENTED,TESTED | same | IMPLEMENTED,TESTED | `capability_evolution.run_controlled_experiment()`/`run_shadow_replication()`/`assert_stability_window()` | Real isolated before/after fixture execution, not attestation |
| PROJECT_EXPERIENCE_EXTRACTION | ABSENT (as a unified concept) | PARTIAL (see below) | same as v50 | PARTIAL | `memory_lineage.py`, `memory_quality_policy.py`, `cross_project_mining.py` | No unified `Experience` record type exists anywhere (confirmed absent both sides); coverage is via several narrower real mechanisms instead |
| USER_INTERACTION_LEARNING | ABSENT | IMPLEMENTED,TESTED | same as v50 | IMPLEMENTED,TESTED | `user_correction_trigger.py` (repeated-correction-pattern detection, reuses `capability_evolution.build_candidate()`) | v50-only; already in canonical via bootstrap |
| CLARIFICATION_LEARNING | ABSENT | ABSENT | ABSENT | ABSENT | none (`QUESTION_AVOIDABLE` or equivalent: zero hits anywhere) | Confirmed absent on every side, not merely unwired |
| GENERATION_EXPERIENCE_LEARNING | ABSENT | ABSENT | ABSENT | ABSENT | none found | No generation-decision -> build/sim-result -> reusable-experience mechanism found anywhere |
| RCA_EXPERIENCE_LEARNING | PARTIAL | PARTIAL | same as v50 | PARTIAL | `capability_evolution.repeated_unresolved_failure_patterns()` (Job-Memory-sourced auto-discovery) | Real but narrow: repeated-failure detection only, not a full RCA-to-fix experience record |
| COVERAGE_CLOSURE_LEARNING | IMPLEMENTED,TESTED (2 modules) | IMPLEMENTED,TESTED (1 different module) | same as v50 | IMPLEMENTED,TESTED (both, after this cohort) | Parent: `coverage_hole_generation_candidate_queue.py` + `coverage_closure_loop_leg_matrix.py`; v50/canonical: `coverage_closure_hole_correlation.py`; shared base `coverage_closure_action_utility.py` (byte-identical) | **CAP-M3-005 closes half this gap** (queue module migrated this cohort); `coverage_closure_loop_leg_matrix.py` investigated and DEFERRED (see below) |
| SIGNOFF_EXPERIENCE_CONSOLIDATION | ABSENT | ABSENT | ABSENT | ABSENT | none (`signoff_export.py`/`qualified_conclusion.py` checked, zero "experience"/"consolidat" hits) | Confirmed absent on every side |
| KNOWLEDGE_PROMOTION | IMPLEMENTED,TESTED | IMPLEMENTED,TESTED | same | IMPLEMENTED,TESTED | `memory_router.py::route_and_store()`/`promote_to_organizational()` (pre-existing, unrelated to this cohort) | Already documented under the M1 Knowledge Brain inventory |
| CROSS_PROJECT_GENERALIZATION | IMPLEMENTED,TESTED | IMPLEMENTED,TESTED | same | IMPLEMENTED,TESTED | `cross_project_mining.py` (byte-identical both sides) | Already present via v50 bootstrap |
| MULTI_AGENT_KNOWLEDGE_CONSUMPTION | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | — | Not independently audited this cohort; out of scope for M3's leaf-capability focus |
| CONTINUOUS_CAPABILITY_EVOLUTION (composite) | PARTIAL | PARTIAL | PARTIAL | PARTIAL | (sum of the above) | Real for the EXTERNAL loop's research->candidate->experiment path (RESEARCH_* + CAPABILITY_EXPERIMENT_VALIDATION rows); the INTERNAL experience loop is confirmed structurally broken on every side today (see below) — composite cannot be OPERATIONAL while either half is PARTIAL/ABSENT |

### Confirmed-broken mechanism common to Parent AND v50/Canonical (not a migration gap — a pre-existing defect on every side)

`tools/verification_flow/promotion_chain_audit_gate.py` hard-requires an
`EXPERIENCE_READY` event in its mandatory event list whenever
`failure_detected` is false, but **no stage in `gates.py`'s `STAGE_GATES` or
`prompts.py`'s `STAGE_INSTRUCTIONS` ever emits that event**, and
`memory_router.route_and_store()` has no caller in the prompt/gate pipeline
— confirmed identically broken on Parent, v50, and canonical (re-verified
fresh, not merely cited from the pre-existing `_tmp_experience_loop_design.txt`
design note, which independently documents the same gap). This is the
concrete, current-evidence reason `SIGNOFF_EXPERIENCE_CONSOLIDATION` and the
INTERNAL learning loop half of `CONTINUOUS_CAPABILITY_EVOLUTION` are
`ABSENT`/`PARTIAL` rather than `OPERATIONAL` — not a migration omission, a
real, pre-existing, still-open gap this migration inherits and must not
silently claim closed. **M8's job, not M3's.**

### `coverage_closure_loop_leg_matrix.py` — investigated, deferred (not migrated)

Zero Python-import dependencies, but 8 of its own tests fail in canonical:
the module performs literal-text self-checks against `cli.py`'s and
CLAUDE.md's specific source shape (e.g. "is the vPlan-traceability leg
really wired into cli.py", checked by inspecting cli.py's actual source
text) — Parent's and canonical's `cli.py`/CLAUDE.md structurally diverge
(different dispatch pattern, different module-index format per M1's own
CLAUDE.md router rewrite), so this module's hardcoded expectations about
*where* things appear in source text don't hold in canonical even though no
Python import is missing. **A real, hidden text-shape dependency invisible
to import-graph analysis alone** — caught only by running its actual tests,
exactly as instruction #14 anticipated. `DEFERRED_TO_M6/M7` (needs
canonical's own `cli.py` shape finalized first, which is M7's job).

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

## M4.5 — AI_ORCHESTRATION_TOKEN_OPTIMIZATION (new capability family)

Real, evidence-based audit (background investigation) of the "believed"
ChatGPT+Claude CLI+Codex multi-model token-efficiency capability. Full
detail: `M4_5_MULTI_MODEL_ORCHESTRATION_AUDIT.md`,
`M4_5_TOKEN_EFFICIENCY_CAPABILITY_MATRIX.csv`,
`M4_5_CHATGPT_INTEGRATION_AUDIT.md`, `M4_5_CODEX_INTEGRATION_AUDIT.md`,
`M4_5_STRUCTURED_HANDOFF_AUDIT.md`, `M4_5_TOKEN_OBSERVABILITY_AUDIT.md`.

**Headline finding**: `TOKEN_EFFICIENT_MULTI_MODEL_ORCHESTRATION` (as a
working automated loop) is `NOT_PRESENT` on any tree. `CHATGPT_INTEGRATION
= HUMAN_MEDIATED_CHATGPT_HANDOFF` (stale, abandoned pipeline).
`CODEX_INTEGRATION = HUMAN_MEDIATED_CODEX_REVIEW` (3 real, honest,
self-blocking package-assembly modules, Parent-only, not migrated).
`TOKEN_REDUCTION_MEASURED = NO`; real Claude-only token telemetry exists
(`stage_profile.py`, confirmed present in canonical) but is never combined
with any multi-model handoff.

One real, new, canonical-only capability WAS built this same M4.5 wave,
unrelated to the ChatGPT/Codex finding: `TASK_SCOPED_GOVERNANCE_RETRIEVAL`
(`dv_harness/governance_registry.py`, `OPERATIONAL`, 10/10 real tests) --
this is genuinely new infrastructure, not a preserved capability from
either source (neither source has an equivalent mechanism, per direct
verification against v50's real Phase-1-hygiene-audit evidence).

| Sub-capability | Status | Wave |
|---|---|---|
| `TASK_SCOPED_GOVERNANCE_RETRIEVAL` | OPERATIONAL (new, canonical-only) | M4.5 (done) |
| `MINIMUM_SUFFICIENT_CONTEXT` | PARTIAL | M4.5 (partial), M8+ (full) |
| `CHATGPT_PLANNING_OFFLOAD` | HUMAN_MEDIATED, stale, unmigrated | unscheduled |
| `CODEX_REVIEW_OFFLOAD` | HUMAN_MEDIATED, self-blocking, unmigrated | unscheduled |
| `STRUCTURED_AGENT_HANDOFF` | PARTIAL (review schema real, never operationalized; task/planning schema not found) | unscheduled |
| `CONTEXT_DISTILLATION` | PARTIAL (real for DUT/VIP evidence only) | unscheduled |
| `SESSION_RESUME` | UNKNOWN (not investigated to sufficient depth this wave) | future audit needed |
| `TOKEN_USAGE_OBSERVABILITY` | PARTIAL (real Claude-only telemetry, confirmed present in canonical) | unscheduled |

None of these 8 items are fixed/implemented/migrated this wave, per
instruction ("Do not implement missing multi-model integration during
M4.5"). All assigned `unscheduled` rather than defaulted into any specific
future wave number, consistent with the same discipline already applied
to the governing-contract-corpus finding.
