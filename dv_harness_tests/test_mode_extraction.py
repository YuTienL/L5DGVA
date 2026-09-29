"""Tests for dv_harness/mode_extraction.py -- declared operating-MODE facts
(a mode-select register field and its documented legal values), built on
sys_regmap.py's real mode-bit classification and register_rtl_trace.py's
real RTL tracing.

Same evidence discipline as test_register_rtl_trace.py: any test that needs
a real parse runs the REAL `verible-verilog-syntax` subprocess and is
SKIPPED (never mocked) on a machine without it. Every RTL/sys_regmap fixture
here is synthetic, built directly in this file -- never real project content
(Evidence Truth Rule / No Golden-Reference Content Mining)."""
from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

import pytest

from dv_harness import mode_extraction as mx
from dv_harness import register_rtl_trace as rt
from dv_harness import sys_regmap

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None, reason="verible-verilog-syntax not on PATH")


# --- fixtures -----------------------------------------------------------------

def _field(name, bit_offset, bit_width, control_kind, *, required_value=None,
           governs_interfaces=None, access="RW"):
    d = {
        "name": name, "bit_offset": bit_offset, "bit_width": bit_width,
        "access": access, "control_kind": control_kind,
    }
    if required_value is not None:
        d["required_value"] = required_value
    if governs_interfaces is not None:
        d["governs_interfaces"] = governs_interfaces
    return d


def _sys_regmap_doc(fields):
    return {
        "schema_version": "1.0",
        "blocks": [{
            "name": "PMU",
            "base_address": "0x1000",
            "kind": "phy_control",
            "registers": [{
                "name": "MODE_CTRL",
                "address_offset": "0x10",
                "width": 32,
                "access": "RW",
                "fields": fields,
            }],
        }],
    }


PHY_MODE_SEL_FIELD = _field(
    "PHY_MODE_SEL", 0, 2, "phy_select",
    required_value="0x1", governs_interfaces=["usb_phy0"])
CLOCK_ENABLE_FIELD = _field("USB_CLK_EN", 4, 1, "clock_enable")
NOT_MODE_FIELD = _field("SCRATCH", 8, 4, "not_mode_determining")
MUX_SELECT_FIELD = _field("BUS_MUX_SEL", 12, 1, "mux_select")

RTL_WITH_MATCHING_PORT = textwrap.dedent("""\
    module phy_top (
        input  logic clk,
        input  logic rst_n,
        input  logic phy_mode_sel
    );
        logic mode_out;
        assign mode_out = phy_mode_sel;
    endmodule
""")

RTL_WITH_NO_MATCH = textwrap.dedent("""\
    module unrelated_block (
        input logic clk,
        input logic rst_n
    );
        logic something_else;
        assign something_else = clk;
    endmodule
""")


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# --- mode_select_bits: reuse + narrowing --------------------------------------

def test_mode_select_bits_includes_only_select_kinds():
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD, CLOCK_ENABLE_FIELD, NOT_MODE_FIELD, MUX_SELECT_FIELD])
    bits = mx.mode_select_bits(doc)
    names = {b["field"] for b in bits}
    assert names == {"PHY_MODE_SEL", "BUS_MUX_SEL"}
    for b in bits:
        assert b["control_kind"] in mx.MODE_SELECT_CONTROL_KINDS


def test_mode_select_bits_excludes_clock_enable_and_not_mode_determining():
    doc = _sys_regmap_doc([CLOCK_ENABLE_FIELD, NOT_MODE_FIELD])
    assert mx.mode_select_bits(doc) == []


def test_mode_select_bits_reuses_sys_regmap_mode_determining_bits(monkeypatch):
    """Proves this is a real filter over sys_regmap.py's own real output,
    not a re-implementation: a monkeypatched mode_determining_bits() is
    actually consulted."""
    sentinel = [
        {"block": "X", "register": "Y", "field": "A", "control_kind": "phy_select",
         "absolute_address": "0x1", "bit_offset": 0},
        {"block": "X", "register": "Y", "field": "B", "control_kind": "clock_enable",
         "absolute_address": "0x2", "bit_offset": 0},
    ]
    called = {}

    def fake_mode_determining_bits(doc, interface=None):
        called["doc"] = doc
        called["interface"] = interface
        return sentinel

    monkeypatch.setattr(sys_regmap, "mode_determining_bits", fake_mode_determining_bits)
    result = mx.mode_select_bits({"fake": True}, interface="usb0")
    assert called == {"doc": {"fake": True}, "interface": "usb0"}
    assert result == [sentinel[0]]


