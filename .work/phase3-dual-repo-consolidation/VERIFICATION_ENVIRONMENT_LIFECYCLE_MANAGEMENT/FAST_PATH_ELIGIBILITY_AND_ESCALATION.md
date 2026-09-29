# Fast Path Eligibility and Escalation

ROADMAP requirements only. No production code implements this document.

## FAST_PATH_ELIGIBILITY (Section 8)

A change is Fast-Path-eligible only when ALL of the following hold.
Thresholds (what counts as "bounded", "adequate confidence", etc.)
belong to a future policy/config file, not this document -- naming the
gate now, deferring the number now, matching every other threshold-
bearing gate already in this codebase (`context_budget.policy.json`,
`environment_mode_policy.json`).

```
1. valid project identity/rehydration succeeded
2. every affected artifact's ownership is KNOWN (never UNKNOWN --
   UNKNOWN always escalates, see below)
3. scope is bounded (single test/sequence/checker/scoreboard/config,
   not a topology/architecture change)
4. no unresolved design-intent issue is implicated
5. no PROTECTED artifact requires modification without prior explicit
   authority
6. no broad topology/architecture change is implicated
7. confidence in the proposed root cause/change is adequate
8. a focused validation path is available (a real, runnable test/
   regression subset exists for this change)
9. a rollback is definable (a known-good state to return to exists)
10. signoff impact is understood (not merely absent -- UNDERSTOOD, which
    can include "understood to be zero")
```

Any one of these failing means NOT eligible -- eligibility is a
conjunction, not a score.

## FAST_PATH_ESCALATION_TO_L5DGVA (Section 9)

Any of the following triggers escalation from Fast Path to Full L5DGVA,
mid-session, preserving session evidence (never restarting from zero):

```
SCOPE_EXPANDED
MULTI_SUBSYSTEM_IMPACT
ARCHITECTURE_CHANGE
TOPOLOGY_CHANGE
DESIGN_INTENT_REQUIRED
SHARED_AUTHORITY_REQUIRED
OWNERSHIP_UNKNOWN
PROTECTED_ARTIFACT
LOW_CONFIDENCE
RCA_UNRESOLVED
COVERAGE_CLOSURE_REQUIRED
BROAD_EVIDENCE_INVALIDATION
SIGNOFF_IMPACT_HIGH
SEMANTIC_MERGE_COMPLEX
REGRESSION_SELECTION_UNCERTAIN
POLICY_REQUIRED_FULL_L5DGVA
```

Each of these is the direct negation or overflow of one of the 10
eligibility conditions above (e.g. `OWNERSHIP_UNKNOWN` negates condition
2; `PROTECTED_ARTIFACT` negates condition 5; `SIGNOFF_IMPACT_HIGH`
overflows condition 10's "understood" into "understood to be large") --
eligibility and escalation are two views of the same real gate, not two
independently-invented lists.

**"Preserves session evidence; do not restart from zero"** is the
concrete requirement `FAST_TO_FULL_CONTEXT_HANDOFF` (`CAP-VELM-023`,
see `FAST_TO_FULL_CONTEXT_HANDOFF_CONTRACT.md`) exists to satisfy -- an
escalation without a real handoff record would violate this requirement
even if the escalation trigger itself fired correctly.

## Validation

```
FAST_PATH_ELIGIBILITY = DEFINED
FAST_PATH_ESCALATION_TO_L5DGVA = DEFINED
```
