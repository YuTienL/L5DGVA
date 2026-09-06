"""Tests for dv_harness/command_precondition_gate.py.

Covers: the core positive path (a command whose declared preconditions all
resolve to FIRED events reads READY), plus real negative controls -- a
FAILED/TIMEOUT/BLOCKED_BY_DEPENDENCY precondition (BLOCKED), a still-PENDING
precondition (BLOCKED), a precondition naming no event in the registry
(UNKNOWN_PRECONDITION, never silently READY), BLOCKED outranking
UNKNOWN_PRECONDITION when a command declares both kinds of trouble at once,
duplicate/blank declaration errors, and the vocabulary-collision guard. Also
drives both real CLI verbs (`list`/`check`) as the module's own
`execute_verb()` and as real subprocesses, never a mock.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.command_precondition_gate import (
    CommandDispatchStatus,
    CommandPreconditionDeclaration,
    CommandPreconditionGateError,
    commands_from_dict,
    evaluate_command_preconditions,
    evaluate_dispatch_readiness,
    execute_verb,
    load_commands,
    render_commands,
    render_dispatch_gate,
    write_report,
)
from dv_harness.runtime_event_registry import (
    EventRelationDecl,
    EventRelationType,
    EventStatus,
    RuntimeEventDef,
    RuntimeEventObservation,
    RuntimeEventRegistry,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# helpers: a real illustrative event registry matching this repo's own
# block/branch_a*/branch_fw/branch_b* vocabulary (branch-mapper /
# pattern-architecture SKILL.md), declared as data -- never hardcoded inside
# the module under test. GLOBAL_READY/DUT_READY/FW_READY/VIP_READY/
# RESET_DEASSERTED are illustrative precondition names only.
# ---------------------------------------------------------------------------

def _pattern_style_registry(**overrides) -> RuntimeEventRegistry:
    events = (
        RuntimeEventDef("GLOBAL_READY", producer="block", consumer=("branch_a0",),
                        timeout=10.0, scope="GLOBAL",
                        source="pattern-architecture/SKILL.md sec 1, block prologue"),
        RuntimeEventDef("DUT_READY", producer="branch_a0", consumer=("branch_fw", "branch_b0"),
                        timeout=5.0, scope="PORT:0",
                        source="pattern-architecture/SKILL.md sec 1, branch_a* per-port bring-up"),
        RuntimeEventDef("RESET_DEASSERTED", producer="branch_a0", consumer=("branch_fw",),
                        timeout=2.0, scope="PORT:0",
                        source="pattern-architecture/SKILL.md sec 1, branch_a* reset release"),
        RuntimeEventDef("FW_READY", producer="branch_fw", consumer=("branch_b0",),
                        timeout=3.0, scope="PORT:0",
                        source="interrupt-event-dispatch/SKILL.md FW service-loop ready"),
        RuntimeEventDef("VIP_READY", producer="branch_b0", consumer=("branch_b0",),
                        timeout=None, scope="PORT:0",
                        source="pattern-architecture/SKILL.md sec 1, branch_b* VIP-driven body"),
    )
    relations = (
        EventRelationDecl("DUT_READY", EventRelationType.REQUIRES, "GLOBAL_READY",
                          reason="per-port bring-up cannot start before the SoC-global prologue"),
        EventRelationDecl("FW_READY", EventRelationType.REQUIRES, "DUT_READY",
                          reason="the FW service loop cannot arm before the port is bound up"),
    )
    kwargs = dict(registry_id="usb_dual_port_command_gate_illustration",
                 events=events, relations=relations,
                 description="illustrative event set, not this repo's own universal vocabulary")
    kwargs.update(overrides)
    return RuntimeEventRegistry(**kwargs)


def _cmd(command_id: str, *preconditions: str, source: str = "") -> CommandPreconditionDeclaration:
    return CommandPreconditionDeclaration(command_id=command_id, preconditions=tuple(preconditions),
                                          source=source)


# ---------------------------------------------------------------------------
# core positive path
# ---------------------------------------------------------------------------

def test_all_preconditions_fired_command_is_ready():
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:10"),
        "DUT_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:55 port0 link trained"),
    })
    report = reg.propagate()
    cmd = _cmd("SEND_PACKET_PORT0", "GLOBAL_READY", "DUT_READY", source="command.txt:120")
    result = evaluate_command_preconditions(cmd, report)
    assert result.status == CommandDispatchStatus.READY.value
    assert result.blocking_preconditions == ()
    assert result.awaiting_preconditions == ()
    assert result.unresolved_preconditions == ()
    assert "READY" in result.reason


def test_zero_declared_preconditions_is_vacuously_ready():
    reg = _pattern_style_registry()
    report = reg.propagate()
    cmd = _cmd("NO_OP_COMMAND")
    result = evaluate_command_preconditions(cmd, report)
    assert result.status == CommandDispatchStatus.READY.value
    assert result.checks == ()
    assert "no preconditions declared" in result.reason


# ---------------------------------------------------------------------------
# negative controls -- BLOCKED
# ---------------------------------------------------------------------------

def test_failed_precondition_blocks_the_command():
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:42 UVM_FATAL"),
    })
    report = reg.propagate()
    cmd = _cmd("SEND_PACKET_PORT0", "GLOBAL_READY")
    result = evaluate_command_preconditions(cmd, report)
    assert result.status == CommandDispatchStatus.BLOCKED.value
    assert result.blocking_preconditions == ("GLOBAL_READY",)
    check = result.checks[0]
    assert check.known is True
    assert check.effective_status == EventStatus.FAILED.value


def test_dependency_cascade_blocked_by_dependency_blocks_the_command():
    """GLOBAL_READY FAILED cascades DUT_READY to BLOCKED_BY_DEPENDENCY via
    runtime_event_registry's own REQUIRES propagation -- the gate must read
    the EFFECTIVE (post-propagation) status, not the raw one."""
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:42"),
    })
    report = reg.propagate()
    assert report.effective_status["DUT_READY"] == EventStatus.BLOCKED_BY_DEPENDENCY.value
    cmd = _cmd("SEND_PACKET_PORT0", "DUT_READY")
    result = evaluate_command_preconditions(cmd, report)
    assert result.status == CommandDispatchStatus.BLOCKED.value
    assert result.blocking_preconditions == ("DUT_READY",)
    assert "BLOCKED_BY_DEPENDENCY" in result.checks[0].reason


def test_timeout_precondition_blocks_the_command():
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:10"),
        "DUT_READY": RuntimeEventObservation(EventStatus.TIMEOUT, evidence="sim.log:900 no link training within 5.0us"),
    })
    report = reg.propagate()
    cmd = _cmd("SEND_PACKET_PORT0", "DUT_READY")
    result = evaluate_command_preconditions(cmd, report)
    assert result.status == CommandDispatchStatus.BLOCKED.value
    assert result.blocking_preconditions == ("DUT_READY",)


def test_still_pending_precondition_blocks_the_command_but_is_not_a_failure():
    """A precondition whose event is declared and simply has not fired yet
    (no failure evidence at all) still reads BLOCKED -- classic
    process-scheduling sense of "waiting on a condition that hasn't occurred"
    -- and is reported distinctly from a genuine FAILED/TIMEOUT via
    `awaiting_preconditions` vs `blocking_preconditions`."""
    reg = _pattern_style_registry()  # nothing observed -- everything PENDING
    report = reg.propagate()
    cmd = _cmd("SEND_PACKET_PORT0", "GLOBAL_READY")
    result = evaluate_command_preconditions(cmd, report)
    assert result.status == CommandDispatchStatus.BLOCKED.value
    assert result.blocking_preconditions == ()
    assert result.awaiting_preconditions == ("GLOBAL_READY",)
    check = result.checks[0]
    assert check.known is True
    assert check.effective_status == EventStatus.PENDING.value
    assert "not yet FIRED" in result.reason


# ---------------------------------------------------------------------------
# negative controls -- UNKNOWN_PRECONDITION (never silently READY)
# ---------------------------------------------------------------------------

def test_unresolved_precondition_name_is_reported_unknown_never_ready():
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:10"),
    })
    report = reg.propagate()
    cmd = _cmd("CONFIGURE_PHY", "GLOBAL_READY", "PHY_READY")  # PHY_READY not declared in this registry
    result = evaluate_command_preconditions(cmd, report)
    assert result.status == CommandDispatchStatus.UNKNOWN_PRECONDITION.value
    assert result.unresolved_preconditions == ("PHY_READY",)
    check = next(c for c in result.checks if c.precondition_name == "PHY_READY")
    assert check.known is False
    assert check.effective_status is None
    assert "never assumed satisfied" in result.reason


def test_blocked_outranks_unknown_precondition_when_both_present():
    """A command declaring one genuinely FAILED precondition AND one
    unresolved-name precondition must read BLOCKED overall (real evidence of
    failure outranks mere absence of information), while the unresolved
    finding is still named in the per-precondition detail rather than lost."""
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:42"),
    })
    report = reg.propagate()
    cmd = _cmd("CONFIGURE_PHY", "GLOBAL_READY", "PHY_READY")
    result = evaluate_command_preconditions(cmd, report)
    assert result.status == CommandDispatchStatus.BLOCKED.value
    assert result.blocking_preconditions == ("GLOBAL_READY",)
    assert result.unresolved_preconditions == ("PHY_READY",)
    assert "unresolved" in result.reason


# ---------------------------------------------------------------------------
# negative controls -- declaration-level errors
# ---------------------------------------------------------------------------

def test_blank_command_id_is_refused():
    with pytest.raises(CommandPreconditionGateError, match="non-empty command_id"):
        CommandPreconditionDeclaration(command_id="", preconditions=("GLOBAL_READY",))


def test_blank_precondition_name_is_refused():
    with pytest.raises(CommandPreconditionGateError, match="blank precondition name"):
        CommandPreconditionDeclaration(command_id="X", preconditions=("GLOBAL_READY", "  "))


def test_duplicate_precondition_name_is_refused():
    with pytest.raises(CommandPreconditionGateError, match="duplicate precondition name"):
        CommandPreconditionDeclaration(command_id="X", preconditions=("GLOBAL_READY", "GLOBAL_READY"))


def test_commands_from_dict_rejects_non_mapping():
    with pytest.raises(CommandPreconditionGateError, match="must be a JSON object"):
        commands_from_dict([])  # type: ignore[arg-type]


def test_commands_from_dict_rejects_empty_commands_list():
    with pytest.raises(CommandPreconditionGateError, match="no non-empty 'commands' list"):
        commands_from_dict({"commands": []})


def test_load_commands_missing_file_is_refused(tmp_path):
    with pytest.raises(CommandPreconditionGateError, match="not found"):
        load_commands(tmp_path / "does_not_exist.json")


def test_load_commands_invalid_json_is_refused(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CommandPreconditionGateError, match="not valid JSON"):
        load_commands(path)


# ---------------------------------------------------------------------------
# vocabulary independence from runtime_event_registry.EventStatus
# ---------------------------------------------------------------------------

def test_dispatch_status_vocabulary_does_not_collide_with_event_status():
    event_values = {s.value for s in EventStatus}
    dispatch_values = {s.value for s in CommandDispatchStatus}
    assert not (event_values & dispatch_values)


# ---------------------------------------------------------------------------
# batch evaluation / DispatchGateReport aggregation
# ---------------------------------------------------------------------------

def test_evaluate_dispatch_readiness_aggregates_multiple_commands():
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:10"),
        "DUT_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:55"),
    })
    commands = (
        _cmd("READY_CMD", "GLOBAL_READY", "DUT_READY"),
        _cmd("BLOCKED_CMD", "FW_READY"),  # FW_READY still PENDING (nothing observed)
        _cmd("UNKNOWN_CMD", "PHY_READY"),
    )
    report = evaluate_dispatch_readiness(commands, reg)
    assert report.ready_commands() == ("READY_CMD",)
    assert report.blocked_commands() == ("BLOCKED_CMD",)
    assert report.unknown_precondition_commands() == ("UNKNOWN_CMD",)
    assert report.has_any_blocking_outcome() is True


def test_evaluate_dispatch_readiness_all_ready_has_no_blocking_outcome():
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:10"),
    })
    commands = (_cmd("SIMPLE_CMD", "GLOBAL_READY"),)
    report = evaluate_dispatch_readiness(commands, reg)
    assert report.has_any_blocking_outcome() is False
    assert report.ready_commands() == ("SIMPLE_CMD",)


# ---------------------------------------------------------------------------
# rendering + file I/O + CLI (execute_verb, and a real subprocess entry
# point), never a mock
# ---------------------------------------------------------------------------

def test_render_commands_and_dispatch_gate_are_markdown_tables():
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:42"),
    })
    commands = (_cmd("SEND_PACKET_PORT0", "GLOBAL_READY", source="command.txt:120"),)
    commands_text = render_commands(commands)
    assert "SEND_PACKET_PORT0" in commands_text and "GLOBAL_READY" in commands_text

    report = evaluate_dispatch_readiness(commands, reg)
    status_text = render_dispatch_gate(report)
    assert "BLOCKED" in status_text
    assert "dispatches nothing, runs no build, submits no job, and gates nothing" in status_text


def test_write_report_is_atomic_and_readable_back(tmp_path):
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:10"),
    })
    commands = (_cmd("SEND_PACKET_PORT0", "GLOBAL_READY"),)
    report = evaluate_dispatch_readiness(commands, reg)
    out = write_report(tmp_path, report)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["registry_id"] == reg.registry_id
    assert data["results"][0]["command_id"] == "SEND_PACKET_PORT0"
    assert data["results"][0]["status"] == CommandDispatchStatus.READY.value


def _write_commands_file(tmp_path: Path, commands) -> Path:
    path = tmp_path / "commands.json"
    path.write_text(json.dumps({"commands": [c.to_dict() for c in commands]}), encoding="utf-8")
    return path


def _write_registry_file(tmp_path: Path, name: str, reg: RuntimeEventRegistry) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(reg.to_dict()), encoding="utf-8")
    return path


def test_execute_verb_list_exits_zero(tmp_path):
    commands = (_cmd("SEND_PACKET_PORT0", "GLOBAL_READY"),)
    cpath = _write_commands_file(tmp_path, commands)
    text, code = execute_verb("list", commands_path=str(cpath))
    assert code == 0
    assert "SEND_PACKET_PORT0" in text


def test_execute_verb_check_exits_zero_when_all_ready(tmp_path):
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:10"),
    })
    commands = (_cmd("SEND_PACKET_PORT0", "GLOBAL_READY"),)
    cpath = _write_commands_file(tmp_path, commands)
    rpath = _write_registry_file(tmp_path, "events.json", reg)
    text, code = execute_verb("check", commands_path=str(cpath), registry_path=str(rpath))
    assert code == 0
    assert "READY" in text


def test_execute_verb_check_exits_one_when_blocked(tmp_path):
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:42"),
    })
    commands = (_cmd("SEND_PACKET_PORT0", "GLOBAL_READY"),)
    cpath = _write_commands_file(tmp_path, commands)
    rpath = _write_registry_file(tmp_path, "events.json", reg)
    text, code = execute_verb("check", commands_path=str(cpath), registry_path=str(rpath))
    assert code == 1
    assert "BLOCKED" in text


def test_execute_verb_check_missing_registry_is_usage_error(tmp_path):
    commands = (_cmd("SEND_PACKET_PORT0", "GLOBAL_READY"),)
    cpath = _write_commands_file(tmp_path, commands)
    text, code = execute_verb("check", commands_path=str(cpath), registry_path=None)
    assert code == 2
    assert "requires --registry" in text


def test_execute_verb_missing_commands_path_is_usage_error():
    text, code = execute_verb("check", commands_path=None)
    assert code == 2
    assert "requires --commands" in text


def test_execute_verb_unknown_verb_is_usage_error(tmp_path):
    commands = (_cmd("SEND_PACKET_PORT0", "GLOBAL_READY"),)
    cpath = _write_commands_file(tmp_path, commands)
    text, code = execute_verb("bogus", commands_path=str(cpath))
    assert code == 2
    assert "unknown command-precondition-gate verb" in text


def test_execute_verb_bad_commands_declaration_is_reported_not_raised(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"commands": [{"command_id": "", "preconditions": []}]}), encoding="utf-8")
    text, code = execute_verb("list", commands_path=str(path))
    assert code == 2
    assert "CommandPreconditionGateError" in text


def test_execute_verb_bad_registry_declaration_is_reported_not_raised(tmp_path):
    commands = (_cmd("SEND_PACKET_PORT0", "GLOBAL_READY"),)
    cpath = _write_commands_file(tmp_path, commands)
    rpath = tmp_path / "bad_events.json"
    rpath.write_text(json.dumps({"registry_id": "bad", "events": []}), encoding="utf-8")
    text, code = execute_verb("check", commands_path=str(cpath), registry_path=str(rpath))
    assert code == 2
    assert "EventRegistryError" in text


def test_cli_subprocess_check_real_exit_code(tmp_path):
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:42"),
    })
    commands = (_cmd("SEND_PACKET_PORT0", "GLOBAL_READY"),)
    cpath = _write_commands_file(tmp_path, commands)
    rpath = _write_registry_file(tmp_path, "events.json", reg)
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.command_precondition_gate", "check",
         "--commands", str(cpath), "--registry", str(rpath), "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["results"][0]["status"] == CommandDispatchStatus.BLOCKED.value


def test_cli_subprocess_list_real_exit_code(tmp_path):
    commands = (_cmd("SEND_PACKET_PORT0", "GLOBAL_READY"),)
    cpath = _write_commands_file(tmp_path, commands)
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.command_precondition_gate", "list", "--commands", str(cpath)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "SEND_PACKET_PORT0" in result.stdout
