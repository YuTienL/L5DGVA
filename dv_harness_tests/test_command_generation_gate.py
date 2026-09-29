"""Real-subprocess tests for tools/verification_flow/command_generation_gate.py --
the New-Command Creation Gate.

Every test drives the actual script as a subprocess (`python
tools/verification_flow/command_generation_gate.py --command-request <file>`),
exactly the way `dv_harness/gates.py`'s `run_gate()` would invoke it: cwd is
this repo's own root (so the script's `parents[2]` package-root fallback
resolves the real `dv_harness` package, the same dogfooding-layout idiom
`test_loop_budget.py::test_the_cli_verb_is_registered_and_runs_as_a_real_
subprocess` already relies on), and the payload is a real JSON file on disk --
never an in-process function call, and never a mock of
`existing_command_reuse_score` / `branch_ownership_resolver`.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = REPO_ROOT / "tools" / "verification_flow" / "command_generation_gate.py"


def run_gate(payload: dict, tmp_path: Path, extra_args=None):
    request_path = tmp_path / "command_request.json"
    request_path.write_text(json.dumps(payload), encoding="utf-8")
    args = [sys.executable, str(GATE_SCRIPT), "--command-request", str(request_path)]
    if extra_args:
        args.extend(extra_args)
    out = subprocess.run(args, capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert out.stdout.strip(), f"no stdout; stderr={out.stderr}"
    result = json.loads(out.stdout)
    return out.returncode, result


# --- shared building blocks ----------------------------------------------------

def _vip_owned_proposed_command(branch_layer="branch_b0"):
    return {
        "command_name": "usb_reconfig_link_speed",
        "protocol": "USB",
        "description": "reconfigure the USB link to a new negotiated speed mid-test",
        "keywords": ["reconfig", "link", "speed"],
        "arguments": ["ADDRESS", "VALUE"],
        "branch_layer": branch_layer,
    }


def _vip_owned_ownership():
    return {
        "operation_kind": "VIP_DRIVEN_TEST_BODY",
        "per_port": True,
        "driven_by": "VIP_SEQUENCE",
    }


def _vip_owned_task_evidence(grounding_basis="VIP_USER_GUIDE"):
    return {
        "implementation_plan": (
            "extend usb_base_vseq with a new reconfigure task sequenced after "
            "link training completes, per the VIP user guide's own reconfigure "
            "example flow"
        ),
        "source_citations": [
            "svt_usb_agent VIP user guide section 4.2, reconfigure sequence example",
        ],
        "grounding_basis": grounding_basis,
    }


def _dut_owned_proposed_command(branch_layer="branch_a0"):
    return {
        "command_name": "usb_phy_link_train_init",
        "protocol": "USB",
        "description": "drive PHY link-training init registers for this port",
        "arguments": ["ADDRESS", "VALUE"],
        "branch_layer": branch_layer,
    }


def _dut_owned_ownership():
    return {
        "operation_kind": "DUT_PHY_PORT_BRINGUP",
        "per_port": True,
        "driven_by": "DUT_BRINGUP_FLOW",
    }


def _dut_owned_task_evidence(grounding_basis="DUT_RTL"):
    return {
        "implementation_plan": "issue the per-port PHY init register sequence at bring-up",
        "source_citations": ["usb3_phy_ctrl.v:212 PHY_INIT_SEQ register block"],
        "grounding_basis": grounding_basis,
    }


# --- positive path --------------------------------------------------------------

def test_pass_no_existing_commands_vip_owned_command_well_grounded(tmp_path):
    payload = {
        "proposed_command": _vip_owned_proposed_command(),
        "existing_commands": [],
        "ownership": _vip_owned_ownership(),
        "task_evidence": _vip_owned_task_evidence(),
    }
    code, result = run_gate(payload, tmp_path)
    assert code == 0, result
    assert result["status"] == "PASS"
    assert result["reuse_check"]["passed"] is True
    assert result["ownership_check"]["passed"] is True
    assert result["ownership_check"]["validation"]["verdict"] == "VALID"
    assert result["implementability_check"]["passed"] is True


def test_pass_dut_owned_command_with_unrelated_existing_command(tmp_path):
    """A real existing_commands list is supplied (exercising the REAL
    existing_command_reuse_score import, not just the empty-list shortcut),
    but it names an unrelated VIP-owned command on a different branch family
    -- branch_compatibility() excludes it, so NO_REUSE_CANDIDATE is still the
    honest verdict."""
    payload = {
        "proposed_command": _dut_owned_proposed_command(),
        "existing_commands": [{
            "command_name": "pcie_send_tlp_completion",
            "command_category": "vip_scenario",
            "arguments": "DESTINATION,VALUE",
            "branch_layer": "branch_b1",
            "target_sequence": "pcie_tlp_completion_seq",
        }],
        "ownership": _dut_owned_ownership(),
        "task_evidence": _dut_owned_task_evidence(),
    }
    code, result = run_gate(payload, tmp_path)
    assert code == 0, result
    assert result["status"] == "PASS"
    assert result["reuse_check"]["report_status"] == "NO_REUSE_CANDIDATE"


# --- negative control 1: a real reusable command exists -------------------------

def test_blocked_when_a_real_reusable_command_exists(tmp_path):
    proposed = _vip_owned_proposed_command()
    payload = {
        "proposed_command": proposed,
        "existing_commands": [{
            "command_name": "usb_reconfig_link_speed_v1",
            "description": "reconfigure the USB link to a new negotiated speed mid-test",
            "arguments": ["ADDRESS", "VALUE"],
            "branch_layer": "branch_b0",
            "target_sequence": "usb_reconfig_speed_seq",
        }],
        "ownership": _vip_owned_ownership(),
        "task_evidence": _vip_owned_task_evidence(),
    }
    code, result = run_gate(payload, tmp_path)
    assert code == 4
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "REUSABLE_COMMAND_EXISTS"
    assert result["reuse_check"]["report_status"] == "REUSE_CANDIDATES_FOUND"
    assert result["reuse_check"]["top_candidate"]["command_name"] == "usb_reconfig_link_speed_v1"


# --- negative control 2: branch ownership INVALID (wrong tier) ------------------

def test_blocked_when_vip_driven_work_assigned_to_branch_a(tmp_path):
    payload = {
        "proposed_command": _vip_owned_proposed_command(branch_layer="branch_a0"),
        "existing_commands": [],
        "ownership": _vip_owned_ownership(),
        "task_evidence": _vip_owned_task_evidence(),
    }
    code, result = run_gate(payload, tmp_path)
    assert code == 5
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "BRANCH_OWNERSHIP_NOT_VALID"
    validation = result["ownership_check"]["validation"]
    assert validation["verdict"] == "INVALID"
    assert validation["violated_rule"] == "VIP_DRIVEN_WORK_ASSIGNED_TO_BRANCH_A"


# --- negative control 3: branch ownership AMBIGUOUS (never a guessed pass) ------

def test_blocked_when_ownership_is_ambiguous_not_guessed(tmp_path):
    """A shared-resource access with no declared per_port cannot be classified
    GLOBAL vs. DUT -- this must read AMBIGUOUS and BLOCK, never a silent
    confident tier guess."""
    payload = {
        "proposed_command": _dut_owned_proposed_command(),
        "existing_commands": [],
        "ownership": {
            "operation_kind": "SHARED_RESOURCE_ARBITRATED_ACCESS",
            # per_port deliberately omitted
            "arbitration_policy": "round_robin_priority",
        },
        "task_evidence": _dut_owned_task_evidence(),
    }
    code, result = run_gate(payload, tmp_path)
    assert code == 5
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "BRANCH_OWNERSHIP_NOT_VALID"
    assert result["ownership_check"]["validation"]["verdict"] == "AMBIGUOUS"


# --- negative control 4: legacy/non-canonical branch naming ---------------------

def test_blocked_on_legacy_non_canonical_branch_label(tmp_path):
    payload = {
        "proposed_command": _dut_owned_proposed_command(branch_layer="BranchA0"),
        "existing_commands": [],
        "ownership": _dut_owned_ownership(),
        "task_evidence": _dut_owned_task_evidence(),
    }
    code, result = run_gate(payload, tmp_path)
    assert code == 5
    validation = result["ownership_check"]["validation"]
    assert validation["verdict"] == "INVALID"
    assert validation["violated_rule"] == "ARCH_CONFORMANCE_NAMING_VIOLATION"


# --- negative control 5: task not implementable (no real evidence cited) -------

def test_blocked_when_no_source_citations_supplied(tmp_path):
    task_evidence = _vip_owned_task_evidence()
    task_evidence["source_citations"] = ["TBD"]
    payload = {
        "proposed_command": _vip_owned_proposed_command(),
        "existing_commands": [],
        "ownership": _vip_owned_ownership(),
        "task_evidence": task_evidence,
    }
    code, result = run_gate(payload, tmp_path)
    assert code == 6
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "TASK_NOT_IMPLEMENTABLE"
    assert result["implementability_check"]["reason"] == "NO_SOURCE_CITATIONS"


def test_blocked_when_implementation_plan_is_a_placeholder(tmp_path):
    task_evidence = _vip_owned_task_evidence()
    task_evidence["implementation_plan"] = "unknown"
    payload = {
        "proposed_command": _vip_owned_proposed_command(),
        "existing_commands": [],
        "ownership": _vip_owned_ownership(),
        "task_evidence": task_evidence,
    }
    code, result = run_gate(payload, tmp_path)
    assert code == 6
    assert result["implementability_check"]["reason"] == "NO_IMPLEMENTATION_PLAN"


# --- negative control 6: grounding basis for the wrong ownership tier -----------

def test_blocked_when_grounding_basis_is_for_the_wrong_tier(tmp_path):
    """A VIP-owned command citing DUT-RTL grounding (or vice versa) is
    treated as unimplementable -- the wrong kind of primary source is not
    weaker evidence, it is evidence about a different command, per the
    Engineering Discipline Rules' branch-B-vs-branch-A sourcing split."""
    payload = {
        "proposed_command": _vip_owned_proposed_command(),
        "existing_commands": [],
        "ownership": _vip_owned_ownership(),
        "task_evidence": _vip_owned_task_evidence(grounding_basis="DUT_RTL"),
    }
    code, result = run_gate(payload, tmp_path)
    assert code == 6
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "TASK_NOT_IMPLEMENTABLE"
    assert result["implementability_check"]["reason"] == "GROUNDING_BASIS_WRONG_TIER"


