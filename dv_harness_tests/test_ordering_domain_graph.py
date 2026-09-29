"""Tests for dv_harness/ordering_domain_graph.py -- the Ordering-Domain Graph.

Core positive path (domains, membership, declared preservation edges resolve correctly), plus
real negative controls proving every honesty rule the module claims: an uncited domain/membership/
edge is refused, a reconfigurable claim with no grounding evidence is refused (the module's own
governing "never inferred from a fabric protocol alone" rule), a contradictory edge declaration is
reported rather than arbitrated, and a query with no declared evidence reports UNKNOWN/NOT_AVAILABLE
rather than a guessed answer -- the module's own most important requirement.
"""
import json
import subprocess
import sys

import pytest

from dv_harness.ordering_domain_graph import (
    FINDING_CONTRADICTORY_EDGE,
    FINDING_KINDS,
    FINDING_MULTI_DOMAIN_MEMBERSHIP,
    FINDING_ORPHAN_DOMAIN,
    FINDING_SELF_LOOP_EDGE,
    OrderingDomain,
    OrderingDomainGraphError,
    PRESERVATION_NOT_PRESERVED,
    PRESERVATION_PRESERVED,
    PRESERVATION_UNKNOWN,
    NodeMembership,
    PreservationEdge,
    build_ordering_domain_graph,
    findings_of_kind,
    is_domain_reconfigurable,
    main,
    nodes_in_domain,
    query_domain_preservation,
    query_node_domains,
    query_node_pair_ordering,
    render_graph_markdown,
)


# ===========================================================================
# Fixtures
# ===========================================================================

def _basic_domains():
    return [
        {"domain_id": "AXI_M0_DOMAIN", "evidence": "arbiter.sv:42 -- reorder buffer scoped per "
                                                      "master AXI_M0"},
        {"domain_id": "AXI_M1_DOMAIN", "evidence": "arbiter.sv:58 -- reorder buffer scoped per "
                                                      "master AXI_M1"},
        {"domain_id": "BRIDGE_DOMAIN", "evidence": "bridge_top.sv:10 -- bridge re-orders "
                                                     "completions crossing the AXI->AHB boundary"},
    ]


def _basic_memberships():
    return [
        {"node_id": "M0", "domain_id": "AXI_M0_DOMAIN",
         "evidence": "port_registry row M0: master AXI_M0"},
        {"node_id": "M1", "domain_id": "AXI_M1_DOMAIN",
         "evidence": "port_registry row M1: master AXI_M1"},
        {"node_id": "BRIDGE0", "domain_id": "AXI_M0_DOMAIN",
         "evidence": "bridge_top.sv:12 -- BRIDGE0 consumes AXI_M0_DOMAIN's stream"},
        {"node_id": "BRIDGE0", "domain_id": "BRIDGE_DOMAIN",
         "evidence": "bridge_top.sv:14 -- BRIDGE0 re-emits into BRIDGE_DOMAIN"},
    ]


def _basic_edges():
    return [
        {"from_domain": "AXI_M0_DOMAIN", "to_domain": "BRIDGE_DOMAIN",
         "preservation": PRESERVATION_PRESERVED,
         "evidence": "bridge_top.sv:20 -- bridge preserves per-master issue order into "
                     "BRIDGE_DOMAIN"},
        {"from_domain": "BRIDGE_DOMAIN", "to_domain": "AXI_M0_DOMAIN",
         "preservation": PRESERVATION_NOT_PRESERVED,
         "evidence": "bridge_top.sv:26 -- the reverse direction is NOT ordered; responses may "
                     "return out of the request order"},
    ]


# ===========================================================================
# Core positive path
# ===========================================================================

