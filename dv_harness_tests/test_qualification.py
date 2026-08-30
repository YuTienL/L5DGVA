"""Tests for dv_harness/qualification.py -- the canonical qualification-status
vocabulary (see plan-qualification-vocab design pass, 2026-08-28)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import qualification as q

ROOT = Path(__file__).resolve().parents[1]


def test_ladder_matches_the_8_named_tiers_in_order():
    assert q.CANONICAL_LADDER == (
        "BUILDER_AVAILABLE", "EVIDENCE_READY", "ENV_GENERATED", "COMPILE_QUALIFIED",
        "SMOKE_QUALIFIED", "PROTOCOL_QUALIFIED", "REGRESSION_QUALIFIED", "PRODUCTION_QUALIFIED",
    )


def test_policy_json_matches_canonical_ladder_exactly():
    # Drift guard: if this JSON file and the Python ladder ever disagree, the
    # doc has silently gone stale relative to the code (or vice versa).
    policy = json.loads(
        (ROOT / ".dv-harness" / "qualification" / "protocol_qualification_policy.json")
        .read_text(encoding="utf-8")
    )
    assert policy["labels"] == list(q.CANONICAL_LADDER)


def test_is_canonical():
    assert q.is_canonical("PRODUCTION_QUALIFIED") is True
    assert q.is_canonical("NOT_A_REAL_TIER") is False


def test_tier_index_orders_correctly():
    assert q.tier_index("BUILDER_AVAILABLE") == 0
    assert q.tier_index("PRODUCTION_QUALIFIED") == 7
    assert q.tier_index("SMOKE_QUALIFIED") < q.tier_index("REGRESSION_QUALIFIED")
    with pytest.raises(ValueError):
        q.tier_index("NOT_A_REAL_TIER")


@pytest.mark.parametrize("canonical,expected", [
    ("SMOKE_QUALIFIED", "SMOKE_QUALIFIED"),
    ("REGRESSION_QUALIFIED", "REGRESSION_QUALIFIED"),
    ("PRODUCTION_QUALIFIED", "PRODUCTION_QUALIFIED"),
    ("PROTOCOL_QUALIFIED", "SMOKE_QUALIFIED"),  # floor-collapse, see module docstring
])
def test_map_to_system_level_state_valid_tiers(canonical, expected):
    assert q.map_to_system_level_state(canonical) == expected


@pytest.mark.parametrize("below_smoke", ["BUILDER_AVAILABLE", "EVIDENCE_READY", "ENV_GENERATED", "COMPILE_QUALIFIED"])
def test_map_to_system_level_state_rejects_below_smoke(below_smoke):
    with pytest.raises(ValueError):
        q.map_to_system_level_state(below_smoke)


def test_map_to_system_level_state_rejects_non_canonical_value():
    with pytest.raises(ValueError):
        q.map_to_system_level_state("MADE_UP_TIER")


def test_validate_system_level_state():
    assert q.validate_system_level_state("SMOKE_QUALIFIED") is True
    assert q.validate_system_level_state("PRODUCTION_QUALIFIED") is True
    assert q.validate_system_level_state("BUILDER_AVAILABLE") is False
    assert q.validate_system_level_state("garbage") is False


def _run_gate_script(rel_path, flag, payload):
    tmp = Path(tempfile.mkdtemp())
    try:
        infile = tmp / "in.json"
        infile.write_text(json.dumps(payload), encoding="utf-8")
        script = ROOT / "tools" / rel_path
        r = subprocess.run(
            [sys.executable, str(script), flag, str(infile)],
            capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        import shutil
        shutil.rmtree(tmp)


def _base_protocol_entry(**overrides):
    entry = {
        "protocol": "usb", "qualification_state": "SMOKE_QUALIFIED",
        "passing_test_count": 10, "coverage_percent": 60.0, "evidence_count": 5,
    }
    entry.update(overrides)
    return entry


def test_qualification_matrix_consistency_gate_passes_consistent_canonical_status():
    payload = {"protocols": [_base_protocol_entry(
        qualification_state="SMOKE_QUALIFIED", canonical_qualification_status="SMOKE_QUALIFIED",
    )]}
    rc, out = _run_gate_script("verification_flow/qualification_matrix_consistency_gate.py", "--matrix", payload)
    assert rc == 0, out


def test_qualification_matrix_consistency_gate_fails_on_invalid_canonical_status():
    payload = {"protocols": [_base_protocol_entry(
        qualification_state="SMOKE_QUALIFIED", canonical_qualification_status="NOT_A_REAL_TIER",
    )]}
    rc, out = _run_gate_script("verification_flow/qualification_matrix_consistency_gate.py", "--matrix", payload)
    assert rc != 0
    assert out.get("reason") == "INVALID_CANONICAL_QUALIFICATION_STATUS"


def test_qualification_matrix_consistency_gate_fails_on_canonical_state_mismatch():
    payload = {"protocols": [_base_protocol_entry(
        qualification_state="SMOKE_QUALIFIED", canonical_qualification_status="PRODUCTION_QUALIFIED",
    )]}
    rc, out = _run_gate_script("verification_flow/qualification_matrix_consistency_gate.py", "--matrix", payload)
    assert rc != 0
    assert out.get("reason") == "QUALIFICATION_STATUS_STATE_MISMATCH"


def test_qualification_matrix_consistency_gate_fails_below_system_level_floor():
    payload = {"protocols": [_base_protocol_entry(
        qualification_state="SMOKE_QUALIFIED", canonical_qualification_status="BUILDER_AVAILABLE",
    )]}
    rc, out = _run_gate_script("verification_flow/qualification_matrix_consistency_gate.py", "--matrix", payload)
    assert rc != 0
    assert out.get("reason") == "CANONICAL_STATUS_BELOW_SYSTEM_LEVEL_FLOOR"


def test_qualification_matrix_consistency_gate_without_canonical_status_unaffected():
    # Backward compatibility: entries with no canonical_qualification_status
    # field at all must behave exactly as before this extension.
    payload = {"protocols": [_base_protocol_entry()]}
    rc, out = _run_gate_script("verification_flow/qualification_matrix_consistency_gate.py", "--matrix", payload)
    assert rc == 0, out
