"""Tests for dv_harness/amba_fabric_graph_ir.py -- AMBAFabricGraphIR (typed
nodes/edges) and AMBAPathIR (multi-path enumeration per master/slave pair).
"""
import pytest

from dv_harness.amba_fabric_graph_ir import (
    ALL_NODE_KINDS,
    AMBAFabricGraphError,
    FABRIC_NODE_KINDS,
    ROUTE_CONSISTENT_WITH_GRAPH,
    ROUTE_CONSISTENCY_NOT_CHECKED,
    ROUTE_INCONSISTENT_WITH_GRAPH,
    assert_declared_multiplicity_preserved,
    assert_no_ungrounded_reconfigurable_claim,
    build_amba_fabric_graph,
    build_amba_path_ir,
    render_fabric_graph_report,
    render_path_ir_report,
)


def _node(node_id, kind, evidence="cited", **attrs):
    return {"node_id": node_id, "kind": kind, "attributes": attrs,
            "evidence": [{"citation": evidence, "source_kind": attrs.get("source_kind",
                                                                        "human_confirmation")}]}


def _edge(a, b, evidence="cited"):
    return {"from_node": a, "to_node": b, "evidence": [{"citation": evidence}]}


# ===========================================================================
# Node-kind vocabulary
# ===========================================================================

def test_all_twelve_fabric_node_kinds_are_declared():
    expected = {"crossbar", "arbiter", "decoder", "bridge", "width_converter",
                "id_converter", "clock_converter", "register_slice", "firewall",
                "address_translator", "coherent_node", "memory_controller"}
    assert set(FABRIC_NODE_KINDS) == expected
    assert expected <= ALL_NODE_KINDS


def test_unknown_node_kind_is_refused():
    nodes = [_node("N1", "hyperspace_router")]
    with pytest.raises(AMBAFabricGraphError) as exc:
        build_amba_fabric_graph(nodes, [])
    assert exc.value.code == "UNKNOWN_NODE_KIND"


# ===========================================================================
# Graph construction: positive path
# ===========================================================================

def test_build_a_real_multi_node_graph_with_several_kinds():
    nodes = [
        _node("M0", "master_endpoint"),
        _node("XBAR0", "crossbar"),
        _node("DEC0", "decoder"),
        _node("BRIDGE0", "bridge"),
        _node("S0", "slave_endpoint"),
    ]
    edges = [
        _edge("M0", "XBAR0"),
        _edge("XBAR0", "DEC0"),
        _edge("DEC0", "BRIDGE0"),
        _edge("BRIDGE0", "S0"),
    ]
    graph = build_amba_fabric_graph(nodes, edges)
    assert len(graph.nodes) == 5
    assert len(graph.edges) == 4
    assert graph.node("XBAR0").kind == "crossbar"
    assert graph.has_edge("M0", "XBAR0")
    assert not graph.has_edge("M0", "S0")
    assert [n.node_id for n in graph.nodes_by_kind("decoder")] == ["DEC0"]
    report = render_fabric_graph_report(graph)
    assert "crossbar" in report and "bridge" in report


# ===========================================================================
# Negative controls: construction
# ===========================================================================

def test_node_without_evidence_is_refused():
    nodes = [{"node_id": "N1", "kind": "arbiter", "evidence": []}]
    with pytest.raises(AMBAFabricGraphError) as exc:
        build_amba_fabric_graph(nodes, [])
    assert exc.value.code == "NODE_WITHOUT_EVIDENCE"


def test_edge_without_evidence_is_refused():
    nodes = [_node("A", "crossbar"), _node("B", "decoder")]
    edges = [{"from_node": "A", "to_node": "B", "evidence": []}]
    with pytest.raises(AMBAFabricGraphError) as exc:
        build_amba_fabric_graph(nodes, edges)
    assert exc.value.code == "EDGE_WITHOUT_EVIDENCE"


def test_edge_referencing_undeclared_node_is_refused():
    nodes = [_node("A", "crossbar")]
    edges = [_edge("A", "GHOST")]
    with pytest.raises(AMBAFabricGraphError) as exc:
        build_amba_fabric_graph(nodes, edges)
    assert exc.value.code == "EDGE_REFERENCES_UNKNOWN_NODE"
    assert exc.value.detail["value"] == "GHOST"


def test_duplicate_node_id_is_refused():
    nodes = [_node("A", "crossbar"), _node("A", "decoder")]
    with pytest.raises(AMBAFabricGraphError) as exc:
        build_amba_fabric_graph(nodes, [])
    assert exc.value.code == "DUPLICATE_NODE_ID"