def test_build_graph_positive_path():
    graph = build_ordering_domain_graph(_basic_domains(), _basic_memberships(), _basic_edges())
    assert set(graph.domains) == {"AXI_M0_DOMAIN", "AXI_M1_DOMAIN", "BRIDGE_DOMAIN"}
    assert nodes_in_domain(graph, "AXI_M0_DOMAIN") == ["BRIDGE0", "M0"]
    assert nodes_in_domain(graph, "AXI_M1_DOMAIN") == ["M1"]

    q = query_node_domains(graph, "M0")
    assert q["status"] == "RESOLVED"
    assert q["domains"] == ["AXI_M0_DOMAIN"]

    fwd = query_domain_preservation(graph, "AXI_M0_DOMAIN", "BRIDGE_DOMAIN")
    assert fwd["status"] == PRESERVATION_PRESERVED
    rev = query_domain_preservation(graph, "BRIDGE_DOMAIN", "AXI_M0_DOMAIN")
    assert rev["status"] == PRESERVATION_NOT_PRESERVED


def test_node_pair_ordering_same_domain():
    graph = build_ordering_domain_graph(_basic_domains(), _basic_memberships(), _basic_edges())
    result = query_node_pair_ordering(graph, "M0", "BRIDGE0")
    assert result["status"] == "SAME_DOMAIN"
    assert result["shared_domains"] == ["AXI_M0_DOMAIN"]


def test_node_pair_ordering_cross_domain_uses_declared_edges():
    graph = build_ordering_domain_graph(_basic_domains(), _basic_memberships(), _basic_edges())
    result = query_node_pair_ordering(graph, "M0", "BRIDGE0")
    # BRIDGE0 also sits in BRIDGE_DOMAIN (multi-domain membership); cross_domain_pairwise reports
    # the AXI_M0_DOMAIN -> BRIDGE_DOMAIN edge even though the two nodes also share a domain.
    # The pairwise sweep is the a-domains x b-domains cross product (skipping da==db), so only
    # the forward direction from M0's domain into BRIDGE0's other domain is reported here.
    pair_statuses = {(p["from_domain"], p["to_domain"]): p["status"]
                     for p in result["cross_domain_pairwise"]}
    assert pair_statuses[("AXI_M0_DOMAIN", "BRIDGE_DOMAIN")] == PRESERVATION_PRESERVED
    assert ("BRIDGE_DOMAIN", "AXI_M0_DOMAIN") not in pair_statuses

    # the reverse direction is independently queryable and correctly resolves to the other
    # declared edge, proving both directions really are tracked separately.
    reverse = query_domain_preservation(graph, "BRIDGE_DOMAIN", "AXI_M0_DOMAIN")
    assert reverse["status"] == PRESERVATION_NOT_PRESERVED


def test_node_pair_ordering_cross_domain_only():
    graph = build_ordering_domain_graph(_basic_domains(), _basic_memberships(), _basic_edges())
    result = query_node_pair_ordering(graph, "M0", "M1")
    assert result["status"] == "CROSS_DOMAIN"
    assert result["shared_domains"] == []
    pair = result["cross_domain_pairwise"][0]
    assert pair["from_domain"] == "AXI_M0_DOMAIN"
    assert pair["to_domain"] == "AXI_M1_DOMAIN"
    # no edge was ever declared between AXI_M0_DOMAIN and AXI_M1_DOMAIN -- honest UNKNOWN.
    assert pair["status"] == PRESERVATION_UNKNOWN
    assert "no ordering-preservation edge declared" in pair["reason"]


def test_multi_domain_membership_finding_recorded():
    graph = build_ordering_domain_graph(_basic_domains(), _basic_memberships(), _basic_edges())
    hits = findings_of_kind(graph, FINDING_MULTI_DOMAIN_MEMBERSHIP)
    assert len(hits) == 1
    assert hits[0]["node_id"] == "BRIDGE0"
    assert set(hits[0]["domains"]) == {"AXI_M0_DOMAIN", "BRIDGE_DOMAIN"}


