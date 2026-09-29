"""Tests for the COVERAGE_POINTS DSL extension to the top-level
"coverage_points" manifest field (2026-09-01), implementing
.work/coverage-generator-design-report.md's Part 1.

Gap closed by this task: coverage() did nothing but comment-dump every
"coverage_points" entry into an otherwise-empty `uvm_component` class body --
no real `covergroup`/`coverpoint`/`bins`/`cross` SV was ever emitted, and the
class had no analysis export or write() hook at all (confirmed, this task's
own read-first pass). Symmetrically, the `uvm_subscriber` base-class fix
(replacing `uvm_component`) is the load-bearing change that makes sampling
possible at all -- see generator.py's coverage() docstring for the full
sampling-wiring RULING (every coverpoint gets a persistent class-member
shadow variable "cp_<cp_name>", never a write()-local, because a no-arg
`cg.sample()` call can only read symbols in scope at the class level).

Discriminator (additive, backward compatible): a "coverage_points" entry
that is a dict AND carries a "cg_name" key opts into the new structured
shape; every existing manifest's entries (plain {"TODO": "..."} dicts, same
shape SCOREBOARD_CHECKS' own backward-compat tests use) carry no such key and
so are completely unaffected -- verified byte-identical against the original
comment-dump template.

Groups:
  - backward-compat: absent key / empty list / legacy freeform entries ->
    byte-identical to the pre-existing comment-dump template
  - a worked "subscriber_write" example (register_decode + enum_translation
    on one coverpoint, a plain coverpoint, a cross with an evidence-cited
    ignore_bins) -- covers the uvm_subscriber base-class swap, the shadow
    member declarations, write()'s decode/translate/sample sequence, and the
    covergroup/bins/cross SV shape
  - an "explicit_call" example -- covers the generated
    `function void sample_<cg_name>(<params>)` shape and its own
    decode/translate/sample sequence
  - a mixed manifest: legacy freeform entry stays comment-dumped, structured
    entries appended
  - multiple "subscriber_write" entries sharing one item_class -- both
    covergroups' write()-body fragments land in ONE write() override
  - error cases the DSL's own field list defines (see
    MalformedCoveragePointError's docstring for the full reason-code list)
"""
from __future__ import annotations

import tempfile

import pytest

from dv_harness.uvm_generator.generator import (
    MalformedCoveragePointError,
    UVMEnvironmentGenerator,
    sv_id,
)


def _gen():
    return UVMEnvironmentGenerator(tempfile.mkdtemp())


# ---------------------------------------------------------------------------
# backward-compat: absent key / empty list / legacy freeform entries
# ---------------------------------------------------------------------------

EXPECTED_EMPTY_COVERAGE_SV = '''class usb3_2_coverage extends uvm_component;
  `uvm_component_utils(usb3_2_coverage)
  // Protocol-specific coverage comes from the semantic model.
  function new(string name="usb3_2_coverage", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
'''


def test_absent_coverage_points_key_byte_identical_to_placeholder():
    gen = _gen()
    m = {"protocol": "usb3_2"}
    cov = gen.coverage(m, sv_id(m["protocol"]))
    assert cov == EXPECTED_EMPTY_COVERAGE_SV


def test_empty_coverage_points_list_byte_identical_to_placeholder():
    gen = _gen()
    m = {"protocol": "usb3_2", "coverage_points": []}
    cov = gen.coverage(m, sv_id(m["protocol"]))
    assert cov == EXPECTED_EMPTY_COVERAGE_SV


LEGACY_MANIFEST = {
    "protocol": "usb3_2",
    "coverage_points": [
        {"TODO": "not enough real evidence gathered this pass to state a specific coverage bin"},
    ],
}

EXPECTED_LEGACY_COVERAGE_SV = '''class usb3_2_coverage extends uvm_component;
  `uvm_component_utils(usb3_2_coverage)
  // COVER: {"TODO": "not enough real evidence gathered this pass to state a specific coverage bin"}
  function new(string name="usb3_2_coverage", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
'''


def test_legacy_freeform_entry_comment_dumps_byte_identical():
    gen = _gen()
    cov = gen.coverage(LEGACY_MANIFEST, sv_id(LEGACY_MANIFEST["protocol"]))
    assert cov == EXPECTED_LEGACY_COVERAGE_SV
    assert "covergroup" not in cov
    assert "uvm_subscriber" not in cov


