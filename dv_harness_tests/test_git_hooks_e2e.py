"""End-to-end tests that GIT ITSELF fires the PR-only governance gate.

Why this file exists (2026-09-04 governance-layer gap close): the existing
`test_git_governance.py` (pure decision logic) and `test_cli_git_guard.py`
(real `python -m dv_harness.cli git-guard` subprocess) between them prove
every piece works *when something calls it*. Neither one ever runs a real
`git push` / `git merge`, so up to now nothing proved the one edge the
architecture diagram actually claims:

    agent runs `git push`/`git merge`
      -> git's own hook runner (core.hooksPath = tools/git-hooks)
        -> tools/git-hooks/pre-push | pre-merge-commit
          -> dv-harness git-guard -> git_governance decision
            -> non-zero exit ABORTS the real git operation
              -> GIT_GUARD_DECISION appended to .dv-harness/events.jsonl
                -> readable back through `dv-harness audit`

Every `GIT_GUARD_DECISION` in this repo's own trail before this file was
written came from a manual/direct invocation of the hook script or the CLI,
never from git organically invoking the hook -- so the connection itself
was untested. These tests close that by driving REAL `git push` and REAL
`git merge` in a throwaway repo whose `core.hooksPath` points at this
repo's real `tools/git-hooks/` directory (the hook scripts under test, not
copies), pushing to a throwaway LOCAL BARE remote -- never a network
remote, and never this repo itself.

Env handling follows test_cli_git_guard.py's established rule: the agent
markers are passed to the CHILD git process via the real `env=` kwarg and
are explicitly STRIPPED for the "human" cases, because the guard reads the
environment of the process git spawns, and this test runner is itself
running inside a real AI-agent environment.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = ROOT / "tools" / "git-hooks"

sys.path.insert(0, str(ROOT))
from dv_harness.git_governance import AI_AGENT_ENV_MARKERS  # noqa: E402

GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(
    GIT is None or not (HOOKS_DIR / "pre-push").exists(),
    reason="needs a real git executable and the tools/git-hooks scripts",
)


def _base_env(agent: bool):
    """A real child environment for git. `PYTHONPATH=ROOT` is what lets the
    hook's `python -m dv_harness.cli` resolve this package from inside the
    throwaway repo (a genuine clone would have dv_harness in-tree)."""
    env = dict(os.environ)
    for marker in AI_AGENT_ENV_MARKERS:
        env.pop(marker, None)          # this runner is itself an agent env
    if agent:
        env["CLAUDECODE"] = "1"
    env["PYTHONPATH"] = str(ROOT)
    env.pop("GIT_DIR", None)
    return env


def _git(work, *args, env=None, check=True):
    r = subprocess.run(
        [GIT, *args], cwd=str(work), capture_output=True, text=True,
        timeout=120, encoding="utf-8", errors="replace",
        env=env if env is not None else _base_env(agent=False),
    )
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


@pytest.fixture()
def repo(tmp_path):
    """A throwaway work repo with THIS repo's real hooks installed via
    core.hooksPath, plus a throwaway local bare remote to push at."""
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run([GIT, "init", "--bare", "-q", str(remote)], check=True, timeout=60)
    subprocess.run([GIT, "init", "-q", "-b", "master", str(work)], check=True, timeout=60)
    _git(work, "config", "user.email", "e2e@example.invalid")
    _git(work, "config", "user.name", "e2e")
    _git(work, "config", "core.hooksPath", str(HOOKS_DIR))
    (work / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(work, "add", "a.txt")
    _git(work, "commit", "-qm", "init")
    _git(work, "remote", "add", "origin", str(remote))
    return work, remote


def _remote_refs(remote):
    r = subprocess.run([GIT, "--git-dir", str(remote), "for-each-ref", "--format=%(refname)"],
                       capture_output=True, text=True, timeout=60, check=True)
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _guard_events(work):
    trail = work / ".dv-harness" / "events.jsonl"
    if not trail.exists():
        return []
    out = []
    for line in trail.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") == "GIT_GUARD_DECISION":
            out.append(ev)
    return out


class TestRealGitPushIsGatedByGit:
    """`git push` -- not a hand-invoked script -- must reach the gate."""

    def test_agent_push_to_master_is_blocked_by_git_itself(self, repo):
        work, remote = repo
        assert _remote_refs(remote) == []

        r = _git(work, "push", "origin", "master", env=_base_env(agent=True), check=False)

        # git aborted the push because the hook exited non-zero (githooks(5)).
        assert r.returncode != 0, f"push was NOT blocked:\n{r.stdout}\n{r.stderr}"
        combined = r.stdout + r.stderr
        assert "BLOCKED" in combined and "pre-push" in combined
        assert "protected branch 'master'" in combined
        # ...and nothing actually landed on the remote.
        assert _remote_refs(remote) == [], "blocked push still wrote refs to the remote"

    def test_blocked_real_push_writes_a_git_guard_decision_event(self, repo):
        """The audit edge: a real blocked `git push` must leave a real
        GIT_GUARD_DECISION behind, not just print to the terminal."""
        work, remote = repo
        assert _guard_events(work) == []

        _git(work, "push", "origin", "master", env=_base_env(agent=True), check=False)

        events = _guard_events(work)
        assert len(events) == 1, f"expected exactly one guard event, got {events}"
        ev = events[0]
        assert ev["hook"] == "pre-push"
        assert ev["allowed"] is False
        assert ev["branch"] == "master"
        assert "CLAUDECODE" in ev["detected_markers"]

    def test_blocked_real_push_is_readable_through_dv_harness_audit(self, repo):
        """Closes the full diagram edge: git push -> hook -> events.jsonl
        -> `dv-harness audit` (what audit-change-governance-agent reads)."""
        work, remote = repo
        _git(work, "push", "origin", "master", env=_base_env(agent=True), check=False)

        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(work),
             "audit", "--limit", "20"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace", env=_base_env(agent=False),
        )
        assert r.returncode == 0, r.stderr
        assert "GIT_GUARD_DECISION" in r.stdout
        assert "pre-push" in r.stdout

    def test_human_push_to_master_is_allowed_end_to_end(self, repo):
        """The gate must not become a blanket local branch protection: with
        no agent marker in git's environment the real push must succeed."""
        work, remote = repo

        r = _git(work, "push", "origin", "master", env=_base_env(agent=False), check=False)

        assert r.returncode == 0, f"human push was wrongly blocked:\n{r.stdout}\n{r.stderr}"
        assert "refs/heads/master" in _remote_refs(remote)

    def test_agent_push_to_feature_branch_is_allowed_end_to_end(self, repo):
        """Policy is 'an agent may branch/commit/open a PR' -- a real agent
        push to a non-protected branch must go through."""
        work, remote = repo
        env = _base_env(agent=True)
        _git(work, "checkout", "-q", "-b", "feat/gate-e2e", env=env)
        (work / "b.txt").write_text("feature\n", encoding="utf-8")
        _git(work, "add", "b.txt", env=env)
        _git(work, "commit", "-qm", "feature work", env=env)

        r = _git(work, "push", "origin", "feat/gate-e2e", env=env, check=False)

        assert r.returncode == 0, f"agent feature-branch push was wrongly blocked:\n{r.stderr}"
        assert "refs/heads/feat/gate-e2e" in _remote_refs(remote)


