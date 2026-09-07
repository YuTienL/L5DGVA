"""Tests for dv_harness/iface_contract_vip_bind_validator.py -- spec section
219's Interface Contract / VIP Bind Validator.

Discipline (the same one test_vip_api_card.py uses):
  1. A CLEAN declared contract, validated against a REAL bind statement (grepped
     from a real temp file by the real connectivity.grep_existing_binds()) and
     REAL verible_parser.ModuleInfo/PortInfo evidence, reports PROVEN on every
     axis with zero BLOCKED/UNPROVABLE cards -- a validator that fires on
     correct input is unusable no matter what else it catches.
  2. Every BLOCKED rule is then driven by mutating exactly one fact away from
     that clean baseline (one wrong signal, one wrong protocol, one wrong
     direction) so each assertion proves the validator caught THAT specific
     defect, never a coincidence.
  3. Every UNPROVABLE / OUT_OF_SCOPE / NOT_AVAILABLE path is exercised as its
     own real negative control: no bind found, no modules supplied, no
     contracts supplied, an axis simply not declared -- each must degrade to
     the honestly-named status and never to a silently-passing PROVEN.
  4. The whole-report worst-wins fold (one BLOCKED card among clean ones still
     fails the report) and the real `python -m` CLI subprocess (all four exit
     codes) are both driven end to end.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import connectivity as conn
from dv_harness import iface_contract_vip_bind_validator as icv
from dv_harness.vip_api_card import BLOCKED, NOT_AVAILABLE, OUT_OF_SCOPE, PROVEN, UNPROVABLE

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# shared real fixtures
# ---------------------------------------------------------------------------

def _axi4_module() -> conn.verible_parser.ModuleInfo:
    """A REAL ModuleInfo/PortInfo dataclass tree -- the exact shape
    connectivity.build_interface_fingerprints() and this validator both
    consume, and the same construction technique test_connectivity.py itself
    uses in place of a live verible run."""
    P = conn.verible_parser.PortInfo
    return conn.verible_parser.ModuleInfo(
        name="usb3_axi_target",
        ports=[
            P(name="awvalid", direction="input", data_type="logic"),
            P(name="awready", direction="output", data_type="logic"),
            P(name="awaddr", direction="input", data_type="logic [31:0]"),
            P(name="awlen", direction="input", data_type="logic [7:0]"),
            P(name="awsize", direction="input", data_type="logic [2:0]"),
            P(name="awburst", direction="input", data_type="logic [1:0]"),
            P(name="awid", direction="input", data_type="logic [3:0]"),
            P(name="wvalid", direction="input", data_type="logic"),
            P(name="wready", direction="output", data_type="logic"),
            P(name="wdata", direction="input", data_type="logic [31:0]"),
            P(name="wlast", direction="input", data_type="logic"),
            P(name="bvalid", direction="output", data_type="logic"),
            P(name="bready", direction="input", data_type="logic"),
            P(name="bresp", direction="output", data_type="logic [1:0]"),
            P(name="bid", direction="output", data_type="logic [3:0]"),
            P(name="arvalid", direction="input", data_type="logic"),
            P(name="arready", direction="output", data_type="logic"),
            P(name="araddr", direction="input", data_type="logic [31:0]"),
            P(name="arlen", direction="input", data_type="logic [7:0]"),
            P(name="arsize", direction="input", data_type="logic [2:0]"),
            P(name="arburst", direction="input", data_type="logic [1:0]"),
            P(name="arid", direction="input", data_type="logic [3:0]"),
            P(name="rvalid", direction="output", data_type="logic"),
            P(name="rready", direction="input", data_type="logic"),
            P(name="rdata", direction="output", data_type="logic [31:0]"),
            P(name="rresp", direction="output", data_type="logic [1:0]"),
            P(name="rid", direction="output", data_type="logic [3:0]"),
            P(name="rlast", direction="output", data_type="logic"),
        ],
    )


def _write_bind_file(tmp_path: Path, target: str = "tb_top.dut.usb0",
                     bound_module: str = "usb3_axi_target") -> Path:
    sv = tmp_path / "bind_usb0.sv"
    sv.write_text(
        f"bind {target} {bound_module} u_axi_vip_bind (.*);\n",
        encoding="utf-8",
    )
    return sv


def _clean_contract() -> dict:
    return {
        "interface": "usb0_axi_target",
        "target_instance": "tb_top.dut.usb0",
        "protocol": "AXI4",
        "direction": "input",
        "anchor_signal": "awvalid",
        "signals": ["AWVALID", "AWREADY", "WVALID", "BVALID", "ARVALID", "RVALID"],
    }


def _validate(tmp_path, contract_dict, *, module=None):
    contracts = icv.load_declared_contracts([contract_dict])
    binds = conn.grep_existing_binds(tmp_path)
    modules = [module] if module is not None else [_axi4_module()]
    return icv.validate_interface_contracts(contracts, binds=binds, modules=modules)


# ===========================================================================
# 1. clean baseline: real bind + real ports -> PROVEN on every axis
# ===========================================================================

def test_clean_contract_is_proven_on_every_axis(tmp_path):
    _write_bind_file(tmp_path)
    report = _validate(tmp_path, _clean_contract())
    assert report.status == PROVEN
    assert report.counts == {PROVEN: 1, BLOCKED: 0, UNPROVABLE: 0, NOT_AVAILABLE: 0}
    card = report.cards[0]
    assert card.status == PROVEN
    assert card.signal_axis["status"] == PROVEN
    assert card.protocol_axis["status"] == PROVEN
    assert card.protocol_axis["resolved"] == "AXI4"
    assert card.direction_axis["status"] == PROVEN
    # awvalid is an INPUT on the DUT's target module (the VIP drives it in),
    # so the DUT is the target and the VIP is the master/initiator -- the
    # real, name-free determine_role_from_port_direction() verdict.
    assert card.direction_axis["derived_role"].startswith("vip_role=master_initiator")
    # the bind citation is real, not synthesized
    assert card.bind["bound_module"] == "usb3_axi_target"
    assert card.bind["line_no"] == 1
    assert card.bind["tier"] == conn.BindTier.T1_ALREADY_DECIDED.value


def test_report_to_dict_round_trips_through_json(tmp_path):
    _write_bind_file(tmp_path)
    report = _validate(tmp_path, _clean_contract())
    blob = json.dumps(report.to_dict())
    doc = json.loads(blob)
    assert doc["status"] == PROVEN
    assert doc["cards"][0]["signal_axis"]["matched"]


# ===========================================================================
# 2. BLOCKED: each axis mutated away from the clean baseline, one at a time
# ===========================================================================

def test_signal_axis_blocked_on_fabricated_signal(tmp_path):
    _write_bind_file(tmp_path)
    bad = _clean_contract()
    bad["signals"] = bad["signals"] + ["AWQOS_THAT_DOES_NOT_EXIST"]
    report = _validate(tmp_path, bad)
    assert report.status == BLOCKED
    card = report.cards[0]
    assert card.signal_axis["status"] == BLOCKED
    assert card.signal_axis["reason"] == icv.R_SIGNAL_MISSING
    assert "AWQOS_THAT_DOES_NOT_EXIST" in card.signal_axis["missing"]
    # the other two axes are still independently PROVEN -- worst-wins does not
    # smear one bad axis's reason across the others
    assert card.protocol_axis["status"] == PROVEN
    assert card.direction_axis["status"] == PROVEN
    assert card.reason == icv.R_SIGNAL_MISSING


def test_protocol_axis_blocked_on_wrong_declared_protocol(tmp_path):
    _write_bind_file(tmp_path)
    bad = _clean_contract()
    bad["protocol"] = "AHB"  # real evidence resolves to AXI4, not AHB
    report = _validate(tmp_path, bad)
    assert report.status == BLOCKED
    card = report.cards[0]
    assert card.protocol_axis["status"] == BLOCKED
    assert card.protocol_axis["reason"] == icv.R_PROTOCOL_RESOLVED_MISMATCH
    assert card.protocol_axis["resolved"] == "AXI4"


def test_protocol_axis_blocked_on_amba_declared_but_zero_amba_evidence(tmp_path):
    _write_bind_file(tmp_path, bound_module="plain_glue_logic")
    module = conn.verible_parser.ModuleInfo(
        name="plain_glue_logic",
        ports=[conn.verible_parser.PortInfo(name="clk", direction="input", data_type="logic"),
               conn.verible_parser.PortInfo(name="rst_n", direction="input", data_type="logic")],
    )
    bad = _clean_contract()
    bad["signals"] = []          # only checking the protocol axis here
    bad["direction"] = None
    bad["anchor_signal"] = None
    report = _validate(tmp_path, bad, module=module)
    assert report.status == BLOCKED
    card = report.cards[0]
    assert card.protocol_axis["status"] == BLOCKED
    assert card.protocol_axis["reason"] == icv.R_PROTOCOL_NOT_AMBA
    assert card.signal_axis["status"] == OUT_OF_SCOPE
    assert card.direction_axis["status"] == OUT_OF_SCOPE


def test_direction_axis_blocked_on_wrong_declared_direction(tmp_path):
    _write_bind_file(tmp_path)
    bad = _clean_contract()
    bad["direction"] = "output"  # the real awvalid port is an input
    report = _validate(tmp_path, bad)
    assert report.status == BLOCKED
    card = report.cards[0]
    assert card.direction_axis["status"] == BLOCKED
    assert card.direction_axis["reason"] == icv.R_DIRECTION_MISMATCH
    assert card.direction_axis["actual"] == "input"
    assert card.direction_axis["declared"] == "output"


# ===========================================================================
# 3. UNPROVABLE / OUT_OF_SCOPE / NOT_AVAILABLE -- the honesty surface
# ===========================================================================

def test_no_bind_found_is_unprovable_never_a_silent_pass(tmp_path):
    # tmp_path has no bind file at all -- grep_existing_binds() finds nothing
    report = _validate(tmp_path, _clean_contract())
    assert report.status == UNPROVABLE
    card = report.cards[0]
    assert card.status == UNPROVABLE
    assert card.reason == icv.R_NO_BIND
    assert card.bind is None
    assert card.signal_axis["status"] == UNPROVABLE
    assert card.protocol_axis["status"] == UNPROVABLE
    assert card.direction_axis["status"] == UNPROVABLE


def test_bound_module_ports_not_supplied_is_unprovable(tmp_path):
    _write_bind_file(tmp_path)
    contracts = icv.load_declared_contracts([_clean_contract()])
    binds = conn.grep_existing_binds(tmp_path)
    report = icv.validate_interface_contracts(contracts, binds=binds, modules=[])
    assert report.status == UNPROVABLE
    card = report.cards[0]
    assert card.bind is not None  # the bind itself IS real evidence
    assert card.signal_axis["status"] == UNPROVABLE
    assert card.signal_axis["reason"] == icv.R_MODULE_NOT_SUPPLIED
    assert card.protocol_axis["status"] == UNPROVABLE
    assert card.direction_axis["status"] == UNPROVABLE


def test_undeclared_axes_are_out_of_scope_not_fabricated_pass_or_fail(tmp_path):
    _write_bind_file(tmp_path)
    minimal = {"interface": "usb0_axi_target", "target_instance": "tb_top.dut.usb0"}
    report = _validate(tmp_path, minimal)
    # nothing was declared to check -> nothing decided -> honestly NOT_AVAILABLE,
    # never a vacuous PROVEN
    assert report.status == NOT_AVAILABLE
    card = report.cards[0]
    assert card.status == NOT_AVAILABLE
    assert card.signal_axis["status"] == OUT_OF_SCOPE
    assert card.protocol_axis["status"] == OUT_OF_SCOPE
    assert card.direction_axis["status"] == OUT_OF_SCOPE


def test_anchor_signal_absent_from_real_ports_is_unprovable(tmp_path):
    _write_bind_file(tmp_path)
    bad = _clean_contract()
    bad["signals"] = []
    bad["protocol"] = None
    bad["anchor_signal"] = "NO_SUCH_PORT_ANYWHERE"
    report = _validate(tmp_path, bad)
    assert report.status == UNPROVABLE
    card = report.cards[0]
    assert card.direction_axis["status"] == UNPROVABLE
    assert card.direction_axis["reason"] == icv.R_DIRECTION_ANCHOR_MISSING


def test_partial_protocol_evidence_is_unprovable_not_blocked(tmp_path):
    """connectivity.PROTOCOL_FINGERPRINTS' non-AMBA entries require the FULL
    signature; partial real evidence must not be rounded up to a hard
    BLOCKED against a fingerprint this repo's own module docstring flags as
    illustrative/unverified -- it must degrade to UNPROVABLE."""
    _write_bind_file(tmp_path, bound_module="usb3_partial")
    module = conn.verible_parser.ModuleInfo(
        name="usb3_partial",
        ports=[conn.verible_parser.PortInfo(name="tx_hs_p", direction="output", data_type="logic")],
        # USB3 fingerprint needs TX_HS_P, TX_HS_N, RX_HS_P, RX_HS_N -- only one present
    )
    bad = {"interface": "usb0_usb3", "target_instance": "tb_top.dut.usb0", "protocol": "USB3"}
    report = _validate(tmp_path, bad, module=module)
    assert report.status == UNPROVABLE
    assert report.cards[0].protocol_axis["status"] == UNPROVABLE
    assert report.cards[0].protocol_axis["reason"] == icv.R_PROTOCOL_PARTIAL_EVIDENCE


def test_no_contracts_supplied_is_not_available(tmp_path):
    report = icv.validate_interface_contracts([], binds=[], modules=[])
    assert report.status == NOT_AVAILABLE
    assert report.reason == icv.R_NO_CONTRACTS
    assert report.cards == []


def test_unknown_protocol_fingerprint_is_unprovable(tmp_path):
    _write_bind_file(tmp_path)
    bad = _clean_contract()
    bad["signals"] = []
    bad["direction"] = None
    bad["anchor_signal"] = None
    bad["protocol"] = "TOTALLY_MADE_UP_PROTOCOL"
    report = _validate(tmp_path, bad)
    assert report.status == UNPROVABLE
    assert report.cards[0].protocol_axis["reason"] == icv.R_PROTOCOL_UNKNOWN_FINGERPRINT


# ===========================================================================
# 4. worst-wins composite: one BLOCKED interface fails the whole report
# ===========================================================================

def test_one_blocked_card_among_clean_ones_fails_the_whole_report(tmp_path):
    _write_bind_file(tmp_path, target="tb_top.dut.usb0", bound_module="usb3_axi_target")
    sv2 = tmp_path / "bind_usb1.sv"
    sv2.write_text("bind tb_top.dut.usb1 usb3_axi_target u_axi_vip_bind1 (.*);\n", encoding="utf-8")

    good = _clean_contract()
    bad = _clean_contract()
    bad["interface"] = "usb1_axi_target"
    bad["target_instance"] = "tb_top.dut.usb1"
    bad["protocol"] = "AHB"  # the one wrong fact

    contracts = icv.load_declared_contracts([good, bad])
    binds = conn.grep_existing_binds(tmp_path)
    report = icv.validate_interface_contracts(contracts, binds=binds, modules=[_axi4_module()])
    assert report.status == BLOCKED
    assert report.counts[BLOCKED] == 1
    assert report.counts[PROVEN] == 1
    statuses = {c.interface: c.status for c in report.cards}
    assert statuses["usb0_axi_target"] == PROVEN
    assert statuses["usb1_axi_target"] == BLOCKED


# ===========================================================================
# malformed-input negative controls
# ===========================================================================

def test_missing_required_field_raises_named_error():
    with pytest.raises(icv.InterfaceContractError) as exc:
        icv.load_declared_contracts([{"interface": "x"}])  # no target_instance
    assert exc.value.reason == icv.R_MISSING_FIELD


def test_duplicate_interface_name_raises_named_error():
    rec = _clean_contract()
    with pytest.raises(icv.InterfaceContractError) as exc:
        icv.load_declared_contracts([rec, dict(rec)])
    assert exc.value.reason == icv.R_DUPLICATE_INTERFACE


def test_non_dict_record_raises_named_error():
    with pytest.raises(icv.InterfaceContractError) as exc:
        icv.load_declared_contracts(["not-a-dict"])
    assert exc.value.reason == icv.R_MISSING_FIELD


# ===========================================================================
# real subprocess CLI, all four exit codes
# ===========================================================================

def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.iface_contract_vip_bind_validator", *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )


def test_cli_proven_exit_0(tmp_path):
    _write_bind_file(tmp_path)
    contracts_path = tmp_path / "contracts.json"
    contracts_path.write_text(json.dumps({"interfaces": [_clean_contract()]}), encoding="utf-8")
    modules_path = tmp_path / "modules.json"
    modules_path.write_text(json.dumps([{
        "name": "usb3_axi_target",
        "ports": [{"name": p.name, "direction": p.direction} for p in _axi4_module().ports],
    }]), encoding="utf-8")

    proc = _run_cli("--contracts", str(contracts_path), "--bind-root", str(tmp_path),
                    "--modules", str(modules_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PROVEN" in proc.stdout


def test_cli_blocked_exit_1(tmp_path):
    _write_bind_file(tmp_path)
    bad = _clean_contract()
    bad["protocol"] = "AHB"
    contracts_path = tmp_path / "contracts.json"
    contracts_path.write_text(json.dumps({"interfaces": [bad]}), encoding="utf-8")
    modules_path = tmp_path / "modules.json"
    modules_path.write_text(json.dumps([{
        "name": "usb3_axi_target",
        "ports": [{"name": p.name, "direction": p.direction} for p in _axi4_module().ports],
    }]), encoding="utf-8")

    proc = _run_cli("--contracts", str(contracts_path), "--bind-root", str(tmp_path),
                    "--modules", str(modules_path))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "BLOCKED" in proc.stdout


def test_cli_not_available_exit_2_no_contracts(tmp_path):
    contracts_path = tmp_path / "contracts.json"
    contracts_path.write_text(json.dumps({"interfaces": []}), encoding="utf-8")
    proc = _run_cli("--contracts", str(contracts_path))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "NOT_AVAILABLE" in proc.stdout


def test_cli_unprovable_exit_3_by_default_0(tmp_path):
    contracts_path = tmp_path / "contracts.json"
    contracts_path.write_text(json.dumps({"interfaces": [_clean_contract()]}), encoding="utf-8")
    # no --bind-root at all -> no bind evidence -> UNPROVABLE
    proc = _run_cli("--contracts", str(contracts_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr  # UNPROVABLE is non-blocking by default
    assert "UNPROVABLE" in proc.stdout

    proc_strict = _run_cli("--contracts", str(contracts_path), "--strict-unprovable")
    assert proc_strict.returncode == 3, proc_strict.stdout + proc_strict.stderr


def test_cli_malformed_input_exit_2():
    proc = _run_cli("--contracts", "/no/such/file.json")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "InterfaceContractError" in proc.stdout or "InterfaceContractError" in proc.stderr


def test_cli_json_output_is_valid_json(tmp_path):
    _write_bind_file(tmp_path)
    contracts_path = tmp_path / "contracts.json"
    contracts_path.write_text(json.dumps({"interfaces": [_clean_contract()]}), encoding="utf-8")
    modules_path = tmp_path / "modules.json"
    modules_path.write_text(json.dumps([{
        "name": "usb3_axi_target",
        "ports": [{"name": p.name, "direction": p.direction} for p in _axi4_module().ports],
    }]), encoding="utf-8")
    proc = _run_cli("--contracts", str(contracts_path), "--bind-root", str(tmp_path),
                    "--modules", str(modules_path), "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["status"] == "PROVEN"
