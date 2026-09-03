"""dv_harness_tests/mcp_manifest_fixture.py -- a synthetic env.manifest.json
fixture matching the REAL, now-landed generator's contract:
dv_harness/schemas/env_manifest.schema.json (dv_harness/env_manifest.py).

RECONCILIATION NOTE (2026-09-03): this MCP server's verbs.py was originally
built against an ASSUMED manifest shape (Part A's own spec text) because
the real env.manifest.json generator workstream was running in parallel and
had not landed yet. It landed partway through this same session; this
fixture and dv_harness/mcp/verbs.py were both then updated to match the
REAL field names below exactly (see .work/mcp-server-report.md for the
full diff of what changed and why). dv_harness_tests/
test_mcp_env_manifest_integration.py additionally builds a manifest through
the real generator's own generate_env_manifest() (not just this hand-authored
fixture) as the strongest available proof this package's verbs.py actually
matches the real contract, not just this file's own guess at it.

Deliberately NOT collected as a pytest test module (no `test_` prefix), so
other test files import `build_fixture_manifest()` from here the same way
dv_harness_tests/test_evidence_db.py imports FIFO_FIXTURE from
test_verible_parser.py."""
from __future__ import annotations

import copy

_FIXTURE_MANIFEST = {
    "schema_version": "1.0",
    "generator": {"tool": "dv_harness.env_manifest", "version": "1.0"},

    "vip_config": {
        "status": "CAPTURED",
        "source": {"kind": "vip_config_dump_json", "path": "run/usb3_smoke/vip_config_dump.json"},
        "reason": None,
        "vip_instances": [
            {
                "instance_path": "uvm_test_top.env.usb3_agent0.cfg",
                "vip_type": "usb3_vip_config",
                "config_fields": {"is_active": "UVM_ACTIVE", "speed_mode": "SS_GEN1", "num_lanes": "1"},
            },
            {
                "instance_path": "uvm_test_top.env.apb_agent0.cfg",
                "vip_type": "apb_vip_config",
                "config_fields": {"is_active": "UVM_PASSIVE"},
            },
        ],
    },

    "dut_facts": {
        "rtl": {
            "status": "PARSED",
            "reason": None,
            "files": [
                {
                    "file_path": "rtl/usb3_top.sv",
                    "source_sha256": "aaaa1111",
                    "verible_version": "v0.0-3000-g1234567",
                    "modules": [
                        {
                            "name": "usb3_top",
                            "parameters": [
                                {"name": "NUM_LANES", "type_text": "int", "default_text": "1"},
                            ],
                            "ports": [
                                {"name": "clk", "direction": "input", "data_type": "logic"},
                                {"name": "rst_n", "direction": "input", "data_type": "logic"},
                                {"name": "utmi_txvalid", "direction": "output", "data_type": "logic"},
                            ],
                            "signals": [
                                {"name": "link_state", "data_type": "logic [3:0]", "unpacked_dims": None},
                            ],
                        },
                    ],
                },
                {
                    "file_path": "rtl/apb_bridge.sv",
                    "source_sha256": "bbbb2222",
                    "verible_version": "v0.0-3000-g1234567",
                    "modules": [
                        {
                            "name": "apb_bridge",
                            "parameters": [],
                            "ports": [
                                {"name": "pclk", "direction": "input", "data_type": "logic"},
                                {"name": "pready", "direction": "output", "data_type": "logic"},
                            ],
                            "signals": [],
                        },
                    ],
                },
            ],
        },
        "registers": {
            "status": "LOADED",
            "source": {"kind": "ral_model_export", "path": "regmap/usb3_regmap.json"},
            "reason": None,
            "blocks": [
                {
                    "name": "USB3_CTRL_BLOCK",
                    "base_address": "0x1000",
                    "description": "USB3 control/status block.",
                    "registers": [
                        {
                            "name": "CTRL",
                            "address_offset": "0x0",
                            "width": 32,
                            "access": "RW",
                            "reset_value": "0x0",
                            "description": "Block enable/control.",
                            "fields": [
                                {"name": "EN", "bit_offset": 0, "bit_width": 1, "access": "RW",
                                 "reset_value": "0x0", "description": "Block enable."},
                            ],
                        },
                        {
                            "name": "STATUS",
                            "address_offset": "0x4",
                            "width": 32,
                            "access": "RO",
                            "reset_value": None,
                            "description": "Block status.",
                            "fields": [],
                        },
                    ],
                },
            ],
        },
    },

    "env_topology": {
        "component_hierarchy": {
            "status": "CAPTURED",
            "source": {"kind": "topology_dump_json", "path": "run/usb3_smoke/topology_dump.json"},
            "reason": None,
            "components": [
                {"full_name": "uvm_test_top", "type_name": "usb3_base_test", "is_active": "NOT_APPLICABLE"},
                {"full_name": "uvm_test_top.env", "type_name": "usb3_env", "is_active": "NOT_APPLICABLE"},
                {"full_name": "uvm_test_top.env.usb3_agent0", "type_name": "usb3_agent", "is_active": "UVM_ACTIVE"},
                {"full_name": "uvm_test_top.env.usb3_agent0.monitor", "type_name": "usb3_monitor",
                 "is_active": "NOT_APPLICABLE"},
                {"full_name": "uvm_test_top.env.apb_agent0", "type_name": "apb_agent", "is_active": "UVM_PASSIVE"},
            ],
        },
        "config_db_trace": {
            "status": "CAPTURED",
            "source": {"kind": "sim_log_uvm_config_db_trace", "path": "run/usb3_smoke/sim.log"},
            "reason": None,
            "parse_confidence": "envelope_verified_message_opaque",
            "entries": [
                {"kind": "SET", "file": "usb3_config.sv", "line": 120, "time": "0",
                 "reporter": "uvm_test_top.env.usb3_agent0.cfg", "message": "set vif for usb3_agent0"},
                {"kind": "GET", "file": "usb3_agent.sv", "line": 55, "time": "0",
                 "reporter": "uvm_test_top.env.usb3_agent0.driver", "message": "get vif in driver"},
                {"kind": "GET", "file": "usb3_agent.sv", "line": 61, "time": "0",
                 "reporter": "uvm_test_top.env.usb3_agent0.monitor", "message": "get vif in monitor"},
                {"kind": "SET", "file": "apb_config.sv", "line": 80, "time": "0",
                 "reporter": "uvm_test_top.env.apb_agent0.cfg", "message": "set vif for apb_agent0"},
                # Deliberately no matching GET reporter under
                # uvm_test_top.env.apb_agent0.* -- Part C: "a set with no
                # get is direct evidence of a miswired vif". See
                # dv_harness/mcp/verbs.py's get_topology docstring for why
                # this package reports RAW SET/GET counts only and does NOT
                # claim a per-field matched/unmatched verdict (the real
                # generator's own parse_confidence flags the message BODY
                # as unparsed/opaque, so field-level pairing is not
                # evidence-backed yet).
            ],
        },
    },
}


