# L5DGVA_MODEL_RESULT_V1

<!-- L5DGVA_VALUE_ENCODING=escaped-v1 -->

## RESULT_VERSION
1.0

## TASK_ID
M7-V1-CODEX-REVIEW-005

## PRODUCER_MODEL
codex

## TASK_TYPE
review-route

## RESULT_STATUS
FAIL

## CLAIMS
- CLAIM: R004-1 is narrowed, not closed. Default ingestion now rejects an absent registration, arbitrary path, symlink, empty file, and a write that changes during the synchronous observation interval; the AUTO watcher remains functional and `allow_unregistered_path=True` is the explicit path-gate override. However, the quiet-interval algorithm can consume a valid intermediate document from a slow writer that pauses longer than the interval, and registration content is not authenticated.
- CLAIM: R004-2 is not closed. Token-matched release prevents the originally reported owner-blind release in the ordinary sequential case, but stale takeover still treats malformed owner content as proof of death and performs an owner-unchecked unlink susceptible to a real two-contender race.
- CLAIM: R004-3 is closed for the reviewed concurrent-thread scenario. The registry idempotency check, migration, and append share one registry-scoped lock, and migration temporary names are unique per call.
- CLAIM: R004-4 is closed when a persisted workflow or registry digest exists: matching bytes reconcile as consumed and mismatching bytes are quarantined. The explicitly disclosed pre-digest fallback remains narrower because it cannot verify identity when no digest exists.

## FINDINGS
- FINDING R005-1 (CRITICAL, R004-2 NOT CLOSED): stale takeover does not prove that the lock being unlinked is the same lock whose owner was examined. `_lock_owner_pid()` returns `-1` for empty, truncated, or malformed content, `_pid_alive(-1)` returns false, and `_acquire_lock()` therefore deletes a stale malformed lock even though no recorded owner PID was proved dead. Separately, takeover reads age and owner and then unlinks by pathname without comparing the observed ownership token. A targeted real two-thread probe forced contenders B and C to inspect stale dead-owner lock A; B replaced A, then C resumed from its earlier check, unlinked B's live replacement, and acquired C's token. Both B and C returned successful tokens and the final file belonged to C. Token-aware `_release_lock()` cannot repair this acquisition-time check/unlink race. The same primitive protects task ingestion, task import, and the global registry.
- FINDING R005-2 (HIGH, R004-1 NARROWER THAN REQUIRED): the synchronous stability check establishes only two equal snapshots separated by `quiet_seconds`; it cannot establish that a writer is finished. A targeted real writer-thread probe placed a complete, valid intermediate RESULT_V1, paused for 0.12 seconds, and then wrote a different complete valid result. Manual ingestion used a 0.05-second quiet interval, consumed the intermediate result, and returned before the writer's final update; afterward the expected file contained the later result. This violates the stated invariant that a file must never be imported while it may still be written. The watcher uses the same bounded-quiet assumption across observations, so a sufficiently long legitimate pause has the same semantic boundary even though its code path is otherwise unaffected by the new synchronous check.
- FINDING R005-3 (MEDIUM, NEW REGISTRATION-AUTHENTICITY GAP): `_unsafe_manual_path_reason()` treats any successfully decoded JSON object at `expected_result.json` as a registration. It does not validate `TASK_ID`, `EXPECTED_RESULT_FILE`, producer, task type, contract, wait state, or checkpoint, and `register_expected_result()` returns any existing decoded object without validating it. Thus `{}` or a tampered registration satisfies the manual/shared presence gate as long as the caller supplies the hard-coded task result path. Expected-path enforcement still prevents an arbitrary result pathname by default, but the claim that a genuine registered expectation is required is broader than the implemented check.

## EVIDENCE_REFS
- dv_harness/model_handoff_workflow.py:320-403
- dv_harness/model_handoff_workflow.py:406-446
- dv_harness/model_handoff_workflow.py:492-524
- dv_harness/model_handoff_workflow.py:527-595
- dv_harness/result_ingestion.py:299-358
- dv_harness/result_ingestion.py:376-408
- dv_harness/result_ingestion.py:507-550
- dv_harness/result_ingestion.py:555-593
- dv_harness_tests/test_model_handoff_review004_remediation.py:72-167
- dv_harness_tests/test_model_handoff_review004_remediation.py:169-227
- dv_harness_tests/test_model_handoff_review004_remediation.py:230-336
- dv_harness_tests/test_result_ingestion.py:129-185
- dv_harness_tests/test_result_ingestion.py:235-458
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-004/RESULT_V1.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_CODEX_REVIEW_004_FINDINGS_REMEDIATION_REPORT.md

