"""dv_harness/fabric_progress_ir.py -- FabricProgressIR: deadlock/livelock
RISK reporting over a caller-declared resource-dependency graph and a
caller-declared credit/outstanding-transaction fact set.

GAP THIS CLOSES. This project's real AMBA/SyoSil integration family
(`amba_fabric_discovery.py`, `amba_port_registry.py`, `amba_fabric_analysis.py`,
`amba_transaction_ir.py`, `amba_route_transform_predictor.py`,
`amba_scoreboard_env.py`, `syoscb_*`) already models fabric TOPOLOGY,
TRANSACTION content and ROUTING/TRANSFORM prediction -- none of it asks
whether a caller-declared wait-for relationship among fabric agents forms a
real CIRCULAR WAIT, and none of it tracks credit/outstanding-transaction
counts toward exhaustion. A repo-wide check before writing this module found
no `deadlock`/`livelock`/`circular_wait`/`credit_exhaust`/`outstanding_exhaust`
detector anywhere in `dv_harness/` (the word "deadlock" appears only inside
free-text failure-classifier regexes in `system_failure_taxonomy.py` and
`command_error_taxonomy.py`, which classify already-REPORTED failure TEXT --
neither builds or walks a dependency graph). `dv_harness/fabric_progress_ir.py`
is that missing analysis, and only that.

WHAT THIS IS. Two independent, real graph/arithmetic analyses over facts a
caller already has -- never self-derived from RTL, a VIP transaction stream,
or any other producer in this project:

  1. `analyze_resource_dependency_cycle(facts)` -- `facts` is a generic list
     of `{resource, held_by, waiting_for}` records (the exact shape this
     task names): `resource` is the arbitrated fabric resource this fact is
     about (a port, a shared bus, a buffer slot, an arbitration grant), and
     `held_by` is the agent presently holding it. `waiting_for` names zero,
     one, or several OTHER resources that same holder is blocked waiting to
     acquire before it can make forward progress (a bare string, a list of
     strings, or absent/None -- not blocked). This module never invents a
     circular-wait scenario: it builds a resource->holder map from the
     `resource`/`held_by` pairs the caller already declared, resolves each
     `waiting_for` entry to the (holder of that resource) it names, and runs
     real cycle detection over the resulting holder-level wait-for graph.

  2. `analyze_credit_outstanding(facts)` -- `facts` is a generic list of
     `{resource, credit_available, credit_max, outstanding_count,
     outstanding_limit}` records (all fields but `resource` optional; a fact
     may declare the credit axis, the outstanding axis, or both). Exhaustion
     is decided from the caller's own numbers: `credit_available <= 0` is
     `CREDIT_EXHAUSTED`; `outstanding_count >= outstanding_limit` is
     `OUTSTANDING_EXHAUSTED`. Neither threshold, neither axis's presence, and
     neither number is invented here.

`analyze_fabric_progress(resource_dependency_facts, credit_outstanding_facts)`
composes all THREE into one `FabricProgressIR`, folding an `overall_status`
by strict WORST-WINS (a real risk finding on ANY axis outranks everything;
an evidence GAP on any axis, with no real risk found anywhere, outranks a
clean report on all three) -- the same no-averaging discipline
`golden_flow_readiness.combine_readiness()` / `spec_vplan_readiness_gate.py`
/ `system_readiness_gates.py` already apply to their own composite folds,
never re-derived a second way here.

  3. `analyze_resource_contention(facts)` -- a real CONTENTION-specific
     metric this module's original two analyses never asked: over the SAME
     `resource_dependency_facts` shape `analyze_resource_dependency_cycle()`
     already consumes, this counts, per resource, how many DISTINCT holders
     currently declare that resource in their own `waiting_for` -- i.e. how
     many real parties are concurrently racing to acquire it. This is a
     genuinely different question from circular-wait detection (a resource
     can be heavily contended with zero cycle anywhere in the graph -- N
     agents queued on one arbiter grant is real contention with no deadlock)
     and from credit/outstanding exhaustion (a resource can be contended
     while its own credit/outstanding counters are still healthy). A
     resource with two or more concurrent waiters is `CONTENDED`; the module
     never invents a severity threshold beyond that raw count, and never
     arbitrates an ambiguous holder declaration here either -- an ambiguously
     -held contended resource is reported with `holder: None`,
     `ambiguous_holder: True`, and its real waiter set, never a guessed
     single holder.

THE EVIDENCE TRUTH RULE, APPLIED LITERALLY. This module's headline
obligation is the one this task states explicitly: never claim
deadlock-freedom (or exhaustion-freedom) from an INCOMPLETE graph. A
`waiting_for` entry naming a resource this module has no `{resource,
held_by}` fact for at all, or one whose holder is AMBIGUOUS (two facts
declare two different holders for the same resource -- a real evidence
conflict this module never arbitrates, the same ARBITRATION boundary
`requirement_contract.py`/`design_knowledge_correlation.py` already keep for
their own conflicting-claim findings), is reported as an UNRESOLVED
dependency. Finding zero cycles over a graph carrying even one unresolved
dependency reports `INSUFFICIENT_EVIDENCE`, never `NO_CYCLE_DETECTED` -- an
absent edge is not proof no cycle exists through it. A genuine cycle found
DESPITE some other, unrelated unresolved edges is still reported as
`CIRCULAR_WAIT_DETECTED`, because a real proven cycle is real evidence
regardless of what else in the graph could not be resolved. Symmetrically
for credit/outstanding: a fact declaring `outstanding_count` with no
`outstanding_limit` (or vice versa) cannot be judged on that axis and
contributes `INSUFFICIENT_EVIDENCE`, never a guessed OK.

WHAT THIS MODULE DOES NOT DO. It never arbitrates an ambiguous holder
declaration, never picks an arbitration WINNER, never proposes a fix, never
retries anything, never touches a human-approval gate, and performs no file
I/O or subprocess call of its own -- every input is a plain, generic/
duck-typed parameter. Per this batch's file-safety scope it imports nothing
from any file in this project's claimed-file list or from any other new
module in this same batch; the only import is `dv_harness.models` (a small,
stable, unclaimed enum), used solely to assert this module's own vocabulary
shares no token with a real verification-verdict status -- the same
disjointness discipline several sibling taxonomy/classification modules in
this project already apply to themselves.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

# -----------------------------------------------------------------------------
# Vocabulary.
# -----------------------------------------------------------------------------

#: Circular-wait detection over the resource-dependency graph -- exactly the
#: three values this task names, verbatim.
CIRCULAR_WAIT_STATUSES: Tuple[str, ...] = (
    "NO_CYCLE_DETECTED",
    "CIRCULAR_WAIT_DETECTED",
    "INSUFFICIENT_EVIDENCE",
)

#: Credit/outstanding exhaustion detection over the credit/outstanding fact
#: set. A composite value distinguishes "both axes exhausted" from either
#: alone rather than silently reporting only one of two simultaneous findings.
CREDIT_OUTSTANDING_STATUSES: Tuple[str, ...] = (
    "NO_EXHAUSTION_DETECTED",
    "CREDIT_EXHAUSTION_DETECTED",
    "OUTSTANDING_EXHAUSTION_DETECTED",
    "CREDIT_AND_OUTSTANDING_EXHAUSTION_DETECTED",
    "INSUFFICIENT_EVIDENCE",
)

#: Concurrent resource CONTENTION -- two or more distinct holders declared
#: as waiting to acquire the same resource at once. A separate concern from
#: both circular-wait detection and credit/outstanding exhaustion; a fourth
#: vocabulary, never a relabeling of either.
CONTENTION_STATUSES: Tuple[str, ...] = (
    "NO_CONTENTION_DETECTED",
    "CONTENTION_DETECTED",
    "INSUFFICIENT_EVIDENCE",
)

#: Per-resource contention verdict.
RESOURCE_CONTENTION_STATUSES: Tuple[str, ...] = (
    "CONTENDED",
    "NOT_CONTENDED",
)

#: The composed report's own overall status -- a fifth vocabulary, never a
#: relabeling of any sub-analysis's own words, so a reader always knows
#: which report a given status string belongs to.
OVERALL_STATUSES: Tuple[str, ...] = (
    "NO_RISK_DETECTED",
    "PROGRESS_RISK_DETECTED",
    "INSUFFICIENT_EVIDENCE",
)


class FabricProgressIrError(ValueError):
    """A resource-dependency or credit/outstanding fact was malformed --
    never silently dropped or coerced. Carries a real `code` naming which
    rule was violated."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's three vocabularies must share no token with
    `dv_harness.models.Status`, the harness's stage-verdict vocabulary -- a
    fabric-progress finding must never be confusable with a stage PASS/FAIL.
    Run at import time, the same discipline several sibling taxonomy/
    classification modules in this project already apply to themselves."""
    from .models import Status

    verdicts = {s.value for s in Status}
    vocabulary = (
        set(CIRCULAR_WAIT_STATUSES)
        | set(CREDIT_OUTSTANDING_STATUSES)
        | set(CONTENTION_STATUSES)
        | set(RESOURCE_CONTENTION_STATUSES)
        | set(OVERALL_STATUSES)
    )
    collision = verdicts.intersection(vocabulary)
    if collision:
        raise AssertionError(
            f"fabric_progress_ir vocabulary collides with dv_harness.models.Status "
            f"on {sorted(collision)} -- a fabric-progress finding must never be "
            "confusable with a verification verdict"
        )


# -----------------------------------------------------------------------------
# (1) Resource-dependency circular-wait detection.
# -----------------------------------------------------------------------------


def _normalize_waiting_for(raw: Any, *, resource: str) -> List[str]:
    """Normalize one fact's `waiting_for` field to a list of resource names
    (possibly empty -- "not currently blocked"). Accepts a bare string, a
    list/tuple of strings, or None/absent. Anything else is malformed."""
    if raw is None:
        return []
    if isinstance(raw, str):
        stripped = raw.strip()
        return [stripped] if stripped else []
    if isinstance(raw, (list, tuple)):
        out: List[str] = []
        for item in raw:
            if not isinstance(item, str) or not item.strip():
                raise FabricProgressIrError(
                    "MALFORMED_WAITING_FOR",
                    f"resource {resource!r}: waiting_for list entries must be "
                    f"non-empty strings, got {item!r}",
                )
            out.append(item.strip())
        return out
    raise FabricProgressIrError(
        "MALFORMED_WAITING_FOR",
        f"resource {resource!r}: waiting_for must be a str, a list of str, or "
        f"None, got {type(raw)}",
    )


@dataclass
class ResourceDependencyFact:
    resource: str
    held_by: str
    waiting_for: List[str] = field(default_factory=list)


def _parse_resource_dependency_facts(
    facts: Sequence[Mapping[str, Any]]
) -> List[ResourceDependencyFact]:
    parsed: List[ResourceDependencyFact] = []
    for i, raw in enumerate(facts):
        if not isinstance(raw, Mapping):
            raise FabricProgressIrError(
                "MALFORMED_FACT", f"resource-dependency fact[{i}] must be a mapping, got {type(raw)}"
            )
        resource = raw.get("resource")
        held_by = raw.get("held_by")
        if not isinstance(resource, str) or not resource.strip():
            raise FabricProgressIrError(
                "MISSING_RESOURCE", f"resource-dependency fact[{i}] must declare a non-empty 'resource'"
            )
        if not isinstance(held_by, str) or not held_by.strip():
            raise FabricProgressIrError(
                "MISSING_HELD_BY",
                f"resource-dependency fact[{i}] (resource={resource!r}) must declare a non-empty 'held_by'",
            )
        waiting_for = _normalize_waiting_for(raw.get("waiting_for"), resource=resource)
        parsed.append(ResourceDependencyFact(resource.strip(), held_by.strip(), waiting_for))
    return parsed


@dataclass
class ResourceDependencyFinding:
    """Result of `analyze_resource_dependency_cycle()`.

    `status` is one of `CIRCULAR_WAIT_STATUSES`. `cycle` names the real
    holder-level cycle (first entry repeated at the end) when
    `CIRCULAR_WAIT_DETECTED`, else `None`. `cycle_detail` cites, per hop, the
    resource that hop is waiting for and who holds it, so the cycle is
    inspectable against the real facts it was derived from. `unresolved`
    lists every `waiting_for` reference this module could not resolve to a
    known, unambiguous holder (dangling or ambiguous), each with a real
    reason -- present-and-non-empty is exactly what keeps a
    `NO_CYCLE_DETECTED` result honest. `ambiguous_resources` lists any
    resource declared with two or more conflicting `held_by` values.
    """

    status: str
    cycle: Optional[List[str]]
    cycle_detail: Optional[List[Dict[str, Any]]]
    unresolved: List[Dict[str, Any]]
    ambiguous_resources: List[Dict[str, Any]]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "cycle": self.cycle,
            "cycle_detail": self.cycle_detail,
            "unresolved": list(self.unresolved),
            "ambiguous_resources": list(self.ambiguous_resources),
            "reason": self.reason,
        }


def _build_holders_by_resource(parsed: Sequence[ResourceDependencyFact]) -> Dict[str, List[str]]:
    """resource -> list of distinct declared `held_by` values, in first-seen
    order. Shared, unchanged logic behind both `analyze_resource_dependency_
    cycle()`'s ambiguity detection and `analyze_resource_contention()`'s
    holder resolution -- one definition of "who holds this resource,
    according to the facts", never two."""
    holders_by_resource: Dict[str, List[str]] = {}
    for f in parsed:
        holders_by_resource.setdefault(f.resource, [])
        if f.held_by not in holders_by_resource[f.resource]:
            holders_by_resource[f.resource].append(f.held_by)
    return holders_by_resource


