"""Tests for tools/verification_flow/de_local_sim_env_intake_gate.py.

GAP THIS CLOSES (2026-09-01, de-local-sim-env-intake design pass): an audit
found DE-local-simulation-environment intake (compile script, run script,
filelist, environment-setup script -- the local DE simulation environment a
project may already have before the harness gets involved) had ZERO schema
or code backing anywhere in the codebase. This file drives the new gate
script directly (same subprocess convention as
test_server_sync_identity_gate.py) and also covers its wiring into
dv_harness.gates.STAGE_GATES["INTAKE"] via evaluate_stage_evidence(), same
as test_engine_gates_and_routing.py does for the other INTAKE gates.

RULING under test: the gate is OPTIONAL/non-blocking -- an entirely empty
("{}") or field-free payload is a no-op PASS (a project may genuinely have
no pre-existing DE-local environment), but the moment ANY of the four
required fields is populated, all four become required and are each
checked for real, non-empty, on-disk file existence plus a non-empty
"evidence" note -- partial evidence is never treated as if the whole block
were absent.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "de_local_sim_env_intake_gate.py"


def _run(payload):
    import tempfile
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, tmp)
    tmp.close()
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--intake", tmp.name],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def _valid_block(tmp_path, **overrides):
    files = {}
    for name in ("compile", "run", "filelist", "env_setup"):
        p = tmp_path / f"{name}.txt"
        p.write_text(f"real {name} content\n", encoding="utf-8")
        files[name] = p
    block = {
        "compile_script_path": {"path": str(files["compile"]), "evidence": "Read the file and executed it once."},
        "run_script_path": {"path": str(files["run"]), "evidence": "Executed and observed PASS output."},
        "filelist_path": {"path": str(files["filelist"]), "evidence": "Read the filelist content directly."},
        "env_setup_script_path": {"path": str(files["env_setup"]), "evidence": "Sourced it and confirmed env vars set."},
    }
    block.update(overrides)
    return block


# --- OPTIONAL / no-op PASS behavior ------------------------------------------

def test_empty_object_is_no_op_pass():
    rc, out = _run({})
    assert rc == 0
    assert out == {"status": "PASS", "de_local_sim_env": "NOT_APPLICABLE"}


def test_missing_payload_dict_type_is_treated_as_no_op_pass():
    # A non-dict payload (defensive) is treated the same as "no fields" --
    # never crashes, never silently PASSes something it shouldn't enforce.
    rc, out = _run([])
    assert rc == 0
    assert out["status"] == "PASS" and out["de_local_sim_env"] == "NOT_APPLICABLE"


def test_all_falsy_field_values_is_still_no_op_pass():
    rc, out = _run({"compile_script_path": None, "run_script_path": False, "filelist_path": "", "env_setup_script_path": 0})
    assert rc == 0
    assert out["de_local_sim_env"] == "NOT_APPLICABLE"


# --- Full valid block ---------------------------------------------------------

def test_full_valid_block_passes(tmp_path):
    rc, out = _run(_valid_block(tmp_path))
    assert rc == 0
    assert out["status"] == "PASS"
    assert out["de_local_sim_env"] == "CONFIRMED"
    assert set(out["fields_confirmed"]) == {
        "compile_script_path", "run_script_path", "filelist_path", "env_setup_script_path",
    }


# --- Partial block: any one populated field makes all four required ---------

def test_partial_block_missing_other_fields_fails_typed(tmp_path):
    block = _valid_block(tmp_path)
    del block["run_script_path"]
    rc, out = _run(block)
    assert rc == 2
    assert out["status"] == "FAIL"
    assert out["reason"] == "RUN_SCRIPT_PATH_FIELD_MISSING"
    assert out["field"] == "run_script_path"


def test_field_present_but_not_a_dict_fails_field_missing(tmp_path):
    block = _valid_block(tmp_path)
    block["filelist_path"] = "/just/a/string/not/an/object"
    rc, out = _run(block)
    assert rc == 2
    assert out["reason"] == "FILELIST_PATH_FIELD_MISSING"


# --- Per-field validation kinds, each with a typed FAIL reason ---------------

def test_missing_path_key_fails_path_missing(tmp_path):
    block = _valid_block(tmp_path)
    block["compile_script_path"] = {"evidence": "some evidence but no path"}
    rc, out = _run(block)
    assert rc == 3
    assert out["reason"] == "COMPILE_SCRIPT_PATH_PATH_MISSING"


def test_blank_path_fails_path_missing(tmp_path):
    block = _valid_block(tmp_path)
    block["compile_script_path"] = {"path": "   ", "evidence": "..."}
    rc, out = _run(block)
    assert rc == 3
    assert out["reason"] == "COMPILE_SCRIPT_PATH_PATH_MISSING"


def test_missing_evidence_note_fails(tmp_path):
    block = _valid_block(tmp_path)
    block["run_script_path"] = {"path": block["run_script_path"]["path"]}
    rc, out = _run(block)
    assert rc == 4
    assert out["reason"] == "RUN_SCRIPT_PATH_EVIDENCE_MISSING"


def test_blank_evidence_note_fails(tmp_path):
    block = _valid_block(tmp_path)
    block["run_script_path"]["evidence"] = "   "
    rc, out = _run(block)
    assert rc == 4
    assert out["reason"] == "RUN_SCRIPT_PATH_EVIDENCE_MISSING"


def test_nonexistent_path_fails_not_found(tmp_path):
    block = _valid_block(tmp_path)
    block["filelist_path"]["path"] = str(tmp_path / "does_not_exist.f")
    rc, out = _run(block)
    assert rc == 5
    assert out["reason"] == "FILELIST_PATH_PATH_NOT_FOUND"


def test_directory_path_fails_not_a_file(tmp_path):
    block = _valid_block(tmp_path)
    subdir = tmp_path / "a_directory"
    subdir.mkdir()
    block["env_setup_script_path"]["path"] = str(subdir)
    rc, out = _run(block)
    assert rc == 6
    assert out["reason"] == "ENV_SETUP_SCRIPT_PATH_PATH_NOT_A_FILE"


def test_empty_file_fails_file_empty(tmp_path):
    block = _valid_block(tmp_path)
    empty = tmp_path / "empty_compile.sh"
    empty.write_text("", encoding="utf-8")
    block["compile_script_path"]["path"] = str(empty)
    rc, out = _run(block)
    assert rc == 7
    assert out["reason"] == "COMPILE_SCRIPT_PATH_PATH_FILE_EMPTY"


def test_first_failing_field_wins_deterministically(tmp_path):
    # compile_script_path is checked before run_script_path -- break both
    # and confirm the earlier field's failure is what's reported.
    block = _valid_block(tmp_path)
    block["compile_script_path"]["path"] = str(tmp_path / "nope.sh")
    block["run_script_path"]["path"] = str(tmp_path / "also_nope.sh")
    rc, out = _run(block)
    assert out["field"] == "compile_script_path"


# --- Engine wiring: dv_harness.gates.STAGE_GATES["INTAKE"] -------------------

def test_gate_registered_in_intake_stage_gates():
    from dv_harness.gates import STAGE_GATES
    gate_ids = [g[0] for g in STAGE_GATES["INTAKE"]]
    assert "de_local_sim_env_intake_gate" in gate_ids
    # Additive: the pre-existing intake gates must still be present, unbroken.
    assert "intake_readiness" in gate_ids
    assert "generated_artifact_boundary_gate" in gate_ids
    assert "interactive_evidence_intake_gate" in gate_ids


def test_evaluate_stage_evidence_empty_block_does_not_block_intake_pass(tmp_path):
    from dv_harness.gates import evaluate_stage_evidence

    # command_txt/vip_reference must name real, on-disk files (checked
    # relative to cwd=ROOT by tools/vplan/intake_readiness.py) -- reuse the
    # same real-file convention as test_engine_gates_and_routing.py's own
    # test_newly_wired_orphan_gates_pass_with_valid_evidence.
    intake_evidence = {
        "mode": "SUBSYSTEM", "target_name": "usb_dev", "protocols": ["usb"],
        "required_artifacts": {"protocol_spec": True, "dut_design_spec": True,
                                "rtl_top_or_interface_files": True,
                                "command_txt": ["CLAUDE.md"], "vip_reference": ["dv_harness/gates.py"]},
    }
    inventory_evidence = {"artifacts": []}
    interactive_state = {"status": "READY"}
    text = (
        f"```dv-harness-evidence:intake_readiness\n{json.dumps(intake_evidence)}\n```\n"
        f"```dv-harness-evidence:generated_artifact_boundary_gate\n{json.dumps(inventory_evidence)}\n```\n"
        f"```dv-harness-evidence:interactive_evidence_intake_gate\n{json.dumps(interactive_state)}\n```\n"
        f"```dv-harness-evidence:de_local_sim_env_intake_gate\n{{}}\n```\n"
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "INTAKE", text)
    assert verdict == "PASS", reasons


def test_evaluate_stage_evidence_broken_de_local_field_causes_gate_fail(tmp_path):
    from dv_harness.gates import evaluate_stage_evidence

    intake_evidence = {
        "mode": "SUBSYSTEM", "target_name": "usb_dev", "protocols": ["usb"],
        "required_artifacts": {"protocol_spec": True, "dut_design_spec": True,
                                "rtl_top_or_interface_files": True,
                                "command_txt": [], "vip_reference": []},
    }
    inventory_evidence = {"artifacts": []}
    interactive_state = {"status": "READY"}
    de_local_block = {"compile_script_path": {"path": str(tmp_path / "nope.sh"), "evidence": "..."}}
    text = (
        f"```dv-harness-evidence:intake_readiness\n{json.dumps(intake_evidence)}\n```\n"
        f"```dv-harness-evidence:generated_artifact_boundary_gate\n{json.dumps(inventory_evidence)}\n```\n"
        f"```dv-harness-evidence:interactive_evidence_intake_gate\n{json.dumps(interactive_state)}\n```\n"
        f"```dv-harness-evidence:de_local_sim_env_intake_gate\n{json.dumps(de_local_block)}\n```\n"
    )
    verdict, reasons = evaluate_stage_evidence(ROOT, "INTAKE", text)
    assert verdict == "GATE_FAIL"
    assert any("de_local_sim_env_intake_gate" in r for r in reasons)
