"""Regression tests for Finding I7 (2026-09-02 final-review follow-up):
run_gate() (dv_harness/gates.py) now tells every gate subprocess exactly
where the real, currently-running dv_harness package lives via a
DV_HARNESS_PACKAGE_ROOT env var, instead of letting each gate script guess
its own import root via a fragile `Path(__file__).resolve().parents[2]`
(only correct in this repo's own dogfooding layout, where
tools/verification_flow/ and dv_harness/ are siblings under the same root).

Three things need proving:
  1. run_gate() actually SETS the env var, with the correct value, on both
     subprocess.run() call sites (single-flag and multi-flag).
  2. The 5 patched gate scripts still work with NO env var set (backward
     compatibility with direct/manual invocation, and with this repo's own
     dogfooding layout, where the parents[2] fallback happens to be correct).
  3. The env var is what actually makes a REAL deployed-project layout work
     -- a gate script copied to an isolated location with no dv_harness
     package 2 directories above it, the exact shape I7 is about.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import dv_harness as dv_harness_pkg
import dv_harness.gates as gates_mod

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PACKAGE_ROOT = str(Path(dv_harness_pkg.__file__).resolve().parent.parent)

FIVE_PATCHED_SCRIPTS = [
    "self_tuning_proposal_gate.py",
    "rtl_write_scope_guard_gate.py",
    "signoff_bundle_completeness_gate.py",
    "qualification_matrix_consistency_gate.py",
    "pattern_registry_completeness_gate.py",
]


class _FakeCompletedProcess:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = ""


def _mk_project_with_stub_gate(script_name, script_body=None):
    tmp = Path(tempfile.mkdtemp())
    d = tmp / "tools" / "verification_flow"
    d.mkdir(parents=True)
    (d / script_name).write_text(
        script_body or "import json,sys\nprint(json.dumps({'status':'PASS'}))\nsys.exit(0)\n",
        encoding="utf-8",
    )
    return tmp


# --- 1. run_gate() sets DV_HARNESS_PACKAGE_ROOT on both call sites ---------

def test_run_gate_sets_dv_harness_package_root_env_single_flag_path():
    tmp = _mk_project_with_stub_gate("dummy_single_flag_gate.py")
    try:
        captured = {}

        def fake_run(args, **kwargs):
            captured["args"] = args
            captured["env"] = kwargs.get("env")
            return _FakeCompletedProcess(json.dumps({"status": "PASS"}))

        with patch.object(gates_mod.subprocess, "run", side_effect=fake_run):
            result = gates_mod.run_gate(tmp, "dummy_single_flag_gate.py", "--input", {"a": 1})

        assert result.ok is True
        env = captured["env"]
        assert env is not None, "run_gate() must pass an explicit env= to subprocess.run()"
        assert env.get("DV_HARNESS_PACKAGE_ROOT") == EXPECTED_PACKAGE_ROOT
        # Merged with, not replacing, the real environment -- the subprocess
        # still needs PATH etc. to run python at all.
        assert env.get("PATH") == os.environ.get("PATH")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_gate_sets_dv_harness_package_root_env_multi_flag_path():
    tmp = _mk_project_with_stub_gate("dummy_multi_flag_gate.py")
    try:
        captured = {}

        def fake_run(args, **kwargs):
            captured["args"] = args
            captured["env"] = kwargs.get("env")
            return _FakeCompletedProcess(json.dumps({"status": "PASS"}))

        cli_flag = (
            gates_mod.EvidenceFlag("--edit", "edit"),
            gates_mod.ContextFlag("--root", lambda root: str(root)),
        )
        with patch.object(gates_mod.subprocess, "run", side_effect=fake_run):
            result = gates_mod.run_gate(
                tmp, "dummy_multi_flag_gate.py", cli_flag, {"edit": {"touched_paths": []}}
            )

        assert result.ok is True
        env = captured["env"]
        assert env is not None
        assert env.get("DV_HARNESS_PACKAGE_ROOT") == EXPECTED_PACKAGE_ROOT
        assert env.get("PATH") == os.environ.get("PATH")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- 2. Backward compatibility: the 5 scripts still work with NO env var --

def test_self_tuning_proposal_gate_fallback_works_without_env_var():
    script = ROOT / "tools" / "verification_flow" / "self_tuning_proposal_gate.py"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"proposals": []}, f)
        payload_path = f.name
    try:
        env = {k: v for k, v in os.environ.items() if k != "DV_HARNESS_PACKAGE_ROOT"}
        proc = subprocess.run(
            [sys.executable, str(script), "--proposal", payload_path],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["status"] == "PASS"
    finally:
        os.unlink(payload_path)


def test_pattern_registry_completeness_gate_fallback_works_without_env_var():
    script = ROOT / "tools" / "verification_flow" / "pattern_registry_completeness_gate.py"
    payload = {"patterns": [], "suite_names": []}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(payload, f)
        payload_path = f.name
    try:
        env = {k: v for k, v in os.environ.items() if k != "DV_HARNESS_PACKAGE_ROOT"}
        proc = subprocess.run(
            [sys.executable, str(script), "--registry", payload_path],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["status"] == "PASS"
    finally:
        os.unlink(payload_path)


# --- 3. The env var is what makes a REAL deployed-project layout work -----

def test_gate_script_copied_to_isolated_deployment_layout_needs_env_var():
    """The actual I7 scenario: a project's OWN copy of a gate script, with
    no dv_harness package 2 directories above it (unlike this repo's own
    dogfooding layout). Without DV_HARNESS_PACKAGE_ROOT this must fail with
    ModuleNotFoundError; with it (as run_gate() now supplies), it must work."""
    tmp = Path(tempfile.mkdtemp())
    try:
        deployed_dir = tmp / "some_deployed_project" / "tools" / "verification_flow"
        deployed_dir.mkdir(parents=True)
        script_src = ROOT / "tools" / "verification_flow" / "self_tuning_proposal_gate.py"
        script_dst = deployed_dir / "self_tuning_proposal_gate.py"
        shutil.copy(script_src, script_dst)

        # Confirm the OLD parents[2]-guess genuinely does not hold here --
        # otherwise this test would not actually exercise the gap I7 closes.
        old_guess_root = script_dst.resolve().parents[2]
        assert not (old_guess_root / "dv_harness").exists()

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"proposals": []}, f)
            payload_path = f.name

        try:
            # Without the env var: fails, proving the gap is real.
            env_without = {k: v for k, v in os.environ.items() if k != "DV_HARNESS_PACKAGE_ROOT"}
            proc_fail = subprocess.run(
                [sys.executable, str(script_dst), "--proposal", payload_path],
                cwd=str(tmp), capture_output=True, text=True, timeout=30, env=env_without,
            )
            assert proc_fail.returncode != 0
            assert "ModuleNotFoundError" in proc_fail.stderr

            # With the env var (as run_gate() now supplies it): works.
            env_with = {**os.environ, "DV_HARNESS_PACKAGE_ROOT": EXPECTED_PACKAGE_ROOT}
            proc_ok = subprocess.run(
                [sys.executable, str(script_dst), "--proposal", payload_path],
                cwd=str(tmp), capture_output=True, text=True, timeout=30, env=env_with,
            )
            assert proc_ok.returncode == 0, proc_ok.stderr
            out = json.loads(proc_ok.stdout)
            assert out["status"] == "PASS"
        finally:
            os.unlink(payload_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
