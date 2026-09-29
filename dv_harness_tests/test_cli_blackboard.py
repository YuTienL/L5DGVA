"""Tests for the `dv-harness blackboard write|read` CLI subcommands and their
backing dv_harness/commands.py functions (cmd_blackboard_write/
cmd_blackboard_read).

Added for the multi-agent-rca-orchestrator-implementation task: a Workflow
tool script (plain JS, no filesystem/Python access of its own -- see
workflow-authoring) cannot call the real Blackboard.write() method directly.
This CLI subcommand is the real, tested bridge one of its subagents uses (via
a real PowerShell/Bash tool call) so `.claude/workflows/rca-multi-agent-
fusion.js`'s Evidence Fusion stage genuinely persists to
`.dv-harness/blackboard/rca_evidence_fusion.json`, not just to workflow
return-value text. Real subprocess CLI dispatch, mirroring
test_cli_lsf_watch.py's/test_cli_remote_control.py's established
real-subprocess testing style for the CLI-level tests; direct-call unit
tests cover commands.py's own validation.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import commands
from dv_harness.blackboard import Blackboard
from dv_harness.engine import DVHarness

ROOT = Path(__file__).resolve().parents[1]


def _fresh_project():
    return Path(tempfile.mkdtemp())


def _run_cli(tmp, *args):
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
    )
    return r


# ---- direct commands.py unit tests -----------------------------------------

def test_cmd_blackboard_write_uses_real_blackboard_write():
    tmp = _fresh_project()
    h = DVHarness(tmp)
    value = {"findings": [{"agent": "rtl-evidence-agent", "claim": "x"}]}
    entry = commands.cmd_blackboard_write(h, "rca_evidence_fusion", value, source="test", confidence="MEDIUM")
    assert entry["topic"] == "rca_evidence_fusion"
    assert entry["value"] == value
    assert entry["source"] == "test"
    assert entry["confidence"] == "MEDIUM"
    # Real file, independent of the returned payload -- a second, fresh
    # Blackboard instance against the same root must read the same value.
    reread = Blackboard(tmp).read("rca_evidence_fusion")
    assert reread == entry


def test_cmd_blackboard_write_rejects_empty_topic():
    tmp = _fresh_project()
    h = DVHarness(tmp)
    with pytest.raises(ValueError):
        commands.cmd_blackboard_write(h, "", {"a": 1})
    with pytest.raises(ValueError):
        commands.cmd_blackboard_write(h, "   ", {"a": 1})


def test_cmd_blackboard_read_roundtrips_and_defaults_to_none():
    tmp = _fresh_project()
    h = DVHarness(tmp)
    assert commands.cmd_blackboard_read(h, "never_written") is None
    commands.cmd_blackboard_write(h, "some_topic", {"a": 1}, source="s")
    got = commands.cmd_blackboard_read(h, "some_topic")
    assert got["value"] == {"a": 1}


# ---- real subprocess CLI round trip ----------------------------------------

def test_cli_blackboard_write_then_read_roundtrip():
    tmp = _fresh_project()
    value = {"fused_findings": [{"claim": "first bad event at t=120ns", "confidence": "HIGH"}],
              "contributing_agents": ["rtl-evidence-agent", "log-evidence-agent", "vip-spec-evidence-agent"]}
    value_file = tmp / "fusion_value.json"
    value_file.write_text(json.dumps(value), encoding="utf-8")

    r = _run_cli(tmp, "blackboard", "write", "rca_evidence_fusion",
                 "--file", str(value_file), "--source", "rca-multi-agent-fusion", "--confidence", "HIGH")
    assert r.returncode == 0, r.stderr
    written = json.loads(r.stdout)
    assert written["topic"] == "rca_evidence_fusion"
    assert written["value"] == value
    assert written["source"] == "rca-multi-agent-fusion"

    r2 = _run_cli(tmp, "blackboard", "read", "rca_evidence_fusion")
    assert r2.returncode == 0, r2.stderr
    reread = json.loads(r2.stdout)
    assert reread["value"] == value

    # The real on-disk artifact the Blackboard class itself defines -- not
    # just the CLI's stdout -- is what a downstream real reader (e.g. the
    # RCA Review stage re-reading independently) actually depends on.
    on_disk = tmp / ".dv-harness" / "blackboard" / "rca_evidence_fusion.json"
    assert on_disk.is_file()
    assert json.loads(on_disk.read_text(encoding="utf-8"))["value"] == value


def test_cli_blackboard_write_inline_value():
    tmp = _fresh_project()
    r = _run_cli(tmp, "blackboard", "write", "some_topic", "--value", '{"x": 1}')
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["value"] == {"x": 1}


def test_cli_blackboard_read_missing_topic_returns_null():
    tmp = _fresh_project()
    r = _run_cli(tmp, "blackboard", "read", "topic_never_written")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "null"


def test_cli_blackboard_write_requires_value_or_file():
    tmp = _fresh_project()
    r = _run_cli(tmp, "blackboard", "write", "some_topic")
    assert r.returncode != 0
