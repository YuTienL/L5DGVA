"""Tests for dv_harness/param_define_extraction.py -- real RTL parameter
extraction (via verible_parser.py, each with its real file:line citation)
and real preprocessor `define constant extraction (via a raw-text
line-scan), item id param_define_extraction, spec section 284.

Two tiers, matching this repo's own convention (see
test_memory_buffer_arch_extraction.py / test_design_architecture_ir.py):
- Pure, unconditional unit tests drive `extract_defines_from_text()` and
  `extract_module_parameters()` directly against hand-crafted
  `verible_parser.ModuleInfo`/`ParamInfo` objects -- no subprocess needed.
- A small number of tests exercise the REAL end-to-end pipeline through a
  real `verible-verilog-syntax` subprocess and are skipped (never faked) on
  a machine without it on PATH, per this project's own Evidence Truth Rule.
"""
from __future__ import annotations

import shutil
import textwrap

import pytest

from dv_harness.verible_parser import ModuleInfo, ParamInfo
from dv_harness import param_define_extraction as pde
from dv_harness import verible_parser

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

FIFO_FIXTURE = textwrap.dedent("""\
    `define FIFO_MAGIC 32'hCAFEBABE
    `define FIFO_GUARD_H
    `define FIFO_ADD(a, b) ((a) + (b))

    module fifo_ctrl #(
        parameter int DEPTH = 16,
        parameter int WIDTH = 8
    ) (
        input  logic              clk,
        input  logic              rst_n,
        input  logic [WIDTH-1:0]  wr_data,
        output logic [WIDTH-1:0]  rd_data
    );

        logic [WIDTH-1:0] mem [0:DEPTH-1];

        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) rd_data <= '0;
        end

    endmodule
    """)

NO_PARAM_NO_DEFINE_FIXTURE = textwrap.dedent("""\
    module counter (
        input  logic clk,
        input  logic rst_n,
        output logic [7:0] cnt
    );
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) cnt <= 8'd0;
            else cnt <= cnt + 8'd1;
        end
    endmodule
    """)


@pytest.fixture
def fifo_sv(tmp_path):
    p = tmp_path / "fifo_ctrl.sv"
    p.write_text(FIFO_FIXTURE, encoding="utf-8")
    return p


@pytest.fixture
def plain_sv(tmp_path):
    p = tmp_path / "counter.sv"
    p.write_text(NO_PARAM_NO_DEFINE_FIXTURE, encoding="utf-8")
    return p


# ===========================================================================
# Tier 1: pure unit tests (no subprocess)
# ===========================================================================

def test_module_with_parameters_reports_each_with_real_citation():
    module = ModuleInfo(
        name="fifo_ctrl",
        parameters=[
            ParamInfo(name="DEPTH", type_text="int", default_text="16", line=31),
            ParamInfo(name="WIDTH", type_text="int", default_text="8", line=32),
        ],
    )
    report = pde.extract_module_parameters(module, "fifo_ctrl.sv")
    assert report.status == pde.PARAMETERS_FOUND
    assert len(report.parameters) == 2
    by_name = {p.param_name: p for p in report.parameters}
    assert by_name["DEPTH"].default_text == "16"
    assert by_name["DEPTH"].line == 31
    assert by_name["DEPTH"].line_status == pde.PARAM_LINE_RESOLVED
    assert by_name["DEPTH"].file_path == "fifo_ctrl.sv"
    assert by_name["WIDTH"].line == 32


def test_module_with_no_parameters_is_honestly_not_available():
    """Negative control: a module verible really parsed but that declares NO
    parameters must report PARAMETERS_NOT_AVAILABLE, never a fabricated
    parameter and never silently look identical to 'not parsed at all'."""
    module = ModuleInfo(name="counter", parameters=[])
    report = pde.extract_module_parameters(module, "counter.sv")
    assert report.status == pde.PARAMETERS_NOT_AVAILABLE
    assert report.parameters == []


def test_param_with_no_resolvable_span_reports_line_not_available_not_a_guess():
    """Negative control: a ParamInfo whose line could not be computed
    (defensive path) must report None + PARAM_LINE_NOT_AVAILABLE, never a
    fabricated line number."""
    module = ModuleInfo(
        name="m", parameters=[ParamInfo(name="X", type_text="int", default_text="1", line=None)],
    )
    report = pde.extract_module_parameters(module, "m.sv")
    fact = report.parameters[0]
    assert fact.line is None
    assert fact.line_status == pde.PARAM_LINE_NOT_AVAILABLE


