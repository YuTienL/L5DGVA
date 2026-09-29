"""Tests for `dv_harness/ip_ownership_conflict.py`: the IP-level
(single-subsystem) VIP-vs-legacy-BFM active/passive ownership conflict check.

Every fixture is a small synthetic dict/JSON file built inline -- a
`vip_config.vip_instances` shape matching `env_manifest.parse_vip_config_
dump()`'s own real schema, a connectivity-matrix rows list matching
`connectivity.build_connectivity_matrix()`'s own real column set, and a
caller-declared legacy BFM/driver list (there is no real producer for that
half in this codebase, exactly as the module docstring states).

The suite proves the real conflict path AND, in the mutate-one-defect style
this project's suites already use, five negative controls that must NOT read
as CONFLICT: no legacy declared at all, a passive legacy driver, a passive
VIP, an unmatched port_id, a fabricated "VIP" that is really a NO_VIP marker,
and an undeclared legacy active/passive with no connectivity evidence.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import connectivity as conn
from dv_harness import ip_ownership_conflict as ioc
from dv_harness import system_resource_inventory as sri


PORT = "tb_top.dut.usb3_if"


def _vip_instance(instance_path=PORT, vip_type="svt_usb3_agent", config_fields=None):
    return {"instance_path": instance_path, "vip_type": vip_type,
            "config_fields": config_fields or {}}


def _manifest(vip_instances):
    return {"vip_config": {"status": "CAPTURED", "vip_instances": list(vip_instances)}}


def _connectivity_row(dut_instance="tb_top.dut", interface="usb3_if",
                       active_passive="active", bind_target=PORT, vip_type="svt_usb3_agent"):
    return {"dut_instance": dut_instance, "interface": interface, "direction": "",
            "role": "", "vip_type": vip_type, "count": 1,
            "active_passive": active_passive, "bind_target": bind_target, "tier": "",
            "protocol": "", "fabric_side_role": ""}


def _legacy(port_id=PORT, driver_name="legacy_usb3_bfm", active_passive="active",
            evidence="tb/legacy_usb3_bfm.sv:1: hand-written BFM class"):
    return {"port_id": port_id, "driver_name": driver_name,
            "active_passive": active_passive, "evidence": evidence}


# ===========================================================================
# Positive path: a real conflict
# ===========================================================================

def test_real_vip_and_active_legacy_bfm_on_same_port_is_a_conflict():
    manifest = _manifest([_vip_instance()])
    rows = [_connectivity_row()]
    report = ioc.analyze_ip_ownership_conflict(
        manifest, legacy_bfm_declarations=[_legacy()], connectivity_rows=rows)

    assert report["status"] == ioc.STATUS_CONFLICT
    assert len(report["conflicts"]) == 1
    finding = report["conflicts"][0]
    assert finding["sub_status"] == ioc.PAIR_CONFLICT
    assert finding["vip_instance_path"] == PORT
    assert finding["legacy_driver_name"] == "legacy_usb3_bfm"
    assert not report["cleared"]
    assert not report["undetermined"]


def test_conflict_reuses_sys12_vocabulary_verbatim_not_a_second_spelling():
    manifest = _manifest([_vip_instance()])
    report = ioc.analyze_ip_ownership_conflict(
        manifest, legacy_bfm_declarations=[_legacy()], connectivity_rows=[_connectivity_row()])
    finding = report["conflicts"][0]
    # Reused, not restated: the exact same tokens system_resource_inventory.py
    # itself defines for the identical concept.
    assert finding["relationship"] == sri.REL_DRIVER_CONFLICT
    assert finding["resolution"] == sri.INTEGRATION_STOPPED
    assert finding["preferred_model"] == sri.SYS12_PREFERRED_MODEL
    assert ioc.PAIR_CONFLICT == sri.REL_DRIVER_CONFLICT


def test_multiple_legacy_entries_one_conflict_one_clear_still_reports_conflict():
    manifest = _manifest([_vip_instance()])
    rows = [_connectivity_row()]
    legacy = [
        _legacy(port_id=PORT, driver_name="conflicting_bfm", active_passive="active"),
        _legacy(port_id="tb_top.dut.no_such_port", driver_name="unrelated_bfm"),
    ]
    report = ioc.analyze_ip_ownership_conflict(
        manifest, legacy_bfm_declarations=legacy, connectivity_rows=rows)
    assert report["status"] == ioc.STATUS_CONFLICT
    assert len(report["conflicts"]) == 1
    assert len(report["cleared"]) == 1
    assert report["cleared"][0]["sub_status"] == ioc.PAIR_CLEAR_NO_VIP_MATCH


# ===========================================================================
# Negative controls -- must NOT read as CONFLICT
# ===========================================================================

def test_no_legacy_declared_is_not_applicable():
    manifest = _manifest([_vip_instance()])
    report = ioc.analyze_ip_ownership_conflict(manifest, legacy_bfm_declarations=None)
    assert report["status"] == ioc.STATUS_NOT_APPLICABLE
    assert report["legacy_declaration_count"] == 0
    assert report["conflicts"] == []

    report_empty_list = ioc.analyze_ip_ownership_conflict(manifest, legacy_bfm_declarations=[])
    assert report_empty_list["status"] == ioc.STATUS_NOT_APPLICABLE


def test_passive_legacy_driver_is_clear_not_conflict():
    manifest = _manifest([_vip_instance()])
    rows = [_connectivity_row()]
    report = ioc.analyze_ip_ownership_conflict(
        manifest, legacy_bfm_declarations=[_legacy(active_passive="passive")],
        connectivity_rows=rows)
    assert report["status"] == ioc.STATUS_CLEAR
    assert report["cleared"][0]["sub_status"] == ioc.PAIR_CLEAR_LEGACY_PASSIVE
    assert not report["conflicts"]


def test_passive_vip_with_active_legacy_driver_is_clear_not_conflict():
    manifest = _manifest([_vip_instance()])
    rows = [_connectivity_row(active_passive="passive")]
    report = ioc.analyze_ip_ownership_conflict(
        manifest, legacy_bfm_declarations=[_legacy(active_passive="active")],
        connectivity_rows=rows)
    assert report["status"] == ioc.STATUS_CLEAR
    assert report["cleared"][0]["sub_status"] == ioc.PAIR_CLEAR_VIP_PASSIVE
    assert not report["conflicts"]


def test_unmatched_port_id_is_clear_no_fuzzy_matching():
    manifest = _manifest([_vip_instance()])
    rows = [_connectivity_row()]
    report = ioc.analyze_ip_ownership_conflict(
        manifest,
        legacy_bfm_declarations=[_legacy(port_id="tb_top.dut.usb3_if_TYPO")],
        connectivity_rows=rows)
    assert report["status"] == ioc.STATUS_CLEAR
    assert report["cleared"][0]["sub_status"] == ioc.PAIR_CLEAR_NO_VIP_MATCH
    assert not report["conflicts"]


def test_fabricated_vip_that_is_really_a_no_vip_marker_never_conflicts():
    """Mutate-one-defect control on the positive-path fixture: change ONLY
    the vip_instance's vip_type to a real connectivity.NO_VIP_MARKERS value.
    An entry like this is not a real VIP agent (system_resource_inventory.py
    applies the identical exclusion), so the same port/legacy pair that
    conflicted above must now report no conflict at all."""
    manifest = _manifest([_vip_instance(vip_type="NONE")])
    rows = [_connectivity_row(vip_type="NONE")]
    report = ioc.analyze_ip_ownership_conflict(
        manifest, legacy_bfm_declarations=[_legacy()], connectivity_rows=rows)
    assert report["status"] != ioc.STATUS_CONFLICT
    assert report["vip_instance_count"] == 0
    assert report["cleared"][0]["sub_status"] == ioc.PAIR_CLEAR_NO_VIP_MATCH


def test_legacy_active_passive_undeclared_is_undetermined_not_clear_or_conflict():
    manifest = _manifest([_vip_instance()])
    rows = [_connectivity_row()]
    report = ioc.analyze_ip_ownership_conflict(
        manifest, legacy_bfm_declarations=[_legacy(active_passive="sideways")],
        connectivity_rows=rows)
    assert report["status"] == ioc.STATUS_UNKNOWN
    assert report["undetermined"][0]["sub_status"] == ioc.PAIR_UNDETERMINED_LEGACY_UNDECLARED
    assert not report["conflicts"]


def test_active_legacy_with_no_connectivity_rows_is_undetermined_never_a_guessed_conflict():
    """Evidence Truth Rule: with no connectivity_rows supplied, this module
    must never GUESS the VIP is active just because a legacy driver claims
    the same port -- it must report UNKNOWN, honestly distinct from CLEAR."""
    manifest = _manifest([_vip_instance()])
    report = ioc.analyze_ip_ownership_conflict(
        manifest, legacy_bfm_declarations=[_legacy()], connectivity_rows=None)
    assert report["status"] == ioc.STATUS_UNKNOWN
    assert report["undetermined"][0]["sub_status"] == ioc.PAIR_UNDETERMINED_NO_CONNECTIVITY
    assert not report["conflicts"]


def test_active_legacy_with_connectivity_rows_but_no_matching_row_is_undetermined():
    manifest = _manifest([_vip_instance()])
    unrelated_row = _connectivity_row(dut_instance="tb_top.dut", interface="other_if",
                                       bind_target="tb_top.dut.other_if")
    report = ioc.analyze_ip_ownership_conflict(
        manifest, legacy_bfm_declarations=[_legacy()], connectivity_rows=[unrelated_row])
    assert report["status"] == ioc.STATUS_UNKNOWN
    assert report["undetermined"][0]["sub_status"] == ioc.PAIR_UNDETERMINED_NO_MATCHING_ROW


# ===========================================================================
# Vocabulary separation from SYS-11's cross-subsystem classes
# ===========================================================================

def test_report_status_conflict_is_not_a_restated_sys11_relationship_class():
    """The report-level STATUS_CONFLICT is a NEW, coarser, IP-scoped token
    (this check has no per-pair relationship classification of its own) --
    it must never collide with `sri.REL_DRIVER_CONFLICT`, the SYS-11 class it
    stands beside. `UNKNOWN` is deliberately excluded from this check: it is
    a generic honest-absence word this codebase already reuses across many
    unrelated modules (confidence_calibration, waiver_store, ...), not
    proprietary SYS-11 vocabulary, and SYS-11's own `REL_UNKNOWN` happens to
    share that common English word without either module restating the
    other's CONCEPT."""
    assert ioc.STATUS_CONFLICT != sri.REL_DRIVER_CONFLICT
    non_generic = set(sri.RELATIONSHIP_CLASSES) - {sri.REL_UNKNOWN}
    assert set(ioc.REPORT_STATUSES).isdisjoint(non_generic)


