"""Tests for the command-semantic-parser-wiring task (2026-09-01).

command_semantic_expectation_parser.py was a real, correct, deterministic
command.txt-intent extractor that was orphaned: referenced only from the
non-executed documentation registry
.dv-harness/workflow/verification_flow_v13.json, never invoked by the live
STAGE_GATES chain that performs command.txt-vs-sim.log TRUE_PASS semantic
verification (simulation_semantic_validation_gate.py +
simulation_semantic_trace_gate.py).

RULING (documented in .work/command-semantic-parser-wiring-implementation-
report.md): the two live gates do NOT already re-derive command.txt intent
some other real way -- "command_expectations" was pure agent-attested JSON,
never cross-checked against an actual parse of command.txt anywhere in the
live chain (command_intent_semantic_closure_gate, the other VERIFY-stage
gate that sounds related, only compares two agent-self-reported strings to
each other). So per the task's own decision procedure this is option (a):
simulation_semantic_validation_gate.py now imports and invokes the real
parser directly, in-process, as part of computing its own semantic verdict,
via a new OPTIONAL 'command_file_path' evidence field (same "read a real
file from disk when a path is supplied" pattern already used for
'sim_log_path'). Omitting the field is byte-for-byte identical to the
pre-fix gate -- these tests cover both the new behavior and that backward
compatibility guarantee.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PARSER_SCRIPT = ROOT / "tools" / "verification_flow" / "command_semantic_expectation_parser.py"
VALIDATION_GATE_SCRIPT = ROOT / "tools" / "verification_flow" / "simulation_semantic_validation_gate.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


parser_mod = _load_module(PARSER_SCRIPT, "command_semantic_expectation_parser")
gate_mod = _load_module(VALIDATION_GATE_SCRIPT, "simulation_semantic_validation_gate")

# One realistic command.txt line exercising protocol/operation/attribute/
# outcome extraction plus the implied CONTRADICTION set (see parse_line's
# success_requested branch).
COMMAND_LINE = "testcase_id=T1 vplan=V1 protocol=usb operation=reset expect=success port=0"

# The full, exact set of (pattern, match_mode) pairs command_semantic_
# expectation_parser.parse_line() deterministically derives for COMMAND_LINE
# -- traced by hand against the real regex rules in the parser (protocol=usb
# token match, operation=reset token match, the two ATTRIBUTE kv pairs
# actually present -- port and expect, not addr/data/etc -- and the
# expect=success-triggered OUTCOME + CONTRADICTION set).
DERIVED_REQS = {("usb", "TOKEN"), ("reset", "TOKEN"), ("port=0", "TOKEN"),
                ("expect=success", "TOKEN"), ("success", "TOKEN")}
DERIVED_ANTI = {("failed", "TOKEN"), ("timeout", "TOKEN")}

SIM_LOG_MATCHING_ALL = "UVM_INFO: usb reset port=0 expect=success completed"


def _full_agent_expectation(expectation_id="e1", source_line=1):
    return {
        "expectation_id": expectation_id,
        "source_file": "command.txt",
        "source_line": source_line,
        "testcase_id": "T1",
        "required": True,
        "evidence_requirements": [{"pattern": p, "match_mode": m} for p, m in sorted(DERIVED_REQS)],
        "contradiction_requirements": [{"pattern": p, "match_mode": m} for p, m in sorted(DERIVED_ANTI)],
    }


def _write_command_file(tmp: Path, text: str) -> Path:
    p = tmp / "command.txt"
    p.write_text(text, encoding="utf-8")
    return p


def _run_gate_script(payload: dict):
    tmp = Path(tempfile.mkdtemp())
    try:
        input_path = tmp / "input.json"
        input_path.write_text(json.dumps(payload), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(VALIDATION_GATE_SCRIPT), "--input", str(input_path)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        return proc.returncode, json.loads(proc.stdout.strip())
    finally:
        shutil.rmtree(tmp)


# --- command_semantic_expectation_parser.py: previously-untested, now the
# actively-invoked real extractor -----------------------------------------

def test_parser_extracts_protocol_operation_attribute_and_outcome():
    parsed = parser_mod.parse_line(COMMAND_LINE, 1)
    assert parsed is not None
    assert parsed["protocol"] == "USB"
    assert parsed["operation"] == "RESET"
    assert parsed["testcase_id"] == "T1"
    assert parsed["vplan_ids"] == ["V1"]
    got_reqs = {(r["pattern"].lower(), r["match_mode"]) for r in parsed["evidence_requirements"]}
    got_anti = {(r["pattern"].lower(), r["match_mode"]) for r in parsed["contradiction_requirements"]}
    assert got_reqs == DERIVED_REQS
    assert got_anti == DERIVED_ANTI


def test_parser_returns_none_for_blank_and_comment_lines():
    assert parser_mod.parse_line("", 1) is None
    assert parser_mod.parse_line("   ", 2) is None
    assert parser_mod.parse_line("# a comment", 3) is None


def test_parser_cli_smoke_exits_zero_on_real_command_file():
    tmp = Path(tempfile.mkdtemp())
    try:
        cf = _write_command_file(tmp, COMMAND_LINE + "\n")
        proc = subprocess.run(
            [sys.executable, str(PARSER_SCRIPT), "--command-file", str(cf)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert len(out["expectations"]) == 1
        assert out["expectations"][0]["source_line"] == 1
    finally:
        shutil.rmtree(tmp)


# --- simulation_semantic_validation_gate.py: the real wiring -------------

def test_cross_check_passes_when_agent_expectations_cover_command_txt():
    tmp = Path(tempfile.mkdtemp())
    try:
        cf = _write_command_file(tmp, COMMAND_LINE + "\n")
        error, under_reported = gate_mod.cross_check_against_command_file(
            str(cf), [_full_agent_expectation()]
        )
        assert error is None
        assert under_reported == []
    finally:
        shutil.rmtree(tmp)


def test_cross_check_flags_under_reported_operation_pattern():
    tmp = Path(tempfile.mkdtemp())
    try:
        cf = _write_command_file(tmp, COMMAND_LINE + "\n")
        thin = _full_agent_expectation()
        # Drop the deterministic OPERATION requirement ("reset") -- an agent
        # quietly reporting a weaker set than the real command.txt line
        # requires must be caught, not silently accepted.
        thin["evidence_requirements"] = [
            r for r in thin["evidence_requirements"] if r["pattern"] != "reset"
        ]
        error, under_reported = gate_mod.cross_check_against_command_file(str(cf), [thin])
        assert error is None
        assert len(under_reported) == 1
        assert under_reported[0]["source_line"] == 1
        assert "reset|TOKEN" in under_reported[0]["missing_evidence_requirements"]
    finally:
        shutil.rmtree(tmp)


def test_cross_check_flags_missing_contradiction_requirement():
    tmp = Path(tempfile.mkdtemp())
    try:
        cf = _write_command_file(tmp, COMMAND_LINE + "\n")
        thin = _full_agent_expectation()
        thin["contradiction_requirements"] = [
            r for r in thin["contradiction_requirements"] if r["pattern"] != "timeout"
        ]
        error, under_reported = gate_mod.cross_check_against_command_file(str(cf), [thin])
        assert error is None
        assert "timeout|TOKEN" in under_reported[0]["missing_contradiction_requirements"]
    finally:
        shutil.rmtree(tmp)


def test_cross_check_ignores_lines_agent_never_mapped_a_source_line_to():
    # A command.txt line the deterministic parser derives real requirements
    # for, but the agent's command_expectations array has NO entry at all
    # for that source_line, must still be flagged -- it is exactly as
    # under-reported as an entry that omits individual patterns.
    tmp = Path(tempfile.mkdtemp())
    try:
        cf = _write_command_file(tmp, COMMAND_LINE + "\n")
        error, under_reported = gate_mod.cross_check_against_command_file(str(cf), [])
        assert error is None
        assert len(under_reported) == 1
        assert under_reported[0]["source_line"] == 1
    finally:
        shutil.rmtree(tmp)


def test_cross_check_fails_closed_on_missing_command_file():
    error, under_reported = gate_mod.cross_check_against_command_file(
        "/definitely/does/not/exist/command.txt", [_full_agent_expectation()]
    )
    assert error is not None
    assert error[0] == "COMMAND_FILE_PATH_NOT_FOUND"
    assert under_reported == []


def test_gate_main_passes_when_command_file_path_supplied_and_covered():
    tmp = Path(tempfile.mkdtemp())
    try:
        cf = _write_command_file(tmp, COMMAND_LINE + "\n")
        payload = {
            "simulation_passed": True,
            "sim_log": SIM_LOG_MATCHING_ALL,
            "command_file_path": str(cf),
            "command_expectations": [_full_agent_expectation()],
        }
        rc, out = _run_gate_script(payload)
        assert rc == 0, out
        assert out["status"] == "PASS"
        assert out["final_state"] == "TRUE_PASS"
    finally:
        shutil.rmtree(tmp)


def test_gate_main_fails_closed_when_command_expectations_under_report():
    tmp = Path(tempfile.mkdtemp())
    try:
        cf = _write_command_file(tmp, COMMAND_LINE + "\n")
        thin = _full_agent_expectation()
        thin["evidence_requirements"] = [
            r for r in thin["evidence_requirements"] if r["pattern"] != "reset"
        ]
        payload = {
            "simulation_passed": True,
            "sim_log": SIM_LOG_MATCHING_ALL,
            "command_file_path": str(cf),
            "command_expectations": [thin],
        }
        rc, out = _run_gate_script(payload)
        assert rc == 9
        assert out["status"] == "FAIL"
        assert out["final_state"] == "COMMAND_TXT_INTENT_UNDER_REPORTED"
        assert out["under_reported"][0]["source_line"] == 1
    finally:
        shutil.rmtree(tmp)


def test_gate_main_fails_closed_on_bad_command_file_path():
    payload = {
        "simulation_passed": True,
        "sim_log": SIM_LOG_MATCHING_ALL,
        "command_file_path": "/definitely/does/not/exist/command.txt",
        "command_expectations": [_full_agent_expectation()],
    }
    rc, out = _run_gate_script(payload)
    assert rc == 8
    assert out["status"] == "FAIL"
    assert "COMMAND_FILE_PATH_NOT_FOUND" in out["reason"]


def test_gate_main_backward_compatible_when_command_file_path_absent():
    # Byte-identical behavior guarantee: the pre-existing contract (no new
    # field) must still PASS exactly as it did before this wiring fix, even
    # though the agent's command_expectations here would NOT satisfy the
    # deterministic cross-check (there is no real command.txt at all).
    payload = {
        "simulation_passed": True,
        "sim_log": "UVM_INFO enum PASS",
        "command_expectations": [{
            "expectation_id": "e1", "required": True,
            "evidence_requirements": [{"pattern": "enum PASS", "match_mode": "SUBSTRING"}],
        }],
    }
    rc, out = _run_gate_script(payload)
    assert rc == 0
    assert out["status"] == "PASS"
    assert out["final_state"] == "TRUE_PASS"


# --- Live STAGE_GATES chain: prove the wiring actually reaches
# evaluate_stage_evidence(), not just the script in isolation ---------------

def test_live_verify_stage_chain_invokes_real_parser_and_fails_on_underreport():
    from dv_harness.gates import evaluate_stage_evidence
    # Reuse the already-verified VERIFY-stage fixture set from
    # test_engine_gates_and_routing.py (every other mandatory VERIFY gate's
    # evidence, PASS-shaped) so this test isolates the ONE new behavior:
    # simulation_semantic_validation_gate now genuinely fails a
    # command_expectations block that under-reports a REAL command.txt on
    # disk, through the exact same STAGE_GATES/run_gate() path production
    # traffic uses -- not a hand-rolled reimplementation of that path.
    from dv_harness_tests.test_engine_gates_and_routing import _VERIFY_EXTRA_GATES

    tmp = Path(tempfile.mkdtemp())
    try:
        cf = _write_command_file(tmp, COMMAND_LINE + "\n")
        transcript_path = tmp / "verify.txt"
        transcript_path.write_text("REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\nVerification passed\n")
        verify_extra_with_transcript = _VERIFY_EXTRA_GATES.replace(
            '```dv-harness-evidence:remote_execution_provenance_gate\n{"transcript_path": "/tmp/verify.txt", "claimed_exit_code": 0}\n```\n',
            '```dv-harness-evidence:remote_execution_provenance_gate\n'
            + json.dumps({"transcript_path": str(transcript_path), "claimed_exit_code": 0}) + '\n```\n'
        )

        thin = _full_agent_expectation()
        thin["evidence_requirements"] = [
            r for r in thin["evidence_requirements"] if r["pattern"] != "reset"
        ]
        sim_block = {
            "simulation_passed": True,
            "sim_log": SIM_LOG_MATCHING_ALL,
            "command_file_path": str(cf),
            "command_expectations": [thin],
        }
        text = (
            "```dv-harness-evidence:simulation_semantic_validation_gate\n"
            + json.dumps(sim_block) + "\n```\n"
            "```dv-harness-evidence:test_result_provenance_gate\n"
            '{"results": [{"testcase_id": "t1", "run_id": "r1", "rtl_revision": "a", '
            '"tb_revision": "b", "vip_version": "c", "tool_version": "d", "seed": "1", '
            '"config_hash": "h", "result": "PASS", "log_hash": "lh", "evidence_bundle_hash": "eh"}]}\n'
            "```\n"
            "```dv-harness-evidence:false_pass_resistance_gate\n"
            '{"positive_test_pass": true, "negative_test_detects_fault": true, '
            '"checker_detects_injected_fault": true, "semantic_log_match": true, '
            '"oracle_independent": true, "proof_bundle_hash": "h1"}\n'
            "```\n"
            + verify_extra_with_transcript
        )
        verdict, reasons = evaluate_stage_evidence(ROOT, "VERIFY", text)
        assert verdict == "GATE_FAIL"
        assert any("COMMAND_TXT_INTENT_UNDER_REPORTED" in r for r in reasons)
    finally:
        shutil.rmtree(tmp)
