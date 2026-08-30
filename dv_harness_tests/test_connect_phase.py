"""Tests for the top-level "connections" manifest key / real connect_phase
emission (2026-08-29), following the multi-component / port_indexed /
interface / ifdef_macro / plain_object / config_db_key_pattern extensions in
test_multi_component_env.py / test_per_port_env.py /
test_interface_and_conditional_components.py /
test_plain_object_and_key_pattern.py.

Real evidence closed by this task, from D:/DV/Task/DV_Agent_Harness_L5/
USB_UVM_Handoff/uvm/tb/env/usb_top_env.sv's real connect_phase (re-read this
session, lines ~456-489):

  line 456: function void usb_top_env::connect_phase(uvm_phase phase);
  line 458:   super.connect_phase(phase);
  line 472:   if (apb_env != null) virt_seqr.apb_seqr = apb_env.master.sequencer;
  line 475:   virt_seqr.reg_seqr = reg_seqr;
and the port-indexed shape, lines 461-465:
  for (int p = 0; p < NUM_USB_PORTS; p++) begin
    if (!cfg.enable_port[p]) continue;
    if (usb_host_agent[p] == null) continue;
    virt_seqr.usb_xfer_seqr[p] = usb_host_agent[p].xfer_sequencer;
  end

Confirmed before implementation: the generator's _env_multi_component method
never emitted a connect_phase function at all (no "connect_phase" string
anywhere in that method's output).

Schema (additive, backward compatible): an optional top-level manifest key
"connections" -- a list of {"from", "to", "port_indexed" (optional, default
false), "evidence" (required, non-empty)} dicts. Connections are emitted in
manifest order exactly (a flat wire-up list, not topologically sorted).

Groups:
  - a scalar connection: assignment + evidence comment present
  - multiple scalar connections: emitted in manifest order, not
    alphabetical/topological
  - a port_indexed connection: for-loop wrapping + {p} placeholder
    substitution
  - the missing-evidence error case (MissingConnectionEvidenceError)
  - the absent-"connections"-key case: no connect_phase function at all,
    regression-checked against MULTI_COMPONENT_MANIFEST (imported from
    test_multi_component_env.py) to prove zero behavior change
  - a mixed manifest with both scalar and port_indexed connections in a
    specific order, asserting emitted order matches input order exactly
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness.uvm_generator.generator import (
    MissingConnectionEvidenceError,
    UVMEnvironmentGenerator,
    sv_id,
)
from dv_harness.uvm_generator.protocol_env_generator import ProtocolEnvGenerator

from dv_harness_tests.test_multi_component_env import MULTI_COMPONENT_MANIFEST
from dv_harness_tests.test_per_port_env import EXPECTED_MULTI_COMPONENT_ENV_SV


# ---------------------------------------------------------------------------
# scalar connection
# ---------------------------------------------------------------------------

SCALAR_CONNECTION_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "vip_components": [
        {"name": "clk_rst_agent", "class_type": "usb_clk_rst_agent",
         "instance_name": "clk_rst_agent0", "depends_on": []},
    ],
    "connections": [
        {"from": "virt_seqr.apb_seqr", "to": "apb_env.master.sequencer",
         "evidence": "USB_UVM_Handoff/uvm/tb/env/usb_top_env.sv:472"},
    ],
}


def test_scalar_connection_emits_assignment_and_evidence_comment():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(SCALAR_CONNECTION_MANIFEST, sv_id(SCALAR_CONNECTION_MANIFEST["protocol"]))
        assert "  function void connect_phase(uvm_phase phase);" in env_sv
        assert "    super.connect_phase(phase);" in env_sv
        assert (
            "    // evidence: USB_UVM_Handoff/uvm/tb/env/usb_top_env.sv:472"
            in env_sv
        )
        assert "    virt_seqr.apb_seqr = apb_env.master.sequencer;" in env_sv
        # evidence comment sits directly above its assignment line
        idx_evidence = env_sv.index(
            "// evidence: USB_UVM_Handoff/uvm/tb/env/usb_top_env.sv:472")
        idx_assign = env_sv.index("virt_seqr.apb_seqr = apb_env.master.sequencer;")
        evidence_line_end = env_sv.index("\n", idx_evidence)
        assert env_sv[evidence_line_end + 1:].startswith(
            "    virt_seqr.apb_seqr = apb_env.master.sequencer;")
        assert idx_evidence < idx_assign
    finally:
        shutil.rmtree(gen.out)


def test_scalar_connection_calls_super_connect_phase_first():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(SCALAR_CONNECTION_MANIFEST, sv_id(SCALAR_CONNECTION_MANIFEST["protocol"]))
        connect_start = env_sv.index("function void connect_phase(uvm_phase phase);")
        super_call = env_sv.index("super.connect_phase(phase);")
        assign = env_sv.index("virt_seqr.apb_seqr = apb_env.master.sequencer;")
        assert connect_start < super_call < assign
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# multiple scalar connections -- manifest order, not alphabetical/topological
# ---------------------------------------------------------------------------

MULTI_SCALAR_CONNECTIONS_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "vip_components": [
        {"name": "clk_rst_agent", "class_type": "usb_clk_rst_agent",
         "instance_name": "clk_rst_agent0", "depends_on": []},
    ],
    "connections": [
        {"from": "virt_seqr.axi_seqr", "to": "axi_env.master[0].sequencer",
         "evidence": "usb_top_env.sv:473"},
        {"from": "virt_seqr.apb_seqr", "to": "apb_env.master.sequencer",
         "evidence": "usb_top_env.sv:472"},
        {"from": "virt_seqr.reg_seqr", "to": "reg_seqr",
         "evidence": "usb_top_env.sv:475"},
    ],
}


def test_multiple_scalar_connections_emitted_in_manifest_order():
    """Manifest order is axi_seqr, apb_seqr, reg_seqr -- alphabetically or
    topologically that would differ (apb < axi < reg), so this pins that
    connections are a flat list in input order, never reordered."""
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(MULTI_SCALAR_CONNECTIONS_MANIFEST,
                          sv_id(MULTI_SCALAR_CONNECTIONS_MANIFEST["protocol"]))
        pos_axi = env_sv.index("virt_seqr.axi_seqr = axi_env.master[0].sequencer;")
        pos_apb = env_sv.index("virt_seqr.apb_seqr = apb_env.master.sequencer;")
        pos_reg = env_sv.index("virt_seqr.reg_seqr = reg_seqr;")
        assert pos_axi < pos_apb < pos_reg
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# port_indexed connection -- for-loop wrapping + {p} placeholder substitution
# ---------------------------------------------------------------------------

PORT_INDEXED_CONNECTION_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "port_count": 2,
    "vip_components": [
        {"name": "host_agent", "class_type": "svt_usb_agent", "instance_name": "usb_host_agent",
         "port_indexed": True, "depends_on": []},
    ],
    "connections": [
        {"from": "virt_seqr.usb_xfer_seqr[{p}]", "to": "usb_host_agent[{p}].xfer_sequencer",
         "port_indexed": True, "evidence": "usb_top_env.sv:464"},
    ],
}


def test_port_indexed_connection_wraps_for_loop_and_substitutes_placeholder():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(PORT_INDEXED_CONNECTION_MANIFEST,
                          sv_id(PORT_INDEXED_CONNECTION_MANIFEST["protocol"]))
        assert "    for (int p = 0; p < 2; p++) begin" in env_sv
        assert "      // evidence: usb_top_env.sv:464" in env_sv
        assert (
            "      virt_seqr.usb_xfer_seqr[p] = usb_host_agent[p].xfer_sequencer;"
            in env_sv
        )
        # the {p} placeholder itself must never survive into the output
        assert "{p}" not in env_sv
        # the for-loop must be properly closed
        connect_start = env_sv.index("function void connect_phase(uvm_phase phase);")
        connect_body = env_sv[connect_start:]
        assert "    end" in connect_body
    finally:
        shutil.rmtree(gen.out)


def test_port_indexed_connection_reuses_top_level_port_count():
    """A different port_count must change the loop bound accordingly --
    confirms the value is read from the manifest's own top-level
    "port_count", not hardcoded."""
    m = dict(PORT_INDEXED_CONNECTION_MANIFEST, port_count=4)
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(m, sv_id(m["protocol"]))
        assert "for (int p = 0; p < 4; p++) begin" in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# missing-evidence error case
# ---------------------------------------------------------------------------

def test_missing_evidence_raises_missing_connection_evidence_error():
    m = dict(SCALAR_CONNECTION_MANIFEST)
    m["connections"] = [
        {"from": "virt_seqr.apb_seqr", "to": "apb_env.master.sequencer"},
    ]
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MissingConnectionEvidenceError) as exc_info:
            gen.env(m, sv_id(m["protocol"]))
        err = exc_info.value
        assert err.reason == "MISSING_CONNECTION_EVIDENCE"
        assert err.detail["connection"]["from"] == "virt_seqr.apb_seqr"
    finally:
        shutil.rmtree(gen.out)


def test_empty_evidence_string_also_raises():
    m = dict(SCALAR_CONNECTION_MANIFEST)
    m["connections"] = [
        {"from": "virt_seqr.apb_seqr", "to": "apb_env.master.sequencer", "evidence": ""},
    ]
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MissingConnectionEvidenceError) as exc_info:
            gen.env(m, sv_id(m["protocol"]))
        assert exc_info.value.reason == "MISSING_CONNECTION_EVIDENCE"
    finally:
        shutil.rmtree(gen.out)


def test_whitespace_only_evidence_string_also_raises():
    m = dict(SCALAR_CONNECTION_MANIFEST)
    m["connections"] = [
        {"from": "virt_seqr.apb_seqr", "to": "apb_env.master.sequencer", "evidence": "   "},
    ]
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MissingConnectionEvidenceError):
            gen.env(m, sv_id(m["protocol"]))
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# absent "connections" key -- no connect_phase function at all, regression-
# checked against the sibling task's own MULTI_COMPONENT_MANIFEST fixture
# ---------------------------------------------------------------------------

def test_absent_connections_key_emits_no_connect_phase_function():
    assert "connections" not in MULTI_COMPONENT_MANIFEST
    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(MULTI_COMPONENT_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")
        assert "connect_phase" not in env_sv
        # zero behavior change: byte-identical to the pre-existing pinned
        # output from test_per_port_env.py's own regression fixture.
        assert env_sv == EXPECTED_MULTI_COMPONENT_ENV_SV
    finally:
        shutil.rmtree(tmp)


def test_empty_connections_list_also_emits_no_connect_phase_function():
    m = dict(MULTI_COMPONENT_MANIFEST, connections=[])
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(m, sv_id(m["protocol"]))
        assert "connect_phase" not in env_sv
        assert env_sv == EXPECTED_MULTI_COMPONENT_ENV_SV
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# mixed manifest: scalar + port_indexed connections in a specific order
# ---------------------------------------------------------------------------

MIXED_CONNECTIONS_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "port_count": 2,
    "vip_components": [
        {"name": "host_agent", "class_type": "svt_usb_agent", "instance_name": "usb_host_agent",
         "port_indexed": True, "depends_on": []},
        {"name": "apb_env", "class_type": "apb_env_c", "instance_name": "apb_env",
         "depends_on": []},
    ],
    "connections": [
        {"from": "virt_seqr.usb_xfer_seqr[{p}]", "to": "usb_host_agent[{p}].xfer_sequencer",
         "port_indexed": True, "evidence": "usb_top_env.sv:464"},
        {"from": "virt_seqr.apb_seqr", "to": "apb_env.master.sequencer",
         "evidence": "usb_top_env.sv:472"},
        {"from": "virt_seqr.reg_seqr", "to": "reg_seqr",
         "evidence": "usb_top_env.sv:475"},
    ],
}


def test_mixed_manifest_connections_emitted_in_exact_input_order():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(MIXED_CONNECTIONS_MANIFEST, sv_id(MIXED_CONNECTIONS_MANIFEST["protocol"]))

        loop_pos = env_sv.index("for (int p = 0; p < 2; p++) begin")
        port_assign_pos = env_sv.index(
            "virt_seqr.usb_xfer_seqr[p] = usb_host_agent[p].xfer_sequencer;")
        apb_pos = env_sv.index("virt_seqr.apb_seqr = apb_env.master.sequencer;")
        reg_pos = env_sv.index("virt_seqr.reg_seqr = reg_seqr;")

        # exact input order: port_indexed loop first, then apb, then reg
        assert loop_pos < port_assign_pos < apb_pos < reg_pos
    finally:
        shutil.rmtree(gen.out)


def test_mixed_manifest_all_evidence_comments_present():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(MIXED_CONNECTIONS_MANIFEST, sv_id(MIXED_CONNECTIONS_MANIFEST["protocol"]))
        assert "// evidence: usb_top_env.sv:464" in env_sv
        assert "// evidence: usb_top_env.sv:472" in env_sv
        assert "// evidence: usb_top_env.sv:475" in env_sv
    finally:
        shutil.rmtree(gen.out)
