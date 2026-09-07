"""GET /api/amba-bottleneck -- the AMBA Bottleneck Analysis dashboard card
(dashboard_amba_bottleneck_analysis_ui).

Before this, dashboard.py had no card at all surfacing
amba_performance_classification.identify_bottleneck_candidate()'s real
Hypothesis -> Evidence -> Confidence -> Gap -> Next-Best-Action record --
that module's own MIN_BOTTLENECK_EVIDENCE_COUNT (2) refusal, and its
gap-caps-confidence-at-MEDIUM rule, existed only at the library layer with no
dashboard surface reading them.

The real dashboard server is started for real on a free local port and
driven over real HTTP, reusing test_dashboard_interactive.py's own harness
helpers rather than standing up a second one -- the same cross-test import
convention test_dashboard_amba_connectivity_matrix_card.py and
test_dashboard_amba_path_explorer_card.py already use.
"""
from __future__ import annotations

import json
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
    _write_json,
)


def _candidates_doc_two_clean_one_bad():
    """Two real, buildable candidates (one with >=3 evidence citations and no
    gap -> HIGH confidence; one with exactly 2 citations and a declared gap
    -> confidence capped at MEDIUM) plus one declaration
    identify_bottleneck_candidate() must refuse outright (a single evidence
    citation) -- covering the module's own construction-time refusal and its
    real confidence-derivation rule in one fixture."""
    return {
        "candidates": [
            {
                "id": "C1",
                "hypothesis": "The M0->S0 crossbar port is the write-bandwidth bottleneck",
                "evidence": [
                    "utilization 0.94/1.0 vs near-max threshold 0.90 (bind_topology.json)",
                    "rising_latency_trend=True (fsdb_report.py write-channel latency series)",
                    "no_credit stalls observed on WVALID (sim.log:UVM_INFO @ 1200ns)",
                ],
            },
            {
                "id": "C2",
                "hypothesis": "The shared APB config bus is contended by branch_fw and branch_a1",
                "evidence": [
                    "branch_fw IRQ-ack write observed at 940ns (sim.log)",
                    "branch_a1 PHY config write observed at 942ns (sim.log)",
                ],
                "gap": "no real arbitration-policy evidence cited for this APB bus yet",
                "next_best_action": "cite the real arbiter RTL/spec section granting priority",
            },
            {
                "id": "BAD1",
                "hypothesis": "Single-metric guess",
                "evidence": ["utilization 0.94/1.0 (bind_topology.json)"],
            },
        ]
    }


def _write_candidates(tmp: Path, doc=None) -> Path:
    from dv_harness.dashboard import _default_amba_bottleneck_candidates_path

    path = _default_amba_bottleneck_candidates_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, doc if doc is not None else _candidates_doc_two_clean_one_bad())
    return path


def test_amba_bottleneck_reports_honest_empty_state_when_no_candidates_exist():
    """No bottleneck candidates have been declared for this project: the
    endpoint must say so and name the path it looked at, never invent a
    candidate -- the same honest-empty-state contract the two other AMBA
    cards already hold to."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/amba-bottleneck")
        assert status == 200
        assert data["available"] is False
        assert data["candidates"] == []
        assert data["rejected"] == []
        assert data["error"] is None
        assert data["candidates_path"].endswith("bottleneck_candidates.json")
        assert not Path(data["candidates_path"]).exists()
    finally:
        shutil.rmtree(tmp)


def test_amba_bottleneck_builds_real_records_and_caps_confidence_on_a_declared_gap():
    """Both real, buildable candidates must come back with the exact
    hypothesis/evidence/gap/next_best_action identify_bottleneck_candidate()
    itself produced, and confidence must reflect that module's own real
    rule: >=3 evidence + no gap -> HIGH, and a real unresolved gap caps
    confidence at MEDIUM even with corroborating evidence."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_candidates(tmp)

        status, data = _get(base, "/api/amba-bottleneck")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None

        by_id = {c["id"]: c for c in data["candidates"]}
        assert set(by_id) == {"C1", "C2"}

        c1 = by_id["C1"]
        assert c1["confidence"] == "HIGH"
        assert len(c1["evidence"]) == 3
        assert c1["gap"] == "no unresolved gap declared"
        assert "crossbar" in c1["hypothesis"]

        c2 = by_id["C2"]
        assert c2["confidence"] == "MEDIUM"
        assert "arbitration-policy" in c2["gap"]
        assert "arbiter RTL" in c2["next_best_action"]
    finally:
        shutil.rmtree(tmp)


def test_amba_bottleneck_reports_single_evidence_declaration_as_rejected_not_fabricated():
    """Negative control: a declaration carrying fewer than
    MIN_BOTTLENECK_EVIDENCE_COUNT (2) real evidence citations must be
    refused by the real module and surfaced under `rejected` -- never
    silently dropped, and never fabricated into a bare-label candidate."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_candidates(tmp)

        status, data = _get(base, "/api/amba-bottleneck")
        assert status == 200
        assert data["available"] is True
        assert len(data["rejected"]) == 1
        rejected = data["rejected"][0]
        assert rejected["id"] == "BAD1"
        assert "at least" in rejected["reason"] or "correlated" in rejected["reason"]
        assert "BAD1" not in {c["id"] for c in data["candidates"]}
    finally:
        shutil.rmtree(tmp)


def test_amba_bottleneck_reports_malformed_candidates_file_rather_than_a_500():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.dashboard import _default_amba_bottleneck_candidates_path
        p = _default_amba_bottleneck_candidates_path(tmp)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json", encoding="utf-8")

        status, data = _get(base, "/api/amba-bottleneck")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_CANDIDATES_FILE"
        assert data["candidates"] == [] and data["rejected"] == []
    finally:
        shutil.rmtree(tmp)


def test_amba_bottleneck_candidates_path_is_overridable_by_query_param():
    """Mirrors GET /api/amba-connectivity-matrix's ?graph= override: a
    project whose bottleneck-candidate declarations live elsewhere points at
    it, rather than this module guessing a second location."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        elsewhere = tmp / "amba_out" / "candidates.json"
        elsewhere.parent.mkdir(parents=True, exist_ok=True)
        _write_json(elsewhere, _candidates_doc_two_clean_one_bad())

        status, data = _get(base, "/api/amba-bottleneck")
        assert data["available"] is False  # default location still honestly empty

        status, data = _get(base, "/api/amba-bottleneck?candidates="
                             + urllib.parse.quote(str(elsewhere), safe=""))
        assert status == 200
        assert data["available"] is True
        assert data["candidates_path"] == str(elsewhere)
        assert len(data["candidates"]) == 2
    finally:
        shutil.rmtree(tmp)


def test_amba_bottleneck_card_is_served_and_wired_into_the_page_load():
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
        assert 'id="ambaBottleneckCard"' in html
        assert "AMBA Bottleneck Analysis" in html
        assert "'/api/amba-bottleneck'" in html
        assert "await loadAmbaBottleneck();" in html
        assert 'id="ambaBottleneckTable"' in html
        assert "Read-only" in html
    finally:
        shutil.rmtree(tmp)


def test_amba_bottleneck_never_renders_a_bind_statement():
    """A planning surface accidentally rendering emittable SystemVerilog
    would be a way past this project's usual review discipline -- the card
    and its JSON payload must never carry a `bind` statement."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_candidates(tmp)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        _, data = _get(base, "/api/amba-bottleneck")

        assert "\nbind " not in html and " bind (" not in html
        payload = json.dumps(data)
        assert "\nbind " not in payload and " bind (" not in payload
    finally:
        shutil.rmtree(tmp)
