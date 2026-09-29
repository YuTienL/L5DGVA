# M8 Preflight Report

Analysis / planning / evidence-gathering pass only. M8 implementation NOT
authorized by this report. No production code modified. M7 not reopened.
Reference USB not consumed (`REFERENCE_USB_ENV_CONSUMED=NO`, re-verified
throughout).

## 0. Canonical start state (independently re-verified, not trusted blindly)

```
CURRENT_CANONICAL_HEAD (at Preflight start) = 3477ea85da4b
M7_STATUS                                    = CLOSED_WITH_KNOWN_LIMITATIONS
M8_STATUS                                    = NOT_STARTED
NEXT_CANONICAL_GATE                          = M8_PREFLIGHT
Q-ENV-57D420FA                               = OPEN, unchanged
REVIEW_002_TRANSPORT_REQUIRED                = NO
REFERENCE_USB_ENV_CONSUMED                   = NO
```
All independently re-derived from `MASTER_PROGRAM_STATUS.md`, the real
Question Queue, and the real REVIEW-002 workflow state -- matched the
prior dispatch's own claims exactly.

A separate, bounded governance reconciliation
(`M8_DISCOVERY_REMEDIATION_GOVERNANCE_RECONCILIATION.md`) was performed
before this Preflight body, per explicit instruction: the proposed P7
(Discovery/Remediation separation) and P8 (no discovered gap may
disappear) semantics are `ADOPT` -- already representable via existing
Gap Register/Wave Ownership/Question Queue/Cohort-Plan mechanisms, 0
production code changes required. This report applies that reconciled
model throughout.

## 1. Re-derived M8 scope (not derived from any prompt's own prose alone)

Re-derived from `MASTER_CAPABILITY_STATUS_MATRIX.csv` and `MASTER_WAVE_
OWNERSHIP_MATRIX.csv`'s own `PRIMARY_OWNER_WAVE=M8` rows -- **17 real
rows**, not a hand-picked subset of the 7 items the dispatch's own prose
named. Full classification: `M8_SCOPE_AND_OWNERSHIP_MATRIX.csv`.

```
M8_SCOPE_ITEMS_TOTAL     = 17
M8_SCOPE_ITEMS_CONFIRMED = 17 (all M8_OWNED, re-verified against the
                           authoritative matrices, none disputed)
M8_SCOPE_ITEMS_EXCLUDED  = 0 (nothing removed from scope; 3 low-priority
                           items -- CAP-M4.5-011, CAP-POOL-002,
                           CAP-POOL-010 -- remain M8-owned but are
                           explicitly NOT required to reach WIRED for M8
                           closure, per M8_EXIT_CRITERIA.md's own
                           "explicitly NOT required" section)
```

## 2. Experience loop root cause (CAP-M8-EXPLOOP-001)

Independently reproduced this task (not re-cited from the Capability
Matrix). Full trace: `M8_EXPERIENCE_LOOP_TRACE.md`.

**Precise root cause**: `promotion_chain_audit_gate`'s `EXPERIENCE_READY`
stage is architecturally a self-attested agent claim (`gates.py`'s own
`EvidenceFlag` docstring: *"A CLI flag whose value is agent-attested"*),
structurally validated for presence/order/non-empty-string only --
**never cross-verified against the real, separately-wired `EXPERIENCE_
KNOWLEDGE_PROMOTED`/`route_and_store()` mechanism that already works**
in `engine.py` (6+ real call sites, PASS-gated, tested). Two real halves,
mismatched names, no connecting code path -- a missing bridge, not a
missing producer or a missing consumer.

## 3. CAP-CE-018 relationship (dispatch section 4)

Neither "same defect at two abstraction levels" nor "fully separate" --
`CAP-CE-018` is a real composite with an explicit, CSV-recorded
dependency on BOTH `CAP-M8-EXPLOOP-001` and `CAP-M8-EXPLOOP-002`. One
authoritative mapping, not a duplicate solution target. Full detail:
`M8_DEPENDENCY_GRAPH.md`.

## 4. Global Discoverability Contract (CAP-M4.6-002)

Three real, layered mechanisms exist (registry+reachability, structural
CLAUDE.md-diff, one opt-in production consumer) -- but only 1 of ~301-307
`TASK_SCOPED` sections (the Research Front Door) has a proven BEHAVIORAL
discoverability test. Sampled 6-7 of the 14 lowest-confidence sections:
zero appear anywhere in current CLAUDE.md. `check_reachability()` proves
file-existence only, never that a fact actually surfaces when relevant.
**A real, currently-red test was independently reproduced this task**:
`test_no_current_scope_gap_is_ever_recorded_as_document_only` FAILS (1
failed, 5 passed) -- a pre-existing Gap Register vocabulary drift from
this session's own prior M7 work (GAP-V2-015/016/017), unrelated to M8's
own scope, registered as `GAP-M8-006` and NOT fixed here.

