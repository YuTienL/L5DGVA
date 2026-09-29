# M7 Codex REVIEW-006 Findings Remediation Report

`TASK_ID=M7-V1-CODEX-REVIEW-006`, `RESULT_STATUS=FAIL`, a re-review of the
REVIEW-005 remediation. Real result sha256
`93e5a82f2f11d31d22843b4c812abe4414e5d3c68da7345cce5d01e21a5abe43`, auto-
detected and auto-consumed by the already-running detached watcher with
zero manual intervention (a real `HUMAN_TRANSPORT_EVENT`, not a scheduler
intervention). Original `RESULT_V1.md` was never edited.

## Who performed this remediation, and why (disclosed up front)

Per the standing Human Authority Decision: native detached-Claude-worker
launch remains `BLOCKED_BY_HOST_POLICY`; this remediation continues
through the existing authorized (direct in-session) execution path, the
same mechanism used for REVIEW-003/004/005.

## Independent reproduction (pre-fix, current production code)

| ID | Claim | Reproduction | Confirmed |
|---|---|---|---|
| R006-1 (CRITICAL) | `_content_verified_takeover()`'s stage-then-compare design creates its own staging-window race: the canonical lock path is briefly absent, letting a third, normal acquirer win it, and the mismatch-restore path can then overwrite that third acquirer's live lock | Reproduced deterministically: gated `_read_lock_snapshot_from_fd`'s predecessor (`_read_lock_snapshot`) mid-evaluation and confirmed a concurrent normal `_acquire_lock()` call could succeed while the path was vacated for staging, and that the restore-on-mismatch path would then clobber it | YES |
| R006-2 (CRITICAL) | `_sealed_manifest_confirms_completion()`/`_synchronous_stability_check()` returned a bare Boolean, and `_ingest_locked()`/`import_result()` independently re-read the path afterward for the real import -- a writer could swap content in between | Reproduced live: patched the check to swap the file's real content to a different valid result immediately after the check's own read confirmed the original; the pre-fix code imported the SWAPPED content, not the checked one | YES |
| R006-3 (MEDIUM) | `_valid_registration()` checked only `TASK_ID`/`EXPECTED_RESULT_FILE`, not `TARGET_MODEL`/`EXPECTED_PRODUCER`/`EXPECTED_TASK_TYPE`/`HANDOFF_FILE`/`EXPECTED_RESULT_CONTRACT`/`CURRENT_HEAD` | Reproduced live: a registration with all 10 keys present, `TASK_ID`/`EXPECTED_RESULT_FILE` correct, but `TARGET_MODEL`/`EXPECTED_PRODUCER` changed to `chatgpt`, `EXPECTED_TASK_TYPE` to `wrong-type`, `CURRENT_HEAD` to 40 zeroes -- accepted by the pre-fix validator | YES |
| R006-4 (HIGH, re-confirmed open) | R005-2 remains genuinely open for the default human-transport path, accurately disclosed, not a new regression | Re-verified: `test_slow_writer_pausing_longer_than_quiet_interval_can_still_be_consumed_mid_sequence` still reproduces the characteristic; no change claimed here | YES (status unchanged, see `M7_R005_2_FINAL_DISPOSITION.md`) |

## Fixes

