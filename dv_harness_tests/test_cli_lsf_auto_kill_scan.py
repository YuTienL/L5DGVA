"""Tests for the `dv-harness lsf-auto-kill-scan` CLI subcommand.

Closes the "異常自動 Kill Job" gap: lsf_client.evaluate_auto_kill() existed but
had no invocation point. Real subprocess CLI dispatch, mirroring
test_cli_remote_control.py's established real-subprocess testing style. No
real `bjobs`/`bkill` binary is required on PATH: a RUNNING+should_kill=True
fixture job exercises the real LsfUnavailableError-graceful-degradation path
(bkill not installed in this test environment), which is itself a real,
deterministic behavior worth covering -- not a mock of the outcome.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dv_harness import lsf_client

ROOT = Path(__file__).resolve().parents[1]


def _fresh_project():
    return Path(tempfile.mkdtemp())


def _write_policy(tmp, policy):
    path = tmp.joinpath(*lsf_client.EARLY_FAIL_POLICY_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy), encoding="utf-8")


def _write_job(tmp, job_id, **fields):
    state = lsf_client.JobState(job_id=job_id, **fields)
    lsf_client.save_job_state(tmp, state)


def _run_cli(tmp, *args):
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), "lsf-auto-kill-scan", *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
    )
    lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
    entries = [json.loads(ln) for ln in lines]
    return r.returncode, entries


REAL_POLICY = {
    "uvm_error_threshold": 0,
    "kill_on_uvm_fatal": True,
    "kill_on_uvm_error_above_threshold": True,
    "kill_on_fatal_assertion": True,
    "kill_on_simulator_crash": True,
    "kill_on_explicit_fail_marker": True,
    "kill_on_warning": False,
    "require_exact_job_id": True,
    "require_log_job_match": True,
    "allowlist": [],
    "preserve_other_jobs": True,
    "fix_proposal_required_after_early_fail": True,
}


def test_dry_run_reports_decisions_without_killing():
    tmp = _fresh_project()
    try:
        _write_policy(tmp, REAL_POLICY)
        _write_job(tmp, 101, lsf_status="RUN", uvm_fatal_count=1)
        _write_job(tmp, 102, lsf_status="RUN")
        _write_job(tmp, 103, lsf_status="DONE", uvm_fatal_count=1)

        rc, entries = _run_cli(tmp, "--dry-run")

        assert rc == 0
        by_job = {e["job_id"]: e for e in entries}
        assert 103 not in by_job  # DONE job is never scanned as a RUNNING candidate
        assert by_job[101]["should_kill"] is True
        assert "UVM_FATAL" in by_job[101]["reason"]
        assert "killed" not in by_job[101]  # dry-run never calls bkill
        assert by_job[102]["should_kill"] is False
        assert by_job[102]["reason"] == "NO_AUTO_KILL_TRIGGER_CONDITION_MET"

        # dry-run must not have mutated the job state file.
        assert lsf_client.load_job_state(tmp, 101).lsf_status == "RUN"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_running_jobs_produces_empty_scan():
    tmp = _fresh_project()
    try:
        _write_policy(tmp, REAL_POLICY)
        _write_job(tmp, 201, lsf_status="DONE")
        rc, entries = _run_cli(tmp)
        assert rc == 0
        assert entries == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_should_kill_job_attempts_real_bkill_and_reports_outcome():
    # No real `bkill` binary is on PATH in this test environment, so this
    # exercises lsf_client.bkill_job's real LsfUnavailableError path end to
    # end through the CLI -- a real, deterministic failure mode, not a mock.
    tmp = _fresh_project()
    try:
        _write_policy(tmp, REAL_POLICY)
        _write_job(tmp, 301, lsf_status="RUN", uvm_fatal_count=1)
        rc, entries = _run_cli(tmp)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["job_id"] == 301
        assert entry["should_kill"] is True
        assert "killed" in entry
        if entry["killed"] is False:
            assert rc == 1
        else:
            assert rc == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_missing_policy_file_never_kills():
    tmp = _fresh_project()
    try:
        _write_job(tmp, 401, lsf_status="RUN", uvm_fatal_count=1)
        rc, entries = _run_cli(tmp, "--dry-run")
        assert rc == 0
        assert entries[0]["should_kill"] is False
        assert entries[0]["reason"] == "NO_AUTO_KILL_TRIGGER_CONDITION_MET"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