def analyze_resource_dependency_cycle(
    facts: Sequence[Mapping[str, Any]]
) -> ResourceDependencyFinding:
    """Detect a real circular-wait cycle over a caller-declared
    resource-dependency graph. See the module docstring for the exact fact
    shape and the honesty rules this function enforces."""
    if facts is None:
        raise FabricProgressIrError("NULL_FACTS", "resource_dependency_facts must not be None")
    if not isinstance(facts, Sequence) or isinstance(facts, (str, bytes)):
        raise FabricProgressIrError(
            "MALFORMED_FACTS", f"resource_dependency_facts must be a sequence, got {type(facts)}"
        )
    if len(facts) == 0:
        return ResourceDependencyFinding(
            status="INSUFFICIENT_EVIDENCE",
            cycle=None,
            cycle_detail=None,
            unresolved=[],
            ambiguous_resources=[],
            reason="no resource-dependency facts declared -- nothing to analyze",
        )

    parsed = _parse_resource_dependency_facts(facts)

    # resource -> set of distinct declared holders (ambiguity detection).
    holders_by_resource = _build_holders_by_resource(parsed)

    ambiguous_resources: List[Dict[str, Any]] = [
        {"resource": r, "conflicting_holders": sorted(hs)}
        for r, hs in holders_by_resource.items()
        if len(hs) > 1
    ]
    ambiguous_resource_names = {a["resource"] for a in ambiguous_resources}

    def resolve_holder(resource_name: str) -> Optional[str]:
        if resource_name in ambiguous_resource_names:
            return None
        hs = holders_by_resource.get(resource_name)
        if not hs:
            return None
        return hs[0]

    # holder -> list of (resource_waited_for, target_holder) resolved edges.
    edges: Dict[str, List[Tuple[str, str]]] = {}
    unresolved: List[Dict[str, Any]] = []
    for f in parsed:
        edges.setdefault(f.held_by, [])
        for res in f.waiting_for:
            target = resolve_holder(res)
            if target is None:
                if res in ambiguous_resource_names:
                    reason = (
                        f"resource {res!r} has conflicting held_by declarations "
                        f"{holders_by_resource[res]!r} -- holder cannot be determined"
                    )
                else:
                    reason = (
                        f"resource {res!r} (waited for by {f.held_by!r}) is not "
                        "held by anyone in the declared facts"
                    )
                unresolved.append(
                    {
                        "holder": f.held_by,
                        "waiting_for_resource": res,
                        "reason": reason,
                    }
                )
                continue
            edges[f.held_by].append((res, target))
            edges.setdefault(target, [])

    # Real cycle detection (DFS, white/gray/black) over the resolved edges
    # only -- an unresolved edge contributes no graph structure, it only
    # contributes an honest gap recorded above.
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {node: WHITE for node in edges}
    path: List[str] = []
    path_edges: List[Tuple[str, str]] = []  # (resource_waited_for, holder) aligned with path
    found_cycle: Optional[List[str]] = None
    found_cycle_detail: Optional[List[Dict[str, Any]]] = None

    def dfs(node: str) -> bool:
        nonlocal found_cycle, found_cycle_detail
        color[node] = GRAY
        path.append(node)
        for res, target in edges.get(node, []):
            if color.get(target, WHITE) == WHITE:
                path_edges.append((res, target))
                if dfs(target):
                    return True
                path_edges.pop()
            elif color.get(target) == GRAY:
                # Found the back-edge closing a cycle: target already sits
                # somewhere earlier in `path`. Slice the cycle out precisely.
                start_index = path.index(target)
                cycle_nodes = path[start_index:] + [target]
                detail: List[Dict[str, Any]] = []
                # Rebuild the hop citations for the cyclic portion only.
                # path_edges is aligned to path[1:], so hop i explains the
                # transition path[i] -> path[i+1].
                for i in range(start_index, len(path) - 1):
                    hop_res, hop_target = path_edges[i]
                    detail.append(
                        {
                            "holder": path[i],
                            "waiting_for_resource": hop_res,
                            "held_by": hop_target,
                        }
                    )
                # Final hop closing the cycle: last path node -> target.
                detail.append(
                    {
                        "holder": path[-1],
                        "waiting_for_resource": res,
                        "held_by": target,
                    }
                )
                found_cycle = cycle_nodes
                found_cycle_detail = detail
                return True
        path.pop()
        color[node] = BLACK
        return False

    for node in list(edges.keys()):
        if color[node] == WHITE:
            path.clear()
            path_edges.clear()
            if dfs(node):
                break

    if found_cycle is not None:
        cited = " -> ".join(
            f"{hop['holder']} (waits for {hop['waiting_for_resource']!r}, held by {hop['held_by']})"
            for hop in found_cycle_detail  # type: ignore[union-attr]
        )
        return ResourceDependencyFinding(
            status="CIRCULAR_WAIT_DETECTED",
            cycle=found_cycle,
            cycle_detail=found_cycle_detail,
            unresolved=unresolved,
            ambiguous_resources=ambiguous_resources,
            reason=f"real circular wait: {cited}",
        )

    if unresolved or ambiguous_resources:
        return ResourceDependencyFinding(
            status="INSUFFICIENT_EVIDENCE",
            cycle=None,
            cycle_detail=None,
            unresolved=unresolved,
            ambiguous_resources=ambiguous_resources,
            reason=(
                f"no cycle proven, but {len(unresolved)} waiting_for reference(s) and "
                f"{len(ambiguous_resources)} ambiguous resource(s) could not be resolved -- "
                "deadlock-freedom cannot be claimed from an incomplete graph"
            ),
        )

    return ResourceDependencyFinding(
        status="NO_CYCLE_DETECTED",
        cycle=None,
        cycle_detail=None,
        unresolved=[],
        ambiguous_resources=[],
        reason="every waiting_for reference resolved to a known, unambiguous holder; no cycle found",
    )