def test_orphan_domain_finding_real_case():
    domains = _basic_domains() + [{
        "domain_id": "UNUSED_DOMAIN",
        "evidence": "spec.md:5 -- a domain declared for future use, no node assigned yet"}]
    graph = build_ordering_domain_graph(domains, _basic_memberships(), _basic_edges())
    hits = findings_of_kind(graph, FINDING_ORPHAN_DOMAIN)
    assert {h["domain_id"] for h in hits} == {"UNUSED_DOMAIN"}


def test_self_loop_edge_finding():
    edges = _basic_edges() + [{
        "from_domain": "AXI_M0_DOMAIN", "to_domain": "AXI_M0_DOMAIN",
        "preservation": PRESERVATION_PRESERVED,
        "evidence": "arbiter.sv:44 -- trivially self-consistent"}]
    graph = build_ordering_domain_graph(_basic_domains(), _basic_memberships(), edges)
    hits = findings_of_kind(graph, FINDING_SELF_LOOP_EDGE)
    assert len(hits) == 1
    assert hits[0]["domain_id"] == "AXI_M0_DOMAIN"


def test_is_domain_reconfigurable_true_with_grounding():
    domains = _basic_domains() + [{
        "domain_id": "DYNAMIC_DOMAIN",
        "evidence": "arbiter.sv:80 -- domain scope",
        "reconfigurable": True,
        "reconfiguration_evidence": "regmap.json: REORDER_CTRL.DOMAIN_SEL field remaps which "
                                    "master feeds this domain at runtime"}]
    graph = build_ordering_domain_graph(domains, [], [])
    result = is_domain_reconfigurable(graph, "DYNAMIC_DOMAIN")
    assert result["status"] == "RESOLVED"
    assert result["reconfigurable"] is True
    assert "REORDER_CTRL" in result["reconfiguration_evidence"]


def test_is_domain_reconfigurable_false_for_static_domain():
    graph = build_ordering_domain_graph(_basic_domains(), [], [])
    result = is_domain_reconfigurable(graph, "AXI_M0_DOMAIN")
    assert result["reconfigurable"] is False


def test_render_graph_markdown_smoke():
    graph = build_ordering_domain_graph(_basic_domains(), _basic_memberships(), _basic_edges())
    text = render_graph_markdown(graph)
    assert "Ordering Domains" in text
    assert "Preservation Edges" in text
    assert "AXI_M0_DOMAIN" in text


# ===========================================================================
# Negative controls -- the module's whole reason to exist
# ===========================================================================

def test_domain_with_no_evidence_is_refused():
    with pytest.raises(OrderingDomainGraphError, match="evidence citation"):
        build_ordering_domain_graph(
            [{"domain_id": "NO_EVIDENCE_DOMAIN"}], [], [])


def test_domain_with_blank_evidence_is_refused():
    with pytest.raises(OrderingDomainGraphError, match="evidence citation"):
        build_ordering_domain_graph(
            [{"domain_id": "NO_EVIDENCE_DOMAIN", "evidence": "   "}], [], [])


def test_membership_with_no_evidence_is_refused():
    with pytest.raises(OrderingDomainGraphError, match="evidence citation"):
        build_ordering_domain_graph(
            _basic_domains(),
            [{"node_id": "M0", "domain_id": "AXI_M0_DOMAIN"}],
            [])


def test_edge_with_no_evidence_is_refused():
    with pytest.raises(OrderingDomainGraphError, match="evidence citation"):
        build_ordering_domain_graph(
            _basic_domains(), [],
            [{"from_domain": "AXI_M0_DOMAIN", "to_domain": "BRIDGE_DOMAIN",
              "preservation": PRESERVATION_PRESERVED}])


def test_reconfigurable_claim_with_no_grounding_evidence_is_refused():
    """The module's own governing rule: a 'reconfigurable'/'dynamic' claim must be grounded in
    real evidence that reconfiguration exists (e.g. a real register field), never inferred from a
    fabric protocol alone. Declaring reconfigurable=True with no reconfiguration_evidence is
    exactly the un-grounded claim this must refuse."""
    with pytest.raises(OrderingDomainGraphError, match="never be inferred from a fabric protocol"):
        build_ordering_domain_graph(
            [{"domain_id": "DYNAMIC_DOMAIN", "evidence": "arbiter.sv:80",
              "reconfigurable": True}],
            [], [])


