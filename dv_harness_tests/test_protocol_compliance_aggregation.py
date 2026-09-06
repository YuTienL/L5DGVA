"""Tests for dv_harness/protocol_compliance_aggregation.py (2026-09-06).

Real machinery throughout: a REAL DuckDB `EvidenceStore` with this project's
real schema, and REAL `vip_distill.distill_sim_log()` envelopes produced from
synthetic sim.log text written in this project's own documented FINAL CHECK
epilogue format -- never a hand-typed dict shaped to look like one. The one
place a "protocol-checker verdict" appears is inside a normalized_evidence
row's own free-form `detail` dict, because (as this module's own docstring
verifies) no real distiller in this repo writes one -- so the checker-side
tests deliberately construct that row directly, the same way any future real
protocol-checker producer would, and say so.
"""
from __future__ import annotations

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness.evidence_db import EvidenceStore
from dv_harness.vip_distill import distill_sim_log
from dv_harness import protocol_compliance_aggregation as pca

PASSING_SIM_LOG = """\
UVM_INFO @ 0 ns: reporter [RNTST] Running test usb3_lfps_basic...
FINAL CHECK @ 25000 ns
UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0
VERDICT: PASSED
"""

FAILING_SIM_LOG = """\
UVM_ERROR @ 900 ns: uvm_test_top.env.usb3_agent [LFPS] handshake timeout
FINAL CHECK @ 25000 ns
UVM_FATAL = 0, UVM_ERROR = 1, UVM_WARNING = 0
VERDICT: FAILED
"""

JOB_ID = 424242
PATTERN = "usb3_lfps_basic"


# ---------------------------------------------------------------------------
# Pure aggregation-rule tests (no DB needed)
# ---------------------------------------------------------------------------


def test_scoreboard_pass_checker_pass_is_overall_pass():
    report = pca.aggregate_protocol_compliance("PASSED", "PASS")
    assert report["overall_status"] == pca.OVERALL_PASS
    assert report["scoreboard_status"] == pca.SCOREBOARD_PASS
    assert report["protocol_checker_status"] == pca.CHECKER_PASS


def test_headline_rule_scoreboard_pass_with_real_checker_violation_is_overall_fail():
    """The task's own headline rule: a scoreboard PASS must never silently
    outrank a real protocol-checker violation."""
    report = pca.aggregate_protocol_compliance("PASSED", "FAIL")
    assert report["overall_status"] == pca.OVERALL_FAIL
    assert report["scoreboard_status"] == pca.SCOREBOARD_PASS
    assert report["protocol_checker_status"] == pca.CHECKER_FAIL
    assert "protocol-checker violation" in report["reason"]


def test_scoreboard_fail_checker_pass_is_still_overall_fail():
    report = pca.aggregate_protocol_compliance("FAILED", "PASS")
    assert report["overall_status"] == pca.OVERALL_FAIL
    assert report["scoreboard_status"] == pca.SCOREBOARD_FAIL
    assert report["protocol_checker_status"] == pca.CHECKER_PASS


def test_scoreboard_fail_checker_fail_is_overall_fail():
    report = pca.aggregate_protocol_compliance("FAILED", "FAIL")
    assert report["overall_status"] == pca.OVERALL_FAIL


def test_absent_protocol_checker_evidence_reports_not_checked_never_clean():
    """Absent protocol-checker evidence must report NOT_CHECKED, distinct
    from CLEAN/PASS, and must never be silently assumed clean."""
    report = pca.aggregate_protocol_compliance("PASSED", None)
    assert report["protocol_checker_status"] == pca.CHECKER_NOT_CHECKED
    assert report["protocol_checker_status"] != pca.CHECKER_PASS
    # Overall can still be PASS on scoreboard evidence alone, but the report
    # must carry the NOT_CHECKED caveat rather than reading as a clean pass.
    assert report["overall_status"] == pca.OVERALL_PASS
    assert "NOT_CHECKED" in report["reason"] or "no protocol-checker evidence" in report["reason"]


