"""Tests for dv_harness/digital_thread_traceability.py -- the end-to-end
requirement -> vplan item -> pattern/command -> test -> coverage bin ->
regression evidence -> signoff trace (section 231).

Discipline: the real registry (`change_impact.load_trace_registry()`), the
real testplan_correspondence join (`env_manifest.generate_and_write()` over a
real schema-valid testplan_sources.json), a real DuckDB `EvidenceStore`
carrying a real `vip_distill.distill_sim_log()` envelope and a real
`golden_scenario` capsule, and a real throwaway git repository (so
`golden_scenario.evaluate_freshness()` derives FRESH/STALE from a real
`git diff`) are all driven through their own real production APIs -- never a
hand-shaped dict standing in for one of those readers' own output. Negative
controls omit exactly one real source at a time and prove the module reports
that specific absence as NOT_AVAILABLE, never silently as LINKED.
"""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness import digital_thread_traceability as dt
from dv_harness import env_manifest as em
from dv_harness import golden_scenario as gs
from dv_harness.evidence_db import EvidenceStore
from dv_harness.lsf_client import JobState
from dv_harness.vip_distill import distill_sim_log

GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="git is not on PATH")

REQUIREMENTS_CSV_HEADER = [
    "REQ_ID", "SOURCE", "SCOPE", "VPLAN_ID", "SCENARIO_ID", "COMMAND_ID",
    "PATTERN_ID", "CHECKER_ID", "COVERAGE_ID", "RESULT", "STATUS", "EVIDENCE",
]

PASSING_SIM_LOG = """\
UVM_INFO @ 0 ns: reporter [RNTST] Running test usb3_lfps_basic...
FINAL CHECK @ 25000 ns
UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0
VERDICT: PASSED
"""

DEFAULT_TESTPLAN_SOURCES = {
    "schema_version": "1.0",
    "testlist": [{"name": "usb3_lfps_basic"}],
    "vplan_items": [{"id": "VP-1", "tests": ["usb3_lfps_basic"], "coverage": ["cg_lfps"]}],
    "coverage_model": [{"name": "cg_lfps", "kind": "covergroup"}],
}


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _git(root, *args, check=True):
    r = subprocess.run([GIT, *args], cwd=str(root), capture_output=True, text=True,
                       timeout=120, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def _commit(root, message):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def _write_requirements_csv(root: Path, rows: list) -> Path:
    path = root / ".dv-harness" / "requirements.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=REQUIREMENTS_CSV_HEADER)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in REQUIREMENTS_CSV_HEADER})
    return path


def _write_manifest(root: Path, *, testplan_sources=None) -> Path:
    ts_path = None
    if testplan_sources is not None:
        ts_path = root / "testplan_sources.json"
        ts_path.write_text(json.dumps(testplan_sources), encoding="utf-8")
    out_path = root / ".dv-harness" / "env.manifest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    em.generate_and_write(out_path, testplan_sources_path=str(ts_path) if ts_path else None)
    return out_path


def _write_capsule(root: Path, *, job_id=555, pattern="usb3_lfps_basic",
                    requirements=None, verified_sha=None):
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
            git_sha=verified_sha or "deadbeef1234",
        ))
        capsule = gs.GoldenScenario(
            capsule_id=gs.default_capsule_id("proj", "usb3_link", pattern, "42"),
            project="proj", subsystem="usb3_link", test_name=pattern,
            evidence_id=envelope["evidence_id"], protocol="USB3",
            verified_sha=verified_sha, requirements=list(requirements or []))
        gs.record_golden_scenario(store, capsule)
    finally:
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


@pytest.fixture()
def git_project(tmp_path):
    """A real throwaway git repo with one commit -- .dv-harness/ (evidence db,
    requirements.csv, env.manifest.json, state.json) is gitignored, exactly
    like the golden_scenario.py fixture, so it never becomes tracked content
    the freshness diff would see as a change."""
    if GIT is None:
        pytest.skip("git is not on PATH")
    root = tmp_path / "proj"
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk);\nendmodule\n", encoding="utf-8")
    (root / ".gitignore").write_text(".dv-harness/\nrun/\n", encoding="utf-8")
    subprocess.run([GIT, "init", "-q", "-b", "master", str(root)], check=True, timeout=60)
    _git(root, "config", "user.email", "digital-thread@example.invalid")
    _git(root, "config", "user.name", "digital-thread-test")
    sha = _commit(root, "initial RTL")
    return root, sha


