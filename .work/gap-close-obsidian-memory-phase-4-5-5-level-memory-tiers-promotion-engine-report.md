# Gap close — Phase 4+5: 5-Level Memory tiers + Promotion Engine

**Status: DONE**
**Date:** 2026-09-03/04
**Scope:** the three PARTIAL sub-findings of the Phase 4 / Phase 5 audit. The
two READY verdicts were re-confirmed against their cited evidence and left
untouched.

---

## 1. Re-confirmation of the READY items (no action taken)

| Audit claim | Re-checked | Result |
|---|---|---|
| `MEMORY_LEVELS = ["working","job","project","engineering","organizational"]` | `dv_harness/memory.py:7` | confirmed |
| `WorkingMemoryStore`/`JobMemoryStore`/`ProjectMemoryStore` real thin wrappers; `OrganizationalMemoryStore` delegates to the shared Knowledge Center by design | `memory.py` `_TierMemoryStore` and following classes | confirmed |
| `route_memory()` pure dispatcher; `route_and_store()` the real entry point | `memory_router.py` | confirmed |
| Engineering→Organizational 3-gate promotion (`_verification_is_gate_validated` + `score_confidence()=="HIGH"` + `confirmation_count >= 2`) | `memory_router.promote_to_organizational()`; `test_case_08` in `test_obsidian_memory_final_integration.py` | confirmed, still passing (and now additionally covers the org gate with a store-seeded record — see §4) |
| Tier populations real on disk | `python -m dv_harness.memory_cli --project-root . index-check` | confirmed: working 14, job 1, project 46, engineering 31, organizational 0 (by design) |

---

## 2. Gap A — Job-tier field completeness → CLOSED

The audit found the spec's own named Job Memory fields (start/end time,
command, timeout, fix attempt, result) present on the source data but never
reaching the persisted record, and three `LsfStatus` values that no code path
could produce.

**`dv_harness/lsf_client.py`**

- `JobState` gained five real fields: `command`, `runlimit_minutes`,
  `submit_time`, `run_time`, `observed_terminal_at`. Mirrored into
  `.dv-harness/lsf/job_state_schema.json` (the file this module's own
  docstring says its field names follow exactly).
- `reconcile_job()` now captures LSF's own `SUBMIT_TIME`/`RUN_TIME` from the
  bjobs record — **already requested by `_run_bjobs()`'s `-o` list and
  discarded by every caller until now** — verbatim, never reformatted. An
  absent field never blanks a value an earlier poll already recorded (same
  protection the terminal-status hardening already established).
- `observed_terminal_at` is set on the **first** observation of DONE/EXIT and
  never refreshed by later polls. Deliberately named for what it is: LSF's own
  finish time is not in this module's `-o` list, and calling a poll timestamp
  the job's end time would be dressed-up inference.
- `bsub_submit()` gained `runlimit_minutes`, emitting a real `bsub -W
  <minutes>` — the same knob the generated environments' `lsf_regress.sh`
  drives via `LSF_TIMEOUT`. Threaded through `bsub_submit_with_preflight()`,
  `register_external_job()` (also `command=`), and `dv-harness lsf-submit`
  (new `--runlimit-min`; `command` was already an argument and is now stored).
