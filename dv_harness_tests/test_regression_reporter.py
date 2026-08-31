"""Tests for dv_harness/regression_reporter.py's reconciliation cycle
(Part 2/Part 3 of the 2026-09-01 sim-output-layout-and-background-job-monitor
spec)."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from dv_harness import regression_reporter, lsf_client


def _write_job(root, job_id, **kwargs):
    state = lsf_client.JobState(job_id=job_id, **kwargs)
    lsf_client.save_job_state(root, state)


class TestRunReconciliationCycle:
    def test_registered_job_gets_analyzed_and_regression_list_updated(self, tmp_path):
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
            regression_reporter.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)

        assert (uvm_root / "regression.list").read_text().splitlines() == ["foo"]
        updated = lsf_client.load_job_state(tmp_path, 111)
        assert updated.uvm_error_count == 0
        assert updated.uvm_fatal_count == 0

    def test_indeterminate_verdict_does_not_touch_regression_list(self, tmp_path):
        uvm_root = tmp_path / "uvm"
        run_dir = tmp_path / "sim" / "run" / "bar_1"
        run_dir.mkdir(parents=True)
        log_path = run_dir / "sim.log"
        log_path.write_text("no epilogue in this truncated log\n")
        _write_job(tmp_path, 222, pattern="bar", sim_log=str(log_path), lsf_status="RUN")

        live_bjobs = [{"job_id": 222, "stat": "DONE", "queue": "normal",
                       "exec_host": "host1", "job_name": "bar", "submit_time": "x"}]
        with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                   return_value=live_bjobs), \
             patch("dv_harness.regression_reporter.lsf_client._run_bjobs",
                   return_value={"RECORDS": [{"JOBID": "222", "STAT": "DONE"}]}):
            regression_reporter.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)

        assert not (uvm_root / "regression.list").exists()

    def test_unregistered_job_gets_unregistered_status_not_analyzed(self, tmp_path):
        uvm_root = tmp_path / "uvm"
        live_bjobs = [{"job_id": 333, "stat": "RUN", "queue": "normal",
                       "exec_host": "host1", "job_name": "unregistered_job",
                       "submit_time": "x"}]
        with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                   return_value=live_bjobs):
            snapshot = regression_reporter.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)
        assert "333" in snapshot
        assert not (uvm_root / "regression.list").exists()

    def test_one_failed_bjobs_call_does_not_raise(self, tmp_path):
        uvm_root = tmp_path / "uvm"
        with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                   side_effect=lsf_client.LsfUnavailableError("down")):
            snapshot = regression_reporter.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)
        assert isinstance(snapshot, str)
