# M7 Result Quarantine and Retry

Code: `result_ingestion.py::_ingest_locked()`, `schedule_replay()`. Identity is
the SHA-256 of the file's bytes, recorded per task in `ingestion_state.json`
(`results[<sha>]`).

## Hash states

`IMPORT_STARTED` -> `CONSUMED` | `QUARANTINED`. A quarantined record persists
`TASK_ID`, `RESULT_SHA256`, `rejection_reason` (parse error or the validator
findings), `validation_findings`, `quarantined_at`, `retry_eligibility`.

## Rules (each has a test)

| Situation | Behaviour | Test |
|---|---|---|
| Same (task, sha) already consumed | `DUPLICATE_SUPPRESSED`, at-most-once consumption; logged once, not per poll | `test_same_hash_consumed_once` |
| Rejected hash seen again | not re-imported (import called exactly once over 10 polls); status `QUARANTINED`; next action resolved once | `test_rejected_hash_not_reimported_forever` |
| File content changes (new hash) | retried automatically -- the external author corrected the artifact | `test_changed_result_hash_can_retry_when_authorized` |
| Canonical remediation fixed the validator | `schedule_replay(task, sha, reason)` authorizes exactly one re-import, audited as `REPLAY_SCHEDULED`; re-quarantined if still rejected | `test_scheduled_replay_reimports_the_same_hash_exactly_once` |
| Manual `import` verb | authorized recovery: may re-import a quarantined hash, never a consumed one | `test_manual_import_of_a_valid_result_still_works_for_recovery` |
| Content changed AFTER consumption | `LATE_CHANGE_QUARANTINED` (`RESULT_CHANGED_AFTER_CONSUMPTION`), never re-consumed | `test_change_after_consumption_is_quarantined_not_reimported` |
| Consumed before ingestion records existed | reconciled, not re-consumed | `test_result_consumed_before_ingestion_records_existed_is_reconciled` |
| Forbidden / out-of-scope path | canonical validator rejects -> quarantined | `test_forbidden_path_result_rejected` |
| Persistent import failure | after `max_import_attempts` -> `INGESTION_TERMINATED`, persisted `TERMINATION_POLICY_TRIGGERED`; never a pass | `test_persistent_import_failure_terminates_and_is_never_a_pass` |

The external result is never rewritten, normalized or "repaired" to make it
validate. A rejection routes through the Next Action Resolver
(`AUTO_CLASSIFY_SCOPE_VIOLATION` etc.), not to a human scheduling prompt. Real
precedent: REVIEW-002 was rejected on a validator/handoff defect; after the
generic fix the unmodified file was re-imported (that manual replay predates
this module -- `schedule_replay()` is its automatic, audited equivalent).
