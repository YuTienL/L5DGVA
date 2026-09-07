"""dv_harness/dynamic_intake_graph.py -- Dynamic Intake Graph (section 7): a
live graph VIEW joining `intake_state.py`'s real per-field records with
caller-supplied artifact-relationship edges, so a caller can see the whole
intake surface as one connected structure (fields grouped into categories,
fields cross-linked to one another and to external artifacts) instead of a
flat field list.

REUSE, NOT REINVENTION. This module computes no intake fact itself. Every
FIELD node's `status`/`confidence`/`value`/`source`/`owner`/`reason` is the
real `intake_state.IntakeFieldRecord` this project's own `intake_state.
build_intake_state()` already produced (imported directly -- `intake_state.py`
is not one of the concurrently-edited files this batch was told to avoid).
Every CATEGORY node's rollup status is `intake_state.IntakeState.
category_status()`'s own worst-wins fold, called through, never
re-implemented a second way. `evaluate_uvm_generation_ready()`'s six-category
refusal gate is NOT duplicated here -- a caller who needs that hard refusal
still calls it directly on the same `IntakeState`; this module only adds a
graph SHAPE on top of facts that gate already reads.

`artifact_relationship_discovery.py` DID NOT EXIST IN THIS CODEBASE at the
time this module was first built (`grep -rn "artifact_relationship" .` across
dv_harness/, dv_harness_tests/ and CLAUDE.md returned zero hits, checked
before writing a line of this module -- see Rule 4/Evidence Truth Rule). Per
this project's own established precedent for a named-but-not-yet-real
producer (`intake_state.py`'s own `dut_boundary`/`active_driver_conflicts`/
`known_pass_tests` duck-typing, see that module's docstring), this module
accepts artifact-relationship edges in a documented, caller-supplied
duck-typed shape rather than importing a module that was not there.
The shape is intentionally the smallest useful one an edge-discovery producer
would emit: `{"from": <field-or-artifact-id>, "to": <field-or-artifact-id>,
"relation": <str, optional>, "evidence": <str, optional>, "confidence":
<str, optional>}`.

A real `artifact_relationship_discovery.py` was subsequently built in this
same batch (a concurrent, differently-scoped item -- it discovers real
shared-identifier relationships BETWEEN ARTIFACTS, e.g. a register-map file
and a spec doc both naming one block, keyed by `source_id`; it never touches
an intake FIELD name or an `IntakeState`). Rather than duplicate that
module's own real identifier-matching logic here, or silently leave the stale
"does not exist" claim standing, `edges_from_artifact_relationships()` below
is a small, purely reshaping ADAPTER: it takes that module's own real
`RelationshipDiscoveryReport` (or its `.to_dict()`, or a bare list of its
relationship rows) and reshapes each real, already-discovered relationship
into this module's own duck-typed edge shape, so a caller holding a real
artifact-relationship report can graph it here with no change to either
module's own contract. This module still computes no relationship of its
own -- it only reshapes what `artifact_relationship_discovery.py` already
proved.

NODE KINDS: `FIELD` (one per real `IntakeFieldRecord`, id `FIELD:<field>`),
`CATEGORY` (one per category with at least one real field recorded, PLUS
every `intake_state.BLOCKING_CATEGORIES` name even with zero fields -- reusing
`IntakeState.category_status()` verbatim, which already folds an empty
category to MISSING rather than silently omitting it), `ARTIFACT` (an edge
endpoint that names something this `IntakeState` never recorded as a field --
an honest stub node, the same "referenced but not itself supplied" pattern
`verification_knowledge_graph._ingest_golden_scenarios()` already uses for a
requirement id a capsule cites but no `requirement_contract` record was given
for).

EDGE KINDS: `IN_CATEGORY` (FIELD -> CATEGORY, derived straight from each real
record's own `category`), `RELATES_TO` (FIELD/ARTIFACT -> FIELD/ARTIFACT,
one per caller-supplied relationship-edge dict, carrying that edge's real
`relation`/`evidence`/`confidence` as attrs -- a missing `relation` is
recorded as the honest label `"UNSPECIFIED_RELATION"`, never a guessed verb).

"LIVE": this module builds nothing on a schedule and caches nothing of its
own. `build_dynamic_intake_graph()` is a pure function of whatever
`IntakeState` and relationship-edge list the caller hands it *right now* --
call it again after the caller's `IntakeState` changes (a new answer filed,
a new bind classified) and the returned graph reflects exactly that new
state, the same "read fresh every time, no snapshot to go stale" discipline
`intake_state.py` itself keeps for its own three joined sources.

EVIDENCE TRUTH RULE, applied throughout: a relationship edge naming an
endpoint this `IntakeState` never recorded still gets a real `RELATES_TO`
edge (the edge itself IS real evidence, supplied by the caller) but the
endpoint becomes an honest `ARTIFACT` stub, never silently coerced into an
existing `FIELD` node it does not actually name. `graph_connectivity_report()`
is honestly `NOT_APPLICABLE` when the supplied `IntakeState` carries zero
records (there is no intake surface to report connectivity over) rather than
reporting a clean empty pass. `impacted_neighbors()` for a field name this
graph never saw returns `NOT_AVAILABLE`, never an empty-but-clean neighbor
list indistinguishable from "checked, found nothing".

DELIBERATELY BOUNDED, stated rather than implied closed. (1) `RELATES_TO`
relation TEXT is opaque to this module -- no relation-kind taxonomy is
invented here (that would be presuming what a not-yet-built
`artifact_relationship_discovery.py` will call its own edges); this module
groups/counts by whatever relation string the caller supplied. (2) No
question is filed, no gate is invoked, no build/regression/LSF job starts, no
state/blackboard/approval record is written -- this module builds a graph and
answers read-only queries over it, exactly the same "JOINS and REPORTS"
boundary `intake_state.py` itself keeps. (3) No `dv-harness` CLI verb: `cli.py`
is out of this task's file-safety scope per house style (a large,
heavily-edited file); the front door is `python -m
dv_harness.dynamic_intake_graph`, matching `verification_knowledge_graph.py`'s
own precedent of a standalone module door with no `dv-harness` verb wired in.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import intake_state as ist

NODE_FIELD = "FIELD"
NODE_CATEGORY = "CATEGORY"
NODE_ARTIFACT = "ARTIFACT"

EDGE_IN_CATEGORY = "IN_CATEGORY"
EDGE_RELATES_TO = "RELATES_TO"

UNSPECIFIED_RELATION = "UNSPECIFIED_RELATION"


class DynamicIntakeGraphError(ValueError):
    """A caller-supplied input is structurally malformed -- raised rather
    than silently skipped, the same fail-closed discipline
    `VerificationKnowledgeGraphError`/`DesignKnowledgeCorrelationError`
    already keep in this codebase."""


def field_node_id(field_name: str) -> str:
    return f"{NODE_FIELD}:{field_name}"


def category_node_id(category: str) -> str:
    return f"{NODE_CATEGORY}:{category}"


def artifact_node_id(artifact_id: str) -> str:
    return f"{NODE_ARTIFACT}:{artifact_id}"


class DynamicIntakeGraph:
    """A real, queryable graph. Nodes are `{id, kind, attrs, provenance}`
    dicts; edges are `{source, target, kind, attrs}` dicts -- the same shape
    `verification_knowledge_graph.VerificationKnowledgeGraph` already
    established in this codebase, reused here rather than invented a second
    way. Construction is idempotent per node/edge id: re-adding the same
    node merges attrs and APPENDS provenance (never overwrites an earlier
    citation), and re-adding the same (source, target, kind) edge is a
    no-op, so rebuilding this "live" graph from an unchanged IntakeState
    never duplicates content."""

    def __init__(self) -> None:
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: List[Dict[str, Any]] = []
        self._edge_keys: set = set()
        self.sources_used: Dict[str, bool] = {
            "intake_state": False, "relationship_edges": False,
        }
        self.notes: List[str] = []

    # ---- construction ---------------------------------------------------

    def add_node(self, node_id: str, kind: str, *, provenance: Optional[dict] = None,
                 **attrs) -> None:
        node = self._nodes.setdefault(
            node_id, {"id": node_id, "kind": kind, "attrs": {}, "provenance": []})
        if node["kind"] != kind:
            raise DynamicIntakeGraphError(
                f"node id {node_id!r} already exists as kind {node['kind']!r}, "
                f"cannot also be {kind!r}")
        for k, v in attrs.items():
            if v is not None:
                node["attrs"][k] = v
        if provenance is not None:
            node["provenance"].append(provenance)

    def add_edge(self, source: str, target: str, kind: str, **attrs) -> None:
        key = (source, target, kind)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self._edges.append({"source": source, "target": target, "kind": kind, "attrs": attrs})

    # ---- read access ------------------------------------------------------

    def node(self, node_id: str) -> Optional[dict]:
        return self._nodes.get(node_id)

    def nodes(self, kind: Optional[str] = None) -> List[dict]:
        if kind is None:
            return list(self._nodes.values())
        return [n for n in self._nodes.values() if n["kind"] == kind]

    def edges(self, kind: Optional[str] = None) -> List[dict]:
        if kind is None:
            return list(self._edges)
        return [e for e in self._edges if e["kind"] == kind]

    def neighbors(self, node_id: str, edge_kind: Optional[str] = None,
                  direction: str = "out") -> List[str]:
        if direction not in ("out", "in"):
            raise DynamicIntakeGraphError(f"direction must be 'out' or 'in', got {direction!r}")
        out = []
        for e in self._edges:
            if edge_kind is not None and e["kind"] != edge_kind:
                continue
            if direction == "out" and e["source"] == node_id:
                out.append(e["target"])
            elif direction == "in" and e["target"] == node_id:
                out.append(e["source"])
        return out

    # ---- domain queries -----------------------------------------------------

    def fields_in_category(self, category: str) -> List[str]:
        return self.neighbors(category_node_id(category), EDGE_IN_CATEGORY, direction="in")

    def related_to(self, node_id: str) -> List[dict]:
        """Every real `RELATES_TO` edge touching `node_id`, either direction,
        as `{"neighbor": <node id>, "relation": <str>, "direction": "out"|"in"}`.
        This is the whole point of a graph view over a flat field list: a
        caller inspecting one field can see everything it was ever recorded
        as related to, in one call, rather than re-scanning a flat list."""
        out = []
        for e in self._edges:
            if e["kind"] != EDGE_RELATES_TO:
                continue
            if e["source"] == node_id:
                out.append({"neighbor": e["target"], "relation": e["attrs"].get("relation"),
                            "direction": "out"})
            elif e["target"] == node_id:
                out.append({"neighbor": e["source"], "relation": e["attrs"].get("relation"),
                            "direction": "in"})
        return out

    # ---- serialization ------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "nodes": [self._nodes[k] for k in sorted(self._nodes)],
            "edges": sorted(self._edges, key=lambda e: (e["source"], e["target"], e["kind"])),
            "sources_used": dict(self.sources_used),
            "notes": list(self.notes),
        }

    def stats(self) -> dict:
        by_kind: Dict[str, int] = {}
        for n in self._nodes.values():
            by_kind[n["kind"]] = by_kind.get(n["kind"], 0) + 1
        by_edge_kind: Dict[str, int] = {}
        for e in self._edges:
            by_edge_kind[e["kind"]] = by_edge_kind.get(e["kind"], 0) + 1
        return {"node_counts": by_kind, "edge_counts": by_edge_kind,
                "total_nodes": len(self._nodes), "total_edges": len(self._edges)}


# ---------------------------------------------------------------------------
# Ingestion: intake_state.IntakeState (real fields + real category rollup)
# ---------------------------------------------------------------------------

def _ingest_intake_state(graph: DynamicIntakeGraph, intake_state: ist.IntakeState) -> None:
    categories_seen: set = set()
    for record in intake_state.records:
        fid = field_node_id(record.field)
        graph.add_node(
            fid, NODE_FIELD,
            provenance={"source": "intake_state.IntakeFieldRecord", "field": record.field},
            field=record.field, category=record.category, value=record.value,
            record_source=record.source, confidence=record.confidence, status=record.status,
            last_validated=record.last_validated, owner=record.owner, reason=record.reason,
        )
        cid = category_node_id(record.category)
        # category_status() is IntakeState's own real worst-wins fold over
        # every field actually recorded under this category -- called
        # through, never re-derived a second way here.
        graph.add_node(cid, NODE_CATEGORY,
                        provenance={"source": "intake_state.category_status", "category": record.category},
                        category=record.category,
                        rollup_status=intake_state.category_status(record.category))
        graph.add_edge(fid, cid, EDGE_IN_CATEGORY)
        categories_seen.add(record.category)

    # Every named blocking category is made visible even with zero real
    # fields recorded, reusing category_status()'s own honest MISSING fold
    # for "never evaluated" -- the same "a category this run never saw must
    # never disappear from view" discipline evaluate_uvm_generation_ready()
    # already applies to its own refusal check.
    for category in ist.BLOCKING_CATEGORIES:
        if category in categories_seen:
            continue
        cid = category_node_id(category)
        graph.add_node(cid, NODE_CATEGORY,
                        provenance={"source": "intake_state.BLOCKING_CATEGORIES", "category": category},
                        category=category, rollup_status=intake_state.category_status(category))
    graph.sources_used["intake_state"] = True


# ---------------------------------------------------------------------------
# Ingestion: artifact-relationship edges (duck-typed -- see module docstring
# for why `artifact_relationship_discovery.py` is not imported: it does not
# exist anywhere in this codebase as of this build)
# ---------------------------------------------------------------------------

def _resolve_endpoint(graph: DynamicIntakeGraph, intake_state: ist.IntakeState, raw_id: Any) -> str:
    key = str(raw_id)
    if intake_state.get(key) is not None:
        return field_node_id(key)
    # Honest stub: this edge names something the supplied IntakeState never
    # recorded as a field. Real evidence (the edge itself, and whatever the
    # caller passed as this endpoint's id) is kept; nothing is invented about
    # what kind of artifact it is beyond "referenced, not a known field".
    aid = artifact_node_id(key)
    graph.add_node(aid, NODE_ARTIFACT,
                    provenance={"source": "relationship_edge_endpoint"},
                    artifact_id=key,
                    note="referenced by a relationship edge; not a field this IntakeState recorded")
    return aid


def _ingest_relationship_edges(graph: DynamicIntakeGraph, intake_state: ist.IntakeState,
                                relationship_edges: Sequence[dict]) -> None:
    for idx, edge in enumerate(relationship_edges):
        if not isinstance(edge, dict) or not edge.get("from") or not edge.get("to"):
            raise DynamicIntakeGraphError(
                f"relationship_edges[{idx}] must be a dict carrying real 'from'/'to' endpoint "
                f"ids; got {edge!r}")
        confidence = edge.get("confidence")
        if confidence is not None and confidence not in ist.CONFIDENCE_VOCAB:
            raise DynamicIntakeGraphError(
                f"relationship_edges[{idx}] has unrecognized confidence {confidence!r}; "
                f"must be one of {sorted(ist.CONFIDENCE_VOCAB)} or omitted")
        source = _resolve_endpoint(graph, intake_state, edge["from"])
        target = _resolve_endpoint(graph, intake_state, edge["to"])
        relation = edge.get("relation")
        if not relation or not str(relation).strip():
            relation = UNSPECIFIED_RELATION
            graph.notes.append(
                f"relationship_edges[{idx}] ({edge['from']!r} -> {edge['to']!r}) carries no "
                f"'relation' text; recorded as {UNSPECIFIED_RELATION}, never a guessed verb")
        graph.add_edge(source, target, EDGE_RELATES_TO,
                        relation=str(relation), evidence=edge.get("evidence"),
                        confidence=confidence)
    graph.sources_used["relationship_edges"] = True


# ---------------------------------------------------------------------------
# Adapter: reshape a real artifact_relationship_discovery.py report into this
# module's own duck-typed relationship-edge shape (see module docstring).
# ---------------------------------------------------------------------------

def _relationship_row_fields(rel: Any) -> Dict[str, Any]:
    """Read the real fields off one relationship entry, whether it is an
    `artifact_relationship_discovery.ArtifactRelationship` dataclass instance
    or that same shape already reduced to a plain dict (as `.to_dict()`
    produces)."""
    if isinstance(rel, dict):
        get = rel.get
    else:
        get = lambda k, default=None: getattr(rel, k, default)  # noqa: E731
    return {
        "artifact_a": get("artifact_a"), "artifact_b": get("artifact_b"),
        "identifier": get("identifier"),
        "name_a": get("name_a"), "kind_a": get("kind_a"), "locator_a": get("locator_a"),
        "name_b": get("name_b"), "kind_b": get("kind_b"), "locator_b": get("locator_b"),
    }


def edges_from_artifact_relationships(relationships: Any) -> List[dict]:
    """Reshape a real `artifact_relationship_discovery.py` result into this
    module's own duck-typed relationship-edge list (`build_dynamic_
    intake_graph()`'s `relationship_edges` argument).

    `relationships` may be that module's own `RelationshipDiscoveryReport`
    (read via its `.relationships` attribute), that report's own
    `.to_dict()` result (a dict carrying a `"relationships"` key), or a bare
    list of `ArtifactRelationship` instances / already-dict-shaped rows --
    every one of those is the SAME real, already-discovered evidence, only
    packaged differently by the caller. This function computes no
    relationship of its own: it only relabels `artifact_a`/`artifact_b` as
    `from`/`to` and folds the real per-side citations
    (`name (kind) @ locator`) into one honest `evidence` string, carrying the
    real matched `identifier` as the edge's `relation` -- never a guessed
    verb, since the only real fact discovered is "these two artifacts share
    this identifier", not what relationship that sharing implies.
    """
    if relationships is None:
        return []
    if hasattr(relationships, "relationships"):
        rows: Iterable[Any] = relationships.relationships
    elif isinstance(relationships, dict) and "relationships" in relationships:
        rows = relationships["relationships"]
    else:
        rows = relationships

    edges: List[dict] = []
    for rel in rows:
        try:
            f = _relationship_row_fields(rel)
        except AttributeError as exc:
            raise DynamicIntakeGraphError(
                f"edges_from_artifact_relationships: unrecognized relationship "
                f"entry {rel!r} ({exc})")
        artifact_a, artifact_b = f["artifact_a"], f["artifact_b"]
        if not artifact_a or not artifact_b:
            raise DynamicIntakeGraphError(
                f"edges_from_artifact_relationships: relationship entry missing "
                f"a real 'artifact_a'/'artifact_b' pair: {rel!r}")
        citation_a = f"{f['name_a']} ({f['kind_a']}) @ {f['locator_a']}"
        citation_b = f"{f['name_b']} ({f['kind_b']}) @ {f['locator_b']}"
        edges.append({
            "from": artifact_a, "to": artifact_b,
            "relation": f"SHARES_IDENTIFIER:{f['identifier']}",
            "evidence": f"{citation_a} <-> {citation_b}",
        })
    return edges


# ---------------------------------------------------------------------------
# Front door
# ---------------------------------------------------------------------------

def build_dynamic_intake_graph(
    intake_state: ist.IntakeState,
    relationship_edges: Optional[Sequence[dict]] = None,
) -> DynamicIntakeGraph:
    """Build one live graph view over `intake_state` (a real `intake_state.
    IntakeState`, e.g. from `intake_state.build_intake_state()` -- required;
    there is no field-record content to graph without one) plus whatever
    caller-supplied artifact-relationship edges are available right now (see
    module docstring for the duck-typed edge shape and why
    `artifact_relationship_discovery.py` is not imported).

    `relationship_edges` is independently optional -- a caller with only an
    `IntakeState` and no discovered relationships yet still gets a real,
    honestly partial graph (FIELD/CATEGORY nodes and IN_CATEGORY edges only;
    `sources_used["relationship_edges"]` stays False, never fabricated
    True)."""
    graph = DynamicIntakeGraph()
    _ingest_intake_state(graph, intake_state)
    if relationship_edges is not None:
        _ingest_relationship_edges(graph, intake_state, list(relationship_edges))
    return graph


# ---------------------------------------------------------------------------
# Read-only reports over the built graph
# ---------------------------------------------------------------------------

def graph_connectivity_report(graph: DynamicIntakeGraph) -> dict:
    """A graph-SHAPE summary, deliberately NOT a re-implementation of
    `evaluate_uvm_generation_ready()`'s six-category refusal gate (that gate
    stays `intake_state.py`'s own, called directly by a caller who needs it).
    Honestly `NOT_APPLICABLE` when the graph holds zero FIELD nodes (built
    from an `IntakeState` with no records at all) -- there is no intake
    surface to report connectivity over, never a fabricated clean pass."""
    fields = graph.nodes(NODE_FIELD)
    if not fields:
        return {"status": "NOT_APPLICABLE",
                "reason": "the supplied IntakeState carried zero field records"}
    orphans = sorted(
        n["attrs"]["field"] for n in fields
        if not graph.related_to(n["id"])
    )
    return {
        "status": "OK",
        "field_count": len(fields),
        "category_count": len(graph.nodes(NODE_CATEGORY)),
        "artifact_stub_count": len(graph.nodes(NODE_ARTIFACT)),
        "relationship_edge_count": len(graph.edges(EDGE_RELATES_TO)),
        "orphan_field_count": len(orphans),
        "orphan_fields": orphans,
    }


def impacted_neighbors(graph: DynamicIntakeGraph, field_name: str) -> dict:
    """One field's real neighborhood: its own category/status plus every
    field or artifact it was ever recorded as related to, WITH each
    neighbor's own real status where the neighbor is itself a known FIELD --
    exactly the "see the whole connected structure, not just this one field"
    value a flat field list cannot give. `NOT_AVAILABLE` (never an
    empty-but-clean neighbor list) for a field this graph never saw at all,
    so "no neighbors recorded" and "field unknown to this graph" are never
    conflated."""
    fid = field_node_id(field_name)
    node = graph.node(fid)
    if node is None:
        return {"status": "NOT_AVAILABLE",
                "reason": f"{field_name!r} is not a field this graph's IntakeState recorded"}
    neighbors = []
    for rel in graph.related_to(fid):
        neighbor_node = graph.node(rel["neighbor"])
        neighbors.append({
            "neighbor": rel["neighbor"],
            "relation": rel["relation"],
            "direction": rel["direction"],
            "neighbor_kind": neighbor_node["kind"] if neighbor_node else "UNKNOWN",
            "neighbor_status": (neighbor_node["attrs"].get("status")
                                 if neighbor_node and neighbor_node["kind"] == NODE_FIELD else None),
        })
    return {
        "status": "OK",
        "field": field_name,
        "field_status": node["attrs"].get("status"),
        "category": node["attrs"].get("category"),
        "neighbors": neighbors,
    }


# ---------------------------------------------------------------------------
# CLI (standalone front door -- cli.py is out of this task's file-safety
# scope per house style; matches verification_knowledge_graph.py's own
# precedent of a `python -m dv_harness.<module>` door with no `dv-harness`
# verb wired in).
# ---------------------------------------------------------------------------

def _intake_state_from_dict(doc: dict) -> ist.IntakeState:
    """Reconstructs a real `IntakeState` from the exact JSON shape
    `IntakeState.to_dict()` itself already emits -- `--intake-state` on this
    module's CLI takes that file, never a hand-authored one, so every
    resulting `IntakeFieldRecord` still passes its own `__post_init__`
    status/confidence validation."""
    fields = doc.get("fields")
    if not isinstance(fields, list):
        raise DynamicIntakeGraphError(
            "--intake-state file must be an IntakeState.to_dict()-shaped document "
            "carrying a 'fields' list")
    records = [ist.IntakeFieldRecord(
        field=f["field"], category=f["category"], value=f.get("value"), source=f["source"],
        confidence=f["confidence"], status=f["status"], last_validated=f.get("last_validated"),
        owner=f.get("owner"), reason=f.get("reason", ""),
    ) for f in fields]
    return ist.IntakeState(records, generated_at=doc.get("generated_at"))


def _load_relationship_edges(path: str) -> List[dict]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict) and "edges" in doc:
        return list(doc["edges"])
    raise DynamicIntakeGraphError(
        f"{path}: expected a JSON list of relationship-edge dicts, or a "
        '{"edges": [...]} document')


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dv_harness.dynamic_intake_graph")
    parser.add_argument("--intake-state", required=True,
                         help="path to an IntakeState.to_dict()-shaped JSON file")
    parser.add_argument("--relationships",
                         help="path to a caller-supplied artifact-relationship-edges JSON file "
                              "(see module docstring for the duck-typed edge shape)")
    parser.add_argument("--json", action="store_true", help="emit the full graph as JSON")
    args = parser.parse_args(argv)

    try:
        intake_doc = json.loads(Path(args.intake_state).read_text(encoding="utf-8"))
        intake_state = _intake_state_from_dict(intake_doc)
    except (OSError, ValueError, KeyError, DynamicIntakeGraphError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    relationship_edges = None
    if args.relationships:
        try:
            relationship_edges = _load_relationship_edges(args.relationships)
        except (OSError, ValueError, DynamicIntakeGraphError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    try:
        graph = build_dynamic_intake_graph(intake_state, relationship_edges)
    except DynamicIntakeGraphError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(graph.to_dict(), indent=2, default=str))
    else:
        stats = graph.stats()
        print(f"nodes: {stats['total_nodes']}  edges: {stats['total_edges']}")
        for kind, count in sorted(stats["node_counts"].items()):
            print(f"  {kind}: {count}")
        print(json.dumps(graph_connectivity_report(graph), indent=2))
    # This module is a graph VIEW, not a gate (see module docstring) -- exit
    # 0 for any successfully-built graph, including one with orphan fields
    # or zero relationship edges; only a malformed input (handled above,
    # exit 2) is a failure here.
    return 0


if __name__ == "__main__":  # pragma: no cover - thin shell
    raise SystemExit(main())
