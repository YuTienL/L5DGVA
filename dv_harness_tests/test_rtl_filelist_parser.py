"""Tests for dv_harness/rtl_filelist_parser.py -- expanding a real VCS-style
`.f` RTL compile filelist into an ordered file/incdir/define/library table.

NEW test suite (M5 Capability Pool Closure, CAP-POOL-012). No Parent test
file exists for this module anywhere (it has no committed source at all --
see the module's own PROVENANCE note) -- every test here is derived from
the module's own documented behavior (its "REAL-WORLD `.f` SYNTAX
SUPPORTED" and "BOUNDED, HONESTLY" docstring sections), never copied from
an assumption.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dv_harness import rtl_filelist_parser as rfp

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# root-path availability
# ---------------------------------------------------------------------------

def test_missing_root_file_is_not_available(tmp_path):
    result = rfp.parse_filelist(tmp_path / "does_not_exist.f")
    assert result.status == rfp.STATUS_NOT_AVAILABLE
    assert "not found" in result.reason


def test_root_path_that_is_a_directory_is_not_available(tmp_path):
    d = tmp_path / "a_directory"
    d.mkdir()
    result = rfp.parse_filelist(d)
    assert result.status == rfp.STATUS_NOT_AVAILABLE
    assert "not a regular file" in result.reason


# ---------------------------------------------------------------------------
# bare file tokens, comments, ordering, dedup
# ---------------------------------------------------------------------------

def test_bare_tokens_are_file_paths_in_order(tmp_path):
    _write(tmp_path / "a.sv", "")
    _write(tmp_path / "b.sv", "")
    fl = _write(tmp_path / "top.f", "a.sv\nb.sv\n")
    result = rfp.parse_filelist(fl)
    assert result.status == rfp.STATUS_OK
    assert result.files == [str(tmp_path / "a.sv"), str(tmp_path / "b.sv")]


def test_comments_are_stripped_both_styles(tmp_path):
    _write(tmp_path / "a.sv", "")
    fl = _write(tmp_path / "top.f", "// a full-line comment\na.sv // trailing comment\n# also a comment\n")
    result = rfp.parse_filelist(fl)
    assert result.files == [str(tmp_path / "a.sv")]


def test_duplicate_file_tokens_are_deduplicated_preserving_first_order(tmp_path):
    _write(tmp_path / "a.sv", "")
    fl = _write(tmp_path / "top.f", "a.sv\na.sv\n")
    result = rfp.parse_filelist(fl)
    assert result.files == [str(tmp_path / "a.sv")]


def test_blank_lines_are_skipped(tmp_path):
    _write(tmp_path / "a.sv", "")
    fl = _write(tmp_path / "top.f", "\n\na.sv\n\n")
    result = rfp.parse_filelist(fl)
    assert result.files == [str(tmp_path / "a.sv")]


# ---------------------------------------------------------------------------
# +incdir+
# ---------------------------------------------------------------------------

def test_incdir_single_directory(tmp_path):
    (tmp_path / "inc").mkdir()
    fl = _write(tmp_path / "top.f", "+incdir+inc\n")
    result = rfp.parse_filelist(fl)
    assert result.incdirs == [str(tmp_path / "inc")]


def test_incdir_multiple_directories_plus_joined(tmp_path):
    (tmp_path / "inc1").mkdir()
    (tmp_path / "inc2").mkdir()
    fl = _write(tmp_path / "top.f", "+incdir+inc1+inc2\n")
    result = rfp.parse_filelist(fl)
    assert result.incdirs == [str(tmp_path / "inc1"), str(tmp_path / "inc2")]


def test_incdir_missing_directory_is_recorded_in_missing_paths(tmp_path):
    fl = _write(tmp_path / "top.f", "+incdir+does_not_exist\n")
    result = rfp.parse_filelist(fl)
    assert result.incdirs == [str(tmp_path / "does_not_exist")]
    assert any(m["kind"] == "incdir" for m in result.missing_paths)


# ---------------------------------------------------------------------------
# `define
# ---------------------------------------------------------------------------

def test_define_with_value(tmp_path):
    fl = _write(tmp_path / "top.f", "`define WIDTH 32\n")
    result = rfp.parse_filelist(fl)
    assert result.defines == {"WIDTH": "32"}


def test_define_without_value_is_none(tmp_path):
    fl = _write(tmp_path / "top.f", "`define ENABLE_FEATURE\n")
    result = rfp.parse_filelist(fl)
    assert result.defines == {"ENABLE_FEATURE": None}


def test_define_is_never_treated_as_a_file_or_flag(tmp_path):
    fl = _write(tmp_path / "top.f", "`define FOO bar\n")
    result = rfp.parse_filelist(fl)
    assert result.files == []
    assert result.ignored_flags == []


# ---------------------------------------------------------------------------
# -v / -y library file/dir
# ---------------------------------------------------------------------------

def test_dash_v_library_file_kept_separate_from_files(tmp_path):
    _write(tmp_path / "lib.v", "")
    fl = _write(tmp_path / "top.f", "-v lib.v\n")
    result = rfp.parse_filelist(fl)
    assert result.library_files == [str(tmp_path / "lib.v")]
    assert result.files == []


def test_dash_y_library_dir_kept_separate_from_incdirs(tmp_path):
    (tmp_path / "libdir").mkdir()
    fl = _write(tmp_path / "top.f", "-y libdir\n")
    result = rfp.parse_filelist(fl)
    assert result.library_dirs == [str(tmp_path / "libdir")]
    assert result.incdirs == []


def test_dash_v_with_no_argument_warns_and_does_not_crash(tmp_path):
    fl = _write(tmp_path / "top.f", "-v\n")
    result = rfp.parse_filelist(fl)
    assert any("no file argument" in w for w in result.warnings)


def test_dash_y_with_no_argument_warns_and_does_not_crash(tmp_path):
    fl = _write(tmp_path / "top.f", "-y\n")
    result = rfp.parse_filelist(fl)
    assert any("no dir argument" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# unrecognized flags
# ---------------------------------------------------------------------------

def test_unrecognized_flag_is_recorded_never_dropped_or_treated_as_a_file(tmp_path):
    fl = _write(tmp_path / "top.f", "-sverilog -full64\n")
    result = rfp.parse_filelist(fl)
    assert result.files == []
    flags = [f["flag"] for f in result.ignored_flags]
    assert flags == ["-sverilog", "-full64"]


# ---------------------------------------------------------------------------
# -f / -F nested filelists
# ---------------------------------------------------------------------------

def test_nested_filelist_is_expanded_recursively(tmp_path):
    _write(tmp_path / "a.sv", "")
    _write(tmp_path / "b.sv", "")
    nested = _write(tmp_path / "nested.f", "b.sv\n")
    top = _write(tmp_path / "top.f", f"a.sv\n-f nested.f\n")
    result = rfp.parse_filelist(top)
    assert result.files == [str(tmp_path / "a.sv"), str(tmp_path / "b.sv")]
    assert result.nested_filelists[0]["directive"] == "-f"
    assert result.nested_filelists[0]["path"] == str(tmp_path / "nested.f")


def test_dash_capital_f_is_also_a_nested_filelist_directive(tmp_path):
    _write(tmp_path / "b.sv", "")
    nested = _write(tmp_path / "nested.f", "b.sv\n")
    top = _write(tmp_path / "top.f", "-F nested.f\n")
    result = rfp.parse_filelist(top)
    assert result.files == [str(tmp_path / "b.sv")]
    assert result.nested_filelists[0]["directive"] == "-F"


def test_missing_nested_filelist_is_recorded_and_does_not_crash(tmp_path):
    top = _write(tmp_path / "top.f", "-f does_not_exist.f\n")
    result = rfp.parse_filelist(top)
    assert any(m["kind"] == "filelist" for m in result.missing_paths)
    assert any("does not exist" in w for w in result.warnings)


def test_dash_f_with_no_argument_warns_and_does_not_crash(tmp_path):
    fl = _write(tmp_path / "top.f", "-f\n")
    result = rfp.parse_filelist(fl)
    assert any("no path argument" in w for w in result.warnings)


def test_cyclic_include_is_detected_and_does_not_infinite_loop(tmp_path):
    a = tmp_path / "a.f"
    b = tmp_path / "b.f"
    _write(a, "-f b.f\n")
    _write(b, "-f a.f\n")
    result = rfp.parse_filelist(a)
    assert any("cyclic" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# missing source files
# ---------------------------------------------------------------------------

def test_missing_referenced_source_file_is_recorded_never_dropped_or_fabricated(tmp_path):
    fl = _write(tmp_path / "top.f", "does_not_exist.sv\n")
    result = rfp.parse_filelist(fl)
    # Honest non-guess: the token is still reported as a file (never silently
    # dropped from the ordered list), but flagged missing.
    assert result.files == [str(tmp_path / "does_not_exist.sv")]
    assert any(m["kind"] == "file" for m in result.missing_paths)
    assert result.status == rfp.STATUS_PARTIAL


# ---------------------------------------------------------------------------
# status: OK vs PARTIAL vs zero-files
# ---------------------------------------------------------------------------

def test_clean_filelist_with_all_real_files_is_status_ok(tmp_path):
    _write(tmp_path / "a.sv", "")
    fl = _write(tmp_path / "top.f", "a.sv\n")
    result = rfp.parse_filelist(fl)
    assert result.status == rfp.STATUS_OK
    assert result.reason is None


def test_zero_source_files_with_no_problems_is_status_ok(tmp_path):
    (tmp_path / "inc").mkdir()
    fl = _write(tmp_path / "top.f", "+incdir+inc\n")
    result = rfp.parse_filelist(fl)
    assert result.files == []
    assert result.status == rfp.STATUS_OK
    assert "zero source files" in result.reason


def test_zero_source_files_with_a_missing_incdir_is_partial(tmp_path):
    fl = _write(tmp_path / "top.f", "+incdir+does_not_exist\n")
    result = rfp.parse_filelist(fl)
    assert result.files == []
    assert result.status == rfp.STATUS_PARTIAL


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def test_cli_entry_point_reports_files_and_exits_0(tmp_path):
    _write(tmp_path / "a.sv", "")
    fl = _write(tmp_path / "top.f", "a.sv\n")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.rtl_filelist_parser", str(fl), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == rfp.STATUS_OK
    assert payload["files"] == [str(tmp_path / "a.sv")]


def test_cli_entry_point_exits_2_on_missing_root_file(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.rtl_filelist_parser", str(tmp_path / "nope.f")],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2
    assert "NOT_AVAILABLE" in proc.stdout
