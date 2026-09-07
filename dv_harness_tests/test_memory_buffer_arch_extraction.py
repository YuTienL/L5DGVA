"""Tests for dv_harness/memory_buffer_arch_extraction.py -- real
memory/FIFO/buffer architecture fact extraction (depth, width, read/write
ports) from RTL parameters/ports/signals via verible_parser.py.

Two tiers, matching this repo's own convention (see test_design_architecture_ir.py):
- Pure, unconditional unit tests build `verible_parser.ModuleInfo`/`ParamInfo`/
  `PortInfo`/`SignalInfo` objects DIRECTLY (no subprocess, no verible binary
  needed at all) and drive this module's own resolution/classification logic
  against hand-crafted-but-real RTL declaration shapes.
- A small number of tests exercise the REAL end-to-end pipeline through a
  real `verible-verilog-syntax` subprocess and are skipped (never faked) on a
  machine without it on PATH, per this project's own Evidence Truth Rule.
"""
from __future__ import annotations

import shutil
import textwrap

import pytest

from dv_harness.verible_parser import ModuleInfo, ParamInfo, PortInfo, SignalInfo
from dv_harness import memory_buffer_arch_extraction as mbae

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

FIFO_FIXTURE = textwrap.dedent("""\
    module fifo_ctrl #(
        parameter int DEPTH = 16,
        parameter int WIDTH = 8
    ) (
        input  logic              clk,
        input  logic              rst_n,
        input  logic [WIDTH-1:0]  wr_data,
        input  logic              wr_en,
        output logic [WIDTH-1:0]  rd_data,
        output logic              rd_valid,
        output logic              full,
        output logic              empty
    );

        logic [WIDTH-1:0] mem [0:DEPTH-1];
        logic [3:0] wr_ptr, rd_ptr;

        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                wr_ptr <= 4'd0;
            end else if (wr_en && !full) begin
                mem[wr_ptr] <= wr_data;
                wr_ptr <= wr_ptr + 4'd1;
            end
        end

        assign empty = (wr_ptr == rd_ptr);
        assign full  = ((wr_ptr + 4'd1) == rd_ptr);

    endmodule
    """)

