# Gap-close: Phase 11 + 12 + 19 (Regression Integration / Large Artifact Policy / Security)

Date: 2026-09-04
Scope: one gap-closing pass over the fresh audit's Phase 11, 12 and 19 verdicts.
Mode: LOCAL_ANALYSIS (no server, no VCS/simulation).

## Result: DONE

One real, closeable gap existed (Phase 19). It is closed, tested and committed
as `ba68716 memory(security): guard the organizational tier before it reaches
the shared broker`.

Test summary: 291 passed across the 14 memory-related test modules
(`test_memory_write_guard_and_job_evidence`, `test_memory_security`,
`test_memory_tier_completion`, `test_memory_tier_integrity_and_admission`,
`test_memory_vault`, `test_memory_dedup`, `test_memory_doctor`,
`test_debug_flow_memory`, `test_job_memory_evidence_mirror`,
`test_knowledge_center`, `test_cli_memory_commands`,
`test_obsidian_memory_final_integration`, `test_react_working_memory_bridge`,
`test_memory_search_filters`), plus 17 passed in `test_doc_citation_check`.

---

## Phase 11 — Regression Integration: **READY** (re-confirmed, no action)

Every cited line was independently re-checked against the current tree; the
audit's evidence holds. Line numbers below are current.

- `lsf_client._write_job_tier_memory_on_terminal_reconcile()` at
  `dv_harness/lsf_client.py:926`, called from the real reconcile at
  `lsf_client.py:1245`.
- `_upsert_job_tier_memory_record()` at `lsf_client.py:1055` is the single
  persistence body; the record is keyed by `job_tier_memory_id(jid)`
  (`lsf_client.py:667`, used at `:1106`), so repeated reconciles upsert rather
  than duplicate.
- Spec-named fields all present and sourced from real `JobState`:
  `job_id`/`pattern` (`:1108-1109`), `lsf_status` (`:1112`) kept separate from
  `dv_result = state.sim_status` (`:1130`) per CLAUDE.md's "LSF DONE is not
  equal to DV PASS", `uvm_error_count`/`uvm_fatal_count` (`:1114-1115`),
  `root_cause_status`/`fix_proposal_status` (`:1128-1129`).
- `confidence`/`confidence_basis` come from a real
  `_score_job_memory_confidence()` (`lsf_client.py:986`) — independent-source
  count, path-exists check, counter-evidence — not a constant.
- `failure_signature` + `prior_related_knowledge` are written only when
  `is_failure` (`:1198`), via `memory_vault.build_failure_signature()` /
  `search_related_memory_for_debug()` — the same shared interface
  `engine.py`'s FAILURE_RECOVERY uses, not a second copy.
- **"Always re-verify, never blindly copy" is wired, not merely commented**:
  `prompts.py:2940-2946` folds `vault_related_cases` into the real
  FAILURE_RECOVERY prompt, and `prompts.py:2944` emits the explicit
  disclaimer text `current evidence 永遠優先於這裡任何一筆記錄；不得直接假設
  previous root cause == ...` into the prompt body.
- `route_and_store()` at `lsf_client.py:1222` is best-effort and cannot break
  the reconcile.

No change made.

## Phase 12 — Large Artifact Policy: **READY** (re-confirmed, no action)

- `dv_harness/memory_artifact_policy.py` is the single policy home:
  `FORBIDDEN_ARTIFACT_EXTENSIONS` at `:50`, `LARGE_FILE_SIZE_BYTES`/
  `HUGE_LOG_SIZE_BYTES` at `:54-55`.
- Wired at write time through `memory._guard_record_before_write()`
  (`memory.py:13`, importing at `:7-8`, applying at `:40` and `:44`), which
  `MemoryStore.add()` calls at `memory.py:251` and `CornerCaseLibrary.add()`
  at `memory.py:676`. `MemoryStore.add()` returns the guarded record, which is
  what every vault write-through then mirrors.
