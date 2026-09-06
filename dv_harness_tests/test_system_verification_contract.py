"""Tests for dv_harness/system_verification_contract.py.

Every subsystem-contract/system-topology/system-resource-registry/system-
command-registry fixture below is a small, hand-built dict shaped exactly
like the real producer's own documented output (`subsystem_contract.py`,
`system_topology_analysis.py`, `system_resource_inventory.py`,
`system_command_plan.py`) -- this module never imports any of those four,
per its own strict file-safety scope, so these fixtures stand in for their
real output shape without importing the modules that produce it."""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import system_verification_contract as svc


# ---------------------------------------------------------------------------
# Fixtures -- real-shaped, hand-built (never imported from the real producers)
# ---------------------------------------------------------------------------

def _clean_subsystem_contract(name: str) -> dict:
    return {
        "schema_version": "1.0",
        "assembled_at": "2026-09-06T00:00:00+00:00",
        "project_root": f"/projects/{name}",
        "subsystem": {"requested": name, "resolved_name": name,
                      "source": "REGISTERED_SUBSYSTEM_ENTRY"},
        "spec_version": {"status": "CAPTURED", "value": "1.2"},
        "dut_sha": {"status": "CAPTURED", "value": "abc123"},
        "tb_sha": {"status": "CAPTURED", "value": "def456"},
        "protocols": ["USB"],
        "interfaces": [{"instance_path": f"{name}.usb0", "vip_type": "svt_usb"}],
        "vip_config": {"status": "PRESENT"},
        "requirements": {"status": "PRESENT"},
        "vplan_tests_coverage": {"status": "COMPUTED"},
        "regression": {"status": "PRESENT"},
        "signoff": {"stage": {"stage_status": "PASS"},
                    "baseline_freeze": {"status": "PRESENT"}},
        "evidence_references": {"status": "PRESENT"},
        "reproducibility_capsules": {"status": "PRESENT"},
        "waivers": {"status": "PRESENT"},
        "unknowns": [],
        "tracked_aspect_count": 11,
        "unavailable_aspect_count": 0,
        "completeness": "COMPLETE",
    }


def _partial_subsystem_contract(name: str) -> dict:
    doc = _clean_subsystem_contract(name)
    doc["regression"] = {"status": "NOT_AVAILABLE", "reason": "NO_RECORDED_JOBS"}
    doc["unknowns"] = [{"field": "regression", "reason": "NO_RECORDED_JOBS"}]
    doc["unavailable_aspect_count"] = 1
    doc["completeness"] = "PARTIAL"
    return doc


def _not_available_subsystem_contract(name: str) -> dict:
    return {
        "subsystem": {"requested": name, "resolved_name": None,
                      "source": "SUBSYSTEM_NOT_REGISTERED"},
        "unknowns": [{"field": f, "reason": "nothing on disk"} for f in range(11)],
        "completeness": "NOT_AVAILABLE",
    }


def _clean_topology() -> dict:
    return {
        "schema_version": "1.0",
        "selected_subsystems": ["usb_sub", "pcie_sub"],
        "address_map_reconciliation": {"summary": {"region_count": 4, "conflicts": 0}},
        "summary": {
            "selected_subsystems": ["usb_sub", "pcie_sub"],
            "address_regions": 4, "address_overlaps": 0, "address_conflicts": 0,
            "shared_memory_windows": 0, "interrupt_lines": 2, "shared_interrupt_lines": 0,
            "clock_reset_conflicts": 0, "cdc_boundaries": 0,
            "duplicate_clock_reset_agents": 0, "scenarios_planned": 3,
            "topology_clean": True,
        },
        "artifacts_generated": [],
    }


def _clean_resource_registry() -> dict:
    return {
        "status": "CROSSCHECK_AVAILABLE",
        "subsystems": ["usb_sub", "pcie_sub"],
        "resource_count": 6,
        "driver_conflicts": 0,
        "automatic_integration_allowed": True,
        "stopped_resource_ids": [],
        "held_resource_ids": [],
        "blocking_decisions": [],
        "shared_resource_ids": [],
        "preferred_model": "SYS12_PREFERRED_MODEL_TEXT",
    }


