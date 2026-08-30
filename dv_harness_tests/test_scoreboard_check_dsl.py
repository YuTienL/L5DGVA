"""Tests for the SCOREBOARD_CHECKS DSL extension to the top-level
"scoreboard_rules" manifest field (2026-08-29).

Real evidence closed by this task: a DUT-RTL+VIP-only design pass on the
real Synopsys DesignWare USB 3.1 device controller (udc_DWC_usb31,
D:/DV/Task/USB/DUT/RTLCAT/USB_FPGA) vs. the real Synopsys USB SVT VIP
(D:/DV/Task/USB/VIP), cross-checked against D:/DV/Task/USB/DOC's
DWC_usb31_programming.txt, produced a generic DSL for compiling a real
`if (lhs != rhs) `uvm_error(...)`-shaped scoreboard check instead of
today's `// RULE: <json.dumps(x)>` comment-dump.

Confirmed before implementation (this task's own read-first pass):
scoreboard() did nothing but comment-dump every "scoreboard_rules" entry
into an otherwise-empty uvm_scoreboard class body -- no real comparison, no
`uvm_error`, no register decode.

Discriminator (additive, backward compatible): a "scoreboard_rules" entry
that is a dict AND carries a "check_name" key opts into the new structured
shape; every existing manifest's entries (plain {"TODO": "..."} dicts, per
every examples/generated_usb_real_evidence_v*/manifest_inputs/*.json this
session) carry no such key and so are completely unaffected -- verified
byte-identical against the original comment-dump template.

Groups:
  - the DSL spec's own worked example: EPTYPE (register_decode + identity
    enum_translation, still compiled as a real case statement, never
    skipped) and MPS (register_decode only, no enum_translation) checks,
    both compiled from one manifest, evidence-summary-comparison order
  - backward-compat: an old-style freeform scoreboard_rules entry (no
    "check_name") comment-dumps byte-identical to the pre-existing template
  - a mixed manifest (freeform + structured entries) keeps the freeform
    entry's comment-dump position/content untouched and appends the
    compiled check after it
  - error cases the DSL spec's own field list defines: missing check_name,
    malformed lhs_source/rhs_source, invalid compare_op, missing
    on_mismatch/severity/message_template, invalid register_decode,
    unsupported enum_translation kind, missing enum_translation map/note,
    mask_eq with no mask
"""
from __future__ import annotations

import tempfile

import pytest

from dv_harness.uvm_generator.generator import (
    MalformedScoreboardCheckError,
    UVMEnvironmentGenerator,
    sv_id,
)


def _gen():
    return UVMEnvironmentGenerator(tempfile.mkdtemp())


# ---------------------------------------------------------------------------
# DSL spec's own worked example: EPTYPE (enum_translation) + MPS (plain)
# ---------------------------------------------------------------------------

EPTYPE_CHECK = {
    "check_name": "ep0_eptype_dut_vip_match",
    "lhs_source": {
        "component": "dut_reg",
        "field": "eptype",
        "register_decode": {"bit_offset": 1, "bit_width": 2},
    },
    "rhs_source": {
        "component": "vip_ep_cfg",
        "field": "ep_type",
        "sv_type": "svt_usb_types::ep_type_enum",
        "enum_translation": {
            "kind": "value_map",
            "map": {"0": 0, "1": 1, "2": 2, "3": 3},
            "note": "Identity, but verified against real macro-resolved "
                    "values (see evidence), NOT assumed from enum "
                    "declaration order.",
            "confidence": "HIGH",
        },
    },
    "compare_op": "eq",
    "on_mismatch": {
        "severity": "UVM_ERROR",
        "message_template": "EPTYPE mismatch on %s: DUT DEPCFG0.EPTYPE=%0d VIP ep_type=%0d",
    },
}

