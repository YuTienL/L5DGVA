"""dv_harness/verification_knowledge_graph.py -- Verification Knowledge Graph
(CLAUDE.md / ULTIMATE_COMPLETE_VERIFICATION_INTELLIGENCE.md sections 117-118):
a real, queryable graph linking TEST / REQUIREMENT / COVERAGE_CATEGORY /
ROOT_CAUSE nodes, assembled ONLY from rows this project's own real producers
already wrote -- never an invented node or edge.

DISTINCT FROM `design_knowledge_correlation.py`. That module is a generic
engine over an ARBITRARY number of caller-declared "design knowledge fact"
sources (SOURCE/FACT nodes, ASSERTS edges) -- it answers "where do N sources
agree/disagree/leave a gap about a design FACT", and deliberately imports
nothing from `dv_harness` itself so it stays domain-agnostic. This module
answers a different, FIXED-shape question specific to this project's own real
producers: given the real evidence store (`evidence_db.py`), real requirement
records (`requirement_contract.py`'s fifteen-field contract), and the real
memory store (`memory.py`'s root-cause-kind records), what tests verify what
requirements, what coverage do those tests exercise, and what root causes have
been recorded against them? Its node/edge vocabulary (TEST/REQUIREMENT/
COVERAGE_CATEGORY/ROOT_CAUSE, VERIFIES/EXERCISES_COVERAGE/HAS_ROOT_CAUSE) and
every join key below are specific to that question and read those three real
producers directly -- nothing here is a design-fact correlation and nothing
there is a test/requirement/coverage/root-cause graph. The two modules do not
overlap and neither imports the other.

REAL SOURCES, NEVER INVENTED:
  - `evidence_db.EvidenceStore` (already-real DuckDB tables, read via the same
    generic `store.query(sql, params)` real callers `change_impact.py`/
    `consolidated_kpi_benchmark.py`/`coverage_analysis.py` already use --
    no second evidence reader is written here):
      * `golden_scenarios.test_name` + `.requirements_json` -- the ONLY place
        in this codebase a test is EXPLICITLY declared to verify a set of
        real requirement ids (`golden_scenario.GoldenScenario.requirements`).
        This is the sole source of TEST --VERIFIES--> REQUIREMENT edges;
        nothing here guesses a test-to-requirement link from name similarity
        or from `protocol` equality (many tests share a protocol -- that
        would over-link, exactly the fuzzy-join the Evidence Truth Rule and
        `env_topology.testplan_correspondence`'s own exact-match discipline
        forbid).
      * `failure_signatures.pattern` + `.root_cause_hint` -- TEST
        --HAS_ROOT_CAUSE--> ROOT_CAUSE edges. A row with no `root_cause_hint`
        still marks the TEST node as carrying an unresolved failure signature
        (real evidence: "this test failed and no root cause is on file yet")
        without ever inventing a ROOT_CAUSE node for it.
      * `coverage_samples.category_name` (+ `.source`) -- COVERAGE_CATEGORY
        nodes, linked to a TEST node ONLY when `source` is an exact-string
        match to a `pattern`/`test_name` already known to the graph from
        another real row (the same literal, never-fuzzy join
        `design_knowledge_correlation.py`'s `fact_key` match already commits
        to, for the same reason). An unmatched `source` still yields a
        COVERAGE_CATEGORY node -- it is simply left unlinked, honestly,
        rather than guessing which test it belongs to.
  - `requirement_contract`-shaped records (caller-supplied, the same
    extraction-shaped boundary `dut_evidence_correlation.py` and
    `design_knowledge_correlation.py` already draw: this module does not
    parse a spec or a vPlan itself). Each record must
    `requirement_contract.declares_contract_shape()` and carry a
    `requirement_id`, or building raises fail-closed
    (`VerificationKnowledgeGraphError`) rather than silently skipping a
    malformed one. `requirement_contract.derive_status()` -- the module's OWN
    re-derivation from real record content, not the record's self-declared
    `status` -- is read straight through onto the REQUIREMENT node, so a
    requirement that overclaims COMPLETE is visible on the graph exactly as
    `requirement_contract.py` itself would report it, never re-derived a
    second way here.
  - `memory.MemoryStore.find(kind=...)` over the real root-cause-shaped kinds
    this project's own `memory_router.py` already routes on
    (`ROOT_CAUSE_MEMORY_KINDS` below, verbatim from
    `memory_router.engineering_admission_gate`'s own kind list plus the
    job-tier `job_failure`/`job_result` kinds `lsf_client.py` writes) -- never
    a new memory kind vocabulary invented here. A record's `root_cause` (the
    dedicated kinds) or `failure_signature.root_cause_hint` (the job-tier
    kinds) becomes a ROOT_CAUSE node using the SAME identity scheme
    `evidence_db.failure_signatures` rows use below (protocol + normalized
    root-cause text), so the exact same real root cause recorded via a
    job-tier memory record AND independently confirmed via a dedicated
    `root_cause`/`verified_fix` memory record converges onto ONE node rather
    than being fabricated as two -- and a record's `pattern` field (present on
    job-tier records; genuinely absent on many standalone RCA records) is the
    ONLY thing that earns it a TEST edge. No `pattern` means no edge -- never
    a guessed test.

EVIDENCE TRUTH RULE, applied throughout: every node/edge below traces to one
real row/record via an exact-match join key that row/record itself carries.
Nothing is inferred from text similarity, protocol equality, or naming
convention. A source that was never supplied (no evidence store, no
requirement records, no memory store) is a portion of the graph honestly not
built -- never a fabricated empty-but-clean answer -- and `build_report()`'s
`sources_used` says exactly which of the three were actually consulted.

QUERYABLE, not just constructed: `VerificationKnowledgeGraph` exposes
multi-hop query methods (`root_causes_for_requirement()` walks
REQUIREMENT <- TEST -> ROOT_CAUSE in one call) and `traceability_gap_report()`,
a worst-wins rollup over every supplied requirement (ANY requirement with zero
verifying TEST edges makes the whole rollup GAPS_PRESENT, never averaged) that
is honestly NOT_APPLICABLE when no requirement records were supplied at all
(there is nothing to have a gap in) rather than reporting a clean pass.

DELIBERATELY BOUNDED. (1) No arbitration: two DIFFERENT requirement_contract
records disagreeing about the same `feature`/`expected_result` is
`requirement_contract.cross_source_contradictions()`'s own question, left
untouched and not re-checked here. (2) No RTL/register/design-fact
correlation: that is `dut_evidence_correlation.py`'s and
`design_knowledge_correlation.py`'s own, different, question. (3) Coverage
here is CATEGORY-level (`evidence_db.coverage_samples`'s own real granularity
-- `parse_coverage_summary()`'s `{name, percent, bins_total, bins_hit}` shape
has no per-named-bin detail anywhere in this codebase today); this module
reports honestly at that granularity rather than inventing a bin name no real
producer emits. (4) No CLI verb: `cli.py` is out of this task's file-safety
scope per house style; `python -m dv_harness.verification_knowledge_graph` is
the front door, matching `design_knowledge_correlation.py`'s own precedent.
(5) Builds and queries only -- no gate, no stage, no memory write of its own.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from . import requirement_contract as rc

#: The real memory `kind` strings this project's own `memory_router.py`
#: already routes as root-cause-shaped: the three dedicated RCA kinds
#: (`memory_router.engineering_admission_gate`'s own docstring, verbatim) plus
#: the two job-tier kinds `lsf_client._upsert_job_tier_memory_record()`
#: writes (whose `failure_signature.root_cause_hint` is the same real field
#: `evidence_db.failure_signatures.root_cause_hint` mirrors). Not a new
#: vocabulary: every string here already exists as a real `kind` this repo
#: writes today.
ROOT_CAUSE_MEMORY_KINDS: Tuple[str, ...] = (
    "root_cause", "verified_fix", "debug_lesson", "job_failure", "job_result",
)

NODE_TEST = "TEST"
NODE_REQUIREMENT = "REQUIREMENT"
NODE_COVERAGE_CATEGORY = "COVERAGE_CATEGORY"
NODE_ROOT_CAUSE = "ROOT_CAUSE"

EDGE_VERIFIES = "VERIFIES"                    # TEST -> REQUIREMENT
EDGE_EXERCISES_COVERAGE = "EXERCISES_COVERAGE"  # TEST -> COVERAGE_CATEGORY
EDGE_HAS_ROOT_CAUSE = "HAS_ROOT_CAUSE"        # TEST -> ROOT_CAUSE

UNKNOWN_PROTOCOL = "UNKNOWN_PROTOCOL"


class VerificationKnowledgeGraphError(ValueError):
    """A caller-supplied input is malformed -- raised rather than silently
    skipped, the same fail-closed discipline
    `RequirementContractValidationError`/`DesignKnowledgeCorrelationError`
    already keep in this codebase."""


def test_node_id(pattern: str) -> str:
    return f"{NODE_TEST}:{pattern}"


def requirement_node_id(requirement_id: str) -> str:
    return f"{NODE_REQUIREMENT}:{requirement_id}"


def coverage_node_id(category_name: str) -> str:
    return f"{NODE_COVERAGE_CATEGORY}:{category_name}"


def _normalize_root_cause_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def root_cause_node_id(protocol: Optional[str], root_cause_text: str) -> str:
    """Identity scheme deliberately shared by BOTH real sources this module
    reads root causes from (`evidence_db.failure_signatures` and
    `memory.MemoryStore` root-cause-kind records): (protocol, normalized
    root-cause text) equality, the SAME (protocol, root_cause) pairing
    `memory.py`'s own closed-finding "same finding" dedup already keys on
    (see `memory.py`'s duplicate-finding index, case-insensitive on
    root_cause only). Two independently-recorded mentions of the exact same
    real root cause therefore converge onto one node instead of being
    fabricated as two."""
    proto = str(protocol).strip().upper() if protocol else UNKNOWN_PROTOCOL
    return f"{NODE_ROOT_CAUSE}:{proto}|{_normalize_root_cause_text(root_cause_text)}"


class VerificationKnowledgeGraph:
    """A real, queryable graph. Nodes are `{id, kind, attrs, provenance}`
    dicts; edges are `{source, target, kind, attrs}` dicts. Construction is
    idempotent per node/edge id -- re-adding the same node merges attrs and
    APPENDS provenance (never overwrites an earlier citation), and re-adding
    the same (source, target, kind) edge is a no-op, so ingesting the same
    real row twice (e.g. a re-run against an unchanged evidence store) never
    duplicates graph content."""

    def __init__(self) -> None:
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: List[Dict[str, Any]] = []
        self._edge_keys: set = set()
        self.sources_used: Dict[str, bool] = {
            "evidence_store": False, "requirement_records": False, "memory_store": False,
        }
        self.notes: List[str] = []

    # ---- construction -------------------------------------------------

    def add_node(self, node_id: str, kind: str, *, provenance: Optional[dict] = None,
                 **attrs) -> None:
        node = self._nodes.setdefault(
            node_id, {"id": node_id, "kind": kind, "attrs": {}, "provenance": []})
        if node["kind"] != kind:
            raise VerificationKnowledgeGraphError(
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
            raise VerificationKnowledgeGraphError(f"direction must be 'out' or 'in', got {direction!r}")
        out = []
        for e in self._edges:
            if edge_kind is not None and e["kind"] != edge_kind:
                continue
            if direction == "out" and e["source"] == node_id:
                out.append(e["target"])
            elif direction == "in" and e["target"] == node_id:
                out.append(e["source"])
        return out

    # ---- domain queries ---------------------------------------------------

    def tests_verifying_requirement(self, requirement_id: str) -> List[str]:
        return self.neighbors(requirement_node_id(requirement_id), EDGE_VERIFIES, direction="in")

    def requirements_verified_by_test(self, pattern: str) -> List[str]:
        return self.neighbors(test_node_id(pattern), EDGE_VERIFIES, direction="out")

    def root_causes_for_test(self, pattern: str) -> List[str]:
        return self.neighbors(test_node_id(pattern), EDGE_HAS_ROOT_CAUSE, direction="out")

    def coverage_for_test(self, pattern: str) -> List[str]:
        return self.neighbors(test_node_id(pattern), EDGE_EXERCISES_COVERAGE, direction="out")

    def root_causes_for_requirement(self, requirement_id: str) -> Dict[str, List[str]]:
        """Two-hop query: REQUIREMENT <-VERIFIES- TEST -HAS_ROOT_CAUSE-> ROOT_CAUSE.
        Returns {test_node_id: [root_cause_node_id, ...]} for every verifying
        test, including tests with an empty list (verified, no root cause on
        file) -- never omitted, since "no root cause recorded" is itself a
        real, distinct fact from "no verifying test exists"."""
        out: Dict[str, List[str]] = {}
        for test_id in self.tests_verifying_requirement(requirement_id):
            out[test_id] = self.neighbors(test_id, EDGE_HAS_ROOT_CAUSE, direction="out")
        return out

    def traceability_gap_report(self) -> dict:
        """Worst-wins rollup over every REQUIREMENT node this graph holds: ANY
        requirement with zero incoming VERIFIES edges makes the whole
        rollup GAPS_PRESENT, regardless of how many other requirements are
        cleanly verified -- never averaged, never weighted. Honestly
        NOT_APPLICABLE when no requirement records were ever supplied (there
        is no requirement set to have a gap in)."""
        requirements = self.nodes(NODE_REQUIREMENT)
        if not requirements:
            return {"status": "NOT_APPLICABLE",
                    "reason": "no requirement_contract-shaped records were supplied to the builder"}
        gaps = [n["id"].split(":", 1)[1] for n in requirements
                if not self.neighbors(n["id"], EDGE_VERIFIES, direction="in")]
        status = "GAPS_PRESENT" if gaps else "FULLY_TRACED"
        return {"status": status, "requirement_count": len(requirements),
                "unverified_requirement_ids": sorted(gaps)}

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
# Ingestion: requirement_contract-shaped records
# ---------------------------------------------------------------------------

def _ingest_requirement_records(graph: VerificationKnowledgeGraph,
                                 records: Sequence[dict]) -> None:
    for idx, record in enumerate(records):
        if not rc.declares_contract_shape(record):
            raise VerificationKnowledgeGraphError(
                f"requirement_records[{idx}] does not declare_contract_shape() "
                "(missing 'contract_schema_version'); refusing to build a REQUIREMENT "
                "node from a record that is not in requirement_contract.py's own shape")
        requirement_id = record.get("requirement_id")
        if not requirement_id:
            raise VerificationKnowledgeGraphError(
                f"requirement_records[{idx}] has no requirement_id -- this module's "
                "REQUIREMENT node identity requires one")
        derived_status, derived_reason = rc.derive_status(record)
        graph.add_node(
            requirement_node_id(requirement_id), NODE_REQUIREMENT,
            provenance={"source": "requirement_contract_record", "requirement_id": requirement_id},
            requirement_id=requirement_id,
            feature=record.get("feature"),
            protocol=record.get("protocol"),
            coverage_intent=record.get("coverage_intent"),
            declared_status=record.get("status"),
            derived_status=derived_status,
            derived_status_reason=derived_reason,
            contract_available=True,
        )
    graph.sources_used["requirement_records"] = True


# ---------------------------------------------------------------------------
# Ingestion: evidence_db.EvidenceStore
# ---------------------------------------------------------------------------

def _table_exists(store, table_name: str) -> bool:
    # Same real check evidence_db._golden_scenario_rows() already performs: a
    # read-only connection over a DuckDB file created before a table existed
    # (or before this module existed at all) genuinely lacks that relation --
    # that is "nothing recorded here", reported honestly, never a crash and
    # never silently treated as zero rows from a table that in fact exists.
    return bool(store.query(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [table_name]))


def _ingest_golden_scenarios(graph: VerificationKnowledgeGraph, store) -> None:
    if not _table_exists(store, "golden_scenarios"):
        graph.notes.append("evidence_store: golden_scenarios table not present -- "
                            "no TEST--VERIFIES-->REQUIREMENT edges available")
        return
    rows = store.query(
        "SELECT capsule_id, test_name, requirements_json FROM golden_scenarios")
    for capsule_id, test_name, requirements_json in rows:
        if not test_name:
            continue
        tid = test_node_id(test_name)
        graph.add_node(tid, NODE_TEST,
                        provenance={"source": "golden_scenarios", "capsule_id": capsule_id},
                        pattern=test_name)
        try:
            requirement_ids = json.loads(requirements_json) if requirements_json else []
        except (TypeError, ValueError):
            requirement_ids = []
        for requirement_id in requirement_ids:
            if not requirement_id:
                continue
            rid = requirement_node_id(requirement_id)
            if rid not in graph._nodes:
                # Real evidence a requirement id is REFERENCED (this capsule
                # cites it), but no requirement_contract record was supplied
                # for it -- an honestly PARTIAL node, never fabricated as if
                # its contract were known.
                graph.add_node(rid, NODE_REQUIREMENT,
                                provenance={"source": "golden_scenarios", "capsule_id": capsule_id},
                                requirement_id=requirement_id, contract_available=False)
            graph.add_edge(tid, rid, EDGE_VERIFIES, capsule_id=capsule_id)


def _ingest_failure_signatures(graph: VerificationKnowledgeGraph, store) -> None:
    if not _table_exists(store, "failure_signatures"):
        graph.notes.append("evidence_store: failure_signatures table not present -- "
                            "no TEST--HAS_ROOT_CAUSE-->ROOT_CAUSE edges from it")
        return
    rows = store.query(
        "SELECT pattern, protocol, root_cause_hint, signature_key, occurrence_count "
        "FROM failure_signatures")
    for pattern, protocol, root_cause_hint, signature_key, occurrence_count in rows:
        if not pattern:
            continue
        tid = test_node_id(pattern)
        graph.add_node(tid, NODE_TEST,
                        provenance={"source": "failure_signatures", "signature_key": signature_key},
                        pattern=pattern)
        if not root_cause_hint or not str(root_cause_hint).strip():
            # Real evidence of an unresolved failure -- surfaced on the TEST
            # node, never fabricated into a ROOT_CAUSE node with no real text.
            unresolved = graph._nodes[tid]["attrs"].setdefault("unresolved_failure_signatures", [])
            unresolved.append(signature_key)
            continue
        rcid = root_cause_node_id(protocol, root_cause_hint)
        graph.add_node(rcid, NODE_ROOT_CAUSE,
                        provenance={"source": "failure_signatures", "signature_key": signature_key},
                        protocol=protocol or UNKNOWN_PROTOCOL, root_cause=root_cause_hint)
        graph.add_edge(tid, rcid, EDGE_HAS_ROOT_CAUSE,
                        signature_key=signature_key, occurrence_count=occurrence_count)


def _ingest_coverage_samples(graph: VerificationKnowledgeGraph, store) -> None:
    if not _table_exists(store, "coverage_samples"):
        graph.notes.append("evidence_store: coverage_samples table not present -- "
                            "no COVERAGE_CATEGORY nodes available")
        return
    rows = store.query(
        "SELECT category_name, percent, bins_total, bins_hit, source FROM coverage_samples")
    for category_name, percent, bins_total, bins_hit, source in rows:
        if not category_name:
            continue
        cid = coverage_node_id(category_name)
        graph.add_node(cid, NODE_COVERAGE_CATEGORY,
                        provenance={"source": "coverage_samples"},
                        category_name=category_name, percent=percent,
                        bins_total=bins_total, bins_hit=bins_hit)
        if source:
            tid = test_node_id(source)
            if tid in graph._nodes:  # exact-string match against an ALREADY-known test only
                graph.add_edge(tid, cid, EDGE_EXERCISES_COVERAGE, percent=percent)


def _ingest_evidence_store(graph: VerificationKnowledgeGraph, store) -> None:
    _ingest_golden_scenarios(graph, store)
    _ingest_failure_signatures(graph, store)
    _ingest_coverage_samples(graph, store)
    graph.sources_used["evidence_store"] = True


# ---------------------------------------------------------------------------
# Ingestion: memory.MemoryStore root-cause-kind records
# ---------------------------------------------------------------------------

def _ingest_memory_store(graph: VerificationKnowledgeGraph, memory_store) -> None:
    for kind in ROOT_CAUSE_MEMORY_KINDS:
        for record in memory_store.find(kind=kind):
            memory_id = record.get("memory_id")
            protocol = record.get("protocol")
            pattern = record.get("pattern")
            root_cause = record.get("root_cause")
            if not root_cause:
                failure_signature = record.get("failure_signature") or {}
                root_cause = failure_signature.get("root_cause_hint")
                protocol = protocol or failure_signature.get("protocol")
            if pattern:
                tid = test_node_id(pattern)
                graph.add_node(tid, NODE_TEST,
                                provenance={"source": "memory_store", "memory_id": memory_id,
                                            "kind": kind},
                                pattern=pattern)
            if not root_cause or not str(root_cause).strip():
                # A verified_fix/debug_lesson/job_failure record with no real
                # root-cause text on file: nothing to build a ROOT_CAUSE node
                # from -- recorded as skipped, never invented.
                graph.notes.append(
                    f"memory_store: {kind} record {memory_id!r} has no root_cause text; skipped")
                continue
            rcid = root_cause_node_id(protocol, root_cause)
            graph.add_node(rcid, NODE_ROOT_CAUSE,
                            provenance={"source": "memory_store", "memory_id": memory_id, "kind": kind},
                            protocol=protocol or UNKNOWN_PROTOCOL, root_cause=root_cause)
            if pattern:
                graph.add_edge(test_node_id(pattern), rcid, EDGE_HAS_ROOT_CAUSE, memory_id=memory_id)
    graph.sources_used["memory_store"] = True


# ---------------------------------------------------------------------------
# Front door
# ---------------------------------------------------------------------------

def build_verification_knowledge_graph(
    *,
    evidence_store=None,
    requirement_records: Optional[Sequence[dict]] = None,
    memory_store=None,
) -> VerificationKnowledgeGraph:
    """Build the graph from whichever of the three real sources the caller
    actually supplies. Each argument is None-able and independent -- a caller
    with only requirement records (no evidence store, no memory store yet)
    still gets a real, honestly partial graph (`sources_used` says so), never
    an error demanding all three.

    `evidence_store` -- a real `evidence_db.EvidenceStore` instance (already
    constructed by the caller against a real `.duckdb` file; this function
    performs no I/O of its own to obtain one, matching `change_impact.py`'s
    own convention of taking an already-open store).
    `requirement_records` -- an iterable of `requirement_contract.py`-shaped
    dicts (each must `declares_contract_shape()` and carry `requirement_id`;
    a malformed one raises `VerificationKnowledgeGraphError` rather than
    being silently dropped).
    `memory_store` -- a real `memory.MemoryStore` instance (already
    constructed by the caller against a real project root).
    """
    graph = VerificationKnowledgeGraph()
    if requirement_records is not None:
        _ingest_requirement_records(graph, list(requirement_records))
    if evidence_store is not None:
        _ingest_evidence_store(graph, evidence_store)
    if memory_store is not None:
        _ingest_memory_store(graph, memory_store)
    return graph


# ---------------------------------------------------------------------------
# CLI (standalone front door -- cli.py is out of this task's file-safety
# scope per house style; matches design_knowledge_correlation.py's own
# precedent of a `python -m dv_harness.<module>` door with no `dv-harness`
# verb wired in).
# ---------------------------------------------------------------------------

def _load_requirement_records(path: str) -> List[dict]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict) and "requirements" in doc:
        return list(doc["requirements"])
    raise VerificationKnowledgeGraphError(
        f"{path}: expected a JSON list of requirement records, or a "
        '{"requirements": [...]} document')


def _open_evidence_store_readonly(db_path: str):
    from .evidence_db import EvidenceStore
    import duckdb
    try:
        return EvidenceStore(db_path, read_only=True)
    except duckdb.IOException:
        return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dv_harness.verification_knowledge_graph")
    parser.add_argument("--evidence-db", help="path to a real evidence.duckdb")
    parser.add_argument("--requirements", help="path to a requirement_contract-shaped JSON file")
    parser.add_argument("--memory-root", help="project root containing .dv-harness/memory")
    parser.add_argument("--json", action="store_true", help="emit the graph as JSON")
    args = parser.parse_args(argv)

    evidence_store = None
    if args.evidence_db:
        evidence_store = _open_evidence_store_readonly(args.evidence_db)
        if evidence_store is None:
            print(f"warning: {args.evidence_db} does not exist yet; "
                  "skipping evidence-store ingestion", file=sys.stderr)

    requirement_records = None
    if args.requirements:
        try:
            requirement_records = _load_requirement_records(args.requirements)
        except (OSError, ValueError, VerificationKnowledgeGraphError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    memory_store = None
    if args.memory_root:
        from .memory import MemoryStore
        memory_store = MemoryStore(Path(args.memory_root))

    try:
        graph = build_verification_knowledge_graph(
            evidence_store=evidence_store,
            requirement_records=requirement_records,
            memory_store=memory_store,
        )
    except VerificationKnowledgeGraphError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if evidence_store is not None:
            evidence_store.close()

    if args.json:
        print(json.dumps(graph.to_dict(), indent=2, default=str))
    else:
        stats = graph.stats()
        print(f"nodes: {stats['total_nodes']}  edges: {stats['total_edges']}")
        for kind, count in sorted(stats["node_counts"].items()):
            print(f"  {kind}: {count}")
        print(json.dumps(graph.traceability_gap_report(), indent=2))
    return 1 if graph.traceability_gap_report().get("status") == "GAPS_PRESENT" else 0


if __name__ == "__main__":  # pragma: no cover - thin shell
    raise SystemExit(main())
