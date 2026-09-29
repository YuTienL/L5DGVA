"""Tests for the TRANSACTION_SCOREBOARDS DSL: a new top-level
"transaction_scoreboards" manifest key on generator.py's scoreboard()
(2026-09-01), implementing .work/scoreboard-generator-design-report.md.

Gap closed by this task: SCOREBOARD_CHECKS (the existing "scoreboard_rules"
DSL, opted into per-entry via a "check_name" key) compiles exactly one
shape -- a single lhs/rhs field-equality comparison. There is no queue, no
memory across transactions, no TLM port, no matching -- this project's own
vocabulary (.claude/skills/CORE/dv-workflow/SKILL.md) calls that a
"checker", not a "scoreboard". A real transaction/data-integrity scoreboard
is a different mechanism: two independent TLM analysis-port streams
(predicted/observed), an internal queue of not-yet-matched predicted
transactions, a match_key-based lookup, a compare-fields policy once
matched, and disposition of orphaned-predicted (dropped), orphaned-observed
(fabricated/unexpected), and (optionally) duplicate transactions. Confirmed
absent anywhere in dv_harness/uvm_generator/ before this task: no
uvm_tlm_analysis_fifo/uvm_analysis_imp-based comparator, no transaction
queue, no match/orphan state machine existed anywhere in this package.

Schema (additive, backward compatible): an optional top-level manifest key
"transaction_scoreboards" -- a list of dicts. See generator.py's
scoreboard()/_emit_transaction_scoreboard docstrings for the full
field-by-field schema. Absent/empty key -> scoreboard() returns exactly
today's SCOREBOARD_CHECKS-only output, byte-identical (verified below).

Groups:
  - a representative worked example (OUT_OF_ORDER, array_eq payload
    compare, on_duplicate present) -- covers TLM port declarations, the
    match_key equality helper, compare_fields disposition, orphan_observed/
    orphan_predicted/duplicate disposition, report_phase drain check
  - an IN_ORDER variant (queue-head-only match, no on_duplicate) -- covers
    the strict-FIFO search shape and the "no on_duplicate -> no history
    queue, no num_duplicate counter" simplification
  - backward-compat: absent key / empty list -> byte-identical output
  - mixed manifest: existing "scoreboard_rules" check_entries AND
    "transaction_scoreboards" entries coexist, order preserved (check_entries
    stay inside the original "<p>_scoreboard" class; each transaction
    scoreboard is a separate class appended after it)
  - the `uvm_analysis_imp_decl` macro guard: two "transaction_scoreboards"
    entries in one manifest emit the macro pair exactly once, not twice
  - one test per typed-error branch (MalformedTransactionScoreboardError)
"""
from __future__ import annotations

import tempfile

import pytest

from dv_harness.uvm_generator.generator import (
    MalformedTransactionScoreboardError,
    UVMEnvironmentGenerator,
    sv_id,
)

from dv_harness_tests.test_connection_call_statements import _BASE as _CONNECTIONS_BASE


def _gen():
    return UVMEnvironmentGenerator(tempfile.mkdtemp())


# ---------------------------------------------------------------------------
# representative worked example: OUT_OF_ORDER + array_eq + on_duplicate
# ---------------------------------------------------------------------------

DMA_SCOREBOARD = {
    "scoreboard_name": "dma_payload",
    "evidence": "USB_UVM_Handoff usb_top_env.sv:531 "
                "dma_env.master[p].monitor.item_observed_port.connect(dma_sb[p].dma_export); "
                "a real, passive-monitor-only DMA scoreboard pattern -- the DUT itself drives "
                "the memory bus during DMA, so predicted/observed must be two independent "
                "analysis streams, not a single lhs/rhs field check.",
    "item_class": "usb_dma_txn",
    "predicted_port": {"port_name": "predicted_export"},
    "observed_port": {"port_name": "observed_export"},
    "ordering_policy": "OUT_OF_ORDER",
    "match_key": [{"field": "tag"}],
    "compare_fields": [
        {"field": "addr", "compare_op": "eq",
         "on_mismatch": {"severity": "UVM_ERROR",
                          "message_template": "addr mismatch on %s: exp=%0h obs=%0h"}},
        {"field": "payload", "compare_op": "array_eq",
         "on_mismatch": {"severity": "UVM_ERROR",
                          "message_template": "payload mismatch on %s: exp=%p obs=%p"}},
    ],
    "on_orphan_predicted": {"severity": "UVM_ERROR",
                             "message_template": "%s: %0d predicted DMA txns never observed (dropped)"},
    "on_orphan_observed": {"severity": "UVM_ERROR",
                            "message_template": "%s: unexpected observed DMA txn tag=%0d"},
    "on_duplicate": {"severity": "UVM_WARNING",
                      "message_template": "%s: duplicate observed DMA txn tag=%0d"},
}

