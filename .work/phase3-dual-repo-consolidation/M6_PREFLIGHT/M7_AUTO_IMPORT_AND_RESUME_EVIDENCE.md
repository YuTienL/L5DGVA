# M7 Auto Import and Resume Evidence

## Required flow (each step is a persisted, tested event)

```
RESULT_DETECTED -> RESULT_STABILITY_CONFIRMED -> RESULT_HASHED -> AUTO_IMPORT_STARTED
-> (canonical validators) -> RESULT_ACCEPTED -> RESULT_CONSUMED
-> AUTO_RESUME_STARTED -> NEXT_ACTION_RESOLVED
```

Tests: `test_result_not_imported_until_stable`, `test_auto_import_uses_canonical_validator`,
`test_valid_result_auto_consumes`, `test_valid_result_auto_resumes`,
`test_human_decision_result_resumes_into_a_real_authority_stop`,
`test_human_manual_import_not_required`.

## Resume semantics

`resume_after_import()` reads the `next_action.json` the canonical import
persisted, logs `NEXT_ACTION_RESOLVED`, and REPLACES the stale
`WAITING_FOR_HUMAN_TRANSPORT` stop with the real decision through
`execution_contract.can_i_stop()`:

| Consumed result | NEXT_ACTION | Persisted stop |
|---|---|---|
| FAIL / PARTIAL | `AUTO_REMEDIATE_CONFIRMED_FINDINGS` | `AUTO_RUNNING`, `HUMAN_ACTION_REQUIRED=NO` |
| PASS / other clean | `EVALUATE_CANONICAL_TASK_COMPLETION` | `AUTO_RUNNING` |
| `HUMAN_DECISION_REQUIRED` | `HUMAN_AUTHORITY_REQUIRED` | `WAITING_FOR_HUMAN_AUTHORITY` (real question filed) |
| rejected | `AUTO_CLASSIFY_SCOPE_VIOLATION` / `AUTO_DIAGNOSE_VALIDATION_FAILURE` / `AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF` | `AUTO_RUNNING` |
| interrupted import | `AUTO_RETRY_INTERRUPTED_IMPORT` | `AUTO_RUNNING` |

## What "auto resume" does and does not mean (honest)

L5DGVA persists the resolved next action and moves the task to `AUTO_RUNNING`
without asking anyone. The harness itself has no autonomous remediation
executor: the *execution* of `AUTO_REMEDIATE_CONFIRMED_FINDINGS` is performed
by the working agent session, which finds the work item in `next_action.json` /
`status_report()` without a human telling it to continue. That is exactly what
happened for REVIEW-002 and REVIEW-003 (remediation began with no scheduling
prompt). `AUTO_RESUME=IMPLEMENTED_TESTED_LIVE`; an in-harness remediation
runner is out of scope for this capability.

## Live evidence

REVIEW-003: `M7_REVIEW_003_LIVE_INGESTION_EVIDENCE.md`. Real detached watcher
process on a synthetic task: 2.0 s from placement to `RESULT_CONSUMED` with
events `EXPECTED_RESULT_REGISTERED, WATCH_STARTED, RESULT_DETECTED,
RESULT_STABILITY_CONFIRMED, RESULT_HASHED, AUTO_IMPORT_STARTED, RESULT_ACCEPTED,
RESULT_CONSUMED, AUTO_RESUME_STARTED, NEXT_ACTION_RESOLVED`,
`next_action=AUTO_REMEDIATE_CONFIRMED_FINDINGS`, stop decision `AUTO_RUNNING /
HUMAN_ACTION_REQUIRED=NO`, no import command.