def test_bit_qualified_name():
    bit = {"block": "PMU", "register": "MODE_CTRL", "field": "PHY_MODE_SEL"}
    assert mx.bit_qualified_name(bit) == "PMU.MODE_CTRL.PHY_MODE_SEL"


def test_mode_select_control_kinds_assert_catches_a_kind_not_in_schema(monkeypatch):
    monkeypatch.setattr(mx, "MODE_SELECT_CONTROL_KINDS", ("totally_made_up_kind",))
    with pytest.raises(mx.ModeExtractionError) as exc:
        mx._assert_mode_select_kinds_known()
    assert exc.value.reason == "MODE_SELECT_KIND_NOT_IN_SCHEMA"


def test_mode_select_control_kinds_assert_rejects_not_mode_determining(monkeypatch):
    monkeypatch.setattr(mx, "MODE_SELECT_CONTROL_KINDS", (sys_regmap.NOT_MODE_DETERMINING,))
    with pytest.raises(mx.ModeExtractionError) as exc:
        mx._assert_mode_select_kinds_known()
    assert exc.value.reason == "NOT_MODE_DETERMINING_CANNOT_BE_A_MODE_SELECT_KIND"


# --- ModeValueEntry / ModeValueDeclaration: cited, never fabricated ----------

def test_mode_value_entry_round_trip():
    e = mx.ModeValueEntry(value="0x1", label="USB3_MODE", description="link is USB3")
    assert e.to_dict() == {"value": "0x1", "label": "USB3_MODE", "description": "link is USB3"}


def test_mode_value_entry_rejects_non_hex_value():
    with pytest.raises(mx.ModeExtractionError) as exc:
        mx.ModeValueEntry(value="1", label="X")
    assert exc.value.reason == "MODE_VALUE_ENTRY_BAD_VALUE"


def test_mode_value_entry_rejects_missing_label():
    with pytest.raises(mx.ModeExtractionError) as exc:
        mx.ModeValueEntry(value="0x1", label="  ")
    assert exc.value.reason == "MODE_VALUE_ENTRY_MISSING_LABEL"


def _decl(block="PMU", register="MODE_CTRL", field="PHY_MODE_SEL",
          values=(("0x0", "BYPASS"), ("0x1", "USB3_MODE")),
          citation="programming guide sec 4.2"):
    return mx.ModeValueDeclaration(
        block=block, register=register, field=field,
        values=tuple(mx.ModeValueEntry(value=v, label=l) for v, l in values),
        citation=citation,
    )


def test_mode_value_declaration_round_trip():
    d = _decl()
    assert d.qualified_name() == "PMU.MODE_CTRL.PHY_MODE_SEL"
    assert d.matches_bit({"block": "PMU", "register": "MODE_CTRL", "field": "PHY_MODE_SEL"})
    assert not d.matches_bit({"block": "PMU", "register": "MODE_CTRL", "field": "OTHER"})
    out = d.to_dict()
    assert out["citation"] == "programming guide sec 4.2"
    assert len(out["values"]) == 2


def test_mode_value_declaration_rejects_no_citation():
    with pytest.raises(mx.ModeExtractionError) as exc:
        _decl(citation="")
    assert exc.value.reason == "MODE_VALUE_DECLARATION_NO_CITATION"


def test_mode_value_declaration_rejects_no_values():
    with pytest.raises(mx.ModeExtractionError) as exc:
        mx.ModeValueDeclaration(block="B", register="R", field="F", values=(), citation="cite")
    assert exc.value.reason == "MODE_VALUE_DECLARATION_NO_VALUES"


def test_mode_value_declaration_rejects_missing_identity():
    with pytest.raises(mx.ModeExtractionError) as exc:
        _decl(block="")
    assert exc.value.reason == "MODE_VALUE_DECLARATION_MISSING_IDENTITY"


def test_mode_value_declaration_rejects_duplicate_value():
    # "0xA" and "0xa" both satisfy the hex pattern and normalize to the same
    # value -- a genuine duplicate, distinct from an outright bad value.
    with pytest.raises(mx.ModeExtractionError) as exc:
        _decl(values=(("0xA", "A"), ("0xa", "B")))
    assert exc.value.reason == "MODE_VALUE_DECLARATION_DUPLICATE_VALUE"


