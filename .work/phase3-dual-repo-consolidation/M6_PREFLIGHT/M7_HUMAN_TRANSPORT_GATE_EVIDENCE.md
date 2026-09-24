# M7 Human Transport Gate Evidence

Real code: `dv_harness/execution_contract.py::human_transport_report()`,
`signals_from_model_handoff_state()`, `can_i_stop()`. Tests:
`test_human_transport_requires_stop`,
`test_human_transport_report_never_asks_human_to_decide_next_action`,
`test_signals_from_model_handoff_state_reports_transport_when_waiting`,
`test_transport_resume_restores_next_action`.

## Required report shape (verified byte-for-byte against real output)

```
STATE=WAITING_FOR_HUMAN_TRANSPORT
STOP_REASON=HUMAN_TRANSPORT_REQUIRED
TASK_ID
TARGET_MODEL
HANDOFF_FILE
EXPECTED_RESULT_FILE
IMPORT_COMMAND
NEXT_ACTION_AFTER_IMPORT=AUTO_RESUME
```

`human_transport_report()` always sets `NEXT_ACTION_AFTER_IMPORT=
AUTO_RESUME` -- the human is never asked to decide the post-import
action, matching the contract's own "Human moves the artifact; human
does not decide the post-import next action."

## Applied to the live M7-V1-CODEX-REVIEW-002 case (real output)

```
status: WAITING_FOR_HUMAN_TRANSPORT | stop_reason: HUMAN_TRANSPORT_REQUIRED | continue: False
task_id: M7-V1-CODEX-REVIEW-002 | target_model: codex
handoff_file: .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-002/HANDOFF_V1.md
expected_result_file: .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-002/RESULT_V1.md
import_command: python -m dv_harness.model_handoff_workflow import --task-id M7-V1-CODEX-REVIEW-002 --result-file .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-002/RESULT_V1.md --root .
```

Persisted for real to
`.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-002/execution_contract_state.json`
via `persist_stop()` -- a resuming caller reads this file back rather
than reconstructing the stop from conversation memory.

## Status

`HUMAN_TRANSPORT_GATE_STATUS=WIRED_TESTED_AND_APPLIED_TO_LIVE_CASE`.
