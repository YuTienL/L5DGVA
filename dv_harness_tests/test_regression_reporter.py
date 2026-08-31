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

    def test_failed_verdict_with_uvm_errors_appears_in_attention_section(self, tmp_path):
        """Regression test for the reviewer-found to_snapshot_row()/render_snapshot() key
        mismatch (uvm_error/uvm_fatal vs. uvm_error_count/uvm_fatal_count) plus the
        hardcoded sim_status="ANALYZED" bug: a job with a real FAILED verdict and
        non-zero UVM_ERROR/UVM_FATAL counts must actually show up in the ATTENTION
        section, not render as "pending" and disappear."""
        uvm_root = tmp_path / "uvm"
        run_dir = tmp_path / "sim" / "run" / "baz_1"
        run_dir.mkdir(parents=True)
        log_path = run_dir / "sim.log"
        log_path.write_text(
            "UVM_ERROR: something bad happened\n" * 5 +
            "FINAL CHECK @ 1000 ns\n"
            "UVM_FATAL = 1, UVM_ERROR = 5, UVM_WARNING = 0\nVERDICT: FAILED\n"
        )
        _write_job(tmp_path, 444, pattern="baz", sim_log=str(log_path), lsf_status="RUN")

        live_bjobs = [{"job_id": 444, "stat": "DONE", "queue": "normal",
                       "exec_host": "host1", "job_name": "baz", "submit_time": "x"}]
        with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                   return_value=live_bjobs), \
             patch("dv_harness.regression_reporter.lsf_client._run_bjobs",
                   return_value={"RECORDS": [{"JOBID": "444", "STAT": "DONE"}]}):
            snapshot = regression_reporter.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)

        job_row_line = next(line for line in snapshot.splitlines() if line.startswith("444"))
        assert "pending" not in job_row_line
        attention_section = snapshot.split("ATTENTION", 1)[1]
        assert "444" in attention_section
        updated = lsf_client.load_job_state(tmp_path, 444)
        assert updated.sim_status == "FAIL"
        assert not (uvm_root / "regression.list").exists() or \
            "baz" not in (uvm_root / "regression.list").read_text().splitlines()

    def test_one_job_analysis_failure_does_not_abort_other_jobs(self, tmp_path):
        """Regression test for the reviewer-found missing per-job error isolation: an
        exception raised while analyzing ONE job's log (anywhere from
        detect_underreporting() through apply_verdict_to_file()) must not abort
        analysis of a different job in the same cycle, and the cycle must still
        return a valid snapshot rather than raising."""
        uvm_root = tmp_path / "uvm"

        run_dir_a = tmp_path / "sim" / "run" / "job_a_1"
        run_dir_a.mkdir(parents=True)
        log_a = run_dir_a / "sim.log"
        log_a.write_text(
            "FINAL CHECK @ 1000 ns\nUVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0\n"
            "VERDICT: PASSED\n"
        )
        _write_job(tmp_path, 501, pattern="job_a", sim_log=str(log_a), lsf_status="RUN")

        run_dir_b = tmp_path / "sim" / "run" / "job_b_1"
        run_dir_b.mkdir(parents=True)
        log_b = run_dir_b / "sim.log"
        log_b.write_text(
            "FINAL CHECK @ 1000 ns\nUVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0\n"
            "VERDICT: PASSED\n"
        )
        _write_job(tmp_path, 502, pattern="job_b", sim_log=str(log_b), lsf_status="RUN")

        live_bjobs = [
            {"job_id": 501, "stat": "DONE", "queue": "normal", "exec_host": "host1",
             "job_name": "job_a", "submit_time": "x"},
            {"job_id": 502, "stat": "DONE", "queue": "normal", "exec_host": "host1",
             "job_name": "job_b", "submit_time": "x"},
        ]

        real_detect_underreporting = regression_reporter.detect_underreporting

        def flaky_detect_underreporting(job_state, parsed):
            if job_state.get("job_id") == 501:
                raise RuntimeError("simulated analysis failure for job 501")
            return real_detect_underreporting(job_state, parsed)

        with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                   return_value=live_bjobs), \
             patch("dv_harness.regression_reporter.lsf_client._run_bjobs",
                   return_value={"RECORDS": [{"JOBID": "501", "STAT": "DONE"},
                                              {"JOBID": "502", "STAT": "DONE"}]}), \
             patch("dv_harness.regression_reporter.detect_underreporting",
                   side_effect=flaky_detect_underreporting):
            snapshot = regression_reporter.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)

        assert isinstance(snapshot, str)
        assert (uvm_root / "regression.list").read_text().splitlines() == ["job_b"]
        # job 501's failure must not have corrupted its persisted state's sim_status
        # into something bogus -- it simply never got past ANALYZED-or-later here.
        job_501 = lsf_client.load_job_state(tmp_path, 501)
        assert job_501.sim_status != "PASS"