def test_mode_value_declaration_from_dict():
    d = mx.mode_value_declaration_from_dict({
        "block": "PMU", "register": "MODE_CTRL", "field": "PHY_MODE_SEL",
        "citation": "spec sec 3", "source_kind": "programming_guide_transcription",
        "values": [{"value": "0x0", "label": "BYPASS"}, {"value": "0x1", "label": "USB3_MODE"}],
    })
    assert d.qualified_name() == "PMU.MODE_CTRL.PHY_MODE_SEL"
    assert d.source_kind == "programming_guide_transcription"


def test_mode_value_declaration_from_dict_rejects_values_not_a_list():
    with pytest.raises(mx.ModeExtractionError) as exc:
        mx.mode_value_declaration_from_dict({
            "block": "PMU", "register": "MODE_CTRL", "field": "PHY_MODE_SEL",
            "citation": "spec", "values": "not-a-list",
        })
    assert exc.value.reason == "MODE_VALUE_DECLARATION_VALUES_NOT_A_LIST"


def test_mode_value_declaration_from_dict_rejects_entry_not_a_dict():
    with pytest.raises(mx.ModeExtractionError) as exc:
        mx.mode_value_declaration_from_dict({
            "block": "PMU", "register": "MODE_CTRL", "field": "PHY_MODE_SEL",
            "citation": "spec", "values": ["0x0"],
        })
    assert exc.value.reason == "MODE_VALUE_ENTRY_NOT_A_DICT"


def test_mode_value_declaration_from_dict_rejects_non_dict():
    with pytest.raises(mx.ModeExtractionError) as exc:
        mx.mode_value_declaration_from_dict("nope")
    assert exc.value.reason == "MODE_VALUE_DECLARATION_NOT_A_DICT"


# --- cross_check_required_value: real disagreement, never arbitrated --------

def test_cross_check_required_value_agrees_reports_nothing():
    bit = {"block": "PMU", "register": "MODE_CTRL", "field": "PHY_MODE_SEL", "required_value": "0x1"}
    decl = _decl()
    assert mx.cross_check_required_value(bit, decl) is None


def test_cross_check_required_value_disagrees_reports_finding():
    bit = {"block": "PMU", "register": "MODE_CTRL", "field": "PHY_MODE_SEL", "required_value": "0x5"}
    decl = _decl()
    finding = mx.cross_check_required_value(bit, decl)
    assert finding is not None
    assert finding["finding"] == "REQUIRED_VALUE_NOT_IN_DOCUMENTED_LEGAL_VALUES"
    assert finding["required_value"] == "0x5"
    assert finding["documented_values"] == ["0x0", "0x1"]


def test_cross_check_required_value_absent_required_value_reports_nothing():
    bit = {"block": "PMU", "register": "MODE_CTRL", "field": "PHY_MODE_SEL"}
    assert mx.cross_check_required_value(bit, _decl()) is None


def test_cross_check_required_value_no_declaration_reports_nothing():
    bit = {"block": "PMU", "register": "MODE_CTRL", "field": "PHY_MODE_SEL", "required_value": "0x9"}
    assert mx.cross_check_required_value(bit, None) is None


# --- extract_declared_modes: the full, integrated per-bit record ------------

@requires_verible
def test_extract_declared_modes_confirmed_end_to_end(tmp_path):
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD, CLOCK_ENABLE_FIELD])
    rtl_path = _write(tmp_path, "phy_top.sv", RTL_WITH_MATCHING_PORT)
    decl = _decl(values=(("0x0", "BYPASS"), ("0x1", "USB3_MODE")))

    report = mx.extract_declared_modes(
        doc, mode_value_declarations=[decl], rtl_paths=[str(rtl_path)])

    # Only the mode-select field is present -- clock_enable never appears.
    assert len(report.records) == 1
    rec = report.records[0]
    assert rec.qualified_name == "PMU.MODE_CTRL.PHY_MODE_SEL"
    assert rec.legal_values_status == mx.LEGAL_VALUES_DOCUMENTED
    assert {v.label for v in rec.legal_values} == {"BYPASS", "USB3_MODE"}
    assert rec.legal_value_citation == "programming guide sec 4.2"
    assert rec.required_value_conflict is None  # required_value 0x1 IS documented
    assert rec.rtl_trace.status == rt.TRACE_CONFIRMED
    assert rec.status == mx.MODE_FACT_CONFIRMED
    assert report.unmatched_declarations == []

    d = rec.to_dict()
    assert d["status"] == mx.MODE_FACT_CONFIRMED
    assert d["declared_valid_interfaces"]["governs_interfaces"] == ["usb_phy0"]