DMA_MANIFEST = {
    "protocol": "usb3_2",
    "transaction_scoreboards": [DMA_SCOREBOARD],
}


def test_worked_example_emits_separate_class_with_tlm_ports_and_queue():
    gen = _gen()
    sb = gen.scoreboard(DMA_MANIFEST, sv_id(DMA_MANIFEST["protocol"]))

    assert "class usb3_2_dma_payload_scoreboard extends uvm_scoreboard;" in sb
    assert "`uvm_component_utils(usb3_2_dma_payload_scoreboard)" in sb
    assert "uvm_analysis_imp_predicted #(usb_dma_txn, usb3_2_dma_payload_scoreboard) predicted_export;" in sb
    assert "uvm_analysis_imp_observed  #(usb_dma_txn, usb3_2_dma_payload_scoreboard) observed_export;" in sb
    assert "usb_dma_txn predicted_q[$];" in sb
    assert "`uvm_analysis_imp_decl(_predicted)" in sb
    assert "`uvm_analysis_imp_decl(_observed)" in sb


def test_worked_example_build_phase_constructs_both_imps():
    gen = _gen()
    sb = gen.scoreboard(DMA_MANIFEST, sv_id(DMA_MANIFEST["protocol"]))
    assert 'predicted_export = new("predicted_export", this);' in sb
    assert 'observed_export = new("observed_export", this);' in sb


def test_worked_example_write_predicted_pushes_to_queue():
    gen = _gen()
    sb = gen.scoreboard(DMA_MANIFEST, sv_id(DMA_MANIFEST["protocol"]))
    assert "function void write_predicted(usb_dma_txn t);" in sb
    assert "predicted_q.push_back(t);" in sb


def test_worked_example_out_of_order_searches_whole_queue():
    gen = _gen()
    sb = gen.scoreboard(DMA_MANIFEST, sv_id(DMA_MANIFEST["protocol"]))
    assert "for (int i = 0; i < predicted_q.size(); i++) begin" in sb
    assert "if (key_eq(predicted_q[i], t)) begin" in sb
    assert "local function bit key_eq(usb_dma_txn a, usb_dma_txn b);" in sb
    assert "return (a.tag === b.tag);" in sb


def test_worked_example_compare_fields_use_exp_obs_and_correct_ops():
    gen = _gen()
    sb = gen.scoreboard(DMA_MANIFEST, sv_id(DMA_MANIFEST["protocol"]))
    # scalar eq keeps case-inequality `!==`
    assert "if (exp.addr !== obs.addr) begin" in sb
    assert '`uvm_error("SB_DMA_PAYLOAD_MISMATCH_ADDR",' in sb
    # array_eq uses plain `!=`, NOT `!==` -- IEEE 1800 disallows case
    # (in)equality on unpacked array types (dynamic arrays/queues); using
    # `!==` on a queue field would be a real VCS compile error.
    assert "if (exp.payload != obs.payload) begin" in sb
    assert "exp.payload !== obs.payload" not in sb
    assert '`uvm_error("SB_DMA_PAYLOAD_MISMATCH_PAYLOAD",' in sb


