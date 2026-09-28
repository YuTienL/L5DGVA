# L5DGVA_MODEL_RESULT_V1

<!-- L5DGVA_VALUE_ENCODING=escaped-v1 -->

## RESULT_VERSION
1.0

## TASK_ID
M7-V1-CODEX-REVIEW-006

## PRODUCER_MODEL
codex

## TASK_TYPE
review-route

## RESULT_STATUS
FAIL

## CLAIMS
- CLAIM: R005-1 is relocated, not closed. Malformed/empty lock content is now ownership-unknown and the original two-contender check/unlink race is prevented, but `_content_verified_takeover()` creates a new staging-window race that can overwrite a third owner's live lock.
- CLAIM: R005-2 remains open exactly as disclosed for the default quiet-interval human-transport path. The optional manifest is content-bound at check time, but its claimed completion guarantee is not correct because verification and ingestion read different snapshots.
- CLAIM: R005-3 is narrowed, not closed. Empty records and copied records with a mismatched TASK_ID/EXPECTED_RESULT_FILE are rejected, but the alleged complete schema/correlation validation accepts and preserves tampered producer, model, task type, handoff, contract, head, wait-state, and timestamp values when their keys remain present.
- CLAIM: The authorized evidence continues to describe GAP-V2-015 structured worker output as OPEN and production worker qualification as not proven. Its implementation files are forbidden in this handoff, so no broader closure conclusion is made here.

## FINDINGS
- FINDING R006-1 (CRITICAL, R005-1 RELOCATED): `_content_verified_takeover()` atomically moves the current lock from its canonical pathname to a private staging pathname before it reads and compares content. During that interval the canonical lock pathname is absent, so another writer can successfully acquire it. If the staged content differs from the contender's earlier observation, the mismatch branch uses `os.replace(staging, lock)` and overwrites the newly acquired live lock. A targeted real-thread probe placed owner B at the lock path, invoked takeover using stale observation A, paused the takeover after B was moved to staging, and acquired owner D at the now-empty canonical path. When takeover resumed it correctly returned false but restored B over D. D had returned a successful token, while the on-disk lock no longer contained D's token. Thus mutual exclusion and token ownership are violated by the fix itself. This primitive protects ingestion, import, and registry locks.
- FINDING R006-2 (CRITICAL, SEALED-MANIFEST CHECK/USE RACE): `_sealed_manifest_confirms_completion()` reads and hashes the result, returns a Boolean, and then `_ingest_locked()` independently rereads the path for hashing/import. An external writer can replace the result after manifest verification but before the ingestion read. A targeted probe created a manifest correctly binding valid result A, allowed the real manifest check to return true, replaced the file with different valid result B before `_ingest_locked()` continued, and observed B consumed immediately under a five-second quiet policy even though the manifest still bound A. The manifest therefore proves only a past snapshot, not the bytes actually imported. The stale/mismatched-manifest test changes content before verification and does not cover this interleaving.
- FINDING R006-3 (MEDIUM, R005-3 NARROWER THAN CLAIMED): `_valid_registration()` checks that ten keys exist, then validates only TASK_ID and EXPECTED_RESULT_FILE values. It performs no type/non-empty validation and does not correlate TARGET_MODEL, EXPECTED_PRODUCER, EXPECTED_TASK_TYPE, HANDOFF_FILE, EXPECTED_RESULT_CONTRACT, CURRENT_HEAD, WAIT_STATE, or CREATED_AT with the stored handoff/workflow. A targeted probe changed TARGET_MODEL and EXPECTED_PRODUCER to `chatgpt`, EXPECTED_TASK_TYPE to `wrong-type`, and CURRENT_HEAD to forty zeroes while retaining all keys and the two checked fields. `_valid_registration()` returned true and `register_expected_result()` returned the tampered record unchanged. Canonical result validation later uses the handoff and limits direct result-consumption impact, but registration metadata and observability are not genuine or fully correlated as claimed.
- FINDING R006-4 (HIGH, ACKNOWLEDGED OPEN): without a manifest, both manual synchronous stability and AUTO watcher stability continue to infer completion from a bounded quiet interval. The authorized adversarial test deliberately reproduces consumption of a valid intermediate result before a slow writer's final result. This is accurately disclosed by the remediation report and is not a newly introduced regression, but it remains an unresolved qualification failure for the current human-transport path.

## EVIDENCE_REFS
- dv_harness/model_handoff_workflow.py:362-429
- dv_harness/model_handoff_workflow.py:432-479
- dv_harness/model_handoff_workflow.py:492-595
- dv_harness/result_ingestion.py:204-278
- dv_harness/result_ingestion.py:343-427
- dv_harness/result_ingestion.py:430-465
- dv_harness/result_ingestion.py:600-675
- dv_harness_tests/test_model_handoff_review005_remediation.py:63-160
- dv_harness_tests/test_model_handoff_review005_remediation.py:163-258
- dv_harness_tests/test_model_handoff_review005_remediation.py:261-317
- dv_harness_tests/test_model_handoff_review004_remediation.py:169-299
- dv_harness_tests/test_result_ingestion.py:129-185
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-005/RESULT_V1.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_CODEX_REVIEW_005_FINDINGS_REMEDIATION_REPORT.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/L5DGVA_CONTROLLED_CLAUDE_WORKER_PERMISSION_QUALIFICATION.md

