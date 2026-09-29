# M7 Codex REVIEW-005 Findings Remediation Report

`TASK_ID=M7-V1-CODEX-REVIEW-005`, `RESULT_STATUS=FAIL`, a re-review of the
REVIEW-004 remediation. Real result sha256
`f85bbffe7952f6fe6dd43052e149acc065e05c3901128caf63bde39224b009e5`, already
ingested (`RESULT_CONSUMED`, `NEXT_ACTION=AUTO_REMEDIATE_CONFIRMED_FINDINGS`,
`human_action_required=NO`). Original `RESULT_V1.md` was never edited.

## Who performed this remediation, and why (disclosed up front)

Per the standing Human Authority Decision recorded this session: native
detached-Claude-worker launch authorization is
`NATIVE_CONTROLLED_CLAUDE_WORKER=BLOCKED_BY_HOST_POLICY` /
`PRODUCTION_WORKER_AUTHORIZATION=NOT_AVAILABLE_FROM_CURRENT_SESSION` (see
`L5DGVA_CONTROLLED_CLAUDE_WORKER_PERMISSION_QUALIFICATION.md`), and the
decision explicitly directs continuing the real Codex re-review loop
"through the existing authorized execution path" -- the same
direct-in-session-editing mechanism that fixed REVIEW-003's and
REVIEW-004's findings. This is disclosed honestly: no detached worker
performed this remediation; the orchestrating session did, as authorized.

## Independent reproduction (pre-fix, current production code)

| ID | Claim | Reproduction | Confirmed |
|---|---|---|---|
| R005-1 (CRITICAL) | Stale takeover can admit a third writer / destroy a live lock via an owner-blind unlink-by-pathname, and treats malformed lock content as proof of death | Direct inspection of `_acquire_lock()`: `_lock_owner_pid()` returned `-1` for unparseable content and `_pid_alive(-1)` returns `False`, so malformed content was silently "provably dead"; the takeover itself called `lock.unlink()` unconditionally with no re-check that the file still held the content that was judged stale-and-dead. Reproduced with a real, deterministic two-contender scenario (`_content_verified_takeover` called against a lock whose content had genuinely changed underneath the caller) -- the pre-fix bare `unlink()` would have destroyed the new owner's live lock | YES |
| R005-2 (HIGH) | The synchronous two-snapshot stability check cannot distinguish "finished" from "paused longer than `quiet_seconds`" | Reproduced live with a real background writer thread: wrote a complete, valid intermediate result, paused 0.12s (`> quiet_seconds=0.05`), then wrote a different complete valid final result; manual ingestion consumed the intermediate content before the writer's real final update landed | YES |
| R005-3 (MEDIUM) | `_unsafe_manual_path_reason()`/`register_expected_result()` treat any successfully-decoded JSON object as a genuine registration | Reproduced directly: writing `{}` (or a registration copied from a different task) to `expected_result.json` satisfied the presence-only gate (`reg is not None`) and would have been returned unchanged by `register_expected_result()`'s "already registered" short-circuit | YES |

## Fixes