# ---------------------------------------------------------------------------
# No registry at all -> honest NOT_AVAILABLE, never a vacuous pass
# ---------------------------------------------------------------------------

def test_bare_root_reports_not_available(bare_root):
    report = dt.assemble_digital_thread(bare_root)
    assert report["status"] == dt.REPORT_NOT_AVAILABLE
    assert report["chains"] == []
    assert "requirements.csv" in report["reason"]


def test_bare_root_assembly_writes_nothing(bare_root):
    dt.assemble_digital_thread(bare_root)
    assert not (bare_root / ".dv-harness").exists()


# ---------------------------------------------------------------------------
# Registry present, nothing else supplied: the negative control this module
# exists to prove -- absent evidence must never be reported as LINKED.
# ---------------------------------------------------------------------------

def test_registry_only_never_fabricates_linked_links(bare_root):
    _write_requirements_csv(bare_root, [{
        "REQ_ID": "REQ-1", "SOURCE": "spec.pdf", "SCOPE": "usb3_link",
        "VPLAN_ID": "VP-1", "PATTERN_ID": "usb3_lfps_basic", "COVERAGE_ID": "cg_lfps",
    }])
    report = dt.assemble_digital_thread(bare_root)
    assert report["status"] != dt.REPORT_NOT_AVAILABLE
    assert len(report["chains"]) == 1
    chain = report["chains"][0]
    links = chain["links"]

    # Real structural facts the registry itself carries ARE reported --
    # this is not a blanket "everything unknown" claim.
    assert links["pattern_command"]["status"] == dt.LINK_LINKED

    # Everything that needed a source this call never supplied is honestly
    # NOT_AVAILABLE, never silently promoted to LINKED.
    assert links["vplan_item"]["status"] == dt.LINK_NOT_AVAILABLE
    assert links["test"]["status"] == dt.LINK_NOT_AVAILABLE
    assert links["coverage_bin"]["status"] == dt.LINK_NOT_AVAILABLE
    assert links["regression_evidence"]["status"] == dt.LINK_NOT_AVAILABLE
    # SIGNOFF has never been recorded on this project -- a real, structural
    # GAP the harness's own state.json absence proves, not an unmeasured fact.
    assert links["signoff"]["status"] == dt.LINK_GAP

    for name in dt.LINK_NAMES:
        assert links[name]["status"] != dt.LINK_LINKED or name == "pattern_command"

    # Worst-wins: the GAP signoff link outranks every NOT_AVAILABLE link.
    assert chain["chain_status"] == dt.TRACE_GAP


def test_registry_row_declaring_nothing_reports_pattern_gap(bare_root):
    _write_requirements_csv(bare_root, [{"REQ_ID": "REQ-1", "SCOPE": "usb3_link"}])
    report = dt.assemble_digital_thread(bare_root)
    chain = report["chains"][0]
    assert chain["links"]["pattern_command"]["status"] == dt.LINK_GAP


# ---------------------------------------------------------------------------
# vplan_item link: real vplan_artifact.build_vplan_hierarchy() cross-check
# ---------------------------------------------------------------------------

def test_vplan_item_link_confirmed_from_real_vplan_document(bare_root):
    _write_requirements_csv(bare_root, [{
        "REQ_ID": "REQ-1", "VPLAN_ID": "VP-1", "PATTERN_ID": "usb3_lfps_basic",
    }])
    vplan_rows = [{"id": "VP-1", "requirement_refs": ["REQ-1"]}]
    report = dt.assemble_digital_thread(bare_root, vplan_rows=vplan_rows)
    assert report["chains"][0]["links"]["vplan_item"]["status"] == dt.LINK_LINKED


def test_vplan_item_link_dangling_reference_is_broken(bare_root):
    _write_requirements_csv(bare_root, [{"REQ_ID": "REQ-1", "VPLAN_ID": "VP-NOPE"}])
    vplan_rows = [{"id": "VP-1", "requirement_refs": ["REQ-1"]}]
    report = dt.assemble_digital_thread(bare_root, vplan_rows=vplan_rows)
    link = report["chains"][0]["links"]["vplan_item"]
    assert link["status"] == dt.LINK_BROKEN
    assert "VP-NOPE" in link["reason"]
    assert report["chains"][0]["chain_status"] == dt.TRACE_BROKEN