def test_blocked_when_grounding_basis_is_not_recognized(tmp_path):
    payload = {
        "proposed_command": _vip_owned_proposed_command(),
        "existing_commands": [],
        "ownership": _vip_owned_ownership(),
        "task_evidence": _vip_owned_task_evidence(grounding_basis="I_JUST_KNOW"),
    }
    code, result = run_gate(payload, tmp_path)
    assert code == 6
    assert result["implementability_check"]["reason"] == "GROUNDING_BASIS_NOT_RECOGNIZED"


# --- negative control 7: malformed / incomplete payload -------------------------

def test_fail_on_missing_proposed_command(tmp_path):
    payload = {
        "existing_commands": [],
        "ownership": _vip_owned_ownership(),
        "task_evidence": _vip_owned_task_evidence(),
    }
    code, result = run_gate(payload, tmp_path)
    assert code == 3
    assert result["status"] == "FAIL"
    assert result["reason"] == "MISSING_PROPOSED_COMMAND"


def test_fail_on_missing_ownership_declaration(tmp_path):
    payload = {
        "proposed_command": _vip_owned_proposed_command(),
        "existing_commands": [],
        "task_evidence": _vip_owned_task_evidence(),
    }
    code, result = run_gate(payload, tmp_path)
    assert code == 3
    assert result["status"] == "FAIL"
    assert result["reason"] == "MISSING_OWNERSHIP_DECLARATION"