def test_no_scoreboard_evidence_is_not_available_never_a_pass():
    """NEGATIVE CONTROL: absent scoreboard evidence must never read as a
    PASS just because nothing failed."""
    report = pca.aggregate_protocol_compliance(None, None)
    assert report["scoreboard_status"] == pca.SCOREBOARD_NOT_AVAILABLE
    assert report["overall_status"] == pca.OVERALL_NOT_AVAILABLE
    assert report["overall_status"] != pca.OVERALL_PASS


def test_no_scoreboard_evidence_but_real_checker_violation_is_still_overall_fail():
    """A real protocol-checker FAIL must win even when the scoreboard has
    nothing to say at all -- checker FAIL is checked before scoreboard
    availability."""
    report = pca.aggregate_protocol_compliance(None, "VIOLATION")
    assert report["overall_status"] == pca.OVERALL_FAIL
    assert report["scoreboard_status"] == pca.SCOREBOARD_NOT_AVAILABLE
    assert report["protocol_checker_status"] == pca.CHECKER_FAIL


def test_unrecognized_scoreboard_verdict_is_unknown_never_pass_or_fail():
    """NEGATIVE CONTROL: a real but unrecognized verdict string (e.g. an
    AMBIGUOUS scoreboard result) must never be silently treated as a clean
    PASS."""
    report = pca.aggregate_protocol_compliance("AMBIGUOUS", None)
    assert report["scoreboard_status"] == pca.SCOREBOARD_UNKNOWN
    assert report["overall_status"] == pca.OVERALL_UNKNOWN
    assert report["overall_status"] != pca.OVERALL_PASS


def test_unrecognized_checker_verdict_is_unknown_never_pass_or_clean():
    """NEGATIVE CONTROL: an unrecognized protocol-checker verdict string must
    never be silently rounded up to PASS, even though the scoreboard is
    clean."""
    report = pca.aggregate_protocol_compliance("PASSED", "PENDING")
    assert report["protocol_checker_status"] == pca.CHECKER_UNKNOWN
    assert report["overall_status"] == pca.OVERALL_UNKNOWN
    assert report["overall_status"] != pca.OVERALL_PASS


def test_evidence_ids_and_identity_are_carried_through_the_report():
    report = pca.aggregate_protocol_compliance(
        "PASSED", "FAIL", scoreboard_evidence_id="EVID-aaa", checker_evidence_id="EVID-bbb",
        job_id=JOB_ID, pattern=PATTERN)
    assert report["scoreboard_evidence_id"] == "EVID-aaa"
    assert report["protocol_checker_evidence_id"] == "EVID-bbb"
    assert report["job_id"] == JOB_ID
    assert report["pattern"] == PATTERN


# ---------------------------------------------------------------------------
# extract_verdicts_from_evidence_set(): duck-typed evidence-set reading
# ---------------------------------------------------------------------------


def test_extract_from_empty_evidence_set_is_all_absent():
    extracted = pca.extract_verdicts_from_evidence_set([])
    assert extracted["scoreboard_verdict"] is None
    assert extracted["protocol_checker_verdict"] is None
    report = pca.aggregate_stage_evidence_set([])
    assert report["overall_status"] == pca.OVERALL_NOT_AVAILABLE
    assert report["protocol_checker_status"] == pca.CHECKER_NOT_CHECKED


def test_extract_reads_scoreboard_from_sim_log_row_and_finds_no_checker():
    real_envelope = distill_sim_log(log_text=PASSING_SIM_LOG, job_id=JOB_ID, pattern=PATTERN)
    extracted = pca.extract_verdicts_from_evidence_set([real_envelope])
    assert extracted["scoreboard_verdict"] == "PASSED"
    assert extracted["scoreboard_evidence_id"] == real_envelope["evidence_id"]
    # No real protocol-checker producer exists in this repo (see module
    # docstring) -- a real vip_distill envelope never carries this key.
    assert extracted["protocol_checker_verdict"] is None
    report = pca.aggregate_stage_evidence_set([real_envelope])
    assert report["overall_status"] == pca.OVERALL_PASS
    assert report["protocol_checker_status"] == pca.CHECKER_NOT_CHECKED


