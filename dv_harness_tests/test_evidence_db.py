"""Tests for dv_harness/evidence_db.py -- DuckDB-backed evidence store
(2026-09-03, verible+DuckDB evidence-store task). Exercises the real
ingestion path against real DuckDB (no mock connection): a real
`lsf_client.JobState`, a real job_failure record shape (mirroring
`lsf_client._upsert_job_tier_memory_record()`'s own dict), a real
`regression_list_manager` verdict, a real `coverage_analysis`
category, and the real `verible_parser` output for a synthesized .sv
fixture (via test_verible_parser.py's own FIFO_FIXTURE)."""
from __future__ import annotations

import json
import shutil

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness.evidence_db import EvidenceStore, default_db_path, signature_key
from dv_harness.lsf_client import JobState
from dv_harness.uvm_generator.regression_list_manager import record_verdict

from .test_verible_parser import FIFO_FIXTURE, requires_verible


@pytest.fixture
def store(tmp_path):
    s = EvidenceStore(tmp_path / "evidence.duckdb")
    yield s
    s.close()


def _sample_job_state(**overrides):
    base = dict(
        job_id=123456, regression_id="REG-2026-09-03-A", pattern="usb3_lfps_basic",
        options="+ntb_random_seed=42", run_dir="/proj/run/123456",
        sim_log="/proj/run/123456/sim.log", seed="42",
        lsf_status="EXIT", sim_status="FAIL", uvm_error_count=3, uvm_fatal_count=1,
        assertion_failure=True, terminal_signature="UVM_FATAL_LFPS_TIMEOUT",
    )
    base.update(overrides)
    return JobState(**base)


def _sample_failure_signature(**overrides):
    base = dict(
        protocol="USB3", pattern="usb3_lfps_basic", symptom="LFPS handshake timeout",
        root_cause_hint=None, uvm_error_count=3, uvm_fatal_count=1,
        assertion_failure=True, simulator_crash=False,
        terminal_signature="UVM_FATAL_LFPS_TIMEOUT", lsf_status="EXIT",
        abnormal_termination=True, extra_text="usb3_lfps_basic",
    )
    base.update(overrides)
    return base


def _sample_job_failure_record(**overrides):
    base = dict(
        memory_id="JOB-123456-TERMINAL-RECONCILE", kind="job_failure", job_id=123456,
        pattern="usb3_lfps_basic", scope="regression",
        title="LSF job 123456 reached EXIT (dv_analysis_status=ANALYSIS_OWED)",
        lsf_status="EXIT", dv_analysis_status="ANALYSIS_OWED",
        uvm_error_count=3, uvm_fatal_count=1, terminal_signature="UVM_FATAL_LFPS_TIMEOUT",
        seed="42", fsdb_path=None, failure_signature=_sample_failure_signature(),
        prior_related_knowledge=[{"memory_id": "MEM-ABC123", "score": 0.8}],
    )
    base.update(overrides)
    return base


# ---- schema / construction --------------------------------------------------

def test_default_db_path_is_under_dv_harness_evidence_dir(tmp_path):
    p = default_db_path(tmp_path)
    assert p == tmp_path / ".dv-harness" / "evidence" / "evidence.duckdb"


def test_store_construction_creates_db_file_and_is_idempotent(tmp_path):
    db_path = tmp_path / "sub" / "evidence.duckdb"
    s1 = EvidenceStore(db_path)
    s1.close()
    assert db_path.exists()
    # second construction against the same file must not raise / must not
    # clobber the schema
    s2 = EvidenceStore(db_path)
    s2.close()


# ---- read_only=True (2026-09-03 MCP read-only-boundary gap fix) ------------
# EvidenceStore's default (read-write) constructor above always mkdir()s the
# parent dir and runs the full CREATE TABLE/SEQUENCE IF NOT EXISTS schema --
# exactly what dv_harness/mcp/runtime.py's ReadOnlyMcpContext must NEVER do.
# These tests exercise the real `read_only=True` branch directly (below the
# MCP layer -- dv_harness_tests/test_mcp_read_only_boundary.py covers the
# same guarantee through ReadOnlyMcpContext end to end).

def test_read_only_true_against_missing_file_raises_without_creating_anything(tmp_path):
    missing_dir = tmp_path / "nested" / "does_not_exist"
    db_path = missing_dir / "evidence.duckdb"
    with pytest.raises(duckdb.IOException):
        EvidenceStore(db_path, read_only=True)
    assert not missing_dir.exists()
    assert not db_path.exists()


