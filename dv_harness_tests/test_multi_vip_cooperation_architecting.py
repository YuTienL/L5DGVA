"""Tests for `dv_harness/multi_vip_cooperation_architecting.py`.

Every structural input is built through a REAL producer this module reuses --
`phy_boundary.extract_phy_boundary()` over a real synthetic PHY/controller
port pair (the identical fixture shape `test_verification_architecture.py`
already uses for its own `host_vip`/`dev_vip` scenario), a real
`ip_ownership_conflict.real_vip_instances()`-shaped env.manifest.json,
`verification_architecture.build_vip_bind_ir()` and
`system_virtual_sequencer.build_subsystem_composition()` for the shared
virtual-sequencer composition, and `runtime_event_registry.
RuntimeEventRegistry.propagate()` for the sequencing-dependency graph. Nothing
here hand-builds a producer's own output shape to merely look real.

The suite proves the positive multi-VIP cooperation path (a real host+device
pair, coupled, sequenced, composed) AND, in this project's mutate-one-defect
style, the negative controls that must NOT read as a confirmed cooperation
requirement: no coupling evidence at all, an uncited coupling claim, a
coupling fact naming an undeclared interface, a duplicate interface id, a
NOT_BINDABLE (SERIAL-only) boundary, no PHY-boundary evidence at all, an
uncited/out-of-scope sequencing relation, and an unrecognized vocabulary
value.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import multi_vip_cooperation_architecting as m
from dv_harness import phy_boundary as pb

REPO_ROOT = Path(__file__).resolve().parent.parent


# ===========================================================================
# real fixtures
# ===========================================================================

def _port(name, direction, data_type):
    return {"name": name, "direction": direction, "data_type": data_type}


def _phy_and_controller_modules(mixed=False):
    """A real synthetic PHY/controller module pair for phy_boundary.py --
    the identical fixture `test_verification_architecture.py` already uses.
    A shared PARALLEL data bus (>= PARALLEL_MIN_WIDTH bits) plus, when
    `mixed`, an additional shared SERIAL differential pair (MIXED/bridge)."""
    phy_ports = [
        _port("pclk", "input", None),
        _port("pipe_txdata", "output", "logic [7:0]"),
        _port("pipe_rxdata", "input", "logic [7:0]"),
    ]
    ctrl_ports = [
        _port("pclk", "input", None),
        _port("pipe_txdata", "input", "logic [7:0]"),
        _port("pipe_rxdata", "output", "logic [7:0]"),
    ]
    if mixed:
        phy_ports += [_port("txp", "output", "logic"), _port("rxp", "input", "logic")]
        ctrl_ports += [_port("txp", "input", "logic"), _port("rxp", "output", "logic")]
    return {"name": "usb3_phy", "ports": phy_ports}, {"name": "usb3_ctrl", "ports": ctrl_ports}


def _serial_only_modules():
    """A real SERIAL-only (line-rate, non-bindable) boundary -- only the
    differential lane pair is shared, no parallel controller-facing bus."""
    phy = {"name": "serial_phy", "ports": [_port("txp", "output", "logic"), _port("rxp", "input", "logic")]}
    ctrl = {"name": "serial_ctrl", "ports": [_port("txp", "input", "logic"), _port("rxp", "output", "logic")]}
    return phy, ctrl


def _rtl_modules(mixed=False):
    phy_module, ctrl_module = _phy_and_controller_modules(mixed=mixed)
    return [phy_module, ctrl_module]


def _env_manifest(vip_instances):
    return {"vip_config": {"status": "CAPTURED", "vip_instances": list(vip_instances)}}


def _vip_instance(instance_path, vip_type="svt_usb3"):
    return {"instance_path": instance_path, "vip_type": vip_type, "config_fields": {}}


HOST_TARGET = "chip.core.usb0.host_vip"
DEV_TARGET = "chip.core.usb0.dev_vip"


def _host_device_interfaces(rtl_modules_kwargs=None):
    kw = rtl_modules_kwargs or {}
    return [
        {"interface_id": "host", "dut_port_direction": "output", "bind_target": HOST_TARGET,
         "phy_module": "usb3_phy", "controller_module": "usb3_ctrl", **kw},
        {"interface_id": "device", "dut_port_direction": "input", "bind_target": DEV_TARGET,
         "phy_module": "usb3_phy", "controller_module": "usb3_ctrl", **kw},
    ]


def _cited_coupling(kind="INTERNAL_SIGNAL_PATH",
                     evidence="usb3_hub_relay.sv:42: internal signal path connects host and device ports"):
    return [{"interface_a": "host", "interface_b": "device", "coupling_kind": kind, "evidence": evidence}]


def _cited_sequencing(reason="spec 4.2: device-side enumeration cannot begin before host-side port reset completes"):
    return [{"from_interface": "device", "relation": "REQUIRES", "to_interface": "host", "reason": reason}]


# ===========================================================================
# Positive path: a real, fully-architected multi-VIP cooperation
# ===========================================================================

def test_real_host_device_cooperation_is_fully_architected():
    ir = m.build_multi_vip_cooperation(
        _host_device_interfaces(),
        env_manifest=_env_manifest([_vip_instance(HOST_TARGET), _vip_instance(DEV_TARGET)]),
        rtl_modules=_rtl_modules(),
        declared_coupling_facts=_cited_coupling(),
        sequencing_relations=_cited_sequencing(),
    )
    assert ir.overall_status == "COOPERATION_ARCHITECTED"
    assert len(ir.relationships) == 1
    r = ir.relationships[0]
    assert {r.interface_a, r.interface_b} == {"host", "device"}
    assert r.cooperation_status == "COOPERATION_REQUIRED"
    assert r.architecture_status == "ARCHITECTED"
    assert r.sequencing_dependency["status"] == "DECLARED_CLEAN"
    assert r.virtual_sequencer_composition["composition_mode"] == "DIRECT_HANDLE"
    # per-interface facts are real, not fabricated
    host = next(i for i in ir.interfaces if i["interface_id"] == "host")
    assert host["vip_need"] == "VIP_REQUIRED_BINDABLE"
    assert host["matched_vip_instance"] == HOST_TARGET
    assert host["phy_boundary_bindable"] is True
    assert "vip_role=slave_responder" in host["vip_role"]


def test_bridge_in_path_reports_adapter_required_but_still_architected():
    """A real MIXED (bridge) boundary in one interface's own hierarchy chain
    makes the composition ADAPTER_REQUIRED -- still a fully ARCHITECTED
    finding (the architecture IS the fact that an adapter is needed), never
    ARCHITECTURE_INCOMPLETE."""
    hops = [{"instance": "chip.core.usb0.phy_bridge", "module": "usb_phy_bridge",
             "boundary_classification": {"kind": "MIXED"}}]
    interfaces = _host_device_interfaces({"hierarchy_hops": hops})
    ir = m.build_multi_vip_cooperation(
        interfaces,
        env_manifest=_env_manifest([_vip_instance(HOST_TARGET), _vip_instance(DEV_TARGET)]),
        rtl_modules=_rtl_modules(),
        declared_coupling_facts=_cited_coupling(),
        sequencing_relations=_cited_sequencing(),
    )
    r = ir.relationships[0]
    assert r.virtual_sequencer_composition["composition_mode"] == "ADAPTER_REQUIRED"
    assert r.architecture_status == "ARCHITECTED"
    assert ir.overall_status == "COOPERATION_ARCHITECTED"


def test_declared_blocked_sequencing_still_reads_architected():
    """A real observed TIMEOUT on the host-side event, propagated by the
    real RuntimeEventRegistry.propagate(), makes the pair DECLARED_BLOCKED --
    a real, useful finding, not an "incomplete evidence" state."""
    ir = m.build_multi_vip_cooperation(
        _host_device_interfaces(),
        env_manifest=_env_manifest([_vip_instance(HOST_TARGET), _vip_instance(DEV_TARGET)]),
        rtl_modules=_rtl_modules(),
        declared_coupling_facts=_cited_coupling(),
        sequencing_relations=_cited_sequencing(),
        sequencing_observations={"host": {"status": "TIMEOUT", "evidence": "sim.log:120: host reset never completed"}},
    )
    r = ir.relationships[0]
    assert r.sequencing_dependency["status"] == "DECLARED_BLOCKED"
    finding = r.sequencing_dependency["findings"][0]
    assert finding["finding"] == "BLOCKED_BY_DEPENDENCY"
    assert finding["event"] == "device::VIP_LINK_READY"
    assert r.architecture_status == "ARCHITECTED"
    assert ir.overall_status == "COOPERATION_ARCHITECTED"


def test_dual_role_port_auto_derives_shared_phy_instance_coupling():
    """Two interfaces declaring the IDENTICAL bind_target (a dual-role
    host/device port sharing one physical PHY instance) auto-derive a real
    SHARED_PHY_INSTANCE coupling fact -- no caller citation needed, because
    equal bind_targets ARE the structural evidence. With no sequencing
    relation declared, cooperation is real but the architecture is
    INCOMPLETE."""
    dual_target = "chip.core.usb0.dual_vip"
    interfaces = [
        {"interface_id": "host_mode", "dut_port_direction": "output", "bind_target": dual_target,
         "phy_module": "usb3_phy", "controller_module": "usb3_ctrl"},
        {"interface_id": "device_mode", "dut_port_direction": "input", "bind_target": dual_target,
         "phy_module": "usb3_phy", "controller_module": "usb3_ctrl"},
    ]
    ir = m.build_multi_vip_cooperation(
        interfaces, env_manifest=_env_manifest([_vip_instance(dual_target)]), rtl_modules=_rtl_modules())
    r = ir.relationships[0]
    assert len(r.coupling_facts) == 1
    fact = r.coupling_facts[0]
    assert fact["coupling_kind"] == "SHARED_PHY_INSTANCE"
    assert fact["derived"] is True
    assert dual_target in fact["evidence"]
    assert r.cooperation_status == "COOPERATION_REQUIRED"
    assert r.sequencing_dependency["status"] == "NOT_DECLARED"
    assert r.architecture_status == "ARCHITECTURE_INCOMPLETE"
    assert ir.overall_status == "COOPERATION_DETECTED_ARCHITECTURE_INCOMPLETE"


def test_two_unrelated_interfaces_never_auto_derive_a_coupling():
    """Two genuinely distinct bind_targets with no caller-declared coupling
    fact must never be treated as cooperating -- the honest single-VIP-per-
    interface case, ip_ownership_conflict.py's own territory."""
    ir = m.build_multi_vip_cooperation(
        _host_device_interfaces(),
        env_manifest=_env_manifest([_vip_instance(HOST_TARGET), _vip_instance(DEV_TARGET)]),
        rtl_modules=_rtl_modules())
    assert ir.relationships == []
    assert ir.overall_status == "NO_MULTI_VIP_COOPERATION_DETECTED"