```
GLOBAL_DISCOVERABILITY_STATUS = PARTIAL (1 of ~301-307 sections
                                 behaviorally proven; systematic re-audit
                                 required, scoped as Cohort 3)
```

## 5. Multi-Agent Knowledge Consumption (CAP-M8-MAKC-001)

First real audit of this capability -- previously `NOT_VERIFIED`/
effectively unaudited. Real 5-tier trace: Project tier has a real,
passing, code-level cross-agent-consumption proof (`test_run_stage_
retrieves_relevant_memory_into_the_prompt`); Job tier is partially
decision-influencing (repeated-failure detection); Engineering tier
shares the Project-tier mechanism plus an opt-in-but-off-by-default
cross-project Knowledge Center path; Organizational tier has ZERO local
persistence and is a silent no-op without an unconfigured-by-default
remote KC. A real, load-bearing reconciliation finding: the M3-era claim
"`route_and_store()` has no caller in the prompt/gate pipeline" is stale
-- current `engine.py` has 6+ real, tested, PASS-gated callers. Full
detail: `M8_KNOWLEDGE_CONSUMPTION_AUDIT.md`.

```
MULTI_AGENT_KNOWLEDGE_CONSUMPTION_STATUS = PARTIAL (upgraded from
                                            NOT_VERIFIED this Preflight)
```

## 6. Role-Aware Experience Learning (CAP-HITL-008) / Knowledge Domain Classification (CAP-HITL-009)

