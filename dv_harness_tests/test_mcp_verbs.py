"""Tests for dv_harness/mcp/verbs.py's 4 manifest-backed verbs
(get_vip_config, get_dut_port, get_register, get_topology) against the
synthetic fixture (matching the REAL dv_harness/schemas/
env_manifest.schema.json contract -- see mcp_manifest_fixture.py's own
reconciliation note) -- and for verbs.dispatch()'s own fixed-verb-only
routing."""
from __future__ import annotations

import pytest

pytest.importorskip("jsonschema")

from dv_harness.mcp import verbs
from dv_harness.mcp.errors import McpUnknownVerbError, McpValidationError

from .mcp_manifest_fixture import build_fixture_manifest, build_not_available_manifest


@pytest.fixture
def manifest():
    return build_fixture_manifest()


# ---- get_vip_config ---------------------------------------------------------

def test_get_vip_config_lists_all_instances_with_no_filter(manifest):
    result = verbs.get_vip_config(manifest, {})
    assert result["status"] == "CAPTURED"
    assert result["match_count"] == 2
    assert {i["instance_path"] for i in result["instances"]} == {
        "uvm_test_top.env.usb3_agent0.cfg", "uvm_test_top.env.apb_agent0.cfg"}


def test_get_vip_config_filters_by_instance_path(manifest):
    result = verbs.get_vip_config(manifest, {"instance_path": "uvm_test_top.env.usb3_agent0.cfg"})
    assert result["match_count"] == 1
    assert result["instances"][0]["config_fields"]["is_active"] == "UVM_ACTIVE"


def test_get_vip_config_filters_by_vip_type(manifest):
    result = verbs.get_vip_config(manifest, {"vip_type": "apb_vip_config"})
    assert result["match_count"] == 1
    assert result["instances"][0]["config_fields"]["is_active"] == "UVM_PASSIVE"


def test_get_vip_config_no_match_returns_empty_not_an_error(manifest):
    result = verbs.get_vip_config(manifest, {"instance_path": "does.not.exist"})
    assert result["status"] == "CAPTURED"
    assert result["match_count"] == 0


def test_get_vip_config_honestly_reports_not_available():
    result = verbs.get_vip_config(build_not_available_manifest(), {})
    assert result["status"] == "NOT_AVAILABLE"
    assert result["reason"]
    assert result["instances"] == []


def test_get_vip_config_rejects_unknown_param(manifest):
    with pytest.raises(McpValidationError):
        verbs.get_vip_config(manifest, {"free_text_query": "give me everything"})


# ---- get_dut_port -----------------------------------------------------------

def test_get_dut_port_returns_all_ports_and_parameters(manifest):
    result = verbs.get_dut_port(manifest, {"module_name": "usb3_top"})
    assert result["status"] == "FOUND"
    assert {p["name"] for p in result["ports"]} == {"clk", "rst_n", "utmi_txvalid"}
    assert result["parameters"][0]["name"] == "NUM_LANES"
    assert result["file_path"] == "rtl/usb3_top.sv"


def test_get_dut_port_finds_module_in_second_file(manifest):
    """Confirms the search walks EVERY file's modules list, not just the
    first file -- apb_bridge lives in the second dut_facts.rtl.files entry."""
    result = verbs.get_dut_port(manifest, {"module_name": "apb_bridge"})
    assert result["status"] == "FOUND"
    assert result["file_path"] == "rtl/apb_bridge.sv"
    assert {p["name"] for p in result["ports"]} == {"pclk", "pready"}


def test_get_dut_port_filters_by_port_name(manifest):
    result = verbs.get_dut_port(manifest, {"module_name": "usb3_top", "port_name": "rst_n"})
    assert [p["name"] for p in result["ports"]] == ["rst_n"]


def test_get_dut_port_unknown_module_is_not_found_not_a_crash(manifest):
    result = verbs.get_dut_port(manifest, {"module_name": "does_not_exist_top"})
    assert result["status"] == "NOT_FOUND"
    assert result["ports"] == []


def test_get_dut_port_requires_module_name(manifest):
    with pytest.raises(McpValidationError):
        verbs.get_dut_port(manifest, {})


def test_get_dut_port_honestly_reports_not_available():
    result = verbs.get_dut_port(build_not_available_manifest(), {"module_name": "usb3_top"})
    assert result["status"] == "NOT_AVAILABLE"
    assert result["reason"]


# ---- get_register ------------------------------------------------------------

def test_get_register_lists_all_with_no_filter(manifest):
    result = verbs.get_register(manifest, {})
    assert result["status"] == "LOADED"
    assert result["match_count"] == 2


def test_get_register_filters_by_name(manifest):
    result = verbs.get_register(manifest, {"name": "CTRL"})
    assert result["match_count"] == 1
    reg = result["registers"][0]
    assert reg["block_name"] == "USB3_CTRL_BLOCK"
    assert reg["absolute_address"] == "0x1000"
    assert reg["fields"][0]["name"] == "EN"


