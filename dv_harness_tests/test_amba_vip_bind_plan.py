"""Tests for AMBA-15..20 in dv_harness/amba_fabric_discovery.py -- the VIP bind
location checklist, the fabric-port-to-VIP-bind matrix, the unresolved port
table, the topology summary, the topology tree and the VIP instance plan -- and
for the AMBA-15 evidence vocabulary they read from dv_harness/connectivity.py.

Everything topology-shaped here runs against a REAL `verible-verilog-syntax`
parse of a synthetic multi-master / multi-slave AMBA4 SoC written to a tmp dir,
never a hand-built graph object: a hand-built graph proves the code works on the
shape the test author imagined rather than on the shape verible really produces.
Skipped (never faked) without verible on PATH.

The fixture is deliberately NOT a clean topology. Five of its seven fabric ports
are designed to leave a specific AMBA-15 point unprovable -- an ambiguous clock,
a parameterized data width, an unparsed black box, an unconnected port, a
multiple-destination fan-out -- because a bind-location checklist proven only on
a fabric where everything is knowable is exactly the "happy path only" coverage
this project has been burned by before. The READY row is the minority case.

The RTL fixture is synthetic and is the only place a bind-like construct could
legitimately live; it contains none, and `test_no_bind_statement_anywhere`
asserts that of the module's own source and of every artifact it renders, per
the AMBA-30 / AMBA-31 review gate.
"""
from __future__ import annotations

import shutil

import pytest

from dv_harness import amba_fabric_discovery as afd
from dv_harness import connectivity
from dv_harness.amba_fabric_discovery import (
    BIND_CHECK_FAILED,
    BIND_CHECK_KNOWN,
    BIND_CHECK_NOT_APPLICABLE,
    BIND_CHECK_UNKNOWN,
    BIND_LOCATION_CHECK_POINTS,
    BIND_READINESS_BLOCKED,
    BIND_READINESS_PARTIAL,
    BIND_READINESS_READY,
    BIND_READINESS_VALUES,
    FabricDiscoveryError,
    MULTIPLE_BRANCH_PARENT_BIND,
    TraceTerminationStatus,
    VIP_MODE_ACTIVE_DRIVER,
    VIP_MODE_PASSIVE_MONITOR,
    VIP_MSM_MONITOR,
    assert_no_bind_statement,
    assert_vip_plan_defaults_passive,
    build_amba_topology_summary,
    build_fabric_vip_bind_matrix,
    build_fabric_netlist,
    build_unresolved_fabric_port_table,
    build_vip_bind_plan,
    build_vip_instance_plan,
    parent_matrix_rows,
    parse_instance_path,
    render_fabric_vip_bind_matrix,
    render_topology_tree,
    render_unresolved_fabric_port_table,
    render_vip_bind_plan_report,
    render_vip_instance_plan,
    trace_all_fabric_ports,
    validate_vip_bind_location,
    vip_instance_records_from_plan,
)
from dv_harness.verible_parser import parse_file

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)


# ---------------------------------------------------------------------------
# Synthetic RTL fixture
#
# Signal names and widths are spelled out here rather than imported from
# connectivity.py: a fixture built from the same constants the code under test
# reads would pass even if both were wrong together.
# ---------------------------------------------------------------------------

#: signal -> (driven by 'req' initiator or 'rsp' target, declared packed range)
AXI4_SIGNALS = {
    "AWVALID": ("req", ""), "AWADDR": ("req", "[31:0]"), "AWID": ("req", "[3:0]"),
    "AWLEN": ("req", "[7:0]"), "AWSIZE": ("req", "[2:0]"),
    "AWBURST": ("req", "[1:0]"), "AWUSER": ("req", "[3:0]"),
    "AWREADY": ("rsp", ""),
    "WVALID": ("req", ""), "WDATA": ("req", "[63:0]"), "WLAST": ("req", ""),
    "WUSER": ("req", "[3:0]"), "WREADY": ("rsp", ""),
    "BVALID": ("rsp", ""), "BRESP": ("rsp", "[1:0]"), "BID": ("rsp", "[3:0]"),
    "BUSER": ("rsp", "[3:0]"), "BREADY": ("req", ""),
    "ARVALID": ("req", ""), "ARADDR": ("req", "[31:0]"), "ARID": ("req", "[3:0]"),
    "ARLEN": ("req", "[7:0]"), "ARSIZE": ("req", "[2:0]"),
    "ARBURST": ("req", "[1:0]"), "ARUSER": ("req", "[3:0]"),
    "ARREADY": ("rsp", ""),
    "RVALID": ("rsp", ""), "RDATA": ("rsp", "[63:0]"), "RRESP": ("rsp", "[1:0]"),
    "RID": ("rsp", "[3:0]"), "RLAST": ("rsp", ""), "RUSER": ("rsp", "[3:0]"),
    "RREADY": ("req", ""),
}
APB4_SIGNALS = {
    "PADDR": ("req", "[31:0]"), "PSEL": ("req", ""), "PENABLE": ("req", ""),
    "PWRITE": ("req", ""), "PWDATA": ("req", "[31:0]"), "PSTRB": ("req", "[3:0]"),
    "PPROT": ("req", "[2:0]"),
    "PRDATA": ("rsp", "[31:0]"), "PREADY": ("rsp", ""), "PSLVERR": ("rsp", ""),
}

#: The AXI4 address/data/ID/USER widths the fixture declares, as an independent
#: statement of what AMBA-15 points 8-11 must read back.
AXI4_ADDRESS_WIDTH = 32
AXI4_DATA_WIDTH = 64
AXI4_ID_WIDTH = 4
AXI4_USER_WIDTH = 4


