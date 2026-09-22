"""Real tests for dv_harness/root_hygiene_gate.py -- the M1D canonical
root-layout gate (see .work/phase3-dual-repo-consolidation/M1D_CANONICAL_ROOT_NORMALIZATION.md).

No mocking: every test builds a real temp directory tree and checks the
real function against real files on disk.
"""
from pathlib import Path

import pytest

from dv_harness import root_hygiene_gate as rhg


def _touch(root: Path, name: str, content: str = "x") -> None:
    (root / name).write_text(content, encoding="utf-8")


def test_allowlist_is_a_real_nonempty_frozen_set():
    assert len(rhg.PRODUCT_ROOT_ALLOWLIST) > 0
    assert isinstance(rhg.PRODUCT_ROOT_ALLOWLIST, frozenset)


def test_allowlist_contains_the_core_named_files():
    for name in ("README.md", "START_HERE.md", "CLAUDE.md", "pyproject.toml",
                 "justfile", "requirements-harness.txt", ".gitignore", ".claudeignore"):
        assert name in rhg.PRODUCT_ROOT_ALLOWLIST, name


def test_check_root_layout_passes_on_the_real_canonical_root():
    real_root = Path(__file__).resolve().parents[1]
    violations = rhg.check_root_layout(real_root)
    assert violations == [], violations


def test_check_root_layout_flags_a_new_unlisted_root_md_file(tmp_path):
    _touch(tmp_path, "SOME_NEW_DESIGN_DOC.md")
    violations = rhg.check_root_layout(tmp_path)
    assert any(v.path == "SOME_NEW_DESIGN_DOC.md" for v in violations)


def test_check_root_layout_flags_a_new_unlisted_root_ps1_file(tmp_path):
    _touch(tmp_path, "SOME_NEW_LAUNCHER.ps1")
    violations = rhg.check_root_layout(tmp_path)
    assert any(v.path == "SOME_NEW_LAUNCHER.ps1" for v in violations)


def test_check_root_layout_flags_a_new_unlisted_root_json_file(tmp_path):
    _touch(tmp_path, "some_new_config.json", "{}")
    violations = rhg.check_root_layout(tmp_path)
    assert any(v.path == "some_new_config.json" for v in violations)


def test_check_root_layout_flags_tcl_and_sh_too(tmp_path):
    _touch(tmp_path, "build.tcl")
    _touch(tmp_path, "run.sh")
    violations = rhg.check_root_layout(tmp_path)
    flagged = {v.path for v in violations}
    assert "build.tcl" in flagged
    assert "run.sh" in flagged


def test_check_root_layout_does_not_flag_a_nested_file(tmp_path):
    nested = tmp_path / "docs" / "workflow"
    nested.mkdir(parents=True)
    _touch(nested, "NOT_AT_ROOT.md")
    violations = rhg.check_root_layout(tmp_path)
    assert violations == []


def test_check_root_layout_does_not_flag_an_allowlisted_file(tmp_path):
    _touch(tmp_path, "CLAUDE.md")
    violations = rhg.check_root_layout(tmp_path)
    assert violations == []


def test_check_root_layout_ignores_extensions_outside_the_governed_set(tmp_path):
    _touch(tmp_path, "notes.txt")
    violations = rhg.check_root_layout(tmp_path)
    assert violations == []


def test_violation_message_names_a_real_docs_or_scripts_destination(tmp_path):
    _touch(tmp_path, "SOME_NEW_DESIGN_DOC.md")
    violations = rhg.check_root_layout(tmp_path)
    assert "docs/" in violations[0].suggestion


def test_render_report_is_a_string_and_mentions_violation_count(tmp_path):
    _touch(tmp_path, "SOME_NEW_DESIGN_DOC.md")
    violations = rhg.check_root_layout(tmp_path)
    text = rhg.render_report(violations)
    assert isinstance(text, str)
    assert "1" in text