# ---------------------------------------------------------------------------
# worked "subscriber_write" example: register_decode + enum_translation,
# a plain coverpoint, and a cross with an evidence-cited ignore_bins
# ---------------------------------------------------------------------------

EPTYPE_CG = {
    "cg_name": "ep0_cov",
    "evidence": "D:/DV/Task/USB/DOC/DWC_usb31_programming.txt DEPCFG0.EPTYPE",
    "sample_trigger": {"kind": "subscriber_write", "item_class": "svt_usb_transfer"},
    "coverpoints": [
        {
            "cp_name": "eptype",
            "expr": "t.raw_depcfg0",
            "register_decode": {"bit_offset": 1, "bit_width": 2},
            "enum_translation": {
                "kind": "value_map",
                "map": {"0": 0, "1": 1, "2": 2, "3": 3},
                "note": "Identity, verified against real macro-resolved values.",
            },
            "bins": [
                {"kind": "bins", "name": "ctrl", "values": "{0}"},
                {"kind": "bins", "name": "iso_bulk_intr", "values": "{[1:3]}"},
            ],
        },
        {
            "cp_name": "dir",
            "expr": "t.direction",
            "bins": [
                {"kind": "bins", "name": "dir_vals", "values": "{[0:1]}"},
            ],
        },
    ],
    "crosses": [
        {
            "cross_name": "eptype_x_dir",
            "of": ["eptype", "dir"],
            "ignore_bins": [
                {"name": "ctrl_no_dir", "expr": "binsof(eptype) intersect {0}",
                 "evidence": "USB 2.0 spec 9.4: control endpoints are bidirectional, no per-direction split"},
            ],
        }
    ],
}

SUBSCRIBER_MANIFEST = {"protocol": "usb3_2", "coverage_points": [EPTYPE_CG]}


def test_subscriber_write_swaps_base_class_to_uvm_subscriber():
    gen = _gen()
    cov = gen.coverage(SUBSCRIBER_MANIFEST, sv_id(SUBSCRIBER_MANIFEST["protocol"]))
    assert "class usb3_2_coverage extends uvm_subscriber #(svt_usb_transfer);" in cov
    assert "extends uvm_component" not in cov


def test_subscriber_write_declares_covergroup_and_shadow_members():
    gen = _gen()
    cov = gen.coverage(SUBSCRIBER_MANIFEST, sv_id(SUBSCRIBER_MANIFEST["protocol"]))
    assert "covergroup cg_ep0_cov;" in cov
    assert "endgroup" in cov
    # register_decode + enum_translation coverpoint -> int shadow member (post-translation type)
    assert "int cp_eptype;" in cov
    # plain coverpoint -> default int shadow member (no sv_type override given)
    assert "int cp_dir;" in cov
    assert "eptype: coverpoint cp_eptype {" in cov
    assert "dir: coverpoint cp_dir {" in cov
    assert "bins ctrl = {0};" in cov
    assert "bins iso_bulk_intr = {[1:3]};" in cov
    assert "bins dir_vals = {[0:1]};" in cov


def test_subscriber_write_register_decode_and_enum_translation_compiled():
    gen = _gen()
    cov = gen.coverage(SUBSCRIBER_MANIFEST, sv_id(SUBSCRIBER_MANIFEST["protocol"]))
    # register_decode slice: bit_offset=1, bit_width=2 -> [2:1]
    assert "bit [1:0] cp_eptype_raw = t.raw_depcfg0[2:1];" in cov
    assert "case (cp_eptype_raw)" in cov
    assert "0: cp_eptype = 0;" in cov
    assert "1: cp_eptype = 1;" in cov
    assert "default: begin" in cov
    assert "cp_eptype = cp_eptype_raw;" in cov
    assert '`uvm_error("COV_EP0_COV_EPTYPE",' in cov
    # no re-declaration of the class member as a function-local inside
    # write() -- that would shadow it and break sampling (see coverage()'s
    # own RULING docstring on why every coverpoint uses declare_dest=False)
    write_body = cov[cov.index("function void write("):]
    assert "int cp_eptype;" not in write_body


def test_subscriber_write_plain_coverpoint_assigns_directly_no_cast():
    gen = _gen()
    cov = gen.coverage(SUBSCRIBER_MANIFEST, sv_id(SUBSCRIBER_MANIFEST["protocol"]))
    assert "cp_dir = t.direction;" in cov


