"""Tests for dv_harness/task_boundary_conformance.py -- the structural,
evidence-grounded check of whether a real change set stayed inside a
declared task boundary. See the module docstring for what this does and
does not claim to answer.

Every test runs against a real throwaway git repo in tmp_path -- no
production build, regression or LSF submission involved, matching
test_change_blast_radius.py's own real-git-over-tmp_path discipline.

Ported verbatim from this module's Parent source
(D:\\DV\\Task\\DV_Agent_Harness_L5\\dv_harness_tests\\test_task_boundary_conformance.py,
committed 705c469b), independently re-run and confirmed 19/19 passing in
Parent's own tree before being trusted, per this project's standing
migration discipline.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dv_harness import task_boundary_conformance as tbc  # noqa: E402

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, check=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    _run(work, "init", "-q")
    _run(work, "config", "user.email", "test@example.com")
    _run(work, "config", "user.name", "Test")
    (work / "dv_harness").mkdir()
    (work / "dv_harness" / "engine.py").write_text("# engine\n", encoding="utf-8")
    (work / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
    _run(work, "add", "-A")
    _run(work, "commit", "-q", "-m", "initial")
    return work


def _boundary(**overrides) -> tbc.TaskBoundary:
    base = dict(
        task_id="T1",
        allowed_path_prefixes=("dv_harness/task_boundary_conformance.py",
                                "dv_harness_tests/test_task_boundary_conformance.py"),
        forbidden_paths=("dv_harness/engine.py", "dv_harness/cli.py", "CLAUDE.md"),
        require_new_file=True,
    )
    base.update(overrides)
    return tbc.TaskBoundary.from_dict(base)


# ---------------------------------------------------------------------------
# working_tree_changes(): real evidence extraction
# ---------------------------------------------------------------------------
class TestWorkingTreeEvidence:

    def test_no_git_reports_no_git_not_a_crash(self, tmp_path):
        result = tbc.working_tree_changes(tmp_path / "not_a_repo")
        assert result["status"] == "NO_GIT"
        assert result["entries"] == []

    def test_clean_repo_has_no_entries(self, repo):
        result = tbc.working_tree_changes(repo)
        assert result["status"] == "GIT_STATUS_OK"
        assert result["entries"] == []

    def test_new_untracked_file_is_status_added(self, repo):
        (repo / "dv_harness" / "task_boundary_conformance.py").write_text("x", encoding="utf-8")
        result = tbc.working_tree_changes(repo)
        paths = {e["path"]: e["change_status"] for e in result["entries"]}
        assert paths["dv_harness/task_boundary_conformance.py"] == tbc.STATUS_ADDED

    def test_modified_tracked_file_is_status_modified(self, repo):
        (repo / "dv_harness" / "engine.py").write_text("# engine v2\n", encoding="utf-8")
        result = tbc.working_tree_changes(repo)
        paths = {e["path"]: e["change_status"] for e in result["entries"]}
        assert paths["dv_harness/engine.py"] == tbc.STATUS_MODIFIED


# ---------------------------------------------------------------------------
# classify_path(): forbidden beats allowed, outside is outside, add-only
# ---------------------------------------------------------------------------
class TestClassifyPath:

    def test_forbidden_wins_even_if_nested_under_an_allowed_prefix(self):
        b = tbc.TaskBoundary(
            task_id="T", allowed_path_prefixes=("dv_harness",),
            forbidden_paths=("dv_harness/engine.py",),
        )
        assert tbc.classify_path("dv_harness/engine.py", b, tbc.STATUS_MODIFIED) == tbc.CLASS_FORBIDDEN

    def test_path_outside_every_allowed_prefix_is_outside(self):
        b = tbc.TaskBoundary(task_id="T", allowed_path_prefixes=("dv_harness/foo.py",))
        assert tbc.classify_path("dv_harness/bar.py", b, tbc.STATUS_ADDED) == tbc.CLASS_OUTSIDE

    def test_require_new_file_rejects_a_modification(self):
        b = tbc.TaskBoundary(task_id="T", allowed_path_prefixes=("dv_harness/foo.py",),
                              require_new_file=True)
        assert tbc.classify_path("dv_harness/foo.py", b, tbc.STATUS_MODIFIED) == tbc.CLASS_ADD_ONLY_VIOLATION

    def test_require_new_file_accepts_a_real_add(self):
        b = tbc.TaskBoundary(task_id="T", allowed_path_prefixes=("dv_harness/foo.py",),
                              require_new_file=True)
        assert tbc.classify_path("dv_harness/foo.py", b, tbc.STATUS_ADDED) == tbc.CLASS_WITHIN_BOUNDARY

    def test_prefix_match_is_a_real_path_segment_not_a_substring(self):
        # "dv_harness/foo" must not match "dv_harness/foobar.py"
        b = tbc.TaskBoundary(task_id="T", allowed_path_prefixes=("dv_harness/foo",))
        assert tbc.classify_path("dv_harness/foobar.py", b, tbc.STATUS_ADDED) == tbc.CLASS_OUTSIDE


# ---------------------------------------------------------------------------
# check_working_tree_conformance(): the real end-to-end verdict
# ---------------------------------------------------------------------------
class TestWorkingTreeConformance:

    def test_new_file_inside_declared_boundary_holds(self, repo):
        (repo / "dv_harness" / "task_boundary_conformance.py").write_text("x", encoding="utf-8")
        result = tbc.check_working_tree_conformance(repo, _boundary())
        assert result["verdict"] == tbc.VERDICT_HELD
        assert result["findings"][0]["classification"] == tbc.CLASS_WITHIN_BOUNDARY
        assert result["scope_caveat"] == tbc.SCOPE_CAVEAT

    def test_editing_a_forbidden_file_is_a_violation(self, repo):
        (repo / "CLAUDE.md").write_text("# rules v2\n", encoding="utf-8")
        result = tbc.check_working_tree_conformance(repo, _boundary())
        assert result["verdict"] == tbc.VERDICT_VIOLATION
        assert result["findings"][0]["classification"] == tbc.CLASS_FORBIDDEN

    def test_editing_engine_py_is_a_violation_even_though_its_under_dv_harness(self, repo):
        (repo / "dv_harness" / "engine.py").write_text("# engine v2\n", encoding="utf-8")
        boundary = _boundary(allowed_path_prefixes=("dv_harness",))
        result = tbc.check_working_tree_conformance(repo, boundary)
        assert result["verdict"] == tbc.VERDICT_VIOLATION
        assert result["findings"][0]["classification"] == tbc.CLASS_FORBIDDEN

    def test_editing_an_unrelated_existing_file_is_outside_boundary(self, repo):
        (repo / "README.md").write_text("hi", encoding="utf-8")
        _run(repo, "add", "README.md")
        _run(repo, "commit", "-q", "-m", "seed readme")
        (repo / "README.md").write_text("hi v2", encoding="utf-8")
        result = tbc.check_working_tree_conformance(repo, _boundary())
        assert result["verdict"] == tbc.VERDICT_VIOLATION
        assert result["findings"][0]["classification"] == tbc.CLASS_OUTSIDE

    def test_modifying_the_one_allowed_file_violates_an_add_only_boundary(self, repo):
        (repo / "dv_harness" / "task_boundary_conformance.py").write_text("x", encoding="utf-8")
        _run(repo, "add", "-A")
        _run(repo, "commit", "-q", "-m", "seed the new module")
        (repo / "dv_harness" / "task_boundary_conformance.py").write_text("x v2", encoding="utf-8")
        result = tbc.check_working_tree_conformance(repo, _boundary())
        assert result["verdict"] == tbc.VERDICT_VIOLATION
        assert result["findings"][0]["classification"] == tbc.CLASS_ADD_ONLY_VIOLATION

    def test_clean_tree_reports_no_changes_to_check(self, repo):
        result = tbc.check_working_tree_conformance(repo, _boundary())
        assert result["verdict"] == tbc.VERDICT_NO_CHANGES

    def test_no_git_repo_reports_no_git_evidence(self, tmp_path):
        result = tbc.check_working_tree_conformance(tmp_path / "missing", _boundary())
        assert result["verdict"] == tbc.VERDICT_NO_GIT


# ---------------------------------------------------------------------------
# check_committed_range_conformance(): the committed-range counterpart
# ---------------------------------------------------------------------------
class TestCommittedRangeConformance:

    def test_a_committed_in_boundary_add_holds(self, repo):
        base = _run(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / "dv_harness" / "task_boundary_conformance.py").write_text("x", encoding="utf-8")
        _run(repo, "add", "-A")
        _run(repo, "commit", "-q", "-m", "add the module")
        result = tbc.check_committed_range_conformance(repo, _boundary(), base)
        assert result["verdict"] == tbc.VERDICT_HELD

    def test_a_committed_forbidden_edit_is_a_violation(self, repo):
        base = _run(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / "dv_harness" / "engine.py").write_text("# engine v2\n", encoding="utf-8")
        _run(repo, "add", "-A")
        _run(repo, "commit", "-q", "-m", "sneak an engine.py edit in")
        result = tbc.check_committed_range_conformance(repo, _boundary(), base)
        assert result["verdict"] == tbc.VERDICT_VIOLATION
        assert result["findings"][0]["classification"] == tbc.CLASS_FORBIDDEN

    def test_unknown_base_sha_reports_unknown_base(self, repo):
        result = tbc.check_committed_range_conformance(repo, _boundary(), "deadbeef" * 5)
        assert result["verdict"] == tbc.VERDICT_NO_GIT
        assert result["git_status"] == "UNKNOWN_BASE"
