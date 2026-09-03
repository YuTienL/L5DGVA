"""Tests for dv_harness/verible_parser.py -- structured RTL parsing via a
REAL `verible-verilog-syntax --export_json --printtree` subprocess call
(2026-09-03, verible+DuckDB evidence-store task).

These tests run the real verible binary against a synthesized, minimal,
valid .sv fixture (never real project RTL, which is proprietary and lives
only on the remote server -- see CLAUDE.md's Evidence Truth Rule / No
Golden-Reference Content Mining). Skipped outright (not faked/mocked) on a
machine without verible-verilog-syntax on PATH, consistent with this
project's own evidence-truth discipline: a missing real tool is a reported
gap, never a reason to fabricate what its output would have been."""
from __future__ import annotations

import shutil
import textwrap

import pytest

from dv_harness.verible_parser import (
    VeribleParseError,
    VeribleUnavailableError,
    extract_modules,
    get_verible_version,
    parse_file,
    run_export_json,
    to_dict,
)

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


@pytest.fixture
def fifo_sv(tmp_path):
    p = tmp_path / "fifo_ctrl.sv"
    p.write_text(FIFO_FIXTURE, encoding="utf-8")
    return p


@requires_verible
def test_get_verible_version_returns_real_version_string():
    version = get_verible_version()
    assert version
    assert "v" in version.lower() or version[0].isdigit()


@requires_verible
def test_run_export_json_returns_tree_for_valid_file(fifo_sv):
    tree = run_export_json(fifo_sv)
    assert isinstance(tree, dict)
    assert "children" in tree


@requires_verible
def test_run_export_json_raises_parse_error_on_malformed_file(tmp_path):
    broken = tmp_path / "broken.sv"
    broken.write_text("module broken(\n  input logic clk\n", encoding="utf-8")
    with pytest.raises(VeribleParseError) as exc:
        run_export_json(broken)
    assert exc.value.errors
    assert exc.value.errors[0]["phase"] == "parse"


def test_run_export_json_raises_unavailable_for_missing_binary(fifo_sv):
    with pytest.raises(VeribleUnavailableError):
        run_export_json(fifo_sv, verible_bin="verible-verilog-syntax-does-not-exist")


@requires_verible
def test_parse_file_extracts_module_name_and_source_hash(fifo_sv):
    result = parse_file(fifo_sv)
    assert result.file_path == str(fifo_sv)
    assert len(result.source_sha256) == 64
    assert len(result.modules) == 1
    assert result.modules[0].name == "fifo_ctrl"


@requires_verible
def test_parse_file_extracts_full_port_hierarchy(fifo_sv):
    result = parse_file(fifo_sv)
    mod = result.modules[0]
    ports_by_name = {p.name: p for p in mod.ports}
    assert set(ports_by_name) == {
        "clk", "rst_n", "wr_data", "wr_en", "rd_data", "rd_valid", "full", "empty",
    }
    assert ports_by_name["clk"].direction == "input"
    assert ports_by_name["clk"].data_type == "logic"
    assert ports_by_name["wr_data"].direction == "input"
    assert ports_by_name["wr_data"].data_type == "logic [WIDTH-1:0]"
    assert ports_by_name["rd_data"].direction == "output"
    assert ports_by_name["rd_data"].data_type == "logic [WIDTH-1:0]"


@requires_verible
def test_parse_file_extracts_parameters(fifo_sv):
    result = parse_file(fifo_sv)
    params_by_name = {p.name: p for p in result.modules[0].parameters}
    assert params_by_name["DEPTH"].type_text == "int"
    assert params_by_name["DEPTH"].default_text == "16"
    assert params_by_name["WIDTH"].type_text == "int"
    assert params_by_name["WIDTH"].default_text == "8"


@requires_verible
def test_parse_file_extracts_module_level_signals_including_array_dims(fifo_sv):
    result = parse_file(fifo_sv)
    signals_by_name = {s.name: s for s in result.modules[0].signals}
    assert signals_by_name["mem"].data_type == "logic [WIDTH-1:0]"
    assert signals_by_name["mem"].unpacked_dims == "[0:DEPTH-1]"
    assert signals_by_name["wr_ptr"].data_type == "logic [3:0]"
    assert signals_by_name["wr_ptr"].unpacked_dims is None
    assert signals_by_name["rd_ptr"].data_type == "logic [3:0]"


@requires_verible
def test_parse_file_does_not_surface_procedural_block_locals(fifo_sv):
    """wr_ptr/rd_ptr are module-level declarations and DO appear; nothing
    inside the always_ff block (no local var there in this fixture, but the
    scoping rule itself is what's under test: kModuleItemList's DIRECT
    children only) should produce a duplicate/nested signal entry."""
    result = parse_file(fifo_sv)
    names = [s.name for s in result.modules[0].signals]
    assert names.count("wr_ptr") == 1
    assert names.count("rd_ptr") == 1


@requires_verible
def test_extract_modules_on_file_with_no_module_returns_empty_list(tmp_path):
    pkg = tmp_path / "empty_pkg.sv"
    pkg.write_text("package empty_pkg;\nendpackage\n", encoding="utf-8")
    tree = run_export_json(pkg)
    modules = extract_modules(tree, pkg.read_text(encoding="utf-8"))
    assert modules == []


@requires_verible
def test_to_dict_round_trips_plain_json_serializable_shape(fifo_sv):
    import json
    result = parse_file(fifo_sv)
    d = to_dict(result)
    # must be plain-JSON-serializable (evidence_db.insert_rtl_parse() consumes
    # exactly this shape)
    reparsed = json.loads(json.dumps(d))
    assert reparsed["modules"][0]["name"] == "fifo_ctrl"
    assert len(reparsed["modules"][0]["ports"]) == 8
    assert len(reparsed["modules"][0]["parameters"]) == 2
    assert len(reparsed["modules"][0]["signals"]) == 3
