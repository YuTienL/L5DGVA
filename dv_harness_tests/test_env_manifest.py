"""Tests for dv_harness/env_manifest.py -- the env.manifest.json generator
(Part A of the 2026-09-03 env.manifest.json + MCP + question-queue spec,
manifest half only).

Three groups of coverage, matching this module's own honesty contract:
  1. dut_facts.rtl genuinely round-trips through the REAL verible_parser.py
     against a synthesized, minimal .sv fixture (never real project RTL --
     see CLAUDE.md's Evidence Truth Rule / No Golden-Reference Content
     Mining). Skipped (not faked) when verible-verilog-syntax is not on
     PATH, same convention as test_verible_parser.py.
  2. dut_facts.registers, vip_config, env_topology all round-trip through
     their own real parsers against small synthesized fixture files that
     conform to this module's own documented dump/input-file shapes --
     these fixtures are clearly-labeled test data, never presented as real
     captured project content.
  3. Every layer/sub-layer that requires a real captured artifact reports
     NOT_AVAILABLE with a non-empty `reason` when that artifact is absent
     -- asserted explicitly, since a silently-omitted layer would be a
     worse failure mode than a wrong value.
"""
from __future__ import annotations

import json
import shutil
import textwrap

import pytest

from dv_harness import env_manifest
from dv_harness.env_manifest import (
    EnvManifestValidationError,
    RegisterMapValidationError,
    build_component_hierarchy,
    build_config_db_trace,
    build_dut_facts,
    build_dut_facts_registers,
    build_dut_facts_rtl,
    build_env_topology,
    build_vip_config,
    generate_and_write,
    generate_env_manifest,
    load_env_manifest,
    load_register_map,
    parse_config_db_trace_log,
    parse_topology_dump,
    parse_vip_config_dump,
    save_env_manifest,
    validate_env_manifest,
    validate_register_map,
)

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

FIFO_FIXTURE = textwrap.dedent("""\
    module fifo_ctrl #(
        parameter int DEPTH = 16
    ) (
        input  logic       clk,
        input  logic       rst_n,
        output logic       full
    );
        logic [3:0] wr_ptr;
        assign full = (wr_ptr == 4'hF);
    endmodule
    """)


@pytest.fixture
def fifo_sv(tmp_path):
    p = tmp_path / "fifo_ctrl.sv"
    p.write_text(FIFO_FIXTURE, encoding="utf-8")
    return p


# A synthesized, clearly-fictional register map -- test data only, never
# real project register content (see register_map.schema.json's own
# docstring on the input-contract discipline this fixture demonstrates,
# not violates).
REGISTER_MAP_FIXTURE = {
    "schema_version": "1.0",
    "source": {"kind": "ral_model_export", "description": "synthesized test fixture, not a real project"},
    "blocks": [
        {
            "name": "TEST_CTRL_BLOCK",
            "base_address": "0x1000",
            "description": "Synthesized fixture block for env_manifest.py tests.",
            "registers": [
                {
                    "name": "CTRL",
                    "address_offset": "0x0",
                    "width": 32,
                    "access": "RW",
                    "reset_value": "0x0",
                    "description": "Control register.",
                    "fields": [
                        {"name": "ENABLE", "bit_offset": 0, "bit_width": 1, "access": "RW", "reset_value": "0x0"},
                        {"name": "MODE", "bit_offset": 1, "bit_width": 2, "access": "RW", "reset_value": "0x0"},
                    ],
                },
                {
                    "name": "STATUS",
                    "address_offset": "0x4",
                    "width": 32,
                    "access": "RO",
                    "reset_value": None,
                    "fields": [],
                },
            ],
        }
    ],
}


@pytest.fixture
def register_map_json(tmp_path):
    p = tmp_path / "register_map.json"
    p.write_text(json.dumps(REGISTER_MAP_FIXTURE), encoding="utf-8")
    return p


VIP_CONFIG_DUMP_FIXTURE = {
    "schema_version": "1.0",
    "vip_instances": [
        {
            "instance_path": "tb_top.dut_env.usb_agent.cfg",
            "vip_type": "usb_vip_config",
            "config_fields": {"is_active": "UVM_ACTIVE", "speed": "SS", "num_lanes": "1"},
        },
        {
            "instance_path": "tb_top.dut_env.usb_monitor_agent.cfg",
            "vip_type": "usb_vip_config",
            "config_fields": {"is_active": "UVM_PASSIVE", "speed": "SS"},
        },
    ],
}


