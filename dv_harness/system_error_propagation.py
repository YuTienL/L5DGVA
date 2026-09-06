"""dv_harness/system_error_propagation.py -- an ErrorPropagationIR: given an
origin subsystem and an error/failure condition, trace which OTHER
subsystems a real cross-subsystem TOPOLOGY shows a path to, and whether
EACH affected subsystem declares a real recovery/response action.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
`system_topology_analysis.py`'s SYS-28/SYS-29 machinery already computes the
only real cross-subsystem RELATIONSHIPS this repository has: which address
regions two subsystems physically share or collide over (SYS-28), which
interrupt line names two or more subsystems' own evidence both name
(SYS-28's interrupt half), and which clock/reset names two subsystems share
or cross a shared-address path between (SYS-29). Nothing in this repo turned
those relationships into a PROPAGATION graph, or asked "if subsystem X faults,
which other subsystems does the TOPOLOGY actually show could be affected, and
has each of those affected subsystems got a real declared recovery action on
file?" This module is exactly that trace, and nothing else.

Per this task's own file-safety scope, this module does NOT import
`system_topology_analysis.py` (or `system_resource_inventory.py`, or any
other claimed-batch file). It accepts a `topology` parameter that is a
generic, duck-typed Mapping SHAPED LIKE that module's real
`build_system_topology_analysis()` output -- `address_map_reconciliation`
(with its own `overlaps` rows carrying `subsystem_a`/`subsystem_b`/
`verdict`/`pair_id`), `interrupt_map_reconciliation` (`lines` rows carrying
`line`/`verdict`/`subsystems`), and `clock_reset_comparison` (`clock_
comparisons`/`reset_comparisons` rows carrying `subsystem_a`/`subsystem_b`/
`name_a`/`name_b`/`verdict`/`pair_id`) -- read by plain dict access, never by
importing that module's classes or re-deriving its own analysis. A caller
already holding a real `system_topology_analysis.build_system_topology_
analysis()` document may pass it here VERBATIM; this module never asks for
anything that document does not already carry.

WHY ONLY THESE THREE RELATIONSHIP FAMILIES COUNT AS A REAL "PATH"
-------------------------------------------------------------------
This module never invents a propagation path. A cross-subsystem pair is only
ever treated as an edge in the propagation graph when the topology's OWN
verdict for that pair is one that SYS-28/SYS-29 themselves treat as a real,
evidenced coupling -- never one of their own honest "we could not tell"
verdicts:

- Address: `SHARED_MEMORY` (both regions are memory/DMA windows that
  genuinely intersect), `ADDRESS_OVERLAP_VALID` (both subsystems declare the
  IDENTICAL region -- one physical block seen twice), and
  `ADDRESS_OVERLAP_CONFLICT` (a real, unexplained intersection -- still a
  genuine address-range overlap, whatever explains it). The fourth SYS-28
  value, its own `UNKNOWN`, is EXCLUDED on purpose: per that module's own
  `_overlap_signals()`, `UNKNOWN` there means one side's OWN artifacts
  disagree about its base address -- a data-quality defect inside one
  subsystem, not a proven relationship between two, and asserting a
  propagation path on it would be manufacturing a cross-subsystem finding out
  of a single subsystem's internal inconsistency (that module's own words).
- Interrupt: only `INTERRUPT_LINE_SHARED_ACROSS_SUBSYSTEMS` rows (two or more
  selected subsystems' own evidence names the SAME interrupt line). A
  `INTERRUPT_LINE_SUBSYSTEM_LOCAL` row involves only one subsystem and cannot
  be an edge; its own `UNKNOWN` fourth value is excluded for the identical
  reason as address's.
- Clock/reset: `SAME_CLOCK_DOMAIN` / `CONFLICTING_CLOCK_SOURCE` /
  `CONFLICTING_CLOCK_FREQUENCY` and `CDC_BOUNDARY` (clock), `SAME_RESET_
  DOMAIN` / `CONFLICTING_RESET_POLARITY` / `CONFLICTING_RESET_SEQUENCING`
  (reset). Per that module's own `_clock_pair_signals()`/`_reset_pair_
  signals()`, the first three of each group fire ONLY when both subsystems
  name the IDENTICAL clock/reset signal -- a real shared net, whether or not
  the two sides' stated frequency/source/polarity/sequencing then agree
  (agreement is a DATA-QUALITY question; the coupling itself is real either
  way). `CDC_BOUNDARY` fires when two DIFFERENTLY-named clocks are linked by
  a real SYS-28 shared address range -- "a path crosses between two domains",
  in that module's own words. `INDEPENDENT_CLOCK_DOMAIN` /
  `INDEPENDENT_RESET_DOMAIN` (no evidence links them) and the shared
  `UNKNOWN` (facts NOT_AVAILABLE for one or both sides) are excluded.

RULE 8, ENFORCED HERE RATHER THAN RESTATED
--------------------------------------------
A Recovery Chain is reported COMPLETE only when EVERY affected subsystem
carries a real, non-placeholder declared response. One affected subsystem
with no declared response (or an absent `declared_responses` input
altogether) makes the WHOLE chain `RECOVERY_CHAIN_INCOMPLETE`, named
explicitly -- never silently folded into COMPLETE, and never defaulted to
"assume recovered" because nobody supplied an answer.

DECLARED RESPONSES ARE A CALLER-DECLARED FACT, NOT SOMETHING THIS MODULE CAN
DERIVE
-------------------------------------------------------------------------
No producer anywhere in this codebase records "subsystem X's declared
recovery action for error condition Y" (confirmed by direct search before
writing this module: no `recovery_action`/`expected_response`/`error_
handler` field exists in `env_manifest.py`'s schema or any sibling module's
output). `declared_responses` is therefore, honestly, a CALLER-SUPPLIED input
-- the same status `ip_ownership_conflict.py`'s `legacy_bfm_declarations` and
`system_resource_inventory.SubsystemResourceSources.declared_physical_
interfaces` already carry for their own no-producer facts: "a project's own
explicit statement... a human's decision, never this module's inference".

SCOPE BOUNDARY -- DETECTION AND REPORTING ONLY
-------------------------------------------------
This module traces a propagation graph and reports on recovery-declaration
completeness. It never arbitrates which subsystem's declared response is
CORRECT, never decides that a propagation path SHOULD be broken, never picks
an error-handling architecture, and never touches any build/job/approval/
governance mechanism.
"""
from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple, Union

