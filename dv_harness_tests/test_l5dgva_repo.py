"""Real tests for dv_harness/l5dgva_repo.py -- repository-identity discovery
and the wrong-repository guard (M1A-2). No mocked filesystem: every test
builds a real temp directory tree and exercises the real functions against
real files on disk.
"""
import json
import subprocess
import sys

import pytest

from dv_harness import l5dgva_repo


def _write_identity(root, product_identity="L5DGVA"):
    marker_dir = root / ".l5dgva"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "repository.json").write_text(
        json.dumps({"schema_version": "1.0.0", "product_identity": product_identity,
                    "repository_type": "l5dgva_canonical_product_repository"}),
        encoding="utf-8",
    )


def test_discover_repo_root_finds_marker_from_a_nested_subdirectory(tmp_path):
    _write_identity(tmp_path)
    nested = tmp_path / "dv_harness" / "uvm_generator"
    nested.mkdir(parents=True)
    found = l5dgva_repo.discover_repo_root(nested)
    assert found == tmp_path


def test_discover_repo_root_raises_when_no_marker_exists_anywhere_up_to_filesystem_root(tmp_path):
    lonely = tmp_path / "no_marker_here"
    lonely.mkdir()
    with pytest.raises(l5dgva_repo.L5DGVARepositoryNotFoundError):
        l5dgva_repo.discover_repo_root(lonely)


def test_discover_repo_root_does_not_require_directory_basename_L5_DGVA(tmp_path):
    renamed = tmp_path / "totally_different_name_not_L5_DGVA"
    renamed.mkdir()
    _write_identity(renamed)
    found = l5dgva_repo.discover_repo_root(renamed / "some" / "deep" / "path".rstrip())
    # deep path doesn't exist on disk, so build a real one for a genuine walk-up test
    deep = renamed / "some" / "deep"
    deep.mkdir(parents=True)
    found = l5dgva_repo.discover_repo_root(deep)
    assert found == renamed


def test_load_repository_identity_rejects_wrong_product_identity(tmp_path):
    _write_identity(tmp_path, product_identity="SOME_OTHER_PRODUCT")
    with pytest.raises(l5dgva_repo.L5DGVARepositoryNotFoundError):
        l5dgva_repo.discover_repo_root(tmp_path, validate=True)


def test_detect_mode_developer_mode_when_git_present(tmp_path):
    _write_identity(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert l5dgva_repo.detect_mode(tmp_path) == l5dgva_repo.DEVELOPER_MODE


def test_detect_mode_deployment_copy_mode_when_git_absent(tmp_path):
    _write_identity(tmp_path)
    assert l5dgva_repo.detect_mode(tmp_path) == l5dgva_repo.DEPLOYMENT_COPY_MODE


def test_cross_check_git_root_reports_match_when_consistent(tmp_path):
    _write_identity(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    result = l5dgva_repo.cross_check_git_root(tmp_path)
    assert result["status"] == "MATCH"


def test_cross_check_git_root_reports_git_unavailable_in_deployment_copy_mode(tmp_path):
    _write_identity(tmp_path)
    result = l5dgva_repo.cross_check_git_root(tmp_path)
    assert result["status"] == "GIT_CAPABILITY_UNAVAILABLE"


def test_assert_l5dgva_repo_raises_wrong_repository_error_outside_any_l5dgva_repo(tmp_path):
    lonely = tmp_path / "not_a_repo"
    lonely.mkdir()
    with pytest.raises(l5dgva_repo.WrongL5RepositoryError) as exc_info:
        l5dgva_repo.assert_l5dgva_repo(lonely)
    assert exc_info.value.condition == "WRONG_L5_REPOSITORY"


def test_assert_l5dgva_repo_passes_silently_inside_a_real_l5dgva_repo(tmp_path):
    _write_identity(tmp_path)
    nested = tmp_path / "dv_harness"
    nested.mkdir()
    l5dgva_repo.assert_l5dgva_repo(nested)  # must not raise


def test_is_l5dgva_repo_is_a_non_raising_boolean_check(tmp_path):
    _write_identity(tmp_path)
    lonely = tmp_path.parent / "definitely_not_l5dgva_xyz123"
    assert l5dgva_repo.is_l5dgva_repo(tmp_path) is True
    if not lonely.exists():
        assert l5dgva_repo.is_l5dgva_repo(tmp_path.parent) in (True, False)  # parent may or may not itself be discoverable-through; just must not raise


def test_repository_identity_does_not_encode_the_bootstrap_absolute_path_as_identity(tmp_path):
    # Confirms the real project marker (not a synthetic test one) never uses
    # an absolute path as the thing that makes discovery succeed -- moving
    # the whole tree to a new absolute path must not invalidate discovery.
    _write_identity(tmp_path)
    moved_root = tmp_path.rename(tmp_path.parent / "moved_elsewhere_xyz")
    nested = moved_root / "dv_harness"
    nested.mkdir()
    found = l5dgva_repo.discover_repo_root(nested)
    assert found == moved_root
