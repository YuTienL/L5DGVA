# Gap close — Phase 13 (Git Integration policy) + Phase 14 (Session Save/Restore, memory-specific)

**Verdict: DONE.** Both phases re-confirmed READY against the audit's own cited
evidence. One real, closeable gap the audit named *inside* its Phase 13 READY
verdict — "the total absence of a retry/log-and-surface path when a commit was
expected but silently didn't happen" — was built for real, tested, and
committed (`2dac81d`).

Audit-only re-confirmation, no modification, for everything else.

---

## 1. Re-confirmation of the READY items (no change made)

Line numbers in the incoming audit had shifted since it was written (concurrent
Phase 18/19 work landed in `memory_router.py`). Every claim was re-verified
against the file as it stands, not against the cited line.

### Phase 13

| Requirement | Re-confirmed at | Result |
|---|---|---|
| Commit only on verified Job result / Project update / Engineering promotion / Organizational approval — **never** on a Working Memory update | `dv_harness/memory_router.py:122` `_VAULT_WRITE_THROUGH_DESTINATIONS = {"JOB_MEMORY", "PROJECT_MEMORY"}`, with the spec's negative satisfied by construction (comment at `:106-121`); `ORGANIZATIONAL_MEMORY` writes only `if push.get("ok")` (`:248`), `ENGINEERING_MEMORY` only after `engineering_admission_gate()` (`:253` → `:281`); `WORKING_MEMORY` reaches no vault branch | READY |
| Commit message `memory(<protocol>): <short description>` | `memory_router._build_vault_commit_message()` (now `:851-855`) | READY |
| RTL SHA / TB SHA / Knowledge commit SHA preserved | `memory_vault.MEMORY_NOTE_OPTIONAL_FIELDS`; `_commit_vault_change()` returns a real `git rev-parse HEAD`; `_write_back_knowledge_commit_sha()` (now `:935`) patches the same JSON record | READY |

Re-run live on this machine (not a mock, `git_enabled: true`), fresh tmp vault:

```
{"destination": "ENGINEERING_MEMORY", "memory_id": "MEM-9F69D1EBD3",
 "vault_write": {"ok": true,
   "knowledge_commit_sha": "bf3f70c1220184db98b0f7aeaa2ecec70f485e47", ...}}
```
```
$ git log --oneline   # in the resulting vault
bf3f70c memory(USB2): reconfirm phase13
```

### Phase 14

All seven required Save fields re-confirmed real and sourced from live react/job
state in `dv_harness/session_snapshot.py:608-626` — `current_project` (`:612`),
`current_job` (`:613`, via `_collect_current_job_reference()`),
`current_hypothesis` (`:614`), `current_evidence` (`:615`),
`current_confidence` (`:616`), `pending_action` (`:617`), `related_memory`
(`:618`, via `_resolve_related_memory_references()` at `:410-446`).

Restore's four-question contract re-confirmed in `describe_resume_point()`
(`:449-493`), including the provenance wording that keeps
`react_iteration_memory_context` distinguishable from
`recomputed_at_save_time` (`:478-483`) and the honest no-`pending_action`
fallback (`:488-492`) instead of a fabricated next step.

**No change made to Phase 14.** Per this effort's own rule, its
really-consulted-vs-recomputed distinction is more rigorous than the spec's
wording asks for and was kept rather than simplified.

---

## 2. The gap that was closed

**What was wrong.** `memory_vault._run_git()` swallowed every exception and
returned `None`. A `subprocess.TimeoutExpired` at the 10s cap under machine
load, or a momentarily-held `index.lock`, therefore produced exactly the same
observable result as the ordinary, expected "there was nothing to commit": a
result dict with no `knowledge_commit_sha`, no error, no retry. A verified
Engineering promotion could lose its traceability pointer with nothing anywhere
recording that it had. The audit reproduced this live once
(`knowledge_commit_sha == None` on a promotion whose vault note was genuinely
new — a case where NOTHING_TO_COMMIT is impossible).

**What was built** (`dv_harness/memory_vault.py`, `dv_harness/memory_router.py`):

- `_run_git_ex()` — keeps the exception's reason instead of discarding it.
  `_run_git()` is now a thin wrapper over it, so its non-commit callers
  (`_ensure_git_repo()`, `memory_doctor.check_git()`, `cli.py`'s
  `memory vault-commit`) keep their exact prior `Optional[CompletedProcess]`
  contract.
- `_commit_vault_change_detailed()` — retries a transient failure
  (`_GIT_COMMIT_ATTEMPTS = 3`, 0.2s backoff) and reports one of four outcomes
  instead of an Optional SHA:

  | status | meaning |
  |---|---|
  | `COMMITTED` | real commit, real `git rev-parse HEAD` |
  | `NOTHING_TO_COMMIT` | the write changed no bytes — returns at attempt 1, never burns the retry budget |
  | `COMMITTED_SHA_UNRESOLVED` | the commit really landed; only reading its SHA back failed. Its own state, because calling this a failed commit would be a false claim about the repo |
  | `COMMIT_FAILED` | expected commit did not happen; carries git's own bounded error text |

  Never fabricates a SHA. `_commit_vault_change()` keeps its `Optional[str]`
  contract for existing callers.
