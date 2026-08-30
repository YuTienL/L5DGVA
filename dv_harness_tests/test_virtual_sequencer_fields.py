"""Tests for the top-level "virtual_sequencer_fields" manifest key / real
virtual-sequencer field declarations (2026-08-29), following the
"connections" / _connect_phase extension in test_connect_phase.py.

Confirmed before implementation: generator.py's vseq() only ever emitted
generic numbered `uvm_sequencer_base seqr_%d;` handles, one per top-level
"interfaces" entry -- never a real, protocol-specific typed field.

Real evidence closed by this task, from D:/DV/Task/DV_Agent_Harness_L5/
USB_UVM_Handoff/uvm/tb/env/usb_virtual_sequencer.sv (re-read this session):
  line 17: class usb_virtual_sequencer extends uvm_sequencer;
  line 21: svt_usb_transfer_sequencer       usb_xfer_seqr[2];
  line 30: svt_usb_system_virtual_sequencer usb_sys_seqr[2];
  line 36: svt_apb_master_sequencer apb_seqr;
  line 37: svt_axi_master_sequencer axi_seqr;
  line 39: usb_reg_sequencer reg_seqr;
and examples/generated_usb_real_evidence_v7/manifest_inputs/
usb_env_manifest_v7.json's own top-level "connections" entries, which
reference exactly these field names: virt_seqr.apb_seqr,
virt_seqr.axi_seqr, virt_seqr.reg_seqr, virt_seqr.usb_xfer_seqr[{p}],
virt_seqr.usb_sys_seqr[{p}] (lines 210-240 of that manifest).

Schema (additive, backward compatible): an optional top-level manifest key
"virtual_sequencer_fields" -- a list of {"class_type", "field_name",
"port_indexed" (optional, default false), "evidence" (required,
non-empty)} dicts. When present and non-empty, vseq() emits one declaration
per entry, in manifest order, INSTEAD OF the old generic seqr_%d handles.
When absent/empty, vseq() is byte-identical to the pre-existing generic
numbered-handle path.

Groups:
  - real-shaped example: apb_seqr/axi_seqr/reg_seqr scalar fields + one
    port_indexed field (usb_xfer_seqr[2]), matching the real USB evidence
  - the missing-evidence error case (MissingVirtualSequencerFieldEvidenceError)
  - the absent-key backward-compatibility regression (byte-identical to the
    pre-existing generic behavior, reusing MULTI_COMPONENT_MANIFEST from
    test_multi_component_env.py)
  - internal self-consistency: every virt_seqr.<field> referenced in a
    companion "connections" list has a matching declared field in the
    emitted <protocol>_virtual_sequencer.sv
"""
from __future__ import annotations

import shutil
import tempfile

import pytest

from dv_harness.uvm_generator.generator import (
    MissingVirtualSequencerFieldEvidenceError,
    UVMEnvironmentGenerator,
    sv_id,
)

from dv_harness_tests.test_multi_component_env import MULTI_COMPONENT_MANIFEST


# ---------------------------------------------------------------------------
# real-shaped example: apb_seqr/axi_seqr/reg_seqr scalar + usb_xfer_seqr[2]
# port_indexed, matching USB_UVM_Handoff's usb_virtual_sequencer.sv
# ---------------------------------------------------------------------------

REAL_SHAPED_MANIFEST = {
    "protocol": "usb",
    "role": "device",
    "port_count": 2,
    "vip": {"package_imports": ["svt_usb_uvm_pkg"]},
    "virtual_sequencer_fields": [
        {"class_type": "svt_apb_master_sequencer", "field_name": "apb_seqr",
         "evidence": "USB_UVM_Handoff/uvm/tb/env/usb_virtual_sequencer.sv:36"},
        {"class_type": "svt_axi_master_sequencer", "field_name": "axi_seqr",
         "evidence": "USB_UVM_Handoff/uvm/tb/env/usb_virtual_sequencer.sv:37"},
        {"class_type": "usb_reg_sequencer", "field_name": "reg_seqr",
         "evidence": "USB_UVM_Handoff/uvm/tb/env/usb_virtual_sequencer.sv:39"},
        {"class_type": "svt_usb_transfer_sequencer", "field_name": "usb_xfer_seqr",
         "port_indexed": True,
         "evidence": "USB_UVM_Handoff/uvm/tb/env/usb_virtual_sequencer.sv:21"},
    ],
}


