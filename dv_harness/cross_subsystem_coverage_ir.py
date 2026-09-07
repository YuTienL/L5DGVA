"""dv_harness/cross_subsystem_coverage_ir.py -- CrossSubsystemCoverageIR: a
coverage-hole taxonomy view scoped explicitly across SUBSYSTEM BOUNDARIES.

REUSE OVER REINVENT (verified before writing a line of this module). A
repo-wide grep for `cross_subsystem_coverage` / `CrossSubsystemCoverageIR`
found nothing. `dv_harness/system_failure_taxonomy.py` already ships the real
6-value system coverage-hole taxonomy this task names verbatim
(`SUBSYSTEM_GAP` / `INTEGRATION_GAP` / `RESOURCE_GAP` / `SCENARIO_GAP` /
`ERROR_PATH_GAP` / `COVERAGE_MODEL_GAP`, plus the honest
`UNCLASSIFIED_COVERAGE_HOLE` fallback) via `classify_system_coverage_hole()`.
That function already tells a caller a hole's CATEGORY, including whether its
own declared `scope`/`subsystem_ids` make it cross-subsystem
(`INTEGRATION_GAP`) versus single-subsystem (`SUBSYSTEM_GAP`) -- but it
answers that question per HOLE, in isolation, and it never says WHICH
specific pair(s) of subsystems a cross-subsystem hole actually spans, and it
never rolls several holes up into a per-BOUNDARY view. A repo-wide check
(`grep -rn "classify_system_coverage_hole"`) confirmed no other module in
this project has ever called it at all -- the only prior reuse of
`system_failure_taxonomy.py` is `rca_ontology.py`'s disjointness check
against its DIFFERENT `FAILURE_CATEGORIES` vocabulary, not this one. This
module is that missing, additive layer: it imports and calls
`classify_system_coverage_hole()` for every hole's category verbatim -- it
NEVER re-derives, re-names, or invents a second coverage-hole-category
vocabulary of its own -- and adds only the one real fact that function does
not compute: which concrete subsystem-pair BOUNDARY (or boundaries) a hole's
own declared `subsystem_ids` actually name, and a rollup of holes onto those
boundaries.

WHAT THIS MODULE DOES NOT DO. It performs no coverage-tool parsing (that
stays `coverage_analysis.py`'s and `evidence_db.py`'s job -- neither is
imported here); it never decides which subsystem "owns" a boundary gap or
which fix a human should pursue; it runs no build, gate, or approval, and
there is deliberately no stage gate. A boundary/category rollup here is an
input to a human's coverage-closure review, never a substitute for one.

EVIDENCE TRUTH RULE, applied specifically to boundary resolution. A hole's
category (`classify_system_coverage_hole()`'s own verdict) and its BOUNDARY
resolution are two independent facts, decided from two independent pieces of
evidence, and this module never conflates them: a hole classified
`INTEGRATION_GAP` because its caller wrote `scope: "cross_subsystem"` but
never actually NAMED which subsystems are involved gives this module nothing
to resolve a real pair from, and it is reported
`UNRESOLVED_INSUFFICIENT_SUBSYSTEM_IDS` -- never a guessed or synthetic
placeholder pair such as `("UNKNOWN", "UNKNOWN")`. Symmetrically, a hole
whose category is NOT `INTEGRATION_GAP` (e.g. a `RESOURCE_GAP` or
`ERROR_PATH_GAP`) can still name two or more real `subsystem_ids` -- a
shared-resource or error-path gap genuinely can span a specific pair of
subsystems even though `classify_system_coverage_hole()`'s own category
priority order resolved a different, more specific category for it first
(see that module's own `COVERAGE_HOLE_CLASSIFICATION_ORDER` docstring) -- so
boundary resolution here is decided purely from the hole's own real,
declared `subsystem_ids`/`subsystem_id` count, independent of which category
won. A hole naming fewer than two real subsystem ids, and never claiming a
cross-subsystem scope either, is honestly `NOT_APPLICABLE` (there was never
a boundary question to ask).
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .system_failure_taxonomy import (
    COVERAGE_HOLE_CATEGORIES,
    UNCLASSIFIED_COVERAGE_HOLE,
    classify_system_coverage_hole,
)

# -----------------------------------------------------------------------------
# Boundary-resolution vocabulary. Genuinely new here (system_failure_taxonomy.py
# has no boundary concept at all) -- kept as three honest, disjoint outcomes
# rather than a bool, per the Evidence Truth Rule.
# -----------------------------------------------------------------------------

BOUNDARY_RESOLVED = "RESOLVED"
BOUNDARY_UNRESOLVED = "UNRESOLVED_INSUFFICIENT_SUBSYSTEM_IDS"
BOUNDARY_NOT_APPLICABLE = "NOT_APPLICABLE"

BOUNDARY_STATUSES: Tuple[str, ...] = (
    BOUNDARY_RESOLVED,
    BOUNDARY_UNRESOLVED,
    BOUNDARY_NOT_APPLICABLE,
)


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own boundary-status vocabulary (plus the reused
    `COVERAGE_HOLE_CATEGORIES` / `UNCLASSIFIED_COVERAGE_HOLE`) must share no
    token with `dv_harness.models.Status`, the harness's verification-verdict
    vocabulary -- the same guard several sibling taxonomy/IR modules in this
    project already apply to their own vocabularies. `models.py` is small,
    stable, and unclaimed, so it is imported directly rather than
    transcribed."""
    from .models import Status

    verdicts = {s.value for s in Status}
    vocabulary = (
        set(BOUNDARY_STATUSES)
        | set(COVERAGE_HOLE_CATEGORIES)
        | {UNCLASSIFIED_COVERAGE_HOLE}
    )
    collision = verdicts.intersection(vocabulary)
    if collision:
        raise AssertionError(
            f"cross_subsystem_coverage_ir vocabulary collides with "
            f"dv_harness.models.Status on {sorted(collision)} -- a "
            "classification/boundary-status must never be confusable with a "
            "verification verdict"
        )


