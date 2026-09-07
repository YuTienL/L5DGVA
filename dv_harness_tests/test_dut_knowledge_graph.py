"""Tests for dv_harness/dut_knowledge_graph.py -- the DUT-fact Design
Knowledge Graph built ONLY from real, already-real extractor output
(`design_architecture_ir.py`, `register_rtl_trace.py`,
`interrupt_dma_clock_reset_extraction.py`, `phy_model_behavior_ir.py`).

Two independent kinds of test, mirroring this project's own established
discipline for a module built on top of the real verible front end:

  1. Pure, no-verible-needed unit tests directly against the graph/ingestion
     primitives (node/edge identity, honest-absence handling, malformed-
     input refusals).
  2. A full real-integration test driving all four real extractors over a
     small, synthetic (never real-project) multi-file RTL fixture plus a
     synthetic offline-distilled PHY spec fixture, proving every node kind
     and every edge kind this module declares is reachable from real,
     citable evidence -- and that a genuine cross-source ambiguity
     (two modules declared in one file) is reported honestly rather than
     resolved by a guess. Skipped (never faked) on a machine with no real
     `verible-verilog-syntax` on PATH.
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
from dv_harness import dut_knowledge_graph as dkg
from dv_harness import interrupt_dma_clock_reset_extraction as idcre
from dv_harness import phy_boundary
from dv_harness import phy_model_behavior_ir as pmbi
from dv_harness import register_rtl_trace as rt
from dv_harness import vip_user_guide_distill as ugd

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

MODULE_PATH = "dv_harness.dut_knowledge_graph"

# ---------------------------------------------------------------------------
# 1. Pure unit tests over the graph/ingestion primitives -- no verible needed
# ---------------------------------------------------------------------------


def test_add_node_is_idempotent_and_merges_attrs_and_provenance():
    g = dkg.DutKnowledgeGraph()
    g.add_node("A", dkg.NODE_RTL_MODULE, provenance={"p": 1}, name="a", extra=None)
    g.add_node("A", dkg.NODE_RTL_MODULE, provenance={"p": 2}, port_count=3)
    node = g.node("A")
    assert node["kind"] == dkg.NODE_RTL_MODULE
    assert node["attrs"] == {"name": "a", "port_count": 3}
    assert node["provenance"] == [{"p": 1}, {"p": 2}]


def test_add_node_kind_collision_raises():
    g = dkg.DutKnowledgeGraph()
    g.add_node("A", dkg.NODE_RTL_MODULE)
    with pytest.raises(dkg.DutKnowledgeGraphError):
        g.add_node("A", dkg.NODE_REGISTER_FIELD)


def test_add_edge_is_idempotent_and_accumulates_evidence():
    g = dkg.DutKnowledgeGraph()
    g.add_node("A", dkg.NODE_RTL_MODULE)
    g.add_node("B", dkg.NODE_RTL_MODULE)
    g.add_edge("A", "B", dkg.EDGE_INSTANTIATES, evidence={"instance_name": "u1"})
    g.add_edge("A", "B", dkg.EDGE_INSTANTIATES, evidence={"instance_name": "u2"})
    g.add_edge("A", "B", dkg.EDGE_INSTANTIATES, evidence={"instance_name": "u1"})  # exact dup
    edges = g.edges(dkg.EDGE_INSTANTIATES)
    assert len(edges) == 1
    assert edges[0]["evidence"] == [{"instance_name": "u1"}, {"instance_name": "u2"}]


def test_neighbors_direction_and_edge_kind_filtering():
    g = dkg.DutKnowledgeGraph()
    for n in ("A", "B", "C"):
        g.add_node(n, dkg.NODE_RTL_MODULE)
    g.add_edge("A", "B", dkg.EDGE_INSTANTIATES)
    g.add_edge("A", "C", dkg.EDGE_DECLARED_IN_FILE)
    assert g.neighbors("A", dkg.EDGE_INSTANTIATES, "out") == ["B"]
    assert g.neighbors("B", dkg.EDGE_INSTANTIATES, "in") == ["A"]
    assert g.neighbors("A", direction="out") == ["B", "C"]
    with pytest.raises(dkg.DutKnowledgeGraphError):
        g.neighbors("A", direction="sideways")


def test_no_sources_supplied_yields_an_empty_graph_and_no_sources_used():
    g = dkg.build_dut_knowledge_graph()
    assert g.stats()["total_nodes"] == 0
    assert g.stats()["total_edges"] == 0
    assert not any(g.sources_used.values())


def test_architecture_ir_not_built_contributes_nothing_and_is_noted():
    g = dkg.build_dut_knowledge_graph(
        architecture_ir={"status": "NOT_AVAILABLE", "reason": "no rtl_files supplied"})
    assert g.nodes(dkg.NODE_RTL_MODULE) == []
    assert g.sources_used["architecture_ir"] is False
    assert any("not BUILT" in n for n in g.notes)


def test_register_trace_result_with_no_field_identity_is_skipped_not_guessed():
    g = dkg.DutKnowledgeGraph()
    dkg._ingest_register_trace_results(g, [
        {"field": None, "field_name": None, "status": "BLOCKED", "reason": "x", "candidates": []},
    ])
    assert g.nodes(dkg.NODE_REGISTER_FIELD) == []
    assert any("no real field identity" in n for n in g.notes)
    assert g.sources_used["register_trace_results"] is True


def test_register_trace_results_rejects_a_non_dict_non_dataclass_entry():
    with pytest.raises(dkg.DutKnowledgeGraphError):
        dkg.build_dut_knowledge_graph(register_trace_results=[123])


def test_traceability_gap_report_not_applicable_with_no_register_facts():
    g = dkg.build_dut_knowledge_graph()
    report = g.traceability_gap_report()
    assert report["status"] == "NOT_APPLICABLE"


def test_traceability_gap_report_fully_traced_when_every_field_confirmed():
    g = dkg.DutKnowledgeGraph()
    dkg._ingest_register_trace_results(g, [
        {"field": "BLK.REG.f1", "field_name": "f1", "status": "TRACE_CONFIRMED",
         "candidates": [{"module": "m1", "kind": "port", "name": "f1", "referenced": True,
                          "direction": "input", "file_path": "m1.sv",
                          "match_kind": "EXACT", "reference_evidence": []}]},
    ])
    report = g.traceability_gap_report()
    assert report["status"] == "FULLY_TRACED"
    assert report["register_count"] == 1
    assert report["unresolved_register_ids"] == []


def test_interrupt_facet_not_loaded_reports_honest_note_and_no_nodes():
    g = dkg.build_dut_knowledge_graph(
        interrupt_dma_clock_reset_doc={
            "interrupt_architecture": {"status": "NOT_AVAILABLE", "reason": "nothing found"},
            "clock_reset_extension": {"status": "NOT_AVAILABLE", "reason": "nothing found"},
        })
    assert g.nodes(dkg.NODE_INTERRUPT) == []
    assert g.nodes(dkg.NODE_CLOCK) == []
    assert g.sources_used["interrupt_dma_clock_reset_doc"] is False
    assert len(g.notes) == 2


def test_declared_in_file_no_match_leaves_the_fact_node_orphaned_honestly():
    doc = {
        "interrupt_architecture": {
            "status": "LOADED",
            "sources": [{"name": "irq_x", "direction": "input", "width": None,
                         "description": None, "evidence": "/nowhere/unrelated.sv:5"}],
        },
        "clock_reset_extension": {"status": "NOT_AVAILABLE", "reason": "n/a"},
    }
    g = dkg.build_dut_knowledge_graph(
        architecture_ir={"status": "BUILT", "reason": None,
                          "files": [{"status": "PARSED", "file_path": "/elsewhere/top.sv",
                                     "modules": [{"name": "top"}]}],
                          "modules": {"top": {"ports": [], "parameters": []}},
                          "instance_tree": {"top_modules": ["top"], "trees": []}},
        interrupt_dma_clock_reset_doc=doc,
    )
    interrupt_nodes = g.nodes(dkg.NODE_INTERRUPT)
    assert len(interrupt_nodes) == 1
    assert g.neighbors(interrupt_nodes[0]["id"], dkg.EDGE_DECLARED_IN_FILE, "out") == []


def test_phy_boundary_edges_never_added_when_module_not_in_the_same_registry():
    # A PHY doc naming real boundary module names, but built with NO
    # architecture_ir at all -- module_names is empty, so this module must
    # never guess that "phy"/"ctrl" are real RTL_MODULE nodes.
    doc = {
        "disclosure": "not silicon",
        "boundary_context": {"available": True, "phy_module": "phy", "controller_module": "ctrl",
                              "mount_layer": "phy_serial_io", "classification_kind": "PARALLEL",
                              "bindable": True},
        "training_link_startup_stages": {
            "status": "FOUND",
            "items": [{"name": "DETECT", "evidence_text": "DETECT: x",
                       "citation": {"document": "d", "fulltext_path": "d.txt", "line": 1}}],
        },
        "tx_capabilities": {"status": "NOT_AVAILABLE", "reason": "n/a", "items": []},
        "rx_capabilities": {"status": "NOT_AVAILABLE", "reason": "n/a", "items": []},
        "power_states": {"status": "NOT_AVAILABLE", "reason": "n/a", "items": []},
    }
    g = dkg.build_dut_knowledge_graph(phy_model_behavior_doc=doc)
    assert len(g.nodes(dkg.NODE_PHY_TRAINING_STAGE)) == 1
    assert g.edges(dkg.EDGE_DESCRIBES_PHY_BOUNDARY_OF) == []
    assert g.sources_used["phy_model_behavior_doc"] is True


def test_phy_boundary_unavailable_context_never_fabricates_an_edge():
    doc = {
        "disclosure": "not silicon",
        "boundary_context": {"available": False, "reason": "no phy_boundary.json supplied",
                              "phy_module": None, "controller_module": None,
                              "boundary_status": None, "classification_kind": None,
                              "mount_layer": None, "bindable": None},
        "training_link_startup_stages": {"status": "NOT_AVAILABLE", "reason": "n/a", "items": []},
        "tx_capabilities": {
            "status": "FOUND",
            "items": [{"evidence_text": "high swing", "citation": {
                "document": "d", "fulltext_path": "d.txt", "line": 3}}],
        },
        "rx_capabilities": {"status": "NOT_AVAILABLE", "reason": "n/a", "items": []},
        "power_states": {"status": "NOT_AVAILABLE", "reason": "n/a", "items": []},
    }
    g = dkg.build_dut_knowledge_graph(phy_model_behavior_doc=doc)
    assert len(g.nodes(dkg.NODE_PHY_TX_CAPABILITY)) == 1
    assert g.edges(dkg.EDGE_DESCRIBES_PHY_BOUNDARY_OF) == []


def test_evidence_file_part_strips_line_number_including_windows_drive_letters():
    assert dkg._evidence_file_part("C:\\proj\\phy.sv:42") == "C:\\proj\\phy.sv"
    assert dkg._evidence_file_part("/proj/phy.sv:42") == "/proj/phy.sv"
    assert dkg._evidence_file_part("/proj/phy.sv:10-12") == "/proj/phy.sv"
    assert dkg._evidence_file_part(None) is None


def test_to_dict_is_json_serializable_and_sorted():
    g = dkg.DutKnowledgeGraph()
    g.add_node("Z", dkg.NODE_RTL_MODULE)
    g.add_node("A", dkg.NODE_RTL_MODULE)
    g.add_edge("Z", "A", dkg.EDGE_INSTANTIATES)
    out = g.to_dict()
    assert [n["id"] for n in out["nodes"]] == ["A", "Z"]
    json.dumps(out)  # must not raise


# ---------------------------------------------------------------------------
# 2. Full real-integration test -- all four real extractors, one small
#    synthetic multi-file RTL corpus plus a synthetic PHY spec fixture.
# ---------------------------------------------------------------------------

# phy_ctrl + sub_block share ONE file (deliberately, to exercise the honest
# "ambiguous_multi_module_file" DECLARED_IN_FILE case): phy_ctrl is the top,
# instantiates sub_block; phy_irq is a real interrupt-named port; the
# always block gives a real clock (clk) + async reset (rst_n); phy_reset_n
# is a plain port (always TRACE_CONFIRMED by register_rtl_trace's own rule);
# dead_reg is a declared-but-unused internal signal (TRACE_PARTIAL negative
# control).
PHY_CTRL_RTL = textwrap.dedent("""\
    module phy_ctrl (
        input  logic clk,
        input  logic rst_n,
        output logic phy_irq,
        input  logic phy_reset_n
    );

        logic irq_pending;
        logic dead_reg;

        assign phy_irq = irq_pending;

        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                irq_pending <= 1'b0;
            end else begin
                irq_pending <= phy_reset_n;
            end
        end

        sub_block u_sub (
            .clk         (clk),
            .some_signal (phy_reset_n)
        );

    endmodule

    module sub_block (
        input logic clk,
        input logic some_signal
    );
    endmodule
