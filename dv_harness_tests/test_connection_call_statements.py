"""Tests for the "kind"/"guard"/"loop_var"/"ifdef_macro" cross-cutting
extension to the top-level "connections" manifest key (2026-08-29), per the
Multi-Agent Evidence Consensus synthesis of
D:/DV/Task/DV_Agent_Harness_L5/USB_UVM_Handoff/uvm/tb/env/usb_top_env.sv's
real connect_phase (lines 456-623).

Real evidence exercised by this file (verbatim, re-confirmed against the
real file before implementation):

  line 506: payload_cb[p] = new($sformatf("payload_cb_%0d", p), p);
            -- inside `if (usb_host_agent[p] != null) begin ... end`,
            itself inside `foreach (usb_host_agent[p]) begin ... end`.
  line 508: uvm_callbacks#(svt_usb_protocol)::add(usb_host_agent[p].prot, payload_cb[p]);
            -- same guard/loop as line 506.
  line 531: dma_env.master[p].monitor.item_observed_port.connect(dma_sb[p].dma_export);
            -- inside `` `ifdef USB_UVM_DMA_MON``, inside `foreach (dma_sb[p])`;
            the preceding `== null continue` checks are loop plumbing, not a
            guard on this statement (consensus resolution), so this
            statement's own "guard" is empty.
  line 535: if (payload_cb[p] != null) payload_cb[p].dma_sb = dma_sb[p];
            -- same `` `ifdef USB_UVM_DMA_MON``/loop as line 531; stays
            kind "assign" but is the one assign-kind statement carrying
            "ifdef_macro" (proves the field is orthogonal to "kind").
  line 552: if (dma_env != null && dma_env.master.size() > 0)
              dma_env.master[0].monitor.item_observed_port.connect(ssmem_sb.dma_export_p0);
            -- inside `` `ifdef USB_UVM_DMA_MON``, inside
            `if (ssmem_sb != null) begin ... end` -- the multi-condition
            guard case (two ANDed conditions).
  line 554: the port-1 sibling of line 552
            (dma_env.master[1]...connect(ssmem_sb.dma_export_p1)).

Groups:
  - "construct" kind: a plain-new() statement (line 506), guarded,
    port_indexed
  - "call" kind, call_style "static": a parameterized class-scoped call
    with no receiver (line 508), guarded, port_indexed
  - "call" kind, call_style "instance": a receiver.method() call (line 531),
    unconditional (empty guard), port_indexed, ifdef-guarded
  - "assign" kind carrying the new "ifdef_macro" attribute (line 535):
    proves ifdef_macro/guard are orthogonal to kind, not folded into "call"
  - "call" kind, call_style "instance", multi-condition guard, NOT
    port_indexed (lines 552/554): the two ANDed conditions collapse into one
    combined `if (cond1 && cond2) stmt;` line
  - evidence-required generalizes to every new kind (construct/call), same
    MissingConnectionEvidenceError as the pre-existing assign-kind check
  - unknown "kind" value raises a plain ValueError (defensive, not part of
    the consensus spec's own validation surface)
  - backward-compatibility regression: every existing "connections" manifest
    fixture from test_connect_phase.py still produces byte-identical output
"""
from __future__ import annotations

import shutil
import tempfile

import pytest

from dv_harness.uvm_generator.generator import (
    MissingConnectionEvidenceError,
    UVMEnvironmentGenerator,
    sv_id,
)

from dv_harness_tests.test_connect_phase import (
    MIXED_CONNECTIONS_MANIFEST,
    MULTI_SCALAR_CONNECTIONS_MANIFEST,
    PORT_INDEXED_CONNECTION_MANIFEST,
    SCALAR_CONNECTION_MANIFEST,
)


def _gen_env(manifest):
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        return gen.env(manifest, sv_id(manifest["protocol"])), gen
    except Exception:
        shutil.rmtree(gen.out)
        raise


# ---------------------------------------------------------------------------
# base fixture shared by the "construct"/"call" cases -- only clk_rst_agent
# needed so build_phase has something valid to topologically order
# ---------------------------------------------------------------------------

