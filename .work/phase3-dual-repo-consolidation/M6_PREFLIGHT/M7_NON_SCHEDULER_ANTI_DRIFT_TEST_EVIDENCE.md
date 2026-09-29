# M7 Non-Scheduler Anti-Drift Test Evidence

`dv_harness_tests/test_execution_contract.py`: 41/41 pass. All 13 named
anti-drift tests from the requirements doc/integration prompt are
present, each verifying real behavior (via `can_i_stop()`/
`resolve_next_action()`/persistence), never string matching alone:

| Required test | Present as |
|---|---|
| `test_auto_actionable_result_does_not_stop_for_user` | exact name |
| `test_fix_now_correctness_blocker_auto_continues` | exact name |
| `test_required_validation_auto_continues` | exact name |
| `test_required_regression_auto_continues` | exact name |
| `test_rereview_preparation_auto_continues` | exact name |
| `test_result_import_auto_resumes` | exact name |
| `test_human_transport_requires_stop` | exact name |
| `test_human_authority_requires_stop` | exact name |
| `test_waiting_for_review_is_not_valid_stop_reason` | exact name (parametrized over all 15 invalid reasons) |
| `test_waiting_for_continue_is_not_valid_stop_reason` | exact name |
| `test_task_complete_rejected_with_pending_auto_actions` | exact name |
| `test_subtask_complete_does_not_equal_canonical_task_complete` | exact name |
| `test_transport_resume_restores_next_action` | exact name |

Plus 28 additional tests beyond the named minimum: every reject-priority
ordering combination, the `NEXT_ACTION_TABLE`'s 5 worked examples
individually, defensive construction checks
(`StopDecision.__post_init__` rejecting an invalid reason or a
CONTINUE-with-stop-reason combination), the real
`signals_from_model_handoff_state()` adapter against a real throwaway
git repo (not a mock), and both gate-report functions.

## What "verify behavior, not strings alone" means here, concretely

- `test_waiting_for_review_is_not_valid_stop_reason` does not merely
  check that a string appears somewhere -- it calls the real
  `validate_stop_reason()` function and asserts it raises
  `InvalidStopReasonError`, parametrized over all 15 named invalid
  reasons individually.
- `test_signals_from_model_handoff_state_reports_transport_when_waiting`
  builds a real `TaskBoundary` + `ModelHandoffV1`, calls the real
  `build_handoff()`/`export_handoff()` production functions against a
  real, throwaway git repository, then asserts the adapter's OUTPUT
  matches what was actually written to disk -- not a synthetic fixture
  standing in for the real state machine.
- `test_transport_resume_restores_next_action` round-trips through the
  real `persist_stop()`/`read_persisted_stop()` file I/O, not an
  in-memory stand-in.

## Status

`ANTI_DRIFT_TESTS=41/41 PASS`. Full related suite (model_handoff/
model_result/task_boundary/result_action_router/execution_contract +
Prime Directive discoverability) = 128/128 pass as of this task.
