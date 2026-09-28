# L5DGVA_MODEL_RESULT_V1

<!-- L5DGVA_VALUE_ENCODING=escaped-v1 -->

## RESULT_VERSION
1.0

## TASK_ID
M7-V1-CODEX-REVIEW-007

## PRODUCER_MODEL
codex

## TASK_TYPE
review-route

## RESULT_STATUS
FAIL

## CLAIMS
- CLAIM: R006-1's in-place stale-takeover redesign closes the reported canonical-path vacancy and concurrent takeover-evaluation races, but the accompanying `_release_lock()` retry fix introduces a new ownership violation. The remediation is therefore not fully closed.
- CLAIM: R006-2 is closed for the reviewed manual/manifest and synchronous-stability paths: the exact verified byte buffer is hashed, parsed, validated, and consumed without an independent result-path reread anywhere in `_ingest_locked()` -> `import_result()` -> `_import_result_inner()`.
- CLAIM: R006-3 is closed for every registration field with independently derivable ground truth. A stale-but-known `WAIT_STATE` and arbitrary non-empty `CREATED_AT` still pass, but neither value is used to authorize a path, validate a result, or drive workflow state; no material exploit was reproduced from those deliberately historical/advisory fields.
- CLAIM: R006-4/R005-2 remains open exactly as disclosed. `LEGACY_UNSEALED_PUBLICATION=COMPATIBILITY_MODE`, `QUALIFIED_ATOMIC_PUBLICATION=NO`, and the recorded HumanGate are accurate; this review found no new regression in that already-open behavior.

## FINDINGS
- FINDING R007-1 (CRITICAL, NEW DEFECT INTRODUCED BY R006-1 REMEDIATION): `_release_lock()` checks the pathname content against the caller token only once, before entering its retry loop. Every `OSError` from `lock.unlink()` is then classified as transient, and later retries unlink the pathname without re-reading and revalidating ownership. A controlled failure-injection probe began with owner A, made the first unlink fail with a sharing-style `PermissionError` while changing the pathname content to owner B, and allowed the second unlink to execute normally. `_release_lock(lock, A)` made two unlink calls and deleted B's lock (`NEW_OWNER_LOCK_EXISTS=False`). Thus the retry can mask an ownership change as a transient sharing failure and violate the function's stated token-ownership invariant. The same race shape exists if another release/removal wins and a new owner acquires the pathname between a failed retry and a later retry. Because these locks serialize ingestion/import/registry mutation, deleting a live successor lock can admit concurrent writers.
- FINDING R006-4 (HIGH, ACKNOWLEDGED OPEN; NO NEW REGRESSION): the default AUTO human-transport path still uses bounded quiet-interval inference without a required seal/manifest. The authorized slow-writer regression continues to encode consumption of a valid intermediate result. The final disposition accurately classifies this as `LEGACY_UNSEALED_PUBLICATION=COMPATIBILITY_MODE`, does not force-close it, and records a HumanGate for risk acceptance versus a dedicated sealed-transport wave.

## EVIDENCE_REFS
- dv_harness/model_handoff_workflow.py:444-515
- dv_harness/model_handoff_workflow.py:518-549
- dv_harness/model_handoff_workflow.py:185-290
- dv_harness/model_handoff_workflow.py:552-590
- dv_harness/result_ingestion.py:226-283
- dv_harness/result_ingestion.py:437-487
- dv_harness/result_ingestion.py:491-610
- dv_harness/result_ingestion.py:674-720
- dv_harness_tests/test_model_handoff_review006_remediation.py:68-173
- dv_harness_tests/test_model_handoff_review006_remediation.py:176-230
- dv_harness_tests/test_model_handoff_review006_remediation.py:233-291
- dv_harness_tests/test_model_handoff_review005_remediation.py:109-143
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-006/RESULT_V1.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_CODEX_REVIEW_006_FINDINGS_REMEDIATION_REPORT.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_R005_2_FINAL_DISPOSITION.md

## COUNTER_EVIDENCE
- COUNTER_EVIDENCE: `_try_stale_takeover_in_place()` opens the existing canonical lock file, holds a real non-blocking OS advisory lock during evaluation and overwrite, and never unlinks or renames the canonical pathname. The deterministic three-role test and real ungated two-contender test passed; no canonical-path vacancy or dual takeover winner was reproduced in current code.
- COUNTER_EVIDENCE: the release defect does not arise when the first unlink succeeds, and a token mismatch detected before the loop correctly returns without deletion. The defect specifically requires an `OSError` followed by ownership/pathname change before a retry.
- COUNTER_EVIDENCE: manifest and synchronous stability checks return bytes rather than Booleans; `_ingest_locked()` hashes those bytes and supplies them as `pre_read_bytes`; both canonical import layers honor that buffer. Both swap-after-check adversarial tests passed.
- COUNTER_EVIDENCE: `_valid_registration()` now correlates task ID, expected path, target model, producer, task type, handoff path, output contract, and current head against the persisted handoff. Tampering those fields is rejected.
- COUNTER_EVIDENCE: repository-wide searches within authorized files found `WAIT_STATE` and `CREATED_AT` used only for registration creation/validation and tests, not as downstream authorization or workflow-transition inputs.
- COUNTER_EVIDENCE: the complete authorized regression set passed: 147 passed, 3 skipped in 202.05 seconds.

