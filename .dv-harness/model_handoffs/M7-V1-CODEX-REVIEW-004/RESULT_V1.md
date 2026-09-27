# L5DGVA_MODEL_RESULT_V1

<!-- L5DGVA_VALUE_ENCODING=escaped-v1 -->

## RESULT_VERSION
1.0

## TASK_ID
M7-V1-CODEX-REVIEW-004

## PRODUCER_MODEL
codex

## TASK_TYPE
review-route

## RESULT_STATUS
FAIL

## CLAIMS
- CLAIM: Previous finding N1 is closed in the canonical result-field validator for the tested traversal, alias, symlink, and non-canonical declaration cases, but the new manual/shared ingestion front door introduces a separate path-trust bypass before that validator.
- CLAIM: Previous findings N2, N3, N4, and N5 are closed by content-digest identity, distinct empty-scalar encoding, strict document identity, and canonical boundary declarations respectively.
- CLAIM: Previous finding N6 is narrowed: exception NEXT_ACTION persistence and ordinary same-task serialization are implemented, but stale-lock takeover is not ownership-safe and cross-task registry writes are not globally serialized.
- CLAIM: The automatic watcher path is registered-path-only, stability checked, canonical-validator backed, hash deduplicated, quarantined on rejection, and task-correlated in the exercised regression suite.
- CLAIM: The ingestion capability is not qualified because recovery/manual callers can bypass expected-result registration, expected-path enforcement, symlink rejection, and stability observation.

## FINDINGS
- FINDING R004-1 (CRITICAL, NEW INGESTION BOUNDARY BYPASS): `ingest_result_file(root, task_id, path)` accepts an arbitrary caller-supplied path. `_ingest_locked` immediately follows `path.read_bytes()` and passes that same path to the canonical importer; it never verifies equality with `_expected_path(root, task_id)`, never requires an `expected_result.json` registration, and never applies `_observe`'s symlink, parent-directory, non-empty, or stability checks. The manual recovery verb exposes this unchecked path directly. A valid result for the named task can therefore be consumed from an unregistered location, including through a followed symlink where the platform permits it. A file can also be handed to the importer without the required two-snapshot quiet interval. The canonical result validator still checks TASK_ID, producer, task type, schema, and declared content scope, but those checks do not establish that the transported artifact is the registered expected file. This violates the requirements to watch/import registered expected results only and to never import a file while it may still be written.
- FINDING R004-2 (HIGH, NEW LOCK OWNERSHIP RACE): `_acquire_lock` treats age alone as proof that a holder is dead and unlinks a lock older than the stale timeout; it has no owner token, live-owner check, or heartbeat. `_release_lock` then blindly unlinks the pathname without proving ownership. INFERENCE: if a legitimate import exceeds the stale threshold, a second process can delete its live lock and acquire a replacement; when the first process exits, it can delete the second process's lock, admitting a third writer. The same primitive protects both import and ingestion locks, so the claimed single-writer property is time-bounded rather than invariant. Existing tests cover a synthetic stale file and an ordinary held lock, not live ownership across timeout.
- FINDING R004-3 (HIGH, NEW CROSS-TASK REGISTRY RACE): imports are serialized per task, but all tasks share `registry.csv`. `_append_registry` performs an unlocked check-then-append, and `_ensure_registry_schema` performs an unlocked read-all/write-fixed-`.migrate.tmp`/replace migration. INFERENCE: concurrent imports of different task IDs can both migrate or append the global registry, collide on the same migration temporary pathname, replace a file while another process appends, or observe stale contents and lose/corrupt rows. Per-task locks do not serialize this shared resource. This undermines crash consistency and the one-row-per-consumed-result audit invariant during concurrent pending handoffs.
- FINDING R004-4 (MEDIUM, NEW RECONCILIATION IDENTITY ERROR): when workflow state is already RESULT_CONSUMED but ingestion has no consumed entry, `_ingest_locked` labels the hash of the currently supplied file as CONSUMED without comparing it with the workflow state's `accepted_result_sha256`/`result_sha256` or the registry digest. If the file changed before first reconciliation, the replacement hash is recorded as consumed even though different bytes were actually consumed. The branch suppresses re-consumption, but corrupts ingestion identity and causes the genuine consumed hash to be misclassified on later arrival.

## EVIDENCE_REFS
- dv_harness/result_ingestion.py:299-316
- dv_harness/result_ingestion.py:319-410
- dv_harness/result_ingestion.py:454-492
- dv_harness/result_ingestion.py:495-517
- dv_harness/model_handoff_workflow.py:232-265
- dv_harness/model_handoff_workflow.py:317-386
- dv_harness/model_handoff_workflow.py:432-489
- dv_harness/model_handoff_workflow.py:591-606
- dv_harness_tests/test_result_ingestion.py:94-164
- dv_harness_tests/test_result_ingestion.py:235-443
- dv_harness_tests/test_model_handoff_review003_remediation.py
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-003/RESULT_V1.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_RESULT_WATCHER_ARCHITECTURE.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_RESULT_QUARANTINE_AND_RETRY.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_WATCHER_RECOVERY_EVIDENCE.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_RESULT_V1_CONTRACT.md
- docs/architecture/canonical_detailed_governance/L5DGVA_AUTOMATIC_EXTERNAL_RESULT_INGESTION_REQUIREMENTS.md