def test_vplan_item_present_but_does_not_claim_requirement_is_a_gap(bare_root):
    _write_requirements_csv(bare_root, [{"REQ_ID": "REQ-1", "VPLAN_ID": "VP-1"}])
    vplan_rows = [{"id": "VP-1", "requirement_refs": ["REQ-OTHER"]}]
    report = dt.assemble_digital_thread(bare_root, vplan_rows=vplan_rows)
    link = report["chains"][0]["links"]["vplan_item"]
    assert link["status"] == dt.LINK_GAP


def test_malformed_vplan_rows_raises_rather_than_silently_ignored(bare_root):
    _write_requirements_csv(bare_root, [{"REQ_ID": "REQ-1", "VPLAN_ID": "VP-1"}])
    with pytest.raises(dt.DigitalThreadTraceabilityError):
        dt.assemble_digital_thread(bare_root, vplan_rows=[{"no_id": "oops"}])


# ---------------------------------------------------------------------------
# test / coverage_bin links: real env_manifest.testplan_correspondence
# ---------------------------------------------------------------------------

def test_test_and_coverage_links_confirmed_from_real_testplan_correspondence(bare_root):
    _write_requirements_csv(bare_root, [{
        "REQ_ID": "REQ-1", "VPLAN_ID": "VP-1", "PATTERN_ID": "usb3_lfps_basic",
        "COVERAGE_ID": "cg_lfps",
    }])
    _write_manifest(bare_root, testplan_sources=DEFAULT_TESTPLAN_SOURCES)
    report = dt.assemble_digital_thread(bare_root)
    links = report["chains"][0]["links"]
    assert links["test"]["status"] == dt.LINK_LINKED
    assert links["coverage_bin"]["status"] == dt.LINK_LINKED


def test_test_link_broken_when_claimed_pattern_is_a_real_testplan_miss(bare_root):
    ts = {
        "schema_version": "1.0",
        "testlist": [{"name": "some_other_test"}],
        "vplan_items": [{"id": "VP-1", "tests": ["usb3_lfps_basic"], "coverage": ["cg_lfps"]}],
        "coverage_model": [{"name": "cg_lfps", "kind": "covergroup"}],
    }
    _write_requirements_csv(bare_root, [{
        "REQ_ID": "REQ-1", "VPLAN_ID": "VP-1", "PATTERN_ID": "usb3_lfps_basic",
        "COVERAGE_ID": "cg_lfps",
    }])
    _write_manifest(bare_root, testplan_sources=ts)
    report = dt.assemble_digital_thread(bare_root)
    link = report["chains"][0]["links"]["test"]
    assert link["status"] == dt.LINK_BROKEN
    assert "usb3_lfps_basic" in link["reason"]
    assert report["chains"][0]["chain_status"] == dt.TRACE_BROKEN


def test_coverage_link_broken_when_claimed_coverage_id_is_a_real_miss(bare_root):
    ts = {
        "schema_version": "1.0",
        "testlist": [{"name": "usb3_lfps_basic"}],
        "vplan_items": [{"id": "VP-1", "tests": ["usb3_lfps_basic"], "coverage": ["cg_gone"]}],
        "coverage_model": [{"name": "some_other_cg", "kind": "covergroup"}],
    }
    _write_requirements_csv(bare_root, [{
        "REQ_ID": "REQ-1", "VPLAN_ID": "VP-1", "PATTERN_ID": "usb3_lfps_basic",
        "COVERAGE_ID": "cg_gone",
    }])
    _write_manifest(bare_root, testplan_sources=ts)
    report = dt.assemble_digital_thread(bare_root)
    link = report["chains"][0]["links"]["coverage_bin"]
    assert link["status"] == dt.LINK_BROKEN


def test_test_link_not_available_when_no_matching_vplan_item(bare_root):
    _write_requirements_csv(bare_root, [{
        "REQ_ID": "REQ-1", "VPLAN_ID": "VP-NOT-IN-TESTPLAN", "PATTERN_ID": "usb3_lfps_basic",
    }])
    _write_manifest(bare_root, testplan_sources=DEFAULT_TESTPLAN_SOURCES)
    report = dt.assemble_digital_thread(bare_root)
    links = report["chains"][0]["links"]
    assert links["test"]["status"] == dt.LINK_NOT_AVAILABLE
    assert links["coverage_bin"]["status"] == dt.LINK_NOT_AVAILABLE


