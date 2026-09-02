import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "self_tuning_proposal_gate.py"


def _run(payload):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(payload, f)
        path = f.name
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--proposal", path],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    return proc.returncode, json.loads(proc.stdout)


def test_normal_proposal_passes_through_unmodified():
    rc, out = _run({"proposals": [
        {"gate_id": "some_unprotected_gate", "change": {"param": "window_us", "from": 200, "to": 250},
         "rationale": "observed pattern", "confidence": "HIGH", "risk_level": "LOW"},
    ]})
    assert rc == 0
    assert out["status"] == "PASS"
    assert len(out["surviving_proposals"]) == 1
    assert out["stripped"] == []


def test_removal_of_protected_gate_is_stripped():
    rc, out = _run({"proposals": [
        {"gate_id": "fix_risk_approval_gate", "stage": "RE_AUDIT",
         "change": {"action": "remove", "gate_id": "fix_risk_approval_gate"},
         "rationale": "seems redundant", "confidence": "HIGH", "risk_level": "LOW"},
    ]})
    assert rc == 0
    assert out["surviving_proposals"] == []
    assert len(out["stripped"]) == 1
    assert out["stripped"][0]["strip_reason"] == "PROTECTED_REMOVAL"


def test_protected_parameter_exposure_is_stripped():
    rc, out = _run({"proposals": [
        {"gate_id": "fix_risk_approval_gate",
         "change": {"param": "risk_classification_threshold", "from": 0.5, "to": 0.8},
         "rationale": "reduce false positives", "confidence": "HIGH", "risk_level": "LOW"},
    ]})
    assert rc == 0
    assert out["surviving_proposals"] == []
    assert out["stripped"][0]["strip_reason"] == "PROTECTED_PARAMETER"


def test_missing_proposals_key_fails():
    rc, out = _run({})
    assert rc != 0
    assert out["status"] == "FAIL"


def test_proposal_missing_required_field_is_stripped_not_crashed():
    rc, out = _run({"proposals": [
        {"gate_id": "some_gate", "change": {"param": "x", "from": 1, "to": 2}},
    ]})
    assert rc == 0
    assert out["surviving_proposals"] == []
    assert out["stripped"][0]["strip_reason"] == "MISSING_REQUIRED_FIELD"


def test_top_level_payload_is_list_returns_clean_json_not_crash():
    """Regression test: payload is a list, not a dict. Should return clean JSON with exit code 2."""
    rc, out = _run([1, 2, 3])
    assert rc == 2
    assert out["status"] == "FAIL"
    assert out["reason"] == "MISSING_PROPOSALS_LIST"


def test_change_field_is_non_dict_returns_clean_reason_not_crash():
    """Regression test: change is a string, not a dict. Should be stripped with clear reason."""
    rc, out = _run({"proposals": [
        {"gate_id": "some_gate", "change": "not a dict",
         "rationale": "test", "confidence": "HIGH", "risk_level": "LOW"},
    ]})
    assert rc == 0
    assert out["surviving_proposals"] == []
    assert len(out["stripped"]) == 1
    assert out["stripped"][0]["strip_reason"] == "INVALID_CHANGE_SHAPE"
