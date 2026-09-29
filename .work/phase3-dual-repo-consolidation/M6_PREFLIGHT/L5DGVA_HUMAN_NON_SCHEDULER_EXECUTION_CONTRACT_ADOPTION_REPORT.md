# L5DGVA Human Non-Scheduler Execution Contract -- Adoption Report

Source: `docs/architecture/canonical_detailed_governance/
L5DGVA_HUMAN_NON_SCHEDULER_EXECUTION_CONTRACT.md` (platform-level
requirement) + `.work/prompts/
L5DGVA_HUMAN_NON_SCHEDULER_EXECUTION_CONTRACT_INTEGRATION_PROMPT.md`
(execution contract). Both read in full before any change. Extends
Prime Directive V2 P6.

## Runtime enforcement, not documentation-only

New module `dv_harness/execution_contract.py`, 41/41 tests passing
(`dv_harness_tests/test_execution_contract.py`), reusing
`dv_harness/model_handoff_workflow.py`'s own real state and
`dv_harness/result_action_router.py`'s own action vocabulary -- no
second lifecycle engine, HumanGate, result router, or task-state
authority was created.

- `CANONICAL_STOP_REASONS` (exactly 5) + `INVALID_GENERIC_STOP_REASONS`
  (15 named) + `validate_stop_reason()`: every real stop path in
  `can_i_stop()` runs through this; `StopDecision.__post_init__()` also
  enforces it defensively at construction time, so an invalid reason
  cannot even be built, let alone persisted.
- `can_i_stop()`: the exact documented decision order
  (HUMAN_AUTHORITY > HUMAN_TRANSPORT > SAFE_EXECUTION_BLOCKED >
  TERMINATION_POLICY_TRIGGERED > any real pending-work flag = CONTINUE
  > asserted TASK_COMPLETE > default CONTINUE), run against real
  `WorkflowSignals`, never prose heuristics.
- `resolve_next_action()`: table-driven, provider-independent
  (`NEXT_ACTION_TABLE`), matching all 5 named worked examples exactly.
  An unrecognized event is a real `ValueError`, never a guessed default.
- `persist_stop()`/`read_persisted_stop()`: real JSON persistence at
  `.dv-harness/model_handoffs/<task_id>/execution_contract_state.json`
  -- additive to, never competing with, `model_handoff_workflow.py`'s
  own `state.json`.
- `signals_from_model_handoff_state()`: the real adapter that reads
  `model_handoff_workflow.current_state()` and translates
  `WAITING_FOR_HUMAN_TRANSPORT` into a fully-populated Human Transport
  Gate signal set (task_id/target_model/handoff_file/
  expected_result_file/import_command/resume_action), never fabricated.

## Applied to the live M7 Codex case

