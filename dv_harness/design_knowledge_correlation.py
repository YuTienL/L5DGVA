"""dv_harness/design_knowledge_correlation.py -- a cross-source correlation
engine over generic, IR-shaped "design knowledge" facts. Given several
sources (a spec, an RTL extraction, a register map, a testplan, a VIP
document, ... -- whatever a caller supplies, each labelled with its own
epistemic ROLE) it finds three things and assembles them, with everything
that was asserted, into one Design Knowledge Graph:

  CONFLICT                    two (or more) sources disagree about the same
                               fact -- their asserted values do not agree.
  GAP                          a fact the caller EXPECTED some source to
                               cover, that no source covers at all.
  DOCUMENTED_VS_IMPLEMENTED    a fact one side declared (a SPEC_DECLARATION-
                               role source) with no IMPLEMENTATION_EVIDENCE-
                               role source ever asserting it (a spec-declared
                               feature with no RTL evidence), or the reverse
                               (RTL evidence for something the spec never
                               declared).

WHY THIS EXISTS. Every existing correlator in this repo answers a narrower
question against a specific real producer's own shape:
`dut_evidence_correlation.py` joins ONE caller-declared item against
`env_manifest.py`'s `dut_facts` layers; `env_manifest.py`'s own
`testplan_correspondence` is a fixed three-way join of ONE project's
testlist/vPlan/coverage-model triple; `source_authority.py` decides which of
TWO already-identified conflicting VALUES wins, given a 9-level authority
order, but never DISCOVERS a conflict on its own. Nothing in this repo takes
an arbitrary NUMBER of arbitrarily-shaped knowledge sources and finds where
they agree, disagree, or leave a gap. This module is that general engine.

REUSE OVER REINVENT, and why this is a new module rather than an extension
of one of the above. `dut_evidence_correlation.py`'s matching machinery
(exact + fuzzy substring, tuned for "does an RTL/register name resemble a
declared signal name") is private (leading-underscore) and shaped
specifically for its one manifest-shaped candidate structure -- it has no
public surface this module could call, and its fuzzy matching is the wrong
tool here: this module's callers supply an already-canonical `fact_key` per
assertion (the join key), so re-introducing substring fuzz would risk
manufacturing a conflict or a gap between two facts that were never meant to
be the same fact, which is exactly the failure mode
`env_topology.testplan_correspondence`'s own docstring warns against
("Matching is a literal name join, never fuzzy"). No logic is duplicated:
this module's own value-equivalence comparator (`_values_equivalent()`) is
new, small, and does something none of the above do -- compare two arbitrary
JSON-shaped VALUES (not names) for agreement.

INPUT SHAPE IS DELIBERATELY GENERIC (duck-typed), per this batch's file-safety
scope: this task must not import from, or wait on, any other item in this or
the concurrently-running batch, and this module imports NOTHING from
`dv_harness` itself. A "source" is a plain dict:

    {
      "source_id": "spec_v3",                # unique, required
      "source_kind": "spec",                 # free text, required (e.g.
                                              # "spec"/"rtl"/"register_map"/
                                              # "testplan"/"vip_doc" -- purely
                                              # descriptive; nothing in this
                                              # module branches on its value)
      "role": "SPEC_DECLARATION",            # one of SOURCE_ROLES, optional
                                              # (default OTHER) -- THIS is
                                              # what DOCUMENTED_VS_IMPLEMENTED
                                              # keys on, deliberately declared
                                              # by the caller rather than
                                              # guessed from `source_kind`
                                              # text (guessing would be
                                              # exactly the fabricated
                                              # semantics the Evidence Truth
                                              # Rule forbids)
      "facts": [
        {"fact_key": "usb_wake_irq.active_level", "fact_type": "interrupt",
         "value": "HIGH", "evidence_ref": "spec.md:120"},
        ...
      ],
    }

A caller sitting in front of a real producer would build this shape from that
producer's own real output -- e.g. one fact per `env_manifest.py` `dut_facts`
entry (role IMPLEMENTATION_EVIDENCE), one per a real requirement record's
`requirement_contract.py`-validated `feature`/`expected_behavior` field (role
SPEC_DECLARATION), one per a `testplan_sources.schema.json` vPlan item (role
OTHER) -- this module does not parse any of those itself (that is a different,
extraction-shaped problem, the same boundary `dut_evidence_correlation.py`'s
own docstring draws around `requirement_contract.py`'s prose fields, and the
same reasoning `doc_extraction_fanout.py` gives for why several of its own
categories "remain input-CONTRACT transcription pipelines ... performed by a
human or an agent reading the document").

THE JOIN KEY is `fact_key`, compared by exact string equality only -- no
fuzzy/semantic matching, for the reason stated above. Two assertions with
`fact_key` `"usb_wake_irq"` and `"USB Wake IRQ"` are, to this module, facts
about two DIFFERENT things unless the caller normalizes them to the same key
before calling in. Normalizing fact_key naming across heterogeneous real
producers is exactly the "extraction-shaped problem this task does not
attempt" named above.

THE VALUE COMPARATOR (`_values_equivalent()`) is deliberately tolerant of
representation, not of substance: `"HIGH"` == `"high"` == `" High "`, `100`
== `100.0` == `"100"`, `True` == `"true"`, and two dict/list values compare by
canonical JSON. It is NOT tolerant of unit drift a caller did not normalize
(`100` MHz vs `0.1` GHz reads as a genuine conflict) -- inventing a unit
converter would be exactly the kind of unearned semantic inference this
module's "no fuzzy matching" discipline exists to avoid.

DELIBERATELY BOUNDED, stated rather than implied closed.
(1) No arbitration. A CONFLICT is reported with every distinct value and its
    citing source(s); this module never decides which source is right. That
    decision belongs to a human, or to `source_authority.resolve_conflict()`
    given the 9-level authority order and each side's own `evidence_ref` --
    a real, existing, narrower mechanism this module deliberately leaves
    untouched and does not import (per this batch's file-safety scope), so a
    caller who already knows both sides' authority tier is free to feed this
    module's `conflicts` list into that resolver.
(2) GAP requires a caller-declared `expected_facts` list. Without one, "a
    fact no source covers" is undecidable -- there is no enumerated universe
    of facts a design SHOULD have, the same reason `config_variant_coverage.py`
    requires a caller-declared dimension space rather than inventing one.
    Calling `correlate()` with no `expected_facts` still runs CONFLICT and
    DOCUMENTED_VS_IMPLEMENTED detection; it reports zero gaps, honestly,
    rather than fabricating an expectation.
(3) DOCUMENTED_VS_IMPLEMENTED is a PRESENCE check on `role`, not a values
    check. A fact asserted by both a SPEC_DECLARATION source and an
    IMPLEMENTATION_EVIDENCE source, whose values then disagree, is reported
    as a CONFLICT, never additionally as a doc-vs-impl mismatch -- the two
    categories are kept disjoint so one real disagreement is never counted
    twice under two different names. A fact asserted only by OTHER-role
    sources (neither SPEC_DECLARATION nor IMPLEMENTATION_EVIDENCE) yields no
    doc-vs-impl finding either way: this module cannot judge a documentation
    question about a fact neither side spoke to.
(4) It DECIDES nothing beyond the three finding categories and the graph: no
    build, no job, no approval, no stage gate, no memory write. It performs
    no I/O of its own beyond the optional CLI front door reading two JSON
    files the caller names.
(5) It generates no VIP API, RTL content or protocol behavior of any kind --
    it only correlates facts the caller already extracted (No Golden-
    Reference Content Mining rule; there is nothing here to mine, since it
    reads structured facts, not documents).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

ROLE_SPEC_DECLARATION = "SPEC_DECLARATION"
ROLE_IMPLEMENTATION_EVIDENCE = "IMPLEMENTATION_EVIDENCE"
ROLE_OTHER = "OTHER"
SOURCE_ROLES: Tuple[str, ...] = (ROLE_SPEC_DECLARATION, ROLE_IMPLEMENTATION_EVIDENCE, ROLE_OTHER)

FINDING_CONFLICT = "CONFLICT"
FINDING_GAP = "GAP"
FINDING_DOC_VS_IMPL_SPEC_ONLY = "DOCUMENTED_VS_IMPLEMENTED_SPEC_ONLY"
FINDING_DOC_VS_IMPL_IMPLEMENTATION_ONLY = "DOCUMENTED_VS_IMPLEMENTED_IMPLEMENTATION_ONLY"
FINDING_TYPES: Tuple[str, ...] = (
    FINDING_CONFLICT, FINDING_GAP,
    FINDING_DOC_VS_IMPL_SPEC_ONLY, FINDING_DOC_VS_IMPL_IMPLEMENTATION_ONLY,
)

CONSENSUS_SINGLE_SOURCE = "SINGLE_SOURCE"
CONSENSUS_AGREEMENT = "AGREEMENT"
CONSENSUS_CONFLICT = "CONFLICT"


class DesignKnowledgeCorrelationError(ValueError):
    """A caller usage error -- malformed source/fact/expected-fact input, not
    a correlation finding. Raised loudly rather than silently skipping the
    offending record, the same fail-closed shape as
    `dut_evidence_correlation.DutEvidenceCorrelationError`."""


# --------------------------------------------------------------------------
# Validation / normalization
# --------------------------------------------------------------------------

def _require_nonempty_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DesignKnowledgeCorrelationError(f"{what} must be a non-empty string, got {value!r}")
    return value


def _validate_sources(sources: Any) -> List[Dict[str, Any]]:
    if not isinstance(sources, list) or not sources:
        raise DesignKnowledgeCorrelationError("sources must be a non-empty list of source dicts")
    seen_ids: Dict[str, int] = {}
    normalized: List[Dict[str, Any]] = []
    for i, src in enumerate(sources):
        if not isinstance(src, dict):
            raise DesignKnowledgeCorrelationError(f"sources[{i}] must be a dict, got {type(src).__name__}")
        source_id = _require_nonempty_str(src.get("source_id"), f"sources[{i}].source_id")
        if source_id in seen_ids:
            raise DesignKnowledgeCorrelationError(
                f"duplicate source_id {source_id!r} at sources[{i}] and sources[{seen_ids[source_id]}]"
            )
        seen_ids[source_id] = i
        source_kind = _require_nonempty_str(src.get("source_kind"), f"sources[{i}].source_kind ({source_id!r})")
        role = src.get("role", ROLE_OTHER)
        if role not in SOURCE_ROLES:
            raise DesignKnowledgeCorrelationError(
                f"sources[{i}] ({source_id!r}).role must be one of {SOURCE_ROLES}, got {role!r}"
            )
        raw_facts = src.get("facts") or []
        if not isinstance(raw_facts, list):
            raise DesignKnowledgeCorrelationError(f"sources[{i}] ({source_id!r}).facts must be a list")
        facts: List[Dict[str, Any]] = []
        for j, fact in enumerate(raw_facts):
            if not isinstance(fact, dict):
                raise DesignKnowledgeCorrelationError(
                    f"sources[{i}] ({source_id!r}).facts[{j}] must be a dict, got {type(fact).__name__}"
                )
            fact_key = _require_nonempty_str(
                fact.get("fact_key"), f"sources[{i}] ({source_id!r}).facts[{j}].fact_key"
            )
            if "value" not in fact:
                raise DesignKnowledgeCorrelationError(
                    f"sources[{i}] ({source_id!r}).facts[{j}] (fact_key={fact_key!r}) is missing required key 'value'"
                )
            fact_type = fact.get("fact_type")
            if fact_type is not None and not isinstance(fact_type, str):
                raise DesignKnowledgeCorrelationError(
                    f"sources[{i}] ({source_id!r}).facts[{j}].fact_type must be a string when present"
                )
            evidence_ref = fact.get("evidence_ref")
            if evidence_ref is not None and not isinstance(evidence_ref, str):
                raise DesignKnowledgeCorrelationError(
                    f"sources[{i}] ({source_id!r}).facts[{j}].evidence_ref must be a string when present"
                )
            facts.append({
                "fact_key": fact_key, "fact_type": fact_type,
                "value": fact["value"], "evidence_ref": evidence_ref,
            })
        normalized.append({
            "source_id": source_id, "source_kind": source_kind, "role": role, "facts": facts,
        })
    return normalized


def _validate_expected_facts(expected_facts: Any) -> List[Dict[str, Any]]:
    if expected_facts is None:
        return []
    if not isinstance(expected_facts, list):
        raise DesignKnowledgeCorrelationError("expected_facts must be a list when supplied")
    normalized: List[Dict[str, Any]] = []
    seen: set = set()
    for i, entry in enumerate(expected_facts):
        if not isinstance(entry, dict):
            raise DesignKnowledgeCorrelationError(f"expected_facts[{i}] must be a dict, got {type(entry).__name__}")
        fact_key = _require_nonempty_str(entry.get("fact_key"), f"expected_facts[{i}].fact_key")
        if fact_key in seen:
            continue  # duplicate expectation for the same fact -- not an error, just redundant
        seen.add(fact_key)
        reason = entry.get("reason")
        required_by = entry.get("required_by")
        normalized.append({
            "fact_key": fact_key,
            "reason": reason if isinstance(reason, str) else None,
            "required_by": required_by if isinstance(required_by, str) else None,
        })
    return normalized


# --------------------------------------------------------------------------
# Value equivalence
# --------------------------------------------------------------------------

def _try_float(v: Any) -> Optional[float]:
    if isinstance(v, (dict, list)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _values_equivalent(a: Any, b: Any) -> bool:
    """Representation-tolerant, substance-strict. See module docstring's
    "THE VALUE COMPARATOR" section for what this deliberately does and does
    not normalize."""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        try:
            return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
        except TypeError:
            return repr(a) == repr(b)
    fa, fb = _try_float(a), _try_float(b)
    if fa is not None and fb is not None:
        return abs(fa - fb) <= max(1e-9, 0.01 * max(abs(fa), abs(fb)))
    return str(a).strip().lower() == str(b).strip().lower()


def _cluster_by_value(assertions: Sequence[Dict[str, Any]]) -> List[List[int]]:
    """Union-find clustering of `assertions` (each carrying a "value") into
    equivalence classes under `_values_equivalent`. Small-N pairwise
    comparison -- the number of sources asserting one fact is never large."""
    n = len(assertions)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        for j in range(i + 1, n):
            if _values_equivalent(assertions[i]["value"], assertions[j]["value"]):
                union(i, j)

    clusters: Dict[int, List[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)
    return list(clusters.values())


# --------------------------------------------------------------------------
# Fact index
# --------------------------------------------------------------------------

def _index_facts(sources: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """fact_key -> list of assertions, each carrying source_id/source_kind/
    role/value/evidence_ref/fact_type, in source-declaration order."""
    index: Dict[str, List[Dict[str, Any]]] = {}
    for src in sources:
        for fact in src["facts"]:
            index.setdefault(fact["fact_key"], []).append({
                "source_id": src["source_id"],
                "source_kind": src["source_kind"],
                "role": src["role"],
                "value": fact["value"],
                "evidence_ref": fact["evidence_ref"],
                "fact_type": fact["fact_type"],
            })
    return index


# --------------------------------------------------------------------------
# Design Knowledge Graph
# --------------------------------------------------------------------------

def build_knowledge_graph(sources: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Assembles a Design Knowledge Graph over already-validated `sources`
    (the normalized shape `_validate_sources()` returns). SOURCE nodes and
    FACT nodes, connected by ASSERTS edges; each FACT node additionally
    carries its own `provenance` list inline (per-node provenance), so a
    reader does not have to walk the edge list to see who said what about a
    given fact."""
    fact_index = _index_facts(sources)

    source_nodes = [
        {"node_id": f"source:{s['source_id']}", "node_type": "SOURCE",
         "source_id": s["source_id"], "source_kind": s["source_kind"], "role": s["role"]}
        for s in sources
    ]

    fact_nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    for fact_key, assertions in fact_index.items():
        clusters = _cluster_by_value(assertions)
        if len(assertions) == 1:
            consensus = CONSENSUS_SINGLE_SOURCE
        elif len(clusters) == 1:
            consensus = CONSENSUS_AGREEMENT
        else:
            consensus = CONSENSUS_CONFLICT
        fact_types = sorted({a["fact_type"] for a in assertions if a["fact_type"]})
        provenance = [
            {"source_id": a["source_id"], "source_kind": a["source_kind"], "role": a["role"],
             "value": a["value"], "evidence_ref": a["evidence_ref"]}
            for a in assertions
        ]
        fact_nodes.append({
            "node_id": f"fact:{fact_key}", "node_type": "FACT", "fact_key": fact_key,
            "fact_types": fact_types, "consensus": consensus,
            "distinct_value_count": len(clusters), "assertion_count": len(assertions),
            "provenance": provenance,
        })
        for a in assertions:
            edges.append({
                "from": f"source:{a['source_id']}", "to": f"fact:{fact_key}", "relation": "ASSERTS",
                "value": a["value"], "evidence_ref": a["evidence_ref"], "role": a["role"],
            })

    fact_nodes.sort(key=lambda n: n["fact_key"])
    return {
        "nodes": {"sources": source_nodes, "facts": fact_nodes},
        "edges": edges,
        "summary": {
            "source_count": len(source_nodes), "fact_count": len(fact_nodes), "edge_count": len(edges),
            "facts_in_conflict": sum(1 for n in fact_nodes if n["consensus"] == CONSENSUS_CONFLICT),
        },
    }


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------