# -----------------------------------------------------------------------------
# (2) Credit/outstanding-transaction exhaustion detection.
# -----------------------------------------------------------------------------


def _as_optional_number(raw: Any, *, field_name: str, resource: str) -> Optional[Union[int, float]]:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise FabricProgressIrError(
            "MALFORMED_CREDIT_FIELD",
            f"resource {resource!r}: {field_name!r} must be a number or None, got {type(raw)}",
        )
    return raw


@dataclass
class CreditOutstandingResourceFinding:
    resource: str
    credit_status: str  # "CREDIT_OK" | "CREDIT_EXHAUSTED" | "NOT_DECLARED"
    credit_detail: Optional[Dict[str, Any]]
    outstanding_status: str  # "OUTSTANDING_OK" | "OUTSTANDING_EXHAUSTED" | "INSUFFICIENT_EVIDENCE" | "NOT_DECLARED"
    outstanding_detail: Optional[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource": self.resource,
            "credit_status": self.credit_status,
            "credit_detail": self.credit_detail,
            "outstanding_status": self.outstanding_status,
            "outstanding_detail": self.outstanding_detail,
        }


@dataclass
class CreditOutstandingAnalysis:
    status: str
    findings: List[CreditOutstandingResourceFinding]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "findings": [f.to_dict() for f in self.findings],
            "reason": self.reason,
        }