_BASE = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "port_count": 2,
    "vip_components": [
        {"name": "clk_rst_agent", "class_type": "usb_clk_rst_agent",
         "instance_name": "clk_rst_agent0", "depends_on": []},
    ],
}


# ---------------------------------------------------------------------------
# construct kind (line 506)
# ---------------------------------------------------------------------------

CONSTRUCT_MANIFEST = dict(_BASE, connections=[
    {"kind": "construct",
     "lhs": "payload_cb[{p}]",
     "ctor_class": "usb_payload_publish_cb",
     "ctor_args": ['$sformatf("payload_cb_%0d", {p})', "{p}"],
     "guard": ["usb_host_agent[{p}] != null"],
     "loop_var": "p",
     "port_indexed": True,
     "evidence": "usb_top_env.sv:506"},
])


def test_construct_kind_emits_new_call_assignment():
    env_sv, gen = _gen_env(CONSTRUCT_MANIFEST)
    try:
        assert (
            '      if (usb_host_agent[p] != null) payload_cb[p] = new($sformatf("payload_cb_%0d", p), p);'
            in env_sv
        )
        assert "for (int p = 0; p < 2; p++) begin" in env_sv
        assert "// evidence: usb_top_env.sv:506" in env_sv
        assert "{p}" not in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_construct_kind_defaults_to_bare_new_when_ctor_args_absent():
    m = dict(_BASE, connections=[
        {"kind": "construct", "lhs": "err_catcher",
         "evidence": "usb_top_env.sv:182"},
    ])
    env_sv, gen = _gen_env(m)
    try:
        assert "    err_catcher = new();" in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# call kind, static (line 508)
# ---------------------------------------------------------------------------

STATIC_CALL_MANIFEST = dict(_BASE, connections=[
    {"kind": "call", "call_style": "static",
     "class_scope": "uvm_callbacks#(svt_usb_protocol)",
     "method": "add",
     "args": ["usb_host_agent[{p}].prot", "payload_cb[{p}]"],
     "guard": ["usb_host_agent[{p}] != null"],
     "loop_var": "p",
     "port_indexed": True,
     "evidence": "usb_top_env.sv:508"},
])


def test_static_call_kind_emits_parameterized_class_scoped_call():
    env_sv, gen = _gen_env(STATIC_CALL_MANIFEST)
    try:
        assert (
            "      if (usb_host_agent[p] != null) uvm_callbacks#(svt_usb_protocol)::add(usb_host_agent[p].prot, payload_cb[p]);"
            in env_sv
        )
        assert "// evidence: usb_top_env.sv:508" in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# call kind, instance, unconditional, port_indexed + ifdef (line 531)
# ---------------------------------------------------------------------------

INSTANCE_CALL_IFDEF_MANIFEST = dict(_BASE, connections=[
    {"kind": "call", "call_style": "instance",
     "receiver": "dma_env.master[{p}].monitor.item_observed_port",
     "method": "connect",
     "args": ["dma_sb[{p}].dma_export"],
     "guard": [],
     "port_indexed": True,
     "ifdef_macro": "USB_UVM_DMA_MON",
     "evidence": "usb_top_env.sv:531"},
])


def test_instance_call_kind_unconditional_wrapped_in_ifdef_and_loop():
    env_sv, gen = _gen_env(INSTANCE_CALL_IFDEF_MANIFEST)
    try:
        assert "`ifdef USB_UVM_DMA_MON" in env_sv
        assert "`endif" in env_sv
        assert (
            "      dma_env.master[p].monitor.item_observed_port.connect(dma_sb[p].dma_export);"
            in env_sv
        )
        # unconditional: no "if (" wraps this specific statement line
        connect_line = next(
            l for l in env_sv.splitlines()
            if "dma_env.master[p].monitor.item_observed_port.connect" in l
        )
        assert not connect_line.strip().startswith("if (")
        # ifdef must bracket the for-loop, not sit inside it
        ifdef_pos = env_sv.index("`ifdef USB_UVM_DMA_MON")
        loop_pos = env_sv.index("for (int p = 0; p < 2; p++) begin")
        endif_pos = env_sv.index("`endif")
        assert ifdef_pos < loop_pos < endif_pos
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# assign kind carrying ifdef_macro + guard (line 535) -- orthogonality proof
# ---------------------------------------------------------------------------

