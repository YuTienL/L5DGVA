import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "vplan" / "intake_readiness.py"


def run_gate(payload, tmp_path):
    p = tmp_path / "intake.json"
    p.write_text(json.dumps(payload))
    return subprocess.run(
        [sys.executable, str(GATE), "--intake", str(p)],
        capture_output=True, text=True,
    )


def _base_subsystem(protocols):
    return {
        "mode": "SUBSYSTEM",
        "target_name": "amba_soc",
        "protocols": protocols,
        "required_artifacts": {
            "protocol_spec": True,
            "dut_design_spec": True,
            "clock_reset_spec": True,
        },
    }


def test_amba_intake_missing_fabric_topology_is_flagged(tmp_path):
    payload = _base_subsystem(["amba4-soc"])
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "fabric_topology_evidence" in out["missing"]


def test_amba_intake_with_fabric_topology_not_flagged(tmp_path):
    payload = _base_subsystem(["amba4-soc"])
    payload["required_artifacts"]["fabric_topology_spec"] = True
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "fabric_topology_evidence" not in out["missing"]


def test_sd_intake_missing_uhs_tuning_is_flagged(tmp_path):
    payload = _base_subsystem(["sd"])
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "uhs_tuning_evidence" in out["missing"]


def test_pcie_intake_unaffected_by_new_fields(tmp_path):
    payload = _base_subsystem(["pcie"])
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "fabric_topology_evidence" not in out["missing"]
    assert "uhs_tuning_evidence" not in out["missing"]
