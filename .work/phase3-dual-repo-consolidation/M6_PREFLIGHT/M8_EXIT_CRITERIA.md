# M8 Exit Criteria (frozen before implementation starts)

Per the milestone semantics table in `MASTER_PROGRAM_STATUS.md`: `M8:
Canonical >= verified union of all migration sources`. Each criterion
below is objectively classifiable as `PASS`/`FAIL`/`PARTIAL`/`NOT_
APPLICABLE` -- no vague criteria ("architecture improved", "learning
works better", "agents are smarter").

## Foundation

1. **`CAP-M8-EXPLOOP-001` production edge closed**: `promotion_chain_
   audit_gate`'s `EXPERIENCE_READY` stage can no longer be satisfied by
   agent self-attestation alone -- it is cross-verified against a real
   `EXPERIENCE_KNOWLEDGE_PROMOTED`/`route_and_store()` event for the same
   task. Evidence: `GAP-M8-001`'s own new test (negative case: bare claim
   rejected; positive case: real event accepted).

## Internal experience loop

2. **`CAP-M8-EXPLOOP-002` stages real**: `CLARIFICATION_LEARNING`,
   `GENERATION_EXPERIENCE_LEARNING`, `SIGNOFF_EXPERIENCE_CONSOLIDATION`
   each have a real producer, a unified Experience record type, and a
   real behavioral test. Evidence: `GAP-M8-002`'s own per-stage tests.
3. **`CAP-CE-018` composite re-evaluated**: with criteria 1-2 satisfied,
   the composite's own `CANONICAL_STATE` moves from `PARTIAL/ABSENT` to a
   real, evidence-backed state (need not be fully `OPERATIONAL` -- must
   be re-derived from real evidence, not assumed).
4. **`CAP-CE-012` (`RCA_EXPERIENCE_LEARNING`)**: unchanged from its
   current real `PARTIAL` state is acceptable -- this criterion is
   satisfied if its own existing real mechanism (`repeated_unresolved_
   failure_patterns()`) is not regressed, not that it must reach FULL.
5. **`CAP-HITL-008` (`ROLE_AWARE_EXPERIENCE_LEARNING`)**: moves from
   `ROADMAP_DEFINED` to real, tested, `WIRED` status (Cohort 4).

## Discoverability

6. **`CAP-M4.6-002` systematic re-audit performed**: every one of the
   ~301-307 `TASK_SCOPED` CLAUDE.md sections is classified entry-point-
   class or reference-detail-class (a real body-read, not heading-
   keyword-match); every entry-point-class section has a real behavioral
   discoverability test, analogous to `test_research_intent_routing.py`.
   `PARTIAL` is an acceptable exit value if a documented, evidenced
   remainder is explicitly deferred (`GAP-M8-005`'s own disposition).

## Multi-agent knowledge consumption

7. **`CAP-M8-MAKC-001` audit complete and MASTER_CAPABILITY_STATUS_
   MATRIX.csv reconciled**: the matrix's own `NOT_VERIFIED`/stale-citation
   state is corrected to reflect this Preflight's real findings (2 of 5
   tiers proven cross-agent-consumed; Organizational tier disclosed
   inert). `PARTIAL` is an acceptable exit value -- full `OPERATIONAL`
   across all 5 tiers is NOT required for M8 closure unless a future
   convergence pass proves it is a frozen blocker.
8. **`CAP-HITL-009` (`KNOWLEDGE_DOMAIN_CLASSIFICATION`)**: moves from
   `DEFINED` (taxonomy only) to real, tested, `WIRED` status.

## Constitution

9. **Automatic invocation wired**: `constitution_gate.check_constitution_
   intact()` is invoked by a named CI step and/or a `dv-harness
   constitution-check` CLI verb, not merely incidentally collected by the
   full test suite.
10. **`FINAL_COMPLIANCE_GATE` evaluator exists**: a real, callable
    function computing the 13 named "Final Constitutional Acceptance"
    sub-criteria from real evidence sources exists (`constitution_gate.
    py` or a sibling module). Its VERDICT need not be `PASS` (Migration-
    Wave Scoping explicitly allows a non-`PASS` final verdict at this
    wave) -- the EVALUATOR itself existing and being real is the
    criterion, matching this program's own `WIRED != EXECUTED`/`resolved
    != implemented` discipline from the M7 program.

## Program-level (per the frozen milestone semantics)

11. **`CURRENT_SCOPE_CORRECTNESS_BLOCKERS = 0`** at M8 closure (not at
    Preflight closure -- Preflight itself requires `UNCLASSIFIED_GAPS=0`/
    `UNOWNED_GAPS=0`/`OPEN_BLOCKING_GAPS=0`, never `ALL_GAPS_CLOSED=YES`,
    per `M8_DISCOVERY_REMEDIATION_GOVERNANCE_RECONCILIATION.md`).
12. **`CURRENT_SCOPE_SECURITY_BLOCKERS = 0`**.
13. **`M6_GOLDEN_PATH_PRESERVED = YES`** and **`M7`'s own closed status is
    not regressed** -- re-verified before every M8 commit, matching the
    established discipline throughout M7.
14. **All 5 frozen reference sources unchanged** (Parent, v50, b7a, b7b,
    b8) -- re-verified before every commit, matching established
    discipline.
15. **`REFERENCE_USB_ENV_CONSUMED = NO`** remains true throughout M8
    (explicitly out of M8's own scope per the roadmap -- M11 owns it).
16. **`Q-ENV-57D420FA` remains `OPEN`, untouched** -- M8 does not depend
    on or force this Human Authority item's resolution (confirmed
    `NON_BLOCKING_HUMAN_AUTHORITY_ITEM` per section 13 of the dispatch;
    no M8-owned capability's dependency chain traces to it).

## Explicitly NOT required for M8 closure

- `ALL_GAPS_CLOSED = YES` (never required, per the governance
  reconciliation).
- `CAP-M4.5-011` (Cross-model token measurement), `CAP-POOL-002`,
  `CAP-POOL-010` reaching real/WIRED status -- all P3, disclosed as real
  but low-priority; `PARTIAL`/`ABSENT`-with-documented-deferral is an
  acceptable exit state for these three specifically.
- `GAP-M8-003` (Organizational Memory) being FIXED rather than explicitly
  accepted as a documented architectural boundary.
- `GAP-M8-006` (the pre-existing Gap Register vocabulary drift) being
  fixed by M8 at all -- it predates M8, is unrelated to M8's own scope,
  and remains owned by whoever next touches the Gap Register's own
  DISPOSITION vocabulary.
- `L5DGVA_CONSTITUTIONAL_COMPLIANCE = PASS` (the final-product gate) --
  only the EVALUATOR existing is required (criterion 10), never a `PASS`
  verdict at this wave.
