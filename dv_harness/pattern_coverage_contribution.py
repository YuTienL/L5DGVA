"""dv_harness/pattern_coverage_contribution.py -- per-PATTERN marginal
coverage contribution (2026-09-06 gap-closure batch).

WHAT THIS IS, AND HOW IT DIFFERS FROM `loop_convergence.py`
-------------------------------------------------------------------------
`loop_convergence.py`'s own module docstring is explicit about its own
boundary: its coverage series is `trend_analysis.daily_rollup()`'s
bins-weighted, PROJECT-WIDE `coverage_percent` CURVE -- one number per day,
aggregated across every pattern that ran that day -- and that module "never
attributes movement to one pattern". `classify_loop_convergence()` can tell
you the project is CONVERGING, PLATEAU'd, or OSCILLATING; it cannot tell you
WHICH pattern moved the needle, by how much, at what runtime/failure cost.

This module answers that different, narrower question: for ONE named
pattern, what new coverage bins (and, of those, which new CROSS-coverage
bins are independently meaningful rather than fully explained by their own
already-covered single-axis bins) did its own run(s) contribute, and at what
real runtime/failure cost -- never an aggregate curve, never a project-wide
trend, always attributed to the one pattern named.

THE REAL SHAPE THIS MODULE READS (grepped and read BEFORE writing a line of
this reader, per this task's own instruction) -- and the real gap that
shape reveals
-------------------------------------------------------------------------
`evidence_db.py`'s `coverage_samples` table (`insert_coverage_sample()`) is
this project's one real coverage-sample store. Its real columns are
`(id, category_name, percent, bins_total, bins_hit, sample_timestamp,
source, ingested_at)` -- a category snapshot at a point in time, tagged
only with a caller-supplied `source` string (in production,
`dashboard._ingest_coverage_summary_to_evidence_db()` passes the
`summary.json` PATH as `source` -- never a pattern/test name) and a
monotonic `id` (a real DuckDB sequence, so `ORDER BY id` recovers true
insertion order without trusting `ingested_at`'s wall-clock resolution).
**There is no `pattern` column on this table.** `evidence_db.py`'s OTHER
real per-pattern table, `jobs` (`insert_job_state()`), does carry a real
`pattern` column, plus `runtime_seconds`/`uvm_error_count`/
`uvm_fatal_count`/`assertion_failure`/`simulator_crash` -- real, already
per-pattern evidence for the runtime/failure side of this task, with
nothing to build here beyond reading it back.

So the honest state of this project's own evidence store is: runtime and
failure evidence per pattern already exists and needs no new linkage;
coverage-BIN evidence exists only as an un-attributed, project-wide
checkpoint sequence. Building a coverage-per-pattern reader therefore means
reusing `coverage_samples` EXACTLY as it is recorded (never adding a
column, never inventing a parallel per-pattern coverage table) and asking
the ONE additional real fact the schema cannot supply on its own: which
checkpoint (`source` value) belongs to which pattern's run. That fact is
supplied by the caller as `sample_attribution` -- an explicit, real
declaration a project makes when it knows which coverage-merge checkpoint
followed which pattern's regression (the same "accept an explicit
caller-declared fact rather than invent one" discipline
`ip_ownership_conflict.py`'s `legacy_bfm_declarations` and
`existing_command_reuse_score.py`'s `existing_commands` already use for a
fact their own real evidence store cannot supply). A pattern with no
attributed checkpoint, and no `jobs` rows, has recorded NOTHING this
project's evidence store can attribute to it -- and this module reports
that as `NOT_AVAILABLE`, never an estimated or zero delta.

REUSE, NOT REINVENTION -- and one deliberate exception, stated rather than
silently violated
-------------------------------------------------------------------------
Every row this module reads comes from `evidence_db.py`'s own real schema,
through `EvidenceStore(db_path, read_only=True).query()` with an explicit
column list zipped back into named dicts -- the same convention
`protocol_compliance_aggregation.py`'s `load_normalized_evidence_rows()`
already established for reading this store's raw positional tuples safely.
No new table, no new column, no write path: this module never constructs
an `EvidenceStore` in writable mode and never calls any of its `insert_*`
methods.

`coverage_analysis.py` already has a private `_cross_axes()`/
`_cross_axes_all_covered()` pair solving almost exactly this task's
"meaningful crosses only" helper (used there to classify a
CROSS_COVERAGE_ONLY_UNCOVERED coverage hole). It is NOT imported here: per
this task's own file-safety scope, `coverage_analysis.py` is one of the
concurrently-claimed batch files this task must never import from, so this
module re-derives the identical, small, generic logic
(`classify_cross_coverage_meaningfulness()` below) directly over plain
`{"percent","bins_total","bins_hit"}` category dicts -- the same shape
`coverage_samples` rows already carry -- rather than importing a claimed
file or leaving the helper unbuilt. The duplication is disclosed, not
hidden: both implementations answer "are this cross bin's two axes already
fully explained by their own single-axis coverage" from the same kind of
evidence, independently, by design for this batch.

WHAT THIS MODULE DOES NOT DO
-------------------------------------------------------------------------
It writes nothing to `evidence_db.py` and mints no memory/blackboard/
approval record. It arbitrates nothing and runs no gate; there is
deliberately no stage gate here. `cost` is always reported `NOT_AVAILABLE`:
a repo-wide check before writing this module found no per-job compute or
license-usage cost producer anywhere in this codebase --
`loop_budget.py`'s own CLAUDE.md section states plainly that
"max_compute / max_license_usage / max_token_cost ... have no producer in
this harness at all" -- so inventing a dollar or license-seat-hour figure
here would be exactly the fabrication the Evidence Truth Rule forbids.
`runtime_seconds` (a real `jobs.runtime_seconds` sum) is reported as a
distinct, real, measured field instead.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

# `models.py` is NOT one of this batch's claimed files -- imported only for
# the same vocabulary-disjointness self-check several sibling modules
# already run (`capability_evolution.py`, `benchmark_dataset.py`,
# `subsystem_maturity_gate.py`, ...): this module's own status words must
# never silently collide with a real verification-verdict token.
from . import models as _models


class PatternCoverageContributionError(ValueError):
    """Raised on malformed input this module was explicitly handed (a bad
    `sample_attribution`/`cross_definitions` record) -- never on an honest
    absence of evidence, which is reported as `NOT_AVAILABLE` instead."""


# ---------------------------------------------------------------------------
# Status vocabulary -- deliberately disjoint from dv_harness.models.Status
# ---------------------------------------------------------------------------
MEASURED = "MEASURED"
PARTIALLY_MEASURED = "PARTIALLY_MEASURED"
NOT_AVAILABLE = "NOT_AVAILABLE"

CONTRIBUTION_STATUSES = (MEASURED, PARTIALLY_MEASURED, NOT_AVAILABLE)

#: Cross-coverage-meaningfulness verdicts. FULLY_EXPLAINED is the one
#: "skip this cross bin, it added no new information" case; UNKNOWN is the
#: honest "cannot prove either way" case and is NEVER treated as
#: FULLY_EXPLAINED -- this module never skips a cross bin on the strength
#: of missing evidence, only on the strength of a real, matched, fully
#: covered axis category.
CROSS_MEANINGFUL = "INDEPENDENTLY_MEANINGFUL"
CROSS_FULLY_EXPLAINED = "FULLY_EXPLAINED_BY_AXES"
CROSS_UNKNOWN = "UNKNOWN_AXIS_COVERAGE"

CROSS_VERDICTS = (CROSS_MEANINGFUL, CROSS_FULLY_EXPLAINED, CROSS_UNKNOWN)


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own status/verdict tokens must never collide with a
    real `dv_harness.models.Status` member -- the same guard
    `capability_evolution.py`/`benchmark_dataset.py`/
    `subsystem_maturity_gate.py` already run on their own vocabularies."""
    status_values = {s.value for s in _models.Status}
    mine = set(CONTRIBUTION_STATUSES) | set(CROSS_VERDICTS)
    collision = mine & status_values
    if collision:
        raise AssertionError(
            f"pattern_coverage_contribution vocabulary collides with "
            f"models.Status: {sorted(collision)}")


assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# evidence_db.py's real schema, read back -- no write path, no new column.
# ---------------------------------------------------------------------------
#: `coverage_samples`'s real column order, per `evidence_db.py`'s own
#: `_SCHEMA_STATEMENTS` -- read back, never re-typed as a guess.
COVERAGE_SAMPLE_COLUMNS = (
    "id", "category_name", "percent", "bins_total", "bins_hit",
    "sample_timestamp", "source", "ingested_at",
)

#: `jobs`'s real column order (the columns `insert_job_state()` itself
#: writes, plus `job_id`/`ingested_at`), per `evidence_db.py`'s own schema.
JOB_COLUMNS = (
    "job_id", "regression_id", "pattern", "options", "run_dir", "sim_log",
    "seed", "fsdb_path", "lsf_status", "sim_status", "last_log_offset",
    "uvm_error_count", "uvm_fatal_count", "assertion_failure",
    "simulator_crash", "terminal_signature", "early_kill", "kill_reason",
    "root_cause_status", "fix_proposal_status", "git_sha", "server_sha",
    "last_change_time", "state_fingerprint", "runtime_seconds", "ingested_at",
)


def _open_store(db_path: Union[str, Path]):
    """Read-only `EvidenceStore` construction, or `None` + a real reason.
    Never raises: an absent/corrupt evidence.duckdb is a real, common,
    honest state (this store is opt-in project-wide), not a defect in the
    caller's request."""
    try:
        from . import evidence_db as evidence_db_mod
    except Exception as exc:  # pragma: no cover - evidence_db.py itself missing
        return None, f"evidence_db module unavailable: {exc}"
    try:
        store = evidence_db_mod.EvidenceStore(db_path, read_only=True)
    except Exception as exc:
        return None, f"could not open evidence database at {db_path!r}: {exc}"
    return store, None