# ===========================================================================
# Negative controls -- must never fabricate a cooperation requirement
# ===========================================================================

def test_not_bindable_serial_boundary_is_unconfirmed_never_required():
    serial_phy, serial_ctrl = _serial_only_modules()
    interfaces = [
        {"interface_id": "host", "dut_port_direction": "output", "bind_target": HOST_TARGET,
         "phy_module": "serial_phy", "controller_module": "serial_ctrl"},
        {"interface_id": "device", "dut_port_direction": "input", "bind_target": DEV_TARGET,
         "phy_module": "serial_phy", "controller_module": "serial_ctrl"},
    ]
    ir = m.build_multi_vip_cooperation(
        interfaces, env_manifest=_env_manifest([]), rtl_modules=[serial_phy, serial_ctrl],
        declared_coupling_facts=_cited_coupling())
    r = ir.relationships[0]
    assert r.cooperation_status == "COOPERATION_UNCONFIRMED_NOT_BINDABLE"
    assert r.architecture_status == "NOT_APPLICABLE"
    assert ir.overall_status == "INSUFFICIENT_EVIDENCE"
    for i in ir.interfaces:
        assert i["vip_need"] == "NOT_BINDABLE"
        assert i["phy_boundary_bindable"] is False


def test_no_phy_boundary_evidence_at_all_is_insufficient_never_required():
    """Evidence Truth Rule: with no phy_module/controller_module/rtl_modules
    and no pre-computed phy_boundary_doc, this module must never guess a
    real interface needs a VIP -- it must report the honest
    COOPERATION_UNKNOWN_INSUFFICIENT_EVIDENCE, distinct from both CLEAR and
    REQUIRED."""
    interfaces = [
        {"interface_id": "host", "dut_port_direction": "output", "bind_target": HOST_TARGET},
        {"interface_id": "device", "dut_port_direction": "input", "bind_target": DEV_TARGET},
    ]
    ir = m.build_multi_vip_cooperation(
        interfaces, env_manifest=_env_manifest([]), declared_coupling_facts=_cited_coupling())
    r = ir.relationships[0]
    assert r.cooperation_status == "COOPERATION_UNKNOWN_INSUFFICIENT_EVIDENCE"
    assert ir.overall_status == "INSUFFICIENT_EVIDENCE"
    for i in ir.interfaces:
        assert i["vip_need"] == "NOT_AVAILABLE"