""")

# A SEPARATE single-module file, to exercise the honest "unique" (never
# ambiguous) DECLARED_IN_FILE case for one real clock.
CLK_GEN_RTL = textwrap.dedent("""\
    module clk_gen (
        input  logic ref_clk,
        output logic sys_clk
    );

        logic toggle;

        always @(posedge ref_clk) begin
            toggle <= ~toggle;
        end

        assign sys_clk = toggle;

    endmodule
""")

PHY_SPEC_TEXT = textwrap.dedent("""\
    1.0 Overview

    This is a synthetic PHY specification test fixture for
    test_dut_knowledge_graph.py. It is not real protocol content and
    describes no real vendor IP.

    4.1 Link Training States

    - DETECT: initial state after reset

    4.2 Transmitter Characteristics

    - Supports differential output swing of 800mV to 1200mV typical

    4.3 Receiver Characteristics

    - Provides continuous time linear equalization (CTLE)

    4.4 Power Management States

    P0: fully powered, active link
    """)


@pytest.fixture()
def rtl_files(tmp_path):
    phy_ctrl = tmp_path / "phy_ctrl.sv"
    phy_ctrl.write_text(PHY_CTRL_RTL, encoding="utf-8")
    clk_gen = tmp_path / "clk_gen.sv"
    clk_gen.write_text(CLK_GEN_RTL, encoding="utf-8")
    return [str(phy_ctrl), str(clk_gen)]


@pytest.fixture()
def distilled_phy_doc(tmp_path):
    src = tmp_path / "synthetic_phy_spec.txt"
    src.write_text(PHY_SPEC_TEXT, encoding="utf-8")
    return ugd.distill_user_guide(src, tmp_path / "distilled",
                                   title="Synthetic PHY Spec (dut_knowledge_graph)",
                                   doc_kind="protocol_spec")


def _build_full_graph(rtl_files, distilled_phy_doc):
    architecture_ir = air.build_architecture_ir(rtl_files)
    assert architecture_ir["status"] == "BUILT"

    fr_confirmed = rt.field_ref_from_dict({"name": "phy_reset_n", "register": "CTRL0", "block": "PHY"})
    fr_partial = rt.field_ref_from_dict({"name": "dead_reg", "register": "DBG0", "block": "PHY"})
    fr_not_found = rt.field_ref_from_dict({"name": "totally_unrelated_field_xyz",
                                            "register": "NOPE", "block": "PHY"})
    trace_results = rt.trace_register_fields(
        [fr_confirmed, fr_partial, fr_not_found], corpus=architecture_ir["files"])

    interrupt_doc = idcre.extract_interrupt_dma_clock_reset(rtl_files)
    assert interrupt_doc["status"] == "LOADED"

    boundary_doc = phy_boundary.extract_phy_boundary(
        [
            {"name": "phy_ctrl", "ports": [
                {"name": "pclk", "direction": "input", "data_type": "logic"},
                {"name": "pipe_txdata", "direction": "input", "data_type": "logic [31:0]"},
                {"name": "pipe_rxdata", "direction": "output", "data_type": "logic [31:0]"},
            ]},
            {"name": "sub_block", "ports": [
                {"name": "pclk", "direction": "input", "data_type": "logic"},
                {"name": "pipe_txdata", "direction": "output", "data_type": "logic [31:0]"},
                {"name": "pipe_rxdata", "direction": "input", "data_type": "logic [31:0]"},
            ]},
        ],
        "phy_ctrl", "sub_block",
    )
    assert boundary_doc["status"] == "EXTRACTED"

    phy_doc = pmbi.extract_phy_model_behavior_ir(
        reference_record=distilled_phy_doc, phy_boundary_doc=boundary_doc)
    assert phy_doc["status"] == "EXTRACTED"

    graph = dkg.build_dut_knowledge_graph(
        architecture_ir=architecture_ir,
        register_trace_results=trace_results,
        interrupt_dma_clock_reset_doc=interrupt_doc,
        phy_model_behavior_doc=phy_doc,
    )
    return graph, architecture_ir


@requires_verible
def test_full_graph_every_source_consulted(rtl_files, distilled_phy_doc):
    graph, _ = _build_full_graph(rtl_files, distilled_phy_doc)
    assert all(graph.sources_used.values())


@requires_verible
def test_rtl_modules_and_instantiates_edge(rtl_files, distilled_phy_doc):
    graph, _ = _build_full_graph(rtl_files, distilled_phy_doc)
    module_names = {n["attrs"]["name"] for n in graph.nodes(dkg.NODE_RTL_MODULE)}
    assert module_names == {"phy_ctrl", "sub_block", "clk_gen"}
    inst_edges = graph.edges(dkg.EDGE_INSTANTIATES)
    assert len(inst_edges) == 1
    e = inst_edges[0]
    assert e["source"] == dkg.module_node_id("phy_ctrl")
    assert e["target"] == dkg.module_node_id("sub_block")
    assert e["evidence"][0]["instance_name"] == "u_sub"


@requires_verible
def test_register_field_confirmed_traces_to_real_port(rtl_files, distilled_phy_doc):
    graph, _ = _build_full_graph(rtl_files, distilled_phy_doc)
    sites = graph.rtl_sites_for_register("PHY.CTRL0.phy_reset_n")
    assert sites["confirmed"] == [dkg.site_node_id("phy_ctrl", "port", "phy_reset_n")]
    site = graph.node(sites["confirmed"][0])
    assert site["attrs"]["module"] == "phy_ctrl"
    assert site["attrs"]["site_kind"] == "port"


@requires_verible
def test_register_field_partial_is_ambiguous_never_upgraded_to_confirmed(rtl_files, distilled_phy_doc):
    graph, _ = _build_full_graph(rtl_files, distilled_phy_doc)
    sites = graph.rtl_sites_for_register("PHY.DBG0.dead_reg")
    assert sites["confirmed"] == []
    assert sites["ambiguous"] == [dkg.site_node_id("phy_ctrl", "signal", "dead_reg")]
    site = graph.node(sites["ambiguous"][0])
    assert site["attrs"]["referenced"] is False


@requires_verible
def test_register_field_not_found_has_a_node_but_no_edge(rtl_files, distilled_phy_doc):
    graph, _ = _build_full_graph(rtl_files, distilled_phy_doc)
    node_id = dkg.register_field_node_id("PHY.NOPE.totally_unrelated_field_xyz")
    node = graph.node(node_id)
    assert node is not None
    assert node["attrs"]["trace_status"] == "TRACE_NOT_FOUND"
    assert graph.neighbors(node_id, direction="out") == []


@requires_verible
def test_traceability_gap_report_names_the_real_unresolved_fields(rtl_files, distilled_phy_doc):
    graph, _ = _build_full_graph(rtl_files, distilled_phy_doc)
    report = graph.traceability_gap_report()
    assert report["status"] == "GAPS_PRESENT"
    assert report["register_count"] == 3
    assert dkg.register_field_node_id("PHY.DBG0.dead_reg") in report["unresolved_register_ids"]
    assert dkg.register_field_node_id("PHY.NOPE.totally_unrelated_field_xyz") in report["unresolved_register_ids"]
    assert dkg.register_field_node_id("PHY.CTRL0.phy_reset_n") not in report["unresolved_register_ids"]


@requires_verible
def test_interrupt_declared_in_ambiguous_multi_module_file(rtl_files, distilled_phy_doc):
    graph, _ = _build_full_graph(rtl_files, distilled_phy_doc)
    interrupt_nodes = graph.nodes(dkg.NODE_INTERRUPT)
    assert len(interrupt_nodes) == 1
    assert interrupt_nodes[0]["attrs"]["name"] == "phy_irq"
    targets = graph.neighbors(interrupt_nodes[0]["id"], dkg.EDGE_DECLARED_IN_FILE, "out")
    assert set(targets) == {dkg.module_node_id("phy_ctrl"), dkg.module_node_id("sub_block")}
    edge = graph.edges(dkg.EDGE_DECLARED_IN_FILE)
    matched = [e for e in edge if e["source"] == interrupt_nodes[0]["id"]]
    for e in matched:
        assert e["evidence"][0]["file_match"] == "ambiguous_multi_module_file"
        assert e["evidence"][0]["candidate_module_count"] == 2
    assert set(graph.interrupts_in_module("phy_ctrl")) == {interrupt_nodes[0]["id"]}
    assert set(graph.interrupts_in_module("sub_block")) == {interrupt_nodes[0]["id"]}


@requires_verible
def test_clock_declared_in_unique_single_module_file(rtl_files, distilled_phy_doc):
    graph, _ = _build_full_graph(rtl_files, distilled_phy_doc)
    ref_clk_id = dkg.clock_node_id("ref_clk")
    node = graph.node(ref_clk_id)
    assert node is not None
    targets = graph.neighbors(ref_clk_id, dkg.EDGE_DECLARED_IN_FILE, "out")
    assert targets == [dkg.module_node_id("clk_gen")]
    edge = [e for e in graph.edges(dkg.EDGE_DECLARED_IN_FILE) if e["source"] == ref_clk_id][0]
    assert edge["evidence"][0]["file_match"] == "unique"
    assert edge["evidence"][0]["candidate_module_count"] == 1
    assert graph.clocks_in_module("clk_gen") == [ref_clk_id]


@requires_verible
def test_reset_uses_clock_edge(rtl_files, distilled_phy_doc):
    graph, _ = _build_full_graph(rtl_files, distilled_phy_doc)
    reset_id = dkg.reset_node_id("rst_n")
    node = graph.node(reset_id)
    assert node is not None
    assert node["attrs"]["active_level"] == "LOW"
    assert node["attrs"]["synchronous"] is False
    assert graph.neighbors(reset_id, dkg.EDGE_RESET_USES_CLOCK, "out") == [dkg.clock_node_id("clk")]


@requires_verible
def test_phy_boundary_facts_describe_both_real_modules(rtl_files, distilled_phy_doc):
    graph, _ = _build_full_graph(rtl_files, distilled_phy_doc)
    described = graph.modules_describing_phy_boundary()
    assert described == sorted([dkg.module_node_id("phy_ctrl"), dkg.module_node_id("sub_block")])
    training = graph.nodes(dkg.NODE_PHY_TRAINING_STAGE)
    assert any(n["attrs"].get("name") == "DETECT" for n in training)
    tx = graph.nodes(dkg.NODE_PHY_TX_CAPABILITY)
    assert any("differential output swing" in (n["attrs"].get("evidence_text") or "") for n in tx)
    detect_node = next(n for n in training if n["attrs"].get("name") == "DETECT")
    roles = {e["evidence"][0]["role"] for e in graph.edges(dkg.EDGE_DESCRIBES_PHY_BOUNDARY_OF)
             if e["source"] == detect_node["id"]}
    assert roles == {"phy_module", "controller_module"}


@requires_verible
def test_stats_totals_match_real_node_and_edge_counts(rtl_files, distilled_phy_doc):
    graph, _ = _build_full_graph(rtl_files, distilled_phy_doc)
    stats = graph.stats()
    assert stats["total_nodes"] == len(graph.nodes())
    assert stats["total_edges"] == len(graph.edges())
    assert sum(stats["node_counts"].values()) == stats["total_nodes"]
    assert sum(stats["edge_counts"].values()) == stats["total_edges"]


@requires_verible
def test_to_dict_round_trips_through_json(rtl_files, distilled_phy_doc):
    graph, _ = _build_full_graph(rtl_files, distilled_phy_doc)
    payload = json.dumps(graph.to_dict(), default=str)
    reloaded = json.loads(payload)
    assert reloaded["sources_used"] == graph.sources_used


# ---------------------------------------------------------------------------
# 3. CLI
# ---------------------------------------------------------------------------

@requires_verible
def test_cli_builds_and_reports_over_real_files(tmp_path, rtl_files, distilled_phy_doc):
    architecture_ir = air.build_architecture_ir(rtl_files)
    fr = rt.field_ref_from_dict({"name": "phy_reset_n"})
    trace_results = [r.to_dict() for r in rt.trace_register_fields([fr], corpus=architecture_ir["files"])]
    interrupt_doc = idcre.extract_interrupt_dma_clock_reset(rtl_files)

    arch_path = tmp_path / "arch.json"
    arch_path.write_text(json.dumps(architecture_ir), encoding="utf-8")
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(trace_results), encoding="utf-8")
    irq_path = tmp_path / "irq.json"
    irq_path.write_text(json.dumps(interrupt_doc), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", MODULE_PATH,
         "--architecture-ir", str(arch_path),
         "--register-trace-results", str(trace_path),
         "--interrupt-dma-clock-reset", str(irq_path),
         "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["sources_used"]["architecture_ir"] is True
    assert payload["sources_used"]["register_trace_results"] is True
    assert payload["sources_used"]["interrupt_dma_clock_reset_doc"] is True
    assert payload["sources_used"]["phy_model_behavior_doc"] is False
    assert len(payload["nodes"]) > 0


def test_cli_with_no_arguments_exits_2():
    result = subprocess.run(
        [sys.executable, "-m", MODULE_PATH],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 2
    assert "no real source was supplied" in result.stderr


def test_cli_malformed_json_file_exits_2(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json{{{", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", MODULE_PATH, "--architecture-ir", str(bad)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 2
    assert "error:" in result.stderr


def test_cli_text_output_and_notes(tmp_path):
    arch = {"status": "NOT_AVAILABLE", "reason": "no rtl_files supplied", "files": [],
            "modules": {}, "duplicate_modules": [],
            "instance_tree": {"top_modules": [], "trees": []}, "warnings": []}
    # architecture_ir alone with status NOT_AVAILABLE contributes no nodes,
    # so sources_used stays all-False and the CLI must honestly refuse
    # rather than print an empty-but-successful report.
    arch_path = tmp_path / "arch.json"
    arch_path.write_text(json.dumps(arch), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", MODULE_PATH, "--architecture-ir", str(arch_path)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 2
    assert "no real source was supplied" in result.stderr
