"""Tests for dv_harness/cpuread_byte_shift_checker.py -- self_check_list.md
#25: does a project's CPUREAD task/bridge implementation perform the byte-
shift correction an unaligned sub-word read needs.

Fixtures mirror TWO real conventions confirmed in this repo:
  * `examples/generated_usb_real_evidence_v1/bind/dv_uvm_hook.svh`'s own
    `` `define CPUWRITE1B dv_uvm_cpuwrite1b `` bare-identifier macro redirect
    shape (mirrored here for CPUREAD).
  * `reference/USB_UVM_Handoff/uvm/tb/top/dv_uvm_hook.svh` /
    `usb_apb_arb.sv`'s real hierarchical-target redirect
    (`` `define CPUREAD1B sysn063.u_usb_apb_arb.READ1B ``) and its real
    READ1B/READ2B/READ4B task bodies, whose exact byte-shift expressions
    (`data = 32'(tmp[8*lane +: 8]);` / `32'(tmp[16*lane[1] +: 16]);`, no
    shift at all for the full-word READ4B) are reproduced verbatim below as
    the positive/negative-control evidence this checker is grounded against.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from dv_harness import cpuread_byte_shift_checker as cbsc
from dv_harness.uvm_generator import bind_mechanism_generator as bmg


# --- _width_bytes_from_command_name -------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("CPUREAD1B", 1), ("CPUREAD2B", 2), ("CPUREAD4B", 4),
    ("DEVREAD1B", 1), ("HOSTREAD4B", 4),
])
def test_width_bytes_from_known_register_read_names(name, expected):
    assert cbsc._width_bytes_from_command_name(name) == expected


def test_width_bytes_none_for_write_command():
    assert cbsc._width_bytes_from_command_name("CPUWRITE1B") is None


def test_width_bytes_none_for_non_conforming_name():
    assert cbsc._width_bytes_from_command_name("CPUREAD_STATUS") is None


# --- discover_cpuread_commands (reuse of de_command_style_learning) ----------

def test_discover_cpuread_commands_filters_to_dut_register_reads(tmp_path):
    cmdfile = tmp_path / "command.txt"
    cmdfile.write_text(textwrap.dedent("""\
        `CPUREAD1B(32'h1000_0100, read_val1); //byte read
        `CPUREAD2B(32'h1000_0104, read_val2); //halfword read
        `CPUREAD1B(32'h1000_0100, read_val1); //same command again
        `HOSTREAD4B(32'h2000_0000, host_val); //host-side read, out of scope
        `CPUWRITE4B(32'h1000_0108, 32'hDEAD_BEEF); //a write, out of scope
        """), encoding="utf-8")
    names = cbsc.discover_cpuread_commands(cmdfile)
    assert names == ["CPUREAD1B", "CPUREAD2B"]


def test_discover_cpuread_commands_host_context_filter(tmp_path):
    cmdfile = tmp_path / "command.txt"
    cmdfile.write_text("`HOSTREAD1B(32'h1000_0100, v); //host read\n", encoding="utf-8")
    assert cbsc.discover_cpuread_commands(cmdfile, context="DUT") == []
    assert cbsc.discover_cpuread_commands(cmdfile, context="HOST") == ["HOSTREAD1B"]


# --- analyze_task_body_byte_shift: grounded against real reference text -----

def test_read1b_real_reference_body_reports_present():
    # usb_apb_arb.sv READ1B, verbatim shape.
    body = textwrap.dedent("""\
        task automatic READ1B(input bit [31:0] addr, output bit [31:0] data,
                              input string owner = "unknown");
          bit [31:0] tmp;
          int        lane = addr[1:0];
          acquire(owner, addr);
          dispatch(1'b0, {addr[31:2], 2'b00}, 32'h0, 4'h0, tmp);
          n_read++;
          release_lock();
          data = 32'(tmp[8*lane +: 8]);
        endtask
        """)
    result = cbsc.analyze_task_body_byte_shift(body)
    assert result["status"] == cbsc.STATUS_PRESENT
    assert result["addr_arg"] == "addr"
    assert result["data_arg"] == "data"
    assert result["evidence"], "expected at least one cited shift expression"
    assert "lane" in result["addr_candidates"]


def test_read2b_real_reference_body_reports_present():
    # usb_apb_arb.sv READ2B, verbatim shape (halfword granularity, lane[1]).
    body = textwrap.dedent("""\
        task automatic READ2B(input bit [31:0] addr, output bit [31:0] data,
                              input string owner = "unknown");
          bit [31:0] tmp;
          int        lane = addr[1:0];
          acquire(owner, addr);
          dispatch(1'b0, {addr[31:2], 2'b00}, 32'h0, 4'h0, tmp);
          n_read++;
          release_lock();
          data = 32'(tmp[16*lane[1] +: 16]);
        endtask
        """)
    result = cbsc.analyze_task_body_byte_shift(body)
    assert result["status"] == cbsc.STATUS_PRESENT


def test_read4b_real_reference_body_has_no_shift_but_that_is_expected():
    # usb_apb_arb.sv READ4B: full word, no shift by design. Verifying the
    # RAW body reports MISSING here is correct in isolation (no addr
    # reference in the data assignment) -- the audit-level NOT_APPLICABLE
    # short-circuit (width_bytes >= word_bytes) is what protects a real
    # READ4B command from being flagged; that is tested separately below via
    # audit_cpuread_byte_shift.
    body = textwrap.dedent("""\
        task automatic READ4B(input bit [31:0] addr, output bit [31:0] data,
                              input string owner = "unknown");
          bit [31:0] tmp;
          acquire(owner, addr);
          dispatch(1'b0, {addr[31:2], 2'b00}, 32'h0, 4'h0, tmp);
          n_read++;
          release_lock();
          data = tmp;
        endtask
        """)
    result = cbsc.analyze_task_body_byte_shift(body)
    assert result["status"] == cbsc.STATUS_MISSING


def test_no_recognizable_arguments_reports_arguments_unknown():
    body = "task automatic weird_task(); do_something(); endtask"
    result = cbsc.analyze_task_body_byte_shift(body)
    assert result["status"] == cbsc.STATUS_ARGUMENTS_UNKNOWN


# --- end-to-end audit against a real generated-environment fixture ----------

def _write_bridge_fixture_env(tmp_path: Path) -> Path:
    """A small, hand-authored generated-environment fixture (never mined
    from a real project) mirroring the two real macro-redirect shapes this
    repo has: a bare-identifier bridge target (examples/
    generated_usb_real_evidence_v1's own convention) and a hierarchical
    target (the real USB_UVM_Handoff convention)."""
    env_dir = tmp_path / "generated_env"
    (env_dir / "bind").mkdir(parents=True)
    (env_dir / "top").mkdir(parents=True)

    (env_dir / "bind" / "dv_uvm_hook.svh").write_text(textwrap.dedent("""\
        // -- macro redirect (must precede the model's task definitions) --
        `define CPUREAD1B dv_uvm_cpuread1b
        `define CPUREAD2B sysn999.u_apb_arb.READ2B
        `define CPUREAD4B sysn999.u_apb_arb.READ4B
        """), encoding="utf-8")

    # Bare-identifier target (dv_uvm_cpuread1b), WITH correct byte-shift.
    (env_dir / "bind" / "bridge_read1b.sv").write_text(textwrap.dedent("""\
        task automatic dv_uvm_cpuread1b(input bit [31:0] addr,
                                        output bit [7:0] data);
          bit [31:0] tmp;
          int lane = addr[1:0];
          tmp = apb_seqr.execute_word_read({addr[31:2], 2'b00});
          data = 8'(tmp[8*lane +: 8]);
        endtask
        """), encoding="utf-8")

    # Hierarchical target (sysn999.u_apb_arb.READ2B), MISSING byte-shift --
    # the negative control: reads a word, returns it whole with no lane
    # correction for a declared 2-byte transfer.
    (env_dir / "top" / "apb_arb.sv").write_text(textwrap.dedent("""\
        module apb_arb;
          task automatic READ2B(input bit [31:0] addr, output bit [31:0] data);
            bit [31:0] tmp;
            tmp = apb_seqr.execute_word_read({addr[31:2], 2'b00});
            data = tmp;
          endtask

          task automatic READ4B(input bit [31:0] addr, output bit [31:0] data);
            bit [31:0] tmp;
            tmp = apb_seqr.execute_word_read({addr[31:2], 2'b00});
            data = tmp;
          endtask
        endmodule
        """), encoding="utf-8")

    return env_dir


def test_audit_cpuread_byte_shift_bare_identifier_redirect_present(tmp_path):
    env_dir = _write_bridge_fixture_env(tmp_path)
    findings = cbsc.audit_cpuread_byte_shift(env_dir, ["CPUREAD1B"])
    assert len(findings) == 1
    f = findings[0]
    assert f.status == cbsc.STATUS_PRESENT
    assert f.width_bytes == 1
    assert f.task_name == "dv_uvm_cpuread1b"
    assert f.evidence


def test_audit_cpuread_byte_shift_hierarchical_redirect_missing(tmp_path):
    env_dir = _write_bridge_fixture_env(tmp_path)
    findings = cbsc.audit_cpuread_byte_shift(env_dir, ["CPUREAD2B"])
    assert len(findings) == 1
    f = findings[0]
    assert f.status == cbsc.STATUS_MISSING
    assert f.width_bytes == 2
    assert f.task_name == "READ2B"
    assert f.addr_arg == "addr"
    assert f.data_arg == "data"
    assert not f.evidence
    assert "addr" in f.reason


def test_audit_cpuread_byte_shift_full_word_not_applicable(tmp_path):
    env_dir = _write_bridge_fixture_env(tmp_path)
    findings = cbsc.audit_cpuread_byte_shift(env_dir, ["CPUREAD4B"])
    f = findings[0]
    assert f.status == cbsc.STATUS_NOT_APPLICABLE
    assert f.width_bytes == 4


def test_audit_cpuread_byte_shift_command_not_found(tmp_path):
    env_dir = _write_bridge_fixture_env(tmp_path)
    findings = cbsc.audit_cpuread_byte_shift(env_dir, ["CPUREAD8B"])
    f = findings[0]
    assert f.status == cbsc.STATUS_COMMAND_NOT_FOUND


def test_audit_cpuread_byte_shift_ambiguous_never_guesses(tmp_path):
    env_dir = tmp_path / "generated_env"
    (env_dir / "a").mkdir(parents=True)
    (env_dir / "a" / "one.sv").write_text(
        "task automatic CPUREAD1B(input bit [31:0] addr, output bit [31:0] data);\n"
        "  data = 32'(addr[1:0]*8);\n"
        "endtask\n", encoding="utf-8")
    (env_dir / "a" / "two.sv").write_text(
        "task automatic CPUREAD1B(input bit [31:0] addr, output bit [31:0] data);\n"
        "  data = 32'h0;\n"
        "endtask\n", encoding="utf-8")
    findings = cbsc.audit_cpuread_byte_shift(env_dir, ["CPUREAD1B"])
    f = findings[0]
    assert f.status == cbsc.STATUS_AMBIGUOUS
    assert f.task_macro_citations


def test_audit_cpuread_byte_shift_rejects_empty_command_list(tmp_path):
    env_dir = _write_bridge_fixture_env(tmp_path)
    with pytest.raises(cbsc.CpureadByteShiftCheckerError):
        cbsc.audit_cpuread_byte_shift(env_dir, [])


def test_overall_exit_code():
    present = cbsc.CpureadByteShiftFinding(command_name="A", status=cbsc.STATUS_PRESENT)
    missing = cbsc.CpureadByteShiftFinding(command_name="B", status=cbsc.STATUS_MISSING)
    unknown = cbsc.CpureadByteShiftFinding(command_name="C", status=cbsc.STATUS_WIDTH_UNKNOWN)
    not_applicable = cbsc.CpureadByteShiftFinding(command_name="D", status=cbsc.STATUS_NOT_APPLICABLE)
    assert cbsc.overall_exit_code([present, not_applicable]) == 0
    assert cbsc.overall_exit_code([present, missing]) == 1
    assert cbsc.overall_exit_code([present, unknown]) == 2


# --- grounded against the REAL bind_mechanism_generator output --------------

def _real_apb_bridge_entries():
    """A real, evidence-complete pair of bridge entries in
    `bind_mechanism_generator.validate_apb_bridge_entries`'s own required
    shape: one WRITE (required alongside for a mixed real project), one
    READ at an 8-bit (sub-word) transfer width."""
    return [
        {
            "task_name": "dv_uvm_cpuwrite1b", "direction": "WRITE",
            "sequencer_path": "env.apb_agent.sqr",
            "vip_transaction_type": "svt_apb_master_transaction",
            "vip_addr_field": "addr", "vip_data_field": "data",
            "addr_width": 32, "data_width": 8,
            "reason": "real evidence citation",
        },
        {
            "task_name": "dv_uvm_cpuread1b", "direction": "READ",
            "sequencer_path": "env.apb_agent.sqr",
            "vip_transaction_type": "svt_apb_master_transaction",
            "vip_addr_field": "addr", "vip_data_field": "data",
            "addr_width": 32, "data_width": 8,
            "reason": "real evidence citation",
        },
    ]


def test_audit_apb_bridge_entries_uses_real_generator_output():
    entries = _real_apb_bridge_entries()
    # Cross-check: the checker's analysis really runs over the SAME text the
    # real generator emits -- not a hand-authored stand-in for it.
    generated = bmg.emit_apb_bridge_tasks_sv(entries)
    assert "task dv_uvm_cpuread1b" in generated

    findings = cbsc.audit_apb_bridge_entries_byte_shift(entries)
    assert len(findings) == 1
    f = findings[0]
    assert f.command_name == "dv_uvm_cpuread1b"
    assert f.width_bytes == 1
    # REAL, DISCLOSED FINDING of this gap-close: the harness's own current
    # READ-direction bridge-task template assigns the VIP data field
    # straight to the output with no reference to the address argument at
    # all, so a genuinely unaligned sub-word read would return the wrong
    # byte lane. This is not a test bug -- it is the checker doing its job
    # against real generated output.
    assert f.status == cbsc.STATUS_MISSING
    assert f.addr_arg is not None
    assert f.data_arg is not None


def test_audit_apb_bridge_entries_full_word_read_is_not_applicable():
    entries = [
        {
            "task_name": "dv_uvm_cpuread4b", "direction": "READ",
            "sequencer_path": "env.apb_agent.sqr",
            "vip_transaction_type": "svt_apb_master_transaction",
            "vip_addr_field": "addr", "vip_data_field": "data",
            "addr_width": 32, "data_width": 32,
            "reason": "real evidence citation",
        },
    ]
    findings = cbsc.audit_apb_bridge_entries_byte_shift(entries)
    assert findings[0].status == cbsc.STATUS_NOT_APPLICABLE


def test_audit_apb_bridge_entries_skips_write_only_lists():
    entries = [_real_apb_bridge_entries()[0]]  # WRITE only
    assert cbsc.audit_apb_bridge_entries_byte_shift(entries) == []


def test_format_finding_smoke():
    f = cbsc.CpureadByteShiftFinding(
        command_name="CPUREAD1B", status=cbsc.STATUS_PRESENT,
        task_body_source="foo.sv", task_name="READ1B",
        evidence=[{"statement": "data = 32'(tmp[8*lane +: 8]);"}])
    text = cbsc.format_finding(f)
    assert "CPUREAD1B" in text and "BYTE_SHIFT_PRESENT" in text