def _ports(prefix: str, signals: dict, side: str, *, width_override: dict = None) -> list:
    """(direction, packed range, port name) for one bundle. `side` is the role
    THIS module plays: 'initiator' drives the request signals out."""
    out = []
    for sig, (kind, width) in signals.items():
        direction = ("output" if kind == "req" else "input") if side == "initiator" \
            else ("input" if kind == "req" else "output")
        out.append((direction, (width_override or {}).get(sig, width), f"{prefix}{sig}"))
    return out


def _sv_module(name: str, ports: list, body: str = "", params: str = "") -> str:
    decls = ",\n    ".join(
        f"{d} logic {w + ' ' if w else ''}{n}" for d, w, n in ports)
    header = f"module {name} {params}(\n    {decls}\n);\n"
    return header + body + "endmodule\n"


def _sv_inst(module: str, inst: str, conns: list) -> str:
    body = ",\n        ".join(f".{p}({n})" for p, n in conns)
    return f"    {module} {inst} (\n        {body}\n    );\n"


def _conns(prefix: str, signals: dict, net_prefix: str) -> list:
    return [(f"{prefix}{s}", f"{net_prefix}{s.lower()}") for s in signals]


def _nets(net_prefix: str, signals: dict) -> str:
    return "".join(f"    wire {w + ' ' if w else ''}{net_prefix}{s.lower()};\n"
                   for s, (_, w) in signals.items())


CLK_RST = [("input", "", "ACLK"), ("input", "", "ARESETN")]
APB_CLK_RST = [("input", "", "PCLK"), ("input", "", "PRESETN")]


def write_fixture(tmp_path):
    """One synthetic AMBA4 SoC: 2 fabric slave ports, 5 fabric master ports,
    and a different AMBA-15 obstacle behind most of them."""
    mods = []

    # -- a fully-knowable AXI4 master: literal widths, one clock, one reset.
    mods.append(_sv_module("cpu_core", CLK_RST + _ports("M_AXI_", AXI4_SIGNALS, "initiator")))

    # -- same interface, TWO clock ports. Nothing in the RTL says which one
    #    drives the interface, so AMBA-15 point 6 must report UNKNOWN.
    mods.append(_sv_module(
        "dma_engine",
        [("input", "", "ACLK"), ("input", "", "ACLK2"), ("input", "", "ARESETN")]
        + _ports("M_AXI_", AXI4_SIGNALS, "initiator")))

    # -- an AXI4 slave whose data width is a PARAMETER: point 9 unprovable,
    #    point 12 provable (the parameter list is right there).
    mods.append(_sv_module(
        "ddr_ctrl",
        CLK_RST + _ports("S_AXI_", AXI4_SIGNALS, "target",
                         width_override={"WDATA": "[DW-1:0]", "RDATA": "[DW-1:0]"}),
        params="#(parameter int DW = 64) "))

    # -- a fully-knowable AXI4 slave.
    mods.append(_sv_module("sram_ctrl", CLK_RST + _ports("S_AXI_", AXI4_SIGNALS, "target")))

    # -- AXI4 -> APB4 bridge and its APB4 peripheral (AMBA-11: both sides).
    mods.append(_sv_module(
        "axi_to_apb",
        CLK_RST + APB_CLK_RST
        + _ports("S_AXI_", AXI4_SIGNALS, "target")
        + _ports("M_APB_", APB4_SIGNALS, "initiator"),
        "    assign M_APB_PADDR = S_AXI_AWADDR;\n"
        "    assign M_APB_PWDATA = S_AXI_WDATA;\n"
        "    assign S_AXI_RDATA = M_APB_PRDATA;\n"))
    mods.append(_sv_module("apb_periph",
                           APB_CLK_RST + _ports("S_APB_", APB4_SIGNALS, "target")))

    # -- a decoder fanning one master port out to two SRAMs (AMBA-13).
    mods.append(_sv_module(
        "axi_decoder",
        CLK_RST + _ports("S_AXI_", AXI4_SIGNALS, "target")
        + _ports("M0_AXI_", AXI4_SIGNALS, "initiator")
        + _ports("M1_AXI_", AXI4_SIGNALS, "initiator"),
        "    assign M0_AXI_AWADDR = S_AXI_AWADDR;\n"
        "    assign M1_AXI_AWADDR = S_AXI_AWADDR;\n"
        "    assign M0_AXI_ARADDR = S_AXI_ARADDR;\n"
        "    assign M1_AXI_ARADDR = S_AXI_ARADDR;\n"))

    # -- the fabric itself.
    fabric_ports = (
        CLK_RST
        + _ports("S00_AXI_", AXI4_SIGNALS, "target")      # <- cpu
        + _ports("S01_AXI_", AXI4_SIGNALS, "target")      # <- dma (2 clocks)
        + _ports("M00_AXI_", AXI4_SIGNALS, "initiator")   # -> ddr (param width)
        + _ports("M01_AXI_", AXI4_SIGNALS, "initiator")   # -> axi/apb bridge
        + _ports("M02_AXI_", AXI4_SIGNALS, "initiator")   # -> decoder -> 2 srams
        + _ports("M03_AXI_", AXI4_SIGNALS, "initiator")   # -> unparsed black box
        + _ports("M04_AXI_", AXI4_SIGNALS, "initiator")   # -> nothing
    )
    mods.append(_sv_module("axi_fabric", fabric_ports))

    # -- the SoC top.
    groups = [("cpu_", AXI4_SIGNALS), ("dma_", AXI4_SIGNALS), ("ddr_", AXI4_SIGNALS),
              ("brg_", AXI4_SIGNALS), ("apb_", APB4_SIGNALS), ("dec_", AXI4_SIGNALS),
              ("sram0_", AXI4_SIGNALS), ("sram1_", AXI4_SIGNALS), ("opq_", AXI4_SIGNALS)]
    body = "    wire clk;\n    wire rstn;\n"
    body += "".join(_nets(p, s) for p, s in groups)
    clk = [("ACLK", "clk"), ("ARESETN", "rstn")]
    apb_clk = [("PCLK", "clk"), ("PRESETN", "rstn")]
    body += _sv_inst("cpu_core", "u_cpu", clk + _conns("M_AXI_", AXI4_SIGNALS, "cpu_"))
    body += _sv_inst("dma_engine", "u_dma",
                     [("ACLK", "clk"), ("ACLK2", "clk"), ("ARESETN", "rstn")]
                     + _conns("M_AXI_", AXI4_SIGNALS, "dma_"))
    body += _sv_inst(
        "axi_fabric", "u_fabric",
        clk
        + _conns("S00_AXI_", AXI4_SIGNALS, "cpu_")
        + _conns("S01_AXI_", AXI4_SIGNALS, "dma_")
        + _conns("M00_AXI_", AXI4_SIGNALS, "ddr_")
        + _conns("M01_AXI_", AXI4_SIGNALS, "brg_")
        + _conns("M02_AXI_", AXI4_SIGNALS, "dec_")
        + _conns("M03_AXI_", AXI4_SIGNALS, "opq_"))
    body += _sv_inst("ddr_ctrl", "u_ddr", clk + _conns("S_AXI_", AXI4_SIGNALS, "ddr_"))
    body += _sv_inst("axi_to_apb", "u_bridge",
                     clk + apb_clk + _conns("S_AXI_", AXI4_SIGNALS, "brg_")
                     + _conns("M_APB_", APB4_SIGNALS, "apb_"))
    body += _sv_inst("apb_periph", "u_periph",
                     apb_clk + _conns("S_APB_", APB4_SIGNALS, "apb_"))
    body += _sv_inst("axi_decoder", "u_decoder",
                     clk + _conns("S_AXI_", AXI4_SIGNALS, "dec_")
                     + _conns("M0_AXI_", AXI4_SIGNALS, "sram0_")
                     + _conns("M1_AXI_", AXI4_SIGNALS, "sram1_"))
    body += _sv_inst("sram_ctrl", "u_sram0", clk + _conns("S_AXI_", AXI4_SIGNALS, "sram0_"))
    body += _sv_inst("sram_ctrl", "u_sram1", clk + _conns("S_AXI_", AXI4_SIGNALS, "sram1_"))
    # opaque_ip is deliberately never declared: an unparsed black box. It is
    # instantiated with a SECOND, downstream bundle, so the trace cannot tell
    # whether it terminates here or passes through -- TRACE_BLOCKED, not a
    # guessed endpoint.
    body += _sv_inst("opaque_ip", "u_opaque",
                     _conns("S_AXI_", AXI4_SIGNALS, "opq_")
                     + [(f"M_APB_{s}", f"opq_apb_{s.lower()}") for s in APB4_SIGNALS])

    mods.append(_sv_module("soc_top", [("input", "", "EXT_CLK")], body))

    path = tmp_path / "amba4_bind_plan_fixture.sv"
    path.write_text("\n".join(mods), encoding="utf-8")
    return path