def build_fixture_manifest() -> dict:
    """Returns a fresh deep copy each call -- callers are free to mutate
    their own copy (e.g. to build a NOT_AVAILABLE variant) without affecting
    other tests."""
    return copy.deepcopy(_FIXTURE_MANIFEST)


def build_not_available_manifest() -> dict:
    """A manifest whose vip_config/dut_facts.registers/dut_facts.rtl/
    env_topology all honestly report NOT_AVAILABLE (no live dump/RAL
    source/topology capture/trace log exists yet) -- exercises every verb's
    honest-NOT_AVAILABLE path, matching the real generator's own
    NOT_AVAILABLE-by-honest-design contract."""
    m = build_fixture_manifest()
    m["vip_config"] = {"status": "NOT_AVAILABLE", "source": {"kind": "vip_config_dump_json", "path": None},
                        "reason": "no end_of_elaboration_phase dump found for this run", "vip_instances": []}
    m["dut_facts"]["rtl"] = {"status": "NOT_AVAILABLE", "reason": "no rtl_files supplied", "files": []}
    m["dut_facts"]["registers"] = {"status": "NOT_AVAILABLE",
                                    "source": {"kind": "register_map_json", "path": None},
                                    "reason": "no register-map input was supplied", "blocks": []}
    m["env_topology"] = {
        "component_hierarchy": {"status": "NOT_AVAILABLE",
                                 "source": {"kind": "topology_dump_json", "path": None},
                                 "reason": "no topology dump found for this run", "components": []},
        "config_db_trace": {"status": "NOT_AVAILABLE",
                             "source": {"kind": "sim_log_uvm_config_db_trace", "path": None},
                             "reason": "no +UVM_CONFIG_DB_TRACE log supplied",
                             "parse_confidence": None, "entries": []},
    }
    return m