def test_subscriber_write_body_and_sample_call_shape():
    gen = _gen()
    cov = gen.coverage(SUBSCRIBER_MANIFEST, sv_id(SUBSCRIBER_MANIFEST["protocol"]))
    assert "function void write(svt_usb_transfer t);" in cov
    assert "cg_ep0_cov.sample();" in cov
    pos_write = cov.index("function void write(")
    pos_sample = cov.index("cg_ep0_cov.sample();")
    pos_endclass = cov.rindex("endclass")
    assert pos_write < pos_sample < pos_endclass


def test_subscriber_write_constructor_news_the_covergroup():
    gen = _gen()
    cov = gen.coverage(SUBSCRIBER_MANIFEST, sv_id(SUBSCRIBER_MANIFEST["protocol"]))
    pos_new_fn = cov.index("function new(")
    pos_cg_new = cov.index("cg_ep0_cov = new();")
    pos_endfn = cov.index("endfunction")
    assert pos_new_fn < pos_cg_new < pos_endfn


def test_cross_with_evidence_cited_ignore_bins():
    gen = _gen()
    cov = gen.coverage(SUBSCRIBER_MANIFEST, sv_id(SUBSCRIBER_MANIFEST["protocol"]))
    assert "eptype_x_dir: cross eptype, dir {" in cov
    assert "// evidence: USB 2.0 spec 9.4: control endpoints are bidirectional, no per-direction split" in cov
    assert "ignore_bins ctrl_no_dir = binsof(eptype) intersect {0};" in cov


# ---------------------------------------------------------------------------
# "explicit_call" example
# ---------------------------------------------------------------------------

EXPLICIT_CG = {
    "cg_name": "xfer_size_cov",
    "evidence": "DUT RTL udc_DWC_usb31 transfer-size counter, verified against DWC_usb31_programming.txt",
    "sample_trigger": {"kind": "explicit_call"},
    "coverpoints": [
        {
            "cp_name": "xfer_len",
            "expr": "xfer_len_bits",
            "register_decode": {"bit_offset": 0, "bit_width": 16},
            "bins": [
                {"kind": "bins_array", "name": "sizes", "range": "[0:65535]"},
            ],
        },
    ],
}

EXPLICIT_MANIFEST = {"protocol": "usb3_2", "coverage_points": [EXPLICIT_CG]}


def test_explicit_call_stays_uvm_component_base():
    gen = _gen()
    cov = gen.coverage(EXPLICIT_MANIFEST, sv_id(EXPLICIT_MANIFEST["protocol"]))
    assert "class usb3_2_coverage extends uvm_component;" in cov
    assert "uvm_subscriber" not in cov


def test_explicit_call_emits_sample_function_with_register_decode_param():
    gen = _gen()
    cov = gen.coverage(EXPLICIT_MANIFEST, sv_id(EXPLICIT_MANIFEST["protocol"]))
    assert "function void sample_xfer_size_cov(bit [31:0] in_xfer_len);" in cov
    assert "bit [15:0] cp_xfer_len_raw = in_xfer_len[15:0];" not in cov  # no enum_translation -> no _raw var
    assert "cp_xfer_len = in_xfer_len[15:0];" in cov
    assert "cg_xfer_size_cov.sample();" in cov
    assert "bins sizes[] = {[0:65535]};" in cov


# ---------------------------------------------------------------------------
# mixed manifest: legacy comment-dump untouched, structured entry appended
# ---------------------------------------------------------------------------

MIXED_MANIFEST = {
    "protocol": "usb3_2",
    "coverage_points": [
        {"TODO": "legacy note kept as-is"},
        EXPLICIT_CG,
    ],
}


def test_mixed_manifest_keeps_legacy_comment_and_appends_compiled_group():
    gen = _gen()
    cov = gen.coverage(MIXED_MANIFEST, sv_id(MIXED_MANIFEST["protocol"]))
    assert '  // COVER: {"TODO": "legacy note kept as-is"}' in cov
    assert "covergroup cg_xfer_size_cov;" in cov
    pos_comment = cov.index("// COVER:")
    pos_cg = cov.index("covergroup cg_xfer_size_cov;")
    assert pos_comment < pos_cg


