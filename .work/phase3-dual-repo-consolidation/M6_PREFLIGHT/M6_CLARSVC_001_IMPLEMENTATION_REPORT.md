# CAP-M6-CLARSVC-001 — Implementation Report

Executed under the approval that closed `CAP-M6-DISPATCH-001` and dispatched
`CAP-M6-CLARSVC-001`. Builds `dv_harness/clarification_service.py` — ONE
Canonical `ClarificationService` (M-1 D2, not reopened as pick-one), composed
strictly from two already-real foundations (`question_queue.py`,
`intake_field_resolution.py`), never a second Field Resolution engine.
Full mechanics, contract-by-contract rationale and per-requirement test
evidence live in this task's own preflight artifacts (cited throughout);
this report gives the named summary fields and the final regression/
governance disposition.

```
CAP_M6_CLARSVC_001_STATUS = IMPLEMENTED

START_HEAD = 7c9a363d5863b97ae0926be2d71ee4ea19b91662
END_HEAD   = <filled in follow-up commit>

QUESTION_QUEUE_FOUNDATION = ALREADY_RESOLVED
ONE_CLARIFICATION_SERVICE = YES
QUESTION_OWNER_ROUTING = WIRED
HUMAN_GATE_INTEGRATION = WIRED (human_gate_state() projection has 0 production
                          callers today, disclosed; the real gate mechanism
                          it projects -- block-until-answered -- is wired
                          and tested independently of that helper)
ANSWER_TO_FIELD_RESOLUTION_LOOP = WIRED
AUTO_DISCOVERY_FIRST = PRESERVED
MINIMAL_STRUCTURED_CLARIFICATION = PRESERVED
NO_QUESTION_WHEN_AUTOMATICALLY_RESOLVED = YES

UNKNOWN_RUNTIME_CALLERS = 0
PUBLIC_SIGNATURE_BREAKS = 0

REGRESSION_CAUSED_BY_M6_CLARSVC = 0
UNKNOWN_REGRESSION_FAILURES = 0

M6_VERTICAL_SLICE_CONNECTED_STAGES_BEFORE = 6
M6_VERTICAL_SLICE_CONNECTED_STAGES_AFTER  = 8

AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT = 4
M6_CORE_BLOCKERS_REMAINING = 1 (CAP-M5M6-VLEVEL-001: VerificationLevel/
                              IP_MODE, narrowed this task — see below)
REFERENCE_USB_ENV_CONSUMED = NO

NEXT_RECOMMENDED_GATE = CAP-M5M6-VLEVEL-001 (VerificationLevel /
                          environment_mode_router.py IP_MODE branch) —
                          held per this dispatch's own explicit instruction
                          not to auto-start it
```

## QUESTION_QUEUE_FOUNDATION = ALREADY_RESOLVED — how this was established

