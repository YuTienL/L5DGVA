# L5DGVA Automatic External Result Ingestion Requirements

## Purpose

Platform-level requirement completing P6 and the Human Non-Scheduler
Contract for human-mediated external-model transport.

> The human may transfer HANDOFF/RESULT artifacts across an external
> boundary, but shall not be required to invoke the next workflow
> command. Once an expected RESULT appears, L5DGVA detects, stabilizes,
> identifies, imports, validates, consumes/rejects, persists,
> auto-resumes, and resolves the next action.

``` text
AUTOMATIC_EXTERNAL_RESULT_INGESTION=REQUIRED
HUMAN_MANUAL_IMPORT_REQUIRED=NO
HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES
HUMAN_IS_WORKFLOW_SCHEDULER=NO
```

## Target UX

At transport stop:

``` text
STATE=WAITING_FOR_HUMAN_TRANSPORT
STOP_REASON=HUMAN_TRANSPORT_REQUIRED
TASK_ID=<task>
TARGET_MODEL=<model>
HANDOFF_FILE=<path>
EXPECTED_RESULT_FILE=<path>
HUMAN_ACTION_REQUIRED=Transport HANDOFF and ensure returned RESULT_V1 is placed at EXPECTED_RESULT_FILE
RESULT_WATCHER=ACTIVE_OR_RECOVERABLE
AUTO_IMPORT=ENABLED
AUTO_RESUME=ENABLED
```

The user does not run
`python -m dv_harness.model_handoff_workflow import ...` in the normal
flow.

## Canonical Flow

``` text
WAITING_FOR_HUMAN_TRANSPORT
→ EXPECTED RESULT REGISTERED
→ RESULT FILE APPEARS
→ FILE STABILITY CHECK
→ RESULT SHA256
→ DUPLICATE CHECK
→ CANONICAL AUTO IMPORT
→ VALIDATION
→ CONSUMPTION or REJECTION
→ PERSIST
→ AUTO RESUME
→ NEXT ACTION RESOLVER
```

## Required Capability Family

``` text
AUTOMATIC_EXTERNAL_RESULT_INGESTION
EXPECTED_RESULT_REGISTRATION
RESULT_ARRIVAL_WATCHER
RESULT_FILE_STABILITY_CHECK
RESULT_CONTENT_IDENTITY
DUPLICATE_RESULT_SUPPRESSION
AUTO_IMPORT
AUTO_VALIDATION
AUTO_CONSUMPTION
AUTO_RESUME
STARTUP_PENDING_RESULT_SCAN
RESULT_QUARANTINE
WATCHER_RECOVERY
RESULT_ARRIVAL_AUDIT_TRACE
```

Reuse existing M7 handoff workflow, execution contract, lifecycle
persistence, registry, replay/idempotency and validators. No competing
engines.

## Expected Result Registration

When a handoff reaches HUMAN_TRANSPORT_REQUIRED persist:

``` text
TASK_ID
TARGET_MODEL
HANDOFF_FILE
EXPECTED_RESULT_FILE
EXPECTED_RESULT_CONTRACT
EXPECTED_PRODUCER
EXPECTED_TASK_TYPE
CURRENT_HEAD / applicable checkpoint
WAIT_STATE
CREATED_AT
```

Watch only registered expected results; never scan arbitrary Markdown as
external results.

## Result Arrival Watcher

Observe registered pending result paths only. Detect creation,
authorized changed content, and files already present when watcher
starts.

The semantic contract must not depend on a particular filesystem
library.

## File Stability

Never import a file while it may still be written.

Use evidence such as stable size/mtime/hash, readability and
configurable quiet interval:

``` text
FILE_APPEARS → SNAPSHOT_A → STABILITY_INTERVAL → SNAPSHOT_B
→ A==B → READY_FOR_IMPORT
```

Do not hard-code an arbitrary interval merely for closure.

## Content Identity

Prefer SHA-256 and persist:

``` text
TASK_ID
RESULT_PATH
RESULT_SHA256
IMPORT_ATTEMPT_ID
IMPORT_STATE
IMPORTED_AT
CONSUMED_AT
```

## Duplicate Suppression

``` text
SAME_TASK_ID + SAME_RESULT_SHA256
→ AT_MOST_ONE_ACCEPTED_SEMANTIC_CONSUMPTION
```

Repeated watcher events, restart, recopy, or startup scan must not
duplicate consumption.

## Canonical Auto Import

Automatic import must call the same Canonical
ingestion/validation/consumption path as manual import:

``` text
AUTO_IMPORT_PATH == CANONICAL_IMPORT_PATH
```

Manual import may remain for recovery/debug/replay, but is not required
for normal transport.

## Validation

Preserve all current checks as applicable: Task ID, producer, task type,
schema/version, read/write scope, EvidenceRefs, governance
refs/NOT_APPLICABLE semantics, expected output schema, returned
artifacts, parser-fidelity protections.

Detection never implies trust.

## Accepted Result

``` text
DETECTED → STABLE → IMPORTED → VALIDATED → CONSUMED
→ PERSISTED → AUTO_RESUME → NEXT_ACTION_RESOLVER
```

After transport completes, HUMAN_ACTION_REQUIRED=NO unless the result
reaches a genuine HumanGate.

