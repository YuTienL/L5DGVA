"""GET /api/amba-connectivity-matrix -- the AMBA Fabric Connectivity Matrix
dashboard card (dashboard_amba_connectivity_matrix_ui).

Before this, dashboard.py had no reference to amba_fabric_graph_ir.py: that
module builds a real AMBAFabricGraphIR from caller-declared nodes/edges (a
fixed, closed twelve-kind internal-fabric-component vocabulary plus
master/slave endpoints, every node/edge requiring a real evidence citation,
and a reconfigurable/dynamic claim requiring grounded evidence per
assert_no_ungrounded_reconfigurable_claim()), but nothing rendered it.

The real dashboard server is started for real on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's own harness helpers
rather than standing up a second one -- the same cross-test import convention
test_dashboard_amba_card.py already uses.
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


def _graph_doc():
    """A real, small multi-kind fabric graph: a master endpoint into a
    crossbar, through a bridge (declared reconfigurable, with real grounded
    evidence), into a slave endpoint -- covering the node/edge/evidence/
    reconfigurable-flag shape this card actually renders."""
    return {
        "nodes": [
            {"node_id": "M0", "kind": "master_endpoint",
             "evidence": [{"citation": "amba16_matrix:u_fabric:S00_AXI_"}]},
            {"node_id": "XBAR0", "kind": "crossbar",
             "evidence": [{"citation": "u_fabric.sv:42"}]},
            {"node_id": "BRIDGE0", "kind": "bridge",
             "attributes": {"reconfigurable": True},
             "evidence": [{"citation": "u_fabric.sv:88",
                            "source_kind": "rtl_register"}]},
            {"node_id": "S0", "kind": "slave_endpoint",
             "evidence": [{"citation": "amba16_matrix:u_fabric:M01_APB_"}]},
        ],
        "edges": [
            {"from_node": "M0", "to_node": "XBAR0", "evidence": [{"citation": "route trace 1"}]},
            {"from_node": "XBAR0", "to_node": "BRIDGE0", "evidence": [{"citation": "route trace 2"}]},
            {"from_node": "BRIDGE0", "to_node": "S0", "evidence": [{"citation": "route trace 3"}]},
        ],
    }


def _write_graph(tmp: Path, doc=None) -> Path:
    from dv_harness.dashboard import _default_amba_fabric_graph_path

    path = _default_amba_fabric_graph_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, doc if doc is not None else _graph_doc())
    return path


def test_amba_connectivity_matrix_reports_honest_empty_state_when_no_graph_exists():
    """No fabric graph has been declared for this project: the endpoint must
    say so and name the path it looked at, never invent a node/edge -- the
    same honest-empty-state contract GET /api/amba already holds to."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/amba-connectivity-matrix")
        assert status == 200
        assert data["available"] is False
        assert data["nodes"] == []
        assert data["edges"] == []
        assert data["summary"] is None
        assert data["error"] is None
        assert data["graph_path"].endswith("amba_fabric_graph.json")
        assert not Path(data["graph_path"]).exists()
    finally:
        shutil.rmtree(tmp)


