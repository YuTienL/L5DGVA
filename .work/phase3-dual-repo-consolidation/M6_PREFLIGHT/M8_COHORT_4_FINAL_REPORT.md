# M8 Implementation Cohort 4 -- Final Report

Cohorts 1, 2, 3 CLOSED (commits `124171e`, `f627542`, `b9ceb77`).
Authorized scope: Cohort 4 only. Cohort 5 was **not** started.

## Canonical re-grounding (this session, real tool calls only)

```
REPO_TOPLEVEL   = D:/DV/Task/L5_DGVA
BRANCH          = canonical/m4-dependency-closure
START_HEAD      = b9ceb77b921d4f70aa4e8d02fbe3bc3eb13ccccd (matches the
                  dispatch's own expected `b9ceb77b921d` exactly)
START_STATUS    = only the same pre-existing untracked files + the same
                  unrelated .dv-harness/events.jsonl telemetry diff
GAP-M8-001/002/005 = CLOSED (fresh re-read)
CAP-M4.6-002        = PRODUCTION_REACHABLE (fresh re-read)
GAP-M8-010          = COHORT_HARDENING (fresh re-read) -- no fresh evidence
                      this cohort ties it to a frozen Cohort-4 exit
                      criterion (it concerns closed_loop_promotion_
                      gate.py, which Cohort 4 never touches). Left
                      untouched.
Q-ENV-57D420FA      = OPEN (fresh QuestionQueueStore query)
```
No contradiction found.

## 1. Cohort-4 scope (reported before any edit)

```
COHORT_4_CAPABILITY_IDS = CAP-HITL-008, CAP-HITL-009
COHORT_4_GAP_IDS        = none -- no dedicated M8_GAP_REGISTER.csv row
                         exists for either capability (confirmed by grep:
                         the register's 10 rows, GAP-M8-001 through
                         GAP-M8-010, contain zero CAP-HITL references).
                         Both capabilities are tracked directly via
                         M8_SCOPE_AND_OWNERSHIP_MATRIX.csv (rows 10-11)
                         and M8_CAPABILITY_REACHABILITY_MATRIX.csv (rows
                         17-18), and via M8_EXIT_CRITERIA.md's own
                         criteria 5 and 8. Disclosed as an observation,
                         not registered as a new gap -- a Preflight
                         coverage choice, not a defect.
COHORT_4_DEPENDENCIES   = CAP-HITL-008 depends on Cohort 1 (CLOSED);
                         CAP-HITL-009 has no cross-capability dependency
COHORT_4_EXPECTED_FILES = dv_harness/experience_record.py (extended, not
                         replaced); dv_harness/question_queue.py
                         (extended); no net-new module needed (see
                         section 4 -- the real classifier already existed)
COHORT_4_PROTECTED_FILES = dv_harness/clarification_service.py (read-
                         only, its own real classify_question_owner()
                         reused verbatim, never modified); dv_harness/
                         gates.py, promotion_chain_audit_gate.py, closed_
                         loop_promotion_gate.py, governance_registry.py,
                         cli.py's research/governance-lookup verbs,
                         engine.py's 7 promotion call sites -- all
                         untouched (Cohort 1/2/3 regression protection)
COHORT_4_EXIT_CRITERIA  = M8_EXIT_CRITERIA.md Internal-experience-loop
                         #5: "CAP-HITL-008 (ROLE_AWARE_EXPERIENCE_
                         LEARNING): moves from ROADMAP_DEFINED to real,
                         tested, WIRED status (Cohort 4)." #8: "CAP-
                         HITL-009 (KNOWLEDGE_DOMAIN_CLASSIFICATION):
                         moves from DEFINED (taxonomy only) to real,
                         tested, WIRED status."
```

