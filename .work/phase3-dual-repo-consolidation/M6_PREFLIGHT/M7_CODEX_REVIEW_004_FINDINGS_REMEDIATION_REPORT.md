# M7 Codex REVIEW-004 Findings Remediation Report

`TASK_ID=M7-V1-CODEX-REVIEW-004`, `RESULT_STATUS=FAIL`, auto-ingested by the
real detached watcher (armed 3 days earlier) with zero manual intervention
across the gap -- see `M7_CLAUDE_WORKER_LIVE_QUALIFICATION.md`'s own "Live-fire
attempt" section for the full timeline. Original `RESULT_V1.md` (sha256
`59099ec77a93820819cd2ef52ff4f4784f2a2f63768d5265e9ce61b5b5df9127`) was never
edited.

## Who performed this remediation, and why (disclosed up front)

The Autonomous Agent Execution Backend built earlier in this same task was
used to build a real `AgentRunRequest` and attempt a real `launch_worker()`
call against this exact FAIL result. **That launch was refused by this
Claude Code installation's own auto-mode permission classifier** (reason:
`"Create Unsafe Agents"`), before any subprocess started -- a genuine,
platform-level `SAFE_EXECUTION_BLOCKED` condition, not an L5DGVA governance
decision, and not something retried through another tool/subagent/encoding
per that denial's own explicit instructions. Full detail:
`M7_CLAUDE_WORKER_LIVE_QUALIFICATION.md`.

Prime Directive V2 P5 forbids leaving a confirmed current-scope defect as
`DOCUMENT_ONLY`. Since the specific blocked action was "spawn a new
autonomous worker process," not "edit code in the current interactive
session" (which has been sanctioned and exercised throughout this entire
task), the remediation below was performed directly by the orchestrating
session -- the same mechanism that fixed R1-R8 and N1-N6 in the two prior
review rounds. **This is disclosed honestly: the live worker-launch
qualification remains unproven this task; only the underlying findings
were fixed.**

## Independent reproduction (pre-fix, current production code)

| ID | Claim | Reproduction | Confirmed |
|---|---|---|---|
| R004-1 (CRITICAL) | Manual/shared ingestion front door bypasses registration/path/symlink/stability checks | Direct code inspection of `_ingest_locked()`: `path.read_bytes()` runs immediately with no comparison to `_expected_path()`, no `expected_result.json` check, no symlink/parent/stability check; the CLI `import` verb passes `args.result_file` straight through | YES |
| R004-2 (HIGH) | Lock takeover proves ownership by age alone; release is owner-blind | Direct inspection of `_acquire_lock()`/`_release_lock()`: content was a bare pid, staleness check compared only file mtime, `_release_lock()` unlinked by pathname with no ownership check | YES |
| R004-3 (HIGH) | `registry.csv` writes across different tasks are unlocked | Direct inspection: only a per-task `import.lock` existed; `_append_registry()`/`_ensure_registry_schema()` had no lock of their own, and the migration used a single fixed `.migrate.tmp` name | YES |
| R004-4 (MEDIUM) | Reconciliation labels the currently-supplied hash CONSUMED without checking it against the real consumed identity | Direct inspection of the `RECONCILED_FROM_WORKFLOW_STATE` branch: it unconditionally trusted the newly observed hash | YES |

## Fixes

