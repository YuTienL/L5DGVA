# L5DGVA Automatic External Result Ingestion Integration Prompt

## Mission

Adopt and implement:

`docs/architecture/canonical_detailed_governance/L5DGVA_AUTOMATIC_EXTERNAL_RESULT_INGESTION_REQUIREMENTS.md`

as the production-wiring completion of P6 and the Human Non-Scheduler
Execution Contract.

Target:

``` text
HUMAN_MANUAL_IMPORT_REQUIRED=NO
```

The human may transport HANDOFF/RESULT artifacts across a boundary. The
human must not need to invoke the Canonical import command merely to
progress the workflow.

Do not start M8 or later waves. Do not consume Reference USB. Do not
modify frozen Parent/v50/b7a/b7b/b8.

## 1. Preflight

Record PROCESS_CWD, REPO_ROOT, CURRENT_BRANCH, CURRENT_HEAD,
WORKING_TREE_STATUS.

Read completely: - Automatic External Result Ingestion Requirements; -
Human Non-Scheduler Execution Contract; - Result-Driven Autonomous
Closed-Loop Requirements; - Prime Directive V2/P6; - M7 handoff/result
workflow; - execution_contract.py and lifecycle persistence; - current
import/validation/consumption/replay logic; - registry/event
mechanisms; - current REVIEW-003 handoff/result state; - M6
non-regression contract.

Verify frozen sources unchanged.

## 2. Reconcile, Do Not Duplicate

Reuse the Canonical manual import implementation as the single ingestion
authority.

Do not create a second parser, validator, consumer, task state,
lifecycle engine, result registry or action router.

Required:

``` text
AUTO_IMPORT_PATH == CANONICAL_IMPORT_PATH
```

## 3. Register Expected Results

When a workflow stops for HUMAN_TRANSPORT_REQUIRED, persist:

``` text
TASK_ID
TARGET_MODEL
HANDOFF_FILE
EXPECTED_RESULT_FILE
EXPECTED_RESULT_CONTRACT
EXPECTED_PRODUCER
EXPECTED_TASK_TYPE
CURRENT_HEAD/APPLICABLE_CHECKPOINT
WAIT_STATE
CREATED_AT
```

Watch only registered expected results.

## 4. Implement Result Arrival Detection

Implement/reuse a lightweight watcher appropriate for the current
environment.

Requirements:

``` text
WATCH_ONLY_EXPECTED_RESULTS=YES
ARBITRARY_REPO_FILE_IMPORT=NO
```

Detect: - expected result creation; - authorized changed result
content; - result already present at watcher startup.

Do not require a specific filesystem library if a simpler reliable
implementation fits the repository.

## 5. File Stability

Before import prove the file is stable/readable and not mid-write.

Use configurable policy based on size/mtime/hash/readability or
equivalent.

Do not hard-code an arbitrary delay solely to pass tests.

Persist stability evidence where appropriate.

## 6. SHA-256 / Identity

Compute/persist:

``` text
TASK_ID
RESULT_PATH
RESULT_SHA256
IMPORT_ATTEMPT_ID
IMPORT_STATE
IMPORTED_AT
CONSUMED_AT
```

Use identity for duplicate suppression, replay, quarantine and audit.

## 7. Duplicate Suppression

Require:

``` text
SAME_TASK_ID + SAME_RESULT_SHA256
→ AT_MOST_ONE_ACCEPTED_SEMANTIC_CONSUMPTION
```

Repeated watcher events, restart/startup scan, recopy or metadata
changes must not duplicate consumption.

Reuse existing replay/idempotency foundations.

## 8. Auto Import

On stable, non-duplicate expected result invoke the same Canonical
ingestion function used by:

``` text
python -m dv_harness.model_handoff_workflow import ...
```

The CLI may remain for debug/recovery/replay, but normal transport must
not require it.

## 9. Validation

Preserve all current validation semantics. Watcher detection never
grants trust.

Validate Task ID, producer, task type, schema/version, read/write scope,
evidence, governance, expected output schema, returned artifacts and
parser protections as applicable.

## 10. Accepted Result

Required flow:

``` text
RESULT_DETECTED
→ STABILITY_CONFIRMED
→ HASHED
→ AUTO_IMPORT
→ VALIDATED
→ CONSUMED
→ PERSISTED
→ AUTO_RESUME
→ NEXT_ACTION_RESOLVER
```

After transport:

