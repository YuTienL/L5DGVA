"""Tests for dv_harness/verification_knowledge_graph.py -- the Verification
Knowledge Graph (sections 117-118). Exercises the REAL ingestion path against
a real `evidence_db.EvidenceStore` (DuckDB, no mock connection), real
`requirement_contract.py`-shaped records, and a real `memory.MemoryStore`
(no mock store) -- matching test_evidence_db.py's own "never mock the real
producer" discipline. Every positive-linking assertion is paired with a
negative control proving the module refuses to fabricate a node/edge when
the real join key is genuinely absent.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness.evidence_db import EvidenceStore
from dv_harness.memory import MemoryStore
from dv_harness.verification_knowledge_graph import (
    VerificationKnowledgeGraph,
    VerificationKnowledgeGraphError,
    build_verification_knowledge_graph,
    coverage_node_id,
    requirement_node_id,
    root_cause_node_id,
    test_node_id as make_test_node_id,
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = EvidenceStore(tmp_path / "evidence.duckdb")
    yield s
    s.close()


def clean_requirement(**over):
    """A fully-populated, internally coherent COMPLETE requirement_contract
    record (mirrors test_requirement_contract.py's own clean_record())."""
    r = {
        "contract_schema_version": "1.0",
        "requirement_id": "REQ-USB-LPM-001",
        "source": {"document": "usb2_spec.pdf", "locator": "section 7.2.3",
                   "quote": "The device shall enter L1 within tL1Entry."},
        "feature": "LPM L1 entry",
        "protocol": "USB2",
        "configuration": "HS, LPM enabled",
        "precondition": "device configured, link in U0",
        "stimulus": "host issues an LPM EXT token with HIRD=3",
        "expected_result": "device ACKs and enters L1 within tL1Entry",
        "observability": "utmi_suspend_o asserted; VIP LPM callback",
        "checker": "scoreboard compares observed L1 entry latency against tL1Entry",
        "coverage_intent": "cover HIRD 0..15 crossed with BESL",
        "priority": "P0",
        "criticality": "BLOCKER",
        "confidence": "HIGH",
        "status": "COMPLETE",
    }
    r.update(over)
    return r


def _golden_scenario(**over):
    base = dict(
        capsule_id="CAP-USB-001", project="proj", subsystem="usb", protocol="USB2",
        test_name="usb2_lpm_l1_basic", sequence_name="usb2_lpm_seq", seed="1",
        expected_result="PASS", evidence_id="EVID-abc123", job_id=42,
        verified_sha="deadbeef", verified_at="2026-09-06T00:00:00Z",
        requirements=["REQ-USB-LPM-001"], vip_versions={}, configuration={},
        command_txt_inputs=[], known_limitations=[], watched_paths=[],
    )
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# Requirement-record ingestion (requirement_contract.py integration)
# ---------------------------------------------------------------------------

def test_requirement_only_graph_creates_requirement_node_with_derived_status():
    g = build_verification_knowledge_graph(requirement_records=[clean_requirement()])
    node = g.node(requirement_node_id("REQ-USB-LPM-001"))
    assert node is not None
    assert node["kind"] == "REQUIREMENT"
    assert node["attrs"]["derived_status"] == "COMPLETE"
    assert node["attrs"]["contract_available"] is True
    assert g.sources_used == {"evidence_store": False, "requirement_records": True,
                               "memory_store": False}


def test_requirement_node_carries_real_derived_status_even_when_declared_status_overclaims():
    # status field lies (declares COMPLETE) while checker is a TBD sentinel --
    # derive_status() must re-derive PARTIAL from the real content, not trust
    # the caller's own claim (the Evidence Truth Rule, applied to this graph).
    bad = clean_requirement(checker="TBD", status="COMPLETE")
    g = build_verification_knowledge_graph(requirement_records=[bad])
    node = g.node(requirement_node_id("REQ-USB-LPM-001"))
    assert node["attrs"]["declared_status"] == "COMPLETE"
    assert node["attrs"]["derived_status"] == "PARTIAL"


def test_malformed_requirement_record_rejected_not_silently_skipped():
    """Negative control: a record that does not declare_contract_shape()
    must raise, never silently vanish from the graph."""
    with pytest.raises(VerificationKnowledgeGraphError, match="declare_contract_shape"):
        build_verification_knowledge_graph(requirement_records=[{"feature": "no shape marker"}])


def test_requirement_record_missing_requirement_id_rejected():
    bad = clean_requirement()
    del bad["requirement_id"]
    with pytest.raises(VerificationKnowledgeGraphError, match="requirement_id"):
        build_verification_knowledge_graph(requirement_records=[bad])


def test_traceability_gap_report_not_applicable_with_no_requirements():
    g = build_verification_knowledge_graph()
    assert g.traceability_gap_report() == {
        "status": "NOT_APPLICABLE",
        "reason": "no requirement_contract-shaped records were supplied to the builder",
    }


def test_traceability_gap_report_gaps_present_with_no_evidence_store():
    """Negative control: a requirement with real content but NO golden_scenario
    ever citing it must be reported as a gap, never a fabricated FULLY_TRACED."""
    g = build_verification_knowledge_graph(requirement_records=[clean_requirement()])
    report = g.traceability_gap_report()
    assert report["status"] == "GAPS_PRESENT"
    assert report["unverified_requirement_ids"] == ["REQ-USB-LPM-001"]


# ---------------------------------------------------------------------------
# evidence_db integration: golden_scenarios -> VERIFIES edges
# ---------------------------------------------------------------------------

def test_golden_scenario_creates_real_verifies_edge_between_real_test_and_requirement(store):
    store.insert_golden_scenario(_golden_scenario())
    g = build_verification_knowledge_graph(
        evidence_store=store, requirement_records=[clean_requirement()])
    tid = make_test_node_id("usb2_lpm_l1_basic")
    rid = requirement_node_id("REQ-USB-LPM-001")
    assert g.node(tid)["kind"] == "TEST"
    assert rid in g.requirements_verified_by_test("usb2_lpm_l1_basic")
    assert tid in g.tests_verifying_requirement("REQ-USB-LPM-001")
    assert g.traceability_gap_report()["status"] == "FULLY_TRACED"


def test_worst_wins_gap_report_over_two_requirements_one_unverified(store):
    store.insert_golden_scenario(_golden_scenario())
    g = build_verification_knowledge_graph(
        evidence_store=store,
        requirement_records=[clean_requirement(),
                              clean_requirement(requirement_id="REQ-USB-LPM-002",
                                                 feature="a different, unverified feature")])
    report = g.traceability_gap_report()
    assert report["status"] == "GAPS_PRESENT"
    assert report["unverified_requirement_ids"] == ["REQ-USB-LPM-002"]


def test_golden_scenario_referencing_unsupplied_requirement_yields_honest_stub_node(store):
    """A capsule can cite a requirement id the caller never supplied a
    requirement_contract record for. Real evidence of the reference is kept
    (the edge exists), but the node is honestly marked contract_available=False
    rather than fabricating the missing contract content."""
    store.insert_golden_scenario(_golden_scenario(requirements=["REQ-NEVER-SUPPLIED"]))
    g = build_verification_knowledge_graph(evidence_store=store)
    node = g.node(requirement_node_id("REQ-NEVER-SUPPLIED"))
    assert node["attrs"]["contract_available"] is False
    assert "derived_status" not in node["attrs"]


def test_golden_scenarios_table_absent_is_honest_note_not_crash(store):
    """Negative control: a stale evidence.duckdb predating this table (or any
    table this module reads) must not crash -- it must report the honest
    absence."""
    store._conn.execute("DROP TABLE golden_scenarios")
    g = build_verification_knowledge_graph(evidence_store=store)
    assert any("golden_scenarios table not present" in n for n in g.notes)
    assert g.nodes("TEST") == []


# ---------------------------------------------------------------------------
# evidence_db integration: failure_signatures -> ROOT_CAUSE / HAS_ROOT_CAUSE
# ---------------------------------------------------------------------------

def _job_failure_record(**over):
    base = dict(memory_id="JOB-1-TERMINAL-RECONCILE", kind="job_failure", job_id=1,
                pattern="usb2_lpm_l1_basic", scope="regression", title="t",
                lsf_status="EXIT", dv_analysis_status="ANALYSIS_OWED",
                uvm_error_count=3, uvm_fatal_count=1, terminal_signature="UVM_FATAL_X",
                seed="1", fsdb_path=None,
                failure_signature=dict(protocol="USB2", pattern="usb2_lpm_l1_basic",
                                        symptom="LPM timeout", root_cause_hint=None,
                                        uvm_error_count=3, uvm_fatal_count=1,
                                        assertion_failure=True, simulator_crash=False,
                                        terminal_signature="UVM_FATAL_X", lsf_status="EXIT",
                                        abnormal_termination=True, extra_text=""))
    base.update(over)
    return base


def test_failure_signature_with_root_cause_creates_real_root_cause_edge(store):
    rec = _job_failure_record()
    rec["failure_signature"]["root_cause_hint"] = "LPM timer misconfigured for HIRD=3"
    store.insert_job_memory_record(rec)
    g = build_verification_knowledge_graph(evidence_store=store)
    tid = make_test_node_id("usb2_lpm_l1_basic")
    rcid = root_cause_node_id("USB2", "LPM timer misconfigured for HIRD=3")
    assert rcid in g.root_causes_for_test("usb2_lpm_l1_basic")
    assert g.node(rcid)["kind"] == "ROOT_CAUSE"


def test_failure_signature_with_no_root_cause_hint_never_fabricates_a_root_cause_node(store):
    """Negative control: root_cause_hint is None (a real, unresolved failure)
    -- must surface as an unresolved-failure marker on the TEST node, and must
    NEVER create a ROOT_CAUSE node out of nothing."""
    store.insert_job_memory_record(_job_failure_record())
    g = build_verification_knowledge_graph(evidence_store=store)
    assert g.nodes("ROOT_CAUSE") == []
    tid_attrs = g.node(make_test_node_id("usb2_lpm_l1_basic"))["attrs"]
    assert tid_attrs["unresolved_failure_signatures"]


# ---------------------------------------------------------------------------
# evidence_db integration: coverage_samples -> COVERAGE_CATEGORY
# ---------------------------------------------------------------------------

def test_coverage_sample_links_to_known_test_by_exact_source_match(store):
    store.insert_golden_scenario(_golden_scenario())
    store.insert_coverage_sample(
        {"name": "hird_x_besl", "percent": 87.5, "bins_total": 32, "bins_hit": 28},
        source="usb2_lpm_l1_basic")
    g = build_verification_knowledge_graph(evidence_store=store)
    cid = coverage_node_id("hird_x_besl")
    assert cid in g.coverage_for_test("usb2_lpm_l1_basic")
    assert g.node(cid)["attrs"]["percent"] == 87.5


def test_coverage_sample_with_unmatched_source_stays_unlinked_not_guessed(store):
    """Negative control: a coverage sample whose `source` matches no test this
    graph knows about must still produce the category node (real evidence of
    a real coverage sample) but MUST NOT be linked to any test -- guessing the
    owner would be exactly the fabricated link the Evidence Truth Rule
    forbids."""
    store.insert_coverage_sample(
        {"name": "orphan_bin", "percent": 10.0, "bins_total": 10, "bins_hit": 1},
        source="some_unknown_pattern")
    g = build_verification_knowledge_graph(evidence_store=store)
    cid = coverage_node_id("orphan_bin")
    assert g.node(cid) is not None
    assert g.neighbors(cid, edge_kind="EXERCISES_COVERAGE", direction="in") == []


# ---------------------------------------------------------------------------
# memory.py integration
# ---------------------------------------------------------------------------

def test_memory_root_cause_kind_record_creates_node_and_test_edge(tmp_path):
    ms = MemoryStore(tmp_path)
    ms.add("engineering", {"kind": "root_cause", "verified": True,
                            "protocol": "USB2", "pattern": "usb2_lpm_l1_basic",
                            "root_cause": "LPM timer misconfigured for HIRD=3",
                            "confidence": "HIGH"})
    g = build_verification_knowledge_graph(memory_store=ms)
    rcid = root_cause_node_id("USB2", "LPM timer misconfigured for HIRD=3")
    assert rcid in g.root_causes_for_test("usb2_lpm_l1_basic")
    assert g.sources_used["memory_store"] is True


def test_memory_and_evidence_db_root_cause_converge_on_one_node(store, tmp_path):
    """The same real root cause, recorded independently via the job-tier
    memory path (mirrored into evidence_db.failure_signatures) AND via a
    dedicated engineering-tier root_cause memory record, must converge onto
    ONE ROOT_CAUSE node, not be fabricated as two -- proving the shared
    (protocol, normalized text) identity scheme actually unifies real,
    independently-authored evidence."""
    rec = _job_failure_record()
    rec["failure_signature"]["root_cause_hint"] = "LPM timer misconfigured for HIRD=3"
    store.insert_job_memory_record(rec)

    ms = MemoryStore(tmp_path)
    ms.add("engineering", {"kind": "root_cause", "verified": True,
                            "protocol": "usb2", "pattern": "usb2_lpm_l1_basic",
                            "root_cause": "  LPM timer misconfigured for HIRD=3  ",
                            "confidence": "HIGH"})

    g = build_verification_knowledge_graph(evidence_store=store, memory_store=ms)
    assert len(g.nodes("ROOT_CAUSE")) == 1
    node = g.nodes("ROOT_CAUSE")[0]
    assert len(node["provenance"]) == 2
    sources = {p["source"] for p in node["provenance"]}
    assert sources == {"failure_signatures", "memory_store"}


def test_memory_record_with_no_root_cause_text_is_skipped_never_fabricated(tmp_path):
    """Negative control: a verified_fix record with no root_cause text at all
    must be skipped honestly (recorded in `notes`), never turned into an
    empty-text ROOT_CAUSE node."""
    ms = MemoryStore(tmp_path)
    ms.add("engineering", {"kind": "verified_fix", "verified": True,
                            "protocol": "USB2", "confidence": "HIGH"})
    g = build_verification_knowledge_graph(memory_store=ms)
    assert g.nodes("ROOT_CAUSE") == []
    assert any("has no root_cause text" in n for n in g.notes)


def test_memory_root_cause_record_with_no_pattern_stays_unlinked(tmp_path):
    """Negative control: a standalone RCA record genuinely has no `pattern`
    field -- the ROOT_CAUSE node is still real, but no TEST node/edge is
    fabricated for it."""
    ms = MemoryStore(tmp_path)
    ms.add("engineering", {"kind": "debug_lesson", "verified": True,
                            "protocol": "USB2", "root_cause": "some standalone lesson",
                            "confidence": "HIGH"})
    g = build_verification_knowledge_graph(memory_store=ms)
    assert g.nodes("TEST") == []
    assert len(g.nodes("ROOT_CAUSE")) == 1


# ---------------------------------------------------------------------------
# Graph mechanics: idempotence, conflicting kind, multi-hop query
# ---------------------------------------------------------------------------

def test_add_node_is_idempotent_and_merges_provenance():
    g = VerificationKnowledgeGraph()
    g.add_node("TEST:x", "TEST", provenance={"source": "a"}, pattern="x")
    g.add_node("TEST:x", "TEST", provenance={"source": "b"}, extra="y")
    node = g.node("TEST:x")
    assert node["attrs"] == {"pattern": "x", "extra": "y"}
    assert len(node["provenance"]) == 2


def test_add_node_conflicting_kind_raises():
    g = VerificationKnowledgeGraph()
    g.add_node("SAME:id", "TEST")
    with pytest.raises(VerificationKnowledgeGraphError, match="already exists as kind"):
        g.add_node("SAME:id", "ROOT_CAUSE")


def test_add_edge_is_idempotent_no_duplicate():
    g = VerificationKnowledgeGraph()
    g.add_node("TEST:x", "TEST")
    g.add_node("REQUIREMENT:y", "REQUIREMENT")
    g.add_edge("TEST:x", "REQUIREMENT:y", "VERIFIES")
    g.add_edge("TEST:x", "REQUIREMENT:y", "VERIFIES")
    assert len(g.edges("VERIFIES")) == 1


def test_root_causes_for_requirement_two_hop_query_includes_tests_with_no_root_cause(store):
    store.insert_golden_scenario(_golden_scenario())
    rec = _job_failure_record()
    rec["failure_signature"]["root_cause_hint"] = "LPM timer misconfigured for HIRD=3"
    store.insert_job_memory_record(rec)
    g = build_verification_knowledge_graph(
        evidence_store=store, requirement_records=[clean_requirement()])
    result = g.root_causes_for_requirement("REQ-USB-LPM-001")
    tid = make_test_node_id("usb2_lpm_l1_basic")
    assert tid in result
    assert result[tid] == [root_cause_node_id("USB2", "LPM timer misconfigured for HIRD=3")]


def test_root_causes_for_requirement_reports_verified_test_with_no_root_cause_on_file(store):
    store.insert_golden_scenario(_golden_scenario())
    g = build_verification_knowledge_graph(
        evidence_store=store, requirement_records=[clean_requirement()])
    result = g.root_causes_for_requirement("REQ-USB-LPM-001")
    assert result[make_test_node_id("usb2_lpm_l1_basic")] == []


def test_neighbors_rejects_unknown_direction():
    g = VerificationKnowledgeGraph()
    with pytest.raises(VerificationKnowledgeGraphError, match="direction"):
        g.neighbors("TEST:x", direction="sideways")


def test_to_dict_and_stats_are_stable_and_sorted(store):
    store.insert_golden_scenario(_golden_scenario())
    g = build_verification_knowledge_graph(
        evidence_store=store, requirement_records=[clean_requirement()])
    d = g.to_dict()
    assert [n["id"] for n in d["nodes"]] == sorted(n["id"] for n in d["nodes"])
    stats = g.stats()
    assert stats["node_counts"]["TEST"] == 1
    assert stats["node_counts"]["REQUIREMENT"] == 1
    assert stats["edge_counts"]["VERIFIES"] == 1


# ---------------------------------------------------------------------------
# CLI (standalone `python -m dv_harness.verification_knowledge_graph`)
# ---------------------------------------------------------------------------

def test_cli_requirements_only_reports_gaps_present_exit_1(tmp_path):
    req_path = tmp_path / "reqs.json"
    req_path.write_text(json.dumps([clean_requirement()]), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.verification_knowledge_graph", "--requirements", str(req_path), "--json"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["nodes"][0]["attrs"]["requirement_id"] == "REQ-USB-LPM-001"


def test_cli_malformed_requirements_file_exits_2(tmp_path):
    req_path = tmp_path / "reqs.json"
    req_path.write_text(json.dumps([{"feature": "no shape marker"}]), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.verification_knowledge_graph", "--requirements", str(req_path)],
        capture_output=True, text=True, cwd=str(ROOT))
    assert result.returncode == 2
    assert "declare_contract_shape" in result.stderr


def test_cli_nonexistent_evidence_db_warns_and_continues(tmp_path):
    req_path = tmp_path / "reqs.json"
    req_path.write_text(json.dumps([clean_requirement()]), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.verification_knowledge_graph",
         "--requirements", str(req_path),
         "--evidence-db", str(tmp_path / "does_not_exist.duckdb")],
        capture_output=True, text=True, cwd=str(ROOT))
    assert "does not exist yet" in result.stderr
    assert result.returncode == 1