MPS_CHECK = {
    "check_name": "ep0_mps_dut_vip_match",
    "lhs_source": {
        "component": "dut_reg",
        "field": "mps",
        "register_decode": {"bit_offset": 3, "bit_width": 11},
    },
    "rhs_source": {
        "component": "vip_ep_cfg",
        "field": "max_packet_size",
        "enum_translation": None,
    },
    "compare_op": "eq",
    "on_mismatch": {
        "severity": "UVM_ERROR",
        "message_template": "MaxPacketSize mismatch on %s: DUT DEPCFG0.MPS=%0d VIP max_packet_size=%0d",
    },
}

SCOREBOARD_CHECKS_MANIFEST = {
    "protocol": "usb3_2",
    "scoreboard_rules": [EPTYPE_CHECK, MPS_CHECK],
}


def test_eptype_check_compiles_register_decode_and_case_table():
    gen = _gen()
    sb = gen.scoreboard(SCOREBOARD_CHECKS_MANIFEST, sv_id(SCOREBOARD_CHECKS_MANIFEST["protocol"]))

    assert "function void check_ep0_eptype_dut_vip_match(" in sb
    assert "bit [31:0] dut_reg_eptype" in sb
    assert "svt_usb_types::ep_type_enum vip_ep_cfg_ep_type" in sb
    # register_decode slice: bit_offset=1, bit_width=2 -> [2:1]
    assert "bit [1:0] lhs = dut_reg_eptype[2:1];" in sb
    # enum_translation is ALWAYS compiled into a real case table, even
    # though the map here is a numeric identity -- never skipped/optimized
    # away, per the DSL spec's own "no translation needed is a conclusion
    # that has to be verified, never assumed" finding.
    assert "case (rhs_raw)" in sb
    assert "0: rhs = 0;" in sb
    assert "1: rhs = 1;" in sb
    assert "2: rhs = 2;" in sb
    assert "3: rhs = 3;" in sb
    assert "default: begin" in sb
    assert "endcase" in sb
    assert "if (lhs !== rhs)" in sb
    assert '`uvm_error("SB_EP0_EPTYPE_DUT_VIP_MATCH",' in sb
    assert (
        '$sformatf("EPTYPE mismatch on %s: DUT DEPCFG0.EPTYPE=%0d VIP ep_type=%0d", '
        '"ep0_eptype_dut_vip_match", lhs, rhs)' in sb
    )


def test_mps_check_compiles_plain_field_no_enum_translation():
    gen = _gen()
    sb = gen.scoreboard(SCOREBOARD_CHECKS_MANIFEST, sv_id(SCOREBOARD_CHECKS_MANIFEST["protocol"]))

    assert "function void check_ep0_mps_dut_vip_match(" in sb
    assert "bit [31:0] dut_reg_mps" in sb
    assert "int vip_ep_cfg_max_packet_size" in sb
    # register_decode slice: bit_offset=3, bit_width=11 -> [13:3]
    assert "bit [10:0] lhs = dut_reg_mps[13:3];" in sb
    # plain field, no enum_translation: direct int cast, no case table
    assert "int rhs = int'(vip_ep_cfg_max_packet_size);" in sb
    assert "if (lhs !== rhs)" in sb
    assert '`uvm_error("SB_EP0_MPS_DUT_VIP_MATCH",' in sb


def test_both_checks_appended_after_placeholder_body_before_endclass():
    gen = _gen()
    sb = gen.scoreboard(SCOREBOARD_CHECKS_MANIFEST, sv_id(SCOREBOARD_CHECKS_MANIFEST["protocol"]))
    pos_new = sb.index("function new(")
    pos_eptype = sb.index("function void check_ep0_eptype_dut_vip_match(")
    pos_mps = sb.index("function void check_ep0_mps_dut_vip_match(")
    pos_endclass = sb.rindex("endclass")
    assert pos_new < pos_eptype < pos_mps < pos_endclass
    assert sb.strip().endswith("endclass")


# ---------------------------------------------------------------------------
# backward-compat: old-style freeform entry (no "check_name")
# ---------------------------------------------------------------------------

LEGACY_MANIFEST = {
    "protocol": "usb3_2",
    "scoreboard_rules": [
        {"TODO": "not enough real evidence gathered this pass to state a specific checking rule"},
    ],
}