FABRIC = ("u_fabric",)


@pytest.fixture(scope="module")
def netlist(tmp_path_factory):
    if shutil.which(VERIBLE_BIN) is None:
        pytest.skip("verible-verilog-syntax not on PATH")
    sv = write_fixture(tmp_path_factory.mktemp("amba_bind_plan"))
    return build_fabric_netlist([parse_file(sv)], "soc_top")


@pytest.fixture(scope="module")
def traces(netlist):
    return trace_all_fabric_ports(netlist, FABRIC)


@pytest.fixture(scope="module")
def plan(netlist, traces):
    return build_vip_bind_plan(netlist, traces)


def _row(rows, fabric_port):
    return next(r for r in rows if r["fabric_port"] == fabric_port)


# ---------------------------------------------------------------------------
# connectivity.py's AMBA-15 evidence vocabulary
# ---------------------------------------------------------------------------

def test_clock_reset_prefers_spec_named_bundle_prefixed_port():
    verdict = connectivity.find_amba_clock_reset_ports(
        "AXI4", "S00_AXI_", ["S00_AXI_ACLK", "S00_AXI_ARESETN", "ACLK", "ARESETN"])
    assert verdict["clock"]["status"] == connectivity.CLOCK_RESET_RESOLVED
    assert verdict["clock"]["port"] == "S00_AXI_ACLK"
    assert verdict["clock"]["evidence"] == connectivity.CLOCK_RESET_EVIDENCE_SPEC_PREFIXED
    assert verdict["reset"]["port"] == "S00_AXI_ARESETN"


def test_clock_reset_accepts_a_shared_unprefixed_spec_named_port():
    verdict = connectivity.find_amba_clock_reset_ports(
        "AHB_LITE", "M_", ["HCLK", "HRESETN", "M_HADDR"])
    assert verdict["clock"]["port"] == "HCLK"
    assert verdict["clock"]["evidence"] == connectivity.CLOCK_RESET_EVIDENCE_SPEC_SHARED
    assert verdict["reset"]["port"] == "HRESETN"


