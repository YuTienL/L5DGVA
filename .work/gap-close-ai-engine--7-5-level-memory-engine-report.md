# Gap close — AI mechanism #7: 5-Level Memory Engine

**Status: DONE** (one confirmed gap closed; two other audit findings are environment-dependent, not code gaps — detail below)

Date: 2026-09-04. Working root: `D:\DV\Task\DV_Agent_Harness_L5\v50`.

---

## 1. Audit evidence re-verified first (not taken on trust)

Counted directly in the live root before touching anything — the audit's numbers reproduce exactly:

| Tier | Files under `.dv-harness/memory/` |
|---|---|
| working | 14 |
| engineering | 31 |
| project | 46 |
| job | 1 |
| organizational | 0 |

`.dv-harness/lsf/jobs/` contains only `README.md` (zero real `JobState` files). No `evidence.duckdb` exists anywhere under the project root (`find . -name evidence.duckdb` → empty). Full-repo grep confirmed `insert_job_memory_record` had **zero** call sites outside `dv_harness/evidence_db.py` and `dv_harness_tests/`.

`git diff --stat` on `dv_harness/regression_reporter.py`, `dv_harness/lsf_client.py`, `dv_harness/evidence_db.py` was empty before I started — no concurrent workstream had touched them, so no hand-scoped patching was needed.

---

## 2. The gap that was real, in scope, and is now closed

**`EvidenceStore.insert_job_memory_record()` was dormant.**

It is the *only* function in `dv_harness/evidence_db.py` whose purpose is mirroring the 5-level Memory engine's **JOB tier** into DuckDB — sole writer of the `job_memory_records` table, and sole writer of the cross-run `failure_signatures` aggregate ("has this exact failure shape been seen before, how often") that the table exists to feed. Both of its siblings inside the very same function body — `insert_job_state()` and `insert_regression_verdict()` — were already wired into the real reconciliation cycle. It was not.

Net effect: a real reconciliation cycle wrote the job's `jobs` row and its `regression_verdicts` row, but never the job's Memory-tier record, and `failure_signatures` would have stayed permanently empty no matter how many real failures reconciled.

### What changed

`dv_harness/regression_reporter.py` — `_write_reconciliation_evidence_if_configured()`, inside the existing per-job `try` block, alongside its two already-wired siblings:

```python
store.insert_job_state(state)
job_memory_record = lsf_client.load_job_tier_memory_record(root, jid)
if job_memory_record is not None:
    store.insert_job_memory_record(job_memory_record)
```

Two deliberate design decisions, both documented in the function's own docstring:

1. **The record is read back from the real Memory store**, via the existing named reader `lsf_client.load_job_tier_memory_record()` (keyed by the deterministic `job_tier_memory_id(jid)` both writers already agree on) — it is *not* re-derived here. `_upsert_job_tier_memory_record()` runs **earlier** in the same cycle, after the real sim.log epilogue parse; that is what upgrades a premature `job_result` classification to the accurate `job_failure` one with its `failure_signature`/`prior_related_knowledge` attached. Reading at this point mirrors the final, best-evidence record. Re-deriving would produce a second, possibly disagreeing copy of a record the Memory tier already owns.
2. **What lands in DuckDB is by construction what the JSON Memory tier actually holds** — the mirror cannot silently drift from the thing it mirrors. A job with no Job-tier record yet returns `None` and is skipped; an absent record is a real, normal state and is never backfilled with an invented one.

No new mechanism was built. This wires the existing, already-tested function into the existing production reconciliation cycle — one call site, no parallel path.

---

## 3. Tests

New file: `dv_harness_tests/test_job_memory_evidence_mirror.py` — 6 tests, all about the **wire**, not the function (that `insert_job_memory_record()` works in isolation was never the gap and is already covered by `test_evidence_db.py`). Every memory record in these tests is produced by the **real production writer** `lsf_client._upsert_job_tier_memory_record()`, never a hand-built dict; only the LSF discovery layer is mocked, matching `test_evidence_db_wiring.py`'s existing convention.

- real on-disk Memory-tier record → mirrored into `job_memory_records` under the same deterministic `memory_id`
- job with no Memory-tier record → mirrors nothing, `jobs` row still written (no fabrication)
- one bad mirror insert is isolated to its own job; siblings keep their full evidence
- **end-to-end**: one real `run_reconciliation_cycle()` over a genuinely failing job leaves the `job_memory_records` row *and* a real `failure_signatures` row (`occurrence_count=1`), with the stored `failure_signature_json` byte-identical to the JSON Memory tier's own
- two cycles over the same failure upsert **one** record row while accumulating `occurrence_count` to 2 — what the mirror is actually for
- static AST guard: `insert_job_memory_record` must have a real caller in `dv_harness/` outside `evidence_db.py`, and specifically in `regression_reporter.py` — so this cannot silently go dormant again

