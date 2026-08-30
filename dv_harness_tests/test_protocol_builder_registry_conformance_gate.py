"""Tests for tools/verification_flow/protocol_builder_registry_conformance_gate.py
(see plan-protocol-registry-crosscheck design pass, 2026-08-28)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_gate(registry_root, profile):
    tmp = Path(tempfile.mkdtemp())
    try:
        infile = tmp / "profile.json"
        infile.write_text(json.dumps(profile), encoding="utf-8")
        script = ROOT / "tools" / "verification_flow" / "protocol_builder_registry_conformance_gate.py"
        r = subprocess.run(
            [sys.executable, str(script), "--registry-root", str(registry_root), "--profile", str(infile)],
            capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        shutil.rmtree(tmp)


# Real registry item keys for "usb" (verified against the actual
# .dv-harness/builder/protocol_builder_registry.json content):
#   discover: host_device_role, usb2_usb3_mode, port_topology, phy_controller_boundary
#   build: vip_topology, enumeration, usb2_speed_modes, usb3_ltssm_lfps_ts_patterns,
#          endpoint_transfer_sequences, scoreboard, error_injection,
#          coverage_assertions_smoke_tests

def _complete_usb_profile(**overrides):
    profile = {
        "protocol": "usb",
        "discover_items": [
            {"key": "host_device_role", "status": "SATISFIED", "evidence": "RTL top shows device-mode only"},
            {"key": "usb2_usb3_mode", "status": "SATISFIED", "evidence": "spec section 4.2"},
            {"key": "port_topology", "status": "SATISFIED", "evidence": "single port, device"},
            {"key": "phy_controller_boundary", "status": "SATISFIED", "evidence": "utmi_phy_if.sv"},
        ],
        "build_items": [
            {"key": "vip_topology", "status": "SATISFIED", "evidence": "1 device agent"},
            {"key": "enumeration", "status": "SATISFIED", "evidence": "enum_test.sv"},
            {"key": "usb2_speed_modes", "status": "SATISFIED", "evidence": "HS/FS covered"},
            {"key": "usb3_ltssm_lfps_ts_patterns", "status": "WAIVED",
             "waiver_approved": True, "waiver_evidence": "USB2-only DUT, no SS PHY"},
            {"key": "endpoint_transfer_sequences", "status": "SATISFIED", "evidence": "bulk/int/iso tests"},
            {"key": "scoreboard", "status": "SATISFIED", "evidence": "usb_scoreboard.sv"},
            {"key": "error_injection", "status": "SATISFIED", "evidence": "babble/timeout tests"},
            {"key": "coverage_assertions_smoke_tests", "status": "SATISFIED", "evidence": "smoke_test.sv"},
        ],
    }
    profile.update(overrides)
    return profile


def test_pass_when_all_discover_and_build_items_covered():
    rc, out = _run_gate(ROOT, _complete_usb_profile())
    assert rc == 0 and out["status"] == "PASS"
    assert out["protocol"] == "usb"
    assert out["discover_covered"] == 4
    assert out["build_covered"] == 8


def test_fail_missing_checklist_items_when_one_dropped():
    profile = _complete_usb_profile()
    profile["build_items"] = [i for i in profile["build_items"] if i["key"] != "error_injection"]
    rc, out = _run_gate(ROOT, profile)
    assert rc != 0
    assert out["reason"] == "MISSING_CHECKLIST_ITEMS"
    assert "error injection" in out["missing"]["build"]


def test_fail_fabricated_checklist_key_not_in_registry():
    profile = _complete_usb_profile()
    profile["discover_items"].append({"key": "made_up_thing", "status": "SATISFIED", "evidence": "x"})
    rc, out = _run_gate(ROOT, profile)
    assert rc != 0
    assert out["reason"] == "FABRICATED_CHECKLIST_KEY"
    assert out["key"] == "made_up_thing"


def test_fail_fabricated_key_crossing_protocol_namespace():
    # A real key from "amba4-soc" submitted while protocol is "usb" -- proves
    # namespace-crossing is caught, not just made-up strings.
    profile = _complete_usb_profile()
    profile["build_items"].append({"key": "address_decoder_model", "status": "SATISFIED", "evidence": "x"})
    rc, out = _run_gate(ROOT, profile)
    assert rc != 0
    assert out["reason"] == "FABRICATED_CHECKLIST_KEY"


def test_fail_unapproved_waiver():
    profile = _complete_usb_profile()
    for item in profile["build_items"]:
        if item["key"] == "usb3_ltssm_lfps_ts_patterns":
            item["waiver_approved"] = False
    rc, out = _run_gate(ROOT, profile)
    assert rc != 0
    assert out["reason"] == "UNAPPROVED_WAIVER"


def test_fail_invalid_item_status():
    profile = _complete_usb_profile()
    profile["discover_items"][0]["status"] = "MAYBE"
    rc, out = _run_gate(ROOT, profile)
    assert rc != 0
    assert out["reason"] == "INVALID_ITEM_STATUS"


def test_fail_satisfied_without_evidence():
    profile = _complete_usb_profile()
    del profile["discover_items"][0]["evidence"]
    rc, out = _run_gate(ROOT, profile)
    assert rc != 0
    assert out["reason"] == "INVALID_ITEM_STATUS"


def test_fail_unknown_protocol_not_in_registry():
    profile = _complete_usb_profile(protocol="some-custom-protocol")
    rc, out = _run_gate(ROOT, profile)
    assert rc != 0
    assert out["reason"] == "UNKNOWN_PROTOCOL"


def test_pass_escape_hatch_for_unregistered_protocol():
    rc, out = _run_gate(ROOT, {"registry_applicable": False,
                                "registry_not_applicable_reason": "custom in-house protocol, not in registry"})
    assert rc == 0 and out["status"] == "SKIPPED_NOT_APPLICABLE"


def test_fail_escape_hatch_without_justification():
    rc, out = _run_gate(ROOT, {"registry_applicable": False})
    assert rc != 0
    assert out["reason"] == "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"


def test_fail_duplicate_checklist_key():
    profile = _complete_usb_profile()
    profile["discover_items"].append(dict(profile["discover_items"][0]))
    rc, out = _run_gate(ROOT, profile)
    assert rc != 0
    assert out["reason"] == "DUPLICATE_CHECKLIST_KEY"


# --- protocol-identity cross-check (2026-08-29, industrial-grade-audit
# follow-up: self-declared `protocol` was NEVER independently checked
# against any real evidence before this) --------------------------------

def _complete_pcie_profile_with_evidence(evidence_by_key):
    """Real 'pcie' registry keys (verified against
    protocol_builder_registry.json's live 'pcie' entry) paired with
    caller-supplied evidence text per key, so tests can control exactly
    what the cited evidence says without touching key validation at all."""
    discover_keys = ["rc_ep_switch_role", "gen2_gen6", "lane_width",
                      "serial_pipe_controller_boundary"]
    build_keys = ["vip_topology", "ltssm_link_training", "configuration_space",
                  "bar", "tlp_completion_scoreboard", "msi_msi_x",
                  "aer_error_injection", "aspm_ltr",
                  "sr_iov_ats_pasid_pri_where_applicable",
                  "coverage_assertions_smoke_tests"]

    def _item(key):
        text = evidence_by_key[key]
        if key == "sr_iov_ats_pasid_pri_where_applicable":
            return {"key": key, "status": "WAIVED", "waiver_approved": True,
                     "waiver_evidence": text}
        return {"key": key, "status": "SATISFIED", "evidence": text}

    return {
        "protocol": "pcie",
        "discover_items": [_item(k) for k in discover_keys],
        "build_items": [_item(k) for k in build_keys],
    }


def test_pass_when_declared_protocol_confirmed_by_its_own_cited_evidence():
    # Genuine pcie evidence (mentions pcie-distinctive vocabulary: TLP,
    # LTSSM/link training, AER, MSI) -> declared "pcie" is corroborated.
    evidence = {
        "rc_ep_switch_role": "root_complex_top.sv instantiates RC role only",
        "gen2_gen6": "spec section 3.1 says Gen4 support",
        "lane_width": "x4 lane width confirmed in pcie_phy_if.sv",
        "serial_pipe_controller_boundary": "PIPE interface defined in pcie_pipe_if.sv",
        "vip_topology": "1 RC VIP, 1 EP DUT",
        "ltssm_link_training": "ltssm_monitor.sv covers link training states",
        "configuration_space": "config_space_test.sv",
        "bar": "BAR0/BAR1 sized per config_space_test.sv",
        "tlp_completion_scoreboard": "tlp_scoreboard.sv checks completion TLPs",
        "msi_msi_x": "msix_test.sv",
        "aer_error_injection": "aer_test.sv injects correctable errors",
        "aspm_ltr": "aspm_test.sv",
        "sr_iov_ats_pasid_pri_where_applicable": "no SR-IOV support in this EP, waived",
        "coverage_assertions_smoke_tests": "smoke_test.sv",
    }
    rc, out = _run_gate(ROOT, _complete_pcie_profile_with_evidence(evidence))
    assert rc == 0 and out["status"] == "PASS"
    assert out["protocol"] == "pcie"


def test_pass_when_evidence_is_generic_with_no_protocol_signal_either_way():
    # No protocol-distinctive keyword at all, in either direction -- must
    # NOT be flagged just for lacking self-confirmation (conservative check:
    # only blocks on an actual CONTRADICTION, never on mere silence).
    evidence = {k: "confirmed via internal design review, see team wiki"
                for k in ["rc_ep_switch_role", "gen2_gen6", "lane_width",
                          "serial_pipe_controller_boundary", "vip_topology",
                          "ltssm_link_training", "configuration_space", "bar",
                          "tlp_completion_scoreboard", "msi_msi_x",
                          "aer_error_injection", "aspm_ltr",
                          "coverage_assertions_smoke_tests"]}
    evidence["sr_iov_ats_pasid_pri_where_applicable"] = "not applicable, waived per review"
    rc, out = _run_gate(ROOT, _complete_pcie_profile_with_evidence(evidence))
    assert rc == 0 and out["status"] == "PASS"


def test_fail_protocol_evidence_mismatch_declares_pcie_with_usb_evidence():
    # Valid pcie checklist KEYS (so key validation above is a non-issue) but
    # every item's cited evidence is actually USB material -- the exact
    # confirmed gap: self-declared protocol never checked against evidence.
    evidence = {
        "rc_ep_switch_role": "utmi_phy_if.sv shows usb2 device controller boundary",
        "gen2_gen6": "usb2 high speed only, no multi-generation concept",
        "lane_width": "single-port usb device, no lane concept",
        "serial_pipe_controller_boundary": "usb phy boundary in utmi_phy_if.sv",
        "vip_topology": "1 usb device agent, see usb_scoreboard.sv",
        "ltssm_link_training": "usb3 not implemented, usb2-only per spec",
        "configuration_space": "usb enumeration replaces this, see enum_test.sv",
        "bar": "no usb equivalent, see usb_scoreboard.sv",
        "tlp_completion_scoreboard": "usb_scoreboard.sv checks usb bulk and iso transfers",
        "msi_msi_x": "usb signals via endpoint transfers instead, see enum_test.sv",
        "aer_error_injection": "babble/timeout tests reflect usb2 error handling",
        "aspm_ltr": "usb2 suspend/resume only, see power_test.sv",
        "sr_iov_ats_pasid_pri_where_applicable": "not needed for a usb2-only endpoint device",
        "coverage_assertions_smoke_tests": "smoke_test.sv covers usb enumeration and bulk transfer paths",
    }
    rc, out = _run_gate(ROOT, _complete_pcie_profile_with_evidence(evidence))
    assert rc != 0
    assert out["reason"] == "PROTOCOL_EVIDENCE_MISMATCH"
    assert out["protocol"] == "pcie"
    assert out["suspected_protocol"] == "usb"
    assert "usb2" in out["matched_keywords"] or "usb" in out["matched_keywords"]