| ID | Fix | Files | Tests (`test_model_handoff_review004_remediation.py`) |
|---|---|---|---|
| R004-1 | `ingest_result_file()`/`_ingest_locked()` fail closed by default: `_unsafe_manual_path_reason()` requires a real `expected_result.json`, requires `path.resolve() == _expected_path().resolve()`, requires a real non-symlink file whose resolved parent is the task directory and is non-empty, and (for non-`AUTO` triggers) requires a real synchronous two-snapshot stability check (`_synchronous_stability_check()`). A new, explicit, separately-auditable `allow_unregistered_path=True` override exists for documented recovery. The `AUTO` watcher path is unaffected (it already supplies the exact registered path and was already stability-checked by `poll_once()`). | `dv_harness/result_ingestion.py` | `test_arbitrary_unregistered_path_is_refused_by_default`, `test_manual_import_cli_verb_refuses_an_arbitrary_result_file`, `test_ingestion_with_no_registration_at_all_is_refused`, `test_symlinked_manual_path_is_refused`, `test_empty_manual_result_file_is_refused`, `test_manual_partial_write_is_refused_by_the_synchronous_stability_check`, `test_the_real_registered_expected_path_is_still_accepted_manually`, `test_explicit_override_still_permits_a_documented_recovery_path`, `test_auto_watcher_path_is_unaffected_by_the_new_gate` |
| R004-2 | `_acquire_lock()` now writes a real unique ownership token (`<uuid4>:<pid>`) and returns it (never a bare bool); a stale-timeout takeover additionally requires the recorded owner pid to be provably dead (`_pid_alive()`, the same real OS-level check `agent_execution_backend.py` uses, reimplemented locally to avoid a backwards layering dependency); `_release_lock()` now takes the caller's own token and only unlinks the file if its content still matches it. Both call sites (`import_result`'s own lock, `result_ingestion._task_lock`) updated. | `dv_harness/model_handoff_workflow.py`, `dv_harness/result_ingestion.py` | `test_lock_carries_a_real_unique_owner_token_not_a_bare_pid`, `test_release_cannot_remove_a_lock_it_does_not_own`, `test_stale_takeover_requires_the_recorded_owner_to_be_provably_dead`, `test_stale_takeover_succeeds_only_once_the_owner_is_provably_dead`, `test_a_third_writer_cannot_be_admitted_by_two_sequential_owner_blind_releases` |
| R004-3 | New `_registry_lock()` (a dedicated `registry.csv.lock`, same ownership-token primitive, short bounded retry since this is ordinary mutual exclusion between legitimately-concurrent different-task writers) wraps the ENTIRE `_append_registry()` body (idempotency re-check + schema migration + row append) as one atomic critical section; `_ensure_registry_schema()`'s migration now uses a unique per-call temp filename (`registry.csv.migrate.<pid>.<uuid8>.tmp`) instead of one fixed shared name. | `dv_harness/model_handoff_workflow.py` | `test_two_different_tasks_consuming_concurrently_each_get_exactly_one_row` (3 real threads, real concurrent imports), `test_registry_migration_uses_a_unique_temp_filename`, `test_registry_lock_serializes_concurrent_appends_without_a_shared_fixed_temp_name` |
| R004-4 | New `_real_consumed_digest()` reads the real persisted consumed identity (workflow state's `result_sha256`/`accepted_result_sha256`, else the registry row's `result_sha256` column). The reconciliation branch now: matches -> reconcile as CONSUMED (`RECONCILED_DIGEST_VERIFIED`); mismatches -> quarantine the observed hash (`RECONCILIATION_DIGEST_MISMATCH`) instead of mislabeling it; no real digest recorded at all (pre-digest-era state) -> honest fallback to the prior behavior, explicitly labeled `RECONCILED_FROM_WORKFLOW_STATE`. | `dv_harness/result_ingestion.py` | `test_reconciliation_matches_the_real_persisted_consumed_digest`, `test_reconciliation_quarantines_a_hash_that_does_not_match_the_real_consumed_digest`, `test_reconciliation_without_any_persisted_digest_falls_back_honestly` |

## Verification

- 20 new tests, all pass; 4 independent mutation controls (disable the
  path-registration check, disable the lock-owner check, disable the
  registry lock, disable the reconciliation-digest check) each fail a real
  test.
- 397 tests pass across the full M7 handoff/result/ingestion/contract/router/
  backend/governance suite. Constitution gate PASS. Frozen sources
  (Parent/v50/b7a/b7b/b8) unchanged.
- `test_two_different_tasks_consuming_concurrently_each_get_exactly_one_row`
  is a REAL concurrency test (3 real `threading.Thread`s importing 3
  different tasks at once against the same `registry.csv`), not a
  simulated race -- it is the closest this task came to actually exercising
  R004-3's own named scenario live, and it passes cleanly with the fix and
  fails without it.

## Disclosed limits

- R004-2's fix does not make the lock a distributed/cross-host primitive --
  it is still a single local file with a real pid-liveness check, correct
  for this project's single-host worker model (matching
  `agent_execution_backend.py`'s own Canonical Mutation Lease, which has the
  identical disclosed limitation).
- R004-1's synchronous stability check adds real wall-clock latency
  (`policy.quiet_seconds`, default 2.0s) to every non-`AUTO` ingestion call
  -- a deliberate, disclosed trade-off (safety over a small manual/recovery
  latency cost), not something silently absorbed.
- The live spawned-worker qualification this capability exists to prove
  remains open; see `M7_CLAUDE_WORKER_LIVE_QUALIFICATION.md`.

Status: `FIXED_AND_VERIFIED_BY_AUTHOR`; `PENDING_INDEPENDENT_REREVIEW`
(`M7-V1-CODEX-REVIEW-005`).