def _normalize_subsystem_ids(hole: Dict[str, Any]) -> List[str]:
    """Real, declared subsystem ids only -- never guessed, never derived from
    a category. Accepts either `subsystem_ids` (a list/tuple of ids) or the
    singular `subsystem_id`, mirroring exactly the two shapes
    `classify_system_coverage_hole()` itself already reads. Returns a
    de-duplicated list, order-preserving, of non-empty string ids."""
    raw_ids = hole.get("subsystem_ids")
    ids: List[Any] = list(raw_ids) if isinstance(raw_ids, (list, tuple)) else []
    single = hole.get("subsystem_id")
    if single:
        ids.append(single)

    seen: set = set()
    normalized: List[str] = []
    for raw in ids:
        if raw is None:
            continue
        sid = str(raw).strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        normalized.append(sid)
    return normalized


def _boundary_pairs(subsystem_ids: List[str]) -> List[Tuple[str, str]]:
    """Every unordered pair among `subsystem_ids`, each pair sorted so
    `(A, B)` and `(B, A)` are never counted as two different boundaries.
    Deterministic order (sorted by the pair itself) so a rendered matrix is
    reproducible across runs over the same input."""
    return sorted(
        tuple(sorted(pair)) for pair in itertools.combinations(sorted(subsystem_ids), 2)
    )


@dataclass
class CrossSubsystemCoverageHoleRecord:
    """One coverage hole's classification (reused verbatim from
    `system_failure_taxonomy.classify_system_coverage_hole()`) plus its
    independently-resolved subsystem-boundary scoping.

    `category` / `matched_field` / `category_reason` are exactly that
    function's own `CoverageHoleClassification` fields -- never re-derived
    here. `boundary_status` is one of `BOUNDARY_STATUSES`; `boundaries` is the
    real, sorted list of subsystem-id pairs this hole was resolved to touch
    (empty unless `boundary_status == BOUNDARY_RESOLVED`); `subsystem_ids` is
    the real, normalized id list this hole declared (may be non-empty even
    when `boundary_status` is not `RESOLVED`, e.g. exactly one real id).
    """
    hole_id: str
    category: str
    matched_field: Optional[str]
    category_reason: str
    boundary_status: str
    boundaries: List[Tuple[str, str]]
    subsystem_ids: List[str]
    boundary_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hole_id": self.hole_id,
            "category": self.category,
            "matched_field": self.matched_field,
            "category_reason": self.category_reason,
            "boundary_status": self.boundary_status,
            "boundaries": [list(pair) for pair in self.boundaries],
            "subsystem_ids": list(self.subsystem_ids),
            "boundary_reason": self.boundary_reason,
        }