- HARD REJECT (`EmbeddedArtifactError`, `:92`) for a NUL byte or
  `$enddefinitions` + `$dumpvars` — raised, never repaired
  (`_binary_artifact_reason`, `:99`).
- TRUNCATE-with-disclosure (`_truncate_oversized`, `:116`) keeps head **and
  tail** (a sim.log's UVM epilogue is at the end) and stamps
  `large_artifact_truncated` on the record.
- `build_evidence_reference()` (`:184`) is the one builder for
  `evidence: {sim_log, fsdb, coverage, lsf_job}` (+`run_dir`), paths/ids only —
  a multi-line or >`MAX_EVIDENCE_REFERENCE_CHARS` value raises. Its only real
  caller is `lsf_client._upsert_job_tier_memory_record()` (`:1170-1180`).
- `coverage` is honestly OMITTED (no per-job coverage-DB path producer exists
  in this repo) rather than written as a null placeholder — asserted by an
  existing test.

No change made. (This phase's policy is what the Phase 19 fix below extends to
one further destination — the policy module itself needed nothing.)

## Phase 19 — Security: **PARTIAL → closed**

### What was confirmed already real (no change)

1. Hard REJECT-by-kind: `memory_router.route_memory()` `:577-578` returns
   `"REJECT"` for `credential/password/token/secret`; `route_and_store()`
   `:126-127` raises `ValueError` on it — nothing is persisted. Exactly what
   CLAUDE.md's Engineering Memory Policy claims.
2. Real pattern-based REDACTION: `memory_security.SECRET_PATTERNS` (12 real
   regexes) via `redact_record()` inside `_guard_record_before_write()` for
   every JSON store write, and `redact_note_content()` inside
   `memory_vault.FileSystemMarkdownAdapter.create()`/`update()`
   (`memory_vault.py:899`, `:948`) for the Markdown mirror. Both run before
   write and stamp `secrets_redacted`/`secrets_redacted_types` rather than
   silently mutating. The re-redaction idempotency guard
   (`_ALREADY_REDACTED_VALUE_RE`, `memory_security.py:113`) is real.

### The gap (confirmed by direct read, not assumed) and what closed it

`OrganizationalMemoryStore.add()` was the one write path in `memory.py`
reaching durable storage without the guard. It forwarded the caller's record
verbatim to `KnowledgeCenterClient.add()` (`knowledge_center.py:193`), and a
repo-wide grep for `redact_record` / `enforce_record_artifact_policy` returned
zero hits anywhere on that path. This is the most exposed destination in the
system, not the least: that tier deliberately has no local file store, so the
Knowledge Center on the Linux server IS its backing store — an unredacted
secret there reaches every other user's harness. `route_memory()` `:614-615`
routes `methodology`/`best_practice`/`cross_project_lesson` + `verified=True`
straight there, so a plain `route_and_store()` call reached it unguarded.
`promote_to_organizational()` was safe only incidentally, by copying fields
off an already-guarded engineering-tier record.

**Closed in two places** (commit `ba68716`):

- `dv_harness/memory.py` — `OrganizationalMemoryStore.add()` now runs
  `_guard_record_before_write()` before the push. This is the chokepoint, so a
  caller that constructs the store directly (as every other
  `KnowledgeCenterClient` consumer does) is covered too, not just the router
  branch. Guarding before the push means an `EmbeddedArtifactError` aborts the
  push rather than shipping raw waveform content to a shared server.
- `dv_harness/memory_router.py` — the `ORGANIZATIONAL_MEMORY` branch rebinds
  `record` to the guarded form so the vault note mirrors byte-identical
  content to what was pushed. Without it this destination was the only one
  whose Markdown note was rendered from an unguarded record (every other
  vault-write-through branch passes the guarded record `MemoryStore.add()`
  returns), so a log truncated out of the shared push would have survived in
  full inside the vault note — the exact thing CLAUDE.md forbids "in a memory
  record or vault note". The second guard call is a documented no-op: the
  guard is idempotent by construction.

### Tests written (6 new, in `dv_harness_tests/test_memory_write_guard_and_job_evidence.py`)

`TestPhase19OrganizationalMemoryIsGuardedBeforeTheSharedPush`. Four of them
assert on the payload that genuinely went **onto the wire**, captured by a real
local relay server (`_FakeKnowledgeCenterRelay`, the same transport pattern
`test_knowledge_center.py` and `test_memory_tier_completion.py` already use) —
not on what a mocked `KnowledgeCenterClient.add()` was handed. That distinction
is the point: the gap was a raw record crossing a machine boundary.

1. `test_a_secret_never_reaches_the_shared_broker_over_the_wire` — a VCPW
   password and an SSH PEM block, one of them nested inside `evidence`, are
   both absent from the uploaded payload and replaced by typed markers;
   `secrets_redacted_types == {vc_password, ssh_private_key}`.
2. `test_a_giant_log_is_truncated_with_disclosure_before_the_shared_push` —
   the uploaded field is under both caps, carries the in-band truncation
   marker, still contains the sim.log tail epilogue, and is disclosed via
   `large_artifact_truncated`.
3. `test_embedded_waveform_content_hard_rejects_and_nothing_is_pushed` —
   `EmbeddedArtifactError` raises and `KnowledgeCenterClient.add` is never
   called: zero transport contact, no partial record on the shared server.
4. `test_the_store_guards_even_when_called_directly_not_through_the_router` —
   proves the chokepoint is the store, not the router branch, and that
   protocol routing off the record is unchanged.
5. `test_the_vault_mirror_carries_the_same_guarded_content_that_was_pushed` —
   the record handed to `_maybe_write_vault_note()` equals the pushed one.
6. `test_guarding_an_already_guarded_record_changes_nothing` — the
   double-guard is a genuine no-op, never a `***REDACTED-***` inside another
   marker.

**Proven non-vacuous**: with the two source hunks reverted, 5 of the 6 fail
(the 6th is an idempotency property of the pre-existing guard and passes
either way). Restored and re-run: 32 passed in that file.

### Documentation touched

`docs/MEMORY_ARCHITECTURE.md`'s "The write-time guard" section listed only
`MemoryStore.add()` and `CornerCaseLibrary.add()`; it now names the third path
and explains why that one matters most. While there, five drifted
`file.py:line` citations were corrected across `MEMORY_ARCHITECTURE.md` and
`MEMORY_SCHEMA.md` — **three of the five were already stale before this
change** (`memory.py:783-789`, `memory.py:576`, `memory_router.py:571`), i.e.
`test_doc_citation_check.py::test_real_memory_docs_have_no_drifted_citations`
was already failing on HEAD; two were caused by this change's line shift.
`python -m dv_harness.doc_citation_check --memory-docs` now reports
`8 OK, 0 drifted, 0 unverifiable` and that test file is 17/17 green.

---

## Notes for whoever reads this next

- No CLAUDE.md change was needed. Its Engineering Memory Policy already states
  the two "Never" rules this fix enforces; the fix made the enforcement cover
  the last destination that had escaped it, so the prose was already true of
  intent and is now true of code.
- A concurrent workflow's in-flight `.claude/` edits caused a transient
  failure of
  `test_engine_gates_and_routing.py::test_self_audit_against_real_repo_reports_real_current_findings`
  during one run of this pass. Re-running it alone passes (24s), and
  `python tools/verification_flow/agent_skill_binding_gate.py --root .` returns
  `{"status": "PASS"}`. Unrelated to this change, which touches no skill or
  agent file.
- Other agents concurrently modified `dv_harness/cli.py`, `engine.py`,
  `gates.py`, `prompts.py` and `test_engine_gates_and_routing.py`. None of
  those overlap this change's five files, so the commit was staged file-by-file
  and contains nothing else.
