# M5 Cohort 4 — Canonical Contract / OpenSpec Semantic Merge — Final Report

```
M5_STATUS = IN_PROGRESS (Cohort 4 CLOSED for its own scoped task; the
            wider queue's Cohort 4 grouping -- which also includes
            CAP-M5-COV-001/CAP-M5-DSI-001 -- is PARTIAL, since those two
            were never in this task's scope; Cohort 5 remains)
M5_COHORT_4_STATUS = CLOSED (for CAP-ATL-004 + CAP-ATL-007, this task's
            own full scope)

START_HEAD = 3980908
END_HEAD = d957c4b391f852bbda2202cb214d266fd3711521 (commit d957c4b, this Cohort's own commit)

TASK_BOUNDARY_CAPABILITY_STATUS = RESOLVED (migrated as FOUNDATION;
            IMPLEMENTED=YES, TESTED=YES, WIRED=NO -- deferred to
            CAP-M6-DISPATCH-001)
FIELD_RESOLUTION_CAPABILITY_STATUS = RESOLVED (migrated as FOUNDATION,
            ADAPTED not blind-copied; IMPLEMENTED=YES, TESTED=YES,
            WIRED=NO -- reconciliation with intake_state.py deferred to
            CAP-M6-CLARSVC-001)

PARENT_BEHAVIORS_ANALYZED = 2 modules in full (330 + 658 lines), plus 2
            real Parent test files in full (19 + 24 tests, both
            independently re-run in Parent's own tree before trusting)
PARENT_BEHAVIORS_MERGED = 2 (the complete task-boundary contract; the
            complete field-resolution contract minus its Parent-only
            OPENSPEC_FIELD_ATTRIBUTES import, which is redefined locally
            with an identical value)
CANONICAL_BEHAVIORS_REUSED = 4 (change_impact._git/resolve_sha;
            source_authority.authority_rank/SourceClaim/resolve_conflict;
            question_queue.make_question_id/QuestionQueueStore;
            intake_state.IntakeFieldRecord/IntakeFieldStatus left
            untouched as a parallel, unreconciled system)

CALLERS_ANALYZED = 11 for task_boundary_conformance.py (1 Parent CLI
            verb + 1 Parent test file + 2 canonical dependency modules +
            skills/graph/engine zero-match checks); 15 for
            intake_field_resolution.py (9 real Parent sibling modules +
            10 Parent test files + 2 canonical dependency modules +
            1 canonical parallel-system module + skills/graph/engine
            zero-match checks)
UNKNOWN_RUNTIME_CALLERS = 0

SCHEMA_CHANGES = 0 (neither module has or gets a JSON Schema; no second
            competing OpenSpec schema introduced)
PUBLIC_SIGNATURE_BREAKS = 0
SOURCE_DEFECTS_NOT_PROPAGATED = 0 (both Parent modules passed their own
            real tests clean; no defect found in either this Cohort,
            unlike Cohorts 2/3's B8/B7B findings)
SOURCE_CAPABILITY_LOSS = 0 (every ported symbol/enum/algorithm branch
            preserved; the 2 deliberate departures are disclosed scope
            adaptations, not capability loss)

REGRESSION_CAUSED_BY_M5_COHORT_4 = 0
UNKNOWN_REGRESSION_FAILURES = 0
            (555 individual test results across all regression steps,
            0 failures -- see M5_COHORT_4_TEST_EVIDENCE.md)

N_WAY_TARGETS_COMPLETED_TOTAL = 8 of 8 shared-file/contract targets named
            in the original Cohort 0 inventory (CAP-M5-ENV-001,
            CAP-M5-ARCH-001, CAP-M5-ARCH-002, CAP-M5-ARCH-003,
            CAP-M5-TOPTB-001, CAP-M5-VIP-001, CAP-ATL-004, CAP-ATL-007)
N_WAY_TARGETS_REMAINING = 2 (CAP-M5-COV-001, CAP-M5-DSI-001 -- both
            HUMAN_DECISION-flavored contract questions, not pure
            engineering merges, still Cohort 4's nominal queue-grouping
            but never in THIS task's own scope) + Cohort 5's pool

AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT = 5 (unchanged -- neither
            CAP-ATL-004 nor CAP-ATL-007 was ever P0)
M6_BLOCKERS = 3 (CAP-M6-DISPATCH-001, CAP-M6-CLARSVC-001,
            CAP-M5M6-VLEVEL-001 -- unchanged; NOT closed by this Cohort,
            per explicit instruction -- both new FOUNDATION modules are
            disclosed DEPENDENCIES those blockers can now build on)

NEXT_RECOMMENDED_GATE = CAP-M5-COV-001 / CAP-M5-DSI-001 (the two
            remaining named Cohort-4-grouped items) or Cohort 5 -- awaits
            explicit review/approval

COHORT_5_STARTED = NO
M6_STARTED = NO
M10_5_STARTED = NO
M14_STARTED = NO
M14_ROADMAP_PRESERVED = YES

MASTER_CAPABILITY_MATRIX_ROWS = 133 (excl. header)
MASTER_CAPABILITY_MATRIX_MALFORMED_ROWS = 0
MASTER_CAPABILITY_MATRIX_DUPLICATE_IDS = 0

OPENSPEC_8_FIELD_MODEL_PRESERVED = YES
CONFIDENCE_VALIDATION_CONFIRMATION_SEPARATION = PRESERVED
AUTO_DISCOVERY_FIRST = YES
M6_CLARIFICATION_FOUNDATION_READY = YES

REFERENCE_USB_ENV_CONSUMED = NO
```