def test_two_candidate_clocks_are_ambiguous_not_arbitrarily_chosen():
    verdict = connectivity.find_amba_clock_reset_ports(
        "AXI4", "M_AXI_", ["ACLK", "ACLK2", "ARESETN", "M_AXI_AWVALID"])
    assert verdict["clock"]["status"] == connectivity.CLOCK_RESET_AMBIGUOUS
    assert verdict["clock"]["port"] is None
    assert verdict["clock"]["candidates"] == ["ACLK", "ACLK2"]
    # The reset is unaffected: one unresolvable fact does not poison the other.
    assert verdict["reset"]["status"] == connectivity.CLOCK_RESET_RESOLVED


def test_no_clock_port_at_all_is_reported_as_such():
    verdict = connectivity.find_amba_clock_reset_ports("APB4", "S_APB_", ["S_APB_PADDR"])
    assert verdict["clock"]["status"] == connectivity.CLOCK_RESET_NO_CANDIDATE
    assert verdict["reset"]["status"] == connectivity.CLOCK_RESET_NO_CANDIDATE


def test_generic_clock_name_is_only_used_when_no_spec_named_port_exists():
    spec = connectivity.find_amba_clock_reset_ports("AXI4", "", ["ACLK", "clk"])
    assert spec["clock"]["port"] == "ACLK"
    generic = connectivity.find_amba_clock_reset_ports("AXI4", "", ["clk", "rst_n"])
    assert generic["clock"]["port"] == "clk"
    assert generic["clock"]["evidence"] == connectivity.CLOCK_RESET_EVIDENCE_GENERIC_SHARED
    assert generic["reset"]["port"] == "rst_n"


def test_amba_signal_role_is_token_based():
    assert connectivity.amba_signal_role("S_AXI_AWADDR") == connectivity.AMBA_SIGNAL_ROLE_ADDRESS
    assert connectivity.amba_signal_role("M_APB_PRDATA") == connectivity.AMBA_SIGNAL_ROLE_DATA
    assert connectivity.amba_signal_role("AWID") == connectivity.AMBA_SIGNAL_ROLE_ID
    assert connectivity.amba_signal_role("m_axis_tuser") == connectivity.AMBA_SIGNAL_ROLE_USER
    # AWLEN is address-CHANNEL signalling; its width is not the address width.
    assert connectivity.amba_signal_role("S_AXI_AWLEN") is None
    assert connectivity.amba_signal_role("some_address_valid") is None


def test_protocols_that_have_no_id_or_user_signals_say_so():
    for protocol in ("APB4", "AHB_LITE", "AXI4_LITE"):
        roles = connectivity.AMBA_PROTOCOL_SIGNAL_ROLES[protocol]
        assert connectivity.AMBA_SIGNAL_ROLE_ID not in roles
        assert connectivity.AMBA_SIGNAL_ROLE_USER not in roles
    # AXI4-Stream is not memory-mapped, so it has no address at all.
    assert connectivity.AMBA_SIGNAL_ROLE_ADDRESS not in \
        connectivity.AMBA_PROTOCOL_SIGNAL_ROLES["AXI4_STREAM"]


def test_every_amba4_protocol_has_a_family_and_signal_role_entry():
    for protocol in connectivity.AMBA4_PROTOCOLS:
        assert protocol in connectivity.AMBA_PROTOCOL_FAMILY
        assert protocol in connectivity.AMBA_PROTOCOL_SIGNAL_ROLES
        family = connectivity.AMBA_PROTOCOL_FAMILY[protocol]
        assert family in connectivity.AMBA_FAMILY_CLOCK_SIGNALS
        assert family in connectivity.AMBA_FAMILY_RESET_SIGNALS


def test_axi_user_sidebands_are_in_the_signal_vocabulary():
    # Without this, an AWUSER port is not grouped into its own interface's
    # bundle and AMBA-15 point 11 could never read its width.
    assert connectivity.AXI_USER_SIDEBAND_SIGNALS <= connectivity.ALL_AMBA_SIGNAL_NAMES
    assert afd.amba_bundle_prefix("S_AXI_AWUSER") == "S_AXI_"


# ---------------------------------------------------------------------------
# connectivity.render_markdown_table
# ---------------------------------------------------------------------------

def test_markdown_table_renders_headers_alignment_and_rows():
    text = connectivity.render_markdown_table(
        [("a", "Alpha"), ("n", "Count")], [{"a": "x", "n": 3}], aligns={"n": "right"})
    assert text.splitlines() == ["| Alpha | Count |", "|---|---:|", "| x | 3 |"]


def test_markdown_table_of_no_rows_says_so_instead_of_a_bare_header():
    text = connectivity.render_markdown_table(["a", "b"], [], empty_note="(nothing)")
    assert "(nothing)" in text.splitlines()[-1]


def test_markdown_table_tolerates_a_row_missing_a_column():
    text = connectivity.render_markdown_table(["a", "b"], [{"a": 1}])
    assert text.splitlines()[-1] == "| 1 |  |"


def test_markdown_table_refuses_an_unknown_alignment():
    with pytest.raises(connectivity.ConnectivityError) as exc:
        connectivity.render_markdown_table(["a"], [], aligns={"a": "middle"})
    assert "MARKDOWN_TABLE_UNKNOWN_ALIGNMENT" in str(exc.value)


# ---------------------------------------------------------------------------
# AMBA-15: the 13-point bind location checklist
# ---------------------------------------------------------------------------

def test_parse_instance_path_round_trips_including_the_top_module():
    assert parse_instance_path("u_a/u_b") == ("u_a", "u_b")
    assert parse_instance_path("<top>") == ()
    assert parse_instance_path("") == ()