# ===========================================================================
# Rendering
# ===========================================================================

def test_format_report_names_scope_and_status():
    manifest = _manifest([_vip_instance()])
    report = ioc.analyze_ip_ownership_conflict(
        manifest, legacy_bfm_declarations=[_legacy()], connectivity_rows=[_connectivity_row()])
    text = ioc.format_report(report)
    assert "CONFLICT" in text
    assert "detection only" in text
    assert "legacy_usb3_bfm" in text


# ===========================================================================
# Real CLI subprocess, exit codes
# ===========================================================================

def _write(path: Path, obj) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def _run_cli(env_manifest_path, legacy_path=None, connectivity_path=None):
    argv = [sys.executable, "-m", "dv_harness.ip_ownership_conflict",
            "--env-manifest", str(env_manifest_path), "--json"]
    if legacy_path is not None:
        argv += ["--legacy-bfm", str(legacy_path)]
    if connectivity_path is not None:
        argv += ["--connectivity-rows", str(connectivity_path)]
    repo_root = Path(__file__).resolve().parents[1]
    return subprocess.run(argv, cwd=str(repo_root), capture_output=True, text=True)


def test_cli_exit_code_1_on_real_conflict(tmp_path):
    manifest_path = _write(tmp_path / "env.manifest.json", _manifest([_vip_instance()]))
    legacy_path = _write(tmp_path / "legacy_bfm.json", [_legacy()])
    conn_path = _write(tmp_path / "connectivity_rows.json", [_connectivity_row()])
    result = _run_cli(manifest_path, legacy_path, conn_path)
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == ioc.STATUS_CONFLICT


def test_cli_exit_code_2_on_not_applicable(tmp_path):
    manifest_path = _write(tmp_path / "env.manifest.json", _manifest([_vip_instance()]))
    result = _run_cli(manifest_path)
    assert result.returncode == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == ioc.STATUS_NOT_APPLICABLE


def test_cli_exit_code_0_on_clear(tmp_path):
    manifest_path = _write(tmp_path / "env.manifest.json", _manifest([_vip_instance()]))
    legacy_path = _write(tmp_path / "legacy_bfm.json", [_legacy(active_passive="passive")])
    conn_path = _write(tmp_path / "connectivity_rows.json", [_connectivity_row()])
    result = _run_cli(manifest_path, legacy_path, conn_path)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == ioc.STATUS_CLEAR