class TestRealGitMergeIsGatedByGit:
    """`git merge` -- not a hand-invoked script -- must reach the gate."""

    def test_agent_merge_into_master_is_blocked_by_git_itself(self, repo):
        work, _ = repo
        env = _base_env(agent=True)
        _git(work, "checkout", "-q", "-b", "feat/merge-e2e", env=env)
        (work / "c.txt").write_text("merge me\n", encoding="utf-8")
        _git(work, "add", "c.txt", env=env)
        _git(work, "commit", "-qm", "feature to merge", env=env)
        _git(work, "checkout", "-q", "master", env=env)
        head_before = _git(work, "rev-parse", "HEAD", env=env).stdout.strip()

        # --no-ff so git actually creates a merge COMMIT; githooks(5) skips
        # pre-merge-commit entirely for a fast-forward merge.
        r = _git(work, "merge", "--no-ff", "-m", "merge feat", "feat/merge-e2e",
                 env=env, check=False)

        assert r.returncode != 0, f"merge was NOT blocked:\n{r.stdout}\n{r.stderr}"
        combined = r.stdout + r.stderr
        assert "BLOCKED" in combined and "pre-merge-commit" in combined
        # master did not move: no merge commit was created.
        assert _git(work, "rev-parse", "HEAD", env=env).stdout.strip() == head_before

        events = _guard_events(work)
        assert [e["hook"] for e in events] == ["pre-merge-commit"]
        assert events[0]["allowed"] is False
        assert events[0]["branch"] == "master"


class TestRepoOwnGateIsActuallyInstalled:
    """CLAUDE.md's governance section makes a factual claim about THIS
    repo's own install state. Assert the claim against reality so the
    documentation can never silently go stale again (it already did once:
    the hooks were installed after CLAUDE.md said they were not)."""

    def test_core_hookspath_points_at_tools_git_hooks(self):
        r = subprocess.run([GIT, "config", "--get", "core.hooksPath"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        configured = r.stdout.strip().replace("\\", "/")
        assert configured, (
            "core.hooksPath is not set in this repo -- the PR-only governance "
            "hooks are NOT installed. Run: git config core.hooksPath tools/git-hooks "
            "(and update CLAUDE.md's gh CLI + PR-Only Governance Policy section)."
        )
        assert configured.rstrip("/").endswith("tools/git-hooks"), configured

    def test_both_hook_scripts_exist_under_the_configured_path(self):
        assert (HOOKS_DIR / "pre-push").is_file()
        assert (HOOKS_DIR / "pre-merge-commit").is_file()
