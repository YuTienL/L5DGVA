# M8 Implementation Cohort Plan

Preflight evidence only -- naming/ordering cohorts is planning, not
starting them. Derived from `M8_DEPENDENCY_GRAPH.md`'s real dependency
edges and `M8_GAP_REGISTER.csv`'s real, evidenced gaps -- never a
suggested 6-7-step template imposed without evidence.

## Cohort 1: EXPERIENCE_READY root-edge fix (foundation)

```
CAPABILITY_IDS:        CAP-M8-EXPLOOP-001 (GAP-M8-001)
DEPENDENCIES:          none -- the real foundation node
FILES_EXPECTED_TO_CHANGE: dv_harness/engine.py (the real EXPERIENCE_
                        KNOWLEDGE_PROMOTED emission sites, lines 1944/
                        3189/3258/3434/3656); tools/verification_flow/
                        promotion_chain_audit_gate.py or gates.py's own
                        evidence-extraction path (to cross-verify the
                        agent's self-attested EXPERIENCE_READY claim
                        against a real EXPERIENCE_KNOWLEDGE_PROMOTED
                        event for the same task)
PRODUCTION_EDGE_TO_CLOSE: the missing bridge between the two real,
                        currently-disconnected mechanisms identified in
                        M8_EXPERIENCE_LOOP_TRACE.md
TESTS:                  a new test proving EXPERIENCE_READY is accepted
                        ONLY when a real EXPERIENCE_KNOWLEDGE_PROMOTED
                        event/route_and_store() call exists for the same
                        task/stage; a negative test proving a bare
                        self-attested claim with no real backing event is
                        REJECTED
LIVE_QUALIFICATION:     a real PROMOTION_READINESS stage run (or a
                        realistic simulated one) where the fix correctly
                        distinguishes a genuine experience-promotion from
                        a bare claim
EXIT_CRITERIA:          promotion_chain_audit_gate can no longer be
                        satisfied by agent self-attestation alone
ROLLBACK_BOUNDARY:      engine.py's own existing KC-harvest call sites
                        (1944/3189/3258/3434/3656) and their real,
                        already-tested PASS-branch behavior must remain
                        unchanged in every case where no EXPERIENCE_READY
                        cross-check is involved
```

## Cohort 2: Absent internal-loop stages (depends on Cohort 1)

```
CAPABILITY_IDS:        CAP-M8-EXPLOOP-002, CAP-CE-010, CAP-CE-011,
                        CAP-CE-014 (GAP-M8-002)
DEPENDENCIES:          Cohort 1 (these stages feed the same
                        EXPERIENCE_READY/EXPERIENCE_KNOWLEDGE_PROMOTED
                        chain Cohort 1 makes trustworthy)
FILES_EXPECTED_TO_CHANGE: net-new modules for CLARIFICATION_LEARNING /
                        GENERATION_EXPERIENCE_LEARNING / SIGNOFF_
                        EXPERIENCE_CONSOLIDATION, plus a unified
                        Experience record type (no existing module to
                        extend -- confirmed genuinely absent)
PRODUCTION_EDGE_TO_CLOSE: each stage's own producer -> the unified record
                        type -> Cohort 1's now-trustworthy EXPERIENCE_
                        READY chain
TESTS:                  a real behavioral test per stage, analogous to
                        the existing KC-harvest tests already covering
                        the working PASS-branch mechanisms
LIVE_QUALIFICATION:     a real end-to-end run through each of the 3
                        newly-built stages, producing a real persisted
                        Experience record
EXIT_CRITERIA:          all 3 stages produce real, tested, persisted
                        Experience records; CAP-CE-018's own composite
                        can be re-evaluated as real rather than
                        PARTIAL/ABSENT
ROLLBACK_BOUNDARY:      no existing PROMOTION_READINESS/experience
                        mechanism regresses -- explicit regression sweep
                        of engine.py's existing memory-tier tests required
```

## Cohort 3: Discoverability systematic re-audit (independent of Cohorts 1-2)

```
CAPABILITY_IDS:        CAP-M4.6-002 (GAP-M8-005)
DEPENDENCIES:          none -- can run in parallel with Cohorts 1-2
FILES_EXPECTED_TO_CHANGE: CLAUDE.md (compact ALWAYS_ON pointers, per
                        instance, following the Research Front Door
                        precedent -- never re-inflating toward the
                        pre-M4.6 901,622-byte state); possibly new
                        dv_harness/router.py-style intent classifiers for
                        genuinely entry-point-class facts
PRODUCTION_EDGE_TO_CLOSE: the ~300-section behavioral-discoverability gap
                        Agent A's report identified with concrete
                        file:line proof (6-7 sampled sections, zero
                        CLAUDE.md matches)
TESTS:                  a behavioral test per newly-classified entry-
                        point-class section, same shape as
                        test_research_intent_routing.py (replay plausible
                        phrasing, assert the right content surfaces)
LIVE_QUALIFICATION:     a real task phrased plausibly for each newly-
                        classified section, confirming the right content
                        is actually reached
EXIT_CRITERIA:          every section classified entry-point-class (not
                        merely reference-detail-class) has a real
                        behavioral discoverability test passing
ROLLBACK_BOUNDARY:      CLAUDE.md's own byte-size ceiling (Article 0 P3 /
                        MINIMUM_SUFFICIENT_CONTEXT) must never regress
                        back toward the pre-M4.6 state
```

## Cohort 4: Role-Aware Experience Learning + Knowledge Domain Classification

