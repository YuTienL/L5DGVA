"""Tests for `dv_harness/subsys_compat_matrix.py`: the Subsystem
Compatibility Matrix (section 233) -- a rollup, over the REAL
`system_resource_inventory.py` SYS-9..14 cross-subsystem analysis and the
REAL `ip_ownership_conflict.py` per-subsystem self-check, never a hand-typed
matrix and never a re-implementation of either module's own judgment.

The two-subsystem, real-conflict fixture is IMPORTED (never copied) from
`test_system_level_track_b_gate_crosscheck.py`, which CLAUDE.md's own
"Generation Readiness Matrix" section records as already reused this way by
another module -- one real fixture, one place its shape can drift, not a
second hand-typed copy of it here. This file adds one more real fixture
variant of its own (independent, non-overlapping resources) for the plain
COMPATIBLE case that fixture does not produce.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import connectivity as conn
from dv_harness import env_manifest
from dv_harness import ip_ownership_conflict as ioc
from dv_harness import subsys_compat_matrix as scm
from dv_harness import system_resource_inventory as sri
from dv_harness_tests import test_system_level_track_b_gate_crosscheck as fixture

ROOT = Path(__file__).resolve().parents[1]


# ===========================================================================
# A third, INDEPENDENT-resources fixture variant -- neither subsystem's
# resources share a bind target, a VIP type, a protocol or an address range,
# so SYS-9..14's own comparator (compare_resources()) finds zero agreeing
# signals and produces NO relationship between them at all. This is what
# proves this module's own COMPATIBLE status is a real, checked "nothing
# found" and not a default.
# ===========================================================================

def _independent_subsystem_env(tmp_path: Path, name: str, *, bind_target: str,
                               vip_type: str, base_address: str, clock_name: str) -> Path:
    env = tmp_path / "generated" / name.lower()
    (env / ".dv-harness").mkdir(parents=True, exist_ok=True)
    fixture._write(env / "command.txt", fixture.COMMANDS)
    for rel in ("rtl/dut_core.sv", "env/synth_env.sv", "env/synth_agent.sv",
                "env/synth_scoreboard.sv", "vip/svt_synth_vip.sv", "Makefile",
                "filelist.f", "test/synth_test.sv", "seq/synth_seq.sv",
                "tb/tb_top.sv", "cfg/synth_config.sv", "cfg/clock_reset_map.json",
                "logs/sim.log", "regression.list", "docs/readme.md"):
        fixture._write(env / rel, "// synthetic fixture, empty on purpose\n")

    vip_dump = fixture._write(env / "vip_dump.json", json.dumps({
        "schema_version": "1.0",
        "vip_instances": [{"instance_path": bind_target, "vip_type": vip_type,
                           "config_fields": {"data_width": "64"}}]}))
    soc_map = fixture._write(env / "soc_arch_map.json", json.dumps({
        "schema_version": "1.0",
        "address_map": [{"name": f"{name}_BLOCK", "base_address": base_address,
                         "size_bytes": 4096, "bus": vip_type.upper()}],
        "clocks": [{"name": clock_name, "frequency_mhz": 100}],
        "resets": [{"name": f"{clock_name}_rst_n", "active_level": "low",
                    "clock": clock_name}]}))
    env_manifest.generate_and_write(
        env / ".dv-harness" / "env.manifest.json",
        vip_config_dump_path=vip_dump, soc_arch_map_path=soc_map)
    fixture._write(env / ".dv-harness" / "connectivity_matrix.json", json.dumps({
        "columns": conn.MATRIX_COLUMNS,
        "rows": [{
            "dut_instance": bind_target, "interface": "if0", "direction": "input",
            "role": conn.determine_role_from_port_direction("output"),
            "vip_type": vip_type, "count": 1, "active_passive": "active",
            "bind_target": bind_target, "tier": conn.BindTier.T1_ALREADY_DECIDED.value,
            "protocol": vip_type.upper(), "fabric_side_role": conn.FABRIC_SIDE_MASTER_INTERFACE,
        }]}))
    return env


def _independent_project(tmp_path: Path):
    """Two subsystems whose resources share nothing -- different bind
    targets, different VIP types, different non-overlapping addresses,
    different clocks -- so the real SYS-9..14 analysis finds zero
    cross-subsystem relationships between them."""
    from dv_harness import subsystem_discovery as sd
    a = _independent_subsystem_env(
        tmp_path, "SUBSYS_C", bind_target="chip.soc.usb0", vip_type="svt_usb_agent",
        base_address="0x20000000", clock_name="usb_clk")
    b = _independent_subsystem_env(
        tmp_path, "SUBSYS_D", bind_target="chip.soc.pcie0", vip_type="svt_pcie_agent",
        base_address="0x30000000", clock_name="pcie_clk")
    entries = [fixture._registry_entry("SUBSYS_C", a, "ccc333"),
               fixture._registry_entry("SUBSYS_D", b, "ddd444")]
    fixture._write(tmp_path / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json",
                   json.dumps({"subsystems": entries}))
    fixture._write(sd.candidate_sources_path(tmp_path), json.dumps({"candidates": [
        {"name": "SUBSYS_C", "protocol": "SYNTH_C", "environment_path": str(a)},
        {"name": "SUBSYS_D", "protocol": "SYNTH_D", "environment_path": str(b)}]}))
    return entries


# ===========================================================================
# Precondition checks -- the fixtures really do (and really don't) produce
# what each test below assumes, exactly the discipline
# test_system_level_track_b_gate_crosscheck.py applies to its own fixture.
# ===========================================================================

def test_the_independent_fixture_really_has_no_cross_subsystem_relationship(tmp_path):
    _independent_project(tmp_path)
    findings = sri.real_cross_subsystem_findings(tmp_path)
    assert findings["status"] == sri.CROSSCHECK_AVAILABLE, findings
    assert findings["driver_conflicts"] == 0
    assert findings["shared_relationships"] == []
    assert findings["automatic_integration_allowed"] is True


# ===========================================================================
# CROSS_SUBSYSTEM_DRIVER_CONFLICT: the real SYS-12 stop rule, per pair
# ===========================================================================

def test_cross_subsystem_driver_conflict_blocks_the_pair(tmp_path):
    fixture._project(tmp_path, b_active=True)
    matrix = scm.build_subsystem_compatibility_matrix(tmp_path)
    assert matrix["status"] == scm.MATRIX_BLOCKED, matrix
    assert matrix["subsystems"] == ["SUBSYS_A", "SUBSYS_B"]
    assert len(matrix["pairs"]) == 1
    pair = matrix["pairs"][0]
    assert pair["subsystem_a"] == "SUBSYS_A" and pair["subsystem_b"] == "SUBSYS_B"
    assert pair["status"] == scm.PAIR_CONFLICT
    assert pair["known_compatible"] is False
    assert pair["preferred_resolution_model"] == sri.SYS12_PREFERRED_MODEL
    assert any(r["relationship"] == sri.REL_DRIVER_CONFLICT for r in pair["relationships"])
    assert matrix["counts"][scm.PAIR_CONFLICT] == 1
    assert matrix["known_compatible_pairs"] == []


# ===========================================================================
# SHARED_RESOURCE_REQUIRES_REVIEW: a real physical match, not active/active
# ===========================================================================

def test_passive_second_driver_is_shared_resource_review_not_compatible(tmp_path):
    """The negative control for the driver-conflict test above (same pair,
    same bind target, B now passive): SYS-12 does not stop it, but a real
    REL_SAME_PHYSICAL relationship still exists, so this must NOT collapse
    into COMPATIBLE."""
    fixture._project(tmp_path, b_active=False)
    matrix = scm.build_subsystem_compatibility_matrix(tmp_path)
    assert matrix["status"] == scm.MATRIX_NEEDS_REVIEW, matrix
    pair = matrix["pairs"][0]
    assert pair["status"] == scm.PAIR_SHARED_RESOURCE_REVIEW
    assert pair["known_compatible"] is False
    assert any(r["relationship"] == sri.REL_SAME_PHYSICAL for r in pair["relationships"])
    assert matrix["counts"][scm.PAIR_SHARED_RESOURCE_REVIEW] == 1


# ===========================================================================
# SUBSYSTEM_SELF_CONFLICT_BLOCKS_COMPOSITION: ip_ownership_conflict.py's own
# real CONFLICT, folded in, and proven to OUTRANK a milder cross-subsystem
# finding on the SAME pair.
# ===========================================================================

def test_self_conflict_outranks_shared_resource_review(tmp_path):
    """SUBSYS_A carries its own real IP-level VIP-vs-legacy-BFM conflict
    (a legacy driver declared ACTIVE on the same port a real VIP instance is
    ALSO resolved ACTIVE on, via the real connectivity_rows fixture row) --
    fed straight to `ip_ownership_conflict.analyze_ip_ownership_conflict()`,
    never re-implemented here. The base project (b_active=False) would
    otherwise only produce SHARED_RESOURCE_REQUIRES_REVIEW for this pair
    (proven above); the self-conflict must win."""
    fixture._project(tmp_path, b_active=False)
    legacy = [{"port_id": fixture.SHARED_CPU_BIND, "driver_name": "legacy_axi_bfm",
               "active_passive": "active", "evidence": "test fixture"}]
    rows = [fixture._matrix_row("active")]
    ip_ownership_inputs = {"SUBSYS_A": {"legacy_bfm_declarations": legacy,
                                        "connectivity_rows": rows}}

    # Precondition: the real ip_ownership_conflict check on SUBSYS_A alone
    # really does report CONFLICT from this exact input.
    manifest = env_manifest.load_env_manifest(
        tmp_path / "generated" / "subsys_a" / ".dv-harness" / "env.manifest.json")
    real_self_check = ioc.analyze_ip_ownership_conflict(
        manifest, legacy_bfm_declarations=legacy, connectivity_rows=rows)
    assert real_self_check["status"] == ioc.STATUS_CONFLICT, real_self_check

    matrix = scm.build_subsystem_compatibility_matrix(
        tmp_path, ip_ownership_inputs=ip_ownership_inputs)
    assert matrix["status"] == scm.MATRIX_BLOCKED, matrix
    pair = matrix["pairs"][0]
    assert pair["status"] == scm.PAIR_SELF_CONFLICT
    assert pair["known_compatible"] is False
    assert "SUBSYS_A" in pair["blocking_self_checks"]
    assert matrix["self_conflict_checks"]["SUBSYS_A"]["status"] == ioc.STATUS_CONFLICT
    # SUBSYS_B was never asked for a self-check.
    assert matrix["self_conflict_checks"]["SUBSYS_B"]["status"] == "NOT_REQUESTED"


# ===========================================================================
# UNKNOWN: a real ip_ownership_conflict.STATUS_UNKNOWN (undetermined
# ownership) must never be silently promoted past a pair's real evidence, and
# must outrank a milder SHARED_RESOURCE_REQUIRES_REVIEW finding on that pair.
# ===========================================================================

def test_unresolved_self_check_forces_pair_unknown_not_review(tmp_path):
    fixture._project(tmp_path, b_active=False)
    legacy = [{"port_id": fixture.SHARED_CPU_BIND, "driver_name": "legacy_axi_bfm",
               "active_passive": "active", "evidence": "test fixture"}]
    # No connectivity_rows supplied -- the real module cannot resolve the
    # VIP's own active/passive state, so it reports STATUS_UNKNOWN.
    ip_ownership_inputs = {"SUBSYS_B": {"legacy_bfm_declarations": legacy}}

    manifest = env_manifest.load_env_manifest(
        tmp_path / "generated" / "subsys_b" / ".dv-harness" / "env.manifest.json")
    real_self_check = ioc.analyze_ip_ownership_conflict(manifest, legacy_bfm_declarations=legacy)
    assert real_self_check["status"] == ioc.STATUS_UNKNOWN, real_self_check

    matrix = scm.build_subsystem_compatibility_matrix(
        tmp_path, ip_ownership_inputs=ip_ownership_inputs)
    assert matrix["status"] == scm.MATRIX_INCOMPLETE, matrix
    pair = matrix["pairs"][0]
    assert pair["status"] == scm.PAIR_UNKNOWN
    assert pair["known_compatible"] is False
    assert "SUBSYS_B" in pair["unresolved_self_checks"]


# ===========================================================================
# COMPATIBLE: real evidence checked, nothing found -- known_compatible: True
# ===========================================================================

def test_independent_resources_are_compatible(tmp_path):
    _independent_project(tmp_path)
    matrix = scm.build_subsystem_compatibility_matrix(tmp_path)
    assert matrix["status"] == scm.MATRIX_ALL_COMPATIBLE, matrix
    pair = matrix["pairs"][0]
    assert pair["subsystem_a"] == "SUBSYS_C" and pair["subsystem_b"] == "SUBSYS_D"
    assert pair["status"] == scm.PAIR_COMPATIBLE
    assert pair["known_compatible"] is True
    # A real REL_INDEPENDENT relationship is expected and reported (the
    # comparator found agreeing "role"/etc. signals but disagreeing logical
    # identity signals) -- it must be carried through for transparency
    # without affecting the COMPATIBLE verdict, since INDEPENDENT_RESOURCE is
    # positive evidence the two are different resources, not a conflict.
    assert all(r["relationship"] == sri.REL_INDEPENDENT for r in pair["relationships"])
    assert matrix["known_compatible_pairs"] == [["SUBSYS_C", "SUBSYS_D"]]
    # Neither subsystem was asked for an IP-ownership self-check, and that
    # alone must never force UNKNOWN.
    assert matrix["self_conflict_checks"]["SUBSYS_C"]["status"] == "NOT_REQUESTED"
    assert matrix["self_conflict_checks"]["SUBSYS_D"]["status"] == "NOT_REQUESTED"


# ===========================================================================
# NEGATIVE CONTROL (rule 5): absent evidence must never fabricate an answer.
# ===========================================================================

def test_no_registered_subsystems_reports_not_available_never_a_fabricated_matrix(tmp_path):
    """An empty project (no registry, no candidates -- nothing SYS-1 could
    even select) must never report COMPATIBLE, or any confirmed pair status.
    Mirrors real_cross_subsystem_findings()'s own identical negative
    control."""
    matrix = scm.build_subsystem_compatibility_matrix(tmp_path)
    assert matrix["status"] == scm.MATRIX_NOT_AVAILABLE
    assert matrix["reason"] == "FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE"
    assert matrix["pairs"] == []
    assert matrix["known_compatible_pairs"] == []


def test_a_single_selected_subsystem_is_also_not_available(tmp_path):
    fixture._project(tmp_path, b_active=True)
    matrix = scm.build_subsystem_compatibility_matrix(tmp_path, selected=["SUBSYS_A"])
    assert matrix["status"] == scm.MATRIX_NOT_AVAILABLE
    assert matrix["reason"] == "FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE"


def test_an_unselected_environment_not_on_disk_is_not_available(tmp_path):
    """SYS-1's own refusal to analyze an environment that is not really on
    disk must not be bypassed -- naming a subsystem this project never
    registered must produce NOT_AVAILABLE, never a guess."""
    fixture._project(tmp_path, b_active=True)
    matrix = scm.build_subsystem_compatibility_matrix(
        tmp_path, selected=["SUBSYS_A", "SUBSYS_NEVER_REGISTERED"])
    assert matrix["status"] == scm.MATRIX_NOT_AVAILABLE
    for pair in matrix["pairs"]:
        assert pair["status"] == scm.PAIR_UNKNOWN
        assert pair["known_compatible"] is False


# ===========================================================================
# classify_pair() as a pure function -- worst-wins precedence over synthetic
# (but real-shaped) relationship/self-check records, independent of any
# filesystem fixture.
# ===========================================================================

def test_classify_pair_precedence_conflict_beats_shared_review():
    relationships = [
        {"resource_a": "A::x::y", "resource_b": "B::x::y", "subsystem_a": "A",
         "subsystem_b": "B", "relationship": sri.REL_DRIVER_CONFLICT, "reason": "both active"},
        {"resource_a": "A::p::q", "resource_b": "B::p::q", "subsystem_a": "A",
         "subsystem_b": "B", "relationship": sri.REL_SAME_PHYSICAL, "reason": "same bind"},
    ]
    result = scm.classify_pair("A", "B", relationships, {})
    assert result["status"] == scm.PAIR_CONFLICT
    assert result["known_compatible"] is False


def test_classify_pair_self_conflict_beats_cross_subsystem_conflict():
    relationships = [
        {"resource_a": "A::x::y", "resource_b": "B::x::y", "subsystem_a": "A",
         "subsystem_b": "B", "relationship": sri.REL_DRIVER_CONFLICT, "reason": "both active"},
    ]
    self_checks = {"A": {"status": ioc.STATUS_CONFLICT, "reason": "own VIP/legacy conflict"}}
    result = scm.classify_pair("A", "B", relationships, self_checks)
    assert result["status"] == scm.PAIR_SELF_CONFLICT
    assert result["blocking_self_checks"] == {"A": self_checks["A"]}


def test_classify_pair_ignores_unrelated_pair_relationships():
    """A relationship between A and C must never leak into the A/B pair."""
    relationships = [
        {"resource_a": "A::x::y", "resource_b": "C::x::y", "subsystem_a": "A",
         "subsystem_b": "C", "relationship": sri.REL_DRIVER_CONFLICT, "reason": "unrelated"},
    ]
    result = scm.classify_pair("A", "B", relationships, {})
    assert result["status"] == scm.PAIR_COMPATIBLE
    assert result["relationships"] == []


def test_classify_pair_monitor_only_duplicate_does_not_block():
    relationships = [
        {"resource_a": "A::x::y", "resource_b": "B::x::y", "subsystem_a": "A",
         "subsystem_b": "B", "relationship": sri.REL_MONITOR_ONLY_DUPLICATE,
         "reason": "two passive monitors"},
    ]
    result = scm.classify_pair("A", "B", relationships, {})
    assert result["status"] == scm.PAIR_COMPATIBLE
    assert result["known_compatible"] is True
    assert len(result["relationships"]) == 1


# ===========================================================================
# NOT_REQUESTED vs. no manifest available -- two honestly different reasons
# a self-check did not run, checked directly against
# `evaluate_subsystem_self_check()`.
# ===========================================================================

def test_evaluate_subsystem_self_check_not_requested_when_no_input_supplied():
    result = scm.evaluate_subsystem_self_check("SUBSYS_A", "/some/env.manifest.json", {})
    assert result["status"] == "NOT_REQUESTED"


def test_evaluate_subsystem_self_check_no_manifest_available_when_path_empty():
    result = scm.evaluate_subsystem_self_check(
        "SUBSYS_A", "", {"SUBSYS_A": {"legacy_bfm_declarations": []}})
    assert result["status"] == "NO_MANIFEST_AVAILABLE"


def test_evaluate_subsystem_self_check_uses_a_supplied_manifest_dict_directly(tmp_path):
    manifest = {"vip_config": {"vip_instances": []}, "dut_facts": {}, "env_topology": {},
                "generator": {"tool": "test", "version": "1.0"}}
    result = scm.evaluate_subsystem_self_check(
        "SUBSYS_A", "", {"SUBSYS_A": {"env_manifest": manifest,
                                      "legacy_bfm_declarations": []}})
    # NOT_APPLICABLE (ip_ownership_conflict.py's own honest common case: no
    # legacy declared) proves the real function ran rather than degrading to
    # NO_MANIFEST_AVAILABLE just because no path was given.
    assert result["status"] == ioc.STATUS_NOT_APPLICABLE


# ===========================================================================
# Real CLI subprocess, exercised end to end
# ===========================================================================

def _run_cli(args, cwd):
    return subprocess.run([sys.executable, "-m", "dv_harness.subsys_compat_matrix", *args],
                          cwd=str(ROOT), capture_output=True, text=True, timeout=60)


def test_cli_blocked_exit_code_and_json(tmp_path):
    fixture._project(tmp_path, b_active=True)
    proc = _run_cli(["--root", str(tmp_path), "--json"], ROOT)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == scm.MATRIX_BLOCKED


def test_cli_all_compatible_exit_code(tmp_path):
    _independent_project(tmp_path)
    proc = _run_cli(["--root", str(tmp_path)], ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SUBSYSTEM COMPATIBILITY MATRIX: ALL_KNOWN_COMPATIBLE" in proc.stdout


def test_cli_not_available_exit_code(tmp_path):
    proc = _run_cli(["--root", str(tmp_path)], ROOT)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "NOT_AVAILABLE" in proc.stdout
