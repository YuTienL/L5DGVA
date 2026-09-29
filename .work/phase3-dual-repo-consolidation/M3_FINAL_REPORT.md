# M3 Final Report — Independent/Leaf Capability Migration

Two cohorts executed on branch `canonical/m3-capability-union`, off the
approved M1 checkpoint (`9a5c3eeb2a894c86d9c85186d58aa46002c5ef9c`). Cohort
selection derived from the existing authoritative registries
(`17_CANONICAL_MIGRATION_WAVES.md`, `05_PARENT_ONLY_FILE_CLASSIFICATION.csv`,
`09_TRANSITIVE_DEPENDENCY_CLOSURE.md`) — not rediscovered from scratch — plus
one dedicated read-only audit for the research/experience-learning
capability-preservation addendum. Full detail in
`M3_CAPABILITY_MIGRATION_RECORDS.md` and `CANONICAL_CAPABILITY_SUPERSET_MATRIX.md`.

## Cohort 1 (4 migrated, 3 investigated-and-deferred)

`lifecycle.py`, `debug_evidence_behavioral_firewall_gate.py`,
`l5dgva_v5_ss86_understanding_plan_contradiction_taxonomy.py`,
`diagnostic_bound_compatibility.py` — all Parent-only, zero internal
dependencies, each ported with its own real test file, 57/57 pass.

3 originally-eligible-by-static-analysis candidates
(`ipxact_register_import.py`, `reference_irq_event_to_service_flow_discovery.py`,
`l5dgva_requirement_dependency_closure.py`) were removed after **real test
execution** — not static import analysis — surfaced dependency gaps: a
pre-DUT-10 `register_excel_extract.py` API mismatch, a Reference-USB-tree
test dependency blocked by standing policy, and an unmigrated
`l5dgva_contract_registry.py` dependency respectively. Reassigned to M5,
M11, and M4.

## Cohort 2 (1 migrated, 1 investigated-and-deferred, capability-family audit)

Per the research/experience-learning preservation addendum: a dedicated
audit traced 18 named capability sub-families across Parent, v50/canonical,
and worktrees. **Headline finding: canonical already had the overwhelming
majority of both families via its v50 lineage** — re-confirmed present
directly (`self_learning_readiness.py`, `memory_lineage.py`,
`memory_quality_policy.py`, `user_correction_trigger.py`,
`coverage_closure_hole_correlation.py`, confidence-reweight functions,
`coverage_closure_action_utility.py`, `cross_project_mining.py`).

`coverage_hole_generation_candidate_queue.py` (CAP-M3-005) migrated — the
one real Parent-only gap in `COVERAGE_CLOSURE_LEARNING` — after correcting
an earlier over-broad deferral in this same session (file-level "diverged"
flag was too coarse; specific-symbol check + a real 12/12 test pass
resolved it). `coverage_closure_loop_leg_matrix.py` investigated and
deferred to M6/M7: zero import dependency, but 8 tests fail on a hidden
text-shape dependency against `cli.py`/CLAUDE.md's literal source, which
diverges structurally between Parent and canonical.

A real, pre-existing, identically-broken mechanism was confirmed on every
tree (not a migration gap): the `EXPERIENCE_READY` promotion-gate wiring.
Explicitly assigned to M8, not fixed here.
`CLARIFICATION_LEARNING`/`GENERATION_EXPERIENCE_LEARNING`/a unified
`Experience` record type: confirmed absent on every tree by direct
evidence, real future-build items for M8.

## Verification performed

- Both cohorts: full-repo `--collect-only` clean after each (13842, then
  13854, tests collected — no import/naming collision introduced)
- `dv-harness doctor`: `ROOT_LAYOUT_GATE: PASS`, `REPOSITORY_IDENTITY: PASS`
  unchanged throughout
- No `engine.py`/`cli.py`/`dashboard.py`/`question_queue.py`/
  `multi_agent.py`/`loop_telemetry.py` modification — every M3 exclusion
  respected
- No worktree modified; no worktree branch merged
- Source integrity re-verified before and after both cohorts: Parent
  `3e9dd736`, v50 `f3fd173`, b7a `7b2a65a`, b7b `c7c7fa0`, b8 `c9cdd06` —
  all unchanged throughout M3

## Report

```
M3_STATUS = READY_FOR_APPROVAL

M3_BRANCH = canonical/m3-capability-union
M3_HEAD = 12ca213e5da58e04f19b31bbfa160a0e22f30678

M3_ELIGIBLE_CAPABILITIES = 9 (candidates copied into the canonical repo and
                              given a real, test-execution-backed migration
                              decision: 7 in Cohort 1 + 2 in Cohort 2)
M3_MIGRATED_CAPABILITIES = 5 (CAP-M3-001 through CAP-M3-005)
M3_DEFERRED_CAPABILITIES = 4, each test-execution-investigated and
                            reassigned with a concrete reason
                            (ipxact_register_import.py -> M5,
                             reference_irq_event_to_service_flow_discovery.py -> M11,
                             l5dgva_requirement_dependency_closure.py -> M4,
                             coverage_closure_loop_leg_matrix.py -> M6/M7)

Additionally, ~16 further candidates were screened at the lighter,
static-dependency-check level during cohort selection (never copied in,
since a real blocking dependency was already visible from their own
import statements) and reassigned to M4/M5/M7/M8 -- full list in
CANONICAL_CAPABILITY_SUPERSET_MATRIX.md's "investigated-but-not-migrated"
table. This is NOT an exhaustive triage of all 177
MIGRATE_REQUIRED_DIRECT/TRANSITIVE files -- a disclosed scope boundary
("prefer a conservative batch"), not silence.

M3_FILES_ADDED = 10 (5 capability modules + 5 test files)
M3_FILES_MODIFIED = 0 (no existing canonical file was modified -- pure
                        additive migration, consistent with "capability,
                        not file" and "no semantic merge" for this wave)

SOURCE_CAPABILITY_LOSS = 0
V50_CAPABILITY_LOSS = 0
CANONICAL_NEW_PRESERVED_CAPABILITIES = 5
CANONICAL_ENHANCED_CAPABILITIES = 0 (M3 adds new standalone modules only;
                                      no existing canonical capability was
                                      enhanced -- that requires the
                                      semantic-merge waves)
UNKNOWN_MIGRATION_FAILURES = 0

ROOT_LAYOUT_GATE = PASS
LOCATION_INDEPENDENT = YES

CANONICAL_CAPABILITY_STRICT_SUPERSET = NOT_YET_QUALIFIED

M1_CHECKPOINT_PRESERVED = YES (9a5c3eeb2a894c86d9c85186d58aa46002c5ef9c
                                unchanged, unrewritten; M3 branched off it)

SOURCE_A_CHANGED_SINCE_M0 = NO
SOURCE_B_CHANGED_SINCE_M0 = NO
B7A_CHANGED = NO
B7B_CHANGED = NO
B8_CHANGED = NO

REFERENCE_USB_ENV_CONSUMED = NO

C6_STARTED = NO
PLATFORM_UPGRADE_STARTED = NO
```

**M3_STATUS = READY_FOR_APPROVAL.**

**STOP. Not starting M4/M5/M6. Waiting for review.**
