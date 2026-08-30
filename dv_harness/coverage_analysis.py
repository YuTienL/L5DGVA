"""Coverage hole/trend analysis plumbing (see poster-compliance audit gap:
"Coverage 詳細分析（Hole 分析/Waiver UI/趨勢圖）", 2026-08-29).

This module deliberately does NOT parse any real coverage database (UCIS,
urg HTML, or otherwise) -- per the project's Evidence Truth Rule, this repo
has no such parser, and inventing one here would be fabricated evidence.
Instead, this operates on a coverage summary that has ALREADY been reduced
to plain JSON by whatever real coverage tool the project uses (e.g. a urg
merge report converted to JSON). If no such file exists yet, there is
nothing to run this against -- that is the correct, honest state, not an
error to be papered over.

dashboard.py's GET /api/coverage wires parse_coverage_summary()/
identify_holes()/compute_coverage_trend()/render_coverage_trend_svg() up to
a real coverage-summary file and history file on disk (see that module for
the HTTP surface); append_history_sample() below is the one production write
path a coverage-producing step uses to grow that history file."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .storage import _atomic_replace


class CoverageAnalysisError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def parse_coverage_summary(data: dict) -> dict:
    """Validates and returns a real coverage summary already reduced to plain
    JSON of shape {"categories": [{"name", "percent", "bins_total",
    "bins_hit"}, ...]}. Never silently clamps or fixes malformed input --
    raises CoverageAnalysisError with a specific reason instead."""
    categories = data.get("categories") if isinstance(data, dict) else None
    if not isinstance(categories, list) or not categories:
        raise CoverageAnalysisError(
            "MALFORMED_CATEGORY",
            {"reason": "'categories' must be a non-empty list", "data": data},
        )

    validated = []
    for entry in categories:
        if not isinstance(entry, dict) or not all(
            k in entry for k in ("name", "percent", "bins_total", "bins_hit")
        ):
            raise CoverageAnalysisError(
                "MALFORMED_CATEGORY",
                {"reason": "category missing name/percent/bins_total/bins_hit", "entry": entry},
            )
        name = entry["name"]
        percent = entry["percent"]
        bins_total = entry["bins_total"]
        bins_hit = entry["bins_hit"]

        if bins_hit > bins_total:
            raise CoverageAnalysisError(
                "BINS_HIT_EXCEEDS_TOTAL",
                {"name": name, "bins_hit": bins_hit, "bins_total": bins_total},
            )
        if not (0 <= percent <= 100):
            raise CoverageAnalysisError(
                "PERCENT_OUT_OF_RANGE",
                {"name": name, "percent": percent},
            )

        validated.append({
            "name": name,
            "percent": percent,
            "bins_total": bins_total,
            "bins_hit": bins_hit,
        })

    return {"categories": validated}


def identify_holes(parsed: dict, threshold_percent: float = 100.0) -> list:
    """Every category whose percent < threshold_percent, sorted ascending by
    percent (worst first), each annotated with bins_missing = bins_total -
    bins_hit. An empty list is a legitimate, correct result -- not an error."""
    holes = [
        {**c, "bins_missing": c["bins_total"] - c["bins_hit"]}
        for c in parsed["categories"]
        if c["percent"] < threshold_percent
    ]
    holes.sort(key=lambda c: c["percent"])
    return holes


def compute_coverage_trend(history: list) -> dict:
    """Pure function over [{"timestamp": str|number, "percent": float}, ...]
    in any order. Sorts by timestamp first, then reports delta =
    last_percent - first_percent. FLAT tolerance is |delta| < 0.5 (a small,
    deliberately fixed tolerance so trivial run-to-run noise doesn't get
    reported as an IMPROVING/DECLINING trend). Requires at least 2 entries --
    never guesses a trend from a single data point."""
    if len(history) < 2:
        raise CoverageAnalysisError(
            "INSUFFICIENT_HISTORY",
            {"reason": "at least 2 history entries are required", "count": len(history)},
        )

    ordered = sorted(history, key=lambda h: h["timestamp"])
    first_percent = ordered[0]["percent"]
    last_percent = ordered[-1]["percent"]
    delta = last_percent - first_percent

    if abs(delta) < 0.5:
        trend = "FLAT"
    elif delta > 0:
        trend = "IMPROVING"
    else:
        trend = "DECLINING"

    return {
        "trend": trend,
        "delta": delta,
        "first_percent": first_percent,
        "last_percent": last_percent,
    }


def render_hole_report_text(holes: list) -> str:
    """Plain-text human-readable report, one line per hole. Presentation-only
    -- no new logic beyond formatting."""
    if not holes:
        return "No coverage holes -- 100% across all reported categories."
    lines = [
        f"{h['name']}: {h['percent']}% ({h['bins_missing']}/{h['bins_total']} bins missing)"
        for h in holes
    ]
    return "\n".join(lines)


def render_coverage_trend_svg(history: list, width: int = 480, height: int = 140, margin: int = 24) -> str:
    """Hand-rolled inline SVG line chart over history (no external chart
    library -- this project has no CDN access to load one). Requires >= 2
    points, same floor as compute_coverage_trend() (a single point has no
    line to draw) -- raises CoverageAnalysisError('INSUFFICIENT_HISTORY')
    rather than silently drawing a degenerate chart. Points are plotted in
    timestamp order on a fixed 0-100 percent Y axis (not autoscaled to the
    data's own min/max), so a consistently-high-coverage run doesn't
    visually look like it swings wildly. Presentation-only: one <circle> per
    sample plus one <polyline> joining them, no new coverage logic beyond
    compute_coverage_trend()'s own sort-by-timestamp."""
    if len(history) < 2:
        raise CoverageAnalysisError(
            "INSUFFICIENT_HISTORY",
            {"reason": "at least 2 history entries are required to render a trend chart",
             "count": len(history)},
        )
    ordered = sorted(history, key=lambda h: h["timestamp"])
    n = len(ordered)
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    def x_for(i):
        return margin + (plot_w * i / (n - 1) if n > 1 else 0)

    def y_for(percent):
        pct = max(0.0, min(100.0, percent))
        return margin + plot_h * (1 - pct / 100.0)

    points = [(x_for(i), y_for(h["percent"])) for i, h in enumerate(ordered)]
    polyline_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    circles = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="cov-trend-point">'
        f'<title>{h["timestamp"]}: {h["percent"]}%</title></circle>'
        for (x, y), h in zip(points, ordered)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'class="cov-trend-svg" role="img" aria-label="Coverage trend over {n} samples">'
        f'<polyline points="{polyline_points}" fill="none" stroke="#2457a6" stroke-width="2"/>'
        f"{circles}"
        f"</svg>"
    )


def append_history_sample(history_path, percent: float, timestamp: Any = None) -> list:
    """Appends one {"timestamp","percent"} sample to the JSON array at
    history_path (creating the parent directory and starting a fresh empty
    array if neither exists yet), atomically (via storage._atomic_replace) so
    a concurrent reader (dashboard.py's GET /api/coverage polling loop) never
    observes a torn/partial write. This is the real production write path a
    coverage-producing step (a future COVERAGE_CLOSURE-stage script, or any
    tool that just reduced a fresh urg/UCIS merge report to a percent number)
    calls to grow the history compute_coverage_trend()/render_coverage_trend_svg()
    read -- never hand-edited JSON. An existing file that fails to parse or
    isn't a JSON list is treated as an empty history rather than raising --
    this is an append operation, not a validator; parse_coverage_summary()'s
    strict validation is for the summary file, not this trend log. timestamp
    defaults to time.time() (epoch seconds) when omitted. Returns the full
    updated history list."""
    path = Path(history_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = loaded
        except Exception:
            existing = []
    existing.append({"timestamp": timestamp if timestamp is not None else time.time(), "percent": percent})
    fd, tmp = tempfile.mkstemp(prefix="history.", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        _atomic_replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return existing
