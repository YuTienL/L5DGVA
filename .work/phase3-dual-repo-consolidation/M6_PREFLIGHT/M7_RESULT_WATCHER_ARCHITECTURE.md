# M7 Result Watcher Architecture

Code: `dv_harness/result_ingestion.py`. **Not a second ingestion engine**: the
module owns only detection, stability, identity, duplicate/quarantine
suppression and resume. Every import -- automatic or manual -- ends in
`model_handoff_workflow.import_result()`, the single parser / validator /
consumer / registry / replay authority (`AUTO_IMPORT_PATH == CANONICAL_IMPORT_PATH`;
`test_manual_and_auto_import_share_ingestion_path` spies both layers).

```
export_handoff -> register_expected_result           (WAITING_FOR_HUMAN_TRANSPORT)
poll_once / startup_scan / watch loop
  per registered pending task, under ingestion.lock:
    _observe: ABSENT | UNSAFE | TRANSIENT | OBSERVING | STABLE
    STABLE -> ingest_result_file()  (the SAME entry point the manual verb uses)
                sha256 -> duplicate/quarantine decision -> import_result()  [canonical]
                -> CONSUMED | QUARANTINED record -> resume_after_import()
```

## Design decisions

- **No filesystem-event library.** The semantic contract is a persisted poll;
  stat + hash + read are portable, restartable and testable with an injected
  clock. The watcher is just `poll_once()` in a loop with a heartbeat.
- **Correctness does not depend on the watcher being alive.** All state is
  persisted (`expected_result.json`, `ingestion_state.json`,
  `ingestion_events.jsonl`); `startup_scan()` or a fresh watcher resumes
  anywhere. Watcher status is `ACTIVE` (fresh heartbeat), `RECOVERABLE`
  (absent/stale -- `ensure_watcher()` restarts it) or `STOPPED` (cooperative
  flag file, no process is killed).
- **Stability is evidence, not a delay.** Identical (size, mtime_ns, SHA-256)
  across >= `min_observations` observations spanning >= `quiet_seconds`, on a
  readable non-empty file; a change resets the evidence; evidence persists
  across restarts. Policy is configurable
  (`.dv-harness/result_ingestion_policy.json`); the 2.0 s default is a
  documented conservative starting point, and a mid-write import is
  self-correcting anyway (partial content is rejected, its hash quarantined,
  the completed file has a new hash and is retried).
- **Detection never grants trust.** A detected file is only ever handed to the
  canonical validator; content is never executed or rewritten; symlinks,
  non-files and paths whose parent is not the task directory are `UNSAFE`
  and never followed.
- **Single writer per task.** `ingestion.lock` (watcher / manual front door)
  and, inside the workflow, `import.lock` (any importer) use one O_EXCL
  primitive with stale-lock recovery. Bounded automatic attempts per hash
  (`max_import_attempts`, default 5) end in `TERMINATION_POLICY_TRIGGERED`
  (persisted stop), never a silent pass.
- **Observability** (`status_report()`, `python -m dv_harness.result_ingestion status`):
  `RESULT_WATCHER_STATUS`, `PENDING_EXTERNAL_RESULTS`, and per task
  `EXPECTED_RESULT_FILE`, `LAST_DETECTED_RESULT_SHA256`, `AUTO_IMPORT_STATUS`,
  `QUARANTINE_STATUS`, `AUTO_RESUME_STATUS`, `NEXT_ACTION`,
  `HUMAN_ACTION_REQUIRED`. "Waiting for user to import" does not exist as a
  state and is an invalid stop reason.
- **Watcher process.** `ensure_watcher()` starts a detached
  `python -m dv_harness.result_ingestion watch`; it exits after
  `idle_exit_seconds` with nothing pending, and `export` re-ensures it. The
  test-suite sets `L5DGVA_RESULT_WATCHER=off` (conftest) so tests never leave
  background processes.
- **Direct write by the external model** at `EXPECTED_RESULT_FILE` uses the
  same detection path and grants the writer no extra authority
  (`test_direct_write_by_the_external_model_*`).

## Honest status

`RESULT_ARRIVAL_WATCHER=IMPLEMENTED_TESTED_QUALIFIED_ON_SYNTHETIC_TASK`;
armed for the next real arrival (REVIEW-004). See
`M7_WATCHER_RECOVERY_EVIDENCE.md`.