def analyze_credit_outstanding(
    facts: Sequence[Mapping[str, Any]]
) -> CreditOutstandingAnalysis:
    """Detect credit-exhaustion / outstanding-transaction-exhaustion over a
    caller-declared credit/outstanding fact set. See the module docstring
    for the exact fact shape and the honesty rules this function enforces."""
    if facts is None:
        raise FabricProgressIrError("NULL_FACTS", "credit_outstanding_facts must not be None")
    if not isinstance(facts, Sequence) or isinstance(facts, (str, bytes)):
        raise FabricProgressIrError(
            "MALFORMED_FACTS", f"credit_outstanding_facts must be a sequence, got {type(facts)}"
        )
    if len(facts) == 0:
        return CreditOutstandingAnalysis(
            status="INSUFFICIENT_EVIDENCE",
            findings=[],
            reason="no credit/outstanding facts declared -- nothing to analyze",
        )

    findings: List[CreditOutstandingResourceFinding] = []
    for i, raw in enumerate(facts):
        if not isinstance(raw, Mapping):
            raise FabricProgressIrError(
                "MALFORMED_FACT", f"credit/outstanding fact[{i}] must be a mapping, got {type(raw)}"
            )
        resource = raw.get("resource")
        if not isinstance(resource, str) or not resource.strip():
            raise FabricProgressIrError(
                "MISSING_RESOURCE", f"credit/outstanding fact[{i}] must declare a non-empty 'resource'"
            )
        resource = resource.strip()

        credit_available = _as_optional_number(raw.get("credit_available"), field_name="credit_available", resource=resource)
        credit_max = _as_optional_number(raw.get("credit_max"), field_name="credit_max", resource=resource)
        outstanding_count = _as_optional_number(raw.get("outstanding_count"), field_name="outstanding_count", resource=resource)
        outstanding_limit = _as_optional_number(raw.get("outstanding_limit"), field_name="outstanding_limit", resource=resource)

        has_any_field = any(
            v is not None for v in (credit_available, credit_max, outstanding_count, outstanding_limit)
        )
        if not has_any_field:
            raise FabricProgressIrError(
                "NO_CREDIT_OR_OUTSTANDING_FIELDS",
                f"resource {resource!r} declares neither a credit nor an outstanding field -- "
                "nothing for this module to judge",
            )

        # Credit axis.
        if credit_available is None:
            credit_status = "NOT_DECLARED"
            credit_detail = None
        elif credit_available <= 0:
            credit_status = "CREDIT_EXHAUSTED"
            credit_detail = {"credit_available": credit_available, "credit_max": credit_max}
        else:
            credit_status = "CREDIT_OK"
            credit_detail = {"credit_available": credit_available, "credit_max": credit_max}

        # Outstanding axis.
        if outstanding_count is None and outstanding_limit is None:
            outstanding_status = "NOT_DECLARED"
            outstanding_detail = None
        elif outstanding_count is None or outstanding_limit is None:
            outstanding_status = "INSUFFICIENT_EVIDENCE"
            outstanding_detail = {
                "outstanding_count": outstanding_count,
                "outstanding_limit": outstanding_limit,
                "reason": "both outstanding_count and outstanding_limit are required to judge exhaustion",
            }
        elif outstanding_count >= outstanding_limit:
            outstanding_status = "OUTSTANDING_EXHAUSTED"
            outstanding_detail = {"outstanding_count": outstanding_count, "outstanding_limit": outstanding_limit}
        else:
            outstanding_status = "OUTSTANDING_OK"
            outstanding_detail = {"outstanding_count": outstanding_count, "outstanding_limit": outstanding_limit}

        findings.append(
            CreditOutstandingResourceFinding(
                resource=resource,
                credit_status=credit_status,
                credit_detail=credit_detail,
                outstanding_status=outstanding_status,
                outstanding_detail=outstanding_detail,
            )
        )

    any_credit_exhausted = any(f.credit_status == "CREDIT_EXHAUSTED" for f in findings)
    any_outstanding_exhausted = any(f.outstanding_status == "OUTSTANDING_EXHAUSTED" for f in findings)
    any_insufficient = any(f.outstanding_status == "INSUFFICIENT_EVIDENCE" for f in findings)

    if any_credit_exhausted and any_outstanding_exhausted:
        status = "CREDIT_AND_OUTSTANDING_EXHAUSTION_DETECTED"
        reason = "both a credit exhaustion and an outstanding-transaction exhaustion were detected"
    elif any_credit_exhausted:
        status = "CREDIT_EXHAUSTION_DETECTED"
        reason = "at least one resource has credit_available <= 0"
    elif any_outstanding_exhausted:
        status = "OUTSTANDING_EXHAUSTION_DETECTED"
        reason = "at least one resource has outstanding_count >= outstanding_limit"
    elif any_insufficient:
        status = "INSUFFICIENT_EVIDENCE"
        reason = (
            "no exhaustion proven, but at least one resource declared an outstanding_count "
            "or outstanding_limit with no matching counterpart -- exhaustion-freedom cannot "
            "be claimed from an incomplete fact"
        )
    else:
        status = "NO_EXHAUSTION_DETECTED"
        reason = "every declared credit/outstanding axis was judged and none is exhausted"

    return CreditOutstandingAnalysis(status=status, findings=findings, reason=reason)


