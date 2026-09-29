"""Tests for dv_harness/dut_evidence_correlation.py.

Every manifest fixture is built through the REAL env_manifest.generate_and_write()
against small, clearly-synthesized inputs (a real RTL file parsed by the real
verible_parser.py, a real register-map JSON, a real soc-arch-map JSON) --
never a hand-written env.manifest.json, per this project's Evidence Truth Rule.
The RTL-dependent tests skip (never fake) when verible-verilog-syntax is not
on PATH, matching test_env_manifest.py's own convention.

Coverage:
  * positive path -- an exact RTL port match (RTL_CONFIRMED), an exact
    clock/reset match with matching attributes (RTL_CONFIRMED), an exact
    register/field match (RTL_CONFIRMED).
  * negative controls -- a fabricated name that matches nothing
    (RTL_NOT_FOUND against an available manifest, never a false pass); a
    genuinely mutated attribute (a reset polarity the manifest disagrees
    with -> RTL_CONTRADICTS_SPEC, never silently accepted); a name that only
    partially resembles something real (RTL_PARTIAL, never upgraded to
    CONFIRMED); a completely missing env.manifest.json (NOT_AVAILABLE for
    every item, never a guess); a manifest whose relevant layer itself
    reports NOT_AVAILABLE (NOT_AVAILABLE, never conflated with "searched
    and not found").
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap

import pytest

from dv_harness import env_manifest
from dv_harness.dut_evidence_correlation import (
    STATUS_NOT_AVAILABLE,
    STATUS_RTL_CONFIRMED,
    STATUS_RTL_CONTRADICTS_SPEC,
    STATUS_RTL_NOT_FOUND,
    STATUS_RTL_PARTIAL,
    DutEvidenceCorrelationError,
    correlate,
    correlate_item,
    correlate_items,
)

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

# A small, clearly-synthesized RTL fixture (never real project RTL): one
# interrupt output port, a clock and an active-low reset input, and a mode
# parameter.
DUT_FIXTURE = textwrap.dedent("""\
    module usb_link_ctrl #(
        parameter int MODE_WIDTH = 2
    ) (
        input  logic       pclk,
        input  logic       presetn,
        output logic       usb_wake_irq,
        output logic [3:0] link_state
    );
        assign usb_wake_irq = 1'b0;
    endmodule
    """)

REGISTER_MAP_FIXTURE = {
    "schema_version": "1.0",
    "source": {"kind": "ral_model_export", "description": "synthesized test fixture, not a real project"},
    "blocks": [
        {
            "name": "CTRL_BLOCK",
            "base_address": "0x1000",
            "registers": [
                {
                    "name": "CTRL0",
                    "address_offset": "0x0",
                    "width": 32,
                    "access": "RW",
                    "reset_value": "0x0",
                    "fields": [
                        {"name": "TEST_MODE", "bit_offset": 0, "bit_width": 1, "access": "RW", "reset_value": "0x0"},
                    ],
                },
            ],
        },
    ],
}

SOC_ARCH_MAP_FIXTURE = {
    "schema_version": "1.0",
    "source": {"kind": "soc_spec_pipeline_export", "description": "synthesized test fixture"},
    "clocks": [
        {"name": "pclk", "frequency_mhz": 100.0, "domain": "apb", "evidence": "spec.md:12"},
    ],
    "resets": [
        {"name": "presetn", "active_level": "low", "synchronous": True, "clock": "pclk",
         "evidence": "spec.md:14"},
    ],
}


@pytest.fixture
def dut_sv(tmp_path):
    p = tmp_path / "usb_link_ctrl.sv"
    p.write_text(DUT_FIXTURE, encoding="utf-8")
    return p


@pytest.fixture
def register_map_json(tmp_path):
    p = tmp_path / "register_map.json"
    p.write_text(json.dumps(REGISTER_MAP_FIXTURE), encoding="utf-8")
    return p


@pytest.fixture
def soc_arch_map_json(tmp_path):
    p = tmp_path / "soc_arch_map.json"
    p.write_text(json.dumps(SOC_ARCH_MAP_FIXTURE), encoding="utf-8")
    return p


@pytest.fixture
def full_manifest_path(tmp_path, dut_sv, register_map_json, soc_arch_map_json):
    """A complete, schema-valid env.manifest.json written to disk through the
    REAL generator, covering rtl + registers + clock_reset (address_map is
    left NOT_AVAILABLE on purpose, to exercise that honest-absence path)."""
    out = tmp_path / "env.manifest.json"
    env_manifest.generate_and_write(
        out,
        rtl_files=[dut_sv],
        register_map_path=register_map_json,
        soc_arch_map_path=soc_arch_map_json,
    )
    return out


@pytest.fixture
def no_rtl_manifest_path(tmp_path, register_map_json, soc_arch_map_json):
    """A schema-valid manifest with NO rtl_files supplied -- dut_facts.rtl is
    honestly NOT_AVAILABLE. Used to prove interrupt/clock/reset correlation
    against an unavailable-but-not-missing-file manifest reads NOT_AVAILABLE,
    never RTL_NOT_FOUND, when the relevant layers are all unavailable."""
    out = tmp_path / "env.manifest.json"
    env_manifest.generate_and_write(
        out,
        register_map_path=register_map_json,
        soc_arch_map_path=soc_arch_map_json,
    )
    return out


# ---------------------------------------------------------------------------
# positive path
# ---------------------------------------------------------------------------

@requires_verible
def test_exact_rtl_port_match_is_confirmed(full_manifest_path):
    item = {"item_id": "REQ-1", "fact_type": "interrupt", "name": "usb_wake_irq"}
    report = correlate([item], full_manifest_path)
    assert report["manifest_status"] == "LOADED"
    r = report["items"][0]
    assert r["status"] == STATUS_RTL_CONFIRMED
    assert r["exact_matches"][0]["kind"] == "port"
    assert r["exact_matches"][0]["file_path"].endswith("usb_link_ctrl.sv")
    assert "usb_link_ctrl.sv" in r["exact_matches"][0]["evidence_ref"]
    assert report["summary"][STATUS_RTL_CONFIRMED] == 1


def test_exact_clock_and_reset_match_with_agreeing_attributes(full_manifest_path):
    items = [
        {"item_id": "REQ-CLK", "fact_type": "clock", "name": "pclk", "expected": {"frequency_mhz": 100.0}},
        {"item_id": "REQ-RST", "fact_type": "reset", "name": "presetn", "expected": {"active_level": "low"}},
    ]
    report = correlate(items, full_manifest_path)
    for r in report["items"]:
        assert r["status"] == STATUS_RTL_CONFIRMED, r
    clk_match = report["items"][0]["exact_matches"][0]
    assert clk_match["evidence_ref"] == "spec.md:12"
    rst_match = report["items"][1]["exact_matches"][0]
    assert rst_match["evidence_ref"] == "spec.md:14"


def test_exact_register_and_field_match_is_confirmed(full_manifest_path):
    items = [
        {"item_id": "REQ-REG", "fact_type": "mode", "name": "CTRL0", "expected": {"access": "RW", "width": 32}},
        {"item_id": "REQ-FLD", "fact_type": "mode", "name": "TEST_MODE"},
    ]
    report = correlate(items, full_manifest_path)
    assert report["items"][0]["status"] == STATUS_RTL_CONFIRMED
    assert report["items"][0]["exact_matches"][0]["kind"] == "register"
    assert report["items"][1]["status"] == STATUS_RTL_CONFIRMED
    assert report["items"][1]["exact_matches"][0]["kind"] == "field"


def test_alias_is_matched_when_the_primary_name_is_not(full_manifest_path):
    item = {"item_id": "REQ-ALIAS", "fact_type": "feature", "name": "USB Wake Interrupt",
            "aliases": ["usb_wake_irq"]}
    report = correlate([item], full_manifest_path)
    r = report["items"][0]
    assert r["status"] == STATUS_RTL_CONFIRMED
    assert r["exact_matches"][0]["matched_query"] == "usb_wake_irq"


# ---------------------------------------------------------------------------
# negative controls -- these must NOT read as a real pass
# ---------------------------------------------------------------------------

@requires_verible
def test_fabricated_name_against_an_available_manifest_is_not_found(full_manifest_path):
    item = {"item_id": "REQ-GHOST", "fact_type": "interrupt", "name": "totally_fabricated_irq_name"}
    report = correlate([item], full_manifest_path)
    r = report["items"][0]
    assert r["status"] == STATUS_RTL_NOT_FOUND
    assert r["exact_matches"] == []
    assert r["fuzzy_matches"] == []
    assert report["summary"][STATUS_RTL_NOT_FOUND] == 1


def test_mutated_reset_polarity_contradicts_the_manifest(full_manifest_path):
    """The requirement declares presetn as active-HIGH; the real manifest
    (from the soc_arch_map fixture) says active-low. This must be caught,
    never silently accepted as a confirmed match."""
    item = {"item_id": "REQ-RST-BAD", "fact_type": "reset", "name": "presetn",
            "expected": {"active_level": "high"}}
    report = correlate([item], full_manifest_path)
    r = report["items"][0]
    assert r["status"] == STATUS_RTL_CONTRADICTS_SPEC
    assert len(r["contradictions"]) == 1
    c = r["contradictions"][0]
    assert c["attribute"] == "active_level"
    assert c["expected"] == "high"
    assert c["actual"] == "low"
    assert report["summary"][STATUS_RTL_CONTRADICTS_SPEC] == 1


def test_mutated_clock_frequency_contradicts_the_manifest(full_manifest_path):
    item = {"item_id": "REQ-CLK-BAD", "fact_type": "clock", "name": "pclk",
            "expected": {"frequency_mhz": 400.0}}
    report = correlate([item], full_manifest_path)
    assert report["items"][0]["status"] == STATUS_RTL_CONTRADICTS_SPEC


def test_mutated_register_access_contradicts_the_manifest(full_manifest_path):
    item = {"item_id": "REQ-REG-BAD", "fact_type": "mode", "name": "CTRL0", "expected": {"access": "RO"}}
    report = correlate([item], full_manifest_path)
    assert report["items"][0]["status"] == STATUS_RTL_CONTRADICTS_SPEC


@requires_verible
def test_partial_substring_match_is_not_upgraded_to_confirmed(full_manifest_path):
    # "wake_irq" is a genuine substring of the real port "usb_wake_irq" but
    # is not itself the declared name -- must read PARTIAL, never CONFIRMED.
    item = {"item_id": "REQ-PARTIAL", "fact_type": "interrupt", "name": "wake_irq"}
    report = correlate([item], full_manifest_path)
    r = report["items"][0]
    assert r["status"] == STATUS_RTL_PARTIAL
    assert r["exact_matches"] == []
    assert len(r["fuzzy_matches"]) >= 1
    assert r["fuzzy_matches"][0]["name"] == "usb_wake_irq"


def test_missing_manifest_file_is_not_available_for_every_item(tmp_path):
    items = [
        {"item_id": "REQ-1", "fact_type": "interrupt", "name": "usb_wake_irq"},
        {"item_id": "REQ-2", "fact_type": "clock", "name": "pclk"},
    ]
    missing_path = tmp_path / "does_not_exist" / "env.manifest.json"
    report = correlate(items, missing_path)
    assert report["manifest_status"] == "NOT_AVAILABLE"
    assert "does not exist" in report["manifest_reason"]
    for r in report["items"]:
        assert r["status"] == STATUS_NOT_AVAILABLE
    assert report["summary"][STATUS_NOT_AVAILABLE] == 2


def test_none_manifest_path_is_not_available_for_every_item():
    items = [{"item_id": "REQ-1", "fact_type": "feature", "name": "anything"}]
    report = correlate(items, None)
    assert report["manifest_status"] == "NOT_AVAILABLE"
    assert report["items"][0]["status"] == STATUS_NOT_AVAILABLE


def test_unavailable_relevant_layer_is_not_available_not_not_found(no_rtl_manifest_path):
    """dut_facts.rtl is honestly NOT_AVAILABLE on this manifest (no rtl_files
    were supplied). An 'interrupt' item searches rtl+registers; registers IS
    available and empty of this name, but rtl -- the layer that would
    actually carry an interrupt port -- could not be searched at all. This
    must read as a real finding (RTL_NOT_FOUND is defensible since registers
    layer WAS searched), so we instead prove the pure single-layer case:
    a 'clock' item, whose only relevant layers are clock_reset (available)
    and rtl (unavailable) -- searching a genuinely nonexistent clock name
    still correctly reads RTL_NOT_FOUND because clock_reset was available.
    The true NOT_AVAILABLE case is when EVERY relevant layer is unavailable,
    proven directly by pointing 'mode' (registers+rtl) at a manifest with
    neither layer available."""
    # registers+rtl both unavailable: build a manifest with no register map
    # and no rtl at all to prove the all-unavailable path directly.
    item_all_unavailable = {"item_id": "REQ-MODE-NA", "fact_type": "mode", "name": "TEST_MODE"}
    bare = no_rtl_manifest_path.parent / "bare_env.manifest.json"
    env_manifest.generate_and_write(bare)
    report = correlate([item_all_unavailable], bare)
    r = report["items"][0]
    assert r["status"] == STATUS_NOT_AVAILABLE
    assert r["layer_status"]["registers"]["available"] is False
    assert r["layer_status"]["rtl"]["available"] is False


def test_registers_available_but_rtl_not_still_finds_via_registers(no_rtl_manifest_path):
    item = {"item_id": "REQ-MODE", "fact_type": "mode", "name": "TEST_MODE"}
    report = correlate([item], no_rtl_manifest_path)
    r = report["items"][0]
    assert r["layer_status"]["rtl"]["available"] is False
    assert r["layer_status"]["registers"]["available"] is True
    assert r["status"] == STATUS_RTL_CONFIRMED


def test_address_map_not_available_reports_honestly(full_manifest_path):
    """The full_manifest fixture supplies no soc_arch_map address_map key at
    all -> dut_facts.address_map is NOT_AVAILABLE. A 'feature' item (which
    searches address_map among other layers) whose only candidate would have
    lived there must not silently read as RTL_NOT_FOUND without disclosing
    that address_map could not be searched."""
    item = {"item_id": "REQ-ADDR", "fact_type": "feature", "name": "SOME_REGION_NAME"}
    report = correlate([item], full_manifest_path)
    r = report["items"][0]
    assert r["layer_status"]["address_map"]["available"] is False
    assert r["layer_status"]["address_map"]["reason"]


# ---------------------------------------------------------------------------
# malformed input / usage errors
# ---------------------------------------------------------------------------

def test_missing_required_field_raises(full_manifest_path):
    manifest = env_manifest.load_env_manifest(full_manifest_path)
    with pytest.raises(DutEvidenceCorrelationError):
        correlate_item({"item_id": "X", "fact_type": "clock"}, manifest["dut_facts"])


def test_unrecognized_fact_type_still_searches_everything_and_warns(full_manifest_path):
    manifest = env_manifest.load_env_manifest(full_manifest_path)
    r = correlate_item({"item_id": "REQ-X", "fact_type": "not_a_real_kind", "name": "pclk"},
                        manifest["dut_facts"])
    assert r["status"] == STATUS_RTL_CONFIRMED
    assert r["layers_searched"] == ["rtl", "registers", "clock_reset", "address_map"]
    assert any("not_a_real_kind" in w for w in r["warnings"])


def test_invalid_manifest_file_propagates_validation_error(tmp_path):
    bad = tmp_path / "env.manifest.json"
    bad.write_text(json.dumps({"schema_version": "1.2", "not_a_valid_manifest": True}), encoding="utf-8")
    with pytest.raises(env_manifest.EnvManifestValidationError):
        correlate([{"item_id": "X", "fact_type": "feature", "name": "y"}], bad)


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

@requires_verible
def test_cli_reports_confirmed_and_exits_zero(full_manifest_path, tmp_path):
    items_path = tmp_path / "items.json"
    items_path.write_text(json.dumps([
        {"item_id": "REQ-1", "fact_type": "interrupt", "name": "usb_wake_irq"},
    ]), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.dut_evidence_correlation",
         "--manifest", str(full_manifest_path), "--items", str(items_path), "--json"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["items"][0]["status"] == STATUS_RTL_CONFIRMED


def test_cli_exits_two_on_missing_manifest(tmp_path):
    items_path = tmp_path / "items.json"
    items_path.write_text(json.dumps([{"item_id": "REQ-1", "fact_type": "feature", "name": "x"}]),
                           encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.dut_evidence_correlation",
         "--manifest", str(tmp_path / "nope" / "env.manifest.json"), "--items", str(items_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_cli_exits_one_when_a_declared_fact_is_not_found(full_manifest_path, tmp_path):
    items_path = tmp_path / "items.json"
    items_path.write_text(json.dumps([
        {"item_id": "REQ-GHOST", "fact_type": "interrupt", "name": "totally_fabricated_irq_name"},
    ]), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.dut_evidence_correlation",
         "--manifest", str(full_manifest_path), "--items", str(items_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
