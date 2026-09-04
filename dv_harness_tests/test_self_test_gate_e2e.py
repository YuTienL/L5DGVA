"""End-to-end tests that GIT ITSELF fires the harness self-test gate, and
that a failing self-test really aborts a real push (2026-09-04).

WHY THIS FILE EXISTS. tools/testing/self_test.py was real, correct, and
passing -- but nothing ever ran it on its own. `tools/self_test.sh` is typed
by hand, and `.github/workflows/dv-harness-ci.yml` could not fire because
this repo's `origin`, though reachable, had no pushed refs at all. "The
harness's own infrastructure breaking is harder to notice than a wrong
judgment call" is the premise the self-test was written on, and a check that
only runs when a human remembers it does not address that premise.

The fix is a second gate in `tools/git-hooks/pre-push` -- a directory that is
ALREADY this repo's live `core.hooksPath`, so it is a trigger that genuinely
fires here today, needing no remote and no CI runner. These tests prove that
edge the same way test_git_hooks_e2e.py proves the governance one:

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

The remote has since stopped being empty (a real branch carrying the workflow
is now pushed), which retired the "no pushed refs" half of the paragraph
above. That claim had already gone stale twice inside two days while nothing
checked it, so TestCiDisclosureIsNotStale below now holds the workflow file's
own DISCLOSURE-CHECK token to the REAL ref state of `origin` -- the same
"prose is only improved by being held to the code" discipline
dv_harness/mcp/claude_md_index.py and source_authority.assert_doc_matches_code()
already apply to CLAUDE.md.
"""
from __future__ import annotations

import json
import os
import re
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


CI_WORKFLOW = ROOT / ".github" / "workflows" / "dv-harness-ci.yml"
DISCLOSURE_TOKEN_RE = re.compile(
    r"^#\s*DISCLOSURE-CHECK:\s*remote_pushed_refs=(yes|no)\s*$", re.MULTILINE)


def _origin_has_pushed_refs() -> bool | None:
    """Real current answer to "has anything ever been pushed to origin", or
    None when this checkout genuinely cannot tell.

    Deliberately network-free. `git ls-remote` would be the authoritative
    source, but a test that reaches the network fails offline and on any
    runner without credentials for a PRIVATE repo -- and a flaky truth check
    is one that gets deleted. Local remote-tracking refs under refs/remotes/
    are written by the very push/fetch whose existence is the question, so
    their presence is positive evidence a real push happened. Their ABSENCE
    is genuinely ambiguous (a fresh clone that never fetched looks identical
    to an empty remote), which is why that case returns None and the test
    skips rather than asserting something it cannot support.
    """
    if GIT is None:
        return None
    try:
        proc = subprocess.run([GIT, "for-each-ref", "--format=%(refname)", "refs/remotes"],
                               cwd=str(ROOT), capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return True if proc.stdout.strip() else None


class TestCiDisclosureIsNotStale:
    """The CI workflow's honest-disclosure header states whether `origin` has
    any pushed refs, because that single fact decides whether the workflow can
    fire at all. It was written wrong twice in two days -- not through
    carelessness, but because nothing compared it to reality. These hold it to
    reality.
    """

    def test_the_workflow_carries_a_machine_checkable_disclosure_token(self):
        """A prose disclosure nothing parses is exactly what went stale. The
        token must exist and be one of the two legal values -- a reworded,
        deleted or hand-mangled token fails here rather than silently
        disabling the check below."""
        assert CI_WORKFLOW.exists(), f"missing {CI_WORKFLOW}"
        matches = DISCLOSURE_TOKEN_RE.findall(CI_WORKFLOW.read_text(encoding="utf-8"))
        assert len(matches) == 1, (
            "expected exactly one '# DISCLOSURE-CHECK: remote_pushed_refs=yes|no' "
            f"line in {CI_WORKFLOW.name}, found {len(matches)}: {matches}")

    def test_the_disclosed_state_matches_the_real_remote(self):
        """The actual anti-staleness gate: what the file CLAIMS about origin's
        refs must equal what origin's refs really are."""
        real = _origin_has_pushed_refs()
        if real is None:
            pytest.skip("no remote-tracking refs in this checkout -- cannot "
                        "distinguish an empty remote from a never-fetched clone")
        claimed = DISCLOSURE_TOKEN_RE.findall(CI_WORKFLOW.read_text(encoding="utf-8"))[0]
        assert claimed == "yes", (
            f"{CI_WORKFLOW.name} discloses remote_pushed_refs={claimed}, but this "
            "checkout has real remote-tracking refs under refs/remotes/, so a push "
            "to origin really has happened and the workflow's push/pull_request "
            "triggers are live. Update that header's disclosure to match.")

    def test_the_disclosure_does_not_reassert_the_retracted_empty_remote_claim(self):
        """Belt-and-braces on the specific sentence that was wrong twice. The
        token above governs; this catches a well-meaning edit that restores the
        old narrative prose around a still-correct token, which would leave a
        reader believing CI cannot run."""
        text = CI_WORKFLOW.read_text(encoding="utf-8")
        if _origin_has_pushed_refs() is None:
            pytest.skip("cannot determine real remote state in this checkout")
        for retracted in ("remote EXISTS and is reachable, but is EMPTY",
                           "has still never actually executed",
                           "there are no remote branches"):
            assert retracted not in text, (
                f"{CI_WORKFLOW.name} still contains the retracted claim "
                f"{retracted!r}, which real remote-tracking refs contradict.")
