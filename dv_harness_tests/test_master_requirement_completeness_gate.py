import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "verification_flow" / "master_requirement_completeness_gate.py"

BASE_IDS = [
    "STEP_BY_STEP_INTERACTIVE", "FIVE_CORE_INPUTS", "SPEC", "COMMAND_TXT",
    "PROTOCOL_STANDARD_REFERENCE", "REFERENCE_UVM", "RTL_FIRST_ARCH_DISCOVERY",
    "DE_LOCAL_SIM_BASELINE", "VPLAN_FIRST", "VERIFICATION_ARCHITECTURE",
    "SCOREBOARD_CHECKER_ASSERTION", "TEST_GENERATION", "NEGATIVE_TEST",
    "LOCAL_SIM", "COMMAND_SIMLOG_SEMANTIC", "FALSE_PASS_DEFENSE",
    "DUT_TB_BUG_CLASSIFICATION", "WAVEFORM_RCA", "PROTOCOL_CORNER_CASE",
    "LSF_REGRESSION", "PER_JOB_MONITOR", "REMOTE", "COVERAGE_CLOSURE",
    "SYSTEM_LEVEL", "EXPERT_FEEDBACK", "SIGNOFF", "FEATURE_CONTINUITY",
    "EVIDENCE_PROVENANCE",
]


def run_gate(payload, tmp_path):
    p = tmp_path / "matrix.json"
    p.write_text(json.dumps(payload))
    return subprocess.run(
        [sys.executable, str(GATE), "--matrix", str(p)],
        capture_output=True, text=True,
    )


def _req(rid):
    return {"requirement_id": rid, "implemented": True, "pytest_evidence": True, "hard_gate": True}


def test_all_requirements_with_new_key_passes(tmp_path):
    payload = {"requirements": [_req(r) for r in BASE_IDS]}
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert out["status"] == "PASS"


def test_missing_new_key_reported(tmp_path):
    ids_without_reference = [r for r in BASE_IDS if r != "PROTOCOL_STANDARD_REFERENCE"]
    payload = {"requirements": [_req(r) for r in ids_without_reference]}
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert out["status"] == "FAIL"
    assert "PROTOCOL_STANDARD_REFERENCE" in out["missing"]
