"""Real tests for dv_harness/safety_sandbox.py -- Safety Sandbox / Change Containment.

Every test drives the real module functions against a real temp directory tree
(no mocks of the module under test). Git-diff-based tests
(`verify_diff_against_sandbox`) drive a real throwaway git repository via
subprocess, the same convention `test_change_blast_radius.py` and
`test_golden_scenario.py` already use.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import safety_sandbox as sbx


# --- declaration --------------------------------------------------------------


def test_declare_and_load_round_trip(tmp_path):
    decl = sbx.declare_sandbox(
        tmp_path, ["dv_harness/foo_module.py", "dv_harness_tests/test_foo_module.py"],
        declared_by="agent-1", reason="add foo_module per task X",
    )
    assert decl.sandbox_id
    assert decl.digest

    loaded = sbx.load_sandbox(tmp_path, decl.sandbox_id)
    assert loaded is not None
    assert loaded.allowed_paths == decl.allowed_paths
    assert loaded.declared_by == "agent-1"
    assert loaded.reason == "add foo_module per task X"


def test_declare_requires_real_attribution(tmp_path):
    with pytest.raises(sbx.SandboxError):
        sbx.declare_sandbox(tmp_path, ["a.py"], declared_by="", reason="x")
    with pytest.raises(sbx.SandboxError):
        sbx.declare_sandbox(tmp_path, ["a.py"], declared_by="agent", reason="   ")


def test_declare_refuses_blank_pattern(tmp_path):
    with pytest.raises(sbx.SandboxError):
        sbx.declare_sandbox(tmp_path, ["a.py", "  "], declared_by="agent", reason="x")


def test_declare_empty_allowlist_is_legal_write_nothing_sandbox(tmp_path):
    decl = sbx.declare_sandbox(tmp_path, [], declared_by="agent", reason="read-only pass")
    assert decl.allowed_paths == []
    # Any proposed path against an empty allowlist is a real VIOLATION, not ALLOWED.
    assessment = sbx.assess_proposed_change(tmp_path, decl.sandbox_id, ["a.py"])
    assert assessment.status == sbx.STATUS_VIOLATION


def test_explicit_sandbox_id_is_used_verbatim(tmp_path):
    decl = sbx.declare_sandbox(tmp_path, ["x.py"], declared_by="a", reason="r",
                                sandbox_id="SBX-fixed-1")
    assert decl.sandbox_id == "SBX-fixed-1"
    assert sbx.load_sandbox(tmp_path, "SBX-fixed-1") is not None


def test_redeclaring_same_id_overwrites(tmp_path):
    sbx.declare_sandbox(tmp_path, ["a.py"], declared_by="a", reason="r", sandbox_id="SBX-1")
    sbx.declare_sandbox(tmp_path, ["b.py"], declared_by="a", reason="r2", sandbox_id="SBX-1")
    loaded = sbx.load_sandbox(tmp_path, "SBX-1")
    assert loaded.allowed_paths == ["b.py"]
    assert loaded.reason == "r2"


def test_list_sandboxes(tmp_path):
    assert sbx.list_sandboxes(tmp_path) == []
    sbx.declare_sandbox(tmp_path, ["a.py"], declared_by="a", reason="r", sandbox_id="SBX-a")
    sbx.declare_sandbox(tmp_path, ["b.py"], declared_by="a", reason="r", sandbox_id="SBX-b")
    ids = sorted(d.sandbox_id for d in sbx.list_sandboxes(tmp_path))
    assert ids == ["SBX-a", "SBX-b"]


def test_invalid_sandbox_id_refused(tmp_path):
    with pytest.raises(sbx.SandboxError):
        sbx.declare_sandbox(tmp_path, ["a.py"], declared_by="a", reason="r",
                             sandbox_id="../escape")


# --- path pattern matching --------------------------------------------------


def test_exact_path_match():
    assert sbx.path_matches_pattern("dv_harness/foo.py", "dv_harness/foo.py")
    assert not sbx.path_matches_pattern("dv_harness/foo.py", "dv_harness/bar.py")


def test_directory_prefix_match():
    assert sbx.path_matches_pattern("docs/x/y.md", "docs/")
    assert sbx.path_matches_pattern("docs", "docs/")
    assert not sbx.path_matches_pattern("docsx/y.md", "docs/")


def test_recursive_glob_suffix_match():
    assert sbx.path_matches_pattern("docs/a/b/c.md", "docs/**")
    assert sbx.path_matches_pattern("docs", "docs/**")


def test_fnmatch_glob_match():
    assert sbx.path_matches_pattern("dv_harness/foo_module.py", "dv_harness/*.py")
    assert not sbx.path_matches_pattern("dv_harness/sub/foo.py", "dv_harness/*.py")


def test_normalize_relpath_handles_traversal_and_absolute(tmp_path):
    assert sbx.normalize_relpath(tmp_path, "a/b.py") == "a/b.py"
    assert sbx.normalize_relpath(tmp_path, "../outside.py") is None
    outside_abs = str((tmp_path.parent / "outside.py").resolve())
    assert sbx.normalize_relpath(tmp_path, outside_abs) is None


# --- classify_path / assess_proposed_change ---------------------------------


def test_classify_path_allowed_and_violation(tmp_path):
    decl = sbx.declare_sandbox(tmp_path, ["dv_harness/foo.py"], declared_by="a", reason="r")
    ok = sbx.classify_path(tmp_path, decl, "dv_harness/foo.py")
    assert ok.status == sbx.STATUS_ALLOWED
    assert ok.matched_pattern == "dv_harness/foo.py"

    bad = sbx.classify_path(tmp_path, decl, "dv_harness/bar.py")
    assert bad.status == sbx.STATUS_VIOLATION


def test_classify_path_invalid_path_beats_missing_declaration(tmp_path):
    """An escape attempt is INVALID_PATH regardless of whether a sandbox was
    ever declared -- it is a defect in the path itself, checked first."""
    result = sbx.classify_path(tmp_path, None, "../escape.py")
    assert result.status == sbx.STATUS_INVALID_PATH


def test_negative_control_no_declaration_never_reads_as_allowed(tmp_path):
    """THE required negative control: checking a path against a sandbox_id
    with NO declaration on disk must never fabricate an ALLOWED answer --
    absent evidence must produce an honest, distinctly-named NOT_DECLARED
    status, never a silently-defaulted or guessed pass."""
    assessment = sbx.assess_proposed_change(tmp_path, "SBX-never-declared", ["anything.py"])
    assert assessment.status == sbx.STATUS_NOT_DECLARED
    assert assessment.status != sbx.STATUS_ALLOWED
    assert all(p.status == sbx.STATUS_NOT_DECLARED for p in assessment.checked_paths)


def test_negative_control_assert_raises_on_undeclared_sandbox(tmp_path):
    with pytest.raises(sbx.SandboxViolationError):
        sbx.assert_change_within_sandbox(tmp_path, "SBX-never-declared", ["anything.py"])


def test_assess_proposed_change_requires_at_least_one_path(tmp_path):
    with pytest.raises(sbx.SandboxError):
        sbx.assess_proposed_change(tmp_path, "SBX-any", [])


def test_worst_wins_one_violation_blocks_whole_batch(tmp_path):
    """Rule 3: a single UNMET/BLOCKED condition makes the whole verdict fail
    regardless of how many other conditions are clean -- never averaged."""
    decl = sbx.declare_sandbox(
        tmp_path, ["dv_harness/a.py", "dv_harness/b.py", "dv_harness/c.py"],
        declared_by="a", reason="r",
    )
    proposed = ["dv_harness/a.py", "dv_harness/b.py", "dv_harness/c.py", "dv_harness/gates.py"]
    assessment = sbx.assess_proposed_change(tmp_path, decl.sandbox_id, proposed)
    assert assessment.status == sbx.STATUS_VIOLATION
    statuses = {p.path: p.status for p in assessment.checked_paths}
    assert statuses["dv_harness/gates.py"] == sbx.STATUS_VIOLATION
    assert statuses["dv_harness/a.py"] == sbx.STATUS_ALLOWED
    assert statuses["dv_harness/b.py"] == sbx.STATUS_ALLOWED
    assert statuses["dv_harness/c.py"] == sbx.STATUS_ALLOWED


def test_worst_wins_invalid_path_outranks_plain_violation(tmp_path):
    decl = sbx.declare_sandbox(tmp_path, ["dv_harness/a.py"], declared_by="a", reason="r")
    assessment = sbx.assess_proposed_change(
        tmp_path, decl.sandbox_id, ["dv_harness/a.py", "dv_harness/not_allowed.py", "../escape.py"]
    )
    assert assessment.status == sbx.STATUS_INVALID_PATH


def test_all_paths_allowed_is_clean_pass(tmp_path):
    decl = sbx.declare_sandbox(
        tmp_path, ["dv_harness/foo_module.py", "dv_harness_tests/test_foo_module.py"],
        declared_by="a", reason="r",
    )
    assessment = sbx.assess_proposed_change(
        tmp_path, decl.sandbox_id,
        ["dv_harness/foo_module.py", "dv_harness_tests/test_foo_module.py"],
    )
    assert assessment.status == sbx.STATUS_ALLOWED
    result = sbx.assert_change_within_sandbox(
        tmp_path, decl.sandbox_id,
        ["dv_harness/foo_module.py", "dv_harness_tests/test_foo_module.py"],
    )
    assert result.status == sbx.STATUS_ALLOWED


def test_directory_prefix_sandbox_covers_new_files_under_it(tmp_path):
    decl = sbx.declare_sandbox(tmp_path, ["docs/"], declared_by="a", reason="r")
    assessment = sbx.assess_proposed_change(tmp_path, decl.sandbox_id, ["docs/new_page.md"])
    assert assessment.status == sbx.STATUS_ALLOWED


# --- SandboxViolationError message content ---------------------------------


def test_violation_error_names_offending_paths(tmp_path):
    decl = sbx.declare_sandbox(tmp_path, ["dv_harness/a.py"], declared_by="a", reason="r")
    try:
        sbx.assert_change_within_sandbox(tmp_path, decl.sandbox_id,
                                          ["dv_harness/a.py", "dv_harness/gates.py"])
    except sbx.SandboxViolationError as e:
        assert "dv_harness/gates.py" in str(e)
        assert e.assessment.status == sbx.STATUS_VIOLATION
    else:
        pytest.fail("expected SandboxViolationError")


# --- verify_diff_against_sandbox (real git repo) ----------------------------


def _run(cmd, cwd):
    subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_repo(root: Path):
    _run(["git", "init"], root)
    _run(["git", "config", "user.email", "test@example.com"], root)
    _run(["git", "config", "user.name", "Test"], root)


@pytest.fixture
def git_repo(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "dv_harness").mkdir()
    (tmp_path / "dv_harness" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _run(["git", "add", "-A"], tmp_path)
    _run(["git", "commit", "-m", "base"], tmp_path)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(tmp_path), check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    return tmp_path, base_sha


def test_verify_diff_within_sandbox_passes(git_repo):
    root, base_sha = git_repo
    decl = sbx.declare_sandbox(root, ["dv_harness/a.py"], declared_by="a", reason="r")
    (root / "dv_harness" / "a.py").write_text("x = 2\n", encoding="utf-8")
    # Only stage the real reviewed change -- the sandbox's own bookkeeping
    # under .dv-harness/ is deliberately never part of the diff being checked
    # (the same convention harness_deploy.py's own exclude list applies).
    _run(["git", "add", "dv_harness/a.py"], root)
    _run(["git", "commit", "-m", "change a"], root)

    assessment = sbx.verify_diff_against_sandbox(root, decl.sandbox_id, base_rev=base_sha)
    assert assessment.status == sbx.STATUS_ALLOWED


def test_verify_diff_outside_sandbox_is_violation(git_repo):
    root, base_sha = git_repo
    decl = sbx.declare_sandbox(root, ["dv_harness/a.py"], declared_by="a", reason="r")
    (root / "dv_harness" / "b.py").write_text("y = 1\n", encoding="utf-8")
    _run(["git", "add", "dv_harness/b.py"], root)
    _run(["git", "commit", "-m", "add b (not declared)"], root)

    assessment = sbx.verify_diff_against_sandbox(root, decl.sandbox_id, base_rev=base_sha)
    assert assessment.status == sbx.STATUS_VIOLATION
    assert any(p.path == "dv_harness/b.py" for p in assessment.checked_paths)


def test_verify_diff_no_real_diff_never_reads_as_allowed(tmp_path):
    """Not a real git repo at all -> no real diff -> must never report ALLOWED."""
    decl = sbx.declare_sandbox(tmp_path, ["a.py"], declared_by="a", reason="r")
    assessment = sbx.verify_diff_against_sandbox(tmp_path, decl.sandbox_id, base_rev="HEAD~1")
    assert assessment.status != sbx.STATUS_ALLOWED


def test_verify_diff_requires_base_rev(tmp_path):
    decl = sbx.declare_sandbox(tmp_path, ["a.py"], declared_by="a", reason="r")
    with pytest.raises(sbx.SandboxError):
        sbx.verify_diff_against_sandbox(tmp_path, decl.sandbox_id, base_rev=None)


# --- vocabulary guard --------------------------------------------------------


def test_status_vocabulary_disjoint_from_models_status():
    from dv_harness.models import Status
    verdict_tokens = {m.value for m in Status}
    ours = {sbx.STATUS_ALLOWED, sbx.STATUS_VIOLATION, sbx.STATUS_INVALID_PATH,
            sbx.STATUS_NOT_DECLARED}
    assert not (ours & verdict_tokens)


# --- CLI ---------------------------------------------------------------------


def _cli(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.safety_sandbox", "--root", str(cwd)] + args,
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True,
    )


def test_cli_declare_and_check_real_subprocess(tmp_path):
    result = _cli(
        ["declare", "--paths", "dv_harness/foo.py", "--declared-by", "agent",
         "--reason", "cli test", "--sandbox-id", "SBX-cli-1"],
        tmp_path,
    )
    assert result.returncode == 0, result.stderr

    ok = _cli(["check", "--sandbox-id", "SBX-cli-1", "--paths", "dv_harness/foo.py"], tmp_path)
    assert ok.returncode == 0, ok.stderr
    assert "ALLOWED" in ok.stdout

    bad = _cli(["check", "--sandbox-id", "SBX-cli-1", "--paths", "dv_harness/other.py"], tmp_path)
    assert bad.returncode == 1
    assert "VIOLATION" in bad.stdout


def test_cli_check_undeclared_sandbox_exits_2(tmp_path):
    result = _cli(["check", "--sandbox-id", "SBX-nope", "--paths", "a.py"], tmp_path)
    assert result.returncode == 2
    assert "NOT_DECLARED" in result.stdout


def test_cli_status_and_list(tmp_path):
    _cli(["declare", "--paths", "a.py", "--declared-by", "agent", "--reason", "r",
          "--sandbox-id", "SBX-s1"], tmp_path)
    status = _cli(["status", "--sandbox-id", "SBX-s1"], tmp_path)
    assert status.returncode == 0
    listing = _cli(["list"], tmp_path)
    assert listing.returncode == 0
    assert "SBX-s1" in listing.stdout

    missing = _cli(["status", "--sandbox-id", "SBX-missing"], tmp_path)
    assert missing.returncode == 2
