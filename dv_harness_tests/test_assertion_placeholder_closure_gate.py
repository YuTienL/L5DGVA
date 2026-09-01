"""Tests for tools/verification_flow/assertion_placeholder_closure_gate.py
(STAGE_GATES["VERIFICATION_ARCHITECTURE"], checker-sva-generator task,
2026-09-01).

Confirms the one narrow check the design report assigns this gate: FAIL
when any implementation_manifest.json "assertion_entries[]" row classified
"PROTOCOL_STATE_MACHINE_LEGALITY" still shows
"generation_method": "placeholder"; PASS otherwise, including when
"classification" is absent/None (Q2/Q3/hand-authored territory this gate
deliberately does not police) or when a PROTOCOL_STATE_MACHINE_LEGALITY
entry is already real DSL output.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "assertion_placeholder_closure_gate.py"


def _run(implementation: dict):
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "implementation_manifest.json"
    path.write_text(json.dumps(implementation), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--implementation", str(path)],
        capture_output=True, text=True, timeout=15,
    )
    return r.returncode, json.loads(r.stdout)


def test_help_smoke():
    r = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                        capture_output=True, text=True, timeout=15)
    assert r.returncode == 0
    assert r.stdout.strip()


def test_pass_when_no_assertion_entries():
    code, out = _run({"assertion_entries": []})
    assert code == 0
    assert out["status"] == "PASS"


def test_pass_when_legality_entry_is_real_dsl_output():
    code, out = _run({"assertion_entries": [
        {"target_id": "obs_001", "classification": "PROTOCOL_STATE_MACHINE_LEGALITY",
         "generation_method": "state_machine_checks_dsl:valid_transition_table"},
    ]})
    assert code == 0
    assert out["status"] == "PASS"


def test_pass_when_placeholder_entry_is_unclassified():
    code, out = _run({"assertion_entries": [
        {"target_id": "obs_002", "classification": None, "generation_method": "placeholder"},
    ]})
    assert code == 0
    assert out["status"] == "PASS"


def test_pass_when_placeholder_entry_is_a_different_classification():
    code, out = _run({"assertion_entries": [
        {"target_id": "obs_003", "classification": "INTERRUPT_RESPONSE_SEMANTIC",
         "generation_method": "placeholder"},
    ]})
    assert code == 0
    assert out["status"] == "PASS"


def test_fail_when_legality_entry_still_placeholder():
    code, out = _run({"assertion_entries": [
        {"target_id": "obs_004", "classification": "PROTOCOL_STATE_MACHINE_LEGALITY",
         "generation_method": "placeholder"},
    ]})
    assert code == 2
    assert out["status"] == "FAIL"
    assert out["reason"] == "STATE_MACHINE_LEGALITY_ASSERTION_STILL_PLACEHOLDER"
    assert out["unresolved_target_ids"] == ["obs_004"]


def test_fail_lists_every_unresolved_entry():
    code, out = _run({"assertion_entries": [
        {"target_id": "obs_005", "classification": "PROTOCOL_STATE_MACHINE_LEGALITY",
         "generation_method": "placeholder"},
        {"target_id": "obs_006", "classification": "PROTOCOL_STATE_MACHINE_LEGALITY",
         "generation_method": "state_machine_checks_dsl:legal_value_set"},
        {"target_id": "obs_007", "classification": "PROTOCOL_STATE_MACHINE_LEGALITY",
         "generation_method": "placeholder"},
    ]})
    assert code == 2
    assert out["unresolved_target_ids"] == ["obs_005", "obs_007"]
