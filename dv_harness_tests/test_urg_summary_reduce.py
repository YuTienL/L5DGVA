"""Tests for tools/coverage/urg_summary_reduce.py (2026-09-01), implementing
.work/coverage-generator-design-report.md's Part 2 -- BUILD SKELETON ONLY.

This script's real urg-report parsing step is deliberately NOT implemented
(see parse_urg_report()'s own NotImplementedError and this module's
docstring): the design report explicitly forbids guessing urg's report
schema without a real sample/version-pinned evidence (Open Questions 1-2).
These tests therefore verify everything the design report DOES ask to be
built now:

  - CLI parsing (--urg-report/--out, both required)
  - the self-validation step (build_summary() calls
    dv_harness.coverage_analysis.parse_coverage_summary() before returning
    -- proven here via monkeypatching parse_urg_report() to return both a
    well-formed and a malformed category list, since the real parse itself
    is blocked)
  - atomic write (write_summary_atomic() produces valid, fully-written JSON
    at the destination path, creating parent dirs as needed)
  - the 5 real code-coverage metric name constants the project's own
    Makefile CM_OPTS already fixes, plus the "functional" placeholder
  - the NotImplementedError itself: calling parse_urg_report()/
    build_summary()/main() with today's code raises/exits exactly as
    documented, never silently fabricating a plausible-looking result
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "coverage" / "urg_summary_reduce.py"

_spec = importlib.util.spec_from_file_location("urg_summary_reduce", MODULE_PATH)
usr = importlib.util.module_from_spec(_spec)
sys.modules["urg_summary_reduce"] = usr
_spec.loader.exec_module(usr)

from dv_harness.coverage_analysis import CoverageAnalysisError  # noqa: E402


# ---------------------------------------------------------------------------
# constants: the real, already-committed metric set (Makefile CM_OPTS)
# ---------------------------------------------------------------------------

def test_code_coverage_metrics_match_makefile_cm_opts():
    assert usr.CODE_COVERAGE_METRICS == ("line", "cond", "fsm", "tgl", "branch")


def test_functional_category_placeholder_present():
    assert usr.FUNCTIONAL_COVERAGE_CATEGORY == "functional"
    assert usr.ALL_CATEGORY_NAMES == ("line", "cond", "fsm", "tgl", "branch", "functional")


# ---------------------------------------------------------------------------
# the blocking NotImplementedError -- deliberate, documented, never guessed
# ---------------------------------------------------------------------------

def test_parse_urg_report_raises_not_implemented():
    with pytest.raises(NotImplementedError) as exc_info:
        usr.parse_urg_report(pathlib.Path("/nonexistent/urgReport"))
    assert "BLOCKED" in str(exc_info.value)
    assert "coverage-generator-design-report.md" in str(exc_info.value)


def test_build_summary_propagates_not_implemented():
    with pytest.raises(NotImplementedError):
        usr.build_summary(pathlib.Path("/nonexistent/urgReport"))


def test_main_exits_2_on_not_implemented(capsys):
    rc = usr.main(["--urg-report", "/nonexistent/urgReport", "--out", "/tmp/does_not_matter.json"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"] == "NOT_IMPLEMENTED"
    assert "BLOCKED" in out["detail"]


# ---------------------------------------------------------------------------
# CLI parsing: both flags required
# ---------------------------------------------------------------------------

def test_missing_urg_report_flag_errors():
    with pytest.raises(SystemExit):
        usr.main(["--out", "/tmp/x.json"])


def test_missing_out_flag_errors():
    with pytest.raises(SystemExit):
        usr.main(["--urg-report", "/tmp/urgReport"])


# ---------------------------------------------------------------------------
# self-validation: build_summary() must call parse_coverage_summary()
# before returning -- proven by monkeypatching the (currently blocked)
# parse_urg_report() step, since the real parse cannot be exercised yet.
# ---------------------------------------------------------------------------

def test_build_summary_self_validates_well_formed_categories(monkeypatch):
    monkeypatch.setattr(usr, "parse_urg_report", lambda d: [
        {"name": "line", "percent": 87.5, "bins_total": 400, "bins_hit": 350},
        {"name": "functional", "percent": 60.0, "bins_total": 20, "bins_hit": 12},
    ])
    summary = usr.build_summary(pathlib.Path("/whatever"))
    assert summary == {"categories": [
        {"name": "line", "percent": 87.5, "bins_total": 400, "bins_hit": 350},
        {"name": "functional", "percent": 60.0, "bins_total": 20, "bins_hit": 12},
    ]}


def test_build_summary_self_validation_rejects_malformed_categories(monkeypatch):
    """A future real parse_urg_report() implementation that produced
    bins_hit > bins_total (or any other parse_coverage_summary()-rejected
    shape) must be caught HERE, before ever reaching write_summary_atomic()
    -- this script must never write a summary.json its own downstream
    reader would reject."""
    monkeypatch.setattr(usr, "parse_urg_report", lambda d: [
        {"name": "line", "percent": 87.5, "bins_total": 10, "bins_hit": 99},
    ])
    with pytest.raises(CoverageAnalysisError) as exc_info:
        usr.build_summary(pathlib.Path("/whatever"))
    assert exc_info.value.reason == "BINS_HIT_EXCEEDS_TOTAL"


def test_main_exits_1_and_reports_reason_on_self_validation_failure(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(usr, "parse_urg_report", lambda d: [
        {"name": "line", "percent": 150.0, "bins_total": 10, "bins_hit": 1},
    ])
    out_path = tmp_path / "summary.json"
    rc = usr.main(["--urg-report", str(tmp_path), "--out", str(out_path)])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "PERCENT_OUT_OF_RANGE"
    assert not out_path.exists()


# ---------------------------------------------------------------------------
# atomic write
# ---------------------------------------------------------------------------

def test_write_summary_atomic_creates_parent_dir_and_writes_valid_json(tmp_path):
    out_path = tmp_path / "nested" / "dir" / "summary.json"
    summary = {"categories": [
        {"name": "line", "percent": 100.0, "bins_total": 5, "bins_hit": 5},
    ]}
    usr.write_summary_atomic(summary, out_path)
    assert out_path.exists()
    assert json.loads(out_path.read_text(encoding="utf-8")) == summary


def test_write_summary_atomic_overwrites_existing_file(tmp_path):
    out_path = tmp_path / "summary.json"
    out_path.write_text('{"stale": true}', encoding="utf-8")
    summary = {"categories": [
        {"name": "functional", "percent": 42.0, "bins_total": 100, "bins_hit": 42},
    ]}
    usr.write_summary_atomic(summary, out_path)
    assert json.loads(out_path.read_text(encoding="utf-8")) == summary


def test_main_end_to_end_writes_summary_when_parse_succeeds(monkeypatch, capsys, tmp_path):
    """End-to-end main() happy path with parse_urg_report() monkeypatched --
    the one piece this script cannot exercise for real (see module
    docstring) -- proving CLI parsing, self-validation, and atomic write all
    wire together correctly."""
    monkeypatch.setattr(usr, "parse_urg_report", lambda d: [
        {"name": "line", "percent": 90.0, "bins_total": 200, "bins_hit": 180},
        {"name": "cond", "percent": 80.0, "bins_total": 50, "bins_hit": 40},
        {"name": "fsm", "percent": 100.0, "bins_total": 10, "bins_hit": 10},
        {"name": "tgl", "percent": 75.0, "bins_total": 300, "bins_hit": 225},
        {"name": "branch", "percent": 85.0, "bins_total": 60, "bins_hit": 51},
        {"name": "functional", "percent": 60.0, "bins_total": 20, "bins_hit": 12},
    ])
    out_path = tmp_path / "summary.json"
    rc = usr.main(["--urg-report", str(tmp_path / "urgReport"), "--out", str(out_path)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["wrote"] == str(out_path)
    assert payload["categories"] == 6
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert {c["name"] for c in written["categories"]} == set(usr.ALL_CATEGORY_NAMES)
