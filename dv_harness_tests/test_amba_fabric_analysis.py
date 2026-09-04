"""Tests for dv_harness/amba_fabric_analysis.py -- AMBA-23 (address map
cross-check), AMBA-24 (clock/reset domain analysis) and AMBA-25 (scoreboard +
port scaling).

AMBA-24 runs against a REAL `verible-verilog-syntax` parse of a synthetic
multi-master / multi-slave AMBA4 SoC written to a tmp dir, exactly as
test_amba_fabric_discovery.py does and for the same reason: a hand-built graph
object would prove the walk works on the shape this test author imagined rather
than on the shape verible really produces. Skipped, never faked, without
verible on PATH.

The fixture is synthetic RTL for a test and it contains no bind-like construct
of any kind; per AMBA-30/AMBA-31 this whole layer is discovery/planning and
`test_no_bind_statement_is_ever_emitted` asserts that of the module's source and
of every artifact it renders.

The fixture deliberately carries the UNRESOLVED cases alongside the clean ones
-- a clock net with two drivers, a clock mux with two candidate inputs, an
undriven reset, an address-map document naming a slave nobody traced, two
equal-authority sources that disagree, and an unresolvable scoreboard pair.
A tracer or a cross-check proven only on the happy path is not covered.
"""
from __future__ import annotations

import shutil


import pytest

from dv_harness import amba_fabric_analysis as afa
from dv_harness import amba_fabric_discovery as afd
from dv_harness import amba_port_registry as apr
from dv_harness.amba_fabric_analysis import (
    ADDRESS_MAP_COMPLETE,
    ADDRESS_MAP_SOURCE_ADDRESS_MAP_PACKAGE,
    ADDRESS_MAP_SOURCE_CSR_DEFINITIONS,
    ADDRESS_MAP_SOURCE_FIRMWARE_HEADERS,
    ADDRESS_MAP_SOURCE_MEMORY_MAP_DOCUMENT,
    ADDRESS_MAP_SOURCE_RTL_DECODER,
    ADDRESS_REGION_AGREED,
    ADDRESS_REGION_NO_ADDRESS_EVIDENCE,
    ADDRESS_REGION_RESOLVED_BY_AUTHORITY,
    ADDRESS_REGION_UNDECIDABLE,
    BIND_SIDE_ENDPOINT,
    BIND_SIDE_NO_CDC,
    CDC_CROSSING_IDENTIFIED,
    CDC_NONE_ON_PATH,
    CLOCK_FREQUENCY_MEASURED,
    CLOCK_FREQUENCY_NOT_CONSTANT,
    DOMAIN_UNKNOWN,
    DOMAIN_WALK_AMBIGUOUS_PORT,
    DOMAIN_WALK_MULTIPLE_DRIVERS,
    DOMAIN_WALK_RESOLVED,
    DOMAIN_WALK_UNDRIVEN,
    INTERLOCK_DEPENDENCY_SHARED_SLAVE,
    INTERLOCK_NOT_REQUIRED,
    INTERLOCK_REQUIRED,
    PHYSICAL_CONNECTIVITY_ABSENT,
    PHYSICAL_CONNECTIVITY_CONFIRMED,
    RESET_ACTIVE_LOW,
    RESET_POLARITY_DISAGREEMENT,
    RESET_POLARITY_UNKNOWN,
    RESET_SYNC_SYNCHRONIZED,
    TRAFFIC_POLICY_PARALLEL,
    TRAFFIC_POLICY_SERIALIZED,
    AddressRegionClaim,
    FabricAnalysisError,
    address_map_slaves_for_topology,
    analyze_all_bind_point_domains,
    analyze_clock_frequency,
    analyze_reset_polarity,
    analyze_reset_synchronization,
    assert_address_map_never_creates_a_slave,
    assert_every_port_has_its_own_channel,
    build_fabric_scaling_plan,
    cross_check_fabric_address_map,
    derived_reset_active_low,
    measure_clock_period,
    render_address_map_cross_check_report,
    render_clock_reset_domain_report,
    render_fabric_scaling_report,
    traffic_policy_for,
)
from dv_harness.connectivity import REQUIRED_HUMAN_INPUT, SignalTrace
from dv_harness.verible_parser import parse_file

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)


# ---------------------------------------------------------------------------
# Synthetic RTL fixture
#
# Signal sets are spelled out rather than imported from connectivity.py, the
# same discipline test_amba_fabric_discovery.py follows: a fixture built from
# the classifier's own constants would pass even if both were wrong together.
# ---------------------------------------------------------------------------

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


def _ports(prefix: str, signals: dict, side: str) -> list:
    out = []
    for sig, kind in signals.items():
        if side == "initiator":
            direction = "output" if kind == "req" else "input"
        else:
            direction = "input" if kind == "req" else "output"
        out.append((direction, f"{prefix}{sig}"))
    return out


def _ck(prefix: str, clock: str = "ACLK", reset: str = "ARESETN") -> list:
    """This interface's own spec-named, bundle-prefixed clock and reset -- the
    only tier `find_amba_clock_reset_ports()` resolves without qualification."""
    return [("input", f"{prefix}{clock}"), ("input", f"{prefix}{reset}")]


def _sv_module(name: str, ports: list, body: str = "", params: str = "") -> str:
    decls = ",\n    ".join(f"{d} logic {n}" for d, n in ports)
    head = f"module {name} {params}(\n    {decls}\n);\n"
    return head + body + "\nendmodule\n"


def _sv_inst(module: str, inst: str, conns: list) -> str:
    body = ",\n        ".join(f".{p}({n})" for p, n in conns)
    return f"    {module} {inst} (\n        {body}\n    );\n"


def _bundle_conns(prefix: str, signals: dict, net_prefix: str) -> list:
    return [(f"{prefix}{s}", f"{net_prefix}{s.lower()}") for s in signals]


def _bundle_nets(net_prefix: str, signals: dict) -> str:
    return "".join(f"    wire {net_prefix}{s.lower()};\n" for s in signals)


