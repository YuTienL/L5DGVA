# M8 Implementation Cohort 2 -- Final Report

Cohort 1 CLOSED (commit `124171e`). Authorized scope: Cohort 2 only.
Cohort 3 was **not** started.

## Canonical re-grounding (this session, real tool calls only)

```
REPO_TOPLEVEL   = D:/DV/Task/L5_DGVA
BRANCH          = canonical/m4-dependency-closure
START_HEAD      = 124171e9b2d221a6d2117ce2bb5c1ad8e7f85d9a (git log confirms
                  it is exactly the Cohort-1 commit)
START_STATUS    = only the same pre-existing untracked files + the same
                  unrelated .dv-harness/events.jsonl telemetry diff; no
                  other modified tracked files
GAP-M8-001      = CLOSED (freshly re-read from M8_GAP_REGISTER.csv)
GAP-M8-002      = OPEN, TARGET_COHORT="Cohort 2 (depends on Cohort 1)",
                  CAPABILITY_ID="CAP-M8-EXPLOOP-002;CAP-CE-010;CAP-CE-011;
                  CAP-CE-014" -- matches the dispatch's own expected scope
                  exactly, re-derived independently from the CSV itself
Q-ENV-57D420FA  = OPEN, Tier 3 (freshly queried via QuestionQueueStore)
```
All named authoritative artifacts (`M8_IMPLEMENTATION_COHORT_PLAN.md`,
`M8_GAP_REGISTER.csv`, `M8_SCOPE_AND_OWNERSHIP_MATRIX.csv`,
`M8_DEPENDENCY_GRAPH.md`, `M8_CAPABILITY_REACHABILITY_MATRIX.csv`,
`M8_EXPERIENCE_LOOP_TRACE.md`, `M8_EXIT_CRITERIA.md`,
`M8_COHORT_1_FINAL_REPORT.md`) were freshly re-read this session.

## 1. Cohort-2 scope (reported before any edit)

```
COHORT_2_CAPABILITY_IDS = CAP-M8-EXPLOOP-002, CAP-CE-010, CAP-CE-011, CAP-CE-014
COHORT_2_GAP_IDS        = GAP-M8-002
COHORT_2_DEPENDENCIES   = Cohort 1 (closed)
COHORT_2_EXPECTED_FILES = net-new: dv_harness/experience_record.py; additive:
                          dv_harness/engine.py (2 new methods + 2 new PASS-
                          branch call sites), dv_harness/question_queue.py
                          (1 new hook inside answer_question())
COHORT_2_PROTECTED_FILES = dv_harness/gates.py; tools/verification_flow/
                          promotion_chain_audit_gate.py; engine.py's 5
                          pre-existing KC-harvest call sites (1944/3189/
                          3258/3434/3656) and their own PASS-branch call
                          order -- all untouched
COHORT_2_EXIT_CRITERIA  = M8_EXIT_CRITERIA.md, Internal-experience-loop #2:
                          "CAP-M8-EXPLOOP-002 stages real: CLARIFICATION_
                          LEARNING, GENERATION_EXPERIENCE_LEARNING,
                          SIGNOFF_EXPERIENCE_CONSOLIDATION each have a real
                          producer, a unified Experience record type, and a
                          real behavioral test." (#3, CAP-CE-018's own
                          re-evaluation, addressed in section 9 below --
                          not required to reach OPERATIONAL.)
```
Matches the dispatch's own expected scope exactly; no discrepancy with the
authoritative Cohort Plan.

## 2. Cohort-1 preserved, not redesigned