Both real, both design-only (schema/taxonomy defined in the M4.5 DE/DV
HITL roadmap wave, zero code on any tree). `CAP-HITL-008` structurally
depends on `CAP-M8-EXPLOOP-001` closing first (per `MASTER_WAVE_
OWNERSHIP_MATRIX.csv`'s own `SECONDARY_DEPENDENCY`); `CAP-HITL-009` has
no cross-capability dependency and could be built independently/earlier.
No new role taxonomy invented -- the existing `DESIGN_AUTHORITY`/
`VERIFICATION_AUTHORITY`/`SHARED_AUTHORITY` model from the DE/DV HITL
architecture is reused as-is, per instruction.

```
ROLE_AWARE_EXPERIENCE_LEARNING_STATUS = FOUNDATION_ONLY (real design doc,
                                          zero code)
KNOWLEDGE_DOMAIN_CLASSIFICATION_STATUS = FOUNDATION_ONLY (real design doc,
                                          zero code)
```

## 7. Constitution Qualification (CAP-M4.5-003)

Real, narrow, textual-intactness gate (`constitution_gate.py`, 7 real
checks) -- live-run this task, `PASS, 0 reasons`. Automatic invocation is
genuinely `PARTIAL` (only incidentally covered by the full CI test suite,
never a dedicated step; not one of `self_audit.py`'s 23 gates; excluded
from the fast `pre-push` subset). **No coded `FINAL_COMPLIANCE_GATE`
evaluator exists at all** for the 13 named "Final Constitutional
Acceptance" sub-criteria -- only a fixed sentinel string. Full detail,
the complete rule-by-rule mapping: `M8_CONSTITUTION_QUALIFICATION_PLAN.md`.

```
CONSTITUTION_PREFLIGHT_STATUS = COMPLETE (the mapping this Preflight
                                 exists to produce is real and complete;
                                 the underlying gate itself remains
                                 PARTIAL/NOT_YET_QUALIFIED, correctly
                                 unresolved by a Preflight pass)
```

## 8. Production Reachability (strict WIRED definition, all 17 rows)

Full matrix: `M8_CAPABILITY_REACHABILITY_MATRIX.csv`. Summary:

```
WIRED             = 0 of 17 (none reach the full strict bar)
PARTIALLY_WIRED   = 6 (CAP-M4.5-003, CAP-M8-EXPLOOP-001, CAP-M4.6-002,
                    CAP-CE-008, CAP-CE-012, CAP-CE-018)
FOUNDATION_ONLY   = 3 (CAP-M4.5-002, CAP-HITL-008, CAP-HITL-009)
ABSENT            = 8 (CAP-M4.5-011, CAP-POOL-002, CAP-POOL-010,
                    CAP-M8-EXPLOOP-002, CAP-M8-MAKC-001, CAP-CE-010,
                    CAP-CE-011, CAP-CE-014)
```

The single most load-bearing missing production edge, confirmed by
independent re-derivation: no `engine.py` stage ever emits `EXPERIENCE_
READY` (`CAP-M8-EXPLOOP-001`) -- `route_and_store()` IS genuinely called
at 6+ production sites, but never in a way that satisfies this specific
stage-chain. Closing this one edge would not make the 8 fully-ABSENT rows
exist, but is the edge that would move the most currently-blocked rows
toward real WIRED status.

## 9. Source-tree reconciliation (dispatch section 11)

Read-only lineage check (Parent, v50 -- never modified): the same
`EXPERIENCE_READY` self-attestation defect exists on ALL THREE trees
(Parent, v50, canonical), confirmed by direct grep of each. v50 contains
a real, PARTIAL prior attempt worth recording as a candidate, not
importing: `experience_knowledge_gate` (a stricter, more-fields-required
self-attestation check inside the separate `EXPERT_FEEDBACK_LOOP` stage,
`v50/dv_harness_tests/test_engine_gates_and_routing.py:1638-1639`'s own
comment: *"EXPERIENCE_READY was previously a dangling reference... now
enforces the fields needed before promotion"*) -- still fundamentally
self-attestation-based (an agent-supplied `expert_approved: true` field
is trusted, never cross-verified), not a full fix, but real evidence this
exact problem class was previously worked on elsewhere. Not migrated;
recorded as evidence only, per instruction.

## 10. M7 limitation firewall (dispatch section 12)

No Post-M7 hardening item was pulled into M8 scope. `CURRENT_SESSION_
EXECUTOR` activation improvements, detached-Claude host-policy work,
watcher telemetry polish, and quarantined-hash logging cleanup all remain
correctly excluded -- none of M8's own 17 real capability rows traces a
dependency to any of them.

## 11. Human Authority (dispatch section 13)

`Q-ENV-57D420FA` (R005-2/R006-4): re-checked, still `OPEN`, untouched.
No M8-owned capability's own dependency chain (`M8_DEPENDENCY_GRAPH.md`)
traces to it.

```
Q_ENV_57D420FA_DEPENDENCY = NON_BLOCKING_HUMAN_AUTHORITY_ITEM
```

## Final Preflight report fields

```
M8_PREFLIGHT_STATUS       = CLOSED
M8_IMPLEMENTATION_STATUS  = NOT_STARTED

M8_SCOPE_ITEMS_TOTAL      = 17
M8_SCOPE_ITEMS_CONFIRMED  = 17
M8_SCOPE_ITEMS_EXCLUDED   = 0

M8_CURRENT_CAPABILITY_GAPS   = 9 (GAP-M8-001 through GAP-M8-009,
                                see M8_GAP_REGISTER.csv)
M8_CURRENT_SCOPE_BLOCKERS    = 0 (GAP-M8-001/002/005/007/008 are real,
                                CURRENT_MILESTONE_BLOCKER/SCOPE-classified
                                findings targeted at M8 IMPLEMENTATION,
                                not blockers to PREFLIGHT's own closure --
                                Preflight requires UNCLASSIFIED_GAPS=0/
                                UNOWNED_GAPS=0/OPEN_BLOCKING_GAPS=0, never
                                ALL_GAPS_CLOSED=YES, per the adopted P7/P8
                                model)
M8_SECURITY_BLOCKERS         = 0

CAP_M8_EXPLOOP_001_STATUS              = CONFIRMED_BROKEN (root cause precisely traced)
CAP_CE_018_STATUS                      = PARTIAL/ABSENT (composite depends on EXPLOOP-001+002)
GLOBAL_DISCOVERABILITY_STATUS          = PARTIAL (1 of ~301-307 sections proven)
MULTI_AGENT_KNOWLEDGE_CONSUMPTION_STATUS = PARTIAL (upgraded from NOT_VERIFIED)
ROLE_AWARE_EXPERIENCE_LEARNING_STATUS  = FOUNDATION_ONLY
KNOWLEDGE_DOMAIN_CLASSIFICATION_STATUS = FOUNDATION_ONLY
CONSTITUTION_PREFLIGHT_STATUS          = COMPLETE (mapping done; gate itself PARTIAL)

IMPLEMENTATION_COHORTS    = 6 (Cohort 1 foundation; Cohort 2 absent
                            stages; Cohort 3 discoverability, parallel-
                            eligible; Cohort 4 role/domain; Cohort 5
                            Constitution rollup; Cohort H optional
                            hardening)
M8_EXIT_CRITERIA_COUNT    = 16 (see M8_EXIT_CRITERIA.md)

Q_ENV_57D420FA_DEPENDENCY = NON_BLOCKING_HUMAN_AUTHORITY_ITEM
REFERENCE_USB_ENV_CONSUMED = NO

PRODUCTION_FILES_CHANGED  = 0
UNKNOWN_PREFLIGHT_ITEMS   = 1 (no real dynamic re-prioritization scoring
                            mechanism exists yet for USB-operational-
                            feedback criteria -- deferred per instruction
                            until real USB Generation Vertical Slice
                            evidence exists; see the governance
                            reconciliation's own UNKNOWN_ITEMS section)

NEXT_CANONICAL_GATE = M8_IMPLEMENTATION_COHORT_1
```

**STOP. M8 Preflight complete. Scope frozen, dependencies mapped, gaps
evidenced (9 real gaps, each classified and owned, none disappeared),
implementation cohorts ordered (6, dependency-derived, none a giant all-
at-once wave), exit criteria frozen (16, each objectively classifiable).
No M8 defect was fixed during this Preflight. No production code was
modified. M7 was not reopened. Reference USB was not consumed. Cohort 1
is NOT automatically started.**
