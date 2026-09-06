"""Tests for dv_harness/branch_ownership_resolver.py.

Exercises classify_operation_ownership() / validate_branch_assignment()
against the canonical block/branch_a*/branch_fw/branch_b* architecture
documented in `.claude/skills/CORE/branch-mapper/SKILL.md`,
`.claude/skills/CORE/pattern-architecture/SKILL.md` and CLAUDE.md's
Engineering Discipline Rules. Includes a real command.txt-shaped fixture and
a real small directory tree, and a core positive path plus real negative
controls: an ambiguous/malformed/contradictory input must read as
AMBIGUOUS/UNKNOWN/INVALID, never a confident guess.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.branch_ownership_resolver import (
    AMBIGUOUS,
    ARCH_CONFORMANCE_NAMING_VIOLATION,
    INVALID,
    OWNER_DUT,
    OWNER_FW,
    OWNER_GLOBAL,
    OWNER_VIP,
    RESOLVED,
    UNKNOWN,
    VALID,
    classify_operation_ownership,
    execute_verb,
    validate_branch_assignment,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Real fixture: a small command.txt-shaped text file (a USB-style two-port
# pattern header, in the same block/branch_a*/branch_fw/branch_b* shape the
# pattern-architecture SKILL.md documents) and a small real directory tree
# containing it plus a sibling "legacy" pattern using pre-v8 naming.
# ---------------------------------------------------------------------------

CANONICAL_PATTERN_TXT = """\
// usb20_enumeration.txt -- canonical block/branch_a*/branch_fw/branch_b* shape
`SOC_GLOBAL_INIT(block)
`USB_FORK_PORT_BRINGUP(branch_a0, branch_a1)
`USB_FORK_FW_SERVICE(branch_fw)
fork
  branch_b0: `USB_HOST_ENUM_SEQ(port=0)
  branch_b1: `USB_HOST_ENUM_SEQ(port=1)
join
`FINAL_CHECK("usb20_enumeration")
"""

LEGACY_PATTERN_TXT = """\
// legacy_pattern.txt -- pre-v8 dash-separated, 1-indexed naming
`SOC_GLOBAL_INIT(block)
`USB_FORK_PORT_BRINGUP(branch-a1, branch-a2)
fork
  branch-b1: `USB_HOST_ENUM_SEQ(port=1)
join
`FINAL_CHECK("legacy_pattern")
"""


@pytest.fixture()
def pattern_tree(tmp_path):
    patterns_dir = tmp_path / "patterns"
    patterns_dir.mkdir()
    (patterns_dir / "usb20_enumeration.txt").write_text(CANONICAL_PATTERN_TXT, encoding="utf-8")
    (patterns_dir / "legacy_pattern.txt").write_text(LEGACY_PATTERN_TXT, encoding="utf-8")
    return patterns_dir


def _branch_labels_in(pattern_text: str) -> list:
    """Minimal, honest extraction: pull the labels this fixture actually
    declares (before a ':' at line start, or inside the FORK_PORT_BRINGUP
    macro args), rather than pretending to be a real command.txt parser."""
    labels = []
    for line in pattern_text.splitlines():
        line = line.strip()
        if ":" in line and line.split(":", 1)[0].strip().startswith("branch"):
            labels.append(line.split(":", 1)[0].strip())
    return labels


def test_fixture_extraction_sees_the_real_branch_b_labels(pattern_tree):
    canonical_text = (pattern_tree / "usb20_enumeration.txt").read_text(encoding="utf-8")
    assert _branch_labels_in(canonical_text) == ["branch_b0", "branch_b1"]
    legacy_text = (pattern_tree / "legacy_pattern.txt").read_text(encoding="utf-8")
    assert _branch_labels_in(legacy_text) == ["branch-b1"]


# ---------------------------------------------------------------------------
# classify_operation_ownership -- core positive paths (fixed-tier kinds)
# ---------------------------------------------------------------------------


def test_classify_soc_global_init_is_global():
    result = classify_operation_ownership(
        "SOC_GLOBAL_ONE_SHOT_INIT", per_port=False, driven_by="DUT_BRINGUP_FLOW"
    )
    assert result.status == RESOLVED
    assert result.tier == OWNER_GLOBAL


def test_classify_dut_phy_bringup_is_dut():
    result = classify_operation_ownership(
        "DUT_PHY_PORT_BRINGUP", per_port=True, driven_by="DUT_BRINGUP_FLOW"
    )
    assert result.status == RESOLVED
    assert result.tier == OWNER_DUT


def test_classify_fw_event_service_loop_is_fw():
    result = classify_operation_ownership(
        "FW_EVENT_SERVICE_LOOP", per_port=True, driven_by="FW_FIRMWARE_MODEL"
    )
    assert result.status == RESOLVED
    assert result.tier == OWNER_FW


def test_classify_vip_driven_test_body_is_vip():
    result = classify_operation_ownership(
        "VIP_DRIVEN_TEST_BODY", per_port=True, driven_by="VIP_SEQUENCE"
    )
    assert result.status == RESOLVED
    assert result.tier == OWNER_VIP


def test_classify_vip_driven_data_transfer_is_vip():
    result = classify_operation_ownership("VIP_DRIVEN_DATA_TRANSFER", per_port=True)
    assert result.status == RESOLVED
    assert result.tier == OWNER_VIP


def test_classify_fixed_tier_kind_with_no_extra_facts_still_resolves():
    # A fixed-tier kind's tier follows from the kind alone; per_port/driven_by
    # are optional consistency checks, not requirements.
    result = classify_operation_ownership("FW_EVENT_SERVICE_LOOP")
    assert result.status == RESOLVED
    assert result.tier == OWNER_FW


# ---------------------------------------------------------------------------
# classify_operation_ownership -- context-dependent kinds
# ---------------------------------------------------------------------------


def test_classify_raw_dut_write_per_port_true_is_dut():
    result = classify_operation_ownership(
        "RAW_DUT_REGISTER_WRITE", per_port=True, driven_by="DUT_BRINGUP_FLOW"
    )
    assert result.status == RESOLVED
    assert result.tier == OWNER_DUT


def test_classify_raw_dut_write_per_port_false_is_global():
    result = classify_operation_ownership(
        "RAW_DUT_REGISTER_WRITE", per_port=False, driven_by="HOST_SCRIPT_INIT"
    )
    assert result.status == RESOLVED
    assert result.tier == OWNER_GLOBAL


def test_classify_shared_resource_access_with_policy_resolves():
    result = classify_operation_ownership(
        "SHARED_RESOURCE_ARBITRATED_ACCESS",
        per_port=True,
        arbitration_policy="round-robin, verified against arbiter RTL u_apb_arb",
    )
    assert result.status == RESOLVED
    assert result.tier == OWNER_DUT


# ---------------------------------------------------------------------------
# Negative controls: ambiguous/malformed/contradictory inputs must read as
# AMBIGUOUS/UNKNOWN, never a confident guess. (Required: at least 3-5.)
# ---------------------------------------------------------------------------


def test_negative_unrecognized_operation_kind_is_unknown():
    result = classify_operation_ownership("SOMETHING_MADE_UP")
    assert result.status == UNKNOWN
    assert result.tier is None
    assert "not in the recognized taxonomy" in result.reason


def test_negative_missing_operation_kind_is_unknown():
    result = classify_operation_ownership(None)
    assert result.status == UNKNOWN
    assert result.tier is None


def test_negative_raw_dut_write_with_no_per_port_is_ambiguous():
    result = classify_operation_ownership(
        "RAW_DUT_REGISTER_WRITE", driven_by="DUT_BRINGUP_FLOW"
    )
    assert result.status == AMBIGUOUS
    assert result.tier is None
    assert "per_port not declared" in result.reason


def test_negative_raw_dut_write_driven_by_vip_is_contradictory_ambiguous():
    # A "raw DUT register write" claimed to be VIP-issued is an internal
    # contradiction -- must not be silently classified as either DUT or VIP.
    result = classify_operation_ownership(
        "RAW_DUT_REGISTER_WRITE", per_port=True, driven_by="VIP_SEQUENCE"
    )
    assert result.status == AMBIGUOUS
    assert result.tier is None
    assert "contradictory declared facts" in result.reason


def test_negative_shared_resource_access_with_no_arbitration_policy_is_ambiguous():
    result = classify_operation_ownership(
        "SHARED_RESOURCE_ARBITRATED_ACCESS", per_port=True
    )
    assert result.status == AMBIGUOUS
    assert "arbitration_policy" in result.reason


def test_negative_fixed_tier_kind_contradicted_by_per_port_is_ambiguous():
    # DUT_PHY_PORT_BRINGUP is canonically per-port; declaring per_port=False
    # contradicts its own grounding and must not be silently overridden.
    result = classify_operation_ownership("DUT_PHY_PORT_BRINGUP", per_port=False)
    assert result.status == AMBIGUOUS
    assert "contradicts operation_kind" in result.reason


def test_negative_fixed_tier_kind_contradicted_by_driven_by_is_ambiguous():
    result = classify_operation_ownership(
        "VIP_DRIVEN_TEST_BODY", driven_by="DUT_BRINGUP_FLOW"
    )
    assert result.status == AMBIGUOUS
    assert "contradicts operation_kind" in result.reason


def test_negative_unrecognized_driven_by_is_ambiguous():
    result = classify_operation_ownership(
        "DUT_PHY_PORT_BRINGUP", driven_by="SOME_UNKNOWN_DRIVER"
    )
    assert result.status == AMBIGUOUS
    assert "not a recognized value" in result.reason


# ---------------------------------------------------------------------------
# validate_branch_assignment -- core positive paths
# ---------------------------------------------------------------------------


def test_validate_block_soc_global_init_is_valid():
    result = validate_branch_assignment(
        "block", "SOC_GLOBAL_ONE_SHOT_INIT", per_port=False, driven_by="DUT_BRINGUP_FLOW"
    )
    assert result.verdict == VALID
    assert result.violated_rule is None
    assert result.expected_tier == OWNER_GLOBAL == result.assigned_tier


def test_validate_branch_a_dut_phy_bringup_is_valid():
    result = validate_branch_assignment(
        "branch_a0", "DUT_PHY_PORT_BRINGUP", per_port=True, driven_by="DUT_BRINGUP_FLOW"
    )
    assert result.verdict == VALID


def test_validate_branch_fw_service_loop_is_valid():
    result = validate_branch_assignment(
        "branch_fw", "FW_EVENT_SERVICE_LOOP", per_port=True, driven_by="FW_FIRMWARE_MODEL"
    )
    assert result.verdict == VALID


def test_validate_branch_b_vip_test_body_is_valid():
    result = validate_branch_assignment(
        "branch_b1", "VIP_DRIVEN_TEST_BODY", per_port=True, driven_by="VIP_SEQUENCE"
    )
    assert result.verdict == VALID


# ---------------------------------------------------------------------------
# validate_branch_assignment -- the three headline INVALID examples the task
# names verbatim, plus their mirror-image mismatches.
# ---------------------------------------------------------------------------


def test_invalid_vip_driven_transfer_assigned_to_branch_a():
    result = validate_branch_assignment(
        "branch_a0", "VIP_DRIVEN_DATA_TRANSFER", per_port=True, driven_by="VIP_SEQUENCE"
    )
    assert result.verdict == INVALID
    assert result.violated_rule == "VIP_DRIVEN_WORK_ASSIGNED_TO_BRANCH_A"
    assert result.expected_tier == OWNER_VIP
    assert result.assigned_tier == OWNER_DUT


def test_invalid_raw_dut_write_assigned_to_branch_b():
    result = validate_branch_assignment(
        "branch_b0",
        "RAW_DUT_REGISTER_WRITE",
        per_port=True,
        driven_by="DUT_BRINGUP_FLOW",
    )
    assert result.verdict == INVALID
    assert result.violated_rule == "RAW_DUT_OPERATION_ASSIGNED_TO_BRANCH_B"
    assert result.expected_tier == OWNER_DUT
    assert result.assigned_tier == OWNER_VIP


def test_invalid_fw_service_loop_duplicated_inside_branch_b():
    result = validate_branch_assignment(
        "branch_b0", "FW_EVENT_SERVICE_LOOP", per_port=True, driven_by="FW_FIRMWARE_MODEL"
    )
    assert result.verdict == INVALID
    assert result.violated_rule == "FW_SERVICE_LOOP_DUPLICATED_IN_BRANCH_B"
    assert result.expected_tier == OWNER_FW
    assert result.assigned_tier == OWNER_VIP


def test_invalid_global_init_split_across_branch_a():
    result = validate_branch_assignment(
        "branch_a0", "SOC_GLOBAL_ONE_SHOT_INIT", per_port=False, driven_by="DUT_BRINGUP_FLOW"
    )
    assert result.verdict == INVALID
    assert result.violated_rule == "GLOBAL_INIT_SPLIT_ACROSS_BRANCH_A"


def test_invalid_per_port_dut_init_collapsed_into_block():
    result = validate_branch_assignment(
        "block", "DUT_PHY_PORT_BRINGUP", per_port=True, driven_by="DUT_BRINGUP_FLOW"
    )
    assert result.verdict == INVALID
    assert result.violated_rule == "PER_PORT_DUT_INIT_COLLAPSED_INTO_BLOCK"


def test_invalid_vip_work_assigned_to_block():
    result = validate_branch_assignment(
        "block", "VIP_DRIVEN_TEST_BODY", per_port=True, driven_by="VIP_SEQUENCE"
    )
    assert result.verdict == INVALID
    assert result.violated_rule == "VIP_DRIVEN_WORK_ASSIGNED_TO_BLOCK"


def test_invalid_fw_loop_assigned_to_branch_a():
    result = validate_branch_assignment(
        "branch_a0", "FW_EVENT_SERVICE_LOOP", per_port=True, driven_by="FW_FIRMWARE_MODEL"
    )
    assert result.verdict == INVALID
    assert result.violated_rule == "FW_SERVICE_LOOP_ASSIGNED_TO_BRANCH_A"


# ---------------------------------------------------------------------------
# validate_branch_assignment -- naming-conformance negative controls
# ---------------------------------------------------------------------------


def test_negative_legacy_dash_separated_branch_name_is_invalid(pattern_tree):
    legacy_labels = _branch_labels_in(
        (pattern_tree / "legacy_pattern.txt").read_text(encoding="utf-8")
    )
    assert legacy_labels == ["branch-b1"]
    result = validate_branch_assignment(
        legacy_labels[0], "VIP_DRIVEN_TEST_BODY", per_port=True, driven_by="VIP_SEQUENCE"
    )
    assert result.verdict == INVALID
    assert result.violated_rule == ARCH_CONFORMANCE_NAMING_VIOLATION
    assert "legacy" in result.reason.lower()


def test_negative_uppercase_category_tag_is_invalid():
    result = validate_branch_assignment(
        "BRANCH_A_DUT", "DUT_PHY_PORT_BRINGUP", per_port=True, driven_by="DUT_BRINGUP_FLOW"
    )
    assert result.verdict == INVALID
    assert result.violated_rule == ARCH_CONFORMANCE_NAMING_VIOLATION


def test_negative_completely_unrelated_label_is_invalid():
    result = validate_branch_assignment(
        "port0_sequence", "VIP_DRIVEN_TEST_BODY", per_port=True, driven_by="VIP_SEQUENCE"
    )
    assert result.verdict == INVALID
    assert result.violated_rule == ARCH_CONFORMANCE_NAMING_VIOLATION


def test_negative_missing_branch_label_is_invalid():
    result = validate_branch_assignment(None, "VIP_DRIVEN_TEST_BODY", per_port=True)
    assert result.verdict == INVALID
    assert result.violated_rule == ARCH_CONFORMANCE_NAMING_VIOLATION


# ---------------------------------------------------------------------------
# validate_branch_assignment -- unresolved classification propagates as
# AMBIGUOUS rather than being silently treated as VALID or INVALID.
# ---------------------------------------------------------------------------


def test_negative_validate_with_unrecognized_operation_kind_is_ambiguous():
    result = validate_branch_assignment("branch_b0", "NOT_A_REAL_KIND")
    assert result.verdict == AMBIGUOUS
    assert result.violated_rule is None
    assert result.assigned_tier == OWNER_VIP  # the name itself IS canonical
    assert result.classification.status == UNKNOWN


def test_negative_validate_raw_dut_write_missing_per_port_is_ambiguous():
    result = validate_branch_assignment(
        "branch_a0", "RAW_DUT_REGISTER_WRITE", driven_by="DUT_BRINGUP_FLOW"
    )
    assert result.verdict == AMBIGUOUS
    assert result.classification.status == AMBIGUOUS


# ---------------------------------------------------------------------------
# CLI front door (execute_verb), against a real payload file on disk.
# ---------------------------------------------------------------------------


def test_execute_verb_classify_real_payload_file(tmp_path):
    payload = tmp_path / "op.json"
    payload.write_text(
        json.dumps(
            {
                "operation_kind": "VIP_DRIVEN_TEST_BODY",
                "per_port": True,
                "driven_by": "VIP_SEQUENCE",
            }
        ),
        encoding="utf-8",
    )
    exit_code, result = execute_verb("classify", payload_path=str(payload))
    assert exit_code == 0
    assert result["tier"] == OWNER_VIP


def test_execute_verb_validate_real_payload_file_invalid(tmp_path):
    payload = tmp_path / "assignment.json"
    payload.write_text(
        json.dumps(
            {
                "branch_label": "branch_b0",
                "operation_kind": "FW_EVENT_SERVICE_LOOP",
                "per_port": True,
                "driven_by": "FW_FIRMWARE_MODEL",
            }
        ),
        encoding="utf-8",
    )
    exit_code, result = execute_verb("validate", payload_path=str(payload))
    assert exit_code == 1
    assert result["violated_rule"] == "FW_SERVICE_LOOP_DUPLICATED_IN_BRANCH_B"


def test_execute_verb_missing_payload_is_unknown_exit_2():
    exit_code, result = execute_verb("classify", payload_path=None)
    assert exit_code == 2
    assert result["status"] == UNKNOWN


def test_cli_subprocess_real_run(tmp_path):
    payload = tmp_path / "assignment.json"
    payload.write_text(
        json.dumps(
            {
                "branch_label": "branch_a0",
                "operation_kind": "VIP_DRIVEN_DATA_TRANSFER",
                "per_port": True,
                "driven_by": "VIP_SEQUENCE",
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.branch_ownership_resolver", "validate",
         "--payload", str(payload)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    assert out["violated_rule"] == "VIP_DRIVEN_WORK_ASSIGNED_TO_BRANCH_A"
