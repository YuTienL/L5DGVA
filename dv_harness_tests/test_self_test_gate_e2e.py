"""End-to-end tests that GIT ITSELF fires the harness self-test gate, and
that a failing self-test really aborts a real push (2026-09-04).

WHY THIS FILE EXISTS. tools/testing/self_test.py was real, correct, and
passing -- but nothing ever ran it on its own. `tools/self_test.sh` is typed
by hand; `.github/workflows/dv-harness-ci.yml` has never actually executed
(this repo's `origin` exists but has no pushed refs, so there has never been
an Actions run). "The harness's own infrastructure breaking is harder to
notice than a wrong judgment call" is the premise the self-test was written
on, and a check that only runs when a human remembers it does not address
that premise.

The fix is a second gate in `tools/git-hooks/pre-push` -- a directory that is
ALREADY this repo's live `core.hooksPath`, so it is a trigger that genuinely
fires here today with no remote and no CI runner. These tests prove that edge
the same way test_git_hooks_e2e.py proves the governance one:

    a real `git push`
      -> git's own hook runner (core.hooksPath = tools/git-hooks)
        -> tools/git-hooks/pre-push (the real script, not a copy)
          -> tools/testing/self_test.py (the real script)
            -> non-zero exit ABORTS the real push
            -> a real run record lands in runs.jsonl, tagged trigger=pre-push

Real everywhere it matters: a real git executable, a real local BARE remote
(never a network remote, never this repo itself), the real hook script, and
for the passing case the REAL self-test running a REAL check against this
repo. Only two things are injected, through seams the hook documents for
exactly this purpose: DV_HARNESS_SELF_TEST_CHECKS narrows the default ~50s
check pair to one check so a test suite stays usable, and
DV_HARNESS_SELF_TEST_SCRIPT points the FAILING case at a throwaway script --
because the only other way to test "a failing self-test blocks the push"
would be to actually break this repo's harness.
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
SELF_TEST = ROOT / "tools" / "testing" / "self_test.py"

sys.path.insert(0, str(ROOT))
from dv_harness.git_governance import AI_AGENT_ENV_MARKERS  # noqa: E402

GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(
    GIT is None or not (HOOKS_DIR / "pre-push").exists() or not SELF_TEST.exists(),
    reason="needs a real git executable, the tools/git-hooks scripts, and self_test.py",
)


def _base_env(record_dir: Path, **extra):
    """A real child environment for git. The agent markers are STRIPPED so
    the governance gate (which runs first in the same hook) allows the push
    and we are genuinely testing the self-test gate that follows it -- this
    runner is itself inside a real AI-agent environment, exactly the case
    test_git_hooks_e2e.py's own `_base_env` already handles this way.
    PYTHONPATH=ROOT is what lets the hook's `python -m dv_harness.cli`
    resolve this package from inside the throwaway repo."""
    env = dict(os.environ)
    for marker in AI_AGENT_ENV_MARKERS:
        env.pop(marker, None)
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("GIT_DIR", None)
    # Never append to this repo's own run history from a test.
    env["DV_HARNESS_SELF_TEST_RECORD_DIR"] = str(record_dir)
    env.pop("DV_HARNESS_SKIP_SELF_TEST", None)
    env.pop("DV_HARNESS_SELF_TEST_SCRIPT", None)
    env.update(extra)
    return env


def _git(work, *args, env=None, check=True):
    r = subprocess.run(
        [GIT, *args], cwd=str(work), capture_output=True, text=True,
        timeout=600, encoding="utf-8", errors="replace",
        env=env if env is not None else _base_env(Path(work) / "_unused_records"),
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
    records = tmp_path / "records"
    subprocess.run([GIT, "init", "--bare", "-q", str(remote)], check=True, timeout=120)
    subprocess.run([GIT, "init", "-q", "-b", "master", str(work)], check=True, timeout=120)
    _git(work, "config", "user.email", "e2e@example.invalid")
    _git(work, "config", "user.name", "e2e")
    _git(work, "config", "core.hooksPath", str(HOOKS_DIR))
    (work / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(work, "add", "a.txt")
    _git(work, "commit", "-qm", "init")
    _git(work, "remote", "add", "origin", str(remote))
    return work, remote, records


def _remote_refs(remote):
    r = subprocess.run([GIT, "--git-dir", str(remote), "for-each-ref", "--format=%(refname)"],
                       capture_output=True, text=True, timeout=120, check=True)
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _records(record_dir: Path):
    log = record_dir / "runs.jsonl"
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


class TestPrePushSelfTestGate:

    def test_a_real_push_runs_the_real_self_test_and_records_it(self, repo):
        """The whole point: an automatic trigger that actually fires. No
        human types anything -- `git push` alone causes the real self-test
        script to run a real check against this repo, and leaves a real,
        trigger-tagged record behind."""
        work, remote, records = repo
        env = _base_env(records, DV_HARNESS_SELF_TEST_CHECKS="import-sanity")
        r = _git(work, "push", "origin", "master", env=env, check=False)

        assert r.returncode == 0, f"push should have succeeded:\n{r.stdout}\n{r.stderr}"
        assert "refs/heads/master" in _remote_refs(remote)
        assert "[self-test]" in r.stderr, "the gate must announce itself"

        rows = _records(records)
        assert len(rows) == 1, f"expected exactly one run record, got {rows}"
        row = rows[0]
        assert row["trigger"] == "pre-push", "the record must name what triggered it"
        assert row["ok"] is True
        assert [c["name"] for c in row["checks"]] == ["import-sanity"]
        assert row["checks"][0]["ok"] is True
        assert row["checks"][0]["seconds"] > 0, "a real check really ran"
        # last_run.json is the cheap-to-read view of the same run.
        last = json.loads((records / "last_run.json").read_text(encoding="utf-8"))
        assert last["trigger"] == "pre-push" and last["ok"] is True

    def test_a_failing_self_test_aborts_the_real_push(self, tmp_path, repo):
        """Fail-CLOSED. A self-test that really ran and really failed must
        abort the push -- otherwise the gate is decoration. Driven through
        git's own hook runner, and asserted on the remote's refs, not on the
        hook's output."""
        work, remote, records = repo
        broken = tmp_path / "broken_self_test.py"
        broken.write_text(
            "import sys\n"
            "print('==> pretend-check ...\\n    FAIL (0.0s)')\n"
            "sys.exit(1)\n", encoding="utf-8")
        env = _base_env(records, DV_HARNESS_SELF_TEST_SCRIPT=str(broken))

        r = _git(work, "push", "origin", "master", env=env, check=False)

        assert r.returncode != 0, "a failing self-test must abort the push"
        assert "[self-test] FAILED" in r.stderr
        assert _remote_refs(remote) == [], "nothing may reach the remote"

    def test_the_documented_bypass_really_bypasses(self, repo):
        """The escape hatch the hook documents for "I am pushing the fix
        itself" -- asserted, not assumed, because a bypass that silently does
        not work would turn every broken-harness push into a dead end."""
        work, remote, records = repo
        env = _base_env(records, DV_HARNESS_SKIP_SELF_TEST="1")
        r = _git(work, "push", "origin", "master", env=env, check=False)

        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert "refs/heads/master" in _remote_refs(remote)
        assert "skipped" in r.stderr
        assert _records(records) == [], "a bypassed gate must not record a run it never did"

    def test_a_missing_self_test_script_fails_open(self, tmp_path, repo):
        """Fail-OPEN on an unrelated environment problem: a checkout that
        simply has no self_test.py (someone else's repo using these hooks)
        must not have its pushes blocked by ours."""
        work, remote, records = repo
        env = _base_env(records, DV_HARNESS_SELF_TEST_SCRIPT=str(tmp_path / "nope.py"))
        r = _git(work, "push", "origin", "master", env=env, check=False)

        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert "refs/heads/master" in _remote_refs(remote)
        assert "not found" in r.stderr

    def test_the_governance_gate_still_runs_first_and_still_blocks_an_agent(self, repo):
        """Regression guard on the hook's ordering: adding a second gate must
        not have broken the first one. git feeds the push refspecs on stdin
        and stdin can only be read once, so the governance gate must still be
        the consumer and must still abort an AGENT's direct push to master
        BEFORE the self-test ever runs."""
        work, remote, records = repo
        env = _base_env(records, CLAUDECODE="1")
        r = _git(work, "push", "origin", "master", env=env, check=False)

        assert r.returncode != 0, "an agent's direct push to master must still be blocked"
        assert _remote_refs(remote) == []
        assert "[self-test]" not in r.stderr, "the self-test must not run after a governance BLOCK"
        assert _records(records) == []