def _unavailable_resource_registry() -> dict:
    return {
        "status": "CROSSCHECK_UNAVAILABLE",
        "reason": "FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE",
        "subsystems": ["usb_sub"],
    }


def _clean_command_registry() -> dict:
    return {
        "schema_version": "1.0",
        "system_architecture": {"selected_subsystems": ["usb_sub", "pcie_sub"]},
        "summary": {
            "selected_subsystems": ["usb_sub", "pcie_sub"],
            "system_commands": 12, "routes_reusing_subsystem_semantics": 10,
            "ir_entries": 12, "collisions": 0, "blocking_collisions": 0,
            "subsystem_modes_preserved": True, "command_plan_clean": True,
        },
        "artifacts_generated": [],
    }


# ---------------------------------------------------------------------------
# Core positive path
# ---------------------------------------------------------------------------

def test_assemble_full_complete_record():
    record = svc.assemble_system_verification_contract(
        subsystem_contracts=[_clean_subsystem_contract("usb_sub"),
                             _clean_subsystem_contract("pcie_sub")],
        system_topology=_clean_topology(),
        system_resource_registry=_clean_resource_registry(),
        system_command_registry=_clean_command_registry(),
        system_name="my_soc")

    assert record["schema_version"] == svc.SCHEMA_VERSION
    assert record["system_name"] == "my_soc"
    assert record["completeness"] == svc.COMPLETE
    assert record["unknowns"] == []
    assert record["unavailable_aspect_count"] == 0
    assert record["tracked_aspect_count"] == len(svc.TRACKED_ASPECTS)

    sc = record["subsystem_contracts"]
    assert sc["status"] == svc.STATUS_PRESENT
    assert sc["count"] == 2
    assert sc["completeness_rollup"]["COMPLETE"] == 2
    assert sc["entries"][0]["subsystem_name"] == "usb_sub"
    assert sc["entries"][0]["spec_version_status"] == "CAPTURED"
    assert sc["entries"][0]["signoff_stage_status"] == "PASS"

    topo = record["system_topology"]
    assert topo["status"] == svc.STATUS_PRESENT
    assert topo["address_conflicts"] == 0
    assert topo["topology_clean"] is True

    rr = record["system_resource_registry"]
    assert rr["status"] == svc.STATUS_PRESENT
    assert rr["driver_conflicts"] == 0
    assert rr["preferred_model"] == "SYS12_PREFERRED_MODEL_TEXT"

    cr = record["system_command_registry"]
    assert cr["status"] == svc.STATUS_PRESENT
    assert cr["command_plan_clean"] is True

    # render_contract_text() must not raise and must reflect COMPLETE
    text = svc.render_contract_text(record)
    assert "COMPLETE" in text
    assert "no unknowns" in text


def test_a_partial_subsystem_contract_is_visible_but_not_an_unknown():
    """A subsystem contract that is legitimately PARTIAL (a real fact about
    that subsystem) must not be conflated with this module's own inability
    to assemble a fact -- it is surfaced in the rollup, never in
    `unknowns`."""
    record = svc.assemble_system_verification_contract(
        subsystem_contracts=[_partial_subsystem_contract("usb_sub")],
        system_topology=_clean_topology(),
        system_resource_registry=_clean_resource_registry(),
        system_command_registry=_clean_command_registry())

    sc = record["subsystem_contracts"]
    assert sc["completeness_rollup"]["PARTIAL"] == 1
    assert record["completeness"] == svc.COMPLETE
    assert record["unknowns"] == []


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------

def test_bare_record_reports_every_aspect_not_available_never_fabricated():
    """MOST IMPORTANT: with nothing supplied at all, this module must never
    claim COMPLETE, and must never fabricate a section's own facts."""
    record = svc.assemble_system_verification_contract()

    assert record["completeness"] == svc.NOT_AVAILABLE_OVERALL
    assert len(record["unknowns"]) == len(svc.TRACKED_ASPECTS) == 4
    fields = {u["field"] for u in record["unknowns"]}
    assert fields == set(svc.TRACKED_ASPECTS)

    for section_name in ("subsystem_contracts", "system_topology",
                         "system_resource_registry", "system_command_registry"):
        assert record[section_name]["status"] == svc.STATUS_NOT_AVAILABLE
        assert record[section_name]["reason"]

    # render_contract_text() must not raise on the bare case either
    text = svc.render_contract_text(record)
    assert "NOT_AVAILABLE" in text
    assert "UNKNOWNS (4)" in text