def test_read_only_true_against_existing_db_does_not_add_missing_tables(tmp_path):
    db_path = tmp_path / "evidence.duckdb"
    rw = EvidenceStore(db_path)  # creates the full real schema
    rw.close()

    def _table_count():
        conn = duckdb.connect(str(db_path), read_only=True)
        try:
            return len(conn.execute("SHOW TABLES").fetchall())
        finally:
            conn.close()

    before = _table_count()
    ro = EvidenceStore(db_path, read_only=True)
    ro.query("SELECT count(*) FROM regression_verdicts")
    ro.close()
    assert _table_count() == before


def test_read_only_true_blocks_ddl_and_dml(tmp_path):
    """Even setting `read_only=True` aside, DuckDB's own read-only
    connection refuses any write -- confirms this defense-in-depth layer
    (not just this class skipping the schema DDL) is real."""
    db_path = tmp_path / "evidence.duckdb"
    rw = EvidenceStore(db_path)
    rw.close()
    ro = EvidenceStore(db_path, read_only=True)
    try:
        with pytest.raises(duckdb.Error):
            ro._conn.execute("CREATE TABLE should_never_exist (id INTEGER)")
        with pytest.raises(duckdb.Error):
            ro.insert_regression_verdict("some_pattern", True, job_id=1)
    finally:
        ro.close()


# ---- jobs (JobState mirror) -------------------------------------------------

def test_insert_job_state_round_trips_real_jobstate_fields(store):
    state = _sample_job_state()
    store.insert_job_state(state)
    rows = store.query(
        "SELECT job_id, pattern, lsf_status, sim_status, uvm_error_count, "
        "uvm_fatal_count, assertion_failure, terminal_signature, seed FROM jobs"
    )
    assert rows == [(123456, "usb3_lfps_basic", "EXIT", "FAIL", 3, 1, True,
                      "UVM_FATAL_LFPS_TIMEOUT", "42")]


def test_insert_job_state_upserts_on_repeat_job_id(store):
    store.insert_job_state(_sample_job_state(sim_status="RUNNING", uvm_error_count=0))
    store.insert_job_state(_sample_job_state(sim_status="FAIL", uvm_error_count=3))
    rows = store.query("SELECT sim_status, uvm_error_count FROM jobs WHERE job_id = 123456")
    assert rows == [("FAIL", 3)]
    count = store.query("SELECT count(*) FROM jobs")[0][0]
    assert count == 1


def test_insert_job_state_requires_job_id(store):
    with pytest.raises(ValueError):
        store.insert_job_state(JobState(job_id=None, pattern="x"))


def test_insert_job_state_accepts_plain_dict_shape(store):
    """A caller may pass json.loads() of a real on-disk
    .dv-harness/lsf/jobs/<id>.json instead of a JobState instance."""
    store.insert_job_state({"job_id": 7, "pattern": "p7", "lsf_status": "DONE",
                             "sim_status": "PASS"})
    rows = store.query("SELECT job_id, pattern, lsf_status FROM jobs WHERE job_id = 7")
    assert rows == [(7, "p7", "DONE")]


# ---- job_memory_records (job_result/job_failure mirror) --------------------

def test_insert_job_memory_record_round_trips_job_failure_shape(store):
    store.insert_job_memory_record(_sample_job_failure_record())
    rows = store.query(
        "SELECT memory_id, kind, job_id, pattern, lsf_status, dv_analysis_status, "
        "uvm_error_count, uvm_fatal_count, seed FROM job_memory_records"
    )
    assert rows == [("JOB-123456-TERMINAL-RECONCILE", "job_failure", 123456,
                      "usb3_lfps_basic", "EXIT", "ANALYSIS_OWED", 3, 1, "42")]


def test_insert_job_memory_record_upserts_by_memory_id(store):
    """Mirrors MemoryStore.add()'s own upsert-by-memory_id semantics --
    lsf_client._upsert_job_tier_memory_record() relies on repeat reconciles
    of the SAME stuck job updating the SAME record, not duplicating rows."""
    store.insert_job_memory_record(_sample_job_failure_record(kind="job_result",
                                                                dv_analysis_status="ANALYSIS_OWED",
                                                                failure_signature=None))
    store.insert_job_memory_record(_sample_job_failure_record())  # better evidence arrives
    rows = store.query("SELECT kind FROM job_memory_records WHERE memory_id = 'JOB-123456-TERMINAL-RECONCILE'")
    assert rows == [("job_failure",)]
    count = store.query("SELECT count(*) FROM job_memory_records")[0][0]
    assert count == 1


def test_insert_job_memory_record_requires_memory_id(store):
    with pytest.raises(ValueError):
        store.insert_job_memory_record({"kind": "job_result", "job_id": 1})


def test_insert_job_memory_record_without_failure_signature_writes_no_failure_signature_row(store):
    store.insert_job_memory_record(_sample_job_failure_record(kind="job_result", failure_signature=None))
    rows = store.query("SELECT failure_signature_json FROM job_memory_records")
    assert rows == [(None,)]
    count = store.query("SELECT count(*) FROM failure_signatures")[0][0]
    assert count == 0


