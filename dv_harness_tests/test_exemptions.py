"""Tests for dv_harness/exemptions.py (structured exemptions.yaml system)
and its `dv-harness exemptions {list,add,check,expire-report}` CLI surface.

Covers: schema validation (required fields, valid_until required with no
"no expiry" escape hatch), expiry detection (both a not-yet-expired and a
genuinely-expired case), the CLI subcommands (real subprocess dispatch,
mirroring test_cli_blackboard.py's established style), and the real content
shape of the review-queue JSON file build_review_queue()/write_review_queue()
produce.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import jsonschema
import pytest
import yaml

from dv_harness import exemptions

ROOT = Path(__file__).resolve().parents[1]


def _fresh_project() -> Path:
    return Path(tempfile.mkdtemp())


def _run_cli(tmp, *args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
    )


def _valid_entry(**overrides):
    entry = {
        "id": "EXEMPT-0001",
        "check_id": "coverage_unreachability_analysis_partcomp",
        "reason": "UNR needs a separate VCS license and does not support -partcomp.",
        "basis_document": "dv_harness/uvm_generator/templates/sim_scripts/Makefile:1501-1508",
        "owner": "dv-infra-team",
        "valid_until": "2099-01-01",
    }
    entry.update(overrides)
    return entry


# ---- schema validation ------------------------------------------------

def test_schema_file_is_valid_json_and_draft_2020_12():
    schema = json.loads(exemptions.SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["title"] == "exemptions"


def test_valid_document_passes_validation():
    doc = {"schema_version": "1.0", "exemptions": [_valid_entry()]}
    exemptions.validate_exemptions_document(doc)  # must not raise


@pytest.mark.parametrize("missing_field", exemptions.REQUIRED_FIELDS)
def test_entry_missing_a_required_field_fails_validation(missing_field):
    entry = _valid_entry()
    del entry[missing_field]
    doc = {"schema_version": "1.0", "exemptions": [entry]}
    with pytest.raises(exemptions.ExemptionValidationError):
        exemptions.validate_exemptions_document(doc)


def test_valid_until_is_the_field_the_schema_makes_impossible_to_omit():
    """The user's own spec: 有效期是關鍵欄位 -- no permanent/no-expiry
    exemptions allowed. An entry with every other field present but no
    valid_until must still fail validation."""
    entry = _valid_entry()
    del entry["valid_until"]
    assert set(entry) == {"id", "check_id", "reason", "basis_document", "owner"}
    doc = {"schema_version": "1.0", "exemptions": [entry]}
    with pytest.raises(exemptions.ExemptionValidationError, match="valid_until"):
        exemptions.validate_exemptions_document(doc)


def test_valid_until_must_match_iso_date_pattern():
    doc = {"schema_version": "1.0", "exemptions": [_valid_entry(valid_until="not-a-date")]}
    with pytest.raises(exemptions.ExemptionValidationError):
        exemptions.validate_exemptions_document(doc)


def test_unknown_field_rejected_additional_properties_false():
    doc = {"schema_version": "1.0", "exemptions": [_valid_entry(made_up_field="x")]}
    with pytest.raises(exemptions.ExemptionValidationError):
        exemptions.validate_exemptions_document(doc)


def test_basis_document_must_not_be_empty():
    doc = {"schema_version": "1.0", "exemptions": [_valid_entry(basis_document="")]}
    with pytest.raises(exemptions.ExemptionValidationError):
        exemptions.validate_exemptions_document(doc)


# ---- load / save / add --------------------------------------------------

def test_load_missing_file_returns_empty_valid_document():
    tmp = _fresh_project()
    path = exemptions.default_exemptions_path(tmp)
    assert not path.exists()
    doc = exemptions.load_exemptions_document(path)
    assert doc == {"schema_version": "1.0", "exemptions": []}


def test_add_exemption_creates_file_and_round_trips_as_real_yaml():
    tmp = _fresh_project()
    path = exemptions.default_exemptions_path(tmp)
    saved = exemptions.add_exemption(path, _valid_entry(id=None))
    assert saved["id"] == "EXEMPT-0001"
    assert saved["created_at"] == date.today().isoformat()
    assert saved["status"] == "active"

    assert path.is_file()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "1.0"
    assert raw["exemptions"][0]["check_id"] == "coverage_unreachability_analysis_partcomp"

    # A second, independent load must see the same real on-disk content.
    reread = exemptions.list_exemptions(path)
    assert len(reread) == 1
    assert reread[0]["owner"] == "dv-infra-team"


def test_add_exemption_auto_increments_id_and_rejects_duplicate():
    tmp = _fresh_project()
    path = exemptions.default_exemptions_path(tmp)
    first = exemptions.add_exemption(path, _valid_entry(id=None))
    second = exemptions.add_exemption(path, _valid_entry(id=None, check_id="another_check"))
    assert first["id"] == "EXEMPT-0001"
    assert second["id"] == "EXEMPT-0002"

    with pytest.raises(exemptions.ExemptionValidationError, match="already exists"):
        exemptions.add_exemption(path, _valid_entry(id="EXEMPT-0001", check_id="dup"))


def test_add_exemption_without_valid_until_refuses_write():
    tmp = _fresh_project()
    path = exemptions.default_exemptions_path(tmp)
    entry = _valid_entry(id=None)
    del entry["valid_until"]
    with pytest.raises(exemptions.ExemptionValidationError):
        exemptions.add_exemption(path, entry)
    assert not path.exists()  # refused write must not leave a partial file


# ---- independent-review repro: calendar-invalid valid_until ("2026-02-30") ---
# Before the fix, this string satisfies the schema's ^\d{4}-\d{2}-\d{2}$
# pattern (it looks like a date) but February never has 30 days, so it is
# not a real calendar day. A bare Draft202012Validator(schema) with no
# format_checker attached treats the schema's declared "format": "date" as
# an annotation only and never actually checks it -- so this value used to
# pass validate_exemptions_document(), get written to disk by
# add_exemption(), and then crash is_expired()/build_review_queue() (and
# therefore `dv-harness exemptions check`) with an unhandled ValueError
# from date.fromisoformat(). Fixed by attaching jsonschema.FormatChecker()
# to the validator (rejects it up front) AND by defensively guarding
# is_expired()/build_review_queue()'s own date.fromisoformat() calls via
# the new _parse_valid_until() helper (in case a bad value ever reaches
# them some other way, e.g. a hand-edited file or a direct call with a raw
# entry dict that never went through schema validation).

def test_add_exemption_rejects_calendar_invalid_valid_until():
    tmp = _fresh_project()
    path = exemptions.default_exemptions_path(tmp)
    entry = _valid_entry(id=None, valid_until="2026-02-30")
    with pytest.raises(exemptions.ExemptionValidationError, match="2026-02-30"):
        exemptions.add_exemption(path, entry)
    assert not path.exists()  # refused write must not leave a bad file on disk


def test_validate_exemptions_document_rejects_calendar_invalid_date_via_format_checker():
    """Directly exercises the fix: the schema's pattern alone would accept
    '2026-02-30' (it matches \\d{4}-\\d{2}-\\d{2}); only an attached
    format_checker catches that February has no 30th day."""
    doc = {"schema_version": "1.0", "exemptions": [_valid_entry(valid_until="2026-02-30")]}
    with pytest.raises(exemptions.ExemptionValidationError, match="2026-02-30"):
        exemptions.validate_exemptions_document(doc)


def test_is_expired_raises_clean_error_for_calendar_invalid_valid_until_bypassing_schema():
    """Defense in depth: is_expired() (and therefore find_expired()/
    find_active()/check_expiry(), and build_review_queue() via the same
    _parse_valid_until() helper) must raise a clean, catchable
    ExemptionValidationError -- never an unhandled ValueError -- for a
    calendar-invalid valid_until reaching it directly as a raw entry dict,
    independent of whether that entry was ever schema-validated on load."""
    bad_entry = _valid_entry(valid_until="2026-02-30")
    with pytest.raises(exemptions.ExemptionValidationError, match="2026-02-30"):
        exemptions.is_expired(bad_entry, date(2026, 9, 3))
    with pytest.raises(exemptions.ExemptionValidationError, match="2026-02-30"):
        exemptions.find_expired([bad_entry], date(2026, 9, 3))
    with pytest.raises(exemptions.ExemptionValidationError, match="2026-02-30"):
        exemptions._parse_valid_until(bad_entry)


def test_cli_exemptions_check_on_hand_written_bad_file_fails_cleanly_not_a_traceback():
    """End-to-end reviewer repro via the CLI: a hand-written exemptions.yaml
    on disk (never went through add_exemption(), so today's upfront
    format_checker rejection never had a chance to apply) with a
    calendar-invalid valid_until must make `dv-harness exemptions check`
    fail with a clean one-line message on a nonzero exit, not dump a raw
    Python traceback to the user."""
    tmp = _fresh_project()
    path = exemptions.default_exemptions_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    bad_doc = {"schema_version": "1.0", "exemptions": [_valid_entry(valid_until="2026-02-30")]}
    path.write_text(yaml.safe_dump(bad_doc, sort_keys=False), encoding="utf-8")

    r = _run_cli(tmp, "exemptions", "check", "--as-of", "2026-09-03")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Traceback" not in r.stderr
    assert "2026-02-30" in r.stderr
    assert "exemptions check FAILED" in r.stderr


# ---- expiry detection: real not-yet-expired vs. genuinely-expired -------

def test_find_expired_leaves_a_future_valid_until_entry_active():
    as_of = date(2026, 9, 3)
    future = _valid_entry(id="EXEMPT-0001", valid_until="2026-12-31")
    assert exemptions.is_expired(future, as_of) is False
    assert exemptions.find_expired([future], as_of) == []
    assert exemptions.find_active([future], as_of) == [future]


def test_find_expired_flags_a_past_valid_until_entry():
    as_of = date(2026, 9, 3)
    past = _valid_entry(id="EXEMPT-0002", valid_until="2026-01-01")
    assert exemptions.is_expired(past, as_of) is True
    assert exemptions.find_expired([past], as_of) == [past]
    assert exemptions.find_active([past], as_of) == []


def test_valid_until_equal_to_as_of_is_still_active_last_valid_day():
    as_of = date(2026, 9, 3)
    entry = _valid_entry(id="EXEMPT-0003", valid_until="2026-09-03")
    assert exemptions.is_expired(entry, as_of) is False


def test_retired_entry_is_never_reported_expired_regardless_of_date():
    as_of = date(2099, 1, 1)
    entry = _valid_entry(id="EXEMPT-0004", valid_until="2020-01-01", status="retired")
    assert exemptions.is_expired(entry, as_of) is False


def test_check_expiry_reports_mixed_active_and_expired_counts():
    tmp = _fresh_project()
    path = exemptions.default_exemptions_path(tmp)
    exemptions.add_exemption(path, _valid_entry(id="EXEMPT-0001", check_id="still_good",
                                                 valid_until="2099-01-01"))
    exemptions.add_exemption(path, _valid_entry(id="EXEMPT-0002", check_id="lapsed",
                                                 valid_until="2020-01-01"))

    result = exemptions.check_expiry(path, as_of=date(2026, 9, 3))
    assert result["total"] == 2
    assert result["active_count"] == 1
    assert result["expired_count"] == 1
    assert [e["id"] for e in result["expired"]] == ["EXEMPT-0002"]
    assert [e["id"] for e in result["active"]] == ["EXEMPT-0001"]


# ---- review queue: real content shape -----------------------------------

def test_build_review_queue_shape_and_content_for_expired_entries_only():
    tmp = _fresh_project()
    path = exemptions.default_exemptions_path(tmp)
    exemptions.add_exemption(path, _valid_entry(id="EXEMPT-0001", check_id="still_good",
                                                 valid_until="2099-01-01"))
    exemptions.add_exemption(path, _valid_entry(id="EXEMPT-0002", check_id="lapsed_check",
                                                 reason="temporary IP-tooling workaround",
                                                 basis_document="TICKET-4242",
                                                 owner="alice", valid_until="2026-01-01"))

    as_of = date(2026, 9, 3)
    queue = exemptions.build_review_queue(path, as_of=as_of)
    assert len(queue) == 1
    record = queue[0]
    assert record["exemption_id"] == "EXEMPT-0002"
    assert record["check_id"] == "lapsed_check"
    assert record["reason"] == "temporary IP-tooling workaround"
    assert record["owner"] == "alice"
    assert record["basis_document"] == "TICKET-4242"
    assert record["valid_until"] == "2026-01-01"
    assert record["expired_since"] == "2026-01-01"
    assert record["days_expired"] == (as_of - date(2026, 1, 1)).days
    assert record["as_of"] == "2026-09-03"


def test_write_review_queue_writes_real_json_file_even_when_empty():
    tmp = _fresh_project()
    out_path = exemptions.default_review_queue_path(tmp)
    written = exemptions.write_review_queue([], out_path)
    assert written == out_path
    assert out_path.is_file()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["entries"] == []
    assert "generated_at" in payload


def test_write_review_queue_persists_the_real_queue_content():
    tmp = _fresh_project()
    path = exemptions.default_exemptions_path(tmp)
    exemptions.add_exemption(path, _valid_entry(id="EXEMPT-0001", valid_until="2020-01-01"))
    queue = exemptions.build_review_queue(path, as_of=date(2026, 9, 3))
    out_path = exemptions.default_review_queue_path(tmp)
    exemptions.write_review_queue(queue, out_path)

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["exemption_id"] == "EXEMPT-0001"


# ---- CLI subcommands (real subprocess dispatch) --------------------------

def test_cli_exemptions_add_then_list():
    tmp = _fresh_project()
    r = _run_cli(tmp, "exemptions", "add",
                 "--check-id", "coverage_unreachability_analysis_partcomp",
                 "--reason", "UNR needs a separate VCS license and does not support -partcomp.",
                 "--basis-document", "dv_harness/uvm_generator/templates/sim_scripts/Makefile:1501-1508",
                 "--owner", "dv-infra-team",
                 "--valid-until", "2099-01-01")
    assert r.returncode == 0, r.stderr
    added = json.loads(r.stdout)
    assert added["id"] == "EXEMPT-0001"
    assert added["check_id"] == "coverage_unreachability_analysis_partcomp"

    r2 = _run_cli(tmp, "exemptions", "list")
    assert r2.returncode == 0, r2.stderr
    listed = json.loads(r2.stdout)
    assert len(listed) == 1
    assert listed[0]["id"] == "EXEMPT-0001"

    on_disk = exemptions.default_exemptions_path(tmp)
    assert on_disk.is_file()


def test_cli_exemptions_add_missing_required_flag_fails():
    tmp = _fresh_project()
    r = _run_cli(tmp, "exemptions", "add",
                 "--check-id", "some_check", "--reason", "x",
                 "--basis-document", "y", "--owner", "z")  # no --valid-until
    assert r.returncode != 0


def test_cli_exemptions_check_exits_zero_when_nothing_expired():
    tmp = _fresh_project()
    r = _run_cli(tmp, "exemptions", "add",
                 "--check-id", "future_check", "--reason", "r", "--basis-document", "b",
                 "--owner", "o", "--valid-until", "2099-01-01")
    assert r.returncode == 0, r.stderr

    r2 = _run_cli(tmp, "exemptions", "check")
    assert r2.returncode == 0, r2.stderr
    result = json.loads(r2.stdout)
    assert result["expired_count"] == 0
    assert result["active_count"] == 1


def test_cli_exemptions_check_exits_nonzero_when_something_expired():
    tmp = _fresh_project()
    r = _run_cli(tmp, "exemptions", "add",
                 "--check-id", "lapsed_check", "--reason", "r", "--basis-document", "b",
                 "--owner", "o", "--valid-until", "2020-01-01")
    assert r.returncode == 0, r.stderr

    r2 = _run_cli(tmp, "exemptions", "check", "--as-of", "2026-09-03")
    assert r2.returncode == 1, r2.stdout + r2.stderr
    result = json.loads(r2.stdout)
    assert result["expired_count"] == 1
    assert result["expired"][0]["check_id"] == "lapsed_check"


def test_cli_exemptions_expire_report_writes_review_queue_and_exits_nonzero():
    tmp = _fresh_project()
    r = _run_cli(tmp, "exemptions", "add",
                 "--check-id", "lapsed_check", "--reason", "temporary IP-tooling workaround",
                 "--basis-document", "TICKET-4242", "--owner", "alice", "--valid-until", "2020-01-01")
    assert r.returncode == 0, r.stderr

    r2 = _run_cli(tmp, "exemptions", "expire-report", "--as-of", "2026-09-03")
    assert r2.returncode == 1, r2.stdout + r2.stderr
    payload = json.loads(r2.stdout)
    assert payload["expired_count"] == 1

    queue_path = exemptions.default_review_queue_path(tmp)
    assert queue_path.is_file()
    on_disk = json.loads(queue_path.read_text(encoding="utf-8"))
    assert len(on_disk["entries"]) == 1
    assert on_disk["entries"][0]["check_id"] == "lapsed_check"
    assert on_disk["entries"][0]["owner"] == "alice"


def test_cli_exemptions_expire_report_exits_zero_when_nothing_expired():
    tmp = _fresh_project()
    r = _run_cli(tmp, "exemptions", "add",
                 "--check-id", "future_check", "--reason", "r", "--basis-document", "b",
                 "--owner", "o", "--valid-until", "2099-01-01")
    assert r.returncode == 0, r.stderr

    r2 = _run_cli(tmp, "exemptions", "expire-report")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    payload = json.loads(r2.stdout)
    assert payload["expired_count"] == 0

    queue_path = exemptions.default_review_queue_path(tmp)
    assert queue_path.is_file()  # written even when empty, per write_review_queue()'s own contract
    assert json.loads(queue_path.read_text(encoding="utf-8"))["entries"] == []
