"""dv_harness/amba_fabric_graph_ir.py -- AMBAFabricGraphIR + AMBAPathIR: a typed
multi-node fabric graph, and multi-path route enumeration per Master->Slave
pair, built ENTIRELY from caller-supplied duck-typed topology facts.

WHY THIS IS NOT `amba_master_slave_constraint_ir.py`
-----------------------------------------------------
That module (this session's own Batch 9) is a FLAT three-layer per-master/
slave CONSTRAINT model -- what the protocol allows, what the DUT confirms,
what a scenario may legally send, per (master, slave) pair, with no notion of
the fabric's own internal STRUCTURE. It is not imported here, and this module
does not accept its constraint-model shape either -- if a caller happens to
also hold one, it is a separate, unrelated fact set (accept it as a generic
parameter of your own code, never pass it into this module's builders).

This module answers a structurally different question: what NODES make up the
fabric between a master and a slave (a crossbar, an arbiter, a decoder, a
bridge, a width/id/clock converter, a register slice, a firewall, an address
translator, a coherent node, a memory controller), how are they CONNECTED, and
-- when the caller's own real topology evidence shows more than one physical
route between one (master, slave) pair -- ALL of those routes, kept distinct,
never collapsed into "the" path the way a flat constraint record would have
to.

EVIDENCE TRUTH RULE, APPLIED TO THIS MODULE'S OWN HIGH-RISK CLAIM
------------------------------------------------------------------
A fabric node's `kind` is never guessed from an instance name or a protocol
family -- it is a caller-declared fact, validated only against the fixed,
closed vocabulary below (`NODE_KINDS`); an unrecognized kind is a hard
`AMBAFabricGraphError`, never silently coerced to the nearest-sounding one.

The one dimension this domain most tempts a confident guess on is whether a
node's behavior is RECONFIGURABLE/DYNAMIC (a decoder whose region map can be
reprogrammed at runtime, an arbiter whose scheme can be switched). That claim
is refused outright -- `assert_no_ungrounded_reconfigurable_claim()` runs on
every node before a graph is built, and raises unless a node declaring
`reconfigurable: True` also cites real grounding evidence (a register field
that controls the reconfiguration, from `ALLOWED_RECONFIG_EVIDENCE_SOURCE_
KINDS`) -- never inferred from the node's protocol or fabric family alone.
There is no soft downgrade path for this one, the same "not a weaker
confirmation, not confirmation at all" posture
`amba_master_slave_constraint_ir.assert_no_vip_sourced_dut_capability()`
already takes for its own one hard rule.

MULTI-PATH, HONESTLY
---------------------
`build_amba_path_ir()` never traverses the graph to INVENT a route: doing so
would assert a route is real merely because the graph's edges make it
topologically possible, which is exactly the kind of routing guess this
project's AMBA family (see `amba_route_transform_predictor.py`'s own "Do not
guess routing") already forbids one level up. Every route is instead a
caller-declared `RouteFact` -- real evidence that a route exists, cited --
and multiple real `RouteFact`s naming the same (master, slave) pair are always
ALL preserved, in declaration order, never deduplicated or narrowed to one.
When a route also declares its own hop sequence and a graph was supplied,
that hop sequence is cross-checked against the graph's real edges and any
disagreement is reported as a finding on that one route -- never silently
trusted, and never a reason to drop the route.

PHASE-1 ONLY
------------
This module builds an IR a human/generator reads. It runs no build, no
simulation, no gate, and mints no approval; there is deliberately no stage
gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class AMBAFabricGraphError(Exception):
    """A fabric graph or path-set this module refuses to build: an unknown
    node kind, a dangling edge reference, a node/edge with no cited evidence,
    or a `reconfigurable`/`dynamic` claim with no real grounding evidence."""

    def __init__(self, code: str, detail=None):
        self.code = code
        self.detail = detail or {}
        super().__init__(f"{code}: {self.detail}")


# ===========================================================================
# The fixed, closed node-kind vocabulary
# ===========================================================================

#: The twelve real internal-fabric-component kinds this IR models, exactly as
#: named by the task. A tuple because it is the contract every node is
#: validated against -- never widened by a caller typing a plausible-looking
#: new string.
FABRIC_NODE_KINDS: tuple = (
    "crossbar",
    "arbiter",
    "decoder",
    "bridge",
    "width_converter",
    "id_converter",
    "clock_converter",
    "register_slice",
    "firewall",
    "address_translator",
    "coherent_node",
    "memory_controller",
)

#: A path's two ends are not internal fabric components -- they are the
#: master/slave PORTS the graph's internal nodes sit between. Modeled as a
#: separate, smaller vocabulary rather than folded into `FABRIC_NODE_KINDS`,
#: because "this node IS a crossbar" and "this node IS where a master's
#: traffic enters the fabric" are different kinds of fact and a reader must
#: never confuse an endpoint for an internal component when reading a
#: rendered node-kind table.
ENDPOINT_NODE_KINDS: tuple = ("master_endpoint", "slave_endpoint")

#: The full set a node's `kind` may legally declare.
ALL_NODE_KINDS: frozenset = frozenset(FABRIC_NODE_KINDS) | frozenset(ENDPOINT_NODE_KINDS)


# ===========================================================================
# Reconfigurable/dynamic claims -- grounded evidence only, never inferred
# ===========================================================================

#: The only sanctioned real-evidence source kinds for a `reconfigurable`/
#: `dynamic` claim -- deliberately the same shape (never the same list
#: object) as `amba_master_slave_constraint_ir.ALLOWED_DUT_EVIDENCE_SOURCE_
#: KINDS`, restated locally rather than imported: that module is this
#: session's Batch 9 and is explicitly off-limits to import from. A VIP
#: source kind is never in this set for the identical reason it is never in
#: that one -- a VIP manual/example proves what the VIP can drive, never what
#: this fabric instance actually implements.
ALLOWED_RECONFIG_EVIDENCE_SOURCE_KINDS: frozenset = frozenset({
    "rtl_register", "rtl_parameter", "rtl_port", "rtl_localparam",
    "register_map", "spec_document", "programming_guide",
    "human_confirmation", "register_rtl_trace",
})


def _is_allowed_reconfig_source(source_kind) -> bool:
    if not source_kind:
        return False
    return str(source_kind).strip().lower() in ALLOWED_RECONFIG_EVIDENCE_SOURCE_KINDS


def assert_no_ungrounded_reconfigurable_claim(nodes) -> None:
    """This module's one hard rule: a node's `attributes.reconfigurable` (or
    `attributes.dynamic`) may be `True` ONLY when the node's own `evidence`
    list carries at least one citation whose `source_kind` is a real
    register/RTL/spec/confirmation source -- never inferred from the node's
    `kind`, its protocol, or a fabric family alone. Raises before anything is
    built; there is no soft downgrade path."""
    offenders = []
    for n in nodes or ():
        attrs = n.get("attributes") if isinstance(n, dict) else getattr(n, "attributes", None)
        attrs = attrs or {}
        claimed = bool(attrs.get("reconfigurable")) or bool(attrs.get("dynamic"))
        if not claimed:
            continue
        evidence = (n.get("evidence") if isinstance(n, dict) else getattr(n, "evidence", None)) or ()
        grounded = any(
            isinstance(e, dict) and _is_allowed_reconfig_source(e.get("source_kind"))
            for e in evidence
        )
        if not grounded:
            offenders.append({
                "node_id": n.get("node_id") if isinstance(n, dict) else getattr(n, "node_id", None),
                "evidence": list(evidence),
            })
    if offenders:
        raise AMBAFabricGraphError("RECONFIGURABLE_CLAIM_WITHOUT_GROUNDED_EVIDENCE", {
            "offenders": offenders,
            "hint": "a reconfigurable/dynamic claim must cite a real register field, RTL "
                    "parameter/port, register map, spec/programming-guide document, or human "
                    "confirmation that controls the reconfiguration -- never inferred from the "
                    "node's protocol or fabric family alone"})


# ===========================================================================
# Layer 1: AMBAFabricGraphIR -- typed nodes connected by edges
# ===========================================================================

@dataclass(frozen=True)
class FabricNodeIR:
    node_id: str
    kind: str
    attributes: dict = field(default_factory=dict)
    evidence: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class FabricEdgeIR:
    edge_id: str
    from_node: str
    to_node: str
    attributes: dict = field(default_factory=dict)
    evidence: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class AMBAFabricGraphIR:
    """Nodes and edges, plus a real adjacency index built once at construction
    time so path work never has to re-scan the edge list."""
    nodes: tuple
    edges: tuple
    _by_id: dict = field(default_factory=dict, repr=False, compare=False)
    _out_edges: dict = field(default_factory=dict, repr=False, compare=False)

    def node(self, node_id: str) -> Optional[FabricNodeIR]:
        return self._by_id.get(node_id)

    def nodes_by_kind(self, kind: str) -> list:
        return [n for n in self.nodes if n.kind == kind]

    def has_edge(self, from_node: str, to_node: str) -> bool:
        return any(e.to_node == to_node for e in self._out_edges.get(from_node, ()))

    def out_edges(self, node_id: str) -> tuple:
        return self._out_edges.get(node_id, ())


def _evidence_tuple(raw) -> tuple:
    """Every evidence item as a plain dict (never a bare string silently
    accepted as if it carried a `source_kind`) -- a string is wrapped as
    `{"citation": <the string>}` so it still renders, but it can never satisfy
    `assert_no_ungrounded_reconfigurable_claim()`'s source-kind check."""
    out = []
    for item in raw or ():
        if isinstance(item, dict):
            out.append(dict(item))
        else:
            out.append({"citation": str(item)})
    return tuple(out)


