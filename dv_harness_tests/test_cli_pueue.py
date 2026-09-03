"""Real-subprocess CLI tests for `dv-harness pueue` (2026-09-03 task).

Mirrors test_cli_preflight.py's real-subprocess testing style. Skipped
(not failed) on a machine with no pueue/pueued binary installed -- see
dv_harness/pueue_client.py's module docstring for why no winget/choco
package exists and what the real install path is.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import pueue_client as pc

ROOT = Path(__file__).resolve().parents[1]

_HAS_REAL_PUEUE = shutil.which(pc._resolve_binary("pueue")) is not None or Path(
    pc._resolve_binary("pueue")).is_file()

pytestmark = pytest.mark.skipif(
    not _HAS_REAL_PUEUE,
    reason="pueue not installed on this machine (see pueue_client.py module docstring)")


def _fresh_project():
    return Path(tempfile.mkdtemp())


def _run_cli(tmp, *args, timeout=30):
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=timeout, encoding="utf-8",
    )
    out = json.loads(r.stdout.strip() or "{}")
    return r.returncode, out


class TestPueueAddAndStatus:
    def test_add_then_status_shows_the_task(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(tmp, "pueue", "add", "echo cli_pueue_test", "--label", "cli_test")
            assert rc == 0
            task_id = out["task_id"]
            rc2, status = _run_cli(tmp, "pueue", "status")
            assert rc2 == 0
            assert str(task_id) in status["tasks"]
            assert status["tasks"][str(task_id)]["label"] == "cli_test"
        finally:
            pc.PueueClient().clean()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_wait_reports_success(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(tmp, "pueue", "add", "echo cli_wait_test")
            assert rc == 0
            task_id = out["task_id"]
            rc2, waited = _run_cli(tmp, "pueue", "wait", str(task_id), "--timeout", "15")
            assert rc2 == 0
            assert waited["success"] is True
        finally:
            pc.PueueClient().clean()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_wait_exits_nonzero_on_real_failure(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(tmp, "pueue", "add", "exit 5")
            assert rc == 0
            task_id = out["task_id"]
            rc2, waited = _run_cli(tmp, "pueue", "wait", str(task_id), "--timeout", "15")
            assert rc2 == 1
            assert waited["success"] is False
        finally:
            pc.PueueClient().clean()
            shutil.rmtree(tmp, ignore_errors=True)


class TestPueueChain:
    def test_chain_enqueues_dependent_tasks_in_order(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(
                tmp, "pueue", "chain",
                "--build", "echo build_step",
                "--verify", "echo verify_step",
            )
            assert rc == 0
            chain = out["chain"]
            assert [c["label"] for c in chain] == ["build", "verify"]
            build_id, verify_id = chain[0]["task_id"], chain[1]["task_id"]
            rc2, waited = _run_cli(tmp, "pueue", "wait", str(verify_id), "--timeout", "15")
            assert rc2 == 0
            assert waited["success"] is True
        finally:
            pc.PueueClient().clean()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_chain_with_no_steps_errors(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(tmp, "pueue", "chain")
            assert rc == 2
            assert out["error"] == "NO_STEPS"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_chain_propagates_a_real_failure_to_the_next_step(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(
                tmp, "pueue", "chain",
                "--build", "exit 1",
                "--verify", "echo should_not_run",
            )
            assert rc == 0
            chain = out["chain"]
            verify_id = chain[1]["task_id"]
            rc2, waited = _run_cli(tmp, "pueue", "wait", str(verify_id), "--timeout", "15")
            assert rc2 == 1
            assert waited["success"] is False
        finally:
            pc.PueueClient().clean()
            shutil.rmtree(tmp, ignore_errors=True)
