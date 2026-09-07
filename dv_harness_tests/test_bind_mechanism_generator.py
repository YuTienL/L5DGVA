"""Tests for dv_harness/uvm_generator/bind_mechanism_generator.py (9-policy
audit / USB regen-fidelity plan Phase 1 item 3, 2026-08-29)."""
from __future__ import annotations

import pytest

from dv_harness.uvm_generator.bind_mechanism_generator import (
    validate_bind_entries, emit_bind_sv, emit_hook_svh, BindTopologyError,
    validate_apb_bridge_entries, emit_apb_bridge_tasks_sv, ApbBridgeTaskError,
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


# ===========================================================================
# Bind-confidence TIER gate on the real emission path (gap closure
# 2026-09-04). Before this wiring, emit_bind_sv() would happily write a
# naming-heuristic-only (T3) or undecidable (T4) bind into a .sv file.
# ===========================================================================

def _tiered(tier, **over):
    e = dict(VALID_ENTRY)
    e["tier"] = tier
    e.update(over)
    return e


def test_emit_bind_sv_still_accepts_a_legacy_untiered_entry():
    """The existing 3-field contract (used by the real
    examples/.../usb_bind_topology.json) keeps working unchanged."""
    assert "bind chip.core.evt_ctrl" in emit_bind_sv([VALID_ENTRY])


def test_emit_bind_sv_emits_a_t1_or_t2_entry():
    assert "bind chip.core.evt_ctrl" in emit_bind_sv([_tiered("T2_STRUCTURAL_MATCH")])


def test_emit_bind_sv_refuses_an_unconfirmed_t3_entry():
    from dv_harness.connectivity import BindTierError
    with pytest.raises(BindTierError) as exc:
        emit_bind_sv([_tiered("T3_NAMING_HEURISTIC")])
    assert exc.value.reason == "T3_BIND_REQUIRES_HUMAN_CONFIRMATION"


def test_emit_bind_sv_emits_a_t3_entry_once_a_human_confirmed_it():
    from dv_harness.question_queue import HUMAN_DECISION_SOURCE
    sv = emit_bind_sv([_tiered("T3_NAMING_HEURISTIC", human_confirmation={
        "source": HUMAN_DECISION_SOURCE, "confirmed_by": "dv_owner",
        "basis": "confirmed against the RTL hierarchy dump"})])
    assert "bind chip.core.evt_ctrl" in sv


def test_emit_bind_sv_never_emits_a_t4_entry():
    from dv_harness.connectivity import BindTierError
    with pytest.raises(BindTierError) as exc:
        emit_bind_sv([_tiered("T4_UNDECIDABLE")])
    assert exc.value.reason == "T4_BIND_MUST_GO_TO_QUESTION_QUEUE"


def test_emit_bind_sv_require_tier_refuses_an_untiered_entry():
    from dv_harness.connectivity import BindTierError
    with pytest.raises(BindTierError) as exc:
        emit_bind_sv([VALID_ENTRY], require_tier=True)
    assert exc.value.reason == "BIND_ENTRY_MISSING_TIER"


def test_nothing_is_emitted_when_any_entry_in_the_list_is_blocked():
    from dv_harness.connectivity import BindTierError
    with pytest.raises(BindTierError):
        emit_bind_sv([_tiered("T1_ALREADY_DECIDED"), _tiered("T4_UNDECIDABLE")])


# ===========================================================================
# CPUREAD/CPUWRITE bridge-task body generation (gap closure 2026-09-06,
# self_check_list.md #27 / uvm_bridge_task_verification). Before this, the
# only real generated example this repo ships
# (examples/generated_usb_real_evidence_v1/bind/dv_uvm_hook.svh) carried a
# bare TODO_PLACEHOLDER comment where the CPUWRITE1B bridge task body should
# be -- no bridge task body of any kind was ever actually generated,
# raw-pin-level or APB-sequence-calling.
# ===========================================================================

WRITE_ENTRY = {
    "task_name": "dv_uvm_cpuwrite1b",
    "direction": "WRITE",
    "sequencer_path": "`DV_UVM_ENV.virtual_sequencer.apb_seqr",
    "vip_transaction_type": "svt_apb_master_transaction",
    "vip_addr_field": "address",
    "vip_data_field": "data",
    "vip_xact_type_field": "xact_type",
    "vip_write_enum": "svt_apb_master_transaction::WRITE",
    "vip_read_enum": "svt_apb_master_transaction::READ",
    "addr_width": 32,
    "data_width": 8,
    "reason": "CPUWRITE1B redirected here per dv_uvm_hook.svh Hook 1; "
              "apb_seqr is the real svt_apb_master_sequencer field declared "
              "on usb_virtual_sequencer.sv:36 (VIP class reference).",
}

READ_ENTRY = {
    "task_name": "dv_uvm_cpuread1b",
    "direction": "READ",
    "sequencer_path": "`DV_UVM_ENV.virtual_sequencer.apb_seqr",
    "vip_transaction_type": "svt_apb_master_transaction",
    "vip_addr_field": "address",
    "vip_data_field": "data",
    "addr_width": 32,
    "data_width": 8,
    "reason": "CPUREAD1B redirected here per dv_uvm_hook.svh Hook 1; "
              "apb_seqr is the real svt_apb_master_sequencer field declared "
              "on usb_virtual_sequencer.sv:36 (VIP class reference).",
}


def test_validate_apb_bridge_entries_accepts_well_formed_entries():
    assert validate_apb_bridge_entries([WRITE_ENTRY, READ_ENTRY]) == [WRITE_ENTRY, READ_ENTRY]


def test_validate_apb_bridge_entries_rejects_empty_list():
    with pytest.raises(ApbBridgeTaskError) as exc:
        validate_apb_bridge_entries([])
    assert exc.value.reason == "NO_BRIDGE_ENTRIES"


@pytest.mark.parametrize("field", [
    "task_name", "direction", "sequencer_path", "vip_transaction_type",
    "vip_addr_field", "vip_data_field", "addr_width", "data_width", "reason",
])
def test_validate_apb_bridge_entries_rejects_missing_required_field(field):
    entry = dict(WRITE_ENTRY)
    entry.pop(field)
    with pytest.raises(ApbBridgeTaskError) as exc:
        validate_apb_bridge_entries([entry])
    assert exc.value.reason == "MISSING_BRIDGE_EVIDENCE"
    assert exc.value.detail["field"] == field


def test_validate_apb_bridge_entries_rejects_invalid_direction():
    entry = dict(WRITE_ENTRY, direction="BIDIRECTIONAL")
    with pytest.raises(ApbBridgeTaskError) as exc:
        validate_apb_bridge_entries([entry])
    assert exc.value.reason == "INVALID_BRIDGE_DIRECTION"


def test_validate_apb_bridge_entries_rejects_duplicate_task_names():
    with pytest.raises(ApbBridgeTaskError) as exc:
        validate_apb_bridge_entries([WRITE_ENTRY, dict(WRITE_ENTRY)])
    assert exc.value.reason == "DUPLICATE_BRIDGE_TASK_NAME"


def test_validate_apb_bridge_entries_rejects_xact_type_field_with_no_matching_enum():
    # citing vip_xact_type_field without the matching direction's enum value
    # would silently drop the WRITE-vs-READ constraint on the emitted item.
    entry = dict(WRITE_ENTRY)
    del entry["vip_write_enum"]
    with pytest.raises(ApbBridgeTaskError) as exc:
        validate_apb_bridge_entries([entry])
    assert exc.value.reason == "MISSING_BRIDGE_EVIDENCE"
    assert exc.value.detail["field"] == "vip_write_enum"


def test_emit_apb_bridge_tasks_sv_rejects_invalid_entries_before_emitting_anything():
    with pytest.raises(ApbBridgeTaskError):
        emit_apb_bridge_tasks_sv([dict(WRITE_ENTRY, task_name="")])


def test_emit_apb_bridge_tasks_sv_calls_a_real_uvm_sequence_not_a_raw_pin():
    sv = emit_apb_bridge_tasks_sv([WRITE_ENTRY])
    # the crux of the audit question: does the bridge task actually call a
    # real UVM sequence item against the real VIP sequencer, rather than
    # doing raw pin-level force/deposit bridging.
    assert "task dv_uvm_cpuwrite1b(" in sv
    assert "svt_apb_master_transaction req;" in sv
    assert "`uvm_create_on(req, `DV_UVM_ENV.virtual_sequencer.apb_seqr)" in sv
    assert "req.randomize() with" in sv
    assert "xact_type == svt_apb_master_transaction::WRITE;" in sv
    assert "address == addr;" in sv
    assert "data == data;" in sv
    assert "`DV_UVM_ENV.virtual_sequencer.apb_seqr.execute_item(req);" in sv
    assert "endtask" in sv
    assert WRITE_ENTRY["reason"] in sv
    # no raw pin-level force/deposit anywhere in the emitted TASK BODY itself
    # (the module's own header comment legitimately says the word "force" in
    # describing what this function is NOT doing).
    task_body = sv[sv.index("task dv_uvm_cpuwrite1b("):]
    assert "force" not in task_body.lower()
    assert "deposit" not in task_body.lower()
    assert "TODO_PLACEHOLDER" not in sv


def test_emit_apb_bridge_tasks_sv_write_task_has_input_data_arg():
    sv = emit_apb_bridge_tasks_sv([WRITE_ENTRY])
    assert "task dv_uvm_cpuwrite1b(input bit [31:0] addr, input bit [7:0] data);" in sv


def test_emit_apb_bridge_tasks_sv_read_task_has_output_data_arg_and_assigns_it():
    sv = emit_apb_bridge_tasks_sv([READ_ENTRY])
    assert "task dv_uvm_cpuread1b(input bit [31:0] addr, output bit [7:0] data);" in sv
    assert "address == addr;" in sv
    assert "data = req.data;" in sv


def test_emit_apb_bridge_tasks_sv_multiple_entries_all_present():
    sv = emit_apb_bridge_tasks_sv([WRITE_ENTRY, READ_ENTRY])
    assert "task dv_uvm_cpuwrite1b(" in sv
    assert "task dv_uvm_cpuread1b(" in sv


def test_emit_apb_bridge_tasks_output_composes_into_emit_hook_svh_top_scope_decls():
    """The intended integration point: the bridge task body is one
    top_scope_decls entry, so it lands in the same TOP-MODULE-SCOPE region
    the hook skeleton already reserves for bridge instances -- closing the
    real TODO_PLACEHOLDER gap in
    examples/generated_usb_real_evidence_v1/bind/dv_uvm_hook.svh."""
    bridge_sv = emit_apb_bridge_tasks_sv([WRITE_ENTRY])
    svh = emit_hook_svh(
        "usb",
        {"CPUWRITE1B": "dv_uvm_cpuwrite1b"},
        [bridge_sv],
    )
    assert "`define CPUWRITE1B dv_uvm_cpuwrite1b" in svh
    assert "task dv_uvm_cpuwrite1b(" in svh
    assert "execute_item(req);" in svh
    assert "TODO_PLACEHOLDER" not in svh
    redirect_pos = svh.index("`define CPUWRITE1B")
    task_pos = svh.index("task dv_uvm_cpuwrite1b(")
    run_test_pos = svh.index("initial run_test();")
    assert redirect_pos < task_pos < run_test_pos
