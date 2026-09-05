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
    "schema_version": "1.2",
    # Schema 1.2's `generator` block is spec section 210's per-artifact
    # generation provenance tuple. This fixture is hand-authored, so it
    # honestly declares no producing agent and no input IR -- exactly what a
    # generation run that declared neither really records.
    "generator": {
        "tool": "dv_harness.env_manifest",
        "version": "1.2",
        "tool_version": "15.0.0",
        "agent": {"status": "NOT_DECLARED", "identifier": None,
                  "resolution": "NOT_DECLARED",
                  "reason": "hand-authored MCP test fixture; no generating agent was declared"},
        "input_ir": {"status": "NOT_DECLARED", "kind": None, "reference": None,
                     "source": {"path": None, "sha256": None, "bytes": None},
                     "contract_schema_version": None, "requirement_status": None,
                     "downstream_consumable": None,
                     "reason": "hand-authored MCP test fixture; no input IR was declared"},
        "repository_sha": {
            "harness": {"status": "NOT_AVAILABLE", "sha": None,
                        "reason": "hand-authored MCP test fixture; no real generation run produced it"},
            "project": {"status": "NOT_DECLARED", "sha": None,
                        "reason": "hand-authored MCP test fixture; no project root was declared"},
        },
    },

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
        # Schema 1.1's two added VIP fact sources (2026-09-04). Kept as
        # NOT_AVAILABLE/empty here on purpose: this fixture exists to
        # exercise the MCP verbs, none of which read these sub-layers, and a
        # fabricated DesignWare install path would be fixture content
        # pretending to describe a real tree.
        "vip_release": {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "designware_home_scan", "path": None},
            "reason": "$DESIGNWARE_HOME is not set for this fixture",
            "designware_home": None,
            "packages": [],
        },
        "user_guide_refs": {
            "status": "NOT_AVAILABLE",
            "reason": "no VIP user guide has been distilled for this fixture",
            "documents": [],
        },
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
        # Schema 1.1's SoC-spec-pipeline DUT fact source (2026-09-04). The
        # address_map entry deliberately AGREES with USB3_CTRL_BLOCK's
        # 0x1000 above, so this fixture models a consistent environment;
        # the disagreement path is exercised by test_env_manifest_fact_
        # sources.py against the real builder rather than hand-authored here.
        "address_map": {
            "status": "LOADED",
            "source": {"kind": "soc_arch_map_json", "path": "arch/usb3_soc_arch_map.json"},
            "reason": None,
            "entries": [
                {
                    "name": "USB3_CTRL_BLOCK",
                    "base_address": "0x1000",
                    "size_bytes": 4096,
                    "target": "chip.core.usb0",
                    "bus": "APB",
                    "evidence": "rtl/soc_decoder.sv:212",
                    "description": "USB3 control/status region.",
                    "register_map_agreement": "AGREES",
                },
            ],
            "disagreement_count": 0,
        },
        "clock_reset": {
            "status": "LOADED",
            "source": {"kind": "soc_arch_map_json", "path": "arch/usb3_soc_arch_map.json"},
            "reason": None,
            "clocks": [
                {"name": "pclk", "frequency_mhz": 100.0, "source": "pll0_out_div4",
                 "domain": "apb", "evidence": "arch/clocks.md#apb", "description": "APB register clock."},
            ],
            "resets": [
                {"name": "presetn", "active_level": "low", "synchronous": True, "clock": "pclk",
                 "clock_resolved": "RESOLVED", "evidence": "arch/resets.md#apb",
                 "description": "APB reset."},
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
        # Schema 1.1's testlist/vPlan/coverage three-way join (2026-09-04).
        # VP-002 deliberately claims `usb3_link_recovery_test`, which is NOT
        # in the testlist -- a real broken link, so this fixture exercises
        # the finding this layer exists to surface rather than an all-clean
        # environment no correspondence check would ever have been built for.
        "testplan_correspondence": {
            "status": "COMPUTED",
            "source": {"kind": "testplan_sources_json", "path": "vplan/usb3_testplan_sources.json"},
            "reason": None,
            "axes_available": {"testlist": True, "vplan_items": True, "coverage_model": True},
            "items": [
                {
                    "id": "VP-001",
                    "tests_claimed": 1, "tests_present": ["usb3_smoke_test"], "tests_missing": [],
                    "coverage_claimed": 1, "coverage_present": ["cg_usb3_link_state"], "coverage_missing": [],
                    "verdict": "LINKED",
                },
                {
                    "id": "VP-002",
                    "tests_claimed": 1, "tests_present": [], "tests_missing": ["usb3_link_recovery_test"],
                    "coverage_claimed": 0, "coverage_present": [], "coverage_missing": [],
                    "verdict": "BROKEN_TEST_REF",
                },
            ],
            "orphans": {
                "tests_not_in_any_vplan_item": ["usb3_reset_test"],
                "coverage_not_referenced_by_any_vplan_item": [],
            },
            "summary": {
                "testlist_count": 2, "vplan_item_count": 2, "coverage_model_count": 1,
                "linked_count": 1, "broken_count": 1, "unclaimed_count": 0,
                "orphan_test_count": 1, "orphan_coverage_count": 0,
            },
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
    m["vip_config"] = {
        "status": "NOT_AVAILABLE", "source": {"kind": "vip_config_dump_json", "path": None},
        "reason": "no end_of_elaboration_phase dump found for this run", "vip_instances": [],
        "vip_release": {"status": "NOT_AVAILABLE",
                         "source": {"kind": "designware_home_scan", "path": None},
                         "reason": "$DESIGNWARE_HOME is not set", "designware_home": None, "packages": []},
        "user_guide_refs": {"status": "NOT_AVAILABLE",
                             "reason": "no VIP user guide has been distilled yet", "documents": []},
    }
    m["dut_facts"]["rtl"] = {"status": "NOT_AVAILABLE", "reason": "no rtl_files supplied", "files": []}
    m["dut_facts"]["registers"] = {"status": "NOT_AVAILABLE",
                                    "source": {"kind": "register_map_json", "path": None},
                                    "reason": "no register-map input was supplied", "blocks": []}
    m["dut_facts"]["address_map"] = {"status": "NOT_AVAILABLE",
                                      "source": {"kind": "soc_arch_map_json", "path": None},
                                      "reason": "no SoC architecture-map input was supplied",
                                      "entries": [], "disagreement_count": 0}
    m["dut_facts"]["clock_reset"] = {"status": "NOT_AVAILABLE",
                                      "source": {"kind": "soc_arch_map_json", "path": None},
                                      "reason": "no SoC architecture-map input was supplied",
                                      "clocks": [], "resets": []}
    m["env_topology"] = {
        "component_hierarchy": {"status": "NOT_AVAILABLE",
                                 "source": {"kind": "topology_dump_json", "path": None},
                                 "reason": "no topology dump found for this run", "components": []},
        "config_db_trace": {"status": "NOT_AVAILABLE",
                             "source": {"kind": "sim_log_uvm_config_db_trace", "path": None},
                             "reason": "no +UVM_CONFIG_DB_TRACE log supplied",
                             "parse_confidence": None, "entries": []},
        "testplan_correspondence": {
            "status": "NOT_AVAILABLE",
            "source": {"kind": "testplan_sources_json", "path": None},
            "reason": "no testplan-sources input was supplied",
            "axes_available": {"testlist": False, "vplan_items": False, "coverage_model": False},
            "items": [],
            "orphans": {"tests_not_in_any_vplan_item": [],
                         "coverage_not_referenced_by_any_vplan_item": []},
            "summary": {"testlist_count": 0, "vplan_item_count": 0, "coverage_model_count": 0,
                         "linked_count": 0, "broken_count": 0, "unclaimed_count": 0,
                         "orphan_test_count": 0, "orphan_coverage_count": 0},
        },
    }
    return m
