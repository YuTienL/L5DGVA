"""End-to-end reconciliation proof: builds a REAL env.manifest.json through
the actual generator (dv_harness.env_manifest.generate_env_manifest()) --
not just this package's own hand-authored mcp_manifest_fixture.py -- and
drives all 4 manifest-backed MCP verbs against it. This is the strongest
available evidence that dv_harness/mcp/verbs.py's field-name assumptions
actually match dv_harness/schemas/env_manifest.schema.json's real,
generator-produced content, not just this test suite's own guess at that
contract. See .work/mcp-server-report.md for the reconciliation writeup."""
from __future__ import annotations

import json
import shutil

import pytest

pytest.importorskip("jsonschema")

from dv_harness import env_manifest
from dv_harness.mcp import schema, verbs

from .test_env_manifest import (
    CONFIG_DB_TRACE_LOG_FIXTURE,
    REGISTER_MAP_FIXTURE,
    TOPOLOGY_DUMP_FIXTURE,
    VIP_CONFIG_DUMP_FIXTURE,
    FIFO_FIXTURE,
    requires_verible,
)


@pytest.fixture
def real_manifest(tmp_path):
    """Builds a real env.manifest.json via the real generator, from real
    (synthesized-fixture) inputs -- register map, VIP config dump, topology
    dump, config_db trace log, plus verible-parsed RTL when verible is on
    PATH (skipped, not faked, otherwise -- see requires_verible below)."""
    register_map_path = tmp_path / "register_map.json"
    register_map_path.write_text(json.dumps(REGISTER_MAP_FIXTURE), encoding="utf-8")

    vip_config_dump_path = tmp_path / "vip_config_dump.json"
    vip_config_dump_path.write_text(json.dumps(VIP_CONFIG_DUMP_FIXTURE), encoding="utf-8")

    topology_dump_path = tmp_path / "topology_dump.json"
    topology_dump_path.write_text(json.dumps(TOPOLOGY_DUMP_FIXTURE), encoding="utf-8")

    config_db_trace_log_path = tmp_path / "sim.log"
    config_db_trace_log_path.write_text(CONFIG_DB_TRACE_LOG_FIXTURE, encoding="utf-8")

    rtl_files = []
    if shutil.which("verible-verilog-syntax") is not None:
        fifo_sv = tmp_path / "fifo_ctrl.sv"
        fifo_sv.write_text(FIFO_FIXTURE, encoding="utf-8")
        rtl_files = [fifo_sv]

    return env_manifest.generate_env_manifest(
        rtl_files=rtl_files,
        register_map_path=register_map_path,
        vip_config_dump_path=vip_config_dump_path,
        topology_dump_path=topology_dump_path,
        config_db_trace_log_path=config_db_trace_log_path,
    )


def test_real_generator_output_matches_this_packages_manifest_schema_validator(real_manifest):
    """Sanity: the real generator's own output validates against the exact
    same schema.py loads (both point at dv_harness/schemas/
    env_manifest.schema.json) -- confirms this package is not silently
    validating against a stale/forked copy."""
    schema.validate_manifest(real_manifest)


def test_get_vip_config_against_real_generator_output(real_manifest):
    result = verbs.get_vip_config(real_manifest, {})
    assert result["status"] == "CAPTURED"
    assert result["match_count"] == 2
    active = verbs.get_vip_config(real_manifest, {"instance_path": "tb_top.dut_env.usb_agent.cfg"})
    assert active["instances"][0]["config_fields"]["is_active"] == "UVM_ACTIVE"


def test_get_register_against_real_generator_output(real_manifest):
    result = verbs.get_register(real_manifest, {"name": "CTRL"})
    assert result["status"] == "LOADED"
    assert result["match_count"] == 1
    reg = result["registers"][0]
    assert reg["block_name"] == "TEST_CTRL_BLOCK"
    assert reg["absolute_address"] == "0x1000"
    assert {f["name"] for f in reg["fields"]} == {"ENABLE", "MODE"}


def test_get_topology_against_real_generator_output(real_manifest):
    result = verbs.get_topology(real_manifest, {})
    assert result["component_hierarchy_status"] == "CAPTURED"
    assert {c["full_name"] for c in result["components"]} == {
        "uvm_test_top", "uvm_test_top.env",
        "uvm_test_top.env.usb_agent", "uvm_test_top.env.usb_monitor_agent",
    }
    assert result["config_db_trace_status"] == "CAPTURED"
    # CONFIG_DB_TRACE_LOG_FIXTURE has exactly one CFGDB/SET and one
    # CFGDB/GET real UVM_INFO line (plus unrelated noise the parser must
    # ignore) -- see that fixture in test_env_manifest.py.
    assert result["config_db_set_event_count"] == 1
    assert result["config_db_get_event_count"] == 1
    assert result["config_db_trace_parse_confidence"] == "envelope_verified_message_opaque"


@requires_verible
def test_get_dut_port_against_real_verible_parsed_rtl(real_manifest):
    assert real_manifest["dut_facts"]["rtl"]["status"] == "PARSED"
    result = verbs.get_dut_port(real_manifest, {"module_name": "fifo_ctrl"})
    assert result["status"] == "FOUND"
    assert {p["name"] for p in result["ports"]} == {"clk", "rst_n", "full"}
    assert result["parameters"][0]["name"] == "DEPTH"


def test_get_dut_port_honestly_not_available_without_verible_when_no_rtl_files(tmp_path):
    """When rtl_files is empty (this fixture's own behavior on a machine
    with no verible on PATH), the real generator reports dut_facts.rtl as
    NOT_AVAILABLE -- and get_dut_port must surface that honestly, not
    crash or silently return NOT_FOUND."""
    manifest = env_manifest.generate_env_manifest(rtl_files=[])
    result = verbs.get_dut_port(manifest, {"module_name": "anything"})
    assert result["status"] == "NOT_AVAILABLE"
    assert result["reason"]
