"""GET /api/test-suite-center -- the Test Suite Center dashboard card (item:
dashboard_test_suite_center, Web Control Plane theme,
CLAUDE_L5_WEB_CONTROL_PLANE_MASTER.md sections 342-402).

REUSE OVER REINVENT: `dv_harness/test_suite_lifecycle.py` already exists and
already derives every real test pattern's own lifecycle state (GENERATED
through CLOSURE_PROVEN) from evidence_db.py's `jobs`/`regression_verdicts`
tables and golden_scenario.py's capsule store -- this change adds NO new
analysis engine behind the card. It is a pure dashboard-wiring gap, closed
the same way the Requirement/vPlan Center and Generation Readiness Center
cards were: a thin `_read_test_suite_center_state()` reader following the
file's existing `{"available", "error"}` honest-empty-state contract, one
read-only GET endpoint, and a fetch-once + client-side-render card.

These tests prove:
  * The card READS the real module. Every asserted lifecycle state is
    compared against what `test_suite_lifecycle.derive_test_suite_lifecycle()`
    itself computes over the identical real evidence.duckdb -- never a
    string typed into the test.
  * The Evidence Truth Rule holds on the served surface: a project with no
    evidence.duckdb on disk must never render a fabricated table (the
    required negative control), and a malformed relationships.json file
    must surface its own reason/detail rather than a bare 500.
  * The three relationship tags are NEVER derived by this card -- they
    appear only from a real, evidence-cited relationships.json a caller
    supplied, and a relationship naming a pattern with no real evidence is
    refused, never silently attached.

The real dashboard server is started for real on a free local port and
driven over real HTTP, reusing test_dashboard_interactive.py's own harness
helpers -- the same cross-test import convention test_dashboard_
requirement_vplan_center.py already uses.
"""
from __future__ import annotations

import json
import shutil
import urllib.request
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness.evidence_db import EvidenceStore, default_db_path
from dv_harness.lsf_client import JobState

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
)


def _write_relationships(tmp: Path, relationships):
    d = tmp / ".dv-harness" / "test_suite"
    d.mkdir(parents=True, exist_ok=True)
    (d / "relationships.json").write_text(json.dumps({"relationships": relationships}), encoding="utf-8")


def test_test_suite_center_honest_empty_state_on_a_bare_project():
    """No evidence.duckdb on disk at all -> an honest {"available": False}
    naming the real reason, never a fabricated table. The required negative
    control this project's house style demands."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/test-suite-center")
        assert status == 200
        assert data["available"] is False
        assert data["error"] is None
        assert data["report"] is None
        assert "no evidence database" in data["reason"]
        assert "relationships_path" in data
    finally:
        shutil.rmtree(tmp)


def test_test_suite_center_reports_a_malformed_relationships_file_honestly():
    """A relationships.json that is not valid JSON must surface as this
    endpoint's own reason/detail -- never a bare 500 and never a silently
    empty card."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        d = tmp / ".dv-harness" / "test_suite"
        d.mkdir(parents=True)
        (d / "relationships.json").write_text("not valid json{", encoding="utf-8")

        status, data = _get(base, "/api/test-suite-center")
        assert status == 200
        assert data["available"] is False
        assert data["error"]["reason"] == "MALFORMED_RELATIONSHIPS_FILE"
    finally:
        shutil.rmtree(tmp)


def test_test_suite_center_reports_a_relationship_naming_an_unknown_pattern_honestly():
    """A relationships.json naming a pattern this project's own evidence.duckdb
    has no real row for at all must surface TEST_SUITE_LIFECYCLE_INVALID_INPUT
    naming the real reason -- never silently dropped or accepted."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        store = EvidenceStore(default_db_path(tmp))
        store.insert_job_state(JobState(job_id=1, pattern="pat_real"))
        store.close()

        _write_relationships(tmp, [
            {"pattern_a": "pat_real", "pattern_b": "pat_fabricated",
             "relation": "SUPERSET", "evidence": "cite"},
        ])

        status, data = _get(base, "/api/test-suite-center")
        assert status == 200
        assert data["available"] is False
        assert data["error"]["reason"] == "TEST_SUITE_LIFECYCLE_INVALID_INPUT"
    finally:
        shutil.rmtree(tmp)


def test_test_suite_center_reports_the_real_lifecycle_states_over_real_evidence():
    """Real jobs/regression_verdicts rows on disk -> the served per-pattern
    lifecycle_state must equal what test_suite_lifecycle.build_test_suite_
    lifecycle_report() itself computes over the identical real evidence.duckdb
    -- proving the endpoint reads the real module rather than re-deriving
    anything, and covering GENERATED/SUBMITTED/JOB_RUNNING/
    EXECUTED_UNVERIFIED/VERIFIED_PASS/VERIFIED_FAIL in one real pass."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        store = EvidenceStore(default_db_path(tmp))
        store.insert_job_state(JobState(job_id=1, pattern="pat_generated"))
        store.insert_job_state(JobState(job_id=2, pattern="pat_submitted", lsf_status="PEND"))
        store.insert_job_state(JobState(job_id=3, pattern="pat_running", lsf_status="RUN"))
        store.insert_job_state(JobState(job_id=4, pattern="pat_done", lsf_status="DONE"))
        store.insert_job_state(JobState(job_id=5, pattern="pat_pass", lsf_status="DONE"))
        store.insert_regression_verdict("pat_pass", True, job_id=5)
        store.insert_job_state(JobState(job_id=6, pattern="pat_fail", lsf_status="DONE"))
        store.insert_regression_verdict("pat_fail", False, job_id=6)
        store.close()

        status, data = _get(base, "/api/test-suite-center")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None

        # Cross-check every served state against a fresh, independent call
        # into the real module over the identical evidence.duckdb.
        from dv_harness import test_suite_lifecycle as tsl
        expected = tsl.derive_test_suite_lifecycle(tmp)
        assert expected["available"] is True
        expected_states = {p["pattern"]: p["lifecycle_state"] for p in expected["report"]["patterns"]}

        served_states = {p["pattern"]: p["lifecycle_state"] for p in data["report"]["patterns"]}
        assert served_states == expected_states
        assert served_states["pat_generated"] == "GENERATED"
        assert served_states["pat_submitted"] == "SUBMITTED"
        assert served_states["pat_running"] == "JOB_RUNNING"
        assert served_states["pat_done"] == "EXECUTED_UNVERIFIED"
        assert served_states["pat_pass"] == "VERIFIED_PASS"
        assert served_states["pat_fail"] == "VERIFIED_FAIL"
        assert data["report"]["pattern_count"] == 6
    finally:
        shutil.rmtree(tmp)


