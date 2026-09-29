"""GET /api/amba-performance -- the AMBA Per-Port Performance Center dashboard
card (dashboard_amba_per_port_performance_center).

Before this, dashboard.py had no card surfacing
amba_performance_calculator.py's real PortPerformanceIR/PathPerformanceIR
aggregates -- pure arithmetic over real, caller-supplied samples, with an
explicit COMPUTED/UNKNOWN/NOT_APPLICABLE status on every metric. This module
this file tests never computes a bandwidth/throughput/latency/outstanding/
stall-ratio/utilization number itself; it is a thin JSON-file front door onto
`amba_performance_calculator.aggregate_port_performance()`, and every test
below cross-checks the card's numbers against that real module's own
documented arithmetic and status rules -- most importantly the negative
control that an absent `peak_bandwidth_bytes_per_second` reports the real
`bandwidth_utilization` metric as honest UNKNOWN, never a fabricated
percentage.

The real dashboard server is started for real on a free local port and
driven over real HTTP, reusing test_dashboard_interactive.py's own harness
helpers rather than standing up a second one -- the same cross-test import
convention test_dashboard_amba_bottleneck_card.py already uses.
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


def _two_sample_port(peak_bandwidth=None, latency_definition="ISSUE_TO_FIRST_BEAT"):
    entry = {
        "samples": [
            {
                "sample_id": "s1", "start_time": 0.0, "end_time": 1.0,
                "byte_count": 1000, "transaction_count": 10, "latency": 0.0001,
                "outstanding_count": 2, "busy_cycles": 800, "stalled_cycles": 200,
                "total_cycles": 1000,
            },
            {
                "sample_id": "s2", "start_time": 1.0, "end_time": 2.0,
                "byte_count": 2000, "transaction_count": 20, "latency": 0.0002,
                "outstanding_count": 3, "busy_cycles": 900, "stalled_cycles": 100,
                "total_cycles": 1000,
            },
        ],
        "latency_definition": latency_definition,
    }
    if peak_bandwidth is not None:
        entry["peak_bandwidth_bytes_per_second"] = peak_bandwidth
    return entry


def _write_samples(tmp: Path, doc: dict) -> Path:
    from dv_harness.dashboard import _default_amba_performance_samples_path

    path = _default_amba_performance_samples_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, doc)
    return path


def test_amba_performance_reports_honest_empty_state_when_no_samples_exist():
    """No performance samples have been declared for this project: the
    endpoint must say so and name the path it looked at, never invent a
    port/path -- the same honest-empty-state contract the other AMBA cards
    already hold to."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/amba-performance")
        assert status == 200
        assert data["available"] is False
        assert data["ports"] == []
        assert data["paths"] == []
        assert data["rejected"] == []
        assert data["error"] is None
        assert data["samples_path"].endswith("performance_samples.json")
        assert not Path(data["samples_path"]).exists()
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_builds_real_port_aggregates_with_a_declared_peak_bandwidth():
    """A port declaring a real peak_bandwidth_bytes_per_second must come back
    with bandwidth/throughput/outstanding/stall_ratio/utilization/
    bandwidth_utilization all COMPUTED, matching
    aggregate_port_performance()'s own real arithmetic exactly."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_samples(tmp, {"ports": {"M0": _two_sample_port(peak_bandwidth=1_000_000_000.0)}})

        status, data = _get(base, "/api/amba-performance")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        assert data["rejected"] == []
        assert len(data["ports"]) == 1

        p = data["ports"][0]
        assert p["port_id"] == "M0"
        assert p["sample_count"] == 2

        assert p["bandwidth"]["status"] == "COMPUTED"
        assert p["bandwidth"]["value"] == pytest.approx(3000.0 / 2.0)
        assert p["bandwidth"]["unit"] == "bytes_per_second"

        assert p["throughput"]["status"] == "COMPUTED"
        assert p["throughput"]["value"] == pytest.approx(30.0 / 2.0)

        assert p["latency_report"]["status"] == "COMPUTED"
        assert p["latency_report"]["latency_definition"] == "ISSUE_TO_FIRST_BEAT"
        assert set(p["latency_report"]["percentiles"]) == {"p50", "p90", "p95", "p99"}

        assert p["outstanding"]["status"] == "COMPUTED"
        assert p["outstanding"]["average"] == pytest.approx(2.5)
        assert p["outstanding"]["peak"] == 3

        assert p["stall_ratio"]["status"] == "COMPUTED"
        assert p["stall_ratio"]["value"] == pytest.approx(300.0 / 2000.0)

        assert p["utilization"]["status"] == "COMPUTED"
        assert p["utilization"]["value"] == pytest.approx(1700.0 / 2000.0)

        assert p["bandwidth_utilization"]["status"] == "COMPUTED"
        expected_bw = 3000.0 / 2.0
        assert p["bandwidth_utilization"]["value"] == pytest.approx(
            100.0 * expected_bw / 1_000_000_000.0)
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_absent_peak_bandwidth_is_honest_unknown_never_fabricated():
    """The negative control this card exists to prove: a port with real
    samples but NO declared peak_bandwidth_bytes_per_second must report
    bandwidth_utilization as UNKNOWN with the real reason
    bandwidth_utilization() itself gives -- never a computed-looking
    percentage, and never silently omitted from the response. Every other
    metric on the same port must still compute normally, proving the
    honesty is per-metric, not a whole-port failure."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_samples(tmp, {"ports": {"M1": _two_sample_port(peak_bandwidth=None)}})

        status, data = _get(base, "/api/amba-performance")
        assert status == 200
        assert data["available"] is True
        assert len(data["ports"]) == 1

        p = data["ports"][0]
        assert p["port_id"] == "M1"

        bwu = p["bandwidth_utilization"]
        assert bwu["status"] == "UNKNOWN"
        assert bwu["value"] is None
        assert "peak" in bwu["reason"]
        assert "invented" in bwu["reason"] or "assumed" in bwu["reason"]

        # Every other metric on the SAME port still computes normally --
        # absence of ONE input never taints an unrelated metric.
        assert p["bandwidth"]["status"] == "COMPUTED"
        assert p["throughput"]["status"] == "COMPUTED"
        assert p["outstanding"]["status"] == "COMPUTED"
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_empty_port_reports_every_metric_honestly_unknown_or_not_applicable():
    """A declared port with ZERO samples must still return a real
    PortPerformanceIR -- every metric UNKNOWN/NOT_APPLICABLE, never a
    fabricated zero or a crash."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_samples(tmp, {"ports": {"EMPTY0": {"samples": []}}})

        status, data = _get(base, "/api/amba-performance")
        assert status == 200
        assert len(data["ports"]) == 1
        p = data["ports"][0]
        assert p["sample_count"] == 0
        assert p["bandwidth"]["status"] == "UNKNOWN"
        assert p["bandwidth"]["value"] is None
        assert p["throughput"]["status"] == "UNKNOWN"
        # No latency_definition declared at all -> NOT_APPLICABLE, distinct
        # from UNKNOWN (an unproven target vs. missing observed data).
        assert p["latency_report"]["status"] == "NOT_APPLICABLE"
        assert p["outstanding"]["status"] == "UNKNOWN"
        assert p["bandwidth_utilization"]["status"] == "UNKNOWN"
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_builds_a_real_path_performance_ir_reusing_the_same_aggregation():
    """A declared path must come back as a real PathPerformanceIR -- only the
    fields that dataclass declares (bandwidth/throughput/latency_report),
    computed by the SAME real aggregate_port_performance() the port rows use,
    never a fourth arithmetic engine."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_samples(tmp, {
            "paths": {
                "M0->S0": {
                    "source_port": "M0",
                    "dest_port": "S0",
                    "samples": [
                        {"sample_id": "p1", "start_time": 0.0, "end_time": 1.0,
                         "byte_count": 500, "transaction_count": 5},
                    ],
                    # latency_definition deliberately omitted -> NOT_APPLICABLE
                },
            },
        })

        status, data = _get(base, "/api/amba-performance")
        assert status == 200
        assert data["rejected"] == []
        assert len(data["paths"]) == 1

        p = data["paths"][0]
        assert p["path_id"] == "M0->S0"
        assert p["source_port"] == "M0"
        assert p["dest_port"] == "S0"
        assert p["sample_count"] == 1
        assert p["bandwidth"]["status"] == "COMPUTED"
        assert p["bandwidth"]["value"] == pytest.approx(500.0)
        assert p["throughput"]["status"] == "COMPUTED"
        assert p["throughput"]["value"] == pytest.approx(5.0)
        assert p["latency_report"]["status"] == "NOT_APPLICABLE"
        # PathPerformanceIR carries no outstanding/stall_ratio/utilization/
        # bandwidth_utilization fields at all -- never fabricated here either.
        assert "outstanding" not in p
        assert "bandwidth_utilization" not in p
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_reports_rejected_declarations_not_fabricated():
    """Three real refusals, each surfaced under `rejected` rather than
    silently dropped or turned into a fabricated aggregate: an invalid
    latency definition, a path missing its dest_port, and a malformed
    (non-object) sample entry."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_samples(tmp, {
            "ports": {
                "BADLAT": {"samples": [{"byte_count": 100, "transaction_count": 1,
                                          "start_time": 0.0, "end_time": 1.0}],
                            "latency_definition": "NOT_A_REAL_DEFINITION"},
                "BADSHAPE": {"samples": ["not-a-dict"]},
            },
            "paths": {
                "NODEST": {"source_port": "M0", "samples": []},
            },
        })

        status, data = _get(base, "/api/amba-performance")
        assert status == 200
        assert data["ports"] == []
        assert data["paths"] == []
        assert len(data["rejected"]) == 3

        by_id = {(r["kind"], r["id"]): r for r in data["rejected"]}
        assert ("port", "BADLAT") in by_id
        assert "NOT_A_REAL_DEFINITION" in by_id[("port", "BADLAT")]["reason"]
        assert ("port", "BADSHAPE") in by_id
        assert ("path", "NODEST") in by_id
        assert by_id[("path", "NODEST")]["reason"] == "MISSING_SOURCE_OR_DEST_PORT"
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_reports_malformed_samples_file_rather_than_a_500():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.dashboard import _default_amba_performance_samples_path
        p = _default_amba_performance_samples_path(tmp)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json", encoding="utf-8")

        status, data = _get(base, "/api/amba-performance")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_SAMPLES_FILE"
        assert data["ports"] == [] and data["paths"] == [] and data["rejected"] == []
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_samples_path_is_overridable_by_query_param():
    """Mirrors GET /api/amba-bottleneck's ?candidates= override: a project
    whose performance-sample declarations live elsewhere points at it,
    rather than this module guessing a second location."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        elsewhere = tmp / "amba_out" / "perf_samples.json"
        elsewhere.parent.mkdir(parents=True, exist_ok=True)
        _write_json(elsewhere, {"ports": {"M0": _two_sample_port(peak_bandwidth=1e9)}})

        status, data = _get(base, "/api/amba-performance")
        assert data["available"] is False  # default location still honestly empty

        status, data = _get(base, "/api/amba-performance?samples="
                             + urllib.parse.quote(str(elsewhere), safe=""))
        assert status == 200
        assert data["available"] is True
        assert data["samples_path"] == str(elsewhere)
        assert len(data["ports"]) == 1
    finally:
        shutil.rmtree(tmp)


def test_amba_performance_card_is_served_and_wired_into_the_page_load():
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
        assert 'id="ambaPerfCenterCard"' in html
        assert "AMBA Per-Port Performance Center" in html
        assert "'/api/amba-performance'" in html
        assert "await loadAmbaPerf();" in html
        assert 'id="ambaPerfPortTable"' in html
        assert 'id="ambaPerfPathTable"' in html
        assert "Read-only" in html
    finally:
        shutil.rmtree(tmp)
