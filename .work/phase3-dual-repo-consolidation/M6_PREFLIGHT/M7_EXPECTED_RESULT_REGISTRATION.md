# M7 Expected Result Registration

Code: `dv_harness/result_ingestion.py::register_expected_result()`, called by
`model_handoff_workflow.export_handoff()` the moment a handoff reaches
`WAITING_FOR_HUMAN_TRANSPORT`. Tests: `test_expected_result_registration`,
`test_two_pending_tasks_claiming_one_expected_path_is_a_conflict`,
`test_unsafe_task_id_is_rejected`,
`test_startup_scan_registers_a_waiting_task_that_has_no_registration`.

## Persisted record

`.dv-harness/model_handoffs/<task_id>/expected_result.json`:

```
TASK_ID, TARGET_MODEL, HANDOFF_FILE, EXPECTED_RESULT_FILE,
EXPECTED_RESULT_CONTRACT (= handoff EXPECTED_OUTPUT_SCHEMA),
EXPECTED_PRODUCER (= target model), EXPECTED_TASK_TYPE,
CURRENT_HEAD (= handoff head), WAIT_STATE, CREATED_AT
```

Real example: `M7-V1-CODEX-REVIEW-003/expected_result.json`
(`EXPECTED_RESULT_FILE=.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-003/RESULT_V1.md`,
`EXPECTED_PRODUCER=codex`, `EXPECTED_TASK_TYPE=review-route`).

## Rules

- **Only registered paths are watched.** `list_pending()` reads registrations,
  never a Markdown scan (`test_watcher_ignores_unregistered_files`: a result
  planted in an unregistered task directory, at the repo root, and an
  arbitrary `notes.md` are all ignored and never change state).
- The path is derived (`<task_dir>/RESULT_V1.md`), never taken from the result.
  A task id that could traverse (`../x`) is rejected (`UNSAFE_TASK_ID`).
- Registration is idempotent; two pending tasks claiming one expected path is
  `EXPECTED_RESULT_FILE_CONFLICT`.
- Correlation for concurrency is TASK_ID + EXPECTED_RESULT_FILE +
  EXPECTED_PRODUCER + RESULT_SHA256: the canonical validator enforces task id
  and producer, the per-task directory enforces the path, the digest identifies
  the content (`test_multiple_pending_tasks_do_not_cross_resume`,
  `test_wrong_producer_cannot_resume_the_task`).
- Startup/resume registers any persisted `WAITING_FOR_HUMAN_TRANSPORT` task
  that lacks a registration (e.g. exported before this capability existed) from
  its own stored handoff. REVIEW-003 and `M7-V1-CHATGPT-DECISION-001` were
  registered this way. Registration means "watch this path"; it does not start
  any round trip.
