"""Tests for dv_harness/reference_uvm_dut_top_integration_manifest.py --
DISCOVERY-ONLY manifest of whether a project already has a DE-authored top
TB, and how its real facts compare against a real generated `soc_tb_top.sv`.

Every fixture is a small SYNTHETIC `.sv` file written inside a tmp_path --
never a real project's real top TB. Nothing here calls
`soc_environment_composer._soc_tb_top()` in a way that writes files or
mutates that module; it is imported and called read-only, exactly as
`generated_top_tb_facts()` itself does.
"""
from pathlib import Path

import pytest

from dv_harness import reference_uvm_dut_top_integration_manifest as rutim

# A hand-authored top TB that instantiates the real DUT, declares its own
# clock/reset nets, and already carries the real DV_UVM two-hook convention
# (bind_mechanism_generator.py's own `` `ifdef DV_UVM ``/`dv_uvm_hook.svh`
# shape).
EXISTING_TOP_WITH_HOOKS = """\
module sysn063_tb_top;
  logic sys_clk;
  logic sys_rst_n;

  initial begin sys_clk = 0; forever #5 sys_clk = ~sys_clk; end
  initial begin sys_rst_n = 0; #100; sys_rst_n = 1; end

  sysn063 u_dut (
    .clk(sys_clk),
    .rst_n(sys_rst_n)
  );

`ifdef DV_UVM
  `include "dv_uvm_hook.svh"
`endif

  initial run_test();
endmodule
"""

# A hand-authored top TB with NO DV_UVM hooks and a differently-named reset
# net -- used to exercise DIVERGENT/EXISTING_ONLY paths.
EXISTING_TOP_NO_HOOKS = """\
module legacy_tb_top;
  logic legacy_clk;
  logic legacy_resetn;

  sysn063 u_dut (
    .clk(legacy_clk),
    .rst_n(legacy_resetn)
  );

  initial run_test();
endmodule
"""

# Not a top TB at all (used to confirm discovery does not false-positive on
# an unrelated .sv file).
UNRELATED_SV = "module some_ip_block(input logic a, output logic b);\nendmodule\n"

_SOC_SUBSYSTEMS = [
    {"name": "usb", "environment_manifest": None},
]
_SOC_MANIFEST = {}


def _generated_facts():
    return rutim.generated_top_tb_facts(_SOC_SUBSYSTEMS, _SOC_MANIFEST,
                                        dut_module_name="sysn063")


# --- discover_existing_top_tb ------------------------------------------------

def test_discover_finds_conventional_tb_top_file(tmp_path):
    (tmp_path / "tb").mkdir()
    (tmp_path / "tb" / "sysn063_tb_top.sv").write_text(EXISTING_TOP_WITH_HOOKS, encoding="utf-8")
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "unrelated_ip.sv").write_text(UNRELATED_SV, encoding="utf-8")

    result = rutim.discover_existing_top_tb(tmp_path)

    assert result["status"] == "FOUND"
    assert result["candidates"] == ["tb/sysn063_tb_top.sv"]
    assert "top_hierarchy" in result["basis"]


def test_discover_reports_not_found_when_no_top_file_present(tmp_path):
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "unrelated_ip.sv").write_text(UNRELATED_SV, encoding="utf-8")

    result = rutim.discover_existing_top_tb(tmp_path)

    assert result["status"] == "NOT_FOUND"
    assert result["candidates"] == []


def test_discover_reports_unknown_for_missing_project_root(tmp_path):
    missing = tmp_path / "does_not_exist"

    result = rutim.discover_existing_top_tb(missing)

    assert result["status"] == "UNKNOWN"


def test_discover_declared_path_beats_name_convention(tmp_path):
    odd_dir = tmp_path / "weird_layout"
    odd_dir.mkdir()
    odd_file = odd_dir / "not_a_conventional_name.sv"
    odd_file.write_text(EXISTING_TOP_WITH_HOOKS, encoding="utf-8")

    result = rutim.discover_existing_top_tb(
        tmp_path, declared_path="weird_layout/not_a_conventional_name.sv")

    assert result["status"] == "FOUND"
    assert result["candidates"] == ["weird_layout/not_a_conventional_name.sv"]
    assert result["basis"] == "DECLARED_PATH"


def test_discover_declared_path_not_on_disk_is_not_found(tmp_path):
    result = rutim.discover_existing_top_tb(tmp_path, declared_path="nope/nope.sv")

    assert result["status"] == "NOT_FOUND"
    assert "DECLARED_PATH_NOT_ON_DISK" in result["basis"]


# --- extract_existing_top_tb_facts ------------------------------------------

def test_extract_facts_finds_dut_instantiation_clock_reset_and_hooks(tmp_path):
    f = tmp_path / "sysn063_tb_top.sv"
    f.write_text(EXISTING_TOP_WITH_HOOKS, encoding="utf-8")

    facts = rutim.extract_existing_top_tb_facts(f, dut_module_name="sysn063")

    assert facts["module_name"] == "sysn063_tb_top"
    assert facts["dut_instantiation"]["status"] == "PRESENT"
    assert facts["dut_instantiation"]["instance_name"] == "u_dut"
    assert {c["name"] for c in facts["clock_signals"]} == {"sys_clk"}
    assert {r["name"] for r in facts["reset_signals"]} == {"sys_rst_n"}
    assert facts["uvm_hooks"]["dv_uvm_ifdef_present"] is True
    assert facts["uvm_hooks"]["dv_uvm_hook_svh_included"] is True
    assert len(facts["source_sha256"]) == 64