def _as_mapping(item) -> dict:
    if isinstance(item, dict):
        return item
    return {
        "node_id": getattr(item, "node_id", None),
        "edge_id": getattr(item, "edge_id", None),
        "kind": getattr(item, "kind", None),
        "from_node": getattr(item, "from_node", None),
        "to_node": getattr(item, "to_node", None),
        "attributes": getattr(item, "attributes", None),
        "evidence": getattr(item, "evidence", None),
    }


def build_amba_fabric_graph(nodes, edges) -> AMBAFabricGraphIR:
    """The graph, from caller-declared nodes/edges only -- never self-derived
    from RTL. `nodes`/`edges` are generic duck-typed records: a plain dict, or
    any object exposing the same fields.

    Refuses (raises `AMBAFabricGraphError`) rather than silently repairs:
    an unrecognized `kind`, a duplicate `node_id`, a node/edge with no cited
    evidence, an edge naming a node id the caller never declared, and (via
    `assert_no_ungrounded_reconfigurable_claim()`) an ungrounded
    reconfigurable/dynamic claim."""
    node_dicts = [_as_mapping(n) for n in (nodes or ())]
    assert_no_ungrounded_reconfigurable_claim(node_dicts)

    by_id: dict = {}
    built_nodes = []
    for n in node_dicts:
        node_id = n.get("node_id")
        if not node_id:
            raise AMBAFabricGraphError("NODE_WITHOUT_ID", {"node": n})
        if node_id in by_id:
            raise AMBAFabricGraphError("DUPLICATE_NODE_ID", {"node_id": node_id})
        kind = n.get("kind")
        if kind not in ALL_NODE_KINDS:
            raise AMBAFabricGraphError("UNKNOWN_NODE_KIND", {
                "node_id": node_id, "kind": kind, "known_kinds": sorted(ALL_NODE_KINDS)})
        evidence = _evidence_tuple(n.get("evidence"))
        if not evidence:
            raise AMBAFabricGraphError("NODE_WITHOUT_EVIDENCE", {"node_id": node_id})
        node = FabricNodeIR(node_id=node_id, kind=kind,
                            attributes=dict(n.get("attributes") or {}), evidence=evidence)
        by_id[node_id] = node
        built_nodes.append(node)

    out_edges: dict = {}
    built_edges = []
    seen_edge_ids: set = set()
    for e in edges or ():
        e = _as_mapping(e)
        from_node = e.get("from_node")
        to_node = e.get("to_node")
        if from_node not in by_id:
            raise AMBAFabricGraphError("EDGE_REFERENCES_UNKNOWN_NODE", {
                "endpoint": "from_node", "value": from_node})
        if to_node not in by_id:
            raise AMBAFabricGraphError("EDGE_REFERENCES_UNKNOWN_NODE", {
                "endpoint": "to_node", "value": to_node})
        evidence = _evidence_tuple(e.get("evidence"))
        if not evidence:
            raise AMBAFabricGraphError("EDGE_WITHOUT_EVIDENCE", {
                "from_node": from_node, "to_node": to_node})
        edge_id = e.get("edge_id") or f"{from_node}__TO__{to_node}"
        if edge_id in seen_edge_ids:
            raise AMBAFabricGraphError("DUPLICATE_EDGE_ID", {"edge_id": edge_id})
        seen_edge_ids.add(edge_id)
        edge = FabricEdgeIR(edge_id=edge_id, from_node=from_node, to_node=to_node,
                            attributes=dict(e.get("attributes") or {}), evidence=evidence)
        out_edges.setdefault(from_node, []).append(edge)
        built_edges.append(edge)

    return AMBAFabricGraphIR(
        nodes=tuple(built_nodes), edges=tuple(built_edges), _by_id=by_id,
        _out_edges={k: tuple(v) for k, v in out_edges.items()})