def test_malformed_subsystem_contract_entry_reports_unknown_shape_not_a_crash():
    record = svc.assemble_system_verification_contract(
        subsystem_contracts=["not-a-dict", _clean_subsystem_contract("pcie_sub")],
        system_topology=_clean_topology(),
        system_resource_registry=_clean_resource_registry(),
        system_command_registry=_clean_command_registry())

    sc = record["subsystem_contracts"]
    assert sc["entries"][0]["completeness"] == svc.SUBSYSTEM_UNKNOWN_SHAPE
    assert "not a mapping" in sc["entries"][0]["reason"]
    assert sc["completeness_rollup"][svc.SUBSYSTEM_UNKNOWN_SHAPE] == 1
    # the aspect itself is still PRESENT (a real, if partly broken, aggregate)
    assert sc["status"] == svc.STATUS_PRESENT
    # but it is named in unknowns, since a real subsystem entry could not be read
    assert any(u["field"] == "subsystem_contracts" for u in record["unknowns"])
    assert record["completeness"] == svc.PARTIAL


def test_unavailable_resource_registry_carries_the_real_reason_never_silently_clear():
    record = svc.assemble_system_verification_contract(
        subsystem_contracts=[_clean_subsystem_contract("usb_sub")],
        system_topology=_clean_topology(),
        system_resource_registry=_unavailable_resource_registry(),
        system_command_registry=_clean_command_registry())

    rr = record["system_resource_registry"]
    assert rr["status"] == svc.STATUS_NOT_AVAILABLE
    assert rr["reason"] == "FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE"
    assert any(u["field"] == "system_resource_registry"
              and u["reason"] == "FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE"
              for u in record["unknowns"])
    assert record["completeness"] == svc.PARTIAL


def test_topology_missing_summary_block_reports_not_available_with_reason():
    record = svc.assemble_system_verification_contract(
        subsystem_contracts=[_clean_subsystem_contract("usb_sub")],
        system_topology={"selected_subsystems": ["usb_sub"]},  # no "summary" key
        system_resource_registry=_clean_resource_registry(),
        system_command_registry=_clean_command_registry())

    topo = record["system_topology"]
    assert topo["status"] == svc.STATUS_NOT_AVAILABLE
    assert "summary" in topo["reason"]
    assert topo["selected_subsystems"] == ["usb_sub"]
    assert record["completeness"] == svc.PARTIAL


def test_unrecognized_resource_registry_status_reported_honestly():
    record = svc.assemble_system_verification_contract(
        system_resource_registry={"status": "SOMETHING_ELSE"})
    rr = record["system_resource_registry"]
    assert rr["status"] == svc.STATUS_NOT_AVAILABLE
    assert "unrecognized status" in rr["reason"]


def test_command_registry_wrong_type_reported_not_a_crash():
    record = svc.assemble_system_verification_contract(
        system_command_registry=["this", "is", "a", "list"])
    cr = record["system_command_registry"]
    assert cr["status"] == svc.STATUS_NOT_AVAILABLE
    assert "not a mapping" in cr["reason"]


def test_completeness_thresholds():
    # exactly 4 unknowns (nothing supplied) -> NOT_AVAILABLE
    assert svc.assemble_system_verification_contract()["completeness"] == svc.NOT_AVAILABLE_OVERALL
    # 1 of 4 unknown -> PARTIAL
    record = svc.assemble_system_verification_contract(
        subsystem_contracts=[_clean_subsystem_contract("usb_sub")],
        system_topology=_clean_topology(),
        system_resource_registry=_clean_resource_registry())
    assert record["completeness"] == svc.PARTIAL
    assert record["unavailable_aspect_count"] == 1


# ---------------------------------------------------------------------------
# Write / snapshot
# ---------------------------------------------------------------------------

