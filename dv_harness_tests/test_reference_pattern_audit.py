"""Tests for dv_harness.reference_pattern_audit.

Two tiers, matching this codebase's own established precedent
(test_makefile_to_run_profile.py extracting against the real template
Makefile, not a synthetic fixture):

1. Extraction-logic unit tests against a small SYNTHETIC fixture (never real
   project content) -- proves the macro-call parsing itself works, on
   deliberately-simple made-up register names/addresses.
2. A real integration test that runs the tool against the actual
   reference/bfm_patterns/ directory under the sibling
   D:/DV/Task/USB/usb31_dev_uvm project (read-only) and asserts the known
   real usb_p2_switch_en host/DUT asymmetry is actually flagged in the
   output -- skipped (not failed) if that directory is not present on the
   machine running the tests, since it lives outside this repo.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dv_harness.reference_pattern_audit import (
    RegisterWrite,
    audit_directory,
    discover_paired_blocks,
    extract_directory,
    extract_register_writes,
    find_symmetry_asymmetries,
    format_report,
)

_REAL_PATTERN_DIR = Path("D:/DV/Task/USB/usb31_dev_uvm/reference/bfm_patterns")


# --- Tier 1: synthetic fixture ------------------------------------------------

_SYNTHETIC_PATTERN = """\
// synthetic fixture -- never real project content
`include "wave.txt"
initial begin
  `HOSTWRITE4B(32'hAA00_0004, 32'hFFFF); //enable_evt
  `CPUWRITE4B (32'hBB00_0004, 32'hFFFF); //enable_evt
  `HOSTWRITE4B(32'hAA00_0008, 32'h11  ); //mode_sel
  `CPUWRITE4B (32'hBB00_0008, 32'h11  ); //mode_sel
  `HOSTWRITE4B(32'hAA00_000C, 32'h2600); //only_on_host_field
  //`CPUWRITE4B (32'hBB00_0010, 32'h1); //dead_from_the_start, should stay excluded
  `CPUWRITE1B (32'hBB00_0020, 8'h02); //dut_only_field
  `HOSTREAD4B (32'hAA00_0004, regdata4B); //read calls are out of scope
  $finish;
end
"""


@pytest.fixture()
def synthetic_dir(tmp_path: Path) -> Path:
    d = tmp_path / "synthetic_bfm_patterns"
    d.mkdir()
    (d / "synth_pattern_a.txt").write_text(_SYNTHETIC_PATTERN, encoding="utf-8")
    return d


def test_extract_register_writes_parses_macro_addr_value_comment(synthetic_dir):
    writes = extract_register_writes(synthetic_dir / "synth_pattern_a.txt")
    active = [w for w in writes if not w.commented_out]
    # 6 WRITE-style calls in the fixture (the commented-out one and the READ
    # call are excluded from the WRITE set, but still extracted/marked).
    assert len(active) == 6
    first = next(w for w in active if w.address_or_register == "32'hAA00_0004")
    assert first.macro == "HOSTWRITE4B"
    assert first.prefix == "HOST"
    assert first.value == "32'hFFFF"
    assert first.comment == "enable_evt"
    assert first.host_or_dut_context == "HOST"
    assert first.base == "AA00"
    assert first.offset == "0004"
    assert isinstance(first, RegisterWrite)


def test_extract_register_writes_classifies_dut_context(synthetic_dir):
    writes = extract_register_writes(synthetic_dir / "synth_pattern_a.txt")
    cpu_write = next(w for w in writes if w.macro == "CPUWRITE4B" and w.offset == "0004")
    assert cpu_write.host_or_dut_context == "DUT"
    assert cpu_write.base == "BB00"


def test_extract_register_writes_excludes_read_calls_from_write_set(synthetic_dir):
    writes = extract_register_writes(synthetic_dir / "synth_pattern_a.txt")
    assert not any(w.macro.endswith("READ4B") for w in writes)


def test_extract_register_writes_marks_commented_out_call(synthetic_dir):
    writes = extract_register_writes(synthetic_dir / "synth_pattern_a.txt")
    dead = next(w for w in writes if w.offset == "0010")
    assert dead.commented_out is True
    assert dead.macro == "CPUWRITE4B"


def test_extract_directory_reads_every_matching_file(synthetic_dir):
    (synthetic_dir / "synth_pattern_b.txt").write_text(
        "`HOSTWRITE1B(32'hAA00_0004, 8'h1); //dup\n", encoding="utf-8"
    )
    writes = extract_directory(synthetic_dir)
    files = {w.file for w in writes}
    assert files == {"synth_pattern_a.txt", "synth_pattern_b.txt"}


def test_discover_paired_blocks_pairs_host_and_dut_bases(synthetic_dir):
    writes = extract_directory(synthetic_dir)
    pairs = discover_paired_blocks(writes)
    assert len(pairs) == 1
    pb = pairs[0]
    assert pb.host_base == "AA00"
    assert pb.dut_base == "BB00"
    assert set(pb.shared_offsets) == {"0004", "0008"}


def test_find_symmetry_asymmetries_flags_synthetic_host_only_field(synthetic_dir):
    writes = extract_directory(synthetic_dir)
    pairs = discover_paired_blocks(writes)
    findings = find_symmetry_asymmetries(writes, pairs)
    host_only = [f for f in findings if f.offset == "000C"]
    assert len(host_only) == 1
    assert host_only[0].written_side == "HOST"
    assert host_only[0].missing_side == "DUT"
    assert host_only[0].field_hint == "only_on_host_field"


def test_find_symmetry_asymmetries_flags_synthetic_dut_only_field(synthetic_dir):
    writes = extract_directory(synthetic_dir)
    pairs = discover_paired_blocks(writes)
    findings = find_symmetry_asymmetries(writes, pairs)
    dut_only = [f for f in findings if f.offset == "0020"]
    assert len(dut_only) == 1
    assert dut_only[0].written_side == "DUT"
    assert dut_only[0].missing_side == "HOST"


def test_find_symmetry_asymmetries_never_flags_shared_offset(synthetic_dir):
    writes = extract_directory(synthetic_dir)
    pairs = discover_paired_blocks(writes)
    findings = find_symmetry_asymmetries(writes, pairs)
    assert not any(f.offset in ("0004", "0008") for f in findings)


def test_find_symmetry_asymmetries_never_uses_a_commented_out_write_as_coverage(synthetic_dir):
    # offset 0010's only CPUWRITE4B is commented out -- it must not count as
    # DUT-side coverage for anything (there's no HOST-side write at that
    # offset in the fixture either, so it should simply not appear at all).
    writes = extract_directory(synthetic_dir)
    pairs = discover_paired_blocks(writes)
    findings = find_symmetry_asymmetries(writes, pairs)
    assert not any(f.offset == "0010" for f in findings)


def test_audit_directory_end_to_end_on_synthetic_fixture(synthetic_dir):
    result = audit_directory(synthetic_dir)
    assert result["summary"]["verdict"] == "ASYMMETRY_FOUND"
    assert result["summary"]["findings_count"] == 2
    assert result["commented_out_writes"] == 1
    report = format_report(result)
    assert "only_on_host_field" in report  # field_hint from the flagged HOST-only write's own comment
    assert "000C" in report
    assert "0020" in report


# --- Tier 2: real integration test against real reference/bfm_patterns/ -----

pytestmark_real = pytest.mark.skipif(
    not _REAL_PATTERN_DIR.is_dir(),
    reason="D:/DV/Task/USB/usb31_dev_uvm/reference/bfm_patterns is not present on this machine",
)


@pytestmark_real
def test_real_reference_patterns_reproduce_known_usb_p2_switch_en_asymmetry():
    """The real regression test this tool exists to pass: run the audit
    against the actual reference/bfm_patterns/ directory (read-only, real
    content) and confirm it flags the known real host/DUT asymmetry --
    usb_p2_switch_en written on the host TCA offset 0x161A_0020 but never
    on the DUT TCA offset 0x1272_0020 in any HS-speed (USB2_*) pattern.
    """
    result = audit_directory(_REAL_PATTERN_DIR)

    assert result["summary"]["verdict"] == "ASYMMETRY_FOUND"

    # The detector must have discovered the host(161A)/DUT(1272) TCA pairing
    # generically from real offset-overlap evidence, not a hardcoded table.
    pair = next(
        (pb for pb in result["paired_blocks"] if pb["host_base"] == "161A" and pb["dut_base"] == "1272"),
        None,
    )
    assert pair is not None, "did not discover the real HOST 161A / DUT 1272 TCA register-block pairing"
    assert "0020" in pair["shared_offsets"], (
        "the 0020 offset must be corpus-wide known to this pair (USB3_susres.txt/"
        "USB31_SSPcon.txt genuinely write it on both sides) for the per-file gap to be checkable"
    )

    # Every real HS-speed (USB2_*.txt) pattern file that touches TCA must be
    # flagged for offset 0020 host-written/DUT-missing -- this is the exact
    # real finding that cost 3 real debugging rounds before an upfront audit.
    flagged_020 = {
        f["file"] for f in result["findings"]
        if f["offset"] == "0020" and f["written_side"] == "HOST" and f["missing_side"] == "DUT"
    }
    expected_hs_files = {
        "USB2_bulkin.txt", "USB2_bulkout.txt", "USB2_con.txt",
        "USB2_interruptin.txt", "USB2_interruptout.txt",
        "USB2_isochin.txt", "USB2_isochout.txt", "USB2_susres.txt",
    }
    missing = expected_hs_files - flagged_020
    assert not missing, f"real HS-speed files not flagged for the known asymmetry: {sorted(missing)}"

    # A field-name hint recovered straight from the real file's own trailing
    # comment, so a human reading the finding immediately recognizes it.
    bulkin_finding = next(
        f for f in result["findings"]
        if f["file"] == "USB2_bulkin.txt" and f["offset"] == "0020"
    )
    assert "usb_p2_switch_en" in bulkin_finding["field_hint"]

    # And the real SS-speed pattern that DOES write both sides (USB3_susres.txt)
    # must NOT be flagged for this offset -- the per-file check has to stay
    # precise, not blanket-flag every file that ever touches base 1272.
    assert "USB3_susres.txt" not in flagged_020


@pytestmark_real
def test_real_reference_patterns_ss_pattern_is_symmetric_for_tca():
    result = audit_directory(_REAL_PATTERN_DIR)
    ss_flagged = [f for f in result["findings"] if f["file"] == "USB3_susres.txt" and f["offset"] == "0020"]
    assert ss_flagged == []