# -----------------------------------------------------------------------------
# (3) Resource-contention detection -- a contention-specific metric neither
# the cycle detector nor the credit/outstanding analysis above computes.
# -----------------------------------------------------------------------------


@dataclass
class ResourceContentionFinding:
    """One resource's own contention verdict.

    `holder` is the resolved, unambiguous `held_by` value when exactly one is
    declared for this resource, else `None` (with `ambiguous_holder: True`)
    -- this module never guesses a single holder out of two conflicting
    declarations, the same arbitration boundary
    `analyze_resource_dependency_cycle()` already keeps. `waiters` names
    every DISTINCT holder whose own `waiting_for` names this resource;
    `status` is `CONTENDED` when two or more concurrent waiters are declared,
    `NOT_CONTENDED` otherwise (zero or exactly one waiter -- a single queued
    party is not contention)."""

    resource: str
    holder: Optional[str]
    ambiguous_holder: bool
    waiter_count: int
    waiters: List[str]
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource": self.resource,
            "holder": self.holder,
            "ambiguous_holder": self.ambiguous_holder,
            "waiter_count": self.waiter_count,
            "waiters": list(self.waiters),
            "status": self.status,
        }


@dataclass
class ResourceContentionAnalysis:
    status: str
    findings: List[ResourceContentionFinding]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "findings": [f.to_dict() for f in self.findings],
            "reason": self.reason,
        }