def classify_cross_subsystem_hole(
    hole: Dict[str, Any], hole_id: Optional[str] = None
) -> CrossSubsystemCoverageHoleRecord:
    """Classify one caller-declared system coverage-hole record, reusing
    `system_failure_taxonomy.classify_system_coverage_hole()` for the
    6-category verdict verbatim, then independently resolve which real
    subsystem-boundary pair(s) (if any) this hole's own declared
    `subsystem_ids`/`subsystem_id` actually name.

    `hole_id` is a caller-supplied identity for this hole (falls back to
    `hole.get("hole_id")`, then a synthetic index-based id) -- purely a label
    for the resulting record, never consulted for classification.
    """
    if hole is None:
        raise ValueError("classify_cross_subsystem_hole: hole must not be None")
    if not isinstance(hole, dict):
        raise ValueError(
            f"classify_cross_subsystem_hole: hole must be a dict, got {type(hole)}"
        )

    base = classify_system_coverage_hole(hole)

    resolved_id = hole_id if hole_id is not None else hole.get("hole_id")
    if resolved_id is None:
        resolved_id = "hole"
    resolved_id = str(resolved_id)

    subsystem_ids = _normalize_subsystem_ids(hole)
    declared_cross_scope = hole.get("scope") == "cross_subsystem"

    if len(subsystem_ids) >= 2:
        boundary_status = BOUNDARY_RESOLVED
        boundaries = _boundary_pairs(subsystem_ids)
        boundary_reason = (
            f"declared subsystem_ids {subsystem_ids} resolve to "
            f"{len(boundaries)} real boundary pair(s)"
        )
    elif declared_cross_scope:
        boundary_status = BOUNDARY_UNRESOLVED
        boundaries = []
        boundary_reason = (
            "declared scope='cross_subsystem' but named fewer than two real "
            f"subsystem ids ({subsystem_ids!r}) -- no specific boundary can "
            "be resolved without guessing"
        )
    else:
        boundary_status = BOUNDARY_NOT_APPLICABLE
        boundaries = []
        boundary_reason = (
            "no cross-subsystem scope was declared and fewer than two real "
            f"subsystem ids were named ({subsystem_ids!r}) -- this hole was "
            "never posed as a boundary question"
        )

    return CrossSubsystemCoverageHoleRecord(
        hole_id=resolved_id,
        category=base.category,
        matched_field=base.matched_field,
        category_reason=base.reason,
        boundary_status=boundary_status,
        boundaries=boundaries,
        subsystem_ids=subsystem_ids,
        boundary_reason=boundary_reason,
    )


@dataclass
class CrossSubsystemCoverageIR:
    """The full IR over a set of coverage-hole records: every hole's
    classification+boundary record, plus a per-boundary rollup (which
    category(ies) of gap touch which specific subsystem-pair boundary) and a
    project-wide category total. Nothing here is computed a second,
    disagreeing way from `holes` -- the rollups are pure reductions of the
    per-hole records already produced by `classify_cross_subsystem_hole()`.
    """
    holes: List[CrossSubsystemCoverageHoleRecord] = field(default_factory=list)

    def boundary_matrix(self) -> Dict[Tuple[str, str], Dict[str, List[str]]]:
        """`{boundary_pair: {category: [hole_id, ...]}}`, over only the holes
        whose boundary actually `RESOLVED`. A boundary pair never appears in
        this matrix on the strength of a guess -- only a real, resolved
        pairing contributes."""
        matrix: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
        for rec in self.holes:
            if rec.boundary_status != BOUNDARY_RESOLVED:
                continue
            for pair in rec.boundaries:
                by_category = matrix.setdefault(pair, {})
                by_category.setdefault(rec.category, []).append(rec.hole_id)
        return matrix

    def category_totals(self) -> Dict[str, int]:
        """Count of holes per category (including
        `UNCLASSIFIED_COVERAGE_HOLE`), across the whole hole set -- not
        boundary-scoped, a plain project-wide tally."""
        totals: Dict[str, int] = {}
        for rec in self.holes:
            totals[rec.category] = totals.get(rec.category, 0) + 1
        return totals

    def unresolved_boundary_hole_ids(self) -> List[str]:
        """Every hole this IR could not resolve a real boundary for despite a
        declared cross-subsystem scope -- an honest gap list, never silently
        dropped from the report."""
        return [
            rec.hole_id
            for rec in self.holes
            if rec.boundary_status == BOUNDARY_UNRESOLVED
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "holes": [rec.to_dict() for rec in self.holes],
            "boundary_matrix": {
                f"{a}<->{b}": by_category
                for (a, b), by_category in self.boundary_matrix().items()
            },
            "category_totals": self.category_totals(),
            "unresolved_boundary_hole_ids": self.unresolved_boundary_hole_ids(),
        }