def test_real_shaped_fields_emit_correct_declarations():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        vseq_sv = gen.vseq(REAL_SHAPED_MANIFEST, sv_id(REAL_SHAPED_MANIFEST["protocol"]))
        assert "  svt_apb_master_sequencer apb_seqr;" in vseq_sv
        assert "  svt_axi_master_sequencer axi_seqr;" in vseq_sv
        assert "  usb_reg_sequencer reg_seqr;" in vseq_sv
        assert "  svt_usb_transfer_sequencer usb_xfer_seqr[2];" in vseq_sv
        # the generic numbered-handle path must not fire at all
        assert "seqr_0" not in vseq_sv
        assert "uvm_sequencer_base" not in vseq_sv
    finally:
        shutil.rmtree(gen.out)


def test_real_shaped_fields_emitted_in_manifest_order():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        vseq_sv = gen.vseq(REAL_SHAPED_MANIFEST, sv_id(REAL_SHAPED_MANIFEST["protocol"]))
        pos_apb = vseq_sv.index("apb_seqr;")
        pos_axi = vseq_sv.index("axi_seqr;")
        pos_reg = vseq_sv.index("reg_seqr;")
        pos_xfer = vseq_sv.index("usb_xfer_seqr[2];")
        assert pos_apb < pos_axi < pos_reg < pos_xfer
    finally:
        shutil.rmtree(gen.out)


def test_real_shaped_fields_reuse_top_level_port_count():
    """A different port_count must change the array bound accordingly --
    confirms the value is read from the manifest's own top-level
    "port_count", not hardcoded, same as build_phase/connect_phase."""
    m = dict(REAL_SHAPED_MANIFEST, port_count=4)
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        vseq_sv = gen.vseq(m, sv_id(m["protocol"]))
        assert "svt_usb_transfer_sequencer usb_xfer_seqr[4];" in vseq_sv
    finally:
        shutil.rmtree(gen.out)


def test_real_shaped_fields_class_declaration_shape_preserved():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        vseq_sv = gen.vseq(REAL_SHAPED_MANIFEST, sv_id(REAL_SHAPED_MANIFEST["protocol"]))
        assert "class usb_virtual_sequencer extends uvm_sequencer #(uvm_sequence_item);" in vseq_sv
        assert "`uvm_component_utils(usb_virtual_sequencer)" in vseq_sv
        assert 'function new(string name="usb_virtual_sequencer", uvm_component parent=null);' in vseq_sv
        assert vseq_sv.strip().endswith("endclass")
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# missing-evidence error case
# ---------------------------------------------------------------------------

def test_missing_evidence_raises_missing_virtual_sequencer_field_evidence_error():
    m = dict(REAL_SHAPED_MANIFEST)
    m["virtual_sequencer_fields"] = [
        {"class_type": "svt_apb_master_sequencer", "field_name": "apb_seqr"},
    ]
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MissingVirtualSequencerFieldEvidenceError) as exc_info:
            gen.vseq(m, sv_id(m["protocol"]))
        err = exc_info.value
        assert err.reason == "MISSING_VIRTUAL_SEQUENCER_FIELD_EVIDENCE"
        assert err.detail["field"]["field_name"] == "apb_seqr"
    finally:
        shutil.rmtree(gen.out)


def test_empty_evidence_string_also_raises():
    m = dict(REAL_SHAPED_MANIFEST)
    m["virtual_sequencer_fields"] = [
        {"class_type": "svt_apb_master_sequencer", "field_name": "apb_seqr", "evidence": ""},
    ]
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MissingVirtualSequencerFieldEvidenceError) as exc_info:
            gen.vseq(m, sv_id(m["protocol"]))
        assert exc_info.value.reason == "MISSING_VIRTUAL_SEQUENCER_FIELD_EVIDENCE"
    finally:
        shutil.rmtree(gen.out)