SCHEMA_VERSION = "1.0"


# ===========================================================================
# Error-condition-kind vocabulary
# ===========================================================================

CONDITION_ADDRESS_DECODE_FAULT = "ADDRESS_DECODE_FAULT"
CONDITION_BUS_ERROR = "BUS_ERROR"
CONDITION_DMA_CORRUPTION = "DMA_CORRUPTION"
CONDITION_INTERRUPT_STORM = "INTERRUPT_STORM"
CONDITION_RESET_ASSERTION = "RESET_ASSERTION"
CONDITION_CLOCK_LOSS = "CLOCK_LOSS"
CONDITION_CDC_VIOLATION = "CDC_VIOLATION"
CONDITION_GENERIC = "GENERIC"

CONDITION_KINDS: Tuple[str, ...] = (
    CONDITION_ADDRESS_DECODE_FAULT, CONDITION_BUS_ERROR, CONDITION_DMA_CORRUPTION,
    CONDITION_INTERRUPT_STORM, CONDITION_RESET_ASSERTION, CONDITION_CLOCK_LOSS,
    CONDITION_CDC_VIOLATION, CONDITION_GENERIC,
)

# ---------------------------------------------------------------------------
# Propagation-EDGE-kind vocabulary -- one per real relationship family SYS-28/
# SYS-29 already compute (see module docstring for exactly which topology
# verdicts populate each).
# ---------------------------------------------------------------------------

EDGE_SHARED_ADDRESS_SPACE = "SHARED_ADDRESS_SPACE"
EDGE_SHARED_INTERRUPT_LINE = "SHARED_INTERRUPT_LINE"
EDGE_SHARED_CLOCK_DOMAIN = "SHARED_CLOCK_DOMAIN"
EDGE_CLOCK_DOMAIN_CROSSING = "CLOCK_DOMAIN_CROSSING"
EDGE_SHARED_RESET_DOMAIN = "SHARED_RESET_DOMAIN"

EDGE_KINDS: Tuple[str, ...] = (
    EDGE_SHARED_ADDRESS_SPACE, EDGE_SHARED_INTERRUPT_LINE, EDGE_SHARED_CLOCK_DOMAIN,
    EDGE_CLOCK_DOMAIN_CROSSING, EDGE_SHARED_RESET_DOMAIN,
)

#: Which edge kinds a given error condition can plausibly propagate over.
#: GENERIC (or an unrecognized condition kind, which is treated as GENERIC --
#: see `resolve_condition_kind()`) is deliberately the WIDEST set: an
#: unclassified condition must never be under-traced by guessing which
#: coupling it cannot cross.
CONDITION_TO_EDGE_KINDS: Dict[str, Tuple[str, ...]] = {
    CONDITION_ADDRESS_DECODE_FAULT: (EDGE_SHARED_ADDRESS_SPACE,),
    CONDITION_BUS_ERROR: (EDGE_SHARED_ADDRESS_SPACE,),
    CONDITION_DMA_CORRUPTION: (EDGE_SHARED_ADDRESS_SPACE,),
    CONDITION_INTERRUPT_STORM: (EDGE_SHARED_INTERRUPT_LINE,),
    CONDITION_RESET_ASSERTION: (EDGE_SHARED_RESET_DOMAIN,),
    CONDITION_CLOCK_LOSS: (EDGE_SHARED_CLOCK_DOMAIN,),
    CONDITION_CDC_VIOLATION: (EDGE_SHARED_CLOCK_DOMAIN, EDGE_CLOCK_DOMAIN_CROSSING,
                              EDGE_SHARED_RESET_DOMAIN),
    CONDITION_GENERIC: EDGE_KINDS,
}

