"""Tests for the `dv-harness remote-control {bootstrap,status,cmd}` CLI surface.

BUG FIX (2026-08-28, plan-remote-control-wiring design pass): dv_harness/
remote_control.py's session/gate substrate (bootstrap_session/
validate_and_transition/get_status) was complete and unit-tested in its own
right (dv_harness_tests/test_remote_control.py), but had zero callers -- no
CLI subcommand, no GUI route. These tests exercise the real CLI dispatch
end to end (real subprocess, real gate scripts under tools/verification_flow/,
mirroring this codebase's established real-subprocess CLI-testing style).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fresh_project_with_tools():
    """remote_control.py resolves gate scripts as `project_root/tools/verification_flow/...`
    (not relative to cwd), so every real project root needs its own copy."""
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(ROOT / "tools", tmp / "tools")
    return tmp


def _run_cli(tmp, *args):
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), "remote-control", *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
    )
    out = json.loads(r.stdout.strip() or "{}")
    return r.returncode, out


def test_bootstrap_lands_on_running_and_is_idempotent_safe():
    tmp = _fresh_project_with_tools()
    try:
        rc, out = _run_cli(tmp, "bootstrap")
        assert rc == 0
        assert out["state"] == "RUNNING"
        assert out["remote_control_enabled"] is True
        first_session_id = out["session_id"]

        # A second bootstrap is a fresh session, not an error -- it's an
        # explicit re-establishment, not one of the 11 gated commands.
        rc2, out2 = _run_cli(tmp, "bootstrap")
        assert rc2 == 0 and out2["state"] == "RUNNING"
        assert out2["session_id"] != first_session_id
    finally:
        shutil.rmtree(tmp)


def test_status_is_read_only_and_matches_get_status():
    from dv_harness import remote_control
    tmp = _fresh_project_with_tools()
    try:
        _run_cli(tmp, "bootstrap")
        rc, out = _run_cli(tmp, "status")
        assert rc == 0
        assert out["session"]["state"] == "RUNNING"
        assert out["last_action"]["command"] == "BOOTSTRAP"
        assert out == remote_control.get_status(tmp)
    finally:
        shutil.rmtree(tmp)


def test_cmd_pause_resume_round_trip_moves_real_control_plane_state():
    from dv_harness.control_plane import ControlPlane
    tmp = _fresh_project_with_tools()
    try:
        _run_cli(tmp, "bootstrap")

        rc, out = _run_cli(tmp, "cmd", "PAUSE", "--reason", "investigating")
        assert rc == 0 and out["ok"] is True and out["state"] == "PAUSED"
        assert ControlPlane(tmp).is_paused() is True

        rc, out = _run_cli(tmp, "cmd", "RESUME")
        assert rc == 0 and out["ok"] is True and out["state"] == "RUNNING"
        assert ControlPlane(tmp).is_paused() is False
    finally:
        shutil.rmtree(tmp)


def test_cmd_takeover_and_release_moves_real_control_plane_state():
    from dv_harness.control_plane import ControlPlane
    tmp = _fresh_project_with_tools()
    try:
        _run_cli(tmp, "bootstrap")
        rc, out = _run_cli(tmp, "cmd", "TAKEOVER", "--target-stage", "VERIFY", "--reason", "manual check")
        assert rc == 0 and out["ok"] is True and out["state"] == "TAKEOVER"
        cp_state = ControlPlane(tmp).load()
        assert cp_state["takeover"]["active"] is True
        assert cp_state["takeover"]["stage"] == "VERIFY"
    finally:
        shutil.rmtree(tmp)


def test_cmd_illegal_transition_exits_nonzero_and_persists_nothing():
    tmp = _fresh_project_with_tools()
    try:
        _run_cli(tmp, "bootstrap")
        # RESUME from RUNNING (never paused) is not a legal transition.
        rc, out = _run_cli(tmp, "cmd", "RESUME")
        assert rc == 1
        assert out["ok"] is False
        assert out["error"]

        # Nothing should have moved off RUNNING.
        rc2, status = _run_cli(tmp, "status")
        assert status["session"]["state"] == "RUNNING"
    finally:
        shutil.rmtree(tmp)


def test_cmd_mutating_command_without_target_stage_rejected_by_argparse_layer():
    tmp = _fresh_project_with_tools()
    try:
        _run_cli(tmp, "bootstrap")
        rc, out = _run_cli(tmp, "cmd", "TAKEOVER")
        assert rc == 1
        assert out["ok"] is False
        assert out["error"] == "CONTROL_ACTION_WITHOUT_TARGET_STAGE"
    finally:
        shutil.rmtree(tmp)