## COUNTER_EVIDENCE
- COUNTER_EVIDENCE: The automatic watcher enumerates registered pending tasks, derives each path with `_expected_path`, and applies `_observe`; `_observe` rejects a symlink, non-file, or resolved parent outside the task directory and requires repeated equal size, mtime, and SHA-256 snapshots across the configurable quiet interval.
- COUNTER_EVIDENCE: The canonical importer reads result bytes once and hashes the exact bytes it parses. State and registry retain the digest, and changed content conflicts with an already accepted digest. This closes previous N2 in the canonical import path.
- COUNTER_EVIDENCE: Current codec and parser tests exercise distinct `(empty)` and `(none)` values plus exact title/marker placement, supporting closure of N3 and N4.
- COUNTER_EVIDENCE: Current canonical-path tests cover dot-dot traversal, absolute/drive paths, case and trailing-dot aliases, existing symlink escape, governance references, own-result exemption, and non-canonical handoff declarations, supporting closure of N1 and N5 inside the validator.
- COUNTER_EVIDENCE: `import_result` persists `AUTO_RETRY_INTERRUPTED_IMPORT` after an exception and holds a per-task exclusive lock for the import. Tests cover interruption recovery, ordinary concurrent refusal, synthetic stale-lock recovery, and lock release after exception.
- COUNTER_EVIDENCE: The authorized regression execution completed with 284 passed and 2 platform-conditional skipped tests across all five ALLOWED_FILES test modules.

## UNKNOWN_ITEMS
- UNKNOWN: The two skipped tests are Windows-host platform conditionals; POSIX-only symlink/case behavior was not dynamically exercised in this environment.
- UNKNOWN: The initial test run using `C:\\tmp` produced 124 passes and 162 fixture setup errors because that directory was not writable. Per the handoff, this is an environment limitation, not a product defect; rerunning with an in-workspace pytest base temp completed successfully.
- UNKNOWN: The precise corrupt on-disk outcome of simultaneous cross-task registry migration/append depends on OS file-sharing semantics and timing. R004-3 is an INFERENCE from the unprotected shared read/replace/append sequence; no destructive race was injected into the canonical repository.
- UNKNOWN: The exact live-lock takeover schedule in R004-2 was not delayed for 120 seconds during this review. The race is an INFERENCE from the age-only unlink and owner-blind release operations.

## FILES_REFERENCED
- dv_harness/md_kv_codec.py
- dv_harness/model_handoff.py
- dv_harness/model_result.py
- dv_harness/model_handoff_workflow.py
- dv_harness/result_ingestion.py
- dv_harness/execution_contract.py
- dv_harness_tests/test_model_handoff_v1.py
- dv_harness_tests/test_model_handoff_review002_remediation.py
- dv_harness_tests/test_model_handoff_review003_remediation.py
- dv_harness_tests/test_result_ingestion.py
- dv_harness_tests/test_execution_contract.py
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-003/RESULT_V1.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_CODEX_REVIEW_003_FINDINGS_REMEDIATION_REPORT.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_REVIEW_003_LIVE_INGESTION_EVIDENCE.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_RESULT_WATCHER_ARCHITECTURE.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_RESULT_QUARANTINE_AND_RETRY.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_WATCHER_RECOVERY_EVIDENCE.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_RESULT_V1_CONTRACT.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_HANDOFF_V1_CONTRACT.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv
- docs/architecture/canonical_detailed_governance/L5DGVA_AUTOMATIC_EXTERNAL_RESULT_INGESTION_REQUIREMENTS.md

## VALIDATION_PERFORMED
- Read the complete REVIEW-004 handoff and independently inspected the authorized implementation, tests, previous result, remediation evidence, watcher/recovery design, contracts, gap register, and automatic-ingestion requirements.
- Re-derived previous findings N1-N6 against current code rather than accepting the remediation report or passing tests as dispositive.
- Traced automatic arrival from registered pending-task enumeration through expected-path derivation, stability snapshots, digesting, canonical import, quarantine/duplicate handling, resume, and NEXT_ACTION persistence.
- Traced the manual recovery route from its caller-supplied result path through the shared ingestion entry point and confirmed there is no registration, expected-path, symlink, or stability gate on that route.
- Reviewed consumed/quarantined hash state transitions, changed-during-import digest replacement, consumed-state reconciliation, and cross-task correlation.
- Reviewed lock acquisition, stale takeover, release, per-task lock scope, global registry append, and additive registry migration for ownership and crash/concurrency boundaries.
- Ran pytest with bytecode and pytest cache writes disabled over all five authorized test modules. The successful in-workspace run produced 284 passed and 2 skipped in 267.98 seconds.
- Preserved the existing REVIEW-003 result unchanged, modified no production file, performed no fix, and did not invoke the L5DGVA import command.

## RECOMMENDED_ACTIONS
- Make `ingest_result_file` fail closed unless the task has a valid registration and the supplied path is the canonical registered expected path. Apply the same symlink, resolved-parent, regular-file, non-empty, and stability policy to manual/recovery ingestion, with any deliberate override explicit, separately authorized, and audited.
- Replace age-only lock stealing with ownership-aware leases: persist a unique token and owner metadata, refresh or prove liveness before takeover, and unlink only when the on-disk token still belongs to the releaser.
- Serialize all `registry.csv` schema migration and row append operations with a single registry-scoped lock and ownership-safe atomic protocol; use unique same-directory temporary files and fsync/replace durability appropriate to both Windows and POSIX.
- During ingestion reconciliation, compare the workflow and registry consumed digest to the observed hash. Record the persisted consumed digest as CONSUMED and quarantine a differing observed hash rather than relabeling it.
- Add adversarial tests for arbitrary/manual unregistered paths, manual symlink paths, manual partial-write bypass, live-lock timeout takeover with owner-safe release, concurrent different-task registry writes/migration, and changed-file reconciliation against the persisted consumed digest.

## HUMAN_DECISIONS_REQUIRED
(none)

## SCOPE_EXCEPTIONS
(none)

## RETURNED_ARTIFACTS
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-004/RESULT_V1.md
