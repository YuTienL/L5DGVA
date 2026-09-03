"""Tests for the real EvidenceStore WIRING (2026-09-03, evidence-db-wiring
step 1) into regression_reporter.run_reconciliation_cycle() via
regression_reporter._write_reconciliation_evidence_if_configured(), and
(evidence-db-wiring STEP 2) the vip_distill.py -> EvidenceStore.
normalized_evidence bridge via
regression_reporter._write_normalized_evidence_if_configured().

Before step 1, dv_harness/evidence_db.py's EvidenceStore was a real,
individually-tested class (see test_evidence_db.py) with no real caller
anywhere in this codebase -- .dv-harness/evidence/evidence.duckdb never got
written by any real reconciliation cycle. Before step 2, vip_distill.py's
Normalized Evidence JSON had nowhere to land even after step 1 landed (see
.work/governance-vip-distill-report.md's own "Schema reconciliation note").
These tests prove both gaps are closed: a real run_reconciliation_cycle()
call leaves real rows in jobs/regression_verdicts/normalized_evidence,
readable back through a fresh EvidenceStore/duckdb connection (no mocking
of EvidenceStore or vip_distill themselves -- only the LSF/live-job
discovery layer this file's own pre-existing tests already mock)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness import regression_reporter as rr
from dv_harness import lsf_client
from dv_harness import vip_distill as vd
from dv_harness.evidence_db import EvidenceStore, default_db_path


def _write_job(root, job_id, **kwargs):
    state = lsf_client.JobState(job_id=job_id, **kwargs)
    lsf_client.save_job_state(root, state)
    return state


# --- unit-level: _write_reconciliation_evidence_if_configured() ------------


class TestWriteReconciliationEvidenceIfConfigured:
    def test_pass_job_writes_job_state_and_regression_verdict(self, tmp_path):
        state = lsf_client.JobState(job_id=111, pattern="foo", lsf_status="DONE",
                                     sim_status="PASS", uvm_error_count=0, uvm_fatal_count=0)
        reconciled = {111: (state, [])}
        rr._write_reconciliation_evidence_if_configured(tmp_path, reconciled)

        db_path = default_db_path(tmp_path)
        assert db_path.exists()
        with EvidenceStore(db_path) as store:
            job_rows = store.query("SELECT job_id, pattern, sim_status FROM jobs")
            assert job_rows == [(111, "foo", "PASS")]
            verdict_rows = store.query(
                "SELECT pattern, verdict_passed, job_id FROM regression_verdicts")
            assert verdict_rows == [("foo", True, 111)]

    def test_fail_job_writes_job_state_and_failing_regression_verdict(self, tmp_path):
        state = lsf_client.JobState(job_id=222, pattern="bar", lsf_status="EXIT",
                                     sim_status="FAIL", uvm_error_count=5, uvm_fatal_count=1)
        reconciled = {222: (state, [])}
        rr._write_reconciliation_evidence_if_configured(tmp_path, reconciled)

        with EvidenceStore(default_db_path(tmp_path)) as store:
            verdict_rows = store.query(
                "SELECT pattern, verdict_passed FROM regression_verdicts")
            assert verdict_rows == [("bar", False)]

    def test_indeterminate_verdict_writes_job_state_but_no_regression_verdict(self, tmp_path):
        """Mirrors the EXACT condition the regression-list safety net uses
        at its own apply_verdict_to_file() call site (state.pattern and
        verdict in ("PASSED", "FAILED")) -- an UNKNOWN/RUNNING sim_status
        (no determinate verdict yet) must still get its job state recorded
        (a job's own state IS the fact being recorded) but must NOT mint a
        regression_verdicts row, exactly as apply_verdict_to_file() itself
        would not be called for it."""
        state = lsf_client.JobState(job_id=333, pattern="baz", lsf_status="RUN",
                                     sim_status="UNKNOWN")
        reconciled = {333: (state, [])}
        rr._write_reconciliation_evidence_if_configured(tmp_path, reconciled)

        with EvidenceStore(default_db_path(tmp_path)) as store:
            job_rows = store.query("SELECT job_id FROM jobs")
            assert job_rows == [(333,)]
            assert store.query("SELECT count(*) FROM regression_verdicts")[0][0] == 0

    def test_pattern_missing_writes_job_state_but_no_regression_verdict(self, tmp_path):
        state = lsf_client.JobState(job_id=444, pattern=None, lsf_status="DONE",
                                     sim_status="PASS")
        reconciled = {444: (state, [])}
        rr._write_reconciliation_evidence_if_configured(tmp_path, reconciled)

        with EvidenceStore(default_db_path(tmp_path)) as store:
            assert store.query("SELECT job_id FROM jobs")[0] == (444,)
            assert store.query("SELECT count(*) FROM regression_verdicts")[0][0] == 0

    def test_empty_reconciled_writes_nothing_but_creates_no_error(self, tmp_path):
        rr._write_reconciliation_evidence_if_configured(tmp_path, {})
        # Best-effort function still constructs the store (schema init is
        # idempotent CREATE TABLE IF NOT EXISTS), so the file exists with
        # empty tables rather than not existing at all.
        with EvidenceStore(default_db_path(tmp_path)) as store:
            assert store.query("SELECT count(*) FROM jobs")[0][0] == 0

    def test_disabled_config_skips_the_write_entirely(self, tmp_path):
        (tmp_path / ".dv-harness").mkdir()
        from dv_harness import config as _config
        cfg = json.loads(json.dumps(_config.DEFAULT_CONFIG))
        cfg["evidence_db"]["enabled"] = False
        (tmp_path / ".dv-harness" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

        state = lsf_client.JobState(job_id=555, pattern="qux", lsf_status="DONE",
                                     sim_status="PASS")
        rr._write_reconciliation_evidence_if_configured(tmp_path, {555: (state, [])})

        assert not default_db_path(tmp_path).exists()

    def test_construction_failure_never_raises(self, tmp_path):
        """A locked/corrupt DB file (or any other EvidenceStore construction
        failure) must never break the reconciliation cycle's own real work
        -- same discipline _escalate_uvm_fatal_burst_if_needed() already
        follows for its own side-effect."""
        state = lsf_client.JobState(job_id=666, pattern="corrupt", lsf_status="DONE",
                                     sim_status="PASS")
        with patch("dv_harness.evidence_db.EvidenceStore",
                   side_effect=RuntimeError("simulated locked/corrupt DB file")):
            rr._write_reconciliation_evidence_if_configured(tmp_path, {666: (state, [])})
        # No exception escaped -- that is the entire assertion.

    def test_one_bad_insert_among_siblings_does_not_block_jobs_after_it(self, tmp_path):
        """Fault-injection mirror of
        test_unreadable_sim_log_for_one_job_does_not_block_another() below,
        proving the same per-job isolation for THIS function (post-review
        fix): with only an outer try/except, a raise from
        insert_job_state() for one job in the middle of iteration order used
        to abort the whole loop, silently dropping every job after it too --
        not just the bad one. 801/802/803 here mirror the reviewer's own
        real fault-injection scenario (three jobs, the middle one's
        insert_job_state() raises); both siblings, INCLUDING the one after
        the bad job in iteration order, must still land."""
        state_801 = lsf_client.JobState(job_id=801, pattern="p801", lsf_status="DONE",
                                         sim_status="PASS")
        state_802 = lsf_client.JobState(job_id=802, pattern="p802", lsf_status="DONE",
                                         sim_status="PASS")
        state_803 = lsf_client.JobState(job_id=803, pattern="p803", lsf_status="DONE",
                                         sim_status="PASS")
        reconciled = {801: (state_801, []), 802: (state_802, []), 803: (state_803, [])}

        real_insert_job_state = EvidenceStore.insert_job_state

        def _raise_for_802(self, state):
            if getattr(state, "job_id", None) == 802 or (
                    isinstance(state, dict) and state.get("job_id") == 802):
                raise RuntimeError("simulated insert failure for job 802")
            return real_insert_job_state(self, state)

        with patch.object(EvidenceStore, "insert_job_state", _raise_for_802):
            rr._write_reconciliation_evidence_if_configured(tmp_path, reconciled)

        with EvidenceStore(default_db_path(tmp_path)) as store:
            job_ids = {row[0] for row in store.query("SELECT job_id FROM jobs")}
            # The bad job (802) is the only one missing; both good siblings
            # -- including 803, which comes AFTER the bad job in iteration
            # order -- are still present.
            assert job_ids == {801, 803}
            verdict_patterns = {row[0] for row in
                                 store.query("SELECT pattern FROM regression_verdicts")}
            assert verdict_patterns == {"p801", "p803"}


# --- unit-level: _write_normalized_evidence_if_configured() (step 2) -------


_PASS_SIM_LOG = (
    "some output\nFINAL CHECK @ 1000 ns\n"
    "UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0\nVERDICT: PASSED\n"
)
_FAIL_SIM_LOG = (
    "UVM_ERROR test_top.sv(10) @ 500 ns: scoreboard mismatch\n"
    "FINAL CHECK @ 1000 ns\n"
    "UVM_FATAL = 0, UVM_ERROR = 1, UVM_WARNING = 0\nVERDICT: FAILED\n"
)


class TestWriteNormalizedEvidenceIfConfigured:
    def test_job_with_sim_log_writes_normalized_evidence_row(self, tmp_path):
        log_path = tmp_path / "sim.log"
        log_path.write_text(_PASS_SIM_LOG)
        state = lsf_client.JobState(job_id=111, pattern="foo", sim_log=str(log_path),
                                     lsf_status="DONE", sim_status="PASS")
        rr._write_normalized_evidence_if_configured(tmp_path, {111: (state, [])})

        with EvidenceStore(default_db_path(tmp_path)) as store:
            rows = store.query(
                "SELECT schema_version, source_kind, job_id, pattern, verdict "
                "FROM normalized_evidence")
            assert rows == [(vd.NORMALIZED_EVIDENCE_SCHEMA_VERSION, "sim_log", 111, "foo", "PASSED")]

    def test_job_without_sim_log_is_skipped(self, tmp_path):
        state = lsf_client.JobState(job_id=222, pattern="bar", sim_log=None,
                                     lsf_status="DONE", sim_status="PASS")
        rr._write_normalized_evidence_if_configured(tmp_path, {222: (state, [])})

        with EvidenceStore(default_db_path(tmp_path)) as store:
            assert store.query("SELECT count(*) FROM normalized_evidence")[0][0] == 0

    def test_disabled_config_skips_the_write_entirely(self, tmp_path):
        (tmp_path / ".dv-harness").mkdir()
        from dv_harness import config as _config
        cfg = json.loads(json.dumps(_config.DEFAULT_CONFIG))
        cfg["evidence_db"]["enabled"] = False
        (tmp_path / ".dv-harness" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

        log_path = tmp_path / "sim.log"
        log_path.write_text(_PASS_SIM_LOG)
        state = lsf_client.JobState(job_id=333, pattern="baz", sim_log=str(log_path),
                                     lsf_status="DONE", sim_status="PASS")
        rr._write_normalized_evidence_if_configured(tmp_path, {333: (state, [])})

        assert not default_db_path(tmp_path).exists()

    def test_unreadable_sim_log_for_one_job_does_not_block_another(self, tmp_path):
        """distill_sim_log() raises when the log file cannot be read --
        best-effort, per-job try/except must isolate that failure so a
        sibling job's real evidence still lands."""
        good_log = tmp_path / "good.log"
        good_log.write_text(_PASS_SIM_LOG)
        bad_state = lsf_client.JobState(job_id=444, pattern="missing",
                                         sim_log=str(tmp_path / "does_not_exist.log"),
                                         lsf_status="DONE", sim_status="UNKNOWN")
        good_state = lsf_client.JobState(job_id=555, pattern="ok", sim_log=str(good_log),
                                          lsf_status="DONE", sim_status="PASS")
        rr._write_normalized_evidence_if_configured(
            tmp_path, {444: (bad_state, []), 555: (good_state, [])})

        with EvidenceStore(default_db_path(tmp_path)) as store:
            rows = store.query("SELECT job_id FROM normalized_evidence")
            assert rows == [(555,)]

    def test_construction_failure_never_raises(self, tmp_path):
        log_path = tmp_path / "sim.log"
        log_path.write_text(_PASS_SIM_LOG)
        state = lsf_client.JobState(job_id=666, pattern="corrupt", sim_log=str(log_path),
                                     lsf_status="DONE", sim_status="PASS")
        with patch("dv_harness.evidence_db.EvidenceStore",
                   side_effect=RuntimeError("simulated locked/corrupt DB file")):
            rr._write_normalized_evidence_if_configured(tmp_path, {666: (state, [])})
        # No exception escaped -- that is the entire assertion.


# --- end-to-end: real run_reconciliation_cycle() ---------------------------


class TestReconciliationCycleEndToEndEvidenceWrite:
    def test_full_cycle_leaves_real_rows_in_evidence_duckdb(self, tmp_path):
        """The test that proves 'DuckDB stops being empty': a real
        run_reconciliation_cycle() call (only the LSF discovery layer
        mocked, exactly like this file's other reconciliation-cycle tests)
        leaves real, independently-readable rows in jobs/
        regression_verdicts."""
        uvm_root = tmp_path / "uvm"
        run_dir = tmp_path / "sim" / "run" / "foo_1"
        run_dir.mkdir(parents=True)
        log_path = run_dir / "sim.log"
        log_path.write_text(
            "some output\nFINAL CHECK @ 1000 ns\n"
            "UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0\nVERDICT: PASSED\n"
        )
        _write_job(tmp_path, 111, pattern="foo", sim_log=str(log_path), lsf_status="RUN")

        live_bjobs = [{"job_id": 111, "stat": "DONE", "queue": "normal",
                       "exec_host": "host1", "job_name": "foo", "submit_time": "x"}]
        with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                   return_value=live_bjobs), \
             patch("dv_harness.regression_reporter.lsf_client._run_bjobs",
                   return_value={"RECORDS": [{"JOBID": "111", "STAT": "DONE"}]}):
            rr.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)

        # The cycle's own pre-existing real work still happened.
        assert (uvm_root / "regression.list").read_text().splitlines() == ["foo"]

        # ...and it is now ALSO durably recorded in DuckDB, opened fresh
        # (independent of whatever connection the cycle itself used).
        db_path = default_db_path(tmp_path)
        assert db_path.exists()
        with EvidenceStore(db_path) as store:
            job_rows = store.query(
                "SELECT job_id, pattern, sim_status, uvm_error_count, uvm_fatal_count "
                "FROM jobs WHERE job_id = 111")
            assert job_rows == [(111, "foo", "PASS", 0, 0)]
            verdict_rows = store.query(
                "SELECT pattern, verdict_passed, job_id FROM regression_verdicts "
                "WHERE pattern = 'foo'")
            assert verdict_rows == [("foo", True, 111)]

    def test_full_cycle_normalized_evidence_row_is_consistent_with_job_and_verdict_rows(self, tmp_path):
        """The step-2 counterpart of the test above: a real
        run_reconciliation_cycle() call also leaves a real
        normalized_evidence row (vip_distill's own schema_version, real
        distilled content), and it carries the SAME job/pattern identity as
        this cycle's own jobs/regression_verdicts rows for that job --
        proving the bridge reconciles into the store rather than minting a
        disconnected third shape."""
        uvm_root = tmp_path / "uvm"
        run_dir = tmp_path / "sim" / "run" / "baz_1"
        run_dir.mkdir(parents=True)
        log_path = run_dir / "sim.log"
        log_path.write_text(_FAIL_SIM_LOG)
        _write_job(tmp_path, 333, pattern="baz", sim_log=str(log_path), lsf_status="RUN")

        live_bjobs = [{"job_id": 333, "stat": "DONE", "queue": "normal",
                       "exec_host": "host1", "job_name": "baz", "submit_time": "x"}]
        with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                   return_value=live_bjobs), \
             patch("dv_harness.regression_reporter.lsf_client._run_bjobs",
                   return_value={"RECORDS": [{"JOBID": "333", "STAT": "DONE"}]}):
            rr.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)

        with EvidenceStore(default_db_path(tmp_path)) as store:
            job_rows = store.query(
                "SELECT job_id, pattern, sim_status FROM jobs WHERE job_id = 333")
            assert job_rows == [(333, "baz", "FAIL")]

            verdict_rows = store.query(
                "SELECT pattern, verdict_passed, job_id FROM regression_verdicts "
                "WHERE pattern = 'baz'")
            assert verdict_rows == [("baz", False, 333)]

            ne_rows = store.query(
                "SELECT schema_version, source_kind, job_id, pattern, verdict, counts_json "
                "FROM normalized_evidence WHERE job_id = 333")
            assert len(ne_rows) == 1
            schema_version, source_kind, ne_job_id, ne_pattern, verdict, counts_json = ne_rows[0]
            assert schema_version == vd.NORMALIZED_EVIDENCE_SCHEMA_VERSION
            assert source_kind == "sim_log"
            assert verdict == "FAILED"
            assert json.loads(counts_json) == {"uvm_fatal": 0, "uvm_error": 1, "uvm_warning": 0}

            # Same job/pattern identity across all three tables -- no
            # duplication, no drift between what this bridge stored and
            # what step 1's own writer stored for the SAME reconciled job.
            assert ne_job_id == 333 == job_rows[0][0] == verdict_rows[0][2]
            assert ne_pattern == "baz" == job_rows[0][1] == verdict_rows[0][0]

    def test_db_write_failure_does_not_break_the_reconciliation_cycle(self, tmp_path):
        """A corrupt/unopenable evidence.duckdb file must not prevent the
        cycle's own real reconciliation work (job state persistence,
        regression.list safety net, snapshot rendering) from completing."""
        uvm_root = tmp_path / "uvm"
        run_dir = tmp_path / "sim" / "run" / "bar_1"
        run_dir.mkdir(parents=True)
        log_path = run_dir / "sim.log"
        log_path.write_text(
            "some output\nFINAL CHECK @ 1000 ns\n"
            "UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0\nVERDICT: PASSED\n"
        )
        _write_job(tmp_path, 222, pattern="bar", sim_log=str(log_path), lsf_status="RUN")

        # Pre-create a corrupt (not-a-real-duckdb-file) evidence.duckdb --
        # duckdb.connect() raises IOException opening it, simulating a
        # locked/corrupt DB file on disk.
        db_path = default_db_path(tmp_path)
        db_path.parent.mkdir(parents=True)
        db_path.write_bytes(b"not a real duckdb file" * 8)

        live_bjobs = [{"job_id": 222, "stat": "DONE", "queue": "normal",
                       "exec_host": "host1", "job_name": "bar", "submit_time": "x"}]
        with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                   return_value=live_bjobs), \
             patch("dv_harness.regression_reporter.lsf_client._run_bjobs",
                   return_value={"RECORDS": [{"JOBID": "222", "STAT": "DONE"}]}):
            snapshot = rr.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)

        # The cycle's own real work completed despite the unopenable DB.
        assert isinstance(snapshot, str)
        assert (uvm_root / "regression.list").read_text().splitlines() == ["bar"]
        updated = lsf_client.load_job_state(tmp_path, 222)
        assert updated.sim_status == "PASS"
        assert "222" in snapshot