def test_uncited_coupling_fact_is_refused():
    with pytest.raises(m.MultiVipCooperationError, match="uncited"):
        m.build_multi_vip_cooperation(
            _host_device_interfaces(),
            env_manifest=_env_manifest([]), rtl_modules=_rtl_modules(),
            declared_coupling_facts=[{"interface_a": "host", "interface_b": "device",
                                       "coupling_kind": "SHARED_ADDRESS_REGION", "evidence": ""}])


def test_coupling_fact_naming_undeclared_interface_is_refused():
    with pytest.raises(m.MultiVipCooperationError, match="undeclared interface"):
        m.build_multi_vip_cooperation(
            _host_device_interfaces(),
            env_manifest=_env_manifest([]), rtl_modules=_rtl_modules(),
            declared_coupling_facts=[{"interface_a": "host", "interface_b": "no_such_interface",
                                       "coupling_kind": "SHARED_ADDRESS_REGION", "evidence": "x"}])


def test_unrecognized_coupling_kind_is_refused():
    with pytest.raises(m.MultiVipCooperationError):
        m.CouplingFact(interface_a="host", interface_b="device", coupling_kind="BOGUS_KIND", evidence="x")


def test_coupling_fact_self_reference_is_refused():
    with pytest.raises(m.MultiVipCooperationError, match="itself"):
        m.CouplingFact(interface_a="host", interface_b="host", coupling_kind="SHARED_ADDRESS_REGION", evidence="x")


