"""Tests for tools/verification_flow/rtl_first_architecture_discovery_gate.py.

Covers both the pre-existing shape-only checks (regression coverage -- these
already worked before this session's provenance hardening) and the new
`architectural_claims` / rtl_citation provenance requirement (2026-09-01,
RTL-first-architecture-discovery provenance audit): each architectural claim
(module/port/interface/register_block) must carry an `rtl_citation` naming a
real file, at a real line range, that actually contains the claimed name --
verified against a real filesystem fixture in every test below, never
trusted as agent-attested text.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "verification_flow" / "rtl_first_architecture_discovery_gate.py"

MINIMUM_AUTO_FIELDS = ["TOP", "HIERARCHY", "INTERFACE", "CLOCK_RESET", "PARAM_DEFINE", "PORT_CHANNEL"]


def _run_gate(state, cwd):
    p = cwd / "state.json"
    p.write_text(json.dumps(state), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(GATE), "--state", str(p)],
        cwd=str(cwd), capture_output=True, text=True, timeout=15,
    )
    out = json.loads((r.stdout or "").strip() or "{}")
    return r.returncode, out


def _write_rtl_fixture(cwd, rel_path="rtl/usb_top.v"):
    """Writes a small, realistic-shaped RTL fixture under cwd and returns its
    project-root-relative path string (posix separators, matching the
    citation convention). Line numbers below are load-bearing for the tests
    that cite specific lines -- keep them stable if this text changes."""
    rtl_dir = cwd / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    text = (
        "// line 1: header comment\n"          # 1
        "// line 2: header comment\n"           # 2
        "module usb_top (\n"                    # 3
        "    input  wire        phy_clk,\n"     # 4
        "    input  wire        phy_rst_n,\n"   # 5
        "    output wire [7:0]  utmi_data,\n"   # 6
        "    input  wire        axi_aclk\n"     # 7
        ");\n"                                  # 8
        "\n"                                    # 9
        "endmodule\n"                           # 10
    )
    (rtl_dir / "usb_top.v").write_text(text, encoding="utf-8")
    return "rtl/usb_top.v"


def _base_state(claims):
    return {
        "rtl_source_available": True,
        "architecture_document_required": False,
        "auto_discovered_fields": list(MINIMUM_AUTO_FIELDS),
        "asked_user_before_rtl_analysis": False,
        "unknown_items": [],
        "architecture_evidence_db_generated": True,
        "architectural_claims": claims,
        "lock_requested": False,
        "calibration_complete": False,
    }


# --- pre-existing shape-only checks (regression coverage) -------------------

def test_missing_rtl_source_still_fails(tmp_path):
    rc, out = _run_gate({"rtl_source_available": False}, tmp_path)
    assert rc != 0 and out == {"status": "FAIL", "reason": "RTL_SOURCE_REQUIRED_FOR_STEP5"}


def test_architecture_document_required_still_fails(tmp_path):
    rc, out = _run_gate(
        {"rtl_source_available": True, "architecture_document_required": True}, tmp_path)
    assert rc != 0 and out == {"status": "FAIL", "reason": "ARCHITECTURE_DOCUMENT_MUST_BE_OPTIONAL"}


def test_shallow_discovery_still_fails(tmp_path):
    rc, out = _run_gate(
        {"rtl_source_available": True, "architecture_document_required": False,
         "auto_discovered_fields": ["TOP"]}, tmp_path)
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "RTL_DISCOVERY_TOO_SHALLOW"


def test_unknown_item_without_next_action_still_fails(tmp_path):
    state = _base_state([])
    state["unknown_items"] = [{"name": "mystery_block", "confidence": "LOW"}]
    rc, out = _run_gate(state, tmp_path)
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "UNKNOWN_ARCHITECTURE_WITHOUT_CALIBRATION_ACTION"


def test_missing_evidence_db_flag_still_fails(tmp_path):
    state = _base_state([])
    state["architecture_evidence_db_generated"] = False
    rc, out = _run_gate(state, tmp_path)
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "NO_ARCHITECTURE_EVIDENCE_DATABASE"


# --- new: architectural_claims / rtl_citation provenance requirement --------

def test_missing_architectural_claims_field_fails():
    state = _base_state([])
    del state["architectural_claims"]
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        rc, out = _run_gate(state, Path(d))
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "ARCHITECTURAL_CLAIMS_MISSING"


def test_empty_architectural_claims_list_fails(tmp_path):
    rc, out = _run_gate(_base_state([]), tmp_path)
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "ARCHITECTURAL_CLAIMS_MISSING"


def test_valid_module_and_port_claims_pass(tmp_path):
    rel = _write_rtl_fixture(tmp_path)
    claims = [
        {"kind": "MODULE", "name": "usb_top", "rtl_citation": f"{rel}:3"},
        {"kind": "PORT", "name": "phy_clk", "rtl_citation": f"{rel}:4"},
    ]
    rc, out = _run_gate(_base_state(claims), tmp_path)
    assert rc == 0 and out["status"] == "PASS"


def test_citation_to_nonexistent_file_fails(tmp_path):
    claims = [{"kind": "MODULE", "name": "usb_top", "rtl_citation": "rtl/does_not_exist.v:3"}]
    rc, out = _run_gate(_base_state(claims), tmp_path)
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "UNVERIFIABLE_RTL_CITATION"
    assert "does_not_exist" in out["detail"]


def test_citation_with_fabricated_name_fails(tmp_path):
    # Real file, real line range -- but the claimed name genuinely never
    # appears anywhere near it. This is the exact fabrication case the audit
    # found: a plausible-looking, unbacked claim.
    rel = _write_rtl_fixture(tmp_path)
    claims = [{"kind": "MODULE", "name": "totally_invented_module_xyz", "rtl_citation": f"{rel}:3"}]
    rc, out = _run_gate(_base_state(claims), tmp_path)
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "UNVERIFIABLE_RTL_CITATION"
    assert "totally_invented_module_xyz" in out["detail"]


def test_malformed_citation_format_fails(tmp_path):
    rel = _write_rtl_fixture(tmp_path)
    claims = [{"kind": "MODULE", "name": "usb_top", "rtl_citation": f"{rel} line three"}]
    rc, out = _run_gate(_base_state(claims), tmp_path)
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "UNVERIFIABLE_RTL_CITATION"


def test_citation_line_range_past_end_of_file_fails(tmp_path):
    rel = _write_rtl_fixture(tmp_path)
    claims = [{"kind": "MODULE", "name": "usb_top", "rtl_citation": f"{rel}:9999"}]
    rc, out = _run_gate(_base_state(claims), tmp_path)
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "UNVERIFIABLE_RTL_CITATION"
    assert "past end of file" in out["detail"]


def test_citation_with_backwards_range_fails(tmp_path):
    rel = _write_rtl_fixture(tmp_path)
    claims = [{"kind": "MODULE", "name": "usb_top", "rtl_citation": f"{rel}:10-3"}]
    rc, out = _run_gate(_base_state(claims), tmp_path)
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "UNVERIFIABLE_RTL_CITATION"


def test_claim_missing_kind_fails_as_malformed(tmp_path):
    rel = _write_rtl_fixture(tmp_path)
    claims = [{"name": "usb_top", "rtl_citation": f"{rel}:3"}]
    rc, out = _run_gate(_base_state(claims), tmp_path)
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "ARCHITECTURAL_CLAIM_MALFORMED"


def test_claim_with_invalid_kind_fails_as_malformed(tmp_path):
    rel = _write_rtl_fixture(tmp_path)
    claims = [{"kind": "CLOCK_DOMAIN", "name": "usb_top", "rtl_citation": f"{rel}:3"}]
    rc, out = _run_gate(_base_state(claims), tmp_path)
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "ARCHITECTURAL_CLAIM_MALFORMED"


def test_claim_missing_name_fails_as_malformed(tmp_path):
    rel = _write_rtl_fixture(tmp_path)
    claims = [{"kind": "MODULE", "rtl_citation": f"{rel}:3"}]
    rc, out = _run_gate(_base_state(claims), tmp_path)
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "ARCHITECTURAL_CLAIM_MALFORMED"


def test_citation_slightly_off_line_within_tolerance_still_passes(tmp_path):
    # A citation of "around line 1" for a name that actually sits a few
    # lines away (module header at line 3) is still a real, honest citation
    # -- this is a spot-check with tolerance, not an exact-line requirement.
    rel = _write_rtl_fixture(tmp_path)
    claims = [{"kind": "MODULE", "name": "usb_top", "rtl_citation": f"{rel}:1"}]
    rc, out = _run_gate(_base_state(claims), tmp_path)
    assert rc == 0 and out["status"] == "PASS"


def test_citation_far_outside_tolerance_fails(tmp_path):
    # Same file, but the name is 10 files' worth of padding away from the
    # cited line -- well past the tolerance window.
    rtl_dir = tmp_path / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    lines = ["// padding line %d\n" % i for i in range(1, 40)]
    lines.insert(0, "module far_module (a, b);\n")
    (rtl_dir / "big.v").write_text("".join(lines), encoding="utf-8")
    claims = [{"kind": "MODULE", "name": "far_module", "rtl_citation": "rtl/big.v:30"}]
    rc, out = _run_gate(_base_state(claims), tmp_path)
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "UNVERIFIABLE_RTL_CITATION"


def test_multiple_claims_first_bad_one_reported(tmp_path):
    rel = _write_rtl_fixture(tmp_path)
    claims = [
        {"kind": "MODULE", "name": "usb_top", "rtl_citation": f"{rel}:3"},
        {"kind": "PORT", "name": "invented_signal_not_in_rtl", "rtl_citation": f"{rel}:4"},
    ]
    rc, out = _run_gate(_base_state(claims), tmp_path)
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "UNVERIFIABLE_RTL_CITATION"
    assert "invented_signal_not_in_rtl" in out["detail"]


def test_interface_and_register_block_claim_kinds_accepted(tmp_path):
    rel = _write_rtl_fixture(tmp_path)
    claims = [
        {"kind": "MODULE", "name": "usb_top", "rtl_citation": f"{rel}:3"},
        {"kind": "INTERFACE", "name": "utmi_data", "rtl_citation": f"{rel}:6"},
        {"kind": "REGISTER_BLOCK", "name": "axi_aclk", "rtl_citation": f"{rel}:7"},
    ]
    rc, out = _run_gate(_base_state(claims), tmp_path)
    assert rc == 0 and out["status"] == "PASS"


def test_lock_requested_without_calibration_still_fails_after_valid_claims(tmp_path):
    rel = _write_rtl_fixture(tmp_path)
    claims = [{"kind": "MODULE", "name": "usb_top", "rtl_citation": f"{rel}:3"}]
    state = _base_state(claims)
    state["lock_requested"] = True
    state["calibration_complete"] = False
    rc, out = _run_gate(state, tmp_path)
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "ARCHITECTURE_LOCK_BEFORE_CALIBRATION"


def test_full_valid_state_passes_end_to_end(tmp_path):
    rel = _write_rtl_fixture(tmp_path)
    claims = [
        {"kind": "MODULE", "name": "usb_top", "rtl_citation": f"{rel}:3"},
        {"kind": "PORT", "name": "phy_rst_n", "rtl_citation": f"{rel}:5"},
    ]
    state = _base_state(claims)
    state["lock_requested"] = True
    state["calibration_complete"] = True
    rc, out = _run_gate(state, tmp_path)
    assert rc == 0 and out["status"] == "PASS"
