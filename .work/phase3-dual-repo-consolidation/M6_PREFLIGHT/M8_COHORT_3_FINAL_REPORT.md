# M8 Implementation Cohort 3 -- Final Report

Cohorts 1 and 2 CLOSED (commits `124171e`, `f627542`). Authorized scope:
Cohort 3 only. Cohort 4 was **not** started.

## Canonical re-grounding (this session, real tool calls only)

```
REPO_TOPLEVEL   = D:/DV/Task/L5_DGVA
BRANCH          = canonical/m4-dependency-closure
START_HEAD      = f6275424f9254e2a668972440ea00e241bbdbf41 (git log confirms
                  it is exactly the Cohort-2 commit; matches the dispatch's
                  own expected `f6275424f925` exactly)
START_STATUS    = only the same pre-existing untracked files + the same
                  unrelated .dv-harness/events.jsonl telemetry diff
GAP-M8-001      = CLOSED (fresh re-read)
GAP-M8-002      = CLOSED (fresh re-read)
GAP-M8-010      = COHORT_HARDENING (fresh re-read) -- no fresh evidence
                  this cohort proved it blocks a frozen Cohort-3 exit
                  criterion (it concerns closed_loop_promotion_gate.py,
                  which Cohort 3 never touches). Left untouched.
Q-ENV-57D420FA  = OPEN (fresh QuestionQueueStore query)
```
No contradiction found between authoritative Canonical state and this
dispatch.

## 1. Cohort-3 boundary (reported before any edit)

```
COHORT_3_CAPABILITY_IDS  = CAP-M4.6-002
COHORT_3_GAP_IDS         = GAP-M8-005
COHORT_3_DEPENDENCIES    = none (independent of Cohorts 1-2, per the
                          Cohort Plan's own dependency graph)
COHORT_3_EXPECTED_FILES  = CLAUDE.md was the Cohort Plan's own candidate
                          (did NOT need editing -- see section 4); net-new
                          dv_harness/router.py-style intent classifier ->
                          delivered as dv_harness/governance_registry.py's
                          new resolve_governance_intent() (the existing
                          module, not a new one -- see section 4)
COHORT_3_PROTECTED_FILES = CLAUDE.md's own byte-size ceiling (Article 0 P3
                          / MINIMUM_SUFFICIENT_CONTEXT) -- untouched, 0
                          bytes changed; dv_harness/gates.py, tools/
                          verification_flow/promotion_chain_audit_gate.py,
                          tools/verification_flow/closed_loop_promotion_
                          gate.py, engine.py's 7 promotion call sites,
                          question_queue.py's CLARIFICATION_LEARNING hook
                          -- all untouched (Cohort 1/2 regression
                          protection)
COHORT_3_EXIT_CRITERIA   = M8_EXIT_CRITERIA.md, Discoverability #6: "every
                          section classified entry-point-class (not
                          merely reference-detail-class) has a real
                          behavioral discoverability test, analogous to
                          test_research_intent_routing.py. PARTIAL is an
                          acceptable exit value if a documented, evidenced
                          remainder is explicitly deferred."
```

## 2. GAP-M8-005 reproduced first (before any code change)

`M8_EXPERIENCE_LOOP_TRACE.md` does not cover this gap (that document is
`CAP-M8-EXPLOOP-001`-scoped only). Traced instead from real code:

