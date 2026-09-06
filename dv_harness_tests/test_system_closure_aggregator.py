"""Tests for dv_harness/system_closure_aggregator.py."""

import json
import subprocess
import sys

import pytest

from dv_harness.system_closure_aggregator import (
    CLOSURE_CLOSED,
    CLOSURE_INCOMPLETE_EVIDENCE,
    CLOSURE_NOT_CLOSED,
    CLOSURE_DIMENSIONS,
    DIMENSION_AMBIGUOUS_CONFLICTING_SUBMISSIONS,
    DIMENSION_MET,
    DIMENSION_NOT_APPLICABLE,
    DIMENSION_NOT_AVAILABLE,
    DIMENSION_NOT_SUPPLIED,
    DIMENSION_UNKNOWN,
    DIMENSION_UNMET,
    aggregate_system_closure,
    normalize_dimension_status,
    render_system_closure_markdown,
)


def _all_met_records():
    return [{"dimension_name": name, "status": "MET"} for name in CLOSURE_DIMENSIONS]


# --- core positive path -------------------------------------------------------


def test_all_twelve_met_or_not_applicable_is_closed():
    records = _all_met_records()
    # swap one to NOT_APPLICABLE -- must still clear
    records[3] = {"dimension_name": CLOSURE_DIMENSIONS[3], "status": "NOT_APPLICABLE"}
    report = aggregate_system_closure(records)
    assert report["overall_status"] == CLOSURE_CLOSED
    assert len(report["dimensions"]) == 12
    assert report["blocking_dimensions"] == []
    assert report["incomplete_dimensions"] == []


def test_every_dimension_individually_reported_never_collapsed():
    report = aggregate_system_closure(_all_met_records())
    names = [d["dimension_name"] for d in report["dimensions"]]
    assert names == list(CLOSURE_DIMENSIONS)
    for d in report["dimensions"]:
        assert d["normalized_status"] == DIMENSION_MET
        assert d["supplied"] is True


def test_dimensions_render_in_fixed_order_regardless_of_input_order():
    records = list(reversed(_all_met_records()))
    report = aggregate_system_closure(records)
    assert [d["dimension_name"] for d in report["dimensions"]] == list(CLOSURE_DIMENSIONS)


# --- worst-wins: a single UNMET blocks regardless of how many are clean -------


def test_single_unmet_dimension_blocks_overall_closure_even_with_eleven_clean():
    records = _all_met_records()
    records[7] = {"dimension_name": CLOSURE_DIMENSIONS[7], "status": "FAIL"}
    report = aggregate_system_closure(records)
    assert report["overall_status"] == CLOSURE_NOT_CLOSED
    assert report["blocking_dimensions"] == [CLOSURE_DIMENSIONS[7]]
    assert CLOSURE_DIMENSIONS[7] in report["reason"]


def test_unmet_outranks_simultaneous_unknown_dimensions():
    records = _all_met_records()
    records[0] = {"dimension_name": CLOSURE_DIMENSIONS[0], "status": "UNKNOWN"}
    records[1] = {"dimension_name": CLOSURE_DIMENSIONS[1], "status": "BLOCKED"}
    report = aggregate_system_closure(records)
    # BLOCKED (UNMET-equivalent) wins over the simultaneous UNKNOWN dimension.
    assert report["overall_status"] == CLOSURE_NOT_CLOSED
    assert report["blocking_dimensions"] == [CLOSURE_DIMENSIONS[1]]


def test_multiple_unmet_dimensions_all_named():
    records = _all_met_records()
    records[2] = {"dimension_name": CLOSURE_DIMENSIONS[2], "status": "OPEN"}
    records[9] = {"dimension_name": CLOSURE_DIMENSIONS[9], "status": "VIOLATED"}
    report = aggregate_system_closure(records)
    assert report["overall_status"] == CLOSURE_NOT_CLOSED
    assert set(report["blocking_dimensions"]) == {CLOSURE_DIMENSIONS[2], CLOSURE_DIMENSIONS[9]}


# --- UNKNOWN/NOT_AVAILABLE/never-supplied -> INCOMPLETE_EVIDENCE -------------


