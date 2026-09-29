"""Tests for dv_harness/rtl_control_flow_extraction.py -- bounded,
disclosed-scope control-flow / combinational-vs-sequential logic-intent
extraction over always-block bodies.

Two independent kinds of test, mirroring test_design_architecture_ir.py's
own discipline:

  1. The always-block classification + if/else-if chain + case-shape scan
     (`extract_control_flow_facts()`) is a PURE function over plain text --
     no verible dependency at all -- so it is unit-tested directly against
     hand-written SystemVerilog snippets, never mocked.
  2. Everything that needs real module boundaries (`parse_rtl_file()` /
     `build_control_flow_ir()`, and the CLI) runs the REAL
     `verible-verilog-syntax` subprocess against real files written to
     `tmp_path`, and is SKIPPED (never faked) on a machine without it on
     PATH.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dv_harness import rtl_control_flow_extraction as cfe

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

ROOT = Path(__file__).resolve().parents[1]


def _blocks(text: str):
    return cfe.extract_control_flow_facts(text, "m", base_line=1)


# ---------------------------------------------------------------------------
# 1. Pure-function tests (no verible needed)
# ---------------------------------------------------------------------------

def test_no_always_block_is_honest_not_available_never_fabricated():
    """The required negative control: a module with no procedural block at
    all must report NOT_AVAILABLE with a real reason, never a fabricated
    CONTROL_FLOW_EXTRACTED with a silently-empty block list read as 'no
    control flow found here'."""
    summary = cfe._module_control_flow_summary(_blocks("assign y = a & b;\n"))
    assert summary["status"] == "NOT_AVAILABLE"
    assert summary["reason"]
    assert summary["blocks"] == []


def test_sequential_posedge_with_complete_case_and_if_else_no_findings():
    text = textwrap.dedent("""\
        reg [1:0] state;
        always @(posedge clk or negedge rst_n) begin
          if (!rst_n) begin
            state <= 2'd0;
          end else begin
            case (state)
              IDLE: state <= BUSY;
              BUSY: state <= DONE;
              default: state <= IDLE;
            endcase
          end
        end
        """)
    blocks = _blocks(text)
    assert len(blocks) == 1
    b = blocks[0]
    assert b["block_kind"] == "SEQUENTIAL"
    assert b["block_kind_reason"] is None
    assert b["if_chain"]["branch_count"] == 1
    assert b["if_chain"]["has_terminal_else"] is True
    assert b["case_shape"]["present"] is True
    assert b["case_shape"]["has_default"] is True
    assert b["findings"] == []


def test_sequential_if_chain_with_no_terminal_else_is_informational_finding():
    text = textwrap.dedent("""\
        always @(posedge clk) begin
          if (load)
            q <= d;
          else if (clear)
            q <= 0;
        end
        """)
    b = _blocks(text)[0]
    assert b["block_kind"] == "SEQUENTIAL"
    assert b["if_chain"]["branch_count"] == 2
    assert b["if_chain"]["has_terminal_else"] is False
    assert len(b["findings"]) == 1
    assert b["findings"][0]["finding"] == "PRIORITY_STRUCTURE_NO_TERMINAL_ELSE"


def test_combinational_always_comb_incomplete_if_is_latch_risk_candidate():
    text = textwrap.dedent("""\
        always_comb begin
          if (sel)
            y = a;
        end
        """)
    b = _blocks(text)[0]
    assert b["block_kind"] == "COMBINATIONAL"
    assert b["if_chain"]["has_terminal_else"] is False
    assert len(b["findings"]) == 1
    assert b["findings"][0]["finding"] == "LATCH_INFERENCE_RISK_CANDIDATE"


def test_combinational_always_comb_complete_if_else_no_finding():
    text = textwrap.dedent("""\
        always_comb begin
          if (sel)
            y = a;
          else
            y = b;
        end
        """)
    b = _blocks(text)[0]
    assert b["block_kind"] == "COMBINATIONAL"
    assert b["if_chain"]["has_terminal_else"] is True
    assert b["findings"] == []


def test_combinational_case_without_default_is_latch_risk_candidate():
    text = textwrap.dedent("""\
        always @(*) begin
          case (sel)
            2'b00: y = a;
            2'b01: y = b;
          endcase
        end
        """)
    b = _blocks(text)[0]
    assert b["block_kind"] == "COMBINATIONAL"
    assert b["case_shape"]["has_default"] is False
    findings = [f["finding"] for f in b["findings"]]
    assert findings == ["LATCH_INFERENCE_RISK_CANDIDATE"]