- `apply_commit_outcome()` — surfaces the outcome as `knowledge_commit_status`
  (+ `knowledge_commit_error` / `knowledge_commit_attempts`) on every provider
  result, so it reaches `route_and_store()`'s `vault_write` unchanged. Also
  wired into `_fold_into_matched_note()`, which was copying only the SHA — the
  fold path writes no note of its own and so was the write most likely to stay
  silent about a failure.
- `_write_back_knowledge_commit_sha()` — writes a `COMMIT_FAILED` back onto the
  durable JSON record. `COMMITTED` and `NOTHING_TO_COMMIT` are deliberately not
  written back as a status (the first is fully carried by the SHA itself, the
  second is the ordinary outcome of a re-write that changed nothing).

**Explicitly unchanged:** with `git_enabled: false` — this project's documented
default — a result carries none of these keys at all. Git being off is not a
commit failure, the same distinction `memory_doctor.check_git()` already makes.

Live demonstration of the closed gap (git commit forced to fail):

```
VAULT_WRITE: {"ok": true, "knowledge_commit_status": "COMMIT_FAILED",
              "knowledge_commit_error": "TimeoutExpired: git commit timed out after 10 seconds",
              "knowledge_commit_attempts": 3}
RECORD:      {"knowledge_commit_status": "COMMIT_FAILED",
              "knowledge_commit_error": "TimeoutExpired: git commit timed out after 10 seconds"}
```

The note itself still landed — a git failure never costs the knowledge, it only
had to stop being silent about itself.

---

## 3. Items deliberately left alone

- **`JOB_MEMORY` not gated on a `verified` flag inside `route_memory()`.** The
  audit called this "a real, closeable gap in strictness … not currently
  exploited by any real code path". Left as-is: it is a disclosed, reasoned
  divergence documented at `memory_router.py:115-121`, the only two real
  writers fire from an already-reconciled LSF/gate fact, and forcing a literal
  `verified=True` gate would change real behaviour to match spec wording the
  existing design already satisfies in substance. Per this effort's rule 3,
  reported rather than rebuilt.
- **`FileSystemMarkdownAdapter`'s generic default commit messages**
  (`memory-vault: create <id>`) for direct, non-router callers. Documented
  intentional non-change; format compliance is a router-level guarantee.
- **`ORGANIZATIONAL_MEMORY` excluded from the SHA write-back.** It has no local
  file-store record to patch by design (`OrganizationalMemoryStore`).

---

## 4. Tests

New, each with real detection power (real repos, real `git log`, real
`route_and_store()`, never a mocked success):

`dv_harness_tests/test_debug_flow_memory.py`
- `test_a_transient_git_failure_is_retried_and_the_retry_really_commits` —
  fails the first `git commit` for real, asserts `attempts == 2` and that the
  retry's SHA equals the repo's actual `git rev-parse HEAD`.
- `test_a_persistent_git_failure_is_reported_as_COMMIT_FAILED_with_the_real_reason`
- `test_nothing_to_commit_is_its_own_status_and_is_never_retried`
- `test_a_silently_failed_vault_commit_now_reaches_route_and_store_and_the_durable_record`
- `test_a_successful_promotion_records_the_sha_and_no_failure_status`
- `test_a_git_disabled_vault_write_carries_no_commit_keys_at_all`
- `test_the_sha_only_helper_keeps_its_prior_optional_str_contract`

`dv_harness_tests/test_memory_dedup_write_path.py`
- `test_a_folded_write_reports_a_failed_commit_instead_of_swallowing_it`

**Results (all real runs this session):**

| Suite | Result |
|---|---|
| `test_debug_flow_memory` + `test_knowledge_layer_git_and_duckdb` + `test_memory_dedup_write_path` + `test_memory_vault` (final code) | **102 passed** in 159.90s |
| 11-file memory/vault/session suite (incl. `test_cli_memory_commands`, `test_memory_doctor`, `test_memory_security`, `test_obsidian_memory_final_integration`, `test_session_and_info`) | **262 passed** in 822.89s |
| `test_react_working_memory_bridge` + `test_memory_write_guard_and_job_evidence` + `test_job_memory_evidence_mirror` | **42 passed** in 225.17s |
| `test_memory_docs_mirror_source` + `test_memory_tier_completion` | **26 passed** in 29.47s |
| `python -m dv_harness.doc_citation_check` | 8 citations, **8 OK, 0 drifted** |

---

## 5. Housekeeping done in the touched files

- `docs/MEMORY_ARCHITECTURE.md` gained a "Vault commit outcomes" section
  documenting the four statuses and the retry, per the Methodology
  Consolidation Rule.
- Two `memory_router.py:NNN` citations in that same doc had drifted from my own
  line-number shift and were corrected (`1098 → 1124`, `962 → 988`);
  `doc_citation_check` was clean before my change and is clean again.
- Stale comment text in `memory_vault.py`'s module changelog (which described
  `_commit_vault_change()` as returning only a SHA) was updated rather than left
  behind. No dead code introduced: `_run_git()` and `_commit_vault_change()`
  both still have real callers.

## 6. Scope discipline

Concurrent agents hold `dv_harness/cli.py`, `dv_harness/engine.py`,
`dv_harness/connectivity.py` and several test files. None were touched. The
commit stages exactly five files, all of which were clean in `git status`
before this pass began.

**Commit:** `2dac81d memory(_general): report a vault commit that was expected
and silently did not happen`