# ---------------------------------------------------------------------------
# multiple subscriber_write entries sharing one item_class
# ---------------------------------------------------------------------------

SECOND_CG = {
    "cg_name": "dir_cov",
    "evidence": "D:/DV/Task/USB/DOC direction bit",
    "sample_trigger": {"kind": "subscriber_write", "item_class": "svt_usb_transfer"},
    "coverpoints": [
        {"cp_name": "dir2", "expr": "t.direction",
         "bins": [{"kind": "bins", "name": "d", "values": "{[0:1]}"}]},
    ],
}

MULTI_CG_MANIFEST = {"protocol": "usb3_2", "coverage_points": [EPTYPE_CG, SECOND_CG]}


def test_multiple_subscriber_entries_share_one_write_override():
    gen = _gen()
    cov = gen.coverage(MULTI_CG_MANIFEST, sv_id(MULTI_CG_MANIFEST["protocol"]))
    assert cov.count("function void write(svt_usb_transfer t);") == 1
    assert "cg_ep0_cov.sample();" in cov
    assert "cg_dir_cov.sample();" in cov
    assert "covergroup cg_ep0_cov;" in cov
    assert "covergroup cg_dir_cov;" in cov


def test_conflicting_item_class_raises():
    gen = _gen()
    conflicting = dict(SECOND_CG)
    conflicting["cg_name"] = "dir_cov2"
    conflicting["sample_trigger"] = {"kind": "subscriber_write", "item_class": "svt_other_transfer"}
    m = {"protocol": "usb3_2", "coverage_points": [EPTYPE_CG, conflicting]}
    with pytest.raises(MalformedCoveragePointError) as exc_info:
        gen.coverage(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "CONFLICTING_ITEM_CLASS"


# ---------------------------------------------------------------------------
# error cases
# ---------------------------------------------------------------------------

def _cg(**overrides):
    base = {
        "cg_name": "some_cov",
        "evidence": "evidence text",
        "sample_trigger": {"kind": "subscriber_write", "item_class": "some_item"},
        "coverpoints": [
            {"cp_name": "cp1", "expr": "t.f",
             "bins": [{"kind": "bins", "name": "b1", "values": "{0}"}]},
        ],
    }
    base.update(overrides)
    return base


def _raises(m, reason):
    gen = _gen()
    with pytest.raises(MalformedCoveragePointError) as exc_info:
        gen.coverage(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == reason


def test_missing_cg_name_raises():
    _raises({"protocol": "usb3_2", "coverage_points": [{"cg_name": ""}]}, "MISSING_CG_NAME")


def test_missing_evidence_raises():
    cg = _cg()
    del cg["evidence"]
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "MISSING_COVERAGE_EVIDENCE")


def test_invalid_sample_trigger_kind_raises():
    cg = _cg(sample_trigger={"kind": "on_the_fly"})
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "INVALID_SAMPLE_TRIGGER_KIND")


def test_missing_sample_trigger_raises():
    cg = _cg()
    del cg["sample_trigger"]
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "INVALID_SAMPLE_TRIGGER_KIND")


def test_missing_item_class_for_subscriber_write_raises():
    cg = _cg(sample_trigger={"kind": "subscriber_write"})
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "MISSING_ITEM_CLASS")


def test_empty_coverpoints_raises():
    cg = _cg(coverpoints=[])
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "EMPTY_COVERPOINTS")


def test_malformed_coverpoint_missing_expr_raises():
    cg = _cg(coverpoints=[{"cp_name": "cp1", "bins": [{"kind": "bins", "name": "b", "values": "{0}"}]}])
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "MALFORMED_COVERPOINT")


def test_duplicate_cp_name_raises():
    dup_cp = {"cp_name": "cp1", "expr": "t.g", "bins": [{"kind": "bins", "name": "b2", "values": "{0}"}]}
    cg = _cg(coverpoints=[_cg()["coverpoints"][0], dup_cp])
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "DUPLICATE_CP_NAME")


def test_empty_bins_raises():
    cg = _cg(coverpoints=[{"cp_name": "cp1", "expr": "t.f", "bins": []}])
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "EMPTY_BINS")


def test_invalid_bin_kind_raises():
    cg = _cg(coverpoints=[{"cp_name": "cp1", "expr": "t.f",
                            "bins": [{"kind": "transition_bins", "name": "b", "values": "{0}"}]}])
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "INVALID_BIN_KIND")