@requires_verible
def test_checklist_always_answers_all_thirteen_points_in_order(netlist):
    validation = validate_vip_bind_location(netlist, ("u_cpu",), "M_AXI_")
    assert [c.point for c in validation.checks] == list(range(1, 14))
    assert [c.key for c in validation.checks] == [k for _, k, _ in BIND_LOCATION_CHECK_POINTS]


@requires_verible
def test_a_fully_knowable_location_is_ready_with_real_widths(netlist):
    validation = validate_vip_bind_location(netlist, ("u_cpu",), "M_AXI_")
    assert validation.readiness == BIND_READINESS_READY
    assert validation.value_of("protocol_identified") == "AXI4"
    assert validation.value_of("clock_known") == "ACLK"
    assert validation.value_of("reset_known") == "ARESETN"
    assert validation.value_of("address_width_known") == str(AXI4_ADDRESS_WIDTH)
    assert validation.value_of("data_width_known") == str(AXI4_DATA_WIDTH)
    assert validation.value_of("id_width_known") == str(AXI4_ID_WIDTH)
    assert validation.value_of("user_width_known") == str(AXI4_USER_WIDTH)
    assert validation.value_of("parameterization_known") == "NONE"
    assert validation.by_key["uvm_accessible"].status == BIND_CHECK_KNOWN
    assert validation.unknown_points == []


@requires_verible
def test_two_candidate_clocks_hold_a_location_at_partial(netlist):
    validation = validate_vip_bind_location(netlist, ("u_dma",), "M_AXI_")
    clock = validation.by_key["clock_known"]
    assert clock.status == BIND_CHECK_UNKNOWN
    assert "ACLK" in clock.evidence and "ACLK2" in clock.evidence
    # Everything else about this location IS knowable, so it is PARTIAL and not
    # UNKNOWN -- the distinction a reviewer acts on.
    assert validation.readiness == BIND_READINESS_PARTIAL
    assert validation.by_key["reset_known"].status == BIND_CHECK_KNOWN
    assert validation.value_of("data_width_known") == str(AXI4_DATA_WIDTH)


@requires_verible
def test_a_parameterized_width_is_unknown_and_the_parameter_list_is_known(netlist):
    validation = validate_vip_bind_location(netlist, ("u_ddr",), "S_AXI_")
    data = validation.by_key["data_width_known"]
    assert data.status == BIND_CHECK_UNKNOWN
    assert "DW-1:0" in data.evidence
    params = validation.by_key["parameterization_known"]
    assert params.status == BIND_CHECK_KNOWN
    assert "DW" in params.evidence and "64" in params.evidence
    # The address width is a literal on the same interface and stays known: an
    # unresolvable width does not spread to its neighbours.
    assert validation.value_of("address_width_known") == str(AXI4_ADDRESS_WIDTH)
    assert validation.readiness == BIND_READINESS_PARTIAL


@requires_verible
def test_apb_reports_id_and_user_widths_as_not_applicable_and_stays_ready(netlist):
    validation = validate_vip_bind_location(netlist, ("u_periph",), "S_APB_")
    assert validation.protocol == "APB4"
    assert validation.by_key["id_width_known"].status == BIND_CHECK_NOT_APPLICABLE
    assert validation.by_key["user_width_known"].status == BIND_CHECK_NOT_APPLICABLE
    assert validation.value_of("clock_known") == "PCLK"
    assert validation.value_of("reset_known") == "PRESETN"
    # A protocol that HAS no ID width is not a protocol whose ID width is a gap.
    assert validation.readiness == BIND_READINESS_READY


@requires_verible
def test_an_unparsed_black_box_reports_unknowns_not_confident_answers(netlist):
    validation = validate_vip_bind_location(netlist, ("u_opaque",), "S_AXI_")
    assert validation.by_key["hierarchy_exists"].status == BIND_CHECK_KNOWN
    for key in ("roles_identified", "parameterization_known", "data_width_known",
                "uvm_accessible"):
        assert validation.by_key[key].status == BIND_CHECK_UNKNOWN, key
    assert validation.readiness == BIND_READINESS_PARTIAL


@requires_verible
def test_a_nonexistent_hierarchy_is_blocked_and_says_why_once(netlist):
    validation = validate_vip_bind_location(netlist, ("u_not_a_real_instance",), "S_AXI_")
    assert validation.readiness == BIND_READINESS_BLOCKED
    assert validation.by_key["hierarchy_exists"].status == BIND_CHECK_FAILED
    assert all(c.status == BIND_CHECK_FAILED for c in validation.checks)
    assert len(validation.checks) == 13


@requires_verible
def test_a_missing_bundle_at_a_real_instance_is_blocked(netlist):
    validation = validate_vip_bind_location(netlist, ("u_cpu",), "NO_SUCH_PREFIX_")
    assert validation.by_key["hierarchy_exists"].status == BIND_CHECK_KNOWN
    assert validation.by_key["amba_signals_exist"].status == BIND_CHECK_FAILED
    assert validation.readiness == BIND_READINESS_BLOCKED


@requires_verible
def test_checklist_renders_all_thirteen_rows(netlist):
    text = validate_vip_bind_location(netlist, ("u_cpu",), "M_AXI_").render_checklist()
    for _, _, label in BIND_LOCATION_CHECK_POINTS:
        assert label in text


# ---------------------------------------------------------------------------
# AMBA-16: the fabric port to VIP bind matrix
# ---------------------------------------------------------------------------

@requires_verible
def test_every_fabric_port_appears_exactly_once_as_a_parent_row(netlist, traces, plan):
    parents = parent_matrix_rows(plan.matrix)
    assert [r["fabric_port"] for r in parents] == [t.interface_id for t in traces]
    assert len(parents) == 7