def test_get_register_filters_by_block_name(manifest):
    result = verbs.get_register(manifest, {"block_name": "USB3_CTRL_BLOCK"})
    assert result["match_count"] == 2


def test_get_register_filters_by_block_name_no_match(manifest):
    result = verbs.get_register(manifest, {"block_name": "DOES_NOT_EXIST_BLOCK"})
    assert result["match_count"] == 0


def test_get_register_filters_by_absolute_address(manifest):
    result = verbs.get_register(manifest, {"address": "0x1004"})
    assert result["registers"][0]["name"] == "STATUS"


def test_get_register_filters_by_address_offset(manifest):
    """address may also be given as the register's own address_offset
    (relative to its block), not only the computed absolute address."""
    result = verbs.get_register(manifest, {"address": "0x4"})
    assert result["registers"][0]["name"] == "STATUS"


def test_get_register_honestly_reports_not_available():
    result = verbs.get_register(build_not_available_manifest(), {})
    assert result["status"] == "NOT_AVAILABLE"
    assert result["reason"]


# ---- get_topology -------------------------------------------------------------

def test_get_topology_lists_components_and_config_db_entries(manifest):
    result = verbs.get_topology(manifest, {})
    assert result["component_hierarchy_status"] == "CAPTURED"
    assert result["config_db_trace_status"] == "CAPTURED"
    assert len(result["components"]) == 5
    assert len(result["config_db_entries"]) == 4


def test_get_topology_reports_honest_set_get_event_counts(manifest):
    result = verbs.get_topology(manifest, {})
    assert result["config_db_set_event_count"] == 2
    assert result["config_db_get_event_count"] == 2


def test_get_topology_never_fabricates_a_matched_field(manifest):
    """Part C's per-field SET/GET pairing is an HONEST open gap (the real
    generator leaves config_db_trace entries[].message unparsed/opaque per
    parse_confidence) -- get_topology must not invent a 'matched' verdict
    from that unparsed text."""
    result = verbs.get_topology(manifest, {})
    for entry in result["config_db_entries"]:
        assert "matched" not in entry
    assert "config_db_pairs" not in result


def test_get_topology_parse_confidence_is_surfaced_for_caller_awareness(manifest):
    result = verbs.get_topology(manifest, {})
    assert result["config_db_trace_parse_confidence"] == "envelope_verified_message_opaque"


def test_get_topology_filters_components_by_path_prefix(manifest):
    result = verbs.get_topology(manifest, {"path_prefix": "uvm_test_top.env.usb3_agent0"})
    assert all(c["full_name"].startswith("uvm_test_top.env.usb3_agent0") for c in result["components"])
    assert len(result["components"]) == 2


def test_get_topology_filters_config_db_entries_by_reporter_path_prefix(manifest):
    """Part C: apb_agent0's SET has no reachable GET under its own path
    prefix -- filtering surfaces exactly that asymmetry in the raw counts,
    without this verb claiming a 'matched: false' verdict outright."""
    result = verbs.get_topology(manifest, {"path_prefix": "uvm_test_top.env.apb_agent0"})
    assert result["config_db_set_event_count"] == 1
    assert result["config_db_get_event_count"] == 0


def test_get_topology_filters_by_component_type(manifest):
    result = verbs.get_topology(manifest, {"component_type": "apb_agent"})
    assert len(result["components"]) == 1
    assert result["components"][0]["is_active"] == "UVM_PASSIVE"


def test_get_topology_can_exclude_config_db(manifest):
    result = verbs.get_topology(manifest, {"include_config_db": False})
    assert result["config_db_entries"] == []


def test_get_topology_honestly_reports_not_available_per_sublayer():
    result = verbs.get_topology(build_not_available_manifest(), {})
    assert result["component_hierarchy_status"] == "NOT_AVAILABLE"
    assert result["config_db_trace_status"] == "NOT_AVAILABLE"
    assert result["components"] == []
    assert result["config_db_entries"] == []
    assert result["component_hierarchy_reason"]
    assert result["config_db_trace_reason"]


# ---- dispatch(): fixed-verb-only routing -------------------------------------

def test_dispatch_routes_to_correct_verb(manifest):
    result = verbs.dispatch("get_dut_port", {"module_name": "apb_bridge"}, manifest=manifest)
    assert result["verb"] == "get_dut_port"
    assert result["status"] == "FOUND"


def test_dispatch_rejects_unknown_verb_name(manifest):
    with pytest.raises(McpUnknownVerbError):
        verbs.dispatch("grep_the_repo", {}, manifest=manifest)


def test_dispatch_manifest_verb_without_manifest_is_a_validation_error():
    with pytest.raises(McpValidationError):
        verbs.dispatch("get_dut_port", {"module_name": "x"})


def test_dispatch_query_regression_without_evidence_store_is_a_validation_error():
    with pytest.raises(McpValidationError):
        verbs.dispatch("query_regression", {"query_shape": "latest"})


def test_dispatch_verb_set_is_exactly_the_5_fixed_verbs():
    assert set(verbs.VERBS) == {
        "get_vip_config", "get_dut_port", "get_register", "get_topology", "query_regression",
    }