NO_MEMORY_FIXTURE = textwrap.dedent("""\
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
def no_memory_sv(tmp_path):
    p = tmp_path / "counter.sv"
    p.write_text(NO_MEMORY_FIXTURE, encoding="utf-8")
    return p


# ---- vocabulary -------------------------------------------------------

def test_vocabulary_disjoint_from_status():
    # already ran at import; calling again must still be a no-op (no raise)
    mbae.assert_no_verification_verdict_vocabulary()


# ---- literal parsing ---------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("16", 16),
    ("1_024", 1024),
    ("8'd16", 16),
    ("16'h0010", 16),
    ("4'b1010", 10),
    ("'h10", 16),
    ("", None),
    (None, None),
    ("DEPTH-1", None),
])
def test_try_parse_int_literal(text, expected):
    assert mbae._try_parse_int_literal(text) == expected


def test_try_parse_int_literal_refuses_dont_care_bits():
    assert mbae._try_parse_int_literal("4'bx1x0") is None
    assert mbae._try_parse_int_literal("8'dz") is None
    assert mbae._try_parse_int_literal("4'b1?10") is None


# ---- depth resolution ---------------------------------------------------

def test_resolve_depth_literal_range():
    value, status, raw = mbae.resolve_depth("[0:15]", {})
    assert value == 16
    assert status == mbae.DEPTH_RESOLVED_LITERAL
    assert raw == "[0:15]"


def test_resolve_depth_resolved_via_parameter():
    value, status, raw = mbae.resolve_depth("[0:DEPTH-1]", {"DEPTH": 16})
    assert value == 16
    assert status == mbae.DEPTH_RESOLVED_VIA_PARAMETER


def test_resolve_depth_unresolved_when_parameter_not_supplied():
    value, status, raw = mbae.resolve_depth("[0:DEPTH-1]", {})
    assert value is None
    assert status == mbae.DEPTH_SYMBOLIC_UNRESOLVED
    assert raw == "[0:DEPTH-1]"  # raw expression kept verbatim, never dropped


def test_resolve_depth_unresolved_complex_expression_never_guessed():
    # "DEPTH*2-1" is outside this module's bounded IDENT(+|-)INT grammar --
    # it must never be silently evaluated to a plausible number.
    value, status, raw = mbae.resolve_depth("[0:DEPTH*2-1]", {"DEPTH": 16})
    assert value is None
    assert status == mbae.DEPTH_SYMBOLIC_UNRESOLVED


def test_resolve_depth_multi_dimensional_never_collapsed():
    value, status, raw = mbae.resolve_depth("[0:1][0:15]", {})
    assert value is None
    assert status == mbae.DEPTH_MULTI_DIM_UNRESOLVED
    assert raw == "[0:1][0:15]"


def test_resolve_depth_empty_text():
    value, status, raw = mbae.resolve_depth("", {})
    assert value is None
    assert status == mbae.DEPTH_SYMBOLIC_UNRESOLVED
    value, status, raw = mbae.resolve_depth(None, {})
    assert value is None
    assert status == mbae.DEPTH_SYMBOLIC_UNRESOLVED


# ---- width resolution ---------------------------------------------------

def test_resolve_width_literal_range():
    value, status, raw = mbae.resolve_width("logic [31:0]", {})
    assert value == 32
    assert status == mbae.WIDTH_RESOLVED_LITERAL


def test_resolve_width_scalar_base_type_is_one_bit():
    for base in ("logic", "bit", "reg", "wire"):
        value, status, raw = mbae.resolve_width(base, {})
        assert value == 1, base
        assert status == mbae.WIDTH_RESOLVED_LITERAL, base


def test_resolve_width_resolved_via_parameter():
    value, status, raw = mbae.resolve_width("logic [WIDTH-1:0]", {"WIDTH": 8})
    assert value == 8
    assert status == mbae.WIDTH_RESOLVED_VIA_PARAMETER


def test_resolve_width_typedef_never_assumed_a_width():
    # The headline rule: a typedef/struct-shaped data type with no packed
    # range must NEVER be assumed to be any particular width.
    value, status, raw = mbae.resolve_width("axi_beat_t", {})
    assert value is None
    assert status == mbae.WIDTH_UNRESOLVED_TYPE
    assert raw == "axi_beat_t"


def test_resolve_width_multi_dimensional_never_collapsed():
    value, status, raw = mbae.resolve_width("logic [3:0][7:0]", {})
    assert value is None
    assert status == mbae.WIDTH_MULTI_DIM_UNRESOLVED


def test_resolve_width_empty_text():
    value, status, raw = mbae.resolve_width("", {})
    assert value is None
    assert status == mbae.WIDTH_SYMBOLIC_UNRESOLVED
    value, status, raw = mbae.resolve_width(None, {})
    assert value is None
    assert status == mbae.WIDTH_SYMBOLIC_UNRESOLVED


# ---- port role classification (naming-convention evidence only) --------

def test_classify_port_role_write_and_read():
    assert mbae._classify_port_role("wr_en") == "write"
    assert mbae._classify_port_role("wr_data") == "write"
    assert mbae._classify_port_role("waddr") == "write"
    assert mbae._classify_port_role("rd_data") == "read"
    assert mbae._classify_port_role("rd_valid") == "read"
    assert mbae._classify_port_role("raddr") == "read"


def test_classify_port_role_no_match_is_none_not_guessed():
    assert mbae._classify_port_role("clk") is None
    assert mbae._classify_port_role("rst_n") is None
    assert mbae._classify_port_role("full") is None
    assert mbae._classify_port_role("empty") is None
    assert mbae._classify_port_role(None) is None
    assert mbae._classify_port_role("") is None


def test_classify_port_role_ambiguous_name_is_never_guessed():
    # A name whose tokens match BOTH vocabularies must resolve to neither --
    # never guessed into either direction.
    assert mbae._classify_port_role("read_write_ctrl") is None


def test_classify_ports_matches_and_status():
    ports = [
        PortInfo("clk", "input", "logic"),
        PortInfo("rst_n", "input", "logic"),
        PortInfo("wr_data", "input", "logic [7:0]"),
        PortInfo("wr_en", "input", "logic"),
        PortInfo("rd_data", "output", "logic [7:0]"),
        PortInfo("rd_valid", "output", "logic"),
        PortInfo("full", "output", "logic"),
        PortInfo("empty", "output", "logic"),
    ]
    module = ModuleInfo(name="fifo_ctrl", ports=ports)
    read_ports, write_ports, status = mbae.classify_ports(module)
    assert {p["name"] for p in write_ports} == {"wr_data", "wr_en"}
    assert {p["name"] for p in read_ports} == {"rd_data", "rd_valid"}
    assert status == mbae.PORTS_MATCHED_BY_NAMING_CONVENTION


def test_classify_ports_no_match_reports_honest_status():
    ports = [PortInfo("clk", "input", "logic"), PortInfo("rst_n", "input", "logic")]
    module = ModuleInfo(name="glue", ports=ports)
    read_ports, write_ports, status = mbae.classify_ports(module)
    assert read_ports == []
    assert write_ports == []
    assert status == mbae.PORT_DIRECTION_NOT_DETERMINABLE


# ---- parameter default resolution ---------------------------------------

def test_param_defaults_only_literal_defaults_resolve():
    params = [
        ParamInfo("DEPTH", "int", "16"),
        ParamInfo("WIDTH", "int", "OTHER_PARAM"),  # not a literal -- never guessed
        ParamInfo("NAME", "string", None),
    ]
    module = ModuleInfo(name="m", parameters=params)
    defaults = mbae._param_defaults(module)
    assert defaults == {"DEPTH": 16}


# ---- module-level extraction (no verible needed) ------------------------

def _build_fifo_module_info():
    params = [ParamInfo("DEPTH", "int", "16"), ParamInfo("WIDTH", "int", "8")]
    ports = [
        PortInfo("clk", "input", "logic"),
        PortInfo("rst_n", "input", "logic"),
        PortInfo("wr_data", "input", "logic [WIDTH-1:0]"),
        PortInfo("wr_en", "input", "logic"),
        PortInfo("rd_data", "output", "logic [WIDTH-1:0]"),
        PortInfo("rd_valid", "output", "logic"),
        PortInfo("full", "output", "logic"),
        PortInfo("empty", "output", "logic"),
    ]
    signals = [
        SignalInfo("mem", "logic [WIDTH-1:0]", "[0:DEPTH-1]"),
        SignalInfo("wr_ptr", "logic [3:0]", None),
        SignalInfo("rd_ptr", "logic [3:0]", None),
    ]
    return ModuleInfo(name="fifo_ctrl", parameters=params, ports=ports, signals=signals)


def test_extract_module_memory_structures_fifo():
    module = _build_fifo_module_info()
    report = mbae.extract_module_memory_structures(module, "fifo_ctrl.sv")
    assert report.status == mbae.STRUCTURE_FOUND
    # only "mem" carries unpacked_dims -- wr_ptr/rd_ptr are plain scalars,
    # never mistaken for a second memory structure.
    assert len(report.structures) == 1
    s = report.structures[0]
    assert s.module_name == "fifo_ctrl"
    assert s.signal_name == "mem"
    assert s.depth_value == 16
    assert s.depth_status == mbae.DEPTH_RESOLVED_VIA_PARAMETER
    assert s.width_value == 8
    assert s.width_status == mbae.WIDTH_RESOLVED_VIA_PARAMETER
    assert {p["name"] for p in s.write_ports} == {"wr_data", "wr_en"}
    assert {p["name"] for p in s.read_ports} == {"rd_data", "rd_valid"}
    assert s.port_status == mbae.PORTS_MATCHED_BY_NAMING_CONVENTION


def test_extract_module_memory_structures_negative_control_no_array_signal():
    # THE required negative control: a module declaring NO array-shaped
    # signal must report NOT_AVAILABLE, never a fabricated memory structure.
    module = ModuleInfo(
        name="counter",
        ports=[PortInfo("clk", "input", "logic")],
        signals=[SignalInfo("cnt", "logic [7:0]", None)],
    )
    report = mbae.extract_module_memory_structures(module, "counter.sv")
    assert report.status == mbae.STRUCTURE_NOT_AVAILABLE
    assert report.structures == []


def test_extract_module_memory_structures_negative_control_no_signals_at_all():
    module = ModuleInfo(name="empty_mod", ports=[PortInfo("clk", "input", "logic")], signals=[])
    report = mbae.extract_module_memory_structures(module, "empty_mod.sv")
    assert report.status == mbae.STRUCTURE_NOT_AVAILABLE
    assert report.structures == []


def test_array_presence_is_real_even_when_depth_unresolvable():
    # Presence of a real unpacked dimension is itself the structural fact --
    # an unresolvable depth must not make the structure disappear entirely.
    module = ModuleInfo(
        name="ram",
        parameters=[],
        ports=[PortInfo("clk", "input", "logic")],
        signals=[SignalInfo("storage", "logic [7:0]", "[0:UNKNOWN_PARAM-1]")],
    )
    report = mbae.extract_module_memory_structures(module, "ram.sv")
    assert report.status == mbae.STRUCTURE_FOUND
    assert len(report.structures) == 1
    s = report.structures[0]
    assert s.depth_value is None
    assert s.depth_status == mbae.DEPTH_SYMBOLIC_UNRESOLVED
    assert s.depth_expr_text == "[0:UNKNOWN_PARAM-1]"


def test_to_dict_round_trips_json_serializable():
    import json
    module = _build_fifo_module_info()
    report = mbae.extract_module_memory_structures(module, "fifo_ctrl.sv")
    payload = report.to_dict()
    text = json.dumps(payload)
    assert "mem" in text
    assert mbae.DEPTH_RESOLVED_VIA_PARAMETER in text


# ---- rendering ------------------------------------------------------------

def test_render_memory_structures_markdown_reports_every_status_honestly():
    module = _build_fifo_module_info()
    module_report = mbae.extract_module_memory_structures(module, "fifo_ctrl.sv")
    no_mem_report = mbae.extract_module_memory_structures(
        ModuleInfo(name="glue", ports=[], signals=[]), "glue.sv"
    )
    file_report = mbae.FileMemoryReport(
        file_path="fifo_ctrl.sv", status=mbae.FILE_PARSED,
        modules=[module_report, no_mem_report],
    )
    unavailable_report = mbae.FileMemoryReport(
        file_path="missing.sv", status=mbae.FILE_UNAVAILABLE, reason="binary not found",
    )
    text = mbae.render_memory_structures_markdown([file_report, unavailable_report])
    assert "mem" in text
    assert "16" in text  # resolved depth
    assert mbae.STRUCTURE_NOT_AVAILABLE in text
    assert "missing.sv" in text
    assert "binary not found" in text


def test_render_memory_structures_markdown_empty_is_honest():
    text = mbae.render_memory_structures_markdown([])
    assert "(no RTL files supplied)" in text


# ---- file-level extraction: unconditional (bad binary path) -------------

def test_extract_file_memory_structures_unavailable_binary(fifo_sv):
    report = mbae.extract_file_memory_structures(
        fifo_sv, verible_bin="definitely_not_a_real_verible_binary_xyz"
    )
    assert report.status == mbae.FILE_UNAVAILABLE
    assert report.reason
    assert report.modules == []


def test_extract_memory_structures_batch_is_per_file_independent(fifo_sv, tmp_path):
    other = tmp_path / "counter.sv"
    other.write_text(NO_MEMORY_FIXTURE, encoding="utf-8")
    reports = mbae.extract_memory_structures(
        [str(fifo_sv), str(other)], verible_bin="definitely_not_a_real_verible_binary_xyz"
    )
    assert len(reports) == 2
    assert all(r.status == mbae.FILE_UNAVAILABLE for r in reports)


# ---- file-level extraction: real verible subprocess (skipped without it) --

@requires_verible
def test_extract_file_memory_structures_real_verible_fifo(fifo_sv):
    report = mbae.extract_file_memory_structures(fifo_sv)
    assert report.status == mbae.FILE_PARSED
    assert report.verible_version
    assert len(report.modules) == 1
    module_report = report.modules[0]
    assert module_report.module_name == "fifo_ctrl"
    assert module_report.status == mbae.STRUCTURE_FOUND
    assert len(module_report.structures) == 1
    s = module_report.structures[0]
    assert s.signal_name == "mem"
    assert s.depth_value == 16
    assert s.depth_status == mbae.DEPTH_RESOLVED_VIA_PARAMETER
    assert s.width_value == 8
    assert s.width_status == mbae.WIDTH_RESOLVED_VIA_PARAMETER
    assert {p["name"] for p in s.write_ports} >= {"wr_data", "wr_en"}
    assert {p["name"] for p in s.read_ports} >= {"rd_data", "rd_valid"}


@requires_verible
def test_extract_file_memory_structures_real_verible_no_memory(no_memory_sv):
    report = mbae.extract_file_memory_structures(no_memory_sv)
    assert report.status == mbae.FILE_PARSED
    assert len(report.modules) == 1
    module_report = report.modules[0]
    assert module_report.module_name == "counter"
    assert module_report.status == mbae.STRUCTURE_NOT_AVAILABLE
    assert module_report.structures == []


@requires_verible
def test_extract_file_memory_structures_real_syntax_error(tmp_path):
    bad = tmp_path / "bad.sv"
    bad.write_text("module bad( ; endmodule\n", encoding="utf-8")
    report = mbae.extract_file_memory_structures(bad)
    assert report.status == mbae.FILE_PARSE_ERROR
    assert report.reason


# ---- CLI front door -------------------------------------------------------

def test_execute_verb_unavailable_binary_exits_2(fifo_sv, capsys):
    code = mbae.execute_verb([
        str(fifo_sv), "--verible-bin", "definitely_not_a_real_verible_binary_xyz",
    ])
    assert code == 2
    out = capsys.readouterr().out
    assert mbae.FILE_UNAVAILABLE in out


def test_main_calls_sys_exit_with_execute_verb_code(fifo_sv, capsys):
    with pytest.raises(SystemExit) as excinfo:
        mbae.main([str(fifo_sv), "--verible-bin", "definitely_not_a_real_verible_binary_xyz"])
    assert excinfo.value.code == 2


@requires_verible
def test_execute_verb_real_verible_json_and_exit_0(fifo_sv, capsys):
    code = mbae.execute_verb([str(fifo_sv), "--json"])
    assert code == 0
    out = capsys.readouterr().out
    assert "DEPTH_RESOLVED_VIA_PARAMETER" in out
    assert '"mem"' in out