@requires_verible
def test_matrix_rows_carry_all_twelve_mandated_columns(plan):
    for row in plan.matrix:
        for key, _ in afd.AMBA16_MATRIX_COLUMNS:
            assert key in row, key
            assert row[key] not in (None, "")


@requires_verible
def test_a_resolved_port_carries_its_endpoint_trace_path_and_bind_candidate(plan):
    row = _row(plan.matrix, "u_fabric:S00_AXI_")
    assert row["protocol"] == "AXI4"
    assert row["fabric_role"] == connectivity.FABRIC_SIDE_SLAVE_INTERFACE
    assert row["external_endpoint_role"] == connectivity.EXTERNAL_ENDPOINT_MASTER
    assert "u_cpu" in row["endpoint"]
    assert "u_cpu" in row["proposed_vip_bind_hierarchy"]
    assert row["clock"] == "ACLK"
    assert row["status"] == BIND_READINESS_READY
    assert row["confidence"].startswith("T")


@requires_verible
def test_a_multiple_destination_port_gets_child_rows_and_chooses_none(plan):
    parent = _row(plan.matrix, "u_fabric:M02_AXI_")
    assert parent["trace_status"] == TraceTerminationStatus.MULTIPLE_DESTINATION.value
    assert parent["proposed_vip_bind_hierarchy"] == MULTIPLE_BRANCH_PARENT_BIND
    children = [r for r in plan.matrix if r.get("parent_row_id") == parent["row_id"]]
    assert len(children) == 2
    endpoints = sorted(r["endpoint"] for r in children)
    assert "u_sram0" in endpoints[0] and "u_sram1" in endpoints[1]
    assert all(r["proposed_vip_bind_hierarchy"] != MULTIPLE_BRANCH_PARENT_BIND
               for r in children)


@requires_verible
def test_a_multiple_destination_parent_is_never_ready_however_clean_its_branches(plan):
    parent = _row(plan.matrix, "u_fabric:M02_AXI_")
    children = [r for r in plan.matrix if r.get("parent_row_id") == parent["row_id"]]
    assert all(r["status"] == BIND_READINESS_READY for r in children)
    # The branches validate cleanly, but AMBA-12/13 leave which of them to
    # observe to a human, so the PORT still carries an open decision.
    assert parent["status"] == BIND_READINESS_PARTIAL


@requires_verible
def test_a_bridge_records_both_sides_without_relabelling_either(plan):
    upstream = _row(plan.matrix, "u_fabric:M01_AXI_")
    assert upstream["protocol"] == "AXI4"
    assert upstream["trace_status"] == TraceTerminationStatus.PROTOCOL_BRIDGE_FOUND.value
    # AMBA-11: the downstream side is recorded as a subordinate row, and its
    # protocol is its OWN classification, never the upstream's.
    downstream = next(r for r in plan.matrix if r.get("amba11_second_side"))
    assert downstream["parent_row_id"] == upstream["row_id"]
    assert downstream["protocol"] == "APB4"
    assert "u_bridge:M_APB_" in downstream["proposed_vip_bind_hierarchy"]
    assert downstream["clock"] == "PCLK"


@requires_verible
def test_the_bridge_second_side_is_recorded_but_not_auto_planned(plan):
    # AMBA-11 recommends both sides "only when justified by verification
    # goals", so VIP-B is evidence for a reviewer, not a VIP the plan asks for.
    assert any(r.get("amba11_second_side") for r in plan.matrix)
    assert not any(r["protocol"] == "APB4" for r in plan.vip_instances)


@requires_verible
def test_row_ids_are_unique_and_usable_by_the_existing_row_lock_store(plan, tmp_path):
    ids = [r["row_id"] for r in plan.matrix]
    assert len(ids) == len(set(ids))
    store = connectivity.RowLockStore(tmp_path / "locks.json")
    row = _row(plan.matrix, "u_fabric:S00_AXI_")
    content = {k: v for k, v in row.items() if k != "validation"}
    store.confirm_row(row["row_id"], content, confirmed_by="test-reviewer",
                      evidence=["fixture RTL"])
    assert store.is_locked(row["row_id"])


@requires_verible
def test_matrix_renders_the_doc_s_twelve_headers(plan):
    text = render_fabric_vip_bind_matrix(plan.matrix)
    header = text.splitlines()[0]
    for _, label in afd.AMBA16_MATRIX_COLUMNS:
        assert label in header


# ---------------------------------------------------------------------------
# AMBA-17: the unresolved port table
# ---------------------------------------------------------------------------

@requires_verible
def test_unresolved_table_lists_the_blocked_and_not_found_ports(plan):
    ports = {r["fabric_port"] for r in plan.unresolved}
    assert "u_fabric:M03_AXI_" in ports      # unparsed black box downstream
    assert "u_fabric:M04_AXI_" in ports      # nothing connected
    assert "u_fabric:S00_AXI_" not in ports  # fully resolved and READY


@requires_verible
def test_every_unresolved_row_carries_all_eight_columns_and_a_real_next_action(plan):
    assert plan.unresolved
    for row in plan.unresolved:
        for key, _ in afd.AMBA17_UNRESOLVED_COLUMNS:
            assert key in row and str(row[key]).strip(), key
        assert row["last_known_hierarchy"]
        assert row["next_best_action"] != connectivity.REQUIRED_HUMAN_INPUT


@requires_verible
def test_a_blocked_trace_next_action_names_the_missing_rtl(plan):
    row = _row(plan.unresolved, "u_fabric:M03_AXI_")
    assert row["trace_result"] == TraceTerminationStatus.TRACE_BLOCKED.value
    assert "unparsed" in row["next_best_action"]
    assert row["missing_evidence"] != "-"