| ID | Fix | Files | Tests (`test_model_handoff_review006_remediation.py`) |
|---|---|---|---|
| R006-1 | Full redesign, not a patch: `_try_stale_takeover_in_place()` replaces `_content_verified_takeover()` entirely. Takeover NEVER unlinks/renames the canonical lock path. It opens the EXISTING file in place (`os.open(path, O_RDWR)`), takes a real, non-blocking OS advisory lock on it (`fcntl.flock()` on POSIX, a 1-byte `msvcrt.locking()` region on Windows -- both stdlib), and -- only if still genuinely eligible -- overwrites its content with the new token via truncate+write on the SAME fd. Because the path is never vacated, a normal `O_CREAT\|O_EXCL` acquirer can never observe it as absent, structurally closing the staging-window race rather than detecting it after the fact. `_acquire_lock()` simplified accordingly (the old 2-iteration retry loop is gone -- takeover now claims ownership directly, no second create attempt needed). A real, reproduced side-flake surfaced by this fix and also closed here: Windows refuses to delete a file that another handle still has open without `FILE_SHARE_DELETE`, and the new takeover's open-flock-read window is long enough, under real concurrent retry pressure, to intermittently make a live release's unlink fail and get silently swallowed -- `_release_lock()` now retries its unlink for up to 1s on a transient `OSError` (POSIX has no such restriction and typically succeeds first try there). | `dv_harness/model_handoff_workflow.py` | `test_third_normal_acquirer_cannot_win_while_a_stale_takeover_evaluation_is_in_progress` (deterministic, gated), `test_real_two_contender_race_admits_exactly_one_winner_never_corrupts_the_lock` (real, ungated concurrency), `test_stale_takeover_still_requires_a_provably_dead_owner`, `test_malformed_lock_content_still_never_treated_as_proof_of_death` |
| R006-2 | `_sealed_manifest_confirms_completion()` and `_synchronous_stability_check()` now return the VERIFIED byte buffer (`Optional[bytes]`), never a bare Boolean. `_unsafe_manual_path_reason()` returns `(reason, verified_bytes)`; `_ingest_locked()` imports `verified_bytes` directly when present, never re-reading `path`. Threaded one level deeper than the original REVIEW-005 fix reached: `model_handoff_workflow.import_result()`/`_import_result_inner()` gained an optional `pre_read_bytes` parameter -- the Canonical parser itself (which does its own internal read) now also uses the pre-verified buffer when the caller supplies one, closing the full gap end-to-end, not just at the hash/dedup layer. | `dv_harness/result_ingestion.py`, `dv_harness/model_handoff_workflow.py` | `test_sealed_manifest_verified_bytes_are_what_gets_imported_even_if_file_changes_right_after`, `test_quiet_interval_verified_bytes_are_what_gets_imported_even_if_file_changes_right_after` |
| R006-3 | `_valid_registration()` now correlates every field with a real, independently-derivable ground truth against the task's own current, persisted handoff: `TARGET_MODEL`/`EXPECTED_PRODUCER`/`EXPECTED_TASK_TYPE`/`HANDOFF_FILE`/`EXPECTED_RESULT_CONTRACT`/`CURRENT_HEAD` must equal exactly what `register_expected_result()` itself would derive right now. `WAIT_STATE` and `CREATED_AT` are deliberately NOT compared for live equality (disclosed, not silently narrower): `WAIT_STATE` legitimately reflects the state AT REGISTRATION TIME, which differs from the CURRENT state by the time this check runs during real ingestion by design -- it is validated as a real, known workflow-state value (a domain check, sourced from `model_handoff_workflow.STATE_*`) instead. `CREATED_AT` has no independent ground truth to recompute; validated as a non-empty string only. | `dv_harness/result_ingestion.py` | `test_tampered_model_producer_task_type_and_head_are_rejected_despite_correct_task_id_and_path` (Codex's own exact probe), `test_tampered_handoff_file_and_contract_are_also_rejected`, `test_wait_state_is_validated_as_a_known_state_value_not_live_equality`, `test_valid_real_registration_still_passes_after_the_correlation_fix` |

## Verification

- 10 new tests in `test_model_handoff_review006_remediation.py`, all pass.
- `test_third_normal_acquirer_cannot_win_while_a_stale_takeover_evaluation_is_in_progress`
  is a deterministic, gated reproduction of Codex's own real 3-role probe
  (stale A, contender C evaluating, normal acquirer D) -- proves D can
  never win mid-evaluation and the canonical path is never observed absent.
- `test_real_two_contender_race_admits_exactly_one_winner_never_corrupts_the_lock`
  is a real, ungated 2-thread concurrency test with no artificial gating at
  all, relying on the real OS advisory lock alone.
- 3 obsolete tests exercising the REMOVED `_content_verified_takeover()`/
  `_read_lock_snapshot()` functions were deleted from
  `test_model_handoff_review005_remediation.py` with a pointer comment to
  their stronger REVIEW-006 replacements (comment hygiene: a test asserting
  behavior of a function that no longer exists is not left in place).
- Full related regression re-run after all three fixes (result_ingestion,
  review003/004/005/006, agent_execution_backend): passed (see this
  task's own commit for the exact count).
- All 5 frozen reference sources (Parent/v50/b7a/b7b/b8) reverified
  unchanged immediately before commit.

## Disclosed limits

- R006-1's fix is a real, meaningfully stronger primitive (never vacates
  the canonical path), but it is still a single-host advisory-lock design,
  not a distributed lease -- consistent with this project's existing,
  disclosed limitation for the Canonical Mutation Lease
  (`agent_execution_backend.py`) and the original REVIEW-004 R004-2 fix.
- The `_release_lock()` retry-on-sharing-failure fix is a real, bounded
  (1s) mitigation for a genuinely transient Windows-only condition; it is
  not a claim that Windows file-locking semantics now perfectly match
  POSIX's unlink-while-open tolerance.
- R005-2/R006-4 remains open exactly as before -- this remediation pass
  did not touch it; see `M7_R005_2_FINAL_DISPOSITION.md` for its dedicated,
  separate disposition.
- GAP-V2-015 (production multi-field worker structured output) remains
  OPEN and out of this handoff's scope, as Codex itself noted (the backend/
  profile files were forbidden in this review round).

Status: `FIXED_AND_VERIFIED_BY_AUTHOR` (R006-1 CRITICAL, R006-2 CRITICAL,
R006-3 MEDIUM); `PENDING_INDEPENDENT_REREVIEW` (REVIEW-007).
