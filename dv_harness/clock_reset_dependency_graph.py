"""dv_harness/clock_reset_dependency_graph.py -- a standalone, queryable
clock/reset dependency GRAPH object, wrapping real caller-supplied evidence.

THE GAP THIS CLOSES. No module named `clock_reset_dependency_graph` (or any
close variant) existed anywhere in this repository before this file -- checked
by grep before writing a line of it. The real evidence shape with the content
a dependency graph needs already exists in TWO places, producing an IDENTICAL
field shape from two different sources: `env_manifest.
build_dut_facts_clock_reset()` (reading a `soc_arch_map.json` input contract)
and `interrupt_dma_clock_reset_extraction.py`'s own `clock_reset_extension`
block (reading real RTL/spec text). Both already model each reset's
DEPENDENCY on a clock -- a `clock` field naming the clock it synchronises to,
and a `clock_resolved` verdict (RESOLVED / UNKNOWN_CLOCK / NOT_SPECIFIED) for
whether that named clock actually resolves against the same document's own
declared clocks -- but neither exposes it as a class, and neither module
carries any notion of a POWER DOMAIN node or a multi-die/PARTITION dimension.

`dv_harness/holistic_clock_reset_power_consistency.py` already reads this
identical dict and treats it AS a dependency graph (clocks are nodes, each
RESOLVED reset is an edge to its clock) for its own narrower purpose --
whole-bind-set consistency against a chosen environment architecture. This
module reuses that EXACT pattern (consuming the dict verbatim, never
re-parsing RTL or UPF) and generalises it into a real, standalone, queryable
graph object with two axes that module never needed: POWER DOMAIN nodes (from
a real caller-supplied `power_intent.py` `PowerIntent` object, reusing its
real `.domains`/`.switchable_domains()` -- never re-deriving UPF parsing) and
an OPTIONAL, caller-declared per-node PARTITION/DIE assignment, the genuinely
new dimension: no existing extractor in this repository tracks per-die or
per-partition scoping for a clock/reset fact, so that data can only ever be a
plain dict the caller supplies, never inferred.

DECLARATION-LEVEL / GRAPH-WRAPPER, NEVER AN ELABORATOR. This module parses no
RTL and no UPF itself, evaluates no `generate`/`` `ifdef `` condition, runs no
simulation, and proves no formal property. It builds a graph over facts an
upstream extractor already produced and answers structural queries over that
graph -- reachability, dependency direction, unresolved-dependency and
cross-partition reporting -- nothing more. Any RTL/UPF re-derivation stays
`env_manifest.py`'s / `interrupt_dma_clock_reset_extraction.py`'s /
`power_intent.py`'s own job.

EVIDENCE TRUTH RULE, ENFORCED STRUCTURALLY, NOT BY CONVENTION. Three
independent inputs, three independent honest-absence stories, never merged
into one vague "incomplete" flag:
- `clock_reset_facts=None`, a non-mapping value, or a document whose own
  `status` is not `"LOADED"` makes `clock_reset_topology_available` False
  with a real, distinct `clock_reset_topology_reason` -- the graph still
  builds (with zero clock/reset nodes), it is never silently treated as "no
  dependencies exist".
- `power_intent=None` makes `power_intent_available` False with a real
  reason; a caller-supplied value that is not the real `power_intent.
  PowerIntent` object `power_intent.extract_power_intent()` returns is
  refused outright (`ClockResetDependencyGraphError`), mirroring
  `holistic_clock_reset_power_consistency.py`'s identical refusal for the
  identical reason -- a hand-shaped dict pretending to be a `PowerIntent`
  would silently fabricate domain facts nobody actually parsed from UPF.
- `partition_assignment=None` makes `partition_data_available` False. Every
  cross-partition query then returns the honest, distinct
  `NO_PARTITION_DATA_AVAILABLE` status rather than an empty-but-clean result
  list -- an empty list would read as "checked, found no cross-partition
  dependency", which is exactly the fabrication this rule forbids when no
  partition data was ever supplied to check against. A cross-partition
  dependency is asserted ONLY when both endpoints' own partitions are known;
  an edge touching a node this assignment never mentions is reported under
  `edges_with_unknown_partition`, never silently dropped and never counted
  as either same-partition or cross-partition.
`unresolved_dependency_report()` applies the identical discipline one level
down: UNKNOWN_CLOCK (the topology names a clock that does not exist) and
NOT_SPECIFIED (no clock was ever declared) are two different kinds of
"unresolved" and are kept in two separate lists, never merged into one
generic "unresolved" bucket -- collapsing them would hide which of the two
real problems a reader is looking at.

WHAT THIS MODULE DOES NOT DO. It never generates or authors a `bind`
statement, VIP API, RTL, or UPF content. It never arbitrates a genuine
disagreement it finds (a reset whose clock resolves in one partition but
whose own declared clock lives in another is reported as a real finding for
a human to judge, never resolved). There is deliberately no stage gate: no
build, job, or approval is touched anywhere in this file.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import power_intent as _power_intent_module

PowerIntent = _power_intent_module.PowerIntent

# ---------------------------------------------------------------------------
# Vocabulary -- deliberately disjoint from dv_harness.models.Status
# ---------------------------------------------------------------------------
NODE_KIND_CLOCK = "CLOCK"
NODE_KIND_RESET = "RESET"
NODE_KIND_POWER_DOMAIN = "POWER_DOMAIN"
NODE_KINDS = (NODE_KIND_CLOCK, NODE_KIND_RESET, NODE_KIND_POWER_DOMAIN)

EDGE_KIND_SYNCHRONIZES_TO = "SYNCHRONIZES_TO"  # reset -> clock
EDGE_KIND_POWERS = "POWERS"                    # power domain -> clock/reset
EDGE_KINDS = (EDGE_KIND_SYNCHRONIZES_TO, EDGE_KIND_POWERS)

STATUS_LOADED = "LOADED"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_EVALUATED = "EVALUATED"

CROSS_PARTITION_STATUS_NOT_AVAILABLE = "NO_PARTITION_DATA_AVAILABLE"
CROSS_PARTITION_STATUS_EVALUATED = "EVALUATED"

# clock_resolved vocabulary, reused verbatim from env_manifest.py /
# interrupt_dma_clock_reset_extraction.py -- never re-spelled here.
CLOCK_RESOLVED_RESOLVED = "RESOLVED"
CLOCK_RESOLVED_UNKNOWN_CLOCK = "UNKNOWN_CLOCK"
CLOCK_RESOLVED_NOT_SPECIFIED = "NOT_SPECIFIED"

_OWN_STATUS_VOCABULARY = {
    STATUS_LOADED, STATUS_NOT_AVAILABLE, STATUS_EVALUATED,
    CROSS_PARTITION_STATUS_NOT_AVAILABLE, CROSS_PARTITION_STATUS_EVALUATED,
}


def assert_no_verification_verdict_vocabulary() -> None:
    """Import-time guard: this module's own status vocabulary must never
    collide with a real stage-gate verdict, the same discipline
    `holistic_clock_reset_power_consistency.py` already applies to itself."""
    from . import models
    verdicts = {s.value for s in models.Status}
    collision = verdicts & _OWN_STATUS_VOCABULARY
    if collision:  # pragma: no cover -- defensive, would only fire on a future edit
        raise AssertionError(
            f"clock_reset_dependency_graph status vocabulary collides with "
            f"dv_harness.models.Status: {sorted(collision)}")


assert_no_verification_verdict_vocabulary()


class ClockResetDependencyGraphError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ---------------------------------------------------------------------------
# Graph primitives
# ---------------------------------------------------------------------------
@dataclass
class GraphNode:
    node_id: str
    kind: str
    partition: Optional[str] = None
    attrs: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"node_id": self.node_id, "kind": self.kind,
                "partition": self.partition, "attrs": dict(self.attrs)}


@dataclass
class GraphEdge:
    source: str
    target: str
    kind: str
    attrs: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target,
                "kind": self.kind, "attrs": dict(self.attrs)}


class ClockResetDependencyGraph:
    """The queryable graph object. Construct only via
    `build_clock_reset_dependency_graph()` below -- the constructor itself
    performs no evidence handling."""

    def __init__(self) -> None:
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: List[GraphEdge] = []
        self.clock_reset_topology_available: bool = False
        self.clock_reset_topology_reason: Optional[str] = None
        self.power_intent_available: bool = False
        self.power_intent_reason: Optional[str] = None
        self.partition_data_available: bool = False
        # Non-fatal construction findings (malformed domain_power_scope
        # entries, a partition_assignment key naming an unknown node, ...):
        # reported, never silently dropped, never a reason to abort the build.
        self.findings: List[dict] = []

    # -- internal construction helpers --------------------------------
    def _add_node(self, node_id: str, kind: str, **attrs: Any) -> None:
        self.nodes[node_id] = GraphNode(node_id=node_id, kind=kind, attrs=dict(attrs))

    def _add_edge(self, source: str, target: str, kind: str, **attrs: Any) -> None:
        self.edges.append(GraphEdge(source=source, target=target, kind=kind, attrs=dict(attrs)))

    # -- basic node/edge queries ----------------------------------------
    def nodes_of_kind(self, kind: str) -> List[str]:
        return sorted(n.node_id for n in self.nodes.values() if n.kind == kind)

    def clock_names(self) -> List[str]:
        return self.nodes_of_kind(NODE_KIND_CLOCK)

    def reset_names(self) -> List[str]:
        return self.nodes_of_kind(NODE_KIND_RESET)

    def power_domain_names(self) -> List[str]:
        return self.nodes_of_kind(NODE_KIND_POWER_DOMAIN)

    def resets_depending_on_clock(self, clock_name: str) -> List[str]:
        """Every reset with a real RESOLVED dependency edge onto `clock_name`."""
        return sorted(e.source for e in self.edges
                      if e.kind == EDGE_KIND_SYNCHRONIZES_TO and e.target == clock_name)

    def clock_for_reset(self, reset_name: str) -> dict:
        """Which clock (if any) `reset_name` depends on -- honestly, never a
        guess when the dependency did not resolve. Returns
        `{"status": ..., "clock": name-or-None}` where `status` is one of
        RESOLVED / UNKNOWN_CLOCK / NOT_SPECIFIED / RESET_NOT_FOUND, or the
        real recorded status verbatim when it is none of the three known
        values (never silently dropped)."""
        node = self.nodes.get(reset_name)
        if node is None or node.kind != NODE_KIND_RESET:
            return {"status": "RESET_NOT_FOUND", "clock": None}
        resolved = node.attrs.get("clock_resolved")
        if resolved == CLOCK_RESOLVED_RESOLVED:
            return {"status": CLOCK_RESOLVED_RESOLVED, "clock": node.attrs.get("clock")}
        return {"status": resolved or "UNRECORDED", "clock": None}

    def domains_powering(self, node_id: str) -> List[str]:
        """Every power-domain node with a real, caller-declared POWERS edge
        onto `node_id`. Empty whenever no `domain_power_scope` was supplied
        at build time -- that absence is never distinguishable from "checked
        and none found" here, since this is a plain edge lookup; callers
        wanting the honest absence distinction should consult
        `domain_power_scope_declared`."""
        return sorted(e.source for e in self.edges
                      if e.kind == EDGE_KIND_POWERS and e.target == node_id)

    def switchable_domain_ids(self) -> List[str]:
        return sorted(n.node_id for n in self.nodes.values()
                      if n.kind == NODE_KIND_POWER_DOMAIN and n.attrs.get("switchable"))

    # -- reachability / traversal ----------------------------------------
    def traverse(self, start_node_id: str, direction: str = "forward",
                 max_depth: Optional[int] = None) -> List[str]:
        """BFS reachability from `start_node_id` over the real edges, in
        `"forward"` (follow edge direction: reset -> clock, domain -> node)
        or `"backward"` (reverse: clock -> its dependent resets, node -> the
        domain(s) powering it) direction. Returns an empty list for an
        unknown start node -- never an error, and never a fabricated result
        for a node this graph never built."""
        if direction not in ("forward", "backward"):
            raise ClockResetDependencyGraphError(
                "UNKNOWN_TRAVERSAL_DIRECTION", {"direction": direction})
        if start_node_id not in self.nodes:
            return []
        adjacency: Dict[str, set] = defaultdict(set)
        for e in self.edges:
            if direction == "forward":
                adjacency[e.source].add(e.target)
            else:
                adjacency[e.target].add(e.source)
        visited: set = set()
        frontier = [start_node_id]
        depth = 0
        while frontier:
            if max_depth is not None and depth >= max_depth:
                break
            nxt: List[str] = []
            for n in frontier:
                for m in adjacency.get(n, ()):
                    if m not in visited and m != start_node_id:
                        visited.add(m)
                        nxt.append(m)
            frontier = nxt
            depth += 1
        return sorted(visited)

    # -- unresolved-dependency report -------------------------------------
    def unresolved_dependency_report(self) -> dict:
        """Every reset whose clock dependency did NOT resolve, grouped by its
        own distinct resolution status. UNKNOWN_CLOCK (the topology names a
        clock that does not exist) and NOT_SPECIFIED (no clock was ever
        declared) are two different real facts and are never merged into one
        "unresolved" bucket. Honestly NOT_AVAILABLE, with zero fabricated
        content, when the clock/reset topology axis itself was never
        supplied."""
        if not self.clock_reset_topology_available:
            return {
                "status": STATUS_NOT_AVAILABLE,
                "reason": self.clock_reset_topology_reason,
                "unknown_clock": [], "not_specified": [],
                "other_unrecognized_status": [], "resolved_count": 0,
            }
        unknown_clock: List[str] = []
        not_specified: List[str] = []
        other: List[dict] = []
        resolved_count = 0
        for n in self.nodes.values():
            if n.kind != NODE_KIND_RESET:
                continue
            status = n.attrs.get("clock_resolved")
            if status == CLOCK_RESOLVED_RESOLVED:
                resolved_count += 1
            elif status == CLOCK_RESOLVED_UNKNOWN_CLOCK:
                unknown_clock.append(n.node_id)
            elif status == CLOCK_RESOLVED_NOT_SPECIFIED:
                not_specified.append(n.node_id)
            else:
                # A real reset record whose clock_resolved value is neither
                # of the three known ones -- never silently dropped.
                other.append({"reset": n.node_id, "clock_resolved": status})
        return {
            "status": STATUS_EVALUATED,
            "unknown_clock": sorted(unknown_clock),
            "not_specified": sorted(not_specified),
            "other_unrecognized_status": sorted(other, key=lambda x: x["reset"]),
            "resolved_count": resolved_count,
        }

    # -- multi-die / partition topology -----------------------------------
    def cross_partition_dependencies(self) -> dict:
        """Every real RESOLVED reset->clock dependency edge whose two
        endpoints sit in DIFFERENT declared partitions -- the genuinely new
        finding a flat, partition-blind graph cannot surface. Honestly
        `NO_PARTITION_DATA_AVAILABLE` (never an empty-but-clean result list)
        when no partition/die assignment was ever supplied to this graph."""
        if not self.partition_data_available:
            return {
                "status": CROSS_PARTITION_STATUS_NOT_AVAILABLE,
                "reason": "no partition/die assignment was supplied for this "
                          "graph -- a cross-partition dependency can never be "
                          "asserted without one",
                "cross_partition_findings": [],
                "same_partition_edge_count": 0,
                "edges_with_unknown_partition": [],
            }
        cross: List[dict] = []
        same = 0
        unknown: List[dict] = []
        for e in self.edges:
            if e.kind != EDGE_KIND_SYNCHRONIZES_TO:
                continue
            reset_node = self.nodes.get(e.source)
            clock_node = self.nodes.get(e.target)
            if reset_node is None or clock_node is None:
                continue
            rp, cp = reset_node.partition, clock_node.partition
            if rp is None or cp is None:
                missing = []
                if rp is None:
                    missing.append("reset")
                if cp is None:
                    missing.append("clock")
                unknown.append({"reset": e.source, "clock": e.target,
                                 "missing_partition_for": missing})
                continue
            if rp != cp:
                cross.append({"reset": e.source, "reset_partition": rp,
                              "clock": e.target, "clock_partition": cp})
            else:
                same += 1
        cross.sort(key=lambda x: (x["reset"], x["clock"]))
        unknown.sort(key=lambda x: (x["reset"], x["clock"]))
        return {
            "status": CROSS_PARTITION_STATUS_EVALUATED,
            "cross_partition_findings": cross,
            "same_partition_edge_count": same,
            "edges_with_unknown_partition": unknown,
        }

    def resets_in_partition_depending_on_clock_in_partition(
            self, reset_partition: str, clock_partition: str) -> dict:
        """The concrete worked query the module docstring names: "which
        resets in partition A depend on a clock in partition B". Honestly
        `NO_PARTITION_DATA_AVAILABLE` absent any partition assignment."""
        if not self.partition_data_available:
            return {
                "status": CROSS_PARTITION_STATUS_NOT_AVAILABLE,
                "reason": "no partition/die assignment was supplied for this "
                          "graph -- a cross-partition dependency can never be "
                          "asserted without one",
                "resets": [],
            }
        matches: List[str] = []
        for e in self.edges:
            if e.kind != EDGE_KIND_SYNCHRONIZES_TO:
                continue
            reset_node = self.nodes.get(e.source)
            clock_node = self.nodes.get(e.target)
            if reset_node is None or clock_node is None:
                continue
            if reset_node.partition == reset_partition and clock_node.partition == clock_partition:
                matches.append(e.source)
        return {"status": CROSS_PARTITION_STATUS_EVALUATED, "resets": sorted(matches)}

    # -- serialisation ------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "clock_reset_topology_available": self.clock_reset_topology_available,
            "clock_reset_topology_reason": self.clock_reset_topology_reason,
            "power_intent_available": self.power_intent_available,
            "power_intent_reason": self.power_intent_reason,
            "partition_data_available": self.partition_data_available,
            "nodes": [n.to_dict() for n in
                      sorted(self.nodes.values(), key=lambda n: (n.kind, n.node_id))],
            "edges": [e.to_dict() for e in
                      sorted(self.edges, key=lambda e: (e.kind, e.source, e.target))],
            "findings": list(self.findings),
        }


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------
def _clock_reset_topology_absence_reason(clock_reset_facts: Optional[Mapping]) -> Optional[str]:
    if clock_reset_facts is None:
        return ("no clock/reset facts supplied (see "
                "env_manifest.build_dut_facts_clock_reset() / "
                "interrupt_dma_clock_reset_extraction.py's clock_reset_extension)")
    if not isinstance(clock_reset_facts, Mapping):
        return f"clock_reset_facts is not a mapping (got {type(clock_reset_facts).__name__})"
    status = clock_reset_facts.get("status")
    if status != STATUS_LOADED:
        reason = clock_reset_facts.get("reason")
        if reason:
            return str(reason)
        return f"clock_reset_facts status is {status!r}, not {STATUS_LOADED!r}"
    return None


def build_clock_reset_dependency_graph(
    clock_reset_facts: Optional[Mapping] = None,
    *,
    power_intent: Optional[PowerIntent] = None,
    partition_assignment: Optional[Mapping[str, str]] = None,
    domain_power_scope: Optional[Mapping[str, Sequence[str]]] = None,
) -> ClockResetDependencyGraph:
    """The one entry point. `clock_reset_facts` is a real, caller-supplied
    `env_manifest.build_dut_facts_clock_reset()`-shaped dict, or the
    equivalent `interrupt_dma_clock_reset_extraction.py` `clock_reset_extension`
    block -- read verbatim, never re-parsed. `power_intent` must be the real
    object `power_intent.extract_power_intent()` returns, or `None`.
    `partition_assignment` is an OPTIONAL plain dict mapping a node id (a
    clock, reset, or power-domain name already present in the topology/UPF
    evidence) to a caller-declared partition/die id string -- never inferred.
    `domain_power_scope` is an OPTIONAL plain dict mapping a power-domain
    name to the list of clock/reset node ids it is declared to power --
    likewise never inferred; a project supplying none of it still gets real
    power-domain NODES (from `power_intent.py`), just with no POWERS edges."""
    if power_intent is not None and not isinstance(power_intent, PowerIntent):
        raise ClockResetDependencyGraphError(
            "POWER_INTENT_NOT_A_REAL_POWERINTENT_INSTANCE",
            {"got": type(power_intent).__name__,
             "hint": "pass the real object power_intent.extract_power_intent() "
                     "returns, never a hand-shaped dict"})
    if partition_assignment is not None and not isinstance(partition_assignment, Mapping):
        raise ClockResetDependencyGraphError(
            "PARTITION_ASSIGNMENT_NOT_A_MAPPING",
            {"got": type(partition_assignment).__name__})
    if domain_power_scope is not None and not isinstance(domain_power_scope, Mapping):
        raise ClockResetDependencyGraphError(
            "DOMAIN_POWER_SCOPE_NOT_A_MAPPING",
            {"got": type(domain_power_scope).__name__})

    g = ClockResetDependencyGraph()

    # -- clock/reset topology axis --------------------------------------
    absence_reason = _clock_reset_topology_absence_reason(clock_reset_facts)
    if absence_reason is not None:
        g.clock_reset_topology_available = False
        g.clock_reset_topology_reason = absence_reason
    else:
        g.clock_reset_topology_available = True
        clocks = clock_reset_facts.get("clocks") or []
        resets = clock_reset_facts.get("resets") or []
        clock_ids = set()
        for c in clocks:
            if not isinstance(c, Mapping) or not c.get("name"):
                g.findings.append({"kind": "MALFORMED_CLOCK_ENTRY_SKIPPED", "entry": c})
                continue
            name = c["name"]
            clock_ids.add(name)
            g._add_node(name, NODE_KIND_CLOCK,
                        frequency_mhz=c.get("frequency_mhz"), domain=c.get("domain"))
        for r in resets:
            if not isinstance(r, Mapping) or not r.get("name"):
                g.findings.append({"kind": "MALFORMED_RESET_ENTRY_SKIPPED", "entry": r})
                continue
            name = r["name"]
            g._add_node(name, NODE_KIND_RESET,
                        active_level=r.get("active_level"), synchronous=r.get("synchronous"),
                        clock=r.get("clock"), clock_resolved=r.get("clock_resolved"))
            if r.get("clock_resolved") == CLOCK_RESOLVED_RESOLVED and r.get("clock") in clock_ids:
                g._add_edge(name, r["clock"], EDGE_KIND_SYNCHRONIZES_TO)

    # -- power intent axis: real PowerIntent.domains / .switchable_domains() --
    if power_intent is None:
        g.power_intent_available = False
        g.power_intent_reason = ("no power intent supplied (pass the real object "
                                 "power_intent.extract_power_intent() returns)")
    else:
        g.power_intent_available = True
        switchable = set(power_intent.switchable_domains())
        for d in power_intent.domains:
            g._add_node(d.name, NODE_KIND_POWER_DOMAIN,
                        switchable=d.name in switchable, elements=list(d.elements),
                        include_scope=d.include_scope,
                        primary_power_net=d.primary_power_net)

    # -- partition / die axis: entirely caller-declared, never inferred ------
    g.partition_data_available = partition_assignment is not None
    if partition_assignment:
        for node_id, part in partition_assignment.items():
            node = g.nodes.get(node_id)
            if node is None:
                g.findings.append({
                    "kind": "PARTITION_ASSIGNMENT_REFERENCES_UNKNOWN_NODE",
                    "node_id": node_id,
                })
                continue
            node.partition = part

    # -- optional domain-to-clock/reset power scope, entirely caller-declared -
    if domain_power_scope:
        for domain_id, node_ids in domain_power_scope.items():
            domain_node = g.nodes.get(domain_id)
            if domain_node is None or domain_node.kind != NODE_KIND_POWER_DOMAIN:
                g.findings.append({
                    "kind": "DOMAIN_POWER_SCOPE_REFERENCES_UNKNOWN_DOMAIN",
                    "domain": domain_id,
                })
                continue
            if not isinstance(node_ids, (list, tuple, set)):
                g.findings.append({
                    "kind": "DOMAIN_POWER_SCOPE_ENTRY_NOT_A_LIST",
                    "domain": domain_id,
                })
                continue
            for nid in node_ids:
                if nid not in g.nodes:
                    g.findings.append({
                        "kind": "DOMAIN_POWER_SCOPE_REFERENCES_UNKNOWN_NODE",
                        "domain": domain_id, "node_id": nid,
                    })
                    continue
                g._add_edge(domain_id, nid, EDGE_KIND_POWERS)

    return g


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_report_markdown(graph: ClockResetDependencyGraph) -> str:
    from . import connectivity as _connectivity

    lines = ["# Clock/Reset Dependency Graph"]
    lines.append(
        f"\nClock/reset topology available: {graph.clock_reset_topology_available}  "
        f"Power intent available: {graph.power_intent_available}  "
        f"Partition data available: {graph.partition_data_available}\n")
    if not graph.clock_reset_topology_available:
        lines.append(f"\nClock/reset topology: NOT_AVAILABLE -- {graph.clock_reset_topology_reason}\n")
    if not graph.power_intent_available:
        lines.append(f"\nPower intent: NOT_AVAILABLE -- {graph.power_intent_reason}\n")

    node_rows = [n.to_dict() for n in sorted(graph.nodes.values(), key=lambda n: (n.kind, n.node_id))]
    lines.append("\n## Nodes\n")
    lines.append(_connectivity.render_markdown_table(
        [("node_id", "Node"), ("kind", "Kind"), ("partition", "Partition")],
        node_rows, empty_note="(no nodes)"))

    edge_rows = [e.to_dict() for e in sorted(graph.edges, key=lambda e: (e.kind, e.source, e.target))]
    lines.append("\n## Edges\n")
    lines.append(_connectivity.render_markdown_table(
        [("source", "Source"), ("kind", "Kind"), ("target", "Target")],
        edge_rows, empty_note="(no edges)"))

    urd = graph.unresolved_dependency_report()
    lines.append("\n## Unresolved Dependencies\n")
    if urd["status"] == STATUS_NOT_AVAILABLE:
        lines.append(f"\nNOT_AVAILABLE -- {urd['reason']}\n")
    else:
        lines.append(f"\nResolved: {urd['resolved_count']}  "
                     f"Unknown clock: {urd['unknown_clock']}  "
                     f"Not specified: {urd['not_specified']}\n")

    cpd = graph.cross_partition_dependencies()
    lines.append("\n## Cross-Partition Dependencies\n")
    if cpd["status"] == CROSS_PARTITION_STATUS_NOT_AVAILABLE:
        lines.append(f"\n{CROSS_PARTITION_STATUS_NOT_AVAILABLE} -- {cpd['reason']}\n")
    else:
        lines.append(_connectivity.render_markdown_table(
            [("reset", "Reset"), ("reset_partition", "Reset Partition"),
             ("clock", "Clock"), ("clock_partition", "Clock Partition")],
            cpd["cross_partition_findings"], empty_note="(no cross-partition dependencies found)"))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI front door -- standalone, per this project's own house rule against
# editing cli.py/gates.py/dashboard.py while under concurrent edit pressure.
# ---------------------------------------------------------------------------
def execute_verb(argv: Sequence[str]) -> int:
    import argparse
    import json as _json
    import sys as _sys

    parser = argparse.ArgumentParser(prog="clock_reset_dependency_graph")
    parser.add_argument("--clock-reset-facts", default=None)
    parser.add_argument("--upf", nargs="*", default=None)
    parser.add_argument("--partition-assignment", default=None)
    parser.add_argument("--domain-power-scope", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))

    clock_reset_facts = None
    if args.clock_reset_facts:
        try:
            with open(args.clock_reset_facts, "r", encoding="utf-8") as fh:
                clock_reset_facts = _json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"could not read --clock-reset-facts: {exc}", file=_sys.stderr)
            return 2

    power_intent = None
    if args.upf:
        power_intent = _power_intent_module.extract_power_intent(args.upf)

    partition_assignment = None
    if args.partition_assignment:
        try:
            with open(args.partition_assignment, "r", encoding="utf-8") as fh:
                partition_assignment = _json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"could not read --partition-assignment: {exc}", file=_sys.stderr)
            return 2

    domain_power_scope = None
    if args.domain_power_scope:
        try:
            with open(args.domain_power_scope, "r", encoding="utf-8") as fh:
                domain_power_scope = _json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"could not read --domain-power-scope: {exc}", file=_sys.stderr)
            return 2

    try:
        graph = build_clock_reset_dependency_graph(
            clock_reset_facts, power_intent=power_intent,
            partition_assignment=partition_assignment,
            domain_power_scope=domain_power_scope)
    except ClockResetDependencyGraphError as exc:
        print(f"{exc.reason}: {exc.detail}", file=_sys.stderr)
        return 2

    if args.json:
        print(_json.dumps(graph.to_dict(), indent=2))
    else:
        print(render_report_markdown(graph))

    if graph.clock_reset_topology_available:
        return 0
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys as _sys
    return execute_verb(argv if argv is not None else _sys.argv[1:])


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(main(sys.argv[1:]))