## COUNTER_EVIDENCE
- COUNTER_EVIDENCE: Default `ingest_result_file()` now routes both direct/manual and watcher calls through `_unsafe_manual_path_reason()` unless `allow_unregistered_path=True`; the gate rejects no-registration, non-expected paths, symlinks, non-files, resolved-parent escapes, empty files, and non-AUTO content that changes across its two snapshots.
- COUNTER_EVIDENCE: The explicit override is default-false and is not enabled by the manual CLI call. The AUTO watcher supplies the expected path and retains its existing persisted multi-observation stability check.
- COUNTER_EVIDENCE: A unique `<uuid>:<pid>` token is persisted on normal lock acquisition, ordinary release compares the token, a stale lock whose parsed PID is live is retained, and the prior A-release/B-owner/C-contender sequential test now passes.
- COUNTER_EVIDENCE: `_append_registry()` holds one registry-scoped lock across the idempotency re-check, schema migration, and append. `_ensure_registry_schema()` uses a PID-plus-UUID temporary filename. The real three-thread different-task regression test verifies three distinct rows without corruption or duplication.
- COUNTER_EVIDENCE: Reconciliation reads the persisted workflow digest first and registry digest second; current tests verify both the matching consumed case and mismatching quarantine case.
- COUNTER_EVIDENCE: The authorized regression run completed with 128 passed and 3 platform-conditional skipped tests across all three authorized test modules.

## UNKNOWN_ITEMS
- UNKNOWN: The three skipped tests depend on host capabilities such as symlink creation or platform-specific alias behavior; those cases were not dynamically executed on this Windows host.
- UNKNOWN: PID reuse can keep an abandoned stale lock indefinitely because a different live process may later own the same PID. This is an availability risk inherent in PID-only liveness, but it was not reproduced during this review.
- UNKNOWN: Crash durability of a partially appended `registry.csv` row was not failure-injected. The concurrent-thread row-loss scenario named by R004-3 was exercised and passed, but process termination during the non-atomic append remains outside the performed probe.
- UNKNOWN: Pre-digest-era consumed state has no persisted content identity to compare. The fallback is explicitly labeled, but its correctness cannot be established from absent evidence.

## FILES_REFERENCED
- dv_harness/result_ingestion.py
- dv_harness/model_handoff_workflow.py
- dv_harness_tests/test_result_ingestion.py
- dv_harness_tests/test_model_handoff_review003_remediation.py
- dv_harness_tests/test_model_handoff_review004_remediation.py
- dv_harness/execution_contract.py
- dv_harness/md_kv_codec.py
- dv_harness/model_handoff.py
- dv_harness/model_result.py
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-004/RESULT_V1.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_CODEX_REVIEW_004_FINDINGS_REMEDIATION_REPORT.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_CLAUDE_WORKER_LIVE_QUALIFICATION.md

## VALIDATION_PERFORMED
- Read the complete REVIEW-005 handoff and independently inspected the authorized current implementation, remediation tests, prior REVIEW-004 result, remediation report, gap register, and disclosed live-qualification evidence.
- Re-derived R004-1 through R004-4 against current control flow rather than accepting author conclusions.
- Ran all three authorized test modules with bytecode and pytest cache writes disabled and an in-task temporary directory: 128 passed, 3 skipped in 177.89 seconds.
- Executed a targeted stale malformed-token probe. A stale lock containing `truncated-token` was taken over, confirming invalid content is treated as a dead owner rather than an unprovable owner.
- Executed a targeted real two-thread stale-takeover probe. Both contenders returned successful ownership tokens and the later contender replaced the earlier contender's live lock after relying on stale observations of the original lock.
- Executed a targeted real slow-writer probe in a throwaway Git repository. Ingestion consumed a valid intermediate result after a 0.05-second quiet interval; the writer then replaced it with a different valid final result after a 0.12-second pause.
- Inspected lock ordering. Imports acquire task lock before registry lock; reviewed code contains no registry-lock-to-task-lock reverse acquisition, so no deadlock was identified in the authorized paths.
- Removed all probe and pytest temporary artifacts, modified no production file, performed no fix, preserved REVIEW-004 unchanged, and did not invoke the L5DGVA import command.

## RECOMMENDED_ACTIONS
- Make stale takeover compare-and-delete ownership-safe. Read and retain the complete observed token, reject malformed/truncated content as ownership unknown, and remove the lock only if the on-disk token is still exactly the observed token at the deletion boundary. Use an atomic lease/rename or OS locking primitive where a read-compare-unlink sequence cannot provide that guarantee.
- Add a deterministic two-contender regression in which both contenders inspect A, B replaces A, and C must not delete B. Add empty, truncated, malformed, and partially written lock-token cases.
- Replace quiet-time inference with a completion protocol for manual and automatic transport, such as producer atomic rename from a non-watched temporary name or an explicit sealed/manifest marker binding size and SHA-256. Treat snapshot stability as readiness evidence only when the transport contract guarantees no further writes after publication.
- Validate the complete expected-result registration schema and correlation fields before ingestion. Reject malformed, empty, mismatched, symlinked, or tampered registration records rather than treating JSON decode success as registration.
- Retain the registry-scoped critical section and unique migration temporary names; add process-level crash injection around migration replace and row append before claiming crash durability.

## HUMAN_DECISIONS_REQUIRED
(none)

## SCOPE_EXCEPTIONS
(none)

## RETURNED_ARTIFACTS
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-005/RESULT_V1.md
