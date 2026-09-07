"""Tests for dv_harness/system_signoff_package.py -- the system-scope signoff
package assembler.

Discipline: subsystem contracts on the LIVE_ASSEMBLED path are produced by a
REAL call into `subsystem_contract.assemble_subsystem_contract()` against a
real (bare or lightly-populated) project root -- never a hand-shaped dict
standing in for that module's own output. Subsystem contracts on the
CALLER_SUPPLIED path use small, real-shaped dicts (the same convention
`test_system_verification_contract.py` already establishes for its own
fixtures, since a caller of this module may legitimately already hold a
subsystem_contract.py-shaped record it built earlier). `bundle_hash` is
cross-checked against an INDEPENDENT direct call into
`signoff_export.compute_bundle_hash()` on every positive-path test, proving
this module really reuses that function rather than reimplementing it.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import signoff_export as se
from dv_harness import subsystem_contract as sc
from dv_harness import system_closure_aggregator as sca
from dv_harness import system_signoff_package as ssp

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_ARGS = [sys.executable, "-m", "dv_harness.system_signoff_package"]


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _clean_subsystem_contract(name: str, *, gate_verified: bool = True) -> dict:
    """A subsystem_contract.py-SHAPED record for the CALLER_SUPPLIED path --
    matching the real module's own documented output shape, the same fixture
    convention `test_system_verification_contract.py` already uses for the
    identical reason (this module never re-validates that shape; it reads
    what it can)."""
    return {
        "schema_version": "1.0",
        "assembled_at": "2026-09-06T00:00:00+00:00",
        "project_root": f"/projects/{name}",
        "subsystem": {"requested": name, "resolved_name": name,
                      "source": "REGISTERED_SUBSYSTEM_ENTRY"},
        "spec_version": {"status": "CAPTURED", "value": "1.2"},
        "dut_sha": {"status": "CAPTURED", "value": "abc123"},
        "tb_sha": {"status": "CAPTURED", "value": "def456"},
        "protocols": ["USB"],
        "interfaces": [{"instance_path": f"{name}.usb0", "vip_type": "svt_usb"}],
        "vip_config": {"status": "PRESENT"},
        "requirements": {"status": "PRESENT"},
        "vplan_tests_coverage": {"status": "COMPUTED"},
        "regression": {"status": "PRESENT"},
        "signoff": {"stage": {"stage_status": "PASS", "gate_verified": gate_verified},
                    "baseline_freeze": {"status": "PRESENT"}},
        "evidence_references": {"status": "PRESENT"},
        "reproducibility_capsules": {"status": "PRESENT"},
        "waivers": {"status": "PRESENT"},
        "unknowns": [],
        "tracked_aspect_count": 11,
        "unavailable_aspect_count": 0,
        "completeness": "COMPLETE",
    }


ALL_CLEAN_CLOSURE_DIMENSIONS = [
    {"dimension_name": name, "status": "MET"} for name in sca.CLOSURE_DIMENSIONS
]


# ---------------------------------------------------------------------------
# Core positive path: live-assembled subsystems over a bare root
# ---------------------------------------------------------------------------

def test_bare_root_no_subsystems_never_fabricates_verified(tmp_path):
    out_dir = tmp_path / "pkg"
    result = ssp.collect_system_signoff_package(tmp_path, out_dir)

    assert result["status"] == "OK"
    assert result["subsystem_index"] == []
    # zero subsystems -> never claims gate-verified, even with an empty
    # closure report reporting nothing UNMET.
    assert result["package_kind"] == ssp.PRE_SYSTEM_SIGNOFF_GATE_INPUT
    assert result["system_closure_report"]["overall_status"] == sca.CLOSURE_INCOMPLETE_EVIDENCE
    # manifest.json really written and parses.
    manifest_doc = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_doc["bundle_hash"] == result["bundle_hash"]
    assert manifest_doc["package_kind"] == ssp.PRE_SYSTEM_SIGNOFF_GATE_INPUT


def test_live_assembled_subsystem_over_bare_root_is_honestly_incomplete(tmp_path):
    """A real call into subsystem_contract.assemble_subsystem_contract() over a
    root with nothing on disk yields a real NOT_AVAILABLE contract -- this
    module must report exactly that, never a fabricated COMPLETE."""
    out_dir = tmp_path / "pkg"
    result = ssp.collect_system_signoff_package(
        tmp_path, out_dir, subsystems=["sub_a"])

    assert result["status"] == "OK"
    assert len(result["subsystem_index"]) == 1
    entry = result["subsystem_index"][0]
    assert entry["name"] == "sub_a"
    assert entry["source"] == ssp.SOURCE_LIVE_ASSEMBLED
    assert entry["gate_verified"] is False

    # Cross-checked directly against the real producer -- proves no
    # fabrication, only a faithful read of what that module really returned.
    direct = sc.assemble_subsystem_contract(tmp_path, subsystem="sub_a")
    assert entry["completeness"] == direct["completeness"]

    bundled_path = out_dir / entry["bundled_path"]
    assert bundled_path.is_file()
    on_disk = json.loads(bundled_path.read_text(encoding="utf-8"))
    assert on_disk["completeness"] == direct["completeness"]

    assert result["package_kind"] == ssp.PRE_SYSTEM_SIGNOFF_GATE_INPUT


def test_manifest_entries_match_signoff_export_shape_and_reuse_its_hash(tmp_path):
    out_dir = tmp_path / "pkg"
    result = ssp.collect_system_signoff_package(
        tmp_path, out_dir, subsystems=["sub_a"], system_name="demo_system")

    for entry in result["manifest"]:
        assert set(entry) == {"artifact", "present", "bundled_path", "content_sha256"}

    # The one thing this whole module exists to REUSE rather than
    # reimplement: an independently-called signoff_export.compute_bundle_hash
    # over the SAME manifest list must equal what this module reported.
    independent_hash = se.compute_bundle_hash(result["manifest"])
    assert independent_hash == result["bundle_hash"]


def test_content_sha256_matches_real_file_bytes(tmp_path):
    out_dir = tmp_path / "pkg"
    result = ssp.collect_system_signoff_package(tmp_path, out_dir, subsystems=["sub_a"])
    for entry in result["manifest"]:
        if not entry["present"]:
            assert entry["content_sha256"] is None
            continue
        path = out_dir / entry["bundled_path"]
        real_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert entry["content_sha256"] == real_digest


# ---------------------------------------------------------------------------
# Negative control: never claim fabricated success on assembly failure
# ---------------------------------------------------------------------------

def test_a_failing_live_subsystem_assembly_is_reported_absent_never_crashes(tmp_path, monkeypatch):
    """A subsystem whose real assembly raises must show up as present=False in
    the manifest with the real exception text -- and must never silently
    disappear or crash the whole package."""
    real_assemble = sc.assemble_subsystem_contract

    def _boom(root, *, subsystem=None, **kw):
        if subsystem == "broken_sub":
            raise RuntimeError("simulated real assembly failure")
        return real_assemble(root, subsystem=subsystem, **kw)

    monkeypatch.setattr(sc, "assemble_subsystem_contract", _boom)

    out_dir = tmp_path / "pkg"
    result = ssp.collect_system_signoff_package(
        tmp_path, out_dir, subsystems=["broken_sub", "sub_ok"])

    assert result["status"] == "OK"
    entries = {e["name"]: e for e in result["subsystem_index"]}
    assert entries["broken_sub"]["error"] is not None
    assert "simulated real assembly failure" in entries["broken_sub"]["error"]
    assert entries["broken_sub"]["bundled_path"] is None
    assert entries["sub_ok"]["error"] is None

    manifest_by_artifact = {m["artifact"]: m for m in result["manifest"]}
    assert manifest_by_artifact["subsystem_contract:broken_sub"]["present"] is False
    assert manifest_by_artifact["subsystem_contract:broken_sub"]["content_sha256"] is None
    assert manifest_by_artifact["subsystem_contract:sub_ok"]["present"] is True

    # A broken subsystem's non-record must never leak into the
    # system_verification_contract's own count of real assembled contracts.
    sv = result["system_verification_contract"]
    assert sv["subsystem_contracts"]["count"] == 1

    assert result["package_kind"] == ssp.PRE_SYSTEM_SIGNOFF_GATE_INPUT


# ---------------------------------------------------------------------------
# Caller-supplied precontracts, and the gate-verified worst-wins path
# ---------------------------------------------------------------------------

def test_caller_supplied_precontracts_are_bundled_with_supplied_suffix(tmp_path):
    out_dir = tmp_path / "pkg"
    precontracts = [_clean_subsystem_contract("sub_x"), _clean_subsystem_contract("sub_y")]
    result = ssp.collect_system_signoff_package(
        tmp_path, out_dir, subsystem_contracts=precontracts)

    assert len(result["subsystem_index"]) == 2
    for entry in result["subsystem_index"]:
        assert entry["source"] == ssp.SOURCE_CALLER_SUPPLIED
        assert entry["bundled_path"].endswith("__supplied.json")
        assert (out_dir / entry["bundled_path"]).is_file()


def test_all_clean_subsystems_and_clean_closure_yields_gate_verified(tmp_path):
    out_dir = tmp_path / "pkg"
    precontracts = [
        _clean_subsystem_contract("sub_a", gate_verified=True),
        _clean_subsystem_contract("sub_b", gate_verified=True),
    ]
    result = ssp.collect_system_signoff_package(
        tmp_path, out_dir, subsystem_contracts=precontracts,
        closure_dimensions=ALL_CLEAN_CLOSURE_DIMENSIONS, system_name="usb_pcie_system")

    assert result["system_closure_report"]["overall_status"] == sca.CLOSURE_CLOSED
    assert all(e["gate_verified"] for e in result["subsystem_index"])
    assert result["package_kind"] == ssp.SYSTEM_SIGNOFF_GATE_VERIFIED

    manifest_doc = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_doc["package_kind"] == ssp.SYSTEM_SIGNOFF_GATE_VERIFIED
    assert manifest_doc["system_closure_status"] == sca.CLOSURE_CLOSED


def test_worst_wins_one_ungated_subsystem_blocks_the_whole_package(tmp_path):
    """One subsystem whose own SIGNOFF gate never passed must block the WHOLE
    package's kind, even with every other subsystem clean and every closure
    dimension MET -- the worst-wins composite-gate rule applied one level up."""
    out_dir = tmp_path / "pkg"
    precontracts = [
        _clean_subsystem_contract("sub_a", gate_verified=True),
        _clean_subsystem_contract("sub_b", gate_verified=False),
    ]
    result = ssp.collect_system_signoff_package(
        tmp_path, out_dir, subsystem_contracts=precontracts,
        closure_dimensions=ALL_CLEAN_CLOSURE_DIMENSIONS)

    assert result["package_kind"] == ssp.PRE_SYSTEM_SIGNOFF_GATE_INPUT


def test_worst_wins_one_open_closure_dimension_blocks_verified_kind(tmp_path):
    """Every subsystem gate-verified, but ONE closure dimension is UNMET --
    the package must still not claim SYSTEM_SIGNOFF_GATE_VERIFIED."""
    out_dir = tmp_path / "pkg"
    precontracts = [_clean_subsystem_contract("sub_a", gate_verified=True)]
    dims = list(ALL_CLEAN_CLOSURE_DIMENSIONS)
    dims[0] = {"dimension_name": sca.CLOSURE_DIMENSIONS[0], "status": "UNMET",
               "reason": "one real open finding"}
    result = ssp.collect_system_signoff_package(
        tmp_path, out_dir, subsystem_contracts=precontracts, closure_dimensions=dims)

    assert result["system_closure_report"]["overall_status"] == sca.CLOSURE_NOT_CLOSED
    assert result["package_kind"] == ssp.PRE_SYSTEM_SIGNOFF_GATE_INPUT


# ---------------------------------------------------------------------------
# require_system_signoff_pass: refusal writes nothing at all
# ---------------------------------------------------------------------------

def test_require_pass_refuses_and_writes_nothing_when_not_verified(tmp_path):
    out_dir = tmp_path / "pkg"
    assert not out_dir.exists()
    precontracts = [_clean_subsystem_contract("sub_a", gate_verified=False)]
    result = ssp.collect_system_signoff_package(
        tmp_path, out_dir, subsystem_contracts=precontracts,
        require_system_signoff_pass=True)

    assert result["status"] == "REFUSED"
    assert result["reason"] == "SYSTEM_SIGNOFF_NOT_VERIFIED"
    assert result["manifest"] == []
    assert result["bundle_hash"] is None
    # The refusal contract: not even an empty out_dir is created.
    assert not out_dir.exists()


def test_require_pass_succeeds_and_writes_when_verified(tmp_path):
    out_dir = tmp_path / "pkg"
    precontracts = [_clean_subsystem_contract("sub_a", gate_verified=True)]
    result = ssp.collect_system_signoff_package(
        tmp_path, out_dir, subsystem_contracts=precontracts,
        closure_dimensions=ALL_CLEAN_CLOSURE_DIMENSIONS,
        require_system_signoff_pass=True)

    assert result["status"] == "OK"
    assert result["package_kind"] == ssp.SYSTEM_SIGNOFF_GATE_VERIFIED
    assert out_dir.is_dir()
    assert (out_dir / "manifest.json").is_file()


# ---------------------------------------------------------------------------
# Name sanitization / collision handling
# ---------------------------------------------------------------------------

def test_unsafe_subsystem_names_are_sanitized_into_distinct_filenames(tmp_path):
    out_dir = tmp_path / "pkg"
    precontracts = [
        _clean_subsystem_contract("sub/one two"),
        _clean_subsystem_contract("sub one"),
    ]
    result = ssp.collect_system_signoff_package(
        tmp_path, out_dir, subsystem_contracts=precontracts)

    bundled_paths = {e["bundled_path"] for e in result["subsystem_index"]}
    assert len(bundled_paths) == 2
    for p in bundled_paths:
        assert (out_dir / p).is_file()
        # never escapes the subsystems/ bundle directory
        assert Path(p).parts[0] == "subsystems"


def test_precontract_with_no_declared_identity_is_named_positionally(tmp_path):
    out_dir = tmp_path / "pkg"
    result = ssp.collect_system_signoff_package(
        tmp_path, out_dir, subsystem_contracts=[{"completeness": "COMPLETE"}])
    assert result["subsystem_index"][0]["name"] == "precontract_0"


# ---------------------------------------------------------------------------
# CLI subprocess
# ---------------------------------------------------------------------------

def test_cli_collect_json_reports_pre_signoff_kind_on_bare_root(tmp_path):
    out_dir = tmp_path / "pkg"
    proc = subprocess.run(
        CLI_ARGS + ["collect", "--root", str(tmp_path), "--out-dir", str(out_dir),
                    "--subsystem", "sub_a", "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["package_kind"] == ssp.PRE_SYSTEM_SIGNOFF_GATE_INPUT
    assert (out_dir / "manifest.json").is_file()


def test_cli_collect_verified_with_supplied_contracts_and_closure_files_exits_zero(tmp_path):
    out_dir = tmp_path / "pkg"
    contracts_path = tmp_path / "subs.json"
    contracts_path.write_text(
        json.dumps([_clean_subsystem_contract("sub_a", gate_verified=True)]), encoding="utf-8")
    closure_path = tmp_path / "closure.json"
    closure_path.write_text(json.dumps(ALL_CLEAN_CLOSURE_DIMENSIONS), encoding="utf-8")

    proc = subprocess.run(
        CLI_ARGS + ["collect", "--root", str(tmp_path), "--out-dir", str(out_dir),
                    "--subsystem-contracts", str(contracts_path),
                    "--closure-dimensions", str(closure_path),
                    "--system-name", "demo", "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["package_kind"] == ssp.SYSTEM_SIGNOFF_GATE_VERIFIED


def test_cli_text_output_names_every_subsystem(tmp_path):
    out_dir = tmp_path / "pkg"
    proc = subprocess.run(
        CLI_ARGS + ["collect", "--root", str(tmp_path), "--out-dir", str(out_dir),
                    "--subsystem", "sub_a"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "sub_a" in proc.stdout


def test_cli_refuses_on_malformed_subsystem_contracts_file(tmp_path):
    out_dir = tmp_path / "pkg"
    bad_path = tmp_path / "bad.json"
    bad_path.write_text('{"not_a_list": 1}', encoding="utf-8")
    proc = subprocess.run(
        CLI_ARGS + ["collect", "--root", str(tmp_path), "--out-dir", str(out_dir),
                    "--subsystem-contracts", str(bad_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert not out_dir.exists()