# ===========================================================================
# Layer 2: AMBAPathIR -- multiple distinct routes per (master, slave) pair
# ===========================================================================

#: A route's hop sequence was checked against the graph's real edges and
#: every consecutive pair is a real, declared edge.
ROUTE_CONSISTENT_WITH_GRAPH = "CONSISTENT_WITH_GRAPH"
#: A route named at least one hop, or one consecutive hop pair, the graph
#: does not actually connect. Reported, never silently trusted and never a
#: reason to drop the route -- the disagreement itself is the finding.
ROUTE_INCONSISTENT_WITH_GRAPH = "INCONSISTENT_WITH_GRAPH"
#: The caller declared no fabric graph at all (or the route carries no hop
#: sequence) -- there is nothing to cross-check the route against. Honest,
#: distinct from both of the above: never reported as consistent, and never
#: reported as a finding either, since nothing was actually checked.
ROUTE_CONSISTENCY_NOT_CHECKED = "CONSISTENCY_NOT_CHECKED"

ROUTE_CONSISTENCY_STATUSES: tuple = (
    ROUTE_CONSISTENT_WITH_GRAPH, ROUTE_INCONSISTENT_WITH_GRAPH, ROUTE_CONSISTENCY_NOT_CHECKED)


@dataclass(frozen=True)
class PathIR:
    route_id: str
    master_id: str
    slave_id: str
    hops: tuple
    evidence: tuple
    consistency_status: str
    consistency_findings: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class AMBAPathIR:
    """One `PathIR` list per (master_id, slave_id) pair, in the order the
    caller declared them. `paths_for()` is the one accessor a consumer should
    use rather than reaching into `by_pair` directly, so "this pair has no
    declared route at all" (an empty list) and "this pair was never asked
    about" stay distinguishable at the call site."""
    by_pair: dict

    def pairs(self) -> list:
        return sorted(self.by_pair.keys())

    def paths_for(self, master_id: str, slave_id: str) -> tuple:
        return self.by_pair.get((master_id, slave_id), ())

    def path_count(self, master_id: str, slave_id: str) -> int:
        return len(self.paths_for(master_id, slave_id))

    def has_multiple_paths(self, master_id: str, slave_id: str) -> bool:
        return self.path_count(master_id, slave_id) > 1


