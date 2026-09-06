"""Tests for dv_harness/spec_vplan_delta.py -- semantic diffing of a spec
document's content against a previously-recorded requirement-IR-shaped
baseline. Fixtures are synthetic requirement-IR-shaped records constructed
directly (no requirement-IR producer is guaranteed to exist in this repo),
some declaring the real section-184 contract shape
(`contract_schema_version`) so `requirement_contract.derive_status()` reuse
is exercised against a REAL function, never a stub.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import spec_vplan_delta as m
from dv_harness import change_impact


def _contract_record(req_id: str, **overrides) -> dict:
    """A minimal, fully-populated section-184 contract-shaped record (every
    field resolved, status COMPLETE) -- the same clean-baseline convention
    `test_requirement_contract.py` establishes."""
    rec = {
        "contract_schema_version": "1.0",
        "requirement_id": req_id,
        "source": {"document": "usb31_spec.pdf", "section": "8.4.2"},
        "feature": "LFPS handshake",
        "protocol": "USB3",
        "configuration": "NONE",
        "precondition": "NONE",
        "stimulus": "host asserts LFPS.Handshake",
        "expected_result": "device responds within 400ns",
        "observability": "monitor lfps_state signal",
        "checker": "lfps_response_time_checker",
        "coverage_intent": "cover lfps handshake latency bins",
        "priority": "P1",
        "criticality": "MAJOR",
        "confidence": "HIGH",
        "status": "COMPLETE",
    }
    rec.update(overrides)
    return rec


def _generic_record(req_id: str, **overrides) -> dict:
    """A plain, non-contract-shaped requirement-IR record -- proves the
    diff works with no requirement_contract producer involved at all."""
    rec = {
        "req_id": req_id,
        "expected_result": "device asserts ready within 2 clocks",
        "stimulus": "assert req",
        "notes": "extracted by hand",
    }
    rec.update(overrides)
    return rec


# --------------------------------------------------------------------------
# core positive path
# --------------------------------------------------------------------------

def test_added_modified_removed_revalidation_and_unchanged_all_classified():
    before = [
        _contract_record("REQ-1"),
        _contract_record("REQ-2"),
        _contract_record("REQ-3"),
        _contract_record("REQ-4"),
    ]
    after = [
        _contract_record("REQ-1"),  # byte-identical -> UNCHANGED
        _contract_record("REQ-2", expected_result="device responds within 200ns"),  # content changed
        _contract_record("REQ-4", confidence="MEDIUM"),  # only provenance changed
        _contract_record("REQ-5"),  # new
        # REQ-3 dropped -> REMOVED
    ]
    result = m.diff_requirement_sets(before, after)
    assert result["status"] == "DELTA_FOUND"
    by_id = {it["requirement_id"]: it for it in result["items"]}

    assert by_id["REQ-1"]["status"] == m.STATUS_UNCHANGED
    assert by_id["REQ-2"]["status"] == m.STATUS_MODIFIED
    assert "expected_result" in by_id["REQ-2"]["changed_content_fields"]
    assert by_id["REQ-3"]["status"] == m.STATUS_REMOVED
    assert by_id["REQ-4"]["status"] == m.STATUS_REVALIDATION_REQUIRED
    assert "confidence" in by_id["REQ-4"]["changed_revalidation_fields"]
    assert by_id["REQ-5"]["status"] == m.STATUS_ADDED

    assert result["status_counts"] == {
        "ADDED": 1, "MODIFIED": 1, "REMOVED": 1,
        "REVALIDATION_REQUIRED": 1, "UNCHANGED": 1,
    }


def test_no_delta_when_snapshots_are_identical():
    before = [_contract_record("REQ-1"), _contract_record("REQ-2")]
    after = [_contract_record("REQ-2"), _contract_record("REQ-1")]  # reordered, identical content
    result = m.diff_requirement_sets(before, after)
    assert result["status"] == "NO_DELTA"
    assert result["status_counts"]["UNCHANGED"] == 2
    assert all(it["status"] == m.STATUS_UNCHANGED for it in result["items"])


def test_generic_non_contract_shaped_records_work_with_no_producer():
    before = [_generic_record("R1")]
    after = [_generic_record("R1", stimulus="assert req for 3 clocks")]
    result = m.diff_requirement_sets(before, after)
    item = result["items"][0]
    assert item["status"] == m.STATUS_MODIFIED
    assert "stimulus" in item["changed_content_fields"]
    # `notes` unchanged and not asked about since content already differs,
    # but content_fields_for must never have included it as content:
    assert "notes" not in item["changed_content_fields"]


def test_provenance_only_change_on_generic_record_is_revalidation_required():
    before = [_generic_record("R1")]
    after = [_generic_record("R1", notes="re-checked against rev B of the spec")]
    result = m.diff_requirement_sets(before, after)
    item = result["items"][0]
    assert item["status"] == m.STATUS_REVALIDATION_REQUIRED
    assert "notes" in item["changed_revalidation_fields"]


# --------------------------------------------------------------------------
# negative controls
# --------------------------------------------------------------------------

def test_empty_string_vs_missing_field_is_not_a_false_modified():
    """A record re-serialized with an explicit empty string for a field the
    other side simply omitted must not read as a content change -- that
    would manufacture MODIFIED findings out of formatting noise."""
    before = [_generic_record("R1", junk_field=None)]
    after = [_generic_record("R1", junk_field="")]
    result = m.diff_requirement_sets(before, after)
    assert result["items"][0]["status"] == m.STATUS_UNCHANGED


def test_content_change_wins_over_simultaneous_provenance_change():
    """MODIFIED must outrank REVALIDATION_REQUIRED (worst-wins): a real
    behavioural change is never demoted to a mere provenance note just
    because provenance also moved in the same edit."""
    before = [_contract_record("REQ-1")]
    after = [_contract_record("REQ-1", checker="new_checker_class",
                              confidence="LOW")]
    result = m.diff_requirement_sets(before, after)
    item = result["items"][0]
    assert item["status"] == m.STATUS_MODIFIED
    assert "checker" in item["changed_content_fields"]
    # the confidence drop must NOT leak into the MODIFIED item's detail as
    # if it were the reason -- MODIFIED carries only content fields.
    assert "changed_revalidation_fields" not in item


def test_duplicate_identity_is_reported_not_silently_merged():
    before = [_contract_record("REQ-1")]
    after = [_contract_record("REQ-1"), _contract_record("REQ-1", checker="dup_checker")]
    result = m.diff_requirement_sets(before, after)
    assert "REQ-1" in result["duplicate_identities"]["after"]
    # the first occurrence still gets classified so the run does not crash
    assert any(it["requirement_id"] == "REQ-1" for it in result["items"])


def test_unidentified_record_is_counted_not_dropped():
    before = [{"expected_result": "no id at all here"}]
    after = []
    result = m.diff_requirement_sets(before, after)
    assert result["unidentified_records"]["before"] == 1
    assert result["items"] == []  # nothing to classify, but nothing crashed either


def test_both_empty_is_not_available_never_a_clean_pass():
    result = m.diff_requirement_sets([], [])
    assert result["status"] == "NOT_AVAILABLE"


def test_caller_declared_identity_field_is_honored():
    before = [{"my_id": "X1", "expected_result": "a"}]
    after = [{"my_id": "X1", "expected_result": "b"}]
    result = m.diff_requirement_sets(before, after, identity_field="my_id")
    assert result["items"][0]["requirement_id"] == "X1"
    assert result["items"][0]["status"] == m.STATUS_MODIFIED


def test_derived_status_delta_reuses_real_requirement_contract_function():
    """A requirement whose content moved from COMPLETE-supporting to
    AMBIGUOUS-supporting (an unresolved ambiguity filed) must show that via
    the REAL requirement_contract.derive_status(), not a re-implementation."""
    before = _contract_record("REQ-1")
    after = _contract_record("REQ-1", checker="new_checker",
                             ambiguities=[{"question": "which clock domain?"}],
                             status="AMBIGUOUS")
    result = m.diff_requirement_sets([before], [after])
    item = result["items"][0]
    assert item["status"] == m.STATUS_MODIFIED  # checker changed too
    assert item["derived_status_delta"]["before"] == "COMPLETE"
    assert item["derived_status_delta"]["after"] == "AMBIGUOUS"


def test_derived_status_delta_absent_when_not_contract_shaped():
    before = [_generic_record("R1")]
    after = [_generic_record("R1", stimulus="different")]
    result = m.diff_requirement_sets(before, after)
    assert "derived_status_delta" not in result["items"][0]


# --------------------------------------------------------------------------
# vPlan traceability linkage (real registry, read-only)
# --------------------------------------------------------------------------

def test_vplan_linkage_not_requested_without_root():
    before = [_contract_record("REQ-1")]
    after = [_contract_record("REQ-1", checker="x")]
    result = m.diff_requirement_sets(before, after)
    assert result["items"][0]["vplan_linkage"]["status"] == m.LINKAGE_NOT_REQUESTED
    assert result["vplan_linkage_requested"] is False


def test_vplan_linkage_reads_the_real_requirements_csv_registry(tmp_path):
    dv = tmp_path / ".dv-harness"
    dv.mkdir()
    (dv / "requirements.csv").write_text(
        "REQ_ID,SOURCE,SCOPE,VPLAN_ID,SCENARIO_ID,COMMAND_ID,PATTERN_ID,"
        "CHECKER_ID,COVERAGE_ID,RESULT,STATUS,EVIDENCE\n"
        "REQ-1,spec,usb3,VP-100,SC-1,CMD-1,PAT-1,CHK-1,COV-1,PASS,CLOSED,ev1\n",
        encoding="utf-8",
    )
    before = [_contract_record("REQ-1")]
    after = [_contract_record("REQ-1", checker="new_checker")]
    result = m.diff_requirement_sets(before, after, root=tmp_path)
    linkage = result["items"][0]["vplan_linkage"]
    assert linkage["status"] == "LINKED"
    assert linkage["rows"][0]["vplan_id"] == "VP-100"
    assert result["vplan_linkage_requested"] is True

    # cross-check against the REAL change_impact reader directly, so a
    # future change to load_trace_registry's shape is caught here too.
    real_rows = change_impact.load_trace_registry(tmp_path)
    assert real_rows[0]["VPLAN_ID"] == "VP-100"


def test_vplan_linkage_honest_no_registry_row_vs_no_registry_at_all(tmp_path):
    # a project root with a registry, but no row for this requirement
    dv = tmp_path / ".dv-harness"
    dv.mkdir()
    (dv / "requirements.csv").write_text(
        "REQ_ID,SOURCE,SCOPE,VPLAN_ID,SCENARIO_ID,COMMAND_ID,PATTERN_ID,"
        "CHECKER_ID,COVERAGE_ID,RESULT,STATUS,EVIDENCE\n"
        "REQ-OTHER,spec,usb3,VP-200,,,,,,,,\n",
        encoding="utf-8",
    )
    before = [_contract_record("REQ-1")]
    after = [_contract_record("REQ-1", checker="new_checker")]
    result = m.diff_requirement_sets(before, after, root=tmp_path)
    assert result["items"][0]["vplan_linkage"]["status"] == m.LINKAGE_NO_REGISTRY_ROW

    # a project root with NO registry file at all
    empty_root = tmp_path / "no_registry_project"
    empty_root.mkdir()
    result2 = m.diff_requirement_sets(before, after, root=empty_root)
    # load_trace_registry() itself reports an empty registry (missing file
    # is a real, correct empty state per its own docstring) -- this must
    # surface as NO_REGISTRY_ROW too, not a crash or a fabricated linkage.
    assert result2["items"][0]["vplan_linkage"]["status"] == m.LINKAGE_NO_REGISTRY_ROW


# --------------------------------------------------------------------------
# the real change_impact.py axis is genuinely different (sanity check the
# claim this module's docstring makes, rather than merely asserting it)
# --------------------------------------------------------------------------

def test_change_impact_is_a_file_diff_axis_not_a_content_diff_axis(tmp_path):
    """change_impact.compute_and_write() needs a real git repo and a real
    file-system diff; it has no function that accepts two in-memory
    requirement-IR documents. Confirms the two modules are not duplicating
    one mechanism under two names."""
    assert not hasattr(change_impact, "diff_requirement_sets")
    assert not hasattr(change_impact, "classify_requirement_delta")
    # change_impact's real entry point requires git plumbing (base/head SHAs
    # against an actual repo), demonstrated by it raising nothing useful over
    # a bare non-git directory rather than accepting two JSON documents:
    result = change_impact.compute_and_write(tmp_path, base_sha="HEAD~1", head_sha="HEAD")
    assert result["diff_status"] == "NO_GIT"


# --------------------------------------------------------------------------
# CLI entry point, run for real as a subprocess
# --------------------------------------------------------------------------

def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.spec_vplan_delta", *args],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True,
    )


def test_cli_reports_delta_found_and_exits_1(tmp_path):
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(json.dumps({"requirements": [_contract_record("REQ-1")]}), encoding="utf-8")
    after_path.write_text(json.dumps({"requirements": [
        _contract_record("REQ-1", checker="different_checker")]}), encoding="utf-8")

    proc = _run_cli("--before", str(before_path), "--after", str(after_path), "--json")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "DELTA_FOUND"
    assert payload["status_counts"]["MODIFIED"] == 1


def test_cli_reports_no_delta_and_exits_0(tmp_path):
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    rec = _contract_record("REQ-1")
    before_path.write_text(json.dumps({"requirements": [rec]}), encoding="utf-8")
    after_path.write_text(json.dumps({"requirements": [dict(rec)]}), encoding="utf-8")

    proc = _run_cli("--before", str(before_path), "--after", str(after_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "NO_DELTA" in proc.stdout


def test_cli_not_available_on_unreadable_file_exits_2(tmp_path):
    proc = _run_cli("--before", str(tmp_path / "does_not_exist.json"),
                    "--after", str(tmp_path / "also_missing.json"))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "NOT_AVAILABLE" in proc.stdout


def test_cli_root_flag_grounds_vplan_linkage(tmp_path):
    dv = tmp_path / ".dv-harness"
    dv.mkdir()
    (dv / "requirements.csv").write_text(
        "REQ_ID,SOURCE,SCOPE,VPLAN_ID,SCENARIO_ID,COMMAND_ID,PATTERN_ID,"
        "CHECKER_ID,COVERAGE_ID,RESULT,STATUS,EVIDENCE\n"
        "REQ-1,spec,usb3,VP-9,,,,,,,,\n",
        encoding="utf-8",
    )
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(json.dumps({"requirements": [_contract_record("REQ-1")]}), encoding="utf-8")
    after_path.write_text(json.dumps({"requirements": [
        _contract_record("REQ-1", checker="c2")]}), encoding="utf-8")

    proc = _run_cli("--before", str(before_path), "--after", str(after_path),
                    "--root", str(tmp_path), "--json")
    payload = json.loads(proc.stdout)
    assert payload["items"][0]["vplan_linkage"]["rows"][0]["vplan_id"] == "VP-9"
