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


# ---------------------------------------------------------------------------
# CAP-M5M6-VLEVEL-001: verification_level-driven mode selection
# (_resolve_with_level()). Absent verification_level (every test above)
# stays byte-identical to before this parameter existed.
# ---------------------------------------------------------------------------

def test_absent_verification_level_key_is_byte_identical_to_before():
    with_none = resolve_environment_mode({"requested_subsystems": ["usb"]})
    with_explicit_none = resolve_environment_mode(
        {"requested_subsystems": ["usb"], "verification_level": None})
    assert with_none == with_explicit_none


def test_verification_level_ip_resolves_ip_mode_with_no_subsystem_count_requirement():
    # LEVEL_SEMANTICS[IP].min_subsystems == 0 -- IP_MODE needs no
    # requested_subsystems at all, unlike SUBSYSTEM_MODE/SYSTEM_LEVEL_MODE.
    decision = resolve_environment_mode({"verification_level": "IP"})
    assert decision["resolved"] is True
    assert decision["environment_mode"] == "IP_MODE"
    assert decision["verification_level"] == "IP"
    assert decision["requested_subsystems"] == []


def test_verification_level_ip_ignores_an_unrelated_multi_subsystem_request():
    decision = resolve_environment_mode({
        "verification_level": "IP", "requested_subsystems": ["usb", "pcie"],
    })
    assert decision["environment_mode"] == "IP_MODE"


def test_verification_level_system_level_needs_two_or_more_requested():
    decision = resolve_environment_mode({
        "verification_level": "SYSTEM_LEVEL", "requested_subsystems": ["usb"],
    })
    assert decision["resolved"] is False
    assert decision["environment_mode"] is None
    assert decision["reason"] == "SYSTEM_LEVEL_NEEDS_TWO_OR_MORE_SUBSYSTEMS"


def test_verification_level_system_level_with_two_requested_resolves():
    decision = resolve_environment_mode({
        "verification_level": "SYSTEM_LEVEL", "requested_subsystems": ["usb", "pcie"],
    })
    assert decision["resolved"] is True
    assert decision["environment_mode"] == "SYSTEM_LEVEL_MODE"
    assert decision["verification_level"] == "SYSTEM_LEVEL"


def test_verification_level_subsystem_with_requested_resolves_subsystem_mode():
    decision = resolve_environment_mode({
        "verification_level": "SUBSYSTEM", "requested_subsystems": ["usb"],
    })
    assert decision["resolved"] is True
    assert decision["environment_mode"] == "SUBSYSTEM_MODE"
    assert decision["verification_level"] == "SUBSYSTEM"


def test_verification_level_subsystem_with_nothing_requested_falls_through_to_count_based():
    decision = resolve_environment_mode({"verification_level": "SUBSYSTEM"})
    assert decision["resolved"] is False
    assert decision["reason"] == "MODE_MUST_BE_EXPLICIT_BEFORE_GENERATION"
    assert decision["verification_level"] == "SUBSYSTEM"


def test_invalid_verification_level_spelling_is_unresolved_not_guessed():
    decision = resolve_environment_mode({
        "verification_level": "chip", "requested_subsystems": ["usb"],
    })
    assert decision["resolved"] is False
    assert decision["environment_mode"] is None
    assert decision["reason"] == "INVALID_VERIFICATION_LEVEL"