def _table_exists(store, table_name: str) -> bool:
    try:
        row = store.query(
            "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [table_name]
        )
    except Exception:
        return False
    return bool(row)


def load_coverage_sample_rows(db_path: Union[str, Path]) -> Dict[str, Any]:
    """Every real `coverage_samples` row, in true insertion order (`id`
    ascending -- a real DuckDB sequence, never trusted-by-wall-clock).
    Returns `{"status": MEASURED|NOT_AVAILABLE, "reason": ..., "rows": [...]}`
    -- `rows` is `[]` on `NOT_AVAILABLE`, never fabricated."""
    store, reason = _open_store(db_path)
    if store is None:
        return {"status": NOT_AVAILABLE, "reason": reason, "rows": []}
    try:
        if not _table_exists(store, "coverage_samples"):
            return {
                "status": NOT_AVAILABLE,
                "reason": ("evidence.duckdb has no coverage_samples table -- "
                            "predates this schema, or nothing has ever "
                            "recorded a coverage sample"),
                "rows": [],
            }
        cols_sql = ", ".join(COVERAGE_SAMPLE_COLUMNS)
        raw_rows = store.query(
            f"SELECT {cols_sql} FROM coverage_samples ORDER BY id ASC")
    finally:
        store.close()
    rows = [dict(zip(COVERAGE_SAMPLE_COLUMNS, raw)) for raw in raw_rows]
    if not rows:
        return {
            "status": NOT_AVAILABLE,
            "reason": "evidence.duckdb's coverage_samples table is empty",
            "rows": [],
        }
    return {"status": MEASURED, "reason": None, "rows": rows}


def load_job_rows_for_pattern(db_path: Union[str, Path], pattern: str) -> Dict[str, Any]:
    """Every real `jobs` row recorded for `pattern`, ordered by `job_id`.
    Same `{"status", "reason", "rows"}` shape as
    `load_coverage_sample_rows()`."""
    store, reason = _open_store(db_path)
    if store is None:
        return {"status": NOT_AVAILABLE, "reason": reason, "rows": []}
    try:
        if not _table_exists(store, "jobs"):
            return {
                "status": NOT_AVAILABLE,
                "reason": "evidence.duckdb has no jobs table",
                "rows": [],
            }
        cols_sql = ", ".join(JOB_COLUMNS)
        raw_rows = store.query(
            f"SELECT {cols_sql} FROM jobs WHERE pattern = ? ORDER BY job_id ASC",
            [pattern],
        )
    finally:
        store.close()
    rows = [dict(zip(JOB_COLUMNS, raw)) for raw in raw_rows]
    if not rows:
        return {
            "status": NOT_AVAILABLE,
            "reason": f"no evidence_db.jobs rows recorded for pattern {pattern!r}",
            "rows": [],
        }
    return {"status": MEASURED, "reason": None, "rows": rows}


