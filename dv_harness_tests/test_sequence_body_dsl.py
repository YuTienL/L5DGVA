"""Tests for the top-level "virtual_sequences" manifest key / real
sequence-body content emission (2026-08-29), following the "connections" /
"virtual_sequencer_fields" extension conventions in test_connect_phase.py /
test_virtual_sequencer_fields.py.

Confirmed before implementation: generator.py's base_vseq() consulted zero
manifest input -- no `randomize() with {}`, no `uvm_do_with`, no per-step
field values -- it always emitted the same fixed placeholder body
regardless of manifest content.

Real evidence closed by this task (VIP-evidence-only design pass, no
reference to any golden/reference environment), from real Synopsys USB VIP
files under D:/DV/Task/USB/VIP:
  - examples/tb_usb_svt_uvm_20_phy/env/usb_directed_transfers_sequence.sv,
    lines 157-325: the real `uvm_create` + `fix_anchors()` +
    `randomize() with {field == value; ...}` + status-check + `uvm_send`
    idiom.
  - examples/tb_usb_svt_uvm_basic_sys/env/usb_isoc_sequence.sv, lines
    198-206: the real `uvm_do_with(item, {field == value; ...})` idiom.
  - USB 2.0 spec section 9.4.6 (p.256): a device does not change its
    address until after a SET_ADDRESS control transfer's Status stage
    completes -- justifying the DSL's "$name"/"@name"/capture/post_actions
    inter-step data-dependency mechanism (a later step's field can depend
    on an earlier step's captured/propagated value).

Schema (additive, backward compatible): an optional top-level manifest key
"virtual_sequences" -- a list of {"seq_name", "evidence" (required,
non-empty), "sequencer_handle" (optional), "item_class" (optional),
"steps": [...]} dicts. See generator.py's base_vseq()/_emit_virtual_sequence
docstrings for the full step-level schema. Absent/empty key -> base_vseq()
returns exactly today's fixed placeholder, byte-identical.

Groups:
  - a representative example using the DSL spec's own shape (enumeration
    virtual sequence: a "randomize_with" step with pre_actions/capture/
    wait_conditions, a "randomize_with" step propagating a "$"-parameter
    into a post_action local, and a "uvm_do_with" step consuming that local
    via "@" reference) -- covers both emit_style variants, both reference
    token kinds, capture, wait_conditions, pre_actions, post_actions
  - the missing-evidence error case (MissingSequenceBodyEvidenceError)
  - the malformed-field_values error case (MalformedSequenceFieldValueError)
  - the absent-key / empty-list backward-compatibility regression
    (byte-identical to the pre-existing fixed placeholder)
"""
from __future__ import annotations

import shutil
import tempfile

import pytest

from dv_harness.uvm_generator.generator import (
    MalformedSequenceFieldValueError,
    MissingSequenceBodyEvidenceError,
    UVMEnvironmentGenerator,
    sv_id,
)

# ---------------------------------------------------------------------------
# representative example: real DSL spec shape (USB enumeration virtual
# sequence: GET_DESCRIPTOR(8B) -> SET_ADDRESS -> GET_DESCRIPTOR(config))
# ---------------------------------------------------------------------------