Direct, structural re-investigation (not trust in the prior Master Blocker
Register text), documented in full in
`M6_CLARSVC_001_QUESTION_QUEUE_NWAY_ANALYSIS.md`: canonical's
`question_queue.py` is byte-identical (modulo line endings) to
v50/b7a/b7b/b8, and a confirmed strict superset of Parent's own copy — 13
real functions Parent lacks, 0 functions canonical lacks relative to Parent;
166 canonical tests vs. 67 Parent tests, both independently re-run and
green. The prior blocker text describing this as an open "N-way merge"
dependency was stale; this task corrected it at the point of use
(`CAP-M5M6-VLEVEL-001`'s own Master row, below) rather than silently
carrying the stale claim forward.

## ONE_CLARIFICATION_SERVICE = YES

`dv_harness/clarification_service.py` is the only module of its kind added
by this task. `resolve_or_ask()` is the single real entry point; it composes
`intake_field_resolution.resolve_field()` /
`evaluate_question_gate()` / `file_clarification()` (all three reused
verbatim, zero forked copies) with one new, real function
(`classify_question_owner()`) and one new, real persisted field
(`authority_role`). No second field-resolution engine, no duplicate question
schema. Full contract: `M6_CLARSVC_001_CONTRACT.md`.

## QUESTION_OWNER_ROUTING = WIRED

`classify_question_owner(control, decision)` — evidence/policy-based
(`FieldControl.domain` + `QuestionDecision.kind`), never a lazy `SHARED`
fallback. `SHARED` is reserved strictly for a `"dut"`-domain genuine
`CONFLICT`, matching `DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md`'s own first
named `SHARED` example (Spec/RTL contradiction). Persisted as a new,
additive, nullable `authority_role` property on
`schemas/question.schema.json` and `question_queue.add_question()`. Full
mapping and rationale: `M6_CLARSVC_001_ROLE_ROUTING.md`.

## HUMAN_GATE_INTEGRATION = WIRED, with one disclosed nuance

The real gate mechanism — dispatch blocks in `start_lifecycle()` until a
filed question's `answer` is non-null, then resumes through the same
`_start_dispatch()` path — is genuinely wired and tested
(`test_dispatch_blocks_on_unresolved_field_and_resumes_after_answer`).
`human_gate_state()`, the named projection onto
`HUMAN_GATE_CONTRACT.md`'s `RESOLUTION_STATE` vocabulary
(`WAITING_FOR_HUMAN`/`ANSWERED`/`SUPERSEDED`, with
`REJECTED`/`DEFERRED`/`CANCELLED` honestly returned as `NOT_SUPPORTED` since
no real code path produces them), exists and is tested in isolation but has
zero production call sites today — disclosed in
`M6_CLARSVC_001_CALLER_SWEEP.csv`, not hidden. The stage is still counted
CONNECTED because the underlying gate behavior it describes is real, not
because the helper's name merely exists.

## ANSWER_TO_FIELD_RESOLUTION_LOOP = WIRED

`resolve_or_ask()` checks `QuestionQueueStore.get_question()` for a real,
non-null `answer` BEFORE filing a new question; when found, it re-enters
`resolve_field(..., human_answer=existing["answer"])` — never a direct
`EffectiveValue` overwrite. This means the answer passes through the same
9-level source-authority arbitration, validation and confirmation-state
logic as any other candidate. Verified end-to-end by
`test_answer_round_trip_feeds_back_through_field_resolution` and
`test_dispatch_blocks_on_unresolved_field_and_resumes_after_answer`.

## AUTO_DISCOVERY_FIRST / MINIMAL_STRUCTURED_CLARIFICATION = PRESERVED

Both are properties of the reused `intake_field_resolution.py` functions,
untouched by this task. `resolve_or_ask()` always calls `resolve_field()`
first and only proceeds to `evaluate_question_gate()`/question-filing when
`field_is_sufficient()` says the auto/derived result is insufficient —
confirmed by `test_no_question_when_automatically_resolved` and
`test_optional_field_never_asks_even_when_unresolved`.

## Duplicate-question prevention

`resolve_or_ask()` derives a stable `question_key` (`intake:<field_id>`) and
looks up the existing record by `make_question_id()` before filing —
confirmed by `test_duplicate_question_is_not_re_filed_without_evidence_change`.

## Caller sweep

22 rows, `M6_CLARSVC_001_CALLER_SWEEP.csv`. `UNKNOWN_RUNTIME_CALLERS = 0`:
every real caller of the touched public functions
(`resolve_field`/`evaluate_question_gate`/`file_clarification`/
`add_question`) is either this task's own new `clarification_service.py`,
`engine.py`'s refactored `start_lifecycle()`, or a test file.
`PUBLIC_SIGNATURE_BREAKS = 0`: every changed signature
(`add_question`, `file_clarification`) added its new parameter
(`authority_role`) as the last keyword-only argument with a `None` default —
every existing call site continues to work unchanged.

## Regression

Full run across the same 47 dispatch-caller files
(`.loop(`/`.run_stage(` touchers) plus this task's own new
`test_clarification_service.py`:

```
python -m pytest <47 files> dv_harness_tests/test_clarification_service.py -v
=> 5 failed, 1159 passed, 10 skipped in 1110.68s (0:18:30)
```

`1159 = 1146 + 13` — exactly `CAP-M6-DISPATCH-001`'s own prior passing count
plus this task's 13 new `test_clarification_service.py` tests; no other
population member changed status.

All 5 failures are byte-identical, by test ID, to the same 5 failures
`CAP-M6-DISPATCH-001`'s own regression already classified as `PRE_EXISTING`
(itself citing `M5_FINAL_CLOSURE_FAILURE_CLASSIFICATION.md`):

```
FAILED dv_harness_tests/test_question_queue_digest_auto_trigger.py::test_digest_fires_after_a_real_gate_verified_stage_pass
FAILED dv_harness_tests/test_resource_cost_autonomy.py::test_3b_run_stage_performs_the_escalation_for_the_agent
FAILED dv_harness_tests/test_waveform_dump_scope_human_confirmation.py::test_autonomous_loop_files_the_question_it_parks_on_and_a_human_answer_closes_it
FAILED dv_harness_tests/test_waveform_dump_scope_human_confirmation.py::test_a_question_already_waiting_is_not_re_filed_by_a_second_loop_pass
FAILED dv_harness_tests/test_waveform_dump_scope_human_confirmation.py::test_nothing_is_filed_when_the_agent_declared_no_scope_or_no_level
```

Same file/count breakdown as the DISPATCH-001 regression (1 in
`test_question_queue_digest_auto_trigger.py`, 1 in
`test_resource_cost_autonomy.py`, 3 in
`test_waveform_dump_scope_human_confirmation.py`) — a real, pre-existing
`question_queue.py` digest/filing behavior producing more question records
than a shared test scenario expects, unrelated to
`clarification_service.py`/`start_lifecycle()`. None of the 5 failing files
touch `clarification_service.py`, `lifecycle.py`, `start_lifecycle()`, or
`_intake_first_guard()`. `REGRESSION_CAUSED_BY_M6_CLARSVC = 0`,
`UNKNOWN_REGRESSION_FAILURES = 0`.

Real per-test hang discipline was applied throughout (current-test identity
checked across consecutive polls, cross-referenced against the known
~19-minute historical duration of this same population from the
DISPATCH-001 run, rather than judged from CPU usage alone) — no hang was
declared; the run completed naturally in 18m30s, consistent with that prior
timing.

Full per-family test mapping: `M6_CLARSVC_001_TEST_EVIDENCE.md`.

## Vertical slice recount

`M6_VERTICAL_SLICE_STATUS.md`: 6 → 8 connected stages. `QuestionOwner` and
`HumanGate` moved from `ROADMAP_DEFINED` to real, connected, tested
mechanism. `VerificationLevel` and `IP/SUBSYSTEM/SYSTEM_LEVEL` remain
unconnected, correctly out of this task's scope (items 18/19 of the prior
`DEC-M6-DISPATCH-001` approval).

