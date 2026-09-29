"""dv_harness/unknown_uncertainty_registry.py -- a first-class registry of
open UNKNOWNs across a project.

THE GAP THIS CLOSES
--------------------
This repository has several real, row-based readiness reports, and every one
of them can carry rows whose status is the honest `UNKNOWN` this project's
Evidence Truth Rule requires ("absent evidence must produce an honest,
distinctly-named status ... never a silently defaulted or guessed one").
`golden_flow_readiness.py` (section 47's twenty stage rows) and
`generation_readiness.py` (section 211's twenty capability rows) both already
do exactly that -- both reuse `subsystem_discovery.UNKNOWN` rather than
minting a second vocabulary, and both print it row by row. What did not exist
anywhere in this repo (confirmed by a repo-wide grep for
`uncertainty_registry`/`UncertaintyRegistry`/`unknown_registry` before writing
a line of this) is a single place that COLLECTS those open UNKNOWNs across
every source that reports them, so a human reviewing a project's readiness
does not have to open N different reports and manually count how many rows in
each one read UNKNOWN. Two audits of the same project, reading the same two
reports by hand, could disagree about how many open unknowns exist and which
ones they were -- the same "two audits could disagree about the same facts"
problem `golden_flow_readiness.py`'s own docstring names for section 47's
matrix, one level up.

WHAT THIS MODULE IS NOT
------------------------
  * It DERIVES NO NEW FACT. Every entry in this registry is a row some other,
    already-real module produced, filtered down to the rows whose own
    `status` field already reads UNKNOWN. This module never decides that a
    row IS uncertain -- it only collects the rows that already say so.
  * It DOES NOT RESOLVE an UNKNOWN. There is no `resolve`/`answer` verb here:
    an open UNKNOWN stays open until whatever produced it (a human answering
    a question, new evidence landing, a re-run of the underlying analyzer)
    changes that row's own status. This registry is read-only reporting, the
    same boundary `golden_flow_readiness.py` and `generation_readiness.py`
    already draw for themselves.
  * It DOES NOT IMPORT AN ARBITRARY ROSTER OF OTHER ANALYZERS. Only
    `golden_flow_readiness.py` and `generation_readiness.py` are imported and
    run directly -- this task's own instruction names them as the real input
    sources to reuse, and importing a wider, ad hoc set of sibling modules
    from a project this size would risk exactly the "never import a module
    currently claimed by another concurrently-running batch" collision this
    project's house rules warn about. A caller who already has ANOTHER real
    analyzer's row-based output (any module in this repo that follows the
    same `row`/`row_id`/`status`/`evidence`/`gap`/`fact_source` convention
    those two modules established) may register it through
    `extra_sources=` without this module ever importing that analyzer
    itself -- see `build_unknown_uncertainty_registry()`.
  * It WRITES NO GOVERNANCE STATE and RUNS NOTHING, by default. Building the
    registry (`build_unknown_uncertainty_registry()`) is a pure read: it
    performs no filesystem write of its own (its two real sources, per their
    own docstrings, are the "untouched-tree" `golden_flow_readiness.py`/
    `generation_readiness.py`). `write_unknown_uncertainty_registry()` is a
    SEPARATE, explicit act -- the same `assemble` vs `snapshot` split
    `subsystem_contract.py`/`system_verification_contract.py` already use.
  * It APPROVES NOTHING. An open-uncertainty count is an input to a human's
    review, never a substitute for one, and this module has no write path to
    any approval record.

WHY THE ENTRY SHAPE IS THE SOURCE ROWS' OWN SHAPE, NOT A NEW ONE
------------------------------------------------------------------
`golden_flow_readiness.py`'s and `generation_readiness.py`'s own rows already
carry `row_id`/`row`/`status`/`evidence`/`gap`/`fact_source` -- the shape
`extract_unknown_rows()` below reads by default. Reusing those key names
(rather than inventing a fourth vocabulary for "row label", "reason", "why")
means a future module following the same convention needs no adapter code at
all to register itself here; one whose fields are spelled differently can
still register, via the `*_key` overrides `extract_unknown_rows()` accepts.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from . import subsystem_discovery as sd

SCHEMA_VERSION = "1.0"

#: Reused, not re-minted -- the same `subsystem_discovery` word
#: `golden_flow_readiness.py`/`generation_readiness.py`/`system_readiness.py`
#: already share for "we do not know".
UNKNOWN = sd.UNKNOWN

#: This registry's one rendered table's columns, in a fixed order. Rendered
#: through `connectivity.render_markdown_table()`, this repo's only
#: parameterized table renderer -- a hand-rolled `"| " + " | ".join(...)` loop
#: is how a column list drifts out of agreement with the entry shape below.
REGISTRY_COLUMNS: tuple = (
    ("source", "Source"),
    ("row_id", "Row Id"),
    ("label", "Label"),
    ("evidence", "Evidence"),
    ("gap", "Gap"),
    ("fact_source", "Fact Source"),
)

#: Rendered in any cell whose real source supplied nothing. Never an empty
#: string: "this fact is absent" and "this column was never filled in" must
#: not look alike to a reviewer -- the same convention
#: `golden_flow_readiness.NONE_CELL`/`generation_readiness.NONE_CELL` use.
NONE_CELL = "-"

#: Where an explicit `snapshot` write lands, relative to a project root --
#: the same `.dv-harness/<name>.json` convention
#: `subsystem_contract.write_subsystem_contract()` and
#: `system_verification_contract.write_system_verification_contract()` use.
SNAPSHOT_RELATIVE_PATH = Path(".dv-harness") / "unknown_uncertainty_registry.json"


class UnknownUncertaintyRegistryError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def _cell(value: Any) -> str:
    """Pipe/newline-safe cell text -- the same escaping
    `golden_flow_readiness._cell()`/`generation_readiness._cell()` apply
    before their own tables. A gap/evidence string read off a real report can
    legitimately contain a `|`, and `render_markdown_table()` deliberately
    renders values verbatim."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _stringify_fact_source(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) if value else NONE_CELL
    if value in (None, ""):
        return NONE_CELL
    return str(value)


