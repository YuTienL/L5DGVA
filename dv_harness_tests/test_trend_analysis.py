"""End-to-end tests for the cross-run TIME dimension (2026-09-03,
cross-run-trend task): `dv_harness/trend_analysis.py` plus the three real
production wirings that give it something to read.

Deliberately end-to-end, not isolated unit tests, because the audit these
close found the OPPOSITE failure: `evidence_db.insert_coverage_sample()` was
real and unit-tested but had zero production call sites, so
`coverage_samples` was permanently empty in every real project; and
`insert_regression_verdict()`'s upsert destroyed the verdict history it was
being asked to trend. A test that constructs a store and calls the insert
directly would have passed cheerfully through both. So:

  - runtime capture starts at a REAL `reconcile_batch()` over a faked bjobs
    RECORD (only the LSF subprocess boundary is patched -- the same boundary
    test_lsf_client.py already patches), goes through the REAL
    `regression_reporter._write_reconciliation_evidence_if_configured()`, and
    is read back out of a real DuckDB file;
  - coverage ingestion starts at the REAL production write path engine.py
    calls (`dashboard.append_coverage_history_sample()`) over a real
    summary.json on disk;
  - regression bisect runs against a REAL `git init` repository with real
    commits, real .sv files and real SHAs -- never a stubbed git.

Only genuinely-external boundaries are faked: the `bjobs` subprocess, and the
`ingested_at`/`recorded_at` clock (back-dated by direct SQL) for the
multi-day rollup, since a test cannot wait a day.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness import dashboard
from dv_harness import lsf_client
from dv_harness import regression_reporter as rr
from dv_harness import trend_analysis as ta
from dv_harness.evidence_db import EvidenceStore, default_db_path


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _store(root) -> EvidenceStore:
    return EvidenceStore(default_db_path(root))


def _record_verdict(root, pattern, passed, *, job_id, git_sha=None,
                    sim_status=None, runtime_seconds=None):
    """Drives the REAL production evidence write path for one job."""
    state = lsf_client.JobState(
        job_id=job_id, pattern=pattern,
        lsf_status="DONE" if passed else "EXIT",
        sim_status=sim_status or ("PASS" if passed else "FAIL"),
        git_sha=git_sha, runtime_seconds=runtime_seconds)
    rr._write_reconciliation_evidence_if_configured(root, {job_id: (state, [])})
    return state


def _backdate(root, table, column, day, *, where="TRUE"):
    """Back-dates a store-clock timestamp so a multi-day curve is testable.
    The only clock manipulation in this file -- every row's CONTENT still
    comes from the real production write path."""
    with _store(root) as store:
        store.query(f"UPDATE {table} SET {column} = TIMESTAMP '{day} 12:00:00' WHERE {where}")


def _git(repo, *args):
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


@pytest.fixture
def rtl_repo(tmp_path):
    """A REAL git repository with real commits, some touching RTL (.sv) and
    some not. Returns (repo_path, {label: sha})."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "trend test")

    shas = {}

    def commit(label, rel_path, text):
        p = repo / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", label)
        shas[label] = _git(repo, "rev-parse", "HEAD")

    commit("base_rtl", "rtl/usb_link.sv", "module usb_link; endmodule\n")
    commit("doc_only", "docs/notes.md", "notes\n")
    commit("rtl_change_a", "rtl/usb_link.sv", "module usb_link; wire a; endmodule\n")
    commit("tb_only", "tb/usb_tb.py", "print('tb')\n")
    commit("rtl_change_b", "rtl/usb_phy.sv", "module usb_phy; endmodule\n")
    return repo, shas


# --------------------------------------------------------------------------
# 1. runtime capture -- the field that did not exist at all before this task
# --------------------------------------------------------------------------