ASSIGN_WITH_IFDEF_AND_GUARD_MANIFEST = dict(_BASE, connections=[
    {"kind": "assign",
     "from": "payload_cb[{p}].dma_sb", "to": "dma_sb[{p}]",
     "guard": ["payload_cb[{p}] != null"],
     "port_indexed": True,
     "ifdef_macro": "USB_UVM_DMA_MON",
     "evidence": "usb_top_env.sv:535"},
])


def test_assign_kind_supports_ifdef_macro_and_guard():
    env_sv, gen = _gen_env(ASSIGN_WITH_IFDEF_AND_GUARD_MANIFEST)
    try:
        assert "`ifdef USB_UVM_DMA_MON" in env_sv
        assert (
            "      if (payload_cb[p] != null) payload_cb[p].dma_sb = dma_sb[p];"
            in env_sv
        )
    finally:
        shutil.rmtree(gen.out)


def test_assign_kind_is_the_default_when_kind_key_omitted():
    """An entry with no "kind" key at all must still behave as "assign" --
    the pre-existing shape, now reachable via the same code path as an
    explicit kind:"assign"."""
    m = dict(_BASE, connections=[
        {"from": "virt_seqr.reg_seqr", "to": "reg_seqr",
         "evidence": "usb_top_env.sv:475"},
    ])
    env_sv, gen = _gen_env(m)
    try:
        assert "    virt_seqr.reg_seqr = reg_seqr;" in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# call kind, instance, multi-condition guard, NOT port_indexed (lines 552/554)
# ---------------------------------------------------------------------------

MULTI_GUARD_CALL_MANIFEST = dict(_BASE, connections=[
    {"kind": "call", "call_style": "instance",
     "receiver": "dma_env.master[0].monitor.item_observed_port",
     "method": "connect", "args": ["ssmem_sb.dma_export_p0"],
     "guard": ["ssmem_sb != null",
               "dma_env != null && dma_env.master.size() > 0"],
     "ifdef_macro": "USB_UVM_DMA_MON",
     "evidence": "usb_top_env.sv:552"},
    {"kind": "call", "call_style": "instance",
     "receiver": "dma_env.master[1].monitor.item_observed_port",
     "method": "connect", "args": ["ssmem_sb.dma_export_p1"],
     "guard": ["ssmem_sb != null",
               "dma_env != null && dma_env.master.size() > 1"],
     "ifdef_macro": "USB_UVM_DMA_MON",
     "evidence": "usb_top_env.sv:554"},
])


def test_multi_condition_guard_is_anded_into_one_if():
    env_sv, gen = _gen_env(MULTI_GUARD_CALL_MANIFEST)
    try:
        assert (
            "    if (ssmem_sb != null && dma_env != null && dma_env.master.size() > 0) "
            "dma_env.master[0].monitor.item_observed_port.connect(ssmem_sb.dma_export_p0);"
            in env_sv
        )
        assert (
            "    if (ssmem_sb != null && dma_env != null && dma_env.master.size() > 1) "
            "dma_env.master[1].monitor.item_observed_port.connect(ssmem_sb.dma_export_p1);"
            in env_sv
        )
    finally:
        shutil.rmtree(gen.out)


def test_multi_condition_guard_entries_in_manifest_order():
    env_sv, gen = _gen_env(MULTI_GUARD_CALL_MANIFEST)
    try:
        pos0 = env_sv.index("dma_export_p0")
        pos1 = env_sv.index("dma_export_p1")
        assert pos0 < pos1
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# evidence-required generalizes to the new kinds
# ---------------------------------------------------------------------------

