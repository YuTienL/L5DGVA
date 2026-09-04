# Gap close: AI mechanism #11 Session Save/Restore

**Status: DONE**

Audit verdict was PARTIALLY_WIRED with one concrete, in-scope gap: the evidence
store (`.dv-harness/evidence/`, `evidence_db.py`'s real `evidence_id`-keyed
DuckDB) was named in NONE of `session_snapshot.py`'s four capture lists, so
every save silently dropped the field the user's required list calls
"Evidence IDs". Everything else on that list was already really captured and
really restored. The fix is a wiring fix, not a new mechanism.

## Gap re-confirmed independently, before changing anything

- `grep evidence dv_harness/session_snapshot.py` — zero hits in `SESSION_FILES`,
  `SESSION_DIRS`, `SESSION_EXTRA_DIRS`, `SESSION_ARTIFACT_REFERENCE_DIRS`.
- This repo's own real snapshot `.dv-harness/sessions/2026-08-30_usb_gap_closing_progress/`
  contains `agents blackboard config.json control.json events.jsonl lsf plans
  react session_manifest.json state.json telemetry` — no `evidence`.
- Live negative reproduction against the real functions (pre-fix code path
  simulated by removing the entry again): write a real `normalized_evidence`
  row through `evidence_db.EvidenceStore`, `save_session()`, delete
  `.dv-harness/evidence/`, `restore_session()` → manifest `dirs` was
  `['blackboard','plans','react','agents','telemetry']` and the DB **did not
  come back**. So the new tests genuinely fail without the fix.
- `git status` on all three target files was clean before editing — no
  concurrent workstream had touched them.

## What changed

`dv_harness/session_snapshot.py` (the only production file touched):

1. **`"evidence"` added to `SESSION_DIRS`** — Ruling 3, documented in place
   alongside the existing Rulings 1/2. It rides the existing generic
   `copytree` loop in `save_session()` and the existing generic
   `rmtree`+`copytree` loop in `restore_session()`; no parallel capture path
   was built, and `restore_session()` needed no new manifest key to find it.
2. **Write-safety, scoped to `SESSION_BEST_EFFORT_DIRS = {"evidence"}`** —
   it is the one entry that is not plain JSON but a live DuckDB file real
   production callers hold open (`regression_reporter.py`'s
   `with EvidenceStore(db_path) as store:`, `mcp/runtime.py`). A copy or a
   restore-rewind failure now costs that one directory and is recorded with
   its reason (`manifest["dirs_copy_skipped"]`,
   `restore_session()["dirs_restore_skipped"]`) instead of taking the whole
   snapshot/restore down. Every other `SESSION_DIRS` entry still raises on
   failure — a snapshot silently missing `blackboard` would be worse than no
   snapshot. Restore is best-effort for the same entry specifically so a
   locked DB cannot leave a **partial** rollback behind.
3. **Size guard (`EVIDENCE_DIR_COPY_SIZE_LIMIT_BYTES`, 64 MB)** — added on
   own judgment beyond the audit's plan, because `save_auto_checkpoint()`
   fires at every stage transition with 10 retained: an unbounded wholesale
   copy there is exactly the disk-doubling Ruling 2 already exists to prevent.
   Over the limit the directory is recorded as a real path+size+sha256
   REFERENCE (reusing `_hash_file()`, Ruling 2's own shape) rather than
   dropped. This repo's real store is 2.1 MB, so the limit is a ceiling for a
   pathological case, not a routine path.

Documented ruling, stated rather than glossed: restore rewinds this directory
wholesale, which does rewind `evidence_db.py`'s deliberately append-only
`regression_verdict_history`. Accepted, because `restore_session()`'s own
`_pre_restore_` auto-backup captures the newer store first — the same safety
net every other destructive directory restore here already relies on. Asserted
by a test.

## Verification

Nine new tests in `dv_harness_tests/test_session_and_info.py`, all against the
real functions and a real DuckDB (never a mock or a stubbed store):

- real `evidence_id` survives save → **delete the live directory** → restore,
  read back through a real `EvidenceStore(read_only=True)`;
- **the production entry point**: `save_auto_checkpoint()` — what
  `engine.run_stage()` actually calls at every terminal exit — captures a real
  evidence row, not just `save_session()`;
- restore is a rollback not a merge (post-checkpoint row gone, checkpoint row
  back, discarded row recoverable from the `_pre_restore_` backup);
- `"evidence" in SESSION_DIRS` and in a fresh manifest's `dirs`, matching how
  `lsf`/`blackboard` are already covered;
- absent evidence dir reports absent, not skipped;
- oversized dir → real sha256 reference, not copied, and restore leaves the
  live store untouched;
- a simulated `PermissionError` (Windows "file in use") on evidence records
  why and still captures `blackboard`/`state.json`;
- the same failure on `blackboard` still raises;
- a locked evidence DB never aborts a restore midway.

Also verified on this project's own live tree: a real `save_session()` here
now reports `dirs: [... 'lsf', 'evidence']`, `dirs_copy_skipped: {}`, and the
snapshot's 2,109,440-byte `evidence.duckdb` opens read-only and queries
(temporary session deleted afterwards).

**Test summary: 191 passed, 0 failed** — `test_session_and_info.py` (43),
`test_harness_reliability.py` + `test_active_stages_read_sites.py` +
`test_evidence_db.py` (80), `test_obsidian_memory_final_integration.py` +
`test_dashboard_interactive.py` (68).

## Not in scope / not done

The audit's own framing of the two analysis items (generic multi-protocol
scope, subsystem-to-SoC generation) is untouched here. No CLI or dashboard
change was needed: both already `json.dumps` the whole manifest/result, so the
two new keys surface without edits.