def test_combinational_case_with_default_no_finding():
    text = textwrap.dedent("""\
        always @(*) begin
          case (sel)
            2'b00: y = a;
            default: y = b;
          endcase
        end
        """)
    b = _blocks(text)[0]
    assert b["case_shape"]["has_default"] is True
    assert b["findings"] == []


def test_star_paren_sensitivity_is_combinational():
    b = _blocks("always @(*) begin y = a; end\n")[0]
    assert b["block_kind"] == "COMBINATIONAL"
    assert b["block_kind_reason"] is None


def test_plain_signal_list_sensitivity_no_edge_is_combinational():
    b = _blocks("always @(a or b) begin y = a & b; end\n")[0]
    assert b["block_kind"] == "COMBINATIONAL"


def test_always_ff_with_posedge_is_sequential_no_reason():
    b = _blocks("always_ff @(posedge clk) q <= d;\n")[0]
    assert b["block_kind"] == "SEQUENTIAL"
    assert b["block_kind_reason"] is None


def test_always_latch_explicit_never_produces_a_risk_finding():
    text = textwrap.dedent("""\
        always_latch begin
          if (en)
            q = d;
        end
        """)
    b = _blocks(text)[0]
    assert b["block_kind"] == "LATCH_EXPLICIT"
    assert b["if_chain"]["has_terminal_else"] is False
    # An explicit always_latch is not a candidate for a latch-inference
    # finding -- the design already declared the latch on purpose.
    assert b["findings"] == []


def test_no_sensitivity_clause_is_honestly_unclassified_never_guessed():
    b = _blocks("always #5 clk = ~clk;\n")[0]
    assert b["block_kind"] == "UNCLASSIFIED_SENSITIVITY"
    assert b["block_kind_reason"]
    # No finding is ever fabricated for a block whose own kind this scan
    # could not classify -- the negative control this task is graded on.
    assert b["findings"] == []


def test_comment_and_string_noise_does_not_corrupt_the_scan():
    text = textwrap.dedent("""\
        always_comb begin
          // an else lurking in a comment: if (x) y = 1; else y = 2;
          s = "if (fake) else fake";
          if (sel)
            y = a;
        end
        """)
    b = _blocks(text)[0]
    assert b["block_kind"] == "COMBINATIONAL"
    assert b["if_chain"]["branch_count"] == 1
    assert b["if_chain"]["has_terminal_else"] is False
    assert len(b["findings"]) == 1


def test_nested_if_inside_then_branch_is_not_folded_into_outer_chain():
    text = textwrap.dedent("""\
        always_comb begin
          if (a) begin
            if (b)
              y = 1;
            else
              y = 2;
          end else begin
            y = 3;
          end
        end
        """)
    b = _blocks(text)[0]
    # The OUTER chain (if a ... else ...) is depth-0; it must report exactly
    # 1 branch (the outer 'if') plus its own terminal else -- the nested
    # if/else inside the then-branch must never inflate branch_count.
    assert b["if_chain"]["branch_count"] == 1
    assert b["if_chain"]["has_terminal_else"] is True
    assert b["findings"] == []


def test_three_branch_if_elseif_elseif_no_terminal_else():
    text = textwrap.dedent("""\
        always_comb begin
          if (a)
            y = 1;
          else if (b)
            y = 2;
          else if (c)
            y = 3;
        end
        """)
    b = _blocks(text)[0]
    assert b["if_chain"]["branch_count"] == 3
    assert b["if_chain"]["has_terminal_else"] is False


def test_case_missing_endcase_is_unparseable_never_fabricated_default():
    text = textwrap.dedent("""\
        always @(*) begin
          case (sel)
            2'b00: y = a;
        end
        """)
    b = _blocks(text)[0]
    assert b["case_shape"]["status"] == "UNPARSEABLE"
    assert b["case_shape"]["has_default"] is None
    # An unparseable case must never be silently treated as "no default
    # found" and turned into a fabricated finding.
    assert b["findings"] == []


def test_block_with_neither_if_nor_case_reports_none_shape_no_findings():
    b = _blocks("always_comb begin y = a & b; end\n")[0]
    assert b["if_chain"] is None
    assert b["case_shape"]["present"] is False
    assert b["case_shape"]["status"] == "NOT_APPLICABLE"
    assert b["findings"] == []


def test_module_summary_extracted_when_at_least_one_block_found():
    summary = cfe._module_control_flow_summary(
        _blocks("always_comb begin y = a; end\n"))
    assert summary["status"] == "CONTROL_FLOW_EXTRACTED"
    assert len(summary["blocks"]) == 1


def test_always_ff_without_edge_in_sensitivity_trusts_keyword_with_reason():
    # Deliberately malformed-looking sensitivity to exercise the disclosed
    # keyword-vs-evidence disagreement path.
    b = _blocks("always_ff @(clk) q <= d;\n")[0]
    assert b["block_kind"] == "SEQUENTIAL"
    assert b["block_kind_reason"] is not None