def _check_hops_against_graph(hops: tuple, graph: Optional[AMBAFabricGraphIR]) -> tuple:
    """`(status, findings)` for one route's hop sequence. Never called when
    `graph` is `None` or `hops` is empty -- both of those are
    `ROUTE_CONSISTENCY_NOT_CHECKED`, decided by the caller before this runs."""
    findings = []
    for node_id in hops:
        if graph.node(node_id) is None:
            findings.append(f"hop {node_id!r} is not a node this fabric graph declares")
    for a, b in zip(hops, hops[1:]):
        if graph.node(a) is not None and graph.node(b) is not None and not graph.has_edge(a, b):
            findings.append(f"no declared edge {a!r} -> {b!r}, but the route names them as "
                            f"consecutive hops")
    if findings:
        return ROUTE_INCONSISTENT_WITH_GRAPH, tuple(findings)
    return ROUTE_CONSISTENT_WITH_GRAPH, ()


def build_amba_path_ir(route_facts, *, graph: Optional[AMBAFabricGraphIR] = None) -> AMBAPathIR:
    """Every caller-declared route, grouped by its own (master_id, slave_id)
    pair, in declaration order -- NEVER deduplicated, narrowed, or collapsed:
    when the caller's own evidence names more than one real route for one
    pair, every one of them is preserved as its own `PathIR`.

    `route_facts` is a generic duck-typed list: each entry names `master_id`,
    `slave_id`, an optional `hops` (an ordered list of node ids this route
    passes through, from the master endpoint to the slave endpoint) and a
    required, non-empty `evidence` citing why this route is believed real.
    This function never traverses `graph` to INVENT a route -- a route is
    reported only because a caller declared one, and a route's own hop
    sequence is used only to cross-check it against the graph's real edges,
    never as the SOURCE of the route."""
    by_pair: dict = {}
    for idx, r in enumerate(route_facts or ()):
        r = _as_mapping(r)
        master_id = r.get("master_id")
        slave_id = r.get("slave_id")
        if not master_id or not slave_id:
            raise AMBAFabricGraphError("ROUTE_WITHOUT_ENDPOINTS", {"route": r})
        evidence = _evidence_tuple(r.get("evidence"))
        if not evidence:
            raise AMBAFabricGraphError("ROUTE_WITHOUT_EVIDENCE", {
                "master_id": master_id, "slave_id": slave_id})
        hops = tuple(r.get("hops") or ())
        route_id = r.get("route_id") or f"{master_id}__TO__{slave_id}__ROUTE{idx}"

        if graph is None or not hops:
            status, findings = ROUTE_CONSISTENCY_NOT_CHECKED, ()
        else:
            status, findings = _check_hops_against_graph(hops, graph)

        path = PathIR(route_id=route_id, master_id=master_id, slave_id=slave_id, hops=hops,
                      evidence=evidence, consistency_status=status,
                      consistency_findings=findings)
        by_pair.setdefault((master_id, slave_id), []).append(path)

    return AMBAPathIR(by_pair={k: tuple(v) for k, v in by_pair.items()})


