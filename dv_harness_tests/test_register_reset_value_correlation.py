"""Tests for dv_harness/register_reset_value_correlation.py -- cross-checking
register_excel_extract.py's documented reset value against
register_rtl_trace.py's real RTL trace + this module's own reset-branch
literal scan.

Same evidence discipline as test_register_rtl_trace.py / test_register_excel_extract.py:
every test that needs a real parse runs the REAL `verible-verilog-syntax`
subprocess and is SKIPPED (never mocked) on a machine without it. Fixtures
are small, synthetic, hand-written RTL/spreadsheets -- never real project
content (Evidence Truth Rule / No Golden-Reference Content Mining).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import openpyxl
import pytest

from dv_harness import register_reset_value_correlation as rrvc
from dv_harness import register_rtl_trace as rt
from dv_harness import register_excel_extract as rex

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None, reason="verible-verilog-syntax not on PATH",
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# parse_verilog_literal
# ---------------------------------------------------------------------------

class TestParseVerilogLiteral:
    def test_sized_hex_literal(self):
        assert rrvc.parse_verilog_literal("8'h00") == (0, None)
        assert rrvc.parse_verilog_literal("8'hFF") == (255, None)

    def test_sized_binary_literal(self):
        assert rrvc.parse_verilog_literal("1'b0") == (0, None)
        assert rrvc.parse_verilog_literal("1'b1") == (1, None)

    def test_sized_decimal_and_octal_literal(self):
        assert rrvc.parse_verilog_literal("32'd10") == (10, None)
        assert rrvc.parse_verilog_literal("8'o17") == (15, None)

    def test_unsized_based_literal(self):
        assert rrvc.parse_verilog_literal("'h2A") == (0x2A, None)

    def test_underscore_grouped_literal(self):
        assert rrvc.parse_verilog_literal("16'hDE_AD") == (0xDEAD, None)

    def test_0x_prefixed_hex(self):
        assert rrvc.parse_verilog_literal("0xAB") == (0xAB, None)

    def test_plain_decimal(self):
        assert rrvc.parse_verilog_literal("42") == (42, None)

    def test_x_bit_is_never_a_guessed_value(self):
        value, err = rrvc.parse_verilog_literal("8'hxx")
        assert value is None
        assert "X/Z" in err

    def test_z_bit_is_never_a_guessed_value(self):
        value, err = rrvc.parse_verilog_literal("1'bz")
        assert value is None
        assert "X/Z" in err

    def test_expression_is_not_a_literal(self):
        value, err = rrvc.parse_verilog_literal("a + b")
        assert value is None
        assert err is not None

    def test_parameter_reference_is_not_a_literal(self):
        value, err = rrvc.parse_verilog_literal("DEFAULT_VAL")
        assert value is None
        assert err is not None

    def test_none_text(self):
        assert rrvc.parse_verilog_literal(None) == (None, "no text supplied")

    def test_empty_text(self):
        value, err = rrvc.parse_verilog_literal("   ")
        assert value is None and err == "empty text"


# ---------------------------------------------------------------------------
# find_rtl_reset_assignments / resolve_rtl_reset_value -- pure, no verible
# ---------------------------------------------------------------------------

ASYNC_RESET_TEXT = textwrap.dedent("""\
    module ctrl (
        input logic clk,
        input logic rst_n
    );
        logic [7:0] ctrl_reg;
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                ctrl_reg <= 8'h00;
            end else begin
                ctrl_reg <= ctrl_reg + 1;
            end
        end
    endmodule
""")

SYNC_RESET_TEXT = textwrap.dedent("""\
    module ctrl (
        input logic clk,
        input logic reset
    );
        logic [7:0] mode_reg;
        always_ff @(posedge clk) begin
            if (reset)
                mode_reg <= 8'h01;
            else
                mode_reg <= mode_reg + 1;
        end
    endmodule