EXPECTED_LEGACY_SCOREBOARD_SV = '''class usb3_2_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(usb3_2_scoreboard)
  // RULE: {"TODO": "not enough real evidence gathered this pass to state a specific checking rule"}
  function new(string name="usb3_2_scoreboard", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
'''


def test_legacy_freeform_rule_comment_dumps_byte_identical():
    gen = _gen()
    sb = gen.scoreboard(LEGACY_MANIFEST, sv_id(LEGACY_MANIFEST["protocol"]))
    assert sb == EXPECTED_LEGACY_SCOREBOARD_SV
    assert "function void check_" not in sb


EXPECTED_EMPTY_SCOREBOARD_SV = '''class usb3_2_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(usb3_2_scoreboard)
  // Protocol-specific checking rules come from the semantic model.
  function new(string name="usb3_2_scoreboard", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
'''


def test_absent_scoreboard_rules_key_byte_identical_to_placeholder():
    gen = _gen()
    m = {"protocol": "usb3_2"}
    sb = gen.scoreboard(m, sv_id(m["protocol"]))
    assert sb == EXPECTED_EMPTY_SCOREBOARD_SV


def test_empty_scoreboard_rules_list_byte_identical_to_placeholder():
    gen = _gen()
    m = {"protocol": "usb3_2", "scoreboard_rules": []}
    sb = gen.scoreboard(m, sv_id(m["protocol"]))
    assert sb == EXPECTED_EMPTY_SCOREBOARD_SV


# ---------------------------------------------------------------------------
# mixed manifest: freeform entry untouched, structured check appended after
# ---------------------------------------------------------------------------

MIXED_MANIFEST = {
    "protocol": "usb3_2",
    "scoreboard_rules": [
        {"TODO": "legacy note kept as-is"},
        MPS_CHECK,
    ],
}


def test_mixed_manifest_keeps_legacy_comment_and_appends_compiled_check():
    gen = _gen()
    sb = gen.scoreboard(MIXED_MANIFEST, sv_id(MIXED_MANIFEST["protocol"]))
    assert '  // RULE: {"TODO": "legacy note kept as-is"}' in sb
    assert "function void check_ep0_mps_dut_vip_match(" in sb
    pos_comment = sb.index("// RULE:")
    pos_check = sb.index("function void check_ep0_mps_dut_vip_match(")
    assert pos_comment < pos_check


# ---------------------------------------------------------------------------
# error cases the DSL spec's own field list defines
# ---------------------------------------------------------------------------

def _check(**overrides):
    base = {
        "check_name": "some_check",
        "lhs_source": {"component": "dut_reg", "field": "f",
                        "register_decode": {"bit_offset": 0, "bit_width": 1}},
        "rhs_source": {"component": "vip_cfg", "field": "f"},
        "compare_op": "eq",
        "on_mismatch": {"severity": "UVM_ERROR", "message_template": "%s %0d %0d"},
    }
    base.update(overrides)
    return base


