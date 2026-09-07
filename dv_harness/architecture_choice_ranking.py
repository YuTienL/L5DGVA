"""dv_harness/architecture_choice_ranking.py -- when a verification boundary genuinely has
MORE THAN ONE structurally-valid bind location, RANK them by real architectural-quality
signals instead of silently picking whichever one a caller happened to list first.

THE GAP THIS CLOSES
--------------------
`connectivity.py`'s Gate 1/2/3 are binary PASS/FAIL checks over ONE already-chosen candidate
bind. `phy_boundary.decide_bind_location()` likewise returns exactly one decision for one
PHY<->controller module pair. Neither module has ever had to choose BETWEEN two or more
candidates that are all individually valid (a DUT that exposes the same functional interface
at more than one hierarchy level -- e.g. a raw PHY-facing port AND a re-exported port one
wrapper up, or two structurally equivalent bind targets either side of a passthrough module) --
so nothing in this repo has ever compared two VALID bind locations against each other and said
which one is architecturally BETTER, only whether one candidate is bindable at all.

REUSE OVER REINVENT -- three real producers, none re-derived here
--------------------------------------------------------------------
1. Bindability itself is never re-decided. Each candidate carries a caller-supplied
   `bind_decision` dict -- the REAL, unmodified output of `phy_boundary.decide_bind_location()`
   (or `phy_boundary.extract_phy_boundary(...)["bind_decision"]`) for that candidate's own
   boundary. This module reads its `bindable` field and nothing else decides bindability.
2. Wrapper/bridge hop counting reuses `verification_architecture.derive_wrapper_bridge_chain()`
   verbatim -- the same WRAPPER/BRIDGE/UNCLASSIFIED per-hop classification
   `verification_architecture.py`'s own `VipBindIR.chain_classification` is built from. This
   module counts real `BRIDGE`-classified hops (each already citing the real
   `phy_boundary.classify_boundary()` MIXED verdict that made it one); it invents no second
   wrapper/bridge detector.
3. "Cleaner clock-domain alignment" is read literally off `verification_boundary_ir.py`'s own
   fixed 10-value `BoundaryClass` taxonomy: `CLASS_CLOCK_RESET` is that module's own real,
   documented meaning for "a clock-domain or reset-sequencing boundary (CDC, reset deassertion
   order)". A candidate's own hierarchy chain may carry zero or more CITED
   `VerificationBoundaryIR` declarations (built through
   `verification_boundary_ir.build_verification_boundary_ir()`, unmodified, so an uncited
   classification is refused exactly the way that module already refuses one); this module
   counts how many of those declared boundaries classify `CLASS_CLOCK_RESET` -- i.e. how many
   real, cited clock-domain crossings a candidate's bind chain traverses. Fewer crossings is a
   real, citable "cleaner clock-domain alignment" signal, not a second CDC classifier.

EVIDENCE TRUTH RULE, APPLIED TO THE RANKING ITSELF
----------------------------------------------------
A candidate whose `bind_decision` never reports `bindable: True` is not a "valid bind
location" at all -- it is EXCLUDED, with the real reason, and never ranked. Absent
`boundary_declarations` for a candidate (nobody cited any clock-domain-crossing evidence for
its chain) is recorded as `clock_domain_crossing_status = "NOT_DECLARED"`, kept honestly
distinct from `"ASSESSED"` (real cited evidence was checked and a real count was produced) and
`"PARTIAL"` (some declarations were cited and counted, others were malformed/uncited and are
named in `boundary_declaration_errors` rather than silently dropped or silently counted).
Fewer than two valid candidates is reported as a real, distinct status
(`NO_VALID_BIND_LOCATION` / `SINGLE_VALID_BIND_LOCATION`) rather than a fabricated ranking over
nothing to compare.

RANKING ORDER, MATCHING THIS TASK'S OWN STATED PRIORITY
-----------------------------------------------------------
Ascending, best first: (1) fewer real `BRIDGE`-classified hops (this task's own first-listed
signal -- a bridge is a real protocol/width conversion point a monitor mounted past it would
observe a converted, not the original, signal); (2) fewer real cited clock-domain crossings
(`CLASS_CLOCK_RESET`-classified boundaries along the chain -- "cleaner clock-domain
alignment"); (3) fewer total hops (a tie-break: even an all-WRAPPER chain is a hierarchy the
generated bind path must still express); (4) `candidate_id`, for full determinism when every
real signal ties.

DELIBERATELY BOUNDED
------------------------
This module picks no bind target, emits no `bind` statement, and authors no RTL/VIP content --
it only enumerates and ranks candidates a caller already built. It decides, approves and
arbitrates nothing beyond that ranking; there is deliberately no stage gate. `phy_boundary.py`'s
own bind-location DECISION for any one candidate is untouched -- this module never overrides
`bindable`, it only compares several candidates that are each already `bindable: True`. No
`dv-harness` CLI verb is wired (`cli.py`/`gates.py` are out of scope for this module) -- the
front door is `python -m dv_harness.architecture_choice_ranking --candidates <file.json>
[--json]`.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .connectivity import render_markdown_table
from .verification_architecture import CHAIN_HOP_ROLES, derive_wrapper_bridge_chain
from .verification_boundary_ir import (
    CLASS_CLOCK_RESET,
    VerificationBoundaryIrError,
    build_verification_boundary_ir,
)

SCHEMA_VERSION = "1.0"

#: A candidate carrying no valid `bind_decision.bindable == True` fact is excluded from ranking
#: for exactly one of these reasons -- never silently dropped, never silently ranked as if it
#: were bindable.
EXCLUDE_NO_BIND_DECISION = "NO_BIND_DECISION_SUPPLIED"
EXCLUDE_NOT_BINDABLE = "BIND_DECISION_NOT_BINDABLE"
EXCLUDE_BINDABLE_FIELD_MISSING = "BIND_DECISION_MISSING_BINDABLE_FIELD"
EXCLUDE_REASONS: Tuple[str, ...] = (
    EXCLUDE_NO_BIND_DECISION, EXCLUDE_NOT_BINDABLE, EXCLUDE_BINDABLE_FIELD_MISSING,
)

#: Whether a candidate's clock-domain-crossing count is real, cited evidence, or an honest
#: absence of any cited evidence at all. Never conflated: `NOT_DECLARED` must never be read as
#: "zero crossings confirmed" the way `ASSESSED` with `count == 0` genuinely is.
CROSSING_NOT_DECLARED = "NOT_DECLARED"
CROSSING_ASSESSED = "ASSESSED"
CROSSING_PARTIAL = "PARTIAL"
CROSSING_STATUS_VALUES: Tuple[str, ...] = (CROSSING_NOT_DECLARED, CROSSING_ASSESSED, CROSSING_PARTIAL)

#: Whole-report status. Fewer than two valid candidates is a real, distinct fact -- this
#: module never fabricates a ranking over zero or one candidate.
STATUS_NO_VALID_BIND_LOCATION = "NO_VALID_BIND_LOCATION"
STATUS_SINGLE_VALID_BIND_LOCATION = "SINGLE_VALID_BIND_LOCATION"
STATUS_MULTIPLE_RANKED = "MULTIPLE_VALID_BIND_LOCATIONS_RANKED"
REPORT_STATUS_VALUES: Tuple[str, ...] = (
    STATUS_NO_VALID_BIND_LOCATION, STATUS_SINGLE_VALID_BIND_LOCATION, STATUS_MULTIPLE_RANKED,
)

# A huge sentinel used ONLY as a sort key for an unknown (never-assessed) crossing count, so an
# honestly-unknown candidate sorts after every candidate whose crossing count was actually
# assessed -- it never competes on a signal nobody checked for it, and it never silently reads
# as "0 crossings" for ranking purposes even though its own recorded `clock_domain_crossings`
# field stays the real integer count (partial-evidence candidates) or `None` (no evidence at
# all).
_UNKNOWN_CROSSING_SORT_SENTINEL = 1 << 30


class ArchitectureChoiceRankingError(ValueError):
    """A malformed candidate: no `candidate_id`, a duplicate `candidate_id`, a non-dict
    `bind_decision`/`chain_hops`/`boundary_declarations`, or a non-list `candidates` argument.
    Raised rather than silently skipped or coerced -- these are shape defects in the caller's
    own input, not a real "this candidate isn't bindable" finding."""


# ===========================================================================
# Per-candidate evidence
# ===========================================================================

@dataclass
class RankedBindLocation:
    """One VALID (`bind_decision.bindable is True`) bind-location candidate, carrying the two
    real architectural-quality signals this module ranks on plus the raw evidence each was
    derived from. `rank` is 1-based and assigned only after sorting the whole valid set --
    `None` until then."""

    candidate_id: str
    target_instance: Optional[str]
    bind_decision: dict
    chain: list
    bridge_hop_count: int
    total_hop_count: int
    clock_domain_crossings: Optional[int]
    clock_domain_crossing_status: str
    boundary_declaration_errors: List[str] = field(default_factory=list)
    rank: Optional[int] = None

    def sort_key(self) -> tuple:
        crossings = (
            self.clock_domain_crossings
            if self.clock_domain_crossings is not None
            else _UNKNOWN_CROSSING_SORT_SENTINEL
        )
        return (self.bridge_hop_count, crossings, self.total_hop_count, self.candidate_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "target_instance": self.target_instance,
            "rank": self.rank,
            "bridge_hop_count": self.bridge_hop_count,
            "total_hop_count": self.total_hop_count,
            "clock_domain_crossings": self.clock_domain_crossings,
            "clock_domain_crossing_status": self.clock_domain_crossing_status,
            "boundary_declaration_errors": self.boundary_declaration_errors,
            "bind_decision": self.bind_decision,
            "chain": self.chain,
        }


@dataclass
class ExcludedBindLocation:
    """A candidate this module did NOT rank, and the real, named reason why -- never silently
    absent from the report."""

    candidate_id: str
    target_instance: Optional[str]
    reason: str
    detail: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "target_instance": self.target_instance,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class BindLocationRankingReport:
    status: str
    ranked: List[RankedBindLocation] = field(default_factory=list)
    excluded: List[ExcludedBindLocation] = field(default_factory=list)

    def best(self) -> Optional[RankedBindLocation]:
        return self.ranked[0] if self.ranked else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "ranked": [r.to_dict() for r in self.ranked],
            "excluded": [e.to_dict() for e in self.excluded],
        }


# ===========================================================================
# Per-candidate signal derivation
# ===========================================================================

def _count_bridge_hops(chain_hops: Optional[list]) -> Tuple[list, int, int]:
    """Reuses `verification_architecture.derive_wrapper_bridge_chain()` verbatim. Returns
    `(chain, bridge_hop_count, total_hop_count)`. An empty/absent `chain_hops` is a real DIRECT
    bind (no intermediate hierarchy declared) -- zero bridge hops, matching
    `verification_architecture.py`'s own `chain_classification == "DIRECT"` semantics, never a
    fabricated "unknown" for the common, legitimate case of a bind straight off the DUT top."""
    chain = derive_wrapper_bridge_chain(chain_hops)
    bridge_count = sum(1 for hop in chain if hop.get("role") == "BRIDGE")
    return chain, bridge_count, len(chain)


def _count_clock_domain_crossings(
    boundary_declarations: Optional[List[Dict[str, Any]]],
    candidate_id: str,
) -> Tuple[Optional[int], str, List[str]]:
    """Reuses `verification_boundary_ir.build_verification_boundary_ir()` verbatim, per
    declared boundary along a candidate's own chain. A boundary this module can classify
    `CLASS_CLOCK_RESET` is a real, cited clock-domain-crossing point (per that module's own
    documented meaning for the class). Returns `(count_or_None, status, errors)`:

    - `None` (the key was omitted entirely) -> `(None, NOT_DECLARED, [])` -- honestly "nobody
      cited any evidence for this candidate's clock-domain crossings", never read as "0
      confirmed". An explicit, caller-supplied empty list `[]` is a DIFFERENT, stronger fact --
      "these are the hops I checked and none of them are cited CLOCK_RESET boundaries" -- and is
      classified `ASSESSED` with `count == 0` below, exactly like any other real evidence.
    - every declaration classifies cleanly -> `(count, ASSESSED, [])`.
    - some declarations are malformed/uncited (refused by
      `verification_boundary_ir.VerificationBoundaryIrError`) -> the cleanly-classified ones are
      still counted, the malformed ones are named in `errors`, and the status is `PARTIAL` --
      never silently dropped, never silently promoted to a full `ASSESSED` count.
    """
    if boundary_declarations is None:
        return None, CROSSING_NOT_DECLARED, []

    count = 0
    errors: List[str] = []
    for idx, raw in enumerate(boundary_declarations):
        if not isinstance(raw, dict):
            errors.append(f"boundary_declarations[{idx}]: not a dict ({type(raw).__name__!r})")
            continue
        try:
            ir = build_verification_boundary_ir(
                boundary_id=raw.get("boundary_id") or f"{candidate_id}:hop{idx}",
                boundary_class=raw.get("boundary_class"),
                class_evidence=raw.get("class_evidence"),
                role_inputs=raw.get("roles"),
            )
        except VerificationBoundaryIrError as exc:
            errors.append(f"boundary_declarations[{idx}]: {exc}")
            continue
        if ir.boundary_class == CLASS_CLOCK_RESET:
            count += 1

    status = CROSSING_PARTIAL if errors else CROSSING_ASSESSED
    return count, status, errors


# ===========================================================================
# Top-level assembly
# ===========================================================================

def rank_bind_location_candidates(candidates: List[Dict[str, Any]]) -> BindLocationRankingReport:
    """Enumerate and rank every VALID bind-location candidate.

    `candidates`: a list of dicts, each:
      - `candidate_id` (required, non-empty str, unique across the list)
      - `target_instance` (optional; the real hierarchy path this candidate would bind at)
      - `bind_decision` (required dict -- the real, unmodified output of
        `phy_boundary.decide_bind_location()` for this candidate's own boundary; a candidate
        whose `bind_decision["bindable"]` is not `True` is EXCLUDED, never ranked)
      - `chain_hops` (optional list, the same shape
        `verification_architecture.derive_wrapper_bridge_chain()` accepts -- each hop may carry
        an optional `boundary_classification` for WRAPPER/BRIDGE/UNCLASSIFIED role derivation)
      - `boundary_declarations` (optional list, each a
        `verification_boundary_ir.build_verification_boundary_ir()`-shaped dict -- used only to
        count real, cited `CLASS_CLOCK_RESET` clock-domain-crossing boundaries along this
        candidate's chain)

    Raises `ArchitectureChoiceRankingError` on a malformed candidate (missing/blank
    `candidate_id`, a duplicate `candidate_id`, a non-dict `bind_decision`/`chain_hops`/
    `boundary_declarations`) -- these are shape defects in the caller's own input, never
    silently skipped.
    """
    if not isinstance(candidates, list):
        raise ArchitectureChoiceRankingError(
            f"candidates must be a list of dicts, got {type(candidates).__name__!r}"
        )

    seen_ids: set = set()
    ranked: List[RankedBindLocation] = []
    excluded: List[ExcludedBindLocation] = []

    for idx, raw in enumerate(candidates):
        if not isinstance(raw, dict):
            raise ArchitectureChoiceRankingError(f"candidates[{idx}] must be a dict, got {type(raw).__name__!r}")

        candidate_id = raw.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ArchitectureChoiceRankingError(f"candidates[{idx}]: candidate_id must be a non-empty str")
        if candidate_id in seen_ids:
            raise ArchitectureChoiceRankingError(f"candidates[{idx}]: duplicate candidate_id {candidate_id!r}")
        seen_ids.add(candidate_id)

        target_instance = raw.get("target_instance")
        bind_decision = raw.get("bind_decision")
        chain_hops = raw.get("chain_hops")
        boundary_declarations = raw.get("boundary_declarations")

        if bind_decision is not None and not isinstance(bind_decision, dict):
            raise ArchitectureChoiceRankingError(
                f"candidates[{idx}] ({candidate_id!r}): bind_decision must be a dict or None, "
                f"got {type(bind_decision).__name__!r}"
            )
        if chain_hops is not None and not isinstance(chain_hops, list):
            raise ArchitectureChoiceRankingError(
                f"candidates[{idx}] ({candidate_id!r}): chain_hops must be a list or None, "
                f"got {type(chain_hops).__name__!r}"
            )
        if boundary_declarations is not None and not isinstance(boundary_declarations, list):
            raise ArchitectureChoiceRankingError(
                f"candidates[{idx}] ({candidate_id!r}): boundary_declarations must be a list or "
                f"None, got {type(boundary_declarations).__name__!r}"
            )

        if bind_decision is None:
            excluded.append(ExcludedBindLocation(
                candidate_id=candidate_id, target_instance=target_instance,
                reason=EXCLUDE_NO_BIND_DECISION,
                detail="no phy_boundary.decide_bind_location() result was supplied for this "
                       "candidate -- bindability was never evaluated, so it cannot be ranked",
            ))
            continue

        bindable = bind_decision.get("bindable")
        if bindable is None and "bindable" not in bind_decision:
            excluded.append(ExcludedBindLocation(
                candidate_id=candidate_id, target_instance=target_instance,
                reason=EXCLUDE_BINDABLE_FIELD_MISSING,
                detail="bind_decision carries no 'bindable' field at all",
            ))
            continue
        if bindable is not True:
            excluded.append(ExcludedBindLocation(
                candidate_id=candidate_id, target_instance=target_instance,
                reason=EXCLUDE_NOT_BINDABLE,
                detail=bind_decision.get("rationale") or f"bind_decision.bindable == {bindable!r}",
            ))
            continue

        chain, bridge_count, total_hops = _count_bridge_hops(chain_hops)
        crossings, crossing_status, crossing_errors = _count_clock_domain_crossings(
            boundary_declarations, candidate_id
        )

        ranked.append(RankedBindLocation(
            candidate_id=candidate_id,
            target_instance=target_instance,
            bind_decision=bind_decision,
            chain=chain,
            bridge_hop_count=bridge_count,
            total_hop_count=total_hops,
            clock_domain_crossings=crossings,
            clock_domain_crossing_status=crossing_status,
            boundary_declaration_errors=crossing_errors,
        ))

    ranked.sort(key=lambda r: r.sort_key())
    for position, r in enumerate(ranked, start=1):
        r.rank = position

    if not ranked:
        status = STATUS_NO_VALID_BIND_LOCATION
    elif len(ranked) == 1:
        status = STATUS_SINGLE_VALID_BIND_LOCATION
    else:
        status = STATUS_MULTIPLE_RANKED

    return BindLocationRankingReport(status=status, ranked=ranked, excluded=excluded)


# ===========================================================================
# Rendering
# ===========================================================================

def render_ranking_markdown(report: BindLocationRankingReport) -> str:
    columns = [
        ("rank", "Rank"), ("candidate_id", "Candidate"), ("target_instance", "Target Instance"),
        ("bridge_hop_count", "Bridge Hops"), ("clock_domain_crossings", "CDC Crossings"),
        ("clock_domain_crossing_status", "CDC Evidence"), ("total_hop_count", "Total Hops"),
    ]
    rows = [r.to_dict() for r in report.ranked]
    table = render_markdown_table(columns, rows, empty_note="(no valid bind location candidates)")
    lines = [f"Status: {report.status}", "", table]
    if report.excluded:
        lines.append("")
        lines.append("Excluded candidates:")
        for e in report.excluded:
            lines.append(f"  - {e.candidate_id} ({e.target_instance}): {e.reason} -- {e.detail}")
    return "\n".join(lines)


# ===========================================================================
# CLI front door -- no dv-harness verb (cli.py/gates.py are out of scope)
# ===========================================================================

def execute_verb(argv: Optional[list] = None) -> Tuple[int, Dict[str, Any], str]:
    parser = argparse.ArgumentParser(prog="architecture_choice_ranking")
    parser.add_argument("--candidates", required=True, help="path to a JSON file: a list of candidate dicts")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    with open(args.candidates, "r", encoding="utf-8") as f:
        candidates_doc = json.load(f)

    try:
        report = rank_bind_location_candidates(candidates_doc)
    except ArchitectureChoiceRankingError as exc:
        result = {"error": str(exc)}
        return 2, result, json.dumps(result, indent=2)

    result = report.to_dict()
    text = json.dumps(result, indent=2) if args.json else render_ranking_markdown(report)
    exit_code = 0 if report.status == STATUS_MULTIPLE_RANKED else 1
    return exit_code, result, text


def main(argv: Optional[list] = None) -> int:
    exit_code, _result, text = execute_verb(argv)
    print(text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
