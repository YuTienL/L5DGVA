"""Tests for dv_harness/uvm_generator/bind_mechanism_generator.py (9-policy
audit / USB regen-fidelity plan Phase 1 item 3, 2026-08-29)."""
from __future__ import annotations

import pytest

from dv_harness.uvm_generator.bind_mechanism_generator import (
    validate_bind_entries, emit_bind_sv, emit_hook_svh, BindTopologyError,
)

VALID_ENTRY = {
    "target_instance": "chip.core.evt_ctrl",
    "ports": ["irq_evt_reg", "irq_evt_valid"],
    "reason": "irq_evt_reg declared at chip.core.evt_ctrl; the subsystem wrapper only routes it through, not owns it",
}


def test_validate_bind_entries_accepts_well_formed_entries():
    assert validate_bind_entries([VALID_ENTRY]) == [VALID_ENTRY]


def test_validate_bind_entries_rejects_empty_list():
    with pytest.raises(BindTopologyError) as exc:
        validate_bind_entries([])
    assert exc.value.reason == "NO_BIND_ENTRIES"


def test_validate_bind_entries_rejects_missing_target_instance():
    with pytest.raises(BindTopologyError) as exc:
        validate_bind_entries([{"ports": ["a"], "reason": "x"}])
    assert exc.value.reason == "MISSING_BIND_EVIDENCE"
    assert exc.value.detail["field"] == "target_instance"


def test_validate_bind_entries_rejects_empty_ports():
    with pytest.raises(BindTopologyError) as exc:
        validate_bind_entries([{"target_instance": "chip.core.evt_ctrl", "ports": [], "reason": "x"}])
    assert exc.value.reason == "MISSING_BIND_EVIDENCE"
    assert exc.value.detail["field"] == "ports"


def test_validate_bind_entries_rejects_missing_reason():
    # Never a silently-emitted empty bind: a bind target/ports without a
    # stated evidence reason is still a hard failure, not just a warning.
    with pytest.raises(BindTopologyError) as exc:
        validate_bind_entries([{"target_instance": "chip.core.evt_ctrl", "ports": ["a"]}])
    assert exc.value.reason == "MISSING_BIND_EVIDENCE"
    assert exc.value.detail["field"] == "reason"


def test_emit_bind_sv_never_invents_names_beyond_supplied_evidence():
    sv = emit_bind_sv([VALID_ENTRY])
    assert "bind chip.core.evt_ctrl" in sv
    assert ".irq_evt_reg(irq_evt_reg)" in sv
    assert ".irq_evt_valid(irq_evt_valid)" in sv
    assert VALID_ENTRY["reason"] in sv


def test_emit_bind_sv_rejects_invalid_entries_before_emitting_anything():
    with pytest.raises(BindTopologyError):
        emit_bind_sv([{"target_instance": "chip.core.evt_ctrl", "ports": [], "reason": "x"}])


def test_emit_hook_svh_contains_macro_redirect_before_decls_and_run_test():
    svh = emit_hook_svh(
        "usb3_2",
        {"REG_WRITE_TASK": "dv_uvm_reg_write_task"},
        ["dv_uvm_seq_launcher u_seq_launcher();"],
    )
    assert "`define REG_WRITE_TASK dv_uvm_reg_write_task" in svh
    assert "dv_uvm_seq_launcher u_seq_launcher();" in svh
    assert "initial run_test();" in svh
    redirect_pos = svh.index("`define REG_WRITE_TASK")
    decl_pos = svh.index("dv_uvm_seq_launcher u_seq_launcher();")
    run_test_pos = svh.index("initial run_test();")
    assert redirect_pos < decl_pos < run_test_pos
