"""Tests for dv_harness/subsystem_contract.py -- the Subsystem Verification
Contract aggregator.

Discipline: every positive-path assertion is driven against a REAL producer
this repo already ships (a real, schema-valid env.manifest.json built through
`env_manifest.generate_env_manifest()`; a real waiver recorded through
`waiver_store.record_waiver()`; a real DuckDB `EvidenceStore` carrying a real
`vip_distill.distill_sim_log()` envelope and a real `golden_scenario` capsule;
a real LSF job record shaped exactly like `regression_reporter.load_jobs()`
reads; a real `signoff_export.freeze_signoff_baseline()` freeze) -- never a
hand-shaped dict standing in for one of those readers' own output. Negative
controls mutate or omit exactly one of those real inputs at a time so each
assertion proves the aggregator reports that SPECIFIC absence honestly
(a distinct NOT_AVAILABLE reason, never a silent default and never collapsed
with a different kind of absence), rather than merely proving a function
returns a value.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness import environment_mode_router as emr
from dv_harness import env_manifest as em
from dv_harness import golden_scenario as gs
from dv_harness import signoff_export as se
from dv_harness import subsystem_contract as sc
from dv_harness import waiver_store as ws
from dv_harness.evidence_db import EvidenceStore
from dv_harness.lsf_client import JobState
from dv_harness.vip_distill import distill_sim_log

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_ARGS = [sys.executable, "-m", "dv_harness.subsystem_contract"]


# ---------------------------------------------------------------------------
# Fixture builders -- each writes ONE real artifact through its real producer
# ---------------------------------------------------------------------------

def _write_manifest(root: Path, *, vip_instances=None, testplan_sources=None,
                    out_rel=".dv-harness/env.manifest.json"):
    vip_dump = None
    if vip_instances is not None:
        vip_dump = root / "vip_config_dump.json"
        vip_dump.write_text(json.dumps({"schema_version": "1.0",
                                        "vip_instances": vip_instances}), encoding="utf-8")
    ts_path = None
    if testplan_sources is not None:
        ts_path = root / "testplan_sources.json"
        ts_path.write_text(json.dumps(testplan_sources), encoding="utf-8")
    out_path = root / out_rel
    out_path.parent.mkdir(parents=True, exist_ok=True)
    em.generate_and_write(
        out_path,
        vip_config_dump_path=str(vip_dump) if vip_dump else None,
        testplan_sources_path=str(ts_path) if ts_path else None,
    )
    return out_path


DEFAULT_VIP_INSTANCES = [
    {"instance_path": "tb.usb3_agent", "vip_type": "svt_usb3",
     "config_fields": {"speed": "SS", "lane_width": "1"}},
]
DEFAULT_TESTPLAN_SOURCES = {
    "schema_version": "1.0",
    "testlist": [{"name": "usb3_lfps_basic"}],
    "vplan_items": [{"id": "VP-1", "tests": ["usb3_lfps_basic"], "coverage": ["cg_lfps"]}],
    "coverage_model": [{"name": "cg_lfps", "kind": "covergroup"}],
}


def _clean_requirement_record(**over):
    r = {
        "contract_schema_version": "1.0",
        "requirement_id": "REQ-USB-LPM-001",
        "source": {"document": "usb2_spec.pdf", "locator": "section 7.2.3",
                   "quote": "The device shall enter L1 within tL1Entry."},
        "feature": "LPM L1 entry", "protocol": "USB2",
        "configuration": "HS, LPM enabled", "precondition": "device configured, link in U0",
        "stimulus": "host issues an LPM EXT token with HIRD=3",
        "expected_result": "device ACKs and enters L1 within tL1Entry",
        "observability": "utmi_suspend_o asserted; VIP LPM callback",
        "checker": "scoreboard compares observed L1 entry latency against tL1Entry",
        "coverage_intent": "cover HIRD 0..15 crossed with BESL",
        "priority": "P0", "criticality": "BLOCKER", "confidence": "HIGH",
        "status": "COMPLETE",
    }
    r.update(over)
    return r


def _write_requirements(root: Path, *, rel=".dv-harness/requirements/requirement_contract.json",
                        records=None):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"requirements": records or [_clean_requirement_record()]}),
                    encoding="utf-8")
    return path


def _write_valid_waiver(root: Path, *, waiver_id="W-1", expires_at="2099-01-01T00:00:00Z"):
    return ws.record_waiver(root, {
        "waiver_id": waiver_id, "item": "some open finding", "reason": "accepted for now",
        "evidence": "reviewed offline", "approver": "alice",
        "scope": {"requirement_ids": ["REQ-1"], "subsystem": "usb3_link",
                  "spec_revision": "r1", "design_evidence_hash": "abc123",
                  "approval_id": "AP-1", "scope_hash": "h1"},
        "affected_version": {"revision": "r1"}, "risk": "LOW",
        "created_at": "2026-01-01T00:00:00Z", "expires_at": expires_at,
    })


def _write_lsf_job(root: Path, *, job_id=1, dv_status="PASS", lsf_status="DONE"):
    jobs_dir = root / ".dv-harness" / "lsf" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / f"{job_id}.json").write_text(json.dumps({
        "job_id": job_id, "lsf_status": lsf_status, "dv_analysis_status": dv_status,
        "sim_status": dv_status, "early_kill": False,
    }), encoding="utf-8")


PASSING_SIM_LOG = """\
UVM_INFO @ 0 ns: reporter [RNTST] Running test usb3_lfps_basic...
FINAL CHECK @ 25000 ns
UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0
VERDICT: PASSED
"""


def _write_evidence_and_capsule(root: Path, *, job_id=555, pattern="usb3_lfps_basic",
                                record_capsule=True):
    log_path = root / "run" / str(job_id) / "sim.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(PASSING_SIM_LOG, encoding="utf-8")
    store = EvidenceStore(root / ".dv-harness" / "evidence" / "evidence.duckdb")
    try:
        envelope = distill_sim_log(log_path=log_path, job_id=job_id, pattern=pattern,
                                   protocol="USB3", run_dir=str(log_path.parent))
        store.insert_normalized_evidence(envelope)
        store.insert_job_state(JobState(
            job_id=job_id, regression_id="REG-1", pattern=pattern,
            run_dir=str(log_path.parent), sim_log=str(log_path), seed="42",
            lsf_status="DONE", sim_status="PASS", uvm_error_count=0, uvm_fatal_count=0,
            git_sha="deadbeef1234",
        ))
        if record_capsule:
            capsule = gs.GoldenScenario(
                capsule_id=gs.default_capsule_id("proj", "usb3_link", pattern, "42"),
                project="proj", subsystem="usb3_link", test_name=pattern,
                evidence_id=envelope["evidence_id"], protocol="USB3")
            gs.record_golden_scenario(store, capsule)
    finally:
        store.close()
    return envelope


def _empty_evidence_db(root: Path):
    store = EvidenceStore(root / ".dv-harness" / "evidence" / "evidence.duckdb")
    store.close()


def _write_signoff_pass_state(root: Path):
    state_path = root / ".dv-harness" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "current_stage": "SIGNOFF", "stages": {"SIGNOFF": {"status": "PASS"}},
    }), encoding="utf-8")


@pytest.fixture()
def bare_root(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    return root


# ---------------------------------------------------------------------------
# Bare-root honesty: nothing fabricated, everything real absence is named
# ---------------------------------------------------------------------------

def test_bare_root_is_not_available_overall_with_every_field_named(bare_root):
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["completeness"] == sc.NOT_AVAILABLE_OVERALL
    assert record["unavailable_aspect_count"] == len(sc.TRACKED_ASPECTS)
    fields = {u["field"] for u in record["unknowns"]}
    assert fields >= set(sc.TRACKED_ASPECTS)
    # every unknown carries a real, non-empty reason string
    for u in record["unknowns"]:
        assert u["reason"]
    assert record["subsystem"]["source"] == "PROJECT_SCOPE_NO_SUBSYSTEM_REQUESTED"
    assert record["waivers"]["status"] == "NOT_AVAILABLE"
    assert record["evidence_references"]["status"] == "NOT_AVAILABLE"
    assert record["reproducibility_capsules"]["status"] == "NOT_AVAILABLE"
    assert record["regression"]["status"] == "NOT_AVAILABLE"
    assert record["signoff"]["baseline_freeze"]["status"] == "NOT_AVAILABLE"


def test_bare_root_assemble_never_creates_dv_harness_tree(bare_root):
    sc.assemble_subsystem_contract(bare_root)
    assert not (bare_root / ".dv-harness").exists()


# ---------------------------------------------------------------------------
# env.manifest.json: protocols / interfaces / vplan_tests_coverage
# ---------------------------------------------------------------------------

def test_real_manifest_populates_protocols_interfaces_and_vplan(bare_root):
    _write_manifest(bare_root, vip_instances=DEFAULT_VIP_INSTANCES,
                    testplan_sources=DEFAULT_TESTPLAN_SOURCES)
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["protocols"] == ["svt_usb3"]
    assert record["interfaces"] == [{"instance_path": "tb.usb3_agent", "vip_type": "svt_usb3",
                                     "config_field_count": 2}]
    assert record["vip_config"]["status"] == "CAPTURED"
    assert record["vplan_tests_coverage"]["status"] == "COMPUTED"
    assert record["vplan_tests_coverage"]["summary"]["linked_count"] == 1
    unknown_fields = {u["field"] for u in record["unknowns"]}
    assert "protocols_interfaces" not in unknown_fields
    assert "vplan_tests_coverage" not in unknown_fields


def test_no_manifest_reports_not_available_naming_absence(bare_root):
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["vip_config"]["status"] == "NOT_AVAILABLE"
    assert "no env.manifest.json found" in record["vip_config"]["reason"]
    assert record["protocols"] == []
    assert record["interfaces"] == []


def test_malformed_manifest_reports_not_available_never_crashes(bare_root):
    """Negative control: a manifest that EXISTS but fails schema validation
    must surface as a named gap, never be quietly treated as absent-but-fine
    nor crash the whole assembly."""
    manifest_path = bare_root / ".dv-harness" / "env.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"env_topology": {}}), encoding="utf-8")
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["vip_config"]["status"] == "NOT_AVAILABLE"
    assert "failed schema validation" in record["vip_config"]["reason"]
    assert record["vplan_tests_coverage"]["status"] == "NOT_AVAILABLE"
    # the rest of assembly still completed
    assert record["completeness"] in (sc.PARTIAL, sc.NOT_AVAILABLE_OVERALL)


# ---------------------------------------------------------------------------
# requirements
# ---------------------------------------------------------------------------

def test_real_requirement_contract_record_reports_complete(bare_root):
    _write_requirements(bare_root)
    record = sc.assemble_subsystem_contract(bare_root)
    req = record["requirements"]
    assert req["status"] == "PASS"
    assert req["analyzed"] == 1
    assert req["status_counts"]["COMPLETE"] == 1
    assert not any(u["field"] == "requirements" for u in record["unknowns"])


def test_no_requirements_artifact_reports_not_available_with_checked_paths(bare_root):
    record = sc.assemble_subsystem_contract(bare_root)
    req = record["requirements"]
    assert req["status"] == "NOT_AVAILABLE"
    assert len(req["checked_paths"]) == len(sc.DEFAULT_REQUIREMENTS_CANDIDATES)
    assert any(u["field"] == "requirements" for u in record["unknowns"])


def test_explicit_requirements_path_bypasses_conventional_locations(tmp_path, bare_root):
    elsewhere = tmp_path / "elsewhere_requirements.json"
    elsewhere.write_text(json.dumps({"requirements": [_clean_requirement_record()]}),
                         encoding="utf-8")
    record = sc.assemble_subsystem_contract(bare_root, requirements_path=str(elsewhere))
    assert record["requirements"]["status"] == "PASS"
    assert record["requirements"]["source_path"] == str(elsewhere)


def test_overclaimed_requirement_status_surfaces_as_a_fail_not_a_silent_pass(bare_root):
    """Negative control: mutating one field of the clean record (declaring
    COMPLETE while `checker` is a placeholder) must make requirement_contract
    FAIL, and this module must carry that FAIL through rather than smoothing
    it into PASS."""
    bad = _clean_requirement_record(checker="TBD")
    _write_requirements(bare_root, records=[bad])
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["requirements"]["status"] == "FAIL"
    assert record["requirements"]["findings"]


# ---------------------------------------------------------------------------
# regression
# ---------------------------------------------------------------------------

def test_real_lsf_job_record_populates_regression(bare_root):
    _write_lsf_job(bare_root, job_id=42, dv_status="PASS")
    record = sc.assemble_subsystem_contract(bare_root)
    reg = record["regression"]
    assert reg["status"] == "PRESENT"
    assert reg["total"] == 1
    assert reg["pass_confirmed"] == 1
    assert not any(u["field"] == "regression" for u in record["unknowns"])


def test_no_lsf_jobs_reports_not_available(bare_root):
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["regression"]["status"] == "NOT_AVAILABLE"
    assert record["regression"]["reason"] == "NO_RECORDED_JOBS"


def test_lsf_job_with_no_dv_analysis_is_not_confirmed_pass(bare_root):
    """Negative control: LSF DONE is not DV PASS -- a job with no recorded
    dv_analysis_status must not be counted as pass_confirmed."""
    jobs_dir = bare_root / ".dv-harness" / "lsf" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / "1.json").write_text(json.dumps({
        "job_id": 1, "lsf_status": "DONE", "dv_analysis_status": None,
        "sim_status": None, "early_kill": False}), encoding="utf-8")
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["regression"]["status"] == "PRESENT"
    assert record["regression"]["pass_confirmed"] == 0


# ---------------------------------------------------------------------------
# waivers
# ---------------------------------------------------------------------------

def test_valid_waiver_ledger_reports_clear(bare_root):
    _write_valid_waiver(bare_root)
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["waivers"]["status"] == "CLEAR"
    assert record["waivers"]["waivers"][0]["status"] == "VALID"
    assert not any(u["field"] == "waivers" for u in record["unknowns"])


def test_expired_waiver_reports_not_valid_but_is_still_assembled(bare_root):
    """Negative control: an EXPIRED waiver is real, derived content -- it must
    surface as WAIVERS_NOT_VALID, never as NOT_AVAILABLE (which would hide a
    real expired waiver behind 'nothing to report')."""
    _write_valid_waiver(bare_root, expires_at="2020-01-01T00:00:00Z")
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["waivers"]["status"] == "WAIVERS_NOT_VALID"
    assert record["waivers"]["waivers"][0]["status"] == "EXPIRED"
    assert not any(u["field"] == "waivers" for u in record["unknowns"])


def test_no_waiver_ledger_reports_not_available(bare_root):
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["waivers"]["status"] == "NOT_AVAILABLE"
    assert any(u["field"] == "waivers" for u in record["unknowns"])


# ---------------------------------------------------------------------------
# evidence references / reproducibility capsules
# ---------------------------------------------------------------------------

def test_real_evidence_and_capsule_populate_both_sections(bare_root):
    envelope = _write_evidence_and_capsule(bare_root)
    record = sc.assemble_subsystem_contract(bare_root)
    ev = record["evidence_references"]
    assert ev["status"] == "PRESENT"
    assert ev["count"] == 1
    assert ev["items"][0]["evidence_id"] == envelope["evidence_id"]
    caps = record["reproducibility_capsules"]
    assert caps["status"] == "PRESENT"
    assert caps["capsule_count"] == 1
    assert caps["freshness_status"] in ("FRESH", "STALE", "UNKNOWN")


def test_capture_baseline_failure_degrades_to_not_available_never_crashes(bare_root):
    """`signoff_export.capture_baseline()` captures all fifteen section-238
    fields in one call -- including `evidence_hashes`, which (a real,
    pre-existing defect in that module: `_capture_evidence_hashes()` indexes
    `EvidenceStore.query()`'s plain tuple rows with string keys) raises once
    real `normalized_evidence` rows exist. This module must never let a
    failure in a baseline field it does not even expose crash the whole
    contract assembly -- it must degrade spec_version/dut_sha/tb_sha to a
    named NOT_AVAILABLE instead."""
    _write_evidence_and_capsule(bare_root)
    record = sc.assemble_subsystem_contract(bare_root)
    for name in ("spec_version", "dut_sha", "tb_sha"):
        assert record[name]["status"] == "NOT_AVAILABLE"
        assert "capture_baseline" in record[name]["reason"]
    assert {"spec_version", "dut_sha", "tb_sha"} <= {u["field"] for u in record["unknowns"]}
    # the evidence/capsule sections themselves are unaffected
    assert record["evidence_references"]["status"] == "PRESENT"
    assert record["reproducibility_capsules"]["status"] == "PRESENT"
    assert not any(u["field"] == "evidence_references" for u in record["unknowns"])
    assert not any(u["field"] == "reproducibility_capsules" for u in record["unknowns"])


def test_evidence_present_but_no_capsule_recorded(bare_root):
    _write_evidence_and_capsule(bare_root, record_capsule=False)
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["evidence_references"]["status"] == "PRESENT"
    assert record["reproducibility_capsules"]["status"] == "NOT_AVAILABLE"
    assert record["reproducibility_capsules"]["reason"] == "NO_GOLDEN_SCENARIO_CAPSULES_RECORDED"


def test_empty_evidence_database_reports_not_available_not_zero_rows_as_present(bare_root):
    """Negative control: a real evidence.duckdb that exists but holds no rows
    must not be mistaken for 'evidence present, zero items'."""
    _empty_evidence_db(bare_root)
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["evidence_references"]["status"] == "NOT_AVAILABLE"
    assert record["evidence_references"]["reason"] == "NO_NORMALIZED_EVIDENCE_ROWS"
    assert record["reproducibility_capsules"]["status"] == "NOT_AVAILABLE"


def test_no_evidence_database_reports_not_available(bare_root):
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["evidence_references"]["status"] == "NOT_AVAILABLE"
    assert record["evidence_references"]["reason"] == "NO_EVIDENCE_DATABASE"


# ---------------------------------------------------------------------------
# signoff (stage + frozen baseline)
# ---------------------------------------------------------------------------

def test_signoff_stage_reflects_real_state_json(bare_root):
    _write_signoff_pass_state(bare_root)
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["signoff"]["stage"]["stage_status"] == "PASS"
    assert record["signoff"]["stage"]["gate_verified"] is True


def test_no_state_json_reports_signoff_not_recorded(bare_root):
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["signoff"]["stage"]["stage_status"] == se.SIGNOFF_STATUS_NOT_RECORDED
    assert record["signoff"]["stage"]["gate_verified"] is False


def test_real_signoff_freeze_populates_baseline_freeze(bare_root):
    se.freeze_signoff_baseline(bare_root, frozen_by="tester")
    record = sc.assemble_subsystem_contract(bare_root)
    baseline = record["signoff"]["baseline_freeze"]
    assert baseline["status"] == "PRESENT"
    assert baseline["freeze_id"]
    assert baseline["frozen_by"] == "tester"
    assert baseline["invalidation_status"] in ("VALID", "INVALIDATED", "UNKNOWN")
    assert not any(u["field"] == "signoff_baseline_freeze" for u in record["unknowns"])


def test_no_signoff_freeze_reports_not_available(bare_root):
    record = sc.assemble_subsystem_contract(bare_root)
    baseline = record["signoff"]["baseline_freeze"]
    assert baseline["status"] == "NOT_AVAILABLE"
    assert baseline["reason"] == "NO_SIGNOFF_FREEZE_RECORDED"
    assert any(u["field"] == "signoff_baseline_freeze" for u in record["unknowns"])


# ---------------------------------------------------------------------------
# subsystem scope resolution
# ---------------------------------------------------------------------------

def test_unregistered_subsystem_falls_back_to_project_manifest(bare_root):
    _write_manifest(bare_root, vip_instances=DEFAULT_VIP_INSTANCES,
                    testplan_sources=DEFAULT_TESTPLAN_SOURCES)
    record = sc.assemble_subsystem_contract(bare_root, subsystem="usb3_link")
    assert record["subsystem"]["source"] == "SUBSYSTEM_NOT_REGISTERED"
    assert record["subsystem"]["requested"] == "usb3_link"
    assert any(u["field"] == "subsystem_scope" for u in record["unknowns"])
    # the fallback to the project's own manifest still worked
    assert record["protocols"] == ["svt_usb3"]


def test_registered_subsystem_uses_its_own_registry_manifest_path(bare_root):
    # The DEFAULT manifest at .dv-harness/env.manifest.json describes one
    # protocol; the REGISTERED subsystem's own manifest (a different path)
    # describes a different one, so which one wins proves the lookup really
    # used the registry entry and not the default fallback.
    _write_manifest(bare_root, vip_instances=DEFAULT_VIP_INSTANCES,
                    testplan_sources=DEFAULT_TESTPLAN_SOURCES)
    alt_instances = [{"instance_path": "tb.pcie_agent", "vip_type": "svt_pcie",
                      "config_fields": {"lanes": "4"}}]
    alt_manifest = _write_manifest(bare_root, vip_instances=alt_instances,
                                   out_rel="subsystems/pcie_link/env.manifest.json")
    registry_path = emr.registry_path(bare_root)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps({"subsystems": [{
        "name": "pcie_link",
        "environment_manifest": str(alt_manifest.relative_to(bare_root)),
        "release_sha": "abc123", "qualification_state": "BASELINE_READY",
        "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS",
    }]}), encoding="utf-8")

    record = sc.assemble_subsystem_contract(bare_root, subsystem="pcie_link")
    assert record["subsystem"]["source"] == "REGISTERED_SUBSYSTEM_ENTRY"
    assert record["subsystem"]["registry_entry"]["qualification_state"] == "BASELINE_READY"
    assert record["protocols"] == ["svt_pcie"]


def test_registered_subsystem_lookup_is_case_insensitive_by_name(bare_root):
    registry_path = emr.registry_path(bare_root)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps({"subsystems": [{"name": "USB3_Link"}]}),
                             encoding="utf-8")
    record = sc.assemble_subsystem_contract(bare_root, subsystem="usb3_link")
    assert record["subsystem"]["source"] == "REGISTERED_SUBSYSTEM_ENTRY"
    assert record["subsystem"]["resolved_name"] == "USB3_Link"


# ---------------------------------------------------------------------------
# completeness scoring
# ---------------------------------------------------------------------------

def test_completeness_is_partial_when_some_but_not_all_aspects_assembled(bare_root):
    _write_manifest(bare_root, vip_instances=DEFAULT_VIP_INSTANCES,
                    testplan_sources=DEFAULT_TESTPLAN_SOURCES)
    _write_valid_waiver(bare_root)
    record = sc.assemble_subsystem_contract(bare_root)
    assert record["completeness"] == sc.PARTIAL
    assert 0 < record["unavailable_aspect_count"] < len(sc.TRACKED_ASPECTS)


def test_completeness_counts_only_tracked_aspects_not_subsystem_scope(bare_root):
    """The scope-resolution unknown (recorded when a requested subsystem is
    not registered) must not inflate the tracked-aspect completeness count --
    it is a different kind of unknown, about the REQUEST, not about a
    contract field."""
    record_scoped = sc.assemble_subsystem_contract(bare_root, subsystem="anything")
    record_unscoped = sc.assemble_subsystem_contract(bare_root)
    assert record_scoped["unavailable_aspect_count"] == record_unscoped["unavailable_aspect_count"]
    assert record_scoped["completeness"] == record_unscoped["completeness"]


# ---------------------------------------------------------------------------
# write_subsystem_contract / execute_verb
# ---------------------------------------------------------------------------

def test_snapshot_writes_the_contract_file(bare_root):
    _write_manifest(bare_root, vip_instances=DEFAULT_VIP_INSTANCES,
                    testplan_sources=DEFAULT_TESTPLAN_SOURCES)
    text, code = sc.execute_verb("snapshot", root=bare_root, as_json=True)
    written = json.loads((bare_root / ".dv-harness" / "subsystem_contract.json").read_text())
    assert written["protocols"] == ["svt_usb3"]
    parsed = json.loads(text)
    assert parsed["written_to"] == str(bare_root / ".dv-harness" / "subsystem_contract.json")


def test_assemble_verb_never_writes_the_snapshot_file(bare_root):
    _write_manifest(bare_root, vip_instances=DEFAULT_VIP_INSTANCES,
                    testplan_sources=DEFAULT_TESTPLAN_SOURCES)
    sc.execute_verb("assemble", root=bare_root, as_json=True)
    assert not (bare_root / ".dv-harness" / "subsystem_contract.json").exists()


def test_write_subsystem_contract_refuses_a_nonexistent_root(tmp_path):
    missing = tmp_path / "does_not_exist_at_all"
    with pytest.raises(sc.SubsystemContractError):
        sc.write_subsystem_contract(missing, {"x": 1})


def test_execute_verb_unknown_verb_reports_usage_error(bare_root):
    text, code = sc.execute_verb("bogus", root=bare_root)
    assert code == 2
    assert "unknown subsystem-contract verb" in text


def test_exit_code_is_2_for_bare_root(bare_root):
    _text, code = sc.execute_verb("assemble", root=bare_root)
    assert code == 2


def test_exit_code_is_1_when_partial(bare_root):
    _write_manifest(bare_root, vip_instances=DEFAULT_VIP_INSTANCES,
                    testplan_sources=DEFAULT_TESTPLAN_SOURCES)
    _write_valid_waiver(bare_root)
    _text, code = sc.execute_verb("assemble", root=bare_root)
    assert code == 1


# ---------------------------------------------------------------------------
# Real subprocess CLI (`python -m dv_harness.subsystem_contract`)
# ---------------------------------------------------------------------------

def test_cli_assemble_bare_root_exits_2(bare_root):
    result = subprocess.run(
        CLI_ARGS + ["assemble", "--root", str(bare_root), "--json"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120)
    assert result.returncode == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["completeness"] == sc.NOT_AVAILABLE_OVERALL


def test_cli_snapshot_writes_real_file_via_subprocess(bare_root):
    _write_manifest(bare_root, vip_instances=DEFAULT_VIP_INSTANCES,
                    testplan_sources=DEFAULT_TESTPLAN_SOURCES)
    result = subprocess.run(
        CLI_ARGS + ["snapshot", "--root", str(bare_root)],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120)
    assert result.returncode == 1, result.stdout + result.stderr
    out_path = bare_root / ".dv-harness" / "subsystem_contract.json"
    assert out_path.is_file()
    written = json.loads(out_path.read_text())
    assert written["protocols"] == ["svt_usb3"]