```
CAPABILITY_IDS:        CAP-HITL-008 (depends on Cohort 1),
                        CAP-HITL-009 (independent)
DEPENDENCIES:          CAP-HITL-008 needs Cohort 1 closed first;
                        CAP-HITL-009 has no cross-capability dependency
                        and MAY run earlier/in parallel
FILES_EXPECTED_TO_CHANGE: net-new modules building on the existing
                        M4.5 DE/DV HITL roadmap schema/architecture docs
                        (currently design-only, zero code)
PRODUCTION_EDGE_TO_CLOSE: schema -> real classifier/consumer -> Memory-
                        tier integration
TESTS:                  real behavioral tests proving role-classified/
                        domain-classified experience records are
                        actually retrievable differently per role/domain
LIVE_QUALIFICATION:     a real retrieval scenario distinguishing at least
                        2 roles/domains with different results
EXIT_CRITERIA:          both capabilities move from ROADMAP_DEFINED/
                        DEFINED to real, tested, WIRED status
ROLLBACK_BOUNDARY:      the existing single-Knowledge-Brain,
                        one-generic-workflow invariant (`KNOWLEDGE_
                        BRAIN_COUNT=1`, already frozen in MASTER_PROGRAM_
                        STATUS.md) must never be violated -- no second
                        Knowledge Brain, no separate DE/DV engines
```

## Cohort 5: Constitution final-compliance composite (depends on Cohorts 1-4)

```
CAPABILITY_IDS:        CAP-M4.5-003 final compliance (GAP-M8-007,
                        GAP-M8-008)
DEPENDENCIES:          Cohorts 1-4 (the 13 named sub-criteria draw
                        evidence from CAP-M8-EXPLOOP-001/002,
                        CAP-M8-MAKC-001, CAP-M4.6-002 -- this cohort is
                        the rollup, not independent work)
FILES_EXPECTED_TO_CHANGE: dv_harness/constitution_gate.py (a new
                        FINAL_COMPLIANCE_GATE-style function); a CI step
                        or dv-harness constitution-check CLI verb for
                        automatic invocation
PRODUCTION_EDGE_TO_CLOSE: the missing FINAL_COMPLIANCE_GATE evaluator
                        (confirmed not to exist even in skeleton form);
                        the missing automatic-invocation wiring
TESTS:                  a test asserting a computed FinalComplianceResult
                        object's per-sub-criterion values against live
                        evidence; a test asserting the CLI verb/CI step
                        exists and is referenced by name
LIVE_QUALIFICATION:     a real run of the composite evaluator against the
                        post-Cohort-1-4 codebase, producing a real
                        (likely still PARTIAL, honestly) verdict
EXIT_CRITERIA:          a real, coded, callable composite evaluator
                        exists (its VERDICT need not be PASS -- Migration-
                        Wave Scoping explicitly allows this -- but the
                        EVALUATOR itself must be real); automatic
                        invocation wired
ROLLBACK_BOUNDARY:      constitution_gate.py's own existing textual-
                        intactness checks (already real, already PASS)
                        must remain unchanged and still PASS
```

## Cohort H: Hardening/Cleanup (optional, bounded -- reuses the existing cohort model per `M8_DISCOVERY_REMEDIATION_GOVERNANCE_RECONCILIATION.md`)

```
CAPABILITY_IDS:        GAP-M8-003 (Organizational Memory inertness),
                        GAP-M8-004 (debug-agent.md prose-only retrieval
                        instruction), GAP-M8-009 (stale MASTER_
                        CAPABILITY_STATUS_MATRIX.csv citation)
DEPENDENCIES:          none blocking -- reserved AFTER the functional
                        cohorts, BEFORE final convergence, per the
                        governance reconciliation's own explicit bound
FILES_EXPECTED_TO_CHANGE: .claude/agents/debug-agent.md (documentation);
                        MASTER_CAPABILITY_STATUS_MATRIX.csv (bookkeeping);
                        optionally config.py/a remote KC setup decision
                        (GAP-M8-003 -- may instead be explicitly accepted
                        and documented rather than fixed)
PRODUCTION_EDGE_TO_CLOSE: none required -- these are bounded, low-
                        architectural-risk, well-understood items
TESTS:                  a static check that every agent profile
                        referencing memory retrieval names the real API
                        (GAP-M8-004); no dedicated test for GAP-M8-003/009
                        (documentation-only)
LIVE_QUALIFICATION:     not required for documentation-only items
EXIT_CRITERIA:          each item explicitly resolved OR explicitly
                        deferred with a documented reason -- this cohort
                        must NEVER become "fix every open issue before M8
                        can close"
ROLLBACK_BOUNDARY:      documentation/bookkeeping only -- no production
                        behavior change expected
```

## Dependency graph (text form)

```
Cohort 1 (EXPLOOP-001 root edge)
  |
  +--> Cohort 2 (absent internal-loop stages)
  |
  +--> Cohort 4's CAP-HITL-008 only (CAP-HITL-009 independent, may run anytime)
  |
  +--> Cohort 5 (Constitution final-compliance rollup, needs 1+2+3+4 evidence)

Cohort 3 (discoverability re-audit) -- fully independent, parallel-eligible

Cohort H (hardening) -- after the functional cohorts, before final convergence
```

Avoids a giant all-at-once implementation: each cohort has its own real
exit criteria and rollback boundary; Cohort 1 alone unblocks the largest
number of downstream rows (8 of 17), matching `M8_DEPENDENCY_GRAPH.md`'s
own finding.
