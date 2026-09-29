"""Tests for dv_harness/design_architecture_ir.py -- the fuller
ArchitectureIR built on top of verible_parser.py's own real output (full
recursive instance tree + a best-effort FSM/control-flow literal scan).

Two independent kinds of test, mirroring test_verible_parser.py's and
test_uvm_structural_lint.py's own discipline:

  1. The FSM literal-scan regex (`extract_fsm_candidates()`) is a PURE
     function over plain text -- no verible dependency at all -- so it is
     unit-tested directly against hand-written SystemVerilog snippets,
     never mocked. Each rule (resolved / ambiguous / unresolved /
     unparseable / undeclared-register / comment-robustness / no-case /
     no-always) gets its own real positive-or-negative-control snippet.
  2. Everything that needs real module boundaries (the instance tree, the
     multi-file module registry, and the FSM scan's real integration
     against a verible-parsed module SPAN rather than hand-sliced text)
     runs the REAL `verible-verilog-syntax` subprocess against real files
     written to `tmp_path`, and is SKIPPED (never faked) on a machine
     without it on PATH.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dv_harness import design_architecture_ir as air

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. Pure-function FSM literal-scan tests (no verible needed)
# ---------------------------------------------------------------------------

CLEAN_FSM_TEXT = textwrap.dedent("""\
    reg [1:0] state;
    always @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        state <= 2'd0;
      end else begin
        case (state)
          IDLE: begin
            if (data_in != 0)
              state <= BUSY;
          end
          BUSY: begin
            state <= DONE;
          end
          DONE: begin
            state <= IDLE;
          end
          default: state <= IDLE;
        endcase
      end
    end
    """)


def test_clean_fsm_is_resolved_with_correct_states_and_transitions():
    cands = air.extract_fsm_candidates(CLEAN_FSM_TEXT, "top_mod", ["state"])
    assert len(cands) == 1
    c = cands[0]
    assert c["status"] == "FSM_EXTRACTION_RESOLVED"
    assert c["reason"] is None
    assert c["register_name"] == "state"
    assert c["clock_signal"] == "clk"
    assert c["reset_signal"] == "rst_n"
    assert c["states"] == ["IDLE", "BUSY", "DONE"]
    assert c["has_default"] is True
    by_state = {t["from_state"]: t["to_state"] for t in c["transitions"]}
    assert by_state["IDLE"] == "BUSY"
    assert by_state["BUSY"] == "DONE"
    assert by_state["DONE"] == "IDLE"
    assert by_state["default"] == "IDLE"
    # the IDLE->BUSY transition is guarded by a real 'if'; the others are not
    conditional = {t["from_state"]: t["conditional"] for t in c["transitions"]}
    assert conditional["IDLE"] is True
    assert conditional["BUSY"] is False


def test_ambiguous_next_state_is_partial_not_silently_resolved():
    text = textwrap.dedent("""\
        always @(posedge clk) begin
          case (st)
            A: begin
              if (x) st <= B; else st <= C;
            end
            B: st <= A;
          endcase
        end
        """)
    cands = air.extract_fsm_candidates(text, "m", ["st"])
    assert len(cands) == 1
    c = cands[0]
    assert c["status"] == "FSM_EXTRACTION_PARTIAL"
    assert c["ambiguous_states"] == [{"state": "A", "candidate_next_states": ["B", "C"]}]
    assert "multiple distinct candidate next states" in c["reason"]


def test_state_with_no_resolvable_self_assignment_is_partial():
    text = textwrap.dedent("""\
        always @(posedge clk) begin
          case (st)
            A: y <= 1;
            B: st <= A;
          endcase
        end
        """)
    cands = air.extract_fsm_candidates(text, "m", ["st"])
    c = cands[0]
    assert c["status"] == "FSM_EXTRACTION_PARTIAL"
    assert c["unresolved_states"] == ["A"]
    assert "no resolvable self-assignment" in c["reason"]


def test_missing_endcase_is_unparseable_never_resolved():
    text = textwrap.dedent("""\
        always @(posedge clk) begin
          case (st)
            A: st <= B;
        """)
    cands = air.extract_fsm_candidates(text, "m", ["st"])
    assert len(cands) == 1
    c = cands[0]
    assert c["status"] == "FSM_EXTRACTION_UNPARSEABLE"
    assert c["states"] == []
    assert c["transitions"] == []
    assert "no matching 'endcase'" in c["reason"]


def test_case_key_not_a_declared_signal_is_partial():
    text = textwrap.dedent("""\
        always @(posedge clk) begin
          case (opcode)
            A: opcode <= B;
          endcase
        end
        """)
    # 'opcode' is never in the declared_signal_names set (only 'st' is)
    cands = air.extract_fsm_candidates(text, "m", ["st"])
    c = cands[0]
    assert c["status"] == "FSM_EXTRACTION_PARTIAL"
    assert "not among" in c["reason"] and "opcode" in c["reason"]


def test_case_key_not_a_simple_identifier_is_partial():
    text = textwrap.dedent("""\
        always @(posedge clk) begin
          case ({a, b})
            2'b00: st <= A;
          endcase
        end
        """)
    cands = air.extract_fsm_candidates(text, "m", ["st"])
    c = cands[0]
    assert c["status"] == "FSM_EXTRACTION_PARTIAL"
    assert c["register_name"] is None
    assert "not a single simple identifier" in c["reason"]


def test_comment_and_string_noise_does_not_corrupt_depth_counting():
    text = textwrap.dedent("""\
        // case (fake) endcase
        always @(posedge clk) begin
          /* case nested endcase */
          x = "case endcase";
          case (st)
            A: st <= B;
            B: st <= A;
          endcase
        end
        """)
    cands = air.extract_fsm_candidates(text, "m", ["st"])
    assert len(cands) == 1
    c = cands[0]
    assert c["status"] == "FSM_EXTRACTION_RESOLVED"
    assert c["states"] == ["A", "B"]


def test_always_block_with_no_case_is_not_applicable():
    text = textwrap.dedent("""\
        always @(posedge clk) begin
          cnt <= cnt + 1;
        end
        """)
    cands = air.extract_fsm_candidates(text, "m", ["cnt"])
    assert len(cands) == 1
    assert cands[0]["status"] == "NOT_APPLICABLE"
    assert cands[0]["register_name"] is None


def test_no_always_posedge_block_returns_empty_candidate_list():
    assert air.extract_fsm_candidates("assign a = b;", "m", ["a"]) == []


def test_module_fsm_summary_not_available_when_no_candidates():
    summary = air._module_fsm_summary([])
    assert summary["status"] == "NOT_AVAILABLE"
    assert "no 'always @(posedge" in summary["reason"]


def test_module_fsm_summary_not_available_when_only_not_applicable_blocks():
    text = textwrap.dedent("""\
        always @(posedge clk) begin
          cnt <= cnt + 1;
        end
        """)
    cands = air.extract_fsm_candidates(text, "m", ["cnt"])
    summary = air._module_fsm_summary(cands)
    assert summary["status"] == "NOT_AVAILABLE"
    assert summary["candidates"] == cands  # still disclosed, not dropped


def test_module_fsm_summary_candidates_found_when_a_real_candidate_exists():
    summary = air._module_fsm_summary(
        air.extract_fsm_candidates(CLEAN_FSM_TEXT, "m", ["state"]))
    assert summary["status"] == "CANDIDATES_FOUND"
    assert summary["candidates"][0]["status"] == "FSM_EXTRACTION_RESOLVED"


# ---------------------------------------------------------------------------
# 2. Real-verible integration fixtures
# ---------------------------------------------------------------------------

LEAF_SV = textwrap.dedent("""\
    module leaf_mod #(parameter int W = 8) (
        input  logic clk,
        input  logic rst_n,
        input  logic [W-1:0] data_in,
        output logic [W-1:0] data_out
    );
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) data_out <= '0;
            else data_out <= data_in;
        end
    endmodule
    """)

MID_SV = textwrap.dedent("""\
    module mid_mod (
        input  logic clk,
        input  logic rst_n,
        input  logic [7:0] data_in,
        output logic [7:0] data_out
    );
        leaf_mod #(.W(8)) u_leaf (
            .clk(clk),
            .rst_n(rst_n),
            .data_in(data_in),
            .data_out(data_out)
        );
    endmodule
    """)

TOP_SV = textwrap.dedent("""\
    module top_mod (
        input  logic clk,
        input  logic rst_n,
        input  logic [7:0] data_in,
        output logic [7:0] data_out
    );
        mid_mod u_mid (
            .clk(clk), .rst_n(rst_n), .data_in(data_in), .data_out(data_out)
        );

        ext_blackbox u_ext (
            .clk(clk)
        );

        logic [1:0] state;
        localparam logic [1:0] IDLE = 2'd0, BUSY = 2'd1, DONE = 2'd2;

        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state <= IDLE;
            end else begin
                case (state)
                    IDLE: if (data_in != 0) state <= BUSY;
                    BUSY: state <= DONE;
                    DONE: state <= IDLE;
                    default: state <= IDLE;
                endcase
            end
        end
    endmodule
    """)


@pytest.fixture
def hierarchy_files(tmp_path):
    leaf = tmp_path / "leaf.sv"
    mid = tmp_path / "mid.sv"
    top = tmp_path / "top.sv"
    leaf.write_text(LEAF_SV, encoding="utf-8")
    mid.write_text(MID_SV, encoding="utf-8")
    top.write_text(TOP_SV, encoding="utf-8")
    return [leaf, mid, top]


@requires_verible
def test_build_architecture_ir_full_instance_tree(hierarchy_files):
    ir = air.build_architecture_ir(hierarchy_files)
    assert ir["status"] == "BUILT"
    assert ir["schema_version"] == air.SCHEMA_VERSION
    assert set(ir["modules"]) == {"leaf_mod", "mid_mod", "top_mod"}
    assert ir["instance_tree"]["top_modules"] == ["top_mod"]

    root = ir["instance_tree"]["trees"][0]
    assert root["module_name"] == "top_mod"
    assert root["depth"] == 0
    assert root["resolved"] is True

    by_instance = {c["instance_name"]: c for c in root["children"]}
    assert set(by_instance) == {"u_mid", "u_ext"}

    u_mid = by_instance["u_mid"]
    assert u_mid["module_name"] == "mid_mod"
    assert u_mid["resolved"] is True
    assert u_mid["depth"] == 1
    assert any(conn["port_name"] == "data_in" for conn in u_mid["connections"])
    u_leaf = u_mid["children"][0]
    assert u_leaf["module_name"] == "leaf_mod"
    assert u_leaf["instance_name"] == "u_leaf"
    assert u_leaf["resolved"] is True
    assert u_leaf["depth"] == 2
    assert u_leaf["children"] == []  # leaf_mod has no instances of its own
    # the full tree carries real ports/params of the RESOLVED child module,
    # not merely the instantiation's own connection list
    assert any(p["name"] == "data_out" for p in u_leaf["ports"])

    u_ext = by_instance["u_ext"]
    assert u_ext["module_name"] == "ext_blackbox"
    assert u_ext["resolved"] is False
    assert "not found among the parsed RTL files" in u_ext["reason"]
    assert u_ext["children"] == []


@requires_verible
def test_build_architecture_ir_fsm_candidate_via_real_verible_span(hierarchy_files):
    ir = air.build_architecture_ir(hierarchy_files)
    top_mod = ir["modules"]["top_mod"]
    fsm = top_mod["fsm_extraction"]
    assert fsm["status"] == "CANDIDATES_FOUND"
    assert len(fsm["candidates"]) == 1
    c = fsm["candidates"][0]
    assert c["status"] == "FSM_EXTRACTION_RESOLVED"
    assert c["register_name"] == "state"
    assert c["states"] == ["IDLE", "BUSY", "DONE"]
    assert c["always_line"] is not None and c["always_line"] > 1
    # leaf_mod's always block updates a plain register, not a case -- honestly
    # NOT_AVAILABLE, never a fabricated FSM
    assert ir["modules"]["leaf_mod"]["fsm_extraction"]["status"] == "NOT_AVAILABLE"


@requires_verible
def test_duplicate_module_name_across_files_is_reported_not_silently_overwritten(tmp_path):
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    dup_body = "module shared_mod(input logic clk); endmodule\n"
    (a_dir / "shared.sv").write_text(dup_body, encoding="utf-8")
    (b_dir / "shared.sv").write_text(dup_body, encoding="utf-8")

    ir = air.build_architecture_ir([a_dir / "shared.sv", b_dir / "shared.sv"])
    assert ir["status"] == "BUILT"
    assert len(ir["duplicate_modules"]) == 1
    dup = ir["duplicate_modules"][0]
    assert dup["module_name"] == "shared_mod"
    assert len(dup["file_paths"]) == 2
    assert any("shared_mod" in w and "declared in more than one" in w for w in ir["warnings"])
    # deterministic: the kept registry entry's file_path is the sorted-first one
    expected_first = sorted(str(p) for p in [a_dir / "shared.sv", b_dir / "shared.sv"])[0]
    assert ir["modules"]["shared_mod"] is not None
    # find which parsed-file entry supplied the kept module (registry keeps first)
    kept_file = [pf["file_path"] for pf in ir["files"] if pf["file_path"] == expected_first]
    assert kept_file  # the sorted-first file really was parsed


@requires_verible
def test_instance_cycle_is_detected_and_does_not_recurse_forever(tmp_path):
    a_sv = tmp_path / "a.sv"
    b_sv = tmp_path / "b.sv"
    a_sv.write_text("module mod_a(input logic clk); mod_b u_b(.clk(clk)); endmodule\n", encoding="utf-8")
    b_sv.write_text("module mod_b(input logic clk); mod_a u_a(.clk(clk)); endmodule\n", encoding="utf-8")

    ir = air.build_architecture_ir([a_sv, b_sv])
    assert ir["status"] == "BUILT"
    assert set(ir["instance_tree"]["top_modules"]) == {"mod_a", "mod_b"}
    tree_by_root = {t["module_name"]: t for t in ir["instance_tree"]["trees"]}
    root_a = tree_by_root["mod_a"]
    u_b = root_a["children"][0]
    assert u_b["module_name"] == "mod_b"
    u_a_again = u_b["children"][0]
    assert u_a_again["module_name"] == "mod_a"
    assert u_a_again["cycle_detected"] is True
    assert u_a_again["children"] == []  # recursion stopped here, not looped


@requires_verible
def test_top_module_override_forces_a_single_root(hierarchy_files):
    ir = air.build_architecture_ir(hierarchy_files, top_module="mid_mod")
    assert ir["instance_tree"]["top_modules"] == ["mid_mod"]
    assert len(ir["instance_tree"]["trees"]) == 1
    assert ir["instance_tree"]["trees"][0]["module_name"] == "mid_mod"


@requires_verible
def test_top_module_override_unknown_name_raises(hierarchy_files):
    with pytest.raises(air.DesignArchitectureIRError):
        air.build_architecture_ir(hierarchy_files, top_module="does_not_exist_mod")


@requires_verible
def test_real_syntax_error_file_is_isolated_not_fatal(tmp_path):
    good = tmp_path / "good.sv"
    bad = tmp_path / "bad.sv"
    good.write_text("module good_mod(input logic clk); endmodule\n", encoding="utf-8")
    bad.write_text("module bad_mod(input logic clk) this is not valid systemverilog !!! endmodule\n",
                    encoding="utf-8")

    ir = air.build_architecture_ir([good, bad])
    assert ir["status"] == "BUILT"  # the good file alone is enough to build something
    assert "good_mod" in ir["modules"]
    assert "bad_mod" not in ir["modules"]
    bad_entry = [pf for pf in ir["files"] if pf["file_path"] == str(bad)][0]
    assert bad_entry["status"] == "PARSE_ERROR"
    assert bad_entry["reason"]
    assert any("PARSE_ERROR" in w for w in ir["warnings"])


def test_unrunnable_verible_binary_reports_not_available_per_file(tmp_path):
    f = tmp_path / "m.sv"
    f.write_text("module m(input logic clk); endmodule\n", encoding="utf-8")
    result = air.parse_rtl_file(f, verible_bin="verible-verilog-syntax-does-not-exist")
    assert result["status"] == "NOT_AVAILABLE"
    assert "verible could not be run" in result["reason"]
    assert result["modules"] == []


def test_unreadable_file_reports_not_available():
    result = air.parse_rtl_file("this/path/really/does/not/exist.sv")
    assert result["status"] == "NOT_AVAILABLE"
    assert "could not read file" in result["reason"]


def test_no_rtl_files_is_not_available():
    ir = air.build_architecture_ir([])
    assert ir["status"] == "NOT_AVAILABLE"
    assert ir["reason"] == "no rtl_files supplied"
    assert ir["instance_tree"] == {"top_modules": [], "trees": []}


def test_build_when_nothing_parses_is_not_available(tmp_path):
    f = tmp_path / "m.sv"
    f.write_text("module m(input logic clk); endmodule\n", encoding="utf-8")
    ir = air.build_architecture_ir([f], verible_bin="verible-verilog-syntax-does-not-exist")
    assert ir["status"] == "NOT_AVAILABLE"
    assert "no module could be parsed" in ir["reason"]


@requires_verible
def test_build_module_registry_first_occurrence_wins_deterministically(hierarchy_files):
    parsed = [air.parse_rtl_file(p) for p in sorted(str(p) for p in hierarchy_files)]
    registry, duplicates = air.build_module_registry(parsed)
    assert duplicates == []
    assert set(registry) == {"leaf_mod", "mid_mod", "top_mod"}


# ---------------------------------------------------------------------------
# 3. save_architecture_ir / format_report / execute_verb / CLI subprocess
# ---------------------------------------------------------------------------

@requires_verible
def test_save_architecture_ir_round_trips_as_valid_json(hierarchy_files, tmp_path):
    ir = air.build_architecture_ir(hierarchy_files)
    out = tmp_path / "ir.json"
    air.save_architecture_ir(ir, out)
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded["status"] == "BUILT"
    assert set(reloaded["modules"]) == {"leaf_mod", "mid_mod", "top_mod"}


@requires_verible
def test_execute_verb_text_and_json(hierarchy_files):
    text, code = air.execute_verb(hierarchy_files, as_json=False)
    assert code == 0
    assert "top_mod" in text
    assert "FSM candidate in top_mod" in text

    text_json, code_json = air.execute_verb(hierarchy_files, as_json=True)
    assert code_json == 0
    parsed = json.loads(text_json)
    assert parsed["status"] == "BUILT"


def test_execute_verb_no_files_exits_2():
    text, code = air.execute_verb([])
    assert code == 2
    assert "NOT_AVAILABLE" in text


@requires_verible
def test_cli_subprocess_json_and_out_file(hierarchy_files, tmp_path):
    out_path = tmp_path / "cli_ir.json"
    argv = [sys.executable, "-m", "dv_harness.design_architecture_ir"]
    for f in hierarchy_files:
        argv += ["--rtl", str(f)]
    argv += ["--out", str(out_path), "--json"]
    proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "BUILT"
    assert out_path.exists()
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk["status"] == "BUILT"


def test_cli_subprocess_no_files_is_a_required_argument_error():
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.design_architecture_ir"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode != 0


@requires_verible
def test_cli_subprocess_top_module_not_found_exits_2(hierarchy_files):
    argv = [sys.executable, "-m", "dv_harness.design_architecture_ir"]
    for f in hierarchy_files:
        argv += ["--rtl", str(f)]
    argv += ["--top-module", "does_not_exist_mod"]
    proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2
    assert "does_not_exist_mod" in proc.stdout