def test_fsdbreport_rows_never_contribute_a_scoreboard_verdict():
    """NEGATIVE CONTROL: fsdbreport evidence has no verdict concept
    (source_kind not in SCOREBOARD_SOURCE_KINDS) -- even a row that somehow
    carries a stray non-null verdict must not be picked up as scoreboard
    evidence."""
    fake_fsdb_row = {
        "evidence_id": "EVID-fsdb", "source_kind": "fsdbreport",
        "verdict": "PASSED",  # would never really happen; proves the filter
        "detail": {},
    }
    extracted = pca.extract_verdicts_from_evidence_set([fake_fsdb_row])
    assert extracted["scoreboard_verdict"] is None


def test_extraction_pipeline_honors_the_headline_rule_end_to_end():
    """Runs the full extract-then-aggregate pipeline over a real scoreboard
    PASS row plus a second row carrying a real-shaped (if hypothetical)
    protocol-checker violation in its own `detail` dict -- the documented
    extension point -- and proves the same evidence set still aggregates to
    an overall FAIL."""
    real_scoreboard_row = distill_sim_log(log_text=PASSING_SIM_LOG, job_id=JOB_ID, pattern=PATTERN)
    checker_row = {
        "evidence_id": "EVID-checker-1", "source_kind": "combined",
        "job_id": JOB_ID, "pattern": PATTERN, "verdict": None,
        "detail": {"protocol_checker_verdict": "VIOLATION"},
    }
    report = pca.aggregate_stage_evidence_set(
        [real_scoreboard_row, checker_row], job_id=JOB_ID, pattern=PATTERN)
    assert report["scoreboard_status"] == pca.SCOREBOARD_PASS
    assert report["protocol_checker_status"] == pca.CHECKER_FAIL
    assert report["overall_status"] == pca.OVERALL_FAIL


# ---------------------------------------------------------------------------
# load_normalized_evidence_rows() / aggregate_from_evidence_db(): real DuckDB
# ---------------------------------------------------------------------------


@pytest.fixture()
def evidence_db_path(tmp_path):
    return tmp_path / "evidence" / "evidence.duckdb"


def test_load_normalized_evidence_rows_requires_a_scope(evidence_db_path):
    with pytest.raises(pca.ProtocolComplianceError):
        pca.load_normalized_evidence_rows(evidence_db_path)


def test_real_db_round_trip_scoreboard_pass_with_no_checker_evidence(evidence_db_path):
    real_envelope = distill_sim_log(log_text=PASSING_SIM_LOG, job_id=JOB_ID, pattern=PATTERN)
    store = EvidenceStore(evidence_db_path)
    try:
        store.insert_normalized_evidence(real_envelope)
    finally:
        store.close()

    rows = pca.load_normalized_evidence_rows(evidence_db_path, job_id=JOB_ID)
    assert len(rows) == 1
    row = rows[0]
    assert row["verdict"] == "PASSED"
    assert row["source_kind"] == "sim_log"
    assert isinstance(row["detail"], dict)
    assert row["detail"]["epilogue"]["verdict"] == "PASSED"

    report = pca.aggregate_from_evidence_db(evidence_db_path, job_id=JOB_ID)
    assert report["overall_status"] == pca.OVERALL_PASS
    assert report["protocol_checker_status"] == pca.CHECKER_NOT_CHECKED
    assert report["scoreboard_evidence_id"] == real_envelope["evidence_id"]