# ---- failure_signatures (build_failure_signature aggregation) --------------

def test_repeat_job_failure_with_same_signature_aggregates_occurrence_count(store):
    store.insert_job_memory_record(_sample_job_failure_record())
    store.insert_job_memory_record(_sample_job_failure_record(memory_id="JOB-999-TERMINAL-RECONCILE",
                                                                job_id=999))
    rows = store.query(
        "SELECT occurrence_count, pattern, abnormal_termination FROM failure_signatures"
    )
    assert rows == [(2, "usb3_lfps_basic", True)]


def test_different_failure_signatures_produce_distinct_rows(store):
    store.insert_job_memory_record(_sample_job_failure_record())
    store.insert_job_memory_record(_sample_job_failure_record(
        memory_id="JOB-999-TERMINAL-RECONCILE", job_id=999,
        failure_signature=_sample_failure_signature(symptom="different symptom",
                                                      terminal_signature="UVM_FATAL_OTHER"),
    ))
    count = store.query("SELECT count(*) FROM failure_signatures")[0][0]
    assert count == 2


def test_signature_key_is_stable_across_dict_key_order():
    a = _sample_failure_signature()
    b = dict(reversed(list(_sample_failure_signature().items())))
    assert signature_key(a) == signature_key(b)


# ---- regression_verdicts (regression.list mirror) --------------------------

def test_insert_regression_verdict_and_flip_to_fail(store):
    store.insert_regression_verdict("usb3_lfps_basic", True, job_id=1)
    store.insert_regression_verdict("usb3_lfps_basic", False, job_id=2)
    rows = store.query("SELECT pattern, verdict_passed, job_id FROM regression_verdicts")
    assert rows == [("usb3_lfps_basic", False, 2)]


def test_insert_regression_verdict_requires_pattern(store):
    with pytest.raises(ValueError):
        store.insert_regression_verdict("", True)


def test_regression_verdicts_matches_regression_list_manager_semantics(store):
    """Cross-check against the REAL flat-file record_verdict() logic this
    table is the queryable mirror of: a FAIL always evicts a stale PASS."""
    lines = record_verdict([], "patA", True)
    lines = record_verdict(lines, "patB", True)
    lines = record_verdict(lines, "patA", False)
    for pattern in ("patA", "patB"):
        passed = pattern in lines
        store.insert_regression_verdict(pattern, passed)
    rows = dict(store.query("SELECT pattern, verdict_passed FROM regression_verdicts"))
    assert rows == {"patA": False, "patB": True}


# ---- coverage_samples (parse_coverage_summary category mirror) -------------

def test_insert_coverage_sample_round_trips_real_category_shape(store):
    store.insert_coverage_sample(
        {"name": "fsm_state", "percent": 60.0, "bins_total": 10, "bins_hit": 6},
        timestamp="2026-09-03T10:00:00Z", source="urg_merge",
    )
    rows = store.query(
        "SELECT category_name, percent, bins_total, bins_hit, sample_timestamp, source "
        "FROM coverage_samples"
    )
    assert rows == [("fsm_state", 60.0, 10, 6, "2026-09-03T10:00:00Z", "urg_merge")]


def test_insert_coverage_sample_rejects_malformed_category(store):
    with pytest.raises(ValueError):
        store.insert_coverage_sample({"name": "branch", "percent": 80.0})


def test_insert_coverage_sample_appends_multiple_samples_over_time(store):
    store.insert_coverage_sample({"name": "line", "percent": 50.0, "bins_total": 10, "bins_hit": 5},
                                  timestamp=1)
    store.insert_coverage_sample({"name": "line", "percent": 70.0, "bins_total": 10, "bins_hit": 7},
                                  timestamp=2)
    rows = store.query("SELECT percent FROM coverage_samples ORDER BY sample_timestamp")
    assert rows == [(50.0,), (70.0,)]


# ---- traceability: rtl_modules/rtl_ports/rtl_signals/rtl_parameters -------

@requires_verible
def test_insert_rtl_parse_populates_all_traceability_tables(store, tmp_path):
    from dv_harness.verible_parser import parse_file, to_dict

    sv_path = tmp_path / "fifo_ctrl.sv"
    sv_path.write_text(FIFO_FIXTURE, encoding="utf-8")
    parsed = to_dict(parse_file(sv_path))

    module_ids = store.insert_rtl_parse(parsed)
    assert len(module_ids) == 1
    mid = module_ids[0]

    mod_rows = store.query("SELECT module_name, file_path, source_sha256 FROM rtl_modules WHERE id = ?", [mid])
    assert mod_rows == [("fifo_ctrl", str(sv_path), parsed["source_sha256"])]

    port_count = store.query("SELECT count(*) FROM rtl_ports WHERE module_id = ?", [mid])[0][0]
    assert port_count == 8

    signal_rows = store.query(
        "SELECT signal_name, unpacked_dims FROM rtl_signals WHERE module_id = ? ORDER BY signal_name", [mid]
    )
    assert ("mem", "[0:DEPTH-1]") in signal_rows

    param_rows = dict(store.query(
        "SELECT param_name, default_text FROM rtl_parameters WHERE module_id = ?", [mid]
    ))
    assert param_rows == {"DEPTH": "16", "WIDTH": "8"}