def test_manifest_present_but_no_testplan_sources_is_not_available(bare_root):
    _write_requirements_csv(bare_root, [{"REQ_ID": "REQ-1", "VPLAN_ID": "VP-1"}])
    _write_manifest(bare_root, testplan_sources=None)
    report = dt.assemble_digital_thread(bare_root)
    links = report["chains"][0]["links"]
    assert links["test"]["status"] == dt.LINK_NOT_AVAILABLE
    assert links["coverage_bin"]["status"] == dt.LINK_NOT_AVAILABLE


# ---------------------------------------------------------------------------
# regression_evidence link: real golden_scenario capsule + freshness
# ---------------------------------------------------------------------------

@requires_git
def test_regression_evidence_linked_when_capsule_is_fresh(git_project):
    root, sha = git_project
    _write_requirements_csv(root, [{"REQ_ID": "REQ-1", "PATTERN_ID": "usb3_lfps_basic"}])
    _write_capsule(root, pattern="usb3_lfps_basic", requirements=["REQ-1"], verified_sha=sha)
    report = dt.assemble_digital_thread(root)
    link = report["chains"][0]["links"]["regression_evidence"]
    assert link["status"] == dt.LINK_LINKED
    assert link["evidence"]["requirement_corroborated"] is True


@requires_git
def test_regression_evidence_stale_after_a_real_rtl_change(git_project):
    root, sha = git_project
    _write_requirements_csv(root, [{"REQ_ID": "REQ-1", "PATTERN_ID": "usb3_lfps_basic"}])
    _write_capsule(root, pattern="usb3_lfps_basic", requirements=["REQ-1"], verified_sha=sha)
    (root / "rtl" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk, input rst_n);\nendmodule\n", encoding="utf-8")
    _commit(root, "real RTL behavioral change")
    report = dt.assemble_digital_thread(root)
    link = report["chains"][0]["links"]["regression_evidence"]
    assert link["status"] == dt.LINK_STALE
    assert report["chains"][0]["chain_status"] in (dt.TRACE_GAP, dt.TRACE_BROKEN)


def test_regression_evidence_gap_when_no_matching_capsule_recorded(bare_root):
    _write_requirements_csv(bare_root, [{"REQ_ID": "REQ-1", "PATTERN_ID": "usb3_lfps_basic"}])
    store = EvidenceStore(bare_root / ".dv-harness" / "evidence" / "evidence.duckdb")
    store.close()
    report = dt.assemble_digital_thread(bare_root)
    link = report["chains"][0]["links"]["regression_evidence"]
    assert link["status"] == dt.LINK_GAP


def test_regression_evidence_not_available_with_no_evidence_db(bare_root):
    _write_requirements_csv(bare_root, [{"REQ_ID": "REQ-1", "PATTERN_ID": "usb3_lfps_basic"}])
    report = dt.assemble_digital_thread(bare_root)
    link = report["chains"][0]["links"]["regression_evidence"]
    assert link["status"] == dt.LINK_NOT_AVAILABLE


# ---------------------------------------------------------------------------
# signoff link: real signoff_export.read_signoff_stage_status()
# ---------------------------------------------------------------------------

def test_signoff_link_linked_when_gate_verified(bare_root):
    _write_requirements_csv(bare_root, [{"REQ_ID": "REQ-1"}])
    _write_signoff_pass_state(bare_root)
    report = dt.assemble_digital_thread(bare_root)
    assert report["chains"][0]["links"]["signoff"]["status"] == dt.LINK_LINKED


def test_signoff_link_shared_across_every_chain(bare_root):
    _write_requirements_csv(bare_root, [
        {"REQ_ID": "REQ-1"}, {"REQ_ID": "REQ-2"},
    ])
    _write_signoff_pass_state(bare_root)
    report = dt.assemble_digital_thread(bare_root)
    assert len(report["chains"]) == 2
    for chain in report["chains"]:
        assert chain["links"]["signoff"]["status"] == dt.LINK_LINKED


# ---------------------------------------------------------------------------
# Full end-to-end TRACE_COMPLETE, assembled from every real source at once
# ---------------------------------------------------------------------------