class TestRuntimeCaptureEndToEnd:
    def test_real_reconcile_batch_records_lsf_run_time_as_seconds(self, tmp_path):
        """The full real path: bjobs RECORD -> reconcile_batch() ->
        JobState.runtime_seconds -> evidence write -> jobs.runtime_seconds."""
        lsf_client.register_external_job(tmp_path, 9001,
                                          log_path="/proj/sim/run/lfps_9001/sim.log",
                                          pattern="usb3_lfps_basic")
        live = {"JOBID": "9001", "STAT": "DONE", "EXIT_CODE": "0", "EXEC_HOST": "host1",
                "QUEUE": "normal", "RUN_TIME": "612 second(s)", "SUBMIT_TIME": "Sep  3 10:00",
                "JOB_NAME": "usb3_lfps_basic"}
        with patch("dv_harness.lsf_client._run_bjobs", return_value={"RECORDS": [live]}):
            reconciled = lsf_client.reconcile_batch(tmp_path, [9001])

        state, _ = reconciled[9001]
        assert state.runtime_seconds == 612.0

        state.sim_status = "PASS"
        rr._write_reconciliation_evidence_if_configured(tmp_path, {9001: (state, [])})
        with _store(tmp_path) as store:
            assert store.query(
                "SELECT runtime_seconds FROM jobs WHERE job_id = 9001") == [(612.0,)]

    def test_run_time_is_monotonic_across_polls(self, tmp_path):
        """A later poll reporting a SMALLER (or absent) runtime must never
        destroy a larger, real, already-observed duration."""
        state = lsf_client.JobState(job_id=1, pattern="p")
        state, _ = lsf_client.reconcile_job(state, {"JOBID": "1", "STAT": "DONE",
                                                     "RUN_TIME": "900"})
        assert state.runtime_seconds == 900.0
        # LSF forgot the job: no RUN_TIME at all in the record.
        state, _ = lsf_client.reconcile_job(state, {"JOBID": "1"})
        assert state.runtime_seconds == 900.0

    @pytest.mark.parametrize("raw,expected", [
        ("612 second(s)", 612.0), ("10", 10.0), ("10 seconds", 10.0),
        ("3.5", 3.5), (42, 42.0), (7.5, 7.5),
        ("-", None), ("", None), (None, None), ("00:10:00", None), (True, None),
    ])
    def test_parse_run_time_seconds_never_guesses(self, raw, expected):
        assert lsf_client.parse_run_time_seconds(raw) == expected

    def test_existing_database_gains_runtime_column_by_migration(self, tmp_path):
        """An evidence.duckdb created BEFORE runtime_seconds existed must gain
        the column on the next connect -- `CREATE TABLE IF NOT EXISTS` alone
        would silently leave every real on-disk database on its old shape, so
        the column would exist only in freshly-created files and every real
        project's already-on-disk database would keep failing the insert.

        The `jobs` table is built here from the REAL pre-migration schema (the
        exact CREATE TABLE this module shipped, minus the one new column), not
        a toy stand-in -- a 3-column stub would fail on `regression_id` long
        before reaching the column under test and prove nothing."""
        db_path = default_db_path(tmp_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        from dv_harness import evidence_db as _edb

        old_jobs_ddl = next(s for s in _edb._SCHEMA_STATEMENTS
                            if "CREATE TABLE IF NOT EXISTS jobs" in s)
        old_jobs_ddl = old_jobs_ddl.replace("        runtime_seconds DOUBLE,\n", "")
        assert "runtime_seconds" not in old_jobs_ddl

        conn = duckdb.connect(str(db_path))
        conn.execute(old_jobs_ddl)
        conn.execute("INSERT INTO jobs (job_id, pattern, sim_status) VALUES (5, 'old', 'PASS')")
        conn.close()

        with _store(tmp_path) as store:  # opening it runs the migration
            store.insert_job_state(lsf_client.JobState(job_id=6, pattern="new",
                                                        sim_status="PASS",
                                                        runtime_seconds=120.0))
            rows = dict(store.query("SELECT job_id, runtime_seconds FROM jobs"))
        assert rows == {5: None, 6: 120.0}  # pre-existing row survives, untouched


# --------------------------------------------------------------------------
# 2. verdict HISTORY -- the upsert used to destroy it
# --------------------------------------------------------------------------

class TestVerdictHistoryEndToEnd:
    def test_snapshot_is_overwritten_but_history_is_appended(self, tmp_path):
        _record_verdict(tmp_path, "usb3_lfps_basic", True, job_id=1, git_sha="aaa")
        _record_verdict(tmp_path, "usb3_lfps_basic", True, job_id=2, git_sha="bbb")
        _record_verdict(tmp_path, "usb3_lfps_basic", False, job_id=3, git_sha="ccc")

        with _store(tmp_path) as store:
            # (1) snapshot semantics unchanged -- still exactly one row per
            # pattern, still the CURRENT verdict, so the MCP regression
            # queries that read this table are unaffected.
            assert store.query("SELECT pattern, verdict_passed, job_id "
                               "FROM regression_verdicts") == [("usb3_lfps_basic", False, 3)]
            # (2) history is now real and complete, with the real SHAs.
            assert store.query("SELECT verdict_passed, job_id, git_sha FROM "
                               "regression_verdict_history ORDER BY id") == [
                (True, 1, "aaa"), (True, 2, "bbb"), (False, 3, "ccc")]

    def test_history_row_records_null_sha_when_job_had_none(self, tmp_path):
        _record_verdict(tmp_path, "p", True, job_id=1)
        with _store(tmp_path) as store:
            assert store.query("SELECT git_sha FROM regression_verdict_history") == [(None,)]


# --------------------------------------------------------------------------
# 3. coverage ingestion -- insert_coverage_sample() had zero call sites
# --------------------------------------------------------------------------

def _write_coverage_summary(root, categories):
    p = root / ".dv-harness" / "coverage" / "summary.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"categories": categories}), encoding="utf-8")
    return p


class TestCoverageIngestionEndToEnd:
    def test_real_production_write_path_lands_rows_in_coverage_samples(self, tmp_path):
        """`dashboard.append_coverage_history_sample()` is the exact function
        engine.py's `_append_coverage_history_sample()` calls on a gate-verified
        COVERAGE_CLOSURE PASS."""
        _write_coverage_summary(tmp_path, [
            {"name": "line", "percent": 91.5, "bins_total": 200, "bins_hit": 183},
            {"name": "functional", "percent": 74.0, "bins_total": 50, "bins_hit": 37},
        ])
        history = dashboard.append_coverage_history_sample(tmp_path, 87.0)

        assert history[-1]["percent"] == 87.0  # flat history file still grows
        with _store(tmp_path) as store:
            rows = store.query("SELECT category_name, percent, bins_total, bins_hit "
                               "FROM coverage_samples ORDER BY category_name")
        assert rows == [("functional", 74.0, 50, 37), ("line", 91.5, 200, 183)]

    def test_repeated_coverage_runs_append_rather_than_overwrite(self, tmp_path):
        _write_coverage_summary(tmp_path, [
            {"name": "line", "percent": 80.0, "bins_total": 100, "bins_hit": 80}])
        dashboard.append_coverage_history_sample(tmp_path, 80.0)
        _write_coverage_summary(tmp_path, [
            {"name": "line", "percent": 90.0, "bins_total": 100, "bins_hit": 90}])
        dashboard.append_coverage_history_sample(tmp_path, 90.0)

        with _store(tmp_path) as store:
            assert store.query("SELECT percent FROM coverage_samples ORDER BY id") == [
                (80.0,), (90.0,)]

    def test_no_summary_file_writes_nothing_and_never_fabricates_bins(self, tmp_path):
        """The caller's aggregate percent carries no real bins_total/bins_hit;
        inventing them to force a row in would put fabricated numbers into the
        evidence database."""
        dashboard.append_coverage_history_sample(tmp_path, 55.0)
        assert not default_db_path(tmp_path).exists()

    def test_disabled_evidence_db_config_skips_ingestion(self, tmp_path):
        from dv_harness import config as _config
        (tmp_path / ".dv-harness").mkdir(parents=True, exist_ok=True)
        cfg = json.loads(json.dumps(_config.DEFAULT_CONFIG))
        cfg["evidence_db"]["enabled"] = False
        (tmp_path / ".dv-harness" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        _write_coverage_summary(tmp_path, [
            {"name": "line", "percent": 80.0, "bins_total": 100, "bins_hit": 80}])

        dashboard.append_coverage_history_sample(tmp_path, 80.0)
        assert not default_db_path(tmp_path).exists()


# --------------------------------------------------------------------------
# 4. daily curves + day over day
# --------------------------------------------------------------------------

class TestDailyRollup:
    def test_four_curves_over_two_real_days(self, tmp_path):
        # --- day 1: 1 of 2 patterns passing, 2 timed jobs, 100 coverage bins
        _record_verdict(tmp_path, "p_a", True, job_id=1, runtime_seconds=1800.0)
        _record_verdict(tmp_path, "p_b", False, job_id=2, runtime_seconds=1800.0)
        _write_coverage_summary(tmp_path, [
            {"name": "line", "percent": 60.0, "bins_total": 100, "bins_hit": 60}])
        dashboard.append_coverage_history_sample(tmp_path, 60.0)
        for table, col in (("regression_verdict_history", "recorded_at"),
                           ("jobs", "ingested_at"), ("coverage_samples", "ingested_at")):
            _backdate(tmp_path, table, col, "2026-09-01")

        # --- day 2: both patterns passing, 2 timed jobs, coverage up
        _record_verdict(tmp_path, "p_a", True, job_id=3, runtime_seconds=3600.0)
        _record_verdict(tmp_path, "p_b", True, job_id=4, runtime_seconds=3600.0)
        _write_coverage_summary(tmp_path, [
            {"name": "line", "percent": 90.0, "bins_total": 100, "bins_hit": 90}])
        dashboard.append_coverage_history_sample(tmp_path, 90.0)
        for table, col, where in (("regression_verdict_history", "recorded_at", "job_id IN (3,4)"),
                                  ("jobs", "ingested_at", "job_id IN (3,4)"),
                                  ("coverage_samples", "ingested_at", "percent = 90.0")):
            _backdate(tmp_path, table, col, "2026-09-02", where=where)

        with _store(tmp_path) as store:
            points = ta.daily_rollup(store)

        assert [p.day for p in points] == ["2026-09-01", "2026-09-02"]
        d1, d2 = points
        assert d1.pass_rate_percent == 50.0 and d2.pass_rate_percent == 100.0
        assert d1.coverage_percent == 60.0 and d2.coverage_percent == 90.0
        assert d1.total_runtime_hours == 1.0 and d2.total_runtime_hours == 2.0
        assert d1.license_hours == 1.0 and d2.license_hours == 2.0
        assert d1.job_count == 2 and d2.job_count == 2

        dod = ta.day_over_day(points)
        assert dod["latest_day"] == "2026-09-02" and dod["previous_day"] == "2026-09-01"
        assert dod["pass_rate_percent"]["delta"] == 50.0
        assert dod["coverage_percent"]["delta"] == 30.0
        assert dod["total_runtime_hours"]["delta"] == 1.0
        assert dod["license_hours"]["delta"] == 1.0

    def test_seats_per_job_scales_only_the_license_curve(self, tmp_path):
        _record_verdict(tmp_path, "p", True, job_id=1, runtime_seconds=3600.0)
        with _store(tmp_path) as store:
            single = ta.daily_rollup(store)[0]
            dual = ta.daily_rollup(store, seats_per_job=2.0)[0]
        assert single.total_runtime_hours == dual.total_runtime_hours == 1.0
        assert single.license_hours == 1.0 and dual.license_hours == 2.0

    def test_metric_with_no_evidence_is_none_never_zero(self, tmp_path):
        """A day with verdicts but no coverage samples and no timed jobs must
        not render as a real measured 0% coverage / 0 runtime hours."""
        state = lsf_client.JobState(job_id=1, pattern="p", lsf_status="DONE",
                                     sim_status="PASS", runtime_seconds=None)
        rr._write_reconciliation_evidence_if_configured(tmp_path, {1: (state, [])})
        with _store(tmp_path) as store:
            point = ta.daily_rollup(store)[0]
        assert point.pass_rate_percent == 100.0
        assert point.coverage_percent is None
        assert point.total_runtime_hours is None
        assert point.license_hours is None
        assert point.job_count == 1 and point.runtime_job_count == 0

    def test_day_over_day_needs_two_days(self, tmp_path):
        _record_verdict(tmp_path, "p", True, job_id=1)
        with _store(tmp_path) as store:
            assert ta.day_over_day(ta.daily_rollup(store)) is None

    def test_coverage_curve_is_bins_weighted_not_a_mean_of_percents(self, tmp_path):
        """A 4000-bin category must not be outvoted by a 12-bin one."""
        _write_coverage_summary(tmp_path, [
            {"name": "big", "percent": 50.0, "bins_total": 4000, "bins_hit": 2000},
            {"name": "small", "percent": 100.0, "bins_total": 12, "bins_hit": 12}])
        dashboard.append_coverage_history_sample(tmp_path, 50.0)
        with _store(tmp_path) as store:
            point = ta.daily_rollup(store)[0]
        # bins-weighted = 2012/4012 = 50.15%, NOT the 75.0% naive mean.
        assert point.coverage_percent == pytest.approx(50.1496, abs=1e-3)


# --------------------------------------------------------------------------
# 5. regression detection + bisect to an RTL commit
# --------------------------------------------------------------------------

class TestRegressionDetection:
    def test_pass_then_fail_is_a_regression_with_both_shas(self, tmp_path):
        _record_verdict(tmp_path, "p", True, job_id=1, git_sha="good")
        _record_verdict(tmp_path, "p", False, job_id=2, git_sha="bad")
        with _store(tmp_path) as store:
            regs = ta.detect_pattern_regressions(store)
        assert len(regs) == 1
        assert (regs[0].pattern, regs[0].last_good_sha, regs[0].first_bad_sha) == ("p", "good", "bad")
        assert regs[0].bisectable is True

    def test_currently_passing_pattern_is_not_a_regression(self, tmp_path):
        _record_verdict(tmp_path, "p", True, job_id=1, git_sha="a")
        _record_verdict(tmp_path, "p", False, job_id=2, git_sha="b")
        _record_verdict(tmp_path, "p", True, job_id=3, git_sha="c")
        with _store(tmp_path) as store:
            assert ta.detect_pattern_regressions(store) == []

    def test_reports_the_current_breakage_not_a_stale_earlier_one(self, tmp_path):
        """Broke at b, was fixed at c, broke again at d -> the range to
        investigate is c..d, never the stale a..b."""
        _record_verdict(tmp_path, "p", True, job_id=1, git_sha="a")
        _record_verdict(tmp_path, "p", False, job_id=2, git_sha="b")
        _record_verdict(tmp_path, "p", True, job_id=3, git_sha="c")
        _record_verdict(tmp_path, "p", False, job_id=4, git_sha="d")
        with _store(tmp_path) as store:
            reg = ta.detect_pattern_regressions(store)[0]
        assert (reg.last_good_sha, reg.first_bad_sha) == ("c", "d")

    def test_pattern_that_never_passed_is_not_reported_as_a_regression(self, tmp_path):
        _record_verdict(tmp_path, "p", False, job_id=1, git_sha="a")
        _record_verdict(tmp_path, "p", False, job_id=2, git_sha="b")
        with _store(tmp_path) as store:
            assert ta.detect_pattern_regressions(store) == []

    def test_same_sha_passing_then_failing_is_flagged_unbisectable(self, tmp_path):
        """The same commit both passed and failed -- the cause is NOT an RTL
        change, and a bisect over an empty range would be a fabricated answer."""
        _record_verdict(tmp_path, "p", True, job_id=1, git_sha="same")
        _record_verdict(tmp_path, "p", False, job_id=2, git_sha="same")
        with _store(tmp_path) as store:
            reg = ta.detect_pattern_regressions(store)[0]
        assert reg.bisectable is False
        assert reg.reason == "SAME_GIT_SHA_PASSED_AND_FAILED"

    def test_missing_sha_is_flagged_unbisectable_rather_than_guessed(self, tmp_path):
        _record_verdict(tmp_path, "p", True, job_id=1, git_sha=None)
        _record_verdict(tmp_path, "p", False, job_id=2, git_sha="bad")
        with _store(tmp_path) as store:
            reg = ta.detect_pattern_regressions(store)[0]
        assert reg.bisectable is False and reg.reason == "NO_GIT_SHA_RECORDED"


class TestBisectToRtlCommit:
    def test_single_rtl_commit_in_range_is_identified(self, tmp_path, rtl_repo):
        repo, shas = rtl_repo
        _record_verdict(tmp_path, "p", True, job_id=1, git_sha=shas["rtl_change_a"])
        _record_verdict(tmp_path, "p", False, job_id=2, git_sha=shas["rtl_change_b"])
        with _store(tmp_path) as store:
            reg = ta.detect_pattern_regressions(store)[0]
        result = ta.bisect_regression_to_rtl_commit(repo, reg)

        assert result.status == "IDENTIFIED_COMMIT"
        assert result.identified_commit["sha"] == shas["rtl_change_b"]
        assert result.identified_commit["subject"] == "rtl_change_b"
        assert result.identified_commit["rtl_files"] == ["rtl/usb_phy.sv"]
        # tb_only was in the range but is correctly not an RTL candidate.
        assert result.total_commits_in_range == 2

    def test_multiple_rtl_commits_yield_a_candidate_range_and_a_real_bisect_plan(
            self, tmp_path, rtl_repo):
        repo, shas = rtl_repo
        _record_verdict(tmp_path, "p", True, job_id=1, git_sha=shas["base_rtl"])
        _record_verdict(tmp_path, "p", False, job_id=2, git_sha=shas["rtl_change_b"])
        with _store(tmp_path) as store:
            reg = ta.detect_pattern_regressions(store)[0]
        result = ta.bisect_regression_to_rtl_commit(repo, reg)

        assert result.status == "CANDIDATE_RANGE"
        assert [c["subject"] for c in result.candidate_commits] == ["rtl_change_a", "rtl_change_b"]
        assert result.total_commits_in_range == 4
        assert result.bisect_plan[0] == (
            f"git bisect start {shas['rtl_change_b']} {shas['base_rtl']}")

    def test_no_rtl_commit_in_range_is_a_real_negative_result(self, tmp_path, rtl_repo):
        """base_rtl..doc_only contains one real commit, and it touched no RTL:
        look at testbench/VIP/constraint/seed/environment instead."""
        repo, shas = rtl_repo
        _record_verdict(tmp_path, "p", True, job_id=1, git_sha=shas["base_rtl"])
        _record_verdict(tmp_path, "p", False, job_id=2, git_sha=shas["doc_only"])
        with _store(tmp_path) as store:
            reg = ta.detect_pattern_regressions(store)[0]
        result = ta.bisect_regression_to_rtl_commit(repo, reg)

        assert result.status == "NO_RTL_COMMITS_IN_RANGE"
        assert result.total_commits_in_range == 1
        assert result.candidate_commits == []

    def test_sha_absent_from_this_checkout_is_reported_honestly(self, tmp_path, rtl_repo):
        """A SHA from a different checkout must NOT silently produce an empty
        range that would read as 'no RTL commit is responsible'."""
        repo, shas = rtl_repo
        _record_verdict(tmp_path, "p", True, job_id=1, git_sha=shas["base_rtl"])
        _record_verdict(tmp_path, "p", False, job_id=2, git_sha="0" * 40)
        with _store(tmp_path) as store:
            reg = ta.detect_pattern_regressions(store)[0]
        result = ta.bisect_regression_to_rtl_commit(repo, reg)

        assert result.status == "SHA_NOT_IN_REPO"
        assert "0" * 40 in result.detail

    def test_unbisectable_regression_short_circuits(self, tmp_path, rtl_repo):
        repo, _ = rtl_repo
        _record_verdict(tmp_path, "p", True, job_id=1, git_sha="same")
        _record_verdict(tmp_path, "p", False, job_id=2, git_sha="same")
        with _store(tmp_path) as store:
            reg = ta.detect_pattern_regressions(store)[0]
        result = ta.bisect_regression_to_rtl_commit(repo, reg)
        assert result.status == "NOT_BISECTABLE"
        assert result.detail == "SAME_GIT_SHA_PASSED_AND_FAILED"

    def test_custom_pathspec_changes_what_counts_as_rtl(self, tmp_path, rtl_repo):
        repo, shas = rtl_repo
        _record_verdict(tmp_path, "p", True, job_id=1, git_sha=shas["rtl_change_a"])
        _record_verdict(tmp_path, "p", False, job_id=2, git_sha=shas["rtl_change_b"])
        with _store(tmp_path) as store:
            reg = ta.detect_pattern_regressions(store)[0]
        result = ta.bisect_regression_to_rtl_commit(repo, reg, pathspecs=("tb/*",))
        assert result.status == "IDENTIFIED_COMMIT"
        assert result.identified_commit["subject"] == "tb_only"


# --------------------------------------------------------------------------
# 6. runtime anomaly detection
# --------------------------------------------------------------------------

def _seed_runtimes(root, pattern, runtimes, *, sim_status="PASS", first_job_id=100):
    for i, seconds in enumerate(runtimes):
        state = lsf_client.JobState(job_id=first_job_id + i, pattern=pattern,
                                     lsf_status="DONE", sim_status=sim_status,
                                     runtime_seconds=float(seconds))
        rr._write_reconciliation_evidence_if_configured(root, {state.job_id: (state, [])})


class TestRuntimeAnomalies:
    def test_passing_but_far_slower_than_its_own_baseline_is_flagged(self, tmp_path):
        _seed_runtimes(tmp_path, "usb3_lfps_basic", [100, 102, 98, 101, 99, 500])
        with _store(tmp_path) as store:
            anomalies = ta.detect_runtime_anomalies(store)
        assert len(anomalies) == 1
        a = anomalies[0]
        assert a.pattern == "usb3_lfps_basic" and a.runtime_seconds == 500.0
        assert a.baseline_median_seconds == 100.0
        assert a.baseline_sample_count == 5
        assert a.ratio_to_median == 5.0
        assert "RATIO_GE" in a.reason

    def test_a_normal_run_is_not_flagged(self, tmp_path):
        _seed_runtimes(tmp_path, "p", [100, 102, 98, 101, 99, 104])
        with _store(tmp_path) as store:
            assert ta.detect_runtime_anomalies(store) == []

    def test_too_few_prior_runs_yields_no_verdict_at_all(self, tmp_path):
        """An 'anomaly' called against two prior runs is noise; reporting it
        would train a reader to ignore this detector."""
        _seed_runtimes(tmp_path, "p", [100, 100, 900])
        with _store(tmp_path) as store:
            assert ta.detect_runtime_anomalies(store) == []

    def test_failing_jobs_neither_form_the_baseline_nor_get_flagged(self, tmp_path):
        """A FAILing job's runtime is a different distribution (an early
        UVM_FATAL exits fast, a hang runs to timeout)."""
        _seed_runtimes(tmp_path, "p", [100, 102, 98, 101, 99], first_job_id=100)
        _seed_runtimes(tmp_path, "p", [5000], sim_status="FAIL", first_job_id=200)
        with _store(tmp_path) as store:
            anomalies = ta.detect_runtime_anomalies(store)
        assert anomalies == []

    def test_the_outlier_does_not_inflate_the_baseline_it_is_judged_against(self, tmp_path):
        """Self-exclusion: without it a single enormous run drags up the very
        median it is compared to and hides itself."""
        _seed_runtimes(tmp_path, "p", [10, 10, 10, 10, 10, 10000])
        with _store(tmp_path) as store:
            a = ta.detect_runtime_anomalies(store)[0]
        assert a.baseline_median_seconds == 10.0
        assert a.baseline_sample_count == 5
        assert a.runtime_seconds == 10000.0

    def test_zero_variance_baseline_gives_no_z_score_and_never_divides_by_zero(self, tmp_path):
        _seed_runtimes(tmp_path, "p", [10, 10, 10, 10, 10, 40])
        with _store(tmp_path) as store:
            a = ta.detect_runtime_anomalies(store)[0]
        assert a.z_score is None
        assert a.baseline_stddev_seconds is None
        assert a.reason == "RATIO_GE_2.0X_MEDIAN"

    def test_ratio_threshold_is_tunable(self, tmp_path):
        """150s against a 100s median is 1.5x -- under the 2.0x default, over a
        1.4x setting. (z is disabled here with an unreachable threshold so this
        test measures only the ratio trigger; the two triggers are OR'd.)"""
        _seed_runtimes(tmp_path, "p", [100, 102, 98, 101, 99, 150])
        with _store(tmp_path) as store:
            assert ta.detect_runtime_anomalies(store, z_threshold=1e9) == []
            loose = ta.detect_runtime_anomalies(store, ratio_threshold=1.4, z_threshold=1e9)
        assert len(loose) == 1 and loose[0].runtime_seconds == 150.0

    def test_z_score_fires_on_a_tight_baseline_the_ratio_test_would_miss(self, tmp_path):
        """Real, intended behaviour worth pinning rather than an accident: a
        pattern that always runs 100s +/- 1.6s and one day takes 150s is only
        1.5x the median (under the ratio threshold) but ~32 sigma out. That is
        a genuinely abnormal run for THAT pattern, and catching it is exactly
        why the two triggers are OR'd instead of AND'd -- a stable, fast test
        degrading by half is real evidence a pass/fail view cannot see."""
        _seed_runtimes(tmp_path, "p", [100, 102, 98, 101, 99, 150])
        with _store(tmp_path) as store:
            a = ta.detect_runtime_anomalies(store)[0]
        assert a.reason == "Z_SCORE_GE_3.0"
        assert a.ratio_to_median == 1.5           # ratio trigger did NOT fire
        assert a.z_score > 3.0
        with _store(tmp_path) as store:
            assert ta.detect_runtime_anomalies(store, z_threshold=100.0) == []

    def test_jobs_with_no_recorded_runtime_are_simply_absent(self, tmp_path):
        _seed_runtimes(tmp_path, "p", [100, 102, 98, 101, 99, 500])
        state = lsf_client.JobState(job_id=999, pattern="p", lsf_status="DONE",
                                     sim_status="PASS", runtime_seconds=None)
        rr._write_reconciliation_evidence_if_configured(tmp_path, {999: (state, [])})
        with _store(tmp_path) as store:
            anomalies = ta.detect_runtime_anomalies(store)
        assert [a.job_id for a in anomalies] == [105]


# --------------------------------------------------------------------------
# 7. the whole report, and the real CLI
# --------------------------------------------------------------------------

class TestTrendReportAndCli:
    def test_no_database_yet_is_an_honest_unavailable_not_empty_curves(self, tmp_path):
        report = ta.trend_report(tmp_path)
        assert report["available"] is False
        assert "no evidence database yet" in report["reason"]

    def test_trend_report_opens_the_store_read_only(self, tmp_path):
        """This report must never create or migrate a database, nor block a
        concurrently-running lsf-watch writer."""
        _record_verdict(tmp_path, "p", True, job_id=1, runtime_seconds=60.0)
        with patch("dv_harness.evidence_db.EvidenceStore.__init__",
                   autospec=True, side_effect=EvidenceStore.__init__) as spy:
            ta.trend_report(tmp_path)
        assert spy.call_args.kwargs.get("read_only") is True

    def test_full_report_carries_all_four_sections(self, tmp_path, rtl_repo):
        repo, shas = rtl_repo
        # Put the evidence db inside the real git repo so the bisect runs
        # against that repo's own history, exactly as a real project does.
        _record_verdict(repo, "p", True, job_id=1, git_sha=shas["rtl_change_a"],
                        runtime_seconds=100.0)
        _record_verdict(repo, "p", False, job_id=2, git_sha=shas["rtl_change_b"],
                        runtime_seconds=100.0)
        report = ta.trend_report(repo)

        assert report["available"] is True
        assert len(report["daily"]) == 1
        assert report["day_over_day"] is None
        assert report["regressions"][0]["pattern"] == "p"
        assert report["bisects"][0]["status"] == "IDENTIFIED_COMMIT"
        assert report["runtime_anomalies"] == []
        assert "not a measured license checkout" in report["license_hours_model"]
        # JSON-serializable end to end (the CLI's --json path).
        json.dumps(report)

        text = ta.render_trend_report_text(report)
        assert "REGRESSIONS (PASS -> FAIL)" in text
        assert "responsible commit" in text
        assert shas["rtl_change_b"][:12] in text

    def test_real_cli_trend_command_runs_end_to_end(self, tmp_path):
        _record_verdict(tmp_path, "usb3_lfps_basic", True, job_id=1, runtime_seconds=3600.0)
        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness", "--project-root", str(tmp_path),
             "trend", "--json"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout[proc.stdout.index("{"):])
        assert payload["available"] is True
        assert payload["daily"][0]["pass_rate_percent"] == 100.0
        assert payload["daily"][0]["total_runtime_hours"] == 1.0
        assert payload["daily"][0]["license_hours"] == 1.0

    def test_real_cli_trend_text_output(self, tmp_path):
        _record_verdict(tmp_path, "p", True, job_id=1, runtime_seconds=3600.0)
        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness", "--project-root", str(tmp_path), "trend"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
        assert proc.returncode == 0, proc.stderr
        assert "DAY" in proc.stdout and "LIC_H" in proc.stdout
        assert "RUNTIME ANOMALIES" in proc.stdout