`dv_harness/gates.py` and `tools/verification_flow/promotion_chain_audit_
gate.py` were not opened for editing this cohort. The EXPERIENCE_READY
trust-boundary distinction (bare self-attestation != a real project-level
`route_and_store()`-backed promotion event) is unchanged; no task-ID field
was added to any protected call site. Proven, not merely asserted: all 9
of Cohort 1's own tests (`test_engine_gates_and_routing.py::test_
promotion_chain_audit_gate_*` + the re-isolated `test_promotion_readiness_
feature_continuity_gate_context_and_evidence_flag`) were re-run together
with the 11 new Cohort-2 tests in one pytest invocation and all 20 passed
(section 12).

## 3. GAP-M8-002 root cause, independently reproduced this session

Not re-derived from `M8_EXPERIENCE_LOOP_TRACE.md` (that document covers
`CAP-M8-EXPLOOP-001` only -- zero mentions of `CAP-M8-EXPLOOP-002`/`CAP-
CE-010/011/014`, confirmed by grep). Traced instead from the real M3-era
`CANONICAL_CAPABILITY_SUPERSET_MATRIX.md` capability-family table (lines
54-80), which independently defines the 3 stages and shows the exact same
`ABSENT` finding is not new to this Preflight:

- **CLARIFICATION_LEARNING**: "none (`QUESTION_AVOIDABLE` or equivalent:
  zero hits anywhere)".
- **GENERATION_EXPERIENCE_LEARNING**: "No generation-decision ->
  build/sim-result -> reusable-experience mechanism found anywhere".
- **SIGNOFF_EXPERIENCE_CONSOLIDATION**: explicitly tied to the SAME
  `promotion_chain_audit_gate`/`route_and_store()` disconnect
  `GAP-M8-001` fixed -- but that document's own text also independently
  named a DIFFERENT, still-open sibling: `closed_loop_promotion_gate.py`
  (registered alongside `promotion_chain_audit_gate.py` under the same
  `PROMOTION_READINESS` stage) gates on `experience_capture_status in
  ("CAPTURED","NOT_APPLICABLE")` -- a bare agent-typed field, never
  cross-verified. Confirmed by direct read of `closed_loop_promotion_
  gate.py:44-46`. Registered as `GAP-M8-010` (section 10) -- not required
  by Cohort 2's own frozen exit criteria, so not fixed this cohort.

Per stage:
```
producer            = ABSENT (zero code, confirmed fresh this session:
                       zero hits for any of the 3 stage names anywhere
                       under dv_harness/)