def _detect_conflicts(fact_index: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for fact_key in sorted(fact_index):
        assertions = fact_index[fact_key]
        if len(assertions) < 2:
            continue
        clusters = _cluster_by_value(assertions)
        if len(clusters) < 2:
            continue
        groups = []
        for cluster in clusters:
            members = [assertions[i] for i in cluster]
            groups.append({
                "sample_value": members[0]["value"],
                "sources": [
                    {"source_id": m["source_id"], "value": m["value"], "evidence_ref": m["evidence_ref"]}
                    for m in members
                ],
            })
        # deterministic ordering: by first source_id in each group
        groups.sort(key=lambda g: g["sources"][0]["source_id"])
        findings.append({
            "finding_type": FINDING_CONFLICT,
            "fact_key": fact_key,
            "node_id": f"fact:{fact_key}",
            "distinct_value_groups": groups,
            "reason": (
                f"{len(groups)} distinct value(s) asserted by {len(assertions)} source(s) for "
                f"fact_key {fact_key!r}; this module reports the disagreement and does not decide "
                f"which side is right -- arbitration (e.g. via source_authority.resolve_conflict() "
                f"given each side's authority tier) is a separate, human-checked decision."
            ),
        })
    return findings


def _detect_gaps(
    fact_index: Dict[str, List[Dict[str, Any]]], expected_facts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for exp in expected_facts:
        fact_key = exp["fact_key"]
        if fact_index.get(fact_key):
            continue
        reason_bits = []
        if exp["reason"]:
            reason_bits.append(exp["reason"])
        if exp["required_by"]:
            reason_bits.append(f"required by {exp['required_by']}")
        detail = "; ".join(reason_bits) if reason_bits else "no reason/required_by supplied by the caller"
        findings.append({
            "finding_type": FINDING_GAP,
            "fact_key": fact_key,
            "node_id": f"fact:{fact_key}",
            "expected_reason": exp["reason"],
            "required_by": exp["required_by"],
            "reason": (
                f"fact_key {fact_key!r} was declared expected ({detail}) but no supplied source "
                f"asserts any value for it."
            ),
        })
    return findings


def _detect_documented_vs_implemented(fact_index: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for fact_key in sorted(fact_index):
        assertions = fact_index[fact_key]
        spec_assertions = [a for a in assertions if a["role"] == ROLE_SPEC_DECLARATION]
        impl_assertions = [a for a in assertions if a["role"] == ROLE_IMPLEMENTATION_EVIDENCE]
        if spec_assertions and not impl_assertions:
            findings.append({
                "finding_type": FINDING_DOC_VS_IMPL_SPEC_ONLY,
                "fact_key": fact_key,
                "node_id": f"fact:{fact_key}",
                "spec_sources": [
                    {"source_id": a["source_id"], "value": a["value"], "evidence_ref": a["evidence_ref"]}
                    for a in spec_assertions
                ],
                "reason": (
                    f"fact_key {fact_key!r} is declared by {len(spec_assertions)} SPEC_DECLARATION "
                    f"source(s) but no IMPLEMENTATION_EVIDENCE source asserts it -- a spec-declared "
                    f"fact with no RTL/implementation evidence."
                ),
            })
        elif impl_assertions and not spec_assertions:
            findings.append({
                "finding_type": FINDING_DOC_VS_IMPL_IMPLEMENTATION_ONLY,
                "fact_key": fact_key,
                "node_id": f"fact:{fact_key}",
                "implementation_sources": [
                    {"source_id": a["source_id"], "value": a["value"], "evidence_ref": a["evidence_ref"]}
                    for a in impl_assertions
                ],
                "reason": (
                    f"fact_key {fact_key!r} is asserted by {len(impl_assertions)} IMPLEMENTATION_EVIDENCE "
                    f"source(s) but no SPEC_DECLARATION source ever declared it -- implementation evidence "
                    f"for something the spec never declared."
                ),
            })
        # both present (with or without value agreement -- agreement/conflict is CONFLICT's job)
        # or neither present (OTHER-only coverage): no doc-vs-impl finding, by design (see docstring).
    return findings


# --------------------------------------------------------------------------
# Front door
# --------------------------------------------------------------------------

def correlate(sources: Any, expected_facts: Any = None) -> Dict[str, Any]:
    """The one entry point. `sources` and `expected_facts` are plain
    dicts/lists (see module docstring for the shape); raises
    DesignKnowledgeCorrelationError on malformed input. Returns a report
    carrying `conflicts` / `gaps` / `documented_vs_implemented` (each a list
    of findings) plus the assembled `knowledge_graph` and a `summary`."""
    norm_sources = _validate_sources(sources)
    norm_expected = _validate_expected_facts(expected_facts)
    fact_index = _index_facts(norm_sources)

    conflicts = _detect_conflicts(fact_index)
    gaps = _detect_gaps(fact_index, norm_expected)
    doc_vs_impl = _detect_documented_vs_implemented(fact_index)
    graph = build_knowledge_graph(norm_sources)

    return {
        "summary": {
            "source_count": len(norm_sources),
            "fact_count": len(fact_index),
            "expected_fact_count": len(norm_expected),
            "conflict_count": len(conflicts),
            "gap_count": len(gaps),
            "documented_vs_implemented_count": len(doc_vs_impl),
        },
        "conflicts": conflicts,
        "gaps": gaps,
        "documented_vs_implemented": doc_vs_impl,
        "knowledge_graph": graph,
    }


# ---------------------------------------------------------------------------
# CLI front door -- python -m dv_harness.design_knowledge_correlation
# (no dv-harness verb: cli.py is out of scope for this task; the suggested
# STAGE_GATES / CLI-verb snippet an integrator could wire in is returned in
# this task's structured output rather than written here.)
# ---------------------------------------------------------------------------

def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="design-knowledge-correlation")
    parser.add_argument("--sources", required=True, help="path to a JSON file: a list of source dicts")
    parser.add_argument("--expected-facts", help="path to a JSON file: a list of {fact_key, reason?, required_by?}")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)

    sources = json.loads(Path(args.sources).read_text(encoding="utf-8"))
    expected_facts = None
    if args.expected_facts:
        expected_facts = json.loads(Path(args.expected_facts).read_text(encoding="utf-8"))

    try:
        report = correlate(sources, expected_facts)
    except DesignKnowledgeCorrelationError as e:
        print(f"malformed input: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        s = report["summary"]
        print(
            f"sources={s['source_count']} facts={s['fact_count']} "
            f"conflicts={s['conflict_count']} gaps={s['gap_count']} "
            f"documented_vs_implemented={s['documented_vs_implemented_count']}"
        )
        for finding in report["conflicts"] + report["gaps"] + report["documented_vs_implemented"]:
            print(f"  [{finding['finding_type']}] {finding['fact_key']}: {finding['reason']}")

    bad = (
        report["summary"]["conflict_count"]
        + report["summary"]["gap_count"]
        + report["summary"]["documented_vs_implemented_count"]
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(execute_verb())