def test_missing_check_name_raises():
    gen = _gen()
    m = {"protocol": "usb3_2", "scoreboard_rules": [{"check_name": ""}]}
    with pytest.raises(MalformedScoreboardCheckError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "MISSING_CHECK_NAME"


def test_malformed_lhs_source_missing_field_raises():
    gen = _gen()
    check = _check(lhs_source={"component": "dut_reg"})
    m = {"protocol": "usb3_2", "scoreboard_rules": [check]}
    with pytest.raises(MalformedScoreboardCheckError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    err = exc_info.value
    assert err.reason == "MALFORMED_SCORE_SOURCE"
    assert err.detail["side"] == "lhs_source"


def test_malformed_rhs_source_missing_component_raises():
    gen = _gen()
    check = _check(rhs_source={"field": "f"})
    m = {"protocol": "usb3_2", "scoreboard_rules": [check]}
    with pytest.raises(MalformedScoreboardCheckError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.detail["side"] == "rhs_source"


def test_invalid_compare_op_raises():
    gen = _gen()
    check = _check(compare_op="approximately")
    m = {"protocol": "usb3_2", "scoreboard_rules": [check]}
    with pytest.raises(MalformedScoreboardCheckError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "INVALID_COMPARE_OP"


def test_missing_on_mismatch_raises():
    gen = _gen()
    check = _check()
    del check["on_mismatch"]
    m = {"protocol": "usb3_2", "scoreboard_rules": [check]}
    with pytest.raises(MalformedScoreboardCheckError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "MISSING_ON_MISMATCH"


def test_invalid_severity_raises():
    gen = _gen()
    check = _check(on_mismatch={"severity": "UVM_CRITICAL", "message_template": "x"})
    m = {"protocol": "usb3_2", "scoreboard_rules": [check]}
    with pytest.raises(MalformedScoreboardCheckError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "INVALID_MISMATCH_SEVERITY"


def test_missing_message_template_raises():
    gen = _gen()
    check = _check(on_mismatch={"severity": "UVM_ERROR", "message_template": ""})
    m = {"protocol": "usb3_2", "scoreboard_rules": [check]}
    with pytest.raises(MalformedScoreboardCheckError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "MISSING_MISMATCH_MESSAGE_TEMPLATE"


def test_invalid_register_decode_negative_offset_raises():
    gen = _gen()
    check = _check(lhs_source={"component": "dut_reg", "field": "f",
                                "register_decode": {"bit_offset": -1, "bit_width": 2}})
    m = {"protocol": "usb3_2", "scoreboard_rules": [check]}
    with pytest.raises(MalformedScoreboardCheckError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "INVALID_REGISTER_DECODE"


def test_invalid_register_decode_zero_width_raises():
    gen = _gen()
    check = _check(lhs_source={"component": "dut_reg", "field": "f",
                                "register_decode": {"bit_offset": 0, "bit_width": 0}})
    m = {"protocol": "usb3_2", "scoreboard_rules": [check]}
    with pytest.raises(MalformedScoreboardCheckError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "INVALID_REGISTER_DECODE"


def test_unsupported_enum_translation_kind_raises():
    gen = _gen()
    check = _check(rhs_source={"component": "vip_cfg", "field": "f",
                                "enum_translation": {"kind": "reverse_lookup", "map": {"0": 0}, "note": "n"}})
    m = {"protocol": "usb3_2", "scoreboard_rules": [check]}
    with pytest.raises(MalformedScoreboardCheckError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "UNSUPPORTED_ENUM_TRANSLATION_KIND"


def test_missing_enum_translation_map_raises():
    gen = _gen()
    check = _check(rhs_source={"component": "vip_cfg", "field": "f",
                                "enum_translation": {"kind": "value_map", "map": {}, "note": "n"}})
    m = {"protocol": "usb3_2", "scoreboard_rules": [check]}
    with pytest.raises(MalformedScoreboardCheckError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "MISSING_ENUM_TRANSLATION_MAP"


def test_missing_enum_translation_note_raises():
    """Evidence-discipline requirement: an enum_translation map is never
    accepted without a citation of why the mapping is correct -- same
    evidence-required discipline as this generator's "connections"/
    "virtual_sequences" evidence strings."""
    gen = _gen()
    check = _check(rhs_source={"component": "vip_cfg", "field": "f",
                                "enum_translation": {"kind": "value_map", "map": {"0": 0}, "note": ""}})
    m = {"protocol": "usb3_2", "scoreboard_rules": [check]}
    with pytest.raises(MalformedScoreboardCheckError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "MISSING_ENUM_TRANSLATION_NOTE"


def test_mask_eq_without_mask_raises():
    gen = _gen()
    check = _check(compare_op="mask_eq")
    m = {"protocol": "usb3_2", "scoreboard_rules": [check]}
    with pytest.raises(MalformedScoreboardCheckError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "MISSING_MASK_EQ_MASK"


def test_mask_eq_with_mask_compiles():
    gen = _gen()
    check = _check(compare_op="mask_eq", mask="16'hFF00")
    m = {"protocol": "usb3_2", "scoreboard_rules": [check]}
    sb = gen.scoreboard(m, sv_id(m["protocol"]))
    assert "(lhs & (16'hFF00)) !== (rhs & (16'hFF00))" in sb