def test_verible_parser_param_info_has_real_line_field():
    """The small additive verible_parser.py change this module builds on:
    ParamInfo must carry a `line` field, defaulting to None (backward
    compatible with the three existing positional call sites in
    test_memory_buffer_arch_extraction.py)."""
    p = ParamInfo("DEPTH", "int", "16")
    assert p.line is None
    p2 = ParamInfo(name="WIDTH", type_text="int", default_text="8", line=42)
    assert p2.line == 42


def test_extract_defines_finds_object_like_constant_with_real_line():
    text = "`define FOO 42\n`define BAR 32'hDEAD_BEEF\n"
    facts = pde.extract_defines_from_text(text, "f.sv")
    assert len(facts) == 2
    assert facts[0].define_name == "FOO"
    assert facts[0].value_text == "42"
    assert facts[0].line == 1
    assert facts[0].status == pde.DEFINE_CONSTANT_FOUND
    assert facts[1].define_name == "BAR"
    assert facts[1].value_text == "32'hDEAD_BEEF"
    assert facts[1].line == 2


def test_extract_defines_function_like_macro_is_not_a_constant():
    text = "`define ADD(a, b) ((a) + (b))\n"
    facts = pde.extract_defines_from_text(text, "f.sv")
    assert len(facts) == 1
    assert facts[0].status == pde.DEFINE_FUNCTION_LIKE_SKIPPED
    assert facts[0].value_text is None
    assert facts[0].define_name == "ADD"


def test_extract_defines_guard_macro_with_no_value_is_distinct():
    text = "`define MY_GUARD_H\n`define ANOTHER\n"
    facts = pde.extract_defines_from_text(text, "f.sv")
    assert all(f.status == pde.DEFINE_GUARD_NO_VALUE for f in facts)
    assert all(f.value_text is None for f in facts)


def test_extract_defines_multiline_continuation_not_captured_not_guessed():
    """Negative control: a backslash-continued `define must never have its
    value fabricated by joining lines this scan does not splice."""
    text = "`define LONG_MACRO first_part + \\\n    second_part\n"
    facts = pde.extract_defines_from_text(text, "f.sv")
    assert len(facts) == 1
    assert facts[0].status == pde.DEFINE_MULTILINE_NOT_CAPTURED
    assert facts[0].value_text is None
    assert facts[0].define_name == "LONG_MACRO"


def test_extract_defines_inside_comment_or_string_is_never_reported():
    """Negative control: a `define spelled inside a // comment, a /* */
    block comment, or a "..." string literal must not be mistaken for a
    real preprocessor directive."""
    text = (
        "// `define FAKE_ONE 1\n"
        "/* `define FAKE_TWO 2\n"
        "   still a comment */\n"
        '$display("`define FAKE_THREE 3");\n'
        "`define REAL_ONE 99\n"
    )
    facts = pde.extract_defines_from_text(text, "f.sv")
    assert len(facts) == 1
    assert facts[0].define_name == "REAL_ONE"
    assert facts[0].line == 5


def test_extract_defines_line_numbers_survive_comment_blanking():
    """Blanking preserves newlines, so line numbers computed after blanking
    must still agree with the real, un-blanked source."""
    text = (
        "/* header\n"
        "   comment\n"
        "   block */\n"
        "`define AFTER_BLOCK 1\n"
    )
    facts = pde.extract_defines_from_text(text, "f.sv")
    assert len(facts) == 1
    assert facts[0].line == 4


def test_extract_defines_from_text_with_no_defines_is_empty_not_guessed():
    facts = pde.extract_defines_from_text("module m; endmodule\n", "f.sv")
    assert facts == []


def test_file_report_read_failure_is_honest_not_silently_empty():
    """Negative control: a file that cannot be read at all (does not exist)
    must report DEFINES_FILE_UNAVAILABLE, never a silent 'no defines found'
    that looks identical to a real, empty, successfully-read file."""
    status, reason, defines_status, defines = pde._extract_file_defines(
        "/nonexistent/path/does_not_exist.sv"
    )
    assert status == pde.DEFINES_FILE_UNAVAILABLE
    assert reason is not None
    assert defines_status == pde.DEFINES_NOT_AVAILABLE
    assert defines == []


def test_vocabulary_does_not_collide_with_verification_verdict():
    # Re-running the import-time guard directly must not raise.
    pde.assert_no_verification_verdict_vocabulary()


