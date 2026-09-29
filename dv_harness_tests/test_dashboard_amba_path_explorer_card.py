"""GET /api/amba-path-explorer -- the AMBA Path Explorer dashboard card
(dashboard_amba_path_explorer_ui).

Before this, dashboard.py had a card rendering amba_fabric_graph_ir.py's
node/edge topology (the AMBA Fabric Connectivity Matrix card) but nothing
letting a human pick a (master, slave) pair and see that module's real
declared route(s) for it -- amba_fabric_graph_ir.build_amba_path_ir()'s own
AMBAPathIR, which preserves every distinct declared route for one pair
(never collapsing several real routes into one) and cross-checks each
route's own hop sequence against the real fabric graph
(CONSISTENT_WITH_GRAPH / INCONSISTENT_WITH_GRAPH / CONSISTENCY_NOT_CHECKED).

The real dashboard server is started for real on a free local port and
driven over real HTTP, reusing test_dashboard_interactive.py's own harness
helpers rather than standing up a second one -- the same cross-test import
convention test_dashboard_amba_connectivity_matrix_card.py already uses.
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


def _graph_doc_with_two_routes():
    """A real fabric graph (a master endpoint into a crossbar into a slave
    endpoint) plus two REAL, distinct declared routes for the same
    (M0, S0) pair -- one whose hops agree with the graph's real edges, one
    that does not -- covering AMBAPathIR's own "never collapse multiple real
    routes into one" rule and its graph-consistency cross-check in one
    fixture."""
    return {
        "nodes": [
            {"node_id": "M0", "kind": "master_endpoint",
             "evidence": [{"citation": "amba16_matrix:u_fabric:S00_AXI_"}]},
            {"node_id": "XBAR0", "kind": "crossbar",
             "evidence": [{"citation": "u_fabric.sv:42"}]},
            {"node_id": "S0", "kind": "slave_endpoint",
             "evidence": [{"citation": "amba16_matrix:u_fabric:M01_APB_"}]},
        ],
        "edges": [
            {"from_node": "M0", "to_node": "XBAR0", "evidence": [{"citation": "route trace 1"}]},
            {"from_node": "XBAR0", "to_node": "S0", "evidence": [{"citation": "route trace 2"}]},
        ],
        "routes": [
            {"route_id": "R_PRIMARY", "master_id": "M0", "slave_id": "S0",
             "hops": ["M0", "XBAR0", "S0"],
             "evidence": [{"citation": "primary route: address decode table row 3"}]},
            {"route_id": "R_STALE_DOC", "master_id": "M0", "slave_id": "S0",
             "hops": ["M0", "S0"],
             "evidence": [{"citation": "legacy doc: direct-connect diagram (superseded)"}]},
        ],
    }


def _write_graph(tmp: Path, doc=None) -> Path:
    from dv_harness.dashboard import _default_amba_fabric_graph_path

    path = _default_amba_fabric_graph_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, doc if doc is not None else _graph_doc_with_two_routes())
    return path


def test_amba_path_explorer_reports_honest_empty_state_when_no_graph_exists():
    """No fabric graph has been declared for this project: the endpoint must
    say so and name the path it looked at, never invent a pair or a route --
    the same honest-empty-state contract the connectivity-matrix card and
    GET /api/amba already hold to."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/amba-path-explorer")
        assert status == 200
        assert data["available"] is False
        assert data["pairs"] == []
        assert data["paths"] == []
        assert data["master"] is None and data["slave"] is None
        assert data["error"] is None
        assert data["graph_path"].endswith("amba_fabric_graph.json")
        assert not Path(data["graph_path"]).exists()
    finally:
        shutil.rmtree(tmp)


def test_amba_path_explorer_lists_declared_pairs_and_preserves_both_real_routes():
    """Both real declared routes for (M0, S0) must come back -- AMBAPathIR
    never collapses several distinct real routes into one -- with the
    primary route's hops confirmed CONSISTENT_WITH_GRAPH and the stale-doc
    route's hops confirmed INCONSISTENT_WITH_GRAPH, exactly as
    amba_fabric_graph_ir.build_amba_path_ir() itself computes it."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_graph(tmp)

        status, data = _get(base, "/api/amba-path-explorer")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        assert data["pairs"] == [{"master": "M0", "slave": "S0"}]
        # No pair selected yet -> no paths rendered, not an error.
        assert data["paths"] == []

        status, data = _get(base, "/api/amba-path-explorer?master=M0&slave=S0")
        assert status == 200
        assert data["available"] is True
        assert data["master"] == "M0" and data["slave"] == "S0"
        paths_by_id = {p["route_id"]: p for p in data["paths"]}
        assert set(paths_by_id) == {"R_PRIMARY", "R_STALE_DOC"}

        primary = paths_by_id["R_PRIMARY"]
        assert primary["hops"] == ["M0", "XBAR0", "S0"]
        assert primary["consistency"] == "CONSISTENT_WITH_GRAPH"
        assert primary["findings"] == []
        assert "address decode table row 3" in primary["evidence"][0]

        stale = paths_by_id["R_STALE_DOC"]
        assert stale["hops"] == ["M0", "S0"]
        assert stale["consistency"] == "INCONSISTENT_WITH_GRAPH"
        assert stale["findings"]  # a real finding citing the missing hop pair
        assert any("M0" in f and "S0" in f for f in stale["findings"])
    finally:
        shutil.rmtree(tmp)


def test_amba_path_explorer_unknown_pair_returns_empty_paths_not_an_error():
    """Negative control: a pair nobody declared a route for must report zero
    paths honestly -- never an error, and never a fabricated route. This is
    the module's own absence-of-evidence-is-honestly-reported guarantee,
    exercised through the dashboard rather than only at the IR layer."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_graph(tmp)

        status, data = _get(base, "/api/amba-path-explorer?master=M0&slave=NO_SUCH_SLAVE")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        assert data["paths"] == []
        # The real declared pair list is unaffected by an unrelated query.
        assert data["pairs"] == [{"master": "M0", "slave": "S0"}]
    finally:
        shutil.rmtree(tmp)