# ---------------------------------------------------------------------------
# 2. Real-verible integration tests
# ---------------------------------------------------------------------------

@requires_verible
def test_parse_rtl_file_real_module_span_and_line_numbers(tmp_path):
    src = tmp_path / "dut.sv"
    src.write_text(textwrap.dedent("""\
        module dut(input clk, input sel, input a, input b, output reg y);
          always @(*) begin
            if (sel)
              y = a;
          end
        endmodule
        """), encoding="utf-8")
    result = cfe.parse_rtl_file(src, verible_bin=VERIBLE_BIN)
    assert result["status"] == "PARSED"
    assert len(result["modules"]) == 1
    mod = result["modules"][0]
    assert mod["name"] == "dut"
    cf = mod["control_flow_extraction"]
    assert cf["status"] == "CONTROL_FLOW_EXTRACTED"
    blk = cf["blocks"][0]
    assert blk["block_kind"] == "COMBINATIONAL"
    assert blk["findings"][0]["finding"] == "LATCH_INFERENCE_RISK_CANDIDATE"
    # base_line must be relative to the REAL file, not the sliced text.
    assert blk["always_line"] == 2


@requires_verible
def test_build_control_flow_ir_isolates_one_real_syntax_error(tmp_path):
    good = tmp_path / "good.sv"
    good.write_text(textwrap.dedent("""\
        module good(input clk, input a, output reg y);
          always @(posedge clk) y <= a;
        endmodule
        """), encoding="utf-8")
    bad = tmp_path / "bad.sv"
    bad.write_text("module bad( this is not valid systemverilog ;;;\n", encoding="utf-8")
    ir = cfe.build_control_flow_ir([good, bad], verible_bin=VERIBLE_BIN)
    assert ir["status"] == "BUILT"
    statuses = {pf["file_path"]: pf["status"] for pf in ir["files"]}
    assert statuses[str(good)] == "PARSED"
    assert statuses[str(bad)] == "PARSE_ERROR"


@requires_verible
def test_save_control_flow_ir_round_trips(tmp_path):
    src = tmp_path / "dut.sv"
    src.write_text("module dut(input clk, output reg y); always @(posedge clk) y <= 1; endmodule\n",
                    encoding="utf-8")
    ir = cfe.build_control_flow_ir([src], verible_bin=VERIBLE_BIN)
    out = tmp_path / "ir.json"
    cfe.save_control_flow_ir(ir, out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["status"] == "BUILT"


@requires_verible
def test_execute_verb_text_and_json(tmp_path):
    src = tmp_path / "dut.sv"
    src.write_text("module dut(input clk, output reg y); always @(posedge clk) y <= 1; endmodule\n",
                    encoding="utf-8")
    text, code = cfe.execute_verb([src], verible_bin=VERIBLE_BIN, as_json=False)
    assert code == 0
    assert "dut" in text
    js, code2 = cfe.execute_verb([src], verible_bin=VERIBLE_BIN, as_json=True)
    assert code2 == 0
    parsed = json.loads(js)
    assert parsed["status"] == "BUILT"


def test_execute_verb_no_files_exits_2():
    text, code = cfe.execute_verb([])
    assert code == 2
    assert "NOT_AVAILABLE" in text


def test_unreadable_file_reports_not_available(tmp_path):
    missing = tmp_path / "does_not_exist.sv"
    result = cfe.parse_rtl_file(missing)
    assert result["status"] == "NOT_AVAILABLE"


def test_unrunnable_verible_binary_reports_not_available(tmp_path):
    src = tmp_path / "dut.sv"
    src.write_text("module dut(); endmodule\n", encoding="utf-8")
    result = cfe.parse_rtl_file(src, verible_bin="verible-verilog-syntax-does-not-exist")
    assert result["status"] == "NOT_AVAILABLE"


@requires_verible
def test_cli_subprocess_json_and_out_file(tmp_path):
    src = tmp_path / "dut.sv"
    src.write_text(textwrap.dedent("""\
        module dut(input clk, input sel, input a, output reg y);
          always_comb begin
            if (sel)
              y = a;
          end
        endmodule
        """), encoding="utf-8")
    out = tmp_path / "ir.json"
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.rtl_control_flow_extraction",
         "--rtl", str(src), "--out", str(out), "--json"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "BUILT"
    assert out.exists()
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["status"] == "BUILT"


def test_cli_subprocess_no_files_is_a_required_argument_error():
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.rtl_control_flow_extraction"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "--rtl" in proc.stderr
