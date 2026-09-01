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


def test_amba_intake_axi4_spelling_still_flags_fabric_topology(tmp_path):
    # "axi4" is a router-recognized AMBA spelling (protocol-router/SKILL.md
    # lists AXI4 as a valid AMBA resolution) that was NOT in the original
    # alias set -- it must still trigger the fabric_topology_evidence check.
    payload = _base_subsystem(["axi4"])
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "fabric_topology_evidence" in out["missing"]


def test_amba_intake_ahb_lite_spelling_still_flags_fabric_topology(tmp_path):
    payload = _base_subsystem(["ahb-lite"])
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "fabric_topology_evidence" in out["missing"]


# --- command.txt / VIP-reference intake checks --------------------------
# BUG FIX (2026-09-01, commandtxt-vip-intake-gate-implementation): these two
# required_artifacts keys were completely unchecked before this fix -- a
# SUBSYSTEM intake with no command.txt/VIP-reference evidence at all (or a
# bare `true` naming no real file) could still reach READY_FOR_VPLAN. See
# tools/vplan/intake_readiness.py's own header comment for the full
# rationale.

def _real_file(tmp_path, name="command.txt", content="scenario A\n"):
    p = tmp_path / name
    p.write_text(content)
    return str(p)


def test_missing_command_txt_and_vip_reference_both_flagged(tmp_path):
    # Neither field supplied at all (real pre-existing behavior before this
    # fix: the gate never looked at these keys, so this payload used to
    # reach READY_FOR_VPLAN with zero command.txt/VIP evidence).
    payload = _base_subsystem(["usb"])
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "command_txt" in out["missing"]
    assert "vip_reference" in out["missing"]
    assert out["readiness"] == "COLLECTING"
    assert result.returncode != 0


def test_command_txt_bare_true_is_not_well_formed_evidence(tmp_path):
    # A bare boolean attestation names no real file -- must not satisfy the
    # check the way it does for the older boolean-only fields.
    payload = _base_subsystem(["usb"])
    payload["required_artifacts"]["command_txt"] = True
    payload["required_artifacts"]["vip_reference"] = [_real_file(tmp_path, "vip_ref.md")]
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "command_txt_path_not_found" in out["missing"]
    assert "command_txt" not in out["missing"]  # not outright absent, just malformed
    assert "vip_reference" not in out["missing"]


def test_command_txt_path_that_does_not_exist_on_disk_is_flagged(tmp_path):
    payload = _base_subsystem(["usb"])
    payload["required_artifacts"]["command_txt"] = [str(tmp_path / "nonexistent_command.txt")]
    payload["required_artifacts"]["vip_reference"] = [_real_file(tmp_path, "vip_ref.md")]
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "command_txt_path_not_found" in out["missing"]


def test_vip_reference_path_that_does_not_exist_on_disk_is_flagged(tmp_path):
    payload = _base_subsystem(["usb"])
    payload["required_artifacts"]["command_txt"] = [_real_file(tmp_path)]
    payload["required_artifacts"]["vip_reference"] = str(tmp_path / "nonexistent_vip_doc.md")
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "vip_reference_path_not_found" in out["missing"]


def test_vip_reference_empty_string_entry_in_list_is_flagged(tmp_path):
    payload = _base_subsystem(["usb"])
    payload["required_artifacts"]["command_txt"] = [_real_file(tmp_path)]
    payload["required_artifacts"]["vip_reference"] = [_real_file(tmp_path, "vip_ref.md"), "   "]
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "vip_reference_path_not_found" in out["missing"]


def test_command_txt_and_vip_reference_real_paths_pass(tmp_path):
    # Full happy path: every SUBSYSTEM-mode required field present, including
    # real on-disk command.txt/vip_reference paths -> READY_FOR_VPLAN, and
    # neither new field (nor its _path_not_found variant) appears in missing.
    payload = _base_subsystem(["usb"])
    payload["required_artifacts"]["command_txt"] = [_real_file(tmp_path, "command.txt")]
    payload["required_artifacts"]["vip_reference"] = [_real_file(tmp_path, "vip_reference.md")]
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "command_txt" not in out["missing"]
    assert "command_txt_path_not_found" not in out["missing"]
    assert "vip_reference" not in out["missing"]
    assert "vip_reference_path_not_found" not in out["missing"]
    assert out["readiness"] == "READY_FOR_VPLAN"
    assert result.returncode == 0


def test_command_txt_single_string_path_accepted_not_just_list(tmp_path):
    # The schema's canonical shape is a list, but a single path string is
    # accepted too (ergonomic, same normalization tools/vplan/intake_
    # readiness.py's _artifact_paths() applies to both).
    payload = _base_subsystem(["usb"])
    payload["required_artifacts"]["command_txt"] = _real_file(tmp_path, "command.txt")
    payload["required_artifacts"]["vip_reference"] = _real_file(tmp_path, "vip_reference.md")
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "command_txt_path_not_found" not in out["missing"]
    assert "vip_reference_path_not_found" not in out["missing"]


def test_system_level_intake_not_affected_by_new_command_txt_checks(tmp_path):
    # RULING: command_txt/vip_reference are only enforced for SUBSYSTEM-mode
    # intake -- a SYSTEM_LEVEL intake composes already-verified subsystem
    # environments (each already passed its own SUBSYSTEM intake), so it is
    # not independently required here.
    payload = {
        "mode": "SYSTEM_LEVEL",
        "target_name": "soc_top",
        "selected_subsystems": ["usb_subsystem"],
        "required_artifacts": {
            "system_level_use_cases": True,
            "existing_uvm_env": True,
        },
    }
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "command_txt" not in out["missing"]
    assert "vip_reference" not in out["missing"]
    assert out["readiness"] == "READY_FOR_VPLAN"
