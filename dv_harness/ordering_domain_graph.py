"""dv_harness/ordering_domain_graph.py -- the Ordering-Domain Graph: which real ordering
domains exist across a fabric's nodes/masters, which node belongs to which domain, and which
declared ordering-preservation relationships hold BETWEEN domains -- built strictly from
caller-supplied, evidence-cited facts. Never inferred from a fabric protocol name, a topology
shape, or a master/slave naming convention.

THE GAP THIS CLOSES. `amba_route_transform_predictor.detect_ordering_domain()` already answers a
narrower, PER-ROUTE question: given one (master, slave) pair, is that one route's own transaction
stream in-order or out-of-order (from whether the protocol carries a transaction id). It has no
concept of an ordering domain as a first-class, named object with real MEMBERSHIP, and no concept
of a relationship BETWEEN two domains -- "does domain A's completion order say anything about
domain B's". `arbitration_policy_ir.py` (Batch 9, deliberately not imported here) answers a
different question again: it classifies a fabric's flat, per-arbiter ARBITRATION SCHEME
(FIXED_PRIORITY/ROUND_ROBIN/...) from evidence text, never a cross-domain ordering relationship.
Neither module builds a graph of domains, memberships and inter-domain edges, and a repo-wide grep
(`ordering_domain_graph`/`OrderingDomainGraph`/`preservation_edge`) returned zero hits before this
module.

THE EVIDENCE TRUTH RULE, APPLIED LITERALLY. Every domain, every node-to-domain membership, and
every inter-domain preservation edge this module ever reports is something the CALLER declared with
a real evidence citation (an RTL comment, an arbiter/interconnect spec paragraph, a register-field
description) -- never something this module infers from a node's name, a protocol family, or the
topology shape alone. A domain, membership or edge declaration carrying no evidence, or an empty
one, is a hard REFUSAL (`OrderingDomainGraphError`), not a silently-accepted bare claim -- the same
discipline `security_policy_ir.py` already applies to an uncited access rule. A domain claiming to
be RECONFIGURABLE/DYNAMIC (its node membership, or the domains it participates in, can change at
runtime) is refused UNLESS it separately cites real evidence that reconfiguration exists -- a real
register field controlling remapping/decode, a documented mode switch -- never inferred from the
fabric's protocol family alone, per this session's own governing rule on that exact claim shape.

WHAT THE GRAPH ANSWERS, AND WHAT IT REFUSES TO GUESS. `query_domain_preservation()` answers
"does domain A's ordering carry any guarantee into domain B" ONLY from a directly-declared edge in
that exact direction. It NEVER infers a reverse-direction guarantee from a forward one (a bridge can
easily preserve order one way and reorder the other), and it NEVER computes a transitive closure
across three or more domains (A preserves into B, B preserves into C, does NOT imply A preserves
into C -- that is an additional fact about the compare/merge stage between B and C which nobody
declared). Both of those refusals are the module's whole reason to exist rather than a smaller,
transitively-closed convenience function: a fabricated transitive/reverse guarantee is exactly the
kind of confident wrong answer a scoreboard implementer would trust and be burned by.

TWO KINDS OF DISAGREEING EVIDENCE, NEVER SILENTLY RESOLVED. Two declarations of the SAME directed
edge `(from_domain, to_domain)` that disagree on PRESERVED/NOT_PRESERVED/UNKNOWN are a real,
reported `CONTRADICTORY_EDGE` finding -- the resolved edge reads UNKNOWN, citing both conflicting
declarations, and this module never arbitrates which one is right (the same ARBITRATION boundary
`requirement_contract.py`/`design_knowledge_correlation.py`/`security_policy_ir.py` already keep for
their own conflicting-claim findings). A node declared a member of more than one domain is NOT an
error -- a bridge component genuinely can sit in two ordering domains at once -- but it is always
surfaced as a real `MULTI_DOMAIN_MEMBERSHIP` finding rather than silently merged away, since a reader
comparing two transactions through that node needs to know both domains are in play.

REUSE / FILE-SAFETY NOTE. This module imports nothing from `arbitration_policy_ir.py` (named
explicitly out of scope for this task) and nothing from any other new module in this batch. It
reuses `dv_harness.connectivity.render_markdown_table()` (this repo's one parameterized table
renderer, pre-existing and outside this batch) for its optional markdown rendering, and
`dv_harness.models.Status` (also pre-existing) solely to assert this module's own vocabulary shares
no token with a real stage verdict. Every domain/membership/edge input is a plain, duck-typed dict
(or any attribute-bearing object), read through a small `.get()`-or-`getattr()` reader mirroring the
same convention `arbitration_policy_ir._lookup()`/`requirement_risk_ir._lookup()` already use,
re-derived locally rather than imported.

WHAT THIS MODULE DELIBERATELY DOES NOT DO: it discovers no fabric topology, port, or master/slave
fact of its own (a caller's own AMBA-family discovery pipeline supplies node identity); it never
computes a reorder-window depth or an outstanding-transaction bound; it never decides which of two
conflicting evidence citations is correct; it writes nothing, gates nothing, and approves nothing.
There is deliberately no stage gate and no `dv-harness` CLI verb registered in `cli.py`/`gates.py`
(both are out of this batch's file-safety scope) -- the front door is this module's own Python API
plus a small `python -m dv_harness.ordering_domain_graph` reporting wrapper.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

#: The three honest preservation verdicts a declared inter-domain edge can carry. PRESERVED and
#: NOT_PRESERVED are real, cited claims; UNKNOWN is reserved for "no edge declared in this exact
#: direction" or "two declared edges for this direction disagree" -- never silently defaulted to
#: either PRESERVED or NOT_PRESERVED.
PRESERVATION_PRESERVED = "PRESERVED"
PRESERVATION_NOT_PRESERVED = "NOT_PRESERVED"
PRESERVATION_UNKNOWN = "UNKNOWN"
PRESERVATION_VALUES: Tuple[str, ...] = (
    PRESERVATION_PRESERVED, PRESERVATION_NOT_PRESERVED, PRESERVATION_UNKNOWN,
)

#: The four real finding kinds this module can surface while building a graph. Fixed and
#: exhaustive -- a caller iterates this, never a hand-rolled list.
FINDING_MULTI_DOMAIN_MEMBERSHIP = "MULTI_DOMAIN_MEMBERSHIP"
FINDING_CONTRADICTORY_EDGE = "CONTRADICTORY_EDGE"
FINDING_ORPHAN_DOMAIN = "ORPHAN_DOMAIN"
FINDING_SELF_LOOP_EDGE = "SELF_LOOP_EDGE"
FINDING_KINDS: Tuple[str, ...] = (
    FINDING_MULTI_DOMAIN_MEMBERSHIP, FINDING_CONTRADICTORY_EDGE,
    FINDING_ORPHAN_DOMAIN, FINDING_SELF_LOOP_EDGE,
)

#: Node/domain-pair query statuses distinct from the three preservation values above -- a query can
#: fail to resolve for reasons that have nothing to do with what an existing edge says.
QUERY_UNKNOWN_DOMAIN = "UNKNOWN_DOMAIN"
QUERY_UNKNOWN_NODE = "UNKNOWN_NODE"
QUERY_RESOLVED = "RESOLVED"
QUERY_SAME_DOMAIN = "SAME_DOMAIN"
QUERY_CROSS_DOMAIN = "CROSS_DOMAIN"


class OrderingDomainGraphError(Exception):
    """Raised only for a genuinely malformed or uncited caller declaration (a domain/membership/
    edge missing its required identity or evidence field, a duplicate domain id, an unrecognized
    preservation value, a reconfigurable claim with no grounding evidence, a membership/edge naming
    a domain nobody declared) -- never for an honest absence of evidence about a QUERY, which is
    always a reported UNKNOWN/NOT_AVAILABLE-shaped result instead."""


def _lookup(obj: Any, key: str) -> Any:
    """Duck-typed read of one field from `obj`: a Mapping (via `.get`) or any attribute-bearing
    object. Never raises on an object with neither -- returns None, same as a missing key. Mirrors
    `arbitration_policy_ir._lookup()`'s contract; re-derived locally per this batch's file-safety
    scope (no cross-import between new modules in this batch)."""
    if obj is None:
        return None
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except TypeError:
            pass
    return getattr(obj, key, None)


def _non_empty_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


# ===========================================================================
# Declarations -- every field a real, caller-cited fact; never guessed here.
# ===========================================================================

@dataclass
class OrderingDomain:
    """One real, named ordering domain. `evidence` is mandatory: an ordering domain is a claim
    about how a fabric's transactions are grouped for compare/order-checking purposes, and it must
    be grounded in real evidence (an arbiter/interconnect spec paragraph, an RTL comment describing
    a reorder buffer's scope) rather than asserted bare.

    `reconfigurable=True` additionally REQUIRES `reconfiguration_evidence` naming the real control
    mechanism (a register field, a documented mode switch) that lets this domain's membership or
    scope change at runtime. A fabric protocol family alone is never sufficient grounding for that
    claim -- this is the one rule this dataclass exists to enforce structurally rather than merely
    describe."""
    domain_id: str
    evidence: str
    description: Optional[str] = None
    reconfigurable: bool = False
    reconfiguration_evidence: Optional[str] = None

    def __post_init__(self) -> None:
        domain_id = _non_empty_str(self.domain_id)
        if domain_id is None:
            raise OrderingDomainGraphError(
                "an ordering domain must be declared with a non-empty domain_id")
        self.domain_id = domain_id
        evidence = _non_empty_str(self.evidence)
        if evidence is None:
            raise OrderingDomainGraphError(
                f"domain {self.domain_id!r} declared with no evidence citation -- an ordering "
                f"domain's existence must be grounded in real evidence, never asserted bare")
        self.evidence = evidence
        if self.reconfigurable and _non_empty_str(self.reconfiguration_evidence) is None:
            raise OrderingDomainGraphError(
                f"domain {self.domain_id!r} declared reconfigurable/dynamic with no cited "
                f"evidence that reconfiguration actually exists (e.g. a real register field "
                f"controlling decode/remap, a documented mode switch) -- a 'reconfigurable' or "
                f"'dynamic' claim must never be inferred from a fabric protocol alone")
        if self.reconfiguration_evidence is not None:
            self.reconfiguration_evidence = _non_empty_str(self.reconfiguration_evidence)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NodeMembership:
    """One real, cited claim that `node_id` (a fabric master/node identity a caller's own
    discovery pipeline established) belongs to `domain_id`."""
    node_id: str
    domain_id: str
    evidence: str

    def __post_init__(self) -> None:
        node_id = _non_empty_str(self.node_id)
        if node_id is None:
            raise OrderingDomainGraphError(
                "a node membership must be declared with a non-empty node_id")
        self.node_id = node_id
        domain_id = _non_empty_str(self.domain_id)
        if domain_id is None:
            raise OrderingDomainGraphError(
                f"node {self.node_id!r}'s membership declaration names no domain_id")
        self.domain_id = domain_id
        evidence = _non_empty_str(self.evidence)
        if evidence is None:
            raise OrderingDomainGraphError(
                f"node {self.node_id!r}'s membership in domain {self.domain_id!r} carries no "
                f"evidence citation -- membership must be grounded in real evidence, never "
                f"asserted bare")
        self.evidence = evidence

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PreservationEdge:
    """One real, cited, DIRECTED claim about ordering preservation from `from_domain` into
    `to_domain`. Directed on purpose: a bridge can preserve order one way and reorder the other, so
    a caller must declare each direction separately rather than one edge standing for both."""
    from_domain: str
    to_domain: str
    preservation: str
    evidence: str

    def __post_init__(self) -> None:
        from_domain = _non_empty_str(self.from_domain)
        if from_domain is None:
            raise OrderingDomainGraphError(
                "a preservation edge must declare a non-empty from_domain")
        self.from_domain = from_domain
        to_domain = _non_empty_str(self.to_domain)
        if to_domain is None:
            raise OrderingDomainGraphError(
                "a preservation edge must declare a non-empty to_domain")
        self.to_domain = to_domain
        if self.preservation not in PRESERVATION_VALUES:
            raise OrderingDomainGraphError(
                f"preservation edge {self.from_domain!r} -> {self.to_domain!r} declares an "
                f"unrecognized preservation value {self.preservation!r}; must be one of "
                f"{PRESERVATION_VALUES}")
        evidence = _non_empty_str(self.evidence)
        if evidence is None:
            raise OrderingDomainGraphError(
                f"preservation edge {self.from_domain!r} -> {self.to_domain!r} carries no "
                f"evidence citation -- a preservation claim (including a declared UNKNOWN one) "
                f"must be grounded in real evidence, never asserted bare")
        self.evidence = evidence

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _to_domain(raw: Any) -> OrderingDomain:
    if isinstance(raw, OrderingDomain):
        return raw
    return OrderingDomain(
        domain_id=_lookup(raw, "domain_id"),
        evidence=_lookup(raw, "evidence"),
        description=_lookup(raw, "description"),
        reconfigurable=bool(_lookup(raw, "reconfigurable") or False),
        reconfiguration_evidence=_lookup(raw, "reconfiguration_evidence"))


def _to_membership(raw: Any) -> NodeMembership:
    if isinstance(raw, NodeMembership):
        return raw
    return NodeMembership(
        node_id=_lookup(raw, "node_id"),
        domain_id=_lookup(raw, "domain_id"),
        evidence=_lookup(raw, "evidence"))


def _to_edge(raw: Any) -> PreservationEdge:
    if isinstance(raw, PreservationEdge):
        return raw
    return PreservationEdge(
        from_domain=_lookup(raw, "from_domain"),
        to_domain=_lookup(raw, "to_domain"),
        preservation=_lookup(raw, "preservation"),
        evidence=_lookup(raw, "evidence"))


# ===========================================================================
# The assembled graph
# ===========================================================================

@dataclass
class OrderingDomainGraph:
    """The full, resolved ordering-domain graph: real declared domains, real node-to-domain
    membership, and the resolved (possibly-conflicting) inter-domain preservation edges, plus every
    finding surfaced while assembling them."""
    domains: Dict[str, OrderingDomain]
    memberships: List[NodeMembership]
    node_domains: Dict[str, Set[str]]
    domain_nodes: Dict[str, Set[str]]
    edges: Dict[Tuple[str, str], Dict[str, Any]]
    findings: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domains": {d: dom.to_dict() for d, dom in self.domains.items()},
            "memberships": [m.to_dict() for m in self.memberships],
            "node_domains": {n: sorted(ds) for n, ds in self.node_domains.items()},
            "domain_nodes": {d: sorted(ns) for d, ns in self.domain_nodes.items()},
            "edges": [
                {"from_domain": f, "to_domain": t, **v}
                for (f, t), v in sorted(self.edges.items())
            ],
            "findings": list(self.findings),
        }


def build_ordering_domain_graph(domain_decls: Optional[Sequence[Any]],
                                 membership_decls: Optional[Sequence[Any]] = None,
                                 edge_decls: Optional[Sequence[Any]] = None
                                 ) -> OrderingDomainGraph:
    """Assemble the graph from real caller declarations. Raises `OrderingDomainGraphError` on any
    genuinely malformed/uncited declaration or a membership/edge naming a domain nobody declared;
    never silently drops or repairs one. A contradiction between two declared edges for the SAME
    directed pair is NOT raised -- it is a real, reported finding, and the resolved edge reads
    UNKNOWN citing both sides, per this module's own arbitration boundary."""
    domains: Dict[str, OrderingDomain] = {}
    for raw in domain_decls or ():
        dom = _to_domain(raw)
        if dom.domain_id in domains:
            raise OrderingDomainGraphError(
                f"duplicate domain_id {dom.domain_id!r} -- an ordering domain must be declared "
                f"exactly once")
        domains[dom.domain_id] = dom

    memberships: List[NodeMembership] = []
    node_domains: Dict[str, Set[str]] = {}
    domain_nodes: Dict[str, Set[str]] = {d: set() for d in domains}
    for raw in membership_decls or ():
        m = _to_membership(raw)
        if m.domain_id not in domains:
            raise OrderingDomainGraphError(
                f"node {m.node_id!r} declares membership in domain {m.domain_id!r}, which was "
                f"never declared -- a membership can only name a real, declared domain")
        memberships.append(m)
        node_domains.setdefault(m.node_id, set()).add(m.domain_id)
        domain_nodes.setdefault(m.domain_id, set()).add(m.node_id)

    findings: List[Dict[str, Any]] = []
    for node_id, ds in sorted(node_domains.items()):
        if len(ds) > 1:
            findings.append({
                "kind": FINDING_MULTI_DOMAIN_MEMBERSHIP,
                "node_id": node_id, "domains": sorted(ds),
                "reason": f"node {node_id!r} is declared a member of more than one ordering "
                          f"domain ({sorted(ds)}) -- a real, legitimate shape for a bridge "
                          f"component, but a comparison touching this node must consider every "
                          f"one of these domains, never only one"})
    for domain_id, ns in sorted(domain_nodes.items()):
        if not ns:
            findings.append({
                "kind": FINDING_ORPHAN_DOMAIN, "domain_id": domain_id,
                "reason": f"domain {domain_id!r} was declared with no node membership at all"})

    raw_edges: Dict[Tuple[str, str], List[PreservationEdge]] = {}
    for raw in edge_decls or ():
        e = _to_edge(raw)
        if e.from_domain not in domains:
            raise OrderingDomainGraphError(
                f"preservation edge names from_domain {e.from_domain!r}, which was never "
                f"declared")
        if e.to_domain not in domains:
            raise OrderingDomainGraphError(
                f"preservation edge names to_domain {e.to_domain!r}, which was never declared")
        raw_edges.setdefault((e.from_domain, e.to_domain), []).append(e)

    edges: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for pair, decls in sorted(raw_edges.items()):
        f, t = pair
        if f == t:
            findings.append({
                "kind": FINDING_SELF_LOOP_EDGE, "domain_id": f,
                "reason": f"a preservation edge was declared from domain {f!r} to itself"})
        values = {d.preservation for d in decls}
        if len(values) > 1:
            findings.append({
                "kind": FINDING_CONTRADICTORY_EDGE, "from_domain": f, "to_domain": t,
                "declared_values": sorted(values),
                "evidence": [d.evidence for d in decls],
                "reason": f"{len(decls)} declarations of the {f!r} -> {t!r} preservation edge "
                          f"disagree ({sorted(values)}); resolved as UNKNOWN rather than "
                          f"arbitrated"})
            edges[pair] = {
                "status": PRESERVATION_UNKNOWN,
                "evidence": [d.evidence for d in decls],
                "reason": "conflicting declarations for this direction; see findings",
            }
        else:
            edges[pair] = {
                "status": decls[0].preservation,
                "evidence": [d.evidence for d in decls],
                "reason": None,
            }

    return OrderingDomainGraph(
        domains=domains, memberships=memberships,
        node_domains=node_domains, domain_nodes=domain_nodes,
        edges=edges, findings=findings)


# ===========================================================================
# Queries -- every one reports UNKNOWN with a real reason rather than guessing.
# ===========================================================================

def nodes_in_domain(graph: OrderingDomainGraph, domain_id: str) -> List[str]:
    """Every node declared a member of `domain_id`, sorted. Raises if `domain_id` was never
    declared -- a lookup against a nonexistent domain is a caller-usage error, not a fact query."""
    if domain_id not in graph.domains:
        raise OrderingDomainGraphError(f"domain {domain_id!r} was never declared")
    return sorted(graph.domain_nodes.get(domain_id, ()))


def query_node_domains(graph: OrderingDomainGraph, node_id: str) -> Dict[str, Any]:
    """Which declared domain(s) `node_id` belongs to. `NO_DOMAIN_DECLARED` (never an empty-list
    silently read as "no domain exists") when nobody ever declared a membership for this node."""
    domains = sorted(graph.node_domains.get(node_id, ()))
    if not domains:
        return {"node_id": node_id, "status": "NO_DOMAIN_DECLARED", "domains": [],
                "reason": f"no membership declaration found for node {node_id!r}"}
    return {"node_id": node_id, "status": QUERY_RESOLVED, "domains": domains}


def query_domain_preservation(graph: OrderingDomainGraph, from_domain: str,
                               to_domain: str) -> Dict[str, Any]:
    """Does ordering preservation hold from `from_domain` into `to_domain`, from a DIRECTLY
    declared edge only. Never infers the reverse direction from a forward declaration, and never
    computes a transitive answer through a third domain -- both would fabricate a guarantee nobody
    actually declared."""
    if from_domain not in graph.domains or to_domain not in graph.domains:
        unknown = [d for d in (from_domain, to_domain) if d not in graph.domains]
        return {"from_domain": from_domain, "to_domain": to_domain,
                "status": QUERY_UNKNOWN_DOMAIN, "evidence": [],
                "reason": f"domain(s) never declared: {unknown}"}
    edge = graph.edges.get((from_domain, to_domain))
    if edge is None:
        return {"from_domain": from_domain, "to_domain": to_domain,
                "status": PRESERVATION_UNKNOWN, "evidence": [],
                "reason": f"no ordering-preservation edge declared from {from_domain!r} to "
                          f"{to_domain!r}; preservation is never inferred from a reverse-"
                          f"direction edge or from transitivity through a third domain"}
    return {"from_domain": from_domain, "to_domain": to_domain,
            "status": edge["status"], "evidence": list(edge["evidence"]),
            "reason": edge.get("reason")}


def query_node_pair_ordering(graph: OrderingDomainGraph, node_a: str,
                              node_b: str) -> Dict[str, Any]:
    """The ordering relationship between two nodes: SAME_DOMAIN if they share at least one declared
    domain (and the shared set is reported so a reader can see it directly), CROSS_DOMAIN with the
    per-domain-pair preservation lookups across every declared domain either node belongs to
    (covering the MULTI_DOMAIN_MEMBERSHIP case honestly rather than picking one domain per node),
    or UNKNOWN_NODE when either node has no declared membership at all."""
    a_domains = graph.node_domains.get(node_a, set())
    b_domains = graph.node_domains.get(node_b, set())
    missing = [n for n, ds in ((node_a, a_domains), (node_b, b_domains)) if not ds]
    if missing:
        return {"node_a": node_a, "node_b": node_b, "status": QUERY_UNKNOWN_NODE,
                "reason": f"no domain membership declared for: {missing}"}
    shared = sorted(a_domains & b_domains)
    pairwise: List[Dict[str, Any]] = []
    for da in sorted(a_domains):
        for db in sorted(b_domains):
            if da == db:
                continue
            pairwise.append({"from_domain": da, "to_domain": db,
                              **query_domain_preservation(graph, da, db)})
    return {"node_a": node_a, "node_b": node_b,
            "status": QUERY_SAME_DOMAIN if shared else QUERY_CROSS_DOMAIN,
            "shared_domains": shared, "cross_domain_pairwise": pairwise}


def is_domain_reconfigurable(graph: OrderingDomainGraph, domain_id: str) -> Dict[str, Any]:
    """Whether `domain_id` was declared reconfigurable/dynamic, with the grounding citation.
    `UNKNOWN_DOMAIN` when `domain_id` was never declared -- never a guessed False."""
    dom = graph.domains.get(domain_id)
    if dom is None:
        return {"domain_id": domain_id, "status": QUERY_UNKNOWN_DOMAIN,
                "reason": f"domain {domain_id!r} was never declared"}
    return {"domain_id": domain_id, "status": QUERY_RESOLVED,
            "reconfigurable": dom.reconfigurable,
            "reconfiguration_evidence": dom.reconfiguration_evidence}


def findings_of_kind(graph: OrderingDomainGraph, kind: str) -> List[Dict[str, Any]]:
    """Every recorded finding of one kind, in the order they were recorded. `kind` must be one of
    `FINDING_KINDS`."""
    if kind not in FINDING_KINDS:
        raise OrderingDomainGraphError(f"unrecognized finding kind {kind!r}; must be one of "
                                        f"{FINDING_KINDS}")
    return [f for f in graph.findings if f.get("kind") == kind]


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own vocabulary (preservation values, finding kinds, query statuses) must
    never collide with a real stage verdict -- the same guard several sibling domain-vocabulary
    modules in this codebase already run against `dv_harness.models.Status`."""
    from dv_harness.models import Status
    status_values = {s.value for s in Status}
    ours = set(PRESERVATION_VALUES) | set(FINDING_KINDS) | {
        QUERY_UNKNOWN_DOMAIN, QUERY_UNKNOWN_NODE, QUERY_RESOLVED,
        QUERY_SAME_DOMAIN, QUERY_CROSS_DOMAIN, "NO_DOMAIN_DECLARED",
    }
    collision = sorted(status_values & ours)
    if collision:
        raise OrderingDomainGraphError(
            f"ordering_domain_graph vocabulary collides with dv_harness.models.Status: "
            f"{collision}")


assert_no_verification_verdict_vocabulary()


def render_graph_markdown(graph: OrderingDomainGraph) -> str:
    """Two markdown tables (domain membership, resolved inter-domain edges) via
    `connectivity.render_markdown_table()` -- this repo's one parameterized table renderer, reused
    rather than a fourth hand-rolled table loop."""
    from dv_harness.connectivity import render_markdown_table

    domain_rows = [
        {"domain_id": d, "reconfigurable": dom.reconfigurable,
         "node_count": len(graph.domain_nodes.get(d, ())),
         "nodes": ", ".join(sorted(graph.domain_nodes.get(d, ()))) or "(none)"}
        for d, dom in sorted(graph.domains.items())
    ]
    domain_table = render_markdown_table(
        [("domain_id", "Domain"), ("reconfigurable", "Reconfigurable"),
         ("node_count", "Node Count"), ("nodes", "Nodes")],
        domain_rows, empty_note="(no ordering domains declared)")

    edge_rows = [
        {"from_domain": f, "to_domain": t, "status": v["status"],
         "evidence": "; ".join(v["evidence"]) or "(none)"}
        for (f, t), v in sorted(graph.edges.items())
    ]
    edge_table = render_markdown_table(
        [("from_domain", "From"), ("to_domain", "To"), ("status", "Preservation"),
         ("evidence", "Evidence")],
        edge_rows, empty_note="(no preservation edges declared)")

    lines = ["## Ordering Domains", "", domain_table, "", "## Preservation Edges", "", edge_table]
    if graph.findings:
        lines += ["", "## Findings", ""]
        for f in graph.findings:
            lines.append(f"- **{f['kind']}**: {f.get('reason')}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.ordering_domain_graph",
        description="Build and report on an ordering-domain graph from a JSON document carrying "
                    "'domains', 'memberships' and 'edges' lists -- every fact caller-declared and "
                    "evidence-cited, never inferred. Reads and reports only.")
    ap.add_argument("--facts-file", required=True,
                     help="JSON file with {'domains': [...], 'memberships': [...], "
                          "'edges': [...]}.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable graph.")
    a = ap.parse_args(argv)

    with open(a.facts_file, "r", encoding="utf-8") as f:
        doc = json.load(f)

    graph = build_ordering_domain_graph(
        doc.get("domains"), doc.get("memberships"), doc.get("edges"))

    if a.json:
        print(json.dumps(graph.to_dict(), indent=2))
    else:
        print(render_graph_markdown(graph))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