def _passthrough(signals: dict, s_prefix: str, m_prefix: str) -> str:
    return "".join(
        f"    assign {m_prefix}{s} = {s_prefix}{s};\n" if k == "req"
        else f"    assign {s_prefix}{s} = {m_prefix}{s};\n"
        for s, k in signals.items())


def write_fixture(tmp_path):
    """A synthetic AMBA4 SoC with two AXI4 masters, an AXI4 slave behind a real
    clock-domain-crossing wrapper, and an APB4 peripheral behind an AXI-to-APB
    bridge -- plus a PLL, a divider, a reset synchroniser, a two-input clock mux
    and a deliberately double-driven clock net."""
    mods = []

    # --- clock / reset generation ------------------------------------------
    mods.append(_sv_module("clk_pll", [("input", "REF_CLK"), ("output", "PLL_CLK")],
                           params="#(parameter int CLK_FREQ_HZ = 400000000) "))
    mods.append(_sv_module("clk_div2", [("input", "CLK_IN"), ("output", "CLK_OUT")]))
    mods.append(_sv_module("clk_mux2", [("input", "CLK_A"), ("input", "CLK_B"),
                                        ("input", "SEL"), ("output", "CLK_OUT")]))
    mods.append(_sv_module("rst_sync", [("input", "ACLK"), ("input", "ARESETN_IN"),
                                        ("output", "ARESETN_OUT")]))

    # --- AXI4 masters -------------------------------------------------------
    for name in ("cpu_core", "dma_engine"):
        mods.append(_sv_module(name, _ports("M_AXI_", AXI4_SIGNALS, "initiator")
                               + _ck("M_AXI_")))

    # --- AXI4 slave, and the APB4 peripheral --------------------------------
    mods.append(_sv_module("ddr_ctrl", _ports("S_AXI_", AXI4_SIGNALS, "target")
                           + _ck("S_AXI_")))
    mods.append(_sv_module("apb_periph", _ports("S_APB_", APB4_SIGNALS, "target")
                           + _ck("S_APB_", clock="PCLK", reset="PRESETN")))

    # --- the CDC wrapper: same protocol both sides, DIFFERENT clocks --------
    mods.append(_sv_module(
        "axi_cdc_wrapper",
        _ports("S_AXI_", AXI4_SIGNALS, "target") + _ck("S_AXI_")
        + _ports("M_AXI_", AXI4_SIGNALS, "initiator") + _ck("M_AXI_"),
        _passthrough(AXI4_SIGNALS, "S_AXI_", "M_AXI_")))

    # --- the AXI4 -> APB4 protocol bridge -----------------------------------
    mods.append(_sv_module(
        "axi_to_apb",
        _ports("S_AXI_", AXI4_SIGNALS, "target") + _ck("S_AXI_")
        + _ports("M_APB_", APB4_SIGNALS, "initiator") + _ck("M_APB_", "PCLK", "PRESETN"),
        "    assign M_APB_PADDR = S_AXI_AWADDR;\n"
        "    assign M_APB_PWDATA = S_AXI_WDATA;\n"
        "    assign S_AXI_RDATA = M_APB_PRDATA;\n"))

    # --- the fabric ---------------------------------------------------------
    fabric_ports = (
        _ports("S00_AXI_", AXI4_SIGNALS, "target") + _ck("S00_AXI_")
        + _ports("S01_AXI_", AXI4_SIGNALS, "target") + _ck("S01_AXI_")
        + _ports("M00_AXI_", AXI4_SIGNALS, "initiator") + _ck("M00_AXI_")
        + _ports("M01_AXI_", AXI4_SIGNALS, "initiator") + _ck("M01_AXI_"))
    mods.append(_sv_module("axi_fabric", fabric_ports))

    # --- the SoC top --------------------------------------------------------
    net_groups = [("cpu_axi_", AXI4_SIGNALS), ("dma_axi_", AXI4_SIGNALS),
                  ("ddr_in_axi_", AXI4_SIGNALS), ("ddr_axi_", AXI4_SIGNALS),
                  ("brg_axi_", AXI4_SIGNALS), ("apb_", APB4_SIGNALS)]
    top_body = "".join(_bundle_nets(p, s) for p, s in net_groups)
    top_body += ("    wire pll_clk;\n    wire slow_clk;\n    wire sys_rstn;\n"
                 "    wire muxed_clk;\n    wire contended_clk;\n"
                 "    wire orphan_rstn;\n    wire mux_sel;\n")
    top_body += _sv_inst("clk_pll", "u_pll", [("REF_CLK", "CLK_REF"), ("PLL_CLK", "pll_clk")])
    top_body += _sv_inst("clk_div2", "u_div", [("CLK_IN", "pll_clk"), ("CLK_OUT", "slow_clk")])
    top_body += _sv_inst("rst_sync", "u_rst_sync",
                         [("ACLK", "pll_clk"), ("ARESETN_IN", "RSTN_EXT"),
                          ("ARESETN_OUT", "sys_rstn")])
    # A two-input clock mux: which of its inputs its output derives from is not
    # established by a port list, so a walk through it must report AMBIGUOUS.
    top_body += _sv_inst("clk_mux2", "u_clk_mux",
                         [("CLK_A", "pll_clk"), ("CLK_B", "slow_clk"),
                          ("SEL", "mux_sel"), ("CLK_OUT", "muxed_clk")])
    # Two dividers driving ONE net: a real multiple-driver contention, which
    # must be reported rather than resolved to whichever was parsed first.
    top_body += _sv_inst("clk_div2", "u_div_a",
                         [("CLK_IN", "pll_clk"), ("CLK_OUT", "contended_clk")])
    top_body += _sv_inst("clk_div2", "u_div_b",
                         [("CLK_IN", "slow_clk"), ("CLK_OUT", "contended_clk")])

    top_body += _sv_inst("cpu_core", "u_cpu",
                         _bundle_conns("M_AXI_", AXI4_SIGNALS, "cpu_axi_")
                         + [("M_AXI_ACLK", "pll_clk"), ("M_AXI_ARESETN", "sys_rstn")])
    top_body += _sv_inst("dma_engine", "u_dma",
                         _bundle_conns("M_AXI_", AXI4_SIGNALS, "dma_axi_")
                         + [("M_AXI_ACLK", "pll_clk"), ("M_AXI_ARESETN", "sys_rstn")])
    top_body += _sv_inst(
        "axi_fabric", "u_fabric",
        _bundle_conns("S00_AXI_", AXI4_SIGNALS, "cpu_axi_")
        + [("S00_AXI_ACLK", "pll_clk"), ("S00_AXI_ARESETN", "sys_rstn")]
        + _bundle_conns("S01_AXI_", AXI4_SIGNALS, "dma_axi_")
        + [("S01_AXI_ACLK", "pll_clk"), ("S01_AXI_ARESETN", "sys_rstn")]
        + _bundle_conns("M00_AXI_", AXI4_SIGNALS, "ddr_in_axi_")
        + [("M00_AXI_ACLK", "pll_clk"), ("M00_AXI_ARESETN", "sys_rstn")]
        + _bundle_conns("M01_AXI_", AXI4_SIGNALS, "brg_axi_")
        + [("M01_AXI_ACLK", "pll_clk"), ("M01_AXI_ARESETN", "sys_rstn")])
    top_body += _sv_inst(
        "axi_cdc_wrapper", "u_axi_cdc",
        _bundle_conns("S_AXI_", AXI4_SIGNALS, "ddr_in_axi_")
        + [("S_AXI_ACLK", "pll_clk"), ("S_AXI_ARESETN", "sys_rstn")]
        + _bundle_conns("M_AXI_", AXI4_SIGNALS, "ddr_axi_")
        + [("M_AXI_ACLK", "slow_clk"), ("M_AXI_ARESETN", "sys_rstn")])
    # u_ddr's reset comes from `orphan_rstn`, which nothing drives: an undriven
    # reset must be reported, never silently treated as present.
    top_body += _sv_inst("ddr_ctrl", "u_ddr",
                         _bundle_conns("S_AXI_", AXI4_SIGNALS, "ddr_axi_")
                         + [("S_AXI_ACLK", "slow_clk"), ("S_AXI_ARESETN", "orphan_rstn")])
    top_body += _sv_inst(
        "axi_to_apb", "u_apb_bridge",
        _bundle_conns("S_AXI_", AXI4_SIGNALS, "brg_axi_")
        + [("S_AXI_ACLK", "pll_clk"), ("S_AXI_ARESETN", "sys_rstn")]
        + _bundle_conns("M_APB_", APB4_SIGNALS, "apb_")
        + [("M_APB_PCLK", "pll_clk"), ("M_APB_PRESETN", "sys_rstn")])
    top_body += _sv_inst("apb_periph", "u_periph",
                         _bundle_conns("S_APB_", APB4_SIGNALS, "apb_")
                         + [("S_APB_PCLK", "pll_clk"), ("S_APB_PRESETN", "sys_rstn")])

    mods.append(_sv_module("soc_top", [("input", "CLK_REF"), ("input", "RSTN_EXT")],
                           top_body))

    path = tmp_path / "amba4_domain_fixture.sv"
    path.write_text("\n".join(mods), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def netlist(tmp_path_factory):
    if shutil.which(VERIBLE_BIN) is None:
        pytest.skip("verible-verilog-syntax not on PATH")
    sv = write_fixture(tmp_path_factory.mktemp("amba4_domains"))
    return afd.build_fabric_netlist([parse_file(sv)], "soc_top")


@pytest.fixture(scope="module")
def traces(netlist):
    return afd.trace_all_fabric_ports(netlist, ("u_fabric",))


@pytest.fixture(scope="module")
def matrix(netlist, traces):
    return afd.build_fabric_vip_bind_matrix(netlist, traces)


@pytest.fixture(scope="module")
def registry(netlist, traces):
    return apr.build_amba_port_registry(netlist, traces)


# ===========================================================================
# AMBA-24: the clock / reset domain WALK itself
# ===========================================================================

@requires_verible
def test_clock_hierarchy_walks_through_the_divider_and_the_pll(netlist):
    """The hierarchy is the real chain of generators, not just the endpoint's
    own port: u_ddr's clock passes a divider, a PLL and a primary input."""
    chain = afa._walk_domain(netlist, ("u_ddr",), "S_AXI_ACLK", "clock")
    assert chain.status == DOMAIN_WALK_RESOLVED
    assert [(n.path, n.port, n.kind) for n in chain.nodes] == [
        ("u_div", "CLK_OUT", afa.DOMAIN_SOURCE_INSTANCE_OUTPUT),
        ("u_pll", "PLL_CLK", afa.DOMAIN_SOURCE_INSTANCE_OUTPUT),
        ("<top>", "CLK_REF", afa.DOMAIN_SOURCE_PRIMARY_INPUT),
    ]
    assert chain.source_node.port == "CLK_REF"


@requires_verible
def test_a_divider_output_is_a_different_domain_from_its_own_input(netlist):
    """The check that makes CDC detection work at all. Both clocks originate at
    the same primary input; comparing origins would report the crossing as
    absent, so the domain identity is the NEAREST generator."""
    fabric = afa._walk_domain(netlist, ("u_fabric",), "M00_AXI_ACLK", "clock")
    ddr = afa._walk_domain(netlist, ("u_ddr",), "S_AXI_ACLK", "clock")
    assert fabric.domain_id == "u_pll:PLL_CLK"
    assert ddr.domain_id == "u_div:CLK_OUT"
    assert fabric.domain_id != ddr.domain_id
    assert fabric.source_node.port == ddr.source_node.port == "CLK_REF"


@requires_verible
def test_two_bind_points_on_one_clock_share_a_domain(netlist):
    cpu = afa._walk_domain(netlist, ("u_cpu",), "M_AXI_ACLK", "clock")
    fabric = afa._walk_domain(netlist, ("u_fabric",), "S00_AXI_ACLK", "clock")
    assert cpu.is_known_domain()
    assert cpu.domain_id == fabric.domain_id == "u_pll:PLL_CLK"


@requires_verible
def test_a_clock_mux_with_two_candidate_inputs_is_ambiguous_not_guessed(netlist):
    chain = afa._walk_domain(netlist, ("u_clk_mux",), "CLK_OUT", "clock")
    assert chain.status == DOMAIN_WALK_AMBIGUOUS_PORT
    assert sorted(chain.candidates) == ["CLK_A", "CLK_B"]
    assert chain.domain_id == DOMAIN_UNKNOWN
    assert not chain.is_known_domain()
    assert chain.missing_evidence


@requires_verible
def test_a_double_driven_clock_net_reports_both_drivers(netlist):
    chain = afa._walk_domain(netlist, ("u_div_a",), "CLK_OUT", "clock")
    assert chain.status == DOMAIN_WALK_MULTIPLE_DRIVERS
    assert sorted(chain.candidates) == ["u_div_a:CLK_OUT", "u_div_b:CLK_OUT"]
    assert chain.domain_id == DOMAIN_UNKNOWN


@requires_verible
def test_an_undriven_reset_is_reported_with_its_missing_evidence(netlist):
    chain = afa._walk_domain(netlist, ("u_ddr",), "S_AXI_ARESETN", "reset")
    assert chain.status == DOMAIN_WALK_UNDRIVEN
    assert chain.missing_evidence
    assert chain.domain_id == DOMAIN_UNKNOWN


@requires_verible
def test_reset_hierarchy_finds_the_synchroniser(netlist):
    chain = afa._walk_domain(netlist, ("u_cpu",), "M_AXI_ARESETN", "reset")
    assert chain.status == DOMAIN_WALK_RESOLVED
    assert [n.path for n in chain.nodes] == ["u_rst_sync", "<top>"]
    verdict = analyze_reset_synchronization(chain)
    assert verdict["status"] == RESET_SYNC_SYNCHRONIZED
    assert verdict["instance"] == "u_rst_sync"
    assert verdict["requires_human_confirmation"] is True
    assert verdict["tier"] == "T3_NAMING_HEURISTIC"


@requires_verible
def test_no_synchroniser_in_the_chain_is_unknown_not_asynchronous(netlist):
    """u_pll's REF_CLK chain contains no synchroniser. "No synchroniser found"
    must read UNKNOWN with the missing evidence named -- never "asynchronous",
    which a port/instance/assign-level parse cannot establish."""
    walk = afa._walk_domain(netlist, ("u_pll",), "REF_CLK", "clock")
    verdict = analyze_reset_synchronization(walk)
    assert verdict["status"] == afa.RESET_SYNC_UNKNOWN
    assert verdict["missing_evidence"]


# ===========================================================================
# AMBA-24: reset polarity, DERIVED rather than passed in
# ===========================================================================

def _chain(port: str, nodes=()):
    return afa.DomainChain(kind="reset", status=DOMAIN_WALK_RESOLVED, port=port,
                           nodes=list(nodes))


def test_amba_spec_reset_name_establishes_active_low():
    verdict = analyze_reset_polarity(_chain("M_AXI_ARESETN"))
    assert verdict["polarity"] == RESET_ACTIVE_LOW
    assert verdict["evidence_tier"] == "AMBA_SPECIFICATION"
    assert derived_reset_active_low(verdict) is True


def test_an_unsuffixed_reset_name_is_not_evidence_of_active_high():
    verdict = analyze_reset_polarity(_chain("M_AXI_ARESET"))
    assert verdict["polarity"] == RESET_POLARITY_UNKNOWN
    assert "not evidence of" in verdict["name_evidence"]
    with pytest.raises(FabricAnalysisError) as exc:
        derived_reset_active_low(verdict)
    assert exc.value.reason == "RESET_POLARITY_NOT_ESTABLISHED"


def test_a_measured_trace_establishes_active_high_for_an_unnamed_reset():
    trace = SignalTrace(samples={"rst": [(0, "1"), (5, "1"), (10, "0"), (20, "0")]})
    verdict = analyze_reset_polarity(_chain("rst"), {"rst": trace})
    assert verdict["polarity"] == afa.RESET_ACTIVE_HIGH
    assert verdict["evidence_tier"] == "MEASURED_TRACE"
    assert derived_reset_active_low(verdict) is False


def test_name_and_trace_disagreeing_is_reported_not_silently_resolved():
    trace = SignalTrace(samples={"M_AXI_ARESETN": [(0, "1"), (10, "0"), (20, "0")]})
    verdict = analyze_reset_polarity(_chain("M_AXI_ARESETN"),
                                     {"M_AXI_ARESETN": trace})
    assert verdict["status"] == RESET_POLARITY_DISAGREEMENT
    assert verdict["polarity"] == REQUIRED_HUMAN_INPUT
    assert verdict["name_polarity"] == RESET_ACTIVE_LOW
    assert verdict["trace_polarity"] == afa.RESET_ACTIVE_HIGH
    with pytest.raises(FabricAnalysisError):
        derived_reset_active_low(verdict)


def test_a_reset_that_never_releases_establishes_no_polarity():
    trace = SignalTrace(samples={"rst": [(0, "0"), (10, "0")]})
    verdict = analyze_reset_polarity(_chain("rst"), {"rst": trace})
    assert verdict["polarity"] == RESET_POLARITY_UNKNOWN
    assert "establishes no polarity" in verdict["trace_evidence"]


# ===========================================================================
# AMBA-24: clock frequency "if provable"
# ===========================================================================

def test_a_constant_period_trace_yields_a_measured_frequency():
    trace = SignalTrace(samples={"clk": [(t, "1" if (t // 5) % 2 else "0")
                                         for t in range(0, 100, 5)]})
    measured = measure_clock_period(trace, "clk")
    assert measured["status"] == CLOCK_FREQUENCY_MEASURED
    assert measured["period"] == 10
    result = analyze_clock_frequency(None, afa.DomainChain(kind="clock",
                                                           status=DOMAIN_WALK_RESOLVED,
                                                           port="clk"),
                                     {"clk": trace}, time_unit_seconds=1e-9)
    assert result["frequency_hz"] == pytest.approx(1e8)


def test_a_period_that_changes_is_reported_not_averaged():
    trace = SignalTrace(samples={"clk": [(0, "0"), (5, "1"), (10, "0"), (15, "1"),
                                         (20, "0"), (60, "1")]})
    measured = measure_clock_period(trace, "clk")
    assert measured["status"] == CLOCK_FREQUENCY_NOT_CONSTANT
    assert measured["period"] is None
    assert measured["observed_periods"] == [10, 45]


def test_a_measured_period_without_a_time_unit_states_no_frequency():
    trace = SignalTrace(samples={"clk": [(t, "1" if (t // 5) % 2 else "0")
                                         for t in range(0, 60, 5)]})
    result = analyze_clock_frequency(None, afa.DomainChain(kind="clock",
                                                           status=DOMAIN_WALK_RESOLVED,
                                                           port="clk"), {"clk": trace})
    assert result["period"] == 10
    assert result["frequency_hz"] is None
    assert "not stated rather than assumed" in result["reason"]


@requires_verible
def test_a_declared_frequency_parameter_is_used_but_tiered_as_a_name_match(netlist):
    chain = afa._walk_domain(netlist, ("u_cpu",), "M_AXI_ACLK", "clock")
    result = analyze_clock_frequency(netlist, chain)
    assert result["status"] == afa.CLOCK_FREQUENCY_DECLARED
    assert result["parameter"] == "CLK_FREQ_HZ"
    assert result["value"] == 400000000
    assert result["requires_human_confirmation"] is True


@requires_verible
def test_no_trace_and_no_parameter_is_unknown(netlist):
    chain = afa._walk_domain(netlist, ("u_ddr",), "S_AXI_ACLK", "clock")
    # u_div declares no frequency parameter, and u_pll's is behind it -- the
    # nearest declaring instance in this chain is still u_pll, so this asserts
    # the honest fallback on a chain with no such parameter anywhere.
    chain.nodes = [n for n in chain.nodes if n.path == "u_div"]
    result = analyze_clock_frequency(netlist, chain)
    assert result["status"] == afa.CLOCK_FREQUENCY_UNKNOWN
    assert "if provable" in result["reason"]


# ===========================================================================
# AMBA-24: per-bind-point analysis, CDC and side-of-CDC
# ===========================================================================

@requires_verible
def test_every_matrix_row_gets_a_domain_analysis(netlist, traces, matrix):
    analyses = analyze_all_bind_point_domains(netlist, matrix, traces)
    assert len(analyses) == len(matrix)
    assert all(a.to_dict()["clock_hierarchy"] for a in analyses)


@requires_verible
def test_a_bind_behind_the_cdc_wrapper_is_endpoint_side(netlist, traces, matrix):
    row = next(r for r in matrix if r["fabric_port"] == "u_fabric:M00_AXI_")
    analysis = afa.analyze_bind_point_domains(
        netlist, row, next(t for t in traces if t.interface_id == "u_fabric:M00_AXI_"))
    assert analysis.bind_location.startswith("u_ddr:")
    assert analysis.cdc["status"] == CDC_CROSSING_IDENTIFIED
    assert [c["instance_path"] for c in analysis.cdc["crossing_instances"]] == ["u_axi_cdc"]
    assert analysis.cdc["fabric_domain"] == "u_pll:PLL_CLK"
    assert analysis.cdc["endpoint_domain"] == "u_div:CLK_OUT"
    assert analysis.bind_side == BIND_SIDE_ENDPOINT


@requires_verible
def test_a_single_domain_path_reports_no_cdc(netlist, traces, matrix):
    row = next(r for r in matrix if r["fabric_port"] == "u_fabric:S00_AXI_")
    analysis = afa.analyze_bind_point_domains(
        netlist, row, next(t for t in traces if t.interface_id == "u_fabric:S00_AXI_"))
    assert analysis.cdc["status"] == CDC_NONE_ON_PATH
    assert analysis.bind_side == BIND_SIDE_NO_CDC
    assert analysis.reset_polarity["polarity"] == RESET_ACTIVE_LOW
    assert analysis.reset_synchronization["status"] == RESET_SYNC_SYNCHRONIZED


@requires_verible
def test_the_protocol_bridge_path_is_recorded_with_the_bind_side(netlist, traces, matrix):
    rows = [r for r in matrix if r["fabric_port"].startswith("u_fabric:M01_AXI_")]
    analyses = [afa.analyze_bind_point_domains(
        netlist, r, next(t for t in traces if t.interface_id == "u_fabric:M01_AXI_"))
        for r in rows]
    sides = {a.bridge["status"] for a in analyses}
    assert afa.BRIDGE_UPSTREAM_OF_BIND in sides
    assert afa.BRIDGE_DOWNSTREAM_OF_BIND in sides
    assert all(a.bridge["bridges"] for a in analyses)


@requires_verible
def test_the_domain_report_renders_all_seven_determinations(netlist, traces, matrix):
    text = render_clock_reset_domain_report(
        analyze_all_bind_point_domains(netlist, matrix, traces))
    for header in ("Clock Hierarchy", "Clock Frequency", "Reset Hierarchy",
                   "Reset Polarity", "Sync/Async Reset", "CDC / Bridge Path",
                   "Bind Side"):
        assert header in text


# ===========================================================================
# AMBA-23: address map cross-check
# ===========================================================================

DDR = "u_ddr"
PERIPH = "u_periph"
HALF = 0x8000_0000


def _claim(source, owner, base, size, evidence="rtl/decoder.sv:42"):
    return AddressRegionClaim(source_type=source, owner=owner, base=base, size=size,
                              evidence=evidence)


def test_a_claim_without_a_cited_evidence_path_cannot_be_built():
    with pytest.raises(FabricAnalysisError) as exc:
        AddressRegionClaim(source_type=ADDRESS_MAP_SOURCE_RTL_DECODER, owner=DDR,
                           base=0, size=HALF, evidence="")
    assert exc.value.reason == "ADDRESS_MAP_CLAIM_CITES_NO_EVIDENCE"


def test_an_unknown_evidence_source_is_refused():
    with pytest.raises(FabricAnalysisError) as exc:
        AddressRegionClaim(source_type="SOMEONES_SPREADSHEET", owner=DDR, base=0,
                           size=HALF, evidence="x.xlsx")
    assert exc.value.reason == "ADDRESS_MAP_UNKNOWN_EVIDENCE_SOURCE"


def test_agreeing_sources_produce_a_complete_full_coverage_map():
    result = cross_check_fabric_address_map(
        [_claim(ADDRESS_MAP_SOURCE_RTL_DECODER, DDR, 0, HALF),
         _claim(ADDRESS_MAP_SOURCE_ADDRESS_MAP_PACKAGE, DDR, 0, HALF, "pkg/addr_map.sv:11"),
         _claim(ADDRESS_MAP_SOURCE_RTL_DECODER, PERIPH, HALF, HALF),
         _claim(ADDRESS_MAP_SOURCE_FIRMWARE_HEADERS, PERIPH, HALF, HALF, "fw/map.h:9")],
        [DDR, PERIPH], address_width=32)
    assert [r.status for r in result.regions] == [ADDRESS_REGION_AGREED] * 2
    assert all(r.physical_connectivity == PHYSICAL_CONNECTIVITY_CONFIRMED
               for r in result.regions)
    assert result.completeness_status == ADDRESS_MAP_COMPLETE
    assert result.bind_planning_owners == [DDR, PERIPH]


def test_a_document_disagreeing_with_the_decoder_loses_but_is_not_blocking():
    result = cross_check_fabric_address_map(
        [_claim(ADDRESS_MAP_SOURCE_RTL_DECODER, DDR, 0, HALF),
         _claim(ADDRESS_MAP_SOURCE_MEMORY_MAP_DOCUMENT, DDR, 0x1000, HALF,
                "docs/memory_map.md:3"),
         _claim(ADDRESS_MAP_SOURCE_RTL_DECODER, PERIPH, HALF, HALF)],
        [DDR, PERIPH], address_width=32)
    ddr = next(r for r in result.regions if r.owner == DDR)
    assert ddr.status == ADDRESS_REGION_RESOLVED_BY_AUTHORITY
    assert ddr.base == 0
    assert ddr.deciding_source == ADDRESS_MAP_SOURCE_RTL_DECODER
    assert [d["source_type"] for d in ddr.disagreeing_sources] == [
        ADDRESS_MAP_SOURCE_MEMORY_MAP_DOCUMENT]
    assert ddr.usable_for_bind_planning
    assert result.completeness_status == ADDRESS_MAP_COMPLETE


def test_two_equal_authority_sources_that_disagree_are_undecidable():
    result = cross_check_fabric_address_map(
        [_claim(ADDRESS_MAP_SOURCE_ADDRESS_MAP_PACKAGE, DDR, 0, HALF, "pkg/a.sv:1"),
         _claim(ADDRESS_MAP_SOURCE_CSR_DEFINITIONS, DDR, 0x2000, HALF, "csr/a.json:1")],
        [DDR], address_width=32)
    ddr = result.regions[0]
    assert ddr.status == ADDRESS_REGION_UNDECIDABLE
    assert ddr.base is None and not ddr.has_decided_region
    assert result.undecided_owners == [DDR]
    # Undecided, but still physically traced -- bind planning is not blocked by
    # the address map, only by physical connectivity.
    assert ddr.usable_for_bind_planning
    assert address_map_slaves_for_topology(result) == []


def test_an_address_region_for_an_untraced_owner_is_refused_for_bind_planning():
    result = cross_check_fabric_address_map(
        [_claim(ADDRESS_MAP_SOURCE_RTL_DECODER, DDR, 0, HALF),
         _claim(ADDRESS_MAP_SOURCE_RTL_DECODER, PERIPH, HALF, HALF),
         _claim(ADDRESS_MAP_SOURCE_MEMORY_MAP_DOCUMENT, "u_ghost_slave", 0x4000_0000,
                0x1000, "docs/memory_map.md:77")],
        [DDR, PERIPH], address_width=32)
    ghost = next(r for r in result.regions if r.owner == "u_ghost_slave")
    assert ghost.physical_connectivity == PHYSICAL_CONNECTIVITY_ABSENT
    assert not ghost.usable_for_bind_planning
    assert result.refused_owners == ["u_ghost_slave"]
    assert [s["id"] for s in address_map_slaves_for_topology(result)] == [DDR, PERIPH]
    assert_address_map_never_creates_a_slave(result, [DDR, PERIPH])
    assert "u_ghost_slave" in render_address_map_cross_check_report(result)


def test_a_traced_slave_with_no_address_evidence_is_a_gap_not_a_block():
    result = cross_check_fabric_address_map(
        [_claim(ADDRESS_MAP_SOURCE_RTL_DECODER, DDR, 0, HALF)],
        [DDR, PERIPH], address_width=32)
    periph = next(r for r in result.regions if r.owner == PERIPH)
    assert periph.status == ADDRESS_REGION_NO_ADDRESS_EVIDENCE
    assert periph.usable_for_bind_planning
    assert result.owners_without_address_evidence == [PERIPH]
    # The decoder's half of the space alone is not full coverage; the shortfall
    # is RECORDED, not raised.
    assert result.completeness_status == "ADDRESS_MAP_NOT_FULL_COVERAGE"
    assert result.completeness_detail["expected_range"] == [0, 1 << 32]


def test_an_address_map_overlap_is_recorded_not_raised():
    result = cross_check_fabric_address_map(
        [_claim(ADDRESS_MAP_SOURCE_RTL_DECODER, DDR, 0, HALF + 0x1000),
         _claim(ADDRESS_MAP_SOURCE_RTL_DECODER, PERIPH, HALF, HALF)],
        [DDR, PERIPH], address_width=32)
    assert result.completeness_status == "ADDRESS_MAP_OVERLAP"
    assert result.completeness_detail["region_a"]["owner"] == DDR


def test_the_cross_check_feeds_the_existing_topology_projection(registry):
    """The reuse point: AMBA-23's decided regions are exactly the
    `address_map_slaves` argument `project_to_fabric_topology()` asks for."""
    endpoints = apr.registry_endpoints(registry)
    slaves = endpoints["slaves"]
    assert slaves, "the fixture must trace at least one slave endpoint"
    per_slave = (1 << 32) // len(slaves)
    result = cross_check_fabric_address_map(
        [_claim(ADDRESS_MAP_SOURCE_RTL_DECODER, s, i * per_slave, per_slave,
                f"rtl/decoder.sv:{100 + i}")
         for i, s in enumerate(slaves)],
        slaves, address_width=32)
    assert result.completeness_status == ADDRESS_MAP_COMPLETE
    topology = apr.project_to_fabric_topology(
        registry, address_map_slaves=address_map_slaves_for_topology(result),
        address_width=32, assume_full_connectivity=True)
    assert {r["owner"] for r in topology["address_map"]} == set(slaves)
    assert set(topology["slaves"]) == set(slaves)


# ===========================================================================
# AMBA-25: scoreboard + port scaling
# ===========================================================================

def _reg_row(port_id, protocol, endpoint, role, *, channel=None, id_width="4",
             second_side=False, parent=None, bridge_instance=""):
    """A complete AMBA-22 registry row. Hand-built ONLY for the scale and
    error-path tests -- the topology tests below run on rows the real pipeline
    produced from real RTL."""
    from dv_harness.connectivity import (EXTERNAL_ENDPOINT_MASTER,
                                         EXTERNAL_ENDPOINT_SLAVE,
                                         FABRIC_SIDE_MASTER_INTERFACE,
                                         FABRIC_SIDE_SLAVE_INTERFACE)
    is_master = role == "master"
    return {
        "port_id": port_id, "fabric_port": f"u_fabric:{port_id}", "protocol": protocol,
        "fabric_role": (FABRIC_SIDE_SLAVE_INTERFACE if is_master
                        else FABRIC_SIDE_MASTER_INTERFACE),
        "endpoint_role": (EXTERNAL_ENDPOINT_MASTER if is_master
                          else EXTERNAL_ENDPOINT_SLAVE),
        "endpoint_hierarchy": endpoint, "vip_bind_hierarchy": f"{endpoint}:S_AXI_",
        "vip_mode": "PASSIVE", "clock": "ACLK", "reset": "ARESETN",
        "address_width": "32", "data_width": "64", "id_width": id_width,
        "user_widths": "0",
        "scoreboard_channel": channel or REQUIRED_HUMAN_INPUT,
        "trace_status": (afd.TraceTerminationStatus.SOURCE_FOUND.value if is_master
                         else afd.TraceTerminationStatus.DESTINATION_FOUND.value),
        "readiness": afd.BIND_READINESS_READY, "confidence": "T2_STRUCTURAL_MATCH",
        "source_evidence": ["fixture"], "row_id": port_id, "parent_row_id": parent,
        "amba11_second_side": second_side,
        "last_known_hierarchy": bridge_instance or endpoint,
    }


def _grid_registry(masters: int, slaves: int) -> list:
    rows = [_reg_row(f"S{i:02d}_AXI_", "AXI4", f"u_m{i}", "master",
                     channel=f"ch_m{i}") for i in range(masters)]
    rows += [_reg_row(f"M{j:02d}_AXI_", "AXI4", f"u_s{j}", "slave",
                      channel=f"ch_s{j}") for j in range(slaves)]
    return rows


@pytest.mark.parametrize("m,n", [(1, 1), (2, 2), (3, 4), (5, 3)])
def test_the_plan_scales_to_any_fabric_size(m, n):
    plan = build_fabric_scaling_plan(_grid_registry(m, n), assume_full_connectivity=True)
    assert plan.fabric_size == {"masters": m, "slaves": n, "bridges": 0, "pairs": m * n}
    assert len(plan.per_port_channels) == m + n
    assert plan.id_width == {"status": "COMPUTED", "value": plan.id_width["value"],
                             "formula": "ceil(log2(M)) + max_m(I_m)",
                             "master_id_widths": plan.id_width["master_id_widths"],
                             "computed_by": "amba_fabric_generator.compute_id_width"}
    assert plan.id_width["value"] == (m - 1).bit_length() + 4
    assert_every_port_has_its_own_channel(plan)


def test_mixed_protocols_carry_their_own_traffic_policy():
    rows = _grid_registry(2, 0)
    rows.append(_reg_row("M00_AXI_", "AXI4", "u_ddr", "slave", channel="ch_ddr"))
    rows.append(_reg_row("M01_APB_", "APB4", "u_periph", "slave", channel="ch_apb"))
    plan = build_fabric_scaling_plan(rows, assume_full_connectivity=True)
    assert plan.mixed_protocol is True
    policies = {p["port_id"]: p["policy"] for p in plan.traffic_policies}
    assert policies["M01_APB_"] == TRAFFIC_POLICY_SERIALIZED
    assert policies["M00_AXI_"] == TRAFFIC_POLICY_PARALLEL
    crossings = {(p["master_id"], p["slave_id"]): p["protocol_crossing"]
                 for p in plan.scoreboard_matrix}
    assert crossings[("u_m0", "u_periph")] is True
    assert crossings[("u_m0", "u_ddr")] is False


def test_an_unresolved_protocol_gets_no_traffic_policy_by_default():
    assert traffic_policy_for("SOMETHING_UNRESOLVED")["policy"] == REQUIRED_HUMAN_INPUT


def test_masters_sharing_a_slave_get_an_interlock_and_others_do_not():
    rows = _grid_registry(2, 2)
    plan = build_fabric_scaling_plan(rows, connectivity={
        "u_m0": {"accessible_slaves": ["u_s0"],
                 "excluded": [{"slave_id": "u_s1", "waiver_evidence": "not wired"}]},
        "u_m1": {"accessible_slaves": ["u_s0", "u_s1"], "excluded": []},
    })
    interlock = next(i for i in plan.interlocks
                     if {i["master_a"], i["master_b"]} == {"u_m0", "u_m1"})
    assert interlock["verdict"] == INTERLOCK_REQUIRED
    assert interlock["dependency"] == INTERLOCK_DEPENDENCY_SHARED_SLAVE
    assert interlock["shared_resources"] == ["u_s0"]


def test_masters_with_no_shared_resource_are_explicitly_not_interlocked():
    rows = _grid_registry(2, 2)
    plan = build_fabric_scaling_plan(rows, connectivity={
        "u_m0": {"accessible_slaves": ["u_s0"],
                 "excluded": [{"slave_id": "u_s1", "waiver_evidence": "not wired"}]},
        "u_m1": {"accessible_slaves": ["u_s1"],
                 "excluded": [{"slave_id": "u_s0", "waiver_evidence": "not wired"}]},
    })
    interlock = plan.interlocks[0]
    assert interlock["verdict"] == INTERLOCK_NOT_REQUIRED
    assert interlock["shared_resources"] == []
    assert "without an actual dependency" in interlock["rationale"]


def test_a_shared_serialized_apb_segment_outranks_a_plain_shared_slave():
    rows = _grid_registry(2, 0)
    rows.append(_reg_row("M00_APB_", "APB4", "u_periph", "slave", channel="ch_apb"))
    plan = build_fabric_scaling_plan(rows, assume_full_connectivity=True)
    interlock = plan.interlocks[0]
    assert interlock["verdict"] == INTERLOCK_REQUIRED
    assert interlock["dependency"] == afa.INTERLOCK_DEPENDENCY_SERIALIZED_SEGMENT


def test_an_unresolvable_pair_is_refused_never_guessed():
    rows = _grid_registry(1, 2)
    with pytest.raises(FabricAnalysisError) as exc:
        build_fabric_scaling_plan(rows, connectivity={
            "u_m0": {"accessible_slaves": ["u_s0"], "excluded": []}})
    assert exc.value.reason == "AMBA25_SCOREBOARD_MATRIX_UNRESOLVED"
    assert exc.value.detail["reason"] == "UNRESOLVED_PAIR"


def test_two_ports_on_one_scoreboard_channel_is_refused():
    rows = _grid_registry(2, 1)
    for row in rows:
        row["scoreboard_channel"] = "the_one_channel"
    plan = build_fabric_scaling_plan(rows, assume_full_connectivity=True)
    with pytest.raises(FabricAnalysisError) as exc:
        assert_every_port_has_its_own_channel(plan)
    assert exc.value.reason == "AMBA25_SCOREBOARD_CHANNEL_SHARED_BY_TWO_PORTS"


def test_required_human_input_channels_do_not_count_as_a_collision():
    plan = build_fabric_scaling_plan(_grid_registry(2, 2), assume_full_connectivity=True)
    for entry in plan.per_port_channels:
        entry["scoreboard_channel"] = REQUIRED_HUMAN_INPUT
    assert_every_port_has_its_own_channel(plan)


def test_a_protocol_bridge_is_a_distinct_node_with_both_sides():
    rows = _grid_registry(1, 0)
    rows.append(_reg_row("M00_AXI_", "AXI4", "u_apb_bridge", "slave",
                         channel="ch_brg"))
    rows.append(_reg_row("M00_AXI_#bridge1", "APB4", "u_apb_bridge", "slave",
                         channel="ch_brg_apb", second_side=True,
                         parent="M00_AXI_", bridge_instance="u_apb_bridge"))
    plan = build_fabric_scaling_plan(rows, assume_full_connectivity=True)
    assert len(plan.bridges) == 1
    bridge = plan.bridges[0]
    assert bridge["upstream_protocol"] == "AXI4"
    assert bridge["downstream_protocol"] == "APB4"
    assert bridge["upstream_traffic_policy"] == TRAFFIC_POLICY_PARALLEL
    assert bridge["downstream_traffic_policy"] == TRAFFIC_POLICY_SERIALIZED
    # The bridge's own second side must never be counted as an endpoint.
    assert [s["endpoint"] for s in plan.slaves] == ["u_apb_bridge"]


@requires_verible
def test_the_real_pipeline_produces_a_mixed_protocol_scaling_plan(registry):
    plan = build_fabric_scaling_plan(registry, assume_full_connectivity=True)
    assert [m["endpoint"] for m in plan.masters] == ["u_cpu", "u_dma"]
    assert plan.slaves, "the fixture traces at least one slave endpoint"
    assert plan.fabric_size["pairs"] == len(plan.masters) * len(plan.slaves)
    assert {p["protocol"] for p in plan.traffic_policies} >= {"AXI4"}
    assert any(b["downstream_protocol"] == "APB4" for b in plan.bridges)
    assert_every_port_has_its_own_channel(plan)
    text = render_fabric_scaling_report(plan)
    assert "AMBA-25 Scoreboard + Port Scaling" in text
    assert "Cross-port scheduling interlocks" in text


# ===========================================================================
# AMBA-30 / AMBA-31: this layer emits no bind statement, ever
# ===========================================================================

@requires_verible
def test_no_bind_statement_is_ever_emitted(netlist, traces, matrix, registry):
    import inspect

    afd.assert_no_bind_statement(inspect.getsource(afa))
    afd.assert_no_bind_statement(render_clock_reset_domain_report(
        analyze_all_bind_point_domains(netlist, matrix, traces)))
    afd.assert_no_bind_statement(render_fabric_scaling_report(
        build_fabric_scaling_plan(registry, assume_full_connectivity=True)))
    afd.assert_no_bind_statement(render_address_map_cross_check_report(
        cross_check_fabric_address_map(
            [_claim(ADDRESS_MAP_SOURCE_RTL_DECODER, DDR, 0, HALF)], [DDR],
            address_width=32)))


def test_the_fixture_itself_contains_no_bind_statement(tmp_path):
    """The synthetic RTL is the one place a bind-like construct could
    legitimately live in this whole layer -- and it contains none."""
    afd.assert_no_bind_statement(write_fixture(tmp_path).read_text(encoding="utf-8"))
