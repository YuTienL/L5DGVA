"""Regression tests for `dv_harness/controlled_process_executor.py` --
the L5DGVA Controlled Process Execution / Model Worker Governance module
(docs/architecture/canonical_detailed_governance/
L5DGVA_CONTROLLED_PROCESS_EXECUTION_AND_MODEL_WORKER_GOVERNANCE_
REQUIREMENTS.md). Covers the anti-drift test names both the governance
doc and its integration prompt require, scoped to this module's own real
responsibility (repository identity, semantic profiles, bounded temp
cleanup) -- mutation-lease/agent-run anti-drift tests already exist in
test_agent_execution_backend.py and test_model_handoff_review00[6-7]_
remediation.py and are not duplicated here."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import dv_harness.controlled_process_executor as cpe
from dv_harness.safe_tool_profile import CLAUDE_READONLY_PROFILE, CLAUDE_IMPLEMENTATION_PROFILE

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
    (w / "dv_harness").mkdir()
    (w / "dv_harness" / "x.py").write_text("# x\n", encoding="utf-8")
    (w / "dv_harness_tests").mkdir()
    _run(w, "add", "-A")
    _run(w, "commit", "-q", "-m", "i")
    (w / ".dv-harness").mkdir()
    return w


# ================================================================ Repository Identity Gate

def test_real_canonical_root_matches_itself(repo):
    result = cpe.verify_canonical_repository_identity(repo, expected_repo_root=repo)
    assert result.matched is True
    assert result.reason == "MATCHED"
    assert result.head


def test_process_launch_requires_repo_identity_match(repo):
    """A DIFFERENT real repo (not a subdirectory -- a genuinely separate
    root) must never match another repo's expected identity."""
    other = repo.parent / "other_repo"
    other.mkdir()
    _run(other, "init", "-q")
    _run(other, "config", "user.email", "t@example.com")
    _run(other, "config", "user.name", "T")
    (other / "f.txt").write_text("x", encoding="utf-8")
    _run(other, "add", "-A")
    _run(other, "commit", "-q", "-m", "i")
    (other / ".dv-harness").mkdir()

    result = cpe.verify_canonical_repository_identity(other, expected_repo_root=repo)
    assert result.matched is False
    assert result.reason == "REPO_ROOT_MISMATCH"

    with pytest.raises(cpe.RepositoryIdentityError):
        cpe.require_canonical_repository_identity(other, expected_repo_root=repo)


def test_a_nested_throwaway_probe_repo_never_matches_the_canonical_root(repo):
    """The real, observed risk this gate exists for: this program's own
    Codex review probes create a NESTED git repo inside the Canonical
    tree's own .dv-harness scratch area. A relative-.dv-harness-path
    match would wrongly accept it; this gate must not."""
    nested = repo / ".dv-harness" / "model_handoffs" / "T-1" / ".probe_tmp" / "work"
    nested.mkdir(parents=True)
    _run(nested, "init", "-q")
    (nested / ".dv-harness").mkdir()

    result = cpe.verify_canonical_repository_identity(nested)
    assert result.matched is False


def test_a_plain_directory_with_no_git_is_not_a_repository(repo):
    plain = repo / "not_a_repo"
    plain.mkdir()
    result = cpe.verify_canonical_repository_identity(plain)
    assert result.matched is False
    assert result.reason == "NOT_A_GIT_WORKTREE"


# ================================================================ Semantic Safe Tool Profiles

def test_every_semantic_profile_name_resolves_to_a_real_tool_execution_profile_or_none():
    for name in cpe.SEMANTIC_PROFILE_NAMES:
        profile = cpe.semantic_profile_tool_execution_profile(name)
        if name == cpe.SAFE_TEST_TEMP_CLEANUP:
            assert profile is None
        else:
            assert profile in (CLAUDE_READONLY_PROFILE, CLAUDE_IMPLEMENTATION_PROFILE)


def test_powershell_executor_requires_a_known_profile():
    with pytest.raises(ValueError):
        cpe.semantic_profile_tool_execution_profile("NOT_A_REAL_PROFILE")


