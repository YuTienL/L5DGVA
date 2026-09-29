# Gap close — VKA Section 2: cross-run trend DB + regression bisect-detection + runtime anomaly

**Status: DONE**

Scope handled: the audit's Section 2 only (跨 run 的時間維度). Items 2a (PARTIAL),
2b (BLOCKED), 2c (BLOCKED) are all now real, wired and tested end to end.

Execution mode: **LOCAL_ANALYSIS** — pure local code + local git + local DuckDB.
No server, no VCS, no simulation. Nothing below is claimed as runtime/simulation
evidence.

---

## 1. Re-verification of the audit's findings (before changing anything)

Every claim in the incoming audit was re-checked against current code. All held:

| Audit claim | Re-verified |
| --- | --- |
| `insert_coverage_sample` has zero production call sites | Confirmed. `grep -rn "insert_coverage_sample" --include=*.py .` returned only its own definition (`evidence_db.py:404`), the MCP must-not-call list (`mcp/regression_queries.py:7`) and unit tests. |
| `insert_regression_verdict` upserts, destroying history | Confirmed at `evidence_db.py:388-400` — `ON CONFLICT (pattern) DO UPDATE`. |
| `jobs` has no runtime column | Confirmed — the `CREATE TABLE jobs` column list at `evidence_db.py:83-109` had none. |
| no bisect / anomaly / daily-rollup code anywhere | Confirmed — `grep -rniE "bisect\|zscore\|z-score\|stddev\|outlier\|daily\|rollup\|day_over_day\|license_hour" --include=*.py dv_harness/ dv_harness_tests/` returned only unrelated hits (`question_queue.py`'s daily *digest* cadence, `user_info.py`'s per-user access rollup). |

One audit statement needed correcting, and it changed the plan materially:

> "runtime … has no schema **or data source** at all"

The schema half was right; the **data source half was not**. `lsf_client._run_bjobs()`
has always requested `run_time` — `bjobs -json -o "jobid stat exit_code exec_host
queue run_time submit_time job_name"` (`lsf_client.py:254-255`) — and
`reconcile_job()` simply read the record and discarded it. So item 2c did not need
a new LSF query or a new collection mechanism; it needed the already-collected
field to stop being thrown away. That is why this closed as a bounded change
rather than NEEDS_SEPARATE_EFFORT.

---

## 2. What changed

### New: `dv_harness/trend_analysis.py`

The one place that asks what changed *between* runs. Read-only throughout — it
never inserts, never migrates, and its only subprocess is a read-only
`git rev-list`/`cat-file`/`show`.

- `daily_rollup()` / `day_over_day()` — the four daily curves + real
  latest-vs-previous comparison.
- `detect_pattern_regressions()` + `bisect_regression_to_rtl_commit()` — item 2b.
- `detect_runtime_anomalies()` — item 2c.
- `trend_report()` / `render_trend_report_text()` — one JSON-serializable report
  over all three, opened via `EvidenceStore(read_only=True)` so it can never
  create or migrate a database, nor block a live `lsf-watch` writer.

### Extended (not replaced): existing modules

| File | Change |
| --- | --- |
| `dv_harness/evidence_db.py` | `jobs.runtime_seconds DOUBLE`; new append-only `regression_verdict_history` table (pattern/verdict/job_id/**git_sha**/recorded_at); `_MIGRATION_STATEMENTS` replayed on every connect so an already-on-disk `evidence.duckdb` gains the new column; `insert_regression_verdict()` gains an optional `git_sha` and now writes **both** the snapshot and the history row. |
| `dv_harness/lsf_client.py` | `JobState.runtime_seconds`; `parse_run_time_seconds()`; `reconcile_job()` captures LSF's `RUN_TIME` **monotonically**. |
| `dv_harness/regression_reporter.py` | the existing production call site now passes `state.git_sha` through. |
| `dv_harness/dashboard.py` | new `_ingest_coverage_summary_to_evidence_db()`, called from `append_coverage_history_sample()` — the exact function `engine.py:1357` calls on a gate-verified COVERAGE_CLOSURE PASS. |
| `dv_harness/cli.py` | `dv-harness trend` (`--json`, `--seats-per-job`, `--rtl-pathspec`, `--min-baseline-samples`, `--ratio-threshold`, `--z-threshold`). |
| `.dv-harness/lsf/job_state_schema.json` | `runtime_seconds` (kept in lockstep with `JobState`, as `test_lsf_client.py:631-635` enforces). |