""")

SINGLE_STATEMENT_RESET_TEXT = textwrap.dedent("""\
    module ctrl (
        input logic clk,
        input logic rst_n
    );
        logic [7:0] flag_reg;
        always_ff @(posedge clk or negedge rst_n)
            if (!rst_n) flag_reg <= 8'h00; else flag_reg <= flag_reg + 1;
    endmodule
""")

NO_RESET_BRANCH_TEXT = textwrap.dedent("""\
    module ctrl (
        input logic clk
    );
        logic [7:0] free_reg;
        always_ff @(posedge clk) begin
            free_reg <= free_reg + 1;
        end
    endmodule
""")

UNPARSEABLE_RESET_TEXT = textwrap.dedent("""\
    module ctrl (
        input logic clk,
        input logic rst_n
    );
        logic [7:0] x_reg;
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                x_reg <= 8'hxx;
            end else begin
                x_reg <= x_reg + 1;
            end
        end
    endmodule
""")

AMBIGUOUS_RESET_TEXT = textwrap.dedent("""\
    module ctrl (
        input logic clk,
        input logic rst_n
    );
        logic [7:0] dual_reg;
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                dual_reg <= 8'h00;
            end else begin
                dual_reg <= dual_reg + 1;
            end
        end
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                dual_reg <= 8'h05;
            end else begin
                dual_reg <= dual_reg + 1;
            end
        end
    endmodule
""")

TWO_BLOCKS_ONLY_SECOND_MATCHES = textwrap.dedent("""\
    module ctrl (
        input logic clk,
        input logic rst_n
    );
        logic [7:0] other_reg;
        logic [7:0] target_reg;
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                other_reg <= 8'hAA;
            end else begin
                other_reg <= other_reg + 1;
            end
        end
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                target_reg <= 8'h22;
            end else begin
                target_reg <= target_reg + 1;
            end
        end
    endmodule