def test_fail_on_existing_commands_not_a_list(tmp_path):
    payload = {
        "proposed_command": _vip_owned_proposed_command(),
        "existing_commands": {"not": "a list"},
        "ownership": _vip_owned_ownership(),
        "task_evidence": _vip_owned_task_evidence(),
    }
    code, result = run_gate(payload, tmp_path)
    assert code == 3
    assert result["status"] == "FAIL"
    assert result["reason"] == "MALFORMED_EXISTING_COMMANDS"


def test_fail_on_payload_not_a_json_object(tmp_path):
    request_path = tmp_path / "command_request.json"
    request_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--command-request", str(request_path)],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    result = json.loads(out.stdout)
    assert out.returncode == 3
    assert result["status"] == "FAIL"
    assert result["reason"] == "MALFORMED_PAYLOAD"


# --- CLI plumbing ---------------------------------------------------------------

def test_root_flag_is_accepted_and_forwarded(tmp_path):
    """--root is accepted and does not itself change a clean verdict (the
    evidence_db history lookup is optional and this payload's need has no
    matching evidence anyway)."""
    payload = {
        "proposed_command": _vip_owned_proposed_command(),
        "existing_commands": [],
        "ownership": _vip_owned_ownership(),
        "task_evidence": _vip_owned_task_evidence(),
    }
    code, result = run_gate(payload, tmp_path, extra_args=["--root", str(tmp_path)])
    assert code == 0
    assert result["status"] == "PASS"
