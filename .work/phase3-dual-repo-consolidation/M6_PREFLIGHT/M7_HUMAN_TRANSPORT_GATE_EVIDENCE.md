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

## Addendum: REVIEW-003 (live output, this task)

```
STATE=WAITING_FOR_HUMAN_TRANSPORT
STOP_REASON=HUMAN_TRANSPORT_REQUIRED
TASK_ID=M7-V1-CODEX-REVIEW-003
TARGET_MODEL=codex
HANDOFF_FILE=.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-003/HANDOFF_V1.md
EXPECTED_RESULT_FILE=.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-003/RESULT_V1.md
IMPORT_COMMAND=python -m dv_harness.model_handoff_workflow import --task-id M7-V1-CODEX-REVIEW-003 --result-file .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-003/RESULT_V1.md --root .
NEXT_ACTION_AFTER_IMPORT=AUTO_RESUME
```

Superseded stop: `M7-V1-CODEX-REVIEW-002` is now `COMPLETE/TASK_COMPLETE`
(result consumed, findings remediated, successor issued).

## Addendum: transport semantics after Automatic External Result Ingestion (REVIEW-004 live output)

`HUMAN_TRANSPORT_REQUIRED` now means only that the human moves an artifact
across a boundary L5DGVA cannot cross; it never means "run the import command".
The `IMPORT_COMMAND` field quoted in the sections above is superseded (removed
from the stop report; the manual verb remains only for recovery/replay).
Real output of the production `export` verb for the current stop:

```
STATE=WAITING_FOR_HUMAN_TRANSPORT
STOP_REASON=HUMAN_TRANSPORT_REQUIRED
TASK_ID=M7-V1-CODEX-REVIEW-004
TARGET_MODEL=codex
HANDOFF_FILE=.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-004/HANDOFF_V1.md
EXPECTED_RESULT_FILE=.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-004/RESULT_V1.md
HUMAN_ACTION_REQUIRED=Transport HANDOFF and ensure returned RESULT_V1 is placed at EXPECTED_RESULT_FILE
RESULT_WATCHER=ACTIVE
AUTO_IMPORT=ENABLED
AUTO_RESUME=ENABLED
```
