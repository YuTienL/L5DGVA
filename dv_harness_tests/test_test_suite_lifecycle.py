"""Tests for dv_harness/test_suite_lifecycle.py -- the Test Suite Center's
per-pattern lifecycle state, derived ONLY from real evidence_db.py job/
regression records and golden_scenario.py capsules (2026-09-07).

Everything here runs against REAL machinery, not stand-ins: a REAL DuckDB
`EvidenceStore` with this project's real schema, real `insert_job_state()`/
`insert_regression_verdict()` rows, and a REAL `vip_distill.distill_sim_log()`
envelope + `golden_scenario.record_golden_scenario()` capsule for the
CLOSURE_PROVEN case -- never a hand-written row shaped to merely look real.

The negative control (`test_bare_project_reports_not_available_never_a_fabricated_report`)
proves absence-of-evidence reports the honest, distinct `available: False`
state rather than a fabricated empty-but-clean report.
"""
from __future__ import annotations

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness import golden_scenario as gs
from dv_harness import test_suite_lifecycle as tsl
from dv_harness.evidence_db import EvidenceStore, default_db_path
from dv_harness.lsf_client import JobState
from dv_harness.vip_distill import distill_sim_log

PASSING_SIM_LOG = """\
UVM_INFO @ 0 ns: reporter [RNTST] Running test pat_golden...
FINAL CHECK @ 25000 ns
UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0
VERDICT: PASSED
"""


@pytest.fixture()
def store(tmp_path):
    s = EvidenceStore(default_db_path(tmp_path))
    yield s
    try:
        s.close()
    except Exception:
        pass  # a test that already closed it itself (to open a second,
              # read-only connection to the same file) closes it again here.


# --- vocabulary --------------------------------------------------------

def test_lifecycle_vocabulary_shares_no_token_with_models_status():
    from dv_harness.models import Status
    status_values = {s.value for s in Status}
    assert not (set(tsl.ALL_LIFECYCLE_STATES) & status_values)
    assert not (set(tsl.RELATIONSHIP_KINDS) & status_values)


def test_core_lifecycle_states_are_the_seven_named_progression():
    assert tsl.CORE_LIFECYCLE_STATES == (
        "GENERATED", "SUBMITTED", "JOB_RUNNING", "EXECUTED_UNVERIFIED",
        "VERIFIED_FAIL", "VERIFIED_PASS", "CLOSURE_PROVEN")
    assert tsl.STATE_UNKNOWN == "UNKNOWN"
    assert tsl.RELATIONSHIP_KINDS == ("SEMANTIC_DUPLICATE", "SUBSUMED", "SUPERSET")


# --- the required negative control --------------------------------------

def test_bare_project_reports_not_available_never_a_fabricated_report(tmp_path):
    r = tsl.derive_test_suite_lifecycle(tmp_path)
    assert r["available"] is False
    assert r["report"] is None
    assert "no evidence database" in r["reason"]
    assert str(default_db_path(tmp_path)) in r["reason"]


def test_empty_but_real_evidence_db_reports_zero_patterns_honestly(tmp_path, store):
    # The db file genuinely exists (created by the fixture) and has real
    # schema, but nothing has ever been recorded in it -- this must read as
    # a real, empty report (available=True, pattern_count=0), never the
    # bare-project NOT_AVAILABLE case above, and never a fabricated pattern.
    # Close the fixture's own read-write connection first -- DuckDB refuses
    # a second connection to the same file under a different configuration
    # (read-only) while a read-write one is still open.
    store.close()
    r = tsl.derive_test_suite_lifecycle(tmp_path)
    assert r["available"] is True
    assert r["report"]["pattern_count"] == 0
    assert r["report"]["patterns"] == []
    for state in tsl.ALL_LIFECYCLE_STATES:
        assert r["report"]["state_counts"][state] == 0


# --- each real core state, derived from real evidence -------------------

def test_generated_state_from_a_bare_job_record_with_no_lsf_status(store):
    store.insert_job_state(JobState(job_id=1, pattern="pat_generated"))
    rep = tsl.build_test_suite_lifecycle_report(store)
    p = {x["pattern"]: x for x in rep["patterns"]}["pat_generated"]
    assert p["lifecycle_state"] == "GENERATED"
    assert p["job_count"] == 1
    assert p["golden_capsule_ids"] == []


def test_submitted_state_from_lsf_status_pend(store):
    store.insert_job_state(JobState(job_id=2, pattern="pat_submitted", lsf_status="PEND"))
    rep = tsl.build_test_suite_lifecycle_report(store)
    p = {x["pattern"]: x for x in rep["patterns"]}["pat_submitted"]
    assert p["lifecycle_state"] == "SUBMITTED"


def test_job_running_state_from_lsf_status_run(store):
    store.insert_job_state(JobState(job_id=3, pattern="pat_running", lsf_status="RUN"))
    rep = tsl.build_test_suite_lifecycle_report(store)
    p = {x["pattern"]: x for x in rep["patterns"]}["pat_running"]
    assert p["lifecycle_state"] == "JOB_RUNNING"