def test_insert_rtl_parse_on_empty_modules_list_inserts_nothing(store):
    module_ids = store.insert_rtl_parse({"file_path": "x.sv", "source_sha256": "abc",
                                          "verible_version": "v1", "modules": []})
    assert module_ids == []
    assert store.query("SELECT count(*) FROM rtl_modules")[0][0] == 0


# ---- normalized_evidence (vip_distill.py envelope mirror) ------------------
# (evidence-db-wiring step 2, 2026-09-03)

def _sample_normalized_evidence(**overrides):
    """A real envelope shape -- this is exactly what
    `vip_distill.distill_sim_log()` returns for a real epilogue-bearing
    sim.log (see test_vip_distill.py's own FAILING_LOG fixture), not an
    invented shape."""
    base = dict(
        schema_version="0.1.0-draft", evidence_id="EVID-abc123def456",
        source_kind="sim_log", job_id=123456, pattern="usb3_lfps_basic",
        run_dir="/proj/run/123456", verdict="FAILED",
        counts={"uvm_fatal": 1, "uvm_error": 2, "uvm_warning": 0},
        detail={"total_lines": 6, "epilogue": {"verdict": "FAILED"}, "signatures": []},
        provenance={"parser": "sim_log_analysis.parse_sim_log", "source_path": "/proj/run/123456/sim.log"},
        distilled_at=1234567890.5, distiller="vip_distill.py",
    )
    base.update(overrides)
    return base


def test_insert_normalized_evidence_round_trips_real_envelope_fields(store):
    store.insert_normalized_evidence(_sample_normalized_evidence())
    rows = store.query(
        "SELECT evidence_id, schema_version, source_kind, job_id, pattern, "
        "run_dir, verdict, distiller FROM normalized_evidence"
    )
    assert rows == [("EVID-abc123def456", "0.1.0-draft", "sim_log", 123456,
                      "usb3_lfps_basic", "/proj/run/123456", "FAILED", "vip_distill.py")]


def test_insert_normalized_evidence_stores_counts_detail_provenance_as_json(store):
    store.insert_normalized_evidence(_sample_normalized_evidence())
    counts_json, detail_json, provenance_json = store.query(
        "SELECT counts_json, detail_json, provenance_json FROM normalized_evidence"
    )[0]
    assert json.loads(counts_json) == {"uvm_fatal": 1, "uvm_error": 2, "uvm_warning": 0}
    assert json.loads(detail_json)["epilogue"]["verdict"] == "FAILED"
    assert json.loads(provenance_json)["parser"] == "sim_log_analysis.parse_sim_log"


def test_insert_normalized_evidence_upserts_by_evidence_id(store):
    """Mirrors vip_distill's own deterministic evidence_id: re-distilling
    and re-ingesting the SAME real evidence twice must update the same row,
    not duplicate it -- the identical idempotency convention
    insert_job_memory_record() already follows for memory_id."""
    store.insert_normalized_evidence(_sample_normalized_evidence(verdict="FAILED"))
    store.insert_normalized_evidence(_sample_normalized_evidence(verdict="PASSED"))
    rows = store.query("SELECT verdict FROM normalized_evidence WHERE evidence_id = 'EVID-abc123def456'")
    assert rows == [("PASSED",)]
    count = store.query("SELECT count(*) FROM normalized_evidence")[0][0]
    assert count == 1


def test_insert_normalized_evidence_requires_evidence_id(store):
    with pytest.raises(ValueError):
        store.insert_normalized_evidence({"source_kind": "sim_log"})


def test_insert_normalized_evidence_with_null_counts_stores_null_not_placeholder(store):
    """fsdbreport-sourced envelopes carry counts=None (no PASS/FAIL concept
    of their own, per vip_distill's own docstring) -- must round-trip as a
    real SQL NULL, never a JSON-encoded 'null' string masquerading as
    checked-but-unknown counts."""
    store.insert_normalized_evidence(_sample_normalized_evidence(
        evidence_id="EVID-fsdb000", source_kind="fsdbreport", verdict=None, counts=None))
    rows = store.query(
        "SELECT counts_json, verdict FROM normalized_evidence WHERE evidence_id = 'EVID-fsdb000'"
    )
    assert rows == [(None, None)]
