"""Tests for dv_harness/uvm_generator/pattern_registry_generator.py (9-policy
audit / USB regen-fidelity plan Phase 1 item 2, 2026-08-29)."""
from __future__ import annotations

import pytest

from dv_harness.uvm_generator.pattern_registry_generator import (
    build_registry, compute_suite_names, emit_registry_txt,
    emit_pattern_pool_svh, emit_makefile_fragment, RegistryError,
)

PATTERNS = [
    {"name": "usb2_enum", "suite": "enumeration", "dir": "tb/patterns/enumeration"},
    {"name": "usb3_gen1_enum", "suite": "enumeration", "dir": "tb/patterns/enumeration"},
    {"name": "usb_dual_port", "suite": "transfer", "dir": "tb/patterns/transfer"},
]


def test_compute_suite_names_is_sorted_set_never_hardcoded():
    assert compute_suite_names(PATTERNS) == ["enumeration", "transfer"]


def test_build_registry_happy_path():
    reg = build_registry(PATTERNS)
    assert [p["name"] for p in reg["patterns"]] == ["usb2_enum", "usb3_gen1_enum", "usb_dual_port"]
    assert reg["suite_names"] == ["enumeration", "transfer"]
    assert reg["declared_suites"] == ["enumeration", "transfer"]


def test_build_registry_rejects_duplicate_pattern_name():
    dup = PATTERNS + [{"name": "usb2_enum", "suite": "link", "dir": "tb/patterns/link"}]
    with pytest.raises(RegistryError) as exc:
        build_registry(dup)
    assert exc.value.reason == "DUPLICATE_PATTERN_NAME"


def test_build_registry_rejects_missing_suite_or_dir():
    with pytest.raises(RegistryError) as exc:
        build_registry([{"name": "x", "dir": "tb/patterns/x"}])
    assert exc.value.reason == "MISSING_SUITE_DIR"

    with pytest.raises(RegistryError) as exc:
        build_registry([{"name": "x", "suite": "link"}])
    assert exc.value.reason == "MISSING_SUITE_DIR"


def test_build_registry_rejects_malformed_entry_without_name():
    with pytest.raises(RegistryError) as exc:
        build_registry([{"suite": "link", "dir": "tb/patterns/link"}])
    assert exc.value.reason == "MALFORMED_PATTERN_ENTRY"


def test_build_registry_rejects_declared_suite_with_zero_patterns():
    # BUG regression: a taxonomy migration must never leave a declared suite
    # silently matching zero real patterns.
    with pytest.raises(RegistryError) as exc:
        build_registry(PATTERNS, declared_suites=["enumeration", "transfer", "power"])
    assert exc.value.reason == "SUITE_WITH_ZERO_PATTERNS"
    assert exc.value.detail["suites"] == ["power"]


def test_emit_registry_txt_one_line_per_pattern_sorted():
    reg = build_registry(PATTERNS)
    txt = emit_registry_txt(reg)
    lines = txt.strip("\n").split("\n")
    assert lines == [
        "usb2_enum enumeration tb/patterns/enumeration/usb2_enum.txt",
        "usb3_gen1_enum enumeration tb/patterns/enumeration/usb3_gen1_enum.txt",
        "usb_dual_port transfer tb/patterns/transfer/usb_dual_port.txt",
    ]


def test_emit_pattern_pool_svh_has_a_case_arm_per_pattern():
    reg = build_registry(PATTERNS)
    svh = emit_pattern_pool_svh(reg)
    for p in PATTERNS:
        assert f'"{p["name"]}":' in svh
    assert "default:" in svh and "uvm_fatal" in svh


def test_emit_makefile_fragment_has_add_remove_list_targets_with_backup():
    frag = emit_makefile_fragment("tb/patterns/pattern_list.txt")
    assert "list_patterns:" in frag and "add_pattern:" in frag and "remove_pattern:" in frag
    assert ".bak" in frag
