"""dv_harness/mcp/regression_queries.py -- the fixed, parameterized query
shapes behind the query_regression verb.

Reads exclusively through dv_harness.evidence_db.EvidenceStore's real,
already-tested `.query(sql, params)` method (2026-09-03 verible+DuckDB
task) -- never through that store's insert_job_state/
insert_job_memory_record/insert_regression_verdict/insert_coverage_sample/
insert_rtl_parse/insert_normalized_evidence methods, and never through its
underlying connection's `.execute()` directly (this module never touches
`EvidenceStore._conn`).

Every SQL string below is a hard-coded, module-level SELECT -- caller input
only ever supplies VALUES bound through `?` placeholders (`build_args`),
never SQL TEXT. This is the concrete mechanism that keeps query_regression
from degrading into the free-text/arbitrary-SQL verb Part A explicitly
rules out ("passing caller-supplied SQL through to query() would defeat the
entire fixed-verb, not free-access design principle this system exists to
enforce"). See dv_harness_tests/test_mcp_read_only_boundary.py for the
static proof every statement here is SELECT-only, and
dv_harness_tests/test_mcp_query_regression.py for behavioral coverage of
all 4 shapes."""
from __future__ import annotations

from typing import Any

from .errors import McpValidationError

_COLUMNS = ("pattern", "verdict_passed", "job_id", "recorded_at")
_SELECT = f"SELECT {', '.join(_COLUMNS)} FROM regression_verdicts"

# One entry per fixed query_shape. `required` lists the params.query_shape
# request must supply; `build_args` turns validated params into the
# positional `?` bind values for `sql`, in order -- it is called only AFTER
# `required` has already been confirmed present, so it can index params[...]
# directly.
_SHAPES: dict[str, dict[str, Any]] = {
    "latest": {
        "sql": f"{_SELECT} ORDER BY recorded_at DESC LIMIT ?",
        "required": (),
        "build_args": lambda p: [int(p.get("limit", 20))],
    },
    "by_pattern": {
        "sql": f"{_SELECT} WHERE pattern = ? ORDER BY recorded_at DESC",
        "required": ("pattern",),
        "build_args": lambda p: [p["pattern"]],
    },
    "by_verdict": {
        "sql": f"{_SELECT} WHERE verdict_passed = ? ORDER BY recorded_at DESC",
        "required": ("verdict_passed",),
        "build_args": lambda p: [bool(p["verdict_passed"])],
    },
    "by_date_range": {
        "sql": f"{_SELECT} WHERE recorded_at >= ? AND recorded_at <= ? ORDER BY recorded_at DESC",
        "required": ("since", "until"),
        "build_args": lambda p: [p["since"], p["until"]],
    },
}

QUERY_SHAPES = tuple(_SHAPES)


def run_query(evidence_store: Any, query_shape: str, params: dict) -> list:
    """Runs one fixed query shape against `evidence_store.query()` and
    returns a list of JSON-friendly row dicts (column-name keyed, not raw
    tuples). Raises McpValidationError for a `query_shape` outside the fixed
    set or a call missing that shape's required params -- never falls
    through to executing arbitrary SQL."""
    if query_shape not in _SHAPES:
        raise McpValidationError(
            f"{query_shape!r} is not a fixed query_regression shape; valid shapes: {QUERY_SHAPES}")
    shape = _SHAPES[query_shape]
    missing = [k for k in shape["required"] if k not in params]
    if missing:
        raise McpValidationError(
            f"query_regression shape {query_shape!r} missing required params: {missing}")
    args = shape["build_args"](params)
    rows = evidence_store.query(shape["sql"], args)
    return [dict(zip(_COLUMNS, (_jsonable(v) for v in row))) for row in rows]


def _jsonable(value: Any) -> Any:
    """DuckDB returns native `datetime`/`date` objects for TIMESTAMP
    columns (`recorded_at`), which `json.dumps()` cannot serialize as-is --
    normalize to an ISO-8601 string so every query_regression result is
    plain-JSON without a caller needing to know DuckDB's Python typemap."""
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else value