def analyze_resource_contention(
    facts: Sequence[Mapping[str, Any]]
) -> ResourceContentionAnalysis:
    """Detect real CONTENTION -- two or more distinct holders concurrently
    declared as waiting to acquire the SAME resource -- over the identical
    `resource_dependency_facts` shape `analyze_resource_dependency_cycle()`
    consumes. See the module docstring's item (3) for why this is a
    genuinely separate metric from circular-wait detection and from
    credit/outstanding exhaustion, never folded into either."""
    if facts is None:
        raise FabricProgressIrError("NULL_FACTS", "resource_dependency_facts must not be None")
    if not isinstance(facts, Sequence) or isinstance(facts, (str, bytes)):
        raise FabricProgressIrError(
            "MALFORMED_FACTS", f"resource_dependency_facts must be a sequence, got {type(facts)}"
        )
    if len(facts) == 0:
        return ResourceContentionAnalysis(
            status="INSUFFICIENT_EVIDENCE",
            findings=[],
            reason="no resource-dependency facts declared -- nothing to analyze for contention",
        )

    parsed = _parse_resource_dependency_facts(facts)
    holders_by_resource = _build_holders_by_resource(parsed)

    # resource -> list of distinct holders whose own waiting_for names it.
    waiters_by_resource: Dict[str, List[str]] = {}
    for f in parsed:
        for res in f.waiting_for:
            waiters_by_resource.setdefault(res, [])
            if f.held_by not in waiters_by_resource[res]:
                waiters_by_resource[res].append(f.held_by)

    findings: List[ResourceContentionFinding] = []
    any_contended = False
    for resource in sorted(waiters_by_resource):
        waiters = sorted(waiters_by_resource[resource])
        holders = holders_by_resource.get(resource, [])
        ambiguous = len(holders) > 1
        holder = holders[0] if len(holders) == 1 else None
        contended = len(waiters) >= 2
        if contended:
            any_contended = True
        findings.append(
            ResourceContentionFinding(
                resource=resource,
                holder=holder,
                ambiguous_holder=ambiguous,
                waiter_count=len(waiters),
                waiters=waiters,
                status="CONTENDED" if contended else "NOT_CONTENDED",
            )
        )

    if any_contended:
        contended_names = [f.resource for f in findings if f.status == "CONTENDED"]
        return ResourceContentionAnalysis(
            status="CONTENTION_DETECTED",
            findings=findings,
            reason=(
                f"{len(contended_names)} resource(s) have two or more concurrent waiters: "
                f"{', '.join(contended_names)}"
            ),
        )

    return ResourceContentionAnalysis(
        status="NO_CONTENTION_DETECTED",
        findings=findings,
        reason="no resource has more than one concurrent waiter declared",
    )


