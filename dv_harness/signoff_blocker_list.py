"""dv_harness/signoff_blocker_list.py -- the Signoff Blocker List (2026-09-07).

THE GAP THIS CLOSES. Three (going on four) real modules each already answer
one narrow "is signoff blocked" question -- `waiver_store.status_report()`
(is every recorded waiver still VALID), `functional_coverage_signoff.
analyze_functional_coverage_signoff()` (is functional coverage Closure at
100% with no blocking waiver), and `system_closure_aggregator.
aggregate_system_closure()` (the twelve-dimension, worst-wins system-closure
rollup those two are themselves two NAMED dimensions of). Nobody folds the
three into the one thing a human actually wants before signing off: a single,
honest list naming EVERY currently-open reason signoff cannot proceed, so
"what is blocking signoff right now" has one real answer instead of three
separately-read reports that could describe the same project differently. A
repo-wide grep for `signoff_blocker`, `SIGNOFF_BLOCKER`, `blocker_list` before
writing anything matched nothing executable.

THE "9-ITEM" DERIVATION, STATED PRECISELY RATHER THAN ASSERTED. This task's
own brief names a document (`CLAUDE_L5_WEB_CONTROL_PLANE_MASTER.md`, sections
342-402) that is not present anywhere in this checkout -- a repo-wide
`Glob`/`grep` for that filename and for any "9-item"/"nine-item" blocker
enumeration found nothing on disk to read verbatim, and per the Evidence
Truth Rule this module never fabricates a specific named list it cannot cite.
What IS real and on disk is `system_closure_aggregator.CLOSURE_DIMENSIONS`:
a fixed, already-vetted 12-name closure taxonomy. Of those twelve, exactly
THREE already have their own individually-named, more specific real source
in this same task brief: `functional_coverage` (-> `functional_coverage_
signoff.py`'s own Closure verdict), `waiver_status` (-> `waiver_store.py`'s
own `status_report()`), and `evidence_integrity` (-> `evidence_integrity_
states`, this batch's sibling item). Removing exactly those three named
dimensions from the real, already-fixed twelve leaves exactly NINE remaining
names, verbatim from `CLOSURE_DIMENSIONS`, never re-typed or renamed:
`protocol_coverage`, `requirement_closure`, `regression_status`,
`error_propagation`, `build_composition`, `performance_closure`,
`security_closure`, `arbitration_closure`, `change_impact_closure`. This is
this module's own `BLOCKER_CATEGORIES` -- the real "9-item" residual the
brief's "9-item blocker derivation" title names -- and `_assert_nine_item_
derivation()`, run at import, holds the arithmetic (`len() == 9`, every name
a genuine member of `CLOSURE_DIMENSIONS`, no overlap with the three natively
resolved ones) as a real check rather than a comment that can silently drift.
This module discloses this derivation rather than hiding it behind an
unverifiable citation, exactly the "found nothing executable, so the
mechanism is built from the real named sources instead" precedent this
project's own `golden_subsystem_benchmark.py` and `intake_events.py` already
set for an unwritten or unfindable master enumeration.

WHAT THIS MODULE ACTUALLY DOES -- read-only aggregation, nothing invented.
`derive_signoff_blockers(root)` reads the THREE real, individually-named
sources itself (never re-measuring any of their underlying facts):

  - `waiver_store.status_report(root)` -> the `waiver_status` dimension:
    UNMET the instant any recorded waiver is not VALID (naming every
    offending waiver_id and its real derived status), MET when the store
    exists and every waiver is VALID (including zero waivers recorded),
    NOT_AVAILABLE when no ledger exists at all.
  - `functional_coverage_signoff.analyze_functional_coverage_signoff(root)`
    -> the `functional_coverage` dimension: MET only on a real
    SIGNOFF_READY verdict, UNMET on OPEN/BLOCKED_BY_WAIVER (naming the
    real closure_percent and/or blocking waivers), UNKNOWN on
    INCOMPLETE_EVIDENCE, NOT_AVAILABLE when that module's own inputs are
    themselves unavailable.
  - `evidence_integrity_states.classify_project_evidence_integrity(root)`
    (this batch's SIBLING item) -> the `evidence_integrity` dimension. That
    module's own real project-wide rollup reports a six-value vocabulary
    (VALID/STALE/SUPERSEDED/CONTRADICTED/CORRUPT/UNKNOWN) or a real
    NOT_AVAILABLE when the project has recorded no golden-scenario capsule
    and no signoff freeze at all -- none of which is `system_closure_
    aggregator`'s own generic alias table taught to read, so THIS module
    carries its own small, disclosed mapping
    (`_EVIDENCE_INTEGRITY_PROJECT_STATUS_TO_DIMENSION`): VALID and the
    sibling module's own-documented "merely-informational" SUPERSEDED both
    clear (MET); STALE/CONTRADICTED/CORRUPT are each a real, named
    integrity defect and block (UNMET); UNKNOWN stays UNKNOWN. This module
    never assumes the sibling module exists or stays import-clean: a caller
    already holding its real output may pass it directly via
    `evidence_integrity_report`; absent that, the one real call is tried
    and any failure -- an import error, an exception from the call, an
    unrecognized status -- reports NOT_AVAILABLE (or, for a genuinely
    unrecognized status string, honestly UNKNOWN) rather than a guess. THIS
    IS THE MODULE'S OWN REQUIRED NEGATIVE CONTROL: the sibling module (or
    its call) being unavailable never silently reads as "clear", never as
    "blocked" -- it is reported exactly as unmeasured, the same "absence of
    evidence must never become a guessed value" discipline the whole batch
    is built under.

The remaining nine `BLOCKER_CATEGORIES` dimensions have NO real source named
anywhere in this task -- this module does not invent one. A caller who has
real evidence for any of them (e.g. a real `protocol_compliance_aggregation.
py` verdict reduced to `{dimension_name, status}`) supplies it via
`residual_dimension_records`, in the exact generic caller-supplied shape
`system_closure_aggregator.aggregate_system_closure()` already accepts;
supplying nothing for one of the nine is honestly `NOT_SUPPLIED`, never a
guessed MET.

All twelve records (the three natively resolved plus whatever residual ones
a caller supplies) are folded through `system_closure_aggregator.
aggregate_system_closure()` ITSELF -- imported, not re-implemented, so the
worst-wins rule (a single UNMET dimension blocks the whole rollup regardless
of how many others are clean; an UNKNOWN/NOT_AVAILABLE/NOT_SUPPLIED
dimension is honestly `INCOMPLETE_EVIDENCE`, never silently CLOSED or
NOT_CLOSED) is the SAME rule, not a second implementation of it that could
drift out of agreement.

`signoff_blockers` is the real, human-facing headline: every dimension the
fold actually found UNMET right now, individually, with its real reason(s)
and (for the three natively-resolved dimensions) the underlying detail
(which waiver, which coverage bin) a human needs to act on it -- never
collapsed into a bare count, and never padded out to nine/twelve entries
when fewer are actually open. `incomplete_evidence_dimensions` is kept
honestly separate: a dimension nobody has evidence for yet is NOT a blocker
(that would be an unearned "something is wrong" claim about evidence nobody
supplied) -- it is reported as its own, differently-named thing, mirroring
`system_closure_aggregator.py`'s own `blocking_dimensions`/
`incomplete_dimensions` split.

THIS MODULE DECIDES, APPROVES AND ARBITRATES NOTHING. It runs no build, no
gate script, no regression, no LSF job; it revokes no waiver, records no
approval, and asks no question. It writes nothing to disk. There is
deliberately no `STAGE_GATES` entry and no `dv-harness` CLI verb --
`gates.py`/`cli.py`/`dashboard.py` are large, actively-edited files outside
this task's own file-safety scope, the same disclosed choice several recent
modules in this project already make. A `signoff_blockers` list is an input
to a human's signoff review, never a substitute for one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import system_closure_aggregator as sca
from . import waiver_store as ws
from . import functional_coverage_signoff as fcs

SCHEMA_VERSION = "1.0"

#: The three `CLOSURE_DIMENSIONS` this module resolves itself, each from its
#: own real, individually-named source (see module docstring). Verbatim
#: member names of `system_closure_aggregator.CLOSURE_DIMENSIONS` -- never a
#: second spelling of the same three concepts.
NATIVELY_RESOLVED_DIMENSIONS: Tuple[str, ...] = (
    "functional_coverage", "waiver_status", "evidence_integrity",
)

#: This module's own real "9-item signoff-blocker list": every one of
#: `system_closure_aggregator.CLOSURE_DIMENSIONS` EXCEPT the three natively
#: resolved above -- see the module docstring for exactly why this, and only
#: this, is the honest reading of the brief's "9-item" derivation. Fixed
#: order preserved from `CLOSURE_DIMENSIONS` itself.
BLOCKER_CATEGORIES: Tuple[str, ...] = tuple(
    name for name in sca.CLOSURE_DIMENSIONS if name not in NATIVELY_RESOLVED_DIMENSIONS
)


class SignoffBlockerListError(Exception):
    """Base for every refusal in this module -- a real caller-usage error,
    never a silently-repaired input."""


def _assert_nine_item_derivation() -> None:
    """Runs at import so a future edit to either this module's own three
    natively-resolved names or `system_closure_aggregator.CLOSURE_DIMENSIONS`
    that breaks the 12 = 3 + 9 arithmetic fails a test rather than drifting
    quietly into a wrongly-sized "9-item" list."""
    if set(NATIVELY_RESOLVED_DIMENSIONS) - set(sca.CLOSURE_DIMENSIONS):
        raise SignoffBlockerListError(
            "NATIVELY_RESOLVED_DIMENSIONS names a dimension outside "
            "system_closure_aggregator.CLOSURE_DIMENSIONS: "
            f"{sorted(set(NATIVELY_RESOLVED_DIMENSIONS) - set(sca.CLOSURE_DIMENSIONS))!r}")
    if len(set(BLOCKER_CATEGORIES)) != len(BLOCKER_CATEGORIES):
        raise SignoffBlockerListError("BLOCKER_CATEGORIES contains a duplicate name")
    if len(BLOCKER_CATEGORIES) != 9:
        raise SignoffBlockerListError(
            f"BLOCKER_CATEGORIES derivation broke: expected exactly 9 residual "
            f"dimensions (12 CLOSURE_DIMENSIONS - {len(NATIVELY_RESOLVED_DIMENSIONS)} "
            f"natively resolved), got {len(BLOCKER_CATEGORIES)}: {BLOCKER_CATEGORIES!r}")
    if set(BLOCKER_CATEGORIES) | set(NATIVELY_RESOLVED_DIMENSIONS) != set(sca.CLOSURE_DIMENSIONS):
        raise SignoffBlockerListError(
            "BLOCKER_CATEGORIES + NATIVELY_RESOLVED_DIMENSIONS does not exactly "
            "partition system_closure_aggregator.CLOSURE_DIMENSIONS")


_assert_nine_item_derivation()


def _extract(record: Any, *names: str) -> Any:
    """The same tiny duck-typed field read `system_closure_aggregator.
    _extract_field()` uses -- re-declared locally (a few lines) rather than
    reaching into that module's own leading-underscore internal, so a caller
    passing a plain dict OR any attribute-bearing object works identically."""
    for name in names:
        if isinstance(record, Mapping):
            if name in record:
                return record[name]
        elif hasattr(record, name):
            return getattr(record, name)
    return None


# ===========================================================================
# Source 1: waiver_store.status_report()
# ===========================================================================

def _waiver_status_record(root: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """-> (dimension_record, detail). `detail` is the richer, human-facing
    payload (which waiver, which status) `system_closure_aggregator`'s own
    generic `{dimension_name, status, reason}` shape has no room for."""
    report = ws.status_report(root)
    if report.get("status") == "NOT_AVAILABLE":
        detail = {"waivers": [], "source_status": "NOT_AVAILABLE"}
        return ({"dimension_name": "waiver_status", "status": "NOT_AVAILABLE",
                 "reason": report.get("reason") or "NO_WAIVER_STORE"}, detail)
    waivers = report.get("waivers") or []
    blocking = [w for w in waivers if w.get("status") != "VALID"]
    detail = {"waivers": waivers, "blocking_waivers": blocking,
               "evaluated_at": report.get("evaluated_at")}
    if blocking:
        names = ", ".join(f"{w.get('waiver_id')}={w.get('status')}" for w in blocking)
        reason = f"{len(blocking)} of {len(waivers)} recorded waiver(s) not VALID: {names}"
        return ({"dimension_name": "waiver_status", "status": "UNMET", "reason": reason}, detail)
    reason = (f"all {len(waivers)} recorded waiver(s) VALID" if waivers
              else "waiver store exists with zero recorded waivers")
    return ({"dimension_name": "waiver_status", "status": "MET", "reason": reason}, detail)


# ===========================================================================
# Source 2: functional_coverage_signoff.analyze_functional_coverage_signoff()
# ===========================================================================

def _functional_coverage_record(root: Path, cfg: Optional[Dict[str, Any]] = None
                                 ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    report = fcs.analyze_functional_coverage_signoff(root, cfg=cfg)
    status = report.get("status")
    detail = {
        "closure_percent": report.get("closure_percent"),
        "blocking_waivers": report.get("blocking_waivers"),
        "unrecorded_declared": report.get("unrecorded_declared"),
        "malformed_categories": report.get("malformed_categories"),
        "functional_coverage_signoff_status": status,
    }
    if status == fcs.STATUS_SIGNOFF_READY:
        dim_status = "MET"
        reason = f"closure_percent={report.get('closure_percent')}, no blocking waiver"
    elif status == fcs.STATUS_NOT_AVAILABLE:
        dim_status = "NOT_AVAILABLE"
        reason = report.get("reason") or "FUNCTIONAL_COVERAGE_SIGNOFF_INPUTS_UNAVAILABLE"
    elif status == fcs.STATUS_INCOMPLETE_EVIDENCE:
        dim_status = "UNKNOWN"
        reason = (f"{len(report.get('unrecorded_declared') or [])} declared coverage bin(s) "
                  "have no recorded evidence")
    elif status == fcs.STATUS_BLOCKED_BY_WAIVER:
        dim_status = "UNMET"
        bw = report.get("blocking_waivers") or []
        reason = f"{len(bw)} coverage bin(s) blocked by a non-VALID waiver: {bw!r}"
    else:  # STATUS_OPEN
        dim_status = "UNMET"
        reason = f"closure_percent={report.get('closure_percent')} (below 100%)"
    return ({"dimension_name": "functional_coverage", "status": dim_status, "reason": reason}, detail)


# ===========================================================================
# Source 3: evidence_integrity_states.classify_project_evidence_integrity()
# (this batch's sibling item)
# ===========================================================================

#: `evidence_integrity_states.py`'s own real project-rollup `status` values,
#: mapped onto this dimension's MET/UNMET/UNKNOWN/NOT_AVAILABLE -- a mapping
#: this module states and owns, not `system_closure_aggregator`'s generic
#: alias table (which has no idea what VALID/STALE/SUPERSEDED/CONTRADICTED/
#: CORRUPT mean). See the module docstring for why VALID and the sibling
#: module's own-documented "merely-informational" SUPERSEDED both clear
#: while STALE/CONTRADICTED/CORRUPT each block.
_EVIDENCE_INTEGRITY_PROJECT_STATUS_TO_DIMENSION: Dict[str, str] = {
    "VALID": "MET",
    "SUPERSEDED": "MET",
    "STALE": "UNMET",
    "CONTRADICTED": "UNMET",
    "CORRUPT": "UNMET",
    "UNKNOWN": "UNKNOWN",
    "NOT_AVAILABLE": "NOT_AVAILABLE",
}


def _call_evidence_integrity_states(root: Path) -> Any:
    """Isolated into its own function so a test can monkeypatch this ONE
    call to prove the "sibling module unavailable" negative control without
    needing to actually delete `evidence_integrity_states.py` from disk."""
    from . import evidence_integrity_states as eis  # type: ignore
    return eis.classify_project_evidence_integrity(root)


def _evidence_integrity_record(
    root: Path, evidence_integrity_report: Optional[Any] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """See the module docstring's "THIS IS THE MODULE'S OWN REQUIRED NEGATIVE
    CONTROL" paragraph. A caller-supplied report always wins (it is real
    evidence someone already computed); absent that, the one real
    `_call_evidence_integrity_states()` call is tried, and ANY failure to
    obtain a usable result (an import error, an exception raised by the real
    call) reports NOT_AVAILABLE, never a guessed MET/UNMET."""
    if evidence_integrity_report is None:
        try:
            evidence_integrity_report = _call_evidence_integrity_states(root)
        except ImportError:
            detail = {"reason": "EVIDENCE_INTEGRITY_STATES_MODULE_NOT_AVAILABLE"}
            return ({"dimension_name": "evidence_integrity", "status": "NOT_AVAILABLE",
                     "reason": "evidence_integrity_states.py is not importable in this "
                               "checkout (this batch's sibling item) -- never guessed as "
                               "clear or blocked"}, detail)
        except Exception as e:
            detail = {"reason": f"EVIDENCE_INTEGRITY_STATES_CALL_FAILED:{e}"}
            return ({"dimension_name": "evidence_integrity", "status": "NOT_AVAILABLE",
                     "reason": "evidence_integrity_states.classify_project_evidence_integrity() "
                               f"raised: {e}"}, detail)

    raw_status = _extract(evidence_integrity_report, "status", "overall_status")
    dim_status = _EVIDENCE_INTEGRITY_PROJECT_STATUS_TO_DIMENSION.get(
        str(raw_status), sca.normalize_dimension_status(raw_status))
    raw_reason = _extract(evidence_integrity_report, "reason")
    detail = (dict(evidence_integrity_report) if isinstance(evidence_integrity_report, Mapping)
              else {"repr": repr(evidence_integrity_report)})
    if raw_reason:
        reason = raw_reason
    else:
        reason = (f"evidence_integrity_states project rollup: {raw_status} "
                  f"(capsules={_extract(evidence_integrity_report, 'capsule_count')}, "
                  f"freezes={_extract(evidence_integrity_report, 'freeze_count')}, "
                  f"counts={_extract(evidence_integrity_report, 'counts')!r})")
    return ({"dimension_name": "evidence_integrity", "status": dim_status, "reason": reason}, detail)


# ===========================================================================
# The rollup
# ===========================================================================

def derive_signoff_blockers(
    root: Any,
    *,
    residual_dimension_records: Optional[Sequence[Any]] = None,
    evidence_integrity_report: Optional[Any] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The rollup this module exists for: every currently-open signoff
    blocker, real evidence only, worst-wins.

    `residual_dimension_records` is any sequence of generic, duck-typed
    `{dimension_name, status}` records for the NINE `BLOCKER_CATEGORIES` this
    module has no real source for on its own (see module docstring) -- the
    exact shape `system_closure_aggregator.aggregate_system_closure()`
    already accepts. A record naming one of the THREE natively-resolved
    dimensions is not dropped: it is forwarded through unchanged, so a real
    disagreement between a caller's own record and this module's own
    derivation surfaces honestly as `AMBIGUOUS_CONFLICTING_SUBMISSIONS`
    (system_closure_aggregator's own arbitration boundary) rather than this
    module silently picking one.

    `evidence_integrity_report` is passed straight to `_evidence_integrity_
    record()` -- see its docstring for the sibling-module fallback.
    """
    root = Path(root)
    waiver_dim, waiver_detail = _waiver_status_record(root)
    fcov_dim, fcov_detail = _functional_coverage_record(root, cfg=cfg)
    ei_dim, ei_detail = _evidence_integrity_record(root, evidence_integrity_report)

    native_detail = {
        "waiver_status": waiver_detail,
        "functional_coverage": fcov_detail,
        "evidence_integrity": ei_detail,
    }

    all_records: List[Any] = [waiver_dim, fcov_dim, ei_dim]
    all_records.extend(residual_dimension_records or ())

    closure = sca.aggregate_system_closure(all_records)
    dims_by_name = {d["dimension_name"]: d for d in closure["dimensions"]}

    def _render(name: str) -> Dict[str, Any]:
        d = dims_by_name[name]
        entry = {
            "dimension_name": name,
            "in_core_nine": name in BLOCKER_CATEGORIES,
            "status": d["normalized_status"],
            "raw_statuses": d["raw_statuses"],
            "reasons": d["reasons"],
        }
        if name in native_detail:
            entry["detail"] = native_detail[name]
        return entry

    signoff_blockers = [_render(name) for name in closure["blocking_dimensions"]]
    incomplete_evidence_dimensions = [_render(name) for name in closure["incomplete_dimensions"]]

    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        # CLOSED / NOT_CLOSED / INCOMPLETE_EVIDENCE -- system_closure_
        # aggregator's own three-value vocabulary, reused verbatim rather
        # than a second one that could disagree with it about the same fold.
        "signoff_status": closure["overall_status"],
        "reason": closure["reason"],
        # The fixed 9-item taxonomy this module derives from real, on-disk
        # vocabulary (see module docstring) -- always reported, even when
        # every one of the nine is currently clear.
        "blocker_categories": list(BLOCKER_CATEGORIES),
        "natively_resolved_dimensions": list(NATIVELY_RESOLVED_DIMENSIONS),
        # The real, human-facing headline: never padded to nine/twelve
        # entries, never omitted for being empty.
        "signoff_blockers": signoff_blockers,
        "incomplete_evidence_dimensions": incomplete_evidence_dimensions,
        "dimensions": closure["dimensions"],
        "unrecognized_records": closure["unrecognized_records"],
    }