- `_upsert_job_tier_memory_record()` now persists `root_cause_status`,
  `fix_proposal_status` (the spec's "fix attempt") and `dv_result` =
  `sim_status` (the spec's "result", deliberately a key separate from
  `lsf_status` per CLAUDE.md's "LSF DONE is not equal to DV PASS") — these
  three always, since `NOT_STARTED`/`UNKNOWN` is itself informative — plus
  `command`, `runlimit_minutes`, `submit_time`, `run_time`,
  `observed_terminal_at`, `run_dir`, `sim_log`, `regression_id`, and
  `early_kill`/`kill_reason`, each **omitted rather than written as null**
  when its source genuinely captured nothing (the convention seed/fsdb_path
  already established).

**Unreachable enum values — removed, with a disclosed boundary.**
`MEMLIMIT`/`TIMEOUT`/`LICENSE_WAIT` were declared on `LsfStatus` but
`_BJOBS_STAT_MAP` — the only writer of `JobState.lsf_status` — can emit none
of them. Rather than invent an exit-reason mapping this environment cannot
validate (no live LSF instance here), the three were removed with a comment
recording exactly why and what restoring them for real would require. The
honest timeout input for a Job Memory record today is the run limit the
submitter itself requested (`runlimit_minutes`). A test now asserts every
declared `LsfStatus` value is producible, so this cannot silently regress.

---

## 3. Gap B — live engineering-tier index/file integrity → CLOSED (root cause found and fixed, plus the live data repaired)

The audit found 18 of 31 engineering record files with no `index.json` row.
Checking every tier found it was worse: **31 files total** (18 engineering +
13 working) were unindexed — real, well-formed records invisible to
`MemoryRetriever.search()` (which iterates the index) while still reachable
by exact id via `get()` (which reads the file).

**Root cause** — not the out-of-band `.work/persist_*.py` scripts the audit
suspected: those call `route_and_store()` like everything else. `index.json`'s
read-append-write in `MemoryStore.add()` was **unlocked**, so two concurrent
harness processes (this session runs several agents at once, each writing
memory) each read the same index and the second write dropped the first's row.
The signature matches exactly: every record file intact, only index rows lost.

**Fix (`dv_harness/memory.py`)**

- `MemoryStore._index_lock()` — a cross-process lock around the index's
  read-modify-write, using an atomic `os.mkdir` lock directory (works on both
  this project's Windows dev end and its Linux server, no per-platform
  dependency), with stale-lock breaking. Deliberately **availability over
  strictness**: if the lock cannot be taken it proceeds unlocked rather than
  raising, because a memory write must never break the stage/reconcile that
  triggered it — which is what `reindex()` exists to repair.
- `_save_index()` now writes atomically (`os.replace`), closing a second real
  window in which a concurrent reader could hit a truncated index.
- `MemoryStore.index_integrity()` — read-only drift report.
- `MemoryStore.reindex(prune_missing=False)` — repairs the index from the
  record files (the system of record). Adds rows for unindexed files,
  refreshes rows that drifted from their file, and **reports but never drops**
  rows whose file is gone unless explicitly asked (dropping is destructive,
  and such a row is already inert for search).
- `memory_doctor.check_memory_store_index()` wired into `run_doctor()` as the
  `memory_store_index` check (PARTIAL on drift, with the repair command in its
  reason string).
- `python -m dv_harness.memory_cli index-check` / `reindex [--prune-missing]`.

**Live repair performed** (this is real data, not a test fixture):

```
$ python -m dv_harness.memory_cli --project-root . index-check
ok False   engineering {files 31, index_rows 13}   working {files 14, index_rows 1}   missing 31

$ python -m dv_harness.memory_cli --project-root . reindex
added 31   refreshed 1   unreadable []   index_row_count 92

$ python -m dv_harness.memory_cli --project-root . index-check
ok True    engineering {files 31, rows 31}   working {files 14, rows 14}   project 46/46   job 1/1
```

Spot-checked `MEM-04B0C14D91` (one of the 18 the audit named): it is now
returned by `MemoryRetriever.search()`, having been index-invisible before.

---

## 4. Gap C — (Working/Project) → Engineering promotion gate → CLOSED

The audit confirmed live that `route_memory()` sent any
`root_cause`/`verified_fix`/`debug_lesson` record with a caller-supplied
`verified: True` straight to `ENGINEERING_MEMORY` with no confidence, evidence
or reusable check — so a record reading `{"root_cause": "unverified guess",
"verification": {}}` landed at the engineering tier and was only rejected one
tier later, at the organizational gate. Everything treating engineering-tier
membership as "verified reusable knowledge" (stage-prompt retrieval, the
shared Knowledge Center push, the vault's `Engineering/` folder) inherited
that unearned status.

**`memory_router.engineering_admission_gate(record)`** — the counterpart, one
tier down, of `promote_to_organizational()`'s three-gate bar, reusing this
module's existing machinery rather than inventing parallel checks:

1. **Evidence** — non-empty `evidence`, OR a `verification` block in one of
   the two gate-validated shapes, via the **same**
   `_verification_is_gate_validated()` the organizational gate uses.
2. **Confidence** — `confidence` in HIGH/CONFIRMED
   (`inference.promote_if_high_confidence()`'s existing bar and
   `from_closed_finding()`'s own label — no third scale invented), or
   equivalently that same gate-validated block, which is independently
   gate-script-verified evidence rather than a self-declared label.
3. **Reusable** — `reusable` not explicitly `False`, and at least one of
   `root_cause`/`fix`/`lesson`.

A failing record is **demoted to Working Memory**, not dropped and not raised
on: it is written to the working tier carrying
`engineering_admission_rejected: [<reason codes>]`, and `route_and_store()`
returns `{"destination": "WORKING_MEMORY", "requested_destination":
"ENGINEERING_MEMORY", "engineering_admission": {...}}`. That is CLAUDE.md's
own Engineering Memory Policy ("an unverified hypothesis … belongs in Working
Memory until it clears verification") as enforced code rather than trusted
prose. Reason codes: `NO_EVIDENCE`, `CONFIDENCE_BELOW_HIGH`,
`EXPLICITLY_NOT_REUSABLE`, `NO_REUSABLE_CLAIM`.

**Both real production call sites still clear it**, verified by test:
`engine.py`'s `_promote_experience_knowledge()` (evidence from a gate block +
`confidence: "HIGH"`) and `_promote_verified_fix_knowledge()` (RE_AUDIT gate
shape + `confidence: "HIGH"`).

**Side effect worth stating**: a demoted record can no longer bump an existing
engineering record's `confirmation_count`, so the admission gate cannot be
walked around by re-asserting an unevidenced claim twice to reach the
organizational gate's confirmation bar. Covered by a dedicated test.

**Test fixtures updated, not weakened.** Eight existing tests across five
files passed bare `{"kind": ..., "verified": True, "title": "t"}` records and
asserted `ENGINEERING_MEMORY`. Each fixture was enriched with real evidence /
confidence / a reusable claim — their subject (cfg auto-loading, shared push,
vault write-through, dedup-confirm, commit SHA) is unchanged and each now
exercises a record that genuinely belongs at that tier. `test_case_08` was
strengthened rather than relaxed: it now asserts the unevidenced record never
reaches the engineering tier at all, **and** keeps independent coverage of
`promote_to_organizational()`'s own `QUALITATIVE_GATE_FAILED` path by seeding
an engineering record straight into `MemoryStore` (bypassing the router,
precisely because the router will no longer admit one).

---

## 5. Tests

New: `dv_harness_tests/test_memory_tier_integrity_and_admission.py` — 23
tests, all against real files/routing, none a parse-or-import smoke test.
Highlights:

- Job-tier: all five spec-named fields present with real sourced values;
  honest omission of what nothing supplied; `observed_terminal_at` set once
  across three polls; `bsub -W` emitted only when requested; every declared
  `LsfStatus` value producible by `_BJOBS_STAT_MAP`.
- Index integrity: a record file with no index row is proven **invisible to
  `search()` but reachable by `get()`**, then proven searchable after
  `reindex()`; drift reported not silently repaired; rows-without-file kept
  unless `prune_missing`; drifted rows refreshed; **4 real concurrent
  processes × 15 writes each lose zero index rows** (the regression test for
  the actual root cause); `memory doctor` goes PARTIAL→READY; both CLI
  subcommands run end to end.
- Admission gate: admits a fully evidenced record; each of the four reason
  codes named by its own parametrized case; either gate-validated verification
  shape suffices alone; live demotion with content preserved; a demoted record
  never becomes a confirmation; engine's real `verified_fix` record shape
  still clears the gate.

**Test summary:** 312 passed across the 13 memory/LSF/inference suites
(`test_memory_tier_integrity_and_admission`, `test_memory_tier_completion`,
`test_memory_vault`, `test_memory_doctor`, `test_memory_dedup`,
`test_memory_security`, `test_debug_flow_memory`, `test_knowledge_center`,
`test_obsidian_memory_final_integration`, `test_cli_memory_commands`,
`test_react_working_memory_bridge`, `test_lsf_client`, `test_inference`), plus
`test_preflight_lsf_wiring` + `test_inference_engine_wiring` 18 passed, plus
`test_evidence_db`/`test_evidence_db_wiring`/`test_cli_lsf_watch`/
`test_cli_lsf_auto_kill_scan` 59 passed, plus `test_engine_gates_and_routing`
249 passed / 2 failed.

**Those 2 failures are not from this work** and are disclosed rather than
glossed: `test_graph_next_walks_full_mechanism_first_pipeline` and
`test_all_35_stages_have_real_de_explainer_entries` fail on
`RCA_JOIN`/`RCA_VIP_SPEC_EVIDENCE`/`RCA_RTL_EVIDENCE`/`RCA_LOG_EVIDENCE` —
new graph stages added by a concurrently-running multi-agent-orchestrator
workstream without matching explainer entries. Nothing in this change touches
stage/graph/explainer code.

---

## 6. Boundaries and residuals (disclosed, not closed)

- **LSF exit/pending reason mapping** (would restore TIMEOUT/MEMLIMIT/
  LICENSE_WAIT as *derived* statuses): needs validation against a live LSF
  instance, which this environment does not have. Deliberately not guessed —
  the declaration was removed instead, with the reasoning recorded in code.
- **`evidence_db.insert_job_state()`'s explicit column list** does not include
  the five new `JobState` fields. Non-breaking (it is an explicit projection,
  not `SELECT *`), and `evidence_db.py` is actively being edited by a
  concurrent cross-run-trend workstream that owns that schema — left to them
  rather than racing on the same file.
- **Organizational tier still has no local file store** — by design, unchanged
  (backed by the shared Knowledge Center).

---

## 7. Commit / concurrency notes

Committed with a private temporary git index (`GIT_INDEX_FILE`) so that other
agents' concurrently-staged work (`engine.py`, `gates.py`, `models.py`,
`prompts.py`, `.claude/skills/**`, `test_rca_multi_agent_fanout.py`, …) was
neither swept into this commit nor disturbed. For the three files shared with
in-flight work (`dv_harness/cli.py`, `dv_harness/lsf_client.py`,
`.dv-harness/lsf/job_state_schema.json`) only this scope's own hunks were
staged, via the trimmed-patch technique — the concurrent `trend` subcommand
and `runtime_seconds` hunks were left in the working tree for their owner.

One item to note: the CLAUDE.md Engineering Memory Policy addendum written by
this pass (documenting the new admission gate) was picked up and committed by
another agent's commit `98e6b3d` before this commit was made. The content is
correct and in place; only its commit attribution differs.