def test_amba_path_explorer_route_without_graph_reports_consistency_not_checked():
    """A project that has declared routes but no fabric graph (nodes/edges)
    must never fabricate a CONSISTENT_WITH_GRAPH verdict -- build_amba_path_ir()
    reports CONSISTENCY_NOT_CHECKED when there is nothing to check the route
    against, and this endpoint must carry that through unchanged."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        doc = {
            "nodes": [], "edges": [],
            "routes": [
                {"route_id": "R0", "master_id": "MX", "slave_id": "SX",
                 "hops": ["MX", "SX"],
                 "evidence": [{"citation": "programming guide section 4.2"}]},
            ],
        }
        _write_graph(tmp, doc)

        status, data = _get(base, "/api/amba-path-explorer?master=MX&slave=SX")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        assert len(data["paths"]) == 1
        assert data["paths"][0]["consistency"] == "CONSISTENCY_NOT_CHECKED"
        assert data["paths"][0]["findings"] == []
    finally:
        shutil.rmtree(tmp)


def test_amba_path_explorer_reports_real_graph_error_reason_rather_than_a_500():
    """A node claiming reconfigurable=True with no grounded evidence must
    surface amba_fabric_graph_ir's own AMBAFabricGraphError code/detail --
    not a stack trace and not a blank picker."""
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
            "routes": [],
        }
        _write_graph(tmp, doc)

        status, data = _get(base, "/api/amba-path-explorer")
        assert status == 200
        assert data["available"] is True
        assert data["pairs"] == [] and data["paths"] == []
        assert data["error"]["reason"] == "RECONFIGURABLE_CLAIM_WITHOUT_GROUNDED_EVIDENCE"
        assert data["error"]["detail"]["offenders"][0]["node_id"] == "BRIDGE0"
    finally:
        shutil.rmtree(tmp)


def test_amba_path_explorer_reports_malformed_graph_file_rather_than_a_500():
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

        status, data = _get(base, "/api/amba-path-explorer")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_GRAPH_FILE"
        assert data["pairs"] == [] and data["paths"] == []
    finally:
        shutil.rmtree(tmp)


def test_amba_path_explorer_graph_path_is_overridable_by_query_param():
    """Mirrors GET /api/amba-connectivity-matrix's ?graph= override: a
    project whose fabric graph was declared elsewhere points at it, rather
    than this module guessing a second location."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        elsewhere = tmp / "fabric_out" / "graph.json"
        elsewhere.parent.mkdir(parents=True, exist_ok=True)
        _write_json(elsewhere, _graph_doc_with_two_routes())

        status, data = _get(base, "/api/amba-path-explorer")
        assert data["available"] is False  # default location still honestly empty

        status, data = _get(base, "/api/amba-path-explorer?graph="
                             + urllib.parse.quote(str(elsewhere), safe=""))
        assert status == 200
        assert data["available"] is True
        assert data["graph_path"] == str(elsewhere)
        assert data["pairs"] == [{"master": "M0", "slave": "S0"}]
    finally:
        shutil.rmtree(tmp)


def test_amba_path_explorer_card_is_served_and_wired_into_the_page_load():
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
        assert 'id="ambaPathExplorerCard"' in html
        assert "AMBA Path Explorer" in html
        assert "'/api/amba-path-explorer'" in html
        assert "await loadAmbaPathExplorer();" in html
        assert 'id="ambaPathMaster"' in html and 'id="ambaPathSlave"' in html
        assert "Read-only" in html
    finally:
        shutil.rmtree(tmp)


def test_amba_path_explorer_never_renders_a_bind_statement():
    """A planning surface accidentally rendering emittable SystemVerilog
    would be a way past this project's usual review discipline -- the card
    and its JSON payload must never carry a `bind` statement."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_graph(tmp)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        _, data = _get(base, "/api/amba-path-explorer?master=M0&slave=S0")

        assert "\nbind " not in html and " bind (" not in html
        payload = json.dumps(data)
        assert "\nbind " not in payload and " bind (" not in payload
    finally:
        shutil.rmtree(tmp)
