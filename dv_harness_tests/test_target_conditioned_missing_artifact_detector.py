"""Tests for dv_harness.target_conditioned_missing_artifact_detector.

Core positive path (a fully-populated inventory reads READY, per target) plus real negative
controls: an unrecognized target, an empty/unassessed inventory, a confirmed-absent category,
an ambiguous value that must never be silently read as present or absent, and cross-target
proof that two different targets derive two genuinely different, specifically-worded missing
sets from the same partial inventory (never a shared generic message).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.target_conditioned_missing_artifact_detector import (
    ARTIFACT_CATEGORY_DESCRIPTIONS,
    INCOMPLETE_EVIDENCE,
    MISSING,
    MISSING_ARTIFACTS,
    NOT_ASSESSED,
    PRESENT,
    READY,
    TARGET_ARTIFACT_TABLE,
    TARGET_COVERAGE_CLOSURE,
    TARGET_REGRESSION_SUBMISSION,
    TARGET_SIGNOFF_PACKAGE,
    TARGET_VIP_UVM_CREATION,
    UNKNOWN_TARGET,
    detect_missing_artifacts,
    execute_verb,
    known_targets,
    render_report_text,
    required_categories_for_target,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _full_inventory_for(target: str, present: bool = True) -> dict:
    return {req.category_id: present for req in required_categories_for_target(target)}


# --- Core positive path -------------------------------------------------------

@pytest.mark.parametrize(
    "target",
    [TARGET_VIP_UVM_CREATION, TARGET_SIGNOFF_PACKAGE, TARGET_COVERAGE_CLOSURE, TARGET_REGRESSION_SUBMISSION],
)
def test_fully_present_inventory_reads_ready_for_every_real_target(target):
    inventory = _full_inventory_for(target, present=True)
    report = detect_missing_artifacts(target, inventory)
    assert report.target_known is True
    assert report.overall_status == READY
    assert report.missing_categories == ()
    assert report.not_assessed_categories == ()
    assert set(report.present_categories) == set(inventory.keys())
    # Every category this target requires must have a real, non-empty per-target reason.
    for f in report.findings:
        assert f.status == PRESENT
        assert f.reason.strip()
        assert f.description.strip()


def test_known_targets_is_the_real_small_explicit_set():
    targets = known_targets()
    assert set(targets) == {
        TARGET_VIP_UVM_CREATION,
        TARGET_SIGNOFF_PACKAGE,
        TARGET_COVERAGE_CLOSURE,
        TARGET_REGRESSION_SUBMISSION,
    }
    # A "small" set: not an unbounded catch-all.
    assert len(targets) <= 6


# --- Negative control 1: unrecognized target ----------------------------------

def test_unrecognized_target_reports_unknown_target_not_a_guessed_requirement_list():
    report = detect_missing_artifacts("NOT_A_REAL_TARGET", {"vip_config_dump": True})
    assert report.target_known is False
    assert report.overall_status == UNKNOWN_TARGET
    assert report.findings == ()
    assert report.missing_categories == ()


# --- Negative control 2: empty / entirely unassessed inventory ----------------

def test_empty_inventory_is_incomplete_evidence_never_ready_never_missing():
    report = detect_missing_artifacts(TARGET_VIP_UVM_CREATION, {})
    assert report.overall_status == INCOMPLETE_EVIDENCE
    assert report.missing_categories == ()
    required_ids = {r.category_id for r in required_categories_for_target(TARGET_VIP_UVM_CREATION)}
    assert set(report.not_assessed_categories) == required_ids
    for f in report.findings:
        assert f.status == NOT_ASSESSED


def test_omitting_the_inventory_argument_entirely_is_also_incomplete_evidence():
    report = detect_missing_artifacts(TARGET_COVERAGE_CLOSURE)
    assert report.overall_status == INCOMPLETE_EVIDENCE
    assert all(f.status == NOT_ASSESSED for f in report.findings)


# --- Negative control 3: a confirmed-absent category ---------------------------

def test_one_confirmed_absent_category_yields_missing_artifacts_naming_it_specifically():
    inventory = _full_inventory_for(TARGET_COVERAGE_CLOSURE, present=True)
    inventory["waiver_ledger"] = False
    report = detect_missing_artifacts(TARGET_COVERAGE_CLOSURE, inventory)
    assert report.overall_status == MISSING_ARTIFACTS
    assert report.missing_categories == ("waiver_ledger",)
    missing_finding = next(f for f in report.findings if f.category_id == "waiver_ledger")
    assert missing_finding.status == MISSING
    # The reason must be specific to COVERAGE_CLOSURE + waiver_ledger, never a generic phrase.
    assert "waiver" in missing_finding.reason.lower()
    assert "coverage_closure" in missing_finding.reason.lower() or "closure" in missing_finding.reason.lower()
    assert "need more files" not in missing_finding.reason.lower()
    assert "missing files" not in missing_finding.reason.lower()


def test_missing_outranks_not_assessed_in_the_overall_verdict():
    inventory = {"waiver_ledger": False}  # everything else omitted -> NOT_ASSESSED
    report = detect_missing_artifacts(TARGET_COVERAGE_CLOSURE, inventory)
    assert report.overall_status == MISSING_ARTIFACTS
    assert "waiver_ledger" in report.missing_categories
    assert len(report.not_assessed_categories) >= 1


# --- Negative control 4: ambiguous values must never be guessed ----------------

@pytest.mark.parametrize("ambiguous_value", [None, "unknown", "yes", 1, 0, [], {}])
def test_ambiguous_value_is_never_read_as_present_or_confirmed_absent(ambiguous_value):
    inventory = {"vip_config_dump": ambiguous_value}
    report = detect_missing_artifacts(TARGET_VIP_UVM_CREATION, inventory)
    finding = next(f for f in report.findings if f.category_id == "vip_config_dump")
    assert finding.status == NOT_ASSESSED


# --- Cross-target proof: two targets derive genuinely different specifics ------

def test_two_different_targets_derive_specifically_different_missing_sets_from_one_inventory():
    # A partial inventory that happens to satisfy one target's needs but not another's, over
    # the categories the two targets actually share.
    shared_inventory = {
        "vip_config_dump": True,
        "dut_rtl_source": True,
        "bind_topology": False,   # confirmed absent
        "register_map": True,
        "phy_boundary_decision": True,
        "vip_symbol_index": True,
        "regression_list": True,
    }
    vip_report = detect_missing_artifacts(TARGET_VIP_UVM_CREATION, shared_inventory)
    regression_report = detect_missing_artifacts(TARGET_REGRESSION_SUBMISSION, shared_inventory)

    assert vip_report.overall_status == MISSING_ARTIFACTS
    assert regression_report.overall_status == MISSING_ARTIFACTS
    assert vip_report.missing_categories == ("bind_topology",)
    assert regression_report.missing_categories == ("bind_topology",)

    vip_reason = next(f for f in vip_report.findings if f.category_id == "bind_topology").reason
    regression_reason = next(
        f for f in regression_report.findings if f.category_id == "bind_topology"
    ).reason
    # Same category, two different targets -> two different, target-specific reasons.
    assert vip_reason != regression_reason
    assert "vip_uvm_creation" in vip_reason.lower()
    assert "regression_submission" in regression_reason.lower()

    # And the two targets' required-category sets are not identical -- proving the table is
    # genuinely target-conditioned rather than one flat list reused everywhere.
    vip_categories = {req.category_id for req in required_categories_for_target(TARGET_VIP_UVM_CREATION)}
    regression_categories = {
        req.category_id for req in required_categories_for_target(TARGET_REGRESSION_SUBMISSION)
    }
    assert vip_categories != regression_categories


def test_every_reason_string_is_distinct_no_generic_reused_message():
    all_reasons = []
    for reqs in TARGET_ARTIFACT_TABLE.values():
        for req in reqs:
            all_reasons.append(req.reason)
    # Every (target, category) reason is authored specifically -- no duplicate reason text
    # reused across different (target, category) pairs.
    assert len(all_reasons) == len(set(all_reasons))


def test_every_declared_category_has_a_real_description():
    declared_categories = {
        req.category_id for reqs in TARGET_ARTIFACT_TABLE.values() for req in reqs
    }
    for cat in declared_categories:
        assert cat in ARTIFACT_CATEGORY_DESCRIPTIONS
        assert ARTIFACT_CATEGORY_DESCRIPTIONS[cat].strip()


# --- render_report_text ---------------------------------------------------------

def test_render_report_text_names_the_missing_category_and_unknown_target_lists_known_targets():
    inventory = _full_inventory_for(TARGET_SIGNOFF_PACKAGE, present=True)
    inventory["coverage_summary"] = False
    report = detect_missing_artifacts(TARGET_SIGNOFF_PACKAGE, inventory)
    text = render_report_text(report)
    assert "coverage_summary" in text
    assert MISSING_ARTIFACTS in text

    unknown_report = detect_missing_artifacts("BOGUS", {})
    unknown_text = render_report_text(unknown_report)
    for name in known_targets():
        assert name in unknown_text


# --- Real subprocess CLI proof ---------------------------------------------------

def test_cli_ready_exit_code_zero(tmp_path):
    inventory_path = tmp_path / "inv.json"
    inventory_path.write_text(
        json.dumps(_full_inventory_for(TARGET_REGRESSION_SUBMISSION, present=True)),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.target_conditioned_missing_artifact_detector",
         TARGET_REGRESSION_SUBMISSION, str(inventory_path)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert READY in result.stdout


def test_cli_missing_artifacts_exit_code_one(tmp_path):
    inventory = _full_inventory_for(TARGET_SIGNOFF_PACKAGE, present=True)
    inventory["golden_scenario_capsule"] = False
    inventory_path = tmp_path / "inv.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.target_conditioned_missing_artifact_detector",
         TARGET_SIGNOFF_PACKAGE, str(inventory_path)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "golden_scenario_capsule" in result.stdout


def test_cli_unknown_target_exit_code_two_no_inventory_file_needed():
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.target_conditioned_missing_artifact_detector", "NOPE"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2, result.stdout + result.stderr


def test_execute_verb_with_no_args_reports_usage_and_exit_two():
    code, report, text = execute_verb([])
    assert code == 2
    assert report.overall_status == UNKNOWN_TARGET
    assert "usage" in text.lower()