def build_cross_subsystem_coverage_ir(
    holes: List[Dict[str, Any]],
) -> CrossSubsystemCoverageIR:
    """Classify every hole in `holes` (each via `classify_cross_subsystem_hole`)
    and assemble the resulting `CrossSubsystemCoverageIR`. `holes` may be a
    list of plain dicts, or dicts each carrying their own `hole_id` -- an
    entry with no `hole_id` gets a synthetic, index-based one
    (`hole_<index>`), never a duplicate silently overwriting an earlier
    record."""
    if holes is None:
        raise ValueError("build_cross_subsystem_coverage_ir: holes must not be None")
    if not isinstance(holes, (list, tuple)):
        raise ValueError(
            f"build_cross_subsystem_coverage_ir: holes must be a list, got {type(holes)}"
        )

    records: List[CrossSubsystemCoverageHoleRecord] = []
    for idx, hole in enumerate(holes):
        if not isinstance(hole, dict):
            raise ValueError(
                f"build_cross_subsystem_coverage_ir: holes[{idx}] must be a dict, "
                f"got {type(hole)}"
            )
        hole_id = hole.get("hole_id") or f"hole_{idx}"
        records.append(classify_cross_subsystem_hole(hole, hole_id=hole_id))

    return CrossSubsystemCoverageIR(holes=records)


def render_boundary_matrix_markdown(ir: CrossSubsystemCoverageIR) -> str:
    """Render the per-boundary category rollup as a markdown table, reusing
    `connectivity.render_markdown_table()` -- this repo's one parameterized
    table renderer -- rather than a second hand-rolled table loop."""
    from .connectivity import render_markdown_table

    rows = []
    for (a, b), by_category in sorted(ir.boundary_matrix().items()):
        for category, hole_ids in sorted(by_category.items()):
            rows.append(
                {
                    "boundary": f"{a} <-> {b}",
                    "category": category,
                    "hole_count": len(hole_ids),
                    "hole_ids": ", ".join(hole_ids),
                }
            )
    return render_markdown_table(
        [
            ("boundary", "Boundary"),
            ("category", "Category"),
            ("hole_count", "Hole Count"),
            ("hole_ids", "Hole IDs"),
        ],
        rows,
        empty_note="(no cross-subsystem boundaries resolved)",
    )


# -----------------------------------------------------------------------------
# Ad hoc front door -- no `dv-harness` CLI verb (`cli.py` untouched, per this
# batch's own house-style rule 8 against editing `cli.py`/`gates.py`).
# -----------------------------------------------------------------------------

def execute_verb(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dv_harness.cross_subsystem_coverage_ir")
    parser.add_argument("--holes", required=True, help="path to a JSON list of coverage-hole records")
    parser.add_argument("--json", action="store_true", help="print the IR as JSON")
    args = parser.parse_args(argv)

    try:
        with open(args.holes, "r", encoding="utf-8") as f:
            holes = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"NOT_AVAILABLE: could not read/parse {args.holes!r}: {exc}", file=sys.stderr)
        return 2

    try:
        ir = build_cross_subsystem_coverage_ir(holes)
    except ValueError as exc:
        print(f"NOT_AVAILABLE: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(ir.to_dict(), indent=2))
    else:
        print(render_boundary_matrix_markdown(ir))
        unresolved = ir.unresolved_boundary_hole_ids()
        if unresolved:
            print(f"\nUnresolved-boundary holes (declared cross_subsystem, no real ids): {unresolved}")

    return 1 if ir.unresolved_boundary_hole_ids() else 0


def main() -> None:
    sys.exit(execute_verb())


assert_no_verification_verdict_vocabulary()


if __name__ == "__main__":
    main()