def test_single_unknown_dimension_gives_incomplete_evidence_not_closed_or_not_closed():
    records = _all_met_records()
    records[4] = {"dimension_name": CLOSURE_DIMENSIONS[4], "status": "UNKNOWN"}
    report = aggregate_system_closure(records)
    assert report["overall_status"] == CLOSURE_INCOMPLETE_EVIDENCE
    assert report["overall_status"] != CLOSURE_CLOSED
    assert report["overall_status"] != CLOSURE_NOT_CLOSED
    assert report["incomplete_dimensions"] == [CLOSURE_DIMENSIONS[4]]


def test_not_available_dimension_gives_incomplete_evidence():
    records = _all_met_records()
    records[5] = {"dimension_name": CLOSURE_DIMENSIONS[5], "status": "NOT_AVAILABLE"}
    report = aggregate_system_closure(records)
    assert report["overall_status"] == CLOSURE_INCOMPLETE_EVIDENCE


def test_dimension_never_supplied_at_all_gives_incomplete_evidence_not_a_fabricated_met():
    records = [r for r in _all_met_records() if r["dimension_name"] != "security_closure"]
    report = aggregate_system_closure(records)
    assert report["overall_status"] == CLOSURE_INCOMPLETE_EVIDENCE
    sec = next(d for d in report["dimensions"] if d["dimension_name"] == "security_closure")
    assert sec["normalized_status"] == DIMENSION_NOT_SUPPLIED
    assert sec["supplied"] is False
    assert "security_closure" in report["incomplete_dimensions"]


def test_empty_dimension_list_reports_every_dimension_not_supplied():
    report = aggregate_system_closure([])
    assert report["overall_status"] == CLOSURE_INCOMPLETE_EVIDENCE
    assert len(report["dimensions"]) == 12
    assert all(d["normalized_status"] == DIMENSION_NOT_SUPPLIED for d in report["dimensions"])
    assert len(report["incomplete_dimensions"]) == 12


# --- conflicting duplicate submissions: never arbitrated ----------------------


def test_conflicting_duplicate_submissions_for_one_dimension_report_ambiguous_not_arbitrated():
    records = _all_met_records()
    records.append({"dimension_name": CLOSURE_DIMENSIONS[6], "status": "FAIL"})
    report = aggregate_system_closure(records)
    dim = next(d for d in report["dimensions"] if d["dimension_name"] == CLOSURE_DIMENSIONS[6])
    assert dim["normalized_status"] == DIMENSION_AMBIGUOUS_CONFLICTING_SUBMISSIONS
    # ambiguity is treated as incomplete evidence, never silently resolved either way.
    assert report["overall_status"] == CLOSURE_INCOMPLETE_EVIDENCE
    assert CLOSURE_DIMENSIONS[6] in report["incomplete_dimensions"]


def test_agreeing_duplicate_submissions_merge_cleanly():
    records = _all_met_records()
    records.append({"dimension_name": CLOSURE_DIMENSIONS[6], "status": "PASS"})
    report = aggregate_system_closure(records)
    dim = next(d for d in report["dimensions"] if d["dimension_name"] == CLOSURE_DIMENSIONS[6])
    assert dim["normalized_status"] == DIMENSION_MET
    assert report["overall_status"] == CLOSURE_CLOSED


# --- unrecognized dimension names: reported, never silently dropped ----------


def test_unrecognized_dimension_name_is_reported_not_silently_dropped():
    records = _all_met_records()
    records.append({"dimension_name": "not_a_real_dimension", "status": "MET"})
    report = aggregate_system_closure(records)
    assert report["overall_status"] == CLOSURE_CLOSED
    assert len(report["unrecognized_records"]) == 1
    assert report["unrecognized_records"][0]["dimension_name"] == "not_a_real_dimension"


def test_record_missing_dimension_name_entirely_is_reported_as_unrecognized():
    records = _all_met_records()
    records.append({"status": "MET"})
    report = aggregate_system_closure(records)
    assert len(report["unrecognized_records"]) == 1
    assert report["unrecognized_records"][0]["reason"] == "MISSING_DIMENSION_NAME"


# --- normalize_dimension_status: real sibling-module vocabulary --------------


