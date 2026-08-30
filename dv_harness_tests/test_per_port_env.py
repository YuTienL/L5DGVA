"""Tests for the port_indexed / port_count vip_components schema extension
(2026-08-29, following the multi-component env extension in
test_multi_component_env.py).

Real evidence this closes a gap against: D:/DV/Task/DV_Agent_Harness_L5/
USB_UVM_Handoff/uvm/tb/env/usb_top_env.sv declares several components as
PER-PORT ARRAYS for its real dual-port USB DUT --
  line 77:  svt_usb_agent usb_host_agent[NUM_USB_PORTS];
  line 89:  usb_ep_check ep_check [2];
  line 95:  usb_perf_monitor perf_mon [2];
  line 100: usb_xfer_scoreboard xfer_sb [2];
  line 146: svt_usb_system_virtual_sequencer sys_virt_seqr [2];
and creates them in a `for (int p = 0; p < NUM_USB_PORTS; p++)` loop, e.g.
lines 407-414:
  port_name = $sformatf("usb_host_agent_%0d", p);
  usb_host_agent[p] = svt_usb_agent::type_id::create(port_name, this);
This is the standard UVM per-port array idiom -- protocol-agnostic (PCIe
multi-lane/multi-function, CAN-FD multi-node, etc), not USB-specific.

Schema (additive, backward compatible):
  - a vip_components entry may set "port_indexed": true
  - the manifest may set a top-level "port_count": <int>, required only if
    any component sets port_indexed: true

Groups:
  - a single port_indexed component + valid port_count emits a correct
    array declaration + for-loop creation
  - the missing/invalid port_count error case (InvalidPortCountError)
  - a realistic mixed manifest matching real USB dual-port evidence
    (clk_rst_agent scalar, host_agent/mon_agent port_indexed,
    port_count=2), confirming clk_rst_agent is created before the
    port_indexed for-loops (the realistic depends_on direction: a
    port-indexed component depending on a non-port-indexed one)
  - zero regression: the EXISTING non-port-indexed
    MULTI_COMPONENT_MANIFEST (imported from test_multi_component_env.py)
    still produces byte-identical output.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness.uvm_generator.generator import (
    InvalidPortCountError,
    UVMEnvironmentGenerator,
    sv_id,
)
from dv_harness.uvm_generator.protocol_env_generator import ProtocolEnvGenerator

from dv_harness_tests.test_multi_component_env import MULTI_COMPONENT_MANIFEST


# ---------------------------------------------------------------------------
# single port_indexed component + valid port_count
# ---------------------------------------------------------------------------

SINGLE_PORT_INDEXED_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "port_count": 2,
    "vip_components": [
        {"name": "host_agent", "class_type": "svt_usb_agent", "instance_name": "host_agent",
         "port_indexed": True, "depends_on": []},
    ],
}


def test_port_indexed_component_emits_array_declaration():
    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(SINGLE_PORT_INDEXED_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")
        assert "  svt_usb_agent host_agent[2];" in env_sv
        # never emitted as a bare scalar handle
        assert "  svt_usb_agent host_agent;" not in env_sv
    finally:
        shutil.rmtree(tmp)


def test_port_indexed_component_emits_for_loop_creation():
    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(SINGLE_PORT_INDEXED_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")
        assert "for (int p = 0; p < 2; p++) begin" in env_sv
        assert (
            'host_agent[p] = svt_usb_agent::type_id::create($sformatf("host_agent_%0d", p), this);'
            in env_sv
        )
        # never a scalar create() for a port_indexed component
        assert 'host_agent=svt_usb_agent::type_id::create("host_agent",this);' not in env_sv
    finally:
        shutil.rmtree(tmp)


def test_port_indexed_creation_direct_generator_call():
    """Pure/direct check on UVMEnvironmentGenerator.env() (bypassing the
    directory-layout wrapper), pinning the exact emitted array declaration
    and for-loop body."""
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(SINGLE_PORT_INDEXED_MANIFEST["protocol"])
        env_sv = gen.env(SINGLE_PORT_INDEXED_MANIFEST, p)
        assert "  svt_usb_agent host_agent[2];" in env_sv
        assert "    for (int p = 0; p < 2; p++) begin" in env_sv
        assert (
            '      host_agent[p] = svt_usb_agent::type_id::create($sformatf("host_agent_%0d", p), this);'
            in env_sv
        )
        assert "    end" in env_sv
        assert "    // no depends_on" in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# missing / invalid port_count -> InvalidPortCountError
# ---------------------------------------------------------------------------

def test_missing_port_count_raises_invalid_port_count_error():
    m = dict(SINGLE_PORT_INDEXED_MANIFEST)
    del m["port_count"]
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(InvalidPortCountError) as exc_info:
            gen.env(m, sv_id(m["protocol"]))
        err = exc_info.value
        assert err.reason == "INVALID_PORT_COUNT"
        assert err.detail["port_indexed_components"] == ["host_agent"]
        assert err.detail["port_count"] is None
    finally:
        shutil.rmtree(gen.out)


@pytest.mark.parametrize("bad_port_count", [0, -1, "2", 2.0, True, None])
def test_invalid_port_count_values_raise_invalid_port_count_error(bad_port_count):
    m = dict(SINGLE_PORT_INDEXED_MANIFEST, port_count=bad_port_count)
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(InvalidPortCountError) as exc_info:
            gen.env(m, sv_id(m["protocol"]))
        assert exc_info.value.reason == "INVALID_PORT_COUNT"
        assert exc_info.value.detail["port_count"] == bad_port_count
    finally:
        shutil.rmtree(gen.out)


def test_port_indexed_never_defaults_to_a_guessed_port_count():
    """A component without port_indexed never triggers the port_count
    requirement -- confirms the guard is scoped to components that actually
    need it, not a blanket manifest-level requirement."""
    m = {
        "protocol": "usb3_2",
        "vip": {"package_imports": []},
        "vip_components": [
            {"name": "clk_rst_agent", "class_type": "usb_clk_rst_agent",
             "instance_name": "clk_rst_agent0", "depends_on": []},
        ],
    }
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(m, sv_id(m["protocol"]))
        assert "usb_clk_rst_agent clk_rst_agent0;" in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# realistic mixed manifest: clk_rst_agent scalar, host_agent/mon_agent
# port_indexed (port_count=2) DEPENDING ON clk_rst_agent -- matching real
# USB dual-port evidence and the realistic depends_on direction.
# ---------------------------------------------------------------------------

MIXED_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "port_count": 2,
    "vip_components": [
        {"name": "host_agent", "class_type": "svt_usb_agent", "instance_name": "host_agent",
         "port_indexed": True, "depends_on": ["clk_rst_agent"]},
        {"name": "mon_agent", "class_type": "svt_usb_agent", "instance_name": "mon_agent",
         "port_indexed": True, "depends_on": ["clk_rst_agent"]},
        {"name": "clk_rst_agent", "class_type": "usb_clk_rst_agent",
         "instance_name": "clk_rst_agent0", "depends_on": []},
    ],
}


def test_mixed_manifest_declares_scalar_and_array_handles():
    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(MIXED_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")
        assert "  usb_clk_rst_agent clk_rst_agent0;" in env_sv
        assert "  svt_usb_agent host_agent[2];" in env_sv
        assert "  svt_usb_agent mon_agent[2];" in env_sv
    finally:
        shutil.rmtree(tmp)


def test_mixed_manifest_creates_scalar_before_port_indexed_loops():
    """The realistic common case: port-indexed components (host_agent,
    mon_agent) depend on a single non-port-indexed clk_rst_agent. The
    scalar clk_rst_agent create() must land before both port_indexed
    for-loops."""
    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(MIXED_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")

        clk_pos = env_sv.index(
            'clk_rst_agent0=usb_clk_rst_agent::type_id::create("clk_rst_agent0",this);')
        host_loop_pos = env_sv.index(
            'host_agent[p] = svt_usb_agent::type_id::create($sformatf("host_agent_%0d", p), this);')
        mon_loop_pos = env_sv.index(
            'mon_agent[p] = svt_usb_agent::type_id::create($sformatf("mon_agent_%0d", p), this);')

        assert clk_pos < host_loop_pos
        assert clk_pos < mon_loop_pos
        # depends_on ordering comments still cite the real dependency
        assert "// after clk_rst_agent (depends_on)" in env_sv
        assert "// no depends_on" in env_sv
    finally:
        shutil.rmtree(tmp)


def test_mixed_manifest_port_indexed_components_are_one_node_each():
    """Each port_indexed component contributes exactly one for-loop (its
    whole per-port array created together at one topologically-correct
    position) -- not one node per port."""
    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(MIXED_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")
        assert env_sv.count("for (int p = 0; p < 2; p++) begin") == 2
    finally:
        shutil.rmtree(tmp)


# ---------------------------------------------------------------------------
# zero regression: the sibling task's own non-port-indexed manifest must
# still produce byte-identical output (snapshot captured from the generator
# BEFORE this port_indexed extension was implemented).
# ---------------------------------------------------------------------------

EXPECTED_MULTI_COMPONENT_ENV_SV = '''class usb3_2_env extends uvm_env;
  `uvm_component_utils(usb3_2_env)
  usb3_2_config cfg;
  usb3_2_virtual_sequencer vseqr;
  usb3_2_scoreboard sb;
  usb3_2_coverage cov;
  usb_clk_rst_agent clk_rst_agent0;
  usb_host_agent host_agent0;
  usb_host_agent host_agent1;
  usb_mon_agent mon_agent0;
  usb_mon_agent mon_agent1;
  apb_env_c apb_env0;
  axi_env_c axi_env0;
  usb_sideband_agent sideband_agent0;
  reg_sequencer reg_seqr0;
  dma_env_c dma_env0;

  function new(string name="usb3_2_env", uvm_component parent=null); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if(!uvm_config_db#(usb3_2_config)::get(this,"","cfg",cfg))
      cfg=usb3_2_config::type_id::create("cfg");
    vseqr=usb3_2_virtual_sequencer::type_id::create("vseqr",this);
    sb=usb3_2_scoreboard::type_id::create("sb",this);
    cov=usb3_2_coverage::type_id::create("cov",this);
    // no depends_on
    clk_rst_agent0=usb_clk_rst_agent::type_id::create("clk_rst_agent0",this);
    // after clk_rst_agent (depends_on)
    host_agent0=usb_host_agent::type_id::create("host_agent0",this);
    // after clk_rst_agent (depends_on)
    host_agent1=usb_host_agent::type_id::create("host_agent1",this);
    // after clk_rst_agent (depends_on)
    mon_agent0=usb_mon_agent::type_id::create("mon_agent0",this);
    // after clk_rst_agent (depends_on)
    mon_agent1=usb_mon_agent::type_id::create("mon_agent1",this);
    // after clk_rst_agent (depends_on)
    apb_env0=apb_env_c::type_id::create("apb_env0",this);
    // after clk_rst_agent (depends_on)
    axi_env0=axi_env_c::type_id::create("axi_env0",this);
    // after clk_rst_agent (depends_on)
    sideband_agent0=usb_sideband_agent::type_id::create("sideband_agent0",this);
    // after apb_env (depends_on)
    reg_seqr0=reg_sequencer::type_id::create("reg_seqr0",this);
    // after clk_rst_agent, axi_env (depends_on)
    dma_env0=dma_env_c::type_id::create("dma_env0",this);
  endfunction
endclass
'''


def test_existing_non_port_indexed_manifest_still_byte_identical():
    """MULTI_COMPONENT_MANIFEST (imported from test_multi_component_env.py,
    the sibling task's own fixture) has no port_indexed field anywhere and
    no port_count key -- this port_indexed extension must be a complete
    no-op for it."""
    assert "port_indexed" not in str(MULTI_COMPONENT_MANIFEST)
    assert "port_count" not in MULTI_COMPONENT_MANIFEST

    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(MULTI_COMPONENT_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")
        assert env_sv == EXPECTED_MULTI_COMPONENT_ENV_SV
    finally:
        shutil.rmtree(tmp)