## Corrections made mid-Cohort (Evidence Truth Rule)

Two facts asserted at Cohort start (`PARENT_CALLERS = 0`,
`PARENT_TESTS = 0` for `task_boundary_conformance.py`) were **wrong**,
traced to an unscoped background grep across Parent's entire repo root
silently returning no matches. Corrected before any migration decision
was made: Parent has 19 real, passing tests and a real, wired `cli.py`
verb for this module. This changed the migration shape (port Parent's
real tests instead of writing new ones from scratch) and surfaced that
the module's own docstring was itself stale (claimed no `cli.py` wiring,
which was false in Parent) — corrected in canonical's copy rather than
propagated.

## What was migrated

- `dv_harness/task_boundary_conformance.py` (330 lines) +
  `dv_harness_tests/test_task_boundary_conformance.py` (19 tests, ported
  verbatim, independently re-run: 19/19 pass in both Parent and
  canonical).
- `dv_harness/intake_field_resolution.py` (adapted, 2 deliberate
  departures disclosed in its own docstring) +
  `dv_harness_tests/test_intake_field_resolution.py` (25 tests: 24
  ported from Parent + 1 new canonical-specific test; 25/25 pass).

## What was deliberately NOT done

- No `cli.py` wiring for `task_boundary_conformance.py` (deferred to
  `CAP-M6-DISPATCH-001`, an open P0 blocker whose own dispatch-mechanism
  decision this Cohort must not pre-empt).
- No reconciliation between the new `intake_field_resolution.py` and
  canonical's existing, different `intake_state.IntakeFieldRecord`/
  `IntakeFieldStatus` model (deferred to `CAP-M6-CLARSVC-001`).
- No `ClarificationService` implementation.
- No migration of Parent's 9 sibling intake-pipeline modules or
  `irq_openspec_preflight_gate.py` (905 lines) — explicitly out of this
  Cohort's registered scope.
- No touch to `CAP-M5-COV-001`/`CAP-M5-DSI-001`, Cohort 5, M6, M10.5, or
  M14 benchmarks.

## Required artifacts (all 9 produced)

1. `M5_COHORT_4_TASK_BOUNDARY_ANALYSIS.md`
2. `M5_COHORT_4_TASK_BOUNDARY_CALLER_SWEEP.csv`
3. `M5_COHORT_4_FIELD_RESOLUTION_ANALYSIS.md`
4. `M5_COHORT_4_FIELD_RESOLUTION_CALLER_SWEEP.csv`
5. `M5_COHORT_4_SOURCE_BEHAVIOR_MATRIX.csv`
6. `M5_COHORT_4_CANONICAL_CONTRACT_MAP.md`
7. `M5_COHORT_4_SEMANTIC_MERGE_PLAN.md`
8. `M5_COHORT_4_TEST_EVIDENCE.md`
9. `M5_COHORT_4_FINAL_REPORT.md` (this file)

## STOP

Per standing instruction: do not start Cohort 5, M6, or M10.5
automatically. Awaiting explicit review/approval.
