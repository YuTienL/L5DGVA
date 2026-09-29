"""The two SYSTEM_LEVEL gates that decide whether a composed system-level
environment is allowed to exist now run the REAL cross-subsystem analysis, not
only a shape check over the agent's own JSON.

WHAT WAS WRONG (re-verified with grep before this file was written, 2026-09-05,
not taken from an older report):

  * `grep -rln dv_harness tools/verification_flow/system_level_*.py` matched
    NOTHING. All eleven system_level_* gate scripts were pure JSON-shape checks
    over agent-self-attested evidence text.
  * `system_level_resource_contention_gate.py` was nine lines: it required an
    arbitration policy only for a scenario whose `resources` intersected the
    agent's OWN `shared_resources` list, so a hand-typed
    `"shared_resources": []` passed unconditionally.
  * `uvm_generator/soc_environment_composer.py` imported only `.generator`, so
    `compose_soc_environment()` composed blind to every cross-subsystem
    finding.

Meanwhile `dv_harness/system_resource_inventory.py`'s SYS-9..SYS-14 chain
really does detect two ACTIVE agents driving one physical interface -- it was
just unreachable from anything that decides a verdict.

Every test below runs the REAL gate scripts as subprocesses and the REAL
analysis over REAL synthetic environments on disk. Nothing is mocked, and no
gate verdict is stubbed.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import connectivity as conn
from dv_harness import env_manifest
from dv_harness import system_resource_inventory as sri
from dv_harness.uvm_generator import soc_environment_composer as sec

ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "tools" / "verification_flow"

SHARED_CPU_BIND = "chip.soc.cpu_axi_m"

COMMANDS = """\
initial
begin
  `GMODEL.GLOBAL_INIT;
  `CPUWRITE4B(32'h1400_0000, 32'h1);
  `CPUREAD4B (32'h1400_0004, i);
  $finish;
end
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _matrix_row(active_passive: str) -> dict:
    """One connectivity-matrix row in the real MATRIX_COLUMNS shape, for an
    AXI master agent bound to the SHARED SoC CPU port."""
    return {
        "dut_instance": SHARED_CPU_BIND, "interface": "axi_m", "direction": "input",
        "role": conn.determine_role_from_port_direction("output"),
        "vip_type": "svt_axi_master_agent", "count": 1,
        "active_passive": active_passive, "bind_target": SHARED_CPU_BIND,
        "tier": conn.BindTier.T1_ALREADY_DECIDED.value, "protocol": "AXI4",
        "fabric_side_role": conn.FABRIC_SIDE_MASTER_INTERFACE,
    }


def _subsystem_env(tmp_path: Path, name: str, *, active: bool) -> Path:
    """A synthetic subsystem environment complete enough for SYS-1 to classify
    it EXISTS_READY and for SYS-9 to inventory its resources: a real
    schema-valid env.manifest.json written by the REAL env_manifest generator,
    a real-shaped connectivity matrix, a command.txt, and the readiness
    artifacts subsystem_discovery.probe_environment_artifacts() looks for."""
    env = tmp_path / "generated" / name.lower()
    (env / ".dv-harness").mkdir(parents=True, exist_ok=True)
    _write(env / "command.txt", COMMANDS)
    for rel in ("rtl/dut_core.sv", "env/synth_env.sv", "env/synth_agent.sv",
                "env/synth_scoreboard.sv", "vip/svt_synth_vip.sv", "Makefile",
                "filelist.f", "test/synth_test.sv", "seq/synth_seq.sv",
                "tb/tb_top.sv", "cfg/synth_config.sv", "cfg/clock_reset_map.json",
                "logs/sim.log", "regression.list", "docs/readme.md"):
        _write(env / rel, "// synthetic fixture, empty on purpose\n")

    vip_dump = _write(env / "vip_dump.json", json.dumps({
        "schema_version": "1.0",
        "vip_instances": [{"instance_path": SHARED_CPU_BIND,
                           "vip_type": "svt_axi_master_agent",
                           "config_fields": {"data_width": "64"}}]}))
    soc_map = _write(env / "soc_arch_map.json", json.dumps({
        "schema_version": "1.0",
        "address_map": [{"name": "CTRL_BLOCK", "base_address": "0x14000000",
                         "size_bytes": 4096, "bus": "AXI4"}],
        "clocks": [{"name": "core_clk", "frequency_mhz": 100}],
        "resets": [{"name": "core_rst_n", "active_level": "low", "clock": "core_clk"}]}))
    env_manifest.generate_and_write(
        env / ".dv-harness" / "env.manifest.json",
        vip_config_dump_path=vip_dump, soc_arch_map_path=soc_map)
    _write(env / ".dv-harness" / "connectivity_matrix.json", json.dumps({
        "columns": conn.MATRIX_COLUMNS,
        "rows": [_matrix_row("active" if active else "passive")]}))
    return env


def _registry_entry(name: str, env: Path, sha: str) -> dict:
    """The six fields subsystem_environment_registration_gate.py validates
    before a real entry is ever persisted."""
    return {"name": name,
            "environment_manifest": str(env / ".dv-harness" / "env.manifest.json"),
            "release_sha": sha, "qualification_state": "REGRESSION_QUALIFIED",
            "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}


def _project(tmp_path: Path, *, b_active: bool):
    """A project root with two registered, discoverable subsystems. With
    b_active=True both subsystems drive the SAME SoC CPU AXI master port
    ACTIVELY -- a genuine SYS-12 DRIVER_CONFLICT. With b_active=False the
    second one is passive, so there is no conflict."""
    from dv_harness import subsystem_discovery as sd

    a = _subsystem_env(tmp_path, "SUBSYS_A", active=True)
    b = _subsystem_env(tmp_path, "SUBSYS_B", active=b_active)
    entries = [_registry_entry("SUBSYS_A", a, "aaa111"),
               _registry_entry("SUBSYS_B", b, "bbb222")]
    _write(tmp_path / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json",
           json.dumps({"subsystems": entries}))
    _write(sd.candidate_sources_path(tmp_path), json.dumps({"candidates": [
        {"name": "SUBSYS_A", "protocol": "SYNTH_A", "environment_path": str(a)},
        {"name": "SUBSYS_B", "protocol": "SYNTH_B", "environment_path": str(b)}]}))
    return entries


def _run_gate(script: str, flag: str, payload: dict, project_root: Path):
    """Run the REAL gate script as a subprocess, exactly the way
    gates.run_gate() does: the payload in a JSON temp file, CWD set to the
    project root, DV_HARNESS_PACKAGE_ROOT pointing at the real package."""
    import os
    import tempfile
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, tmp)
    tmp.close()
    try:
        proc = subprocess.run(
            [sys.executable, str(GATES / script), flag, tmp.name],
            cwd=str(project_root), capture_output=True, text=True, timeout=120,
            env={**os.environ, "DV_HARNESS_PACKAGE_ROOT": str(ROOT)})
    finally:
        Path(tmp.name).unlink()
    return proc.returncode, json.loads((proc.stdout or "").strip() or "{}")


# ============================================================================
# The real analysis really does find the conflict these fixtures encode
# ============================================================================

def test_the_fixture_encodes_a_real_track_b_driver_conflict(tmp_path):
    """Precondition for every gate test below: the REAL SYS-9..SYS-14 chain,
    reached through the REAL root-based front door, must stop automatic
    integration for these two subsystems. If this ever stops being true the
    gate tests would pass vacuously."""
    _project(tmp_path, b_active=True)
    findings = sri.real_cross_subsystem_findings(tmp_path)
    assert findings["status"] == sri.CROSSCHECK_AVAILABLE, findings
    assert findings["subsystems"] == ["SUBSYS_A", "SUBSYS_B"]
    assert findings["driver_conflicts"] >= 1
    assert findings["automatic_integration_allowed"] is False
    assert findings["stopped_resource_ids"]
    # SYS-12's preferred model is carried as text for a HUMAN, and nothing
    # anywhere picked a winner between the two drivers.
    assert "SYSTEM SHARED AGENT" in findings["preferred_model"]


def test_a_passive_second_driver_is_not_a_conflict(tmp_path):
    """The negative control: the same two subsystems on the same bind target,
    with the second one PASSIVE, must not be reported as blocked -- otherwise
    the FAILs below would be an artifact of the fixture, not of the rule."""
    _project(tmp_path, b_active=False)
    findings = sri.real_cross_subsystem_findings(tmp_path)
    assert findings["status"] == sri.CROSSCHECK_AVAILABLE, findings
    assert findings["automatic_integration_allowed"] is True


def test_an_over_budget_analysis_reports_timed_out_not_clear(tmp_path):
    """gates.run_gate() kills a gate subprocess at 30s and does NOT catch the
    resulting TimeoutExpired -- an unbounded analysis inside a gate would turn
    a stage evaluation into a crash. An impossible budget must therefore yield
    an explicit ANALYSIS_TIMED_OUT that the cross-checks treat as SKIPPED, and
    must never be mistaken for a clean result."""
    _project(tmp_path, b_active=True)
    findings = sri.real_cross_subsystem_findings(tmp_path, budget_seconds=0.001)
    assert findings["status"] == sri.CROSSCHECK_UNAVAILABLE
    assert findings["reason"] == "ANALYSIS_TIMED_OUT"
    for crosscheck in (sri.crosscheck_declared_contention_plan({}, findings),
                       sri.crosscheck_declared_composition({}, findings)):
        assert crosscheck["status"] == sri.CROSSCHECK_SKIPPED
        assert crosscheck["reason"] == "ANALYSIS_TIMED_OUT"


def test_both_gates_bound_the_analysis_to_the_gate_timeout_budget():
    """Drift guard: neither gate may call the analysis unbounded."""
    assert sri.GATE_CROSSCHECK_BUDGET_SECONDS < 30
    for script in ("system_level_resource_contention_gate.py",
                   "system_level_composition_gate.py"):
        body = (GATES / script).read_text(encoding="utf-8")
        assert "budget_seconds=sri.GATE_CROSSCHECK_BUDGET_SECONDS" in body, script


def test_findings_are_unavailable_not_clear_when_there_is_nothing_to_analyze(tmp_path):
    """An empty project must report an explicit UNAVAILABLE, never a silent
    'clear' that would let a cross-check rubber-stamp a declaration."""
    findings = sri.real_cross_subsystem_findings(tmp_path)
    assert findings["status"] == sri.CROSSCHECK_UNAVAILABLE
    assert findings["reason"] == "FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE"


# ============================================================================
# THE HEADLINE TEST: a hand-typed "all clear" is rejected by the real gate
# ============================================================================

def test_hand_typed_all_clear_is_rejected_by_the_real_contention_gate(tmp_path):
    """The exact failure this whole change exists to close.

    The agent declares no shared resources at all and a scenario needing no
    contention policy. Layer 1 (the original nine-line shape check) is
    satisfied by that block and would have printed PASS. The real Track-B
    analysis over the SAME two subsystems finds two ACTIVE AXI masters on one
    SoC port, so the gate must FAIL instead."""
    _project(tmp_path, b_active=True)
    all_clear = {
        "shared_resources": [],
        "scenarios": [{"scenario_id": "SC1", "resources": ["DDR"],
                       "arbitration_or_contention_policy": "",
                       "contention_testcase_ids": []}],
    }
    code, out = _run_gate("system_level_resource_contention_gate.py", "--plan",
                          all_clear, tmp_path)
    assert code != 0, out
    assert out["status"] == "FAIL"
    assert out["reason"] == "ACTIVE_DRIVER_CONFLICT_UNRESOLVED"
    crosscheck = out["cross_subsystem_crosscheck"]
    assert crosscheck["human_arbitration_required"] is True
    assert crosscheck["stopped_resource_ids"]
    assert crosscheck["subsystems"] == ["SUBSYS_A", "SUBSYS_B"]


def test_the_same_all_clear_block_passes_layer_one_alone(tmp_path):
    """Proves the FAIL above comes from the new cross-check and not from a
    tightened shape check: with NO project to analyze, the identical block
    passes and the gate says so explicitly."""
    all_clear = {
        "shared_resources": [],
        "scenarios": [{"scenario_id": "SC1", "resources": ["DDR"],
                       "arbitration_or_contention_policy": "",
                       "contention_testcase_ids": []}],
    }
    code, out = _run_gate("system_level_resource_contention_gate.py", "--plan",
                          all_clear, tmp_path)
    assert code == 0, out
    assert out["status"] == "PASS"
    assert out["cross_subsystem_crosscheck"]["status"] == sri.CROSSCHECK_SKIPPED
    assert out["cross_subsystem_crosscheck"]["reason"] == "FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE"


def test_declaring_a_contention_policy_does_not_buy_past_a_driver_conflict(tmp_path):
    """A conflict is not something an agent can type its way out of: even a
    fully-populated plan with a policy and contention tests still stops at
    BLOCKED, because ownership of the contended port is a human decision."""
    _project(tmp_path, b_active=True)
    thorough = {
        "shared_resources": ["chip.soc.cpu_axi_m"],
        "scenarios": [{"scenario_id": "SC1", "resources": ["chip.soc.cpu_axi_m"],
                       "arbitration_or_contention_policy": "round-robin",
                       "contention_testcase_ids": ["tc_contend_1"]}],
    }
    code, out = _run_gate("system_level_resource_contention_gate.py", "--plan",
                          thorough, tmp_path)
    assert code != 0
    assert out["reason"] == "ACTIVE_DRIVER_CONFLICT_UNRESOLVED"


def test_contention_gate_passes_when_the_real_analysis_agrees(tmp_path):
    """No conflict in the real analysis, and the plan is shape-valid -> PASS,
    with the real findings attached rather than an unexplained PASS."""
    _project(tmp_path, b_active=False)
    plan = {"shared_resources": ["chip.soc.cpu_axi_m"],
            "scenarios": [{"scenario_id": "SC1", "resources": ["chip.soc.cpu_axi_m"],
                           "arbitration_or_contention_policy": "round-robin",
                           "contention_testcase_ids": ["tc_contend_1"]}]}
    code, out = _run_gate("system_level_resource_contention_gate.py", "--plan",
                          plan, tmp_path)
    assert code == 0, out
    assert out["status"] == "PASS"
    assert out["cross_subsystem_crosscheck"]["status"] == sri.CROSSCHECK_PASS
    assert out["cross_subsystem_crosscheck"]["subsystems"] == ["SUBSYS_A", "SUBSYS_B"]


def test_layer_one_shape_failures_are_unchanged(tmp_path):
    """The original checks and their exit codes still stand exactly as before,
    and still fire BEFORE the cross-check runs."""
    code, out = _run_gate("system_level_resource_contention_gate.py", "--plan", {
        "shared_resources": ["DDR"],
        "scenarios": [{"scenario_id": "SC1", "resources": ["DDR"]}]}, tmp_path)
    assert (code, out["reason"]) == (2, "SHARED_RESOURCE_WITHOUT_CONTENTION_POLICY")

    code, out = _run_gate("system_level_resource_contention_gate.py", "--plan", {
        "shared_resources": ["DDR"],
        "scenarios": [{"scenario_id": "SC1", "resources": ["DDR"],
                       "arbitration_or_contention_policy": "fixed priority"}]}, tmp_path)
    assert (code, out["reason"]) == (3, "NO_CONTENTION_TESTS")


# ============================================================================
# The composition gate
# ============================================================================

def _composition_block(entries, scenario_subsystems=None):
    names = [e["name"] for e in entries]
    return {"selected_subsystems": entries,
            "system_level_scenarios": [
                {"scenario_id": "SC1",
                 "participating_subsystems": scenario_subsystems or names}]}


def test_hand_typed_compatibility_pass_is_rejected_by_the_real_composition_gate(tmp_path):
    """Both subsystems are declared interface_compatibility=PASS and
    clock_reset_compatibility=PASS -- strings the agent typed itself. The real
    analysis says the set is not composable, so the gate must FAIL."""
    entries = _project(tmp_path, b_active=True)
    code, out = _run_gate("system_level_composition_gate.py", "--composition",
                          _composition_block(entries), tmp_path)
    assert code != 0, out
    assert out["status"] == "FAIL"
    assert out["reason"] == "ACTIVE_DRIVER_CONFLICT_UNRESOLVED"
    crosscheck = out["cross_subsystem_crosscheck"]
    assert crosscheck["human_arbitration_required"] is True
    assert crosscheck["declared_subsystems"] == ["SUBSYS_A", "SUBSYS_B"]
    assert crosscheck["blocking_decisions"]


def test_composition_gate_passes_when_the_real_analysis_agrees(tmp_path):
    entries = _project(tmp_path, b_active=False)
    code, out = _run_gate("system_level_composition_gate.py", "--composition",
                          _composition_block(entries), tmp_path)
    assert code == 0, out
    assert out["status"] == "READY_FOR_SYSTEM_LEVEL"
    assert out["cross_subsystem_crosscheck"]["status"] == sri.CROSSCHECK_PASS


def test_composition_gate_layer_one_checks_are_unchanged(tmp_path):
    """The original identity/qualification/scenario checks and their exit codes
    still stand, and still run before the cross-check."""
    entries = _project(tmp_path, b_active=True)
    code, out = _run_gate("system_level_composition_gate.py", "--composition",
                          {"selected_subsystems": entries[:1]}, tmp_path)
    assert (code, out["reason"]) == (2, "NEED_AT_LEAST_TWO_SUBSYSTEMS")

    broken = [dict(entries[0]), dict(entries[1])]
    broken[1]["clock_reset_compatibility"] = "FAIL"
    code, out = _run_gate("system_level_composition_gate.py", "--composition",
                          _composition_block(broken), tmp_path)
    assert (code, out["reason"]) == (6, "SUBSYSTEM_COMPATIBILITY_FAIL")

    code, out = _run_gate("system_level_composition_gate.py", "--composition",
                          {"selected_subsystems": entries,
                           "system_level_scenarios": []}, tmp_path)
    assert (code, out["reason"]) == (7, "NO_SYSTEM_LEVEL_SCENARIOS")


def test_a_conflict_between_subsystems_this_composition_excludes_does_not_block_it(tmp_path):
    """The composition gate analyzes the subsystems the composition NAMES, so
    a conflict elsewhere in the registry cannot block an unrelated
    composition. Here only one subsystem is named, which is fewer than two to
    compare -- the cross-check reports SKIPPED with that reason rather than
    inheriting the registry-wide conflict."""
    entries = _project(tmp_path, b_active=True)
    duplicated = [dict(entries[0]), dict(entries[0], name="SUBSYS_A")]
    code, out = _run_gate("system_level_composition_gate.py", "--composition",
                          _composition_block(duplicated), tmp_path)
    # Layer 1 rejects the duplicate name before the cross-check is reached --
    # which is itself the point: the cross-check never widens the set.
    assert (code, out["reason"]) == (4, "DUPLICATE_SUBSYSTEM")


# ============================================================================
# The composer no longer composes blind
# ============================================================================

def test_composer_refuses_to_compose_over_an_unresolved_driver_conflict(tmp_path):
    entries = _project(tmp_path, b_active=True)
    with pytest.raises(sec.CrossSubsystemIntegrationBlockedError) as excinfo:
        sec.compose_soc_environment(entries, {"soc_name": "demo_soc"}, tmp_path)
    assert excinfo.value.reason == "CROSS_SUBSYSTEM_INTEGRATION_BLOCKED"
    assert excinfo.value.detail["human_arbitration_required"] is True
    assert excinfo.value.detail["stopped_resource_ids"]
    # Refusing left nothing behind: no half-composed environment on disk.
    assert not (tmp_path / "generated" / "soc_composition").exists()


def test_composer_records_the_real_findings_when_it_does_compose(tmp_path):
    entries = _project(tmp_path, b_active=False)
    files = sec.compose_soc_environment(entries, {"soc_name": "demo_soc"}, tmp_path)
    record = json.loads(files["soc_composition_manifest.json"])
    findings = record["cross_subsystem_analysis"]
    assert findings["status"] == sri.CROSSCHECK_AVAILABLE
    assert findings["subsystems"] == ["SUBSYS_A", "SUBSYS_B"]
    assert findings["automatic_integration_allowed"] is True
    assert "soc_tb_top.sv" in files


def test_composing_without_a_root_is_unchanged_and_says_it_was_not_consulted(tmp_path):
    """Every pre-2026-09-05 caller passed no root. That path still composes
    identically -- and states that the analysis was not consulted rather than
    implying a clean one."""
    entries = _project(tmp_path, b_active=True)
    files = sec.compose_soc_environment(entries, {"soc_name": "demo_soc"})
    record = json.loads(files["soc_composition_manifest.json"])
    assert record["cross_subsystem_analysis"] == {
        "status": "NOT_CONSULTED", "reason": "NO_PROJECT_ROOT_SUPPLIED"}
    assert "soc_tb_top.sv" in files


# ============================================================================
# Drift guards: the wire itself
# ============================================================================

def test_both_gate_scripts_really_import_the_real_analysis_module(tmp_path):
    """The literal grep that was empty before this change. A future edit that
    reverts either gate to a pure shape check fails here."""
    for script in ("system_level_resource_contention_gate.py",
                   "system_level_composition_gate.py"):
        body = (GATES / script).read_text(encoding="utf-8")
        assert "from dv_harness import system_resource_inventory" in body, script
        assert "real_cross_subsystem_findings" in body, script


def test_the_composer_consults_the_real_analysis(tmp_path):
    body = (ROOT / "dv_harness" / "uvm_generator" / "soc_environment_composer.py").read_text(
        encoding="utf-8")
    assert "real_cross_subsystem_findings" in body
    assert "CrossSubsystemIntegrationBlockedError" in body


def test_both_real_composer_call_sites_pass_their_project_root():
    engine = (ROOT / "dv_harness" / "engine.py").read_text(encoding="utf-8")
    assert "compose_soc_environment(subsystems, registry, self.root)" in engine
    assert "SOC_COMPOSITION_BLOCKED_PENDING_HUMAN_ARBITRATION" in engine
    create = (ROOT / "dv_harness" / "uvm_generator" / "create_environment.py").read_text(
        encoding="utf-8")
    assert "compose_soc_environment(subsystems, request, root)" in create


def test_nothing_here_arbitrates_a_driver_conflict():
    """The hard constraint: detection is wired into the gates; ARBITRATION
    (choosing which subsystem owns the contended interface) stays a human
    decision. No cross-check function may return a winner."""
    body = (ROOT / "dv_harness" / "system_resource_inventory.py").read_text(encoding="utf-8")
    start = body.index("def real_cross_subsystem_findings")
    end = body.index("# Reporting")
    section = body[start:end]
    for forbidden in ("resolve_conflict", "winner", "arbitrate(", "auto_resolve"):
        assert forbidden not in section, forbidden
    assert "human_arbitration_required" in section