@pytest.fixture
def vip_config_dump_json(tmp_path):
    p = tmp_path / "vip_config_dump.json"
    p.write_text(json.dumps(VIP_CONFIG_DUMP_FIXTURE), encoding="utf-8")
    return p


TOPOLOGY_DUMP_FIXTURE = {
    "schema_version": "1.0",
    "components": [
        {"full_name": "uvm_test_top", "type_name": "usb_base_test", "is_active": "NOT_APPLICABLE"},
        {"full_name": "uvm_test_top.env", "type_name": "usb_env", "is_active": "NOT_APPLICABLE"},
        {"full_name": "uvm_test_top.env.usb_agent", "type_name": "usb_agent", "is_active": "UVM_ACTIVE"},
        {"full_name": "uvm_test_top.env.usb_monitor_agent", "type_name": "usb_agent", "is_active": "UVM_PASSIVE"},
    ],
}


@pytest.fixture
def topology_dump_json(tmp_path):
    p = tmp_path / "topology_dump.json"
    p.write_text(json.dumps(TOPOLOGY_DUMP_FIXTURE), encoding="utf-8")
    return p


# A synthesized sim-log excerpt showing the well-documented UVM_INFO report
# envelope (file/line/@time/reporter/[id]) carrying CFGDB/SET and CFGDB/GET
# ids, plus unrelated UVM_INFO/UVM_ERROR noise this parser must ignore.
CONFIG_DB_TRACE_LOG_FIXTURE = textwrap.dedent("""\
    UVM_INFO tb_top.sv(42) @ 0: reporter [RNTST] Running test usb_base_test...
    UVM_INFO usb_config.sv(120) @ 0: uvm_test_top.env.usb_agent.cfg [CFGDB/SET] some opaque message body
    UVM_INFO usb_env.sv(88) @ 0: uvm_test_top.env [CFGDB/GET] another opaque message body
    UVM_ERROR usb_scoreboard.sv(200) @ 1500: uvm_test_top.env.sb [MISMATCH] unrelated error, must be ignored
    """)