**The tests were proven to fail without the fix**: reverting the three added lines and re-running gives `5 failed, 1 passed` (the survivor is the negative "no record → no row" case, correctly passing either way). File restored byte-identically afterwards.

### Full suite result

```
test_job_memory_evidence_mirror.py + test_evidence_db_wiring.py + test_evidence_db.py   50 passed, 1 skipped
test_trend_analysis.py + test_mcp_read_only_boundary.py
  + test_knowledge_layer_git_and_duckdb.py + test_mcp_query_regression.py              102 passed
test_lsf_client.py + test_regression_reporter.py
  + test_memory_write_guard_and_job_evidence.py + test_debug_flow_memory.py            150 passed
test_obsidian_memory_final_integration.py + test_memory_tier_completion.py
  + test_memory_tier_integrity_and_admission.py                                         56 passed
```

**358 passed, 1 skipped, 0 failed.**

Committed as a single scoped commit touching only `dv_harness/regression_reporter.py` and the new test file — nothing else in this concurrently-edited tree.

---

## 4. The other two audit findings — verified in code, and why no code changed

Both were re-checked against the actual source rather than accepted from the report. Neither is a wiring defect; both are **"this code path has never been executed against real data in this root"**, which no amount of code can close and which I will not fake.

### 4a. Job Memory / `reconcile_batch()` never fires in the live root

`_write_job_tier_memory_on_terminal_reconcile()` (`lsf_client.py:926`, called from `reconcile_batch()` at `lsf_client.py:1245`, itself reached from `cli.py` and `regression_reporter.py`) is real, correct, and fully wired. `.dv-harness/lsf/jobs/` is empty because **no real LSF job has ever been submitted from this root** — this environment has no LSF farm. The fix is operational (`dv-harness lsf-watch-start` against a real submitted job), not a code change.

I deliberately did **not** manufacture synthetic `JobState` files or a synthetic `evidence.duckdb` in the live root to make the counts move. That would be fabricating verification evidence, which CLAUDE.md's Evidence Truth Rule forbids, and would make the tier populations *less* trustworthy, not more. The end-to-end test above proves the whole path works against a real cycle in a real temp root; what is missing is a real farm, not real code.

### 4b. Organizational promotion "unreachable"

Re-read all three gates and their machinery. Every part is real and correct:

- `promote_to_organizational()` (`memory_router.py:445`) — three gates, correctly implemented.
- `_add_or_confirm_engineering()` / `_find_confirming_engineering_match()` (`memory_router.py:294/331`) — real dedup on `protocol` + `root_cause`; I verified `MemoryStore._index_row()` really persists **both** of those fields into `index.json` (confirmed against a live index row), so the matcher genuinely can hit.
- `MemoryGC.confirm()` (`memory.py:528`) — really increments `confirmation_count` and rewrites the record.
- `engine.py`'s `_promote_verified_fix_knowledge()` auto-fires the evaluation on every RE_AUDIT PASS and **does** populate `"protocol": rc_block.get("protocol")` on its record — so the dedup path *is* reachable from that production call site today. (`_add_or_confirm_engineering()`'s docstring still carries a "KNOWN LIMITATION" note saying engine.py does not populate `protocol`; that note is now stale, but it is a comment, not a defect, and this pass's mandate was wiring, not doc cleanup. Flagging it here rather than silently editing a shared file mid-pass.)

So the named condition — "no real record has accumulated a second independent confirmation" — is **a data condition on a correct mechanism**, not a broken wire. The only honest ways to clear it are the two the audit itself names: a real RE_AUDIT PASS executing in this root, and future `persist_*.py` lessons searching existing engineering memory first so a re-derived root_cause/protocol lands on the *same* record.

**I explicitly did not**: weaken `ORGANIZATIONAL_MIN_CONFIRMATIONS`, relax the qualitative gate, or hand-write a record with `confirmation_count: 2` to make `.dv-harness/memory/organizational/` non-empty. Any of those would produce a green tier count by defeating the exact design the tier exists to enforce ("Do not re-word the qualitative gate's inputs to force a pass" — CLAUDE.md, Engineering Memory Policy).

---

## 5. Follow-ups for whoever runs this harness against a real farm

1. Run one real `reconcile_batch()` in the live root (`dv-harness lsf-watch-start --vcuser <acct>` with a real submitted job). Verify: `.dv-harness/lsf/jobs/*.json` appears, `.dv-harness/memory/job/*.json` count moves, `evidence.duckdb` appears, and `SELECT count(*) FROM job_memory_records` is non-zero — that last one is what this pass made possible and is the single cheapest check that this fix is live.
2. Get one real RE_AUDIT PASS in the live root so `ORGANIZATIONAL_PROMOTION_EVALUATED` appears in `events.jsonl` at least once (currently: 428 events, zero of them).
3. Refresh `_add_or_confirm_engineering()`'s stale "KNOWN LIMITATION" docstring paragraph (see 4b) next time `memory_router.py` is touched for a real reason.