`engine.py` was deliberately **not** touched — the coverage wiring went into
`dashboard.py`, which is already the documented production write path, so the
existing engine call site needed no edit at all.

---

## 3. Per-item verdicts

### 2a — Trend database with daily pass-rate / coverage / runtime / license-hour curves → **CLOSED**

All five missing pieces the audit named:

1. **Pass-rate history no longer destroyed.** `regression_verdicts` keeps its
   one-row-per-pattern upsert (correct for "is this passing *now*?", and what
   `mcp/regression_queries.py` reads — unchanged); the new append-only
   `regression_verdict_history` answers the different, previously impossible
   question. Both are written from the *same* `insert_regression_verdict()` call,
   so no production call site can grow a history that disagrees with the snapshot.
2. **Coverage ingestion wired** to a real call site, reading
   `.dv-harness/coverage/summary.json` through the same
   `parse_coverage_summary()` validation `GET /api/coverage` already uses.
3. **Runtime column added and populated** from LSF's own already-requested
   `run_time`.
4. **License-hours defined and populated** — see the honest-limits section below.
5. **Daily-rollup + day-over-day query written** (`daily_rollup()` /
   `day_over_day()`), grouping by each table's own store-set timestamp.

Real output (real DuckDB file, real git repo, real production write paths):

```
DAY            PASS%    COV%     RUN_H     LIC_H   JOBS
-------------------------------------------------------
2026-09-04     87.50   82.08     1.654     1.654      8
```

Coverage is **bins-weighted** (`sum(bins_hit)/sum(bins_total)`), not a mean of
category percents, so a 12-bin category cannot outvote a 4000-bin one:
`(1320+256)/(1500+420) = 82.08%`, verified by
`test_coverage_curve_is_bins_weighted_not_a_mean_of_percents`.

Every metric is `Optional` and is `None` — never `0` — on a day with no evidence
for it, so an empty day never renders as a real measured 0% pass rate.

### 2b — Regression detection, auto-bisect to RTL commit → **CLOSED**

```
REGRESSIONS (PASS -> FAIL)
- usb3_link_training: c6e55ea07e35... PASS -> ceb4a5a0ef23... FAIL [PASS_TO_FAIL_ACROSS_DISTINCT_SHAS]
    bisect: IDENTIFIED_COMMIT
    responsible commit: ceb4a5a0ef23 retime lfps detector (rtl/usb_link.sv)
```

Real behaviour, all covered by tests against a **real `git init` repository with
real commits and real SHAs** (never a stubbed git):

- Only the pattern's **most recent** PASS→FAIL transition is reported — a pattern
  that broke, was fixed, then broke again surfaces the *current* range, not a
  stale one (`test_reports_the_current_breakage_not_a_stale_earlier_one`).
- The docs-only commit sitting inside the range is correctly excluded from the
  RTL candidates.
- `NO_RTL_COMMITS_IN_RANGE` is a real, useful negative result: commits exist but
  none touched RTL → look at testbench/VIP/constraint/seed/environment instead.
- `SAME_GIT_SHA_PASSED_AND_FAILED` → flagged **not bisectable**, because the same
  commit both passed and failed, so the cause is *not* an RTL change and pointing
  a bisect at an empty range would be a fabricated answer.
- `NO_GIT_SHA_RECORDED` → reported honestly rather than guessing a commit.
- `SHA_NOT_IN_REPO` → a SHA from a different checkout is named, never silently
  turned into an empty range that would read as "no RTL commit is responsible".

**Stated limit, deliberately not papered over:** this narrows to the commit
range and, when it narrows to one, names the commit — it does **not** execute
`git bisect`. A real bisection re-runs the failing testcase at every probed
commit, which needs a simulator, a license and an LSF submission per step, none
of which exist in a local analysis context. When more than one RTL commit remains,
`bisect_plan` emits the real `git bisect start <bad> <good>` sequence for whoever
can run it. The part that genuinely required the cross-run database — going from
"this pattern is failing" to an evidence-backed commit range — is real.

### 2c — Runtime anomaly detection (passing but abnormally slow) → **CLOSED**

```
RUNTIME ANOMALIES (passed, abnormally slow)
- usb3_lfps_basic job 200: 2150.0s vs median 405.0s over 5 prior runs
  (x5.3086, z=306.09) [RATIO_GE_2.0X_MEDIAN+Z_SCORE_GE_3.0]
```

Design decisions, each with a test pinning it:

