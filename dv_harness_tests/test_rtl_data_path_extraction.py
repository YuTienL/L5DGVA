"""Tests for dv_harness/rtl_data_path_extraction.py -- bounded, disclosed-
scope data-path extraction (which signals feed which combinational/
sequential logic) over verible-parsed continuous-assign and always-block
sources.

Two independent kinds of test, mirroring test_rtl_control_flow_extraction.py's
own discipline:

  1. The always-block assignment scan (`extract_always_block_data_path()`)
     and the continuous-assign fact builder
     (`extract_continuous_assign_data_path()`) are PURE functions over plain
     text/dicts -- no verible dependency at all -- so they are unit-tested
     directly against hand-written SystemVerilog snippets and hand-built
     verible-shaped dicts, never mocked.
  2. Everything that needs real module boundaries (`parse_rtl_file()` /
     `build_data_path_ir()`, and the CLI) runs the REAL
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

from dv_harness import rtl_data_path_extraction as dpe

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

ROOT = Path(__file__).resolve().parents[1]


def _blocks(text: str, **kw):
    return dpe.extract_always_block_data_path(text, "m", **kw)


# ---------------------------------------------------------------------------
# 1a. Continuous-assign data path (verible's own already-parsed fact, no
#     text scanning at all)
# ---------------------------------------------------------------------------

def test_continuous_assign_fact_reuses_verible_lhs_rhs_nets_verbatim():
    facts = dpe.extract_continuous_assign_data_path([
        {"lhs_text": "y", "rhs_text": "a & b", "lhs_nets": ["y"], "rhs_nets": ["a", "b"]},
    ])
    assert len(facts) == 1
    f = facts[0]
    assert f["kind"] == "CONTINUOUS_ASSIGN"
    assert f["evidence_source"] == "VERIBLE_PARSED_TREE"
    assert f["block_kind"] == "COMBINATIONAL"
    assert f["operator"] == "CONTINUOUS"
    assert f["targets"] == ["y"]
    assert f["sources"] == ["a", "b"]
    assert f["lhs_text"] == "y"
    assert f["rhs_text"] == "a & b"


def test_continuous_assign_no_facts_reports_empty_list_never_fabricated():
    assert dpe.extract_continuous_assign_data_path([]) == []


# ---------------------------------------------------------------------------
# 1b. Always-block assignment scan (pure function, no verible needed)
# ---------------------------------------------------------------------------

def test_no_always_block_and_no_continuous_assign_is_honest_not_available():
    """The required negative control: with no data-path evidence at all,
    the module refuses to fabricate an answer -- NOT_AVAILABLE with a real
    reason, never a fabricated DATA_PATH_EXTRACTED with a silently empty
    fact list read as 'no data path here'."""
    summary = dpe._module_data_path_summary([], _blocks("integer i;\n"))
    assert summary["status"] == "NOT_AVAILABLE"
    assert summary["reason"]
    assert summary["facts"] == []


def test_combinational_simple_assignment_target_and_sources():
    blocks = _blocks("always_comb begin y = a & b; end\n")
    assert len(blocks) == 1
    b = blocks[0]
    assert b["block_kind"] == "COMBINATIONAL"
    assert b["status"] == "ASSIGNMENTS_FOUND"
    assert len(b["assignments"]) == 1
    a0 = b["assignments"][0]
    assert a0["operator"] == "BLOCKING"
    assert a0["targets"] == ["y"]
    assert a0["sources"] == ["a", "b"]
    assert a0["kind"] == "PROCEDURAL_ASSIGNMENT"
    assert a0["evidence_source"] == "LITERAL_SCAN"


def test_sequential_nonblocking_assignment():
    blocks = _blocks("always_ff @(posedge clk) begin q <= d; end\n")
    b = blocks[0]
    assert b["block_kind"] == "SEQUENTIAL"
    a0 = b["assignments"][0]
    assert a0["operator"] == "NONBLOCKING"
    assert a0["targets"] == ["q"]
    assert a0["sources"] == ["d"]


def test_condition_header_comparison_operator_never_read_as_assignment():
    """The headline boundary proof: a comparison operator ('<=') sitting
    inside an if/else-if CONDITION must never be mistaken for a real
    non-blocking assignment statement, and the signals used ONLY inside
    that condition must never leak into the data-path facts of the real
    assignments the block actually contains."""
    text = textwrap.dedent("""\
        always @(posedge clk or negedge rst_n) begin
          if (!rst_n)
            q <= 1'b0;
          else if (a <= b)
            q <= c;
          else
            q <= d;
        end
        """)
    b = _blocks(text)[0]
    assert b["block_kind"] == "SEQUENTIAL"
    assert len(b["assignments"]) == 3
    all_sources = set()
    for a0 in b["assignments"]:
        assert a0["targets"] == ["q"]
        all_sources.update(a0["sources"])
    # 'a' and 'b' are used only inside the "else if (a <= b)" CONDITION --
    # they must never appear as a data-path source of any real assignment.
    assert "a" not in all_sources
    assert "b" not in all_sources
    assert all_sources == {"c", "d"}


def test_for_loop_header_assignment_is_excluded_not_a_data_path_fact():
    text = "always_comb begin for (i = 0; i < 8; i = i + 1) y[i] = a[i]; end\n"
    b = _blocks(text)[0]
    targets = [t for a0 in b["assignments"] for t in a0["targets"]]
    # The loop-index bookkeeping ('i = 0', 'i = i + 1') inside the for(...)
    # header is deliberately excluded (see module docstring); only the real
    # body assignment (y[i] = a[i]) is reported.
    assert "i" not in targets
    assert targets == ["y"]
    a0 = b["assignments"][0]
    assert a0["sources"] == sorted({"a", "i"})


def test_indexed_lvalue_reports_index_expression_as_a_source():
    b = _blocks("always_comb begin mem[i] = data; end\n")[0]
    a0 = b["assignments"][0]
    assert a0["targets"] == ["mem"]
    assert a0["rhs_sources"] == ["data"]
    assert a0["lvalue_index_sources"] == ["i"]
    assert a0["sources"] == sorted({"data", "i"})


def test_concatenation_lvalue_reports_every_target():
    b = _blocks("always_comb begin {carry, sum} = a + b; end\n")[0]
    a0 = b["assignments"][0]
    assert a0["targets"] == ["carry", "sum"]
    assert a0["sources"] == ["a", "b"]


def test_sized_literal_and_system_task_never_read_as_signal_refs():
    b = _blocks("always_comb begin y = 8'hFF & $clog2(WIDTH); end\n")[0]
    a0 = b["assignments"][0]
    assert a0["targets"] == ["y"]
    assert a0["sources"] == ["WIDTH"]
    assert "hFF" not in a0["sources"]
    assert "FF" not in a0["sources"]
    assert "clog2" not in a0["sources"]


def test_block_with_no_recognisable_assignment_is_reported_not_dropped():
    b = _blocks('always @(posedge clk) begin $display("hi"); end\n')[0]
    assert b["block_kind"] == "SEQUENTIAL"
    assert b["assignments"] == []
    assert b["status"] == "NO_ASSIGNMENTS_FOUND_IN_SCAN_WINDOW"


def test_known_signal_names_annotates_unrecognized_never_filters():
    b = _blocks(
        "always_comb begin y = a & c; end\n",
        known_signal_names=frozenset({"a", "b", "y"}),
    )[0]
    a0 = b["assignments"][0]
    # 'c' is not in the known set, but it is still reported as a real source
    # -- known_signal_names only ANNOTATES, it never excludes a reference.
    assert a0["sources"] == ["a", "c"]
    assert a0["sources_unrecognized"] == ["c"]
    assert a0["targets_unrecognized"] == []


def test_known_signal_names_omitted_leaves_unrecognized_fields_none():
    """Absence of a known-name cross-check must never be silently read as
    'checked and found nothing unrecognized' -- it is honestly None."""
    b = _blocks("always_comb begin y = a; end\n")[0]
    a0 = b["assignments"][0]
    assert a0["targets_unrecognized"] is None
    assert a0["sources_unrecognized"] is None


def test_comment_and_string_noise_does_not_corrupt_the_scan():
    text = textwrap.dedent("""\
        always_comb begin
          // a fake condition lurking in a comment: if (x <= y) z = 1;
          s = "if (fake <= fake) fake = 2";
          y = a;
        end
        """)
    b = _blocks(text)[0]
    targets = {t for a0 in b["assignments"] for t in a0["targets"]}
    assert "z" not in targets
    assert "fake" not in targets
    assert {"s", "y"} <= targets


def test_multiple_always_blocks_scanned_independently():
    text = textwrap.dedent("""\
        always_comb begin
          y = a & b;
        end
        always_ff @(posedge clk) begin
          q <= y;
        end
        """)
    blocks = _blocks(text)
    assert len(blocks) == 2
    assert blocks[0]["block_kind"] == "COMBINATIONAL"
    assert blocks[0]["assignments"][0]["targets"] == ["y"]
    assert blocks[1]["block_kind"] == "SEQUENTIAL"
    assert blocks[1]["assignments"][0]["sources"] == ["y"]


def test_module_summary_extracted_when_at_least_one_fact_found():
    summary = dpe._module_data_path_summary(
        [], _blocks("always_comb begin y = a; end\n"))
    assert summary["status"] == "DATA_PATH_EXTRACTED"
    assert len(summary["facts"]) == 1
    assert summary["facts"][0]["kind"] == "PROCEDURAL_ASSIGNMENT"


def test_module_summary_combines_continuous_and_procedural_facts():
    continuous = dpe.extract_continuous_assign_data_path([
        {"lhs_text": "w", "rhs_text": "x", "lhs_nets": ["w"], "rhs_nets": ["x"]},
    ])
    always_blocks = _blocks("always_ff @(posedge clk) begin q <= w; end\n")
    summary = dpe._module_data_path_summary(continuous, always_blocks)
    assert summary["status"] == "DATA_PATH_EXTRACTED"
    kinds = sorted(f["kind"] for f in summary["facts"])
    assert kinds == ["CONTINUOUS_ASSIGN", "PROCEDURAL_ASSIGNMENT"]


# ---------------------------------------------------------------------------
# 1c. Query helpers -- pure reads over an already-built summary
# ---------------------------------------------------------------------------

def test_signals_feeding_and_fed_by_query_helpers():
    continuous = dpe.extract_continuous_assign_data_path([
        {"lhs_text": "y", "rhs_text": "a", "lhs_nets": ["y"], "rhs_nets": ["a"]},
    ])
    always_blocks = _blocks("always_ff @(posedge clk) begin q <= y; end\n")
    summary = dpe._module_data_path_summary(continuous, always_blocks)

    feeding_y = dpe.signals_feeding(summary, "y")
    assert len(feeding_y) == 1
    assert feeding_y[0]["kind"] == "CONTINUOUS_ASSIGN"
    assert feeding_y[0]["sources"] == ["a"]

    fed_by_y = dpe.signals_fed_by(summary, "y")
    assert len(fed_by_y) == 1
    assert fed_by_y[0]["kind"] == "PROCEDURAL_ASSIGNMENT"
    assert fed_by_y[0]["targets"] == ["q"]

    # 'q' is fed by exactly the fact 'y' feeds into -- the same edge, read
    # from either end.
    feeding_q = dpe.signals_feeding(summary, "q")
    assert feeding_q == fed_by_y

    assert dpe.signals_feeding(summary, "nonexistent") == []
    assert dpe.signals_fed_by(summary, "nonexistent") == []


# ---------------------------------------------------------------------------
# 2. Real-verible integration tests
# ---------------------------------------------------------------------------

@requires_verible
def test_parse_rtl_file_real_module_combines_continuous_and_procedural(tmp_path):
    src = tmp_path / "dut.sv"
    src.write_text(textwrap.dedent("""\
        module dut(input clk, input rst_n, input a, input b, output reg q, output y);
          assign y = a & b;
          always @(posedge clk or negedge rst_n) begin
            if (!rst_n)
              q <= 1'b0;
            else
              q <= a ^ b;
          end
        endmodule
        """), encoding="utf-8")
    result = dpe.parse_rtl_file(src, verible_bin=VERIBLE_BIN)
    assert result["status"] == "PARSED"
    mod = result["modules"][0]
    assert mod["name"] == "dut"
    dp = mod["data_path_extraction"]
    assert dp["status"] == "DATA_PATH_EXTRACTED"

    assert len(dp["continuous_assigns"]) == 1
    ca = dp["continuous_assigns"][0]
    assert ca["targets"] == ["y"]
    assert ca["sources"] == ["a", "b"]
    assert ca["evidence_source"] == "VERIBLE_PARSED_TREE"

    assert len(dp["always_blocks"]) == 1
    blk = dp["always_blocks"][0]
    assert blk["block_kind"] == "SEQUENTIAL"
    assert len(blk["assignments"]) == 2
    # every real port referenced (clk, rst_n, a, b, q, y) must be recognized
    # -- none of the real assignment facts' own targets/sources should be
    # flagged unrecognized against the module's own real parsed ports.
    for a0 in blk["assignments"]:
        assert a0["targets_unrecognized"] == []
        assert a0["sources_unrecognized"] == []
    reset_branch, normal_branch = blk["assignments"]
    assert reset_branch["targets"] == ["q"]
    assert reset_branch["sources"] == []
    assert normal_branch["targets"] == ["q"]
    assert normal_branch["sources"] == ["a", "b"]

    # union query surface: every fact reachable through 'facts' too.
    assert len(dp["facts"]) == 3


@requires_verible
def test_parse_rtl_file_module_with_no_data_path_is_honest_not_available(tmp_path):
    src = tmp_path / "empty_dut.sv"
    src.write_text("module empty_dut(input clk, output y); endmodule\n", encoding="utf-8")
    result = dpe.parse_rtl_file(src, verible_bin=VERIBLE_BIN)
    assert result["status"] == "PARSED"
    dp = result["modules"][0]["data_path_extraction"]
    assert dp["status"] == "NOT_AVAILABLE"
    assert dp["reason"]
    assert dp["facts"] == []


@requires_verible
def test_build_data_path_ir_isolates_one_real_syntax_error(tmp_path):
    good = tmp_path / "good.sv"
    good.write_text(textwrap.dedent("""\
        module good(input clk, input a, output reg y);
          always @(posedge clk) y <= a;
        endmodule
        """), encoding="utf-8")
    bad = tmp_path / "bad.sv"
    bad.write_text("module bad( this is not valid systemverilog ;;;\n", encoding="utf-8")
    ir = dpe.build_data_path_ir([good, bad], verible_bin=VERIBLE_BIN)
    assert ir["status"] == "BUILT"
    statuses = {pf["file_path"]: pf["status"] for pf in ir["files"]}
    assert statuses[str(good)] == "PARSED"
    assert statuses[str(bad)] == "PARSE_ERROR"


@requires_verible
def test_save_data_path_ir_round_trips(tmp_path):
    src = tmp_path / "dut.sv"
    src.write_text("module dut(input clk, output reg y); always @(posedge clk) y <= 1; endmodule\n",
                    encoding="utf-8")
    ir = dpe.build_data_path_ir([src], verible_bin=VERIBLE_BIN)
    out = tmp_path / "ir.json"
    dpe.save_data_path_ir(ir, out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["status"] == "BUILT"


@requires_verible
def test_execute_verb_text_and_json(tmp_path):
    src = tmp_path / "dut.sv"
    src.write_text("module dut(input clk, output reg y); always @(posedge clk) y <= 1; endmodule\n",
                    encoding="utf-8")
    text, code = dpe.execute_verb([src], verible_bin=VERIBLE_BIN, as_json=False)
    assert code == 0
    assert "dut" in text
    js, code2 = dpe.execute_verb([src], verible_bin=VERIBLE_BIN, as_json=True)
    assert code2 == 0
    parsed = json.loads(js)
    assert parsed["status"] == "BUILT"


def test_execute_verb_no_files_exits_2():
    text, code = dpe.execute_verb([])
    assert code == 2
    assert "NOT_AVAILABLE" in text


def test_unreadable_file_reports_not_available(tmp_path):
    missing = tmp_path / "does_not_exist.sv"
    result = dpe.parse_rtl_file(missing)
    assert result["status"] == "NOT_AVAILABLE"


def test_unrunnable_verible_binary_reports_not_available(tmp_path):
    src = tmp_path / "dut.sv"
    src.write_text("module dut(); endmodule\n", encoding="utf-8")
    result = dpe.parse_rtl_file(src, verible_bin="verible-verilog-syntax-does-not-exist")
    assert result["status"] == "NOT_AVAILABLE"


@requires_verible
def test_cli_subprocess_json_and_out_file(tmp_path):
    src = tmp_path / "dut.sv"
    src.write_text(textwrap.dedent("""\
        module dut(input clk, input sel, input a, output reg y);
          always_comb begin
            y = a;
          end
        endmodule
        """), encoding="utf-8")
    out = tmp_path / "ir.json"
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.rtl_data_path_extraction",
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
        [sys.executable, "-m", "dv_harness.rtl_data_path_extraction"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "--rtl" in proc.stderr
