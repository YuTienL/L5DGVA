"""Tests for dv_harness/mcp/regression_queries.py + verbs.query_regression
against a REAL dv_harness.evidence_db.EvidenceStore (no mock connection),
matching test_evidence_db.py's own real-DuckDB testing convention."""
from __future__ import annotations

import datetime

import pytest

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("jsonschema")

from dv_harness.evidence_db import EvidenceStore
from dv_harness.mcp import regression_queries, verbs
from dv_harness.mcp.errors import McpValidationError


@pytest.fixture
def store(tmp_path):
    s = EvidenceStore(tmp_path / "evidence.duckdb")
    # regression_verdicts is keyed PRIMARY KEY(pattern) -- a real,
    # deliberate upsert-by-pattern semantic (evidence_db.py's own
    # docstring: "a pattern's presence in regression.list IS the currently
    # verified PASS claim; a FAIL evicts it"). So 3 DISTINCT patterns here,
    # not 3 verdicts for one pattern, to actually get 3 rows.
    s.insert_regression_verdict("usb3_lfps_basic", True, job_id=101)
    s.insert_regression_verdict("usb3_link_training", False, job_id=102)
    s.insert_regression_verdict("apb_smoke", True, job_id=201)
    yield s
    s.close()


# ---- regression_queries.run_query() (module-level, direct) -----------------

def test_latest_shape_defaults_limit_and_orders_desc(store):
    rows = regression_queries.run_query(store, "latest", {})
    assert len(rows) == 3
    assert rows[0]["job_id"] == 201  # apb_smoke inserted last


def test_latest_shape_respects_limit(store):
    rows = regression_queries.run_query(store, "latest", {"limit": 1})
    assert len(rows) == 1


def test_by_pattern_shape_filters_to_one_row(store):
    rows = regression_queries.run_query(store, "by_pattern", {"pattern": "usb3_lfps_basic"})
    assert [r["job_id"] for r in rows] == [101]
    assert all(r["pattern"] == "usb3_lfps_basic" for r in rows)


def test_by_verdict_shape_filters_true(store):
    rows = regression_queries.run_query(store, "by_verdict", {"verdict_passed": True})
    assert {r["job_id"] for r in rows} == {101, 201}


def test_by_verdict_shape_filters_false(store):
    rows = regression_queries.run_query(store, "by_verdict", {"verdict_passed": False})
    assert [r["job_id"] for r in rows] == [102]
    assert rows[0]["pattern"] == "usb3_link_training"


def test_by_date_range_shape_includes_all_recent_rows(store):
    since = (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat()
    until = (datetime.datetime.now() + datetime.timedelta(days=1)).isoformat()
    rows = regression_queries.run_query(store, "by_date_range", {"since": since, "until": until})
    assert len(rows) == 3


def test_by_date_range_shape_excludes_out_of_range(store):
    since = (datetime.datetime.now() + datetime.timedelta(days=1)).isoformat()
    until = (datetime.datetime.now() + datetime.timedelta(days=2)).isoformat()
    rows = regression_queries.run_query(store, "by_date_range", {"since": since, "until": until})
    assert rows == []


def test_recorded_at_is_json_serializable_isoformat_string(store):
    rows = regression_queries.run_query(store, "latest", {})
    for row in rows:
        assert isinstance(row["recorded_at"], str)
        datetime.datetime.fromisoformat(row["recorded_at"])


def test_unknown_query_shape_raises_validation_error_not_arbitrary_sql(store):
    with pytest.raises(McpValidationError):
        regression_queries.run_query(store, "'; DROP TABLE regression_verdicts; --", {})


def test_by_pattern_missing_required_param_raises(store):
    with pytest.raises(McpValidationError):
        regression_queries.run_query(store, "by_pattern", {})


def test_by_date_range_missing_one_required_param_raises(store):
    with pytest.raises(McpValidationError):
        regression_queries.run_query(store, "by_date_range", {"since": "2026-01-01"})


def test_every_fixed_sql_statement_is_select_only():
    for name in regression_queries.QUERY_SHAPES:
        sql = regression_queries._SHAPES[name]["sql"]
        assert sql.strip().upper().startswith("SELECT")
        for banned in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", ";"):
            assert banned not in sql.upper()


# ---- verbs.query_regression() (full envelope) --------------------------------

def test_query_regression_verb_wraps_rows_in_envelope(store):
    result = verbs.query_regression(store, {"query_shape": "by_pattern", "pattern": "apb_smoke"})
    assert result["verb"] == "query_regression"
    assert result["status"] == "OK"
    assert result["row_count"] == 1
    assert result["rows"][0]["job_id"] == 201


def test_query_regression_verb_rejects_bad_query_shape_at_param_schema_level(store):
    with pytest.raises(McpValidationError):
        verbs.query_regression(store, {"query_shape": "raw_sql"})


def test_query_regression_verb_rejects_unknown_param(store):
    with pytest.raises(McpValidationError):
        verbs.query_regression(store, {"query_shape": "latest", "sql": "SELECT * FROM jobs"})