def test_write_system_verification_contract(tmp_path):
    record = svc.assemble_system_verification_contract(
        subsystem_contracts=[_clean_subsystem_contract("usb_sub")],
        system_topology=_clean_topology(),
        system_resource_registry=_clean_resource_registry(),
        system_command_registry=_clean_command_registry())
    out = svc.write_system_verification_contract(tmp_path, record)
    assert out == tmp_path / ".dv-harness" / "system_verification_contract.json"
    assert out.is_file()
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded["completeness"] == svc.COMPLETE


def test_write_refuses_nonexistent_root(tmp_path):
    with pytest.raises(svc.SystemVerificationContractError):
        svc.write_system_verification_contract(tmp_path / "does_not_exist", {"x": 1})


# ---------------------------------------------------------------------------
# execute_verb / CLI
# ---------------------------------------------------------------------------

def _write_json(path: Path, data) -> str:
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_execute_verb_assemble_complete(tmp_path):
    sc_path = _write_json(tmp_path / "subsystems.json",
                          [_clean_subsystem_contract("usb_sub")])
    topo_path = _write_json(tmp_path / "topology.json", _clean_topology())
    rr_path = _write_json(tmp_path / "resource_registry.json", _clean_resource_registry())
    cr_path = _write_json(tmp_path / "command_registry.json", _clean_command_registry())

    text, code = svc.execute_verb(
        "assemble", root=tmp_path,
        subsystem_contracts_path=sc_path, topology_path=topo_path,
        resource_registry_path=rr_path, command_registry_path=cr_path,
        as_json=True)
    assert code == 0
    parsed = json.loads(text)
    assert parsed["completeness"] == "COMPLETE"
    # assemble never writes
    assert not (tmp_path / ".dv-harness").exists()


def test_execute_verb_snapshot_writes_file(tmp_path):
    sc_path = _write_json(tmp_path / "subsystems.json",
                          [_clean_subsystem_contract("usb_sub")])
    text, code = svc.execute_verb(
        "snapshot", root=tmp_path, subsystem_contracts_path=sc_path, as_json=True)
    assert code == 1  # PARTIAL: topology/resource/command registries all absent
    parsed = json.loads(text)
    assert parsed["written_to"]
    assert Path(parsed["written_to"]).is_file()


def test_execute_verb_no_inputs_exit_code_2(tmp_path):
    text, code = svc.execute_verb("assemble", root=tmp_path)
    assert code == 2


def test_execute_verb_unknown_verb(tmp_path):
    text, code = svc.execute_verb("bogus", root=tmp_path)
    assert code == 2
    assert "unknown" in text


def test_execute_verb_bad_json_file_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(svc.SystemVerificationContractError):
        svc.execute_verb("assemble", root=tmp_path, topology_path=str(bad))


def test_execute_verb_missing_file_raises(tmp_path):
    with pytest.raises(svc.SystemVerificationContractError):
        svc.execute_verb("assemble", root=tmp_path,
                         topology_path=str(tmp_path / "nope.json"))


def test_real_cli_subprocess(tmp_path):
    sc_path = _write_json(tmp_path / "subsystems.json",
                          [_clean_subsystem_contract("usb_sub")])
    topo_path = _write_json(tmp_path / "topology.json", _clean_topology())
    rr_path = _write_json(tmp_path / "resource_registry.json", _clean_resource_registry())
    cr_path = _write_json(tmp_path / "command_registry.json", _clean_command_registry())

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_verification_contract", "assemble",
         "--root", str(tmp_path),
         "--subsystem-contracts", sc_path, "--topology", topo_path,
         "--resource-registry", rr_path, "--command-registry", cr_path, "--json"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["completeness"] == "COMPLETE"


def test_real_cli_subprocess_not_available(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_verification_contract", "assemble",
         "--root", str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert result.returncode == 2, result.stderr


# ---------------------------------------------------------------------------
# Strict file-safety scope: no cross-imports of the four sibling modules
# ---------------------------------------------------------------------------

def test_module_imports_none_of_the_four_forbidden_sibling_modules():
    src = Path(svc.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"subsystem_contract", "system_topology_analysis",
                "system_resource_inventory", "system_command_plan"}
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.rsplit(".", 1)[-1])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.add(node.module.rsplit(".", 1)[-1])
            for alias in node.names:
                imported_names.add(alias.name)
    collision = forbidden & imported_names
    assert not collision, f"forbidden cross-import(s) found: {collision}"
