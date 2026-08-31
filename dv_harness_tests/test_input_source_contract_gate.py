import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "verification_flow" / "input_source_contract_gate.py"


def run_gate(payload, tmp_path):
    p = tmp_path / "contract.json"
    p.write_text(json.dumps(payload))
    return subprocess.run(
        [sys.executable, str(GATE), "--contract", str(p)],
        capture_output=True, text=True,
    )


def test_pcie_evidence_with_new_key_passes(tmp_path):
    payload = {
        "provided_source_classes": [
            "SPEC", "COMMAND_TXT", "PRIMARY_PROTOCOL_REFERENCE", "RTL_SOURCE", "DE_LOCAL_SIM",
        ],
        "protocol_input_kind": "PUBLIC_STANDARD_SPEC",
        "forbidden_user_prerequisites": [],
    }
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert out["status"] == "PASS"


def test_missing_new_key_still_fails_as_missing_evidence(tmp_path):
    payload = {
        "provided_source_classes": ["SPEC", "COMMAND_TXT", "RTL_SOURCE", "DE_LOCAL_SIM"],
        "protocol_input_kind": "PUBLIC_STANDARD_SPEC",
        "forbidden_user_prerequisites": [],
    }
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert out["status"] == "FAIL"
    assert "PRIMARY_PROTOCOL_REFERENCE" in out["missing"]


def test_old_usb_reference_key_no_longer_satisfies_the_requirement(tmp_path):
    payload = {
        "provided_source_classes": ["SPEC", "COMMAND_TXT", "USB_REFERENCE", "RTL_SOURCE", "DE_LOCAL_SIM"],
        "protocol_input_kind": "PUBLIC_STANDARD_SPEC",
        "forbidden_user_prerequisites": [],
    }
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert out["status"] == "FAIL"