## COUNTER_EVIDENCE
- COUNTER_EVIDENCE: `_parse_lock_owner_pid()` now returns None for empty, malformed, truncated, or non-positive ownership content, and `_acquire_lock()` refuses takeover without a parsed positive PID, stale age, and dead-owner result.
- COUNTER_EVIDENCE: In the exact two-contender test where B and C observe the same stale A snapshot, only one contender wins and the loser restores the winner's token. The uncovered defect requires a third acquisition while the canonical pathname is absent during staging.
- COUNTER_EVIDENCE: Staging filenames include PID and a UUID fragment, making ordinary same-process and cross-process filename collision unlikely; no literal fixed staging-name collision was found.
- COUNTER_EVIDENCE: A manifest with malformed fields or a digest/size mismatch is not trusted and falls back to quiet-interval inference. A matching manifest avoids the synchronous sleep when the result remains unchanged through ingestion.
- COUNTER_EVIDENCE: Empty registration JSON and a registration copied unchanged from another task are rejected; `register_expected_result()` rebuilds an invalid stub, and a legitimate generated registration passes unchanged.
- COUNTER_EVIDENCE: The complete authorized regression run produced 140 passed and 3 platform-conditional skipped tests.

## UNKNOWN_ITEMS
- UNKNOWN: The three skipped tests depend on platform capabilities such as symlink creation or platform-specific alias behavior and were not dynamically executed on this Windows host.
- UNKNOWN: `_content_verified_takeover()` suppresses restoration failures. Additional crash points after staging but before comparison/restoration can strand the lock only under the staging name; process-termination injection at each instruction boundary was not performed.
- UNKNOWN: The registration validator's exact forward-compatibility behavior under a future schema addition cannot be exercised before such a schema exists. Current behavior permits extra keys but rejects older records missing any newly required fixed-tuple key if the tuple is changed in lockstep.
- UNKNOWN: GAP-V2-015 implementation could not be independently reviewed because its backend/profile implementation files are forbidden by this handoff. Authorized evidence explicitly reports the production multi-field structured-output path as still OPEN/NOT_PROVEN.
- UNKNOWN: No reverse registry-lock-to-task-lock acquisition was found in the authorized paths, so no deadlock was reproduced; this does not prove absence under forbidden or future callers.

## FILES_REFERENCED
- dv_harness/result_ingestion.py
- dv_harness/model_handoff_workflow.py
- dv_harness_tests/test_result_ingestion.py
- dv_harness_tests/test_model_handoff_review003_remediation.py
- dv_harness_tests/test_model_handoff_review004_remediation.py
- dv_harness_tests/test_model_handoff_review005_remediation.py
- dv_harness/execution_contract.py
- dv_harness/md_kv_codec.py
- dv_harness/model_handoff.py
- dv_harness/model_result.py
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-005/RESULT_V1.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_CODEX_REVIEW_005_FINDINGS_REMEDIATION_REPORT.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/L5DGVA_CONTROLLED_CLAUDE_WORKER_PERMISSION_QUALIFICATION.md

## VALIDATION_PERFORMED
- Read the complete REVIEW-006 handoff before acting and independently inspected the authorized implementation, all three remediation generations of tests, prior REVIEW-005 result, remediation report, and controlled-worker qualification evidence.
- Re-derived R005-1 through R005-3 against current code and explicitly retained R005-2 as open rather than treating the optional manifest as default-path closure.
- Ran all four authorized test modules with bytecode and pytest cache writes disabled and an in-task temporary directory: 140 passed, 3 skipped in 184.65 seconds.
- Executed a targeted real-thread takeover-staging probe. A new owner successfully acquired the temporarily absent lock path, then the mismatch restoration overwrote that owner's token while returning false.
- Executed a targeted sealed-manifest check/use probe. The real manifest check validated result A, the file changed to result B before ingestion reread it, and B was consumed without the configured five-second stability delay.
- Executed a targeted registration-correlation probe. A record with all fixed keys but false model, producer, task type, and head values passed `_valid_registration()` and was returned unchanged by `register_expected_result()`.
- Inspected lock ordering and unique staging/migration naming; no authorized reverse lock-order deadlock or direct staging-name collision was identified.
- Removed all probe and pytest temporary artifacts, modified no production implementation, performed no fix, preserved prior RESULT_V1 artifacts, and did not invoke the L5DGVA import command.

## RECOMMENDED_ACTIONS
- Replace move-then-compare lock takeover with a primitive that never vacates the authoritative lock pathname before ownership is secured and cannot overwrite a subsequent acquirer. If portable filesystem operations cannot provide compare-and-delete atomically, use an OS lock/lease mechanism or a generation directory/indirection protocol whose ownership transition is atomic.
- Add a regression with three roles: stale A, takeover contender C staging current B, and D acquiring during the staging window. Assert D's successful token remains authoritative and can be released normally.
- Bind manifest verification to the exact bytes passed into canonical import. Read the result once, validate manifest size/digest against that immutable byte buffer, and parse/hash/consume that same buffer; alternatively atomically claim a sealed immutable result object before verification. Never reduce completion to a Boolean followed by a path reread.
- Validate registration values and types against the stored handoff/workflow, including target model, producer, task type, handoff path, output contract, current head/checkpoint, and legitimate wait state. Define versioning/extension semantics explicitly so future optional fields do not invalidate older valid records.
- Keep R005-2 open for all producers that do not use a corrected sealed publication protocol; default quiet-interval inference must not be described as proof of writer completion.
- Retain GAP-V2-015 as OPEN until an independently reviewable, schema-conformant production multi-field worker result is demonstrated within an authorized handoff scope.

## HUMAN_DECISIONS_REQUIRED
(none)

## SCOPE_EXCEPTIONS
(none)

## RETURNED_ARTIFACTS
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-006/RESULT_V1.md
