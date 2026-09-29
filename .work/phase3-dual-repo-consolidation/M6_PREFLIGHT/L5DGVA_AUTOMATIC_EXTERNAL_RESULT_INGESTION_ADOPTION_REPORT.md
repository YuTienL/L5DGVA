# L5DGVA Automatic External Result Ingestion -- Adoption Report

Sources read in full before any change:
`docs/architecture/canonical_detailed_governance/L5DGVA_AUTOMATIC_EXTERNAL_RESULT_INGESTION_REQUIREMENTS.md`
(platform requirement) and
`.work/prompts/L5DGVA_AUTOMATIC_EXTERNAL_RESULT_INGESTION_INTEGRATION_PROMPT.md`
(implementation / live-qualification contract). Extends P6 and the Human
Non-Scheduler Contract.

## Outcome in one paragraph

`HUMAN_MANUAL_IMPORT_REQUIRED=NO` is now code, not prose:
`dv_harness/result_ingestion.py` registers the expected result when a handoff
reaches `HUMAN_TRANSPORT_REQUIRED`, detects the returned file (poll / startup
scan / detached watcher), proves it stable, identifies it by SHA-256,
suppresses duplicates and quarantined hashes, and hands it to the one
canonical `model_handoff_workflow.import_result()`; then it resumes and
resolves the next action. The manual `import` verb still exists for
recovery/replay and now shares the same ingestion layer. A real external
Codex result (REVIEW-003) was ingested this way, unmodified, with no import
command.

## Capability status (honest)

| Capability | Status | Evidence |
|---|---|---|
| AUTOMATIC_EXTERNAL_RESULT_INGESTION | IMPLEMENTED, TESTED, LIVE (startup-scan path on a real result; watcher process on a synthetic task) | `M7_REVIEW_003_LIVE_INGESTION_EVIDENCE.md`, `M7_WATCHER_RECOVERY_EVIDENCE.md` |
| EXPECTED_RESULT_REGISTRATION | IMPLEMENTED, TESTED, LIVE (wired into `export_handoff`) | `M7_EXPECTED_RESULT_REGISTRATION.md` |
| RESULT_ARRIVAL_WATCHER | IMPLEMENTED, TESTED; process qualified on a synthetic task; armed for REVIEW-004 (first live-artifact arrival still to come) | `M7_RESULT_WATCHER_ARCHITECTURE.md` |
| RESULT_FILE_STABILITY_CHECK | IMPLEMENTED, TESTED, LIVE (3 observations / 2.0 s on REVIEW-003) | test evidence |
| RESULT_CONTENT_IDENTITY | IMPLEMENTED, TESTED, LIVE (SHA-256 in ingestion state + state.json + registry column) | remediation report N2 |
| DUPLICATE_RESULT_SUPPRESSION | IMPLEMENTED, TESTED | `M7_RESULT_QUARANTINE_AND_RETRY.md` |
| AUTO_IMPORT / AUTO_VALIDATION / AUTO_CONSUMPTION | IMPLEMENTED, TESTED, LIVE -- through the canonical path, no second engine | `M7_AUTO_IMPORT_AND_RESUME_EVIDENCE.md` |
| AUTO_RESUME | IMPLEMENTED, TESTED, LIVE (persist + resolve + replace stale stop; the *execution* of a resolved action is the agent session's, no in-harness runner) | same |
| STARTUP_PENDING_RESULT_SCAN | IMPLEMENTED, TESTED, LIVE | live evidence |
| RESULT_QUARANTINE | IMPLEMENTED, TESTED | quarantine doc |
| WATCHER_RECOVERY | IMPLEMENTED, TESTED (failure injection in-process; no real process kill) | recovery evidence |

## Reconciliations made

- **HUMAN_TRANSPORT_REQUIRED semantics.** `human_transport_report()` now asks
  only for transport (`HUMAN_ACTION_REQUIRED="Transport HANDOFF and ensure
  returned RESULT_V1 is placed at EXPECTED_RESULT_FILE"`, `RESULT_WATCHER`,
  `AUTO_IMPORT=ENABLED`, `AUTO_RESUME=ENABLED`); the previous `IMPORT_COMMAND`
  field is gone from the stop report; `WAITING_FOR_USER_TO_IMPORT` is an
  invalid stop reason. (Earlier evidence docs that quote `IMPORT_COMMAND` are
  superseded by this task.)
- **Governance registry.** The three requirement docs (Result-Driven Closed
  Loop, Human Non-Scheduler, this one) are registered `TASK_SCOPED`; the first
  two had never been registered in earlier tasks (registered retroactively).
  The requirement documents and their prompts, previously untracked, are now
  committed. CLAUDE.md carries one compact pointer.
- **No duplication.** No second parser, validator, consumer, registry, lifecycle
  or action router; one lock primitive shared with the workflow.

## Consequence for the live case

The ingested REVIEW-003 result was `FAIL` (N1 critical .. N6). The contract's
`AUTO_REMEDIATE_CONFIRMED_FINDINGS` ran to completion: reproduce -> RCA -> fix
-> 75 adversarial tests -> regression -> `M7-V1-CODEX-REVIEW-004` handoff
(`M7_CODEX_REVIEW_003_FINDINGS_REMEDIATION_REPORT.md`). The ingestion work
therefore did not end at "consumed": the Can-I-Stop gate correctly refused to
stop while auto-actionable work remained.

## Final state (see the completion report for the exact status lines)

`CURRENT_SCOPE_GAPS_OPEN` = GAP-V2-011/012/013 fixed-pending-independent-review
(3) + GAP-V2-014 (pre-existing, unrelated failing question-queue digest test;
reproduces at the M6 closure commit). No `UNKNOWN_REGRESSION_FAILURES`.
`REFERENCE_USB_ENV_CONSUMED=NO`. ChatGPT round trip and M8 not started.