``` text
HUMAN_ACTION_REQUIRED=NO
```

unless a genuine HumanGate follows.

## 11. Rejected Result / Quarantine

Do not repeatedly re-import the same rejected hash.

Persist:

``` text
TASK_ID
RESULT_SHA256
REJECTION_REASON
VALIDATION_FINDINGS
QUARANTINE_STATE
RETRY_ELIGIBILITY
```

Then invoke Next Action Resolver.

Retry only on changed content/hash, explicitly scheduled replay after
Canonical remediation, or authorized recovery.

Never rewrite the external result.

## 12. Startup Pending Result Scan

Correctness must not require a continuously alive watcher.

On startup/resume:

``` text
LOAD PERSISTED WAIT STATES
→ FIND WAITING_FOR_HUMAN_TRANSPORT
→ CHECK EXPECTED_RESULT_FILE
→ IF PRESENT: STABILITY/IDENTITY/DUPLICATE CHECK
→ AUTO IMPORT
→ AUTO RESUME
```

## 13. Watcher Recovery

Test/reconcile: - process restart; - already-present file; - transient
filesystem error; - incomplete/locked file; - interrupted import; -
registry write failure; - consumption failure.

No duplicate semantic consumption.

## 14. Human Transport Semantics

Update/reconcile contract so HUMAN_TRANSPORT_REQUIRED means only
artifact transfer across an unavailable transport boundary.

It must not include: - invoking import; - telling Claude to continue; -
deciding whether to validate/fix; - triggering regression; - scheduling
re-review.

## 15. Direct Codex Write

If Codex is running in the same Canonical repo and the handoff permits
writing its result artifact, support the case where Codex writes
directly to EXPECTED_RESULT_FILE.

The watcher should detect it.

Do not grant Codex broader modification authority.

## 16. Security / Scope

Treat result as untrusted. Watch only registered paths. Protect against
unexpected traversal/symlink/path behavior according to existing policy.
Preserve forbidden precedence and Task Boundary.

Do not execute result content.

## 17. Concurrency

Support multiple pending handoffs safely.

Correlate by:

``` text
TASK_ID
EXPECTED_RESULT_FILE
EXPECTED_PRODUCER
RESULT_SHA256
```

Prove one task cannot resume another.

## 18. Audit Trace

Persist events equivalent to:

``` text
EXPECTED_RESULT_REGISTERED
WATCH_STARTED
RESULT_DETECTED
RESULT_STABILITY_CONFIRMED
RESULT_HASHED
DUPLICATE_SUPPRESSED
AUTO_IMPORT_STARTED
RESULT_ACCEPTED
RESULT_REJECTED
RESULT_QUARANTINED
RESULT_CONSUMED
AUTO_RESUME_STARTED
NEXT_ACTION_RESOLVED
```

## 19. Observability

Expose:

``` text
RESULT_WATCHER_STATUS
PENDING_EXTERNAL_RESULTS
EXPECTED_RESULT_FILE
LAST_DETECTED_RESULT_SHA256
AUTO_IMPORT_STATUS
QUARANTINE_STATUS
AUTO_RESUME_STATUS
NEXT_ACTION
HUMAN_ACTION_REQUIRED
```

Do not expose WAITING_FOR_USER_TO_IMPORT.

## 20. Live Qualification: REVIEW-003

Use the real:

``` text
TASK_ID=M7-V1-CODEX-REVIEW-003
EXPECTED_RESULT_FILE=.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-003/RESULT_V1.md
```

as the live qualification case where current timing/state permits.

Do not fabricate or edit Codex output.

If RESULT_V1 already exists, preserve it exactly and use the
startup/pending-result path or another controlled production-equivalent
qualification without asking the user to manually import.

If it does not exist yet, register the expected result, activate/recover
the watcher and stop only at HUMAN_TRANSPORT_REQUIRED. Once the real
result appears, ingestion must occur without a manual import command.

## 21. Anti-Drift Tests

Add behavioral tests equivalent to:

``` text
test_expected_result_registration
test_watcher_ignores_unregistered_files
test_result_not_imported_until_stable
test_same_hash_consumed_once
test_auto_import_uses_canonical_validator
test_valid_result_auto_consumes
test_valid_result_auto_resumes
test_rejected_hash_not_reimported_forever
test_changed_result_hash_can_retry_when_authorized
test_startup_scan_imports_pending_result
test_restart_preserves_idempotency
test_partial_import_recovery
test_registry_failure_recovery
test_multiple_pending_tasks_do_not_cross_resume
test_forbidden_path_result_rejected
test_manual_and_auto_import_share_ingestion_path
test_human_manual_import_not_required
```