- **PASS-only, both sides.** A FAILing job's runtime is a different distribution
  (an early UVM_FATAL exits fast, a hang runs to timeout); mixing them makes the
  baseline meaningless. FAILing jobs neither form the baseline nor get flagged.
- **Self-exclusion.** Each candidate is judged against its pattern's *other* runs.
  Without this one enormous outlier drags up the very median it is compared to
  and hides itself (`test_the_outlier_does_not_inflate_the_baseline...`).
- **`min_samples` (default 5) yields no verdict at all**, rather than a weak one.
  An "anomaly" called against two prior runs is noise and would train a reader to
  ignore the detector.
- **Ratio OR z**, not AND. The ratio test (median-based, robust) catches a big
  jump; the z test catches a pattern that always runs 100s ± 1.6s suddenly taking
  150s — only 1.5x, but ~32σ, and genuinely abnormal *for that pattern*. Pinned by
  `test_z_score_fires_on_a_tight_baseline_the_ratio_test_would_miss`.
- **No division by zero, no fabricated infinite z**: a zero-variance baseline
  yields `z_score=None` and the ratio test alone decides.

---

## 4. Honest limits (recorded, not hidden)

1. **`license_hours` is a derived estimate, not a measured checkout.** Nothing in
   this harness talks to lmstat/FlexLM. It is
   `sum(job wall-clock runtime) x seats_per_job`, and the model string travels
   with the report itself (`LICENSE_HOURS_MODEL`, printed on every text render and
   present in the JSON) so no consumer can mistake it for a license-manager
   reading. `--seats-per-job` exists so a project that knows its own real per-job
   feature checkout can scale it rather than being handed a hardcoded 1.
2. **Daily buckets use each table's store-set timestamp** (`recorded_at` /
   `ingested_at`), not a caller-supplied one.
   `coverage_samples.sample_timestamp` is deliberately free-form passthrough text
   (epoch float, ISO string, whatever the coverage tool emitted) and is not a
   parseable bucket key. For a watcher reconciling continuously this is within
   minutes of the real run time; it is not the job's LSF finish time, which this
   module's `-o` list does not request.
3. **`parse_run_time_seconds()` never guesses.** It accepts the bare-number and
   `N second(s)` forms and returns `None` — never `0.0` — for anything else
   (`"-"`, `""`, `"00:10:00"`). A wrongly-parsed duration would silently poison
   both the runtime curve and the anomaly baseline, so an unconfirmed format is
   reported as "no runtime evidence" per the Tool Usage Verification Gate.
4. **Coverage ingestion writes nothing when there is no `summary.json`.** The
   caller's aggregate `coverage_credit_percent` carries no real
   `bins_total`/`bins_hit`; inventing those to force a row in would put fabricated
   numbers into the evidence database. The percent still reaches `history.json`.
5. **No live LSF on this machine**, so `RUN_TIME` capture is proven against a
   faked `bjobs` RECORD through the real `reconcile_batch()` — the same subprocess
   boundary `test_lsf_client.py` already fakes. The parse and the monotonic-update
   logic are real; the exact real-world `RUN_TIME` string of this site's LSF is
   unconfirmed, which is precisely why an unrecognized format degrades to `None`
   rather than to a guess.

---

## 5. Tests

New: `dv_harness_tests/test_trend_analysis.py` — **51 tests, all passing.**

Deliberately end-to-end, because the audit these close found the opposite failure
mode: `insert_coverage_sample()` was real and unit-tested but had zero production
call sites, and `insert_regression_verdict()`'s upsert destroyed the very history
it was asked to trend. A test that constructed a store and called the insert
directly would have passed cheerfully through both. So instead:

- runtime capture starts at a real `reconcile_batch()` and flows through the real
  `regression_reporter._write_reconciliation_evidence_if_configured()`;
- coverage ingestion starts at the real function `engine.py` calls, over a real
  `summary.json` on disk;
- bisect runs against a **real `git init` repo** with real commits and real SHAs;
- two tests shell out to the **real CLI** (`python -m dv_harness ... trend`).

Only genuinely-external boundaries are faked: the `bjobs` subprocess, and the
store clock (back-dated by direct SQL) for the multi-day rollup, since a test
cannot wait a day.

A migration test builds the **real pre-migration `jobs` DDL** (this module's own
`CREATE TABLE` minus the one new column) and proves an existing database gains
`runtime_seconds` with its pre-existing rows untouched — a toy 3-column stub
would have failed on `regression_id` long before reaching the column under test.