def test_reconfigurable_claim_with_blank_grounding_evidence_is_refused():
    with pytest.raises(OrderingDomainGraphError):
        build_ordering_domain_graph(
            [{"domain_id": "DYNAMIC_DOMAIN", "evidence": "arbiter.sv:80",
              "reconfigurable": True, "reconfiguration_evidence": "   "}],
            [], [])


def test_duplicate_domain_id_is_refused():
    dup = _basic_domains() + [{"domain_id": "AXI_M0_DOMAIN", "evidence": "second declaration"}]
    with pytest.raises(OrderingDomainGraphError, match="duplicate domain_id"):
        build_ordering_domain_graph(dup, [], [])


def test_membership_naming_undeclared_domain_is_refused():
    with pytest.raises(OrderingDomainGraphError, match="never declared"):
        build_ordering_domain_graph(
            _basic_domains(),
            [{"node_id": "M9", "domain_id": "GHOST_DOMAIN", "evidence": "some evidence"}],
            [])


def test_edge_naming_undeclared_domain_is_refused():
    with pytest.raises(OrderingDomainGraphError, match="never declared"):
        build_ordering_domain_graph(
            _basic_domains(), [],
            [{"from_domain": "AXI_M0_DOMAIN", "to_domain": "GHOST_DOMAIN",
              "preservation": PRESERVATION_PRESERVED, "evidence": "some evidence"}])


def test_edge_with_unrecognized_preservation_value_is_refused():
    with pytest.raises(OrderingDomainGraphError, match="unrecognized preservation value"):
        build_ordering_domain_graph(
            _basic_domains(), [],
            [{"from_domain": "AXI_M0_DOMAIN", "to_domain": "BRIDGE_DOMAIN",
              "preservation": "SOMETIMES", "evidence": "some evidence"}])


def test_contradictory_edge_is_reported_not_arbitrated():
    edges = [
        {"from_domain": "AXI_M0_DOMAIN", "to_domain": "BRIDGE_DOMAIN",
         "preservation": PRESERVATION_PRESERVED, "evidence": "arbiter.sv:20: preserved"},
        {"from_domain": "AXI_M0_DOMAIN", "to_domain": "BRIDGE_DOMAIN",
         "preservation": PRESERVATION_NOT_PRESERVED, "evidence": "bridge_top.sv:99: not preserved"},
    ]
    graph = build_ordering_domain_graph(_basic_domains(), [], edges)
    hits = findings_of_kind(graph, FINDING_CONTRADICTORY_EDGE)
    assert len(hits) == 1
    assert hits[0]["from_domain"] == "AXI_M0_DOMAIN"
    assert hits[0]["to_domain"] == "BRIDGE_DOMAIN"
    assert set(hits[0]["declared_values"]) == {PRESERVATION_PRESERVED, PRESERVATION_NOT_PRESERVED}

    # The resolved edge must read UNKNOWN -- never arbitrated to either declared side.
    result = query_domain_preservation(graph, "AXI_M0_DOMAIN", "BRIDGE_DOMAIN")
    assert result["status"] == PRESERVATION_UNKNOWN
    assert len(result["evidence"]) == 2


def test_query_for_unknown_domain_reports_unknown_not_a_guess():
    graph = build_ordering_domain_graph(_basic_domains(), [], [])
    result = query_domain_preservation(graph, "AXI_M0_DOMAIN", "NEVER_DECLARED")
    assert result["status"] == "UNKNOWN_DOMAIN"
    assert "NEVER_DECLARED" in result["reason"]