def test_read_only_semantic_profiles_never_grant_code_execution():
    for name in (cpe.SAFE_STATUS, cpe.SAFE_READ, cpe.SAFE_HANDOFF_GENERATION,
                cpe.SAFE_RESULT_VALIDATION, cpe.CODEX_REVIEW, cpe.CHATGPT_HANDOFF_PREPARATION):
        profile = cpe.semantic_profile_tool_execution_profile(name)
        assert "PowerShell" not in profile.tools


def test_mutation_capable_semantic_profiles_use_the_bounded_implementation_profile():
    for name in (cpe.SAFE_TEST, cpe.SAFE_REGRESSION, cpe.CLAUDE_REMEDIATION, cpe.NATIVE_CANONICAL_MAINTENANCE):
        profile = cpe.semantic_profile_tool_execution_profile(name)
        assert profile is CLAUDE_IMPLEMENTATION_PROFILE
        assert "Edit" in profile.allowed_tool_patterns and "Write" in profile.allowed_tool_patterns


# ================================================================ SAFE_TEST_TEMP_CLEANUP

def _scratch_dir(repo: Path, task_id: str = "T-1", name: str = ".probe_tmp") -> Path:
    d = repo / ".dv-harness" / "model_handoffs" / task_id / name / "work"
    d.mkdir(parents=True)
    (repo / ".dv-harness" / "model_handoffs" / task_id / name).mkdir(exist_ok=True)
    return repo / ".dv-harness" / "model_handoffs" / task_id / name


def test_safe_temp_cleanup_validates_a_real_registered_scratch_dir(repo):
    target = _scratch_dir(repo)
    result = cpe.safe_test_temp_cleanup(repo, target, dry_run=True)
    assert result["validated"] is True
    assert result["deleted"] is False
    assert target.exists()  # dry_run never deletes


def test_safe_temp_cleanup_rejects_out_of_scope_target(repo):
    """An arbitrary, unregistered directory must never be accepted, even
    if it happens to sit under .dv-harness."""
    arbitrary = repo / ".dv-harness" / "agent_runs"
    arbitrary.mkdir(parents=True)
    with pytest.raises(cpe.UnsafeTempCleanupTargetError) as exc:
        cpe.safe_test_temp_cleanup(repo, arbitrary, dry_run=True)
    assert exc.value.reason == "TARGET_NOT_A_REGISTERED_TASK_SCRATCH_DIR"


def test_safe_temp_cleanup_rejects_production_paths(repo):
    with pytest.raises(cpe.UnsafeTempCleanupTargetError) as exc:
        cpe.safe_test_temp_cleanup(repo, repo / "dv_harness", dry_run=True)
    assert exc.value.reason == "TARGET_IS_PRODUCTION_PATH"


def test_safe_temp_cleanup_rejects_the_repository_root_and_git_dir(repo):
    with pytest.raises(cpe.UnsafeTempCleanupTargetError) as exc:
        cpe.safe_test_temp_cleanup(repo, repo, dry_run=True)
    assert exc.value.reason == "TARGET_IS_REPOSITORY_ROOT"

    with pytest.raises(cpe.UnsafeTempCleanupTargetError) as exc2:
        cpe.safe_test_temp_cleanup(repo, repo / ".git", dry_run=True)
    assert exc2.value.reason == "TARGET_IS_GIT_DIRECTORY"


def test_safe_temp_cleanup_rejects_a_target_outside_the_repository(repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(cpe.UnsafeTempCleanupTargetError) as exc:
        cpe.safe_test_temp_cleanup(repo, outside, dry_run=True)
    assert exc.value.reason == "TARGET_ESCAPES_REPOSITORY_ROOT"


def test_safe_temp_cleanup_real_deletion_only_when_explicitly_authorized(repo):
    """dry_run=False on a genuinely valid, bounded target performs a real
    deletion -- proving the mechanism itself works end to end -- while
    this test (a fresh process/context, not the live interactive session
    that hit the real classifier denial) is a legitimate caller for it."""
    target = _scratch_dir(repo)
    assert target.exists()
    result = cpe.safe_test_temp_cleanup(repo, target, dry_run=False)
    assert result["deleted"] is True
    assert not target.exists()
