"""GET /api/amba-performance-trend -- the AMBA Performance Trend View dashboard
card (dashboard_amba_performance_trend_view).

Before this, dashboard.py had no card surfacing
amba_performance_classification.py's real compute_regression_delta()/
detect_anomaly() results across a project's own RECORDED SEQUENCE of periods.
This module this file tests never computes a regression-delta verdict or an
anomaly status itself; it is a thin JSON-file front door onto
`amba_performance_classification.compute_regression_delta()` and
`detect_anomaly()`, and every test below cross-checks the card's numbers
against those real functions' own documented arithmetic and status rules --
most importantly the negative control that a metric with no recorded history
(or only one recorded period) reports the real, honest NOT_AVAILABLE /
INCONCLUSIVE trend status rather than a fabricated trend line.

The real dashboard server is started for real on a free local port and
driven over real HTTP, reusing test_dashboard_interactive.py's own harness
helpers rather than standing up a second one -- the same cross-test import
convention test_dashboard_amba_performance_center.py already uses.
"""
from __future__ import annotations

import json
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
    _write_json,
)


def _write_trend(tmp: Path, doc: dict) -> Path:
    from dv_harness.dashboard import _default_amba_performance_trend_path

    path = _default_amba_performance_trend_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, doc)
    return path


def test_amba_performance_trend_reports_honest_empty_state_when_no_history_exists():
    """No performance-trend history has been declared for this project at
    all: the endpoint must say so and name the path it looked at, never
    invent a metric -- the same honest-empty-state contract the other AMBA
    cards already hold to."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/amba-performance-trend")
        assert status == 200
        assert data["available"] is False
        assert data["metrics"] == []
        assert data["rejected"] == []
        assert data["error"] is None
        assert data["trend_path"].endswith("performance_trend.json")
        assert not Path(data["trend_path"]).exists()
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_trend_metric_with_zero_periods_is_honestly_not_available():
    """A metric declared with an empty periods list must never be reported as
    having a trend -- NOT_AVAILABLE, with a real reason, never a synthesized
    trend line from nothing."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_trend(tmp, {"metrics": {"bandwidth_M0": {"periods": []}}})

        status, data = _get(base, "/api/amba-performance-trend")
        assert status == 200
        assert data["available"] is True
        assert len(data["metrics"]) == 1
        m = data["metrics"][0]
        assert m["metric_name"] == "bandwidth_M0"
        assert m["periods_recorded"] == 0
        assert m["trend_status"] == "NOT_AVAILABLE"
        assert "no history exists" in m["trend_reason"] or "no recorded periods" in m["trend_reason"]
        assert m["deltas"] == []
        assert m["anomalies"] == []
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_trend_metric_with_one_period_is_honestly_inconclusive():
    """A metric with exactly ONE recorded period cannot produce a real
    compute_regression_delta() comparison -- the endpoint must report
    INCONCLUSIVE, never fabricate a two-period comparison out of one
    sample. Anomaly detection for that single period still runs normally,
    since detect_anomaly() needs only one observed value."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_trend(tmp, {
            "metrics": {
                "latency_p99": {
                    "periods": [
                        {"period_id": "2026-08-01", "value": 120.0,
                         "baseline_min": 100.0, "baseline_max": 150.0},
                    ],
                },
            },
        })

        status, data = _get(base, "/api/amba-performance-trend")
        assert status == 200
        m = data["metrics"][0]
        assert m["periods_recorded"] == 1
        assert m["trend_status"] == "INCONCLUSIVE"
        assert "two real measured periods" in m["trend_reason"]
        assert m["deltas"] == []
        # detect_anomaly() only needs one observed value + a baseline range,
        # so this DOES run and produce a real result even with one period.
        assert len(m["anomalies"]) == 1
        a = m["anomalies"][0]
        assert a["period_id"] == "2026-08-01"
        assert a["status"] == "NO_ANOMALY"
        assert a["observed_value"] == pytest.approx(120.0)
        assert a["baseline_description"] == "range[100.0, 150.0]"
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_trend_computes_real_regression_delta_across_two_periods():
    """Two recorded periods must be compared through the REAL
    compute_regression_delta(): a real percent-change and a real IMPROVED/
    REGRESSED/UNCHANGED verdict, matching that function's own documented
    arithmetic exactly."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_trend(tmp, {
            "metrics": {
                "latency_us": {
                    "lower_is_better": True,
                    "periods": [
                        {"period_id": "week1", "value": 100.0, "window": "nightly", "unit": "us"},
                        {"period_id": "week2", "value": 150.0, "window": "nightly", "unit": "us"},
                    ],
                },
            },
        })

        status, data = _get(base, "/api/amba-performance-trend")
        assert status == 200
        m = data["metrics"][0]
        assert m["periods_recorded"] == 2
        assert m["trend_status"] == "AVAILABLE"
        assert m["trend_reason"] is None
        assert len(m["deltas"]) == 1

        d = m["deltas"][0]
        assert d["metric_name"] == "latency_us"
        assert d["baseline_period_id"] == "week1"
        assert d["current_period_id"] == "week2"
        assert d["baseline_value"] == pytest.approx(100.0)
        assert d["current_value"] == pytest.approx(150.0)
        assert d["percent_change"] == pytest.approx(50.0)
        # lower_is_better=True and the value INCREASED -> REGRESSED, exactly
        # compute_regression_delta()'s own documented rule.
        assert d["verdict"] == "REGRESSED"
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_trend_computes_a_delta_per_consecutive_pair_across_three_periods():
    """Three recorded periods produce exactly TWO consecutive-pair deltas
    (period1->period2, period2->period3) -- never a first-to-last shortcut
    that skips the middle recorded period."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_trend(tmp, {
            "metrics": {
                "bandwidth_mbps": {
                    "lower_is_better": False,
                    "periods": [
                        {"period_id": "p1", "value": 800.0},
                        {"period_id": "p2", "value": 900.0},
                        {"period_id": "p3", "value": 850.0},
                    ],
                },
            },
        })

        status, data = _get(base, "/api/amba-performance-trend")
        assert status == 200
        m = data["metrics"][0]
        assert m["periods_recorded"] == 3
        assert m["trend_status"] == "AVAILABLE"
        assert len(m["deltas"]) == 2

        d1, d2 = m["deltas"]
        assert (d1["baseline_period_id"], d1["current_period_id"]) == ("p1", "p2")
        assert d1["verdict"] == "IMPROVED"  # higher-is-better, value rose
        assert (d2["baseline_period_id"], d2["current_period_id"]) == ("p2", "p3")
        assert d2["verdict"] == "REGRESSED"  # higher-is-better, value fell
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_trend_reports_real_inconclusive_delta_for_mismatched_units():
    """A real regression delta between two periods declaring DIFFERENT units
    must come back INCONCLUSIVE -- never a fabricated percentage computed
    across incomparable measurements. This is compute_regression_delta()'s
    own real rule, surfaced verbatim."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_trend(tmp, {
            "metrics": {
                "throughput": {
                    "periods": [
                        {"period_id": "a", "value": 10.0, "unit": "GBps"},
                        {"period_id": "b", "value": 12.0, "unit": "MBps"},
                    ],
                },
            },
        })

        status, data = _get(base, "/api/amba-performance-trend")
        assert status == 200
        d = data["metrics"][0]["deltas"][0]
        assert d["verdict"] == "INCONCLUSIVE"
        assert d["percent_change"] is None
        assert "different units" in d["reason"]
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_trend_detects_a_real_anomaly_against_a_declared_baseline():
    """A period whose value falls outside its own declared baseline range
    must come back ANOMALY_DETECTED, matching detect_anomaly()'s own real
    arithmetic, alongside a genuinely in-range sibling period reporting
    NO_ANOMALY on the same metric."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_trend(tmp, {
            "metrics": {
                "latency_us": {
                    "periods": [
                        {"period_id": "normal", "value": 100.0,
                         "baseline_min": 90.0, "baseline_max": 110.0},
                        {"period_id": "spike", "value": 500.0,
                         "baseline_min": 90.0, "baseline_max": 110.0},
                    ],
                },
            },
        })

        status, data = _get(base, "/api/amba-performance-trend")
        assert status == 200
        anomalies = {a["period_id"]: a for a in data["metrics"][0]["anomalies"]}
        assert anomalies["normal"]["status"] == "NO_ANOMALY"
        assert anomalies["spike"]["status"] == "ANOMALY_DETECTED"
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_trend_absent_baseline_is_honest_not_applicable_never_fabricated():
    """The negative control this card exists to prove for anomaly detection:
    a period with a real observed value but NO declared baseline must report
    NOT_APPLICABLE -- never a fabricated ANOMALY_DETECTED/NO_ANOMALY verdict
    computed against an invented baseline."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_trend(tmp, {
            "metrics": {
                "utilization": {
                    "periods": [
                        {"period_id": "p1", "value": 0.8},
                        {"period_id": "p2", "value": 0.9},
                    ],
                },
            },
        })

        status, data = _get(base, "/api/amba-performance-trend")
        assert status == 200
        for a in data["metrics"][0]["anomalies"]:
            assert a["status"] == "NOT_APPLICABLE"
            assert "never fabricates" in a["reason"] or "never fabricated" in a["reason"]
        # The regression delta between the two periods still computes
        # normally -- absence of a baseline never taints the delta.
        assert data["metrics"][0]["deltas"][0]["verdict"] in (
            "IMPROVED", "REGRESSED", "UNCHANGED", "INCONCLUSIVE")
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_trend_reports_rejected_declarations_not_fabricated():
    """Real refusals, each surfaced under `rejected` rather than silently
    dropped or turned into a fabricated metric: a non-object metric entry, a
    non-list periods field, and a period entry missing its period_id."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_trend(tmp, {
            "metrics": {
                "BADSHAPE": "not-an-object",
                "BADPERIODS": {"periods": "not-a-list"},
                "MISSINGID": {"periods": [{"value": 1.0}]},
            },
        })

        status, data = _get(base, "/api/amba-performance-trend")
        assert status == 200
        # BADSHAPE/BADPERIODS are rejected outright -- no metric entry at
        # all. MISSINGID's own period is individually rejected, but the
        # metric itself still honestly reports as NOT_AVAILABLE with zero
        # recorded periods, rather than being silently dropped.
        assert [m["metric_name"] for m in data["metrics"]] == ["MISSINGID"]
        assert data["metrics"][0]["periods_recorded"] == 0
        assert data["metrics"][0]["trend_status"] == "NOT_AVAILABLE"
        assert any(r["metric"] == "BADSHAPE" and r["reason"] == "METRIC_ENTRY_NOT_AN_OBJECT"
                   for r in data["rejected"])
        assert any(r["metric"] == "BADPERIODS" and r["reason"] == "PERIODS_NOT_A_LIST"
                   for r in data["rejected"])
        assert any(r["metric"] == "MISSINGID" and "MISSING_PERIOD_ID" in r["reason"]
                   for r in data["rejected"])
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_trend_reports_malformed_trend_file_rather_than_a_500():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.dashboard import _default_amba_performance_trend_path
        p = _default_amba_performance_trend_path(tmp)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json", encoding="utf-8")

        status, data = _get(base, "/api/amba-performance-trend")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_TREND_FILE"
        assert data["metrics"] == [] and data["rejected"] == []
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_trend_path_is_overridable_by_query_param():
    """Mirrors GET /api/amba-performance's ?samples= override: a project
    whose trend declarations live elsewhere points at it, rather than this
    module guessing a second location."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        elsewhere = tmp / "amba_out" / "trend.json"
        elsewhere.parent.mkdir(parents=True, exist_ok=True)
        _write_json(elsewhere, {
            "metrics": {"m": {"periods": [
                {"period_id": "a", "value": 1.0}, {"period_id": "b", "value": 2.0}]}},
        })

        status, data = _get(base, "/api/amba-performance-trend")
        assert data["available"] is False  # default location still honestly empty

        status, data = _get(base, "/api/amba-performance-trend?trend="
                             + urllib.parse.quote(str(elsewhere), safe=""))
        assert status == 200
        assert data["available"] is True
        assert data["trend_path"] == str(elsewhere)
        assert len(data["metrics"]) == 1
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_trend_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() --
    an endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    project's Methodology Consolidation Rule exists to avoid."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="ambaPerfTrendCard"' in html
        assert "AMBA Performance Trend" in html
        assert "'/api/amba-performance-trend'" in html
        assert "await loadAmbaPerfTrend();" in html
        assert 'id="ambaPerfTrendTable"' in html
        assert "Read-only" in html
        assert "NOT_AVAILABLE" in html
        assert "INCONCLUSIVE" in html
    finally:
        shutil.rmtree(tmp)