class TestRunRecord:
    """The record itself, independent of git -- what makes 'has an automated
    trigger ever executed the self-test here?' an answerable question."""

    def test_record_is_written_with_the_trigger_and_real_check_results(self, tmp_path):
        env = dict(os.environ)
        env["DV_HARNESS_SELF_TEST_RECORD_DIR"] = str(tmp_path / "rec")
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, str(SELF_TEST), "--only", "import-sanity",
             "--record", "--trigger", "ci", "--json"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=600, env=env)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["ok"] is True
        record = payload["run_record"]
        assert record["trigger"] == "ci"
        assert record["failed_checks"] == []
        assert record["python"] == ".".join(str(p) for p in sys.version_info[:3])
        rows = [json.loads(ln) for ln
                in (tmp_path / "rec" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
                if ln.strip()]
        assert rows == [record]

    def test_nothing_is_recorded_without_the_flag(self, tmp_path):
        """--record is opt-in so an ordinary hand-run does not dirty the
        tree, and so the history stays an honest record of AUTOMATED runs."""
        env = dict(os.environ)
        env["DV_HARNESS_SELF_TEST_RECORD_DIR"] = str(tmp_path / "rec")
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, str(SELF_TEST), "--only", "import-sanity", "--json"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=600, env=env)
        assert proc.returncode == 0
        assert "run_record" not in json.loads(proc.stdout)
        assert not (tmp_path / "rec").exists()

    def test_a_failing_run_is_recorded_too(self, tmp_path):
        """An audit trail that only exists on success is not an audit
        trail. Uses a real check driven to a real failure: pytest against a
        selector that matches nothing exits non-zero."""
        env = dict(os.environ)
        env["DV_HARNESS_SELF_TEST_RECORD_DIR"] = str(tmp_path / "rec")
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, str(SELF_TEST), "--only", "pytest", "--record",
             "--trigger", "scheduled", "--pytest-timeout", "300",
             "--pytest-args", "-k", "this_selector_matches_no_test_at_all"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=600, env=env)
        assert proc.returncode != 0
        record = json.loads((tmp_path / "rec" / "last_run.json").read_text(encoding="utf-8"))
        assert record["ok"] is False
        assert record["trigger"] == "scheduled"
        assert record["failed_checks"] == ["pytest"]