@requires_verible
def test_extract_declared_modes_not_documented(tmp_path):
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD])
    rtl_path = _write(tmp_path, "phy_top.sv", RTL_WITH_MATCHING_PORT)

    report = mx.extract_declared_modes(doc, rtl_paths=[str(rtl_path)])
    rec = report.records[0]
    assert rec.legal_values_status == mx.LEGAL_VALUES_NOT_DOCUMENTED
    assert rec.legal_values == []
    assert rec.rtl_trace.status == rt.TRACE_CONFIRMED
    # RTL is confirmed but the value set is undocumented -- never CONFIRMED.
    assert rec.status == mx.MODE_FACT_VALUES_NOT_DOCUMENTED


def test_extract_declared_modes_conflicting_declarations(tmp_path):
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD])
    decl_a = _decl(citation="guide A sec 1")
    decl_b = _decl(citation="guide B sec 9", values=(("0x0", "OFF"),))

    report = mx.extract_declared_modes(
        doc, mode_value_declarations=[decl_a, decl_b], rtl_corpus=[])
    rec = report.records[0]
    assert rec.legal_values_status == mx.LEGAL_VALUES_CONFLICTING
    assert set(rec.conflicting_citations) == {"guide A sec 1", "guide B sec 9"}
    assert rec.legal_values == []
    # A conflicting declaration outranks even a real RTL problem.
    assert rec.status == mx.MODE_FACT_CONFLICTING_DECLARATIONS
    assert report.unmatched_declarations == []


def test_extract_declared_modes_rtl_blocked_with_no_corpus():
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD])
    report = mx.extract_declared_modes(doc, mode_value_declarations=[_decl()], rtl_corpus=[])
    rec = report.records[0]
    assert rec.rtl_trace.status == rt.TRACE_BLOCKED
    assert rec.status == mx.MODE_FACT_RTL_BLOCKED


@requires_verible
def test_extract_declared_modes_rtl_not_found(tmp_path):
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD])
    rtl_path = _write(tmp_path, "unrelated.sv", RTL_WITH_NO_MATCH)
    report = mx.extract_declared_modes(
        doc, mode_value_declarations=[_decl()], rtl_paths=[str(rtl_path)])
    rec = report.records[0]
    assert rec.rtl_trace.status == rt.TRACE_NOT_FOUND
    # Documented legal values do NOT rescue an RTL field this module cannot find.
    assert rec.status == mx.MODE_FACT_RTL_NOT_FOUND


def test_extract_declared_modes_unmatched_declaration_reported():
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD])
    stray = _decl(field="NO_SUCH_FIELD", citation="guide sec 99")
    report = mx.extract_declared_modes(
        doc, mode_value_declarations=[stray, _decl()], rtl_corpus=[])
    assert len(report.unmatched_declarations) == 1
    assert report.unmatched_declarations[0].field == "NO_SUCH_FIELD"


def test_extract_declared_modes_empty_doc_yields_empty_report():
    doc = _sys_regmap_doc([CLOCK_ENABLE_FIELD, NOT_MODE_FIELD])
    report = mx.extract_declared_modes(doc)
    assert report.records == []


def test_extract_declared_modes_propagates_sys_regmap_validation_error():
    bad_doc = {"schema_version": "1.0"}  # missing required "blocks"
    with pytest.raises(sys_regmap.SysRegmapValidationError):
        mx.extract_declared_modes(bad_doc)


def test_extract_declared_modes_interface_scoping():
    field_scoped = _field(
        "PHY_MODE_SEL", 0, 2, "phy_select", governs_interfaces=["usb_phy0"])
    field_other = _field(
        "OTHER_SEL", 4, 1, "mux_select", governs_interfaces=["usb_phy1"])
    doc = _sys_regmap_doc([field_scoped, field_other])
    report = mx.extract_declared_modes(doc, interface="usb_phy0", rtl_corpus=[])
    assert len(report.records) == 1
    assert report.records[0].qualified_name.endswith("PHY_MODE_SEL")


