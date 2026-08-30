"""Tests for two additive vip_components schema extensions (2026-08-29),
following the multi-component / port_indexed extensions in
test_multi_component_env.py / test_per_port_env.py.

Real evidence closed by this task, from D:/DV/Task/DV_Agent_Harness_L5/
USB_UVM_Handoff/uvm/tb/env/usb_top_env.sv:

1. Virtual interface arrays. Line 75:
       virtual svt_usb_if usb_if[NUM_USB_PORTS];
   declared but never `::type_id::create()`-ed -- a virtual interface handle
   is bound externally. Its value arrives via uvm_config_db, confirmed at
   lines 372-377 (inside a `for (int p = 0; p < NUM_USB_PORTS; p++)` loop):
       if (!uvm_config_db#(virtual svt_usb_if)::get(null, get_full_name(),
                                                    port_name, usb_if[p])) begin
         `uvm_fatal("build_phase", ...)
       end
   New per-component field: "kind": "interface" (optional, default is
   today's implicit class-handle/agent kind).

2. `ifdef`-conditional components. `usb_dma_ssmem_scoreboard ssmem_sb;` is
   declared at line 128 inside an `` `ifdef USB_UVM_DMA_MON `` /
   `` `endif `` guard (lines 120-129), and `ssmem_sb` is created at line 366
   inside that SAME `` `ifdef USB_UVM_DMA_MON `` guard in build_phase
   (lines 356-367) -- both declaration and creation gated behind one
   compile-time macro. New per-component field: "ifdef_macro": "<MACRO>"
   (optional).

Groups:
  - kind="interface" scalar: declaration-only, no create() emitted
  - kind="interface" + port_indexed: array declaration + per-port
    config_db get in a for-loop
  - ifdef_macro wrapping both declaration and creation for a normal
    class-handle component
  - ifdef_macro combined with port_indexed
  - backward-compatibility regression: a component with neither field set
    behaves exactly as the sibling port_indexed/multi-component task built,
    byte-for-byte (reusing MULTI_COMPONENT_MANIFEST and
    SINGLE_PORT_INDEXED_MANIFEST/MIXED_MANIFEST fixtures).
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from dv_harness.uvm_generator.generator import UVMEnvironmentGenerator, sv_id
from dv_harness.uvm_generator.protocol_env_generator import ProtocolEnvGenerator

from dv_harness_tests.test_multi_component_env import MULTI_COMPONENT_MANIFEST
from dv_harness_tests.test_per_port_env import (
    EXPECTED_MULTI_COMPONENT_ENV_SV,
    MIXED_MANIFEST,
    SINGLE_PORT_INDEXED_MANIFEST,
)


# ---------------------------------------------------------------------------
# kind="interface", scalar -- declaration-only, no create()
# ---------------------------------------------------------------------------

SCALAR_INTERFACE_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "vip_components": [
        {"name": "usb_if", "class_type": "svt_usb_if", "instance_name": "usb_if",
         "kind": "interface", "depends_on": []},
    ],
}


def test_scalar_interface_declaration_is_virtual_and_has_no_create():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(SCALAR_INTERFACE_MANIFEST, sv_id(SCALAR_INTERFACE_MANIFEST["protocol"]))
        assert "  virtual svt_usb_if usb_if;" in env_sv
        # never created via the factory -- a virtual interface is bound externally
        assert "svt_usb_if::type_id::create" not in env_sv
        assert 'usb_if=svt_usb_if::type_id::create("usb_if",this);' not in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_scalar_interface_build_phase_uses_config_db_get_with_fatal():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(SCALAR_INTERFACE_MANIFEST, sv_id(SCALAR_INTERFACE_MANIFEST["protocol"]))
        assert (
            '    if (!uvm_config_db#(virtual svt_usb_if)::get(this, "", "usb_if", usb_if))'
            in env_sv
        )
        assert (
            '      `uvm_fatal(get_type_name(), "virtual interface usb_if not found in config_db")'
            in env_sv
        )
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# kind="interface" + port_indexed -- array declaration + per-port
# config_db get inside a for-loop
# ---------------------------------------------------------------------------

PORT_INDEXED_INTERFACE_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "port_count": 2,
    "vip_components": [
        {"name": "usb_if", "class_type": "svt_usb_if", "instance_name": "usb_if",
         "kind": "interface", "port_indexed": True, "depends_on": []},
    ],
}


def test_port_indexed_interface_emits_array_declaration():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(PORT_INDEXED_INTERFACE_MANIFEST, sv_id(PORT_INDEXED_INTERFACE_MANIFEST["protocol"]))
        assert "  virtual svt_usb_if usb_if[2];" in env_sv
        assert "svt_usb_if::type_id::create" not in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_port_indexed_interface_get_config_db_per_port_in_for_loop():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(PORT_INDEXED_INTERFACE_MANIFEST, sv_id(PORT_INDEXED_INTERFACE_MANIFEST["protocol"]))
        assert "    for (int p = 0; p < 2; p++) begin" in env_sv
        assert (
            '      if (!uvm_config_db#(virtual svt_usb_if)::get(this, "", $sformatf("usb_if_%0d", p), usb_if[p]))'
            in env_sv
        )
        assert (
            '        `uvm_fatal(get_type_name(), "virtual interface usb_if not found in config_db")'
            in env_sv
        )
        assert "    end" in env_sv
        # never the plain type_id::create for-loop idiom used for class handles
        assert 'usb_if[p] = svt_usb_if::type_id::create' not in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# ifdef_macro -- wraps BOTH declaration and creation for a normal
# class-handle (non-interface, non-port-indexed) component
# ---------------------------------------------------------------------------

IFDEF_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "vip_components": [
        {"name": "ssmem_sb", "class_type": "usb_dma_ssmem_scoreboard", "instance_name": "ssmem_sb",
         "ifdef_macro": "USB_UVM_DMA_MON", "depends_on": []},
    ],
}


def test_ifdef_macro_wraps_declaration():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(IFDEF_MANIFEST, sv_id(IFDEF_MANIFEST["protocol"]))
        assert "`ifdef USB_UVM_DMA_MON\n  usb_dma_ssmem_scoreboard ssmem_sb;\n`endif" in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_ifdef_macro_wraps_creation():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(IFDEF_MANIFEST, sv_id(IFDEF_MANIFEST["protocol"]))
        assert (
            '`ifdef USB_UVM_DMA_MON\n    // no depends_on\n'
            '    ssmem_sb=usb_dma_ssmem_scoreboard::type_id::create("ssmem_sb",this);\n`endif'
        ) in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_component_without_ifdef_macro_is_never_wrapped():
    """Sanity check for the guard itself: a sibling component with no
    ifdef_macro in the same manifest must not pick up any `ifdef guard."""
    m = dict(IFDEF_MANIFEST)
    m["vip_components"] = list(IFDEF_MANIFEST["vip_components"]) + [
        {"name": "clk_rst_agent", "class_type": "usb_clk_rst_agent",
         "instance_name": "clk_rst_agent0", "depends_on": []},
    ]
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(m, sv_id(m["protocol"]))
        assert "  usb_clk_rst_agent clk_rst_agent0;" in env_sv
        assert "`ifdef USB_UVM_DMA_MON\n  usb_clk_rst_agent" not in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# ifdef_macro combined with port_indexed