### Run summary

In the **shared working tree** (this change + several other workflows' in-flight
edits):

| Suite | Result |
| --- | --- |
| `test_trend_analysis.py` (new) | **51 passed** |
| `test_evidence_db.py`, `test_evidence_db_wiring.py`, `test_mcp_read_only_boundary.py`, `test_mcp_query_regression.py`, `test_mcp_server_transport.py`, `test_coverage_analysis.py` | **109 passed** |
| `test_lsf_client.py`, `test_dashboard_interactive.py`, `test_dashboard_cli_checklist_rendering.py`, `test_cli_lsf_watch.py`, `test_cli_lsf_auto_kill_scan.py` | 149 passed, 1 failed — **not this change**, see below |

**Standalone verification** — a clean `git archive HEAD` tree with *only* this
change's files overlaid, to prove the commit stands alone and depends on no
other workflow's uncommitted work:

```
5 failed, 220 passed in 1446.60s
```

Both failure sets were traced rather than assumed:

- **The 5 standalone failures are pre-existing at `HEAD`.** They are the
  `normalized_evidence` tests: another workflow committed its tests
  (`test_evidence_db_wiring.py`'s `TestWriteNormalizedEvidenceIfConfigured`,
  `test_mcp_read_only_boundary.py::test_evidence_db_row_count_unchanged...`)
  ahead of the table those tests query, which is still uncommitted in the shared
  working tree. Running those same suites on a pristine `git archive HEAD`
  checkout reproduces exactly the same 5 failures with none of this change
  present. They are that workflow's to close.
- **The 1 shared-tree failure is another workflow's in-flight engine work.**
  `test_dashboard_interactive.py::test_start_loop_true_advances_through_
  multiple_stages_in_background` fails only in the shared tree, where
  `engine.py`/`gates.py`/`models.py`/`prompts.py` carry the concurrent
  RCA-fan-out changes. It **passes** on a pristine `HEAD` checkout and **passes**
  on `HEAD + only this change's files`. Left alone.

---

## 6. Concurrency handling

Several other workflows were editing this repo throughout, and **`HEAD` itself
moved twice mid-task** (six commits from other workflows landed while the test
suites were running, including `c2ed261` which committed the Job-Memory
`command`/`runlimit_minutes`/`submit_time`/`run_time` fields on the very
`JobState` this change also extends). Concretely handled:

- **A shared staged index.** Another agent had `gates.py`/`models.py`/`prompts.py`
  and three test files already staged. A plain `git add` + `git commit` would have
  stolen them into this commit. The commit was instead built in an **isolated
  `GIT_INDEX_FILE`** seeded from `HEAD`, so the shared index was never touched.
- **Files edited by two agents at once.** Only this change's hunks were committed,
  reconstructed against the `HEAD` blob rather than by staging whole files. After
  the other workflows' commits landed, `lsf_client.py`, `dashboard.py`,
  `regression_reporter.py`, `cli.py` and `job_state_schema.json` contained only
  this change's edits; `evidence_db.py` remained shared (another workflow's
  still-uncommitted `normalized_evidence` table + insert), so its hunks were
  separated and only this change's eight were committed.
- **A dependency on another agent's then-uncommitted field was found and removed.**
  An intermediate version parsed `state.run_time` (that workflow's new verbatim
  field, uncommitted at the time). That would have made *this* commit broken on
  its own. It now reads `live_bjobs_record.get("RUN_TIME")` directly, so the two
  fields derive independently from the same real record and neither commit
  depends on the other. That field has since been committed by its own workflow,
  and the independence is kept deliberately rather than re-coupled.
- **The first standalone verification was invalidated by a mid-run `HEAD` move**
  and was redone rather than reported. Its 15 failures were traced to the
  extraction having been built against the *previous* `HEAD`, which by then
  reverted another workflow's newly-committed `lsf_client.py` work — not to any
  defect in this change. Re-extracted against the new `HEAD` and re-verified.

---

## 7. Commit

`Add cross-run trend DB, regression bisect and runtime-anomaly detection`
— `dv_harness/trend_analysis.py`, `dv_harness_tests/test_trend_analysis.py`, plus
scoped extensions to `evidence_db.py`, `lsf_client.py`, `regression_reporter.py`,
`dashboard.py`, `cli.py` and `job_state_schema.json`.

---

## 8. Independent re-verification pass (2026-09-04)