def test_malformed_bin_missing_values_raises():
    cg = _cg(coverpoints=[{"cp_name": "cp1", "expr": "t.f",
                            "bins": [{"kind": "bins", "name": "b"}]}])
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "MALFORMED_BIN")


def test_malformed_bin_array_missing_range_raises():
    cg = _cg(coverpoints=[{"cp_name": "cp1", "expr": "t.f",
                            "bins": [{"kind": "bins_array", "name": "b"}]}])
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "MALFORMED_BIN")


def test_undeclared_cross_coverpoint_raises():
    cg = _cg(crosses=[{"cross_name": "x", "of": ["cp1", "does_not_exist"]}])
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "UNDECLARED_CROSS_COVERPOINT")


def test_malformed_cross_missing_of_raises():
    cg = _cg(crosses=[{"cross_name": "x"}])
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "MALFORMED_CROSS")


def test_malformed_cross_ignore_bin_missing_evidence_raises():
    cg = _cg(coverpoints=[
        {"cp_name": "cp1", "expr": "t.f", "bins": [{"kind": "bins", "name": "b1", "values": "{0}"}]},
        {"cp_name": "cp2", "expr": "t.g", "bins": [{"kind": "bins", "name": "b2", "values": "{0}"}]},
    ], crosses=[{"cross_name": "x", "of": ["cp1", "cp2"],
                 "ignore_bins": [{"name": "n", "expr": "e"}]}])
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "MALFORMED_CROSS_IGNORE_BIN")


def test_invalid_register_decode_raises_shared_reason():
    cg = _cg(coverpoints=[{"cp_name": "cp1", "expr": "t.f",
                            "register_decode": {"bit_offset": -1, "bit_width": 2},
                            "bins": [{"kind": "bins", "name": "b1", "values": "{0}"}]}])
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "INVALID_REGISTER_DECODE")


def test_unsupported_enum_translation_kind_raises_shared_reason():
    cg = _cg(coverpoints=[{"cp_name": "cp1", "expr": "t.f",
                            "enum_translation": {"kind": "reverse_lookup", "map": {"0": 0}, "note": "n"},
                            "bins": [{"kind": "bins", "name": "b1", "values": "{0}"}]}])
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "UNSUPPORTED_ENUM_TRANSLATION_KIND")


def test_missing_enum_translation_note_raises_shared_reason():
    cg = _cg(coverpoints=[{"cp_name": "cp1", "expr": "t.f",
                            "enum_translation": {"kind": "value_map", "map": {"0": 0}, "note": ""},
                            "bins": [{"kind": "bins", "name": "b1", "values": "{0}"}]}])
    _raises({"protocol": "usb3_2", "coverage_points": [cg]}, "MISSING_ENUM_TRANSLATION_NOTE")


# ---------------------------------------------------------------------------
# SCOREBOARD_CHECKS regression: _decode_and_translate refactor must not
# change _emit_scoreboard_check's own compiled output (see
# test_scoreboard_check_dsl.py for the full pre-existing suite this
# refactor must keep passing byte-for-byte; these are focused spot-checks
# specific to this task's own refactor, not a duplicate of that file).
# ---------------------------------------------------------------------------

def test_scoreboard_check_dsl_unaffected_by_shared_helper_refactor():
    gen = _gen()
    check = {
        "check_name": "ep0_eptype_dut_vip_match",
        "lhs_source": {
            "component": "dut_reg", "field": "eptype",
            "register_decode": {"bit_offset": 1, "bit_width": 2},
        },
        "rhs_source": {
            "component": "vip_ep_cfg", "field": "ep_type",
            "enum_translation": {"kind": "value_map", "map": {"0": 0}, "note": "n"},
        },
        "compare_op": "eq",
        "on_mismatch": {"severity": "UVM_ERROR", "message_template": "%s %0d %0d"},
    }
    sb = gen.scoreboard({"protocol": "usb3_2", "scoreboard_rules": [check]}, "usb3_2")
    assert "bit [1:0] lhs = dut_reg_eptype[2:1];" in sb
    assert "case (rhs_raw)" in sb
    assert "int rhs;" in sb
    assert '`uvm_error("SB_EP0_EPTYPE_DUT_VIP_MATCH",' in sb
