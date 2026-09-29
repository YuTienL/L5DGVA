"""Tests for dv_harness.uvm_generator.run_profile: schema validation and the
small query helpers other modules build on."""
from __future__ import annotations

import json

import pytest

from dv_harness.uvm_generator.run_profile import (
    RunProfileValidationError,
    check_constraints,
    find_param,
    load_run_profile,
    new_empty_profile,
    save_run_profile,
    validate_run_profile,
)


def _minimal_valid_profile() -> dict:
    profile = new_empty_profile("makefile", "sim/scripts/Makefile", "USB", "usb_")
    profile["runtime_params"].append({"name": "PATTERN", "type": "string", "default": "smoke"})
    profile["compile_time_params"].append(
        {"name": "SPEED", "type": "enum", "default": "ss_capable", "enum": ["usb20", "gen1", "gen2"]}
    )
    profile["constraints"].append(
        {
            "id": "enum_speed",
            "kind": "enum_membership",
            "params": ["SPEED"],
            "message": "SPEED is invalid. Use usb20, gen1 or gen2",
        }
    )
    profile["targets"].append({"name": "compile", "params": ["SPEED"], "requires_rebuild": True})
    return profile


def test_new_empty_profile_is_schema_valid():
    validate_run_profile(_minimal_valid_profile())


def test_missing_required_top_level_field_is_rejected():
    profile = _minimal_valid_profile()
    del profile["targets"]
    with pytest.raises(RunProfileValidationError):
        validate_run_profile(profile)


def test_unknown_top_level_field_is_rejected():
    profile = _minimal_valid_profile()
    profile["totally_made_up_field"] = 1
    with pytest.raises(RunProfileValidationError):
        validate_run_profile(profile)


def test_bad_source_kind_is_rejected():
    profile = _minimal_valid_profile()
    profile["source"]["kind"] = "excel_sheet"
    with pytest.raises(RunProfileValidationError):
        validate_run_profile(profile)


def test_save_and_load_round_trip(tmp_path):
    profile = _minimal_valid_profile()
    path = tmp_path / "run_profile.json"
    save_run_profile(profile, path)
    loaded = load_run_profile(path)
    assert loaded == profile


def test_save_rejects_invalid_profile_before_writing(tmp_path):
    profile = _minimal_valid_profile()
    profile["source"]["kind"] = "not_a_real_kind"
    path = tmp_path / "run_profile.json"
    with pytest.raises(RunProfileValidationError):
        save_run_profile(profile, path)
    assert not path.exists()


def test_load_rejects_invalid_profile_already_on_disk(tmp_path):
    profile = _minimal_valid_profile()
    profile["source"]["kind"] = "not_a_real_kind"
    path = tmp_path / "run_profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(RunProfileValidationError):
        load_run_profile(path)


def test_find_param_locates_across_both_buckets():
    profile = _minimal_valid_profile()
    assert find_param(profile, "SPEED")["name"] == "SPEED"
    assert find_param(profile, "PATTERN")["name"] == "PATTERN"
    assert find_param(profile, "DOES_NOT_EXIST") is None


def test_check_constraints_flags_out_of_enum_value():
    profile = _minimal_valid_profile()
    violations = check_constraints(profile, {"SPEED": "gen5"})
    assert len(violations) == 1
    assert "gen5" in violations[0]
    assert "SPEED is invalid" in violations[0]


def test_check_constraints_accepts_in_enum_value():
    profile = _minimal_valid_profile()
    assert check_constraints(profile, {"SPEED": "gen1"}) == []


def test_check_constraints_skips_params_not_present_in_values():
    profile = _minimal_valid_profile()
    # PATTERN has no enum constraint at all; SPEED constraint is skipped
    # because SPEED itself is not among the values being checked.
    assert check_constraints(profile, {"PATTERN": "anything"}) == []