This section was added by a **later, separate** gap-closing agent that received the
SAME Section 2 audit finding again (the audit text it was handed still described
2a as PARTIAL and 2b/2c as BLOCKED). That audit was **stale**: it predates commit
`3ad311c` and does not cite `dv_harness/trend_analysis.py` at all. Re-checked
against current code, every gap it names is already closed.

**Verdict: NO_ACTION_NEEDED — no file was modified in this pass.** The three items
were re-verified as READY rather than rebuilt.

### Why each of the audit's five "what's missing" bullets is already closed

| Audit's missing piece | Current real evidence |
| --- | --- |
| (1) stop overwriting `regression_verdicts`; keep pass/fail history | `evidence_db.py:472-478` appends to `regression_verdict_history` on the **same call** as the snapshot upsert, so no call site can grow a history that disagrees with it. |
| (2) wire `insert_coverage_sample` into a real call site | `dashboard.py:1534` `_ingest_coverage_summary_to_evidence_db()`, invoked at `dashboard.py:1606` off the real coverage path. The audit's "zero production call sites" no longer holds. |
| (3) add a runtime column to `jobs`, populate from real LSF times | Column: `evidence_db.py:142` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` at `:113`. Populated at `lsf_client.py:858-861` from the `RUN_TIME` column `_run_bjobs()` already requested, recorded **monotonically** so a forgotten-job poll cannot shrink a real duration. |
| (4) define and populate a license-hours metric | `trend_analysis.py:57-61` `LICENSE_HOURS_MODEL` + `daily_rollup()` at `:173`. Labelled in the CLI output as a derived **ESTIMATE**, not a license-manager reading — the honest framing, not a fabricated measurement. |
| (5) an actual daily-rollup / day-over-day query | `daily_rollup()` (`trend_analysis.py:93-175`, three `strftime(...) GROUP BY` queries) and `day_over_day()` (`:184-206`). |

2b's "zero matches for bisect" and 2c's "no runtime-baseline code" are likewise
superseded: `bisect_regression_to_rtl_commit()` (`trend_analysis.py:321-415`) and
`detect_runtime_anomalies()` (`:439-510`).

### Independent end-to-end proof (not the committed tests)

A fresh verification script was written from scratch — deliberately **not** reusing
`test_trend_analysis.py`'s helpers — driving a real temp git repo (real commits), a
real DuckDB store through the real production insert APIs and the real
`JobState` dataclass, then the real `trend_report()`. All 12 checks passed,
including the discriminating negatives that a naive implementation would fail:

- pass-rate 66.67% computed from **append-only history** (2 of 3 verdicts).
- coverage 50.0% **bins-weighted** across two categories (100/200 bins), not a mean of percents.
- runtime + license-hour curves from 7 real `runtime_seconds` rows.
- `day_over_day` honestly `None` on a single day of evidence — no fabricated zero baseline.
- bisect narrowed to the **one** real RTL commit; the docs-only commit in the same
  range was correctly excluded (`IDENTIFIED_COMMIT`, `range=2`, `rtl_files=['dut.sv']`).
- a still-green pattern produced **no** regression.
- the 900s PASS flagged at 8.96x; the six ~100s baseline runs were not, and the
  baseline (`median=100.5`, `n=6`) **excluded the outlier itself**.
- the same regression against an unrelated repo returned `SHA_NOT_IN_REPO`, not a
  silent empty range that would read as "no RTL commit is responsible".

The real CLI was also run against this repo: `python -m dv_harness trend` exits 0
and prints empty curves with "fewer than 2 days of evidence" — correct, since this
harness repo has no real regression jobs of its own.

### Test suites re-run this pass (all pass, nothing modified)

| Suite | Result |
| --- | --- |
| `test_trend_analysis.py` | 51 passed (544s) |
| trend + evidence_db + evidence_db_wiring + lsf_client + regression_reporter + mcp_query_regression + mcp_read_only_boundary + coverage_analysis | **262 passed** (826s) |
| `test_evidence_db.py` + `test_evidence_db_wiring.py` + both MCP suites | 84 passed (227s) |
| `test_dashboard_cli_checklist_rendering.py` + `test_dashboard_interactive.py` | 65 passed (109s) |

### Note for future audits of this section

The stale finding was reproducible because a grep for `bisect|daily|rollup|
license_hour` scoped to the modules the audit expected (`evidence_db.py`,
`regression_reporter.py`) misses the answer: this capability deliberately lives in
a **separate read-only module**, `trend_analysis.py`, which never inserts or
migrates. Any re-audit of Section 2 should read that module first.