# ---------------------------------------------------------------------------
# Topology verdict literals this module recognizes -- documented, not
# imported, per this task's own file-safety scope (see module docstring).
# ---------------------------------------------------------------------------

_ADDRESS_EDGE_VERDICTS = frozenset({"SHARED_MEMORY", "ADDRESS_OVERLAP_VALID",
                                    "ADDRESS_OVERLAP_CONFLICT"})
_INTERRUPT_SHARED_VERDICT = "INTERRUPT_LINE_SHARED_ACROSS_SUBSYSTEMS"
_CLOCK_SAME_DOMAIN_VERDICTS = frozenset({"SAME_CLOCK_DOMAIN", "CONFLICTING_CLOCK_SOURCE",
                                         "CONFLICTING_CLOCK_FREQUENCY"})
_CLOCK_CROSSING_VERDICT = "CDC_BOUNDARY"
_RESET_EDGE_VERDICTS = frozenset({"SAME_RESET_DOMAIN", "CONFLICTING_RESET_POLARITY",
                                  "CONFLICTING_RESET_SEQUENCING"})

# ---------------------------------------------------------------------------
# Recovery-chain / response status vocabulary. Deliberately NOT `PASS`/`FAIL`
# (both real `models.Status` members) -- see
# `assert_no_verification_verdict_vocabulary()` below.
# ---------------------------------------------------------------------------

CHAIN_COMPLETE = "RECOVERY_CHAIN_COMPLETE"
CHAIN_INCOMPLETE = "RECOVERY_CHAIN_INCOMPLETE"
CHAIN_NO_PROPAGATION = "NO_PROPAGATION_DETECTED"
CHAIN_NOT_AVAILABLE = "NOT_AVAILABLE"

RECOVERY_CHAIN_STATUSES: Tuple[str, ...] = (
    CHAIN_COMPLETE, CHAIN_INCOMPLETE, CHAIN_NO_PROPAGATION, CHAIN_NOT_AVAILABLE,
)

RESPONSE_DECLARED = "RESPONSE_DECLARED"
RESPONSE_MISSING = "NO_RESPONSE_DECLARED"
RESPONSE_PLACEHOLDER = "RESPONSE_PLACEHOLDER_ONLY"
RESPONSE_EXPLICITLY_NONE = "RESPONSE_EXPLICITLY_DECLARED_NONE"

RESPONSE_STATUSES: Tuple[str, ...] = (
    RESPONSE_DECLARED, RESPONSE_MISSING, RESPONSE_PLACEHOLDER, RESPONSE_EXPLICITLY_NONE,
)

#: Response statuses that satisfy the Recovery Chain -- exactly one value.
#: `RESPONSE_MISSING` / `RESPONSE_PLACEHOLDER` / `RESPONSE_EXPLICITLY_NONE`
#: all make the chain INCOMPLETE; none of them is ever silently promoted.
_RESPONSE_SATISFIES_CHAIN = frozenset({RESPONSE_DECLARED})

_PLACEHOLDER_TEXTS = frozenset({"", "tbd", "n/a", "na", "unknown", "?", "none", "todo",
                                "pending", "-"})


class SystemErrorPropagationError(ValueError):
    """Malformed input to this module -- raised rather than silently coerced,
    so a caller cannot trace a propagation over an origin/condition/topology
    that was never actually well-formed."""


# ===========================================================================
# Condition normalization
# ===========================================================================

def resolve_condition_kind(condition: Union[str, Mapping[str, Any], None]
                           ) -> Tuple[str, str, Optional[str]]:
    """Normalize the caller's `condition` argument into
    `(condition_kind, description, unknown_note)`.

    Accepts a bare string (matched case/whitespace-insensitively against
    `CONDITION_KINDS`; anything unmatched is treated as free-text
    DESCRIPTION of a `GENERIC` condition, never guessed into one of the
    named kinds by keyword-sniffing) or a mapping carrying `kind`/
    `condition_kind` plus `description`/`condition`/`text`.

    `unknown_note` is non-None exactly when the caller declared a kind this
    module does not recognize -- GENERIC's own (widest) edge-kind set is
    still used, but the caller is told their declared kind was not
    honored as a narrower one."""
    if condition is None:
        raise SystemErrorPropagationError("condition is required")
    if isinstance(condition, str):
        candidate = condition.strip()
        normalized = candidate.upper().replace(" ", "_").replace("-", "_")
        if normalized in CONDITION_KINDS:
            return normalized, candidate, None
        return CONDITION_GENERIC, candidate, None
    if isinstance(condition, Mapping):
        raw_kind = str(condition.get("kind") or condition.get("condition_kind") or "").strip()
        description = str(condition.get("description") or condition.get("condition")
                          or condition.get("text") or raw_kind or "")
        if not raw_kind:
            return CONDITION_GENERIC, description, None
        normalized = raw_kind.upper().replace(" ", "_").replace("-", "_")
        if normalized in CONDITION_KINDS:
            return normalized, description, None
        return (CONDITION_GENERIC, description,
                f"declared condition kind {raw_kind!r} is not one of {CONDITION_KINDS}; "
                "treated as GENERIC (the widest edge-kind set) rather than guessed")
    raise SystemErrorPropagationError(
        f"condition must be a string or a mapping, got {type(condition).__name__}")