event/state          = N/A -- nothing to trigger
persistence           = N/A
consumer               = N/A
production caller       = N/A
feedback/update          = N/A
future consumption point  = N/A
observable evidence        = NONE -- the ABSENT finding IS the evidence
```
Where the loop stops: before it starts. Unlike `GAP-M8-001` (a missing
BRIDGE between two real halves), this is 3 genuinely missing PRODUCERS --
confirmed, not assumed, matching `M8_SCOPE_AND_OWNERSHIP_MATRIX.csv`'s own
`ABSENT` classification for all 3 rows.

## 4. What was built (smallest edge per the frozen contract)

**`dv_harness/experience_record.py`** (new, ~90 lines): `build_experience_
record()`, the unified Experience record type all 3 producers share.
`kind="debug_lesson"`, reusing `memory_router.route_memory()`'s existing,
unchanged rule (`kind in ("root_cause","verified_fix","debug_lesson") and
verified -> ENGINEERING_MEMORY`) -- the exact destination the pre-existing
`_promote_experience_knowledge()` call site already writes to. No new
store, router, event bus, or admission gate.

**`dv_harness/engine.py`**: `_promote_generation_experience_knowledge()`
(fires on `Stage.IMPLEMENT` PASS, sourced from `verification_intent_gate`/
`pattern_registry_completeness_gate` evidence) and `_promote_signoff_
experience_consolidation()` (fires on `Stage.SIGNOFF` PASS, sourced from
`signoff_bundle_completeness_gate`/`false_pass_resistance_gate` evidence).
Both mirror the 5 pre-existing `_promote_*` methods' exact shape (stage-
scoped self-guard, honest no-op on absent/malformed evidence, try/except
around `route_and_store()`, a real `self.store.event()` write either way)
and are called from the SAME PASS-branch block, additively, after the 5
existing calls -- their own call order and behavior is unchanged.

**`dv_harness/question_queue.py`**: `answer_question()` gained a best-
effort hook (mirrors every engine.py `_promote_*` call site's own try/
except discipline) that promotes a `CLARIFICATION_LEARNING` experience
record the moment a human resolves a Q-ID -- the real production event,
not a separate polling mechanism. A promotion failure cannot break the
real answer-persistence flow, which has already completed by that point
(proven in section 6/11).

## 5. Production reachability (strict WIRED definition)

| edge | producer | callable | production caller | consumer | observable evidence |
|---|---|---|---|---|---|
| CLARIFICATION_LEARNING | `answer_question()`'s new hook | real | `answer_question()` itself -- real production callers: `dv-harness question-queue answer` CLI, `intake_resume.py`'s answer-by-Q-ID flow | pre-existing `MemoryRetriever` (unchanged) | real `CLARIFICATION_LEARNING_PROMOTED` event + real ENGINEERING_MEMORY write, both proven by test |
| GENERATION_EXPERIENCE_LEARNING | `_promote_generation_experience_knowledge()` | real | `run_stage()`'s PASS branch (the same real caller as the 5 pre-existing methods) | pre-existing `MemoryRetriever` (unchanged) | real `GENERATION_EXPERIENCE_PROMOTED` event + real ENGINEERING_MEMORY write, proven by test |
| SIGNOFF_EXPERIENCE_CONSOLIDATION | `_promote_signoff_experience_consolidation()` | real | `run_stage()`'s PASS branch (same) | pre-existing `MemoryRetriever` (unchanged) | real `SIGNOFF_EXPERIENCE_CONSOLIDATED` event + real ENGINEERING_MEMORY write, proven by test |

All 3 clear the full strict bar. None of this was proven by a unit test
calling the method in isolation alone -- each positive test additionally
calls the real, pre-existing `MemoryRetriever(store).search()` and asserts
the written record is actually found by its real `memory_id`, so the
"consumer" cell above is evidenced, not assumed.

## 6. Knowledge-state discipline (dispatch section 8 -- no upgrade from storage alone)

```
KNOWLEDGE_STORAGE_STATUS          = REAL (proven: 3/3 producers write a
                                     real ENGINEERING_MEMORY record via the
                                     unchanged route_and_store() pipeline)
KNOWLEDGE_DISCOVERABILITY_STATUS  = REAL (the same pre-existing
                                     MemoryStore._index() every other
                                     ENGINEERING_MEMORY record already
                                     uses -- no new discoverability code)
KNOWLEDGE_RETRIEVAL_STATUS        = REAL (directly proven: MemoryRetriever
                                     .search() finds each new record by
                                     its real memory_id, in 3 of the new
                                     tests)
KNOWLEDGE_CONSUMPTION_STATUS      = NOT_PROVEN_THIS_COHORT -- no evidence
                                     a real stage prompt/agent workflow
                                     queries/uses one of these specific new
                                     experience_type records in an actual
                                     decision. Not required by Cohort 2's
                                     own frozen exit criteria (producer +
                                     unified type + test only).
KNOWLEDGE_ACTION_INFLUENCE_STATUS = OUT_OF_SCOPE -- explicitly Cohort 4's
                                     own CAP-HITL-008 (Role-Aware
                                     Experience Learning) territory per
                                     M8_EXIT_CRITERIA.md criterion 5.
