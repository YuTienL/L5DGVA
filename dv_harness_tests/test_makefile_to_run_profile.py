"""Tests for makefile_to_run_profile against the REAL generic template
Makefile (dv_harness/uvm_generator/templates/sim_scripts/Makefile) -- not a
synthetic fixture. That file is itself a real, chip-genericized copy of the
USB_UVM_Handoff proving-ground Makefile (see CLAUDE.md's Makefile/
sim-scripts migration note), so extracting against it and asserting on the
concrete real variable names, enum values, and plusarg mappings is the same
"trace against the real string, don't guess" discipline this whole tool
exists to enforce elsewhere in the harness.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dv_harness.uvm_generator.makefile_to_run_profile import extract_run_profile
from dv_harness.uvm_generator.run_profile import (
    RunProfileValidationError,
    find_param,
    validate_run_profile,
)

_TEMPLATE_MAKEFILE = (
    Path(__file__).resolve().parents[1]
    / "dv_harness"
    / "uvm_generator"
    / "templates"
    / "sim_scripts"
    / "Makefile"
)


@pytest.fixture(scope="module")
def profile() -> dict:
    assert _TEMPLATE_MAKEFILE.is_file(), "template Makefile moved -- update this test's path"
    return extract_run_profile(_TEMPLATE_MAKEFILE, target_ip="USB", ip_prefix="usb_")


def test_extracted_profile_is_schema_valid(profile):
    validate_run_profile(profile)  # raises on failure


def test_source_records_real_path_and_hash(profile):
    assert profile["source"]["kind"] == "makefile"
    assert profile["source"]["content_sha256"]
    assert len(profile["source"]["content_sha256"]) == 64


def test_target_identity(profile):
    assert profile["target"] == {"target_ip": "USB", "ip_prefix": "usb_"}


def test_required_paths_include_the_four_ifndef_roots(profile):
    names = {p["name"] for p in profile["required_paths"]}
    for real_required in ("VIP_HOME", "VCS_HOME", "UVM_HOME"):
        assert real_required in names
        entry = next(p for p in profile["required_paths"] if p["name"] == real_required)
        assert entry["required"] is True

    # DUT_ROOT_PATH is required via a separate ifeq($(strip ...)) guard, not
    # ifndef, and has an empty default -- the extractor's fallback rule
    # (default in (None, "")) must still catch it.
    dut_root = next(p for p in profile["required_paths"] if p["name"] == "DUT_ROOT_PATH")
    assert dut_root["required"] is True

    # UVM_ROOT_PATH/SIM_ROOT_PATH are assigned on INDENTED lines inside an
    # ifneq/else block -- regression guard for the leading-whitespace bug
    # found and fixed while building this extractor.
    assert "UVM_ROOT_PATH" in names
    assert "SIM_ROOT_PATH" in names


def test_compile_time_params_include_real_dut_spec_knobs(profile):
    names = {p["name"] for p in profile["compile_time_params"]}
    assert {"SPEED", "SPEED0", "SPEED1", "PORTS", "PHY_SIM"} <= names
    # None of these may leak into runtime_params -- they require a rebuild.
    runtime_names = {p["name"] for p in profile["runtime_params"]}
    assert runtime_names.isdisjoint({"SPEED", "SPEED0", "SPEED1", "PORTS", "PHY_SIM"})


def test_runtime_params_include_real_pattern_selection_knobs(profile):
    names = {p["name"] for p in profile["runtime_params"]}
    assert {"PATTERN", "TEST", "SEED", "WAVE", "VERB", "VERB_LEVEL", "VERB_COMP", "TOTAL_RUNTIME"} <= names


def test_speed_enum_matches_real_makefile_guard(profile):
    speed = find_param(profile, "SPEED")
    assert speed["type"] == "enum"
    assert speed["enum"] == ["usb20", "usb20fs", "gen1", "gen2", "ss_capable"]
    assert speed["default"] == "ss_capable"


def test_ports_enum_matches_real_makefile_guard(profile):
    ports = find_param(profile, "PORTS")
    assert ports["type"] == "enum"
    assert set(ports["enum"]) == {"0", "1", "both"}


def test_real_plusarg_bindings_are_derived_from_run_flags_not_guessed(profile):
    # These come from the real RUN_FLAGS := +PATTERN=$(PATTERN) ...
    # +UVM_TESTNAME=$(TEST) ... block -- NOT a hardcoded UVM convention
    # assumption. A generator that assumed +UVM_TESTNAME= for every project
    # without checking would be exactly the "guessed command contract"
    # failure mode this tool exists to prevent.
    assert find_param(profile, "PATTERN")["plusarg"] == "+PATTERN="
    assert find_param(profile, "TEST")["plusarg"] == "+UVM_TESTNAME="
    assert find_param(profile, "VERB")["plusarg"] == "+UVM_VERBOSITY="
    assert find_param(profile, "SEED")["plusarg"] == "+ntb_random_seed="


def test_retired_knobs_constraint_present_and_complete(profile):
    retired = next(c for c in profile["constraints"] if c["kind"] == "retired")
    assert "VIP_TUCH_US" in retired["params"]
    assert "VIP_SS_TIMERS" in retired["params"]
    assert len(retired["params"]) >= 10  # real Makefile lists 11


def test_real_phony_targets_are_all_present(profile):
    names = {t["name"] for t in profile["targets"]}
    for real_target in ("compile", "sim", "regress", "check", "help", "clean", "distclean", "list_patterns"):
        assert real_target in names


def test_sim_target_carries_its_real_params(profile):
    sim = next(t for t in profile["targets"] if t["name"] == "sim")
    assert set(sim["params"]) == {
        "PATTERN", "TEST", "SEED", "WAVE", "VERB", "VERB_LEVEL", "VERB_COMP", "TOTAL_RUNTIME",
    }


def test_compile_target_requires_rebuild_and_carries_dut_spec_params(profile):
    compile_t = next(t for t in profile["targets"] if t["name"] == "compile")
    assert compile_t["requires_rebuild"] is True
    assert set(compile_t["params"]) == {"SPEED", "SPEED0", "SPEED1", "PORTS", "PHY_SIM"}


def test_lsf_block_matches_real_defaults(profile):
    assert profile["lsf"]["enabled_by"] == "LSF"
    assert profile["lsf"]["ncore_var"] == "LSF_NCORE"
    assert profile["lsf"]["ncore_default"] == 8


def test_pattern_registry_points_at_the_real_registry_file(profile):
    assert profile["pattern_registry"]["path"] == "tb/patterns/pattern_list.txt"
    assert profile["pattern_registry"]["selector_param"] == "PATTERN"


def test_extraction_is_deterministic(profile):
    again = extract_run_profile(_TEMPLATE_MAKEFILE, target_ip="USB", ip_prefix="usb_")
    assert again == profile