# ===========================================================================
# Extraction -- pure functions, no I/O
# ===========================================================================

def extract_unknown_rows(
    source_name: str,
    rows: Optional[Sequence[Any]],
    *,
    row_id_key: str = "row_id",
    label_key: str = "row",
    status_key: str = "status",
    evidence_key: str = "evidence",
    gap_key: str = "gap",
    fact_source_key: str = "fact_source",
) -> List[Dict[str, Any]]:
    """Filters `rows` (a `golden_flow_readiness.py`/`generation_readiness.py`
    -shaped row list, or any other analyzer's row list following the same
    row/status/evidence/gap/fact_source convention) down to the rows whose
    `status_key` reads UNKNOWN, normalized into one common entry shape.

    Never raises on a malformed row. A malformed row inside a REAL analyzer's
    real output is itself an honest fact (that analyzer produced something
    this registry could not read as one of its declared rows) -- it is
    recorded as its own entry naming the defect, never silently dropped and
    never allowed to crash the whole registry build over one bad row from an
    otherwise-real source.
    """
    if not rows:
        return []
    entries: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, Mapping):
            entries.append({
                "source": source_name,
                "row_id": f"{source_name}[{idx}]",
                "label": NONE_CELL,
                "status": UNKNOWN,
                "evidence": NONE_CELL,
                "gap": f"MALFORMED_ROW: expected a mapping, got {type(row).__name__}",
                "fact_source": NONE_CELL,
                "malformed": True,
            })
            continue
        status = row.get(status_key)
        if status != UNKNOWN:
            continue
        row_id = row.get(row_id_key) or row.get(label_key) or f"{source_name}[{idx}]"
        entries.append({
            "source": source_name,
            "row_id": str(row_id),
            "label": str(row.get(label_key) or NONE_CELL),
            "status": UNKNOWN,
            "evidence": str(row.get(evidence_key) or NONE_CELL),
            "gap": str(row.get(gap_key) or NONE_CELL),
            "fact_source": _stringify_fact_source(row.get(fact_source_key)),
            "malformed": False,
        })
    return entries