def test_whitespace_only_evidence_string_also_raises():
    m = dict(REAL_SHAPED_MANIFEST)
    m["virtual_sequencer_fields"] = [
        {"class_type": "svt_apb_master_sequencer", "field_name": "apb_seqr", "evidence": "   "},
    ]
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MissingVirtualSequencerFieldEvidenceError):
            gen.vseq(m, sv_id(m["protocol"]))
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# absent key -- byte-identical to the pre-existing generic numbered-handle
# path, regression-checked against test_multi_component_env.py's own
# MULTI_COMPONENT_MANIFEST fixture (which has no "interfaces" key either, so
# it exercises the seqr_0 default)
# ---------------------------------------------------------------------------

def test_absent_key_is_byte_identical_to_generic_numbered_handle_path():
    assert "virtual_sequencer_fields" not in MULTI_COMPONENT_MANIFEST
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(MULTI_COMPONENT_MANIFEST["protocol"])
        actual = gen.vseq(MULTI_COMPONENT_MANIFEST, p)

        # Byte-identical reconstruction of the pre-existing generic path,
        # computed independently of vseq()'s own implementation (the exact
        # pre-existing template/logic, inlined here rather than imported, so
        # this regression cannot silently pass merely because both call
        # sites share a bug).
        handles = '\n'.join(
            '  uvm_sequencer_base seqr_%d;' % i
            for i, _ in enumerate(MULTI_COMPONENT_MANIFEST.get('interfaces') or [{}])
        )
        expected = '''class %s_virtual_sequencer extends uvm_sequencer #(uvm_sequence_item);
  `uvm_component_utils(%s_virtual_sequencer)
%s
  function new(string name="%s_virtual_sequencer", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
''' % (p, p, handles, p)

        assert actual == expected
        assert "seqr_0" in actual
    finally:
        shutil.rmtree(gen.out)


def test_empty_list_also_byte_identical_to_generic_path():
    m = dict(MULTI_COMPONENT_MANIFEST, virtual_sequencer_fields=[])
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(m["protocol"])
        with_empty_key = gen.vseq(m, p)
        without_key = gen.vseq(MULTI_COMPONENT_MANIFEST, p)
        assert with_empty_key == without_key
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# internal self-consistency: every virt_seqr.<field> referenced in a
# companion "connections" list has a matching declared field in the emitted
# <protocol>_virtual_sequencer.sv
# ---------------------------------------------------------------------------

import re

SELF_CONSISTENT_MANIFEST = dict(REAL_SHAPED_MANIFEST, connections=[
    {"from": "virt_seqr.apb_seqr", "to": "apb_env.master.sequencer",
     "evidence": "USB_UVM_Handoff/uvm/tb/env/usb_top_env.sv:472"},
    {"from": "virt_seqr.axi_seqr", "to": "axi_env.master[0].sequencer",
     "evidence": "USB_UVM_Handoff/uvm/tb/env/usb_top_env.sv:473"},
    {"from": "virt_seqr.reg_seqr", "to": "reg_seqr",
     "evidence": "USB_UVM_Handoff/uvm/tb/env/usb_top_env.sv:475"},
    {"from": "virt_seqr.usb_xfer_seqr[{p}]", "to": "usb_host_agent[{p}].xfer_sequencer",
     "port_indexed": True,
     "evidence": "USB_UVM_Handoff/uvm/tb/env/usb_top_env.sv:461-465"},
])


def test_connect_phase_field_references_have_matching_declared_fields():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(SELF_CONSISTENT_MANIFEST["protocol"])
        vseq_sv = gen.vseq(SELF_CONSISTENT_MANIFEST, p)
        env_sv = gen.env(SELF_CONSISTENT_MANIFEST, p)

        # every field_name declared in the *_virtual_sequencer.sv
        declared = set(re.findall(
            r'^\s*\S+\s+(\w+)(?:\[\d+\])?;', vseq_sv, flags=re.MULTILINE))
        assert {"apb_seqr", "axi_seqr", "reg_seqr", "usb_xfer_seqr"} <= declared

        # every virt_seqr.<field> reference in the emitted connect_phase
        referenced = set(re.findall(r'virt_seqr\.(\w+)', env_sv))
        assert referenced == {"apb_seqr", "axi_seqr", "reg_seqr", "usb_xfer_seqr"}

        # self-consistency: nothing referenced that wasn't declared
        assert referenced <= declared
    finally:
        shutil.rmtree(gen.out)