def test_amba_connectivity_matrix_returns_real_graph_built_through_the_real_module():
    """A real graph on disk reaches the endpoint with the exact node/edge
    identities and reconfigurable flag amba_fabric_graph_ir.build_amba_fabric_
    graph() itself produces -- not a dashboard-local re-derivation that could
    disagree with the real IR."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        graph_path = _write_graph(tmp)

        from dv_harness.amba_fabric_graph_ir import build_amba_fabric_graph

        doc = _graph_doc()
        expected_graph = build_amba_fabric_graph(doc["nodes"], doc["edges"])

        status, data = _get(base, "/api/amba-connectivity-matrix")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        assert data["graph_path"] == str(graph_path)

        assert [n["node_id"] for n in data["nodes"]] == [n.node_id for n in expected_graph.nodes]
        assert [n["kind"] for n in data["nodes"]] == [n.kind for n in expected_graph.nodes]
        # Only BRIDGE0 declared reconfigurable=True; every other node is False.
        recon_by_id = {n["node_id"]: n["reconfigurable"] for n in data["nodes"]}
        assert recon_by_id == {"M0": False, "XBAR0": False, "BRIDGE0": True, "S0": False}
        assert recon_by_id["BRIDGE0"] is True

        assert [(e["from"], e["to"]) for e in data["edges"]] == \
            [(e.from_node, e.to_node) for e in expected_graph.edges]
        assert data["edges"][1]["evidence"] == "route trace 2"

        s = data["summary"]
        assert s["node_count"] == 4 and s["edge_count"] == 3
        assert s["reconfigurable_node_count"] == 1
    finally:
        shutil.rmtree(tmp)


def test_amba_connectivity_matrix_reports_real_graph_error_reason_rather_than_a_500():
    """A node claiming reconfigurable=True with no grounded evidence must
    surface amba_fabric_graph_ir's own AMBAFabricGraphError code/detail (the
    module's own assert_no_ungrounded_reconfigurable_claim() rejection) -- not
    a stack trace and not a blank table."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        doc = {
            "nodes": [
                {"node_id": "BRIDGE0", "kind": "bridge",
                 "attributes": {"reconfigurable": True},
                 "evidence": [{"citation": "no source_kind at all"}]},
            ],
            "edges": [],
        }
        _write_graph(tmp, doc)

        status, data = _get(base, "/api/amba-connectivity-matrix")
        assert status == 200
        assert data["available"] is True
        assert data["nodes"] == [] and data["summary"] is None
        assert data["error"]["reason"] == "RECONFIGURABLE_CLAIM_WITHOUT_GROUNDED_EVIDENCE"
        assert data["error"]["detail"]["offenders"][0]["node_id"] == "BRIDGE0"
    finally:
        shutil.rmtree(tmp)


def test_amba_connectivity_matrix_reports_malformed_graph_file_rather_than_a_500():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.dashboard import _default_amba_fabric_graph_path
        p = _default_amba_fabric_graph_path(tmp)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json", encoding="utf-8")

        status, data = _get(base, "/api/amba-connectivity-matrix")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_GRAPH_FILE"
        assert data["nodes"] == []
    finally:
        shutil.rmtree(tmp)


def test_amba_connectivity_matrix_graph_path_is_overridable_by_query_param():
    """Mirrors GET /api/amba's ?registry= override: a project whose fabric
    graph was declared elsewhere points at it, rather than this module
    guessing a second location."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        elsewhere = tmp / "fabric_out" / "graph.json"
        elsewhere.parent.mkdir(parents=True, exist_ok=True)
        _write_json(elsewhere, _graph_doc())

        status, data = _get(base, "/api/amba-connectivity-matrix")
        assert data["available"] is False  # default location still honestly empty

        status, data = _get(base, "/api/amba-connectivity-matrix?graph="
                             + urllib.parse.quote(str(elsewhere), safe=""))
        assert status == 200
        assert data["available"] is True
        assert data["graph_path"] == str(elsewhere)
        assert [n["node_id"] for n in data["nodes"]] == ["M0", "XBAR0", "BRIDGE0", "S0"]
    finally:
        shutil.rmtree(tmp)


def test_amba_connectivity_matrix_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() -- an
    endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    gap-close exists to avoid."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="ambaConnectivityMatrixCard"' in html
        assert "AMBA Fabric Connectivity Matrix" in html
        assert "'/api/amba-connectivity-matrix'" in html
        assert "await loadAmbaConnectivityMatrix();" in html
        assert "Read-only" in html
    finally:
        shutil.rmtree(tmp)


def test_amba_connectivity_matrix_never_renders_a_bind_statement():
    """A planning surface accidentally rendering emittable SystemVerilog would
    be a way past this project's usual review discipline -- the card and its
    JSON payload must never carry a `bind` statement."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_graph(tmp)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        _, data = _get(base, "/api/amba-connectivity-matrix")

        assert "\nbind " not in html and " bind (" not in html
        payload = json.dumps(data)
        assert "\nbind " not in payload and " bind (" not in payload
    finally:
        shutil.rmtree(tmp)