@pytest.fixture
def config_db_trace_log(tmp_path):
    p = tmp_path / "sim.log"
    p.write_text(CONFIG_DB_TRACE_LOG_FIXTURE, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. dut_facts.rtl -- real round-trip through verible_parser.py
# ---------------------------------------------------------------------------

@requires_verible
def test_build_dut_facts_rtl_round_trips_through_real_verible(fifo_sv):
    result = build_dut_facts_rtl([fifo_sv])
    assert result["status"] == "PARSED"
    assert result["reason"] is None
    assert len(result["files"]) == 1
    mod = result["files"][0]["modules"][0]
    assert mod["name"] == "fifo_ctrl"
    ports_by_name = {p["name"]: p for p in mod["ports"]}
    assert ports_by_name["clk"]["direction"] == "input"
    assert ports_by_name["full"]["direction"] == "output"
    assert mod["parameters"][0]["name"] == "DEPTH"
    assert mod["parameters"][0]["default_text"] == "16"


@requires_verible
def test_build_dut_facts_rtl_sorts_files_by_path(tmp_path):
    (tmp_path / "b_mod.sv").write_text("module b_mod(input logic clk); endmodule\n", encoding="utf-8")
    (tmp_path / "a_mod.sv").write_text("module a_mod(input logic clk); endmodule\n", encoding="utf-8")
    result = build_dut_facts_rtl([tmp_path / "b_mod.sv", tmp_path / "a_mod.sv"])
    file_paths = [f["file_path"] for f in result["files"]]
    assert file_paths == sorted(file_paths)


def test_build_dut_facts_rtl_empty_input_is_honest_not_available():
    result = build_dut_facts_rtl([])
    assert result == {"status": "NOT_AVAILABLE", "reason": "no rtl_files supplied to this generation run", "files": []}


@requires_verible
def test_full_manifest_dut_facts_rtl_layer_round_trips_and_is_schema_valid(fifo_sv):
    manifest = generate_env_manifest(rtl_files=[fifo_sv])
    validate_env_manifest(manifest)  # raises on failure
    assert manifest["dut_facts"]["rtl"]["status"] == "PARSED"
    assert manifest["dut_facts"]["rtl"]["files"][0]["modules"][0]["name"] == "fifo_ctrl"


# ---------------------------------------------------------------------------
# 2a. dut_facts.registers -- structured input-contract round-trip
# ---------------------------------------------------------------------------

def test_load_register_map_round_trips_and_validates(register_map_json):
    doc = load_register_map(register_map_json)
    validate_register_map(doc)  # raises on failure
    assert doc["blocks"][0]["name"] == "TEST_CTRL_BLOCK"
    assert doc["blocks"][0]["registers"][0]["fields"][1]["name"] == "MODE"


def test_load_register_map_rejects_malformed_address(tmp_path):
    bad = dict(REGISTER_MAP_FIXTURE)
    bad["blocks"] = [{"name": "X", "base_address": "not-hex", "registers": []}]
    p = tmp_path / "bad_register_map.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(RegisterMapValidationError):
        load_register_map(p)


def test_build_dut_facts_registers_loaded(register_map_json):
    result = build_dut_facts_registers(register_map_json)
    assert result["status"] == "LOADED"
    assert result["reason"] is None
    assert result["source"]["path"] == str(register_map_json)
    assert result["blocks"] == REGISTER_MAP_FIXTURE["blocks"]


def test_build_dut_facts_registers_not_available_when_no_path_supplied():
    result = build_dut_facts_registers(None)
    assert result["status"] == "NOT_AVAILABLE"
    assert result["reason"]  # non-empty, honest explanation
    assert result["blocks"] == []


def test_build_dut_facts_combines_rtl_and_registers(register_map_json):
    result = build_dut_facts(rtl_files=[], register_map_path=register_map_json)
    assert result["rtl"]["status"] == "NOT_AVAILABLE"
    assert result["registers"]["status"] == "LOADED"


# ---------------------------------------------------------------------------
# 2b. vip_config -- real parser round-trip against the template dump shape
# ---------------------------------------------------------------------------

def test_parse_vip_config_dump_round_trips_and_sorts(vip_config_dump_json):
    instances = parse_vip_config_dump(vip_config_dump_json)
    assert [i["instance_path"] for i in instances] == sorted(i["instance_path"] for i in instances)
    active_agent = next(i for i in instances if "usb_agent" in i["instance_path"] and "monitor" not in i["instance_path"])
    assert active_agent["config_fields"]["is_active"] == "UVM_ACTIVE"
    assert active_agent["config_fields"]["speed"] == "SS"


def test_parse_vip_config_dump_rejects_missing_field(tmp_path):
    bad = {"schema_version": "1.0", "vip_instances": [{"instance_path": "x", "vip_type": "y"}]}
    p = tmp_path / "bad_vip_dump.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError):
        parse_vip_config_dump(p)


def test_build_vip_config_captured(vip_config_dump_json):
    result = build_vip_config(vip_config_dump_json)
    assert result["status"] == "CAPTURED"
    assert result["reason"] is None
    assert len(result["vip_instances"]) == 2


def test_build_vip_config_not_available_when_no_dump_supplied():
    result = build_vip_config(None)
    assert result["status"] == "NOT_AVAILABLE"
    assert result["reason"]
    assert result["vip_instances"] == []


def test_build_vip_config_not_available_when_dump_path_does_not_exist(tmp_path):
    result = build_vip_config(tmp_path / "does_not_exist.json")
    assert result["status"] == "NOT_AVAILABLE"
    assert result["reason"]


# ---------------------------------------------------------------------------
# 2b-bis. "a path WAS supplied but does not exist" must stay traceable
# (2026-09-03 review defect F4: all three dump-path layers previously
# reported a supplied-but-missing path identically to "no path supplied",
# silently discarding the actually-supplied wrong path -- a typo'd
# --vip-config-dump argument became invisible in the generated manifest)
# ---------------------------------------------------------------------------

def test_build_vip_config_supplied_but_missing_path_is_distinct_and_traceable(tmp_path):
    missing = tmp_path / "typo_vip_config.json"
    supplied = build_vip_config(missing)
    absent = build_vip_config(None)

    assert supplied["status"] == "NOT_AVAILABLE"
    # the real supplied path survives into the manifest, not None
    assert supplied["source"]["path"] == str(missing)
    assert str(missing) in supplied["reason"]
    # and is genuinely distinguishable from "nothing was supplied at all"
    assert supplied["reason"] != absent["reason"]
    assert absent["source"]["path"] is None


def test_build_component_hierarchy_supplied_but_missing_path_is_distinct_and_traceable(tmp_path):
    missing = tmp_path / "typo_topology.json"
    supplied = build_component_hierarchy(missing)
    absent = build_component_hierarchy(None)

    assert supplied["status"] == "NOT_AVAILABLE"
    assert supplied["source"]["path"] == str(missing)
    assert str(missing) in supplied["reason"]
    assert supplied["reason"] != absent["reason"]
    assert absent["source"]["path"] is None


def test_build_config_db_trace_supplied_but_missing_path_is_distinct_and_traceable(tmp_path):
    missing = tmp_path / "typo_sim.log"
    supplied = build_config_db_trace(missing)
    absent = build_config_db_trace(None)

    assert supplied["status"] == "NOT_AVAILABLE"
    assert supplied["source"]["path"] == str(missing)
    assert str(missing) in supplied["reason"]
    assert supplied["reason"] != absent["reason"]
    assert absent["source"]["path"] is None


def test_full_manifest_with_missing_supplied_dump_paths_is_still_schema_valid(tmp_path):
    """The distinct supplied-but-missing reason/path must not break the
    manifest's own schema -- a traceable honest failure, still a valid file."""
    manifest = generate_env_manifest(
        vip_config_dump_path=tmp_path / "nope_vip.json",
        topology_dump_path=tmp_path / "nope_topo.json",
        config_db_trace_log_path=tmp_path / "nope_sim.log",
    )
    validate_env_manifest(manifest)
    assert manifest["vip_config"]["source"]["path"] == str(tmp_path / "nope_vip.json")
    assert manifest["env_topology"]["component_hierarchy"]["source"]["path"] == str(tmp_path / "nope_topo.json")
    assert manifest["env_topology"]["config_db_trace"]["source"]["path"] == str(tmp_path / "nope_sim.log")


# ---------------------------------------------------------------------------
# 2c. env_topology.component_hierarchy -- real parser round-trip
# ---------------------------------------------------------------------------

def test_parse_topology_dump_round_trips_and_sorts(topology_dump_json):
    components = parse_topology_dump(topology_dump_json)
    assert [c["full_name"] for c in components] == sorted(c["full_name"] for c in components)
    agent = next(c for c in components if c["full_name"].endswith("usb_agent"))
    assert agent["is_active"] == "UVM_ACTIVE"
    monitor_agent = next(c for c in components if c["full_name"].endswith("usb_monitor_agent"))
    assert monitor_agent["is_active"] == "UVM_PASSIVE"
    env = next(c for c in components if c["full_name"].endswith(".env"))
    assert env["is_active"] == "NOT_APPLICABLE"


def test_build_env_topology_component_hierarchy_captured(topology_dump_json):
    result = build_env_topology(hierarchy_dump_path=topology_dump_json)
    assert result["component_hierarchy"]["status"] == "CAPTURED"
    assert len(result["component_hierarchy"]["components"]) == 4


def test_build_env_topology_component_hierarchy_not_available_when_absent():
    result = build_env_topology()
    assert result["component_hierarchy"]["status"] == "NOT_AVAILABLE"
    assert result["component_hierarchy"]["reason"]


# ---------------------------------------------------------------------------
# 2d. env_topology.config_db_trace -- envelope-verified, message-opaque parse
# ---------------------------------------------------------------------------

def test_parse_config_db_trace_log_extracts_only_cfgdb_lines(config_db_trace_log):
    entries = parse_config_db_trace_log(config_db_trace_log.read_text(encoding="utf-8"))
    assert len(entries) == 2  # the RNTST and MISMATCH lines are correctly ignored
    kinds = {e["kind"] for e in entries}
    assert kinds == {"SET", "GET"}
    set_entry = next(e for e in entries if e["kind"] == "SET")
    assert set_entry["file"] == "usb_config.sv"
    assert set_entry["line"] == 120
    assert set_entry["reporter"] == "uvm_test_top.env.usb_agent.cfg"
    assert set_entry["message"] == "some opaque message body"


def test_parse_config_db_trace_log_empty_text_returns_no_entries():
    assert parse_config_db_trace_log("") == []


def test_build_config_db_trace_captured_with_confidence_flag(config_db_trace_log):
    result = build_config_db_trace(config_db_trace_log)
    assert result["status"] == "CAPTURED"
    assert result["parse_confidence"] == "envelope_verified_message_opaque"
    assert len(result["entries"]) == 2


def test_build_config_db_trace_not_available_when_no_log_supplied():
    result = build_config_db_trace(None)
    assert result["status"] == "NOT_AVAILABLE"
    assert result["reason"]
    assert result["parse_confidence"] is None
    assert result["entries"] == []


# ---------------------------------------------------------------------------
# 3. NOT_AVAILABLE is reported honestly (not silently omitted) end-to-end
# ---------------------------------------------------------------------------

def test_full_manifest_with_no_inputs_is_schema_valid_and_honestly_not_available():
    manifest = generate_env_manifest()
    validate_env_manifest(manifest)  # raises on failure
    assert manifest["vip_config"]["status"] == "NOT_AVAILABLE"
    assert manifest["vip_config"]["reason"]
    assert manifest["dut_facts"]["rtl"]["status"] == "NOT_AVAILABLE"
    assert manifest["dut_facts"]["rtl"]["reason"]
    assert manifest["dut_facts"]["registers"]["status"] == "NOT_AVAILABLE"
    assert manifest["dut_facts"]["registers"]["reason"]
    assert manifest["env_topology"]["component_hierarchy"]["status"] == "NOT_AVAILABLE"
    assert manifest["env_topology"]["component_hierarchy"]["reason"]
    assert manifest["env_topology"]["config_db_trace"]["status"] == "NOT_AVAILABLE"
    assert manifest["env_topology"]["config_db_trace"]["reason"]
    # every "reason" present in a NOT_AVAILABLE layer is non-empty text, not
    # merely a present-but-blank field -- an agent grepping for the honest
    # explanation must actually find one.
    for layer_reason in (
        manifest["vip_config"]["reason"],
        manifest["dut_facts"]["rtl"]["reason"],
        manifest["dut_facts"]["registers"]["reason"],
        manifest["env_topology"]["component_hierarchy"]["reason"],
        manifest["env_topology"]["config_db_trace"]["reason"],
    ):
        assert isinstance(layer_reason, str) and len(layer_reason) > 10


def test_full_manifest_never_fabricates_vip_or_topology_content_when_absent():
    manifest = generate_env_manifest()
    assert manifest["vip_config"]["vip_instances"] == []
    assert manifest["env_topology"]["component_hierarchy"]["components"] == []
    assert manifest["env_topology"]["config_db_trace"]["entries"] == []
    assert manifest["dut_facts"]["registers"]["blocks"] == []


# ---------------------------------------------------------------------------
# generate_and_write() / save_env_manifest() / load_env_manifest() -- full
# round trip, plus determinism (diffable-generation requirement)
# ---------------------------------------------------------------------------

def test_generate_and_write_then_load_round_trips(tmp_path, register_map_json, vip_config_dump_json,
                                                     topology_dump_json, config_db_trace_log):
    out = tmp_path / "env.manifest.json"
    written = generate_and_write(
        out,
        register_map_path=register_map_json,
        vip_config_dump_path=vip_config_dump_json,
        topology_dump_path=topology_dump_json,
        config_db_trace_log_path=config_db_trace_log,
    )
    reloaded = load_env_manifest(out)
    assert reloaded == written
    assert reloaded["vip_config"]["status"] == "CAPTURED"
    assert reloaded["dut_facts"]["registers"]["status"] == "LOADED"
    assert reloaded["env_topology"]["component_hierarchy"]["status"] == "CAPTURED"
    assert reloaded["env_topology"]["config_db_trace"]["status"] == "CAPTURED"


def test_regenerating_from_unchanged_inputs_is_byte_identical(tmp_path, register_map_json):
    out1 = tmp_path / "m1.json"
    out2 = tmp_path / "m2.json"
    generate_and_write(out1, register_map_path=register_map_json)
    generate_and_write(out2, register_map_path=register_map_json)
    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")
    assert "generated_at" not in out1.read_text(encoding="utf-8")


def test_save_env_manifest_refuses_invalid_manifest(tmp_path):
    with pytest.raises(EnvManifestValidationError):
        save_env_manifest({"schema_version": "1.0"}, tmp_path / "bad.json")


def test_load_env_manifest_refuses_invalid_file_on_disk(tmp_path):
    p = tmp_path / "not_a_manifest.json"
    p.write_text(json.dumps({"schema_version": "1.0", "extra_bad_field": True}), encoding="utf-8")
    with pytest.raises(EnvManifestValidationError):
        load_env_manifest(p)
