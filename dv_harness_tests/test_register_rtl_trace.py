"""Tests for dv_harness/register_rtl_trace.py -- tracing register_map.schema.json
fields to RTL signal/control-logic references via the real declaration-level
verible parse.

Same evidence discipline as dv_harness_tests/test_verible_parser.py and
test_uvm_structural_lint.py: every test that needs a real parse runs the REAL
`verible-verilog-syntax` subprocess through `verible_parser.parse_file()` and
is SKIPPED (never mocked) on a machine without it. A synthetic-but-realistic
RTL fixture is used throughout, never real project RTL (see CLAUDE.md's
Evidence Truth Rule / No Golden-Reference Content Mining)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dv_harness import register_rtl_trace as rt
from dv_harness.verible_parser import parse_file

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

ROOT = Path(__file__).resolve().parents[1]

# A small, realistic RTL module: two ports actually wired to internal logic
# (phy_reset_n gates a reset mux via a continuous assign; phy_mode_sel feeds a
# sub-instance port), one port that is declared but never referenced anywhere
# in the module body (irq_mask_ack -- a genuine, if unusual, real-world case:
# a port that exists purely as an external connection point), one internal
# signal that IS referenced (link_up, driven by an assign), and one internal
# signal that is declared but never used anywhere (dead_reg -- the bare
# -declaration negative control).
CLEAN_RTL = textwrap.dedent("""\
    module phy_ctrl (
        input  logic clk,
        input  logic rst_n,
        input  logic phy_reset_n,
        input  logic phy_mode_sel,
        input  logic irq_mask_ack
    );

        logic link_up;
        logic dead_reg;
        logic mux_out;

        assign mux_out = phy_reset_n ? rst_n : 1'b0;
        assign link_up = mux_out & clk;

        sub_block u_sub (
            .clk        (clk),
            .mode_sel   (phy_mode_sel),
            .link_up_in (link_up)
        );

    endmodule

    module sub_block (
        input logic clk,
        input logic mode_sel,
        input logic link_up_in
    );
    endmodule
""")

# A second module that ALSO declares a signal named identically to
# `phy_reset_n` (after normalization) -- used to build the cross-module
# AMBIGUITY negative control.
AMBIGUOUS_RTL = textwrap.dedent("""\
    module other_block (
        input logic clk
    );
        logic phy_reset_n;
        assign phy_reset_n = clk;
    endmodule