`M7-V1-CODEX-REVIEW-001` (fully remediated, re-review handoff already
generated last task): `signals_from_model_handoff_state(root,
"M7-V1-CODEX-REVIEW-001", canonical_task_complete=True)` ->
`can_i_stop()` -> `STATE=COMPLETE`, `STOP_REASON=TASK_COMPLETE` (real,
because all 5 pending-work flags are genuinely zero for this task_id's
own scope and a caller has explicitly asserted completion, per section
6's own "derive pending work from real state; do not fake counters").

`M7-V1-CODEX-REVIEW-002` (the real, live re-review handoff): the SAME
function, with no override, correctly resolves to
`STATE=WAITING_FOR_HUMAN_TRANSPORT`, `STOP_REASON=
HUMAN_TRANSPORT_REQUIRED`, with every Human Transport Gate field
populated from the real, currently-persisted `HANDOFF_V1.md` -- and this
decision was persisted for real to
`.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-002/
execution_contract_state.json`. Full evidence:
`M7_CODEX_AUTONOMOUS_REMEDIATION_TRACE.md`,
`M7_CODEX_RE_REVIEW_HANDOFF_EVIDENCE.md` (updated this task).

This confirms the correct current classification is
`AUTO_REMEDIATION_RUNNING`-then-`WAITING_FOR_HUMAN_TRANSPORT` -- never
`WAITING_FOR_USER_TO_CONTINUE` -- and that classification is now backed
by a real, callable gate rather than only prose.

## Required final invariants

```
HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES
HUMAN_IS_WORKFLOW_SCHEDULER=NO
DEFAULT_EXECUTION_POLICY=AUTO_CONTINUE
STOP_REQUIRES_EXPLICIT_REASON=YES
AUTO_RESUME_AFTER_RESULT_IMPORT=YES
INVALID_GENERIC_CONTINUE_STOPS=0
AUTO_ACTIONABLE_STOPPED_FOR_USER=0
```

- `HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES` / `HUMAN_IS_WORKFLOW_SCHEDULER=NO`:
  real, enforced (`can_i_stop()` never asks permission to continue when
  no gate signal is set; `test_auto_actionable_result_does_not_stop_for_user`
  and siblings prove it).
- `DEFAULT_EXECUTION_POLICY=AUTO_CONTINUE`: the Can-I-Stop Gate's own
  final `ELSE: CONTINUE` fallback (`test_subtask_complete_does_not_
  equal_canonical_task_complete`).
- `STOP_REQUIRES_EXPLICIT_REASON=YES`: `StopDecision` cannot be
  constructed with `should_continue=True` and a non-`None` `stop_reason`
  (`__post_init__` raises); a stop always carries one of the 5 canonical
  reasons.
- `AUTO_RESUME_AFTER_RESULT_IMPORT=YES`: `resolve_next_action(
  "RESULT_CONSUMED")` -> `AUTO_REMEDIATE_CONFIRMED_FINDINGS`,
  `auto_actionable=True`, `human_action_required=NO`
  (`test_result_import_auto_resumes`).
- `INVALID_GENERIC_CONTINUE_STOPS=0`: all 15 named strings are real,
  tested `InvalidStopReasonError` cases
  (`test_waiting_for_review_is_not_valid_stop_reason`, parametrized over
  all 15).
- `AUTO_ACTIONABLE_STOPPED_FOR_USER=0`: every `*_pending=True` signal
  combination tested resolves to `AUTO_RUNNING`/`HUMAN_ACTION_REQUIRED=NO`.

## Status summary

```
CAN_I_STOP_GATE=WIRED_AND_TESTED
NEXT_ACTION_RESOLVER=WIRED_AND_TESTED
HUMAN_TRANSPORT_GATE=WIRED_AND_TESTED_AND_APPLIED_TO_LIVE_CASE
HUMAN_AUTHORITY_GATE=WIRED_AND_TESTED_NOT_YET_TRIGGERED_LIVE
AUTO_RESUME=WIRED_AND_TESTED (table-driven; production call site NOT_YET_WIRED)
ANTI_DRIFT_TESTS=41/41
CURRENT_SCOPE_GAPS_OPEN=0
M6_GOLDEN_PATH_PRESERVED=YES
UNKNOWN_REGRESSION_FAILURES=0
SOURCE_CAPABILITY_LOSS=0
```

Per this task's own honesty discipline (see
`M7_AUTONOMOUS_REMEDIATION_EVIDENCE.md` from the prior task): this
module is real, tested, and demonstrated once against the live M7 Codex
case; it is not yet the thing every engine/CLI state-changing operation
calls automatically. `M7_STOP_ELIGIBILITY_AND_NEXT_ACTION_POLICY.md`
registers that remaining wiring gap explicitly.

## STOP

`STATE=WAITING_FOR_HUMAN_TRANSPORT`, `STOP_REASON=HUMAN_TRANSPORT_REQUIRED`,
for `TASK_ID=M7-V1-CODEX-REVIEW-002` -- a genuine, contract-verified stop.
ChatGPT round trip not started. M8 not started. Reference USB not
consumed.