def test_real_db_headline_rule_scoreboard_pass_plus_real_checker_violation_same_job(evidence_db_path):
    """The central proof: TWO real rows recorded in the SAME real evidence
    database, for the SAME job_id (the same evidence set) -- one a real
    `vip_distill.distill_sim_log()` scoreboard PASS, the other a
    protocol-checker-shaped row (this repo's honest extension point, since
    no real checker producer exists yet) reporting a real violation -- and
    the aggregation reads back out of that real database as an overall
    FAIL, never a silent PASS."""
    real_envelope = distill_sim_log(log_text=PASSING_SIM_LOG, job_id=JOB_ID, pattern=PATTERN)
    checker_envelope = {
        "evidence_id": "EVID-real-checker-1", "schema_version": "0.1.0-draft",
        "source_kind": "combined", "job_id": JOB_ID, "pattern": PATTERN,
        "protocol": "usb3", "run_dir": None, "verdict": None,
        "counts": None,
        "detail": {"protocol_checker_verdict": "VIOLATION",
                   "note": "synthetic stand-in for a future real checker distiller"},
        "distilled_at": 0.0, "distiller": "test-fixture",
    }
    store = EvidenceStore(evidence_db_path)
    try:
        store.insert_normalized_evidence(real_envelope)
        store.insert_normalized_evidence(checker_envelope)
    finally:
        store.close()

    report = pca.aggregate_from_evidence_db(evidence_db_path, job_id=JOB_ID)
    assert report["scoreboard_status"] == pca.SCOREBOARD_PASS
    assert report["protocol_checker_status"] == pca.CHECKER_FAIL
    assert report["overall_status"] == pca.OVERALL_FAIL
    assert report["protocol_checker_evidence_id"] == "EVID-real-checker-1"


def test_real_db_with_only_a_failing_scoreboard_and_no_checker_evidence(evidence_db_path):
    real_envelope = distill_sim_log(log_text=FAILING_SIM_LOG, job_id=JOB_ID, pattern=PATTERN)
    store = EvidenceStore(evidence_db_path)
    try:
        store.insert_normalized_evidence(real_envelope)
    finally:
        store.close()

    report = pca.aggregate_from_evidence_db(evidence_db_path, job_id=JOB_ID)
    assert report["scoreboard_status"] == pca.SCOREBOARD_FAIL
    assert report["protocol_checker_status"] == pca.CHECKER_NOT_CHECKED
    assert report["overall_status"] == pca.OVERALL_FAIL


def test_real_db_scoped_by_pattern_ignores_unrelated_jobs(evidence_db_path):
    """A second, unrelated job's evidence (a different pattern) must never
    bleed into this evidence set's aggregation."""
    this_job = distill_sim_log(log_text=PASSING_SIM_LOG, job_id=JOB_ID, pattern=PATTERN)
    other_job_checker_row = {
        "evidence_id": "EVID-other-job-checker", "source_kind": "combined",
        "job_id": 999999, "pattern": "some_other_pattern", "verdict": None,
        "detail": {"protocol_checker_verdict": "VIOLATION"},
    }
    store = EvidenceStore(evidence_db_path)
    try:
        store.insert_normalized_evidence(this_job)
        store.insert_normalized_evidence(other_job_checker_row)
    finally:
        store.close()

    report = pca.aggregate_from_evidence_db(evidence_db_path, job_id=JOB_ID)
    assert report["protocol_checker_status"] == pca.CHECKER_NOT_CHECKED
    assert report["overall_status"] == pca.OVERALL_PASS


def test_empty_database_reports_not_available(evidence_db_path):
    store = EvidenceStore(evidence_db_path)
    store.close()
    report = pca.aggregate_from_evidence_db(evidence_db_path, job_id=JOB_ID)
    assert report["overall_status"] == pca.OVERALL_NOT_AVAILABLE
    assert report["scoreboard_status"] == pca.SCOREBOARD_NOT_AVAILABLE
    assert report["protocol_checker_status"] == pca.CHECKER_NOT_CHECKED