## UNKNOWN_ITEMS
- UNKNOWN: The three platform-conditional skipped tests were not dynamically exercised on this Windows host.
- UNKNOWN: Exhaustive instruction-boundary crash injection was not performed for the in-place takeover primitive. No defect in its canonical-path preservation or advisory-lock serialization was reproduced.
- UNKNOWN: `CREATED_AT` has no independent persisted source against which its original value can be reconstructed. Current code validates only that it is a non-empty string; no downstream correctness or authorization effect was found.

## FILES_REFERENCED
- dv_harness/result_ingestion.py
- dv_harness/model_handoff_workflow.py
- dv_harness_tests/test_result_ingestion.py
- dv_harness_tests/test_model_handoff_review003_remediation.py
- dv_harness_tests/test_model_handoff_review004_remediation.py
- dv_harness_tests/test_model_handoff_review005_remediation.py
- dv_harness_tests/test_model_handoff_review006_remediation.py
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-006/RESULT_V1.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_CODEX_REVIEW_006_FINDINGS_REMEDIATION_REPORT.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_R005_2_FINAL_DISPOSITION.md

## VALIDATION_PERFORMED
- Independently verified the authoritative repository root, branch, starting HEAD, and authoritative REVIEW-007 handoff before substantive work; read the complete handoff and preserved `TASK_ID=M7-V1-CODEX-REVIEW-007`.
- Independently traced R006-1 through the current in-place takeover, OS advisory locking, acquisition, and release implementations; reviewed the deterministic three-role and real ungated concurrent-thread regressions.
- Executed a hostile failure-injection probe against the real `_release_lock()` implementation. After a first sharing-style unlink failure changed the pathname token from owner A to owner B, the unrevalidated second retry deleted owner B's lock, reproducing R007-1.
- Independently traced R006-2 end-to-end from manifest/synchronous verification through ingestion hashing and both canonical import layers; confirmed the exact pre-read buffer is used for parsing and consumption.
- Independently inspected all authorized uses of registration metadata and challenged known-but-stale `WAIT_STATE` plus arbitrary non-empty `CREATED_AT`; both can pass validation, but no material downstream use or exploit was found.
- Reconfirmed the R005-2 final disposition against current code and its slow-writer regression: compatibility mode is truthful, qualification is not claimed, and the HumanGate remains recorded.
- Ran the complete authorized regression set with bytecode and pytest cache writes disabled: 147 passed, 3 skipped in 202.05 seconds.
- After interruption, reverified the same authoritative root/branch/HEAD and absent result, confirmed the pytest base-temp resolved exactly to `D:\DV\Task\L5_DGVA\.review007_pytest_tmp`, inspected it as pytest-generated disposable state, and removed only that exact directory. No regression rerun was needed because the completed output and substantive evidence remained available.
- Modified no production implementation, performed no finding fix, did not rewrite REVIEW-001 through REVIEW-006 artifacts, and did not invoke the manual L5DGVA import command.

## RECOMMENDED_ACTIONS
- Revalidate the pathname token on every `_release_lock()` retry immediately before deletion, and treat any mismatch or unreadable/replaced pathname as loss of ownership rather than as a transient unlink failure. The validation and deletion must be designed so a successor cannot be deleted through a check/use race.
- Add a deterministic regression that forces the first unlink to fail, changes/reacquires the pathname with a successor token, and asserts the retry never deletes that successor lock.
- Retain the current in-place takeover and exact-byte import regressions; they cover real failures and passed independently.
- Keep R005-2/R006-4 open under the existing HumanGate until the project owner accepts compatibility-mode risk or a sealed-transport-contract wave closes it.

## HUMAN_DECISIONS_REQUIRED
- Existing R005-2/R006-4 HumanGate remains required: choose risk acceptance for `LEGACY_UNSEALED_PUBLICATION=COMPATIBILITY_MODE` or block M7 pending a dedicated sealed-transport-contract wave.

## SCOPE_EXCEPTIONS
(none)

## RETURNED_ARTIFACTS
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-007/RESULT_V1.md