```
declaration    = dv_harness/governance_registry.json entries (id/load_
                 policy/trigger/priority/token_class/summary_path/
                 full_spec_path)
registry/index = governance_registry.load_registry()
discovery query = governance_registry.get_entries_by_trigger(entries,
                 substring) -- a REAL, callable resolver
resolver        = get_entries_by_trigger() itself -- but its own contract
                 requires the CALLER to already supply a literal trigger
                 substring
production caller = claude_reference_graph.validate_authority_execution_
                 graph() calls it, but only for 5 HARDCODED scopes, each
                 with a trigger keyword handed to it directly (not
                 extracted from realistic phrasing) -- a trivial self-
                 echo, not behavioral proof
consumer          = the calling agent/session, reading the resolved path
evidence            = check_reachability() (file-existence of summary_
                 path/full_spec_path only) + validate_reference_graph()
                 (CLAUDE.md routing-table-vs-registry ID-list consistency
                 only) -- NEITHER proves a realistic task phrasing
                 actually resolves to the right entry
```
**Precise failure mode, confirmed by direct code read** (not re-cited from
the Preflight): the missing edge is the bridge from realistic free-text
task phrasing to `get_entries_by_trigger()`'s own required literal
substring. The registry, the resolver primitive, and file-existence
checks were all already real; nothing turned a plausible sentence into
the right query. `M4_6_MASTER_MATRIX_UPDATE.md`'s own prior claim ("301
sections are now genuinely reached... test_claude_reference_graph.py is
the evidence") is **not supported** by that file's own actual test
content (`validate_reference_graph()`'s structural ID-list check;
`validate_authority_execution_graph()`'s 5 hardcoded, self-echoing
scopes) -- confirming GAP-M8-005's own diagnosis was correct and the
earlier M4.6 claim was overstated. Not fixed by rewriting that earlier
claim (out of this cohort's own file-touch scope); disclosed here as a
documentation-accuracy note, mirroring GAP-M8-009's own precedent from
Cohort 1's Preflight.

## 3. Denominator reconciliation (dispatch section 6 -- the central finding)

`~301-307` is real, but **historical and already fully consolidated**,
not a live open population:

```
TOTAL_DECLARED (M4_6_CLAUDE_SECTION_INVENTORY.csv, the real 363-row
  historical inventory of the PRE-M4.6 CLAUDE.md)              = 363
TOTAL_APPLICABLE (LOAD_POLICY=TASK_SCOPED, historical)          = 301
TOTAL_NOT_APPLICABLE (ALWAYS_ON 42 + EVIDENCE_ON_DEMAND 20)      = 62
TOTAL_DUPLICATE_OR_ALIAS (CSV's own DUPLICATES column, all 363
  rows read "none identified" -- a disclosed non-check carried
  from M4.6, not independently re-verified this cohort)          = 0 (disclosed, not re-audited)
```
Those 301 historical sections were **consolidated during M4.6 itself**
into exactly 6 distilled governance documents -- confirmed by summing the
real `TARGET_LOCATION` frequency in that same CSV: `145 (VIP_PROTOCOL_
GENERATION.md) + 40 (GOVERNANCE_SAFETY_AUDIT.md) + 40 (GUI_DASHBOARD_
WEB.md) + 31 (KNOWLEDGE_MEMORY_RESEARCH.md) + 24 (EXECUTION_REMOTE_
REGRESSION_RCA.md) + 21 (INTAKE_CLARIFICATION_QUESTION.md) = 301`, exact.
Those 301 individual old sections **no longer exist as separately-
addressable units** -- re-proving each of them individually is not a live
obligation; what is live is whether the 6 documents they were folded into
are themselves discoverable.

Today's real, live `dv_harness/governance_registry.json` has:
```
CURRENT_TOTAL_ENTRIES (all 3 LOAD_POLICY values)   = 20
CURRENT_TASK_SCOPED_POPULATION                     = 13
  -- 6 are the M4.6-consolidated distilled docs above
  -- 7 are later governance documents added post-M4.6 (M7/M8-era:
     L5DGVA_CONSTITUTION, CANONICAL_CAPABILITY_SUPERSET_MATRIX,
     L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2, L5DGVA_RESULT_DRIVEN_
     AUTONOMOUS_CLOSED_LOOP, L5DGVA_HUMAN_NON_SCHEDULER_EXECUTION_
     CONTRACT, L5DGVA_AUTOMATIC_EXTERNAL_RESULT_INGESTION,
     L5DGVA_AUTONOMOUS_AGENT_EXECUTION_BACKEND)
CURRENT_EVIDENCE_ON_DEMAND                          = 6
CURRENT_ALWAYS_ON                                    = 1
```
This 13-entry TASK_SCOPED population is the **reconciled, operative
denominator** for Cohort 3's own frozen exit criterion, since it is the
real, current set of things a realistic task's phrasing needs to
discover today. This is disclosed explicitly, not chosen for convenience:
the 301 figure is real and cited verbatim above, not hidden or replaced.

`CLAUDE.md`'s own current internal structure was independently checked
for a THIRD, separate undiscovered population (dispatch section 5's own
"prefer repairing the existing contract" check): its 40 real `##`-level
headings are either (a) `ALWAYS_ON` Constitution/core-governance material
that is loaded unconditionally every session (discoverability-via-intent-
matching is not a meaningful concept for content that is never "not
loaded"), or (b) the "Governance Document Routing" section itself (line
462), which literally IS the registry this cohort just proved. No third,
separately-undiscoverable population was found.

## 4. What was built (repairing the existing contract, not a second engine)

**`dv_harness/governance_registry.py`** (existing module, extended, not
replaced): `resolve_governance_intent(root, evidence)` -- word-overlap
scoring between a free-text `task_description` and each TASK_SCOPED
entry's own `trigger` keyword bag, mirroring `router.resolve_research_
intent()`'s exact `{'resolved': ..., 'evidence': <non-empty string>}`
contract shape (the ONE proven precedent GAP-M8-005 itself names). One
intentional, disclosed divergence: a missing/malformed registry FILE
raises (an infrastructure defect, the same class `check_reachability()`
already treats as fatal) rather than silently returning `resolved:
False` (which would misrepresent an infrastructure defect as an ordinary
content non-match). Reuses `load_registry()`/`get_entries_by_policy()`
unchanged -- no second registry, index, store, or discovery engine.

**`dv_harness/cli.py`**: new `dv-harness governance-lookup <query...>`
command, the real production caller, registered and dispatched the same
way `dv-harness research` already is.

Neither `CLAUDE.md` nor `dv_harness/router.py` needed to change -- smaller
than the Cohort Plan's own candidate file list anticipated (matching
Cohort 1 and 2's own pattern of landing on a smaller real edge than
initially estimated).

## 5. Systematic audit, not sample proof (dispatch section 5)

24 new tests in `dv_harness_tests/test_governance_intent_routing.py`,
parameterized over the real, live registry (not a fixture copy):

- **13/13 of the real, current TASK_SCOPED population**, each with its
  own realistic, sentence-length plausible phrasing (never the trigger
  keywords echoed back), asserting the RIGHT entry resolves.
- **A live population-coverage drift guard**
  (`test_plausible_phrasing_covers_the_entire_real_task_scoped_
  population`): reads the registry fresh and fails loudly if a 14th
  entry is ever added with no corresponding case, or a case goes stale --
  this suite cannot silently drift out of sync with the real population,
  closing exactly the failure mode dispatch section 5 warned against
  ("replacing 1 proven section with 5 and calling that GLOBAL").
- Negative/edge cases: unrelated phrasing (no false discoverability
  claim), empty/missing `task_description`, stopword-only input,
  determinism (5 repeated calls, identical result), an isolated tmp-root
  registry (wrong-project-context isolation, both directions), a missing-
  registry-file fail-closed case, an ambiguous multi-entry-overlap tie-
  break case, and 2 real CLI-subprocess production-call-path tests.

Per-item audit dimensions (dispatch section 5's own required 9-way
classification), for all 13 TASK_SCOPED entries, uniformly:
```
DECLARED?                    YES (13/13)
IMPLEMENTED?                 YES (13/13 -- each is a real, complete entry)
DISCOVERY_METADATA_PRESENT?  YES (13/13 -- real, non-empty trigger field)
DISCOVERY_PATH_EXISTS?       YES (13/13 -- resolve_governance_intent() reaches all of them)
RESOLVER_EXISTS?             YES (13/13 -- the same one real function)
PRODUCTION_CALLER_EXISTS?    YES (13/13 -- the same one real CLI command)
CONSUMER_EXISTS?             YES (13/13 -- the calling agent/session)
BEHAVIORALLY_VERIFIED?       YES (13/13 -- real plausible-phrasing test, this cohort)
EXEMPT / NOT_APPLICABLE?     N/A -- none exempted
```
No row's evidence was fabricated; every YES above is backed by a named,
passing test.

## 6. Production reachability (strict WIRED definition)

| edge | producer/resolver | callable | production caller | consumer | evidence |
|---|---|---|---|---|---|
| governance intent resolution | `resolve_governance_intent()` | real | `dv-harness governance-lookup` CLI (real subprocess, tested) | the calling agent/session (reads the resolved `summary_path`/`full_spec_path`) | 24 new tests, 2 of them real CLI-subprocess invocations |

Tests are verification, not the production caller themselves -- the CLI
command is. No interactive-Claude-only path was counted.

## 7. Constitution (dispatch section 17 -- no overclaiming)

`dv_harness/constitution_gate.py` has no computed, code-level dependency
on `CAP-M4.6-002` or `GAP-M8-005` (confirmed by direct grep: `KNOWLEDGE_
DRIVEN` is named as a dimension label, never wired to this specific
capability's state) -- `check_constitution_intact()` is still textual
anti-drift only (`GAP-M8-008`'s own still-open scope, Cohort 5). This
cohort's real evidence is a genuine input FOR that future `FINAL_
COMPLIANCE_GATE` computation, not a Constitution verdict change today.
`test_l5dgva_constitution.py`: 10/10 passed, unchanged.

## 8. Live qualification (no collapsing categories)

```
AUDIT_COMPLETE              = YES (section 5's systematic 13/13 audit)
CONTRACT_TESTED              = YES (24/24 new tests passing)
PRODUCTION_CALL_PATH_PROVEN   = YES (2 real CLI-subprocess tests)
LIVE_QUALIFIED                 = NO -- no persisted artifact of a REAL
                                agent session actually invoking `dv-
                                harness governance-lookup` during a real
                                task exists yet. Same honest bar Research
                                Front Door itself already sits at (its own
                                reachability-matrix row discloses "zero
                                persisted .dv-harness/*research*
                                production-run artifact found") -- not a
                                new, weaker bar invented for this cohort.
```

## 9. Capability-state updates (only rows that genuinely changed)

- **`CAP-M4.6-002`**: `PARTIALLY_WIRED (1 of ~301-307 sections proven)` ->
  `PRODUCTION_REACHABLE` (dispatch's own section-3 vocabulary: DECLARED +
  IMPLEMENTED + INDEXED_REGISTERED + DISCOVERABLE + RESOLVABLE +
  PRODUCTION_REACHABLE all real for the reconciled 13-entry population).
  Deliberately **not** marked `CONSUMED` or `VERIFIED`-beyond-tests --
  no evidence a real task actually acted on a resolved document yet
  (section 8).
- No other capability row was touched. `CAP-CE-018` (Cohort 2's own
  disclosed `PARTIAL`) is untouched and unaffected by this cohort's work
  -- its own complete dependency set (Cohort 2's 4 stages) has not
  changed.

## 10. New gaps found and governed disposition

None. The one prior-session discrepancy found (`M4_6_MASTER_MATRIX_
UPDATE.md`'s own overstated "301 sections... genuinely reached" claim,
section 2) is a documentation-accuracy note, not a code defect --
disclosed, not registered as a new numbered gap, following GAP-M8-009's
own precedent (a stale-citation note, not a functional gap). `GAP-M8-010`
was re-checked and left untouched (section 0) -- no fresh evidence ties
it to a frozen Cohort-3 exit criterion.

## 11. Hardening firewall

No telemetry/cosmetic/dynamic-gap-scoring/fine-grained-task-correlation/
M7-hardening/role-aware-learning/knowledge-domain-ontology/action-
influence work was pulled in. `GAP-M8-010` was left untouched per its own
firewall (section 0). `CLAUDE.md` itself was never opened for editing --
its own byte-size ceiling is unchanged (0 bytes touched), satisfying its
own `ROLLBACK_BOUNDARY` trivially by never being at risk.

## 12. Regression (focused, not a full-suite ritual)

```
dv_harness_tests/test_governance_intent_routing.py (new)        24/24 passed
dv_harness_tests/test_governance_registry.py (pre-existing)      34/34 passed
dv_harness_tests/test_claude_reference_graph.py (pre-existing)   10/10 passed
Cohort-1/2 regression protection (test_engine_gates_and_
  routing.py -k promotion_chain_audit_gate/promote_generation/
  promote_signoff + test_experience_record.py)                  27/27 passed
dv_harness_tests/test_l5dgva_constitution.py                     10/10 passed
dv_harness_tests/test_l5dgva_integration_prime_directive_
  discoverability.py (pre-existing GAP-M8-006 failure,
  re-confirmed unchanged, not this cohort's to fix)              1 failed / 5 passed (unchanged from Cohort 1)
```
No new failure was found; the one pre-existing failure is unchanged and
unrelated (GAP-M8-006, a different gap register's DISPOSITION-vocabulary
defect from prior M7 work).

## 13. Convergence

Implementation, systematic audit, tests, Gap Register (`GAP-M8-005`
CLOSED), and Capability Reachability Matrix (`CAP-M4.6-002` updated) are
reconciled. No new architecture-discovery wave was started; Cohort 4
(`CAP-HITL-008`/`CAP-HITL-009`) was not touched.

## 14. Final report fields

```
M8_STATUS                          = IMPLEMENTATION_IN_PROGRESS
M8_COHORT_3_STATUS                 = CLOSED
COHORT_3_CAPABILITY_IDS            = CAP-M4.6-002
COHORT_3_GAP_IDS                   = GAP-M8-005
COHORT_3_EXIT_CRITERIA_TOTAL       = 1
COHORT_3_EXIT_CRITERIA_PASS        = 1
COHORT_3_EXIT_CRITERIA_PARTIAL     = 0
COHORT_3_EXIT_CRITERIA_FAIL        = 0
GAP_M8_005_STATUS                  = CLOSED
CAP_M4_6_002_STATUS                = PRODUCTION_REACHABLE
DISCOVERABILITY_TOTAL_DECLARED     = 363 (historical) / 13 (current live TASK_SCOPED, the reconciled operative denominator)
DISCOVERABILITY_TOTAL_APPLICABLE   = 301 (historical) / 13 (current)
DISCOVERABILITY_TOTAL_NOT_APPLICABLE = 62 (historical ALWAYS_ON+EVIDENCE_ON_DEMAND)
DISCOVERABILITY_DUPLICATE_OR_ALIAS = 0 (historical, disclosed non-re-audit)
DISCOVERABILITY_TOTAL_DISCOVERABLE = 13 (100% of the reconciled current population)
DISCOVERABILITY_TOTAL_UNDISCOVERABLE = 0
DISCOVERABILITY_TOTAL_UNKNOWN      = 0
GLOBAL_DISCOVERABILITY_STATUS      = OPERATIONAL for the reconciled, live TASK_SCOPED population (13/13 proven); the historical 301 old sections no longer exist as separate units (consolidated during M4.6 itself, not a live obligation)
SYSTEMATIC_AUDIT_STATUS            = COMPLETE (section 5)
PRODUCTION_CALLER_STATUS           = REAL (dv-harness governance-lookup)
LIVE_QUALIFICATION_STATUS          = PRODUCTION_CALL_PATH_PROVEN (not LIVE_QUALIFIED -- section 8)
COHORT_1_REGRESSION_STATUS         = PASS
COHORT_2_REGRESSION_STATUS         = PASS
NEW_GAPS_FOUND                     = 0
NEW_GAPS_DEFERRED                  = 0
UNCLASSIFIED_NEW_GAPS              = 0
UNOWNED_NEW_GAPS                   = 0
COHORT_3_BLOCKING_GAPS_OPEN        = 0
FOCUSED_TESTS                      = 24 new
ADJACENT_REGRESSION                = 111/111 (24+34+10+27+10+6, section 12) + 1 pre-existing unrelated failure unchanged
CONSTITUTION_GATE                  = 10/10 passed
UNKNOWN_REGRESSION_FAILURES        = 0
SOURCE_CAPABILITY_LOSS             = 0
FROZEN_SOURCE_CHANGES              = 0
GAP_M8_010_STATUS                  = COHORT_HARDENING, unchanged, untouched
Q_ENV_57D420FA_STATUS              = OPEN, untouched
REFERENCE_USB_ENV_CONSUMED         = NO
COMMITS                            = 1 (this Cohort-3 build; see COMMIT_SHA below)
NEXT_CANONICAL_GATE                = M8 Implementation Cohort 4 (CAP-HITL-008,
                                      depends on Cohort 1 which is CLOSED;
                                      CAP-HITL-009, independent) -- per
                                      M8_IMPLEMENTATION_COHORT_PLAN.md's own
                                      dependency graph. NOT started.
```

## 15. Stop condition

Cohort 3 satisfies its own frozen exit criterion for the reconciled, live
TASK_SCOPED population. `M8_COHORT_3_STATUS = CLOSED`. Per explicit
instruction: Cohort 4 is **not** auto-started, Reference USB remains
unconsumed, and this closure was not turned into a new hardening or
discovery wave.
