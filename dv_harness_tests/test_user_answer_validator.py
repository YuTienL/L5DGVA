"""Tests for dv_harness/user_answer_validator.py -- validating a raw,
user-typed intake answer against REAL evidence: a real
verible-verilog-syntax parse of a supplied RTL file set (module/file
existence), and a real `env_manifest.py` dut_facts.rtl record (build
inclusion).

Requires the real verible-verilog-syntax binary for the module-existence
tests, consistent with dv_harness_tests/test_verible_parser.py's own
discipline -- skipped outright (never faked) on a machine without it."""
from __future__ import annotations

import shutil
import textwrap

import pytest

from dv_harness import env_manifest
from dv_harness.user_answer_validator import (
    CLAIM_FILE_BUILD_INCLUSION,
    CLAIM_MODULE_EXISTENCE,
    CLAIM_UNKNOWN,
    CONTRADICTED,
    PARTIALLY_VALIDATED,
    UNVERIFIABLE,
    VALIDATED,
    check_build_inclusion,
    check_module_existence,
    extract_claim,
    validate_answer,
)

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

USB_CORE_FIXTURE = textwrap.dedent("""\
    module usb_core (
        input  logic clk,
        input  logic rst_n,
        output logic vbus_valid
    );

        assign vbus_valid = rst_n;

    endmodule
    """)

INVALID_FIXTURE = "this is !!! not ### valid verilog @@@ at all (((\n"


# ---------------------------------------------------------------------------
# extract_claim() -- structural parsing only
# ---------------------------------------------------------------------------

def test_extract_claim_dut_top_equals():
    claim = extract_claim("DUT top = usb_core")
    assert claim.claim_type == CLAIM_MODULE_EXISTENCE
    assert claim.target == "usb_core"


def test_extract_claim_build_includes_file():
    claim = extract_claim("build includes file usb_core.sv")
    assert claim.claim_type == CLAIM_FILE_BUILD_INCLUSION
    assert claim.target == "usb_core.sv"


def test_extract_claim_module_exists_phrasing():
    claim = extract_claim("module usb_core exists")
    assert claim.claim_type == CLAIM_MODULE_EXISTENCE
    assert claim.target == "usb_core"


def test_extract_claim_unrecognized_text_is_unknown():
    claim = extract_claim("the weather today is quite nice actually")
    assert claim.claim_type == CLAIM_UNKNOWN
    assert claim.target is None


def test_extract_claim_empty_text_is_unknown():
    claim = extract_claim("")
    assert claim.claim_type == CLAIM_UNKNOWN
    assert extract_claim("   ").claim_type == CLAIM_UNKNOWN
    assert extract_claim(None).claim_type == CLAIM_UNKNOWN


# ---------------------------------------------------------------------------
# validate_answer() over an unrecognized claim -- always UNVERIFIABLE,
# never silently accepted.
# ---------------------------------------------------------------------------

def test_unrecognized_claim_is_unverifiable():
    result = validate_answer("the weather today is quite nice")
    assert result.claim_type == CLAIM_UNKNOWN
    assert result.status == UNVERIFIABLE
    assert result.evidence == []


# ---------------------------------------------------------------------------
# Module existence -- real verible parse of a supplied RTL file set
# ---------------------------------------------------------------------------

@requires_verible
def test_module_existence_validated(tmp_path):
    rtl = tmp_path / "usb_core.sv"
    rtl.write_text(USB_CORE_FIXTURE, encoding="utf-8")

    result = validate_answer("DUT top = usb_core", rtl_files=[rtl])

    assert result.claim_type == CLAIM_MODULE_EXISTENCE
    assert result.target == "usb_core"
    assert result.status == VALIDATED
    assert result.evidence
    assert str(rtl) in result.evidence[0]


@requires_verible
def test_module_existence_contradicted(tmp_path):
    rtl = tmp_path / "usb_core.sv"
    rtl.write_text(USB_CORE_FIXTURE, encoding="utf-8")

    result = validate_answer("DUT top = pcie_core", rtl_files=[rtl])

    assert result.status == CONTRADICTED
    assert "pcie_core" in result.reason