def test_query_for_undeclared_edge_reports_unknown_never_a_reverse_or_transitive_guess():
    """Only a directly-declared edge answers the question -- a reverse edge must never be
    silently reused for the forward direction, and there is no third-domain transitivity."""
    graph = build_ordering_domain_graph(
        _basic_domains(), [],
        [{"from_domain": "BRIDGE_DOMAIN", "to_domain": "AXI_M0_DOMAIN",
          "preservation": PRESERVATION_PRESERVED, "evidence": "reverse direction only"}])
    forward = query_domain_preservation(graph, "AXI_M0_DOMAIN", "BRIDGE_DOMAIN")
    assert forward["status"] == PRESERVATION_UNKNOWN
    assert forward["evidence"] == []


def test_query_node_domains_for_undeclared_node_reports_honest_absence():
    graph = build_ordering_domain_graph(_basic_domains(), _basic_memberships(), _basic_edges())
    result = query_node_domains(graph, "GHOST_MASTER")
    assert result["status"] == "NO_DOMAIN_DECLARED"
    assert result["domains"] == []


def test_node_pair_ordering_unknown_node():
    graph = build_ordering_domain_graph(_basic_domains(), _basic_memberships(), _basic_edges())
    result = query_node_pair_ordering(graph, "M0", "GHOST_MASTER")
    assert result["status"] == "UNKNOWN_NODE"
    assert "GHOST_MASTER" in str(result["reason"])


def test_is_domain_reconfigurable_unknown_domain():
    graph = build_ordering_domain_graph(_basic_domains(), [], [])
    result = is_domain_reconfigurable(graph, "GHOST_DOMAIN")
    assert result["status"] == "UNKNOWN_DOMAIN"


def test_nodes_in_domain_raises_for_undeclared_domain():
    graph = build_ordering_domain_graph(_basic_domains(), [], [])
    with pytest.raises(OrderingDomainGraphError, match="never declared"):
        nodes_in_domain(graph, "GHOST_DOMAIN")


def test_findings_of_kind_raises_for_unknown_kind():
    graph = build_ordering_domain_graph(_basic_domains(), [], [])
    with pytest.raises(OrderingDomainGraphError, match="unrecognized finding kind"):
        findings_of_kind(graph, "SOMETHING_ELSE")


def test_dataclasses_can_be_constructed_directly_and_reused():
    dom = OrderingDomain(domain_id="D1", evidence="ev")
    mem = NodeMembership(node_id="N1", domain_id="D1", evidence="ev2")
    edge = PreservationEdge(from_domain="D1", to_domain="D1",
                             preservation=PRESERVATION_PRESERVED, evidence="ev3")
    graph = build_ordering_domain_graph([dom], [mem], [edge])
    assert "D1" in graph.domains


def test_graph_to_dict_is_json_serializable():
    graph = build_ordering_domain_graph(_basic_domains(), _basic_memberships(), _basic_edges())
    payload = graph.to_dict()
    json.dumps(payload)  # must not raise
    assert "AXI_M0_DOMAIN" in payload["domains"]


# ===========================================================================
# CLI
# ===========================================================================

def test_cli_json_output(tmp_path):
    facts = {"domains": _basic_domains(), "memberships": _basic_memberships(),
             "edges": _basic_edges()}
    facts_file = tmp_path / "facts.json"
    facts_file.write_text(json.dumps(facts), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.ordering_domain_graph",
         "--facts-file", str(facts_file), "--json"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "AXI_M0_DOMAIN" in payload["domains"]


def test_cli_markdown_output(tmp_path):
    facts = {"domains": _basic_domains(), "memberships": _basic_memberships(),
             "edges": _basic_edges()}
    facts_file = tmp_path / "facts.json"
    facts_file.write_text(json.dumps(facts), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.ordering_domain_graph",
         "--facts-file", str(facts_file)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "Ordering Domains" in result.stdout


def test_main_function_returns_zero(tmp_path):
    facts = {"domains": _basic_domains(), "memberships": [], "edges": []}
    facts_file = tmp_path / "facts.json"
    facts_file.write_text(json.dumps(facts), encoding="utf-8")
    rc = main(["--facts-file", str(facts_file), "--json"])
    assert rc == 0