@requires_git
def test_full_chain_assembled_from_every_real_source_is_trace_complete(git_project):
    root, sha = git_project
    _write_requirements_csv(root, [{
        "REQ_ID": "REQ-1", "SOURCE": "spec.pdf", "SCOPE": "usb3_link",
        "VPLAN_ID": "VP-1", "PATTERN_ID": "usb3_lfps_basic", "COVERAGE_ID": "cg_lfps",
    }])
    vplan_rows = [{"id": "VP-1", "requirement_refs": ["REQ-1"]}]
    _write_manifest(root, testplan_sources=DEFAULT_TESTPLAN_SOURCES)
    _write_capsule(root, pattern="usb3_lfps_basic", requirements=["REQ-1"], verified_sha=sha)
    _write_signoff_pass_state(root)

    report = dt.assemble_digital_thread(root, vplan_rows=vplan_rows)
    assert report["status"] == dt.TRACE_COMPLETE
    assert len(report["chains"]) == 1
    chain = report["chains"][0]
    assert chain["chain_status"] == dt.TRACE_COMPLETE
    for name in dt.LINK_NAMES:
        assert chain["links"][name]["status"] == dt.LINK_LINKED, (
            f"{name} unexpectedly {chain['links'][name]}")

    # Overall report-level fold is worst-wins over every chain, never an
    # average -- proven directly by a mixed second chain below.
    md = dt.render_digital_thread_markdown(report)
    assert "TRACE_COMPLETE" in md
    assert "REQ-1" in md


@requires_git
def test_overall_status_is_worst_wins_never_averaged(git_project):
    root, sha = git_project
    _write_requirements_csv(root, [
        {"REQ_ID": "REQ-GOOD", "VPLAN_ID": "VP-1", "PATTERN_ID": "usb3_lfps_basic",
         "COVERAGE_ID": "cg_lfps"},
        {"REQ_ID": "REQ-BAD", "VPLAN_ID": "VP-NOPE"},
    ])
    vplan_rows = [{"id": "VP-1", "requirement_refs": ["REQ-GOOD"]}]
    _write_manifest(root, testplan_sources=DEFAULT_TESTPLAN_SOURCES)
    _write_capsule(root, pattern="usb3_lfps_basic", requirements=["REQ-GOOD"], verified_sha=sha)
    _write_signoff_pass_state(root)

    report = dt.assemble_digital_thread(root, vplan_rows=vplan_rows)
    statuses = {c["req_id"]: c["chain_status"] for c in report["chains"]}
    assert statuses["REQ-GOOD"] == dt.TRACE_COMPLETE
    assert statuses["REQ-BAD"] == dt.TRACE_BROKEN
    # A single BROKEN chain outranks a TRACE_COMPLETE sibling -- the report's
    # own overall_status/`status` is never an average of the two.
    assert report["status"] == dt.TRACE_BROKEN


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def test_cli_reports_not_available_exit_2(bare_root):
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.digital_thread_traceability",
         "--root", str(bare_root), "--json"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == dt.REPORT_NOT_AVAILABLE


@requires_git
def test_cli_full_chain_exit_0(git_project):
    root, sha = git_project
    _write_requirements_csv(root, [{
        "REQ_ID": "REQ-1", "VPLAN_ID": "VP-1", "PATTERN_ID": "usb3_lfps_basic",
        "COVERAGE_ID": "cg_lfps",
    }])
    vplan_path = root / "vplan.json"
    vplan_path.write_text(json.dumps([{"id": "VP-1", "requirement_refs": ["REQ-1"]}]),
                          encoding="utf-8")
    _write_manifest(root, testplan_sources=DEFAULT_TESTPLAN_SOURCES)
    _write_capsule(root, pattern="usb3_lfps_basic", requirements=["REQ-1"], verified_sha=sha)
    _write_signoff_pass_state(root)

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.digital_thread_traceability",
         "--root", str(root), "--vplan-file", str(vplan_path), "--json"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == dt.TRACE_COMPLETE


# ---------------------------------------------------------------------------
# Vocabulary hygiene
# ---------------------------------------------------------------------------

def test_vocabulary_never_collides_with_models_status():
    # Re-run the module's own import-time guard directly, so a future edit
    # that reintroduces a collision fails this test even if it somehow
    # slipped past import (e.g. under -O).
    dt.assert_no_verification_verdict_vocabulary()
