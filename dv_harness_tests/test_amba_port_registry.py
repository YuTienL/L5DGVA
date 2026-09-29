"""Tests for AMBA-21 (dv_harness/amba_scoreboard_env.py -- read-only inspection
of a supplied UVM scoreboard/reference environment, and the mapping from each
proposed VIP monitor to a real scoreboard ingress) and AMBA-22
(dv_harness/amba_port_registry.py -- the AMBA_PORT_REGISTRY and its projection
into fabric_topology_completeness_gate.py's schema).

Two real fixtures, no hand-built objects:

  * The RTL half is the SAME synthetic multi-master / multi-slave AMBA4 SoC
    `test_amba_vip_bind_plan.py` already parses with a REAL
    `verible-verilog-syntax` run -- imported rather than copied, so the registry
    is proven against the exact topology (and the exact five unresolvable
    obstacles) AMBA-15..20 were proven against. Two of its seven fabric ports
    resolve cleanly; the other five are a protocol bridge, a two-way
    fan-out (MULTIPLE_DESTINATION), an unparsed black box (TRACE_BLOCKED) and an
    unconnected port (DESTINATION_NOT_FOUND). A registry proven only on the
    clean two would be exactly the happy-path-only coverage this project has
    been burned by.
  * The scoreboard half is real SystemVerilog class source written to a tmp
    dir, WITH method bodies in it -- the bodies are what make
    `test_no_method_body_text_reaches_the_analysis` a check with detection power
    rather than a check that never looked.

Both fixtures are synthetic and are the only place a bind-like construct could
legitimately live; neither contains one, and `test_no_bind_statement_anywhere`
asserts that of both new modules' own source and of every artifact they render,
per the AMBA-30 / AMBA-31 review gate.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import amba_fabric_discovery as afd
from dv_harness import amba_port_registry as apr
from dv_harness import amba_scoreboard_env as ase
from dv_harness import vip_symbol_index
from dv_harness.amba_fabric_discovery import (
    BIND_READINESS_VALUES,
    TraceTerminationStatus,
    build_fabric_netlist,
    build_vip_bind_plan,
    trace_all_fabric_ports,
)
from dv_harness.amba_port_registry import (
    AMBA_PORT_REGISTRY_FIELDS,
    ENDPOINT_HIERARCHY_NOT_ESTABLISHED,
    PortRegistryError,
    VIP_MODE_NOT_PLANNED,
    assert_no_generic_port_ids,
    assert_projection_agrees_with_traces,
    assert_registry_complete,
    build_amba_port_registry,
    load_amba_port_registry,
    project_to_fabric_topology,
    registry_endpoints,
    render_amba_port_registry_report,
    save_amba_port_registry,
)
from dv_harness.amba_scoreboard_env import (
    ADAPTATION_HUMAN_CHOICE,
    ADAPTATION_NEW_INGRESS_REQUIRED,
    ADAPTATION_NO_ENVIRONMENT,
    ENV_ROLE_ADAPTER,
    ENV_ROLE_PREDICTOR,
    ENV_ROLE_SCOREBOARD,
    ENV_ROLE_SUBSCRIBER,
    ENV_ROLE_UNCLASSIFIED,
    INGRESS_KIND_IMPLICIT_SUBSCRIBER,
    INGRESS_MAP_AMBIGUOUS,
    INGRESS_MAP_MATCHED,
    INGRESS_MAP_NOT_FOUND,
    INGRESS_MAP_NO_ENVIRONMENT,
    SCOREBOARD_ASSUMPTION_FIELDS,
    ScoreboardEnvError,
    analyze_scoreboard_environment,
    assert_sources_unmodified,
    endpoint_hint,
    map_vip_monitors_to_scoreboard_ingress,
    protocol_hint,
    render_scoreboard_env_report,
)
from dv_harness.connectivity import (
    AMBA_PROTOCOL_UNRESOLVED,
    BindTier,
    EXTERNAL_ENDPOINT_MASTER,
    EXTERNAL_ENDPOINT_SLAVE,
    REQUIRED_HUMAN_INPUT,
    ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS,
)
from dv_harness.verible_parser import parse_file
from dv_harness_tests.test_amba_vip_bind_plan import (
    AXI4_ADDRESS_WIDTH,
    AXI4_DATA_WIDTH,
    AXI4_ID_WIDTH,
    AXI4_USER_WIDTH,
    FABRIC,
    write_fixture,
)

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPLETENESS_GATE = REPO_ROOT / "tools" / "verification_flow" / \
    "fabric_topology_completeness_gate.py"


# ---------------------------------------------------------------------------
# Synthetic UVM scoreboard / reference environment fixture
#
# Real class source with real method bodies. The bodies exist so the
# no-body-retention assertion has something to catch if it ever regresses.
# ---------------------------------------------------------------------------

SCOREBOARD_ENV_SV = """
class axi4_txn extends uvm_sequence_item;
  rand bit [31:0] addr;
  rand bit [63:0] data;