| ID | Fix | Files | Tests (`test_model_handoff_review005_remediation.py`) |
|---|---|---|---|
| R005-1 | `_parse_lock_owner_pid()` replaces `_lock_owner_pid()` for takeover decisions: returns `None` (OWNERSHIP UNKNOWN) for empty/truncated/non-positive content, never `-1`-as-dead. Takeover itself now goes through `_content_verified_takeover()`: the current file at the lock's path is atomically stolen into a private staging name (`os.replace()`, atomic on both POSIX and Windows), its content is checked against what the caller originally observed, and on any mismatch it is restored byte-for-byte and the takeover reports failure -- a losing contender only ever gives up, it never destroys another holder's real lock. `_read_lock_snapshot()` factors out the content+age read as one snapshot so a regression test can force two real threads to observe the identical snapshot before racing at the takeover step. | `dv_harness/model_handoff_workflow.py` | `test_malformed_lock_content_is_ownership_unknown_never_proof_of_death`, `test_empty_lock_content_is_ownership_unknown_never_proof_of_death`, `test_content_verified_takeover_refuses_and_restores_a_live_lock_that_changed_underneath_it`, `test_content_verified_takeover_succeeds_when_content_is_unchanged`, `test_real_two_contender_race_never_admits_a_third_writer_or_lock_loss` (real threads + a real barrier forcing Codex's own interleaving) |
| R005-2 | Real, bounded improvement (not a full close -- see Disclosed limits): an OPTIONAL sealed-manifest completion signal. A producer that writes a `<result>.manifest.json` sidecar (`{"sha256": ..., "size": ...}`) matching the file's REAL current bytes gives ingestion a positive completion proof (`_sealed_manifest_confirms_completion()`) that skips `_synchronous_stability_check()`'s sleep-based inference entirely. A missing or mismatched (stale) manifest falls back to the pre-existing, unchanged quiet-interval behavior -- fully backward compatible. | `dv_harness/result_ingestion.py` | `test_slow_writer_pausing_longer_than_quiet_interval_can_still_be_consumed_mid_sequence` (proves the defect is still real and current), `test_sealed_manifest_lets_a_producer_skip_quiet_interval_inference_entirely` (timing proof: a 5s quiet policy returns in under 2s with a matching manifest), `test_stale_sealed_manifest_never_authorizes_early_consumption_of_a_newer_unfinished_write` |
| R005-3 | New `_valid_registration()` requires the COMPLETE registration schema (every key `register_expected_result()` itself writes) AND the two correlation fields that actually bind the record to THIS task (`TASK_ID`, `EXPECTED_RESULT_FILE`) to be correct -- not merely "some JSON object decoded". Wired into both `_unsafe_manual_path_reason()` (new `MALFORMED_REGISTRATION` refusal reason) and `register_expected_result()` (a malformed/mismatched existing record is never returned as-is; it is replaced with a fresh, genuine registration derived from the task's own real handoff, exactly as if no registration existed yet). | `dv_harness/result_ingestion.py` | `test_empty_registration_stub_is_never_treated_as_a_genuine_registration`, `test_registration_copied_from_a_different_task_is_rejected`, `test_register_expected_result_replaces_a_malformed_stub_with_a_genuine_registration`, `test_valid_real_registration_still_passes_unchanged` |

## Verification

- 12 new tests in `test_model_handoff_review005_remediation.py`, all pass.
- `test_real_two_contender_race_never_admits_a_third_writer_or_lock_loss` is
  a REAL concurrency test (two real `threading.Thread`s, gated by a real
  `threading.Barrier` forcing them to observe the identical stale snapshot
  before racing at the takeover step) -- the same real-two-thread shape
  Codex's own probe used, not a simulated race.
- Full related regression re-run after all three fixes:
  `test_result_ingestion.py` + `test_model_handoff_review003_remediation.py`
  + `test_model_handoff_review004_remediation.py` +
  `test_model_handoff_review005_remediation.py` -- all passed (see this
  task's own commit for the exact count).
- All 5 frozen reference sources (Parent/v50/b7a/b7b/b8) reverified
  unchanged immediately before commit.

## Disclosed limits

- **R005-2 is NOT fully closed.** The sealed-manifest mechanism is a real,
  tested, available capability, but it only takes effect for a producer
  that actually writes the manifest sidecar. Codex's real transport into
  this repo today is a human placing `RESULT_V1.md` directly -- until that
  transport step is separately updated to also drop a manifest, the
  DEFAULT observed behavior for an actual REVIEW-00x handoff is unchanged,
  and `test_slow_writer_pausing_longer_than_quiet_interval_can_still_be_
  consumed_mid_sequence` continues to pass, proving the underlying
  characteristic remains real and current. Codex's own recommended action
  (producer atomic rename, or this sealed-manifest marker) is fundamentally
  a TRANSPORT-CONTRACT change involving an external producer this session
  does not control -- disclosed as a genuine scope boundary, not silently
  left unaddressed.
- R005-1's fix narrows the takeover race to the same residual PID-reuse
  availability risk Codex's own REVIEW-005 `UNKNOWN_ITEMS` already
  disclosed (a different live process can later reuse an abandoned owner's
  pid) -- unrelated to and unaffected by this fix, since that risk lives in
  `_pid_alive()`'s OS-level liveness semantics, not in the compare-and-
  delete this fix adds.
- R005-3's fix requires the FULL fixed schema to be present; a future,
  legitimate schema addition to `register_expected_result()`'s own fields
  must update `_REGISTRATION_SCHEMA_FIELDS` in lockstep, or a real
  registration written by an older code version would itself be classified
  `MALFORMED_REGISTRATION` after an upgrade. Not exercised by any current
  test; disclosed as a forward-compatibility note for that future change.
- The live spawned-worker qualification remains open; see
  `L5DGVA_CONTROLLED_CLAUDE_WORKER_PERMISSION_QUALIFICATION.md`.

Status: `FIXED_AND_VERIFIED_BY_AUTHOR` (R005-1 CRITICAL, R005-3 MEDIUM
fully closed; R005-2 HIGH genuinely narrowed via an opt-in mechanism, not
fully closed -- disclosed above); `PENDING_INDEPENDENT_REREVIEW`.
