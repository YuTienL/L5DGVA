"""dv_harness/amba_functional_coverage_ir.py -- AMBAFunctionalCoverageIR: connectivity-driven,
memory-map-driven, routing-driven and ordering-driven functional coverpoints for an AMBA fabric,
plus "meaningful crosses only" and a 7-value per-bin REACHABILITY classification that is never
collapsed to a binary covered/uncovered.

WHY A 7-VALUE REACHABILITY CLASSIFICATION, NOT A BOOLEAN
---------------------------------------------------------------------------
"Covered" and "uncovered" is not the only interesting distinction a functional-coverage bin can
carry. A bin with no connectivity-legal path behind it is a fundamentally different fact from a
bin that IS legal but simply has not been hit yet, which is again different from a bin whose
reachability could not even be established because nobody supplied connectivity evidence for it,
which is again different from a bin two evidence sources actively disagree about. Collapsing all
of those into "uncovered" would erase exactly the distinctions a coverage-closure review needs
(compare `coverage_analysis.classify_coverage_hole()`'s four root causes, or this same session's
`classify_cross_coverage_meaningfulness()` precedent in `pattern_coverage_contribution.py`, both
built on the identical principle: never let an absence of proof read as a confirmed negative, and
never let two different kinds of "not covered" collapse into one word). This module's
`classify_bin_reachability()` is the AMBA-specific instance of that same discipline, over seven
named outcomes (`REACHABILITY_VALUES`) instead of two.

WHAT THIS MODULE DOES AND DOES NOT OWN (per this task's file-safety scope)
---------------------------------------------------------------------------
Per this batch's task boundary, this module does NOT import `connectivity.py` or
`amba_master_slave_constraint_ir.py` (a separate task in this same batch owns the latter) --
connectivity-legal-edge facts, address-region facts, routing facts and ordering facts are all
accepted as generic, duck-typed parameters (plain dicts with documented, aliased key names),
exactly the "accept an explicit caller-declared fact rather than invent one" discipline
`ip_ownership_conflict.py`'s `legacy_bfm_declarations` and
`existing_command_reuse_score.py`'s `existing_commands` already established for a fact their own
real evidence store cannot supply on its own. This module also imports no other new module from
this same batch, per the batch's own "never import from any other new module in this batch"
scope rule.

Nothing here decides connectivity legality, address-map ownership, routing/transform behaviour,
or ordering semantics -- those are real facts a caller (a real connectivity pipeline, a real
address-map cross-check, `amba_route_transform_predictor.py`, a real ordering/ID-tracking
analysis) must supply. This module only turns those facts into coverpoint bins, classifies each
bin's reachability honestly, and decides which CROSS-coverage bins are worth tracking at all.

"MEANINGFUL CROSSES ONLY" -- REIMPLEMENTED INDEPENDENTLY, NOT IMPORTED
---------------------------------------------------------------------------
`pattern_coverage_contribution.py` (this same 2026-09-06 session) already solves almost exactly
this task's "skip a cross whose two axes are already fully explained by their own single-axis
bins" requirement, in its own `classify_cross_coverage_meaningfulness()`. Per this task's own
explicit instruction ("do not import that file, reimplement the same small check independently"),
this module's `classify_cross_coverage_meaningfulness()` below is a fresh, independent
implementation of the identical small idea -- both answer "are this cross bin's two axes already
fully explained by their own single-axis coverage" from the same kind of evidence
(`{"bins_total","bins_hit"}` category snapshots), independently, by design for this batch. The
duplication is disclosed, not hidden.

WHAT THIS MODULE DOES NOT DO
---------------------------------------------------------------------------
It writes nothing to any evidence store and mints no memory/blackboard/approval record. It runs
no build, job, or LSF submission, and there is deliberately no stage gate here -- a gate that
passed on a coverage IR nobody reviewed would be worse than none.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


class AMBAFunctionalCoverageIRError(ValueError):
    """Raised on malformed input this module was explicitly handed (a bad edge/region/route/
    ordering fact, or a malformed cross request) -- never on an honest absence of evidence, which
    is reported as a real reachability status (`REACHABILITY_UNKNOWN_INSUFFICIENT_EVIDENCE`)
    instead."""


# ---------------------------------------------------------------------------
# 7-value reachability vocabulary -- deliberately never collapsed to 2.
# ---------------------------------------------------------------------------
COVERED_OBSERVED = "COVERED_OBSERVED"
REACHABLE_NOT_YET_HIT = "REACHABLE_NOT_YET_HIT"
PARTIALLY_REACHABLE_CONDITIONAL = "PARTIALLY_REACHABLE_CONDITIONAL"
UNREACHABLE_NO_LEGAL_PATH = "UNREACHABLE_NO_LEGAL_PATH"
UNREACHABLE_STRUCTURALLY_EXCLUDED = "UNREACHABLE_STRUCTURALLY_EXCLUDED"
REACHABILITY_CONTRADICTED = "REACHABILITY_CONTRADICTED"
REACHABILITY_UNKNOWN_INSUFFICIENT_EVIDENCE = "REACHABILITY_UNKNOWN_INSUFFICIENT_EVIDENCE"

#: The seven values, in the order `classify_bin_reachability()` decides them -- most-evidenced
#: (a real observed hit) first, least-evidenced (nothing was supplied at all) near the end.
REACHABILITY_VALUES: Tuple[str, ...] = (
    COVERED_OBSERVED,
    REACHABILITY_CONTRADICTED,
    UNREACHABLE_STRUCTURALLY_EXCLUDED,
    UNREACHABLE_NO_LEGAL_PATH,
    REACHABILITY_UNKNOWN_INSUFFICIENT_EVIDENCE,
    PARTIALLY_REACHABLE_CONDITIONAL,
    REACHABLE_NOT_YET_HIT,
)

#: A bin whose reachability is one of these is real, confirmed evidence one way or the other --
#: used only for reporting/summary, never to silently promote a bin's own recorded status.
_RESOLVED_REACHABILITY: frozenset = frozenset({
    COVERED_OBSERVED, UNREACHABLE_NO_LEGAL_PATH, UNREACHABLE_STRUCTURALLY_EXCLUDED,
})

# ---------------------------------------------------------------------------
# Coverpoint categories
# ---------------------------------------------------------------------------
CATEGORY_CONNECTIVITY = "CONNECTIVITY"
CATEGORY_MEMORY_MAP = "MEMORY_MAP"
CATEGORY_ROUTING = "ROUTING"
CATEGORY_ORDERING = "ORDERING"
CATEGORY_CROSS_PREFIX = "CROSS"

COVERPOINT_CATEGORIES: Tuple[str, ...] = (
    CATEGORY_CONNECTIVITY, CATEGORY_MEMORY_MAP, CATEGORY_ROUTING, CATEGORY_ORDERING,
)

# ---------------------------------------------------------------------------
# Cross-coverage-meaningfulness verdicts -- an independent reimplementation of the same idea
# `pattern_coverage_contribution.classify_cross_coverage_meaningfulness()` already solves; see
# the module docstring for why this is a deliberate, disclosed duplication rather than an import.
# ---------------------------------------------------------------------------
CROSS_MEANINGFUL = "INDEPENDENTLY_MEANINGFUL"
CROSS_FULLY_EXPLAINED = "FULLY_EXPLAINED_BY_AXES"
CROSS_UNKNOWN = "UNKNOWN_AXIS_COVERAGE"

CROSS_VERDICTS: Tuple[str, ...] = (CROSS_MEANINGFUL, CROSS_FULLY_EXPLAINED, CROSS_UNKNOWN)


# ---------------------------------------------------------------------------
# Per-bin reachability classification
# ---------------------------------------------------------------------------
_EVIDENCE_FIELDS: Tuple[str, ...] = (
    "observed_hit", "legal", "structurally_excluded", "conditional", "contradicting_evidence",
)


def classify_bin_reachability(fact: Dict[str, Any]) -> Tuple[str, str]:
    """The one place this module decides a bin's reachability, from real caller-declared
    evidence fields on `fact` -- never from a bin's own name or identity.

    Recognised fields (every one optional; an absent field is `None`/falsy, never guessed):
      `observed_hit`   -- True if a real recorded coverage sample hit this bin.
      `legal`          -- True/False/None: does a real connectivity-legal-edge fact support this
                          bin. None means no connectivity evidence was supplied for it at all.
      `structurally_excluded` -- True when a real address-map/config fact excludes this bin
                          structurally (a reserved region, an illegal register-field combination).
      `conditional`    -- True when the bin is reachable only under a declared conditional
                          configuration/mode, never unconditionally.
      `contradicting_evidence` -- True when the caller has already determined two real evidence
                          sources disagree about this bin. Also DERIVED here (not only accepted):
                          `structurally_excluded` together with `legal is True` is itself a
                          contradiction (connectivity says legal, another real source says
                          excluded), and is treated as one even when the caller did not flag it
                          explicitly.

    Returns `(status, reason)`, `status` always one of `REACHABILITY_VALUES`. A real observed hit
    always wins regardless of what any other field claims -- a bin that was actually hit IS
    reachable, whatever a connectivity fact says about it."""
    if not isinstance(fact, dict):
        raise AMBAFunctionalCoverageIRError(f"a coverpoint fact must be a dict, got {fact!r}")

    observed_hit = fact.get("observed_hit")
    legal = fact.get("legal")
    structurally_excluded = bool(fact.get("structurally_excluded"))
    conditional = bool(fact.get("conditional"))
    contradicting = bool(fact.get("contradicting_evidence"))

    if observed_hit is True:
        return COVERED_OBSERVED, "a real observed coverage sample recorded a hit on this bin"

    # A structural exclusion asserted alongside an affirmatively-legal connectivity fact is a
    # real disagreement between two sources, whether or not the caller flagged it explicitly.
    if structurally_excluded and legal is True:
        contradicting = True

    if contradicting:
        return REACHABILITY_CONTRADICTED, (
            "supplied evidence disagrees about whether this bin is reachable -- e.g. "
            "connectivity evidence says this edge is legal while another real source says the "
            "bin is structurally excluded; a human must resolve which is stale")

    if structurally_excluded:
        return UNREACHABLE_STRUCTURALLY_EXCLUDED, (
            "real address-map/configuration evidence excludes this bin structurally (a reserved "
            "region, an illegal register-field or mode combination)")

    if legal is False:
        return UNREACHABLE_NO_LEGAL_PATH, (
            "the supplied connectivity-legal-edge facts contain no legal path supporting this bin")

    if legal is None:
        return REACHABILITY_UNKNOWN_INSUFFICIENT_EVIDENCE, (
            "no connectivity-legal-edge fact was supplied for this bin; reachability cannot be "
            "established one way or the other")

    # legal is True from here.
    if conditional:
        return PARTIALLY_REACHABLE_CONDITIONAL, (
            "reachable only under a declared conditional configuration/mode, not "
            "unconditionally, per the supplied connectivity evidence")

    return REACHABLE_NOT_YET_HIT, (
        "a real connectivity-legal edge supports this bin but no observed hit has been recorded "
        "yet")


def _bin_id(category: str, identity: Dict[str, Any]) -> str:
    parts = "|".join(f"{k}={identity[k]}" for k in sorted(identity))
    return f"{category}:{parts}" if parts else category


def _make_bin(category: str, identity: Dict[str, Any], fact: Dict[str, Any]) -> Dict[str, Any]:
    status, reason = classify_bin_reachability(fact)
    return {
        "bin_id": _bin_id(category, identity),
        "category": category,
        **identity,
        "reachability": status,
        "reachability_reason": reason,
        "evidence": {k: fact.get(k) for k in _EVIDENCE_FIELDS if k in fact},
    }


def _require_dict(item: Any, where: str) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise AMBAFunctionalCoverageIRError(f"{where} is not a dict: {item!r}")
    return item


def _require_facts_list(facts: Any, argname: str) -> Sequence[Dict[str, Any]]:
    if facts is None:
        return ()
    if not isinstance(facts, (list, tuple)):
        raise AMBAFunctionalCoverageIRError(f"{argname} must be a list of fact dicts")
    return facts


# ---------------------------------------------------------------------------
# Connectivity-driven coverpoints
# ---------------------------------------------------------------------------
def build_connectivity_coverpoints(legal_edges: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One coverpoint bin per declared master-slave (or generic source-dest) pair.

    `legal_edges` is a generic, duck-typed list -- the real connectivity-legal-edge facts this
    module never derives itself. Each entry names the pair under `master`/`source` and
    `slave`/`dest` (whichever pair of keys the caller's real connectivity pipeline uses) plus any
    of the reachability evidence fields `classify_bin_reachability()` recognises."""
    edges = _require_facts_list(legal_edges, "legal_edges")
    bins: List[Dict[str, Any]] = []
    seen: set = set()
    for i, edge in enumerate(edges):
        edge = _require_dict(edge, f"legal_edges[{i}]")
        master = edge.get("master", edge.get("source"))
        slave = edge.get("slave", edge.get("dest"))
        if not master or not slave:
            raise AMBAFunctionalCoverageIRError(
                f"legal_edges[{i}] must name a real 'master'/'source' and 'slave'/'dest'")
        key = (master, slave)
        if key in seen:
            raise AMBAFunctionalCoverageIRError(
                f"legal_edges declares the pair {master!r}->{slave!r} more than once; each "
                "master-slave pair may appear once")
        seen.add(key)
        bins.append(_make_bin(CATEGORY_CONNECTIVITY, {"master": master, "slave": slave}, edge))
    return bins


