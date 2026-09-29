# M7 Watcher Recovery Evidence

Requirement: handle watcher / L5DGVA restart, an already-present file,
transient filesystem errors, an incomplete or locked file, an interrupted
import, registry write failure and consumption failure -- with no duplicate
semantic consumption.

| Scenario | Mechanism | Test |
|---|---|---|
| Result already present at startup | `startup_scan()` -> registration from persisted wait state -> stability -> canonical import | `test_startup_scan_imports_pending_result`, `test_startup_scan_registers_a_waiting_task_that_has_no_registration`; **live**: REVIEW-003 (`M7_REVIEW_003_LIVE_INGESTION_EVIDENCE.md`) |
| Process restart | all state persisted; module reloaded as a fresh process; repeated startup scans + polls | `test_restart_preserves_idempotency` (1 registry row, 1 question) |
| Incomplete / mid-write file | stability evidence resets on any change; empty files never imported | `test_result_not_imported_until_stable`, `test_empty_file_is_never_imported` |
| Locked / vanished file | `TRANSIENT` (event `WATCH_TRANSIENT_ERROR`), retried next poll, not counted as an import attempt | covered by `_observe` |
| Interrupted import (state save fails after registry append) | state stays `RESULT_ACCEPTED`; next poll retries; `AUTO_IMPORT_FAILED_TRANSIENT` audited | `test_partial_import_recovery` |
| Registry write failure after the question was filed | question found by `question_key`, one row appended on retry | `test_registry_failure_recovery` |
| Consumption keeps failing | bounded attempts -> persisted `TERMINATION_POLICY_TRIGGERED` | `test_persistent_import_failure_terminates_and_is_never_a_pass` |
| Two pollers at once | per-task `ingestion.lock`; the import itself is under `import.lock` | `test_manual_ingestion_is_refused_while_the_task_ingestion_lock_is_held`, `test_concurrent_import_is_refused_with_no_side_effects` |
| Watcher stale / absent | heartbeat freshness -> `RECOVERABLE`; `ensure_watcher()` restarts; `STOPPED` via cooperative flag | `test_watcher_status_active_recoverable_stopped`, `test_watch_loop_imports_and_reports_a_fresh_heartbeat`, `test_stop_watcher_is_cooperative` |

## Real detached watcher process (controlled qualification)

`live_watcher_qual.py`, throwaway git repo, clearly synthetic task
`SYNTHETIC-LIVE-QUAL-001` (does not touch REVIEW-003; no Codex output is
fabricated; no import command is invoked anywhere in the script):

```
registered: True          ensure_watcher -> ACTIVE (real detached pid)
state before -> WAITING_FOR_HUMAN_TRANSPORT
result placed (the human's only act) ...  elapsed to CONSUMED: 2.0s
events: EXPECTED_RESULT_REGISTERED, WATCH_STARTED, RESULT_DETECTED, RESULT_STABILITY_CONFIRMED,
        RESULT_HASHED, AUTO_IMPORT_STARTED, RESULT_ACCEPTED, RESULT_CONSUMED,
        AUTO_RESUME_STARTED, NEXT_ACTION_RESOLVED
next_action -> AUTO_REMEDIATE_CONFIRMED_FINDINGS   stop decision -> AUTO_RUNNING / HUMAN_ACTION_REQUIRED=NO
watcher after stop -> STOPPED
```

## Honest gaps

- Cross-process *crash* mid-import was exercised by failure injection inside
  one process, not by killing a real OS process.
- The detached watcher is armed for the real REVIEW-004 arrival; that will be
  its first live-artifact qualification.
- Concurrency was tested with lock contention, not with a stress race.
