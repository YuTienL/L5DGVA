"""Tests for dv_harness/de_command_runtime_readiness_gate.py -- the composite
DE_COMMAND_RUNTIME_READY verdict over real runtime_event_registry state, real
command_precondition_gate results, and a caller-supplied duck-typed
branch/grammar-side result set."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.runtime_event_registry import (
    EventRelationDecl,
    EventRelationType,
    EventStatus,
    RuntimeEventDef,
    RuntimeEventObservation,
    RuntimeEventRegistry,
)
from dv_harness.command_precondition_gate import CommandPreconditionDeclaration
from dv_harness.de_command_runtime_readiness_gate import (
    DE_COMMAND_RUNTIME_BLOCKED,
    DE_COMMAND_RUNTIME_PASS,
    DECommandRuntimeReadinessError,
    evaluate_de_command_runtime_readiness,
    execute_verb,
    render_readiness,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _clean_registry() -> RuntimeEventRegistry:
    """A small registry matching this repo's own illustrative
    block(GLOBAL_READY)/branch_a*(DUT_READY)/branch_fw(IRQ_SEEN/IRQ_SERVICED)/
    branch_b*(VIP_STARTED) vocabulary, every event FIRED with real evidence."""
    return RuntimeEventRegistry(
        registry_id="clean_registry",
        events=(
            RuntimeEventDef("GLOBAL_READY", producer="block", consumer=("branch_a0",)),
            RuntimeEventDef("DUT_READY", producer="branch_a0", consumer=("branch_fw0",)),
            RuntimeEventDef("VIP_STARTED", producer="branch_b0", consumer=("check",)),
        ),
        relations=(
            EventRelationDecl("DUT_READY", EventRelationType.REQUIRES, "GLOBAL_READY"),
        ),
        observations={
            "GLOBAL_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:10"),
            "DUT_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:20"),
            "VIP_STARTED": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:30"),
        },
    )


def _clean_commands() -> tuple:
    return (
        CommandPreconditionDeclaration("CPUWRITE1B", preconditions=("GLOBAL_READY", "DUT_READY")),
        CommandPreconditionDeclaration("VIP_SEQ_START", preconditions=("VIP_STARTED",)),
    )


def _clean_branch_grammar() -> list:
    return [
        {"command_id": "CPUWRITE1B", "status": "VALID"},
        {"command_id": "VIP_SEQ_START", "status": "PASS", "reason": "branch ownership resolved"},
    ]


# ---------------------------------------------------------------------------
# core positive path
# ---------------------------------------------------------------------------

def test_all_clean_inputs_produce_pass():
    report = evaluate_de_command_runtime_readiness(
        _clean_registry(), _clean_commands(), _clean_branch_grammar())
    assert report.status == DE_COMMAND_RUNTIME_PASS
    assert not report.has_blocking_outcome()
    assert report.event_registry_blockers == ()
    assert report.command_precondition_blockers == ()
    assert report.branch_grammar_blockers == ()
    assert report.branch_grammar_supplied is True
    assert "PASS" in report.reason
    d = report.to_dict()
    assert d["status"] == "PASS"
    assert len(d["command_precondition_results"]) == 2


def test_zero_commands_and_no_branch_grammar_is_legal_and_passes():
    report = evaluate_de_command_runtime_readiness(_clean_registry(), (), None)
    assert report.status == DE_COMMAND_RUNTIME_PASS
    assert report.branch_grammar_supplied is False
    assert report.branch_grammar_checks == ()
    assert "no branch/grammar-side results were supplied" in report.reason


def test_propagate_is_called_exactly_once_regardless_of_command_count(monkeypatch):
    registry = _clean_registry()
    calls = {"n": 0}
    real_propagate = registry.propagate

    def _counting_propagate():
        calls["n"] += 1
        return real_propagate()

    monkeypatch.setattr(registry, "propagate", _counting_propagate)
    many_commands = tuple(
        CommandPreconditionDeclaration(f"CMD_{i}", preconditions=("GLOBAL_READY",))
        for i in range(5)
    )
    report = evaluate_de_command_runtime_readiness(registry, many_commands, None)
    assert report.status == DE_COMMAND_RUNTIME_PASS
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# negative controls: runtime_event_registry state
# ---------------------------------------------------------------------------

def test_a_real_failed_event_blocks_even_with_no_declaring_command():
    """GLOBAL_READY FAILED for real, but no command declares it as a
    precondition at all -- the composite must still catch it as a runtime
    event blocker, proving this is genuinely an independent input and not
    merely a re-statement of the command-precondition check."""
    registry = RuntimeEventRegistry(
        registry_id="failed_event_registry",
        events=(RuntimeEventDef("GLOBAL_READY", producer="block", consumer=("branch_a0",)),),
        observations={"GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:5")},
    )
    commands = (CommandPreconditionDeclaration("UNRELATED_CMD", preconditions=()),)
    report = evaluate_de_command_runtime_readiness(registry, commands, None)
    assert report.status == DE_COMMAND_RUNTIME_BLOCKED
    assert len(report.event_registry_blockers) == 1
    assert report.event_registry_blockers[0]["event_name"] == "GLOBAL_READY"
    assert report.event_registry_blockers[0]["effective_status"] == "FAILED"
    assert "GLOBAL_READY" in report.reason


def test_blocked_by_dependency_propagation_is_reported_with_real_reason():
    registry = RuntimeEventRegistry(
        registry_id="dependency_registry",
        events=(
            RuntimeEventDef("GLOBAL_READY", producer="block", consumer=("branch_a0",)),
            RuntimeEventDef("DUT_READY", producer="branch_a0", consumer=("branch_fw0",)),
        ),
        relations=(EventRelationDecl("DUT_READY", EventRelationType.REQUIRES, "GLOBAL_READY"),),
        observations={"GLOBAL_READY": RuntimeEventObservation(EventStatus.TIMEOUT, evidence="sim.log:5")},
    )
    report = evaluate_de_command_runtime_readiness(registry, (), None)
    assert report.status == DE_COMMAND_RUNTIME_BLOCKED
    names = {b["event_name"] for b in report.event_registry_blockers}
    assert names == {"GLOBAL_READY", "DUT_READY"}
    dut = next(b for b in report.event_registry_blockers if b["event_name"] == "DUT_READY")
    assert dut["effective_status"] == "BLOCKED_BY_DEPENDENCY"
    assert "REQUIRES" in dut["reason"]


# ---------------------------------------------------------------------------
# negative controls: command_precondition_gate results
# ---------------------------------------------------------------------------

def test_a_still_pending_precondition_blocks_the_command():
    registry = RuntimeEventRegistry(
        registry_id="pending_registry",
        events=(RuntimeEventDef("VIP_STARTED", producer="branch_b0", consumer=("check",)),),
        observations={},  # VIP_STARTED stays PENDING -- nothing observed yet
    )
    commands = (CommandPreconditionDeclaration("VIP_SEQ_START", preconditions=("VIP_STARTED",)),)
    report = evaluate_de_command_runtime_readiness(registry, commands, None)
    assert report.status == DE_COMMAND_RUNTIME_BLOCKED
    assert len(report.command_precondition_blockers) == 1
    b = report.command_precondition_blockers[0]
    assert b["command_id"] == "VIP_SEQ_START"
    assert b["status"] == "BLOCKED"


def test_an_unresolved_precondition_name_is_unknown_precondition_and_blocks():
    registry = RuntimeEventRegistry(
        registry_id="unknown_precondition_registry",
        events=(RuntimeEventDef("GLOBAL_READY", producer="block", consumer=("branch_a0",)),),
        observations={"GLOBAL_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:1")},
    )
    commands = (CommandPreconditionDeclaration("CMD_X", preconditions=("NO_SUCH_EVENT",)),)
    report = evaluate_de_command_runtime_readiness(registry, commands, None)
    assert report.status == DE_COMMAND_RUNTIME_BLOCKED
    b = report.command_precondition_blockers[0]
    assert b["status"] == "UNKNOWN_PRECONDITION"


# ---------------------------------------------------------------------------
# negative controls: duck-typed branch/grammar-side results
# ---------------------------------------------------------------------------

def test_an_invalid_branch_grammar_result_blocks_and_names_the_real_status():
    registry = _clean_registry()
    branch_grammar = [{"command_id": "CPUWRITE1B", "status": "INVALID",
                        "reason": "VIP-driven work assigned to branch_a0"}]
    report = evaluate_de_command_runtime_readiness(registry, _clean_commands(), branch_grammar)
    assert report.status == DE_COMMAND_RUNTIME_BLOCKED
    assert len(report.branch_grammar_blockers) == 1
    b = report.branch_grammar_blockers[0]
    assert b["identifier"] == "CPUWRITE1B"
    assert b["status_value"] == "INVALID"
    assert "VIP-driven work assigned to branch_a0" in b["reason"]


def test_a_branch_grammar_result_with_no_status_field_never_assumed_passing():
    registry = _clean_registry()
    branch_grammar = [{"command_id": "CPUWRITE1B", "note": "no status here at all"}]
    report = evaluate_de_command_runtime_readiness(registry, _clean_commands(), branch_grammar)
    assert report.status == DE_COMMAND_RUNTIME_BLOCKED
    b = report.branch_grammar_blockers[0]
    assert b["status_value"] is None
    assert "no status field found" in b["reason"]


def test_an_unrecognized_pass_looking_word_is_never_silently_accepted():
    """'GREAT' is not in BRANCH_GRAMMAR_PASS_STATUSES -- a genuinely fine but
    oddly-spelled status must still be reported as a blocker per the module's
    stated false-positive-tolerant, false-negative-intolerant bias."""
    registry = _clean_registry()
    branch_grammar = [{"command_id": "CPUWRITE1B", "status": "GREAT"}]
    report = evaluate_de_command_runtime_readiness(registry, _clean_commands(), branch_grammar)
    assert report.status == DE_COMMAND_RUNTIME_BLOCKED
    assert report.branch_grammar_blockers[0]["status_value"] == "GREAT"


def test_branch_grammar_results_as_a_mapping_of_identifier_to_status():
    registry = _clean_registry()
    branch_grammar = {"CPUWRITE1B": "VALID", "VIP_SEQ_START": "AMBIGUOUS"}
    report = evaluate_de_command_runtime_readiness(registry, _clean_commands(), branch_grammar)
    assert report.status == DE_COMMAND_RUNTIME_BLOCKED
    assert len(report.branch_grammar_checks) == 2
    blocked_ids = {b["identifier"] for b in report.branch_grammar_blockers}
    assert blocked_ids == {"VIP_SEQ_START"}


def test_branch_grammar_results_as_a_mapping_with_results_key():
    registry = _clean_registry()
    branch_grammar = {"results": [{"command_id": "CPUWRITE1B", "status": "VALID"}]}
    report = evaluate_de_command_runtime_readiness(registry, (_clean_commands()[0],), branch_grammar)
    assert report.status == DE_COMMAND_RUNTIME_PASS


def test_a_non_mapping_record_in_the_list_is_a_blocker_not_a_crash():
    registry = _clean_registry()
    branch_grammar = ["not-a-record"]
    report = evaluate_de_command_runtime_readiness(registry, (), branch_grammar)
    assert report.status == DE_COMMAND_RUNTIME_BLOCKED
    assert "not a JSON object" in report.branch_grammar_blockers[0]["reason"]


def test_malformed_branch_grammar_results_shape_is_refused():
    registry = _clean_registry()
    with pytest.raises(DECommandRuntimeReadinessError):
        evaluate_de_command_runtime_readiness(registry, (), "just-a-string")
    with pytest.raises(DECommandRuntimeReadinessError):
        evaluate_de_command_runtime_readiness(registry, (), {"results": "not-a-list"})


def test_multiple_blockers_across_all_three_sources_are_all_named():
    registry = RuntimeEventRegistry(
        registry_id="multi_blocker_registry",
        events=(
            RuntimeEventDef("GLOBAL_READY", producer="block", consumer=("branch_a0",)),
            RuntimeEventDef("VIP_STARTED", producer="branch_b0", consumer=("check",)),
        ),
        observations={"GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:1")},
    )
    commands = (CommandPreconditionDeclaration("VIP_SEQ_START", preconditions=("VIP_STARTED",)),)
    branch_grammar = [{"command_id": "VIP_SEQ_START", "status": "INVALID"}]
    report = evaluate_de_command_runtime_readiness(registry, commands, branch_grammar)
    assert report.status == DE_COMMAND_RUNTIME_BLOCKED
    assert len(report.event_registry_blockers) == 1
    assert len(report.command_precondition_blockers) == 1
    assert len(report.branch_grammar_blockers) == 1
    assert "runtime event(s) blocking" in report.reason
    assert "command(s) not READY" in report.reason
    assert "branch/grammar-side result(s) blocking" in report.reason


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def test_render_readiness_produces_markdown_with_verdict_and_tables():
    report = evaluate_de_command_runtime_readiness(
        _clean_registry(), _clean_commands(), _clean_branch_grammar())
    text = render_readiness(report)
    assert "DE_COMMAND_RUNTIME_READY: PASS" in text
    assert "## Runtime Event Blockers" in text
    assert "## Command Precondition Results" in text
    assert "## Branch/Grammar-Side Results" in text


# ---------------------------------------------------------------------------
# CLI (execute_verb) over real declared JSON files
# ---------------------------------------------------------------------------

def _write_registry_file(tmp_path: Path, registry: RuntimeEventRegistry) -> Path:
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(registry.to_dict()), encoding="utf-8")
    return p


def _write_commands_file(tmp_path: Path, commands: tuple) -> Path:
    p = tmp_path / "commands.json"
    p.write_text(json.dumps({"commands": [c.to_dict() for c in commands]}), encoding="utf-8")
    return p


def _write_branch_grammar_file(tmp_path: Path, data) -> Path:
    p = tmp_path / "branch_grammar.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_execute_verb_check_exits_0_on_a_real_clean_declaration(tmp_path):
    registry_path = _write_registry_file(tmp_path, _clean_registry())
    commands_path = _write_commands_file(tmp_path, _clean_commands())
    branch_path = _write_branch_grammar_file(tmp_path, _clean_branch_grammar())
    text, code = execute_verb(
        "check", root=str(tmp_path), registry_path=str(registry_path),
        commands_path=str(commands_path), branch_grammar_path=str(branch_path), as_json=True)
    assert code == 0
    parsed = json.loads(text)
    assert parsed["status"] == "PASS"


def test_execute_verb_check_exits_1_on_a_real_blocked_declaration(tmp_path):
    registry = RuntimeEventRegistry(
        registry_id="cli_blocked_registry",
        events=(RuntimeEventDef("GLOBAL_READY", producer="block", consumer=("branch_a0",)),),
        observations={"GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:9")},
    )
    registry_path = _write_registry_file(tmp_path, registry)
    text, code = execute_verb("check", root=str(tmp_path), registry_path=str(registry_path), as_json=True)
    assert code == 1
    parsed = json.loads(text)
    assert parsed["status"] == "BLOCKED"


def test_execute_verb_check_exits_2_on_a_bad_registry_path(tmp_path):
    text, code = execute_verb("check", root=str(tmp_path), registry_path=str(tmp_path / "nope.json"))
    assert code == 2


def test_execute_verb_writes_a_real_report_file(tmp_path):
    registry_path = _write_registry_file(tmp_path, _clean_registry())
    out_path = tmp_path / "out" / "report.json"
    text, code = execute_verb(
        "check", root=str(tmp_path), registry_path=str(registry_path), out_path=str(out_path))
    assert code == 0
    assert out_path.exists()
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["status"] == "PASS"


# ---------------------------------------------------------------------------
# the real python -m CLI, as a subprocess
# ---------------------------------------------------------------------------

def test_module_cli_subprocess_exit_codes(tmp_path):
    registry_path = _write_registry_file(tmp_path, _clean_registry())
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.de_command_runtime_readiness_gate", "check",
         "--registry", str(registry_path), "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(proc.stdout)
    assert parsed["status"] == "PASS"


# ---------------------------------------------------------------------------
# the STAGE_GATES wrapper script under tools/verification_flow, as a real
# subprocess (never imported in-process, matching the real gates.py contract)
# ---------------------------------------------------------------------------

def _run_wrapper(evidence: dict, tmp_path: Path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    script = REPO_ROOT / "tools" / "verification_flow" / "de_command_runtime_readiness_gate.py"
    env = {"DV_HARNESS_PACKAGE_ROOT": str(REPO_ROOT), **__import__("os").environ}
    proc = subprocess.run(
        [sys.executable, str(script), "--runtime-readiness", str(evidence_path)],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=30, env=env,
    )
    return proc


def test_wrapper_script_passes_on_a_real_clean_evidence_block(tmp_path):
    evidence = {
        "registry": _clean_registry().to_dict(),
        "commands": [c.to_dict() for c in _clean_commands()],
        "branch_grammar_results": _clean_branch_grammar(),
    }
    proc = _run_wrapper(evidence, tmp_path)
    assert proc.returncode == 0, proc.stderr
    detail = json.loads(proc.stdout)
    assert detail["status"] == "PASS"


def test_wrapper_script_blocks_on_a_real_failed_event(tmp_path):
    registry = RuntimeEventRegistry(
        registry_id="wrapper_blocked_registry",
        events=(RuntimeEventDef("GLOBAL_READY", producer="block", consumer=("branch_a0",)),),
        observations={"GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:1")},
    )
    evidence = {"registry": registry.to_dict()}
    proc = _run_wrapper(evidence, tmp_path)
    assert proc.returncode == 1
    detail = json.loads(proc.stdout)
    assert detail["status"] == "FAIL"


def test_wrapper_script_reports_missing_registry(tmp_path):
    proc = _run_wrapper({"commands": []}, tmp_path)
    assert proc.returncode == 3
    detail = json.loads(proc.stdout)
    assert detail["reason"] == "MISSING_REGISTRY"


def test_wrapper_script_reports_malformed_payload(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text("not json", encoding="utf-8")
    script = REPO_ROOT / "tools" / "verification_flow" / "de_command_runtime_readiness_gate.py"
    env = {"DV_HARNESS_PACKAGE_ROOT": str(REPO_ROOT), **__import__("os").environ}
    proc = subprocess.run(
        [sys.executable, str(script), "--runtime-readiness", str(evidence_path)],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=30, env=env,
    )
    assert proc.returncode == 3
    detail = json.loads(proc.stdout)
    assert detail["reason"] == "MALFORMED_PAYLOAD"