ENUMERATION_MANIFEST = {
    "protocol": "usb",
    "role": "DEVICE",
    "virtual_sequences": [
        {
            "seq_name": "usb_enumeration_vseq",
            "evidence": (
                "D:/DV/Task/USB/VIP/examples/tb_usb_svt_uvm_20_phy/env/"
                "usb_directed_transfers_sequence.sv:157-325"
            ),
            "sequencer_handle": "p_sequencer.xfer_sequencer",
            "item_class": "svt_usb_transfer",
            "steps": [
                {
                    "step_name": "get_device_descriptor_8b",
                    "emit_style": "randomize_with",
                    "pre_actions": ["get_device_descriptor_8b_xfer.fix_anchors(0,0,0);"],
                    "field_values": [
                        {"field": "xfer_type", "value": "svt_usb_types::CONTROL_TRANSFER"},
                        {"field": "setup_data_bmrequesttype_dir", "value": "svt_usb_types::DEVICE_TO_HOST"},
                        {"field": "setup_data_brequest", "value": "svt_usb_types::GET_DESCRIPTOR"},
                        {"field": "setup_data_w_value", "value": "16'h0100"},
                        {"field": "setup_data_w_length", "value": "8"},
                    ],
                    "capture": [
                        {"name": "ep0_max_packet_size", "from_expr": "get_device_descriptor_8b_xfer.payload.data[7]"},
                    ],
                    "wait_conditions": [
                        {"expr": "wait_for_host_device_state(svt_usb_types::ENABLED, svt_usb_types::RECEIVING_J);",
                         "evidence": "attach_control_xfers_detach_ls_fs_sequence.sv:161"},
                    ],
                },
                {
                    "step_name": "set_address",
                    "emit_style": "randomize_with",
                    "field_values": [
                        {"field": "setup_data_brequest", "value": "svt_usb_types::SET_ADDRESS"},
                        {"field": "setup_data_w_value", "value": "$new_device_address"},
                    ],
                    "post_actions": [
                        {"expr": "device_address_for_subsequent_steps = $new_device_address;",
                         "evidence": "USB 2.0 spec 9.4.6 (p.256): address changes only after Status stage completes"},
                    ],
                },
                {
                    "step_name": "get_config_descriptor",
                    "emit_style": "uvm_do_with",
                    "field_values": [
                        {"field": "device_address", "value": "@device_address_for_subsequent_steps"},
                        {"field": "setup_data_brequest", "value": "svt_usb_types::GET_DESCRIPTOR"},
                    ],
                },
            ],
        },
    ],
}


def test_emits_one_class_per_virtual_sequence_extending_base_vseq():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(ENUMERATION_MANIFEST["protocol"])
        out = gen.base_vseq(ENUMERATION_MANIFEST, p)
        assert "class usb_base_vseq extends uvm_sequence #(uvm_sequence_item);" in out
        assert "class usb_enumeration_vseq extends usb_base_vseq;" in out
        assert "`uvm_object_utils(usb_enumeration_vseq)" in out
    finally:
        shutil.rmtree(gen.out)


def test_randomize_with_step_emits_real_idiom_shape():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(ENUMERATION_MANIFEST["protocol"])
        out = gen.base_vseq(ENUMERATION_MANIFEST, p)
        assert "svt_usb_transfer get_device_descriptor_8b_xfer;" in out
        assert "`uvm_create_on(get_device_descriptor_8b_xfer, p_sequencer.xfer_sequencer)" in out
        assert "get_device_descriptor_8b_xfer.cfg = cfg;" in out
        assert "get_device_descriptor_8b_xfer.fix_anchors(0,0,0);" in out
        assert "status = get_device_descriptor_8b_xfer.randomize() with {" in out
        assert "xfer_type == svt_usb_types::CONTROL_TRANSFER;" in out
        assert "setup_data_w_value == 16'h0100;" in out
        assert 'if (!status) `uvm_fatal("body", "get_device_descriptor_8b Randomization failed!!!")' in out
        assert "`uvm_send_on(get_device_descriptor_8b_xfer, p_sequencer.xfer_sequencer)" in out
    finally:
        shutil.rmtree(gen.out)


def test_wait_conditions_emitted_with_evidence_comment_before_the_item_is_issued():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(ENUMERATION_MANIFEST["protocol"])
        out = gen.base_vseq(ENUMERATION_MANIFEST, p)
        assert "// evidence: attach_control_xfers_detach_ls_fs_sequence.sv:161" in out
        wait_pos = out.index("wait_for_host_device_state(")
        create_pos = out.index("`uvm_create_on(get_device_descriptor_8b_xfer")
        assert wait_pos < create_pos
    finally:
        shutil.rmtree(gen.out)


def test_capture_declares_local_and_assigns_after_randomize():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(ENUMERATION_MANIFEST["protocol"])
        out = gen.base_vseq(ENUMERATION_MANIFEST, p)
        assert "int ep0_max_packet_size;" in out
        assign = "ep0_max_packet_size = get_device_descriptor_8b_xfer.payload.data[7];"
        assert assign in out
        # capture assignment happens after the randomize+status-check, not before
        randomize_pos = out.index("status = get_device_descriptor_8b_xfer.randomize()")
        assert out.index(assign) > randomize_pos
    finally:
        shutil.rmtree(gen.out)