def assert_declared_multiplicity_preserved(route_facts, path_ir: AMBAPathIR) -> None:
    """A structural self-check, not a build-time gate: the number of `PathIR`
    entries reported for every (master, slave) pair equals exactly the number
    of route facts the caller declared for that pair -- the module's own
    proof that it never collapsed several distinct real routes into one."""
    expected: dict = {}
    for r in route_facts or ():
        r = _as_mapping(r)
        key = (r.get("master_id"), r.get("slave_id"))
        expected[key] = expected.get(key, 0) + 1
    for key, count in expected.items():
        actual = path_ir.path_count(*key)
        if actual != count:
            raise AMBAFabricGraphError("PATH_MULTIPLICITY_NOT_PRESERVED", {
                "pair": key, "declared_route_count": count, "reported_path_count": actual})


# ===========================================================================
# Reporting
# ===========================================================================

def render_fabric_graph_report(graph: AMBAFabricGraphIR) -> str:
    from dv_harness.connectivity import render_markdown_table

    node_rows = [{"node_id": n.node_id, "kind": n.kind,
                 "reconfigurable": bool(n.attributes.get("reconfigurable") or
                                       n.attributes.get("dynamic")),
                 "evidence": "; ".join(str(e.get("citation") or e) for e in n.evidence)}
                for n in graph.nodes]
    edge_rows = [{"edge_id": e.edge_id, "from": e.from_node, "to": e.to_node,
                 "evidence": "; ".join(str(ev.get("citation") or ev) for ev in e.evidence)}
                for e in graph.edges]
    lines = ["# AMBA Fabric Graph", "",
            "## Nodes", "",
            render_markdown_table(
                [("node_id", "Node"), ("kind", "Kind"),
                 ("reconfigurable", "Reconfigurable"), ("evidence", "Evidence")],
                node_rows, empty_note="(no nodes declared)"), "",
            "## Edges", "",
            render_markdown_table(
                [("edge_id", "Edge"), ("from", "From"), ("to", "To"), ("evidence", "Evidence")],
                edge_rows, empty_note="(no edges declared)"), ""]
    return "\n".join(lines)


def render_path_ir_report(path_ir: AMBAPathIR) -> str:
    from dv_harness.connectivity import render_markdown_table

    rows = []
    for master_id, slave_id in path_ir.pairs():
        for path in path_ir.paths_for(master_id, slave_id):
            rows.append({
                "master": master_id, "slave": slave_id, "route_id": path.route_id,
                "hops": " -> ".join(path.hops) if path.hops else "(not declared)",
                "consistency": path.consistency_status,
                "findings": "; ".join(path.consistency_findings) or "-",
            })
    lines = ["# AMBA Path IR -- Master/Slave Route Enumeration", "",
            render_markdown_table(
                [("master", "Master"), ("slave", "Slave"), ("route_id", "Route"),
                 ("hops", "Hops"), ("consistency", "Graph Consistency"),
                 ("findings", "Findings")],
                rows, empty_note="(no routes declared)"), ""]
    return "\n".join(lines)