## 22. M6 Non-Regression

Require:

``` text
M6_GOLDEN_PATH_PRESERVED=YES
STRUCTURAL_CONNECTED_STAGES=10/10
PRODUCTION_CONNECTED_STAGES=10/10
EVIDENCE_CONNECTED_STAGES=10/10
QUALIFIED_CONNECTED_STAGES=10/10
HITL_QUALIFICATION=PASS
```

## 23. Governance / Master Reconciliation

Place detailed requirement under canonical_detailed_governance, keep
CLAUDE.md compact, register task-scoped retrieval, and reconcile
P6/Human Non-Scheduler/M7/master capability and wave artifacts as
required.

Use structural CSV parsing; malformed rows=0, duplicate IDs=0, P0
ambiguity=0.

## 24. Required Artifacts

Produce/update in approved locations: -
`L5DGVA_AUTOMATIC_EXTERNAL_RESULT_INGESTION_ADOPTION_REPORT.md` -
`M7_EXPECTED_RESULT_REGISTRATION.md` -
`M7_RESULT_WATCHER_ARCHITECTURE.md` -
`M7_AUTO_IMPORT_AND_RESUME_EVIDENCE.md` -
`M7_RESULT_QUARANTINE_AND_RETRY.md` -
`M7_WATCHER_RECOVERY_EVIDENCE.md` -
`M7_REVIEW_003_LIVE_INGESTION_EVIDENCE.md` -
`M7_AUTOMATIC_RESULT_INGESTION_TEST_EVIDENCE.md`

Do not place reports in repo root.

## 25. Required Final State

Report honestly:

``` text
AUTOMATIC_EXTERNAL_RESULT_INGESTION=<status>
EXPECTED_RESULT_REGISTRATION=<status>
RESULT_ARRIVAL_WATCHER=<status>
RESULT_FILE_STABILITY_CHECK=<status>
RESULT_CONTENT_IDENTITY=<status>
DUPLICATE_RESULT_SUPPRESSION=<status>
AUTO_IMPORT=<status>
AUTO_VALIDATION=<status>
AUTO_CONSUMPTION=<status>
AUTO_RESUME=<status>
STARTUP_PENDING_RESULT_SCAN=<status>
RESULT_QUARANTINE=<status>
WATCHER_RECOVERY=<status>

HUMAN_MANUAL_IMPORT_REQUIRED=NO/YES
HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES/NO
HUMAN_IS_WORKFLOW_SCHEDULER=NO/YES

REVIEW_003_LIVE_QUALIFICATION=<status>
MANUAL_IMPORT_COMMAND_USED_FOR_LIVE_QUALIFICATION=YES/NO
DUPLICATE_SEMANTIC_CONSUMPTION=<count>
CURRENT_SCOPE_GAPS_OPEN=<count>
M6_GOLDEN_PATH_PRESERVED=YES/NO
UNKNOWN_REGRESSION_FAILURES=<count>
SOURCE_CAPABILITY_LOSS=<count>
REFERENCE_USB_ENV_CONSUMED=NO
```

## 26. Stop Policy

Proceed automatically through implementation, tests, regression,
watcher/startup-scan activation, and live qualification setup.

Do not stop to ask whether to continue.

Legitimate stops remain:

``` text
HUMAN_AUTHORITY_REQUIRED
HUMAN_TRANSPORT_REQUIRED
SAFE_EXECUTION_BLOCKED
TERMINATION_POLICY_TRIGGERED
TASK_COMPLETE
```

If REVIEW-003 still needs external Codex transport, stop with:

``` text
STATE=WAITING_FOR_HUMAN_TRANSPORT
STOP_REASON=HUMAN_TRANSPORT_REQUIRED
TASK_ID=M7-V1-CODEX-REVIEW-003
TARGET_MODEL=codex
HANDOFF_FILE=<path>
EXPECTED_RESULT_FILE=<path>
RESULT_WATCHER=ACTIVE_OR_RECOVERABLE
AUTO_IMPORT=ENABLED
AUTO_RESUME=ENABLED
HUMAN_ACTION_REQUIRED=Transport only
```

Do not tell the human to run the import command.

Do not start ChatGPT round trip automatically. Do not start M8. Do not
consume Reference USB.