def test_worked_example_orphan_observed_and_duplicate_disposition():
    gen = _gen()
    sb = gen.scoreboard(DMA_MANIFEST, sv_id(DMA_MANIFEST["protocol"]))
    assert "usb_dma_txn matched_history_q[$];" in sb
    assert "int num_match, num_mismatch, num_orphan_predicted, num_orphan_observed, num_duplicate;" in sb
    assert "for (int k = 0; k < matched_history_q.size(); k++) begin" in sb
    assert "if (key_eq(matched_history_q[k], t)) begin dup_idx = k; break; end" in sb
    assert '`uvm_warning("SB_DMA_PAYLOAD_DUPLICATE", $sformatf("%s: duplicate observed DMA txn tag=%0d", t.tag))' in sb
    assert '`uvm_error("SB_DMA_PAYLOAD_ORPHAN_OBSERVED", $sformatf("%s: unexpected observed DMA txn tag=%0d", t.tag))' in sb
    assert "matched_history_q.push_back(exp);" in sb
    assert "predicted_q.delete(idx);" in sb
    assert "num_match++;" in sb


def test_worked_example_report_phase_drains_orphan_predicted():
    gen = _gen()
    sb = gen.scoreboard(DMA_MANIFEST, sv_id(DMA_MANIFEST["protocol"]))
    assert "function void report_phase(uvm_phase phase);" in sb
    assert "super.report_phase(phase);" in sb
    assert "if (predicted_q.size() > 0) begin" in sb
    assert "num_orphan_predicted = predicted_q.size();" in sb
    assert ('`uvm_error("SB_DMA_PAYLOAD_ORPHAN_PREDICTED", '
            '$sformatf("%s: %0d predicted DMA txns never observed (dropped)", "dma_payload", predicted_q.size()))') in sb


def test_worked_example_class_appended_after_base_scoreboard_class():
    gen = _gen()
    sb = gen.scoreboard(DMA_MANIFEST, sv_id(DMA_MANIFEST["protocol"]))
    pos_base_endclass = sb.index("endclass")
    pos_macro = sb.index("`uvm_analysis_imp_decl(_predicted)")
    pos_tx_class = sb.index("class usb3_2_dma_payload_scoreboard")
    assert pos_base_endclass < pos_macro < pos_tx_class
    assert sb.rstrip().endswith("endclass")


# ---------------------------------------------------------------------------
# IN_ORDER variant, no on_duplicate: strict-FIFO head-only match, no history
# ---------------------------------------------------------------------------

INORDER_SCOREBOARD = {
    "scoreboard_name": "control_xfer",
    "evidence": "USB 2.0 control transfers on a given endpoint complete strictly in issue "
                "order (single-outstanding control pipe) -- IN_ORDER is the correct matching "
                "policy here, unlike DMA's OUT_OF_ORDER completion.",
    "item_class": "usb_ctrl_txn",
    "predicted_port": {"port_name": "exp_ap"},
    "observed_port": {"port_name": "obs_ap"},
    "ordering_policy": "IN_ORDER",
    "match_key": [{"field": "xfer_id"}],
    "compare_fields": [
        {"field": "status", "compare_op": "eq",
         "on_mismatch": {"severity": "UVM_ERROR", "message_template": "status mismatch on %s: %0d vs %0d"}},
    ],
    "on_orphan_predicted": {"severity": "UVM_ERROR", "message_template": "%s: %0d dropped"},
    "on_orphan_observed": {"severity": "UVM_ERROR", "message_template": "%s: unexpected xfer_id=%0d"},
}

INORDER_MANIFEST = {
    "protocol": "usb3_2",
    "transaction_scoreboards": [INORDER_SCOREBOARD],
}


def test_in_order_policy_checks_only_queue_head():
    gen = _gen()
    sb = gen.scoreboard(INORDER_MANIFEST, sv_id(INORDER_MANIFEST["protocol"]))
    assert "if (predicted_q.size() > 0 && key_eq(predicted_q[0], t)) idx = 0;" in sb
    assert "for (int i = 0; i < predicted_q.size(); i++)" not in sb


def test_no_on_duplicate_omits_history_queue_and_counter():
    gen = _gen()
    sb = gen.scoreboard(INORDER_MANIFEST, sv_id(INORDER_MANIFEST["protocol"]))
    assert "matched_history_q" not in sb
    assert "num_duplicate" not in sb
    assert "int num_match, num_mismatch, num_orphan_predicted, num_orphan_observed;" in sb
    # no on_duplicate -> a second observed txn with a reused key is reported
    # as an ordinary orphan_observed, not distinguished as a duplicate
    assert "if (idx == -1) begin\n      num_orphan_observed++;" in sb


