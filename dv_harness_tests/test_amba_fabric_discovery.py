"""Tests for dv_harness/amba_fabric_discovery.py (AMBA-7..14) and for the
instantiation / port-connection / continuous-assign extraction added to
dv_harness/verible_parser.py to feed it.

Everything here runs against a REAL `verible-verilog-syntax` subprocess over a
synthetic multi-master / multi-slave AMBA4 SoC fabric written to a tmp dir --
never a hand-built graph object, because a hand-built graph would prove the
traversal works on the shape this test author imagined rather than on the shape
verible really produces. Skipped (never faked) without verible on PATH, the
same discipline test_verible_parser.py already follows.

The fixture is synthetic RTL for a test, and it is the ONLY place any bind-like
construct could legitimately live -- and it contains none. Per AMBA-30/AMBA-31,
this whole layer is discovery/planning: `test_no_bind_statement_is_ever_emitted`
asserts that of the module's own source and of every artifact it renders.

The fixture deliberately exercises all TEN of AMBA-14's termination states from
one design, because the states that matter most here are the unresolved ones:
a tracer proven only on a clean wrapper chain is exactly the "happy path only"
coverage this project has already been burned by.
"""
from __future__ import annotations

import re
import shutil
import textwrap

import pytest

from dv_harness import amba_fabric_discovery as afd
from dv_harness import connectivity
from dv_harness.amba_fabric_discovery import (
    FabricDiscoveryError,
    StructuralRole,
    TraceTerminationStatus,
    VipPlacementPriority,
    amba_bundle_prefix,
    assert_unresolved_states_explained,
    build_fabric_netlist,
    bundles_of,
    discovered_topology_ids,
    group_ports_into_amba_bundles,
    render_endpoint_trace_report,
    summarize_trace_terminations,
    trace_all_fabric_ports,
    trace_fabric_master_interface_to_slaves,
    trace_fabric_port,
    trace_fabric_slave_interface_to_masters,
)
from dv_harness.verible_parser import parse_file

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)


# ---------------------------------------------------------------------------
# Synthetic RTL fixture generation
#
# Signal sets are spelled out here rather than imported from connectivity.py on
# purpose: a fixture built from the same constants the classifier reads would
# pass even if both were wrong together. These are the AMBA4 spec signal names
# as an independent second statement of them.
# ---------------------------------------------------------------------------

#: 'req' = driven by the transaction initiator, 'rsp' = driven by the target.
AXI4_SIGNALS = {
    "AWVALID": "req", "AWADDR": "req", "AWID": "req", "AWLEN": "req",
    "AWSIZE": "req", "AWBURST": "req", "AWREADY": "rsp",
    "WVALID": "req", "WDATA": "req", "WLAST": "req", "WREADY": "rsp",
    "BVALID": "rsp", "BRESP": "rsp", "BID": "rsp", "BREADY": "req",
    "ARVALID": "req", "ARADDR": "req", "ARID": "req", "ARLEN": "req",
    "ARSIZE": "req", "ARBURST": "req", "ARREADY": "rsp",
    "RVALID": "rsp", "RDATA": "rsp", "RRESP": "rsp", "RID": "rsp",
    "RLAST": "rsp", "RREADY": "req",
}
APB4_SIGNALS = {
    "PADDR": "req", "PSEL": "req", "PENABLE": "req", "PWRITE": "req",
    "PWDATA": "req", "PSTRB": "req", "PPROT": "req",
    "PRDATA": "rsp", "PREADY": "rsp", "PSLVERR": "rsp",
}
AHB_LITE_SIGNALS = {
    "HADDR": "req", "HTRANS": "req", "HWRITE": "req", "HWDATA": "req",
    "HSIZE": "req", "HBURST": "req",
    "HRDATA": "rsp", "HREADY": "rsp", "HRESP": "rsp",
}


def _ports(prefix: str, signals: dict, side: str) -> list:
    """(direction, port_name) pairs. `side` is the role THIS module plays on
    this interface: 'initiator' drives the request signals out."""
    out = []
    for sig, kind in signals.items():
        if side == "initiator":
            direction = "output" if kind == "req" else "input"
        else:
            direction = "input" if kind == "req" else "output"
        out.append((direction, f"{prefix}{sig}"))
    return out


def _sv_module(name: str, ports: list, body: str = "") -> str:
    decls = ",\n    ".join(f"{d} logic {n}" for d, n in ports)
    return f"module {name} (\n    {decls}\n);\n{body}\nendmodule\n"


def _sv_inst(module: str, inst: str, conns: list) -> str:
    body = ",\n        ".join(f".{p}({n})" for p, n in conns)
    return f"    {module} {inst} (\n        {body}\n    );\n"


def _bundle_conns(prefix: str, signals: dict, net_prefix: str) -> list:
    return [(f"{prefix}{s}", f"{net_prefix}{s.lower()}") for s in signals]