@requires_verible
def test_a_destination_not_found_row_says_the_endpoint_may_be_outside_the_design(plan):
    row = _row(plan.unresolved, "u_fabric:M04_AXI_")
    assert row["trace_result"] == TraceTerminationStatus.DESTINATION_NOT_FOUND.value
    assert "outside the parsed design" in row["next_best_action"]


def test_unresolved_table_is_rendered_even_when_empty():
    text = render_unresolved_fabric_port_table([])
    assert "Fabric Port" in text
    assert "none" in text.lower()


@requires_verible
def test_every_amba14_unresolved_status_has_a_next_best_action():
    for status in afd.UNRESOLVED_TERMINATION_STATUSES:
        assert status.value in afd.NEXT_BEST_ACTION_BY_STATUS, status.value


# ---------------------------------------------------------------------------
# AMBA-18: the topology summary
# ---------------------------------------------------------------------------

@requires_verible
def test_summary_counts_slave_master_and_total_fabric_ports(plan):
    summary = plan.summary
    assert summary["total_fabric_slave_ports"] == 2
    assert summary["total_fabric_master_ports"] == 5
    assert summary["total_amba_ports"] == 7


@requires_verible
def test_summary_lists_all_ten_amba4_protocols_including_the_zero_counts(plan):
    rows = {r["protocol"]: r for r in plan.summary["protocol_counts"]["rows"]}
    for protocol in connectivity.AMBA4_PROTOCOLS:
        assert protocol in rows, protocol
    assert rows["AXI4"]["total"] == 7
    assert rows["APB4"]["total"] == 0


@requires_verible
def test_bind_readiness_tally_covers_every_fabric_port_exactly_once(plan):
    readiness = plan.summary["bind_readiness"]
    assert set(readiness) == set(BIND_READINESS_VALUES)
    assert sum(readiness.values()) == len(parent_matrix_rows(plan.matrix))
    assert readiness[BIND_READINESS_READY] >= 1
    assert readiness[BIND_READINESS_PARTIAL] >= 1


@requires_verible
def test_readiness_tally_agrees_with_the_matrix_it_came_from(netlist, traces, plan):
    recomputed = build_amba_topology_summary(netlist, traces, plan.matrix)
    assert recomputed["bind_readiness"] == plan.summary["bind_readiness"]
    for row in parent_matrix_rows(plan.matrix):
        assert row["status"] in BIND_READINESS_VALUES


@requires_verible
def test_summary_renders_the_three_totals_and_the_readiness_table(plan):
    text = afd.render_amba_topology_summary(plan.summary)
    assert "TOTAL FABRIC SLAVE PORTS: 2" in text
    assert "TOTAL FABRIC MASTER PORTS: 5" in text
    assert "TOTAL AMBA PORTS: 7" in text
    for value in BIND_READINESS_VALUES:
        assert value in text


# ---------------------------------------------------------------------------
# AMBA-19: the topology tree
# ---------------------------------------------------------------------------

@requires_verible
def test_tree_is_rooted_at_bus_fabric_with_protocol_and_role_labels(plan):
    lines = plan.tree.splitlines()
    assert lines[0] == "BUS_FABRIC"
    assert any("u_fabric:S00_AXI_ : AXI4 / SLAVE_INTERFACE" in ln for ln in lines)
    assert any("u_fabric:M00_AXI_ : AXI4 / MASTER_INTERFACE" in ln for ln in lines)
    assert any(ln.startswith(afd.TREE_BRANCH) for ln in lines)
    assert any(ln.startswith(afd.TREE_LAST_BRANCH) for ln in lines)


@requires_verible
def test_tree_shows_the_endpoint_and_the_vip_bind_candidate_under_each_port(plan):
    assert "VIP_BIND_CANDIDATE = u_cpu:M_AXI_" in plan.tree
    assert "u_cpu (cpu_core)" in plan.tree


@requires_verible
def test_tree_unresolved_branch_shows_last_known_hierarchy_and_trace_status(plan):
    lines = plan.tree.splitlines()
    idx = next(i for i, ln in enumerate(lines) if "u_fabric:M04_AXI_" in ln)
    block = "\n".join(lines[idx:idx + 5])
    assert TraceTerminationStatus.DESTINATION_NOT_FOUND.value in block
    assert "LAST_KNOWN_HIERARCHY" in block
    assert "REASON =" in block


@requires_verible
def test_tree_enumerates_both_branches_of_a_multiple_destination_port(plan):
    assert "branch 1:" in plan.tree and "branch 2:" in plan.tree


# ---------------------------------------------------------------------------
# AMBA-20: the VIP instance plan
# ---------------------------------------------------------------------------

@requires_verible
def test_every_vip_row_carries_all_eleven_mandated_columns(plan):
    assert plan.vip_instances
    for row in plan.vip_instances:
        for key, _ in afd.AMBA20_VIP_PLAN_COLUMNS:
            assert key in row and str(row[key]).strip(), key


@requires_verible
def test_vip_plan_defaults_to_passive_monitor_everywhere(plan):
    for row in plan.vip_instances:
        assert row["vip_mode"] == VIP_MODE_PASSIVE_MONITOR
        assert row["active_passive"] == connectivity.PASSIVE_INTERFACE
        assert row["master_slave_monitor"] == VIP_MSM_MONITOR
    assert_vip_plan_defaults_passive(plan.vip_instances)


@requires_verible
def test_scoreboard_connection_is_left_to_the_downstream_step(plan):
    for row in plan.vip_instances:
        assert row["scoreboard_connection"] == connectivity.REQUIRED_HUMAN_INPUT


