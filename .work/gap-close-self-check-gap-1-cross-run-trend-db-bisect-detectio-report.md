# Gap 1 — Cross-run trend DB + regression bisect-detection + runtime anomaly detection

**Status: NO_ACTION_NEEDED** (verdict: WIRED_AND_FIRING)

**Test summary:** no code changed; re-verified green — `test_trend_analysis.py` **51 passed** in 177.96s (the prior audit's incomplete background run reported "41 tests"; the real count is 51), plus adjacent write-path suites `test_evidence_db.py` + `test_evidence_db_wiring.py` + `test_lsf_client.py` + `test_regression_reporter.py` + `test_mcp_query_regression.py` = **166 passed** in 90.09s.

## What was asked

Close the gap the earlier audit (`verification_knowledge_assets_reverify.js`, Section 2) recorded as **BLOCKED**: no daily-rollup time series, no git-bisect-style regression detection, no runtime-vs-baseline anomaly detection, and `JobState` carrying no runtime field at all — which was said to block two of the three sub-items.

## What was found

That BLOCKED finding is **stale**. All four sub-items already exist as real, wired, tested code, delivered by `dv_harness/trend_analysis.py` (dated 2026-09-03 in its own comments) plus schema and write-path additions to existing modules. **Nothing needed to be built, and nothing was changed.** Per task instruction 1, this pass re-confirmed the cited evidence and finished the verification the prior audit left incomplete.

Working tree was clean of source modifications before and after this pass (`git status` showed only per-machine runtime state `.dv-harness/events.jsonl`, `.dv-harness/state.json` and two untracked scratch files, none of them touched here).

### (a) Runtime/duration on JobState — REAL

- `dv_harness/lsf_client.py:184` — `runtime_seconds: Optional[float] = None`, with a comment block at `:167-183` explaining it is DUT simulation wall-clock, explicitly *not* agent/LLM orchestration timing (`stage_profile.py`'s separate concept), and that `None` never degrades to a fabricated `0`.
- `dv_harness/lsf_client.py:859-862` — real write path in `reconcile_job()`: `parse_run_time_seconds(live_bjobs_record.get("RUN_TIME"))`, written **monotonically** (`live_runtime > state.runtime_seconds`), so a later poll of a job LSF has forgotten cannot erase a larger real observed duration. The `run_time` column was already in every `_run_bjobs()` `-o` list and had simply been discarded.
- `dv_harness/evidence_db.py:113` — `ALTER TABLE jobs ADD COLUMN IF NOT EXISTS runtime_seconds DOUBLE`, in `_MIGRATION_STATEMENTS`, replayed on every connect so a pre-existing `evidence.duckdb` is not stranded on the old schema.
- `dv_harness/regression_reporter.py:282` — `store.insert_job_state(state)` inside `_write_reconciliation_evidence_if_configured()`, called at `:596` from `run_reconciliation_cycle()` — the same function the background `lsf-watch` loop drives every cycle.

### (b) Daily rollup with retained history — REAL

`regression_verdicts` remains upsert-only *by design* (it is the "currently passing" snapshot `dv_harness/mcp/regression_queries.py` reads). The time dimension was added beside it rather than by changing it:

- `dv_harness/evidence_db.py:169-177` — `CREATE SEQUENCE ... regression_verdict_history_id_seq` + append-only `regression_verdict_history` (`pattern`, `verdict_passed`, `job_id`, `git_sha`, `recorded_at`).
- `dv_harness/evidence_db.py:434-477` — `insert_regression_verdict()` writes **both** shapes from a single call (upsert + append), deliberately so no production call site can grow history that disagrees with the snapshot.
- `dv_harness/regression_reporter.py:286-299` — the real call site passes `git_sha=state.git_sha` (a real `JobState` field, `lsf_client.py:165`).
- `dv_harness/trend_analysis.py:93-175` (`daily_rollup()`) — per-calendar-day pass-rate (from `regression_verdict_history`), bins-weighted coverage (from `coverage_samples`), runtime and derived license-hours (from `jobs.runtime_seconds`); `day_over_day()` at `:184` gives the latest-vs-previous delta.

### (c) Bisect helper over real RTL git history — REAL

- `dv_harness/trend_analysis.py:231-280` (`detect_pattern_regressions()`) — finds each pattern's current PASS→FAIL transition; reports `bisectable=False` with a real reason (`NO_GIT_SHA_RECORDED` / `SAME_GIT_SHA_PASSED_AND_FAILED`) instead of guessing.
- `dv_harness/trend_analysis.py:321-434` (`bisect_regression_to_rtl_commit()`) — *(the audit cited `:283-415`; actual span is `:321-434`, line drift only)* — real read-only `git rev-list` / `git cat-file` / `git show` between last-good and first-bad SHAs, filtered to RTL pathspecs (`*.v/*.sv/*.svh/*.vh`), returning `IDENTIFIED_COMMIT`, `CANDIDATE_RANGE` (with a real `git bisect start <bad> <good>` plan), `NO_RTL_COMMITS_IN_RANGE`, `SHA_NOT_IN_REPO`, or `GIT_UNAVAILABLE`.

### (d) Runtime anomaly vs. historical baseline — REAL

- `dv_harness/trend_analysis.py:439-510` (`detect_runtime_anomalies()`) — per-pattern PASS-only baseline (median/mean/stdev) that **excludes the candidate job itself** (so one large outlier cannot inflate the median it is judged against), flags at ≥2x median or ≥3σ above mean, requires ≥5 prior samples before any verdict, and emits `z_score=None` rather than a fabricated infinity when baseline variance is zero.

### End-to-end wiring — verified by execution, not just by reading

- `dv_harness/cli.py:717-737` (parser, incl. `--json`, `--seats-per-job`, `--rtl-pathspec`, `--min-baseline-samples`, `--ratio-threshold`, `--z-threshold`) and `:2118-2135` (dispatch to `trend_analysis.trend_report()` / `render_trend_report_text()`).
- **Live run:** `python -m dv_harness.cli trend --json` succeeded, returning `available: true` with the real DB path and an honest `license_hours_model` string disclosing that license hours are a *derived estimate* from measured job runtime, not a real FlexLM/lmstat checkout feed. All result arrays were empty — correct, because this local-analysis machine has no real LSF job rows.
- **Non-vacuity proof:** to confirm the empty output above was data-absence rather than a dead code path, the real functions were driven against a synthetic `EvidenceStore` (temp dir, discarded afterwards). All three detectors fired correctly:
  - anomaly — the 700s job flagged against a 100.5s median, `ratio_to_median: 6.9652`, `baseline_sample_count: 6` (correctly 6, not 7 — the candidate excluded itself), `reason: RATIO_GE_2.0X_MEDIAN+Z_SCORE_GE_3.0`;
  - regression — `sha6` → `shaBAD` PASS→FAIL, `bisectable: True`, `reason: PASS_TO_FAIL_ACROSS_DISTINCT_SHAS`;
  - daily rollup — `verdict_count: 8`, `verdict_passed: 7`, `pass_rate_percent: 87.5`, `total_runtime_hours: 0.393056`, `license_hours: 0.393056`.

## Residual (disclosed, not a defect)

`bisect_regression_to_rtl_commit()` narrows a real commit **range** from real git history but does not execute a live re-run/bisect loop against a simulator. The module's own docstring states this. A local-analysis machine has no simulator, LSF, or license with which to do it, and the code says so rather than pretending otherwise. Closing that would require real remote execution and is out of scope for this workflow (which is declared LOCAL_ANALYSIS).

## Scope discipline

No parallel or duplicate mechanism was created — consistent with this project's norm and with the fact that the correct extension points (`evidence_db.py` schema + `insert_regression_verdict()`, `lsf_client.py`'s `JobState`/`reconcile_job()`, `regression_reporter.py`'s existing reconciliation write path, `cli.py`'s existing subcommand table) were all already used by the existing implementation. No network call of any kind was made.

## Commit

No source change to commit. This report is the only artifact.