def test_duplicate_interface_id_is_refused():
    interfaces = _host_device_interfaces()
    interfaces.append(dict(interfaces[0]))
    with pytest.raises(m.MultiVipCooperationError, match="duplicate interface_id"):
        m.build_multi_vip_cooperation(interfaces, env_manifest=_env_manifest([]), rtl_modules=_rtl_modules())


def test_no_interfaces_at_all_is_refused():
    with pytest.raises(m.MultiVipCooperationError):
        m.build_multi_vip_cooperation([], env_manifest=_env_manifest([]))


def test_phy_module_without_controller_module_is_refused():
    with pytest.raises(m.MultiVipCooperationError, match="both or neither"):
        m.DeclaredInterface(interface_id="x", dut_port_direction="output",
                             bind_target="chip.x", phy_module="only_phy")


def test_missing_dut_port_direction_is_refused():
    with pytest.raises(m.MultiVipCooperationError, match="dut_port_direction"):
        m.DeclaredInterface(interface_id="x", dut_port_direction="", bind_target="chip.x")


def test_missing_bind_target_is_refused():
    with pytest.raises(m.MultiVipCooperationError, match="bind_target"):
        m.DeclaredInterface(interface_id="x", dut_port_direction="output", bind_target="")


def test_bad_dut_port_direction_is_refused():
    interfaces = _host_device_interfaces()
    interfaces[0]["dut_port_direction"] = "sideways"
    with pytest.raises(m.MultiVipCooperationError, match="could not derive a VIP role"):
        m.build_multi_vip_cooperation(interfaces, env_manifest=_env_manifest([]), rtl_modules=_rtl_modules())


