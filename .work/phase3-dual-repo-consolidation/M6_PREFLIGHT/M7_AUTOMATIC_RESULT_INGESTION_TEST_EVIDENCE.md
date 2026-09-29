# M7 Automatic Result Ingestion Test Evidence

`dv_harness_tests/test_result_ingestion.py`: **36 tests, all pass.** Every
test drives the real workflow against a throwaway git repository (real
`build_handoff` / `export_handoff` / `import_result` / validator / registry /
question queue); nothing about the parser, validator or consumer is mocked. Time
is injected (`poll_once(now=...)`) so stability is exercised without sleeping.

## The 17 required names (all present verbatim)

| Required test | Verifies |
|---|---|
| `test_expected_result_registration` | registration record has all 10 fields, idempotent, event logged |
| `test_watcher_ignores_unregistered_files` | stray result in an unregistered task dir, repo root, arbitrary `.md`: never imported |
| `test_result_not_imported_until_stable` | 2 observations < quiet interval not enough; a content change resets evidence; import only when stable; event order DETECTED < STABILITY < HASHED < IMPORT_STARTED |
| `test_same_hash_consumed_once` | recopy/rescan/direct re-ingest: 1 registry row, 1 question, RESULT_CONSUMED once, DUPLICATE_SUPPRESSED logged once |
| `test_auto_import_uses_canonical_validator` | spy on `wf.import_result` called once with the expected path; the canonical TASK_ID check rejects a wrong-task result |
| `test_valid_result_auto_consumes` | CONSUMED record with import_attempt_id, consumed_at, registry row, pending list empty |
| `test_valid_result_auto_resumes` | next action AUTO_REMEDIATE, stale transport stop replaced by AUTO_RUNNING / HUMAN_ACTION_REQUIRED=NO |
| `test_rejected_hash_not_reimported_forever` | 10 polls -> import called once; QUARANTINED with reason/findings/retry eligibility |
| `test_changed_result_hash_can_retry_when_authorized` | corrected content (new hash) consumed automatically |
| `test_startup_scan_imports_pending_result` | file present before any watcher -> consumed |
| `test_restart_preserves_idempotency` | fresh module reload + repeated scans: 1 row, 1 question |
| `test_partial_import_recovery` | state save fails -> ACCEPTED, then retried to CONSUMED, 1 row |
| `test_registry_failure_recovery` | registry down after the question was filed -> 1 question, 1 row on retry |
| `test_multiple_pending_tasks_do_not_cross_resume` | B's result at A's path rejects A only; B untouched; then B's own file consumes B only |
| `test_forbidden_path_result_rejected` | forbidden path -> rejected, never consumed |
| `test_manual_and_auto_import_share_ingestion_path` | spies show AUTO -> CANONICAL and MANUAL -> same two layers; manual on a consumed hash is a suppressed duplicate |
| `test_human_manual_import_not_required` | export -> file placed -> polls: CONSUMED, resumed, `HUMAN_ACTION_REQUIRED=NO`; no `IMPORT_COMMAND`; "waiting for user to import" never appears |

Plus: symlinked result never followed, empty file never imported, conflicting
expected paths, unsafe task id, scheduled replay exactly once, change after
consumption quarantined, legacy-consumed reconcile, persistent failure ->
`TERMINATION_POLICY_TRIGGERED`, watcher status/heartbeat/stop, direct write by
the external model, configurable policy, `WAITING_FOR_USER_TO_IMPORT` invalid.

## Negative controls (do the tests actually bite?)

Four deliberate mutations of `result_ingestion.py`, each restored afterwards
(byte-identical diff verified):

| Mutation | Tests that failed |
|---|---|
| ignore stability | `test_result_not_imported_until_stable`, `test_partial_import_recovery` |
| no quarantine suppression | `test_auto_import_uses_canonical_validator`, `test_rejected_hash_not_reimported_forever`, `test_scheduled_replay_*` |
| no consumed-duplicate suppression | `test_same_hash_consumed_once`, `test_manual_and_auto_import_share_ingestion_path` |
| watch every task directory instead of registrations | `test_watcher_ignores_unregistered_files` + 4 more |

For the REVIEW-003 fixes: mutations of lexical-only scope, no digest conflict,
and no empty token each fail their tests; `test_nonexistent_traversal_*`
isolates the canonical-path layer from the real-filesystem layer.

## Suites run on the final code

| Suite | Tests |
|---|---|
| `test_result_ingestion.py` | 36 |
| `test_model_handoff_review003_remediation.py` | 75 |
| `test_model_handoff_review002_remediation.py` | 76 |
| `test_execution_contract.py` | 47 |
| `test_model_handoff_v1.py` | 51 |
| `test_result_action_router.py` | 30 |
| (six files above, collected) | 316 |
| + governance registry, claude reference graph, Prime Directive discoverability | 341 passed together (author run before the final +1 test) |

Broader non-regression on the final code (`-k` selections over all of `dv_harness_tests`):

| Selection | Result |
|---|---|
| `m6 or task_boundary or question_queue or golden` (M6 golden path, Task Boundary, HITL/question queue) | **433 passed, 1 failed** (GAP-V2-014, pre-existing, below) |
| that plus `handoff or ingestion or execution_contract or result_action or governance_registry or constitution` | **778 passed, 1 failed** (the same single test) |

M6 stage-connectivity metrics (`10/10` structural / production / evidence /
qualified, `HITL_QUALIFICATION=PASS`) rest on the M6 tests inside these
selections, all passing; this task adds no M6 call site and modifies no M6
module (`question_queue.py`, `task_boundary_conformance.py`, `engine.py`,
`cli.py` untouched).

Constitution gate PASS; frozen Parent / v50 / b7a / b7b / b8 unchanged.

## Known unrelated failure (not counted as a regression)

`test_question_queue_digest_auto_trigger.py::test_digest_fires_after_a_real_gate_verified_stage_pass`
fails identically at the M6 closure commit `fb846e1` and before any M7 change
(GAP-V2-014, owner: a dedicated question-queue task). It is the only failure in
the broader M6/M7 selection.