# -----------------------------------------------------------------------------
# Composed report.
# -----------------------------------------------------------------------------


@dataclass
class FabricProgressIR:
    overall_status: str
    resource_dependency: ResourceDependencyFinding
    credit_outstanding: CreditOutstandingAnalysis
    resource_contention: ResourceContentionAnalysis

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "resource_dependency": self.resource_dependency.to_dict(),
            "credit_outstanding": self.credit_outstanding.to_dict(),
            "resource_contention": self.resource_contention.to_dict(),
        }


_RISK_CREDIT_STATUSES = (
    "CREDIT_EXHAUSTION_DETECTED",
    "OUTSTANDING_EXHAUSTION_DETECTED",
    "CREDIT_AND_OUTSTANDING_EXHAUSTION_DETECTED",
)


def analyze_fabric_progress(
    resource_dependency_facts: Sequence[Mapping[str, Any]],
    credit_outstanding_facts: Sequence[Mapping[str, Any]],
) -> FabricProgressIR:
    """Compose `analyze_resource_dependency_cycle()`,
    `analyze_credit_outstanding()` and `analyze_resource_contention()` (the
    latter re-run over the same `resource_dependency_facts`) into one
    `FabricProgressIR`, folding `overall_status` by strict worst-wins: a real
    risk finding on ANY axis outranks everything; an evidence gap on any
    axis (with no real risk found anywhere) outranks a clean report on all
    three -- never averaged, never silently dropped."""
    rd = analyze_resource_dependency_cycle(resource_dependency_facts)
    co = analyze_credit_outstanding(credit_outstanding_facts)
    contention = analyze_resource_contention(resource_dependency_facts)

    if (
        rd.status == "CIRCULAR_WAIT_DETECTED"
        or co.status in _RISK_CREDIT_STATUSES
        or contention.status == "CONTENTION_DETECTED"
    ):
        overall = "PROGRESS_RISK_DETECTED"
    elif (
        rd.status == "INSUFFICIENT_EVIDENCE"
        or co.status == "INSUFFICIENT_EVIDENCE"
        or contention.status == "INSUFFICIENT_EVIDENCE"
    ):
        overall = "INSUFFICIENT_EVIDENCE"
    else:
        overall = "NO_RISK_DETECTED"

    return FabricProgressIR(
        overall_status=overall,
        resource_dependency=rd,
        credit_outstanding=co,
        resource_contention=contention,
    )