endclass

class apb4_txn extends uvm_sequence_item;
  rand bit [31:0] paddr;
endclass

class soc_scoreboard_base extends uvm_scoreboard;
  int unsigned mismatch_count;
endclass

class soc_axi_scoreboard extends soc_scoreboard_base;
  uvm_analysis_imp_axi4_master #(axi4_txn, soc_axi_scoreboard) axi4_master_imp;
  uvm_analysis_export #(axi4_txn) axi4_slave_export;
  uvm_analysis_port #(axi4_txn) mismatch_ap;
  uvm_tlm_analysis_fifo #(apb4_txn) apb4_fifo;
  int max_outstanding;
  bit in_order;
  bit [31:0] base_addr_ddr;
  int reorder_window_depth;
  bit exclusive_access_supported;
  function void write_axi4_master(axi4_txn t);
    if (t.addr >= base_addr_ddr) begin
      $display("SCOREBOARD hit %0h", t.addr);
    end
  endfunction
  task wait_for_drain(input int timeout_ns);
    while (mismatch_count > 0) begin
      #1ns;
    end
  endtask
endclass

class apb4_predictor extends uvm_component;
  uvm_analysis_export #(apb4_txn) apb4_export;
  function void predict();
    $display("predicting");
  endfunction
endclass

class coverage_subscriber extends uvm_subscriber;
  int sample_count;
endclass

class soc_register_adapter extends uvm_reg_adapter;
endclass

class unrelated_helper extends some_project_local_base;
  int scratch;
endclass
"""

#: A SECOND environment, used only for the ambiguity case: two equally-plausible
#: AXI4 master ingress points in two different scoreboards. Kept separate rather
#: than folded into the fixture above, so the matched case stays a real match
#: instead of being weakened into an ambiguity by the ambiguity test's own
#: fixture.
AMBIGUOUS_ENV_SV = """
class axi4_txn extends uvm_sequence_item;
endclass

class latency_scoreboard extends uvm_scoreboard;
  uvm_analysis_export #(axi4_txn) axi4_master_export;
endclass

class throughput_scoreboard extends uvm_scoreboard;
  uvm_analysis_export #(axi4_txn) axi4_master_export;
endclass
"""

#: An environment containing only APB4 ingress, for the "no ingress accepts this
#: protocol" case.
APB_ONLY_ENV_SV = """
class apb4_txn extends uvm_sequence_item;
endclass

class apb4_scoreboard extends uvm_scoreboard;
  uvm_analysis_export #(apb4_txn) apb4_slave_export;
