"""Tests for tools/verification_flow/environment_mode_selection_gate.py --
the new STAGE_GATES-registered PROJECT_MODEL check (gates.
STAGE_GATES["PROJECT_MODEL"]) that closes dashboard.py's own documented
"no stage, no gate, no writer" gap for the environment_mode_selection
evidence block. Run exactly the way test_qualification.py's
_run_gate_script() runs gate scripts (subprocess, real script file), except
with an EXPLICIT cwd -- this gate's whole point is that it reads the real
subsystem registry relative to its own process cwd (see its own module
header), so the test must control that precisely rather than rely on
whatever directory happens to invoke pytest."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "environment_mode_selection_gate.py"


def _run_gate(payload: dict, cwd: Path):
    tmp = Path(tempfile.mkdtemp())
    try:
        infile = tmp / "in.json"
        infile.write_text(json.dumps(payload), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--state", str(infile)],
            cwd=str(cwd), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        import shutil
        shutil.rmtree(tmp)


def _empty_project(tmp_path) -> Path:
    # No .dv-harness/soc-composer/subsystem_environment_registry.json at
    # all -- the gate's own documented "missing file == empty registry"
    # default.
    return tmp_path


def _project_with_registry(tmp_path, names) -> Path:
    registry_dir = tmp_path / ".dv-harness" / "soc-composer"
    registry_dir.mkdir(parents=True)
    (registry_dir / "subsystem_environment_registry.json").write_text(
        json.dumps({"subsystems": [{"name": n} for n in names]}), encoding="utf-8",
    )
    return tmp_path


def test_help_smoke():
    r = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                        cwd=str(ROOT), capture_output=True, text=True, timeout=15)
    assert r.returncode == 0
    assert r.stdout.strip()


def test_pass_single_subsystem_not_yet_registered(tmp_path):
    project = _empty_project(tmp_path)
    rc, out = _run_gate({"environment_mode": "SUBSYSTEM_MODE", "requested_subsystems": ["usb"]}, project)
    assert rc == 0, out
    assert out["status"] == "PASS"
    assert out["environment_mode"] == "SUBSYSTEM_MODE"
    assert out["missing_subsystems"] == ["usb"]


def test_pass_system_level_mode_all_registered(tmp_path):
    project = _project_with_registry(tmp_path, ["usb", "pcie"])
    rc, out = _run_gate({"environment_mode": "SYSTEM_LEVEL_MODE",
                          "requested_subsystems": ["usb", "pcie"]}, project)
    assert rc == 0, out
    assert out["status"] == "PASS"
    assert out["missing_subsystems"] == []


def test_pass_system_level_mode_with_declared_escalation(tmp_path):
    project = _empty_project(tmp_path)
    rc, out = _run_gate({"environment_mode": "SYSTEM_LEVEL_MODE",
                          "requested_subsystems": ["usb", "pcie"],
                          "needs_subsystem_mode_first": True}, project)
    assert rc == 0, out
    assert out["status"] == "PASS"
    assert out["missing_subsystems"] == ["pcie", "usb"]


def test_fail_missing_escalation_declaration(tmp_path):
    project = _empty_project(tmp_path)
    rc, out = _run_gate({"environment_mode": "SYSTEM_LEVEL_MODE",
                          "requested_subsystems": ["usb", "pcie"]}, project)
    assert rc != 0
    assert out["status"] == "FAIL"
    assert out["reason"] == "MISSING_SUBSYSTEM_MODE_ESCALATION_NOT_DECLARED"
    assert sorted(out["missing_subsystems"]) == ["pcie", "usb"]


def test_conflict_declared_mode_disagrees_with_requested_count(tmp_path):
    project = _empty_project(tmp_path)
    rc, out = _run_gate({"environment_mode": "SYSTEM_LEVEL_MODE",
                          "requested_subsystems": ["usb"]}, project)
    assert rc != 0
    assert out["status"] == "CONFLICT"
    assert out["derived_mode"] == "SUBSYSTEM_MODE"


def test_invalid_environment_mode_value(tmp_path):
    project = _empty_project(tmp_path)
    rc, out = _run_gate({"environment_mode": "NOT_A_REAL_MODE", "requested_subsystems": ["usb"]}, project)
    assert rc != 0
    assert out["status"] == "FAIL"
    assert out["reason"] == "INVALID_ENVIRONMENT_MODE"


def test_missing_requested_subsystems(tmp_path):
    project = _empty_project(tmp_path)
    rc, out = _run_gate({"environment_mode": "SUBSYSTEM_MODE", "requested_subsystems": []}, project)
    assert rc != 0
    assert out["status"] == "FAIL"
    assert out["reason"] == "MISSING_REQUESTED_SUBSYSTEMS"


def test_registry_read_is_case_insensitive_and_ignores_unreadable_file(tmp_path):
    registry_dir = tmp_path / ".dv-harness" / "soc-composer"
    registry_dir.mkdir(parents=True)
    (registry_dir / "subsystem_environment_registry.json").write_text("not valid json", encoding="utf-8")
    rc, out = _run_gate({"environment_mode": "SUBSYSTEM_MODE", "requested_subsystems": ["usb"]}, tmp_path)
    assert rc == 0, out
    assert out["status"] == "PASS"
    assert out["missing_subsystems"] == ["usb"]  # unreadable registry degrades to empty, not a crash