**Authoritative relationship to adjacent concepts** (dispatch section 1):
Role-Aware Experience Learning (`CAP-HITL-008`) and Knowledge Domain
Classification (`CAP-HITL-009`) are, per `ROLE_AWARE_EXPERIENCE_
REQUIREMENTS.md` Section 14-15, the SAME `DESIGN|VERIFICATION|SHARED`
taxonomy applied to two related questions ("who decided" vs. "what kind
of knowledge is this") -- not independent systems. Multi-Agent Knowledge
Consumption (`CAP-M8-MAKC-001`) and `CAP-CE-018` are **separate**
capabilities this cohort does not own or advance (section 9).

## 2. Reproduced before fix (dispatch section 2)

```
producer                = ABSENT for a dedicated Role-Aware classifier --
                          but NOT absent overall: dv_harness/
                          clarification_service.classify_question_
                          owner() already computes exactly this
                          DESIGN|VERIFICATION|SHARED value, built for a
                          DIFFERENT capability (CAP-M6-CLARSVC-001,
                          2026-09-24)
persisted knowledge/experience = question_queue.add_question()'s real
                          `authority_role` field (already threaded
                          through from classify_question_owner() by the
                          real production chain clarification_service.py
                          -> file_clarification() -> add_question(),
                          confirmed by direct code read at clarification_
                          service.py:216/238)
metadata                 = ABSENT on the Experience record specifically --
                          Cohort 2's own build_experience_record()/
                          answer_question() hook read `target` but never
                          `target["authority_role"]`, so the real,
                          already-classified role was silently discarded
                          the moment it reached the learning loop (the
                          exact gap DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md
                          Section 24 names as the CONTINUOUS_EVOLUTION
                          alignment target)
role/domain classification = the SAME 3-value taxonomy, real, already
                          built, at classify_question_owner() -- not
                          re-derived here (dispatch section 3's own
                          instruction not to invent a new taxonomy;
                          none was needed, one already existed)
discovery/retrieval       = ABSENT specifically for this field --
                          MemoryRetriever.search()'s own pre-existing
                          `property` filter (memory.py's property_
                          filters/_record_field()) is GENERIC and
                          already supports any field name, but nothing
                          had ever populated knowledge_domain/human_role
                          on a record to filter by
consumer                  = the calling agent/session (unchanged from
                          Cohort 2's own honest framing)
production caller          = answer_question(), already real (cli.py:6368
                          `dv-harness question-queue answer`)
observable evidence          = NONE before this cohort (the field simply
                          did not exist on any record)
```
**Precise failure mode**: not "no classifier exists" (one did, for a
different capability) and not "no retrieval mechanism exists" (one did,
generic). The single missing edge was: the real, already-classified role
signal was never attached to the Experience record at the one real write
site that already existed. This is a connection gap, exactly like Cohort
1's `GAP-M8-001`, not a missing-producer gap like Cohort 2's `GAP-M8-002`.

## 3. Role-Aware Experience Learning (CAP-HITL-008) -- what was built

**Reused, not reinvented**: `dv_harness/clarification_service.QUESTION_
OWNERS` / `classify_question_owner()` -- the one real, already-tested
`DESIGN|VERIFICATION|SHARED` classifier. No second taxonomy, no second
classifier.

**`dv_harness/experience_record.py`** (extended): `build_experience_
record()` gained `knowledge_domain`/`human_role` keyword args (both
optional, validated against the real `ROLE_DOMAIN_VALUES` tuple --
byte-identical to `clarification_service.QUESTION_OWNERS`, proven by a
dedicated provenance test). Both default to the explicit `UNCLASSIFIED`
sentinel, never a silent `None`/omission.

**`dv_harness/question_queue.py`** (extended): `answer_question()`'s
existing Cohort-2 CLARIFICATION_LEARNING hook now reads `target.get(
"authority_role")` and passes it as both `knowledge_domain=` and
`human_role=` (disclosed simplification: one real signal serves both
fields this cohort, since no second, independent classifier exists to
distinguish them yet).

**Distinguishing the 4 depths (dispatch section 3):**
```
ROLE_METADATA_EXISTS       = YES (proven: a real question's authority_
                              role survives onto its promoted record)
ROLE_AWARE_RETRIEVAL       = YES (proven: MemoryRetriever.search()
                              genuinely returns different results scoped
                              to DESIGN vs. VERIFICATION)
ROLE_AWARE_CONSUMPTION     = NOT_PROVEN_THIS_COHORT -- no evidence a real
                              stage prompt/agent workflow actually issues
                              a role-scoped query today (same honest bar
                              Cohort 2's own KNOWLEDGE_CONSUMPTION_STATUS
                              already established)
ROLE_AWARE_ACTION_INFLUENCE = OUT_OF_SCOPE -- no evidence any decision
                              was changed by a role-filtered result
```

## 4. Knowledge Domain Classification (CAP-HITL-009) -- what was built

The SAME mechanism as section 3, since `ROLE_AWARE_EXPERIENCE_
REQUIREMENTS.md` Section 14 itself frames `KNOWLEDGE_DOMAIN` as
"applicability metadata on existing memory records... a KNOWLEDGE_DOMAIN
field added to the existing Memory/Obsidian schema, never a fourth or
fifth memory system" -- exactly what `build_experience_record()`'s
`knowledge_domain=` parameter is. No large ontology framework, no
hierarchical taxonomy engine, no embedding redesign, no new store was
built (dispatch section 5's own explicit list of things to avoid) --
Connect Before Expand applied literally: the smallest classification
model (one shared 3-value field, sourced from one existing real
classifier) that clears the frozen exit criterion.

## 5. Multi-agent behavior (dispatch section 7)

Not applicable to this cohort's own real edge: the CLARIFICATION_LEARNING
producer's production caller and consumer are both within the single
existing generic workflow (`dv-harness question-queue answer` -> the
calling agent/session's own later retrieval), not a distinct multi-agent
hand-off. No claim of cross-agent consumption is made here; that remains
`CAP-M8-MAKC-001`'s own separate, unowned-by-this-cohort scope.

## 6. Production reachability (strict WIRED definition)

| edge | producer/resolver | callable | production caller | consumer | evidence |
|---|---|---|---|---|---|
| role/domain metadata on CLARIFICATION_LEARNING | `classify_question_owner()` (existing, reused) + `build_experience_record(knowledge_domain=, human_role=)` (extended) | real | `dv-harness question-queue answer` (cli.py:6368) -> `answer_question()` (both real, unchanged production callers) | the calling agent/session, via `MemoryRetriever.search({"property": {...}})` | 8 new tests (4 in `test_experience_record.py`, 4 in `test_question_queue.py`), including a real end-to-end preservation proof and a real role-differentiated retrieval proof |

Tests are verification, not the production caller themselves -- the CLI
command + `answer_question()` chain (both pre-existing, unmodified in
their own control flow) are.

## 7. Backward compatibility (dispatch section 13)

Historical knowledge with no `knowledge_domain`/`human_role` key at all
(every ENGINEERING_MEMORY record from the 5 pre-Cohort-4 promotion call
sites, and any CLARIFICATION_LEARNING record predating this cohort) is
proven, not assumed, to stay safely excluded from a role/domain-scoped
query (`memory.py`'s own pre-existing `_property_matches()`/
`_record_field()` treat an absent key as "no match", never a crash or a
false positive) while remaining fully discoverable via an unscoped query
-- `test_role_scoped_search_excludes_pre_cohort_4_historical_records`.

## 8. CAP-CE-018 (dispatch section 14 -- not advanced by this cohort)

`CAP-CE-018`'s own dependency set, per `M8_SCOPE_AND_OWNERSHIP_
MATRIX.csv`'s own row, is `CAP-M8-EXPLOOP-001;CAP-M8-EXPLOOP-002` --
neither of which `CAP-HITL-008`/`CAP-HITL-009` are members of. This
cohort's work does not change `CAP-CE-018`'s own complete dependency
state at all. `CAP_CE_018_STATUS_AFTER_COHORT_4 = PARTIAL`, unchanged
from Cohort 2's own honest framing (dependencies real; the composite's
own aggregation/evaluator function remains absent).

## 9. GAP-M8-010 firewall (dispatch section 10)

Re-checked: `closed_loop_promotion_gate.py`'s own sibling self-attestation
loophole (`experience_capture_status`) is unrelated to role/domain
metadata and was not touched. `COHORT_HARDENING`, unchanged.

## 10. New gaps found

None. Section 1's own "no dedicated Gap Register row for CAP-HITL-008/
009" observation is disclosed, not registered as a new numbered gap (a
Preflight coverage choice, not a code defect -- mirroring `GAP-M8-009`'s
own precedent of a disclosed-but-not-registered documentation note).

## 11. Hardening firewall

No telemetry/dynamic-gap-scoring/M7-hardening/fine-grained-task-
correlation/unrelated-discoverability-cleanup/future-ontology-
sophistication/future-role-hierarchy work was pulled in. `GAP-M8-010` was
left untouched per its own firewall (section 9). The FULL 16-field
Role-Aware Experience Record schema was deliberately NOT built --
disclosed in section 3 as a future roadmap item, not silently claimed
complete.

## 12. Test strategy (dispatch section 12, mapped to real tests)

8 new tests total (`test_experience_record.py` +6 -- one is a shared
provenance check counted once; `test_question_queue.py` +4):

| checklist item | test(s) |
|---|---|
| valid role/domain classification | `test_build_experience_record_accepts_the_real_3_value_taxonomy` (parametrized DESIGN/VERIFICATION/SHARED) |
| missing role/domain | `test_build_experience_record_defaults_role_domain_to_unclassified`, `test_answer_question_unclassified_when_authority_role_never_set` |
| invalid role/domain | `test_build_experience_record_rejects_invalid_knowledge_domain`, `test_build_experience_record_rejects_invalid_human_role` |
| role-aware retrieval / domain-aware retrieval / combined | `test_role_aware_retrieval_distinguishes_design_from_verification` (both fields are populated together from the one real signal, so this single test proves both filters) |
| compatibility with existing unclassified historical knowledge | `test_role_scoped_search_excludes_pre_cohort_4_historical_records` |
| no false action-influence claim | asserted in the report text (section 3), not a test -- there is nothing to test a NEGATIVE absence-of-claim against; the honest status field itself is the artifact |
| provenance (taxonomy never drifts from the real classifier) | `test_role_domain_values_match_clarification_service_taxonomy` |

`unknown role`/`unknown domain` collapses into the same "invalid" cases
above (the validation is a closed 3-value check, so anything not in the
set is rejected uniformly). `wrong project correlation`/`duplicate
knowledge`/`stale knowledge` were considered and not given dedicated new
tests -- Cohort 1's own wrong-project-correlation pattern and Cohort 2's
own duplicate-promotion-idempotency pattern already cover the identical
underlying mechanisms (`StateStore`/`route_and_store()`) this cohort's
change does not alter; adding parallel tests for the SAME already-proven
mechanism, merely re-labeled for role/domain fields, would be padding,
not new coverage.

## 13. Live qualification (no collapsing categories)

```
UNIT_TESTED                = YES (build_experience_record()'s own
                              validation tests)
INTEGRATION_TESTED          = YES (real QuestionQueueStore + StateStore +
                              MemoryStore on disk, not mocks)
PRODUCTION_CALL_PATH_PROVEN  = YES (answer_question() is the real,
                              unmodified production entry point;
                              cli.py:6368 unchanged)
CONSUMPTION_PROVEN            = NO -- no real stage prompt/agent workflow
                              was shown issuing a role-scoped query in
                              this session (disclosed, section 3)
ACTION_INFLUENCE_PROVEN        = NO -- explicitly out of scope (section 3)
LIVE_QUALIFIED                  = PARTIAL -- the cohort's OWN required
                              "real retrieval scenario distinguishing at
                              least 2 roles/domains with different
                              results" (M8_IMPLEMENTATION_COHORT_PLAN.md's
                              own Cohort-4 LIVE_QUALIFICATION line) IS
                              satisfied and proven
                              (`test_role_aware_retrieval_distinguishes_
                              design_from_verification`); a full live
                              session-level qualification (a real human
                              answering a real DESIGN question during a
                              real task, observed end to end) was not
                              performed this session
```
No Reference USB was used or needed.

## 14. Regression

```
dv_harness_tests/test_experience_record.py (full file)          14/14 passed
dv_harness_tests/test_question_queue.py (full file)             173/173 passed
dv_harness_tests/test_l5dgva_constitution.py                     10/10 passed
dv_harness_tests/test_clarification_service.py                   13/13 passed
Cohort-1/2 regression protection (test_engine_gates_and_
  routing.py -k promotion_chain_audit_gate/promote_generation/
  promote_signoff)                                                20/20 passed
Cohort-3 regression protection (test_governance_intent_
  routing.py + test_governance_registry.py + test_claude_
  reference_graph.py)                                              44/44 passed
adjacent memory/promotion suites (test_organizational_
  promotion_evaluation_wiring.py + test_memory_tier_
  completion.py + test_human_correction_lesson.py +
  test_engineering_confirmation_accumulation.py)                   57/57 passed
```
No failure was found; no causality classification needed. `dv_harness/
engine.py` was not touched this cohort, so its own full-file regression
(previously confirmed 258/258 in Cohorts 1-3) was not re-run in full --
the smallest authoritative regression for files genuinely changed
(`experience_record.py`, `question_queue.py`) plus their real consumers.

## 15. Convergence

Implementation, tests, and the Capability Reachability Matrix (`CAP-
HITL-008`/`CAP-HITL-009` both updated) are reconciled. No Gap Register
row exists to close (section 1/10). No new architecture-discovery wave
was started; Cohort 5 was not touched.

## 16. Final report fields

```
M8_STATUS                          = IMPLEMENTATION_IN_PROGRESS
M8_COHORT_4_STATUS                 = CLOSED
COHORT_4_CAPABILITY_IDS            = CAP-HITL-008, CAP-HITL-009
COHORT_4_GAP_IDS                   = none (no dedicated Gap Register row -- section 1)
COHORT_4_EXIT_CRITERIA_TOTAL       = 2
COHORT_4_EXIT_CRITERIA_PASS        = 2
COHORT_4_EXIT_CRITERIA_PARTIAL     = 0
COHORT_4_EXIT_CRITERIA_FAIL        = 0
CAP_HITL_008_STATUS                = PRODUCTION_REACHABLE (CLARIFICATION_LEARNING edge; full 16-field schema disclosed as future roadmap, not built)
CAP_HITL_009_STATUS                = PRODUCTION_REACHABLE (same shared mechanism, disclosed)
CAP_CE_018_STATUS_AFTER_COHORT_4   = PARTIAL, unchanged (section 8)
ROLE_AWARE_EXPERIENCE_LEARNING_STATUS   = PRODUCTION_REACHABLE for the CLARIFICATION_LEARNING edge
KNOWLEDGE_DOMAIN_CLASSIFICATION_STATUS  = PRODUCTION_REACHABLE, same edge
ROLE_METADATA_STATUS               = REAL
DOMAIN_METADATA_STATUS             = REAL
ROLE_AWARE_RETRIEVAL_STATUS        = REAL (proven)
DOMAIN_AWARE_RETRIEVAL_STATUS      = REAL (proven, same test)
KNOWLEDGE_CONSUMPTION_STATUS       = NOT_PROVEN_THIS_COHORT
KNOWLEDGE_ACTION_INFLUENCE_STATUS  = OUT_OF_SCOPE
PRODUCTION_CALLER_STATUS           = REAL (dv-harness question-queue answer, unchanged)
LIVE_QUALIFICATION_STATUS          = PARTIAL (section 13 -- the cohort's own required scenario proven; full live session not performed)
COHORT_1_REGRESSION_STATUS         = PASS
COHORT_2_REGRESSION_STATUS         = PASS
COHORT_3_REGRESSION_STATUS         = PASS
NEW_GAPS_FOUND                     = 0
NEW_GAPS_DEFERRED                  = 0
UNCLASSIFIED_NEW_GAPS              = 0
UNOWNED_NEW_GAPS                   = 0
COHORT_4_BLOCKING_GAPS_OPEN        = 0
FOCUSED_TESTS                      = 8 new
ADJACENT_REGRESSION                = 331/331 (14+173+10+13+20+44+57, section 14)
CONSTITUTION_GATE                  = 10/10 passed
UNKNOWN_REGRESSION_FAILURES        = 0
SOURCE_CAPABILITY_LOSS             = 0
FROZEN_SOURCE_CHANGES              = 0
GAP_M8_010_STATUS                  = COHORT_HARDENING, unchanged, untouched
Q_ENV_57D420FA_STATUS              = OPEN, untouched
REFERENCE_USB_ENV_CONSUMED         = NO
COMMITS                            = 1 (this Cohort-4 build; see COMMIT_SHA below)
NEXT_CANONICAL_GATE                = M8 Implementation Cohort 5 (CAP-M4.5-003
                                      final compliance, GAP-M8-007/GAP-M8-008
                                      -- depends on Cohorts 1-4, the rollup
                                      cohort) -- per M8_IMPLEMENTATION_
                                      COHORT_PLAN.md's own dependency graph.
                                      NOT started.
```

## 17. Stop condition

Cohort 4 satisfies both its own frozen exit criteria. `M8_COHORT_4_STATUS
= CLOSED`. Per explicit instruction: Cohort 5 is **not** auto-started,
Reference USB remains unconsumed, and this closure was not turned into a
new hardening or discovery wave.