# ===========================================================================
# Topology reading -- duck-typed, no import of system_topology_analysis.py
# ===========================================================================

def _block(topology: Mapping[str, Any], key: str) -> Dict[str, Any]:
    value = (topology or {}).get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def known_subsystems(topology: Mapping[str, Any]) -> Set[str]:
    """Every subsystem_id this topology document names anywhere -- the union
    over `selected_subsystems`, every address-region `per_subsystem` key,
    every interrupt line's `subsystems`, and every clock/reset
    `per_subsystem` key. Used only to answer "does this topology know about
    this subsystem at all", never to invent an edge."""
    ids: Set[str] = set()
    selected = (topology or {}).get("selected_subsystems")
    if isinstance(selected, Sequence) and not isinstance(selected, (str, bytes)):
        ids.update(str(s) for s in selected)

    addr = _block(topology, "address_map_reconciliation")
    per_subsystem = addr.get("per_subsystem")
    if isinstance(per_subsystem, Mapping):
        ids.update(str(k) for k in per_subsystem.keys())
    for row in addr.get("overlaps") or []:
        if isinstance(row, Mapping):
            ids.update(str(row.get(k)) for k in ("subsystem_a", "subsystem_b") if row.get(k))

    interrupts = _block(topology, "interrupt_map_reconciliation")
    for row in interrupts.get("lines") or []:
        if isinstance(row, Mapping):
            ids.update(str(s) for s in (row.get("subsystems") or []))

    clock_reset = _block(topology, "clock_reset_comparison")
    cr_per_subsystem = clock_reset.get("per_subsystem")
    if isinstance(cr_per_subsystem, Mapping):
        ids.update(str(k) for k in cr_per_subsystem.keys())
    for key in ("clock_comparisons", "reset_comparisons"):
        for row in clock_reset.get(key) or []:
            if isinstance(row, Mapping):
                ids.update(str(row.get(k)) for k in ("subsystem_a", "subsystem_b")
                          if row.get(k))

    ids.discard("")
    ids.discard("None")
    return ids


def _edge_id(kind: str, sid_a: str, sid_b: str, discriminator: str) -> str:
    pair = "|".join(sorted((sid_a, sid_b)))
    digest = hashlib.sha256(f"{kind}::{pair}::{discriminator}".encode("utf-8")).hexdigest()[:10]
    return f"EDGE-{digest.upper()}"


def _address_edges(topology: Mapping[str, Any]) -> List[Dict[str, Any]]:
    addr = _block(topology, "address_map_reconciliation")
    edges: List[Dict[str, Any]] = []
    for row in addr.get("overlaps") or []:
        if not isinstance(row, Mapping):
            continue
        verdict = str(row.get("verdict") or "")
        if verdict not in _ADDRESS_EDGE_VERDICTS:
            continue
        sid_a, sid_b = str(row.get("subsystem_a") or ""), str(row.get("subsystem_b") or "")
        if not sid_a or not sid_b or sid_a == sid_b:
            continue
        edges.append({
            "edge_id": _edge_id(EDGE_SHARED_ADDRESS_SPACE, sid_a, sid_b, str(row.get("pair_id"))),
            "kind": EDGE_SHARED_ADDRESS_SPACE,
            "subsystem_a": sid_a, "subsystem_b": sid_b,
            "verdict": verdict,
            "basis": (f"address_map_reconciliation.overlaps: {row.get('region_a')} "
                      f"({sid_a}) and {row.get('region_b')} ({sid_b}) -> {verdict}"),
            "source_field": "address_map_reconciliation.overlaps",
            "source_pair_id": row.get("pair_id"),
        })
    return edges


