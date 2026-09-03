"""Real-subprocess CLI tests for `dv-harness git-guard` (2026-09-03 gh CLI +
PR-only governance task). Mirrors test_cli_preflight.py's/
test_cli_lsf_watch.py's established real-subprocess testing style: no mocked
CLI layer, a real `python -m dv_harness.cli` invocation against a fresh
temp project, with a simulated AI-agent environment passed via the real
subprocess `env=` kwarg (never a monkeypatched os.environ inside this
process, since the guard's own detection reads the CHILD process's
environment).
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


def _run_cli(tmp, args, stdin_text="", extra_env=None):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
        cwd=str(ROOT), input=stdin_text, capture_output=True, text=True,
        timeout=30, encoding="utf-8", env=env,
    )
    out = json.loads(r.stdout.strip() or "{}")
    return r.returncode, out


class TestGitGuardPrePush:
    def test_allows_agent_pushing_a_feature_branch(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(
                tmp, ["git-guard", "--check", "pre-push"],
                stdin_text="refs/heads/feature/x a1 refs/heads/feature/x a2\n",
                extra_env={"CLAUDECODE": "1"},
            )
            assert rc == 0
            assert out["allowed"] is True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_blocks_agent_pushing_main_directly(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(
                tmp, ["git-guard", "--check", "pre-push"],
                stdin_text="refs/heads/main a1 refs/heads/main a2\n",
                extra_env={"CLAUDECODE": "1"},
            )
            assert rc == 1
            assert out["allowed"] is False
            assert out["branch"] == "main"
            assert "CLAUDECODE" in out["detected_markers"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_blocks_agent_pushing_master_directly(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(
                tmp, ["git-guard", "--check", "pre-push"],
                stdin_text="refs/heads/master a1 refs/heads/master a2\n",
                extra_env={"ANTHROPIC_API_KEY": "sk-fake"},
            )
            assert rc == 1
            assert out["branch"] == "master"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_allows_human_pushing_main_directly(self):
        """No AI-agent marker present -> this gate does not block a human.
        (Real branch-protection-on-the-remote is the intended gate for that
        case once a remote exists -- see tools/git-hooks/README.md.)"""
        tmp = _fresh_project()
        try:
            clean_env = {k: v for k, v in os.environ.items()
                         if k not in ("CLAUDECODE", "CLAUDE_CODE", "CLAUDE_CODE_ENTRYPOINT",
                                       "CLAUDE_CODE_SESSION_ID", "ANTHROPIC_API_KEY")}
            r = subprocess.run(
                [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
                 "git-guard", "--check", "pre-push"],
                cwd=str(ROOT), input="refs/heads/main a1 refs/heads/main a2\n",
                capture_output=True, text=True, timeout=30, encoding="utf-8",
                env=clean_env,
            )
            out = json.loads(r.stdout.strip() or "{}")
            assert r.returncode == 0
            assert out["allowed"] is True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_blocked_decision_is_logged_to_events_jsonl_audit_trail(self):
        """The Audit/Change Governance Agent's whole premise ('know what it
        did, be able to trace it') depends on this actually landing in the
        one real audit substrate (.dv-harness/events.jsonl) -- not just
        being printed to stdout and forgotten."""
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(
                tmp, ["git-guard", "--check", "pre-push"],
                stdin_text="refs/heads/main a1 refs/heads/main a2\n",
                extra_env={"CLAUDECODE": "1"},
            )
            assert rc == 1
            events_file = tmp / ".dv-harness" / "events.jsonl"
            assert events_file.exists()
            events = [json.loads(l) for l in events_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            guard_events = [e for e in events if e.get("event") == "GIT_GUARD_DECISION"]
            assert len(guard_events) == 1
            assert guard_events[0]["allowed"] is False
            assert guard_events[0]["branch"] == "main"
            assert guard_events[0]["hook"] == "pre-push"

            # Also visible through the existing general audit view -- no
            # second/parallel audit file was invented for this feature.
            rc2, audit_out = _run_cli(tmp, ["audit"])
            assert rc2 == 0
            assert any(e.get("event") == "GIT_GUARD_DECISION" for e in audit_out["events"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_protected_branch_produces_no_audit_event(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(
                tmp, ["git-guard", "--check", "pre-push"],
                stdin_text="refs/heads/feature/x a1 refs/heads/feature/x a2\n",
                extra_env={"CLAUDECODE": "1"},
            )
            assert rc == 0
            events_file = tmp / ".dv-harness" / "events.jsonl"
            if events_file.exists():
                events = [json.loads(l) for l in events_file.read_text(encoding="utf-8").splitlines() if l.strip()]
                assert not any(e.get("event") == "GIT_GUARD_DECISION" for e in events)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestGitGuardPreMergeCommit:
    def test_blocks_agent_merging_into_main(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(
                tmp, ["git-guard", "--check", "pre-merge-commit", "--branch", "main"],
                extra_env={"CLAUDECODE": "1"},
            )
            assert rc == 1
            assert out["allowed"] is False
            assert out["branch"] == "main"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_allows_agent_merging_into_feature_branch(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(
                tmp, ["git-guard", "--check", "pre-merge-commit", "--branch", "feature/x"],
                extra_env={"CLAUDECODE": "1"},
            )
            assert rc == 0
            assert out["allowed"] is True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_branch_arg_is_a_usage_error(self):
        tmp = _fresh_project()
        try:
            rc, out = _run_cli(tmp, ["git-guard", "--check", "pre-merge-commit"])
            assert rc == 2
            assert out["error"] == "BRANCH_REQUIRED_FOR_PRE_MERGE_COMMIT"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