@pytest.mark.parametrize("raw,expected", [
    ("PASS", DIMENSION_MET), ("PASSED", DIMENSION_MET), ("CLOSED", DIMENSION_MET),
    ("READY", DIMENSION_MET), ("QUALIFIED", DIMENSION_MET), ("VALID", DIMENSION_MET),
    ("FAIL", DIMENSION_UNMET), ("BLOCKED", DIMENSION_UNMET), ("OPEN", DIMENSION_UNMET),
    ("VIOLATED", DIMENSION_UNMET), ("EXPIRED", DIMENSION_UNMET), ("REVOKED", DIMENSION_UNMET),
    ("UNKNOWN", DIMENSION_UNKNOWN), ("PENDING", DIMENSION_UNKNOWN),
    ("INCOMPLETE_EVIDENCE", DIMENSION_UNKNOWN),
    ("NOT_AVAILABLE", DIMENSION_NOT_AVAILABLE),
    ("NOT_APPLICABLE", DIMENSION_NOT_APPLICABLE), ("N/A", DIMENSION_NOT_APPLICABLE),
    ("some_totally_unrecognized_token", DIMENSION_UNKNOWN),
    (None, DIMENSION_UNKNOWN),
    ("", DIMENSION_UNKNOWN),
])
def test_normalize_dimension_status_real_vocabulary(raw, expected):
    assert normalize_dimension_status(raw) == expected


def test_normalize_is_case_insensitive_and_whitespace_tolerant():
    assert normalize_dimension_status("  pass  ") == DIMENSION_MET
    assert normalize_dimension_status("Blocked") == DIMENSION_UNMET


# --- duck-typed input: attribute-bearing objects, not only dicts -------------


class _FakeDimensionRecord:
    def __init__(self, dimension_name, status):
        self.dimension_name = dimension_name
        self.status = status


def test_attribute_bearing_objects_accepted_not_only_dicts():
    records = [_FakeDimensionRecord(name, "MET") for name in CLOSURE_DIMENSIONS]
    report = aggregate_system_closure(records)
    assert report["overall_status"] == CLOSURE_CLOSED


# --- rendering -----------------------------------------------------------


def test_render_markdown_includes_overall_status_and_every_dimension():
    report = aggregate_system_closure(_all_met_records())
    text = render_system_closure_markdown(report)
    assert "SYSTEM_CLOSURE_STATUS: CLOSED" in text
    for name in CLOSURE_DIMENSIONS:
        assert name in text


# --- CLI ----------------------------------------------------------------


def _run_cli(tmp_path, records, extra_args=()):
    dims_file = tmp_path / "dims.json"
    dims_file.write_text(json.dumps(records), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_closure_aggregator",
         "--dimensions", str(dims_file), *extra_args],
        capture_output=True, text=True,
    )
    return proc


def test_cli_exit_0_on_closed(tmp_path):
    proc = _run_cli(tmp_path, _all_met_records())
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["overall_status"] == CLOSURE_CLOSED


def test_cli_exit_1_on_not_closed(tmp_path):
    records = _all_met_records()
    records[0] = {"dimension_name": CLOSURE_DIMENSIONS[0], "status": "FAIL"}
    proc = _run_cli(tmp_path, records)
    assert proc.returncode == 1, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["overall_status"] == CLOSURE_NOT_CLOSED


def test_cli_exit_2_on_incomplete_evidence(tmp_path):
    proc = _run_cli(tmp_path, [])
    assert proc.returncode == 2, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["overall_status"] == CLOSURE_INCOMPLETE_EVIDENCE


def test_cli_wrapped_dimensions_form(tmp_path):
    dims_file = tmp_path / "wrapped.json"
    dims_file.write_text(json.dumps({"dimensions": _all_met_records()}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_closure_aggregator",
         "--dimensions", str(dims_file)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_cli_markdown_output(tmp_path):
    proc = _run_cli(tmp_path, _all_met_records(), extra_args=("--markdown",))
    assert proc.returncode == 0, proc.stderr
    assert "SYSTEM_CLOSURE_STATUS: CLOSED" in proc.stdout


def test_cli_malformed_json_is_not_available(tmp_path):
    dims_file = tmp_path / "bad.json"
    dims_file.write_text("{not valid json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_closure_aggregator",
         "--dimensions", str(dims_file)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "NOT_AVAILABLE" in proc.stderr