def _interrupt_edges(topology: Mapping[str, Any]) -> List[Dict[str, Any]]:
    interrupts = _block(topology, "interrupt_map_reconciliation")
    edges: List[Dict[str, Any]] = []
    for row in interrupts.get("lines") or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("verdict") or "") != _INTERRUPT_SHARED_VERDICT:
            continue
        subsystems = sorted({str(s) for s in (row.get("subsystems") or []) if s})
        if len(subsystems) < 2:
            continue
        line = str(row.get("line") or row.get("normalized_line") or "")
        for i, sid_a in enumerate(subsystems):
            for sid_b in subsystems[i + 1:]:
                edges.append({
                    "edge_id": _edge_id(EDGE_SHARED_INTERRUPT_LINE, sid_a, sid_b, line),
                    "kind": EDGE_SHARED_INTERRUPT_LINE,
                    "subsystem_a": sid_a, "subsystem_b": sid_b,
                    "verdict": _INTERRUPT_SHARED_VERDICT,
                    "basis": (f"interrupt_map_reconciliation.lines: {line!r} is named by both "
                              f"{sid_a} and {sid_b}'s own evidence"),
                    "source_field": "interrupt_map_reconciliation.lines",
                    "source_pair_id": None,
                    "line": line,
                })
    return edges


def _clock_reset_edges(topology: Mapping[str, Any]) -> List[Dict[str, Any]]:
    clock_reset = _block(topology, "clock_reset_comparison")
    edges: List[Dict[str, Any]] = []

    def _rows_to_edges(rows: Any, same_domain_verdicts: frozenset, crossing_verdict: Optional[str],
                       same_kind: str, crossing_kind: str, source_field: str) -> None:
        for row in rows or []:
            if not isinstance(row, Mapping):
                continue
            verdict = str(row.get("verdict") or "")
            sid_a, sid_b = str(row.get("subsystem_a") or ""), str(row.get("subsystem_b") or "")
            if not sid_a or not sid_b or sid_a == sid_b:
                continue
            if verdict in same_domain_verdicts:
                kind = same_kind
            elif crossing_verdict is not None and verdict == crossing_verdict:
                kind = crossing_kind
            else:
                continue
            edges.append({
                "edge_id": _edge_id(kind, sid_a, sid_b, str(row.get("pair_id"))),
                "kind": kind,
                "subsystem_a": sid_a, "subsystem_b": sid_b,
                "verdict": verdict,
                "basis": (f"{source_field}: {row.get('name_a')} ({sid_a}) / "
                          f"{row.get('name_b')} ({sid_b}) -> {verdict}"),
                "source_field": source_field,
                "source_pair_id": row.get("pair_id"),
            })

    _rows_to_edges(clock_reset.get("clock_comparisons"), _CLOCK_SAME_DOMAIN_VERDICTS,
                   _CLOCK_CROSSING_VERDICT, EDGE_SHARED_CLOCK_DOMAIN, EDGE_CLOCK_DOMAIN_CROSSING,
                   "clock_reset_comparison.clock_comparisons")
    _rows_to_edges(clock_reset.get("reset_comparisons"), _RESET_EDGE_VERDICTS, None,
                   EDGE_SHARED_RESET_DOMAIN, EDGE_SHARED_RESET_DOMAIN,
                   "clock_reset_comparison.reset_comparisons")
    return edges