## Rejected Result / Quarantine

Avoid infinite re-import loops:

``` text
DETECTED → IMPORT ATTEMPT → RESULT_REJECTED
→ QUARANTINE/REJECTED_HASH_STATE → NEXT_ACTION_RESOLVER
```

Persist TASK_ID, RESULT_SHA256, rejection reason, validation findings,
quarantine state and retry eligibility.

Same rejected hash is not retried automatically until content changes,
Canonical remediation explicitly schedules replay, or authorized
recovery requests it.

Never rewrite external input to make it valid.

## Auto Resume

``` text
AUTO_RESUME_AFTER_RESULT_IMPORT=YES
```

Accepted PASS may close/reconcile and advance. FAIL+auto-actionable
routes to autonomous remediation. HUMAN_DECISION_REQUIRED routes to
Human Authority. Required external re-review prepares a new handoff and
stops only for Human Transport.

No generic continue prompt.

## Startup Pending Result Scan

Continuous watcher uptime is not required for correctness:

``` text
STARTUP/RESUME
→ LOAD WAIT STATES
→ FIND WAITING_FOR_HUMAN_TRANSPORT
→ CHECK EXPECTED_RESULT_FILE
→ IF PRESENT: STABILITY/IDENTITY/DUPLICATE CHECK
→ AUTO IMPORT
→ AUTO RESUME
```

## Watcher Recovery

Handle watcher/L5DGVA restart, already-present file, transient
filesystem error, incomplete/locked file, interrupted import, registry
failure and consumption failure while preserving idempotency.

## Human Transport Definition

`HUMAN_TRANSPORT_REQUIRED` means the human must transfer an artifact
across a boundary L5DGVA cannot cross itself.

It does not mean invoke import, decide whether to validate, tell Claude
to continue/fix, trigger regression, or schedule re-review.

## Direct Codex File Write

If Codex works in the same Canonical repo and the handoff authorizes
writing its result artifact, it may write directly to
EXPECTED_RESULT_FILE. L5DGVA then detects it. This does not make Codex
orchestrator or Source of Truth.

## Security / Scope

Watch registered paths only; never execute returned content; treat text
as untrusted; use Canonical validators; preserve Task Boundary/scope and
forbidden precedence; reject unexpected traversal/symlink behavior per
existing policy.

## Concurrency

Multiple pending handoffs must correlate by TASK_ID,
EXPECTED_RESULT_FILE, EXPECTED_PRODUCER and RESULT_SHA256. One result
must never resume another task.

## Atomicity

No consumed state before mandatory validation; no duplicate accepted
registry row; no contradictory wait/consumed states; safe retry after
partial failure. Reuse M7 crash-safety work.

## Audit Trace

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

## Observability

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

Never expose "waiting for user to import".

## Current Live Qualification Case

Use `M7-V1-CODEX-REVIEW-003` and its real expected result where
feasible. Do not fabricate Codex output. If already present, use it
unchanged.

Qualification must prove that after the real file is placed at the
expected path, no manual import command is required.

## Anti-Drift Tests

Require behavioral tests equivalent to:

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

## Governance Placement

Detailed requirements live under
`docs/architecture/canonical_detailed_governance/`. Keep CLAUDE.md
compact and register task-scoped retrieval for external-result
transport/ingestion, Human Non-Scheduler, P6 and multi-model review.

## Required Invariants

``` text
AUTOMATIC_EXTERNAL_RESULT_INGESTION=REQUIRED
EXPECTED_RESULT_REGISTRATION=REQUIRED
RESULT_ARRIVAL_WATCHER=REQUIRED
RESULT_FILE_STABILITY_CHECK=REQUIRED
RESULT_CONTENT_IDENTITY=REQUIRED
DUPLICATE_RESULT_SUPPRESSION=REQUIRED
AUTO_IMPORT=REQUIRED
AUTO_VALIDATION=REQUIRED
AUTO_CONSUMPTION=REQUIRED
AUTO_RESUME=REQUIRED
STARTUP_PENDING_RESULT_SCAN=REQUIRED
RESULT_QUARANTINE=REQUIRED
WATCHER_RECOVERY=REQUIRED
HUMAN_MANUAL_IMPORT_REQUIRED=NO
HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES
HUMAN_IS_WORKFLOW_SCHEDULER=NO
```

## Qualification

Operational only when real evidence proves:

``` text
HANDOFF_READY
→ HUMAN_TRANSPORT_REQUIRED
→ REAL RESULT ARRIVES
→ WATCHER/STARTUP SCAN DETECTS
→ STABILITY CHECK
→ SHA256
→ AUTO IMPORT
→ CANONICAL VALIDATION
→ CONSUMPTION or REJECTION
→ PERSIST
→ AUTO RESUME
→ NEXT ACTION RESOLVER
```

without human import invocation.

Also prove duplicate suppression, quarantine, restart recovery, no
cross-task confusion, and M6 Golden Path preservation.

## Final Objective

> For human-mediated external-model workflows, the human transports the
> artifact across the boundary. L5DGVA detects its return, imports it,
> validates it, consumes/rejects it, resumes the workflow, and selects
> the next action automatically.
