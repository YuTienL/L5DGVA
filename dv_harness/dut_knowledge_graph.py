"""dv_harness/dut_knowledge_graph.py -- DUT-fact Design Knowledge Graph
(CLAUDE.md's "dut_design_knowledge_graph" gap): a real, queryable GRAPH over
extracted DUT-side facts -- RTL modules, register fields, PHY architecture
states, interrupts, and clocks/resets -- as typed nodes with real, cited
edges, assembled ONLY from rows this project's own real extractors already
produced: `design_architecture_ir.py`, `register_rtl_trace.py`,
`interrupt_dma_clock_reset_extraction.py`, `phy_model_behavior_ir.py`. Never
an invented node or edge.

DISTINCT FROM TWO EXISTING GRAPH MODULES, on purpose and by name, so nobody
mistakes this for a duplicate:

  * `verification_knowledge_graph.py` -- a TEST/REQUIREMENT/COVERAGE_
    CATEGORY/ROOT_CAUSE graph over `evidence_db.py`, `requirement_contract.py`
    and `memory.py`. It answers "what tests verify what requirements, what
    coverage do they exercise, what root causes are on file" -- a
    verification-CLOSURE question over evidence this project's own real
    regression/requirement/memory producers already wrote. It imports none
    of this module's four sources and models no RTL/register/PHY fact at
    all.
  * `design_knowledge_correlation.py` -- a generic, domain-AGNOSTIC engine
    over an arbitrary number of caller-declared "design knowledge fact"
    sources (SOURCE/FACT nodes, ASSERTS edges), deliberately importing
    NOTHING from `dv_harness` itself so it stays reusable for any project's
    own fact shape. It answers "where do N sources agree/disagree/leave a
    gap about a design FACT" -- a cross-source CORRELATION question with no
    fixed node/edge vocabulary of its own.

This module answers a third, FIXED-shape question neither of those two can:
given this project's own four real DUT-fact extractors, what is the DUT's
own architecture -- which module instantiates which, which register field
traces to which real RTL port/signal, which interrupt/clock/reset was
declared in which file (and, honestly, in which module when that file
declares only one), and which PHY-architecture fact describes which real
PHY/controller module's boundary. Its node/edge vocabulary (RTL_MODULE/
RTL_SITE/REGISTER_FIELD/INTERRUPT/CLOCK/RESET/PHY_TRAINING_STAGE/
PHY_TX_CAPABILITY/PHY_RX_CAPABILITY/PHY_POWER_STATE, INSTANTIATES/TRACED_TO/
AMBIGUOUSLY_TRACED_TO/DECLARED_IN_FILE/RESET_USES_CLOCK/
DESCRIBES_PHY_BOUNDARY_OF) is specific to that question and reads the four
real producers named above directly. No logic from either sibling graph
module is duplicated, and neither of them is imported here.

REAL SOURCES, NEVER INVENTED:
  * `design_architecture_ir.build_architecture_ir()`'s own `status: "BUILT"`
    document -- its `modules` dict (real, verible-parsed module/port/
    parameter facts), its `files` list (the real file_path each module was
    parsed from -- `modules` alone drops that), and its `instance_tree`
    (the real, resolved-only instantiation graph). A document whose status
    is anything but `"BUILT"` (no RTL supplied, nothing parseable) is
    honestly recorded in `notes` and contributes ZERO nodes -- never a
    fabricated empty-but-clean module set.
  * `register_rtl_trace.trace_register_fields()`'s own per-field
    `RegisterTraceResult` list (its `.to_dict()` shape, or the dataclass
    instances themselves). A REGISTER_FIELD node is added for every result
    supplied (the caller's own register-map fact, cited by its own
    `field`/`field_name`), but a real RTL edge is added ONLY for
    `TRACE_CONFIRMED` (edge `TRACED_TO`, exactly one candidate by that
    module's own contract) and `TRACE_PARTIAL` (edge
    `AMBIGUOUSLY_TRACED_TO`, one edge per real candidate that module
    actually found -- never resolved to a single winner, since that module
    itself refuses to pick one). `TRACE_NOT_FOUND`/`BLOCKED` results add the
    REGISTER_FIELD node with its real status and NO edge -- a real,
    citable absence of RTL backing, never silently dropped from the graph.
  * `interrupt_dma_clock_reset_extraction.extract_interrupt_dma_clock_reset()`'s
    own `interrupt_architecture.sources` / `clock_reset_extension.clocks` /
    `.resets` -- read only when that facet's own `status` is `"LOADED"`,
    per that module's own per-facet honesty contract. Every INTERRUPT/CLOCK/
    RESET node carries its own real `path:line` citation. DMA facts
    (`dma_architecture`) are the one real facet this module deliberately
    does NOT graph -- see "Deliberately bounded" below.
  * `phy_model_behavior_ir.extract_phy_model_behavior_ir()`'s own four
    fact fields (`training_link_startup_stages`/`tx_capabilities`/
    `rx_capabilities`/`power_states`), each item read only when that
    field's own `status` is `"FOUND"`, carrying its real
    `document + fulltext_path + line` citation, plus that same document's
    own `boundary_context` -- itself a direct, read-only pass-through of
    `phy_boundary.py`'s real RTL-derived bind-location decision (never
    re-classified here).

CROSS-LINKING IS EVIDENCE-BASED, NEVER NAME-GUESSED. `register_rtl_trace.py`
and `phy_model_behavior_ir.py` both cite REAL module names that also appear
in `design_architecture_ir.py`'s own real module registry (the trace
candidate's own `module` field; the PHY doc's own `boundary_context.
phy_module`/`.controller_module`) -- an edge to an RTL_MODULE node is only
ever added when that exact name is present in the SAME build's real
registry, never assumed. Interrupt/clock/reset facts carry a real
`path:line` citation but no module name at all; `DECLARED_IN_FILE` links
each one to every RTL_MODULE this build parsed from that SAME file path
(exact string match after `os.path.normcase(os.path.normpath(...))`, never
fuzzy), honestly flagged `file_match: "ambiguous_multi_module_file"` when
that file declares more than one module -- this module never guesses which
one a bare file-level fact "really" belongs to.

EVIDENCE TRUTH RULE, applied throughout: every node/edge traces to one real
row/citation a caller's already-real extractor produced. A source that was
never supplied (no architecture IR, no register traces, no interrupt/clock/
reset doc, no PHY doc) is a portion of the graph honestly not built -- never
a fabricated empty-but-clean answer -- and `build_report()`'s (`to_dict()`'s
`sources_used`) says exactly which of the four were actually consulted.

QUERYABLE, not just constructed: `DutKnowledgeGraph` exposes `neighbors()`,
`rtl_sites_for_register()` (a register field's real confirmed + ambiguous RTL
backing in one call), `unresolved_registers()`, `interrupts_in_module()` /
`clocks_in_module()` / `resets_in_module()`, and `traceability_gap_report()`
-- a worst-wins rollup over every REGISTER_FIELD node this graph holds (ANY
register with zero `TRACED_TO` edges makes the whole rollup `GAPS_PRESENT`,
never averaged) that is honestly `NOT_APPLICABLE` when no register trace
results were ever supplied at all (there is nothing to have a gap in) rather
than reporting a clean pass.

DELIBERATELY BOUNDED. (1) No arbitration: an `AMBIGUOUSLY_TRACED_TO`
register field with several candidate RTL sites is reported with every real
candidate, never resolved to one -- the same refusal
`register_rtl_trace.trace_register_field()` itself already makes for a
`TRACE_PARTIAL` result. (2) No DMA nodes: this module's four real sources
extract interrupt/clock/reset/PHY facts, and `interrupt_dma_clock_reset_
extraction.py` also extracts DMA channel-count/descriptor facts, but the
assigned scope here is "RTL modules, registers, PHY states, interrupts,
clocks" -- DMA is a real, disclosed residual, not silently folded into
another node kind. (3) No arbitration between two DIFFERENT extraction runs
disagreeing about the same fact -- that stays `design_knowledge_correlation.
py`'s own, different, question, deliberately untouched and not imported
here. (4) No CLI verb: `cli.py`/`gates.py`/`dashboard.py` are out of this
task's file-safety scope per house style; `python -m
dv_harness.dut_knowledge_graph` is the front door, matching `design_
knowledge_correlation.py`'s and `verification_knowledge_graph.py`'s own
precedent. (5) Builds and queries only -- no gate, no stage, no memory
write of its own.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

NODE_RTL_MODULE = "RTL_MODULE"
NODE_RTL_SITE = "RTL_SITE"
NODE_REGISTER_FIELD = "REGISTER_FIELD"
NODE_INTERRUPT = "INTERRUPT"
NODE_CLOCK = "CLOCK"
NODE_RESET = "RESET"
NODE_PHY_TRAINING_STAGE = "PHY_TRAINING_STAGE"
NODE_PHY_TX_CAPABILITY = "PHY_TX_CAPABILITY"
NODE_PHY_RX_CAPABILITY = "PHY_RX_CAPABILITY"
NODE_PHY_POWER_STATE = "PHY_POWER_STATE"

EDGE_INSTANTIATES = "INSTANTIATES"                        # RTL_MODULE -> RTL_MODULE
EDGE_TRACED_TO = "TRACED_TO"                               # REGISTER_FIELD -> RTL_SITE
EDGE_AMBIGUOUS_TRACE = "AMBIGUOUSLY_TRACED_TO"              # REGISTER_FIELD -> RTL_SITE
EDGE_DECLARED_IN_FILE = "DECLARED_IN_FILE"                  # INTERRUPT|CLOCK|RESET -> RTL_MODULE
EDGE_RESET_USES_CLOCK = "RESET_USES_CLOCK"                  # RESET -> CLOCK
EDGE_DESCRIBES_PHY_BOUNDARY_OF = "DESCRIBES_PHY_BOUNDARY_OF"  # PHY_* -> RTL_MODULE

_PHY_CATEGORY_TO_NODE_KIND = {
    "training_link_startup_stages": NODE_PHY_TRAINING_STAGE,
    "tx_capabilities": NODE_PHY_TX_CAPABILITY,
    "rx_capabilities": NODE_PHY_RX_CAPABILITY,
    "power_states": NODE_PHY_POWER_STATE,
}


class DutKnowledgeGraphError(ValueError):
    """A caller-supplied input is malformed -- raised rather than silently
    skipped, the same fail-closed discipline `VerificationKnowledgeGraphError`/
    `DesignKnowledgeCorrelationError` already keep in this codebase."""


# ---------------------------------------------------------------------------
# Node/edge id helpers -- deterministic, so re-ingesting the same real fact
# twice (e.g. re-running an extractor over unchanged sources) never mints a
# duplicate node.
# ---------------------------------------------------------------------------

def module_node_id(module_name: str) -> str:
    return f"{NODE_RTL_MODULE}:{module_name}"


def site_node_id(module_name: str, site_kind: str, name: str) -> str:
    return f"{NODE_RTL_SITE}:{module_name}.{site_kind}:{name}"


def register_field_node_id(qualified_name: str) -> str:
    return f"{NODE_REGISTER_FIELD}:{qualified_name}"


def interrupt_node_id(name: Optional[str], evidence: Optional[str]) -> str:
    return f"{NODE_INTERRUPT}:{name or '<unnamed>'}@{evidence or '<no-citation>'}"


def clock_node_id(name: str) -> str:
    return f"{NODE_CLOCK}:{name}"


def reset_node_id(name: str) -> str:
    return f"{NODE_RESET}:{name}"


def phy_item_node_id(category: str, item: dict) -> str:
    citation = item.get("citation") or {}
    key_part = item.get("name") or (item.get("evidence_text") or "")[:40]
    return (f"PHY:{category}:{citation.get('fulltext_path')}:"
            f"{citation.get('line')}:{key_part}")


def _norm_path(p: Optional[str]) -> Optional[str]:
    if not p:
        return None
    return os.path.normcase(os.path.normpath(str(p)))


def _evidence_file_part(evidence: Optional[str]) -> Optional[str]:
    """`"path:line"` / `"path:line-line2"` -> `"path"`. A path that itself
    legitimately contains a colon (a Windows drive letter, `C:\\...`) is
    handled by taking everything up to the LAST colon-then-digits group
    rather than the first colon."""
    if not evidence:
        return None
    idx = evidence.rfind(":")
    if idx <= 1:  # a bare "C:" drive-letter colon with nothing after it
        return evidence
    tail = evidence[idx + 1:]
    if tail and (tail[0].isdigit() or (tail[0] == "-" and tail[1:2].isdigit())):
        return evidence[:idx]
    return evidence


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------

class DutKnowledgeGraph:
    """A real, queryable graph. Nodes are `{id, kind, attrs, provenance}`
    dicts; edges are `{source, target, kind, evidence}` dicts (`evidence` a
    list, since re-ingesting the same real (source, target, kind) triple
    from a second citation appends rather than overwrites -- e.g. two
    ambiguous trace candidates for one register field never collapse into
    one anonymous edge). Construction is idempotent per node/edge id: a node
    id re-added merges attrs and APPENDS provenance (never overwrites an
    earlier citation)."""

    def __init__(self) -> None:
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: List[Dict[str, Any]] = []
        self._edge_index: Dict[Tuple[str, str, str], int] = {}
        self.sources_used: Dict[str, bool] = {
            "architecture_ir": False,
            "register_trace_results": False,
            "interrupt_dma_clock_reset_doc": False,
            "phy_model_behavior_doc": False,
        }
        self.notes: List[str] = []

    # ---- construction -------------------------------------------------

    def add_node(self, node_id: str, kind: str, *, provenance: Optional[dict] = None,
                 **attrs: Any) -> None:
        node = self._nodes.setdefault(
            node_id, {"id": node_id, "kind": kind, "attrs": {}, "provenance": []})
        if node["kind"] != kind:
            raise DutKnowledgeGraphError(
                f"node id {node_id!r} already exists as kind {node['kind']!r}, "
                f"cannot also be {kind!r}")
        for k, v in attrs.items():
            if v is not None:
                node["attrs"][k] = v
        if provenance is not None:
            node["provenance"].append(provenance)

    def add_edge(self, source: str, target: str, kind: str, *,
                 evidence: Optional[dict] = None) -> None:
        key = (source, target, kind)
        idx = self._edge_index.get(key)
        if idx is not None:
            if evidence is not None and evidence not in self._edges[idx]["evidence"]:
                self._edges[idx]["evidence"].append(evidence)
            return
        self._edge_index[key] = len(self._edges)
        self._edges.append({
            "source": source, "target": target, "kind": kind,
            "evidence": [evidence] if evidence is not None else [],
        })

    # ---- read access ----------------------------------------------------

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
            raise DutKnowledgeGraphError(f"direction must be 'out' or 'in', got {direction!r}")
        out = []
        for e in self._edges:
            if edge_kind is not None and e["kind"] != edge_kind:
                continue
            if direction == "out" and e["source"] == node_id:
                out.append(e["target"])
            elif direction == "in" and e["target"] == node_id:
                out.append(e["source"])
        return out

    # ---- domain queries -------------------------------------------------

    def rtl_sites_for_register(self, qualified_name: str, *,
                                include_ambiguous: bool = True) -> Dict[str, List[str]]:
        """Real RTL backing for one register field: `{"confirmed": [...],
        "ambiguous": [...]}`, each a list of RTL_SITE node ids. Both lists
        are honestly empty (never fabricated) when the field was never
        supplied, or was supplied but found no RTL match at all."""
        node_id = register_field_node_id(qualified_name)
        confirmed = self.neighbors(node_id, EDGE_TRACED_TO, "out")
        ambiguous = self.neighbors(node_id, EDGE_AMBIGUOUS_TRACE, "out") if include_ambiguous else []
        return {"confirmed": confirmed, "ambiguous": ambiguous}

    def unresolved_registers(self) -> List[str]:
        """Register fields with zero `TRACED_TO` (confirmed) edges -- a real,
        citable absence, whether that field found no RTL evidence at all or
        only an ambiguous one."""
        return sorted(
            n["id"] for n in self.nodes(NODE_REGISTER_FIELD)
            if not self.neighbors(n["id"], EDGE_TRACED_TO, "out")
        )

    def _declared_in_module(self, module_name: str, node_kind: str) -> List[str]:
        mod_id = module_node_id(module_name)
        ids = self.neighbors(mod_id, EDGE_DECLARED_IN_FILE, direction="in")
        return sorted(i for i in ids if self.node(i) and self.node(i)["kind"] == node_kind)

    def interrupts_in_module(self, module_name: str) -> List[str]:
        return self._declared_in_module(module_name, NODE_INTERRUPT)

    def clocks_in_module(self, module_name: str) -> List[str]:
        return self._declared_in_module(module_name, NODE_CLOCK)

    def resets_in_module(self, module_name: str) -> List[str]:
        return self._declared_in_module(module_name, NODE_RESET)

    def modules_describing_phy_boundary(self) -> List[str]:
        """Every RTL_MODULE this graph named as a real PHY-boundary
        `phy_module`/`controller_module` -- i.e. every distinct target of a
        `DESCRIBES_PHY_BOUNDARY_OF` edge."""
        return sorted({e["target"] for e in self.edges(EDGE_DESCRIBES_PHY_BOUNDARY_OF)})

    def traceability_gap_report(self) -> dict:
        """Worst-wins rollup over every REGISTER_FIELD node this graph
        holds: ANY register with zero confirmed `TRACED_TO` edges makes the
        whole rollup `GAPS_PRESENT`, regardless of how many other fields are
        cleanly traced -- never averaged, never weighted. Honestly
        `NOT_APPLICABLE` when no register trace results were ever supplied
        at all (there is no register set to have a gap in)."""
        registers = self.nodes(NODE_REGISTER_FIELD)
        if not registers:
            return {"status": "NOT_APPLICABLE",
                    "reason": "no register_trace_results were supplied to the builder"}
        unresolved = self.unresolved_registers()
        status = "GAPS_PRESENT" if unresolved else "FULLY_TRACED"
        return {"status": status, "register_count": len(registers),
                "unresolved_register_ids": unresolved}

    # ---- serialization ------------------------------------------------

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
# Ingestion: design_architecture_ir.build_architecture_ir()
# ---------------------------------------------------------------------------

def _ingest_architecture_ir(graph: DutKnowledgeGraph,
                             architecture_ir: dict) -> Tuple[Dict[str, str], Set[str]]:
    """Returns (module_file_map, module_names) for reuse by the interrupt/
    clock/reset and PHY ingestion passes below -- built once here so those
    passes never re-derive it a second, possibly-disagreeing way."""
    if not architecture_ir or architecture_ir.get("status") != "BUILT":
        reason = (architecture_ir or {}).get("reason") or "no architecture_ir was supplied"
        graph.notes.append(f"architecture_ir: not BUILT ({reason}) -- no RTL_MODULE/INSTANTIATES "
                            f"facts available")
        return {}, set()

    module_file_map: Dict[str, str] = {}
    for pf in architecture_ir.get("files", []) or []:
        if pf.get("status") != "PARSED":
            continue
        for mod in pf.get("modules", []) or []:
            name = mod.get("name")
            if name and name not in module_file_map:
                module_file_map[name] = pf.get("file_path")

    modules = architecture_ir.get("modules", {}) or {}
    for name, mod in modules.items():
        graph.add_node(
            module_node_id(name), NODE_RTL_MODULE,
            provenance={"source": "design_architecture_ir",
                        "file_path": module_file_map.get(name)},
            name=name, file_path=module_file_map.get(name),
            port_count=len(mod.get("ports") or []),
            parameter_count=len(mod.get("parameters") or []),
        )

    def _walk(node: dict) -> None:
        parent_name = node.get("module_name")
        for child in node.get("children", []) or []:
            if child.get("resolved") and child.get("module_name") and parent_name:
                graph.add_edge(
                    module_node_id(parent_name), module_node_id(child["module_name"]),
                    EDGE_INSTANTIATES,
                    evidence={"instance_name": child.get("instance_name"),
                              "file_path": child.get("file_path")},
                )
            _walk(child)

    for root in (architecture_ir.get("instance_tree") or {}).get("trees", []) or []:
        _walk(root)

    graph.sources_used["architecture_ir"] = True
    return module_file_map, set(modules)


# ---------------------------------------------------------------------------
# Ingestion: register_rtl_trace.trace_register_fields()
# ---------------------------------------------------------------------------

def _register_trace_dict(result: Any) -> dict:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return result
    raise DutKnowledgeGraphError(
        f"register_trace_results entries must be RegisterTraceResult instances or dicts, "
        f"got {type(result).__name__}")


def _ingest_register_trace_results(graph: DutKnowledgeGraph,
                                    register_trace_results: Sequence[Any]) -> None:
    for result in register_trace_results:
        rd = _register_trace_dict(result)
        qualified = rd.get("field") or rd.get("field_name")
        if not qualified:
            graph.notes.append("register_rtl_trace: a trace result carries no real field "
                                "identity -- skipped rather than graphed under a guessed name")
            continue
        node_id = register_field_node_id(qualified)
        graph.add_node(
            node_id, NODE_REGISTER_FIELD,
            provenance={"source": "register_rtl_trace", "status": rd.get("status")},
            field_name=rd.get("field_name"), qualified_name=qualified,
            rtl_signal_hint=rd.get("rtl_signal_hint"), trace_status=rd.get("status"),
        )
        status = rd.get("status")
        if status == "TRACE_CONFIRMED":
            edge_kind = EDGE_TRACED_TO
        elif status == "TRACE_PARTIAL":
            edge_kind = EDGE_AMBIGUOUS_TRACE
        else:
            continue  # TRACE_NOT_FOUND / BLOCKED: honest node, no fabricated edge
        for cand in rd.get("candidates", []) or []:
            module_name = cand.get("module")
            site_kind = cand.get("kind")
            site_name = cand.get("name")
            if not module_name or not site_kind or not site_name:
                continue
            site_id = site_node_id(module_name, site_kind, site_name)
            graph.add_node(
                site_id, NODE_RTL_SITE,
                provenance={"source": "register_rtl_trace"},
                module=module_name, site_kind=site_kind, name=site_name,
                direction=cand.get("direction"), file_path=cand.get("file_path"),
                referenced=cand.get("referenced"),
            )
            graph.add_edge(
                node_id, site_id, edge_kind,
                evidence={"match_kind": cand.get("match_kind"),
                          "reference_evidence": cand.get("reference_evidence")},
            )
    graph.sources_used["register_trace_results"] = True


# ---------------------------------------------------------------------------
# Ingestion: interrupt_dma_clock_reset_extraction.extract_interrupt_dma_clock_reset()
# ---------------------------------------------------------------------------

def _link_declared_in_file(graph: DutKnowledgeGraph, node_id: str,
                            evidence_citation: Optional[str],
                            module_file_map: Dict[str, str]) -> None:
    file_part = _norm_path(_evidence_file_part(evidence_citation))
    if not file_part or not module_file_map:
        return
    matches = [name for name, fp in module_file_map.items() if _norm_path(fp) == file_part]
    if not matches:
        return
    file_match = "unique" if len(matches) == 1 else "ambiguous_multi_module_file"
    for name in matches:
        graph.add_edge(
            node_id, module_node_id(name), EDGE_DECLARED_IN_FILE,
            evidence={"citation": evidence_citation, "file_match": file_match,
                      "candidate_module_count": len(matches)},
        )


def _ingest_interrupt_dma_clock_reset(graph: DutKnowledgeGraph, doc: dict,
                                       module_file_map: Dict[str, str]) -> None:
    if not doc:
        return
    consulted_any = False

    ia = doc.get("interrupt_architecture") or {}
    if ia.get("status") == "LOADED":
        consulted_any = True
        for src in ia.get("sources", []) or []:
            ev = src.get("evidence")
            node_id = interrupt_node_id(src.get("name"), ev)
            graph.add_node(
                node_id, NODE_INTERRUPT,
                provenance={"source": "interrupt_dma_clock_reset_extraction", "evidence": ev},
                name=src.get("name"), direction=src.get("direction"), width=src.get("width"),
                description=src.get("description"), evidence=ev,
            )
            _link_declared_in_file(graph, node_id, ev, module_file_map)
    else:
        graph.notes.append("interrupt_dma_clock_reset_extraction: interrupt_architecture not "
                            f"LOADED ({ia.get('reason')}) -- no INTERRUPT facts available")

    cr = doc.get("clock_reset_extension") or {}
    if cr.get("status") == "LOADED":
        consulted_any = True
        clock_names_seen: Set[str] = set()
        for c in cr.get("clocks", []) or []:
            name = c.get("name")
            if not name:
                continue
            clock_names_seen.add(name)
            node_id = clock_node_id(name)
            ev = c.get("evidence")
            graph.add_node(
                node_id, NODE_CLOCK,
                provenance={"source": "interrupt_dma_clock_reset_extraction", "evidence": ev},
                name=name, evidence=ev, description=c.get("description"),
            )
            _link_declared_in_file(graph, node_id, ev, module_file_map)
        for r in cr.get("resets", []) or []:
            name = r.get("name")
            if not name:
                continue
            node_id = reset_node_id(name)
            ev = r.get("evidence")
            graph.add_node(
                node_id, NODE_RESET,
                provenance={"source": "interrupt_dma_clock_reset_extraction", "evidence": ev},
                name=name, active_level=r.get("active_level"), synchronous=r.get("synchronous"),
                clock=r.get("clock"), evidence=ev, description=r.get("description"),
            )
            _link_declared_in_file(graph, node_id, ev, module_file_map)
            clock_ref = r.get("clock")
            if clock_ref and clock_ref in clock_names_seen:
                graph.add_edge(node_id, clock_node_id(clock_ref), EDGE_RESET_USES_CLOCK,
                                evidence={"reset_evidence": ev})
    else:
        graph.notes.append("interrupt_dma_clock_reset_extraction: clock_reset_extension not "
                            f"LOADED ({cr.get('reason')}) -- no CLOCK/RESET facts available")

    if consulted_any:
        graph.sources_used["interrupt_dma_clock_reset_doc"] = True


# ---------------------------------------------------------------------------
# Ingestion: phy_model_behavior_ir.extract_phy_model_behavior_ir()
# ---------------------------------------------------------------------------

def _ingest_phy_model_behavior(graph: DutKnowledgeGraph, doc: dict,
                                module_names: Set[str]) -> None:
    if not doc:
        return
    disclosure = doc.get("disclosure")
    boundary_context = doc.get("boundary_context") or {}
    boundary_available = bool(boundary_context.get("available"))
    consulted_any = False

    for category, node_kind in _PHY_CATEGORY_TO_NODE_KIND.items():
        field = doc.get(category) or {}
        if field.get("status") != "FOUND":
            graph.notes.append(
                f"phy_model_behavior_ir: {category} not FOUND "
                f"({field.get('reason')}) -- no {node_kind} facts available")
            continue
        consulted_any = True
        for item in field.get("items", []) or []:
            node_id = phy_item_node_id(category, item)
            graph.add_node(
                node_id, node_kind,
                provenance={"source": "phy_model_behavior_ir", "citation": item.get("citation")},
                name=item.get("name"), evidence_text=item.get("evidence_text"),
                citation=item.get("citation"), disclosure=disclosure,
            )
            if not boundary_available:
                continue
            for role in ("phy_module", "controller_module"):
                mod_name = boundary_context.get(role)
                if mod_name and mod_name in module_names:
                    graph.add_edge(
                        node_id, module_node_id(mod_name), EDGE_DESCRIBES_PHY_BOUNDARY_OF,
                        evidence={"role": role, "mount_layer": boundary_context.get("mount_layer"),
                                  "classification_kind": boundary_context.get("classification_kind"),
                                  "bindable": boundary_context.get("bindable")},
                    )

    if consulted_any:
        graph.sources_used["phy_model_behavior_doc"] = True


# ---------------------------------------------------------------------------
# Front door
# ---------------------------------------------------------------------------

def build_dut_knowledge_graph(
    *,
    architecture_ir: Optional[dict] = None,
    register_trace_results: Optional[Sequence[Any]] = None,
    interrupt_dma_clock_reset_doc: Optional[dict] = None,
    phy_model_behavior_doc: Optional[dict] = None,
) -> DutKnowledgeGraph:
    """Build the graph from whichever of the four real sources the caller
    actually supplies. Each argument is None-able and independent -- a
    caller with only, say, an architecture IR (no register traces, no
    interrupt/clock/reset doc, no PHY doc yet) still gets a real, honestly
    partial graph (`sources_used` says so), never an error demanding all
    four.

    `architecture_ir` -- a real `design_architecture_ir.build_architecture_ir()`
    result dict (its own `status`/`modules`/`files`/`instance_tree` shape).
    `register_trace_results` -- an iterable of `register_rtl_trace.
    RegisterTraceResult` instances (or their `.to_dict()` shape).
    `interrupt_dma_clock_reset_doc` -- a real `interrupt_dma_clock_reset_
    extraction.extract_interrupt_dma_clock_reset()` result dict.
    `phy_model_behavior_doc` -- a real `phy_model_behavior_ir.
    extract_phy_model_behavior_ir()` result dict.
    """
    graph = DutKnowledgeGraph()
    module_file_map: Dict[str, str] = {}
    module_names: Set[str] = set()
    if architecture_ir is not None:
        module_file_map, module_names = _ingest_architecture_ir(graph, architecture_ir)
    if register_trace_results is not None:
        _ingest_register_trace_results(graph, list(register_trace_results))
    if interrupt_dma_clock_reset_doc is not None:
        _ingest_interrupt_dma_clock_reset(graph, interrupt_dma_clock_reset_doc, module_file_map)
    if phy_model_behavior_doc is not None:
        _ingest_phy_model_behavior(graph, phy_model_behavior_doc, module_names)
    return graph


# ---------------------------------------------------------------------------
# CLI (standalone front door -- cli.py/gates.py/dashboard.py are out of this
# task's file-safety scope per house style; matches design_knowledge_
# correlation.py's/verification_knowledge_graph.py's own precedent of a
# `python -m dv_harness.<module>` door with no `dv-harness` verb wired in).
# ---------------------------------------------------------------------------

def _load_json(path: Optional[str]) -> Optional[Any]:
    if path is None:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dv_harness.dut_knowledge_graph")
    parser.add_argument("--architecture-ir", help="path to a real design_architecture_ir.py JSON output")
    parser.add_argument("--register-trace-results",
                         help="path to a JSON list of real register_rtl_trace.py RegisterTraceResult dicts")
    parser.add_argument("--interrupt-dma-clock-reset",
                         help="path to a real interrupt_dma_clock_reset_extraction.py JSON output")
    parser.add_argument("--phy-model-behavior", help="path to a real phy_model_behavior_ir.py JSON output")
    parser.add_argument("--json", action="store_true", help="emit the full graph as JSON")
    args = parser.parse_args(argv)

    try:
        graph = build_dut_knowledge_graph(
            architecture_ir=_load_json(args.architecture_ir),
            register_trace_results=_load_json(args.register_trace_results),
            interrupt_dma_clock_reset_doc=_load_json(args.interrupt_dma_clock_reset),
            phy_model_behavior_doc=_load_json(args.phy_model_behavior),
        )
    except (OSError, ValueError, DutKnowledgeGraphError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not any(graph.sources_used.values()):
        print("error: no real source was supplied (pass at least one of --architecture-ir / "
              "--register-trace-results / --interrupt-dma-clock-reset / --phy-model-behavior)",
              file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(graph.to_dict(), indent=2, default=str))
    else:
        stats = graph.stats()
        print(f"nodes: {stats['total_nodes']}  edges: {stats['total_edges']}")
        for kind, count in sorted(stats["node_counts"].items()):
            print(f"  {kind}: {count}")
        print(json.dumps(graph.traceability_gap_report(), indent=2))
        for note in graph.notes:
            print(f"note: {note}")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin shell
    raise SystemExit(main())