@requires_verible
def test_vip_ids_are_unique_and_name_their_bind_location(plan):
    ids = [r["vip_id"] for r in plan.vip_instances]
    assert len(ids) == len(set(ids))
    cpu = next(r for r in plan.vip_instances if "u_cpu" in r["bind_hierarchy"])
    assert "U_CPU" in cpu["vip_id"] and "AXI4" in cpu["vip_id"]


@requires_verible
def test_a_port_with_no_validated_bind_location_gets_no_vip_instance(plan):
    planned = {r["source_row_id"] for r in plan.vip_instances}
    parent_ids = {r["row_id"] for r in parent_matrix_rows(plan.matrix)}
    unplanned = parent_ids - planned
    unresolved_ports = {r["fabric_port"] for r in plan.unresolved}
    assert unplanned <= unresolved_ports | {"u_fabric:M02_AXI_"}


def test_an_active_vip_without_a_driving_requirement_is_refused():
    rows = [{"vip_id": "VIP_01", "vip_mode": VIP_MODE_ACTIVE_DRIVER,
             "active_passive": connectivity.ACTIVE_INTERFACE, "vip_type": "AXI4_VIP",
             "driving_requirement": None}]
    with pytest.raises(FabricDiscoveryError) as exc:
        assert_vip_plan_defaults_passive(rows)
    assert "VIP_ACTIVE_WITHOUT_DRIVING_REQUIREMENT" in str(exc.value)
    rows[0]["driving_requirement"] = "the fabric has no real master; the VIP drives it"
    assert_vip_plan_defaults_passive(rows)


def test_a_plan_row_outside_the_active_passive_vocabulary_is_refused():
    rows = [{"vip_id": "VIP_01", "vip_mode": VIP_MODE_PASSIVE_MONITOR,
             "active_passive": "mostly passive?", "vip_type": "AXI4_VIP"}]
    with pytest.raises(connectivity.ConnectivityError) as exc:
        assert_vip_plan_defaults_passive(rows)
    assert "ACTIVE_PASSIVE_NOT_IN_VOCABULARY" in str(exc.value)


@requires_verible
def test_plan_feeds_the_existing_vip_instance_count_check(plan):
    records = vip_instance_records_from_plan(plan.vip_instances)
    assert records and all(isinstance(r, connectivity.VipInstanceRecord) for r in records)
    result = connectivity.check_vip_instance_count_matches_active_interfaces(
        records, active_interface_count=len(records))
    assert result["ok"] is True
    assert result["vip_instance_count"] == len(plan.vip_instances)
    # Every planned VIP is PASSIVE, so the ACTIVE-interface count really is 0
    # and the identity fails loudly against it rather than quietly matching.
    mismatch = connectivity.check_vip_instance_count_matches_active_interfaces(
        records, active_interface_count=0)
    assert mismatch["ok"] is False and mismatch["delta"] == len(records)


@requires_verible
def test_vip_plan_renders_the_doc_s_eleven_headers(plan):
    header = render_vip_instance_plan(plan.vip_instances).splitlines()[0]
    for _, label in afd.AMBA20_VIP_PLAN_COLUMNS:
        assert label in header


def test_vip_plan_renders_a_named_empty_state():
    assert "no VIP instance is proposed" in render_vip_instance_plan([])


# ---------------------------------------------------------------------------
# The assembled artifact, and the AMBA-30 / AMBA-31 gate
# ---------------------------------------------------------------------------

@requires_verible
def test_report_contains_every_mandated_section(plan):
    text = render_vip_bind_plan_report(plan)
    for heading in ("AMBA-18. Topology summary",
                    "AMBA-16. Fabric port to VIP bind matrix",
                    "AMBA-17. Unresolved fabric ports",
                    "AMBA-19. Discovered topology tree",
                    "AMBA-20. VIP instance plan",
                    "AMBA-15. Bind location validation"):
        assert heading in text
    assert "human reviews" in text


@requires_verible
def test_plan_serialises_without_the_live_validation_objects(plan):
    import json
    doc = plan.to_dict()
    json.dumps(doc)      # must be plain JSON, not dataclasses
    assert len(doc["fabric_port_to_vip_bind_matrix"]) == len(plan.matrix)
    assert doc["bind_location_validations"]
    assert doc["topology_summary"]["total_amba_ports"] == 7


@requires_verible
def test_plan_is_schema_compatible_with_the_fabric_topology_gate(netlist, traces, plan):
    # AMBA-16/18/19/22's artifacts must not compete with the existing
    # validator's shape: masters/slaves come from the same discovery pass.
    ids = afd.discovered_topology_ids(traces)
    assert set(ids) == {"masters", "slaves", "unresolved"}
    assert ids["masters"] and ids["slaves"]


@requires_verible
def test_no_bind_statement_anywhere(plan):
    import pathlib
    text = render_vip_bind_plan_report(plan)
    assert_no_bind_statement(text)
    for artifact in (render_fabric_vip_bind_matrix(plan.matrix),
                     render_unresolved_fabric_port_table(plan.unresolved),
                     render_vip_instance_plan(plan.vip_instances),
                     plan.tree):
        assert_no_bind_statement(artifact)
    source = pathlib.Path(afd.__file__).read_text(encoding="utf-8")
    assert_no_bind_statement(source)


def test_assert_no_bind_statement_actually_detects_one():
    with pytest.raises(FabricDiscoveryError) as exc:
        assert_no_bind_statement("bind cpu_core axi_if u_if (.*);")
    assert "BIND_STATEMENT_IN_DISCOVERY_ARTIFACT" in str(exc.value)