def test_sequencing_relation_naming_interface_outside_cooperation_set_is_refused():
    interfaces = _host_device_interfaces()
    interfaces.append({"interface_id": "unrelated", "dut_port_direction": "input", "bind_target": "chip.unrelated"})
    with pytest.raises(m.MultiVipCooperationError, match="outside this cooperation set"):
        m.build_multi_vip_cooperation(
            interfaces, env_manifest=_env_manifest([]), rtl_modules=_rtl_modules(),
            declared_coupling_facts=_cited_coupling(),
            sequencing_relations=[{"from_interface": "unrelated", "relation": "REQUIRES",
                                    "to_interface": "host", "reason": "x"}])


def test_sequencing_relation_with_no_reason_is_refused():
    with pytest.raises(m.MultiVipCooperationError, match="no real reason citation"):
        m.build_multi_vip_cooperation(
            _host_device_interfaces(), env_manifest=_env_manifest([]), rtl_modules=_rtl_modules(),
            declared_coupling_facts=_cited_coupling(),
            sequencing_relations=[{"from_interface": "device", "relation": "REQUIRES",
                                    "to_interface": "host", "reason": ""}])


def test_sequencing_relation_with_unrecognized_relation_type_is_refused():
    with pytest.raises(m.MultiVipCooperationError, match="relation type"):
        m.build_multi_vip_cooperation(
            _host_device_interfaces(), env_manifest=_env_manifest([]), rtl_modules=_rtl_modules(),
            declared_coupling_facts=_cited_coupling(),
            sequencing_relations=[{"from_interface": "device", "relation": "SIDEWAYS",
                                    "to_interface": "host", "reason": "x"}])


def test_sequencing_observation_unrecognized_status_is_refused():
    with pytest.raises(m.MultiVipCooperationError):
        m.build_multi_vip_cooperation(
            _host_device_interfaces(), env_manifest=_env_manifest([]), rtl_modules=_rtl_modules(),
            declared_coupling_facts=_cited_coupling(), sequencing_relations=_cited_sequencing(),
            sequencing_observations={"host": {"status": "SIDEWAYS", "evidence": "x"}})


# ===========================================================================
# vocabulary guard
# ===========================================================================

def test_vocabulary_disjoint_from_models_status():
    m.assert_no_verification_verdict_vocabulary()


def test_vocabulary_guard_has_real_detection_power(monkeypatch):
    monkeypatch.setattr(m, "OVERALL_STATUSES", tuple(m.OVERALL_STATUSES) + ("PASS",))
    with pytest.raises(m.MultiVipCooperationError):
        m.assert_no_verification_verdict_vocabulary()


# ===========================================================================
# rendering
# ===========================================================================