# ---------------------------------------------------------------------------
# Memory-map-driven coverpoints
# ---------------------------------------------------------------------------
def build_memory_map_coverpoints(address_regions: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One coverpoint bin per declared address-region access -- a real owner/region name,
    optionally crossed with the accessing master when the caller's real address-map facts name
    one. `address_regions` is a generic, duck-typed list of address-map facts (never re-derived
    here -- a real address-map cross-check, e.g. `amba_fabric_analysis.py`'s AMBA-23, supplies
    them)."""
    regions = _require_facts_list(address_regions, "address_regions")
    bins: List[Dict[str, Any]] = []
    seen: set = set()
    for i, region in enumerate(regions):
        region = _require_dict(region, f"address_regions[{i}]")
        owner = region.get("owner", region.get("region"))
        if not owner:
            raise AMBAFunctionalCoverageIRError(
                f"address_regions[{i}] must name a real 'owner'/'region'")
        identity: Dict[str, Any] = {"owner": owner}
        accessor = region.get("accessor", region.get("master"))
        if accessor:
            identity["accessor"] = accessor
        key = tuple(sorted(identity.items()))
        if key in seen:
            raise AMBAFunctionalCoverageIRError(
                f"address_regions declares {identity} more than once")
        seen.add(key)
        bins.append(_make_bin(CATEGORY_MEMORY_MAP, identity, region))
    return bins


# ---------------------------------------------------------------------------
# Routing-driven coverpoints
# ---------------------------------------------------------------------------
def build_routing_coverpoints(route_facts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One coverpoint bin per declared routing/transform path through the fabric -- a real
    source-to-destination route, optionally naming the hop sequence. `route_facts` is a generic,
    duck-typed list (never re-derived here -- a real route/transform predictor, e.g.
    `amba_route_transform_predictor.py`, supplies them; this module never imports it)."""
    routes = _require_facts_list(route_facts, "route_facts")
    bins: List[Dict[str, Any]] = []
    seen: set = set()
    for i, route in enumerate(routes):
        route = _require_dict(route, f"route_facts[{i}]")
        source = route.get("source", route.get("master"))
        dest = route.get("dest", route.get("destination", route.get("slave")))
        if not source or not dest:
            raise AMBAFunctionalCoverageIRError(
                f"route_facts[{i}] must name a real 'source' and 'dest'/'destination'")
        identity: Dict[str, Any] = {"source": source, "dest": dest}
        hops = route.get("hops", route.get("path"))
        if hops:
            identity["hops"] = "->".join(str(h) for h in hops) if isinstance(hops, (list, tuple)) else str(hops)
        key = tuple(sorted(identity.items()))
        if key in seen:
            raise AMBAFunctionalCoverageIRError(f"route_facts declares {identity} more than once")
        seen.add(key)
        bins.append(_make_bin(CATEGORY_ROUTING, identity, route))
    return bins


# ---------------------------------------------------------------------------
# Ordering-driven coverpoints
# ---------------------------------------------------------------------------
def build_ordering_coverpoints(ordering_facts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One coverpoint bin per declared ordering scenario -- e.g. an outstanding-transaction-depth
    bucket, a same-ID reordering scenario, an out-of-order-completion scenario -- optionally
    scoped to a real master/ID. `ordering_facts` is a generic, duck-typed list (never re-derived
    here -- a real transaction-IR/ordering analysis, e.g. `amba_transaction_ir.py`, supplies
    them)."""
    facts = _require_facts_list(ordering_facts, "ordering_facts")
    bins: List[Dict[str, Any]] = []
    seen: set = set()
    for i, fact in enumerate(facts):
        fact = _require_dict(fact, f"ordering_facts[{i}]")
        scenario = fact.get("scenario")
        if not scenario:
            raise AMBAFunctionalCoverageIRError(f"ordering_facts[{i}] must name a real 'scenario'")
        identity: Dict[str, Any] = {"scenario": scenario}
        for key in ("master", "id_value"):
            if fact.get(key):
                identity[key] = fact[key]
        ident_key = tuple(sorted(identity.items()))
        if ident_key in seen:
            raise AMBAFunctionalCoverageIRError(f"ordering_facts declares {identity} more than once")
        seen.add(ident_key)
        bins.append(_make_bin(CATEGORY_ORDERING, identity, fact))
    return bins


# ---------------------------------------------------------------------------
# "Meaningful crosses only" -- independent reimplementation; see module docstring.
# ---------------------------------------------------------------------------
def classify_cross_coverage_meaningfulness(
    categories_snapshot: Dict[str, Dict[str, Any]],
    cross_definitions: Sequence[Dict[str, Any]],
    *, threshold_percent: float = 100.0,
) -> List[Dict[str, Any]]:
    """`categories_snapshot` is `{category_name: {"bins_total", "bins_hit"}}` -- a generic
    single-axis coverage snapshot, the same shape any of this module's own coverpoint lists
    reduce to (see `axis_snapshot_from_bins()`). `cross_definitions` is `[{"cross_name",
    "axes": [name1, name2, ...]}]` -- a real, caller-declared fact about which axes a cross
    coverpoint crosses (this module never derives a cross relationship from a bin's own name).

    Returns one record per cross definition: `{"cross_name", "axes", "verdict", "reason",
    "axis_details"}`. `verdict` is `FULLY_EXPLAINED_BY_AXES` ONLY when EVERY declared axis is both
    present in `categories_snapshot` and at/above `threshold_percent` (`bins_hit >= bins_total`
    when `bins_total > 0`). An axis missing from the snapshot, or whose own `bins_total` is not a
    real positive int/float, makes the whole cross `UNKNOWN_AXIS_COVERAGE` -- absence of proof
    that the axes explain the cross is never read as proof they do."""
    if not isinstance(cross_definitions, (list, tuple)):
        raise AMBAFunctionalCoverageIRError(
            "cross_definitions must be a list of {'cross_name','axes'} records")
    results: List[Dict[str, Any]] = []
    for i, cdef in enumerate(cross_definitions):
        cdef = _require_dict(cdef, f"cross_definitions[{i}]")
        cross_name = cdef.get("cross_name")
        axes = cdef.get("axes")
        if not cross_name or not isinstance(cross_name, str):
            raise AMBAFunctionalCoverageIRError(
                f"cross_definitions[{i}] missing a real 'cross_name'")
        if not isinstance(axes, list) or len(axes) < 2:
            raise AMBAFunctionalCoverageIRError(
                f"cross_definitions[{i}] ('{cross_name}') needs >= 2 real 'axes' names")

        axis_details: List[Dict[str, Any]] = []
        all_fully_explained = True
        any_unknown = False
        for axis in axes:
            axis_cat = categories_snapshot.get(axis)
            if not isinstance(axis_cat, dict):
                axis_details.append({"axis": axis, "known": False,
                                      "reason": "axis category not present in the supplied snapshot"})
                any_unknown = True
                all_fully_explained = False
                continue
            bins_total = axis_cat.get("bins_total")
            bins_hit = axis_cat.get("bins_hit")
            if not isinstance(bins_total, (int, float)) or bins_total <= 0 \
                    or not isinstance(bins_hit, (int, float)):
                axis_details.append({"axis": axis, "known": False,
                                      "reason": "axis category has no real bins_total/bins_hit"})
                any_unknown = True
                all_fully_explained = False
                continue
            percent = (bins_hit / bins_total) * 100.0
            fully = percent >= threshold_percent
            axis_details.append({
                "axis": axis, "known": True, "bins_hit": bins_hit, "bins_total": bins_total,
                "percent": percent, "fully_explained": fully,
            })
            if not fully:
                all_fully_explained = False

        if any_unknown:
            verdict = CROSS_UNKNOWN
            reason = "at least one axis's coverage could not be confirmed from supplied evidence"
        elif all_fully_explained:
            verdict = CROSS_FULLY_EXPLAINED
            reason = f"every declared axis is already >= {threshold_percent}% covered"
        else:
            verdict = CROSS_MEANINGFUL
            reason = "at least one declared axis is not yet fully covered"

        results.append({"cross_name": cross_name, "axes": list(axes), "verdict": verdict,
                         "reason": reason, "axis_details": axis_details})
    return results


def axis_snapshot_from_bins(bins: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Reduce a list of already-built coverpoint bins to the `{"bins_total","bins_hit"}` shape
    `classify_cross_coverage_meaningfulness()` needs for one axis. A bin counts as "hit" only
    when its own recorded reachability is `COVERED_OBSERVED` -- any of the other six statuses,
    however reachable-looking, is not a real observed hit."""
    total = len(bins)
    hit = sum(1 for b in bins if b.get("reachability") == COVERED_OBSERVED)
    return {"bins_total": total, "bins_hit": hit}


def evaluate_cross(
    axis_a_name: str, axis_a_snapshot: Dict[str, Any],
    axis_b_name: str, axis_b_snapshot: Dict[str, Any],
    cross_facts: Optional[Sequence[Dict[str, Any]]] = None,
    *, cross_name: Optional[str] = None, threshold_percent: float = 100.0,
) -> Dict[str, Any]:
    """Evaluate one two-axis cross and build its coverpoint bins ONLY when the cross is genuinely
    meaningful. When `classify_cross_coverage_meaningfulness()` reports
    `FULLY_EXPLAINED_BY_AXES` this cross is SKIPPED -- no per-combination bins are built at all,
    because the whole point of "meaningful crosses only" is to not even track a cross whose
    information the two single-axis bin sets already fully carry.

    `cross_facts` (when the cross is not skipped) is a generic list of dicts each naming
    `axis_a_value`/`axis_b_value` plus any reachability evidence fields."""
    cross_name = cross_name or f"{axis_a_name}_x_{axis_b_name}"
    categories_snapshot = {axis_a_name: axis_a_snapshot, axis_b_name: axis_b_snapshot}
    cross_definitions = [{"cross_name": cross_name, "axes": [axis_a_name, axis_b_name]}]
    classification = classify_cross_coverage_meaningfulness(
        categories_snapshot, cross_definitions, threshold_percent=threshold_percent)[0]

    result: Dict[str, Any] = {
        "cross_name": cross_name, "axes": [axis_a_name, axis_b_name],
        "verdict": classification["verdict"], "reason": classification["reason"],
        "axis_details": classification["axis_details"],
    }
    if classification["verdict"] == CROSS_FULLY_EXPLAINED:
        result["skipped"] = True
        result["bins"] = []
        return result

    result["skipped"] = False
    bins: List[Dict[str, Any]] = []
    category = f"{CATEGORY_CROSS_PREFIX}:{cross_name}"
    seen: set = set()
    for i, fact in enumerate(cross_facts or ()):
        fact = _require_dict(fact, f"cross_facts[{i}]")
        av = fact.get("axis_a_value")
        bv = fact.get("axis_b_value")
        if av is None or bv is None:
            raise AMBAFunctionalCoverageIRError(
                f"cross_facts[{i}] missing 'axis_a_value'/'axis_b_value'")
        identity = {axis_a_name: av, axis_b_name: bv}
        key = tuple(sorted(identity.items()))
        if key in seen:
            raise AMBAFunctionalCoverageIRError(f"cross_facts declares {identity} more than once")
        seen.add(key)
        bins.append(_make_bin(category, identity, fact))
    result["bins"] = bins
    return result


# ---------------------------------------------------------------------------
# The assembled IR
# ---------------------------------------------------------------------------
class AMBAFunctionalCoverageIR:
    """Connectivity-driven, memory-map-driven, routing-driven and ordering-driven coverpoints for
    one AMBA fabric, plus zero or more meaningful-crosses-only cross-coverage evaluations."""

    def __init__(self) -> None:
        self.connectivity_coverpoints: List[Dict[str, Any]] = []
        self.memory_map_coverpoints: List[Dict[str, Any]] = []
        self.routing_coverpoints: List[Dict[str, Any]] = []
        self.ordering_coverpoints: List[Dict[str, Any]] = []
        self.crosses: List[Dict[str, Any]] = []

    @classmethod
    def build(
        cls,
        *, legal_edges: Optional[Sequence[Dict[str, Any]]] = None,
        address_regions: Optional[Sequence[Dict[str, Any]]] = None,
        route_facts: Optional[Sequence[Dict[str, Any]]] = None,
        ordering_facts: Optional[Sequence[Dict[str, Any]]] = None,
        cross_requests: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> "AMBAFunctionalCoverageIR":
        """`cross_requests` is a list of `{"axis_a_name","axis_a_snapshot" or "axis_a_category",
        "axis_b_name","axis_b_snapshot" or "axis_b_category", "cross_facts", "cross_name"?,
        "threshold_percent"?}` records. `axis_a_snapshot`/`axis_b_snapshot` may be given directly
        (`{"bins_total","bins_hit"}`), or `axis_a_category`/`axis_b_category` may name one of this
        IR's own four built coverpoint categories (`CATEGORY_CONNECTIVITY` etc.) to derive the
        snapshot from the bins this same call just built -- never from a stale, separately-passed
        set."""
        ir = cls()
        ir.connectivity_coverpoints = build_connectivity_coverpoints(legal_edges or [])
        ir.memory_map_coverpoints = build_memory_map_coverpoints(address_regions or [])
        ir.routing_coverpoints = build_routing_coverpoints(route_facts or [])
        ir.ordering_coverpoints = build_ordering_coverpoints(ordering_facts or [])

        by_category = {
            CATEGORY_CONNECTIVITY: ir.connectivity_coverpoints,
            CATEGORY_MEMORY_MAP: ir.memory_map_coverpoints,
            CATEGORY_ROUTING: ir.routing_coverpoints,
            CATEGORY_ORDERING: ir.ordering_coverpoints,
        }

        for i, req in enumerate(cross_requests or ()):
            req = _require_dict(req, f"cross_requests[{i}]")
            axis_a_name = req.get("axis_a_name")
            axis_b_name = req.get("axis_b_name")
            if not axis_a_name or not axis_b_name:
                raise AMBAFunctionalCoverageIRError(
                    f"cross_requests[{i}] must name a real 'axis_a_name' and 'axis_b_name'")

            axis_a_snapshot = req.get("axis_a_snapshot")
            if axis_a_snapshot is None and req.get("axis_a_category"):
                cat = req["axis_a_category"]
                if cat not in by_category:
                    raise AMBAFunctionalCoverageIRError(
                        f"cross_requests[{i}] axis_a_category {cat!r} is not one of "
                        f"{COVERPOINT_CATEGORIES}")
                axis_a_snapshot = axis_snapshot_from_bins(by_category[cat])
            axis_b_snapshot = req.get("axis_b_snapshot")
            if axis_b_snapshot is None and req.get("axis_b_category"):
                cat = req["axis_b_category"]
                if cat not in by_category:
                    raise AMBAFunctionalCoverageIRError(
                        f"cross_requests[{i}] axis_b_category {cat!r} is not one of "
                        f"{COVERPOINT_CATEGORIES}")
                axis_b_snapshot = axis_snapshot_from_bins(by_category[cat])
            if axis_a_snapshot is None or axis_b_snapshot is None:
                raise AMBAFunctionalCoverageIRError(
                    f"cross_requests[{i}] must supply 'axis_a_snapshot'/'axis_a_category' and "
                    "'axis_b_snapshot'/'axis_b_category'")

            ir.crosses.append(evaluate_cross(
                axis_a_name, axis_a_snapshot, axis_b_name, axis_b_snapshot,
                req.get("cross_facts"), cross_name=req.get("cross_name"),
                threshold_percent=req.get("threshold_percent", 100.0)))
        return ir

    def all_bins(self) -> List[Dict[str, Any]]:
        """Every non-skipped bin this IR carries, across all four categories plus every
        meaningfully-tracked cross."""
        out: List[Dict[str, Any]] = []
        out += self.connectivity_coverpoints
        out += self.memory_map_coverpoints
        out += self.routing_coverpoints
        out += self.ordering_coverpoints
        for cross in self.crosses:
            out += cross.get("bins", [])
        return out

    def reachability_summary(self) -> Dict[str, int]:
        """A count per reachability status across every bin this IR carries -- never a single
        covered/uncovered count."""
        summary = {v: 0 for v in REACHABILITY_VALUES}
        for b in self.all_bins():
            summary[b["reachability"]] = summary.get(b["reachability"], 0) + 1
        return summary

    def skipped_crosses(self) -> List[Dict[str, Any]]:
        return [c for c in self.crosses if c.get("skipped")]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "connectivity_coverpoints": list(self.connectivity_coverpoints),
            "memory_map_coverpoints": list(self.memory_map_coverpoints),
            "routing_coverpoints": list(self.routing_coverpoints),
            "ordering_coverpoints": list(self.ordering_coverpoints),
            "crosses": list(self.crosses),
            "reachability_summary": self.reachability_summary(),
        }


# ---------------------------------------------------------------------------
# Ad hoc front door
# ---------------------------------------------------------------------------
def execute_verb(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="amba-functional-coverage-ir")
    sub = parser.add_subparsers(dest="verb", required=True)

    p1 = sub.add_parser("build", help="build an AMBAFunctionalCoverageIR from a JSON facts file")
    p1.add_argument("--facts", required=True,
                     help="JSON file: {'legal_edges','address_regions','route_facts',"
                          "'ordering_facts','cross_requests'}")
    p1.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.verb == "build":
        try:
            doc = json.loads(Path(args.facts).read_text(encoding="utf-8"))
            ir = AMBAFunctionalCoverageIR.build(
                legal_edges=doc.get("legal_edges"),
                address_regions=doc.get("address_regions"),
                route_facts=doc.get("route_facts"),
                ordering_facts=doc.get("ordering_facts"),
                cross_requests=doc.get("cross_requests"),
            )
        except (AMBAFunctionalCoverageIRError, OSError, json.JSONDecodeError) as exc:
            print(f"status=ERROR reason={exc}")
            return 2

        if args.json:
            print(json.dumps(ir.to_dict(), indent=2, default=str))
        else:
            summary = ir.reachability_summary()
            print(f"bins={len(ir.all_bins())} skipped_crosses={len(ir.skipped_crosses())}")
            for status in REACHABILITY_VALUES:
                print(f"  {status}: {summary[status]}")
        return 0

    return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(execute_verb(sys.argv[1:]))
