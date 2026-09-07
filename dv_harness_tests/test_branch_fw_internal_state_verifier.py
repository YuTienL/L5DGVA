"""Tests for dv_harness/branch_fw_internal_state_verifier.py -- verifying
branch_fw's own internal ARM/WAIT/WAKE/DECODE/CLEAR interrupt-service loop
against real generated command.txt/pattern text.

Fixtures are small, hand-authored, synthetic-but-realistic pattern bodies
shaped after `.claude/skills/CORE/interrupt-event-dispatch/SKILL.md`'s own
worked example (USB, DWC_usb31 wrapper) -- never mined from any real project's
content, matching this repo's own established synthetic-fixture precedent
(`test_reference_pattern_audit.py`, `test_command_task_trace.py`).
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dv_harness import branch_fw_internal_state_verifier as bfsv
from dv_harness import reference_pattern_audit as rpa

ROOT = Path(__file__).resolve().parents[1]


# --- fixtures -------------------------------------------------------------------

FULL_LOOP_BODY = textwrap.dedent("""\
    task automatic branch_fw_port0();
      `CPUWRITE4B(32'h1270_0004, 32'h0000_0001); //irq_enable=1 arm the wrapper interrupt
      fork
        begin
          wait(sysn063.u_usbtop.irq_pending);
        end
        begin
          #500000; //watchdog fallback
        end
      join_any
      `CPUREAD4B(32'h1270_0008, status_var);
      `CPUWRITE4B(32'h1270_0008, 32'h0000_0001); //w1c clear serviced bit
    endtask
    """)


def _statements(body_text: str, tmp_path: Path):
    p = tmp_path / "branch_fw_port0.sv"
    p.write_text(body_text, encoding="utf-8")
    return rpa.extract_command_statements(p)


# --- core verifier over an already-extracted statement stream ------------------

def test_full_loop_verified_in_order(tmp_path):
    stmts = _statements(FULL_LOOP_BODY, tmp_path)
    v = bfsv.verify_branch_fw_loop_in_statements(stmts, command_name="branch_fw_port0")
    assert v.status == bfsv.STATUS_VERIFIED_IN_ORDER
    assert v.order_violations == []
    for state in bfsv.STATE_ORDER:
        finding = v.state(state)
        assert finding.status == bfsv.FINDING_REACHED, (state, finding.reason)
    # strictly ascending lines
    lines = [v.state(s).line for s in bfsv.STATE_ORDER]
    assert lines == sorted(lines)
    assert lines == sorted(set(lines))


def test_verify_branch_fw_loop_in_file_matches_in_statements(tmp_path):
    p = tmp_path / "branch_fw_port0.sv"
    p.write_text(FULL_LOOP_BODY, encoding="utf-8")
    v = bfsv.verify_branch_fw_loop_in_file(p)
    assert v.status == bfsv.STATUS_VERIFIED_IN_ORDER
    assert v.command_name == "branch_fw_port0.sv"


# --- negative controls: honest UNKNOWN, never a fabricated REACHED -------------

def test_no_interrupt_wait_at_all_reports_wait_unknown_and_cascades(tmp_path):
    """A plain, non-interrupt-named signal wait must never be credited as the
    branch_fw event loop's own WAIT state -- and everything defined relative
    to WAIT (WAKE, DECODE, CLEAR) must honestly cascade to UNKNOWN rather than
    being guessed from program order alone."""
    body = textwrap.dedent("""\
        task automatic not_really_branch_fw();
          `CPUWRITE4B(32'h1270_0004, 32'h0000_0001); //some_config=1
          wait(sysn063.u_usbtop.some_plain_signal);
          `CPUREAD4B(32'h1270_0008, status_var);
        endtask
        """)
    stmts = _statements(body, tmp_path)
    v = bfsv.verify_branch_fw_loop_in_statements(stmts)
    assert v.status == bfsv.STATUS_INCOMPLETE
    wait_finding = v.state(bfsv.STATE_WAIT)
    assert wait_finding.status == bfsv.FINDING_UNKNOWN
    wake_finding = v.state(bfsv.STATE_WAKE)
    assert wake_finding.status == bfsv.FINDING_UNKNOWN
    assert "no WAIT state" in wake_finding.reason
    decode_finding = v.state(bfsv.STATE_DECODE)
    assert decode_finding.status == bfsv.FINDING_UNKNOWN
    clear_finding = v.state(bfsv.STATE_CLEAR)
    assert clear_finding.status == bfsv.FINDING_UNKNOWN


def test_missing_arm_token_is_honestly_unknown_not_guessed(tmp_path):
    """A REGISTER_WRITE exists before the interrupt wait, but cites no
    arm/enable/trigger/mask token -- this must not be silently credited as
    ARM just because it is the nearest preceding write."""
    body = textwrap.dedent("""\
        task automatic branch_fw_port0();
          `CPUWRITE4B(32'h1270_0000, 32'h0000_0002); //unrelated_config=2
          wait(sysn063.u_usbtop.irq_pending);
          `CPUREAD4B(32'h1270_0008, status_var);
          `CPUWRITE4B(32'h1270_0008, 32'h0000_0001); //w1c clear serviced bit
        endtask
        """)
    stmts = _statements(body, tmp_path)
    v = bfsv.verify_branch_fw_loop_in_statements(stmts)
    arm_finding = v.state(bfsv.STATE_ARM)
    assert arm_finding.status == bfsv.FINDING_UNKNOWN
    assert "arm/enable/trigger/mask" in arm_finding.reason
    # WAIT/DECODE/CLEAR are unaffected by ARM's absence
    assert v.state(bfsv.STATE_WAIT).status == bfsv.FINDING_REACHED
    assert v.state(bfsv.STATE_DECODE).status == bfsv.FINDING_REACHED
    assert v.state(bfsv.STATE_CLEAR).status == bfsv.FINDING_REACHED
    assert v.status == bfsv.STATUS_INCOMPLETE


def test_wait_not_enclosed_by_fork_join_any_reports_wake_unknown(tmp_path):
    """A plain (unwrapped) interrupt wait is real WAIT evidence, but this
    module must never credit it as WAKE too -- the worked example ties WAKE
    specifically to the bounded fork{...}join_any race."""
    body = textwrap.dedent("""\
        task automatic branch_fw_port0();
          `CPUWRITE4B(32'h1270_0004, 32'h0000_0001); //irq_enable=1 arm it
          wait(sysn063.u_usbtop.irq_pending);
          `CPUREAD4B(32'h1270_0008, status_var);
          `CPUWRITE4B(32'h1270_0008, 32'h0000_0001); //w1c clear serviced bit
        endtask
        """)
    stmts = _statements(body, tmp_path)
    v = bfsv.verify_branch_fw_loop_in_statements(stmts)
    assert v.state(bfsv.STATE_WAIT).status == bfsv.FINDING_REACHED
    wake = v.state(bfsv.STATE_WAKE)
    assert wake.status == bfsv.FINDING_UNKNOWN
    assert "fork" in wake.reason
    # DECODE/CLEAR still resolve via the WAIT fallback anchor
    assert v.state(bfsv.STATE_DECODE).status == bfsv.FINDING_REACHED
    assert v.state(bfsv.STATE_CLEAR).status == bfsv.FINDING_REACHED
    assert v.status == bfsv.STATUS_INCOMPLETE


def test_wrong_join_kind_is_wake_unknown_not_credited(tmp_path):
    """A fork block genuinely encloses the WAIT, but closes with a plain
    'join' (not 'join_any') -- the worked example's specific race shape is
    absent, so WAKE stays UNKNOWN, citing exactly what was actually found."""
    body = textwrap.dedent("""\
        task automatic branch_fw_port0();
          `CPUWRITE4B(32'h1270_0004, 32'h0000_0001); //irq_enable=1 arm it
          fork
            begin
              wait(sysn063.u_usbtop.irq_pending);
            end
          join
          `CPUREAD4B(32'h1270_0008, status_var);
          `CPUWRITE4B(32'h1270_0008, 32'h0000_0001); //w1c clear serviced bit
        endtask
        """)
    stmts = _statements(body, tmp_path)
    v = bfsv.verify_branch_fw_loop_in_statements(stmts)
    wake = v.state(bfsv.STATE_WAKE)
    assert wake.status == bfsv.FINDING_UNKNOWN
    assert "'join'" in wake.reason


def test_missing_decode_and_clear_are_unknown(tmp_path):
    body = textwrap.dedent("""\
        task automatic branch_fw_port0();
          `CPUWRITE4B(32'h1270_0004, 32'h0000_0001); //irq_enable=1 arm it
          fork
            begin
              wait(sysn063.u_usbtop.irq_pending);
            end
            begin
              #500000;
            end
          join_any
          $display("=>woke up, but never reads status or clears anything");
        endtask
        """)
    stmts = _statements(body, tmp_path)
    v = bfsv.verify_branch_fw_loop_in_statements(stmts)
    assert v.state(bfsv.STATE_WAKE).status == bfsv.FINDING_REACHED
    assert v.state(bfsv.STATE_DECODE).status == bfsv.FINDING_UNKNOWN
    assert v.state(bfsv.STATE_CLEAR).status == bfsv.FINDING_UNKNOWN
    assert v.status == bfsv.STATUS_INCOMPLETE


def test_clear_via_token_when_address_differs(tmp_path):
    """CLEAR may also be evidenced by a clear/ack/w1c token citation even
    when the write targets a different address than DECODE's read (e.g. a
    separate IRQ-clear register)."""
    body = textwrap.dedent("""\
        task automatic branch_fw_port0();
          `CPUWRITE4B(32'h1270_0004, 32'h0000_0001); //irq_enable=1 arm it
          fork
            begin
              wait(sysn063.u_usbtop.irq_pending);
            end
            begin
              #500000;
            end
          join_any
          `CPUREAD4B(32'h1270_0008, status_var);
          `CPUWRITE4B(32'h1270_0010, 32'h0000_0001); //irq_ack write to a separate register
        endtask
        """)
    stmts = _statements(body, tmp_path)
    v = bfsv.verify_branch_fw_loop_in_statements(stmts)
    clear = v.state(bfsv.STATE_CLEAR)
    assert clear.status == bfsv.FINDING_REACHED
    assert clear.basis == "SIGNAL_NAME_TOKEN_MATCH"
    assert "ack" in clear.matched_tokens
    assert v.status == bfsv.STATUS_VERIFIED_IN_ORDER


# --- order violation: a real, cited defect -------------------------------------

def test_write_after_wait_is_never_credited_as_arm(tmp_path):
    """A REGISTER_WRITE cites a real arm/enable token, but only appears AFTER
    the interrupt wait -- ARM's own search is bounded to writes strictly
    before WAIT's line, so this is never fabricated as ARM 'because it is the
    nearest arm-shaped write'; it is honestly UNKNOWN. This is what keeps
    STATUS_OUT_OF_ORDER unreachable through this module's own real search
    chain (each phase only searches forward/backward from its own anchor),
    proven directly against the ordering helper itself in
    test_decode_before_wait_is_out_of_order below."""
    body = textwrap.dedent("""\
        task automatic branch_fw_port0();
          fork
            begin
              wait(sysn063.u_usbtop.irq_pending);
            end
            begin
              #500000;
            end
          join_any
          `CPUWRITE4B(32'h1270_0004, 32'h0000_0001); //irq_enable=1 arm it -- too late
          `CPUREAD4B(32'h1270_0008, status_var);
          `CPUWRITE4B(32'h1270_0008, 32'h0000_0001); //w1c clear serviced bit
        endtask
        """)
    stmts = _statements(body, tmp_path)
    v = bfsv.verify_branch_fw_loop_in_statements(stmts)
    # ARM only searches writes strictly before the WAIT line, so a
    # post-WAIT write is never picked up as ARM at all -- ARM is honestly
    # UNKNOWN here, which is itself the correct, non-fabricated outcome.
    assert v.state(bfsv.STATE_ARM).status == bfsv.FINDING_UNKNOWN
    assert v.status == bfsv.STATUS_INCOMPLETE


def test_decode_before_wait_is_out_of_order(tmp_path):
    """Construct a case where DECODE's own anchor search still finds a read
    whose line number is not actually after WAKE because WAKE was reported
    at a line that a later, disconnected read happens to precede -- exercised
    directly via the internal ordering-violation helper against a hand-built
    state list, proving the order check fires independent of how each state
    was found."""
    states = [
        bfsv.StateFinding(state=bfsv.STATE_ARM, status=bfsv.FINDING_REACHED, line=10),
        bfsv.StateFinding(state=bfsv.STATE_WAIT, status=bfsv.FINDING_REACHED, line=20),
        bfsv.StateFinding(state=bfsv.STATE_WAKE, status=bfsv.FINDING_REACHED, line=30),
        bfsv.StateFinding(state=bfsv.STATE_DECODE, status=bfsv.FINDING_REACHED, line=25),
        bfsv.StateFinding(state=bfsv.STATE_CLEAR, status=bfsv.FINDING_REACHED, line=40),
    ]
    violations = bfsv._order_violations(states)
    assert len(violations) == 1
    assert "WAKE" in violations[0] and "DECODE" in violations[0]


# --- reused command_task_trace machinery: full resolution path -----------------

def _write_env_direct_declaration(tmp_path: Path) -> Path:
    env_dir = tmp_path / "generated_env"
    (env_dir / "patterns").mkdir(parents=True)
    (env_dir / "patterns" / "branch_fw_port0.sv").write_text(FULL_LOOP_BODY, encoding="utf-8")
    return env_dir


def test_verify_from_env_direct_declaration(tmp_path):
    env_dir = _write_env_direct_declaration(tmp_path)
    v = bfsv.verify_branch_fw_loop_from_env(env_dir, "branch_fw_port0", use_verible=False)
    assert v.status == bfsv.STATUS_VERIFIED_IN_ORDER
    assert v.task_body_source is not None
    assert v.task_name == "branch_fw_port0"
    assert v.task_macro_citations


def test_verify_from_env_via_macro_redirect(tmp_path):
    """Reuses command_task_trace's macro-redirect (`` `define ``) leg -- this
    project's own real `dv_uvm_hook.svh` convention -- one level, exactly as
    `command_task_trace._resolve_uvm_bridge()` itself does for its own leg."""
    env_dir = tmp_path / "generated_env"
    (env_dir / "bind").mkdir(parents=True)
    (env_dir / "patterns").mkdir(parents=True)
    (env_dir / "bind" / "dv_uvm_hook.svh").write_text(
        "`define BRANCH_FW_PORT0 dv_uvm_branch_fw_port0\n", encoding="utf-8")
    redirected_body = FULL_LOOP_BODY.replace("branch_fw_port0", "dv_uvm_branch_fw_port0")
    (env_dir / "patterns" / "dv_uvm_branch_fw_port0.sv").write_text(
        redirected_body, encoding="utf-8")
    v = bfsv.verify_branch_fw_loop_from_env(env_dir, "BRANCH_FW_PORT0", use_verible=False)
    assert v.status == bfsv.STATUS_VERIFIED_IN_ORDER
    assert v.task_name == "dv_uvm_branch_fw_port0"


def test_command_not_found(tmp_path):
    env_dir = _write_env_direct_declaration(tmp_path)
    v = bfsv.verify_branch_fw_loop_from_env(env_dir, "NO_SUCH_BRANCH_FW", use_verible=False)
    assert v.status == bfsv.STATUS_COMMAND_NOT_FOUND


def test_ambiguous_task_resolution_never_verified(tmp_path):
    env_dir = _write_env_direct_declaration(tmp_path)
    (env_dir / "patterns" / "branch_fw_port0_v2.sv").write_text(textwrap.dedent("""\
        task automatic branch_fw_port0();
          $display("a second, conflicting declaration");
        endtask
        """), encoding="utf-8")
    v = bfsv.verify_branch_fw_loop_from_env(env_dir, "branch_fw_port0", use_verible=False)
    assert v.status == bfsv.STATUS_AMBIGUOUS_TASK_RESOLUTION
    assert v.task_macro_citations


def test_blocked_missing_env_dir(tmp_path):
    v = bfsv.verify_branch_fw_loop_from_env(tmp_path / "does_not_exist", "branch_fw_port0",
                                             use_verible=False)
    assert v.status == bfsv.STATUS_BLOCKED


# --- rendering / exit-code plumbing --------------------------------------------

def test_format_verification_mentions_states_and_status(tmp_path):
    stmts = _statements(FULL_LOOP_BODY, tmp_path)
    v = bfsv.verify_branch_fw_loop_in_statements(stmts, command_name="branch_fw_port0")
    text = bfsv.format_verification(v)
    assert bfsv.STATUS_VERIFIED_IN_ORDER in text
    for state in bfsv.STATE_ORDER:
        assert f"[{state}]" in text


def test_overall_exit_code():
    verified = bfsv.BranchFwLoopVerification(command_name="a", status=bfsv.STATUS_VERIFIED_IN_ORDER)
    out_of_order = bfsv.BranchFwLoopVerification(command_name="b", status=bfsv.STATUS_OUT_OF_ORDER)
    incomplete = bfsv.BranchFwLoopVerification(command_name="c", status=bfsv.STATUS_INCOMPLETE)
    assert bfsv.overall_exit_code([verified]) == 0
    assert bfsv.overall_exit_code([verified, out_of_order]) == 1
    assert bfsv.overall_exit_code([verified, incomplete]) == 2
    assert bfsv.overall_exit_code([out_of_order, incomplete]) == 1


# --- CLI, driven as a real subprocess -------------------------------------------

def test_cli_file_json_exit_code_0(tmp_path):
    p = tmp_path / "branch_fw_port0.sv"
    p.write_text(FULL_LOOP_BODY, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.branch_fw_internal_state_verifier",
         "--file", str(p), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload[0]["status"] == bfsv.STATUS_VERIFIED_IN_ORDER


def test_cli_incomplete_exit_code_2(tmp_path):
    body = textwrap.dedent("""\
        task automatic branch_fw_port0();
          wait(sysn063.u_usbtop.some_plain_signal);
        endtask
        """)
    p = tmp_path / "branch_fw_port0.sv"
    p.write_text(body, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.branch_fw_internal_state_verifier",
         "--file", str(p)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, proc.stderr


def test_cli_env_command_flow(tmp_path):
    env_dir = _write_env_direct_declaration(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.branch_fw_internal_state_verifier",
         "--env-dir", str(env_dir), "--command", "branch_fw_port0", "--no-verible"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert bfsv.STATUS_VERIFIED_IN_ORDER in proc.stdout


def test_cli_requires_command_or_file(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.branch_fw_internal_state_verifier"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2
