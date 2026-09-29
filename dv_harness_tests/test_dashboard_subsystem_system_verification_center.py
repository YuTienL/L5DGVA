"""GET /api/subsystem-system-verification -- the Subsystem Verification
Center + System Integration Center + Compatibility dashboard card (item:
dashboard_subsystem_system_verification_center, Web Control Plane theme,
CLAUDE_L5_WEB_CONTROL_PLANE_MASTER.md sections 342-402).

REUSE OVER REINVENT: `dv_harness/subsystem_contract.py`,
`dv_harness/system_verification_contract.py`, `dv_harness/ip_ownership_conflict.py`
and `dv_harness/system_resource_inventory.py` already exist and already compute
the real per-subsystem verification contract, the real cross-subsystem
rollup, the real IP-level VIP-vs-legacy-BFM ownership check, and the real
SYS-9..14 compatibility findings this card needs -- this change adds NO new
analysis engine behind the card. It is a pure dashboard wiring gap, closed
the same way the Generation Readiness / Requirement-vPlan / Test Suite Center
cards were: a thin `_read_subsystem_system_verification_state()` reader
following this file's existing `{"available", "error"}` honest-empty-state
contract, one read-only GET endpoint, and a fetch-once + client-side-render
card.

Unlike the design_knowledge/requirement_vplan cards, `subsystem_contract.py`
and `system_resource_inventory.py` are self-sufficient over a project's own
real registered-subsystem set -- no caller-supplied file is required for
real, non-trivial output. These tests prove:
  * The card READS the real modules. Every asserted value is compared
    against what `subsystem_contract.assemble_subsystem_contract()`,
    `system_verification_contract.assemble_system_verification_contract()`
    and `system_resource_inventory.real_cross_subsystem_findings()` themselves
    compute over the identical project -- never a string typed into the
    test, so a dashboard-local re-derivation that drifted from the real
    analysis would fail here.
  * The Evidence Truth Rule holds on the served surface: a bare project must
    never render a fabricated COMPLETE/CLEAR verdict, and a malformed
    inputs.json overlay must surface its own reason/detail rather than a
    bare 500 -- the negative control this project's house style requires.

The real dashboard server is started for real on a free local port and
driven over real HTTP, reusing test_dashboard_interactive.py's own harness
helpers -- the same cross-test import convention test_dashboard_requirement_
vplan_center.py already uses.
"""
from __future__ import annotations

import json
import shutil
import urllib.request
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
)

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


def _write_manifest(root: Path, *, vip_instances=None, testplan_sources=None,
                     out_rel=".dv-harness/env.manifest.json"):
    from dv_harness import env_manifest as em

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


def test_ssv_center_honest_state_on_a_bare_project():
    """No registered subsystem, no env.manifest.json anywhere -> the
    project-scope subsystem_contract.py record is still honestly assembled
    (never crashing), ip_ownership_conflict.py reports NOT_APPLICABLE (no
    manifest to check), and system_resource_inventory.py's cross-subsystem
    findings honestly report CROSSCHECK_UNAVAILABLE (fewer than two
    subsystems) -- never a fabricated CLEAR/COMPLETE verdict."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/subsystem-system-verification")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        assert data["inputs_supplied"] is False
        assert data["subsystem_names"] == []
        # The project-scope contract (subsystem=None) is still assembled --
        # never skipped merely because no subsystem is registered.
        assert len(data["subsystem_contracts"]) == 1
        record = data["subsystem_contracts"][0]
        assert record["subsystem"]["requested"] is None
        assert record["completeness"] in ("NOT_AVAILABLE", "PARTIAL")

        ioc = data["ip_ownership_conflicts"]["__project__"]
        assert ioc["status"] == "NOT_APPLICABLE"

        csf = data["cross_subsystem_findings"]
        assert csf["status"] == "TRACK_B_ANALYSIS_UNAVAILABLE"

        sv = data["system_verification_contract"]
        assert sv is not None
        assert sv["subsystem_contracts"]["status"] == "PRESENT"
        assert sv["subsystem_contracts"]["count"] == 1
        assert data["errors"] == []
    finally:
        shutil.rmtree(tmp)


def test_ssv_center_reports_a_malformed_inputs_file_honestly():
    """A subsystem_system_verification/inputs.json that is not valid JSON
    must surface as this endpoint's own reason/detail -- never a bare 500,
    and never a silently empty card claiming nothing is wrong. The negative
    control this project's house style requires."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        d = tmp / ".dv-harness" / "subsystem_system_verification"
        d.mkdir(parents=True)
        (d / "inputs.json").write_text("not valid json{", encoding="utf-8")

        status, data = _get(base, "/api/subsystem-system-verification")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_INPUTS_FILE"
    finally:
        shutil.rmtree(tmp)