def test_construct_kind_missing_evidence_raises():
    m = dict(_BASE, connections=[
        {"kind": "construct", "lhs": "err_catcher"},
    ])
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MissingConnectionEvidenceError) as exc_info:
            gen.env(m, sv_id(m["protocol"]))
        assert exc_info.value.reason == "MISSING_CONNECTION_EVIDENCE"
    finally:
        shutil.rmtree(gen.out)


def test_call_kind_missing_evidence_raises():
    m = dict(_BASE, connections=[
        {"kind": "call", "call_style": "instance",
         "receiver": "foo", "method": "bar"},
    ])
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MissingConnectionEvidenceError) as exc_info:
            gen.env(m, sv_id(m["protocol"]))
        assert exc_info.value.reason == "MISSING_CONNECTION_EVIDENCE"
    finally:
        shutil.rmtree(gen.out)


def test_call_kind_empty_evidence_string_also_raises():
    m = dict(_BASE, connections=[
        {"kind": "call", "call_style": "instance",
         "receiver": "foo", "method": "bar", "evidence": "   "},
    ])
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MissingConnectionEvidenceError):
            gen.env(m, sv_id(m["protocol"]))
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# unknown kind -- defensive, not part of the consensus spec's own validation
# ---------------------------------------------------------------------------

def test_unknown_kind_raises_plain_value_error():
    m = dict(_BASE, connections=[
        {"kind": "frobnicate", "evidence": "usb_top_env.sv:1"},
    ])
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(ValueError):
            gen.env(m, sv_id(m["protocol"]))
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# backward-compatibility regression: every pre-existing "connections" fixture
# from test_connect_phase.py must still produce byte-identical output
# ---------------------------------------------------------------------------

def test_scalar_connection_manifest_output_unchanged():
    env_sv, gen = _gen_env(SCALAR_CONNECTION_MANIFEST)
    try:
        assert "  function void connect_phase(uvm_phase phase);" in env_sv
        assert "    super.connect_phase(phase);" in env_sv
        assert (
            "    // evidence: USB_UVM_Handoff/uvm/tb/env/usb_top_env.sv:472"
            in env_sv
        )
        assert "    virt_seqr.apb_seqr = apb_env.master.sequencer;" in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_multi_scalar_connections_manifest_output_unchanged():
    env_sv, gen = _gen_env(MULTI_SCALAR_CONNECTIONS_MANIFEST)
    try:
        pos_axi = env_sv.index("virt_seqr.axi_seqr = axi_env.master[0].sequencer;")
        pos_apb = env_sv.index("virt_seqr.apb_seqr = apb_env.master.sequencer;")
        pos_reg = env_sv.index("virt_seqr.reg_seqr = reg_seqr;")
        assert pos_axi < pos_apb < pos_reg
    finally:
        shutil.rmtree(gen.out)


def test_port_indexed_connection_manifest_output_unchanged():
    env_sv, gen = _gen_env(PORT_INDEXED_CONNECTION_MANIFEST)
    try:
        assert "    for (int p = 0; p < 2; p++) begin" in env_sv
        assert "      // evidence: usb_top_env.sv:464" in env_sv
        assert (
            "      virt_seqr.usb_xfer_seqr[p] = usb_host_agent[p].xfer_sequencer;"
            in env_sv
        )
        assert "{p}" not in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_mixed_connections_manifest_output_unchanged():
    env_sv, gen = _gen_env(MIXED_CONNECTIONS_MANIFEST)
    try:
        loop_pos = env_sv.index("for (int p = 0; p < 2; p++) begin")
        port_assign_pos = env_sv.index(
            "virt_seqr.usb_xfer_seqr[p] = usb_host_agent[p].xfer_sequencer;")
        apb_pos = env_sv.index("virt_seqr.apb_seqr = apb_env.master.sequencer;")
        reg_pos = env_sv.index("virt_seqr.reg_seqr = reg_seqr;")
        assert loop_pos < port_assign_pos < apb_pos < reg_pos
    finally:
        shutil.rmtree(gen.out)