@requires_verible
def test_module_existence_case_mismatch_is_partially_validated(tmp_path):
    rtl = tmp_path / "usb_core.sv"
    rtl.write_text(USB_CORE_FIXTURE, encoding="utf-8")

    result = validate_answer("DUT top = USB_CORE", rtl_files=[rtl])

    assert result.status == PARTIALLY_VALIDATED
    assert "case" in result.reason


def test_module_existence_no_rtl_files_is_unverifiable():
    result = validate_answer("DUT top = usb_core", rtl_files=None)
    assert result.claim_type == CLAIM_MODULE_EXISTENCE
    assert result.status == UNVERIFIABLE
    assert "no RTL file set" in result.reason

    result_empty = validate_answer("DUT top = usb_core", rtl_files=[])
    assert result_empty.status == UNVERIFIABLE


def test_module_existence_verible_unavailable_is_unverifiable(tmp_path):
    rtl = tmp_path / "usb_core.sv"
    rtl.write_text(USB_CORE_FIXTURE, encoding="utf-8")

    status, reason, evidence = check_module_existence(
        "usb_core", [rtl], verible_bin="definitely-not-a-real-verible-binary-xyz")

    assert status == UNVERIFIABLE
    assert "could not be run" in reason
    assert evidence == []


@requires_verible
def test_module_existence_partial_parse_failure_is_unverifiable_not_contradicted(tmp_path):
    good = tmp_path / "usb_core.sv"
    good.write_text(USB_CORE_FIXTURE, encoding="utf-8")
    bad = tmp_path / "broken.sv"
    bad.write_text(INVALID_FIXTURE, encoding="utf-8")

    # A module that genuinely is not in EITHER file, but one of the two
    # files could not really be parsed -- must not be reported as a proven
    # CONTRADICTION, since the broken file was never actually checked.
    status, reason, evidence = check_module_existence("pcie_core", [good, bad])

    assert status == UNVERIFIABLE
    assert "failed to parse" in reason
    assert any("broken.sv" in e for e in evidence)


@requires_verible
def test_module_existence_found_despite_a_sibling_parse_failure(tmp_path):
    good = tmp_path / "usb_core.sv"
    good.write_text(USB_CORE_FIXTURE, encoding="utf-8")
    bad = tmp_path / "broken.sv"
    bad.write_text(INVALID_FIXTURE, encoding="utf-8")

    # The target module really IS found in the file that parsed cleanly --
    # a sibling file's real parse failure must not suppress a real match.
    status, reason, evidence = check_module_existence("usb_core", [good, bad])

    assert status == VALIDATED


# ---------------------------------------------------------------------------
# Build inclusion -- real env_manifest.py dut_facts.rtl facts
# ---------------------------------------------------------------------------

@requires_verible
def test_build_inclusion_validated_exact_path(tmp_path):
    rtl = tmp_path / "usb_core.sv"
    rtl.write_text(USB_CORE_FIXTURE, encoding="utf-8")
    dut_facts_rtl = env_manifest.build_dut_facts_rtl([rtl])

    answer = f"build includes file {rtl}"
    result = validate_answer(answer, dut_facts_rtl=dut_facts_rtl)

    assert result.claim_type == CLAIM_FILE_BUILD_INCLUSION
    assert result.status == VALIDATED
    assert result.evidence


@requires_verible
def test_build_inclusion_basename_only_is_partially_validated(tmp_path):
    sub = tmp_path / "rtl"
    sub.mkdir()
    rtl = sub / "usb_core.sv"
    rtl.write_text(USB_CORE_FIXTURE, encoding="utf-8")
    dut_facts_rtl = env_manifest.build_dut_facts_rtl([rtl])

    # Claims only the bare filename, not the recorded full path.
    result = validate_answer("build includes file usb_core.sv", dut_facts_rtl=dut_facts_rtl)

    assert result.status == PARTIALLY_VALIDATED
    assert "different" in result.reason