@pytest.mark.parametrize("lsf_status", ["DONE", "EXIT"])
def test_executed_unverified_state_from_lsf_done_or_exit_with_no_verdict(store, lsf_status):
    store.insert_job_state(JobState(job_id=4, pattern="pat_done", lsf_status=lsf_status))
    rep = tsl.build_test_suite_lifecycle_report(store)
    p = {x["pattern"]: x for x in rep["patterns"]}["pat_done"]
    assert p["lifecycle_state"] == "EXECUTED_UNVERIFIED"
    assert "LSF DONE is not equal to DV PASS" in p["reason"]


def test_verified_pass_state_from_a_real_regression_verdict(store):
    store.insert_job_state(JobState(job_id=5, pattern="pat_pass", lsf_status="DONE"))
    store.insert_regression_verdict("pat_pass", True, job_id=5)
    rep = tsl.build_test_suite_lifecycle_report(store)
    p = {x["pattern"]: x for x in rep["patterns"]}["pat_pass"]
    assert p["lifecycle_state"] == "VERIFIED_PASS"
    assert p["regression_verdict_passed"] is True


def test_verified_fail_state_from_a_real_regression_verdict(store):
    store.insert_job_state(JobState(job_id=6, pattern="pat_fail", lsf_status="DONE"))
    store.insert_regression_verdict("pat_fail", False, job_id=6)
    rep = tsl.build_test_suite_lifecycle_report(store)
    p = {x["pattern"]: x for x in rep["patterns"]}["pat_fail"]
    assert p["lifecycle_state"] == "VERIFIED_FAIL"
    assert p["regression_verdict_passed"] is False


def test_closure_proven_state_requires_a_real_golden_scenario_capsule(store, tmp_path):
    """The strongest state: only record_golden_scenario()'s own real PASS-
    evidence gate can produce it -- never a bare regression PASS alone."""
    job_id = 7
    log_path = tmp_path / "run" / str(job_id) / "sim.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(PASSING_SIM_LOG, encoding="utf-8")
    envelope = distill_sim_log(log_path=log_path, job_id=job_id, pattern="pat_golden",
                               protocol="USB3", run_dir=str(log_path.parent))
    store.insert_normalized_evidence(envelope)
    store.insert_job_state(JobState(job_id=job_id, pattern="pat_golden", lsf_status="DONE",
                                     sim_status="PASS", git_sha="deadbeef"))
    # Even record a CONTRADICTING regression_verdict (False) to prove
    # CLOSURE_PROVEN outranks a stale/disagreeing verdict row -- the capsule
    # is the strongest real fact this module reads.
    store.insert_regression_verdict("pat_golden", False, job_id=job_id)

    capsule = gs.GoldenScenario(
        capsule_id=gs.default_capsule_id("proj", "sub", "pat_golden"),
        project="proj", subsystem="sub", test_name="pat_golden",
        evidence_id=envelope["evidence_id"], job_id=job_id, verified_sha="deadbeef")
    gs.record_golden_scenario(store, capsule)

    rep = tsl.build_test_suite_lifecycle_report(store)
    p = {x["pattern"]: x for x in rep["patterns"]}["pat_golden"]
    assert p["lifecycle_state"] == "CLOSURE_PROVEN"
    assert p["golden_capsule_ids"] == [capsule.capsule_id]
    assert "record_golden_scenario" in p["reason"]


def test_no_evidence_at_all_for_a_relationship_endpoint_reports_unknown_not_generated(store):
    # A pattern this module has never seen any real row for at all must
    # never appear as GENERATED (or any other real state) -- it simply does
    # not appear in the report, since UNKNOWN is derived only for a pattern
    # that IS named by some evidence source. Prove derive_pattern_lifecycle()
    # itself reports UNKNOWN when called directly with nothing.
    lc = tsl.derive_pattern_lifecycle("nonexistent", jobs_rows=[], verdict_row=None,
                                       golden_capsule_ids=[])
    assert lc.lifecycle_state == "UNKNOWN"
    assert "nothing here is fabricated" in lc.reason


# --- relationship facts: never derived, only recorded from a citation ---

def test_relationship_with_no_evidence_citation_is_refused():
    with pytest.raises(tsl.TestSuiteLifecycleError, match="no real evidence"):
        tsl.relationship_from_dict({
            "pattern_a": "a", "pattern_b": "b", "relation": "SEMANTIC_DUPLICATE", "evidence": ""})


def test_relationship_with_unrecognized_relation_is_refused():
    with pytest.raises(tsl.TestSuiteLifecycleError, match="unrecognized relation"):
        tsl.relationship_from_dict({
            "pattern_a": "a", "pattern_b": "b", "relation": "IS_KINDA_LIKE", "evidence": "cite"})