def render_signoff_blocker_markdown(report: Mapping[str, Any]) -> str:
    """Reuses `connectivity.render_markdown_table()` -- this repo's one
    parameterized table renderer -- rather than a second hand-rolled loop."""
    from .connectivity import render_markdown_table
    columns = [
        ("dimension_name", "Dimension"), ("in_core_nine", "Core-9"),
        ("status", "Status"), ("reasons", "Reason(s)"),
    ]
    header = (
        f"**SIGNOFF_STATUS: {report.get('signoff_status')}**\n\n"
        f"{report.get('reason', '')}\n\n"
        "## Signoff Blockers\n\n")
    body = header + render_markdown_table(columns, report.get("signoff_blockers") or [],
                                           empty_note="(no open signoff blockers)")
    incomplete = report.get("incomplete_evidence_dimensions") or []
    if incomplete:
        body += "\n\n## Incomplete Evidence (not a blocker -- unmeasured)\n\n"
        body += render_markdown_table(columns, incomplete)
    return body


# --- CLI front door -----------------------------------------------------------


def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m dv_harness.signoff_blocker_list --project-root <dir>
    [--residual-dimensions <file.json>] [--evidence-integrity <file.json>]
    [--markdown]`. Exit 0 CLOSED (no blockers), 1 NOT_CLOSED (at least one
    real blocker), 2 INCOMPLETE_EVIDENCE or a usage/read error. No
    `dv-harness` CLI verb -- `cli.py`/`gates.py`/`dashboard.py` are out of
    this task's own file-safety scope."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(prog="signoff-blocker-list")
    parser.add_argument("--project-root", default=".", help="real project root")
    parser.add_argument("--residual-dimensions",
                         help="path to a JSON file: a bare list of "
                              '{dimension_name, status} records for the nine '
                              'BLOCKER_CATEGORIES this module has no real '
                              'source of its own for, or {"dimensions": [...]}')
    parser.add_argument("--evidence-integrity",
                         help="path to a JSON file carrying a real "
                              "evidence_integrity_states report ({status, reason, ...})")
    parser.add_argument("--markdown", action="store_true",
                         help="render as a markdown report instead of JSON")
    parser.add_argument("--json", action="store_true",
                         help="(default) render as JSON -- accepted for symmetry with "
                              "--markdown; JSON is already the default output")
    args = parser.parse_args(list(argv) if argv is not None else None)

    residual_records: Optional[List[Any]] = None
    if args.residual_dimensions:
        try:
            with open(args.residual_dimensions, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"NOT_AVAILABLE: could not read --residual-dimensions file: {exc}",
                  file=sys.stderr)
            return 2
        if isinstance(data, Mapping) and "dimensions" in data:
            residual_records = list(data["dimensions"])
        elif isinstance(data, list):
            residual_records = data
        else:
            print('NOT_AVAILABLE: --residual-dimensions file must be a JSON list '
                  'or {"dimensions": [...]}', file=sys.stderr)
            return 2

    evidence_integrity_report = None
    if args.evidence_integrity:
        try:
            with open(args.evidence_integrity, "r", encoding="utf-8") as fh:
                evidence_integrity_report = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"NOT_AVAILABLE: could not read --evidence-integrity file: {exc}",
                  file=sys.stderr)
            return 2

    report = derive_signoff_blockers(
        args.project_root,
        residual_dimension_records=residual_records,
        evidence_integrity_report=evidence_integrity_report,
    )
    if args.markdown:
        print(render_signoff_blocker_markdown(report))
    else:
        print(json.dumps(report, indent=2))

    status = report["signoff_status"]
    if status == sca.CLOSURE_CLOSED:
        return 0
    if status == sca.CLOSURE_NOT_CLOSED:
        return 1
    return 2


def main(argv: Optional[Sequence[str]] = None) -> None:
    import sys
    sys.exit(execute_verb(argv))


if __name__ == "__main__":
    main()
