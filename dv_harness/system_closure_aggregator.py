"""dv_harness/system_closure_aggregator.py -- System Closure Aggregator (2026-09-06).

A thin ROLLUP over twelve named closure dimensions, each supplied by the caller as a
generic, duck-typed `{dimension_name, status}` record -- NEVER read from any other
new module in this batch. Per this batch's own strict file-safety scope this module
does not import `functional_coverage_signoff.py`, `waiver_store.py`,
`system_error_propagation.py`, or any other claimed module: it accepts their real
output SHAPES as plain, generic parameters instead, exactly the "accept an explicit
caller-declared fact rather than invent one" discipline several sibling modules in
this project already establish (`ip_ownership_conflict.py`'s `legacy_bfm_declarations`,
`existing_command_reuse_score.py`'s `existing_commands`).

The twelve dimensions, fixed and named here rather than left implicit:

    functional_coverage   -- FUNCTIONAL_COVERAGE_SIGNOFF_READY-shaped closure
                              (see `functional_coverage_signoff.py`)
    protocol_coverage     -- protocol-checker / functional-coverage compliance
                              (see `protocol_compliance_aggregation.py`)
    requirement_closure   -- every requirement traced/resolved
                              (see `requirement_contract.py`, `vplan_artifact.py`)
    waiver_status         -- every applicable waiver VALID, none EXPIRED/REVOKED
                              (see `waiver_store.py`)
    regression_status     -- regression evidence clean
                              (see `golden_scenario.py`, `evidence_db.py`)
    evidence_integrity    -- evidence store / signoff-baseline integrity
                              (see `signoff_export.py`, `coverage_db_integrity.py`)
    error_propagation     -- no un-recovered cross-subsystem error propagation
                              (see `system_error_propagation.py`)
    build_composition     -- system build/merge/composition clean
                              (see `system_build_proof.py`)
    performance_closure   -- performance requirements/targets satisfied
                              (see `amba_performance_requirement_checker.py`,
                              `amba_performance_readiness_gates.py`)
    security_closure      -- security/access-policy closure
                              (see `security_policy_ir.py`)
    arbitration_closure   -- arbitration/starvation-risk closure
                              (see `arbitration_policy_ir.py`, `qos_policy_ir.py`)
    change_impact_closure -- no un-reviewed high/medium-risk post-freeze change
                              (see `change_impact.py`, `signoff_export.py`)

STRICT WORST-WINS, NEVER AVERAGED -- the one rule this whole module exists to
enforce, and the same no-averaging discipline `golden_flow_readiness.
combine_readiness()` / `spec_vplan_readiness_gate.py` / `system_readiness_gates.py`
already apply to their own composite folds, restated independently here rather than
imported (none of those is a stable, unclaimed module this batch may import):

  1. A single dimension reporting UNMET/open BLOCKS overall closure
     (`SYSTEM_CLOSURE_STATUS = "NOT_CLOSED"`) regardless of how many of the other
     eleven are clean -- an 11/12 clean picture is still NOT_CLOSED, never rounded
     up and never averaged into a percentage.
  2. Only once no dimension is UNMET does an UNKNOWN/NOT_AVAILABLE dimension (or one
     never supplied at all) make the whole rollup `INCOMPLETE_EVIDENCE` -- a THIRD,
     honestly distinct value from both CLOSED and NOT_CLOSED. This mirrors GF-AT-28
     ("a Critical UNKNOWN must never silently become READY") applied to closure: an
     unmeasured dimension must never silently read as either "closed" or "not
     closed" -- both would be an unearned claim about evidence nobody supplied.
  3. `NOT_APPLICABLE` is the one status that clears WITHOUT counting as missing
     evidence: a caller may explicitly declare a dimension does not apply to this
     project (e.g. `security_closure` for a project with no declared security
     surface at all) -- that is a real, declared fact, not an absence, and must not
     be treated the same as "nobody looked".
  4. Only `CLOSED` requires every one of the twelve dimensions to have been
     genuinely resolved to `MET` or `NOT_APPLICABLE` -- a dimension the caller never
     supplied at all can NEVER silently default to MET; it is reported
     `NOT_SUPPLIED` and folds into `INCOMPLETE_EVIDENCE` exactly like an explicit
     UNKNOWN.

Every dimension is ALWAYS reported individually in the result's `dimensions` list --
never collapsed into a bare pass/fail count. A caller reading only
`overall_status`/`reason` still cannot tell WHICH of the twelve dimensions is the
actual blocker or gap; `dimensions` (and, for a quick scan, `blocking_dimensions` /
`incomplete_dimensions`) is where that individual detail lives, and it is never
optional or summarized away.

`SYSTEM_CLOSURE_STATUS`'s own `CLOSED` value is DELIBERATELY the same token as
`dv_harness.models.Status.CLOSED` -- the same disclosed reuse
`protocol_compliance_aggregation.py`'s own `OVERALL_PASS`/`OVERALL_FAIL` already
apply to `Status.PASS`/`Status.FAIL`: this module's whole subject IS system closure,
so reusing the one real word for it is correct here, not a collision to guard
against. `NOT_CLOSED`/`INCOMPLETE_EVIDENCE` carry no other token from `models.Status`
at all, and `assert_no_extra_verdict_vocabulary_collision()` checks that at import.

This module DECIDES nothing beyond the rollup itself: it runs no build, no gate, no
job, no LSF submission, mints no approval, and there is deliberately no stage gate --
a `SYSTEM_CLOSURE_STATUS` is an input to a human's closure/signoff review, never a
substitute for one. It reads nothing from disk on its own; every fact is a plain
Python value the caller already holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# --- vocabulary --------------------------------------------------------------

#: The twelve real closure dimensions this rollup covers, in the fixed order every
#: report renders them -- an exhaustive, closed set. A caller-supplied record naming
#: anything else is never silently folded into the twelve; see `unrecognized_dimensions`.
CLOSURE_DIMENSIONS: Tuple[str, ...] = (
    "functional_coverage",
    "protocol_coverage",
    "requirement_closure",
    "waiver_status",
    "regression_status",
    "evidence_integrity",
    "error_propagation",
    "build_composition",
    "performance_closure",
    "security_closure",
    "arbitration_closure",
    "change_impact_closure",
)

#: The five recognized per-dimension status tokens a caller's record may declare
#: directly. Any other raw string is normalized against `STATUS_ALIASES` below, and
#: an unrecognized one is reported honestly as `UNKNOWN` -- never guessed toward MET
#: or UNMET.
DIMENSION_MET = "MET"
DIMENSION_UNMET = "UNMET"
DIMENSION_UNKNOWN = "UNKNOWN"
DIMENSION_NOT_AVAILABLE = "NOT_AVAILABLE"
DIMENSION_NOT_APPLICABLE = "NOT_APPLICABLE"
DIMENSION_STATUSES = (
    DIMENSION_MET, DIMENSION_UNMET, DIMENSION_UNKNOWN,
    DIMENSION_NOT_AVAILABLE, DIMENSION_NOT_APPLICABLE,
)

#: A dimension's status is never supplied at all -- distinct from every real status
#: token above, so "nobody reported this dimension" is never confused with "somebody
#: reported it UNKNOWN".
DIMENSION_NOT_SUPPLIED = "NOT_SUPPLIED"

#: Two records supplied for the same fixed dimension name whose normalized statuses
#: genuinely disagree -- this module never arbitrates which one is right (the same
#: ARBITRATION boundary `requirement_contract.py`/`design_knowledge_correlation.py`
#: already keep for their own conflicting-claim findings), so the honest report is
#: a THIRD outcome, never a silent pick between the two.
DIMENSION_AMBIGUOUS_CONFLICTING_SUBMISSIONS = "AMBIGUOUS_CONFLICTING_SUBMISSIONS"

#: Real, heterogeneous status vocabulary from this project's own sibling modules,
#: normalized onto the five recognized tokens above -- the same "accept the real
#: producer's own spelling, normalize once, never re-derive a second vocabulary"
#: discipline `protocol_compliance_aggregation.py`'s `SCOREBOARD_PASS_VERDICTS`/
#: `CHECKER_PASS_VERDICTS` already apply to scoreboard/checker verdicts. A raw string
#: not present in ANY of these sets is reported `UNKNOWN` rather than guessed.
_MET_ALIASES = frozenset({
    "MET", "CLOSED", "CLEAN", "CLEAR", "PASS", "PASSED", "READY", "QUALIFIED",
    "VALID", "COMPLETE", "RESOLVED", "VERIFIED", "CONFIRMED", "SATISFIED",
    "OK", "TRUE", "GRANTED",
})
_UNMET_ALIASES = frozenset({
    "UNMET", "OPEN", "BLOCKED", "FAIL", "FAILED", "NOT_READY", "VIOLATED",
    "VIOLATION", "CONTENTION", "UNRESOLVED", "INVALIDATED", "EXPIRED", "REVOKED",
    "NOT_QUALIFIED", "NOT_CLOSED", "FALSE", "DENIED", "REJECTED",
})
_UNKNOWN_ALIASES = frozenset({
    "UNKNOWN", "INCOMPLETE_EVIDENCE", "PENDING", "INDETERMINATE",
    "TBD", "NOT_YET_RUN", "AMBIGUOUS", "UNPROVABLE", "NOT_MEASURED",
    "INSUFFICIENT_HISTORY", "INSUFFICIENT_EVIDENCE", "UNKNOWN_INSUFFICIENT_EVIDENCE",
})
_NOT_AVAILABLE_ALIASES = frozenset({
    "NOT_AVAILABLE", "UNAVAILABLE", "NO_DATA", "DATA_NOT_AVAILABLE",
})
_NOT_APPLICABLE_ALIASES = frozenset({
    "NOT_APPLICABLE", "N_A", "NA", "N/A", "NONE_APPLICABLE", "NOT_ASSESSED",
})

#: `SYSTEM_CLOSURE_STATUS`'s own three values -- see module docstring for the
#: deliberate `CLOSED` reuse of `models.Status.CLOSED`.
CLOSURE_CLOSED = "CLOSED"
CLOSURE_NOT_CLOSED = "NOT_CLOSED"
CLOSURE_INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
SYSTEM_CLOSURE_STATUSES = (CLOSURE_CLOSED, CLOSURE_NOT_CLOSED, CLOSURE_INCOMPLETE_EVIDENCE)


class SystemClosureAggregatorError(Exception):
    """Base for every refusal in this module -- a real caller-usage error, never a
    silently-repaired input."""


def assert_no_extra_verdict_vocabulary_collision() -> None:
    """`CLOSED` is a deliberate, disclosed reuse of `models.Status.CLOSED` (see the
    module docstring). `NOT_CLOSED`/`INCOMPLETE_EVIDENCE`, and every per-dimension
    status token, must never ALSO collide with a DIFFERENT real `models.Status`
    member -- that would let a stage-gate verdict and a closure-rollup verdict be
    silently confused with each other. Run at import so a future edit that widens
    either vocabulary into a collision fails a test rather than drifting quietly."""
    try:
        from . import models as _models
    except Exception:
        return
    status_values = {member.value for member in _models.Status}
    guarded = set(SYSTEM_CLOSURE_STATUSES) | set(DIMENSION_STATUSES) | {
        DIMENSION_NOT_SUPPLIED, DIMENSION_AMBIGUOUS_CONFLICTING_SUBMISSIONS,
    }
    guarded.discard(CLOSURE_CLOSED)  # the one deliberate, disclosed reuse
    collisions = guarded & status_values
    if collisions:
        raise SystemClosureAggregatorError(
            f"assert_no_extra_verdict_vocabulary_collision: undisclosed collision "
            f"with models.Status: {sorted(collisions)!r}")


assert_no_extra_verdict_vocabulary_collision()


def normalize_dimension_status(raw_status: Any) -> str:
    """A caller's real status string (or any of this project's own sibling
    modules' verdict tokens) -> one of the five recognized `DIMENSION_STATUSES`.
    `None`/empty/unparseable -> `UNKNOWN`, never guessed toward MET or UNMET."""
    if raw_status is None:
        return DIMENSION_UNKNOWN
    text = str(raw_status).strip().upper()
    if not text:
        return DIMENSION_UNKNOWN
    if text in _MET_ALIASES:
        return DIMENSION_MET
    if text in _UNMET_ALIASES:
        return DIMENSION_UNMET
    if text in _NOT_APPLICABLE_ALIASES:
        return DIMENSION_NOT_APPLICABLE
    if text in _NOT_AVAILABLE_ALIASES:
        return DIMENSION_NOT_AVAILABLE
    if text in _UNKNOWN_ALIASES:
        return DIMENSION_UNKNOWN
    # An unrecognized real status string this module has simply never seen --
    # honestly UNKNOWN, never a guess in either direction.
    return DIMENSION_UNKNOWN


@dataclass
class DimensionReport:
    """One closure dimension's own individually-reported record -- never collapsed
    into a bare count. `raw_statuses` preserves every distinct raw status string a
    caller supplied for this dimension (there may be more than one on a genuine
    conflict), so a reader can see exactly what disagreed."""
    dimension_name: str
    normalized_status: str
    raw_statuses: Tuple[str, ...] = ()
    reasons: Tuple[str, ...] = ()
    supplied: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension_name": self.dimension_name,
            "normalized_status": self.normalized_status,
            "raw_statuses": list(self.raw_statuses),
            "reasons": list(self.reasons),
            "supplied": self.supplied,
        }


def _extract_field(record: Any, *names: str) -> Any:
    """Duck-typed field read: a plain dict via `.get()`, or any attribute-bearing
    object via `getattr()`. Never raises on a record missing every named field --
    returns `None`, which callers treat as "not declared"."""
    for name in names:
        if isinstance(record, Mapping):
            if name in record:
                return record[name]
        else:
            if hasattr(record, name):
                return getattr(record, name)
    return None


def _build_dimension_reports(
    dimension_records: Sequence[Any],
) -> Tuple[List[DimensionReport], List[Dict[str, Any]]]:
    """Group every supplied record by its declared `dimension_name` (case-sensitive,
    matched against the fixed `CLOSURE_DIMENSIONS` list), fold duplicates honestly
    (agreeing normalized statuses merge; disagreeing ones become
    `AMBIGUOUS_CONFLICTING_SUBMISSIONS`), and fill in every one of the twelve
    dimensions the caller never mentioned at all as `NOT_SUPPLIED`.

    Returns `(reports_in_fixed_order, unrecognized_records)` -- the second list
    is every record naming a `dimension_name` outside the fixed twelve, reported
    back to the caller rather than silently dropped."""
    by_name: Dict[str, List[Tuple[str, str, Optional[str]]]] = {}
    unrecognized: List[Dict[str, Any]] = []
    for idx, record in enumerate(dimension_records or ()):
        name = _extract_field(record, "dimension_name", "dimension", "name")
        raw_status = _extract_field(record, "status", "state", "verdict")
        reason = _extract_field(record, "reason", "detail", "message")
        if name is None or not str(name).strip():
            unrecognized.append({
                "index": idx, "reason": "MISSING_DIMENSION_NAME",
                "record": record if isinstance(record, Mapping) else str(record),
            })
            continue
        name = str(name).strip()
        if name not in CLOSURE_DIMENSIONS:
            unrecognized.append({
                "index": idx, "dimension_name": name,
                "reason": "DIMENSION_NAME_NOT_IN_FIXED_TWELVE",
            })
            continue
        by_name.setdefault(name, []).append(
            (str(raw_status) if raw_status is not None else "",
             normalize_dimension_status(raw_status),
             str(reason) if reason is not None else None))

    reports: List[DimensionReport] = []
    for name in CLOSURE_DIMENSIONS:
        entries = by_name.get(name)
        if not entries:
            reports.append(DimensionReport(
                dimension_name=name, normalized_status=DIMENSION_NOT_SUPPLIED,
                raw_statuses=(), reasons=("no record supplied for this dimension",),
                supplied=False))
            continue
        distinct_normalized = {e[1] for e in entries}
        raw_statuses = tuple(dict.fromkeys(e[0] for e in entries if e[0]))
        reasons = tuple(r for r in (e[2] for e in entries) if r)
        if len(distinct_normalized) > 1:
            reports.append(DimensionReport(
                dimension_name=name,
                normalized_status=DIMENSION_AMBIGUOUS_CONFLICTING_SUBMISSIONS,
                raw_statuses=raw_statuses,
                reasons=reasons + (
                    f"conflicting submissions for this dimension normalized to "
                    f"{sorted(distinct_normalized)!r} -- never arbitrated here",),
                supplied=True))
            continue
        reports.append(DimensionReport(
            dimension_name=name, normalized_status=entries[0][1],
            raw_statuses=raw_statuses, reasons=reasons, supplied=True))
    return reports, unrecognized


#: Which normalized per-dimension statuses count as "clear" (never blocks, never
#: counts as missing evidence), "blocking" (forces NOT_CLOSED), or "incomplete"
#: (forces INCOMPLETE_EVIDENCE unless a blocking dimension already exists) --
#: spelled out as data so the fold logic itself stays a short, auditable loop.
_CLEAR_STATUSES = frozenset({DIMENSION_MET, DIMENSION_NOT_APPLICABLE})
_BLOCKING_STATUSES = frozenset({DIMENSION_UNMET})
_INCOMPLETE_STATUSES = frozenset({
    DIMENSION_UNKNOWN, DIMENSION_NOT_AVAILABLE, DIMENSION_NOT_SUPPLIED,
    DIMENSION_AMBIGUOUS_CONFLICTING_SUBMISSIONS,
})
assert _CLEAR_STATUSES | _BLOCKING_STATUSES | _INCOMPLETE_STATUSES == (
    set(DIMENSION_STATUSES) | {DIMENSION_NOT_SUPPLIED, DIMENSION_AMBIGUOUS_CONFLICTING_SUBMISSIONS})


def aggregate_system_closure(dimension_records: Sequence[Any]) -> Dict[str, Any]:
    """The rollup this whole module exists for. `dimension_records` is any sequence
    of generic, duck-typed `{dimension_name, status}` records (plain dicts, or any
    object exposing those as attributes) -- the caller's own reduction of whatever
    real per-domain module actually computed each dimension's closure state.

    Returns a dict carrying, ALWAYS: `overall_status` (one of
    `SYSTEM_CLOSURE_STATUSES`), `reason` (naming every dimension that decided it),
    `dimensions` (all twelve, individually, in `CLOSURE_DIMENSIONS` order -- never
    collapsed into a count), `blocking_dimensions`/`incomplete_dimensions` (the
    quick-scan subsets), and `unrecognized_records` (any input record naming a
    dimension outside the fixed twelve, reported rather than silently dropped).

    STRICT WORST-WINS (see module docstring): a single UNMET dimension makes the
    whole rollup `NOT_CLOSED` regardless of how many others are clean; only absent
    that does an UNKNOWN/NOT_AVAILABLE/never-supplied/ambiguous dimension make it
    `INCOMPLETE_EVIDENCE`; only with every dimension `MET` or `NOT_APPLICABLE` does
    it read `CLOSED`.
    """
    reports, unrecognized = _build_dimension_reports(dimension_records)

    blocking = [r for r in reports if r.normalized_status in _BLOCKING_STATUSES]
    incomplete = [r for r in reports if r.normalized_status in _INCOMPLETE_STATUSES]

    if blocking:
        overall_status = CLOSURE_NOT_CLOSED
        reason = (
            f"{len(blocking)} of {len(CLOSURE_DIMENSIONS)} dimension(s) UNMET: "
            f"{[r.dimension_name for r in blocking]!r} -- a single open dimension "
            f"blocks overall closure regardless of how many others are clean")
    elif incomplete:
        overall_status = CLOSURE_INCOMPLETE_EVIDENCE
        reason = (
            f"{len(incomplete)} of {len(CLOSURE_DIMENSIONS)} dimension(s) have no "
            f"resolved MET/NOT_APPLICABLE evidence: "
            f"{[(r.dimension_name, r.normalized_status) for r in incomplete]!r} -- "
            f"never silently read as CLOSED or NOT_CLOSED")
    else:
        overall_status = CLOSURE_CLOSED
        reason = f"all {len(CLOSURE_DIMENSIONS)} dimensions resolved MET or NOT_APPLICABLE"

    return {
        "overall_status": overall_status,
        "reason": reason,
        "dimensions": [r.to_dict() for r in reports],
        "blocking_dimensions": [r.dimension_name for r in blocking],
        "incomplete_dimensions": [r.dimension_name for r in incomplete],
        "unrecognized_records": unrecognized,
        "rule": "strict_worst_wins_unmet_blocks_unknown_is_incomplete_evidence",
    }


def render_system_closure_markdown(report: Mapping[str, Any]) -> str:
    """Render `aggregate_system_closure()`'s result as a markdown table, one row
    per dimension -- reuses `connectivity.render_markdown_table()`, this repo's one
    parameterized table renderer, rather than a second hand-rolled table loop."""
    from .connectivity import render_markdown_table
    columns = [
        ("dimension_name", "Dimension"), ("normalized_status", "Status"),
        ("raw_statuses", "Raw"), ("reasons", "Reason(s)"),
    ]
    header = (
        f"**SYSTEM_CLOSURE_STATUS: {report.get('overall_status')}**\n\n"
        f"{report.get('reason', '')}\n\n")
    return header + render_markdown_table(columns, report.get("dimensions") or [])


# --- CLI front door -----------------------------------------------------------


def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m dv_harness.system_closure_aggregator --dimensions <file.json>
    [--json]`. Exit 0 CLOSED, 1 NOT_CLOSED, 2 INCOMPLETE_EVIDENCE or a usage error.
    No `dv-harness` CLI verb was added -- `cli.py`/`gates.py`/`CLAUDE.md` are out of
    this task's own file-safety scope."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(prog="system-closure-aggregator")
    parser.add_argument("--dimensions", required=True,
                         help="path to a JSON file: a bare list of "
                              "{dimension_name, status} records, or "
                              '{"dimensions": [...]}')
    parser.add_argument("--markdown", action="store_true",
                         help="render as a markdown table instead of JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        with open(args.dimensions, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"NOT_AVAILABLE: could not read --dimensions file: {exc}", file=sys.stderr)
        return 2

    if isinstance(data, Mapping) and "dimensions" in data:
        records = data["dimensions"]
    elif isinstance(data, list):
        records = data
    else:
        print("NOT_AVAILABLE: --dimensions file must be a JSON list or "
              '{"dimensions": [...]}', file=sys.stderr)
        return 2

    report = aggregate_system_closure(records)
    if args.markdown:
        print(render_system_closure_markdown(report))
    else:
        print(json.dumps(report, indent=2))

    status = report["overall_status"]
    if status == CLOSURE_CLOSED:
        return 0
    if status == CLOSURE_NOT_CLOSED:
        return 1
    return 2


def main(argv: Optional[Sequence[str]] = None) -> None:
    import sys
    sys.exit(execute_verb(argv))


if __name__ == "__main__":
    main()