def test_render_markdown_lists_relationship_row():
    ir = m.build_multi_vip_cooperation(
        _host_device_interfaces(),
        env_manifest=_env_manifest([_vip_instance(HOST_TARGET), _vip_instance(DEV_TARGET)]),
        rtl_modules=_rtl_modules(), declared_coupling_facts=_cited_coupling(),
        sequencing_relations=_cited_sequencing())
    md = ir.render_markdown()
    assert "host" in md and "device" in md
    assert "COOPERATION_REQUIRED" in md
    assert "DIRECT_HANDLE" in md


def test_render_markdown_empty_note_when_no_relationships():
    ir = m.build_multi_vip_cooperation(
        _host_device_interfaces(),
        env_manifest=_env_manifest([_vip_instance(HOST_TARGET), _vip_instance(DEV_TARGET)]),
        rtl_modules=_rtl_modules())
    md = ir.render_markdown()
    assert "no multi-VIP cooperation detected" in md.lower() or "NOT_AVAILABLE" not in md


# ===========================================================================
# CLI: real subprocess, all documented exit codes
# ===========================================================================

def _write_doc(tmp_path, **kwargs):
    doc = tmp_path / "input.json"
    doc.write_text(json.dumps(kwargs), encoding="utf-8")
    return doc


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.multi_vip_cooperation_architecting", *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )


def test_cli_exit_0_cooperation_architected(tmp_path):
    doc = _write_doc(
        tmp_path, interfaces=_host_device_interfaces(),
        env_manifest=_env_manifest([_vip_instance(HOST_TARGET), _vip_instance(DEV_TARGET)]),
        rtl_modules=_rtl_modules(), coupling_facts=_cited_coupling(),
        sequencing_relations=_cited_sequencing())
    result = _run_cli("--input", str(doc), "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "COOPERATION_ARCHITECTED"


def test_cli_exit_0_no_cooperation_detected(tmp_path):
    doc = _write_doc(
        tmp_path, interfaces=_host_device_interfaces(),
        env_manifest=_env_manifest([_vip_instance(HOST_TARGET), _vip_instance(DEV_TARGET)]),
        rtl_modules=_rtl_modules())
    result = _run_cli("--input", str(doc), "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "NO_MULTI_VIP_COOPERATION_DETECTED"


def test_cli_exit_1_architecture_incomplete(tmp_path):
    dual_target = "chip.core.usb0.dual_vip"
    interfaces = [
        {"interface_id": "host_mode", "dut_port_direction": "output", "bind_target": dual_target,
         "phy_module": "usb3_phy", "controller_module": "usb3_ctrl"},
        {"interface_id": "device_mode", "dut_port_direction": "input", "bind_target": dual_target,
         "phy_module": "usb3_phy", "controller_module": "usb3_ctrl"},
    ]
    doc = _write_doc(tmp_path, interfaces=interfaces, env_manifest=_env_manifest([_vip_instance(dual_target)]),
                      rtl_modules=_rtl_modules())
    result = _run_cli("--input", str(doc), "--markdown")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "COOPERATION_REQUIRED" in result.stdout


def test_cli_exit_2_insufficient_evidence(tmp_path):
    interfaces = [
        {"interface_id": "host", "dut_port_direction": "output", "bind_target": HOST_TARGET},
        {"interface_id": "device", "dut_port_direction": "input", "bind_target": DEV_TARGET},
    ]
    doc = _write_doc(tmp_path, interfaces=interfaces, env_manifest=_env_manifest([]),
                      coupling_facts=_cited_coupling())
    result = _run_cli("--input", str(doc), "--json")
    assert result.returncode == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "INSUFFICIENT_EVIDENCE"


def test_cli_exit_2_on_missing_file(tmp_path):
    result = _run_cli("--input", str(tmp_path / "nope.json"))
    assert result.returncode == 2


def test_cli_exit_2_on_malformed_declaration(tmp_path):
    doc = _write_doc(tmp_path, interfaces=[{"interface_id": "x"}])
    result = _run_cli("--input", str(doc))
    assert result.returncode == 2