endclass
"""


def _write_env(tmp_path, name: str, text: str) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}_pkg.sv").write_text(text, encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def netlist(tmp_path_factory):
    if shutil.which(VERIBLE_BIN) is None:
        pytest.skip("verible-verilog-syntax not on PATH")
    sv = write_fixture(tmp_path_factory.mktemp("amba_port_registry_rtl"))
    return build_fabric_netlist([parse_file(sv)], "soc_top")


@pytest.fixture(scope="module")
def traces(netlist):
    return trace_all_fabric_ports(netlist, FABRIC)


@pytest.fixture(scope="module")
def plan(netlist, traces):
    return build_vip_bind_plan(netlist, traces)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = _write_env(tmp_path_factory.mktemp("sb_env"), "soc_sb", SCOREBOARD_ENV_SV)
    return analyze_scoreboard_environment([root], relative_to=root.parent)


@pytest.fixture(scope="module")
def mapping(plan, env):
    return map_vip_monitors_to_scoreboard_ingress(plan.vip_instances, env)


@pytest.fixture(scope="module")
def registry(netlist, traces, plan, mapping):
    return build_amba_port_registry(netlist, traces, plan, mapping)


def _ingress(env, ingress_id):
    found = env.ingress_by_id(ingress_id)
    assert found is not None, f"{ingress_id} not discovered; have " \
                              f"{[i.ingress_id for i in env.ingress]}"
    return found


def _row(rows, port_id):
    return next(r for r in rows if r["port_id"] == port_id)


# ===========================================================================
# vip_symbol_index: the analysis-port declaration capture AMBA-21 rests on
# ===========================================================================

def test_analysis_port_declarations_are_indexed_with_kind_and_direction():
    classes = vip_symbol_index.index_source_text(SCOREBOARD_ENV_SV, "soc_sb_pkg.sv")
    sb = next(c for c in classes if c["name"] == "soc_axi_scoreboard")
    by_name = {p["name"]: p for p in sb["analysis_ports"]}
    assert set(by_name) == {"axi4_master_imp", "axi4_slave_export", "mismatch_ap",
                            "apb4_fifo"}
    assert by_name["axi4_master_imp"]["kind"] == "ANALYSIS_IMP"
    assert by_name["axi4_master_imp"]["direction"] == "INGRESS"
    # Only the FIRST type parameter: the second is the implementing class.
    assert by_name["axi4_master_imp"]["transaction_type"] == "axi4_txn"
    assert by_name["mismatch_ap"]["direction"] == "OUTGOING"
    assert by_name["apb4_fifo"]["kind"] == "ANALYSIS_FIFO"
    for port in by_name.values():
        assert port["line"] > 0 and port["file"] == "soc_sb_pkg.sv"


def test_an_analysis_port_array_records_its_declared_dimension():
    classes = vip_symbol_index.index_source_text(
        "class m extends uvm_scoreboard;\n"
        "  uvm_analysis_export #(axi4_txn) master_export[NUM_MASTERS];\n"
        "endclass\n", "m.sv")
    port = classes[0]["analysis_ports"][0]
    assert port["array_dimension"] == "[NUM_MASTERS]"
    assert port["direction"] == "INGRESS"


def test_analysis_port_capture_did_not_swallow_ordinary_config_fields():
    classes = vip_symbol_index.index_source_text(SCOREBOARD_ENV_SV, "soc_sb_pkg.sv")
    sb = next(c for c in classes if c["name"] == "soc_axi_scoreboard")
    names = {f["name"] for f in sb["config_fields"]}
    assert {"max_outstanding", "in_order", "base_addr_ddr",
            "reorder_window_depth"} <= names
    assert "axi4_master_imp" not in names


# ===========================================================================
# AMBA-21: class roles
# ===========================================================================

def test_a_role_from_a_real_extends_chain_is_structural_t2(env):
    # soc_axi_scoreboard -> soc_scoreboard_base -> uvm_scoreboard: the role is
    # walked transitively, so a project's own base class does not downgrade
    # its children to a naming guess.
    role = env.roles["soc_axi_scoreboard"]
    assert role["role"] == ENV_ROLE_SCOREBOARD
    assert role["tier"] == BindTier.T2_STRUCTURAL_MATCH.value
    assert "soc_scoreboard_base" in role["evidence"]
    assert "uvm_scoreboard" in role["evidence"]


def test_a_name_only_role_is_t3_and_never_auto_accepted(env):
    role = env.roles["apb4_predictor"]
    assert role["role"] == ENV_ROLE_PREDICTOR
    assert role["tier"] == BindTier.T3_NAMING_HEURISTIC.value
    assert "predictor" in role["evidence"]


def test_an_unclassifiable_class_is_t4_not_guessed(env):
    role = env.roles["unrelated_helper"]
    assert role["role"] == ENV_ROLE_UNCLASSIFIED
    assert role["tier"] == BindTier.T4_UNDECIDABLE.value


def test_transactions_adapters_and_subscribers_are_all_identified(env):
    assert set(env.transaction_classes) == {"axi4_txn", "apb4_txn"}
    assert env.classes_with_role(ENV_ROLE_ADAPTER) == ["soc_register_adapter"]
    assert env.classes_with_role(ENV_ROLE_SUBSCRIBER) == ["coverage_subscriber"]
    assert set(env.scoreboard_classes) == {"soc_scoreboard_base", "soc_axi_scoreboard"}


def test_a_cyclic_extends_chain_terminates_instead_of_hanging():
    classes = vip_symbol_index.index_source_text(
        "class a extends b;\nendclass\nclass b extends a;\nendclass\n", "cyc.sv")
    by_name = {c["name"]: c for c in classes}
    assert ase.classify_env_class(by_name["a"], by_name)["tier"] == \
        BindTier.T4_UNDECIDABLE.value


# ===========================================================================
# AMBA-21: ingress discovery
# ===========================================================================

def test_ingress_lists_exports_imps_and_fifos_but_never_an_analysis_port(env):
    ids = {i.ingress_id for i in env.ingress}
    assert "soc_axi_scoreboard.axi4_master_imp" in ids
    assert "soc_axi_scoreboard.axi4_slave_export" in ids
    assert "soc_axi_scoreboard.apb4_fifo" in ids
    # An analysis PORT sends; connecting a monitor to one would be backwards.
    assert "soc_axi_scoreboard.mismatch_ap" not in ids


def test_a_uvm_subscriber_contributes_its_implicit_library_export(env):
    implicit = _ingress(env, "coverage_subscriber.analysis_export")
    assert implicit.kind == INGRESS_KIND_IMPLICIT_SUBSCRIBER
    assert "UVM class library" in implicit.evidence
    assert implicit.transaction_type is None


def test_an_ingress_carries_protocol_and_endpoint_hints_from_declared_names(env):
    master = _ingress(env, "soc_axi_scoreboard.axi4_master_imp")
    assert master.protocol_hint == "AXI4"
    assert master.endpoint_hint == EXTERNAL_ENDPOINT_MASTER
    slave = _ingress(env, "soc_axi_scoreboard.axi4_slave_export")
    assert slave.endpoint_hint == EXTERNAL_ENDPOINT_SLAVE
    fifo = _ingress(env, "soc_axi_scoreboard.apb4_fifo")
    assert fifo.protocol_hint == "APB4"
    assert fifo.endpoint_hint == ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS


def test_a_non_ingress_bearing_class_contributes_no_ingress(env):
    # The adapter and the transaction classes have no ingress of their own.
    assert not [i for i in env.ingress
                if i.component_class in ("soc_register_adapter", "axi4_txn")]


def test_protocol_hint_prefers_the_longest_match_and_refuses_a_conflict():
    assert protocol_hint("s_axi4_lite_export") == "AXI4_LITE"
    assert protocol_hint("apb4_fifo") == "APB4"
    assert protocol_hint("axi4_stream_in") == "AXI4_STREAM"
    # Two different protocols suggested by two texts settle nothing.
    assert protocol_hint("axi4_export", "apb4_txn") == AMBA_PROTOCOL_UNRESOLVED
    assert protocol_hint("generic_export") == AMBA_PROTOCOL_UNRESOLVED


def test_endpoint_hint_refuses_a_name_suggesting_both_perspectives():
    assert endpoint_hint("master_export") == EXTERNAL_ENDPOINT_MASTER
    assert endpoint_hint("target_export") == EXTERNAL_ENDPOINT_SLAVE
    assert endpoint_hint("master_slave_export") == \
        ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS


# ===========================================================================
# AMBA-21: assumptions, and the read-only contract
# ===========================================================================

def test_assumptions_are_required_human_input_with_cited_declarations(env):
    block = env.assumptions["soc_axi_scoreboard"]
    assert set(block) == set(SCOREBOARD_ASSUMPTION_FIELDS)
    for key in SCOREBOARD_ASSUMPTION_FIELDS:
        assert block[key]["value"] == REQUIRED_HUMAN_INPUT
    cited = {c["declaration"] for c in block["outstanding_transactions"]
             ["candidate_declarations"]}
    assert "max_outstanding" in cited
    assert {"in_order"} <= {c["declaration"] for c in block["ordering"]
                            ["candidate_declarations"]}
    assert {"reorder_window_depth"} <= {
        c["declaration"] for c in block["ordering_tolerance_depth"]
        ["candidate_declarations"]}
    assert {"base_addr_ddr"} <= {c["declaration"] for c in
                                 block["address_map_assumptions"]
                                 ["candidate_declarations"]}
    # Every citation is a targeted read location, not a bare name.
    for c in block["outstanding_transactions"]["candidate_declarations"]:
        assert c["line"] > 0 and c["file"]


def test_a_class_with_no_ingress_role_gets_no_assumption_block(env):
    assert "soc_register_adapter" not in env.assumptions
    assert "axi4_txn" not in env.assumptions


def test_no_method_body_text_reaches_the_analysis(env):
    blob = json.dumps(env.to_dict())
    for token in ("$display", "begin", "endtask", "#1ns", "SCOREBOARD hit"):
        assert token not in blob, f"scoreboard analysis leaked body text: {token!r}"


def test_assert_sources_unmodified_passes_and_then_really_fires(tmp_path):
    root = _write_env(tmp_path, "ro_env", SCOREBOARD_ENV_SV)
    analysis = analyze_scoreboard_environment([root])
    assert_sources_unmodified(analysis)
    (root / "ro_env_pkg.sv").write_text(SCOREBOARD_ENV_SV + "\nclass x; endclass\n",
                                        encoding="utf-8")
    with pytest.raises(ScoreboardEnvError) as exc:
        assert_sources_unmodified(analysis)
    assert exc.value.reason == "SCOREBOARD_SOURCE_MODIFIED_DURING_DISCOVERY"


def test_a_deleted_source_is_a_distinct_failure_from_a_modified_one(tmp_path):
    root = _write_env(tmp_path, "gone_env", SCOREBOARD_ENV_SV)
    analysis = analyze_scoreboard_environment([root])
    (root / "gone_env_pkg.sv").unlink()
    with pytest.raises(ScoreboardEnvError) as exc:
        assert_sources_unmodified(analysis)
    assert exc.value.reason == "SCOREBOARD_SOURCE_DISAPPEARED_DURING_DISCOVERY"


def test_a_mistyped_root_raises_rather_than_reporting_an_empty_environment():
    with pytest.raises(ScoreboardEnvError) as exc:
        analyze_scoreboard_environment(["/no/such/scoreboard/root"])
    assert exc.value.reason == "SCOREBOARD_ENV_ROOT_NOT_FOUND"


def test_every_inspected_file_is_recorded_with_a_digest(env):
    assert env.files
    for item in env.files:
        assert len(item.sha256) == 64 and item.bytes > 0


# ===========================================================================
# AMBA-21: VIP monitor -> scoreboard ingress mapping
# ===========================================================================

@requires_verible
def test_every_planned_vip_gets_exactly_one_mapping_row(plan, mapping):
    assert [r["vip_id"] for r in mapping] == [v["vip_id"] for v in plan.vip_instances]
    assert mapping, "the fixture must plan at least one VIP for this to mean anything"


@requires_verible
def test_a_master_side_vip_maps_to_the_master_ingress_and_a_slave_side_to_the_slave(
        plan, mapping):
    by_endpoint = {}
    for row in mapping:
        by_endpoint.setdefault(row["endpoint_role"], []).append(row)
    master_rows = by_endpoint[EXTERNAL_ENDPOINT_MASTER]
    slave_rows = by_endpoint[EXTERNAL_ENDPOINT_SLAVE]
    assert master_rows and slave_rows
    for row in master_rows:
        assert row["status"] == INGRESS_MAP_MATCHED
        assert row["scoreboard_channel"] == "soc_axi_scoreboard.axi4_master_imp"
    for row in slave_rows:
        assert row["status"] == INGRESS_MAP_MATCHED
        assert row["scoreboard_channel"] == "soc_axi_scoreboard.axi4_slave_export"
        assert row["ingress_transaction_type"] == "axi4_txn"


def test_two_equally_plausible_ingress_points_are_ambiguous_never_chosen(tmp_path):
    root = _write_env(tmp_path, "amb_env", AMBIGUOUS_ENV_SV)
    analysis = analyze_scoreboard_environment([root])
    vip = [{"vip_id": "VIP_01_AXI4_U_CPU", "protocol": "AXI4",
            "bind_hierarchy": "u_cpu:M_AXI_",
            "observed_endpoint_role": EXTERNAL_ENDPOINT_MASTER}]
    row = map_vip_monitors_to_scoreboard_ingress(vip, analysis)[0]
    assert row["status"] == INGRESS_MAP_AMBIGUOUS
    assert row["scoreboard_channel"] == REQUIRED_HUMAN_INPUT
    assert row["required_adaptation"] == ADAPTATION_HUMAN_CHOICE
    # Both candidates are NAMED, with locations -- an ambiguity a reviewer
    # cannot see the options for is not actionable.
    assert set(row["candidate_ingress_ids"]) == {
        "latency_scoreboard.axi4_master_export",
        "throughput_scoreboard.axi4_master_export"}
    assert "latency_scoreboard" in row["match_evidence"]
    assert "throughput_scoreboard" in row["match_evidence"]


def test_a_protocol_with_no_matching_ingress_reports_a_required_new_ingress(tmp_path):
    root = _write_env(tmp_path, "apb_env", APB_ONLY_ENV_SV)
    analysis = analyze_scoreboard_environment([root])
    vip = [{"vip_id": "VIP_01_AXI4_U_CPU", "protocol": "AXI4",
            "bind_hierarchy": "u_cpu:M_AXI_",
            "observed_endpoint_role": EXTERNAL_ENDPOINT_MASTER}]
    row = map_vip_monitors_to_scoreboard_ingress(vip, analysis)[0]
    assert row["status"] == INGRESS_MAP_NOT_FOUND
    assert row["required_adaptation"] == ADAPTATION_NEW_INGRESS_REQUIRED
    assert row["scoreboard_channel"] == REQUIRED_HUMAN_INPUT


@requires_verible
def test_no_environment_supplied_is_its_own_state_not_an_empty_match(plan):
    rows = map_vip_monitors_to_scoreboard_ingress(plan.vip_instances, None)
    assert rows
    for row in rows:
        assert row["status"] == INGRESS_MAP_NO_ENVIRONMENT
        assert row["required_adaptation"] == ADAPTATION_NO_ENVIRONMENT
        assert row["scoreboard_channel"] == REQUIRED_HUMAN_INPUT


@requires_verible
def test_the_scoreboard_report_renders_classes_ingress_assumptions_and_the_map(
        env, mapping):
    text = render_scoreboard_env_report(env, mapping)
    assert "soc_axi_scoreboard" in text
    assert "axi4_master_imp" in text
    assert "max_outstanding" in text
    for field in SCOREBOARD_ASSUMPTION_FIELDS:
        assert field in text
    assert "nothing was modified" in text


# ===========================================================================
# AMBA-22: the registry
# ===========================================================================

@requires_verible
def test_every_row_carries_all_nineteen_mandated_fields(registry):
    assert list(AMBA_PORT_REGISTRY_FIELDS) == [
        "port_id", "fabric_port", "protocol", "fabric_role", "endpoint_role",
        "endpoint_hierarchy", "vip_bind_hierarchy", "vip_mode", "clock", "reset",
        "address_width", "data_width", "id_width", "user_widths",
        "scoreboard_channel", "trace_status", "readiness", "confidence",
        "source_evidence"]
    assert registry
    for row in registry:
        for field in AMBA_PORT_REGISTRY_FIELDS:
            assert field in row, field
            assert row[field] not in (None, "", []), (row["port_id"], field)
        assert row["readiness"] in BIND_READINESS_VALUES


@requires_verible
def test_there_is_one_registry_row_per_matrix_row(plan, registry):
    assert len(registry) == len(plan.matrix)
    assert len({r["port_id"] for r in registry}) == len(registry)


@requires_verible
def test_port_ids_come_from_the_real_interface_id_not_a_positional_counter(registry):
    ids = {r["port_id"] for r in registry}
    assert "U_FABRIC_S00_AXI" in ids
    assert "U_FABRIC_M00_AXI" in ids
    assert_no_generic_port_ids(registry)


def test_a_generic_port_id_is_refused_unless_the_project_demands_it():
    rows = [{"port_id": "master0"}]
    with pytest.raises(PortRegistryError) as exc:
        assert_no_generic_port_ids(rows)
    assert exc.value.reason == "AMBA_PORT_REGISTRY_GENERIC_PORT_ID"
    # The escape hatch exists, but only as a deliberate argument.
    assert_no_generic_port_ids(rows, project_convention_allows_generic=True)


@requires_verible
def test_widths_are_read_off_the_amba15_checklist_not_recomputed(registry):
    row = _row(registry, "U_FABRIC_S00_AXI")
    assert row["address_width"] == str(AXI4_ADDRESS_WIDTH)
    assert row["data_width"] == str(AXI4_DATA_WIDTH)
    assert row["id_width"] == str(AXI4_ID_WIDTH)
    assert row["user_widths"] == str(AXI4_USER_WIDTH)
    assert row["clock"] == "ACLK" and row["reset"] == "ARESETN"


@requires_verible
def test_a_parameterized_width_is_unknown_in_the_registry_too(netlist, traces, plan):
    # M00 pushes its VIP out to the DDR controller, whose data width is a
    # parameter -- the registry must carry the checklist's UNKNOWN, not a
    # defaulted number.
    rows = build_amba_port_registry(netlist, traces, plan)
    row = _row(rows, "U_FABRIC_M00_AXI")
    assert row["data_width"] == "UNKNOWN"
    assert row["address_width"] == str(AXI4_ADDRESS_WIDTH)


@requires_verible
def test_an_unresolved_port_never_invents_an_endpoint_hierarchy(registry):
    blocked = _row(registry, "U_FABRIC_M03_AXI")
    assert blocked["trace_status"] == TraceTerminationStatus.TRACE_BLOCKED.value
    assert blocked["endpoint_hierarchy"] == ENDPOINT_HIERARCHY_NOT_ESTABLISHED
    # The trace really did reach the black box; that is a LAST-KNOWN hierarchy
    # (AMBA-17's own column), not an endpoint, and the two must not be
    # collapsed into one claim.
    assert blocked["last_known_hierarchy"] == "u_opaque"
    not_found = _row(registry, "U_FABRIC_M04_AXI")
    assert not_found["trace_status"] == \
        TraceTerminationStatus.DESTINATION_NOT_FOUND.value
    assert not_found["endpoint_hierarchy"] == ENDPOINT_HIERARCHY_NOT_ESTABLISHED


@requires_verible
def test_a_multiple_destination_port_keeps_the_choice_open_and_lists_its_branches(
        registry):
    parent = _row(registry, "U_FABRIC_M02_AXI")
    assert parent["trace_status"] == TraceTerminationStatus.MULTIPLE_DESTINATION.value
    assert parent["vip_mode"] == VIP_MODE_NOT_PLANNED
    assert parent["confidence"] == REQUIRED_HUMAN_INPUT
    children = [r for r in registry if r["parent_row_id"] == "u_fabric:M02_AXI_"]
    assert len(children) == 2
    assert {c["endpoint_hierarchy"] for c in children} == {"u_sram0", "u_sram1"}


@requires_verible
def test_the_amba11_second_side_is_registered_with_its_own_protocol(registry):
    bridge = [r for r in registry if r["amba11_second_side"]]
    assert bridge, "the fixture's AXI->APB bridge must produce a second-side row"
    assert {r["protocol"] for r in bridge} == {"APB4"}
    # Recorded as evidence, never planned as a VIP on its own initiative.
    assert {r["vip_mode"] for r in bridge} == {VIP_MODE_NOT_PLANNED}


@requires_verible
def test_scoreboard_channel_comes_from_the_amba21_mapping(registry, mapping):
    by_vip = {r["vip_id"]: r["scoreboard_channel"] for r in mapping}
    planned = [r for r in registry if r["vip_id"]]
    assert planned
    for row in planned:
        assert row["scoreboard_channel"] == by_vip[row["vip_id"]]
    unplanned = [r for r in registry if not r["vip_id"]]
    assert unplanned
    for row in unplanned:
        assert row["scoreboard_channel"] == REQUIRED_HUMAN_INPUT


@requires_verible
def test_without_an_amba21_mapping_every_scoreboard_channel_is_required_human_input(
        netlist, traces, plan):
    rows = build_amba_port_registry(netlist, traces, plan)
    assert {r["scoreboard_channel"] for r in rows} == {REQUIRED_HUMAN_INPUT}


@requires_verible
def test_source_evidence_cites_the_matrix_row_and_every_amba15_point(registry):
    row = _row(registry, "U_FABRIC_S00_AXI")
    joined = " | ".join(row["source_evidence"])
    assert "AMBA-16 matrix row u_fabric:S00_AXI_" in joined
    assert "AMBA-15 bind location validation" in joined
    for _, key, _ in afd.BIND_LOCATION_CHECK_POINTS:
        assert key in joined, key


def test_an_incomplete_row_is_refused_rather_than_written():
    with pytest.raises(PortRegistryError) as exc:
        assert_registry_complete([{f: "x" for f in AMBA_PORT_REGISTRY_FIELDS
                                   if f != "clock"}])
    assert exc.value.reason == "AMBA_PORT_REGISTRY_INCOMPLETE_ROW"
    assert "clock" in exc.value.detail["missing_fields"]


def test_an_unknown_readiness_value_is_refused():
    row = {f: "x" for f in AMBA_PORT_REGISTRY_FIELDS}
    row["readiness"] = "PROBABLY_FINE"
    with pytest.raises(PortRegistryError) as exc:
        assert_registry_complete([row])
    assert exc.value.reason == "AMBA_PORT_REGISTRY_UNKNOWN_READINESS"


# ===========================================================================
# AMBA-22: projection into the completeness gate's schema
# ===========================================================================

@requires_verible
def test_registry_endpoints_agree_with_the_raw_traces(registry, traces):
    endpoints = registry_endpoints(registry)
    assert sorted(endpoints["masters"]) == ["u_cpu", "u_dma"]
    assert sorted(endpoints["slaves"]) == ["u_ddr", "u_sram0", "u_sram1"]
    # The independent cross-check: the registry and the traces must not be
    # able to disagree about who the endpoints are.
    assert_projection_agrees_with_traces(registry, traces)


@requires_verible
def test_an_unresolved_port_lands_in_unresolved_not_in_masters_or_slaves(registry):
    unresolved = {u["port_id"] for u in registry_endpoints(registry)["unresolved"]}
    assert "U_FABRIC_M03_AXI" in unresolved      # black box, TRACE_BLOCKED
    assert "U_FABRIC_M04_AXI" in unresolved      # unconnected
    assert "U_FABRIC_M01_AXI" in unresolved      # bridge: beyond it is another trace


@requires_verible
def test_the_projection_passes_the_real_completeness_gate(registry, tmp_path):
    slaves = [{"id": "u_ddr", "base_addr": "0x0000_0000", "size": "0x4000_0000"},
              {"id": "u_sram0", "base_addr": "0x4000_0000", "size": "0x4000_0000"},
              {"id": "u_sram1", "base_addr": "0x8000_0000", "size": "0x4000_0000"}]
    reserved = [{"name": "RESERVED_TOP", "base_addr": "0xC000_0000",
                 "size": "0x4000_0000", "decerr": True}]
    doc = project_to_fabric_topology(
        registry, address_map_slaves=slaves, reserved_regions=reserved,
        address_width=32,
        connectivity={"u_cpu": {"accessible_slaves": ["u_ddr", "u_sram0", "u_sram1"]},
                      "u_dma": {"accessible_slaves": ["u_ddr", "u_sram0"],
                                "excluded": [{"slave_id": "u_sram1",
                                              "waiver_evidence": "no decode path from "
                                                                 "u_dma in this fixture"}]}},
        assume_full_connectivity=False)
    for key in ("masters", "slaves", "scoreboard_matrix", "address_map"):
        assert key in doc
    path = tmp_path / "topology.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(COMPLETENESS_GATE), "--topology", str(path)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "PASS"
    assert result["masters"] == 2 and result["slaves"] == 3
    assert result["scoreboard_pairs"] == 6


@requires_verible
def test_a_projection_with_no_address_map_is_refused_by_the_gate_not_faked(
        registry, tmp_path):
    doc = project_to_fabric_topology(
        registry,
        connectivity={"u_cpu": {"accessible_slaves": ["u_ddr", "u_sram0", "u_sram1"]},
                      "u_dma": {"accessible_slaves": ["u_ddr", "u_sram0", "u_sram1"]}},
        assume_full_connectivity=False)
    assert doc["address_map"] == []
    path = tmp_path / "no_addr.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(COMPLETENESS_GATE), "--topology", str(path)],
                          capture_output=True, text=True)
    assert proc.returncode != 0
    assert json.loads(proc.stdout)["reason"] == "SLAVE_WITHOUT_ADDRESS_RANGE"


@requires_verible
def test_a_projection_without_connectivity_evidence_refuses_to_guess(registry):
    from dv_harness.uvm_generator.amba_fabric_generator import ScoreboardMatrixError
    with pytest.raises(ScoreboardMatrixError):
        project_to_fabric_topology(registry)


def test_a_registry_with_no_traced_endpoint_cannot_produce_a_topology():
    row = {f: "UNKNOWN" for f in AMBA_PORT_REGISTRY_FIELDS}
    row.update({"port_id": "U_FABRIC_M00_AXI", "readiness": "BLOCKED",
                "endpoint_hierarchy": ENDPOINT_HIERARCHY_NOT_ESTABLISHED,
                "trace_status": TraceTerminationStatus.TRACE_BLOCKED.value})
    with pytest.raises(PortRegistryError) as exc:
        project_to_fabric_topology([row])
    assert exc.value.reason == "AMBA_PORT_REGISTRY_TOPOLOGY_INCOMPLETE"


# ===========================================================================
# AMBA-22: persistence and reporting
# ===========================================================================

@requires_verible
def test_the_registry_round_trips_and_is_byte_deterministic(registry, tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    save_amba_port_registry(registry, a)
    save_amba_port_registry(registry, b)
    assert a.read_bytes() == b.read_bytes()
    reloaded = load_amba_port_registry(a)
    assert [r["port_id"] for r in reloaded] == [r["port_id"] for r in registry]
    assert reloaded[0]["source_evidence"] == registry[0]["source_evidence"]


@requires_verible
def test_the_registry_report_renders_every_column_and_the_review_gate(registry):
    text = render_amba_port_registry_report(registry)
    for key, _ in apr.AMBA22_REGISTRY_COLUMNS:
        assert key in text, key
    assert "U_FABRIC_S00_AXI" in text
    assert "AMBA-30" in text and "AMBA-31" in text
    assert "Ports with no established endpoint" in text


@requires_verible
def test_no_bind_statement_anywhere(registry, env, mapping):
    """AMBA-30/AMBA-31: neither module's own source nor anything it renders may
    contain an emittable bind statement. Checked with
    `connectivity.parse_bind_line()` -- the repo's one definition of what a bind
    statement is -- so this cannot drift from the grep that finds real ones."""
    for module in (ase, apr):
        afd.assert_no_bind_statement(Path(module.__file__).read_text(encoding="utf-8"))
    afd.assert_no_bind_statement(render_amba_port_registry_report(registry))
    afd.assert_no_bind_statement(render_scoreboard_env_report(env, mapping))
    afd.assert_no_bind_statement(SCOREBOARD_ENV_SV)