# ---------------------------------------------------------------------------
# Checkpoint grouping: coverage_samples rows sharing one real `source` value
# are one coverage-merge event ("checkpoint"), in true chronological order.
# ---------------------------------------------------------------------------
def group_into_checkpoints(coverage_sample_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Groups real `coverage_samples` rows by their own `source` field into
    ordered checkpoints. Order is the MINIMUM `id` in each group (the real
    DuckDB insertion sequence) -- a checkpoint's own internal row order
    never matters, only which checkpoint came before which."""
    by_source: Dict[Any, Dict[str, Any]] = {}
    order_key: Dict[Any, int] = {}
    for row in coverage_sample_rows:
        src = row.get("source")
        cp = by_source.setdefault(
            src, {"source": src, "sample_timestamp": row.get("sample_timestamp"),
                  "categories": {}})
        cp["categories"][row["category_name"]] = {
            "percent": row.get("percent"),
            "bins_total": row.get("bins_total"),
            "bins_hit": row.get("bins_hit"),
        }
        rid = row.get("id")
        if src not in order_key or (rid is not None and rid < order_key[src]):
            order_key[src] = rid if rid is not None else order_key.get(src, 0)
    ordered_sources = sorted(by_source.keys(), key=lambda s: (order_key.get(s) is None, order_key.get(s)))
    return [by_source[s] for s in ordered_sources]


def _validate_sample_attribution(sample_attribution: Sequence[Dict[str, Any]]) -> Dict[Any, str]:
    """Real, caller-declared `{source: pattern}` map. Raises
    `PatternCoverageContributionError` on a malformed entry or on two
    entries declaring different patterns for the SAME source -- an
    ambiguous attribution must never be silently resolved by picking
    one."""
    if not isinstance(sample_attribution, (list, tuple)):
        raise PatternCoverageContributionError(
            "sample_attribution must be a list of {'source','pattern'} records")
    mapping: Dict[Any, str] = {}
    for i, entry in enumerate(sample_attribution):
        if not isinstance(entry, dict):
            raise PatternCoverageContributionError(
                f"sample_attribution[{i}] is not a dict: {entry!r}")
        source = entry.get("source")
        pattern = entry.get("pattern")
        if not source or not isinstance(source, str):
            raise PatternCoverageContributionError(
                f"sample_attribution[{i}] missing a real non-empty 'source' string")
        if not pattern or not isinstance(pattern, str):
            raise PatternCoverageContributionError(
                f"sample_attribution[{i}] missing a real non-empty 'pattern' string")
        if source in mapping and mapping[source] != pattern:
            raise PatternCoverageContributionError(
                f"sample_attribution declares source {source!r} for both "
                f"pattern {mapping[source]!r} and {pattern!r} -- ambiguous, "
                f"never silently resolved")
        mapping[source] = pattern
    return mapping


# ---------------------------------------------------------------------------
# "Meaningful crosses only": skip a cross-coverage bin whose two axes are
# already fully explained by their own single-axis bins.
# ---------------------------------------------------------------------------
def classify_cross_coverage_meaningfulness(
    categories_snapshot: Dict[str, Dict[str, Any]],
    cross_definitions: Sequence[Dict[str, Any]],
    *, threshold_percent: float = 100.0,
) -> List[Dict[str, Any]]:
    """`categories_snapshot` is `{category_name: {"percent","bins_total",
    "bins_hit"}}` -- the same generic shape `coverage_samples` rows already
    carry. `cross_definitions` is `[{"cross_name", "axes": [name1, name2,
    ...]}]`, a real, caller-declared fact about which category IS a
    cross-coverage bin and which single-axis categories it crosses (this
    module never derives a cross relationship from a bin's own name).

    Returns one record per cross definition:
    `{"cross_name", "axes", "verdict", "reason", "axis_details"}`.
    `verdict` is `FULLY_EXPLAINED_BY_AXES` ONLY when EVERY declared axis is
    both present in `categories_snapshot` and at/above `threshold_percent`
    (bins_hit >= bins_total when total > 0). An axis that is missing from
    the snapshot, or whose own bins_total is not a real positive int, makes
    the whole cross `UNKNOWN_AXIS_COVERAGE` -- absence of proof that the
    axes explain the cross is never read as proof they do not."""
    if not isinstance(cross_definitions, (list, tuple)):
        raise PatternCoverageContributionError(
            "cross_definitions must be a list of {'cross_name','axes'} records")
    results = []
    for i, cdef in enumerate(cross_definitions):
        if not isinstance(cdef, dict):
            raise PatternCoverageContributionError(
                f"cross_definitions[{i}] is not a dict: {cdef!r}")
        cross_name = cdef.get("cross_name")
        axes = cdef.get("axes")
        if not cross_name or not isinstance(cross_name, str):
            raise PatternCoverageContributionError(
                f"cross_definitions[{i}] missing a real 'cross_name'")
        if not isinstance(axes, list) or len(axes) < 2:
            raise PatternCoverageContributionError(
                f"cross_definitions[{i}] ('{cross_name}') needs >= 2 real 'axes' names")

        axis_details = []
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
                "axis": axis, "known": True, "bins_hit": bins_hit,
                "bins_total": bins_total, "percent": percent,
                "fully_explained": fully,
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

        results.append({
            "cross_name": cross_name, "axes": list(axes),
            "verdict": verdict, "reason": reason, "axis_details": axis_details,
        })
    return results


# ---------------------------------------------------------------------------
# The per-pattern contribution report.
# ---------------------------------------------------------------------------
def compute_pattern_coverage_contribution(
    db_path: Union[str, Path],
    pattern: str,
    sample_attribution: Sequence[Dict[str, Any]],
    *, cross_definitions: Optional[Sequence[Dict[str, Any]]] = None,
    threshold_percent: float = 100.0,
) -> Dict[str, Any]:
    """The one deliverable this module exists to produce: `pattern`'s real,
    attributed marginal coverage contribution (new bins hit, new
    meaningful cross bins hit, a bins-weighted coverage_delta_percent),
    plus its real runtime/failure evidence from `evidence_db.py`'s `jobs`
    table -- and an always-`NOT_AVAILABLE` `cost` field, since nothing in
    this codebase measures one.

    `sample_attribution` is REQUIRED and is the one fact
    `evidence_db.py`'s own `coverage_samples` schema cannot supply: which
    checkpoint (`source` value) belongs to which pattern's run. Raises
    `PatternCoverageContributionError` on a malformed attribution/
    cross-definition record; never silently drops or guesses one."""
    if not pattern or not isinstance(pattern, str):
        raise PatternCoverageContributionError("pattern must be a real non-empty string")
    source_to_pattern = _validate_sample_attribution(sample_attribution)

    coverage_load = load_coverage_sample_rows(db_path)
    job_load = load_job_rows_for_pattern(db_path, pattern)

    evidence: List[Dict[str, Any]] = [
        {"source": "evidence_db.coverage_samples", "status": coverage_load["status"],
         "reason": coverage_load["reason"]},
        {"source": "evidence_db.jobs", "status": job_load["status"],
         "reason": job_load["reason"]},
    ]

    # ---- coverage side ----------------------------------------------------
    coverage_report: Dict[str, Any]
    if coverage_load["status"] != MEASURED:
        coverage_report = {"status": NOT_AVAILABLE, "reason": coverage_load["reason"]}
    else:
        checkpoints = group_into_checkpoints(coverage_load["rows"])
        attributed_sources = {s for s, p in source_to_pattern.items() if p == pattern}
        checkpoint_sources_seen = {cp["source"] for cp in checkpoints}
        unmatched = sorted(attributed_sources - checkpoint_sources_seen)

        if not attributed_sources:
            coverage_report = {
                "status": NOT_AVAILABLE,
                "reason": (f"sample_attribution declares no checkpoint for "
                           f"pattern {pattern!r}; evidence_db.coverage_samples "
                           f"cannot be attributed to a pattern on its own"),
            }
        else:
            state: Dict[str, Dict[str, Any]] = {}
            category_totals: Dict[str, Dict[str, Any]] = {}
            checkpoints_attributed = 0
            regressed_categories: List[str] = []
            for cp in checkpoints:
                state_before = dict(state)
                if source_to_pattern.get(cp["source"]) == pattern:
                    checkpoints_attributed += 1
                    for cat_name, after in cp["categories"].items():
                        before = state_before.get(
                            cat_name,
                            {"bins_total": after.get("bins_total"), "bins_hit": 0, "percent": 0.0})
                        raw_delta = (after.get("bins_hit") or 0) - (before.get("bins_hit") or 0)
                        if raw_delta < 0 and cat_name not in regressed_categories:
                            regressed_categories.append(cat_name)
                        entry = category_totals.setdefault(cat_name, {
                            "category_name": cat_name, "before_bins_hit": before.get("bins_hit"),
                            "after_bins_hit": after.get("bins_hit"), "bins_total": after.get("bins_total"),
                            "raw_delta_bins_hit": 0, "new_bins_hit": 0,
                        })
                        entry["after_bins_hit"] = after.get("bins_hit")
                        entry["bins_total"] = after.get("bins_total")
                        entry["raw_delta_bins_hit"] += raw_delta
                        entry["new_bins_hit"] += max(0, raw_delta)
                # merge this checkpoint into running state regardless of attribution
                for cat_name, row in cp["categories"].items():
                    state[cat_name] = dict(row)

            cross_by_name: Dict[str, Dict[str, Any]] = {}
            if cross_definitions:
                for cdef in cross_definitions:
                    if isinstance(cdef, dict) and cdef.get("cross_name"):
                        cross_by_name[cdef["cross_name"]] = cdef

            new_bins_hit_total = sum(e["new_bins_hit"] for e in category_totals.values())
            bins_total_touched = sum(
                (e["bins_total"] or 0) for e in category_totals.values() if e["bins_total"])
            coverage_delta_percent = (
                (new_bins_hit_total / bins_total_touched) * 100.0
                if bins_total_touched else 0.0
            )

            cross_classification: List[Dict[str, Any]] = []
            new_crosses_hit_total = 0
            if cross_by_name:
                # meaningfulness is evaluated against the snapshot as it stood
                # BEFORE the pattern's own checkpoint(s) touched it -- "already
                # fully explained" means already, i.e. prior to this pattern's
                # own contribution. Re-derive that pre-pattern snapshot by
                # walking checkpoints again up to (excluding) the first one
                # attributed to this pattern.
                pre_state: Dict[str, Dict[str, Any]] = {}
                for cp in checkpoints:
                    if source_to_pattern.get(cp["source"]) == pattern:
                        break
                    for cat_name, row in cp["categories"].items():
                        pre_state[cat_name] = dict(row)
                cross_classification = classify_cross_coverage_meaningfulness(
                    pre_state, list(cross_by_name.values()), threshold_percent=threshold_percent)
                verdict_by_cross = {c["cross_name"]: c["verdict"] for c in cross_classification}
                for cat_name, entry in category_totals.items():
                    if cat_name in cross_by_name and entry["new_bins_hit"] > 0:
                        entry["is_cross"] = True
                        entry["cross_verdict"] = verdict_by_cross.get(cat_name, CROSS_UNKNOWN)
                        if entry["cross_verdict"] != CROSS_FULLY_EXPLAINED:
                            new_crosses_hit_total += entry["new_bins_hit"]
                    elif cat_name in cross_by_name:
                        entry["is_cross"] = True
                        entry["cross_verdict"] = verdict_by_cross.get(cat_name, CROSS_UNKNOWN)

            coverage_report = {
                "status": MEASURED,
                "reason": None,
                "checkpoints_attributed": checkpoints_attributed,
                "new_bins_hit": new_bins_hit_total,
                "new_crosses_hit": (new_crosses_hit_total if cross_by_name else None),
                "coverage_delta_percent": round(coverage_delta_percent, 4),
                "category_breakdown": sorted(category_totals.values(), key=lambda e: e["category_name"]),
                "cross_classification": cross_classification,
                "regressed_categories": regressed_categories,
                "unmatched_attribution_sources": unmatched,
            }

    # ---- runtime / failures side ------------------------------------------
    if job_load["status"] != MEASURED:
        runtime_report = {"status": NOT_AVAILABLE, "reason": job_load["reason"]}
        failures_report = {"status": NOT_AVAILABLE, "reason": job_load["reason"]}
    else:
        rows = job_load["rows"]
        runtimes = [r["runtime_seconds"] for r in rows if isinstance(r.get("runtime_seconds"), (int, float))]
        runtime_report = {
            "status": MEASURED, "reason": None,
            "jobs_considered": len(rows),
            "runs_with_runtime": len(runtimes),
            "total_seconds": sum(runtimes) if runtimes else None,
        }
        per_job = []
        uvm_error_total = 0
        uvm_fatal_total = 0
        assertion_failure_count = 0
        simulator_crash_count = 0
        failed_job_count = 0
        for r in rows:
            uvm_error = r.get("uvm_error_count") or 0
            uvm_fatal = r.get("uvm_fatal_count") or 0
            assertion_failure = bool(r.get("assertion_failure"))
            simulator_crash = bool(r.get("simulator_crash"))
            failed = bool(uvm_fatal or assertion_failure or simulator_crash or uvm_error)
            uvm_error_total += uvm_error
            uvm_fatal_total += uvm_fatal
            assertion_failure_count += int(assertion_failure)
            simulator_crash_count += int(simulator_crash)
            failed_job_count += int(failed)
            per_job.append({
                "job_id": r.get("job_id"), "runtime_seconds": r.get("runtime_seconds"),
                "uvm_error_count": r.get("uvm_error_count"), "uvm_fatal_count": r.get("uvm_fatal_count"),
                "assertion_failure": assertion_failure, "simulator_crash": simulator_crash,
                "lsf_status": r.get("lsf_status"), "failed": failed,
            })
        failures_report = {
            "status": MEASURED, "reason": None,
            "jobs_considered": len(rows),
            "uvm_error_total": uvm_error_total,
            "uvm_fatal_total": uvm_fatal_total,
            "assertion_failure_count": assertion_failure_count,
            "simulator_crash_count": simulator_crash_count,
            "failed_job_count": failed_job_count,
            "per_job": per_job,
        }

    cost_report = {
        "status": NOT_AVAILABLE,
        "reason": ("no per-job compute/license-usage cost producer exists in this "
                   "codebase's evidence_db.py schema (jobs.runtime_seconds is the "
                   "only cost-adjacent real field); see loop_budget.py's own "
                   "disclosed max_compute/max_license_usage/max_token_cost gap"),
    }

    measured_parts = [p["status"] for p in (coverage_report, runtime_report, failures_report)]
    if all(s == MEASURED for s in measured_parts):
        overall_status = MEASURED
        overall_reason = None
    elif any(s == MEASURED for s in measured_parts):
        overall_status = PARTIALLY_MEASURED
        overall_reason = "some but not all of coverage/runtime/failures could be measured for this pattern"
    else:
        overall_status = NOT_AVAILABLE
        overall_reason = f"no evidence_db evidence (coverage or job) could be attributed to pattern {pattern!r}"

    return {
        "pattern": pattern,
        "status": overall_status,
        "reason": overall_reason,
        "coverage": coverage_report,
        "runtime": runtime_report,
        "failures": failures_report,
        "cost": cost_report,
        "evidence": evidence,
    }


def compute_patterns_coverage_contribution(
    db_path: Union[str, Path],
    patterns: Sequence[str],
    sample_attribution: Sequence[Dict[str, Any]],
    *, cross_definitions: Optional[Sequence[Dict[str, Any]]] = None,
    threshold_percent: float = 100.0,
) -> Dict[str, Dict[str, Any]]:
    """Convenience: one report per pattern in `patterns`, sharing the same
    `sample_attribution`/`cross_definitions` -- each pattern's report is
    independently computed by `compute_pattern_coverage_contribution()`,
    never averaged or folded together."""
    return {
        p: compute_pattern_coverage_contribution(
            db_path, p, sample_attribution,
            cross_definitions=cross_definitions, threshold_percent=threshold_percent)
        for p in patterns
    }


# ---------------------------------------------------------------------------
# Ad hoc front door
# ---------------------------------------------------------------------------
def execute_verb(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="pattern-coverage-contribution")
    sub = parser.add_subparsers(dest="verb", required=True)

    p1 = sub.add_parser("contribution", help="per-pattern marginal coverage contribution")
    p1.add_argument("--db-path", required=True)
    p1.add_argument("--pattern", required=True)
    p1.add_argument("--attribution", required=True,
                    help="JSON file: list of {'source','pattern'} records")
    p1.add_argument("--cross-definitions",
                    help="JSON file: list of {'cross_name','axes'} records")
    p1.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.verb == "contribution":
        try:
            attribution = json.loads(Path(args.attribution).read_text(encoding="utf-8"))
            cross_defs = None
            if args.cross_definitions:
                cross_defs = json.loads(Path(args.cross_definitions).read_text(encoding="utf-8"))
            report = compute_pattern_coverage_contribution(
                args.db_path, args.pattern, attribution, cross_definitions=cross_defs)
        except PatternCoverageContributionError as exc:
            print(f"status=ERROR reason={exc}")
            return 2

        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(f"pattern={report['pattern']} status={report['status']} reason={report['reason']}")
        if report["status"] == MEASURED:
            return 0
        if report["status"] == PARTIALLY_MEASURED:
            return 1
        return 2

    return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(execute_verb(sys.argv[1:]))