def test_extract_facts_reports_absent_dut_when_not_instantiated(tmp_path):
    f = tmp_path / "no_dut_tb_top.sv"
    f.write_text("module no_dut_tb_top;\n  logic clk;\ninitial run_test();\nendmodule\n",
                encoding="utf-8")

    facts = rutim.extract_existing_top_tb_facts(f, dut_module_name="sysn063")

    assert facts["dut_instantiation"]["status"] == "ABSENT"
    assert facts["dut_instantiation"]["instance_name"] is None


def test_extract_facts_reports_not_declared_without_a_dut_module_name(tmp_path):
    f = tmp_path / "legacy_tb_top.sv"
    f.write_text(EXISTING_TOP_NO_HOOKS, encoding="utf-8")

    facts = rutim.extract_existing_top_tb_facts(f)

    assert facts["dut_instantiation"]["status"] == "NOT_DECLARED"
    assert "sysn063" in facts["dut_instantiation"]["other_instantiations_seen"]


def test_extract_facts_reports_absent_hooks_when_none_present(tmp_path):
    f = tmp_path / "legacy_tb_top.sv"
    f.write_text(EXISTING_TOP_NO_HOOKS, encoding="utf-8")

    facts = rutim.extract_existing_top_tb_facts(f, dut_module_name="sysn063")

    assert facts["uvm_hooks"]["dv_uvm_ifdef_present"] is False
    assert facts["uvm_hooks"]["dv_uvm_hook_svh_included"] is False
    assert facts["uvm_hooks"]["evidence"] == []


# --- generated_top_tb_facts (real _soc_tb_top() call, read-only) ------------

def test_generated_facts_come_from_real_soc_tb_top_output():
    facts = _generated_facts()

    assert facts["module_name"] == "soc_tb_top"
    assert facts["source_label"].startswith("soc_environment_composer._soc_tb_top")
    # generator.py's own tb_top()/composer's _soc_tb_top() honest limitation:
    # it never instantiates the raw DUT, only already-generated subsystem env
    # classes -- so a real DUT instantiation is genuinely ABSENT here.
    assert facts["dut_instantiation"]["status"] == "ABSENT"
    assert {c["name"] for c in facts["clock_signals"]} == {"usb_clk"}
    assert {r["name"] for r in facts["reset_signals"]} == {"usb_rst_n"}
    assert facts["uvm_hooks"]["dv_uvm_ifdef_present"] is False


# --- compare_against_generated_top -------------------------------------------

def test_compare_reports_existing_only_dut_and_hooks_and_divergent_clock_reset(tmp_path):
    f = tmp_path / "sysn063_tb_top.sv"
    f.write_text(EXISTING_TOP_WITH_HOOKS, encoding="utf-8")
    existing = rutim.extract_existing_top_tb_facts(f, dut_module_name="sysn063")
    generated = _generated_facts()

    result = rutim.compare_against_generated_top(existing, generated)

    # existing really instantiates the DUT; generated genuinely does not.
    assert result["dut_instantiation"]["verdict"] == rutim.EXISTING_ONLY
    # existing declares sys_clk/sys_rst_n; generated declares usb_clk/usb_rst_n
    # -- disjoint non-empty sets is DIVERGENT, not EXISTING_ONLY/GENERATED_ONLY.
    assert result["clock_signals"]["verdict"] == rutim.DIVERGENT
    assert result["reset_signals"]["verdict"] == rutim.DIVERGENT
    # existing already carries the real DV_UVM hook convention; the generic
    # composer's generated top does not reproduce it.
    assert result["uvm_hooks"]["verdict"] == rutim.EXISTING_ONLY


def test_compare_reports_not_comparable_dut_when_dut_module_name_undeclared(tmp_path):
    f = tmp_path / "legacy_tb_top.sv"
    f.write_text(EXISTING_TOP_NO_HOOKS, encoding="utf-8")
    existing = rutim.extract_existing_top_tb_facts(f)  # no dut_module_name supplied
    generated = rutim.generated_top_tb_facts(_SOC_SUBSYSTEMS, _SOC_MANIFEST)  # neither side declares it

    result = rutim.compare_against_generated_top(existing, generated)

    assert result["dut_instantiation"]["verdict"] == rutim.NOT_COMPARABLE


def test_compare_reports_match_when_both_sides_agree_on_clock_name():
    existing = rutim.extract_top_tb_facts_from_text(
        "module t;\n  logic clk;\n  logic rst_n;\nendmodule\n",
        source_label="existing", dut_module_name="some_dut")
    generated = rutim.extract_top_tb_facts_from_text(
        "module t2;\n  logic clk;\n  logic rst_n;\nendmodule\n",
        source_label="generated", dut_module_name="some_dut")

    result = rutim.compare_against_generated_top(existing, generated)

    assert result["clock_signals"]["verdict"] == rutim.MATCH
    assert result["reset_signals"]["verdict"] == rutim.MATCH
    assert result["dut_instantiation"]["verdict"] == rutim.MATCH  # both genuinely ABSENT
    assert result["uvm_hooks"]["verdict"] == rutim.MATCH  # both genuinely absent


def test_compare_reports_generated_only_when_only_generated_side_has_the_fact():
    existing = rutim.extract_top_tb_facts_from_text(
        "module t;\nendmodule\n", source_label="existing", dut_module_name="some_dut")
    generated = rutim.extract_top_tb_facts_from_text(
        "module t2;\n  logic gen_clk;\nendmodule\n",
        source_label="generated", dut_module_name="some_dut")

    result = rutim.compare_against_generated_top(existing, generated)

    assert result["clock_signals"]["verdict"] == rutim.GENERATED_ONLY


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
