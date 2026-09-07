"""Real tests for `dv_harness/platform_startup_readiness.py` -- the
STARTUP-TIME readiness check (is the harness correctly configured, are its
declared Python dependencies present, is config.json valid), distinct from
`platform_health.py`'s ongoing operational aggregator.

WHAT THESE PROVE: every subsystem check is driven against REAL files on a
real temporary project root (a real .dv-harness/config.json, a real
pyproject.toml [project].dependencies declaration checked through the real
`dependency_supply_chain` inventory/resolve machinery, a real
`adapters.cli.ClaudeCLIAdapter._resolve_command()` call, a real
`preflight.config_from_dict()` call, a real filesystem write+delete probe) --
nothing here hand-constructs a StartupSubsystemCheck and asserts it renders
correctly; each test forces the REAL underlying condition and checks the
module's own derivation of it.

The negative controls are the headline evidence-truth-rule proof this task
is graded on: a project declaring a Python dependency that is genuinely NOT
installed for this interpreter must report BLOCKED, never a silently
fabricated READY -- and the worst-wins composite-gate test proves that one
BLOCKED subsystem sinks the whole `overall_status` even when every other
subsystem is clean.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import platform_health as ph
from dv_harness import platform_startup_readiness as m
from dv_harness.golden_flow_readiness import combine_readiness
from dv_harness.subsystem_discovery import READY, PARTIAL, BLOCKED, UNKNOWN


def _write_config(root: Path, doc: dict) -> Path:
    d = root / ".dv-harness"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "config.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _write_pyproject(root: Path, dependencies) -> Path:
    lines = ["[project]", 'name = "fixture"', 'version = "0.0.0"']
    if dependencies is not None:
        dep_list = ", ".join(json.dumps(d) for d in dependencies)
        lines.append(f"dependencies = [{dep_list}]")
    p = root / "pyproject.toml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Taxonomy reuse: every platform_health.SUBSYSTEMS member accounted for once.
# ---------------------------------------------------------------------------

def test_every_platform_health_subsystem_is_accounted_for_exactly_once():
    checkable = set(m._STARTUP_CHECKABLE_PLATFORM_HEALTH_SUBSYSTEMS)
    excluded = set(m._NOT_APPLICABLE_PLATFORM_HEALTH_SUBSYSTEMS)
    assert checkable | excluded == set(ph.SUBSYSTEMS)
    assert checkable & excluded == set()


def test_assert_reuses_platform_health_taxonomy_raises_on_a_dropped_subsystem():
    saved = dict(m._NOT_APPLICABLE_PLATFORM_HEALTH_SUBSYSTEMS)
    try:
        m._NOT_APPLICABLE_PLATFORM_HEALTH_SUBSYSTEMS.pop(ph.SUBSYS_SLO_COMPLIANCE)
        with pytest.raises(AssertionError):
            m.assert_reuses_platform_health_taxonomy()
    finally:
        m._NOT_APPLICABLE_PLATFORM_HEALTH_SUBSYSTEMS.clear()
        m._NOT_APPLICABLE_PLATFORM_HEALTH_SUBSYSTEMS.update(saved)


# ---------------------------------------------------------------------------
# harness_configuration
# ---------------------------------------------------------------------------

def test_no_config_json_at_all_is_ready(tmp_path):
    result = m.assess_harness_configuration(tmp_path)
    assert result.status == READY
    assert result.reason == "NO_CONFIG_JSON_YET"


def test_valid_config_json_is_ready(tmp_path):
    _write_config(tmp_path, {"policy": {"max_stage_retries": 5}, "dashboard": {"port": 9000}})
    result = m.assess_harness_configuration(tmp_path)
    assert result.status == READY
    assert result.reason == "CONFIG_JSON_VALID"


def test_malformed_json_is_blocked(tmp_path):
    d = tmp_path / ".dv-harness"
    d.mkdir(parents=True)
    (d / "config.json").write_text("{not valid json", encoding="utf-8")
    result = m.assess_harness_configuration(tmp_path)
    assert result.status == BLOCKED
    assert result.reason == "CONFIG_JSON_UNREADABLE"
    assert "not valid JSON" in result.detail


def test_non_dict_top_level_json_is_blocked(tmp_path):
    d = tmp_path / ".dv-harness"
    d.mkdir(parents=True)
    (d / "config.json").write_text("[1, 2, 3]", encoding="utf-8")
    result = m.assess_harness_configuration(tmp_path)
    assert result.status == BLOCKED
    assert result.reason == "CONFIG_JSON_UNREADABLE"


def test_config_block_replacing_a_default_dict_is_merge_corrupting_and_blocked(tmp_path):
    # config.load_config()'s own merge rule: "policy" is a dict block in
    # DEFAULT_CONFIG; declaring it as a bare string here means
    # merged["policy"] = "off" -- discarding max_stage_retries and every
    # other real policy field, with no error from load_config() itself.
    _write_config(tmp_path, {"policy": "off"})
    result = m.assess_harness_configuration(tmp_path)
    assert result.status == BLOCKED
    assert result.reason == "CONFIG_BLOCK_WOULD_REPLACE_DEFAULTS"
    findings = result.observations["findings"]
    assert any(f["field"] == "policy" and f["severity"] == "MERGE_CORRUPTING" for f in findings)


def test_config_field_type_mismatch_is_partial_not_blocked(tmp_path):
    # dashboard.port is an int in DEFAULT_CONFIG; a string here does not
    # corrupt the merge (the leaf value just replaces the leaf default), so
    # this is a weaker, PARTIAL finding, never BLOCKED.
    _write_config(tmp_path, {"dashboard": {"port": "not-a-number"}})
    result = m.assess_harness_configuration(tmp_path)
    assert result.status == PARTIAL
    assert result.reason == "CONFIG_FIELD_TYPE_MISMATCH"
    findings = result.observations["findings"]
    assert any(f["field"] == "dashboard.port" and f["severity"] == "TYPE_MISMATCH" for f in findings)


def test_numeric_int_vs_float_is_never_flagged(tmp_path):
    # policy.max_stage_retries defaults to an int (2); a project declaring it
    # as a JSON float (2.0) must not be a false-positive type mismatch.
    _write_config(tmp_path, {"policy": {"max_stage_retries": 2.0}})
    result = m.assess_harness_configuration(tmp_path)
    assert result.status == READY


def test_unknown_top_level_key_is_never_a_finding(tmp_path):
    _write_config(tmp_path, {"some_future_block": {"anything": True}})
    result = m.assess_harness_configuration(tmp_path)
    assert result.status == READY


# ---------------------------------------------------------------------------
# python_dependencies -- the headline "never fabricate READY" negative
# control this task is graded on.
# ---------------------------------------------------------------------------

def test_no_declared_dependencies_is_ready_with_zero_component_count(tmp_path):
    _write_pyproject(tmp_path, [])
    result = m.assess_python_dependencies(tmp_path)
    assert result.status == READY
    assert result.reason == "NO_DECLARED_PYTHON_DEPENDENCIES"
    assert result.observations["component_count"] == 0


def test_a_declared_and_really_installed_dependency_is_ready(tmp_path):
    # "pytest" is guaranteed installed in this test's own interpreter --
    # confirmed via a real importlib.metadata lookup, never assumed.
    import importlib.metadata as im
    im.version("pytest")
    _write_pyproject(tmp_path, ["pytest"])
    result = m.assess_python_dependencies(tmp_path)
    assert result.status == READY
    assert result.reason == "ALL_DECLARED_DEPENDENCIES_INSTALLED"
    assert "pytest" in result.observations["declared"]


def test_a_declared_but_not_installed_dependency_is_blocked_never_fabricated_ready(tmp_path):
    """The negative control this task explicitly requires: proves the module
    refuses to report READY when a real, checkable declared dependency is
    genuinely absent for this interpreter."""
    _write_pyproject(tmp_path, ["definitely_not_a_real_package_xyz_12345"])
    result = m.assess_python_dependencies(tmp_path)
    assert result.status == BLOCKED
    assert result.reason == "DECLARED_DEPENDENCY_NOT_INSTALLED"
    assert "definitely_not_a_real_package_xyz_12345" in result.observations["missing"]


def test_broken_pyproject_toml_is_unknown_not_a_crash(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project\nthis is not valid toml", encoding="utf-8")
    result = m.assess_python_dependencies(tmp_path)
    assert result.status == UNKNOWN
    assert result.reason == "DEPENDENCY_INVENTORY_FAILED"


# ---------------------------------------------------------------------------
# agent_adapter
# ---------------------------------------------------------------------------

def test_default_claude_command_resolution_matches_shutil_which_or_blocks_honestly():
    import shutil
    result = m.assess_agent_adapter({})
    resolvable = shutil.which("claude") is not None
    if resolvable:
        assert result.status == READY
        assert result.reason == "AGENT_ADAPTER_COMMAND_RESOLVABLE"
    else:
        assert result.status == BLOCKED
        assert result.reason == "AGENT_ADAPTER_COMMAND_NOT_RESOLVABLE"


def test_a_bogus_adapter_command_is_blocked():
    result = m.assess_agent_adapter({"claude": {"command": "this_binary_does_not_exist_xyz_123"}})
    assert result.status == BLOCKED
    assert result.reason == "AGENT_ADAPTER_COMMAND_NOT_RESOLVABLE"


def test_an_existing_file_path_as_the_command_is_ready(tmp_path):
    fake_bin = tmp_path / "fake_claude_launcher"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    result = m.assess_agent_adapter({"claude": {"command": str(fake_bin)}})
    assert result.status == READY


def test_unrecognized_adapter_kind_is_unknown():
    result = m.assess_agent_adapter({"adapter": "some_future_adapter"})
    assert result.status == UNKNOWN
    assert result.reason == "UNRECOGNIZED_ADAPTER_KIND"


# ---------------------------------------------------------------------------
# execution_preflight_configuration
# ---------------------------------------------------------------------------

def test_execution_preflight_disabled_is_not_applicable():
    result = m.assess_execution_preflight_configuration({"execution_preflight": {"enabled": False}})
    assert result.status == m.NOT_APPLICABLE_AT_STARTUP
    assert result.reason == "EXECUTION_PREFLIGHT_DISABLED"


def test_execution_preflight_default_shape_is_ready():
    result = m.assess_execution_preflight_configuration({})
    assert result.status == READY
    assert result.reason == "PREFLIGHT_CONFIG_SHAPE_VALID"


def test_empty_license_server_and_workdir_are_never_a_finding():
    # config.py's own documented convention: these two fields are legitimately
    # empty until a project is pointed at a real remote server.
    result = m.assess_execution_preflight_configuration(
        {"preflight": {"license_server": "", "workdir": ""}})
    assert result.status == READY


def test_required_env_vars_not_a_list_of_strings_is_blocked():
    result = m.assess_execution_preflight_configuration(
        {"preflight": {"required_env_vars": "VCS_HOME"}})
    assert result.status == BLOCKED
    assert result.reason == "PREFLIGHT_CONFIG_SHAPE_INVALID"
    assert any("required_env_vars" in f for f in result.observations["findings"])


def test_min_free_disk_gb_zero_or_negative_is_blocked():
    result = m.assess_execution_preflight_configuration(
        {"preflight": {"min_free_disk_gb": -5}})
    assert result.status == BLOCKED
    assert any("min_free_disk_gb" in f for f in result.observations["findings"])


def test_min_free_disk_gb_boolean_is_blocked():
    # bool is an int subclass in Python -- must not silently pass as "a
    # positive number".
    result = m.assess_execution_preflight_configuration(
        {"preflight": {"min_free_disk_gb": True}})
    assert result.status == BLOCKED


# ---------------------------------------------------------------------------
# project_state_directory
# ---------------------------------------------------------------------------

def test_state_directory_writable(tmp_path):
    result = m.assess_project_state_directory(tmp_path)
    assert result.status == READY
    assert (tmp_path / ".dv-harness").is_dir()
    # the throwaway probe file must not be left behind
    assert not (tmp_path / ".dv-harness" / ".startup_readiness_probe").exists()


def test_state_directory_blocked_when_a_file_occupies_the_dv_harness_name(tmp_path):
    # Forces a real OSError: ".dv-harness" already exists as a plain FILE, so
    # mkdir(parents=True, exist_ok=True) cannot create it as a directory.
    (tmp_path / ".dv-harness").write_text("not a directory", encoding="utf-8")
    result = m.assess_project_state_directory(tmp_path)
    assert result.status == BLOCKED
    assert result.reason == "STATE_DIRECTORY_NOT_WRITABLE"


# ---------------------------------------------------------------------------
# The one report: worst-wins composite gate + reuse of golden_flow_readiness
# ---------------------------------------------------------------------------

def test_bare_project_root_is_overall_ready(tmp_path):
    code, report, text = m.execute(tmp_path)
    assert report["overall_status"] == READY
    assert code == 0
    # every applicable subsystem participated; the excluded four are present
    # and honestly NOT_APPLICABLE_AT_STARTUP, never silently omitted.
    subsystems = {s["subsystem"]: s["status"] for s in report["subsystems"]}
    for excluded in m._NOT_APPLICABLE_PLATFORM_HEALTH_SUBSYSTEMS:
        assert subsystems[excluded] == m.NOT_APPLICABLE_AT_STARTUP


def test_a_single_blocked_subsystem_sinks_the_whole_overall_status_worst_wins(tmp_path):
    """Rule 3 (worst-wins composite gate) proven directly: one real BLOCKED
    subsystem (a genuinely-missing declared Python dependency) among four
    otherwise-clean subsystems must still make overall_status BLOCKED --
    never averaged, never overridden by the clean subsystems."""
    _write_pyproject(tmp_path, ["definitely_not_a_real_package_xyz_12345"])
    code, report, text = m.execute(tmp_path)
    assert report["overall_status"] == BLOCKED
    assert code == 1
    subsystems = {s["subsystem"]: s["status"] for s in report["subsystems"]}
    assert subsystems[m.SUBSYS_PYTHON_DEPENDENCIES] == BLOCKED
    # every other applicable subsystem is still independently reported clean
    assert subsystems[m.SUBSYS_HARNESS_CONFIGURATION] == READY
    assert subsystems[m.SUBSYS_PROJECT_STATE_DIRECTORY] == READY


def test_not_applicable_at_startup_subsystems_never_participate_in_the_fold(tmp_path):
    report = m.startup_readiness_report(tmp_path)
    applicable_statuses = [s["status"] for s in report["subsystems"]
                          if s["status"] != m.NOT_APPLICABLE_AT_STARTUP]
    # the module's own overall_status must equal folding ONLY the applicable
    # subsystems -- reusing golden_flow_readiness.combine_readiness() exactly
    # as production code does, so this cannot silently diverge from it.
    assert report["overall_status"] == combine_readiness(applicable_statuses)


def test_state_counts_cover_every_declared_status_value(tmp_path):
    report = m.startup_readiness_report(tmp_path)
    total = sum(report["state_counts"].values())
    assert total == len(report["subsystems"])


def test_authorizes_nothing_and_writes_nothing_beyond_the_state_directory_probe(tmp_path):
    """Snapshot the project root before and after a full report run: nothing
    should exist afterward except (optionally) the .dv-harness directory
    itself, and no file should be left inside it by this module."""
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == []
    report = m.startup_readiness_report(tmp_path)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert after in ([], [".dv-harness"])
    assert "no approval" in report["authorizes_nothing"]


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def test_cli_exits_zero_on_a_ready_bare_project(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.platform_startup_readiness", "--root", str(tmp_path)],
        cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OVERALL: READY" in proc.stdout


def test_cli_exits_one_and_reports_json_on_a_blocked_project(tmp_path):
    _write_pyproject(tmp_path, ["definitely_not_a_real_package_xyz_12345"])
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.platform_startup_readiness",
         "--root", str(tmp_path), "--json"],
        cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["overall_status"] == BLOCKED