def test_dollar_parameter_reference_emitted_as_bare_identifier():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(ENUMERATION_MANIFEST["protocol"])
        out = gen.base_vseq(ENUMERATION_MANIFEST, p)
        # "$new_device_address" (field_values value) -> bare "new_device_address"
        assert "setup_data_w_value == new_device_address;" in out
        # the post_action's embedded "$new_device_address" is opaque verbatim
        # text (post_actions are never token-substituted), so it is untouched
        assert "device_address_for_subsequent_steps = $new_device_address;" in out
        assert "// evidence: USB 2.0 spec 9.4.6" in out
    finally:
        shutil.rmtree(gen.out)


def test_at_reference_declares_int_local_and_uvm_do_with_step_consumes_it():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(ENUMERATION_MANIFEST["protocol"])
        out = gen.base_vseq(ENUMERATION_MANIFEST, p)
        assert "int device_address_for_subsequent_steps;" in out
        assert "svt_usb_transfer get_config_descriptor_xfer;" in out
        assert "`uvm_do_on_with(get_config_descriptor_xfer, p_sequencer.xfer_sequencer, {" in out
        assert "device_address == device_address_for_subsequent_steps;" in out
        assert "setup_data_brequest == svt_usb_types::GET_DESCRIPTOR;" in out
    finally:
        shutil.rmtree(gen.out)


def test_status_local_declared_once_and_only_when_randomize_with_used():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(ENUMERATION_MANIFEST["protocol"])
        out = gen.base_vseq(ENUMERATION_MANIFEST, p)
        assert out.count("bit status;") == 1
    finally:
        shutil.rmtree(gen.out)


def test_steps_emitted_in_manifest_order_not_reordered():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(ENUMERATION_MANIFEST["protocol"])
        out = gen.base_vseq(ENUMERATION_MANIFEST, p)
        pos_get8 = out.index("get_device_descriptor_8b_xfer;")
        pos_addr = out.index("set_address_xfer;")
        pos_getcfg = out.index("get_config_descriptor_xfer;")
        assert pos_get8 < pos_addr < pos_getcfg
    finally:
        shutil.rmtree(gen.out)


def test_uvm_do_with_step_has_no_status_or_cfg_lines():
    """A "uvm_do_with" step is a single macro call -- it must not emit the
    "randomize_with" idiom's cfg-assignment/status-check machinery."""
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(ENUMERATION_MANIFEST["protocol"])
        out = gen.base_vseq(ENUMERATION_MANIFEST, p)
        do_with_pos = out.index("`uvm_do_on_with(get_config_descriptor_xfer")
        end_pos = out.index("})", do_with_pos)
        block = out[do_with_pos:end_pos]
        assert "get_config_descriptor_xfer.cfg" not in block
        assert "status = get_config_descriptor_xfer" not in block
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# missing-evidence error case
# ---------------------------------------------------------------------------

def test_missing_evidence_raises_missing_sequence_body_evidence_error():
    m = {
        "protocol": "usb",
        "virtual_sequences": [
            {"seq_name": "usb_enumeration_vseq", "steps": []},
        ],
    }
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MissingSequenceBodyEvidenceError) as exc_info:
            gen.base_vseq(m, sv_id(m["protocol"]))
        err = exc_info.value
        assert err.reason == "MISSING_SEQUENCE_BODY_EVIDENCE"
        assert err.detail["virtual_sequence"]["seq_name"] == "usb_enumeration_vseq"
    finally:
        shutil.rmtree(gen.out)


def test_empty_evidence_string_also_raises():
    m = {
        "protocol": "usb",
        "virtual_sequences": [
            {"seq_name": "usb_enumeration_vseq", "evidence": "", "steps": []},
        ],
    }
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MissingSequenceBodyEvidenceError) as exc_info:
            gen.base_vseq(m, sv_id(m["protocol"]))
        assert exc_info.value.reason == "MISSING_SEQUENCE_BODY_EVIDENCE"
    finally:
        shutil.rmtree(gen.out)