def test_render_param_define_markdown_handles_empty_reports():
    md = pde.render_param_define_markdown([])
    assert "no RTL files supplied" in md


# ===========================================================================
# Tier 2: real end-to-end pipeline through a real verible subprocess
# ===========================================================================

@requires_verible
def test_end_to_end_fifo_reports_real_parameters_and_defines_with_citations(fifo_sv):
    report = pde.extract_param_define_facts_for_file(fifo_sv)

    assert report.param_status == pde.PARAMS_FILE_PARSED
    assert len(report.modules) == 1
    mr = report.modules[0]
    assert mr.status == pde.PARAMETERS_FOUND
    by_name = {p.param_name: p for p in mr.parameters}
    assert by_name["DEPTH"].default_text == "16"
    assert by_name["DEPTH"].line_status == pde.PARAM_LINE_RESOLVED
    # Real citation: DEPTH is declared on the file's own real line (6, given
    # the fixture's 3 leading `define/blank lines before the module header).
    real_text = fifo_sv.read_text(encoding="utf-8")
    depth_line = next(
        i + 1 for i, line in enumerate(real_text.splitlines()) if "parameter int DEPTH" in line
    )
    assert by_name["DEPTH"].line == depth_line
    assert by_name["DEPTH"].file_path == str(fifo_sv)

    assert report.define_read_status == pde.DEFINES_FILE_READ
    assert report.defines_status == pde.DEFINES_FOUND
    by_define = {d.define_name: d for d in report.defines}
    assert by_define["FIFO_MAGIC"].value_text == "32'hCAFEBABE"
    assert by_define["FIFO_MAGIC"].status == pde.DEFINE_CONSTANT_FOUND
    magic_line = next(
        i + 1 for i, line in enumerate(real_text.splitlines())
        if line.startswith("`define FIFO_MAGIC")
    )
    assert by_define["FIFO_MAGIC"].line == magic_line
    assert by_define["FIFO_GUARD_H"].status == pde.DEFINE_GUARD_NO_VALUE
    assert by_define["FIFO_ADD"].status == pde.DEFINE_FUNCTION_LIKE_SKIPPED


@requires_verible
def test_end_to_end_plain_module_is_honestly_not_available(plain_sv):
    """Negative control: a real module with no parameters and no `define
    anywhere must report both facets NOT_AVAILABLE, never fabricated."""
    report = pde.extract_param_define_facts_for_file(plain_sv)
    assert report.param_status == pde.PARAMS_FILE_PARSED
    assert len(report.modules) == 1
    assert report.modules[0].status == pde.PARAMETERS_NOT_AVAILABLE
    assert report.defines_status == pde.DEFINES_NOT_AVAILABLE
    assert report.defines == []


@requires_verible
def test_end_to_end_verible_unavailable_is_reported_honestly(fifo_sv):
    """Negative control: pointing at a nonexistent verible binary must
    report PARAMS_FILE_UNAVAILABLE, never silently fall back to 'parsed with
    zero parameters'."""
    report = pde.extract_param_define_facts_for_file(
        fifo_sv, verible_bin="definitely-not-a-real-verible-binary"
    )
    assert report.param_status == pde.PARAMS_FILE_UNAVAILABLE
    assert report.param_reason
    assert report.modules == []
    # The `define scan does not depend on verible at all, so it must still
    # succeed even though the parameter half failed.
    assert report.define_read_status == pde.DEFINES_FILE_READ
    assert report.defines_status == pde.DEFINES_FOUND


@requires_verible
def test_execute_verb_exit_code_reflects_findings(fifo_sv, plain_sv, capsys):
    rc = pde.execute_verb([str(fifo_sv), "--json"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "FIFO_MAGIC" in captured.out
    assert "DEPTH" in captured.out


@requires_verible
def test_execute_verb_exit_code_two_when_nothing_found(plain_sv):
    rc = pde.execute_verb([str(plain_sv)])
    assert rc == 2


@requires_verible
def test_real_verible_parse_file_populates_param_line(fifo_sv):
    """Direct proof that the verible_parser.py additive change is real and
    live end-to-end, not just exercised through hand-built ParamInfo
    objects."""
    result = verible_parser.parse_file(fifo_sv)
    module = result.modules[0]
    params = {p.name: p for p in module.parameters}
    assert params["DEPTH"].line is not None
    assert params["WIDTH"].line is not None
    assert params["DEPTH"].line != params["WIDTH"].line