# --- rendering ----------------------------------------------------------------

def test_render_markdown_smoke():
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD])
    report = mx.extract_declared_modes(doc, mode_value_declarations=[_decl()], rtl_corpus=[])
    text = mx.render_markdown(report)
    assert "PMU.MODE_CTRL.PHY_MODE_SEL" in text
    assert "phy_select" in text
    assert mx.MODE_FACT_RTL_BLOCKED in text


def test_render_markdown_reports_unmatched_declarations():
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD])
    stray = _decl(field="GHOST", citation="nowhere")
    report = mx.extract_declared_modes(doc, mode_value_declarations=[stray, _decl()], rtl_corpus=[])
    text = mx.render_markdown(report)
    assert "GHOST" in text
    assert "nowhere" in text


# --- CLI / execute_verb --------------------------------------------------------

def _write_json(tmp_path: Path, name: str, obj) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


@requires_verible
def test_execute_verb_confirmed_exit_zero(tmp_path):
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD])
    regmap_path = _write_json(tmp_path, "sys_regmap.json", doc)
    values_path = _write_json(tmp_path, "mode_values.json", [{
        "block": "PMU", "register": "MODE_CTRL", "field": "PHY_MODE_SEL",
        "citation": "cli test citation",
        "values": [{"value": "0x0", "label": "BYPASS"}, {"value": "0x1", "label": "USB3_MODE"}],
    }])
    rtl_path = _write(tmp_path, "phy_top.sv", RTL_WITH_MATCHING_PORT)

    text, code = mx.execute_verb(
        str(regmap_path), mode_values_path=str(values_path), rtl_paths=[str(rtl_path)])
    assert code == 0
    assert "MODE_FACT_CONFIRMED" in text

    text_json, code_json = mx.execute_verb(
        str(regmap_path), mode_values_path=str(values_path), rtl_paths=[str(rtl_path)],
        as_json=True)
    assert code_json == 0
    payload = json.loads(text_json)
    assert payload["records"][0]["status"] == "MODE_FACT_CONFIRMED"


def test_execute_verb_no_mode_select_fields_exit_two(tmp_path):
    doc = _sys_regmap_doc([CLOCK_ENABLE_FIELD])
    regmap_path = _write_json(tmp_path, "sys_regmap.json", doc)
    text, code = mx.execute_verb(str(regmap_path))
    assert code == 2


def test_execute_verb_bad_sys_regmap_path_exit_two(tmp_path):
    text, code = mx.execute_verb(str(tmp_path / "does_not_exist.json"))
    assert code == 2


def test_execute_verb_invalid_sys_regmap_document_exit_two(tmp_path):
    regmap_path = _write_json(tmp_path, "sys_regmap.json", {"schema_version": "1.0"})
    text, code = mx.execute_verb(str(regmap_path))
    assert code == 2
    assert "failed validation" in text


def test_execute_verb_bad_mode_values_path_exit_two(tmp_path):
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD])
    regmap_path = _write_json(tmp_path, "sys_regmap.json", doc)
    text, code = mx.execute_verb(
        str(regmap_path), mode_values_path=str(tmp_path / "missing.json"))
    assert code == 2


def test_execute_verb_malformed_mode_values_exit_two(tmp_path):
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD])
    regmap_path = _write_json(tmp_path, "sys_regmap.json", doc)
    values_path = _write_json(tmp_path, "mode_values.json", [{"block": "PMU"}])
    text, code = mx.execute_verb(str(regmap_path), mode_values_path=str(values_path))
    assert code == 2


def test_execute_verb_undocumented_and_unblocked_exit_one(tmp_path):
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD])
    regmap_path = _write_json(tmp_path, "sys_regmap.json", doc)
    text, code = mx.execute_verb(str(regmap_path))
    assert code == 1
    assert mx.MODE_FACT_RTL_BLOCKED in text or mx.MODE_FACT_VALUES_NOT_DOCUMENTED in text


def test_main_smoke(tmp_path, capsys):
    doc = _sys_regmap_doc([PHY_MODE_SEL_FIELD])
    regmap_path = _write_json(tmp_path, "sys_regmap.json", doc)
    code = mx.main(["--sys-regmap", str(regmap_path)])
    assert code in (0, 1, 2)
    out = capsys.readouterr().out
    assert out.strip() != ""