def extract_propagation_edges(topology: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every real cross-subsystem edge this topology document proves, across
    all three relationship families, tagged by `kind`. See the module
    docstring for exactly which topology verdicts become an edge and which
    are excluded as honest non-proof."""
    edges = (_address_edges(topology) + _interrupt_edges(topology)
             + _clock_reset_edges(topology))
    edges.sort(key=lambda e: (e["kind"], e["subsystem_a"], e["subsystem_b"], e["edge_id"]))
    return edges


# ===========================================================================
# Declared-response reading -- caller-supplied, no producer exists
# ===========================================================================

def _is_placeholder(text: Any) -> bool:
    return str(text or "").strip().lower() in _PLACEHOLDER_TEXTS


def _response_text(record: Mapping[str, Any]) -> Optional[str]:
    for key in ("response_action", "response", "recovery_action", "expected_response",
                "action"):
        value = record.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def resolve_declared_response(
        subsystem_id: str,
        declared_responses: Optional[Sequence[Mapping[str, Any]]],
) -> Dict[str, Any]:
    """The real declared response for one subsystem, from the caller-supplied
    `declared_responses` records (see module docstring -- there is no real
    producer for this fact anywhere in this codebase). Each record is
    `{"subsystem_id", "response_action"/"response"/"recovery_action"/
    "expected_response"/"action", "declares_response"?, "evidence"?}`.

    Returns `{"status", "response", "evidence", "reason"}`. `status` is one
    of `RESPONSE_STATUSES`; only `RESPONSE_DECLARED` satisfies the Recovery
    Chain. A subsystem with no matching record at all is `NO_RESPONSE_
    DECLARED` -- absence is never silently read as "recovered"."""
    matches = [r for r in (declared_responses or [])
              if isinstance(r, Mapping) and str(r.get("subsystem_id") or "") == subsystem_id]
    if not matches:
        return {"status": RESPONSE_MISSING, "response": None, "evidence": None,
                "reason": (f"no declared_responses record names subsystem {subsystem_id!r} -- "
                          "absence is never read as a declared response")}
    # Last-wins on a duplicate declaration for the same subsystem, mirroring
    # the "a later reconsideration overrides an earlier one" convention this
    # project already applies elsewhere (e.g. functional_coverage_signoff.py's
    # question-queue re-answer rule) -- a caller correcting an earlier record
    # is a real update, not a conflict to arbitrate here.
    record = matches[-1]
    evidence = record.get("evidence")
    explicit_flag = record.get("declares_response")
    if explicit_flag is False:
        return {"status": RESPONSE_EXPLICITLY_NONE, "response": None, "evidence": evidence,
                "reason": (f"subsystem {subsystem_id!r}'s record explicitly declares "
                          "declares_response=False -- no recovery action was committed")}
    text = _response_text(record)
    if text is None:
        return {"status": RESPONSE_MISSING, "response": None, "evidence": evidence,
                "reason": (f"subsystem {subsystem_id!r} has a declared_responses record but it "
                          "carries no response_action/response/recovery_action/"
                          "expected_response/action text")}
    if _is_placeholder(text):
        return {"status": RESPONSE_PLACEHOLDER, "response": text, "evidence": evidence,
                "reason": (f"subsystem {subsystem_id!r}'s declared response is a placeholder "
                          f"({text!r}), not a real recovery action")}
    return {"status": RESPONSE_DECLARED, "response": text, "evidence": evidence,
            "reason": f"subsystem {subsystem_id!r} declares a real recovery action"}


# ===========================================================================
# Graph traversal
# ===========================================================================

def _adjacency(edges: Sequence[Mapping[str, Any]],
              allowed_kinds: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    allowed = set(allowed_kinds)
    adjacency: MutableMapping[str, List[Dict[str, Any]]] = {}
    for edge in edges:
        if edge["kind"] not in allowed:
            continue
        adjacency.setdefault(edge["subsystem_a"], []).append(edge)
        adjacency.setdefault(edge["subsystem_b"], []).append(edge)
    return dict(adjacency)


def _other_side(edge: Mapping[str, Any], sid: str) -> str:
    return edge["subsystem_b"] if edge["subsystem_a"] == sid else edge["subsystem_a"]


def bfs_reachable(origin: str, edges: Sequence[Mapping[str, Any]],
                  allowed_kinds: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Breadth-first reachability from `origin` over only the edges whose
    `kind` is in `allowed_kinds`. Returns `{subsystem_id: [edge, edge, ...]}`
    -- the shortest real chain of topology-proven edges from `origin` to that
    subsystem, for every OTHER subsystem the graph actually connects it to.
    `origin` itself is never included. A subsystem the graph does not
    connect to `origin` under these edge kinds is never included either --
    this is the one place "never assert propagation reaches a subsystem the
    topology does not actually show a path to" is enforced."""
    adjacency = _adjacency(edges, allowed_kinds)
    paths: Dict[str, List[Dict[str, Any]]] = {}
    visited = {origin}
    queue: deque = deque([origin])
    while queue:
        current = queue.popleft()
        for edge in adjacency.get(current, []):
            neighbor = _other_side(edge, current)
            if neighbor in visited:
                continue
            visited.add(neighbor)
            paths[neighbor] = paths.get(current, []) + [edge]
            queue.append(neighbor)
    return paths


# ===========================================================================
# ErrorPropagationIR
# ===========================================================================

@dataclass
class AffectedSubsystem:
    subsystem_id: str
    path: List[Dict[str, Any]]
    response_status: str
    declared_response: Optional[str]
    response_evidence: Optional[str]
    response_reason: str

    def to_dict(self) -> dict:
        return {
            "subsystem_id": self.subsystem_id,
            "path": list(self.path),
            "hop_count": len(self.path),
            "response_status": self.response_status,
            "declared_response": self.declared_response,
            "response_evidence": self.response_evidence,
            "response_reason": self.response_reason,
        }


@dataclass
class ErrorPropagationIR:
    schema_version: str
    origin: str
    condition_kind: str
    condition_description: str
    relevant_edge_kinds: List[str]
    edges_considered: List[Dict[str, Any]]
    affected: List[AffectedSubsystem]
    recovery_chain_status: str
    recovery_chain_reason: str
    unknowns: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "origin": self.origin,
            "condition_kind": self.condition_kind,
            "condition_description": self.condition_description,
            "relevant_edge_kinds": list(self.relevant_edge_kinds),
            "edges_considered": list(self.edges_considered),
            "affected_subsystems": [a.to_dict() for a in self.affected],
            "affected_count": len(self.affected),
            "missing_response_subsystems": sorted(
                a.subsystem_id for a in self.affected
                if a.response_status not in _RESPONSE_SATISFIES_CHAIN),
            "recovery_chain_status": self.recovery_chain_status,
            "recovery_chain_reason": self.recovery_chain_reason,
            "unknowns": list(self.unknowns),
        }


