"""CAP-M5M6-VLEVEL-001: the three official L5 verification levels
(dv_harness/verification_level.py) -- domain vocabulary only.

Adapted from Parent's real, tested `D:\\DV\\Task\\DV_Agent_Harness_L5\\
dv_harness_tests\\test_verification_level.py` (12 tests). The first 5 cases
below (enum/parse_level/semantics) are ported near-verbatim -- they exercise
pure, resolution-engine-agnostic vocabulary that canonical kept unchanged.

Two cases are DELIBERATELY NOT ported, and two are DELIBERATELY REWRITTEN,
both disclosed in `verification_level.py`'s own module docstring:

  - `ask_verification_level()`/`resolve_verification_level()` do not exist
    in canonical (ONE_CANONICAL_FIELD_RESOLUTION_ENGINE: `verification_level`
    resolves through `clarification_service.resolve_or_ask()` instead, the
    same engine protocol/role already use -- see
    `test_m6_c1_golden_path_connectivity.py`'s own verification_level
    families and `test_m5m6_vlevel_001_production_connectivity.py` for that
    coverage). Parent's own 7 ask/resolve-specific tests have no canonical
    equivalent in THIS file.
  - `suggest_level()`'s own default recommendation is intentionally
    different from Parent's: canonical's real, pre-existing precedent
    (`environment_mode_policy.json`'s SUBSYSTEM_MODE examples list PCIe/
    USB/etc. as ONE-protocol builds) means a single protocol suggests
    SUBSYSTEM here, not IP -- so `test_suggest_level_for_zero_or_one_
    protocol_is_subsystem`/`test_suggest_level_for_two_protocols_is_
    system_level` replace Parent's own `..._suggestion_is_only_a_
    recommendation...`/`..._for_two_protocols_is_subsystem` cases with the
    canonical values.
"""
from __future__ import annotations

import pytest

from dv_harness import generation_field_controls
from dv_harness.verification_level import (
    LEVEL_SEMANTICS,
    VerificationLevel,
    parse_level,
    suggest_level,
)


def test_levels_are_exactly_ip_subsystem_system_level():
    assert [l.value for l in VerificationLevel] == ["IP", "SUBSYSTEM", "SYSTEM_LEVEL"]


@pytest.mark.parametrize("text,expected", [
    ("IP", VerificationLevel.IP), ("ip", VerificationLevel.IP),
    ("IP-level", VerificationLevel.IP), ("ip level", VerificationLevel.IP),
    ("SUBSYSTEM", VerificationLevel.SUBSYSTEM), ("subsystem", VerificationLevel.SUBSYSTEM),
    ("SUBSYSTEM_MODE", VerificationLevel.SUBSYSTEM),
    ("SYSTEM_LEVEL", VerificationLevel.SYSTEM_LEVEL), ("system-level", VerificationLevel.SYSTEM_LEVEL),
    ("system level", VerificationLevel.SYSTEM_LEVEL), ("SYSTEM_LEVEL_MODE", VerificationLevel.SYSTEM_LEVEL),
])
def test_parse_level_accepts_the_documented_spellings(text, expected):
    assert parse_level(text) is expected


@pytest.mark.parametrize("text", ["", None, "chip", "IPSUBSYSTEM", "soc-ish"])
def test_parse_level_rejects_everything_else_instead_of_guessing(text):
    assert parse_level(text) is None


def test_each_level_carries_distinct_semantics_so_it_is_not_a_label():
    fields = ("intake_mode", "environment_mode", "topology_model", "min_subsystems")
    assert set(LEVEL_SEMANTICS) == set(VerificationLevel)
    for f in fields:
        values = [getattr(LEVEL_SEMANTICS[l], f) for l in VerificationLevel]
        assert len(set(values)) == len(values), f"{f} must differ per level: {values}"


def test_semantics_match_the_owner_decision():
    ip = LEVEL_SEMANTICS[VerificationLevel.IP]
    sub = LEVEL_SEMANTICS[VerificationLevel.SUBSYSTEM]
    sys_ = LEVEL_SEMANTICS[VerificationLevel.SYSTEM_LEVEL]
    assert ip.environment_mode == "IP_MODE" and ip.intake_mode == "IP" and ip.min_subsystems == 0
    assert sub.environment_mode == "SUBSYSTEM_MODE" and sub.min_subsystems == 1
    assert sys_.environment_mode == "SYSTEM_LEVEL_MODE" and sys_.min_subsystems == 2


def test_suggest_level_for_zero_or_one_protocol_is_subsystem():
    """Canonical's own real precedent (environment_mode_policy.json's
    SUBSYSTEM_MODE examples: PCIe, USB, Ethernet, ... are all one-protocol
    builds) -- deliberately differs from Parent's IP-biased default."""
    assert suggest_level([])["suggested"] is VerificationLevel.SUBSYSTEM
    assert suggest_level(["usb"])["suggested"] is VerificationLevel.SUBSYSTEM


def test_suggest_level_for_two_protocols_is_system_level():
    assert suggest_level(["usb", "pcie"])["suggested"] is VerificationLevel.SYSTEM_LEVEL


def test_suggestion_never_resolves_anything_it_is_a_pure_function():
    """The level is a HUMAN decision (owner ruling D2). suggest_level() must
    stay a pure, side-effect-free recommendation -- never wired as an
    evidence PRODUCER for verification_level_field_control()'s own
    resolution loop (that would silently auto-resolve a human decision from
    a bare protocol-count guess)."""
    before = suggest_level(["usb"])
    after = suggest_level(["usb"])
    assert before == after  # no state, no side effect
    producer_names = {
        p.name for p in generation_field_controls.verification_level_evidence_producers(
            __import__("pathlib").Path("."))
    }
    assert "suggest_level" not in producer_names
    assert producer_names == {"lifecycle_recorded_verification_level"}