# ---------------------------------------------------------------------------
# backward-compat: absent key / empty list -> byte-identical
# ---------------------------------------------------------------------------

def test_absent_transaction_scoreboards_key_byte_identical_to_scoreboard_checks_only():
    gen = _gen()
    m = {"protocol": "usb3_2"}
    m_with_empty = {"protocol": "usb3_2", "transaction_scoreboards": []}
    sb_absent = gen.scoreboard(m, sv_id(m["protocol"]))
    sb_empty = gen.scoreboard(m_with_empty, sv_id(m_with_empty["protocol"]))
    expected = '''class usb3_2_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(usb3_2_scoreboard)
  // Protocol-specific checking rules come from the semantic model.
  function new(string name="usb3_2_scoreboard", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
'''
    assert sb_absent == expected
    assert sb_empty == expected
    assert "transaction_scoreboards" not in sb_absent
    assert "uvm_analysis_imp_decl" not in sb_absent


# ---------------------------------------------------------------------------
# mixed manifest: SCOREBOARD_CHECKS check_entries + transaction_scoreboards
# ---------------------------------------------------------------------------

MPS_CHECK = {
    "check_name": "ep0_mps_dut_vip_match",
    "lhs_source": {"component": "dut_reg", "field": "mps",
                   "register_decode": {"bit_offset": 3, "bit_width": 11}},
    "rhs_source": {"component": "vip_ep_cfg", "field": "max_packet_size"},
    "compare_op": "eq",
    "on_mismatch": {"severity": "UVM_ERROR",
                     "message_template": "MaxPacketSize mismatch on %s: DUT=%0d VIP=%0d"},
}

MIXED_MANIFEST = {
    "protocol": "usb3_2",
    "scoreboard_rules": [MPS_CHECK],
    "transaction_scoreboards": [DMA_SCOREBOARD],
}


def test_mixed_manifest_keeps_check_entries_inside_base_class_and_appends_tx_class_after():
    gen = _gen()
    sb = gen.scoreboard(MIXED_MANIFEST, sv_id(MIXED_MANIFEST["protocol"]))

    pos_check = sb.index("function void check_ep0_mps_dut_vip_match(")
    pos_base_endclass = sb.index("endclass")
    pos_tx_class = sb.index("class usb3_2_dma_payload_scoreboard")

    # the SCOREBOARD_CHECKS function lives INSIDE the original class, before
    # its endclass -- exactly like today, unaffected by the new DSL
    assert pos_check < pos_base_endclass < pos_tx_class
    assert sb.count("class usb3_2_scoreboard extends uvm_scoreboard;") == 1
    assert sb.count("class usb3_2_dma_payload_scoreboard extends uvm_scoreboard;") == 1


# ---------------------------------------------------------------------------
# macro-declaration guard: two entries -> macro pair emitted exactly once
# ---------------------------------------------------------------------------

SECOND_SCOREBOARD = dict(INORDER_SCOREBOARD, scoreboard_name="second_xfer")

TWO_ENTRY_MANIFEST = {
    "protocol": "usb3_2",
    "transaction_scoreboards": [DMA_SCOREBOARD, SECOND_SCOREBOARD],
}


def test_two_entries_share_one_macro_declaration_pair():
    gen = _gen()
    sb = gen.scoreboard(TWO_ENTRY_MANIFEST, sv_id(TWO_ENTRY_MANIFEST["protocol"]))
    assert sb.count("`uvm_analysis_imp_decl(_predicted)") == 1
    assert sb.count("`uvm_analysis_imp_decl(_observed)") == 1
    assert sb.count("class usb3_2_dma_payload_scoreboard extends uvm_scoreboard;") == 1
    assert sb.count("class usb3_2_second_xfer_scoreboard extends uvm_scoreboard;") == 1
    pos_dma = sb.index("class usb3_2_dma_payload_scoreboard")
    pos_second = sb.index("class usb3_2_second_xfer_scoreboard")
    assert pos_dma < pos_second  # manifest order preserved


# ---------------------------------------------------------------------------
# error cases -- one test per MalformedTransactionScoreboardError branch
# ---------------------------------------------------------------------------