# -----------------------------------------------------------------------------
# CLI front door. No `dv-harness` verb is registered -- `cli.py`/`gates.py`
# are outside this batch's file-safety scope. `python -m
# dv_harness.fabric_progress_ir` is the ad hoc entry point.
# -----------------------------------------------------------------------------


def _load_json_list(path: Optional[str]) -> List[Dict[str, Any]]:
    if not path:
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise FabricProgressIrError("MALFORMED_INPUT_FILE", f"{path!r} must contain a JSON list")
    return data


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dv_harness.fabric_progress_ir")
    parser.add_argument("--resource-dependency", dest="resource_dependency", default=None)
    parser.add_argument("--credit-outstanding", dest="credit_outstanding", default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        rd_facts = _load_json_list(args.resource_dependency)
        co_facts = _load_json_list(args.credit_outstanding)
        report = analyze_fabric_progress(rd_facts, co_facts)
    except FabricProgressIrError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}))
        return 2

    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"overall_status: {report.overall_status}")
        print(f"resource_dependency.status: {report.resource_dependency.status}")
        print(f"  {report.resource_dependency.reason}")
        print(f"credit_outstanding.status: {report.credit_outstanding.status}")
        print(f"  {report.credit_outstanding.reason}")
        print(f"resource_contention.status: {report.resource_contention.status}")
        print(f"  {report.resource_contention.reason}")

    if report.overall_status == "PROGRESS_RISK_DETECTED":
        return 1
    if report.overall_status == "INSUFFICIENT_EVIDENCE":
        return 2
    return 0


assert_no_verification_verdict_vocabulary()


if __name__ == "__main__":
    sys.exit(main())