@requires_verible
def test_build_inclusion_contradicted(tmp_path):
    rtl = tmp_path / "usb_core.sv"
    rtl.write_text(USB_CORE_FIXTURE, encoding="utf-8")
    dut_facts_rtl = env_manifest.build_dut_facts_rtl([rtl])

    result = validate_answer("build includes file totally_unrelated_file.sv", dut_facts_rtl=dut_facts_rtl)

    assert result.status == CONTRADICTED
    assert "totally_unrelated_file.sv" in result.reason


def test_build_inclusion_not_available_status_is_unverifiable():
    dut_facts_rtl = env_manifest.build_dut_facts_rtl([])  # NOT_AVAILABLE, no rtl_files
    assert dut_facts_rtl["status"] == "NOT_AVAILABLE"

    result = validate_answer("build includes file usb_core.sv", dut_facts_rtl=dut_facts_rtl)

    assert result.status == UNVERIFIABLE
    assert "NOT_AVAILABLE" in result.reason


def test_build_inclusion_no_facts_supplied_is_unverifiable():
    result = validate_answer("build includes file usb_core.sv")
    assert result.claim_type == CLAIM_FILE_BUILD_INCLUSION
    assert result.status == UNVERIFIABLE
    assert "no recorded RTL build facts" in result.reason


def test_check_build_inclusion_rejects_non_dict_input():
    status, reason, evidence = check_build_inclusion("x.sv", None)
    assert status == UNVERIFIABLE
    assert evidence == []


@requires_verible
def test_build_inclusion_empty_file_list_is_unverifiable(tmp_path):
    dut_facts_rtl = {"status": "PARSED", "reason": None, "files": []}
    result = validate_answer("build includes file usb_core.sv", dut_facts_rtl=dut_facts_rtl)
    assert result.status == UNVERIFIABLE
    assert "no file entries" in result.reason


# ---------------------------------------------------------------------------
# manifest= convenience path -- reads dut_facts.rtl out of a full
# env.manifest.json-shaped dict (env_manifest.generate_env_manifest()).
# ---------------------------------------------------------------------------

@requires_verible
def test_validate_answer_reads_dut_facts_rtl_out_of_a_full_manifest(tmp_path):
    rtl = tmp_path / "usb_core.sv"
    rtl.write_text(USB_CORE_FIXTURE, encoding="utf-8")
    manifest = env_manifest.generate_env_manifest(rtl_files=[rtl])

    answer = f"build includes file {rtl}"
    result = validate_answer(answer, manifest=manifest)

    assert result.status == VALIDATED


@requires_verible
def test_validate_answer_manifest_convenience_reports_contradiction(tmp_path):
    rtl = tmp_path / "usb_core.sv"
    rtl.write_text(USB_CORE_FIXTURE, encoding="utf-8")
    manifest = env_manifest.generate_env_manifest(rtl_files=[rtl])

    result = validate_answer("build includes file nope_not_here.sv", manifest=manifest)

    assert result.status == CONTRADICTED


def test_validate_answer_manifest_with_no_rtl_layer_is_unverifiable():
    # A manifest generated with no rtl_files at all -- dut_facts.rtl is
    # honestly NOT_AVAILABLE, and this must read as UNVERIFIABLE, never a
    # fabricated CONTRADICTED/VALIDATED.
    manifest = env_manifest.generate_env_manifest(rtl_files=None)
    result = validate_answer("build includes file usb_core.sv", manifest=manifest)
    assert result.status == UNVERIFIABLE


# ---------------------------------------------------------------------------
# to_dict()
# ---------------------------------------------------------------------------

def test_to_dict_shape():
    result = validate_answer("the weather today is quite nice")
    d = result.to_dict()
    assert set(d.keys()) == {"raw_text", "claim_type", "target", "status", "reason", "evidence"}
    assert d["status"] == UNVERIFIABLE