def test_node_with_no_id_is_refused():
    nodes = [{"node_id": None, "kind": "crossbar", "evidence": [{"citation": "x"}]}]
    with pytest.raises(AMBAFabricGraphError) as exc:
        build_amba_fabric_graph(nodes, [])
    assert exc.value.code == "NODE_WITHOUT_ID"


# ===========================================================================
# The one hard rule: reconfigurable/dynamic claims must be grounded
# ===========================================================================

def test_reconfigurable_claim_without_grounded_evidence_is_refused():
    """The module's headline rule: never infer 'reconfigurable' from the
    fabric protocol/family alone -- reports/raises rather than silently
    accepting an ungrounded claim."""
    nodes = [{"node_id": "DEC0", "kind": "decoder",
             "attributes": {"reconfigurable": True},
             "evidence": [{"citation": "AXI protocol implies dynamic decode"}]}]
    with pytest.raises(AMBAFabricGraphError) as exc:
        build_amba_fabric_graph(nodes, [])
    assert exc.value.code == "RECONFIGURABLE_CLAIM_WITHOUT_GROUNDED_EVIDENCE"
    assert exc.value.detail["offenders"][0]["node_id"] == "DEC0"


def test_reconfigurable_claim_with_real_register_field_evidence_is_accepted():
    nodes = [{"node_id": "DEC0", "kind": "decoder",
             "attributes": {"reconfigurable": True},
             "evidence": [{"citation": "REMAP_CTRL register field bit[3]",
                           "source_kind": "rtl_register"}]}]
    graph = build_amba_fabric_graph(nodes, [])
    assert graph.node("DEC0").attributes["reconfigurable"] is True


def test_dynamic_alias_is_checked_the_same_way_as_reconfigurable():
    nodes = [_node("ARB0", "arbiter", dynamic=True)]  # source_kind defaults to human_confirmation
    # human_confirmation IS an allowed source, so this should build cleanly.
    graph = build_amba_fabric_graph(nodes, [])
    assert graph.node("ARB0").attributes["dynamic"] is True

    bad_nodes = [{"node_id": "ARB1", "kind": "arbiter", "attributes": {"dynamic": True},
                 "evidence": [{"citation": "protocol allows it"}]}]  # no source_kind at all
    with pytest.raises(AMBAFabricGraphError) as exc:
        build_amba_fabric_graph(bad_nodes, [])
    assert exc.value.code == "RECONFIGURABLE_CLAIM_WITHOUT_GROUNDED_EVIDENCE"


def test_assert_no_ungrounded_reconfigurable_claim_standalone():
    ok = [_node("X", "crossbar")]  # no reconfigurable claim at all
    assert_no_ungrounded_reconfigurable_claim(ok)  # must not raise

    bad = [{"node_id": "Y", "kind": "decoder", "attributes": {"reconfigurable": True},
           "evidence": [{"citation": "name says so"}]}]
    with pytest.raises(AMBAFabricGraphError):
        assert_no_ungrounded_reconfigurable_claim(bad)


# ===========================================================================
# AMBAPathIR: multiple distinct routes preserved, never collapsed
# ===========================================================================

def _fabric_with_two_routes():
    nodes = [
        _node("M0", "master_endpoint"),
        _node("XBAR_A", "crossbar"),
        _node("XBAR_B", "crossbar"),
        _node("DEC0", "decoder"),
        _node("S0", "slave_endpoint"),
    ]
    edges = [
        _edge("M0", "XBAR_A"), _edge("XBAR_A", "DEC0"),
        _edge("M0", "XBAR_B"), _edge("XBAR_B", "DEC0"),
        _edge("DEC0", "S0"),
    ]
    return build_amba_fabric_graph(nodes, edges)


def test_two_distinct_declared_routes_for_one_pair_are_both_preserved():
    graph = _fabric_with_two_routes()
    routes = [
        {"master_id": "M0", "slave_id": "S0", "hops": ["M0", "XBAR_A", "DEC0", "S0"],
         "evidence": [{"citation": "redundant path A observed in RTL crossbar select mux"}]},
        {"master_id": "M0", "slave_id": "S0", "hops": ["M0", "XBAR_B", "DEC0", "S0"],
         "evidence": [{"citation": "redundant path B observed in RTL crossbar select mux"}]},
    ]
    path_ir = build_amba_path_ir(routes, graph=graph)
    assert path_ir.has_multiple_paths("M0", "S0")
    assert path_ir.path_count("M0", "S0") == 2
    hops_seen = {p.hops for p in path_ir.paths_for("M0", "S0")}
    assert hops_seen == {("M0", "XBAR_A", "DEC0", "S0"), ("M0", "XBAR_B", "DEC0", "S0")}
    for p in path_ir.paths_for("M0", "S0"):
        assert p.consistency_status == ROUTE_CONSISTENT_WITH_GRAPH
    assert_declared_multiplicity_preserved(routes, path_ir)  # must not raise
    report = render_path_ir_report(path_ir)
    assert report.count("M0") >= 2  # both rows present


