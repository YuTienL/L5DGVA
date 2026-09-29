# M8 Dependency Graph

Re-derived from `MASTER_WAVE_OWNERSHIP_MATRIX.csv`'s own real
`SECONDARY_DEPENDENCY` column (re-parsed, not eyeballed) for the 17 real
`PRIMARY_OWNER_WAVE=M8` rows in `MASTER_CAPABILITY_STATUS_MATRIX.csv`.
No dependency asserted here is invented -- every edge below is the CSV's
own already-recorded fact, cross-checked against the real `M8_EXPERIENCE_
LOOP_TRACE.md` root-cause finding.

## Real dependency edges (from `MASTER_WAVE_OWNERSHIP_MATRIX.csv`)

```
CAP-M8-EXPLOOP-001  (P0, root edge -- no dependency, foundation)
  |
  +--> CAP-M8-EXPLOOP-002  (P1, depends on EXPLOOP-001)
  |      |
  |      +--> CAP-CE-008   (P1, PROJECT_EXPERIENCE_EXTRACTION)
  |      +--> CAP-CE-010   (P1, CLARIFICATION_LEARNING)
  |      +--> CAP-CE-011   (P1, GENERATION_EXPERIENCE_LEARNING)
  |      +--> CAP-CE-014   (P1, SIGNOFF_EXPERIENCE_CONSOLIDATION;
  |             also directly depends on EXPLOOP-001)
  |
  +--> CAP-CE-012   (P2, RCA_EXPERIENCE_LEARNING, depends on EXPLOOP-001 only)
  +--> CAP-HITL-008  (P1, ROLE_AWARE_EXPERIENCE_LEARNING, depends on EXPLOOP-001 only)
  +--> CAP-CE-018    (P0, CONTINUOUS_PROJECT_EXPERIENCE_LEARNING composite,
         depends on BOTH EXPLOOP-001 AND EXPLOOP-002 -- the top-level
         composite that rolls up the whole family)

CAP-M4.6-002  (P1, GLOBAL_DISCOVERABILITY_CONTRACT)
  depends on CAP-M4.5-002 (MINIMUM_SUFFICIENT_CONTEXT principle) --
  a REAL cross-wave dependency: CAP-M4.5-002 is itself M8-owned (not a
  different wave), so this is an intra-M8 edge, not a blocking
  cross-wave prerequisite.

CAP-HITL-009  (P2, KNOWLEDGE_DOMAIN_CLASSIFICATION) -- no dependency listed, independent
CAP-M4.5-003  (P1, Constitution full compliance) -- no dependency listed,
  BUT its own "Final Constitutional Acceptance" 13-criteria composite
  (see M8_CONSTITUTION_QUALIFICATION_PLAN.md) structurally OVERLAPS
  CAP-M8-EXPLOOP-001/CAP-M8-MAKC-001/CAP-M4.6-002 as evidence inputs --
  not a hard dependency, a shared-evidence overlap, disclosed distinctly.
CAP-M8-MAKC-001  (P2, MULTI_AGENT_KNOWLEDGE_CONSUMPTION audit) -- no
  dependency listed, independent (an AUDIT capability, not itself
  blocked by EXPLOOP)

CAP-M4.5-011  (P3, Cross-model TOKEN_REDUCTION_MEASUREMENT) -- independent
CAP-POOL-002  (P3, ABSENT from canonical, depends on l5dgva_pre_codex_review_truth.py, also not migrated) -- independent island, deferred
CAP-POOL-010  (P3, ABSENT from canonical, depends on memory.py/memory_router.py "diverged, high fan-in") -- independent island, deferred
```

## Foundation / root-edge identification

`CAP-M8-EXPLOOP-001` is the single real foundation node: 6 of the other
16 M8-owned rows depend on it directly or transitively (`CAP-M8-EXPLOOP-
002`, `CAP-CE-008/010/011/012/014`, `CAP-HITL-008`, `CAP-CE-018`) -- 8
total including itself. This matches `M8_EXPERIENCE_LOOP_TRACE.md`'s own
finding precisely: the missing production edge it identifies (agent
self-attestation never cross-verified against the real `EXPERIENCE_
KNOWLEDGE_PROMOTED` mechanism) is the ROOT CAUSE root-edge for the
majority of M8's own scope by dependency count.

## CAP-CE-018 relationship to CAP-M8-EXPLOOP-001 (dispatch section 4)

Independently determined, not assumed: `CAP-CE-018` (`CONTINUOUS_
PROJECT_EXPERIENCE_LEARNING`, the composite) is **neither** "the same
defect at two abstraction levels" **nor** "a fully separate capability" --
it is a **real composite/rollup capability with an explicit, CSV-recorded
dependency on BOTH `CAP-M8-EXPLOOP-001` and `CAP-M8-EXPLOOP-002`**
(`MASTER_WAVE_OWNERSHIP_MATRIX.csv` row 50: `SECONDARY_DEPENDENCY=
CAP-M8-EXPLOOP-001;CAP-M8-EXPLOOP-002`). `CAP-CE-018`'s own `CANONICAL_
STATE` cell states this explicitly: `"PARTIAL/ABSENT -- structurally
broken at CAP-M8-EXPLOOP-001 (EXPERIENCE_READY never emitted by any
stage)"` -- the Capability Matrix's own `BLOCKER` column already names
`CAP-M8-EXPLOOP-001` as `CAP-CE-018`'s root cause. **One authoritative
mapping**: `CAP-CE-018` is the composite that becomes real once its two
dependencies (`CAP-M8-EXPLOOP-001` the root edge, `CAP-M8-EXPLOOP-002`
the still-absent internal-loop stages it also needs) are both closed --
never a duplicate solution target in its own right.

## Independent (no cross-M8-capability dependency)

`CAP-HITL-009`, `CAP-M8-MAKC-001`, `CAP-M4.5-011`, `CAP-M4.5-003` (shared-
evidence overlap only, not a hard dependency), `CAP-POOL-002`,
`CAP-POOL-010` -- each can, in principle, be investigated/implemented
without waiting on `CAP-M8-EXPLOOP-001` closing first, though `CAP-HITL-
008` (ROLE_AWARE_EXPERIENCE_LEARNING) explicitly cannot, since it depends
on EXPLOOP-001 directly.

## Suggested cohort-ordering implication (Preflight evidence only -- the
real cohort plan is `M8_IMPLEMENTATION_COHORT_PLAN.md`)

The dependency structure above implies the root-edge fix
(`CAP-M8-EXPLOOP-001`) is the natural Cohort 1 foundation -- 8 of 17 rows
depend on it, directly or transitively -- with the fully-independent rows
(`CAP-HITL-009`, `CAP-M8-MAKC-001`, discoverability/constitution
qualification work) eligible to run in parallel cohorts, not gated on
Cohort 1's own closure.
