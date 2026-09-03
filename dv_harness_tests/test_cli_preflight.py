"""Real-subprocess CLI tests for `dv-harness preflight` and the preflight
gate wired into `dv-harness lsf-submit` (2026-09-03 task).

Mirrors test_cli_lsf_auto_kill_scan.py's/test_cli_lsf_watch.py's
established real-subprocess testing style. No real `bqueues`/`lmutil`/
`bsub` binary is required on PATH: this dev machine genuinely lacking
them exercises the real, deterministic BLOCKED/LSF_UNAVAILABLE paths
(not a mock of the outcome) -- exactly the same "real absence is a real
test" convention test_cli_lsf_auto_kill_scan.py's own docstring already
establishes for bkill.
"""
from __future__ import annotations

import json
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


class TestStandalonePreflightCommand:
    def test_blocked_when_no_license_server_configured_and_binaries_absent(self):
        """Fresh project -> config.json's preflight.license_server defaults
        to "" -> the license check FAILs by design (never a silent pass on
        an unconfirmed condition) -- and since real bqueues/lmutil binaries
        are not on this dev machine's PATH either, every check genuinely
        fails, giving a real (not mocked) BLOCKED verdict."""
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(tmp, "preflight", "--queue", "vcs")
            assert rc == 1
            assert out["overall"] == "BLOCKED"
            assert "eda_license" in out["blocked_on"]
            names = {c["name"] for c in out["checks"]}
            assert names == {"eda_license", "lsf_queue_health", "host_reachability",
                              "disk_space", "workdir", "eda_env_vars"}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_license_server_override_is_actually_used(self):
        """--license-server should reach the real lmutil invocation (which
        then fails because lmutil is not on PATH here) -- confirms the CLI
        flag really flows into PreflightConfig.license_server rather than
        being silently ignored."""
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(tmp, "preflight", "--license-server", "2900@host-a")
            assert rc == 1
            lic = next(c for c in out["checks"] if c["name"] == "eda_license")
            assert lic["status"] == "FAIL"
            assert lic["command"] == "lmutil lmstat -a -c 2900@host-a"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestLsfSubmitGating:
    def test_lsf_submit_is_blocked_before_bsub_is_ever_attempted(self):
        """The real point of this whole task: a BLOCKED preflight result
        must prevent submission outright. If bsub had actually been
        attempted, the failure mode would be LSF_UNAVAILABLE (bsub not on
        PATH), not PREFLIGHT_BLOCKED -- so seeing PREFLIGHT_BLOCKED here IS
        the proof bsub was never called, and no job state file is ever
        written."""
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(tmp, "lsf-submit", "vcs -R sim1", "--queue", "vcs")
            assert rc == 1
            assert out["error"] == "PREFLIGHT_BLOCKED"
            assert out["preflight"]["overall"] == "BLOCKED"
            jobs_dir = tmp / ".dv-harness" / "lsf" / "jobs"
            assert not jobs_dir.exists() or list(jobs_dir.glob("*.json")) == []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_skip_preflight_bypasses_the_gate_and_reaches_real_bsub_path(self):
        """With --skip-preflight, the failure mode must flip to
        LSF_UNAVAILABLE (bsub genuinely not on PATH here) -- proof the
        gate was actually bypassed, not just that the command failed for
        some other reason."""
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(tmp, "lsf-submit", "vcs -R sim1", "--queue", "vcs", "--skip-preflight")
            assert rc == 1
            assert out["error"] == "LSF_UNAVAILABLE"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