def _bundle_nets(net_prefix: str, signals: dict) -> str:
    return "".join(f"    wire {net_prefix}{s.lower()};\n" for s in signals)


def write_fabric_fixture(tmp_path):
    """One synthetic AMBA4 SoC whose fabric ports collectively terminate in all
    ten AMBA-14 states. Returns the .sv path."""
    mods = []

    # --- AXI4 masters, one behind a transparent wrapper (P1/P2 ladder) ------
    mods.append(_sv_module("cpu_core", _ports("M_AXI_", AXI4_SIGNALS, "initiator")))
    mods.append(_sv_module(
        "cpu_wrapper", _ports("M_AXI_", AXI4_SIGNALS, "initiator"),
        _sv_inst("cpu_core", "u_cpu_core",
                 [(f"M_AXI_{s}", f"M_AXI_{s}") for s in AXI4_SIGNALS])))
    mods.append(_sv_module("dma_engine", _ports("M_AXI_", AXI4_SIGNALS, "initiator")))

    # --- AXI4 slaves --------------------------------------------------------
    mods.append(_sv_module("ddr_ctrl", _ports("S_AXI_", AXI4_SIGNALS, "target")))
    mods.append(_sv_module("sram_ctrl", _ports("S_AXI_", AXI4_SIGNALS, "target")))

    # --- a protocol-preserving register slice (AMBA-7 mid-path element) -----
    slice_body = "".join(
        f"    assign M_AXI_{s} = S_AXI_{s};\n" if k == "req"
        else f"    assign S_AXI_{s} = M_AXI_{s};\n"
        for s, k in AXI4_SIGNALS.items())
    mods.append(_sv_module(
        "axi_reg_slice",
        _ports("S_AXI_", AXI4_SIGNALS, "target") + _ports("M_AXI_", AXI4_SIGNALS, "initiator"),
        slice_body))

    # --- a real protocol bridge, AXI4 -> APB4 (AMBA-11) ---------------------
    mods.append(_sv_module(
        "axi_to_apb",
        _ports("S_AXI_", AXI4_SIGNALS, "target") + _ports("M_APB_", APB4_SIGNALS, "initiator"),
        "    assign M_APB_PADDR = S_AXI_AWADDR;\n"
        "    assign M_APB_PWDATA = S_AXI_WDATA;\n"
        "    assign S_AXI_RDATA = M_APB_PRDATA;\n"))
    mods.append(_sv_module("apb_periph", _ports("S_APB_", APB4_SIGNALS, "target")))

    # --- an AXI4 decoder feeding two slaves (AMBA-13 fan-out) ---------------
    dec_body = ("    assign M0_AXI_AWADDR = S_AXI_AWADDR;\n"
                "    assign M1_AXI_AWADDR = S_AXI_AWADDR;\n"
                "    assign M0_AXI_ARADDR = S_AXI_ARADDR;\n"
                "    assign M1_AXI_ARADDR = S_AXI_ARADDR;\n")
    mods.append(_sv_module(
        "axi_decoder",
        _ports("S_AXI_", AXI4_SIGNALS, "target")
        + _ports("M0_AXI_", AXI4_SIGNALS, "initiator")
        + _ports("M1_AXI_", AXI4_SIGNALS, "initiator"),
        dec_body))

    # --- an AHB-Lite mux fed by two masters (AMBA-12 fan-in) ----------------
    mux_body = ("    assign OUT_HADDR = SEL ? M0_HADDR : M1_HADDR;\n"
                "    assign OUT_HWDATA = SEL ? M0_HWDATA : M1_HWDATA;\n"
                "    assign M0_HRDATA = OUT_HRDATA;\n"
                "    assign M1_HRDATA = OUT_HRDATA;\n")
    mods.append(_sv_module(
        "ahb_mux",
        [("input", "SEL")]
        + _ports("M0_", AHB_LITE_SIGNALS, "target")
        + _ports("M1_", AHB_LITE_SIGNALS, "target")
        + _ports("OUT_", AHB_LITE_SIGNALS, "initiator"),
        mux_body))
    mods.append(_sv_module("ahb_cpu", _ports("M_", AHB_LITE_SIGNALS, "initiator")))
    mods.append(_sv_module("ahb_dbg", _ports("M_", AHB_LITE_SIGNALS, "initiator")))

    # --- a PARSED module with two AMBA bundles and no visible internal path.
    #     Its correspondence would live in procedural logic a syntax-level
    #     parse cannot see -> AMBIGUOUS, not guessed either way.
    mods.append(_sv_module(
        "mystery_bridge",
        _ports("S_AXI_", AXI4_SIGNALS, "target") + _ports("M_APB_", APB4_SIGNALS, "initiator")))

    # --- fabric-internal monitor, for the INTERNAL_ONLY case ----------------
    mods.append(_sv_module("fabric_internal_mon", _ports("S_AXI_", AXI4_SIGNALS, "target")))

    # --- the fabric itself --------------------------------------------------
    fabric_ports = (
        _ports("S00_AXI_", AXI4_SIGNALS, "target")     # <- cpu (wrapped)
        + _ports("S01_AXI_", AXI4_SIGNALS, "target")   # <- dma
        + _ports("S02_AXI_", AXI4_SIGNALS, "target")   # <- fabric-internal only
        + _ports("S03_AXI_", AXI4_SIGNALS, "target")   # <- top boundary (outside design)
        + _ports("S_AHB_", AHB_LITE_SIGNALS, "target")  # <- ahb mux (2 masters)
        + _ports("M00_AXI_", AXI4_SIGNALS, "initiator")  # -> reg slice -> ddr
        + _ports("M01_AXI_", AXI4_SIGNALS, "initiator")  # -> axi/apb bridge
        + _ports("M02_AXI_", AXI4_SIGNALS, "initiator")  # -> mystery_bridge
        + _ports("M03_AXI_", AXI4_SIGNALS, "initiator")  # -> opaque, unparsed
        + _ports("M04_AXI_", AXI4_SIGNALS, "initiator")  # -> decoder -> 2 srams
        + _ports("M05_AXI_", AXI4_SIGNALS, "initiator")  # -> unconnected
    )
    fabric_body = _sv_inst("fabric_internal_mon", "u_int_mon",
                           [(f"S_AXI_{s}", f"S02_AXI_{s}") for s in AXI4_SIGNALS])
    mods.append(_sv_module("axi_fabric", fabric_ports, fabric_body))

    # --- the SoC top --------------------------------------------------------
    net_groups = [
        ("cpu_axi_", AXI4_SIGNALS), ("dma_axi_", AXI4_SIGNALS),
        ("ddr_in_axi_", AXI4_SIGNALS), ("ddr_axi_", AXI4_SIGNALS),
        ("brg_axi_", AXI4_SIGNALS), ("apb_", APB4_SIGNALS),
        ("mys_axi_", AXI4_SIGNALS), ("opq_axi_", AXI4_SIGNALS),
        ("dec_axi_", AXI4_SIGNALS), ("sram0_axi_", AXI4_SIGNALS),
        ("sram1_axi_", AXI4_SIGNALS),
        ("ahb_out_", AHB_LITE_SIGNALS), ("ahb_m0_", AHB_LITE_SIGNALS),
        ("ahb_m1_", AHB_LITE_SIGNALS),
    ]
    top_body = "    wire mux_sel;\n"
    top_body += "".join(_bundle_nets(p, s) for p, s in net_groups)
    top_body += _sv_inst("cpu_wrapper", "u_cpu_wrap",
                         _bundle_conns("M_AXI_", AXI4_SIGNALS, "cpu_axi_"))
    top_body += _sv_inst("dma_engine", "u_dma",
                         _bundle_conns("M_AXI_", AXI4_SIGNALS, "dma_axi_"))
    top_body += _sv_inst("ahb_cpu", "u_ahb_cpu",
                         _bundle_conns("M_", AHB_LITE_SIGNALS, "ahb_m0_"))
    top_body += _sv_inst("ahb_dbg", "u_ahb_dbg",
                         _bundle_conns("M_", AHB_LITE_SIGNALS, "ahb_m1_"))
    top_body += _sv_inst(
        "ahb_mux", "u_ahb_mux",
        [("SEL", "mux_sel")]
        + _bundle_conns("M0_", AHB_LITE_SIGNALS, "ahb_m0_")
        + _bundle_conns("M1_", AHB_LITE_SIGNALS, "ahb_m1_")
        + _bundle_conns("OUT_", AHB_LITE_SIGNALS, "ahb_out_"))
    top_body += _sv_inst(
        "axi_fabric", "u_fabric",
        _bundle_conns("S00_AXI_", AXI4_SIGNALS, "cpu_axi_")
        + _bundle_conns("S01_AXI_", AXI4_SIGNALS, "dma_axi_")
        # straight onto soc_top's OWN boundary ports: the master is outside
        # the parsed design (SystemVerilog is case-sensitive, so these must be
        # the top port names verbatim, not a lower-cased net spelling).
        + [(f"S03_AXI_{s}", f"EXT_AXI_{s}") for s in AXI4_SIGNALS]
        + _bundle_conns("S_AHB_", AHB_LITE_SIGNALS, "ahb_out_")
        + _bundle_conns("M00_AXI_", AXI4_SIGNALS, "ddr_in_axi_")
        + _bundle_conns("M01_AXI_", AXI4_SIGNALS, "brg_axi_")
        + _bundle_conns("M02_AXI_", AXI4_SIGNALS, "mys_axi_")
        + _bundle_conns("M03_AXI_", AXI4_SIGNALS, "opq_axi_")
        + _bundle_conns("M04_AXI_", AXI4_SIGNALS, "dec_axi_"))
    top_body += _sv_inst(
        "axi_reg_slice", "u_axi_reg_slice",
        _bundle_conns("S_AXI_", AXI4_SIGNALS, "ddr_in_axi_")
        + _bundle_conns("M_AXI_", AXI4_SIGNALS, "ddr_axi_"))
    top_body += _sv_inst("ddr_ctrl", "u_ddr",
                         _bundle_conns("S_AXI_", AXI4_SIGNALS, "ddr_axi_"))
    top_body += _sv_inst(
        "axi_to_apb", "u_apb_bridge",
        _bundle_conns("S_AXI_", AXI4_SIGNALS, "brg_axi_")
        + _bundle_conns("M_APB_", APB4_SIGNALS, "apb_"))
    top_body += _sv_inst("apb_periph", "u_periph",
                         _bundle_conns("S_APB_", APB4_SIGNALS, "apb_"))
    top_body += _sv_inst("mystery_bridge", "u_mystery",
                         _bundle_conns("S_AXI_", AXI4_SIGNALS, "mys_axi_")
                         + [(f"M_APB_{s}", f"apb_unrouted_{s.lower()}") for s in APB4_SIGNALS])
    # opaque_ip is deliberately NEVER declared anywhere: an unparsed module.
    top_body += _sv_inst("opaque_ip", "u_opaque",
                         _bundle_conns("S_AXI_", AXI4_SIGNALS, "opq_axi_")
                         + [(f"M_APB_{s}", f"opq_apb_{s.lower()}") for s in APB4_SIGNALS])
    top_body += _sv_inst(
        "axi_decoder", "u_decoder",
        _bundle_conns("S_AXI_", AXI4_SIGNALS, "dec_axi_")
        + _bundle_conns("M0_AXI_", AXI4_SIGNALS, "sram0_axi_")
        + _bundle_conns("M1_AXI_", AXI4_SIGNALS, "sram1_axi_"))
    top_body += _sv_inst("sram_ctrl", "u_sram0",
                         _bundle_conns("S_AXI_", AXI4_SIGNALS, "sram0_axi_"))
    top_body += _sv_inst("sram_ctrl", "u_sram1",
                         _bundle_conns("S_AXI_", AXI4_SIGNALS, "sram1_axi_"))

    mods.append(_sv_module("soc_top", _ports("EXT_AXI_", AXI4_SIGNALS, "target"), top_body))

    path = tmp_path / "amba4_soc_fixture.sv"
    path.write_text("\n".join(mods), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def fabric_netlist(tmp_path_factory):
    if shutil.which(VERIBLE_BIN) is None:
        pytest.skip("verible-verilog-syntax not on PATH")
    sv = write_fabric_fixture(tmp_path_factory.mktemp("amba4"))
    result = parse_file(sv)
    return build_fabric_netlist([result], "soc_top")


FABRIC = ("u_fabric",)


def _trace(netlist, prefix):
    return trace_fabric_port(netlist, FABRIC, prefix)


# ---------------------------------------------------------------------------
# verible_parser: the raw connectivity data AMBA-7..14 consumes
# ---------------------------------------------------------------------------

@requires_verible
def test_verible_parser_extracts_instances_and_port_connections(tmp_path):
    src = textwrap.dedent("""\
        module leaf (input logic a, input logic b, output logic y);
        endmodule
        module top (input logic clk, input logic [3:0] bus, output logic out);
            wire mid;
            wire alias_net;
            assign alias_net = mid;
            assign out = alias_net & clk;
            leaf u_named (.a(bus[1]), .b(alias_net), .y(mid));
            leaf u_pos (bus[0], , mid);
        endmodule
        """)
    f = tmp_path / "wiring.sv"
    f.write_text(src, encoding="utf-8")
    modules = {m.name: m for m in parse_file(f).modules}

    top = modules["top"]
    insts = {i.instance_name: i for i in top.instances}
    assert set(insts) == {"u_named", "u_pos"}
    assert insts["u_named"].module_name == "leaf"

    named = {c.port_name: c for c in insts["u_named"].connections}
    # An INDEX expression must not leak in as a second connected net.
    assert named["a"].nets == ["bus"]
    assert named["b"].nets == ["alias_net"]
    assert named["y"].nets == ["mid"]
    assert [c.position for c in insts["u_named"].connections] == [0, 1, 2]

    # An OMITTED positional slot ("leave this port open") is elided from
    # verible's tree entirely -- only its commas survive -- so positions must
    # come from the separators. Counting port NODES would call `mid` position 1
    # and wire it to the wrong formal port of `leaf`.
    positional = insts["u_pos"].connections
    assert [(c.port_name, c.position, c.nets) for c in positional] == [
        (None, 0, ["bus"]), (None, 2, ["mid"])]

    assigns = top.continuous_assigns
    assert {tuple(a.lhs_nets) for a in assigns} == {("alias_net",), ("out",)}
    alias = next(a for a in assigns if a.lhs_nets == ["alias_net"])
    assert alias.rhs_nets == ["mid"]
    combo = next(a for a in assigns if a.lhs_nets == ["out"])
    assert sorted(combo.rhs_nets) == ["alias_net", "clk"]


@requires_verible
def test_verible_parser_finds_instances_inside_generate_blocks(tmp_path):
    src = textwrap.dedent("""\
        module leaf (input logic a);
        endmodule
        module top #(parameter int N = 1) (input logic x);
            generate
                if (N > 0) begin : g_blk
                    leaf u_gen (.a(x));
                end
            endgenerate
        endmodule
        """)
    f = tmp_path / "gen.sv"
    f.write_text(src, encoding="utf-8")
    top = {m.name: m for m in parse_file(f).modules}["top"]
    assert [i.instance_name for i in top.instances] == ["u_gen"]


# ---------------------------------------------------------------------------
# Bundle grouping (the grouping is name-based; the PROTOCOL never is)
# ---------------------------------------------------------------------------

def test_bundle_prefix_uses_the_last_amba_signal_token():
    assert amba_bundle_prefix("S00_AXI_AWVALID") == "S00_AXI_"
    assert amba_bundle_prefix("HADDR") == ""
    assert amba_bundle_prefix("m0_pready") == "m0_"
    assert amba_bundle_prefix("clk") is None
    assert amba_bundle_prefix("some_proprietary_sideband") is None


def test_group_ports_into_bundles_excludes_non_amba_ports():
    groups = group_ports_into_amba_bundles(
        ["S_AXI_AWVALID", "S_AXI_AWADDR", "M_APB_PSEL", "clk", "rst_n"])
    assert groups == {"S_AXI_": ["S_AXI_AWVALID", "S_AXI_AWADDR"],
                      "M_APB_": ["M_APB_PSEL"]}


@requires_verible
def test_fabric_bundles_classify_from_signal_evidence_only(fabric_netlist):
    bundles = {b.prefix: b for b in bundles_of(fabric_netlist, FABRIC)}
    assert bundles["S00_AXI_"].protocol == "AXI4"
    assert bundles["S_AHB_"].protocol == "AHB_LITE"
    # AMBA-5 both perspectives, derived from real port directions.
    assert bundles["S00_AXI_"].fabric_side_role == connectivity.FABRIC_SIDE_SLAVE_INTERFACE
    assert bundles["M00_AXI_"].fabric_side_role == connectivity.FABRIC_SIDE_MASTER_INTERFACE


# ---------------------------------------------------------------------------
# The clean topology cases (AMBA-7 / AMBA-8 / AMBA-9 / AMBA-10)
# ---------------------------------------------------------------------------

@requires_verible
def test_slave_port_traces_through_a_transparent_wrapper_to_the_real_master(fabric_netlist):
    trace = trace_fabric_slave_interface_to_masters(fabric_netlist, FABRIC, "S00_AXI_")
    assert trace.status == TraceTerminationStatus.SOURCE_FOUND.value
    assert trace.direction == afd.TRACE_TOWARD_MASTERS
    branch = trace.branches[0]
    # AMBA-7: "Do not stop at a transparent wrapper" -- the endpoint is the
    # core INSIDE the wrapper, not the wrapper.
    assert branch.endpoint_instance_path == "u_cpu_wrap/u_cpu_core"
    assert branch.endpoint_module == "cpu_core"
    assert branch.endpoint_protocol == "AXI4"


@requires_verible
def test_vip_placement_priority_ladder_prefers_the_ip_boundary(fabric_netlist):
    trace = _trace(fabric_netlist, "S00_AXI_")
    ranked = trace.ranked_candidates()
    assert [c.priority for c in ranked] == [
        VipPlacementPriority.P1_TRUE_IP_AMBA_BOUNDARY.value,
        VipPlacementPriority.P2_IMMEDIATE_IP_WRAPPER.value,
    ]
    assert ranked[0].instance_path == "u_cpu_wrap/u_cpu_core"
    assert ranked[1].instance_path == "u_cpu_wrap"
    # AMBA-8's P4 fallback is never preferred when a real IP boundary exists.
    assert trace.best_candidate.priority == VipPlacementPriority.P1_TRUE_IP_AMBA_BOUNDARY.value


@requires_verible
def test_p4_fabric_port_fallback_is_offered_when_nothing_better_exists(fabric_netlist):
    """AMBA-8's ladder has to terminate somewhere. A port with no traced
    endpoint must still get the fabric port itself as a P4 candidate --
    proposing nothing would read as "no VIP needed here"."""
    for prefix in ("S02_AXI_", "S03_AXI_", "M05_AXI_"):
        trace = _trace(fabric_netlist, prefix)
        assert [c.priority for c in trace.ranked_candidates()] == [
            VipPlacementPriority.P4_BUS_FABRIC_PORT.value], prefix
        assert trace.ranked_candidates()[0].instance_path == "u_fabric"

    # ...and it is NOT offered when a real IP boundary was found, since AMBA-8
    # prefers P1/P2/P3 over P4 whenever one is observable.
    resolved = _trace(fabric_netlist, "S00_AXI_")
    assert resolved.fallback_candidates == []
    assert VipPlacementPriority.P4_BUS_FABRIC_PORT.value not in [
        c.priority for c in resolved.ranked_candidates()]


@requires_verible
def test_unresolved_branch_candidates_are_never_ranked_p1(fabric_netlist):
    """A blocked or ambiguous branch's boundary is still worth watching, but
    calling it the TRUE IP AMBA BOUNDARY would assert exactly what the branch
    failed to establish."""
    for prefix in ("M02_AXI_", "M03_AXI_"):
        cands = _trace(fabric_netlist, prefix).ranked_candidates()
        assert cands, prefix
        assert {c.priority for c in cands} == {
            VipPlacementPriority.P3_PROTOCOL_PRESERVING_ADAPTER.value}, prefix
        assert all("never established a real transaction endpoint" in c.rationale
                   for c in cands)

    # The bridge is the deliberate exception: its UPSTREAM side is a real,
    # established AMBA boundary of a real IP -- only the downstream side is out
    # of bounds, and that is recorded as AMBA-11's VIP-B instead.
    bridge_cands = _trace(fabric_netlist, "M01_AXI_").ranked_candidates()
    assert bridge_cands[0].priority == VipPlacementPriority.P1_TRUE_IP_AMBA_BOUNDARY.value
    assert bridge_cands[0].protocol == "AXI4"


@requires_verible
def test_bind_candidates_carry_a_real_connectivity_bind_tier(fabric_netlist):
    trace = _trace(fabric_netlist, "S00_AXI_")
    for cand in trace.ranked_candidates():
        assert cand.bind_tier == connectivity.BindTier.T2_STRUCTURAL_MATCH.value
        assert cand.requires_human_confirmation is False
        assert cand.requires_question_queue_entry is False
        # Structural, not naming: the tier's own rationale says so.
        assert "structural protocol-fingerprint match" in cand.rationale


@requires_verible
def test_master_port_traces_through_a_register_slice_to_the_destination_slave(fabric_netlist):
    trace = trace_fabric_master_interface_to_slaves(fabric_netlist, FABRIC, "M00_AXI_")
    assert trace.status == TraceTerminationStatus.DESTINATION_FOUND.value
    branch = trace.branches[0]
    assert branch.endpoint_instance_path == "u_ddr"
    roles = [h.role for h in branch.hops]
    assert StructuralRole.PROTOCOL_PRESERVING_ADAPTER.value in roles
    adapter = next(h for h in branch.hops
                   if h.role == StructuralRole.PROTOCOL_PRESERVING_ADAPTER.value)
    assert adapter.instance_path == "u_axi_reg_slice"
    # The register-slice SUB-role is a naming heuristic and is tiered as one.
    assert adapter.sub_role_hint["sub_role"] == "REGISTER_SLICE_OR_PIPELINE"
    assert adapter.sub_role_hint["tier"] == connectivity.BindTier.T3_NAMING_HEURISTIC.value
    assert adapter.sub_role_hint["requires_human_confirmation"] is True
    # ...and it never changes the structural verdict or the protocol.
    assert adapter.role_tier == connectivity.BindTier.T2_STRUCTURAL_MATCH.value
    assert adapter.protocol == "AXI4"


@requires_verible
def test_direction_is_derived_from_the_amba5_role_not_from_the_caller(fabric_netlist):
    with pytest.raises(FabricDiscoveryError) as exc:
        trace_fabric_slave_interface_to_masters(fabric_netlist, FABRIC, "M00_AXI_")
    assert exc.value.args[0] == "WRONG_FABRIC_SIDE_ROLE_FOR_TRACE_DIRECTION"


# ---------------------------------------------------------------------------
# AMBA-11: the protocol bridge rule -- BOTH sides, correctly labelled
# ---------------------------------------------------------------------------

@requires_verible
def test_protocol_bridge_records_both_sides_and_stops_the_vip_push(fabric_netlist):
    trace = _trace(fabric_netlist, "M01_AXI_")
    assert trace.status == TraceTerminationStatus.PROTOCOL_BRIDGE_FOUND.value
    assert len(trace.bridges) == 1
    bridge = trace.bridges[0]
    assert bridge.bridge_instance_path == "u_apb_bridge"
    assert bridge.upstream_protocol == "AXI4"
    # "Do not label a downstream APB endpoint as AXI."
    assert bridge.downstream_protocol == "APB4"
    assert bridge.downstream_bundle_prefix == "M_APB_"

    # AMBA-8: VIP is not pushed across the protocol conversion.
    limits = [l["limit"] for l in trace.push_limits]
    assert afd.PUSH_LIMIT_PROTOCOL_CONVERSION in limits
    for cand in trace.ranked_candidates():
        assert cand.protocol == "AXI4"
        assert cand.instance_path != "u_periph"


# ---------------------------------------------------------------------------
# AMBA-12 / AMBA-13: multiple source and multiple destination
# ---------------------------------------------------------------------------

@requires_verible
def test_shared_ahb_mux_reports_multiple_source_and_enumerates_every_master(fabric_netlist):
    trace = _trace(fabric_netlist, "S_AHB_")
    assert trace.status == TraceTerminationStatus.MULTIPLE_SOURCE.value
    endpoints = sorted(b.endpoint_instance_path for b in trace.branches)
    # "Do not arbitrarily choose one source" -- both are listed.
    assert endpoints == ["u_ahb_cpu", "u_ahb_dbg"]
    assert all(b.status == TraceTerminationStatus.SOURCE_FOUND.value for b in trace.branches)
    mux_hops = [h for b in trace.branches for h in b.hops
                if h.role == StructuralRole.MUX_OR_ARBITER.value]
    assert {h.instance_path for h in mux_hops} == {"u_ahb_mux"}
    assert all(h.protocol == "AHB_LITE" for h in mux_hops)


@requires_verible
def test_decoder_reports_multiple_destination_and_enumerates_every_slave(fabric_netlist):
    trace = _trace(fabric_netlist, "M04_AXI_")
    assert trace.status == TraceTerminationStatus.MULTIPLE_DESTINATION.value
    assert sorted(b.endpoint_instance_path for b in trace.branches) == ["u_sram0", "u_sram1"]
    decoder_hops = [h for b in trace.branches for h in b.hops
                    if h.role == StructuralRole.DECODER_OR_INTERCONNECT.value]
    assert {h.instance_path for h in decoder_hops} == {"u_decoder"}


# ---------------------------------------------------------------------------
# AMBA-14: the unresolved states, each with reason + missing evidence
# ---------------------------------------------------------------------------

@requires_verible
def test_unparsed_module_blocks_the_trace_instead_of_being_called_an_endpoint(fabric_netlist):
    trace = _trace(fabric_netlist, "M03_AXI_")
    assert trace.status == TraceTerminationStatus.TRACE_BLOCKED.value
    assert "opaque_ip" in trace.reason
    assert trace.missing_evidence
    assert any("RTL body of opaque_ip" in m for m in trace.missing_evidence)
    assert afd.PUSH_LIMIT_INACCESSIBLE_HIERARCHY in [l["limit"] for l in trace.push_limits]


@requires_verible
def test_two_bundles_with_no_visible_path_is_ambiguous_not_guessed(fabric_netlist):
    trace = _trace(fabric_netlist, "M02_AXI_")
    assert trace.status == TraceTerminationStatus.AMBIGUOUS.value
    assert "mystery_bridge" in trace.reason
    # Neither rounded up to a bridge nor down to an endpoint.
    assert trace.bridges == []
    assert all(b.endpoint_protocol != "APB4" for b in trace.branches)
    assert trace.missing_evidence


@requires_verible
def test_port_reaching_only_fabric_internals_is_internal_only(fabric_netlist):
    trace = _trace(fabric_netlist, "S02_AXI_")
    assert trace.status == TraceTerminationStatus.INTERNAL_ONLY.value
    assert "u_fabric/u_int_mon" in trace.reason


@requires_verible
def test_port_leaving_the_parsed_design_is_source_not_found(fabric_netlist):
    trace = _trace(fabric_netlist, "S03_AXI_")
    assert trace.status == TraceTerminationStatus.SOURCE_NOT_FOUND.value
    assert "soc_top" in trace.reason
    assert trace.missing_evidence


@requires_verible
def test_unconnected_fabric_master_port_is_destination_not_found(fabric_netlist):
    trace = _trace(fabric_netlist, "M05_AXI_")
    assert trace.status == TraceTerminationStatus.DESTINATION_NOT_FOUND.value
    assert trace.missing_evidence


@requires_verible
def test_all_ten_amba14_states_are_reached_by_this_one_fabric(fabric_netlist):
    """The point of a ten-state enum is that the unresolved states are real
    outcomes, not decoration. All ten come out of this single design, so none
    of them is an untested branch."""
    traces = trace_all_fabric_ports(fabric_netlist, FABRIC)
    counts = summarize_trace_terminations(traces)
    assert set(counts) == {s.value for s in TraceTerminationStatus}
    reached = {s for s, n in counts.items() if n}
    assert reached == {s.value for s in TraceTerminationStatus}


@requires_verible
def test_every_fabric_port_is_traced_and_every_unresolved_one_is_explained(fabric_netlist):
    traces = trace_all_fabric_ports(fabric_netlist, FABRIC)
    assert len(traces) == 11        # every AMBA bundle on the fabric, none dropped
    assert_unresolved_states_explained(traces)   # raises if any lacks reason/evidence


def test_unresolved_trace_without_missing_evidence_is_refused():
    bad = afd.FabricPortTrace(
        interface_id="u_fabric:S00_AXI_", fabric_instance_path="u_fabric",
        bundle_prefix="S00_AXI_", fabric_protocol="AXI4",
        fabric_side_role=connectivity.FABRIC_SIDE_SLAVE_INTERFACE,
        direction=afd.TRACE_TOWARD_MASTERS,
        status=TraceTerminationStatus.AMBIGUOUS.value,
        reason="something was unclear")
    with pytest.raises(FabricDiscoveryError) as exc:
        assert_unresolved_states_explained([bad])
    assert exc.value.args[0] == "UNRESOLVED_TRACE_WITHOUT_MISSING_EVIDENCE"


def test_ambiguous_direction_stops_the_trace_before_it_labels_a_source():
    """A bundle whose AMBA-5 role never resolved cannot be traced toward
    'masters' or 'slaves' without inventing which of the two it is."""
    src_modules = {
        "blackboxed_top": {
            "name": "blackboxed_top",
            "ports": [],
            "instances": [{
                "instance_name": "u_fab", "module_name": "unparsed_fabric",
                "connections": [
                    {"port_name": f"S_AXI_{s}", "position": i, "expr_text": None,
                     "nets": [f"n_{s.lower()}"]}
                    for i, s in enumerate(AXI4_SIGNALS)],
            }],
            "continuous_assigns": [],
        },
    }
    netlist = build_fabric_netlist([{"modules": list(src_modules.values())}],
                                  "blackboxed_top")
    trace = trace_fabric_port(netlist, ("u_fab",), "S_AXI_")
    assert trace.status == TraceTerminationStatus.AMBIGUOUS.value
    assert trace.direction == afd.TRACE_DIRECTION_UNRESOLVED
    assert trace.missing_evidence


# ---------------------------------------------------------------------------
# Hand-off shapes and the AMBA-30/AMBA-31 gate
# ---------------------------------------------------------------------------

@requires_verible
def test_discovered_topology_ids_only_list_endpoints_that_really_resolved(fabric_netlist):
    traces = trace_all_fabric_ports(fabric_netlist, FABRIC)
    topo = discovered_topology_ids(traces)
    assert set(topo) == {"masters", "slaves", "unresolved"}
    assert sorted(topo["masters"]) == ["u_ahb_cpu", "u_ahb_dbg", "u_cpu_wrap/u_cpu_core", "u_dma"]
    assert sorted(topo["slaves"]) == ["u_ddr", "u_sram0", "u_sram1"]
    # An unresolved port never quietly becomes a master or a slave.
    unresolved_ifaces = {u["interface"] for u in topo["unresolved"]}
    assert any("M02_AXI_" in i for i in unresolved_ifaces)
    assert any("M03_AXI_" in i for i in unresolved_ifaces)
    assert all(e not in topo["masters"] + topo["slaves"] for e in ("u_periph", "u_opaque"))


@requires_verible
def test_report_states_every_amba14_status_including_the_zero_counts(fabric_netlist):
    traces = trace_all_fabric_ports(fabric_netlist, FABRIC)
    report = render_endpoint_trace_report(traces)
    for status in TraceTerminationStatus:
        assert status.value in report
    assert "MISSING EVIDENCE" in report
    assert "PROTOCOL BRIDGE at u_apb_bridge" in report


@requires_verible
def test_no_bind_statement_is_ever_emitted(fabric_netlist):
    """AMBA-30/AMBA-31: this layer discovers and plans; it never writes a bind.

    Checked against the module's own source AND against its rendered artifact,
    using connectivity.py's own bind-line regex so there is one definition of
    'a bind statement' in this repo, not two."""
    source = (afd.__file__ and open(afd.__file__, encoding="utf-8").read())
    for line in source.splitlines():
        assert connectivity.parse_bind_line(line) is None, line

    report = render_endpoint_trace_report(trace_all_fabric_ports(fabric_netlist, FABRIC))
    for line in report.splitlines():
        assert connectivity.parse_bind_line(line) is None, line
    assert not re.search(r"^\s*bind\s+\S", report, flags=re.MULTILINE)