## Master control-plane update

`MASTER_CAPABILITY_STATUS_MATRIX.csv`: `CAP-M6-CLARSVC-001` row →
`IMPLEMENTED/WIRED/TRIGGERED/CONSUMED/TESTED = YES`, `PRIORITY` P0 → P2.
`CAP-M5M6-VLEVEL-001` row → `BLOCKER` text corrected: the stale
"depends on question_queue.py (diverged, M3-excluded)" clause replaced with
the real, current blocker (`verification_level.py` itself absent;
`environment_mode_router.py` has no `IP_MODE` branch), the resolved
question-queue dependency explicitly disclosed as closed rather than
silently dropped. `MASTER_WAVE_OWNERSHIP_MATRIX.csv`: `CAP-M6-CLARSVC-001`
priority/blocker_type updated to match. Structural re-validation after the
update: 157 status rows, 0 malformed, 0 duplicate `CAPABILITY_ID`s.

**Disclosed finding, out of this task's own scope to fix**:
`AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT` recount after this update is **4**,
not the 3 that would result if `CAP-M6-DISPATCH-001` had also been
downgraded — direct inspection of that row (`MASTER_CAPABILITY_STATUS_
MATRIX.csv`) shows it is still `PRIORITY = P0` /
`CANONICAL_STATE = PARTIAL (conflict named and understood)` /
`BLOCKER = HUMAN_DECISION_REQUIRED: which dispatch mechanism becomes
canonical`, even though `CAP-M6-DISPATCH-001` was approved, implemented,
tested and closed in the immediately prior task. That row's own Master-CSV
update appears to have been skipped when `CAP-M6-DISPATCH-001` closed —
a real, pre-existing bookkeeping gap, not something this task's own
dispatch authorized it to correct (this task's update script was scoped,
by explicit assertion, to only the `CAP-M6-CLARSVC-001` and
`CAP-M5M6-VLEVEL-001` rows). Remaining real P0 rows after this task's
update: `CAP-M6-DISPATCH-001` (stale — recommend a follow-up bookkeeping
fix), `CAP-M5M6-VLEVEL-001`, `CAP-M8-EXPLOOP-001`, `CAP-CE-018`.

## Governance gates

```
dv_harness.constitution_gate.check_constitution_intact('.')
  => ConstitutionCheckResult(status='PASS', reasons=[])
```

All 5 frozen sources (Parent/v50/b7a/b7b/b8) re-verified unchanged
immediately before this report's own commit:

```
Parent (D:\DV\Task\DV_Agent_Harness_L5) = 3e9dd7360f584078ed8f4b04120c9844acabd97b  UNCHANGED
v50    (D:\DV\Task\DV_Agent_Harness_L5\v50)                                        = f3fd17326cf3654aca6fd83fad991a3f247e6682  UNCHANGED
b7a    (D:/wt/b7a)                                                                 = 7b2a65a4dc2d40d493451b409669c90ed0b3d9a5  UNCHANGED
b7b    (D:/wt/b7b)                                                                 = c7c7fa09e9ee8336ba102b4495f4b8808408fe0b  UNCHANGED
b8     (D:/wt/b8)                                                                  = c9cdd06ce586d44f4c0cef00310c10f95ea59f93  UNCHANGED
```

## What this task deliberately did not build (Sections 13/14/18, unchanged)

- Native Claude Fast Maintenance's own CLI flow.
- Structured Excel Intake's own UX.
- `CAP-M5M6-VLEVEL-001` (`VerificationLevel`) — `level`/`protocols` remain
  stored-but-uninterpreted lifecycle facts, unchanged from
  `CAP-M6-DISPATCH-001`'s own implementation. Per this dispatch's own
  explicit closing instruction, not started here and not auto-started next.
- Reference USB environment — not consumed (`REFERENCE_USB_ENV_CONSUMED = NO`).

## STOP

Per this dispatch's own explicit closing instruction: stopping here.
`CAP-M5M6-VLEVEL-001` is the recommended next gate but is not
auto-started.