def trace_error_propagation(
        origin: str,
        condition: Union[str, Mapping[str, Any]],
        topology: Mapping[str, Any],
        *,
        declared_responses: Optional[Sequence[Mapping[str, Any]]] = None,
) -> ErrorPropagationIR:
    """The entry point: given an ORIGIN subsystem, an error/failure
    CONDITION, and a real-or-duck-typed cross-subsystem TOPOLOGY document,
    trace which OTHER subsystems the topology's own proven relationships
    show a path to, and whether each declares a real recovery action.

    `topology` is never imported from -- see the module docstring for its
    expected (duck-typed) shape. `declared_responses` is an optional list of
    caller-supplied records (see `resolve_declared_response()`); omitting it
    means every affected subsystem reads `NO_RESPONSE_DECLARED`, never an
    assumed recovery.
    """
    if not origin or not isinstance(origin, str):
        raise SystemErrorPropagationError("origin must be a non-empty subsystem_id string")
    if not isinstance(topology, Mapping):
        raise SystemErrorPropagationError(
            f"topology must be a mapping, got {type(topology).__name__}")

    condition_kind, condition_description, condition_unknown = resolve_condition_kind(condition)
    unknowns: List[Dict[str, str]] = []
    if condition_unknown:
        unknowns.append({"field": "condition_kind", "reason": condition_unknown})

    subsystems = known_subsystems(topology)
    if not subsystems:
        return ErrorPropagationIR(
            schema_version=SCHEMA_VERSION, origin=origin, condition_kind=condition_kind,
            condition_description=condition_description, relevant_edge_kinds=[],
            edges_considered=[], affected=[],
            recovery_chain_status=CHAIN_NOT_AVAILABLE,
            recovery_chain_reason=("the supplied topology names no subsystem anywhere "
                                   "(address_map_reconciliation/interrupt_map_reconciliation/"
                                   "clock_reset_comparison are all empty or absent) -- a "
                                   "propagation trace has nothing real to trace over"),
            unknowns=unknowns + [{"field": "topology",
                                  "reason": "no subsystem evidence found in any block"}])

    if origin not in subsystems:
        return ErrorPropagationIR(
            schema_version=SCHEMA_VERSION, origin=origin, condition_kind=condition_kind,
            condition_description=condition_description, relevant_edge_kinds=[],
            edges_considered=[], affected=[],
            recovery_chain_status=CHAIN_NOT_AVAILABLE,
            recovery_chain_reason=(f"origin subsystem {origin!r} is not named anywhere in the "
                                   "supplied topology -- a propagation trace cannot begin from a "
                                   "subsystem the topology does not know about"),
            unknowns=unknowns + [{"field": "origin",
                                  "reason": f"{origin!r} not found in known_subsystems(topology)"}])

    relevant_kinds = CONDITION_TO_EDGE_KINDS[condition_kind]
    all_edges = extract_propagation_edges(topology)
    reachable = bfs_reachable(origin, all_edges, relevant_kinds)
    relevant_edges = [e for e in all_edges if e["kind"] in relevant_kinds]

    affected: List[AffectedSubsystem] = []
    for sid in sorted(reachable):
        resolved = resolve_declared_response(sid, declared_responses)
        affected.append(AffectedSubsystem(
            subsystem_id=sid, path=reachable[sid],
            response_status=resolved["status"], declared_response=resolved["response"],
            response_evidence=resolved["evidence"], response_reason=resolved["reason"]))

    if not affected:
        status = CHAIN_NO_PROPAGATION
        reason = (f"no subsystem other than {origin!r} is reachable from it under the edge "
                  f"kind(s) relevant to a {condition_kind} condition ({', '.join(relevant_kinds)}) "
                  "-- the topology shows this error contained to its origin")
    else:
        missing = [a for a in affected if a.response_status not in _RESPONSE_SATISFIES_CHAIN]
        if missing:
            status = CHAIN_INCOMPLETE
            reason = (f"{len(missing)} of {len(affected)} affected subsystem(s) have no real "
                      f"declared recovery action ({', '.join(a.subsystem_id for a in missing)}) "
                      "-- the recovery chain is INCOMPLETE and never silently treated as "
                      "recovered")
        else:
            status = CHAIN_COMPLETE
            reason = (f"all {len(affected)} affected subsystem(s) reachable from {origin!r} "
                      f"under a {condition_kind} condition carry a real declared recovery action")

    return ErrorPropagationIR(
        schema_version=SCHEMA_VERSION, origin=origin, condition_kind=condition_kind,
        condition_description=condition_description, relevant_edge_kinds=list(relevant_kinds),
        edges_considered=relevant_edges, affected=affected,
        recovery_chain_status=status, recovery_chain_reason=reason, unknowns=unknowns)


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's status vocabularies must share no token with
    `models.Status` -- the same guarantee `programming_sequence_ir.py` /
    `dependency_supply_chain.py` / `capability_evolution.py` each hold for
    their own vocabularies, so a reader can never mistake a Recovery Chain
    status or a response status for a stage-gate verdict."""
    from .models import Status

    verdicts = {s.value for s in Status}
    own = set(RECOVERY_CHAIN_STATUSES) | set(RESPONSE_STATUSES) | set(CONDITION_KINDS) \
        | set(EDGE_KINDS)
    overlap = own & verdicts
    if overlap:
        raise AssertionError(
            f"system_error_propagation vocabulary collides with models.Status: {sorted(overlap)}")


assert_no_verification_verdict_vocabulary()


# ===========================================================================
# Rendering + shared CLI front door
# ===========================================================================

def format_report(report: Mapping[str, Any]) -> str:
    lines = [
        f"ERROR PROPAGATION TRACE from {report['origin']!r} "
        f"({report['condition_kind']}): {report['recovery_chain_status']}",
        "",
        report["recovery_chain_reason"],
        "",
        f"  condition: {report.get('condition_description') or '(none supplied)'}",
        f"  relevant edge kinds: {', '.join(report.get('relevant_edge_kinds') or []) or '(none)'}",
        f"  real edges considered: {len(report.get('edges_considered') or [])}",
        f"  affected subsystems: {report.get('affected_count', 0)}",
    ]
    for a in report.get("affected_subsystems") or []:
        lines.append("")
        lines.append(f"  -> {a['subsystem_id']} [{a['response_status']}] "
                     f"({a['hop_count']} hop(s))")
        lines.append(f"     {a['response_reason']}")
        for edge in a.get("path") or []:
            lines.append(f"       via {edge['kind']}: {edge['basis']}")
    if report.get("unknowns"):
        lines.append("")
        lines.append("UNKNOWNS:")
        for u in report["unknowns"]:
            lines.append(f"  [{u['field']}] {u['reason']}")
    return "\n".join(lines)


def _load_json(path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


_EXIT_BY_CHAIN_STATUS = {
    CHAIN_COMPLETE: 0,
    CHAIN_NO_PROPAGATION: 0,
    CHAIN_INCOMPLETE: 1,
    CHAIN_NOT_AVAILABLE: 2,
}


def execute_verb(*, origin: str, condition_path=None, condition_text=None,
                 topology_path: str, declared_responses_path=None,
                 as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for
    `python -m dv_harness.system_error_propagation trace ...`. Returns
    (text, exit_code): 0 RECOVERY_CHAIN_COMPLETE/NO_PROPAGATION_DETECTED,
    1 RECOVERY_CHAIN_INCOMPLETE, 2 NOT_AVAILABLE or malformed input. Reads
    only; runs/submits/approves nothing."""
    try:
        if condition_path:
            condition: Union[str, Mapping[str, Any]] = _load_json(condition_path)
        elif condition_text is not None:
            condition = condition_text
        else:
            raise SystemErrorPropagationError("either --condition or --condition-file is required")
        topology = _load_json(topology_path)
        declared_responses = _load_json(declared_responses_path) if declared_responses_path \
            else None
        ir = trace_error_propagation(origin, condition, topology,
                                     declared_responses=declared_responses)
    except SystemErrorPropagationError as e:
        return f"SystemErrorPropagationError: {e}", 2
    except (OSError, json.JSONDecodeError) as e:
        return f"failed to load input: {e}", 2

    report = ir.to_dict()
    text = json.dumps(report, indent=2) if as_json else format_report(report)
    return text, _EXIT_BY_CHAIN_STATUS[report["recovery_chain_status"]]


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.system_error_propagation",
        description="Trace an ErrorPropagationIR: given an origin subsystem and an error/"
                    "failure condition, over a real-or-duck-typed cross-subsystem topology "
                    "document, find which OTHER subsystems the topology's own proven "
                    "relationships show a path to, and whether each declares a real recovery "
                    "action. Reads only; runs/submits/approves nothing.")
    ap.add_argument("verb", choices=("trace",))
    ap.add_argument("--origin", required=True, help="Origin subsystem_id.")
    ap.add_argument("--condition", dest="condition_text", default=None,
                    help="Error condition, as a bare string (one of "
                         + ", ".join(CONDITION_KINDS) + ", or free text treated as GENERIC).")
    ap.add_argument("--condition-file", dest="condition_path", default=None,
                    help="Path to a JSON document {\"kind\", \"description\"} instead of "
                         "--condition.")
    ap.add_argument("--topology", required=True, dest="topology_path",
                    help="Path to a topology JSON document shaped like "
                         "system_topology_analysis.build_system_topology_analysis()'s output.")
    ap.add_argument("--declared-responses", dest="declared_responses_path", default=None,
                    help="Path to a JSON array of caller-declared "
                         "{\"subsystem_id\", \"response_action\", \"evidence\"} records.")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    text, code = execute_verb(
        origin=a.origin, condition_path=a.condition_path, condition_text=a.condition_text,
        topology_path=a.topology_path, declared_responses_path=a.declared_responses_path,
        as_json=a.as_json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