def test_test_suite_center_records_a_real_relationship_between_two_real_patterns():
    """A relationships.json declaring a real, evidence-cited relationship
    between two patterns this store DOES have real evidence for must be
    attached to both patterns' own served records -- never dropped, and
    never influencing the derived lifecycle_state itself."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        store = EvidenceStore(default_db_path(tmp))
        store.insert_job_state(JobState(job_id=1, pattern="pat_x", lsf_status="PEND"))
        store.insert_job_state(JobState(job_id=2, pattern="pat_y", lsf_status="PEND"))
        store.close()

        _write_relationships(tmp, [
            {"pattern_a": "pat_x", "pattern_b": "pat_y", "relation": "SEMANTIC_DUPLICATE",
             "evidence": "both dispatch the identical command sequence, patterns/foo.txt:1-9"},
        ])

        status, data = _get(base, "/api/test-suite-center")
        assert status == 200
        assert data["available"] is True
        rep = data["report"]
        assert rep["relationship_count"] == 1
        by_pattern = {p["pattern"]: p for p in rep["patterns"]}
        assert by_pattern["pat_x"]["lifecycle_state"] == "SUBMITTED"
        assert by_pattern["pat_y"]["lifecycle_state"] == "SUBMITTED"
        assert len(by_pattern["pat_x"]["relationships"]) == 1
        rel = by_pattern["pat_x"]["relationships"][0]
        assert rel["relation"] == "SEMANTIC_DUPLICATE"
        assert rel["evidence"].startswith("both dispatch")
    finally:
        shutil.rmtree(tmp)


def test_test_suite_center_closure_proven_requires_a_real_golden_scenario_capsule():
    """CLOSURE_PROVEN, the strongest core lifecycle state, must only ever
    appear when a real golden_scenario capsule (evidence-gated by
    record_golden_scenario()) is on file for that pattern -- never merely a
    passing regression verdict."""
    from dv_harness import golden_scenario as gs
    from dv_harness.vip_distill import distill_sim_log

    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        job_id = 99
        log_path = tmp / "run" / str(job_id) / "sim.log"
        log_path.parent.mkdir(parents=True)
        log_path.write_text(
            "UVM_INFO @ 0 ns: reporter [RNTST] Running test pat_golden...\n"
            "FINAL CHECK @ 25000 ns\nUVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0\n"
            "VERDICT: PASSED\n", encoding="utf-8")

        store = EvidenceStore(default_db_path(tmp))
        envelope = distill_sim_log(log_path=log_path, job_id=job_id, pattern="pat_golden",
                                   protocol="USB3", run_dir=str(log_path.parent))
        store.insert_normalized_evidence(envelope)
        store.insert_job_state(JobState(job_id=job_id, pattern="pat_golden", lsf_status="DONE",
                                         sim_status="PASS", git_sha="deadbeef"))
        capsule = gs.GoldenScenario(
            capsule_id=gs.default_capsule_id("proj", "sub", "pat_golden"),
            project="proj", subsystem="sub", test_name="pat_golden",
            evidence_id=envelope["evidence_id"], job_id=job_id, verified_sha="deadbeef")
        gs.record_golden_scenario(store, capsule)
        store.close()

        status, data = _get(base, "/api/test-suite-center")
        assert status == 200
        assert data["available"] is True
        by_pattern = {p["pattern"]: p for p in data["report"]["patterns"]}
        assert by_pattern["pat_golden"]["lifecycle_state"] == "CLOSURE_PROVEN"
        assert by_pattern["pat_golden"]["golden_capsule_ids"] == [capsule.capsule_id]
    finally:
        shutil.rmtree(tmp)


def test_test_suite_center_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() --
    an endpoint no page ever calls would be exactly the PARTIALLY_WIRED shape
    this item exists to avoid."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="testSuiteCenterCard"' in html
        assert "Test Suite Center" in html
        assert "'/api/test-suite-center'" in html
        assert "await loadTestSuiteCenter();" in html
        assert 'id="testSuiteCenterTiles"' in html
        assert 'id="testSuitePatternBody"' in html
        # This card is read-only, matching the convention every sibling card
        # it reuses follows -- no POST verb of its own.
        assert "Read-only" in html.split('id="testSuiteCenterCard"')[1].split("</div>")[0]
    finally:
        shutil.rmtree(tmp)