# ---------------------------------------------------------------------------

IFDEF_PORT_INDEXED_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "port_count": 2,
    "vip_components": [
        {"name": "dma_sb", "class_type": "usb_dma_scoreboard", "instance_name": "dma_sb",
         "ifdef_macro": "USB_UVM_DMA_MON", "port_indexed": True, "depends_on": []},
    ],
}


def test_ifdef_macro_with_port_indexed_wraps_array_declaration():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(IFDEF_PORT_INDEXED_MANIFEST, sv_id(IFDEF_PORT_INDEXED_MANIFEST["protocol"]))
        assert "`ifdef USB_UVM_DMA_MON\n  usb_dma_scoreboard dma_sb[2];\n`endif" in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_ifdef_macro_with_port_indexed_wraps_for_loop_creation():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(IFDEF_PORT_INDEXED_MANIFEST, sv_id(IFDEF_PORT_INDEXED_MANIFEST["protocol"]))
        expected = (
            '`ifdef USB_UVM_DMA_MON\n'
            '    // no depends_on\n'
            '    for (int p = 0; p < 2; p++) begin\n'
            '      dma_sb[p] = usb_dma_scoreboard::type_id::create($sformatf("dma_sb_%0d", p), this);\n'
            '    end\n'
            '`endif'
        )
        assert expected in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# backward compatibility: a component with neither field set behaves exactly
# as before, byte-for-byte
# ---------------------------------------------------------------------------

def test_multi_component_manifest_unaffected_byte_identical():
    """MULTI_COMPONENT_MANIFEST has no "kind" or "ifdef_macro" anywhere --
    these two extensions must be a complete no-op for it."""
    assert "kind" not in str(MULTI_COMPONENT_MANIFEST)
    assert "ifdef_macro" not in str(MULTI_COMPONENT_MANIFEST)

    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(MULTI_COMPONENT_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")
        assert env_sv == EXPECTED_MULTI_COMPONENT_ENV_SV
    finally:
        shutil.rmtree(tmp)


def test_single_port_indexed_manifest_unaffected():
    """SINGLE_PORT_INDEXED_MANIFEST (sibling port_indexed task's own
    fixture) has no "kind"/"ifdef_macro" either -- must still emit the
    plain type_id::create for-loop, unaffected by either extension."""
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(SINGLE_PORT_INDEXED_MANIFEST, sv_id(SINGLE_PORT_INDEXED_MANIFEST["protocol"]))
        assert "  svt_usb_agent host_agent[2];" in env_sv
        assert (
            '      host_agent[p] = svt_usb_agent::type_id::create($sformatf("host_agent_%0d", p), this);'
            in env_sv
        )
        assert "`ifdef" not in env_sv
        assert "virtual svt_usb_agent" not in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_mixed_manifest_unaffected():
    """MIXED_MANIFEST (sibling port_indexed task's own fixture) has no
    "kind"/"ifdef_macro" either -- confirms the extensions do not interfere
    with a realistic scalar + port_indexed mix."""
    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(MIXED_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")
        assert "  usb_clk_rst_agent clk_rst_agent0;" in env_sv
        assert "  svt_usb_agent host_agent[2];" in env_sv
        assert "  svt_usb_agent mon_agent[2];" in env_sv
        assert "`ifdef" not in env_sv
        assert "virtual " not in env_sv
    finally:
        shutil.rmtree(tmp)
