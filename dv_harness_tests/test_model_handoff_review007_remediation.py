"""Regression test for R007-1, independently reproduced and fixed from the
real (if formally quarantined -- see MALFORMED_ESCAPE / GAP-V2-016)
M7-V1-CODEX-REVIEW-007 result content. The finding's CLAIM was
independently re-verified by direct code inspection before this fix was
applied, per this project's own Evidence Truth Rule -- never trusted from
the quarantined document's text alone, quarantined or not."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import dv_harness.model_handoff_workflow as wf

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")


def _run(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    w = tmp_path / "work"
    w.mkdir()
    _run(w, "init", "-q")
    _run(w, "config", "user.email", "t@example.com")
    _run(w, "config", "user.name", "T")
    return w


# ================================================================ R007-1: release-retry ownership revalidation

def test_release_retry_revalidates_ownership_before_every_unlink_attempt(repo, monkeypatch):
    """Codex REVIEW-007 R007-1's real probe, reproduced: `_release_lock()`
    checked the token ONCE before its retry loop (REVIEW-006's own
    sharing-failure-retry fix). A first unlink attempt hitting a transient
    OSError, followed by a legitimate new owner taking over the lock in
    place BEFORE the retry, must never be masked as "still transient" --
    the retry must re-earn the right to delete, not just keep trying the
    original plan."""
    lock = repo / "x.lock"
    token_a = wf._acquire_lock(lock)
    assert token_a is not None

    real_unlink = Path.unlink
    calls = {"n": 0}

    def flaky_unlink(self, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            # A legitimate new owner B takes over the lock IN PLACE
            # (exactly what _try_stale_takeover_in_place() does) between
            # this failed attempt and the retry.
            lock.write_text("new-owner-b-token:999", encoding="utf-8")
            raise PermissionError("simulated transient sharing failure")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    wf._release_lock(lock, token_a)

    assert calls["n"] == 1  # never even attempted a second unlink -- B's token was seen first
    assert lock.exists()
    assert lock.read_text(encoding="utf-8") == "new-owner-b-token:999"  # B's real lock, untouched


def test_release_still_retries_a_genuinely_transient_failure_with_unchanged_ownership(repo, monkeypatch):
    """The fix must not regress the REVIEW-006 flake fix it is built on:
    a transient failure with NO ownership change must still succeed on
    retry, not be treated as a lost-ownership case."""
    lock = repo / "x.lock"
    token_a = wf._acquire_lock(lock)
    assert token_a is not None

    real_unlink = Path.unlink
    calls = {"n": 0}

    def flaky_unlink(self, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("simulated transient sharing failure, no ownership change")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    wf._release_lock(lock, token_a)

    assert calls["n"] == 2
    assert not lock.exists()  # genuinely released


def test_release_with_a_wrong_token_still_refuses_immediately(repo):
    lock = repo / "x.lock"
    token_a = wf._acquire_lock(lock)
    assert token_a is not None
    wf._release_lock(lock, "wrong-token:1")
    assert lock.exists()
    assert lock.read_text(encoding="utf-8") == token_a
    wf._release_lock(lock, token_a)
    assert not lock.exists()