def test_single_route_pair_reports_exactly_one_path():
    routes = [{"master_id": "M1", "slave_id": "S1",
              "evidence": [{"citation": "the only real route"}]}]
    path_ir = build_amba_path_ir(routes)  # no graph supplied at all
    assert path_ir.path_count("M1", "S1") == 1
    assert not path_ir.has_multiple_paths("M1", "S1")
    assert path_ir.paths_for("M1", "S1")[0].consistency_status == ROUTE_CONSISTENCY_NOT_CHECKED


def test_unqueried_pair_reports_zero_paths_not_an_error():
    routes = [{"master_id": "M1", "slave_id": "S1", "evidence": [{"citation": "x"}]}]
    path_ir = build_amba_path_ir(routes)
    assert path_ir.path_count("M2", "S2") == 0
    assert path_ir.paths_for("M2", "S2") == ()


def test_route_without_evidence_is_refused():
    routes = [{"master_id": "M0", "slave_id": "S0", "evidence": []}]
    with pytest.raises(AMBAFabricGraphError) as exc:
        build_amba_path_ir(routes)
    assert exc.value.code == "ROUTE_WITHOUT_EVIDENCE"


def test_route_without_endpoints_is_refused():
    routes = [{"master_id": "M0", "slave_id": None, "evidence": [{"citation": "x"}]}]
    with pytest.raises(AMBAFabricGraphError) as exc:
        build_amba_path_ir(routes)
    assert exc.value.code == "ROUTE_WITHOUT_ENDPOINTS"


def test_route_hops_inconsistent_with_graph_is_reported_but_preserved():
    """A route whose declared hops the graph does not actually connect is a
    real, honest FINDING -- never silently trusted, and never a reason to
    drop the route from the report."""
    graph = _fabric_with_two_routes()
    routes = [{"master_id": "M0", "slave_id": "S0",
              "hops": ["M0", "XBAR_A", "S0"],  # skips DEC0 -- no such edge exists
              "evidence": [{"citation": "claimed direct path"}]}]
    path_ir = build_amba_path_ir(routes, graph=graph)
    path = path_ir.paths_for("M0", "S0")[0]
    assert path.consistency_status == ROUTE_INCONSISTENT_WITH_GRAPH
    assert path.consistency_findings  # non-empty, names the missing edge
    assert any("XBAR_A" in f and "S0" in f for f in path.consistency_findings)


def test_route_hop_naming_a_node_absent_from_the_graph_is_reported():
    graph = _fabric_with_two_routes()
    routes = [{"master_id": "M0", "slave_id": "S0",
              "hops": ["M0", "GHOST_NODE", "S0"],
              "evidence": [{"citation": "bad citation"}]}]
    path_ir = build_amba_path_ir(routes, graph=graph)
    path = path_ir.paths_for("M0", "S0")[0]
    assert path.consistency_status == ROUTE_INCONSISTENT_WITH_GRAPH
    assert any("GHOST_NODE" in f for f in path.consistency_findings)


def test_multiplicity_assertion_catches_a_real_collapse_bug():
    """A deliberately-broken build (two distinct route facts folded into one
    PathIR) must be caught by the structural self-check -- proves the
    assertion actually has detection power rather than trivially passing."""
    routes = [
        {"master_id": "M0", "slave_id": "S0", "evidence": [{"citation": "route 1"}]},
        {"master_id": "M0", "slave_id": "S0", "evidence": [{"citation": "route 2"}]},
    ]
    path_ir = build_amba_path_ir(routes)
    assert_declared_multiplicity_preserved(routes, path_ir)  # real build: must not raise

    # Simulate a broken builder that collapsed the two routes into one.
    from dv_harness.amba_fabric_graph_ir import AMBAPathIR
    broken = AMBAPathIR(by_pair={("M0", "S0"): path_ir.paths_for("M0", "S0")[:1]})
    with pytest.raises(Exception):
        assert_declared_multiplicity_preserved(routes, broken)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
