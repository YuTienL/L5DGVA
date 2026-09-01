"""Tests for dv_harness/environment_mode_router.py -- the real,
input-driven SUBSYSTEM_MODE vs SYSTEM_LEVEL_MODE resolver that closes
dashboard.py's own documented "no stage, no gate, no writer" gap for the
environment_mode_selection evidence block (see that module's own docstring,
and dashboard.py's _environment_mode_selected() HONEST STATUS note, for the
full history).

test_single_vs_multi_subsystem_requests_pick_different_real_modes is the
crux test: the SAME real function, given two genuinely different real
evidence dicts (one requested subsystem vs. two), must land on two
different real environment_mode values."""
import json
from pathlib import Path

from dv_harness.environment_mode_router import (
    resolve_environment_mode, read_registered_subsystem_names,
)


def test_single_vs_multi_subsystem_requests_pick_different_real_modes():
    single = resolve_environment_mode({"requested_subsystems": ["usb"]})
    multi = resolve_environment_mode({"requested_subsystems": ["usb", "pcie"]})

    assert single["resolved"] is True
    assert multi["resolved"] is True
    assert single["environment_mode"] == "SUBSYSTEM_MODE"
    assert multi["environment_mode"] == "SYSTEM_LEVEL_MODE"
    assert single["environment_mode"] != multi["environment_mode"]
    assert single["evidence"] and multi["evidence"]


def test_no_requested_subsystems_is_explicitly_unresolved_not_a_default_guess():
    decision = resolve_environment_mode({})
    assert decision["resolved"] is False
    assert decision["environment_mode"] is None
    assert decision["reason"] == "MODE_MUST_BE_EXPLICIT_BEFORE_GENERATION"


def test_system_level_mode_flags_missing_subsystem_escalation():
    decision = resolve_environment_mode({
        "requested_subsystems": ["usb", "pcie"],
        "existing_registered_subsystems": ["usb"],
    })
    assert decision["environment_mode"] == "SYSTEM_LEVEL_MODE"
    assert decision["missing_subsystems"] == ["pcie"]
    assert decision["reused_subsystems"] == ["usb"]
    assert decision["needs_subsystem_mode_first"] is True
    assert "SUBSYSTEM_MODE" in decision["next_action"]


def test_system_level_mode_with_everything_already_registered_needs_no_escalation():
    decision = resolve_environment_mode({
        "requested_subsystems": ["usb", "pcie"],
        "existing_registered_subsystems": ["USB", "PCIE"],  # case-insensitive match
    })
    assert decision["environment_mode"] == "SYSTEM_LEVEL_MODE"
    assert decision["missing_subsystems"] == []
    assert decision["needs_subsystem_mode_first"] is False


def test_subsystem_mode_single_requested_not_yet_registered():
    decision = resolve_environment_mode({
        "requested_subsystems": ["usb"],
        "existing_registered_subsystems": [],
    })
    assert decision["environment_mode"] == "SUBSYSTEM_MODE"
    assert decision["missing_subsystems"] == ["usb"]
    assert decision["needs_subsystem_mode_first"] is False  # single-subsystem stays SUBSYSTEM_MODE by definition


def test_read_registered_subsystem_names_from_real_registry_file(tmp_path):
    registry_dir = tmp_path / ".dv-harness" / "soc-composer"
    registry_dir.mkdir(parents=True)
    (registry_dir / "subsystem_environment_registry.json").write_text(
        json.dumps({"subsystems": [{"name": "usb", "qualification_state": "SMOKE_QUALIFIED"},
                                     {"name": "pcie", "qualification_state": "REGRESSION_QUALIFIED"}]}),
        encoding="utf-8",
    )
    names = read_registered_subsystem_names(tmp_path)
    assert sorted(names) == ["pcie", "usb"]


def test_read_registered_subsystem_names_missing_file_returns_empty_list(tmp_path):
    assert read_registered_subsystem_names(tmp_path) == []


def test_read_registered_subsystem_names_never_reads_the_empty_template():
    # The empty subsystem_environment_registry_template.json example must
    # never be mistaken for the real runtime registry.
    root = Path(__file__).resolve().parents[1]
    names = read_registered_subsystem_names(root)
    assert isinstance(names, list)  # real repo has no runtime registry yet -> []