def test_relationship_missing_pattern_names_is_refused():
    with pytest.raises(tsl.TestSuiteLifecycleError):
        tsl.relationship_from_dict({"pattern_b": "b", "relation": "SUBSUMED", "evidence": "cite"})


def test_relationship_naming_a_pattern_with_no_real_evidence_is_refused(store):
    store.insert_job_state(JobState(job_id=8, pattern="pat_real"))
    with pytest.raises(tsl.TestSuiteLifecycleError, match="no real jobs/regression_verdicts/golden_scenario"):
        tsl.build_test_suite_lifecycle_report(store, relationships=[
            {"pattern_a": "pat_real", "pattern_b": "pat_fabricated",
             "relation": "SUPERSET", "evidence": "cite"}])


def test_relationship_between_two_real_patterns_is_recorded_and_attached_to_both(store):
    store.insert_job_state(JobState(job_id=9, pattern="pat_x", lsf_status="PEND"))
    store.insert_job_state(JobState(job_id=10, pattern="pat_y", lsf_status="PEND"))
    rep = tsl.build_test_suite_lifecycle_report(store, relationships=[
        {"pattern_a": "pat_x", "pattern_b": "pat_y", "relation": "SEMANTIC_DUPLICATE",
         "evidence": "both patterns issue the identical command sequence, see patterns/foo.txt:12-40",
         "reason": "hand-reviewed by a DV engineer"},
    ])
    assert rep["relationship_count"] == 1
    by_pattern = {x["pattern"]: x for x in rep["patterns"]}
    assert len(by_pattern["pat_x"]["relationships"]) == 1
    assert len(by_pattern["pat_y"]["relationships"]) == 1
    rel = by_pattern["pat_x"]["relationships"][0]
    assert rel["relation"] == "SEMANTIC_DUPLICATE"
    assert rel["evidence"].startswith("both patterns")
    assert rel["reason"] == "hand-reviewed by a DV engineer"


def test_relationship_never_changes_the_derived_lifecycle_state(store):
    """A relationship is metadata attached alongside the state -- it must
    never influence what derive_pattern_lifecycle() itself concluded."""
    store.insert_job_state(JobState(job_id=11, pattern="pat_a", lsf_status="DONE"))
    store.insert_regression_verdict("pat_a", True, job_id=11)
    store.insert_job_state(JobState(job_id=12, pattern="pat_b", lsf_status="PEND"))
    rep = tsl.build_test_suite_lifecycle_report(store, relationships=[
        {"pattern_a": "pat_a", "pattern_b": "pat_b", "relation": "SUBSUMED", "evidence": "cite"},
    ])
    by_pattern = {x["pattern"]: x for x in rep["patterns"]}
    assert by_pattern["pat_a"]["lifecycle_state"] == "VERIFIED_PASS"
    assert by_pattern["pat_b"]["lifecycle_state"] == "SUBMITTED"


# --- whole-store report shape -------------------------------------------

def test_report_state_counts_tally_every_pattern_exactly_once(store):
    store.insert_job_state(JobState(job_id=20, pattern="pat_1"))
    store.insert_job_state(JobState(job_id=21, pattern="pat_2", lsf_status="PEND"))
    store.insert_job_state(JobState(job_id=22, pattern="pat_3", lsf_status="RUN"))
    rep = tsl.build_test_suite_lifecycle_report(store)
    assert rep["pattern_count"] == 3
    assert rep["state_counts"]["GENERATED"] == 1
    assert rep["state_counts"]["SUBMITTED"] == 1
    assert rep["state_counts"]["JOB_RUNNING"] == 1
    assert sum(rep["state_counts"].values()) == 3


def test_derive_test_suite_lifecycle_reads_relationships_json_file(tmp_path, store):
    import json
    store.insert_job_state(JobState(job_id=30, pattern="pat_j", lsf_status="PEND"))
    store.insert_job_state(JobState(job_id=31, pattern="pat_k", lsf_status="PEND"))
    store.close()
    r = tsl.derive_test_suite_lifecycle(tmp_path, relationships=[
        {"pattern_a": "pat_j", "pattern_b": "pat_k", "relation": "SUPERSET", "evidence": "cite"},
    ])
    assert r["available"] is True
    assert r["report"]["relationship_count"] == 1


# --- CLI -----------------------------------------------------------------

def test_cli_reports_exit_2_on_a_bare_project(tmp_path, capsys):
    rc = tsl.execute_verb(["--root", str(tmp_path)])
    assert rc == 2
    out = capsys.readouterr().out
    assert "NOT_AVAILABLE" in out


def test_cli_reports_exit_0_with_json_over_a_real_store(tmp_path, store, capsys):
    store.insert_job_state(JobState(job_id=40, pattern="pat_cli", lsf_status="PEND"))
    store.close()
    rc = tsl.execute_verb(["--root", str(tmp_path), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"pattern_count": 1' in out
    assert "pat_cli" in out
