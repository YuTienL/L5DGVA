"""Tests for dv_harness/regression_reporter.py's reconciliation cycle
(Part 2/Part 3 of the 2026-09-01 sim-output-layout-and-background-job-monitor
spec)."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from dv_harness import regression_reporter, lsf_client

ROOT = Path(__file__).resolve().parents[1]


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


class TestMainWatchLoop:
    def test_watch_false_calls_reconciliation_once(self, tmp_path):
        with patch("dv_harness.regression_reporter.run_reconciliation_cycle",
                   return_value="snapshot text") as m:
            regression_reporter.main(project_root=str(tmp_path), once=True,
                                      vcuser="vcuser1", uvm_root_path=str(tmp_path / "uvm"))
        m.assert_called_once()

    def test_missing_vcuser_falls_back_to_legacy_render(self, tmp_path, capsys):
        # No vcuser supplied -- cannot discover live jobs at all, so fall back
        # to the pre-existing load_jobs()/render_snapshot() behavior rather
        # than crashing.
        regression_reporter.main(project_root=str(tmp_path), once=True)
        captured = capsys.readouterr()
        assert "Periodic Regression Snapshot" in captured.out


class TestWatcherLifecycle:
    def test_ensure_watcher_running_starts_when_no_pid_file(self, tmp_path):
        with patch("dv_harness.regression_reporter.subprocess.Popen") as m:
            m.return_value.pid = 54321
            result = regression_reporter.ensure_watcher_running(
                tmp_path, "vcuser1", tmp_path / "uvm", interval_minutes=5)
        assert result == {"started": True, "pid": 54321}
        pid_file = tmp_path / ".dv-harness" / "lsf" / "watcher.pid"
        assert pid_file.read_text().strip() == "54321"

    def test_ensure_watcher_running_noop_when_already_running(self, tmp_path):
        pid_file = tmp_path / ".dv-harness" / "lsf" / "watcher.pid"
        pid_file.parent.mkdir(parents=True)
        pid_file.write_text(str(os.getpid()))  # our own pid is definitely alive
        with patch("dv_harness.regression_reporter.subprocess.Popen") as m:
            result = regression_reporter.ensure_watcher_running(
                tmp_path, "vcuser1", tmp_path / "uvm")
        m.assert_not_called()
        assert result == {"started": False, "pid": os.getpid()}

    def test_ensure_watcher_running_restarts_on_stale_pid_file(self, tmp_path):
        pid_file = tmp_path / ".dv-harness" / "lsf" / "watcher.pid"
        pid_file.parent.mkdir(parents=True)
        pid_file.write_text("999999999")  # not a real running pid
        with patch("dv_harness.regression_reporter._pid_is_running", return_value=False), \
             patch("dv_harness.regression_reporter.subprocess.Popen") as m:
            m.return_value.pid = 11111
            result = regression_reporter.ensure_watcher_running(
                tmp_path, "vcuser1", tmp_path / "uvm")
        assert result == {"started": True, "pid": 11111}
        assert pid_file.read_text().strip() == "11111"

    def test_stop_watcher_terminates_and_removes_pid_file(self, tmp_path):
        pid_file = tmp_path / ".dv-harness" / "lsf" / "watcher.pid"
        pid_file.parent.mkdir(parents=True)
        pid_file.write_text("22222")
        with patch("dv_harness.regression_reporter._pid_is_running", return_value=True), \
             patch("dv_harness.regression_reporter.os.kill") as m:
            result = regression_reporter.stop_watcher(tmp_path)
        m.assert_called_once()
        assert result == {"stopped": True}
        assert not pid_file.exists()

    def test_stop_watcher_no_pid_file_is_a_noop(self, tmp_path):
        result = regression_reporter.stop_watcher(tmp_path)
        assert result == {"stopped": False}

    def test_watcher_status_reports_running(self, tmp_path):
        pid_file = tmp_path / ".dv-harness" / "lsf" / "watcher.pid"
        pid_file.parent.mkdir(parents=True)
        pid_file.write_text(str(os.getpid()))
        assert regression_reporter.watcher_status(tmp_path) == {"running": True, "pid": os.getpid()}

    def test_watcher_status_reports_not_running_when_no_pid_file(self, tmp_path):
        assert regression_reporter.watcher_status(tmp_path) == {"running": False, "pid": None}

    def test_pid_is_running_true_on_permission_error(self):
        # PermissionError means the process exists but is owned by a
        # different user/UID -- alive, just not signalable by us. Must not
        # be conflated with ProcessLookupError ("no such process"). This
        # exercises the POSIX os.kill(pid, 0) branch specifically (forced
        # via os.name, since _pid_is_running() now takes a Windows-only
        # ctypes path on os.name == "nt" -- see TestPidIsRunningCrossProcess
        # below for that branch's own real-process coverage).
        with patch("dv_harness.regression_reporter.os.name", "posix"), \
             patch("dv_harness.regression_reporter.os.kill", side_effect=PermissionError):
            assert regression_reporter._pid_is_running(12345) is True

    def test_pid_is_running_false_on_process_lookup_error(self):
        with patch("dv_harness.regression_reporter.os.name", "posix"), \
             patch("dv_harness.regression_reporter.os.kill", side_effect=ProcessLookupError):
            assert regression_reporter._pid_is_running(12345) is False


def _spawn_detached_child_from_separate_process():
    """Spawns a real, long-lived child process from inside a SEPARATE
    'starter' process (mirroring ensure_watcher_running()'s exact spawn
    shape -- CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS on Windows,
    start_new_session on POSIX) and lets that starter process exit
    immediately after spawning.

    This is deliberately NOT "spawn via subprocess.Popen in this test
    process, then check the pid in this same test process" -- that
    same-process shape was found to falsely appear to work on Windows
    (a Popen()'d child, or even a Popen()'d grandchild, can still be
    liveness-checked successfully by its own spawning process or that
    process's live descendants). The real dv-harness usage pattern is
    cross-process: `lsf-watch-start` spawns the watcher and exits, then a
    LATER, unrelated `lsf-watch-status` process checks it -- only that
    shape (checker process is not a descendant of, and the original
    spawner has already exited) reproduces the real Windows
    GenerateConsoleCtrlEvent-based os.kill(pid, 0) failure (WinError 87)
    that _pid_is_running() must not be fooled by."""
    starter_script = (
        "import subprocess, sys, json, os\n"
        "popen_kwargs = {}\n"
        "if os.name == 'nt':\n"
        "    popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008\n"
        "else:\n"
        "    popen_kwargs['start_new_session'] = True\n"
        "proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], **popen_kwargs)\n"
        "print(json.dumps({'pid': proc.pid}))\n"
    )
    r = subprocess.run([sys.executable, "-c", starter_script], cwd=str(ROOT),
                        capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())["pid"]


def _pid_is_running_from_separate_process(pid):
    checker_script = f"from dv_harness import regression_reporter as rr\nprint(rr._pid_is_running({pid}))\n"
    r = subprocess.run([sys.executable, "-c", checker_script], cwd=str(ROOT),
                        capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip() == "True"


def _hard_kill(pid):
    """Real, unconditional termination for test cleanup -- independent of
    _pid_is_running()'s own correctness, so a leaked process is never left
    behind even if an assertion above it fails."""
    if pid is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=10)
        else:
            os.kill(pid, 9)
    except Exception:
        pass


class TestPidIsRunningCrossProcess:
    """Regression coverage for a real Windows-only bug found while wiring
    up Task 7's `lsf-watch-start`/`lsf-watch-stop`/`lsf-watch-status` CLI
    commands: _pid_is_running() used `os.kill(pid, 0)` for liveness, which
    on Windows is implemented via GenerateConsoleCtrlEvent and only
    succeeds when called by the process that originally spawned the
    target's console/process group (or one of that process's still-live
    descendants) -- a relationship that never holds for real dv-harness
    usage, where every CLI invocation, including the one that spawned the
    watcher, is a separate, short-lived process that exits right after
    spawning/checking. Confirmed via `git stash`-style manual revert that
    test_pid_is_running_true_for_a_real_process_checked_cross_process
    below fails against the pre-fix os.kill(pid, 0)-only implementation
    and passes against the ctypes-based Windows fix."""

    def test_pid_is_running_true_for_a_real_process_checked_cross_process(self):
        pid = _spawn_detached_child_from_separate_process()
        try:
            assert _pid_is_running_from_separate_process(pid) is True
        finally:
            _hard_kill(pid)

    def test_pid_is_running_false_after_the_process_actually_exits(self):
        pid = _spawn_detached_child_from_separate_process()
        try:
            _hard_kill(pid)
            # Poll briefly for the OS to actually reap it -- taskkill/
            # os.kill(9) is not synchronous.
            deadline = time.time() + 10
            while time.time() < deadline and _pid_is_running_from_separate_process(pid):
                time.sleep(0.2)
            assert _pid_is_running_from_separate_process(pid) is False
        finally:
            _hard_kill(pid)

    def test_pid_is_running_false_for_a_definitely_nonexistent_pid(self):
        # Far outside any real PID range on either Windows or POSIX,
        # without being an invalid argument to the underlying syscall.
        assert regression_reporter._pid_is_running(999_999_999) is False