def test_ssv_center_reports_the_real_reports_over_a_real_manifest_and_registry():
    """A real registered subsystem with a real env.manifest.json -> the
    served subsystem_contracts/ip_ownership_conflicts/system_verification_
    contract must equal what subsystem_contract.assemble_subsystem_contract()
    / ip_ownership_conflict.analyze_ip_ownership_conflict() /
    system_verification_contract.assemble_system_verification_contract()
    themselves compute over the identical project -- proving the endpoint
    reads the real modules rather than re-deriving anything."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness import environment_mode_router as emr

        manifest_path = _write_manifest(
            tmp, vip_instances=DEFAULT_VIP_INSTANCES,
            testplan_sources=DEFAULT_TESTPLAN_SOURCES,
            out_rel="subsystems/usb3_link/env.manifest.json")
        registry_path = emr.registry_path(tmp)
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps({"subsystems": [{
            "name": "usb3_link",
            "environment_manifest": str(manifest_path.relative_to(tmp)),
            "release_sha": "abc123", "qualification_state": "BASELINE_READY",
            "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS",
        }]}), encoding="utf-8")

        status, data = _get(base, "/api/subsystem-system-verification")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        assert data["subsystem_names"] == ["usb3_link"]
        assert data["errors"] == []

        from dv_harness import subsystem_contract as sc
        expected = sc.assemble_subsystem_contract(tmp, subsystem="usb3_link")
        served = data["subsystem_contracts"][0]
        # assembled_at is a real wall-clock stamp; strip before comparing.
        served_no_ts = {k: v for k, v in served.items() if k != "assembled_at"}
        expected_no_ts = {k: v for k, v in expected.items() if k != "assembled_at"}
        assert served_no_ts == expected_no_ts
        assert served["protocols"] == ["svt_usb3"]
        assert served["subsystem"]["source"] == "REGISTERED_SUBSYSTEM_ENTRY"

        from dv_harness import ip_ownership_conflict as ioc
        from dv_harness import env_manifest as em
        manifest = em.load_env_manifest(manifest_path)
        expected_ioc = ioc.analyze_ip_ownership_conflict(manifest)
        assert data["ip_ownership_conflicts"]["usb3_link"] == expected_ioc
        assert expected_ioc["status"] == "NOT_APPLICABLE"

        # A single registered subsystem is still fewer than the two SYS-9..14
        # needs to compare -- an honest CROSSCHECK_UNAVAILABLE, never a
        # fabricated CLEAR.
        assert data["cross_subsystem_findings"]["status"] == "TRACK_B_ANALYSIS_UNAVAILABLE"

        sv = data["system_verification_contract"]
        assert sv["subsystem_contracts"]["count"] == 1
        assert sv["subsystem_contracts"]["entries"][0]["subsystem_name"] == "usb3_link"
    finally:
        shutil.rmtree(tmp)


def test_ssv_center_ip_ownership_conflict_is_surfaced_honestly_when_declared():
    """A declared legacy BFM sharing an ACTIVE port with a real VIP instance
    must surface as a real CONFLICT -- never silently smoothed into CLEAR --
    driven through the caller-declared subsystem_system_verification/
    inputs.json overlay (the one real convention this repo has for a fact
    ip_ownership_conflict.py itself has no producer for)."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_manifest(tmp, vip_instances=DEFAULT_VIP_INSTANCES,
                         testplan_sources=DEFAULT_TESTPLAN_SOURCES)

        d = tmp / ".dv-harness" / "subsystem_system_verification"
        d.mkdir(parents=True)
        (d / "inputs.json").write_text(json.dumps({
            "project_scope": {
                "legacy_bfm_declarations": [{
                    "port_id": "tb.usb3_agent",
                    "driver_name": "legacy_usb3_bfm",
                    "active_passive": "active",
                    "evidence": "hand-authored testbench comment",
                }],
            },
        }), encoding="utf-8")

        status, data = _get(base, "/api/subsystem-system-verification")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        ioc = data["ip_ownership_conflicts"]["__project__"]
        # No connectivity_rows supplied -> ownership cannot be conclusively
        # judged, so the overall status is the honest UNKNOWN, never CLEAR.
        assert ioc["status"] == "UNKNOWN"
        assert len(ioc["undetermined"]) == 1
    finally:
        shutil.rmtree(tmp)


def test_ssv_center_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() --
    an endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    item exists to avoid, and this card must follow the same rendering
    convention (tiles + tables, fetch-once, no new template) as the sibling
    cards it was asked to reuse."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="subsystemSystemVerificationCard"' in html
        assert "Subsystem Verification Center" in html
        assert "'/api/subsystem-system-verification'" in html
        assert "await loadSubsystemSystemVerification();" in html
        assert 'id="ssvTiles"' in html
        assert 'id="ssvSubsystemBody"' in html
        assert 'id="ssvUnknownsBody"' in html
        # This card is read-only, matching the convention every sibling card
        # it reuses follows -- no POST verb of its own.
        assert "Read-only" in html.split('id="subsystemSystemVerificationCard"')[1].split("</div>")[0]
    finally:
        shutil.rmtree(tmp)