def test_whitespace_only_evidence_string_also_raises():
    m = {
        "protocol": "usb",
        "virtual_sequences": [
            {"seq_name": "usb_enumeration_vseq", "evidence": "   ", "steps": []},
        ],
    }
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MissingSequenceBodyEvidenceError):
            gen.base_vseq(m, sv_id(m["protocol"]))
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# malformed field_values error case
# ---------------------------------------------------------------------------

def test_field_value_missing_field_key_raises_malformed_error():
    m = {
        "protocol": "usb",
        "virtual_sequences": [
            {
                "seq_name": "usb_enumeration_vseq",
                "evidence": "usb_directed_transfers_sequence.sv:240-251",
                "steps": [
                    {"step_name": "get_descriptor",
                     "field_values": [{"value": "16'h0100"}]},
                ],
            },
        ],
    }
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MalformedSequenceFieldValueError) as exc_info:
            gen.base_vseq(m, sv_id(m["protocol"]))
        err = exc_info.value
        assert err.reason == "MALFORMED_SEQUENCE_FIELD_VALUE"
        assert err.detail["step_name"] == "get_descriptor"
    finally:
        shutil.rmtree(gen.out)


def test_field_value_missing_value_key_raises_malformed_error():
    m = {
        "protocol": "usb",
        "virtual_sequences": [
            {
                "seq_name": "usb_enumeration_vseq",
                "evidence": "usb_directed_transfers_sequence.sv:240-251",
                "steps": [
                    {"step_name": "get_descriptor",
                     "field_values": [{"field": "setup_data_w_value"}]},
                ],
            },
        ],
    }
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MalformedSequenceFieldValueError) as exc_info:
            gen.base_vseq(m, sv_id(m["protocol"]))
        assert exc_info.value.reason == "MALFORMED_SEQUENCE_FIELD_VALUE"
    finally:
        shutil.rmtree(gen.out)


def test_field_value_not_a_dict_raises_malformed_error():
    m = {
        "protocol": "usb",
        "virtual_sequences": [
            {
                "seq_name": "usb_enumeration_vseq",
                "evidence": "usb_directed_transfers_sequence.sv:240-251",
                "steps": [
                    {"step_name": "get_descriptor",
                     "field_values": ["setup_data_w_value == 16'h0100;"]},
                ],
            },
        ],
    }
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(MalformedSequenceFieldValueError):
            gen.base_vseq(m, sv_id(m["protocol"]))
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# absent key / empty list -- byte-identical to the pre-existing fixed
# placeholder body
# ---------------------------------------------------------------------------

PLACEHOLDER_MANIFEST = {"protocol": "usb", "role": "DEVICE"}


def test_absent_key_is_byte_identical_to_fixed_placeholder():
    assert "virtual_sequences" not in PLACEHOLDER_MANIFEST
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(PLACEHOLDER_MANIFEST["protocol"])
        actual = gen.base_vseq(PLACEHOLDER_MANIFEST, p)

        # Reconstructed independently of base_vseq()'s own implementation
        # (the exact pre-existing template, inlined rather than imported),
        # so this regression cannot silently pass merely because both call
        # sites share a bug.
        expected = '''class %s_base_vseq extends uvm_sequence #(uvm_sequence_item);
  `uvm_object_utils(%s_base_vseq)
  `uvm_declare_p_sequencer(%s_virtual_sequencer)
  function new(string name="%s_base_vseq"); super.new(name); endfunction
  virtual task body();
    `uvm_info(get_type_name(), "Base virtual sequence started", UVM_MEDIUM)
  endtask
endclass
''' % (p, p, p, p)
        assert actual == expected
    finally:
        shutil.rmtree(gen.out)


def test_empty_list_also_byte_identical_to_fixed_placeholder():
    m = dict(PLACEHOLDER_MANIFEST, virtual_sequences=[])
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        p = sv_id(m["protocol"])
        with_empty_key = gen.base_vseq(m, p)
        without_key = gen.base_vseq(PLACEHOLDER_MANIFEST, p)
        assert with_empty_key == without_key
    finally:
        shutil.rmtree(gen.out)