""")


class TestFindAndResolveResetAssignments:
    def test_async_reset_found(self):
        assigns = rrvc.find_rtl_reset_assignments(ASYNC_RESET_TEXT, "ctrl_reg", path="f.sv")
        finding = rrvc.resolve_rtl_reset_value(assigns, target_name="ctrl_reg")
        assert finding.status == "FOUND"
        assert finding.value == 0x00
        assert finding.raw_text == "8'h00"
        assert finding.evidence.startswith("f.sv:")

    def test_sync_reset_found(self):
        assigns = rrvc.find_rtl_reset_assignments(SYNC_RESET_TEXT, "mode_reg", path="f.sv")
        finding = rrvc.resolve_rtl_reset_value(assigns, target_name="mode_reg")
        assert finding.status == "FOUND"
        assert finding.value == 0x01

    def test_single_statement_reset_found(self):
        assigns = rrvc.find_rtl_reset_assignments(SINGLE_STATEMENT_RESET_TEXT, "flag_reg", path="f.sv")
        finding = rrvc.resolve_rtl_reset_value(assigns, target_name="flag_reg")
        assert finding.status == "FOUND"
        assert finding.value == 0x00

    def test_no_reset_branch_is_honestly_not_found(self):
        assigns = rrvc.find_rtl_reset_assignments(NO_RESET_BRANCH_TEXT, "free_reg", path="f.sv")
        finding = rrvc.resolve_rtl_reset_value(assigns, target_name="free_reg")
        assert finding.status == "NOT_FOUND"
        assert finding.value is None

    def test_target_never_assigned_anywhere_is_not_found(self):
        assigns = rrvc.find_rtl_reset_assignments(ASYNC_RESET_TEXT, "nonexistent_reg", path="f.sv")
        finding = rrvc.resolve_rtl_reset_value(assigns, target_name="nonexistent_reg")
        assert finding.status == "NOT_FOUND"

    def test_x_bit_reset_value_is_unparseable_never_guessed(self):
        assigns = rrvc.find_rtl_reset_assignments(UNPARSEABLE_RESET_TEXT, "x_reg", path="f.sv")
        finding = rrvc.resolve_rtl_reset_value(assigns, target_name="x_reg")
        assert finding.status == "UNPARSEABLE"
        assert finding.value is None
        assert "x_reg" in finding.reason

    def test_disagreeing_reset_assignments_are_ambiguous_never_resolved_by_picking_one(self):
        assigns = rrvc.find_rtl_reset_assignments(AMBIGUOUS_RESET_TEXT, "dual_reg", path="f.sv")
        finding = rrvc.resolve_rtl_reset_value(assigns, target_name="dual_reg")
        assert finding.status == "AMBIGUOUS"
        assert finding.value is None
        assert len(finding.assignments) == 2

    def test_reset_branch_scan_never_leaks_across_always_blocks(self):
        # other_reg's reset value must never be attributed to target_reg, and
        # vice versa -- proves the window bound between consecutive always
        # blocks is real, not accidental.
        assigns = rrvc.find_rtl_reset_assignments(TWO_BLOCKS_ONLY_SECOND_MATCHES, "target_reg", path="f.sv")
        finding = rrvc.resolve_rtl_reset_value(assigns, target_name="target_reg")
        assert finding.status == "FOUND"
        assert finding.value == 0x22

        assigns_other = rrvc.find_rtl_reset_assignments(TWO_BLOCKS_ONLY_SECOND_MATCHES, "other_reg", path="f.sv")
        finding_other = rrvc.resolve_rtl_reset_value(assigns_other, target_name="other_reg")
        assert finding_other.status == "FOUND"
        assert finding_other.value == 0xAA

    def test_empty_assignment_list_is_not_found(self):
        finding = rrvc.resolve_rtl_reset_value([], target_name="whatever")
        assert finding.status == "NOT_FOUND"
        assert finding.assignments == []


# ---------------------------------------------------------------------------
# compare_reset_values -- pure comparison logic
# ---------------------------------------------------------------------------

class TestCompareResetValues:
    def _found(self, value, raw="8'h00", evidence="f.sv:5"):
        return rrvc.RtlResetValueFinding(
            status="FOUND", value=value, raw_text=raw, evidence=evidence, reason="unambiguous",
        )

    def test_match(self):
        status, reason = rrvc.compare_reset_values(
            0x00, "0x0", self._found(0x00), rt.TRACE_CONFIRMED, "confirmed",
        )
        assert status == rrvc.STATUS_MATCH

    def test_mismatch(self):
        status, reason = rrvc.compare_reset_values(
            0x01, "0x1", self._found(0x00), rt.TRACE_CONFIRMED, "confirmed",
        )
        assert status == rrvc.STATUS_MISMATCH
        assert "disagrees" in reason

    def test_no_documented_value_is_unknown(self):
        status, reason = rrvc.compare_reset_values(
            None, None, self._found(0x00), rt.TRACE_CONFIRMED, "confirmed",
        )
        assert status == rrvc.STATUS_UNKNOWN
        assert "no documented reset value" in reason

    def test_trace_blocked_is_unknown(self):
        status, reason = rrvc.compare_reset_values(
            0x00, "0x0", None, rt.TRACE_BLOCKED, "no parsed RTL modules were supplied",
        )
        assert status == rrvc.STATUS_UNKNOWN
        assert "could not be attempted" in reason

    def test_trace_not_confirmed_is_unknown(self):
        status, reason = rrvc.compare_reset_values(
            0x00, "0x0", None, rt.TRACE_NOT_FOUND, "no match found",
        )
        assert status == rrvc.STATUS_UNKNOWN
        assert rt.TRACE_NOT_FOUND in reason

    def test_confirmed_trace_but_no_span_is_unknown(self):
        status, reason = rrvc.compare_reset_values(
            0x00, "0x0", None, rt.TRACE_CONFIRMED, "confirmed",
        )
        assert status == rrvc.STATUS_UNKNOWN
        assert "module source span" in reason

    def test_confirmed_trace_but_rtl_finding_not_found_is_unknown(self):
        not_found = rrvc.RtlResetValueFinding(
            status="NOT_FOUND", value=None, raw_text=None, evidence=None, reason="nothing found",
        )
        status, reason = rrvc.compare_reset_values(
            0x00, "0x0", not_found, rt.TRACE_CONFIRMED, "confirmed",
        )
        assert status == rrvc.STATUS_UNKNOWN
        assert "NOT_FOUND" in reason


# ---------------------------------------------------------------------------
# End-to-end: real openpyxl spreadsheet + real verible-parsed RTL
# ---------------------------------------------------------------------------

HEADERS = ["Register Name", "Offset", "Width", "Access", "Reset Value", "Notes"]


def _write_xlsx(path: Path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for row in rows:
        ws.append(row)
    wb.save(path)


@pytest.fixture()
def clean_xlsx(tmp_path):
    p = tmp_path / "regs.xlsx"
    _write_xlsx(p, [
        ["CTRL_REG", "0x10", 8, "RW", "0x0", "matches RTL"],
        ["MODE_REG", "0x14", 8, "RW", "0x3", "documents 0x3, RTL resets to 0x1 -- mismatch"],
        ["STATUS_REG", "0x18", 8, "RO", None, "no documented reset value"],
        ["GHOST_REG", "0x1C", 8, "RO", "0x5", "no matching RTL signal anywhere"],
    ])
    return p


@pytest.fixture()
def rtl_file(tmp_path):
    # ctrl_reg/mode_reg are internal signals, so each needs a real continuous
    # assign (a register-readback path, the same pattern
    # test_register_rtl_trace.py's own CLEAN_RTL fixture uses for `link_up`)
    # to be REFERENCED per register_rtl_trace.collect_rtl_sites() -- a bare
    # declaration with no continuous-assign/instance-connection reference
    # stays TRACE_PARTIAL there, never TRACE_CONFIRMED.
    p = tmp_path / "regs.sv"
    p.write_text(textwrap.dedent("""\
        module reg_block (
            input logic clk,
            input logic rst_n,
            output logic [7:0] ctrl_reg_rdata,
            output logic [7:0] mode_reg_rdata
        );
            logic [7:0] ctrl_reg;
            logic [7:0] mode_reg;

            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    ctrl_reg <= 8'h00;
                end else begin
                    ctrl_reg <= ctrl_reg + 1;
                end
            end

            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    mode_reg <= 8'h01;
                end else begin
                    mode_reg <= mode_reg + 1;
                end
            end

            assign ctrl_reg_rdata = ctrl_reg;
            assign mode_reg_rdata = mode_reg;
        endmodule
    """), encoding="utf-8")
    return p


@requires_verible
class TestEndToEndCorrelation:
    def test_full_report_covers_match_mismatch_and_unknown_honestly(self, clean_xlsx, rtl_file):
        extraction = rex.extract_register_map(clean_xlsx)
        assert extraction.status == rex.STATUS_OK, extraction.reason

        report = rrvc.correlate_register_map_reset_values(
            extraction.registers, [rtl_file], include_fields=False,
        )
        by_name = {r["register_name"]: r for r in report["results"]}

        assert by_name["CTRL_REG"]["status"] == rrvc.STATUS_MATCH
        assert by_name["CTRL_REG"]["rtl_finding"]["value"] == "0x0"

        assert by_name["MODE_REG"]["status"] == rrvc.STATUS_MISMATCH
        assert by_name["MODE_REG"]["documented_reset_value"] == "0x3"
        assert by_name["MODE_REG"]["rtl_finding"]["value"] == "0x1"

        assert by_name["STATUS_REG"]["status"] == rrvc.STATUS_UNKNOWN
        assert "no documented reset value" in by_name["STATUS_REG"]["reason"]

        assert by_name["GHOST_REG"]["status"] == rrvc.STATUS_UNKNOWN
        assert by_name["GHOST_REG"]["trace_status"] == rt.TRACE_NOT_FOUND

        assert report["summary"][rrvc.STATUS_MATCH] == 1
        assert report["summary"][rrvc.STATUS_MISMATCH] == 1
        assert report["summary"][rrvc.STATUS_UNKNOWN] == 2

    def test_no_rtl_paths_at_all_reports_unknown_never_a_fabricated_match(self, clean_xlsx):
        # The mandatory negative control: absent RTL evidence must never be
        # silently read as a MATCH (or a MISMATCH) -- it is BLOCKED at the
        # trace layer, and this module reports that honestly as UNKNOWN.
        extraction = rex.extract_register_map(clean_xlsx)
        report = rrvc.correlate_register_map_reset_values(
            extraction.registers, [], include_fields=False,
        )
        for r in report["results"]:
            if r["register_name"] == "STATUS_REG":
                continue  # no documented value at all -- a different UNKNOWN reason
            assert r["status"] == rrvc.STATUS_UNKNOWN
            assert r["trace_status"] == rt.TRACE_BLOCKED
        assert report["summary"][rrvc.STATUS_MATCH] == 0
        assert report["summary"][rrvc.STATUS_MISMATCH] == 0

    def test_module_source_spans_real_span_and_text(self, rtl_file):
        spans, err = rrvc.module_source_spans(rtl_file)
        assert err is None
        assert len(spans) == 1
        assert spans[0].module_name == "reg_block"
        assert "ctrl_reg" in spans[0].text
        assert spans[0].base_line == 1

    def test_ambiguous_trace_is_reported_unknown(self, tmp_path):
        # Two modules each declaring a signal that normalizes to the same
        # name -- register_rtl_trace.py's own TRACE_PARTIAL ambiguity.
        p1 = tmp_path / "a.sv"
        p1.write_text(textwrap.dedent("""\
            module mod_a (input logic clk, input logic rst_n, output logic [7:0] dup_reg_rdata);
                logic [7:0] dup_reg;
                always_ff @(posedge clk or negedge rst_n) begin
                    if (!rst_n) dup_reg <= 8'h00; else dup_reg <= dup_reg + 1;
                end
                assign dup_reg_rdata = dup_reg;
            endmodule
        """), encoding="utf-8")
        p2 = tmp_path / "b.sv"
        p2.write_text(textwrap.dedent("""\
            module mod_b (input logic clk, input logic rst_n, output logic [7:0] dup_reg_rdata);
                logic [7:0] dup_reg;
                always_ff @(posedge clk or negedge rst_n) begin
                    if (!rst_n) dup_reg <= 8'h00; else dup_reg <= dup_reg + 1;
                end
                assign dup_reg_rdata = dup_reg;
            endmodule
        """), encoding="utf-8")
        parsed, warnings = rt.parse_rtl_sources([p1, p2])
        sites = rt.collect_rtl_sites(parsed)
        span_index, span_warnings = rrvc.build_module_span_index([p1, p2])
        result = rrvc.correlate_register_reset_value(
            "dup_reg", 0x00, "0x0",
            register_name="DUP_REG", sites=sites, span_index=span_index,
        )
        assert result.status == rrvc.STATUS_UNKNOWN
        assert result.trace_status == rt.TRACE_PARTIAL

    def test_fields_are_correlated_too(self, tmp_path):
        xlsx = tmp_path / "fields.xlsx"
        wb_headers = ["Register Name", "Offset", "Width", "Access", "Reset Value",
                      "Field Name", "Bits", "Field Access", "Field Reset", "Notes"]
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(wb_headers)
        ws.append(["CFG_REG", "0x20", 8, "RW", "0x0", None, None, None, None, None])
        ws.append([None, None, None, None, None, "ena_bit", "[0]", "RW", "0x1", "enable"])
        wb.save(xlsx)

        rtl = tmp_path / "field.sv"
        rtl.write_text(textwrap.dedent("""\
            module cfg_block (
                input logic clk,
                input logic rst_n,
                output logic [7:0] cfg_reg_rdata,
                output logic ena_bit_rdata
            );
                logic [7:0] cfg_reg;
                logic ena_bit;
                always_ff @(posedge clk or negedge rst_n) begin
                    if (!rst_n) begin
                        cfg_reg <= 8'h00;
                        ena_bit <= 1'b1;
                    end else begin
                        cfg_reg <= cfg_reg + 1;
                        ena_bit <= ena_bit;
                    end
                end
                assign cfg_reg_rdata = cfg_reg;
                assign ena_bit_rdata = ena_bit;
            endmodule
        """), encoding="utf-8")

        extraction = rex.extract_register_map(xlsx)
        assert extraction.status == rex.STATUS_OK, extraction.reason
        report = rrvc.correlate_register_map_reset_values(
            extraction.registers, [rtl], include_fields=True,
        )
        by_field = {(r["register_name"], r["field_name"]): r for r in report["results"]}
        assert by_field[("CFG_REG", None)]["status"] == rrvc.STATUS_MATCH
        assert by_field[("CFG_REG", "ena_bit")]["status"] == rrvc.STATUS_MATCH
        assert by_field[("CFG_REG", "ena_bit")]["documented_reset_value"] == "0x1"


# ---------------------------------------------------------------------------
# module_source_spans / build_module_span_index -- honest failure paths
# ---------------------------------------------------------------------------

class TestModuleSourceSpanFailures:
    def test_missing_file(self, tmp_path):
        spans, err = rrvc.module_source_spans(tmp_path / "nope.sv")
        assert spans == []
        assert "could not read file" in err

    @requires_verible
    def test_syntax_error_reported_not_swallowed(self, tmp_path):
        p = tmp_path / "broken.sv"
        p.write_text("module broken( ; ; ; not valid\n", encoding="utf-8")
        spans, err = rrvc.module_source_spans(p)
        assert spans == []
        assert err is not None

    def test_unrunnable_verible_binary(self, tmp_path):
        p = tmp_path / "ok.sv"
        p.write_text("module m; endmodule\n", encoding="utf-8")
        spans, err = rrvc.module_source_spans(p, verible_bin="definitely-not-a-real-binary")
        assert spans == []
        assert "verible could not be run" in err

    def test_build_index_collects_warnings_and_keeps_going(self, tmp_path):
        good = tmp_path / "good.sv"
        good.write_text("module m; endmodule\n", encoding="utf-8")
        index, warnings = rrvc.build_module_span_index(
            [good, tmp_path / "missing.sv"], verible_bin="definitely-not-a-real-binary",
        )
        assert index == {}
        assert len(warnings) == 2


# ---------------------------------------------------------------------------
# CLI front door -- `python -m dv_harness.register_reset_value_correlation`
# ---------------------------------------------------------------------------

@requires_verible
class TestCli:
    def test_cli_reports_mismatch_and_exits_1(self, clean_xlsx, rtl_file):
        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness.register_reset_value_correlation",
             "--register-source", str(clean_xlsx), "--rtl", str(rtl_file), "--json"],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert '"MISMATCH"' in proc.stdout

    def test_cli_missing_register_source_exits_2(self, tmp_path, rtl_file):
        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness.register_reset_value_correlation",
             "--register-source", str(tmp_path / "nope.xlsx"), "--rtl", str(rtl_file)],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        assert proc.returncode == 2

    def test_cli_clean_workbook_no_mismatch_exits_0(self, tmp_path, rtl_file):
        clean_only = tmp_path / "clean_only.xlsx"
        _write_xlsx(clean_only, [
            ["CTRL_REG", "0x10", 8, "RW", "0x0", "matches"],
        ])
        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness.register_reset_value_correlation",
             "--register-source", str(clean_only), "--rtl", str(rtl_file), "--json"],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert '"MATCH"' in proc.stdout