#: An explicit alias for callers registering another analyzer's rows here --
#: functionally identical to `extract_unknown_rows()`, named for the intent
#: rather than the mechanics.
register_generic_source = extract_unknown_rows


def unknown_rows_from_golden_flow_matrix(matrix: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Pure extraction over an already-computed
    `golden_flow_readiness.derive_golden_flow_readiness()` result. Performs no
    I/O of its own."""
    return extract_unknown_rows("golden_flow_readiness", matrix.get("rows") or [])


def unknown_rows_from_generation_matrix(matrix: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Pure extraction over an already-computed
    `generation_readiness.derive_generation_readiness()` result. Performs no
    I/O of its own."""
    return extract_unknown_rows("generation_readiness", matrix.get("rows") or [])


# ===========================================================================
# Collection -- the two real, always-consulted sources
# ===========================================================================

def collect_from_golden_flow_readiness(
    root, cfg: Optional[Dict[str, Any]] = None
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Runs the REAL `golden_flow_readiness.derive_golden_flow_readiness()`
    over `root` and returns `(its full matrix, the UNKNOWN rows extracted
    from it)`. Read-only -- see that module's own docstring for its
    untouched-tree guarantee, which this call inherits unchanged."""
    from . import golden_flow_readiness as gfr
    matrix = gfr.derive_golden_flow_readiness(root, cfg)
    return matrix, unknown_rows_from_golden_flow_matrix(matrix)


def collect_from_generation_readiness(
    root, cfg: Optional[Dict[str, Any]] = None, *, deep: bool = True
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Runs the REAL `generation_readiness.derive_generation_readiness()`
    over `root` and returns `(its full matrix, the UNKNOWN rows extracted
    from it)`. Read-only -- see that module's own docstring for its
    untouched-tree guarantee, which this call inherits unchanged.

    `deep=False` skips that module's own expensive SYS-1..SYS-30 chain
    (passed straight through) -- it never changes which rows are UNKNOWN for
    reasons unrelated to that chain, only whether the Flow-B topology rows
    are evaluated at all."""
    from . import generation_readiness as gr
    matrix = gr.derive_generation_readiness(root, cfg, deep=deep)
    return matrix, unknown_rows_from_generation_matrix(matrix)


#: A caller-supplied extra source is either a bare row sequence (using the
#: default `row`/`row_id`/`status`/`evidence`/`gap`/`fact_source` key names),
#: or `(rows, key_overrides)` for a source spelling those fields differently.
ExtraSource = Union[Sequence[Any], Tuple[Sequence[Any], Mapping[str, str]]]


def build_unknown_uncertainty_registry(
    root,
    cfg: Optional[Dict[str, Any]] = None,
    *,
    deep: bool = True,
    extra_sources: Optional[Mapping[str, ExtraSource]] = None,
) -> Dict[str, Any]:
    """The registry: every open (unresolved) UNKNOWN row across every source
    this call consulted, collected into one place.

    Two sources are ALWAYS consulted, because this task's own instruction
    names them as this repo's real row-based UNKNOWN-reporting sources:
    `golden_flow_readiness.py` (section 47's twenty stage rows) and
    `generation_readiness.py` (section 211's twenty capability rows). Reading
    them is not a mutating act -- both are read-only by their own docstrings'
    own guarantee, and this module writes nothing on top of that read.

    `extra_sources`, if supplied, is a caller-declared
    `{source_name: rows}` (or `{source_name: (rows, key_overrides)}`) mapping
    for ANY OTHER analyzer's row-based output the caller already computed
    elsewhere. This module deliberately does not import a wider analyzer
    roster itself -- see the module docstring's "WHAT THIS MODULE IS NOT" --
    so a project wanting a fuller uncertainty surface hands its other
    analyzers' rows in here rather than this module reaching out and
    importing them.
    """
    root = Path(root)
    gf_matrix, gf_entries = collect_from_golden_flow_readiness(root, cfg)
    gr_matrix, gr_entries = collect_from_generation_readiness(root, cfg, deep=deep)

    entries: List[Dict[str, Any]] = list(gf_entries) + list(gr_entries)
    sources_consulted: List[Dict[str, Any]] = [
        {"source": "golden_flow_readiness",
         "rows_total": len(gf_matrix.get("rows") or []),
         "unknown_count": len(gf_entries)},
        {"source": "generation_readiness",
         "rows_total": len(gr_matrix.get("rows") or []),
         "unknown_count": len(gr_entries)},
    ]

    for name, spec in (extra_sources or {}).items():
        if isinstance(spec, tuple) and len(spec) == 2 and isinstance(spec[1], Mapping):
            rows, overrides = spec
        else:
            rows, overrides = spec, {}
        rows = list(rows or [])
        found = extract_unknown_rows(name, rows, **overrides)
        entries.extend(found)
        sources_consulted.append({"source": name, "rows_total": len(rows),
                                   "unknown_count": len(found)})

    by_source: Dict[str, int] = {}
    for e in entries:
        by_source[e["source"]] = by_source.get(e["source"], 0) + 1

    overall = "UNCERTAINTY_SURFACE_OPEN" if entries else "UNCERTAINTY_SURFACE_CLEAR"

    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sources_consulted": sources_consulted,
        "entries": entries,
        "summary": {
            "entries_total": len(entries),
            "by_source": by_source,
        },
        "overall": overall,
        "rule": (
            "Any row from any of this project's real row-based readiness/gate "
            "reports whose status is UNKNOWN is an open, unresolved "
            "uncertainty -- this registry never resolves one and never hides "
            "one. Zero entries means every consulted source's rows carried a "
            "real, non-UNKNOWN verdict, never that nothing was checked."),
        "authorizes": (
            "nothing. This registry is an input to a human's review of the "
            "project's open uncertainty surface; it approves no promotion "
            "and no production write, and it runs no stage, invokes no "
            "gate, and writes no governance state."),
    }


# ===========================================================================
# Rendering
# ===========================================================================

def render_unknown_uncertainty_table(registry: Mapping[str, Any]) -> str:
    """One row per open UNKNOWN, across every consulted source. The JSON
    payload keeps every cell's raw text; only this rendered view is
    escaped."""
    from .connectivity import render_markdown_table
    keys = [k for k, _ in REGISTRY_COLUMNS]
    rows = [{k: _cell(e.get(k, NONE_CELL)) for k in keys}
            for e in (registry.get("entries") or ())]
    return render_markdown_table(
        list(REGISTRY_COLUMNS), rows,
        empty_note="(no open UNKNOWN rows -- every consulted source's rows "
                   "carried a real, non-UNKNOWN verdict)")


def format_unknown_uncertainty_report(registry: Mapping[str, Any]) -> str:
    """The full human-readable report: the verdict, which sources were
    consulted, the table, and the two boundaries (what the rule is, what the
    registry authorizes)."""
    summary = registry["summary"]
    sources = registry.get("sources_consulted") or []
    lines = [
        "# UNKNOWN / UNCERTAINTY REGISTRY",
        "",
        f"**{registry['overall']}** -- {summary['entries_total']} open "
        f"unresolved UNKNOWN row(s) across {len(sources)} source(s).",
        "",
        f"Project root: `{registry['root']}`  (generated {registry['generated_at']})",
        "",
        "## Sources consulted",
        "",
    ]
    for s in sources:
        lines.append(f"- **{s['source']}** -- {s['unknown_count']} unknown / "
                      f"{s['rows_total']} rows")
    lines += [
        "",
        render_unknown_uncertainty_table(registry),
        "",
        registry["rule"],
        "",
        f"This registry authorizes: {registry['authorizes']}",
    ]
    return "\n".join(lines)


# ===========================================================================
# Persistence -- a SEPARATE, explicit write, never performed by `build_*()`
# ===========================================================================

def write_unknown_uncertainty_registry(root, registry: Mapping[str, Any]) -> Path:
    """Persists `registry` to `.dv-harness/unknown_uncertainty_registry.json`
    under `root`. This is the one place this module writes anything --
    `build_unknown_uncertainty_registry()` itself never does, the same
    `assemble` vs `snapshot` split `subsystem_contract.py`/
    `system_verification_contract.py` already use."""
    root = Path(root)
    out_path = root / SNAPSHOT_RELATIVE_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return out_path


def load_unknown_uncertainty_registry(root) -> Optional[Dict[str, Any]]:
    """Reads back a previously-written snapshot, or `None` if none exists.
    Raises `UnknownUncertaintyRegistryError` on a present-but-unreadable file
    -- a broken snapshot must never be read as "no snapshot exists", which
    would be MORE permissive than a missing file."""
    root = Path(root)
    path = root / SNAPSHOT_RELATIVE_PATH
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - reported, never swallowed
        raise UnknownUncertaintyRegistryError("REGISTRY_SNAPSHOT_UNREADABLE", {
            "path": str(path), "error": f"{type(e).__name__}: {e}"})


# ===========================================================================
# One shared entry point for `python -m dv_harness.unknown_uncertainty_registry`
#
# There is deliberately no `dv-harness` CLI verb here: `cli.py` is a large
# file under heavy concurrent edit pressure in this same batch (see this
# project's own house rules on not editing `cli.py`/`gates.py` under that
# condition), the same disclosed choice several very recent sibling modules
# in this codebase (`system_verification_contract.py`,
# `subsystem_contract.py`, `signoff_export.py`, `waiver_store.py`) already
# make. This is a REACHED capability (a real CLI/import caller exists), not a
# WIRED one.
# ===========================================================================

def execute_verb(argv: Optional[List[str]] = None) -> int:
    """`assemble` prints the registry (never writes); `snapshot` additionally
    persists it to `.dv-harness/unknown_uncertainty_registry.json` before
    printing. Exit 0 when the registry is `UNCERTAINTY_SURFACE_CLEAR`
    (zero open UNKNOWNs), 1 when at least one open UNKNOWN was found -- a
    CI-visible "a human should look at this", never an approval signal in
    either direction -- and 2 on a usage/build error."""
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.unknown_uncertainty_registry",
        description="A first-class registry of every open UNKNOWN row across "
                    "this project's real row-based readiness reports "
                    "(golden_flow_readiness.py, generation_readiness.py). "
                    "'assemble' reads only; 'snapshot' additionally persists "
                    "one JSON file.")
    ap.add_argument("verb", choices=["assemble", "snapshot"])
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--no-deep", action="store_true",
                     help="skip generation_readiness's expensive "
                         "SYS-1..SYS-30 topology chain")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    root = Path(args.project_root)
    try:
        registry = build_unknown_uncertainty_registry(root, deep=not args.no_deep)
    except Exception as e:  # noqa: BLE001 - reported, never swallowed
        print(f"UNKNOWN_UNCERTAINTY_REGISTRY_ERROR: {type(e).__name__}: {e}")
        return 2

    if args.verb == "snapshot":
        write_unknown_uncertainty_registry(root, registry)

    if args.as_json:
        print(json.dumps(registry, ensure_ascii=False, indent=2))
    else:
        print(format_unknown_uncertainty_report(registry))

    return 0 if registry["overall"] == "UNCERTAINTY_SURFACE_CLEAR" else 1


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    return execute_verb(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
