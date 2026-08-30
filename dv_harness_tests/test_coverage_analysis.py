"""Tests for dv_harness/coverage_analysis.py -- coverage hole/trend analysis
plumbing (see poster-compliance audit gap: "Coverage 詳細分析（Hole 分析/
Waiver UI/趨勢圖）", 2026-08-29). Mirrors test_amba_fabric_generator.py's
pure-function-test style."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from dv_harness.coverage_analysis import (
    CoverageAnalysisError,
    parse_coverage_summary,
    identify_holes,
    compute_coverage_trend,
    render_hole_report_text,
    render_coverage_trend_svg,
    append_history_sample,
)

ROOT = Path(__file__).resolve().parents[1]


# ---- parse_coverage_summary --------------------------------------------------

def _valid_summary():
    return {
        "categories": [
            {"name": "line", "percent": 100.0, "bins_total": 500, "bins_hit": 500},
            {"name": "branch", "percent": 87.5, "bins_total": 200, "bins_hit": 175},
            {"name": "fsm_state", "percent": 60.0, "bins_total": 10, "bins_hit": 6},
        ]
    }


def test_parse_coverage_summary_valid():
    parsed = parse_coverage_summary(_valid_summary())
    assert len(parsed["categories"]) == 3
    assert parsed["categories"][1]["name"] == "branch"


def test_parse_coverage_summary_rejects_empty_categories():
    with pytest.raises(CoverageAnalysisError) as exc:
        parse_coverage_summary({"categories": []})
    assert exc.value.reason == "MALFORMED_CATEGORY"


def test_parse_coverage_summary_rejects_missing_field():
    with pytest.raises(CoverageAnalysisError) as exc:
        parse_coverage_summary({"categories": [{"name": "line", "percent": 90.0, "bins_total": 10}]})
    assert exc.value.reason == "MALFORMED_CATEGORY"


def test_parse_coverage_summary_rejects_bins_hit_exceeds_total():
    data = {"categories": [{"name": "line", "percent": 50.0, "bins_total": 10, "bins_hit": 11}]}
    with pytest.raises(CoverageAnalysisError) as exc:
        parse_coverage_summary(data)
    assert exc.value.reason == "BINS_HIT_EXCEEDS_TOTAL"


def test_parse_coverage_summary_rejects_percent_out_of_range():
    data = {"categories": [{"name": "line", "percent": 150.0, "bins_total": 10, "bins_hit": 5}]}
    with pytest.raises(CoverageAnalysisError) as exc:
        parse_coverage_summary(data)
    assert exc.value.reason == "PERCENT_OUT_OF_RANGE"


# ---- identify_holes ----------------------------------------------------------

def test_identify_holes_sorts_worst_first_and_computes_bins_missing():
    parsed = parse_coverage_summary(_valid_summary())
    holes = identify_holes(parsed)
    assert [h["name"] for h in holes] == ["fsm_state", "branch"]
    assert holes[0]["bins_missing"] == 4
    assert holes[1]["bins_missing"] == 25


def test_identify_holes_empty_when_all_full():
    parsed = parse_coverage_summary({
        "categories": [{"name": "line", "percent": 100.0, "bins_total": 10, "bins_hit": 10}]
    })
    assert identify_holes(parsed) == []


# ---- compute_coverage_trend ---------------------------------------------------

def test_compute_coverage_trend_improving():
    history = [
        {"timestamp": 2, "percent": 90.0},
        {"timestamp": 1, "percent": 80.0},
    ]
    trend = compute_coverage_trend(history)
    assert trend["trend"] == "IMPROVING"
    assert trend["delta"] == pytest.approx(10.0)
    assert trend["first_percent"] == 80.0
    assert trend["last_percent"] == 90.0


def test_compute_coverage_trend_declining():
    history = [
        {"timestamp": "2026-08-01", "percent": 90.0},
        {"timestamp": "2026-08-28", "percent": 70.0},
    ]
    trend = compute_coverage_trend(history)
    assert trend["trend"] == "DECLINING"
    assert trend["delta"] == pytest.approx(-20.0)


def test_compute_coverage_trend_flat_within_tolerance():
    history = [
        {"timestamp": 1, "percent": 85.2},
        {"timestamp": 2, "percent": 85.5},
    ]
    trend = compute_coverage_trend(history)
    assert trend["trend"] == "FLAT"


def test_compute_coverage_trend_insufficient_history():
    with pytest.raises(CoverageAnalysisError) as exc:
        compute_coverage_trend([{"timestamp": 1, "percent": 85.0}])
    assert exc.value.reason == "INSUFFICIENT_HISTORY"


# ---- render_hole_report_text ---------------------------------------------------

def test_render_hole_report_text_lists_holes():
    parsed = parse_coverage_summary(_valid_summary())
    holes = identify_holes(parsed)
    text = render_hole_report_text(holes)
    assert "fsm_state" in text
    assert "60.0%" in text
    assert "4/10" in text


def test_render_hole_report_text_no_holes():
    assert render_hole_report_text([]) == "No coverage holes -- 100% across all reported categories."


# ---- render_coverage_trend_svg ------------------------------------------------

def test_render_coverage_trend_svg_structural_point_count():
    history = [
        {"timestamp": 1, "percent": 70.0},
        {"timestamp": 2, "percent": 82.5},
        {"timestamp": 3, "percent": 88.0},
    ]
    svg = render_coverage_trend_svg(history)
    assert svg.count("<circle") == 3
    assert svg.count("<polyline") == 1
    # one polyline with exactly 3 "x,y" point pairs
    import re
    polyline_points = re.search(r'points="([^"]*)"', svg).group(1)
    assert len(polyline_points.split()) == 3


def test_render_coverage_trend_svg_orders_by_timestamp_not_input_order():
    # out-of-order input -- the chart must still plot left-to-right by time
    history = [
        {"timestamp": 2, "percent": 90.0},
        {"timestamp": 1, "percent": 50.0},
    ]
    svg = render_coverage_trend_svg(history)
    import re
    xs = [float(pt.split(",")[0]) for pt in re.search(r'points="([^"]*)"', svg).group(1).split()]
    assert xs[0] < xs[1]  # timestamp=1 (first) plots at a smaller x than timestamp=2


def test_render_coverage_trend_svg_rejects_insufficient_history():
    with pytest.raises(CoverageAnalysisError) as exc:
        render_coverage_trend_svg([{"timestamp": 1, "percent": 50.0}])
    assert exc.value.reason == "INSUFFICIENT_HISTORY"


# ---- append_history_sample -----------------------------------------------------

def test_append_history_sample_creates_file_and_grows_it():
    tmp = Path(tempfile.mkdtemp())
    try:
        history_path = tmp / "coverage" / "history.json"
        assert not history_path.exists()

        result1 = append_history_sample(history_path, 70.0, timestamp=1)
        assert history_path.exists()
        assert result1 == [{"timestamp": 1, "percent": 70.0}]

        result2 = append_history_sample(history_path, 82.5, timestamp=2)
        assert result2 == [
            {"timestamp": 1, "percent": 70.0},
            {"timestamp": 2, "percent": 82.5},
        ]
        on_disk = json.loads(history_path.read_text(encoding="utf-8"))
        assert on_disk == result2

        # the newly-grown history is real >=2-sample input compute_coverage_trend
        # (the production reader) can now consume without INSUFFICIENT_HISTORY.
        trend = compute_coverage_trend(on_disk)
        assert trend["trend"] == "IMPROVING"
    finally:
        shutil.rmtree(tmp)


def test_append_history_sample_defaults_timestamp_when_omitted():
    tmp = Path(tempfile.mkdtemp())
    try:
        history_path = tmp / "history.json"
        before = time.time()
        result = append_history_sample(history_path, 55.0)
        after = time.time()
        assert len(result) == 1
        assert before <= result[0]["timestamp"] <= after
    finally:
        shutil.rmtree(tmp)


# ---- CLI ------------------------------------------------------------------------

def test_cli_analyze_coverage_prints_categories_holes_and_trend():
    tmp = Path(tempfile.mkdtemp())
    try:
        summary_path = tmp / "summary.json"
        summary_path.write_text(json.dumps(_valid_summary()), encoding="utf-8")
        history_path = tmp / "history.json"
        history_path.write_text(json.dumps([
            {"timestamp": 1, "percent": 70.0},
            {"timestamp": 2, "percent": 82.5},
        ]), encoding="utf-8")

        script = ROOT / "tools" / "analyze_coverage.py"
        r = subprocess.run(
            [sys.executable, str(script), "--summary", str(summary_path), "--history", str(history_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip())
        assert len(out["categories"]) == 3
        assert [h["name"] for h in out["holes"]] == ["fsm_state", "branch"]
        assert out["trend"]["trend"] == "IMPROVING"
    finally:
        shutil.rmtree(tmp)


def test_cli_analyze_coverage_without_history_omits_trend():
    tmp = Path(tempfile.mkdtemp())
    try:
        summary_path = tmp / "summary.json"
        summary_path.write_text(json.dumps(_valid_summary()), encoding="utf-8")

        script = ROOT / "tools" / "analyze_coverage.py"
        r = subprocess.run(
            [sys.executable, str(script), "--summary", str(summary_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip())
        assert "trend" not in out
    finally:
        shutil.rmtree(tmp)


def test_cli_analyze_coverage_reports_malformed_input_error():
    tmp = Path(tempfile.mkdtemp())
    try:
        summary_path = tmp / "summary.json"
        summary_path.write_text(json.dumps({"categories": []}), encoding="utf-8")

        script = ROOT / "tools" / "analyze_coverage.py"
        r = subprocess.run(
            [sys.executable, str(script), "--summary", str(summary_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode != 0
        out = json.loads(r.stdout.strip())
        assert out["error"] == "MALFORMED_CATEGORY"
    finally:
        shutil.rmtree(tmp)