""")


@pytest.fixture
def clean_sv(tmp_path):
    p = tmp_path / "phy_ctrl.sv"
    p.write_text(CLEAN_RTL, encoding="utf-8")
    return p


@pytest.fixture
def ambiguous_sv(tmp_path):
    p = tmp_path / "other_block.sv"
    p.write_text(AMBIGUOUS_RTL, encoding="utf-8")
    return p


@pytest.fixture
def broken_sv(tmp_path):
    p = tmp_path / "broken.sv"
    p.write_text("module broken(\n  input logic clk\n", encoding="utf-8")
    return p


# --- normalize_signal_name ----------------------------------------------------

def test_normalize_signal_name_is_case_and_underscore_insensitive():
    assert rt.normalize_signal_name("PHY_RESET_N") == rt.normalize_signal_name("phy_reset_n")
    assert rt.normalize_signal_name("PhyResetN") == rt.normalize_signal_name("phy_reset_n")


def test_normalize_signal_name_handles_none_and_empty():
    assert rt.normalize_signal_name(None) == ""
    assert rt.normalize_signal_name("") == ""


# --- field_ref_from_dict / field_refs_from_register_map ----------------------

def test_field_ref_from_dict_builds_qualified_name():
    fr = rt.field_ref_from_dict({"name": "phy_reset_n", "register": "CTRL0", "block": "PHY"})
    assert fr.name == "phy_reset_n"
    assert fr.qualified_name == "PHY.CTRL0.phy_reset_n"


def test_field_ref_from_dict_rejects_record_with_no_name():
    with pytest.raises(ValueError):
        rt.field_ref_from_dict({"block": "PHY"})
    with pytest.raises(ValueError):
        rt.field_ref_from_dict("not a dict")


def test_field_refs_from_register_map_flattens_blocks_registers_fields():
    doc = {
        "schema_version": "1.0",
        "blocks": [
            {
                "name": "PHY", "base_address": "0x1000",
                "registers": [
                    {
                        "name": "CTRL0", "address_offset": "0x0", "width": 32, "access": "RW",
                        "fields": [
                            {"name": "phy_reset_n", "bit_offset": 0, "bit_width": 1, "access": "RW"},
                            {"name": "phy_mode_sel", "bit_offset": 1, "bit_width": 1, "access": "RW"},
                        ],
                    }
                ],
            }
        ],
    }
    refs = rt.field_refs_from_register_map(doc)
    assert [r.name for r in refs] == ["phy_reset_n", "phy_mode_sel"]
    assert refs[0].block_name == "PHY"
    assert refs[0].register_name == "CTRL0"


def test_field_refs_from_register_map_on_empty_blocks_returns_empty_list():
    assert rt.field_refs_from_register_map({"schema_version": "1.0", "blocks": []}) == []


# --- core positive path: TRACE_CONFIRMED -------------------------------------

@requires_verible
def test_trace_confirms_a_port_wired_to_internal_logic(clean_sv):
    result = parse_file(clean_sv)
    fr = rt.field_ref_from_dict({"name": "phy_reset_n"})
    tr = rt.trace_register_field(fr, [result])
    assert tr.status == rt.TRACE_CONFIRMED
    assert tr.candidates[0].site.kind == "port"
    assert tr.candidates[0].site.module_name == "phy_ctrl"
    assert "elaboration-time behavior" in tr.reason


@requires_verible
def test_trace_confirms_an_internal_signal_referenced_in_an_assign(clean_sv):
    result = parse_file(clean_sv)
    fr = rt.field_ref_from_dict({"name": "link_up"})
    tr = rt.trace_register_field(fr, [result])
    assert tr.status == rt.TRACE_CONFIRMED
    assert tr.candidates[0].site.kind == "signal"
    assert tr.candidates[0].site.referenced is True


@requires_verible
def test_trace_confirms_a_port_wired_only_through_an_instance_connection(clean_sv):
    # phy_mode_sel never appears in a continuous assign -- its only real
    # wiring is as the actual net connected to sub_block's `mode_sel` port.
    result = parse_file(clean_sv)
    fr = rt.field_ref_from_dict({"name": "phy_mode_sel"})
    tr = rt.trace_register_field(fr, [result])
    assert tr.status == rt.TRACE_CONFIRMED


@requires_verible
def test_rtl_signal_hint_is_tried_before_the_field_name(clean_sv):
    # The field's own declared name ("reset_control") appears nowhere in the
    # RTL; the document-stated hint ("phy_reset_n") does and is CONFIRMED.
    result = parse_file(clean_sv)
    fr = rt.field_ref_from_dict({"name": "reset_control", "rtl_signal_hint": "phy_reset_n"})
    tr = rt.trace_register_field(fr, [result])
    assert tr.status == rt.TRACE_CONFIRMED
    assert tr.searched_name == "phy_reset_n"


# --- negative control 1: a port declared but never internally referenced
# still counts as CONFIRMED (a port IS the external connection point by
# definition) -- proven separately from the bare-signal negative control
# below, since the two must not be conflated.

@requires_verible
def test_an_unreferenced_port_is_still_confirmed_because_it_is_a_boundary(clean_sv):
    result = parse_file(clean_sv)
    fr = rt.field_ref_from_dict({"name": "irq_mask_ack"})
    tr = rt.trace_register_field(fr, [result])
    assert tr.status == rt.TRACE_CONFIRMED
    assert tr.candidates[0].site.kind == "port"


# --- negative control 2: an exact-name-matching but UNREFERENCED internal
# signal must NEVER be upgraded to TRACE_CONFIRMED.

@requires_verible
def test_exact_match_on_a_bare_unused_signal_is_partial_never_confirmed(clean_sv):
    result = parse_file(clean_sv)
    fr = rt.field_ref_from_dict({"name": "dead_reg"})
    tr = rt.trace_register_field(fr, [result])
    assert tr.status == rt.TRACE_PARTIAL
    assert tr.candidates[0].site.referenced is False
    assert "bare, unused declaration" in tr.reason


# --- negative control 3: an exact match across two DIFFERENT modules is
# ambiguous and must NEVER be upgraded to TRACE_CONFIRMED, even though both
# candidates individually look like a clean referenced match.

@requires_verible
def test_exact_match_across_two_modules_is_ambiguous_never_confirmed(clean_sv, ambiguous_sv):
    r1 = parse_file(clean_sv)
    r2 = parse_file(ambiguous_sv)
    fr = rt.field_ref_from_dict({"name": "phy_reset_n"})
    tr = rt.trace_register_field(fr, [r1, r2])
    assert tr.status == rt.TRACE_PARTIAL
    assert len(tr.candidates) == 2
    assert {c.site.module_name for c in tr.candidates} == {"phy_ctrl", "other_block"}
    assert "AMBIGUOUS" in tr.reason


# --- negative control 4: no matching name anywhere -> TRACE_NOT_FOUND, a
# real search that came up empty, distinct from BLOCKED.

@requires_verible
def test_no_matching_name_anywhere_is_not_found(clean_sv):
    result = parse_file(clean_sv)
    fr = rt.field_ref_from_dict({"name": "totally_unrelated_field_xyz"})
    tr = rt.trace_register_field(fr, [result])
    assert tr.status == rt.TRACE_NOT_FOUND
    assert tr.candidates == []


# --- negative control 5: a genuinely absent RTL corpus is BLOCKED, never
# silently reported as TRACE_NOT_FOUND -- "we never looked" must stay
# distinct from "we looked and found nothing" (Evidence Truth Rule).

def test_empty_corpus_is_blocked_not_not_found():
    fr = rt.field_ref_from_dict({"name": "phy_reset_n"})
    tr = rt.trace_register_field(fr, [])
    assert tr.status == rt.TRACE_BLOCKED
    assert "could not be attempted" in tr.reason


def test_field_with_no_name_is_blocked():
    tr = rt.trace_register_field(rt.RegisterFieldRef(name=""), [])
    assert tr.status == rt.TRACE_BLOCKED


# --- negative control 6: a source file verible cannot parse produces a
# named parse warning and, when it is the ONLY source, BLOCKED rather than a
# fabricated NOT_FOUND.

@requires_verible
def test_broken_source_file_yields_parse_warning_and_blocked(broken_sv):
    parsed, warnings = rt.parse_rtl_sources([broken_sv])
    assert parsed == []
    assert len(warnings) == 1
    assert warnings[0]["file_path"] == str(broken_sv)
    assert "VERIBLE_PARSE_ERROR" in warnings[0]["reason"]

    fr = rt.field_ref_from_dict({"name": "phy_reset_n"})
    tr = rt.trace_register_field(fr, parsed, parse_warnings=warnings)
    assert tr.status == rt.TRACE_BLOCKED
    assert "failed to parse" in tr.reason


@requires_verible
def test_one_broken_file_never_blocks_the_other_real_ones(clean_sv, broken_sv):
    parsed, warnings = rt.parse_rtl_sources([clean_sv, broken_sv])
    assert len(parsed) == 1
    assert len(warnings) == 1
    fr = rt.field_ref_from_dict({"name": "phy_reset_n"})
    tr = rt.trace_register_field(fr, parsed, parse_warnings=warnings)
    assert tr.status == rt.TRACE_CONFIRMED


def test_verible_unavailable_binary_is_reported_as_parse_warning(clean_sv):
    parsed, warnings = rt.parse_rtl_sources([clean_sv], verible_bin="definitely-not-a-real-binary")
    assert parsed == []
    assert len(warnings) == 1
    assert "VERIBLE_UNAVAILABLE" in warnings[0]["reason"]


# --- fuzzy match: too-short fragments are never treated as evidence ----------

@requires_verible
def test_short_field_name_does_not_spuriously_fuzzy_match(clean_sv):
    # "en" is far shorter than MIN_FUZZY_MATCH_LEN and appears nowhere as an
    # exact name either -- must be NOT_FOUND, never a spurious fuzzy PARTIAL
    # against unrelated longer signal names that happen to contain "en".
    result = parse_file(clean_sv)
    fr = rt.field_ref_from_dict({"name": "en"})
    tr = rt.trace_register_field(fr, [result])
    assert tr.status == rt.TRACE_NOT_FOUND


@requires_verible
def test_genuine_fuzzy_substring_match_is_partial_not_confirmed(clean_sv):
    # "phy_reset" is a real substring of "phy_reset_n" but not identical to
    # it after normalization -- must report PARTIAL (plausible, ambiguous),
    # never silently treated as the same signal.
    result = parse_file(clean_sv)
    fr = rt.field_ref_from_dict({"name": "phy_reset"})
    tr = rt.trace_register_field(fr, [result])
    assert tr.status == rt.TRACE_PARTIAL
    assert tr.candidates[0].match_kind == "FUZZY"


# --- batch tracing / summary --------------------------------------------------

@requires_verible
def test_trace_register_fields_batches_against_one_built_index(clean_sv):
    result = parse_file(clean_sv)
    refs = [
        rt.field_ref_from_dict({"name": "phy_reset_n"}),      # CONFIRMED
        rt.field_ref_from_dict({"name": "dead_reg"}),         # PARTIAL
        rt.field_ref_from_dict({"name": "nope_xyz"}),         # NOT_FOUND
    ]
    results = rt.trace_register_fields(refs, [result])
    statuses = [r.status for r in results]
    assert statuses == [rt.TRACE_CONFIRMED, rt.TRACE_PARTIAL, rt.TRACE_NOT_FOUND]

    summary = rt.summarize_trace(results)
    assert summary["total"] == 3
    assert summary["counts"][rt.TRACE_CONFIRMED] == 1
    assert summary["counts"][rt.TRACE_PARTIAL] == 1
    assert summary["counts"][rt.TRACE_NOT_FOUND] == 1
    # worst-first: NOT_FOUND outranks PARTIAL and CONFIRMED for exit code.
    assert summary["exit_code"] == rt.STATUS_EXIT_CODE[rt.TRACE_NOT_FOUND]


def test_summarize_trace_on_empty_results_is_exit_code_two():
    summary = rt.summarize_trace([])
    assert summary["total"] == 0
    assert summary["exit_code"] == 2


@requires_verible
def test_summarize_trace_all_confirmed_is_exit_code_zero(clean_sv):
    result = parse_file(clean_sv)
    refs = [rt.field_ref_from_dict({"name": "phy_reset_n"}),
            rt.field_ref_from_dict({"name": "link_up"})]
    results = rt.trace_register_fields(refs, [result])
    summary = rt.summarize_trace(results)
    assert summary["exit_code"] == 0


# --- corpus shape flexibility: FileParseResult, to_dict() dicts, and a bare
# module-dict list must all work identically (duck-typed, no isinstance
# coupling to a specific concurrently-developed module's shape) -------------

@requires_verible
def test_corpus_accepts_to_dict_shape(clean_sv):
    from dv_harness.verible_parser import to_dict
    result = parse_file(clean_sv)
    as_dict = to_dict(result)
    fr = rt.field_ref_from_dict({"name": "phy_reset_n"})
    tr = rt.trace_register_field(fr, [as_dict])
    assert tr.status == rt.TRACE_CONFIRMED


@requires_verible
def test_corpus_accepts_a_bare_module_list(clean_sv):
    result = parse_file(clean_sv)
    fr = rt.field_ref_from_dict({"name": "phy_reset_n"})
    tr = rt.trace_register_field(fr, list(result.modules))
    assert tr.status == rt.TRACE_CONFIRMED


def test_unrecognized_corpus_entries_are_silently_skipped_not_matched():
    fr = rt.field_ref_from_dict({"name": "phy_reset_n"})
    # Neither entry carries a "modules"/"ports"/"signals"/"name" shape.
    tr = rt.trace_register_field(fr, [{"unrelated": True}, 42, "a string"])
    assert tr.status == rt.TRACE_BLOCKED  # collect_rtl_sites() found nothing usable


# --- to_dict() serialization round trip --------------------------------------

@requires_verible
def test_result_to_dict_is_json_serializable(clean_sv):
    result = parse_file(clean_sv)
    fr = rt.field_ref_from_dict({"name": "phy_reset_n", "register": "CTRL0", "block": "PHY"})
    tr = rt.trace_register_field(fr, [result])
    d = tr.to_dict()
    json.dumps(d)  # must not raise
    assert d["status"] == rt.TRACE_CONFIRMED
    assert d["field"] == "PHY.CTRL0.phy_reset_n"
    assert d["candidates"][0]["module"] == "phy_ctrl"


# --- real CLI front door -----------------------------------------------------

@requires_verible
def test_execute_verb_end_to_end_over_a_real_register_map(tmp_path, clean_sv):
    register_map = {
        "schema_version": "1.0",
        "blocks": [
            {
                "name": "PHY", "base_address": "0x1000",
                "registers": [
                    {
                        "name": "CTRL0", "address_offset": "0x0", "width": 32, "access": "RW",
                        "fields": [
                            {"name": "phy_reset_n", "bit_offset": 0, "bit_width": 1, "access": "RW"},
                            {"name": "no_such_signal_xyz", "bit_offset": 1, "bit_width": 1, "access": "RO"},
                        ],
                    }
                ],
            }
        ],
    }
    rmap_path = tmp_path / "register_map.json"
    rmap_path.write_text(json.dumps(register_map), encoding="utf-8")

    text, code = rt.execute_verb(str(rmap_path), [str(clean_sv)], as_json=True)
    payload = json.loads(text)
    statuses = {f["field_name"]: f["status"] for f in payload["fields"]}
    assert statuses["phy_reset_n"] == rt.TRACE_CONFIRMED
    assert statuses["no_such_signal_xyz"] == rt.TRACE_NOT_FOUND
    # NOT_FOUND is present -> worst-first exit code 1, never masked to 0.
    assert code == 1


def test_execute_verb_reports_invalid_register_map_as_exit_two(tmp_path):
    bad_path = tmp_path / "bad_register_map.json"
    bad_path.write_text(json.dumps({"schema_version": "1.0"}), encoding="utf-8")  # missing "blocks"
    text, code = rt.execute_verb(str(bad_path), [])
    assert code == 2
    assert "failed validation" in text


@requires_verible
def test_main_cli_runs_as_a_real_subprocess(tmp_path, clean_sv):
    register_map = {
        "schema_version": "1.0",
        "blocks": [{
            "name": "PHY", "base_address": "0x1000",
            "registers": [{
                "name": "CTRL0", "address_offset": "0x0", "width": 32, "access": "RW",
                "fields": [{"name": "phy_reset_n", "bit_offset": 0, "bit_width": 1, "access": "RW"}],
            }],
        }],
    }
    rmap_path = tmp_path / "register_map.json"
    rmap_path.write_text(json.dumps(register_map), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.register_rtl_trace",
         "--register-map", str(rmap_path), "--rtl", str(clean_sv), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["fields"][0]["status"] == rt.TRACE_CONFIRMED