```
No capability status below is inflated past what this table supports.

## 7. Capability-state reclassification (independent, per-row, not blanket)

- **`CAP-CE-010` (CLARIFICATION_LEARNING)**: `ABSENT` -> `PRODUCTION_WIRED`
  (real producer + caller + consumer + evidence, per section 5).
- **`CAP-CE-011` (GENERATION_EXPERIENCE_LEARNING)**: `ABSENT` ->
  `PRODUCTION_WIRED`.
- **`CAP-CE-014` (SIGNOFF_EXPERIENCE_CONSOLIDATION)**: `ABSENT` ->
  `PRODUCTION_WIRED`.
- **`CAP-M8-EXPLOOP-002`** (the umbrella capability over the 3 above):
  `ABSENT` -> `PRODUCTION_WIRED` (all 3 constituent stages individually
  clear the strict bar; the umbrella capability itself has no separate
  code of its own beyond its 3 stages, so it inherits their status).
- **`CAP-CE-018`** (composite, section 9's own dedicated treatment below):
  re-evaluated, deliberately NOT marked WIRED or CLOSED.

## 8. Test strategy (dispatch section 11 checklist, mapped to real tests)

21 new tests total: `test_experience_record.py` (7), `test_engine_gates_
and_routing.py` (11 new Cohort-2 + the 9 Cohort-1 tests re-confirmed
together = 20 in that file's Cohort-focused run), `test_question_queue.py`
(3).

| checklist item | test(s) |
|---|---|
| positive end-to-end path | `test_promote_generation_experience_knowledge_positive_end_to_end`, `test_promote_signoff_experience_consolidation_positive_end_to_end`, `test_answer_question_promotes_clarification_learning_experience` |
| missing knowledge | `test_promote_generation_experience_knowledge_missing_evidence_is_honest_noop` |
| invalid knowledge | `test_promote_signoff_experience_consolidation_invalid_evidence_shape_is_honest_noop`, `test_build_experience_record_rejects_unknown_experience_type` |
| wrong project correlation | `test_promote_generation_and_signoff_do_not_cross_project_correlate`, `test_answer_question_clarification_learning_does_not_cross_project_correlate` |
| duplicate consumption/idempotency | `test_promote_generation_experience_knowledge_duplicate_promotion_idempotency` |
| persistence/routing failure | `test_promote_generation_experience_knowledge_persistence_failure_never_false_success`, `test_promote_signoff_experience_consolidation_persistence_failure_never_false_success`, `test_answer_question_promotion_failure_never_breaks_the_real_answer` |
| no false success | same 3 tests -- assert `PROMOTION_FAILED`, never a fabricated success |
| existing valid path compatibility | `test_promote_generation_experience_knowledge_existing_call_sites_unaffected`; the full 258-test `test_engine_gates_and_routing.py` run (section 12) |
| stage-guard correctness (wrong-stage no-op) | `test_promote_generation_experience_knowledge_wrong_stage_is_honest_noop`, `test_promote_signoff_experience_consolidation_wrong_stage_is_honest_noop` |
| unified type shape | `test_build_experience_record_shape_is_unified_across_all_3_types` (parametrized over all 3 real types), `test_build_experience_record_routes_to_engineering_memory` |

`stale knowledge`, `consumer unavailable`, `consumer failure`, `routing
failure` (as a shape distinct from persistence failure) were considered
and NOT given dedicated tests -- none maps to a real failure mode these 3
producers can actually exhibit (routing is deterministic given
`kind="debug_lesson"`+`verified=True`; the consumer, `MemoryRetriever`, is
the unchanged pre-existing one with its own existing test coverage;
staleness is a retrieval-time concern this cohort's producers do not
introduce). Disclosed here rather than padded with a contrived test, per
"do not add tests solely to increase test counts."

## 9. `CAP-CE-018` re-evaluated, not closed

Per the dispatch's own explicit caution: `CAP-CE-018`'s named dependencies
(`M8_SCOPE_AND_OWNERSHIP_MATRIX.csv`'s own row: `CAP-M8-EXPLOOP-001;
CAP-M8-EXPLOOP-002`) are now BOTH real. But `M8_CAPABILITY_REACHABILITY_
MATRIX.csv`'s own `STRICT_CLASSIFICATION` for this row says "No unified
composite implementation found" -- true before this cohort and still true
after it: Cohort 2 built the 3 underlying stage producers, not a composite
EVALUATOR function that aggregates them into one `CAP-CE-018` verdict.
`CAP_CE_018_STATUS_AFTER_COHORT_2 = PARTIAL` (dependencies now real+
tested; the composite's own aggregation/evaluator remains genuinely
ABSENT, out of Cohort 2's own frozen scope) -- matching Exit Criterion 3's
own wording exactly ("moves from PARTIAL/ABSENT to a real, evidence-backed
state ... need not be fully OPERATIONAL").

## 10. New gap found and governed disposition (dispatch section 10)

`GAP-M8-010` (new, registered in `M8_GAP_REGISTER.csv`): `closed_loop_
promotion_gate.py`'s own `experience_capture_status` field is a sibling
self-attestation loophole to the one `GAP-M8-001` fixed, discovered while
re-tracing `PROMOTION_READINESS`'s full registered gate list this cohort.
`CLASSIFICATION = COHORT_HARDENING` (not required by Cohort 2's own frozen
exit criteria, which name only the 3 CAP-M8-EXPLOOP-002 stages). Not
fixed this cohort -- registered, owned, exit-tested, per the No-
Discovered-Gap-May-Disappear principle.

## 11. Live qualification (no overclaiming)

```
UNIT_TESTED              = YES (build_experience_record()'s own 7 tests)
INTEGRATION_TESTED        = YES (all 3 producers tested against a real
                            DVHarness/QuestionQueueStore + real StateStore/
                            MemoryStore on disk, not mocks)
PRODUCTION_CALL_PATH_PROVEN = YES -- every positive test exercises the
                            exact real call site (engine.py's PASS branch
                            method-call sequence; answer_question()'s own
                            body) a real stage run / real CLI answer would
                            hit, with no engine.py/question_queue.py logic
                            bypassed
LIVE_QUALIFIED             = NO -- no real, full DVHarness.run_stage() end-
                            to-end execution through IMPLEMENT/SIGNOFF's
                            own full real gate set was performed this
                            session (would require fabricating realistic
                            evidence for every OTHER IMPLEMENT/SIGNOFF gate
                            too, out of this cohort's own bounded scope).
                            Disclosed, not claimed.
```
No Reference USB was used or needed.

## 12. Regression (focused, not a full-suite ritual)

```
dv_harness_tests/test_experience_record.py                         7/7 passed
dv_harness_tests/test_engine_gates_and_routing.py
    -k "promotion_chain_audit_gate or                              20/20 passed
        promotion_readiness_feature_continuity or                  (Cohort-1
        promote_generation or promote_signoff"                     regression
                                                                     protection,
                                                                     section 2)
dv_harness_tests/test_question_queue.py (full file)               169/169 passed
dv_harness_tests/test_engine_gates_and_routing.py (full file)     258/258 passed
dv_harness_tests/test_l5dgva_constitution.py                        10/10 passed
test_organizational_promotion_evaluation_wiring.py +
test_memory_tier_completion.py + test_human_correction_lesson.py +
test_engineering_confirmation_accumulation.py                      57/57 passed
```
No failure was found; no causality classification needed.

## 13. Hardening firewall

No telemetry/cosmetic/watcher-polish/M7-post-hardening/dynamic-gap-
scoring/documentation-cleanup work was pulled in. `GAP-M8-010` (section
10) was classified and deferred, not fixed. The 2 incidental `CLI_ACCESS`/
`self-audit` telemetry lines this session's own test runs again added to
the real `.dv-harness/events.jsonl` were again left uncommitted, per the
same discipline Cohort 1 established.

## 14. Convergence

Implementation, tests, and the Gap Register are reconciled (`GAP-M8-002`
CLOSED with full evidence; `GAP-M8-010` registered and owned, not force-
closed). No new architecture-discovery wave was started; no Cohort-3 work
(`CAP-M4.6-002`/`GAP-M8-005`, discoverability) was touched.

## 15. Final report fields

```
M8_STATUS                          = IMPLEMENTATION_IN_PROGRESS
M8_COHORT_2_STATUS                 = CLOSED
COHORT_2_CAPABILITY_IDS            = CAP-M8-EXPLOOP-002, CAP-CE-010, CAP-CE-011, CAP-CE-014
COHORT_2_GAP_IDS                   = GAP-M8-002
COHORT_2_EXIT_CRITERIA_TOTAL       = 1 (Cohort 2's own named criterion;
                                      criterion 3's CAP-CE-018 re-
                                      evaluation is addressed but does not
                                      require OPERATIONAL, see section 9)
COHORT_2_EXIT_CRITERIA_PASS        = 1
COHORT_2_EXIT_CRITERIA_PARTIAL     = 0
COHORT_2_EXIT_CRITERIA_FAIL        = 0
GAP_M8_002_STATUS                  = CLOSED
CAP_M8_EXPLOOP_002_STATUS          = PRODUCTION_WIRED
CAP_CE_010_STATUS                  = PRODUCTION_WIRED
CAP_CE_011_STATUS                  = PRODUCTION_WIRED
CAP_CE_014_STATUS                  = PRODUCTION_WIRED
CAP_CE_018_STATUS_AFTER_COHORT_2   = PARTIAL (dependencies real; composite evaluator still absent)
KNOWLEDGE_STORAGE_STATUS           = REAL
KNOWLEDGE_DISCOVERABILITY_STATUS   = REAL
KNOWLEDGE_RETRIEVAL_STATUS         = REAL
KNOWLEDGE_CONSUMPTION_STATUS       = NOT_PROVEN_THIS_COHORT
KNOWLEDGE_ACTION_INFLUENCE_STATUS  = OUT_OF_SCOPE (Cohort 4)
PRODUCTION_CALLER_STATUS           = REAL (section 5 table)
LIVE_QUALIFICATION_STATUS          = PRODUCTION_CALL_PATH_PROVEN (not LIVE_QUALIFIED -- section 11)
COHORT_1_REGRESSION_STATUS         = PASS (20/20 combined, section 2/12)
NEW_GAPS_FOUND                     = 1 (GAP-M8-010)
NEW_GAPS_DEFERRED                  = 1 (GAP-M8-010, COHORT_HARDENING)
COHORT_2_BLOCKING_GAPS_OPEN        = 0
FOCUSED_TESTS                      = 21 new (7+11+3)
ADJACENT_REGRESSION                = 315/315 (169+258 full-file runs dominate;
                                      constitution 10 + memory-tier suites 57
                                      re-confirmed, no new failures)
CONSTITUTION_GATE                  = 10/10 passed
UNKNOWN_REGRESSION_FAILURES        = 0
SOURCE_CAPABILITY_LOSS             = 0
FROZEN_SOURCE_CHANGES              = 0
Q_ENV_57D420FA_STATUS              = OPEN, Tier 3, untouched
REFERENCE_USB_ENV_CONSUMED         = NO
COMMITS                            = 1 (this Cohort-2 build; see COMMIT_SHA below)
NEXT_CANONICAL_GATE                = M8 Implementation Cohort 3
                                      (CAP-M4.6-002 / GAP-M8-005,
                                      discoverability systematic re-audit --
                                      independent of Cohorts 1-2, per
                                      M8_IMPLEMENTATION_COHORT_PLAN.md's own
                                      dependency graph). NOT started.
```

## 16. Stop condition

Cohort 2 satisfies its own frozen exit criterion. `M8_COHORT_2_STATUS =
CLOSED`. Per explicit instruction: Cohort 3 is **not** auto-started,
Reference USB remains unconsumed, and this closure was not turned into a
new hardening wave. Awaiting explicit authorization for Cohort 3.
