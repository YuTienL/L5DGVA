"""Tests for dv_harness.artifact_completeness.

Core positive path (a fully-populated sub-fact inventory reads ARTIFACT_COMPLETE, per real
category) plus real negative controls: an unrecognized category, an empty/unassessed inventory, a
confirmed-absent sub-fact, an ambiguous value that must never be silently read as present or
absent, and proof that the module's own real category vocabulary is reused (not duplicated) from
target_conditioned_missing_artifact_detector.py.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.artifact_completeness import (
    ARTIFACT_ASSESSMENT_INCOMPLETE,
    ARTIFACT_COMPLETE,
    ARTIFACT_INCOMPLETE,
    ARTIFACT_REQUIRED_SUBFACTS,
    ARTIFACT_UNKNOWN_CATEGORY,
    SUBFACT_MISSING,
    SUBFACT_NOT_ASSESSED,
    SUBFACT_PRESENT,
    assess_all_artifacts,
    assess_artifact_completeness,
    execute_verb,
    known_artifact_categories,
    render_report_text,
    required_subfacts_for_category,
)
from dv_harness.target_conditioned_missing_artifact_detector import (
    ARTIFACT_CATEGORY_DESCRIPTIONS,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _full_inventory_for(category: str, present: bool = True) -> dict:
    return {req.subfact_id: present for req in required_subfacts_for_category(category)}


# --- Reuse proof: the category vocabulary is imported, never duplicated -------

def test_every_declared_category_is_a_real_target_conditioned_category():
    for category in known_artifact_categories():
        assert category in ARTIFACT_CATEGORY_DESCRIPTIONS


# --- Core positive path -------------------------------------------------------

@pytest.mark.parametrize("category", list(ARTIFACT_REQUIRED_SUBFACTS.keys()))
def test_fully_present_inventory_reads_complete_for_every_real_category(category):
    inventory = _full_inventory_for(category, present=True)
    report = assess_artifact_completeness(category, inventory)
    assert report.category_known is True
    assert report.artifact_status == ARTIFACT_COMPLETE
    assert report.missing_subfacts == ()
    assert report.not_assessed_subfacts == ()
    assert set(report.present_subfacts) == set(inventory.keys())
    for f in report.findings:
        assert f.status == SUBFACT_PRESENT
        assert f.reason.strip()
    assert report.description == ARTIFACT_CATEGORY_DESCRIPTIONS[category]


def test_known_artifact_categories_is_the_real_full_set():
    categories = known_artifact_categories()
    assert set(categories) == set(ARTIFACT_CATEGORY_DESCRIPTIONS.keys())
    # Every real category has a real, non-trivial (>=2) subfact list.
    for category in categories:
        assert len(required_subfacts_for_category(category)) >= 2


# --- Negative control 1: unrecognized category --------------------------------

def test_unrecognized_category_reports_unknown_category_not_a_guessed_subfact_list():
    report = assess_artifact_completeness("NOT_A_REAL_CATEGORY", {"anything": True})
    assert report.category_known is False
    assert report.artifact_status == ARTIFACT_UNKNOWN_CATEGORY
    assert report.findings == ()
    assert report.missing_subfacts == ()


# --- Negative control 2: empty / entirely unassessed inventory ----------------

def test_empty_inventory_is_assessment_incomplete_never_complete_never_incomplete():
    report = assess_artifact_completeness("register_map", {})
    assert report.artifact_status == ARTIFACT_ASSESSMENT_INCOMPLETE
    assert report.missing_subfacts == ()
    required_ids = {r.subfact_id for r in required_subfacts_for_category("register_map")}
    assert set(report.not_assessed_subfacts) == required_ids
    for f in report.findings:
        assert f.status == SUBFACT_NOT_ASSESSED


def test_omitting_the_inventory_argument_entirely_is_also_assessment_incomplete():
    report = assess_artifact_completeness("coverage_summary")
    assert report.artifact_status == ARTIFACT_ASSESSMENT_INCOMPLETE
    assert all(f.status == SUBFACT_NOT_ASSESSED for f in report.findings)


# --- Negative control 3: a confirmed-absent sub-fact ---------------------------

def test_one_confirmed_absent_subfact_yields_artifact_incomplete_naming_it_specifically():
    inventory = _full_inventory_for("waiver_ledger", present=True)
    inventory["every_waiver_has_expiry_or_trigger"] = False
    report = assess_artifact_completeness("waiver_ledger", inventory)
    assert report.artifact_status == ARTIFACT_INCOMPLETE
    assert report.missing_subfacts == ("every_waiver_has_expiry_or_trigger",)
    missing_finding = next(
        f for f in report.findings if f.subfact_id == "every_waiver_has_expiry_or_trigger"
    )
    assert missing_finding.status == SUBFACT_MISSING
    assert "waiver" in missing_finding.reason.lower()
    assert "trigger" in missing_finding.reason.lower() or "expiry" in missing_finding.reason.lower()


def test_missing_outranks_not_assessed_in_the_overall_verdict():
    inventory = {"capsule_verified_sha_present": False}  # everything else omitted -> NOT_ASSESSED
    report = assess_artifact_completeness("golden_scenario_capsule", inventory)
    assert report.artifact_status == ARTIFACT_INCOMPLETE
    assert "capsule_verified_sha_present" in report.missing_subfacts
    assert len(report.not_assessed_subfacts) >= 1


# --- Negative control 4: ambiguous values must never be guessed ----------------

@pytest.mark.parametrize("ambiguous_value", [None, "unknown", "yes", 1, 0, [], {}])
def test_ambiguous_value_is_never_read_as_present_or_confirmed_absent(ambiguous_value):
    inventory = {"module_hierarchy_parsed": ambiguous_value}
    report = assess_artifact_completeness("dut_rtl_source", inventory)
    finding = next(f for f in report.findings if f.subfact_id == "module_hierarchy_parsed")
    assert finding.status == SUBFACT_NOT_ASSESSED


# --- Cross-category proof: two categories derive specifically different findings ----

def test_two_different_categories_derive_specifically_different_subfact_sets():
    vip_report = assess_artifact_completeness("vip_config_dump", {})
    reg_report = assess_artifact_completeness("register_map", {})
    vip_ids = {f.subfact_id for f in vip_report.findings}
    reg_ids = {f.subfact_id for f in reg_report.findings}
    assert vip_ids != reg_ids


def test_every_reason_string_is_distinct_no_generic_reused_message():
    all_reasons = []
    for reqs in ARTIFACT_REQUIRED_SUBFACTS.values():
        for req in reqs:
            all_reasons.append(req.reason)
    assert len(all_reasons) == len(set(all_reasons))


def test_every_subfact_id_is_unique_within_its_own_category():
    for category, reqs in ARTIFACT_REQUIRED_SUBFACTS.items():
        ids = [r.subfact_id for r in reqs]
        assert len(ids) == len(set(ids)), f"duplicate subfact id within {category!r}"


# --- assess_all_artifacts batch form -------------------------------------------

def test_assess_all_artifacts_only_assesses_what_the_caller_supplied():
    inventories = {
        "vip_config_dump": _full_inventory_for("vip_config_dump", present=True),
        "register_map": {},
    }
    reports = assess_all_artifacts(inventories)
    assert set(reports.keys()) == {"vip_config_dump", "register_map"}
    assert reports["vip_config_dump"].artifact_status == ARTIFACT_COMPLETE
    assert reports["register_map"].artifact_status == ARTIFACT_ASSESSMENT_INCOMPLETE
    # A category never mentioned is simply absent from the batch result, never fabricated.
    assert "coverage_summary" not in reports


# --- render_report_text ---------------------------------------------------------

def test_render_report_text_names_the_missing_subfact_and_unknown_category_lists_known_categories():
    inventory = _full_inventory_for("signoff_gate_evidence", present=True)
    inventory["signoff_stage_gates_cleared"] = False
    report = assess_artifact_completeness("signoff_gate_evidence", inventory)
    text = render_report_text(report)
    assert "signoff_stage_gates_cleared" in text
    assert ARTIFACT_INCOMPLETE in text

    unknown_report = assess_artifact_completeness("BOGUS", {})
    unknown_text = render_report_text(unknown_report)
    for name in known_artifact_categories():
        assert name in unknown_text


# --- Real subprocess CLI proof ---------------------------------------------------

def test_cli_complete_exit_code_zero(tmp_path):
    inventory_path = tmp_path / "inv.json"
    inventory_path.write_text(
        json.dumps(_full_inventory_for("regression_list", present=True)),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.artifact_completeness", "regression_list", str(inventory_path)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert ARTIFACT_COMPLETE in result.stdout


def test_cli_incomplete_exit_code_one(tmp_path):
    inventory = _full_inventory_for("testplan_correspondence", present=True)
    inventory["testplan_items_linked_to_coverage"] = False
    inventory_path = tmp_path / "inv.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.artifact_completeness", "testplan_correspondence", str(inventory_path)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "testplan_items_linked_to_coverage" in result.stdout


def test_cli_unknown_category_exit_code_two_no_inventory_file_needed():
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.artifact_completeness", "NOPE"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2, result.stdout + result.stderr


def test_execute_verb_with_no_args_reports_usage_and_exit_two():
    code, report, text = execute_verb([])
    assert code == 2
    assert report.artifact_status == ARTIFACT_UNKNOWN_CATEGORY
    assert "usage" in text.lower()