def _entry(**overrides):
    base = {
        "scoreboard_name": "sb1",
        "evidence": "some real evidence citation",
        "item_class": "some_item",
        "predicted_port": {"port_name": "p_ap"},
        "observed_port": {"port_name": "o_ap"},
        "ordering_policy": "IN_ORDER",
        "match_key": [{"field": "id"}],
        "compare_fields": [
            {"field": "f", "compare_op": "eq",
             "on_mismatch": {"severity": "UVM_ERROR", "message_template": "%s %0d %0d"}},
        ],
        "on_orphan_predicted": {"severity": "UVM_ERROR", "message_template": "%s %0d"},
        "on_orphan_observed": {"severity": "UVM_ERROR", "message_template": "%s %0d"},
    }
    base.update(overrides)
    return base


def _manifest(entry):
    return {"protocol": "usb3_2", "transaction_scoreboards": [entry]}


def _raises(entry, reason):
    gen = _gen()
    m = _manifest(entry)
    with pytest.raises(MalformedTransactionScoreboardError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == reason
    return exc_info.value


def test_missing_scoreboard_name_raises():
    _raises(_entry(scoreboard_name=""), "MISSING_SCOREBOARD_NAME")


def test_entry_not_a_dict_raises_missing_scoreboard_name():
    gen = _gen()
    m = {"protocol": "usb3_2", "transaction_scoreboards": ["not a dict"]}
    with pytest.raises(MalformedTransactionScoreboardError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "MISSING_SCOREBOARD_NAME"


def test_duplicate_scoreboard_name_raises():
    gen = _gen()
    m = {"protocol": "usb3_2", "transaction_scoreboards": [_entry(), _entry()]}
    with pytest.raises(MalformedTransactionScoreboardError) as exc_info:
        gen.scoreboard(m, sv_id(m["protocol"]))
    assert exc_info.value.reason == "DUPLICATE_SCOREBOARD_NAME"


def test_missing_scoreboard_evidence_raises():
    _raises(_entry(evidence=""), "MISSING_SCOREBOARD_EVIDENCE")


def test_missing_item_class_raises():
    _raises(_entry(item_class=""), "MISSING_ITEM_CLASS")


def test_malformed_predicted_port_spec_raises():
    err = _raises(_entry(predicted_port={"port_name": ""}), "MALFORMED_PORT_SPEC")
    assert err.detail["side"] == "predicted_port"


def test_malformed_observed_port_spec_raises():
    err = _raises(_entry(observed_port={}), "MALFORMED_PORT_SPEC")
    assert err.detail["side"] == "observed_port"


def test_duplicate_port_name_raises():
    _raises(_entry(predicted_port={"port_name": "same"}, observed_port={"port_name": "same"}),
            "DUPLICATE_PORT_NAME")


def test_invalid_ordering_policy_raises():
    _raises(_entry(ordering_policy="RANDOM"), "INVALID_ORDERING_POLICY")


def test_empty_match_key_raises():
    _raises(_entry(match_key=[]), "EMPTY_MATCH_KEY")


def test_malformed_match_key_entry_raises():
    _raises(_entry(match_key=[{"field": ""}]), "MALFORMED_MATCH_KEY_ENTRY")


def test_empty_compare_fields_raises():
    _raises(_entry(compare_fields=[]), "EMPTY_COMPARE_FIELDS")


def test_malformed_compare_field_raises():
    _raises(_entry(compare_fields=[{"compare_op": "eq"}]), "MALFORMED_COMPARE_FIELD")


def test_invalid_compare_op_raises():
    _raises(_entry(compare_fields=[
        {"field": "f", "compare_op": "approximately",
         "on_mismatch": {"severity": "UVM_ERROR", "message_template": "x"}},
    ]), "INVALID_COMPARE_OP")


def test_missing_mask_eq_mask_raises():
    _raises(_entry(compare_fields=[
        {"field": "f", "compare_op": "mask_eq",
         "on_mismatch": {"severity": "UVM_ERROR", "message_template": "x"}},
    ]), "MISSING_MASK_EQ_MASK")


def test_mask_eq_with_mask_compiles():
    gen = _gen()
    m = _manifest(_entry(compare_fields=[
        {"field": "f", "compare_op": "mask_eq", "mask": "16'hFF00",
         "on_mismatch": {"severity": "UVM_ERROR", "message_template": "x %s %0d %0d"}},
    ]))
    sb = gen.scoreboard(m, sv_id(m["protocol"]))
    assert "(exp.f & (16'hFF00)) !== (obs.f & (16'hFF00))" in sb


def test_array_eq_compiles_with_plain_inequality():
    gen = _gen()
    m = _manifest(_entry(compare_fields=[
        {"field": "payload", "compare_op": "array_eq",
         "on_mismatch": {"severity": "UVM_ERROR", "message_template": "x %s %p %p"}},
    ]))
    sb = gen.scoreboard(m, sv_id(m["protocol"]))
    assert "if (exp.payload != obs.payload) begin" in sb


def test_missing_on_mismatch_raises():
    entry = _entry()
    del entry["compare_fields"][0]["on_mismatch"]
    _raises(entry, "MISSING_ON_MISMATCH")


def test_invalid_on_mismatch_severity_raises():
    entry = _entry(compare_fields=[
        {"field": "f", "compare_op": "eq",
         "on_mismatch": {"severity": "UVM_CRITICAL", "message_template": "x"}},
    ])
    _raises(entry, "INVALID_ON_MISMATCH_SEVERITY")


def test_missing_on_mismatch_message_template_raises():
    entry = _entry(compare_fields=[
        {"field": "f", "compare_op": "eq",
         "on_mismatch": {"severity": "UVM_ERROR", "message_template": ""}},
    ])
    _raises(entry, "MISSING_ON_MISMATCH_MESSAGE_TEMPLATE")


def test_missing_on_orphan_predicted_raises():
    entry = _entry()
    del entry["on_orphan_predicted"]
    _raises(entry, "MISSING_ON_ORPHAN_PREDICTED")


def test_invalid_on_orphan_predicted_severity_raises():
    _raises(_entry(on_orphan_predicted={"severity": "BAD", "message_template": "x"}),
            "INVALID_ON_ORPHAN_PREDICTED_SEVERITY")


def test_missing_on_orphan_predicted_message_template_raises():
    _raises(_entry(on_orphan_predicted={"severity": "UVM_ERROR", "message_template": ""}),
            "MISSING_ON_ORPHAN_PREDICTED_MESSAGE_TEMPLATE")


def test_missing_on_orphan_observed_raises():
    entry = _entry()
    del entry["on_orphan_observed"]
    _raises(entry, "MISSING_ON_ORPHAN_OBSERVED")


def test_invalid_on_orphan_observed_severity_raises():
    _raises(_entry(on_orphan_observed={"severity": "BAD", "message_template": "x"}),
            "INVALID_ON_ORPHAN_OBSERVED_SEVERITY")


def test_missing_on_orphan_observed_message_template_raises():
    _raises(_entry(on_orphan_observed={"severity": "UVM_ERROR", "message_template": ""}),
            "MISSING_ON_ORPHAN_OBSERVED_MESSAGE_TEMPLATE")


def test_invalid_on_duplicate_severity_raises():
    _raises(_entry(on_duplicate={"severity": "BAD", "message_template": "x"}),
            "INVALID_ON_DUPLICATE_SEVERITY")


def test_missing_on_duplicate_message_template_raises():
    _raises(_entry(on_duplicate={"severity": "UVM_ERROR", "message_template": ""}),
            "MISSING_ON_DUPLICATE_MESSAGE_TEMPLATE")


def test_on_duplicate_absent_entirely_is_fine():
    gen = _gen()
    m = _manifest(_entry())
    sb = gen.scoreboard(m, sv_id(m["protocol"]))
    assert "class usb3_2_sb1_scoreboard extends uvm_scoreboard;" in sb


# ---------------------------------------------------------------------------
# end-to-end integration: instantiation + TLM wiring reuse the existing,
# UNMODIFIED vip_components/connections machinery (design report point 6) --
# an ordinary class_handle vip_components entry for the generated scoreboard
# class, wired via the existing "connections" kind="call" shape, with zero
# changes anywhere outside scoreboard()/_emit_transaction_scoreboard*.
# ---------------------------------------------------------------------------

INTEGRATION_MANIFEST = dict(
    _CONNECTIONS_BASE,
    transaction_scoreboards=[DMA_SCOREBOARD],
    vip_components=_CONNECTIONS_BASE["vip_components"] + [
        {"name": "dma_predictor", "class_type": "usb_dma_predictor",
         "instance_name": "dma_predictor0", "depends_on": []},
        {"name": "dma_payload_sb", "class_type": "usb3_2_dma_payload_scoreboard",
         "instance_name": "dma_payload_sb0", "depends_on": []},
    ],
    connections=[
        {"kind": "call", "call_style": "instance",
         "receiver": "dma_predictor0.ap", "method": "connect",
         "args": ["dma_payload_sb0.predicted_export"],
         "evidence": "worked-example wiring, mirroring usb_top_env.sv:531's "
                      "<receiver>.<method>(<args>) shape for a predictor->scoreboard connection"},
        {"kind": "call", "call_style": "instance",
         "receiver": "usb_host_agent0.monitor.item_observed_port", "method": "connect",
         "args": ["dma_payload_sb0.observed_export"],
         "evidence": "usb_top_env.sv:531 dma_env.master[p].monitor.item_observed_port.connect(dma_sb[p].dma_export);"},
    ],
)


def test_generated_scoreboard_class_instantiates_via_unmodified_vip_components():
    """The generated "<p>_dma_payload_scoreboard" class is an ordinary
    uvm_component from _env_multi_component's point of view -- default
    class_handle kind, no new "kind" value needed, per design report point
    6. This asserts the class actually gets declared+created in env()'s
    output using ONLY the existing vip_components mechanism."""
    gen = _gen()
    env_sv = gen.env(INTEGRATION_MANIFEST, sv_id(INTEGRATION_MANIFEST["protocol"]))
    assert "usb3_2_dma_payload_scoreboard dma_payload_sb0;" in env_sv
    assert 'dma_payload_sb0=usb3_2_dma_payload_scoreboard::type_id::create("dma_payload_sb0",this);' in env_sv


def test_generated_scoreboard_ports_wired_via_unmodified_connections_call_kind():
    """The generated scoreboard's predicted_export/observed_export handles
    are wired via the pre-existing "connections" kind="call" shape -- the
    exact <receiver>.<method>(<args>) shape a real .connect() call needs
    (real evidence: USB_UVM_Handoff usb_top_env.sv:531), with zero
    connections.py-side changes needed for this DSL."""
    gen = _gen()
    env_sv = gen.env(INTEGRATION_MANIFEST, sv_id(INTEGRATION_MANIFEST["protocol"]))
    assert "dma_predictor0.ap.connect(dma_payload_sb0.predicted_export);" in env_sv
    assert "usb_host_agent0.monitor.item_observed_port.connect(dma_payload_sb0.observed_export);" in env_sv


def test_same_manifest_also_compiles_the_scoreboard_class_body():
    """The same manifest that wires the scoreboard's ports in env() also
    compiles the scoreboard's own class body via scoreboard() -- confirming
    the class name env()'s vip_components entry references
    ("usb3_2_dma_payload_scoreboard") is exactly the class scoreboard()
    actually emits, end to end on one real manifest."""
    gen = _gen()
    sb = gen.scoreboard(INTEGRATION_MANIFEST, sv_id(INTEGRATION_MANIFEST["protocol"]))
    assert "class usb3_2_dma_payload_scoreboard extends uvm_scoreboard;" in sb
    assert "predicted_export;" in sb
    assert "observed_export;" in sb


def test_malformed_third_entry_prevents_any_emission_of_first_two():
    """All-or-nothing posture: a malformed 3rd entry must not leave the
    first two partially emitted (same posture _emit_scoreboard_check's
    per-entry raise already has)."""
    gen = _gen()
    good1 = _entry(scoreboard_name="good_one")
    good2 = _entry(scoreboard_name="good_two")
    bad = _entry(scoreboard_name="")
    m = {"protocol": "usb3_2", "transaction_scoreboards": [good1, good2, bad]}
    with pytest.raises(MalformedTransactionScoreboardError):
        gen.scoreboard(m, sv_id(m["protocol"]))
