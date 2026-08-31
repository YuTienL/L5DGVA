"""Tests for the `dv-harness lsf-watch-{start,stop,status}` CLI subcommands.

Closes the missing invocation-path gap for regression_reporter.py's
ensure_watcher_running()/stop_watcher()/watcher_status() (Part 2 of the
2026-09-01 sim-output-layout spec): those functions were real and already
unit-tested at the regression_reporter layer (dv_harness_tests/
test_regression_reporter.py's TestWatcherLifecycle, which mocks
subprocess.Popen/os.kill to keep that layer's tests hermetic), but had no
CLI entry point at all.

Real subprocess CLI dispatch, mirroring test_cli_lsf_auto_kill_scan.py's/
test_cli_remote_control.py's established real-subprocess testing style.

Cross-process liveness is asserted for real here. An earlier revision of
these tests deliberately avoided that assertion because regression_reporter.
_pid_is_running() checked liveness via `os.kill(pid, 0)`, which on Windows
goes through GenerateConsoleCtrlEvent and only succeeds when called by the
process that spawned the target's console/process group -- so every real
`dv-harness lsf-watch-status` invocation (always a fresh, unrelated
process) got OSError WinError 87 and reported a genuinely-alive watcher as
not running. That was fixed in commit a12b091 (ctypes OpenProcess/
GetExitCodeProcess, see _pid_is_running()'s Windows branch), so the
start -> status -> stop round trip below now asserts the real outcome:
lsf-watch-status must report running: True with the real spawned PID, and
lsf-watch-stop must really terminate that process.

Every test that spawns a real watcher still hard-kills it via
`taskkill`/os.kill in a `finally` block, so no orphan process survives a
run even if an assertion above fails.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fresh_project():
    return Path(tempfile.mkdtemp())


def _run_cli(tmp, *args):
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
    )
    out = json.loads(r.stdout.strip() or "{}")
    return r.returncode, out


def _hard_kill(pid):
    """Real, unconditional termination independent of stop_watcher()'s own
    liveness check -- pure test-hygiene cleanup, not part of what is being
    tested. Safe to call on an already-dead pid."""
    if pid is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                            capture_output=True, timeout=10)
        else:
            os.kill(pid, 9)
    except Exception:
        pass


class TestLsfWatchCli:
    def test_watch_status_reports_not_running_initially(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(tmp, "lsf-watch-status")
            assert rc == 0
            assert out == {"running": False, "pid": None}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_watch_stop_when_not_running_is_a_noop(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(tmp, "lsf-watch-stop")
            assert rc == 0
            assert out == {"stopped": False}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_watch_start_spawns_process_and_writes_pid_file(self):
        tmp = _fresh_project()
        pid = None
        try:
            rc, out = _run_cli(
                tmp, "lsf-watch-start", "--vcuser", "vcuser1",
                "--uvm-root-path", str(tmp / "uvm"), "--interval-minutes", "30")
            assert rc == 0
            assert out["started"] is True
            pid = out["pid"]
            assert isinstance(pid, int) and pid > 0

            pid_file = tmp / ".dv-harness" / "lsf" / "watcher.pid"
            assert pid_file.read_text().strip() == str(pid)
        finally:
            _hard_kill(pid)
            shutil.rmtree(tmp, ignore_errors=True)

    def test_watch_status_reports_the_real_spawned_watcher_as_running(self):
        """The full CLI -> lifecycle -> OS integration check: a watcher
        started by one short-lived `lsf-watch-start` process must be
        correctly reported as running by a LATER, unrelated
        `lsf-watch-status` process. This is exactly the cross-process shape
        that failed on Windows before commit a12b091's ctypes-based
        _pid_is_running() fix (see module docstring)."""
        tmp = _fresh_project()
        pid = None
        try:
            rc, out = _run_cli(
                tmp, "lsf-watch-start", "--vcuser", "vcuser1",
                "--uvm-root-path", str(tmp / "uvm"), "--interval-minutes", "30")
            assert rc == 0 and out["started"] is True
            pid = out["pid"]

            rc, status = _run_cli(tmp, "lsf-watch-status")
            assert rc == 0
            assert status == {"running": True, "pid": pid}

            # A second start is a real no-op: it finds the live watcher via
            # the same cross-process liveness check and does not respawn.
            rc, again = _run_cli(
                tmp, "lsf-watch-start", "--vcuser", "vcuser1",
                "--uvm-root-path", str(tmp / "uvm"), "--interval-minutes", "30")
            assert rc == 0
            assert again == {"started": False, "pid": pid}
        finally:
            _hard_kill(pid)
            shutil.rmtree(tmp, ignore_errors=True)

    def test_watch_stop_removes_pid_file_and_reports_stopped(self):
        tmp = _fresh_project()
        pid = None
        try:
            rc, out = _run_cli(
                tmp, "lsf-watch-start", "--vcuser", "vcuser1",
                "--uvm-root-path", str(tmp / "uvm"), "--interval-minutes", "30")
            assert rc == 0 and out["started"] is True
            pid = out["pid"]

            rc, out = _run_cli(tmp, "lsf-watch-stop")
            assert rc == 0
            # {"stopped": True} is now an honest claim: stop_watcher()
            # returns True only when it found a LIVE process and actually
            # signaled it (a stale-PID-file cleanup returns False), which
            # requires the cross-process liveness check to work.
            assert out == {"stopped": True}

            pid_file = tmp / ".dv-harness" / "lsf" / "watcher.pid"
            assert not pid_file.exists()

            rc, out = _run_cli(tmp, "lsf-watch-status")
            assert rc == 0
            assert out == {"running": False, "pid": None}
        finally:
            _hard_kill(pid)
            shutil.rmtree(tmp, ignore_errors=True)
