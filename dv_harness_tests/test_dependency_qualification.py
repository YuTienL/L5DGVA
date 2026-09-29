"""Real tests for dv_harness/dependency_qualification.py.

Every test drives the real store (a real JSON ledger file under a throwaway
project root), the real `derive_status()`/`record_qualification()`/
`revoke_qualification()` functions, and -- for the inventory-reuse tests -- a
real `dependency_supply_chain.build_inventory()`-shaped document. Nothing is
mocked. Negative controls prove the module refuses to fabricate a
qualification status when no real human decision is on file, and refuses to
record a qualification against a component the real inventory does not
contain.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import dependency_qualification as dq


def _clean_record(**overrides):
    record = {
        "qualification_id": "Q-USB-VIP-1",
        "component": "svt_usb", "ecosystem": "designware_vip",
        "version_qualified": "6.1", "vetted_by": "jane.reviewer",
        "vetted_at": "2026-09-01T00:00:00Z",
        "criteria": {
            dq.CRITERION_LICENSE_REVIEW: {"result": "MET", "evidence": "LICENSE.txt reviewed 2026-09-01"},
            dq.CRITERION_SECURITY_REVIEW: {"result": "MET", "evidence": "no known CVE, checked OSV 2026-09-01"},
        },
        "decision": "APPROVED",
        "evidence": "vetting_memo_2026_09_01.md",
    }
    record.update(overrides)
    return record


# --------------------------------------------------------------------------
# record_qualification()
# --------------------------------------------------------------------------

def test_record_qualification_positive_path(tmp_path):
    saved = dq.record_qualification(tmp_path, _clean_record())
    assert saved["qualification_id"] == "Q-USB-VIP-1"
    assert saved["schema_version"] == dq.SCHEMA_VERSION
    on_disk = dq.read_qualifications(tmp_path)
    assert len(on_disk) == 1
    assert on_disk[0]["component"] == "svt_usb"


def test_missing_required_field_refused(tmp_path):
    record = _clean_record()
    del record["vetted_by"]
    with pytest.raises(dq.DependencyQualificationError, match="missing required fields"):
        dq.record_qualification(tmp_path, record)


def test_stored_status_field_refused(tmp_path):
    record = _clean_record(status="VETTED")
    with pytest.raises(dq.DependencyQualificationError, match="derived"):
        dq.record_qualification(tmp_path, record)


def test_empty_criteria_refused(tmp_path):
    # An empty `criteria` dict is falsy, so it is caught by the same required-
    # field check as an absent one -- "against what criteria" cannot be
    # answered by an empty set either way.
    record = _clean_record(criteria={})
    with pytest.raises(dq.DependencyQualificationError, match="missing required fields.*criteria"):
        dq.record_qualification(tmp_path, record)


def test_unrecognized_criterion_key_refused(tmp_path):
    record = _clean_record(criteria={"MADE_UP_CRITERION": {"result": "MET", "evidence": "x"}})
    with pytest.raises(dq.DependencyQualificationError, match="not in the recognized vocabulary"):
        dq.record_qualification(tmp_path, record)


def test_pass_result_with_no_evidence_refused(tmp_path):
    record = _clean_record(criteria={dq.CRITERION_LICENSE_REVIEW: {"result": "MET"}})
    with pytest.raises(dq.DependencyQualificationError, match="no evidence citation"):
        dq.record_qualification(tmp_path, record)


def test_not_applicable_result_needs_no_evidence(tmp_path):
    record = _clean_record(criteria={
        dq.CRITERION_LICENSE_REVIEW: {"result": "MET", "evidence": "x"},
        dq.CRITERION_EXPORT_CONTROL_REVIEW: {"result": "NOT_APPLICABLE"},
    })
    dq.record_qualification(tmp_path, record)  # does not raise


def test_approved_with_failing_criterion_refused(tmp_path):
    record = _clean_record(criteria={
        dq.CRITERION_LICENSE_REVIEW: {"result": "UNMET", "evidence": "GPL-3.0, incompatible"},
    }, decision="APPROVED")
    with pytest.raises(dq.DependencyQualificationError, match="self-contradictory"):
        dq.record_qualification(tmp_path, record)


def test_rejected_with_failing_criterion_is_legal(tmp_path):
    record = _clean_record(criteria={
        dq.CRITERION_LICENSE_REVIEW: {"result": "UNMET", "evidence": "GPL-3.0, incompatible"},
    }, decision="REJECTED", qualification_id="Q-REJ-1")
    dq.record_qualification(tmp_path, record)  # does not raise


def test_conditional_requires_conditions_text(tmp_path):
    record = _clean_record(decision="CONDITIONAL", qualification_id="Q-COND-1")
    with pytest.raises(dq.DependencyQualificationError, match="non-empty `conditions`"):
        dq.record_qualification(tmp_path, record)


def test_conditional_with_conditions_text_is_legal(tmp_path):
    record = _clean_record(decision="CONDITIONAL", qualification_id="Q-COND-2",
                           conditions="Re-review before next major version bump")
    dq.record_qualification(tmp_path, record)  # does not raise


def test_unsupported_revalidation_trigger_key_refused(tmp_path):
    record = _clean_record(revalidation_trigger={"made_up_key": True})
    with pytest.raises(dq.DependencyQualificationError, match="not measured by this module"):
        dq.record_qualification(tmp_path, record)


def test_duplicate_qualification_id_refused(tmp_path):
    dq.record_qualification(tmp_path, _clean_record())
    with pytest.raises(dq.DependencyQualificationError, match="already recorded"):
        dq.record_qualification(tmp_path, _clean_record())


def test_vetting_target_not_in_inventory_refused(tmp_path):
    known = {("python", "requests"): {}}
    with pytest.raises(dq.DependencyQualificationError, match="VETTING_TARGET_NOT_IN_INVENTORY"):
        dq.record_qualification(tmp_path, _clean_record(), known_components=known)


def test_vetting_target_in_inventory_is_accepted(tmp_path):
    known = {("designware_vip", "svt_usb"): {}}
    dq.record_qualification(tmp_path, _clean_record(), known_components=known)  # does not raise


def test_known_components_from_inventory_reads_real_shape():
    inventory = {"components": [
        {"ecosystem": "python", "name": "jsonschema"},
        {"ecosystem": "designware_vip", "name": "svt_usb"},
    ]}
    known = dq.known_components_from_inventory(inventory)
    assert ("python", "jsonschema") in known
    assert ("designware_vip", "svt_usb") in known
    assert len(known) == 2


# --------------------------------------------------------------------------
# revoke_qualification()
# --------------------------------------------------------------------------

def test_revoke_requires_revoked_by_and_reason(tmp_path):
    dq.record_qualification(tmp_path, _clean_record())
    with pytest.raises(dq.DependencyQualificationError, match="revoked_by and a reason"):
        dq.revoke_qualification(tmp_path, "Q-USB-VIP-1", "", "")


def test_revoke_unknown_id_raises(tmp_path):
    with pytest.raises(dq.DependencyQualificationError, match="no qualification recorded"):
        dq.revoke_qualification(tmp_path, "Q-NOPE", "jane", "no longer used")


def test_revoke_marks_record_revoked(tmp_path):
    dq.record_qualification(tmp_path, _clean_record())
    revoked = dq.revoke_qualification(tmp_path, "Q-USB-VIP-1", "jane.reviewer", "component swapped out")
    assert revoked["revoked"] is True
    assert revoked["revoked_by"] == "jane.reviewer"
    status, reason = dq.derive_status(revoked)
    assert status == dq.STATUS_REVOKED
    assert "jane.reviewer" in reason


# --------------------------------------------------------------------------
# derive_status()
# --------------------------------------------------------------------------

def test_derive_status_vetted():
    status, reason = dq.derive_status(_clean_record())
    assert status == dq.STATUS_VETTED


def test_derive_status_conditionally_vetted():
    record = _clean_record(decision="CONDITIONAL", conditions="re-review annually")
    status, _ = dq.derive_status(record)
    assert status == dq.STATUS_CONDITIONALLY_VETTED


def test_derive_status_rejected():
    record = _clean_record(decision="REJECTED")
    status, reason = dq.derive_status(record)
    assert status == dq.STATUS_REJECTED
    assert reason == "DECISION_REJECTED"


def test_derive_status_revoked_outranks_everything():
    record = _clean_record(revoked=True, revoked_by="jane")
    status, _ = dq.derive_status(record)
    assert status == dq.STATUS_REVOKED


def test_derive_status_missing_fields_is_unknown():
    status, reason = dq.derive_status({"component": "svt_usb"})
    assert status == dq.STATUS_UNKNOWN
    assert "MISSING_REQUIRED_FIELDS" in reason


def test_derive_status_not_a_mapping_is_unknown():
    status, reason = dq.derive_status(["not", "a", "dict"])  # type: ignore[arg-type]
    assert status == dq.STATUS_UNKNOWN
    assert reason == "QUALIFICATION_RECORD_NOT_A_MAPPING"


def test_derive_status_unparseable_expires_at_is_unknown():
    record = _clean_record(expires_at="not-a-date")
    status, reason = dq.derive_status(record, now="2026-09-06T00:00:00Z")
    assert status == dq.STATUS_UNKNOWN
    assert "UNPARSEABLE_EXPIRES_AT" in reason


def test_derive_status_expired():
    record = _clean_record(expires_at="2026-01-01T00:00:00Z")
    status, reason = dq.derive_status(record, now="2026-09-06T00:00:00Z")
    assert status == dq.STATUS_EXPIRED
    assert "EXPIRED_AT" in reason


def test_derive_status_not_expired_before_expiry():
    record = _clean_record(expires_at="2027-01-01T00:00:00Z")
    status, _ = dq.derive_status(record, now="2026-09-06T00:00:00Z")
    assert status == dq.STATUS_VETTED


def test_derive_status_revalidation_required_on_version_mismatch():
    record = _clean_record(revalidation_trigger={"version": True})
    status, reason = dq.derive_status(record, current_version="7.0")
    assert status == dq.STATUS_REVALIDATION_REQUIRED
    assert "VERSION_CHANGED:6.1->7.0" in reason


def test_derive_status_revalidated_for_clears_the_trigger():
    record = _clean_record(revalidation_trigger={"version": True},
                           revalidated_for={"version": "7.0"})
    status, _ = dq.derive_status(record, current_version="7.0")
    assert status == dq.STATUS_VETTED


def test_derive_status_no_trigger_no_current_version_check_is_vetted():
    record = _clean_record()  # no revalidation_trigger declared
    status, _ = dq.derive_status(record, current_version="9.9.9")
    assert status == dq.STATUS_VETTED


# --------------------------------------------------------------------------
# evaluate_qualification_coverage() -- the real join against a real
# dependency_supply_chain-shaped inventory.
# --------------------------------------------------------------------------

def _inventory(*names_ecosystems):
    components = []
    for name, ecosystem, version in names_ecosystems:
        components.append({
            "ecosystem": ecosystem, "name": name, "specifier": f"=={version}",
            "installed": {"resolution": "SATISFIED", "installed_version": version},
        })
    return {"components": components}


def test_coverage_not_available_on_empty_inventory(tmp_path):
    report = dq.evaluate_qualification_coverage(tmp_path, {"components": []})
    assert report["status"] == dq.REPORT_NOT_AVAILABLE


def test_coverage_negative_control_no_qualification_record_is_not_qualified(tmp_path):
    """The headline negative control: a component the real inventory carries,
    with NO qualification ever recorded, must report NOT_QUALIFIED -- never a
    fabricated VETTED, and never silently dropped from the report."""
    inventory = _inventory(("svt_usb", "designware_vip", "6.1"))
    report = dq.evaluate_qualification_coverage(tmp_path, inventory)
    assert report["status"] == dq.REPORT_GAPS_FOUND
    assert report["gap_count"] == 1
    row = report["rows"][0]
    assert row["status"] == dq.COVERAGE_NOT_QUALIFIED
    assert row["qualification_id"] is None
    assert row["reason"] == "NO_QUALIFICATION_RECORD_ON_FILE"


def test_coverage_all_qualified_when_every_component_is_vetted(tmp_path):
    dq.record_qualification(tmp_path, _clean_record())
    inventory = _inventory(("svt_usb", "designware_vip", "6.1"))
    report = dq.evaluate_qualification_coverage(tmp_path, inventory)
    assert report["status"] == dq.REPORT_ALL_QUALIFIED
    assert report["gap_count"] == 0
    assert report["rows"][0]["status"] == dq.STATUS_VETTED


def test_coverage_worst_wins_a_single_gap_blocks_the_whole_report(tmp_path):
    dq.record_qualification(tmp_path, _clean_record())
    inventory = _inventory(
        ("svt_usb", "designware_vip", "6.1"),
        ("requests", "python", "2.31.0"),  # never qualified
    )
    report = dq.evaluate_qualification_coverage(tmp_path, inventory)
    assert report["status"] == dq.REPORT_GAPS_FOUND
    assert report["gap_count"] == 1
    assert report["component_count"] == 2
    statuses = {r["component"]: r["status"] for r in report["rows"]}
    assert statuses["svt_usb"] == dq.STATUS_VETTED
    assert statuses["requests"] == dq.COVERAGE_NOT_QUALIFIED


def test_coverage_reflects_real_version_mismatch_as_a_gap(tmp_path):
    record = _clean_record(revalidation_trigger={"version": True})
    dq.record_qualification(tmp_path, record)
    inventory = _inventory(("svt_usb", "designware_vip", "7.0"))  # pinned version moved
    report = dq.evaluate_qualification_coverage(tmp_path, inventory)
    assert report["status"] == dq.REPORT_GAPS_FOUND
    assert report["rows"][0]["status"] == dq.STATUS_REVALIDATION_REQUIRED


def test_coverage_latest_qualification_wins_when_multiple_exist(tmp_path):
    older = _clean_record(qualification_id="Q-OLD", decision="REJECTED",
                          vetted_at="2026-01-01T00:00:00Z",
                          criteria={dq.CRITERION_LICENSE_REVIEW: {"result": "UNMET", "evidence": "old issue"}})
    dq.record_qualification(tmp_path, older)
    newer = _clean_record(qualification_id="Q-NEW", vetted_at="2026-09-01T00:00:00Z")
    dq.record_qualification(tmp_path, newer)
    inventory = _inventory(("svt_usb", "designware_vip", "6.1"))
    report = dq.evaluate_qualification_coverage(tmp_path, inventory)
    row = report["rows"][0]
    assert row["qualification_id"] == "Q-NEW"
    assert row["status"] == dq.STATUS_VETTED


# --------------------------------------------------------------------------
# Vocabulary hygiene.
# --------------------------------------------------------------------------

def test_vocabularies_share_no_token_with_verification_verdicts_or_env_qualification_ladder():
    from dv_harness.models import Status
    from dv_harness import qualification as env_qualification
    verdicts = {s.value for s in Status}
    ladder = set(env_qualification.CANONICAL_LADDER)
    for vocabulary in (dq.DECISIONS, dq.CRITERION_RESULTS, dq.QUALIFICATION_STATUSES,
                       dq.REPORT_STATUSES):
        assert not verdicts.intersection(vocabulary)
        assert not ladder.intersection(vocabulary)
    dq.assert_no_vocabulary_collision()  # does not raise


def test_negative_control_vocabulary_guard_really_trips(monkeypatch):
    monkeypatch.setattr(dq, "REPORT_STATUSES", dq.REPORT_STATUSES + ("PASS",))
    with pytest.raises(dq.DependencyQualificationError, match="PASS"):
        dq.assert_no_vocabulary_collision()


def test_negative_control_ladder_collision_guard_really_trips(monkeypatch):
    monkeypatch.setattr(dq, "QUALIFICATION_STATUSES",
                        dq.QUALIFICATION_STATUSES + ("PRODUCTION_QUALIFIED",))
    with pytest.raises(dq.DependencyQualificationError, match="PRODUCTION_QUALIFIED"):
        dq.assert_no_vocabulary_collision()


# --------------------------------------------------------------------------
# Read-only guarantee: reading must never mint a store.
# --------------------------------------------------------------------------

def test_reading_a_bare_root_creates_no_store(tmp_path):
    dq.read_qualifications(tmp_path)
    dq.qualifications_for_component(tmp_path, "python", "requests")
    dq.evaluate_qualification_coverage(tmp_path, _inventory(("requests", "python", "1.0")))
    assert not (tmp_path / ".dv-harness").exists()


# --------------------------------------------------------------------------
# CLI front door.
# --------------------------------------------------------------------------

def _run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.dependency_qualification", *args],
        capture_output=True, text=True, cwd=cwd,
    )


def test_cli_statuses_exits_zero():
    result = _run_cli("statuses")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "VETTED" in payload["statuses"]


def test_cli_record_and_list_and_revoke_round_trip(tmp_path):
    record_file = tmp_path / "record.json"
    record_file.write_text(json.dumps(_clean_record()), encoding="utf-8")
    result = _run_cli("record", "--root", str(tmp_path), "--record-file", str(record_file))
    assert result.returncode == 0, result.stderr

    result = _run_cli("list", "--root", str(tmp_path))
    assert result.returncode == 0
    assert "Q-USB-VIP-1" in result.stdout

    result = _run_cli("revoke", "--root", str(tmp_path), "--qualification-id", "Q-USB-VIP-1",
                      "--revoked-by", "jane", "--reason", "swapped VIP vendor")
    assert result.returncode == 0, result.stderr
    assert '"revoked": true' in result.stdout


def test_cli_coverage_exit_codes(tmp_path):
    inventory_file = tmp_path / "inventory.json"
    inventory_file.write_text(json.dumps(_inventory(("svt_usb", "designware_vip", "6.1"))),
                              encoding="utf-8")
    # No qualification recorded yet -> gaps found -> exit 1.
    result = _run_cli("coverage", "--root", str(tmp_path), "--inventory", str(inventory_file))
    assert result.returncode == 1, result.stderr

    record_file = tmp_path / "record.json"
    record_file.write_text(json.dumps(_clean_record()), encoding="utf-8")
    _run_cli("record", "--root", str(tmp_path), "--record-file", str(record_file))

    result = _run_cli("coverage", "--root", str(tmp_path), "--inventory", str(inventory_file))
    assert result.returncode == 0, result.stderr


def test_cli_record_refuses_target_not_in_inventory(tmp_path):
    record_file = tmp_path / "record.json"
    record_file.write_text(json.dumps(_clean_record()), encoding="utf-8")
    inventory_file = tmp_path / "inventory.json"
    inventory_file.write_text(json.dumps(_inventory(("requests", "python", "2.31.0"))),
                              encoding="utf-8")
    result = _run_cli("record", "--root", str(tmp_path), "--record-file", str(record_file),
                      "--inventory", str(inventory_file))
    assert result.returncode == 2
    assert "VETTING_TARGET_NOT_IN_INVENTORY" in result.stdout


# --------------------------------------------------------------------------
# No human-approval machinery is referenced by this module.
# --------------------------------------------------------------------------

def test_no_human_approval_machinery_is_referenced_by_this_module():
    import io
    import tokenize
    source = Path(dq.__file__).read_text(encoding="utf-8")
    code = "".join(
        tok.string for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type not in (tokenize.COMMENT, tokenize.STRING))
    for forbidden in ("ControlPlane", "can_signoff", "assert_human_approval",
                      "HumanApprovalRequiredError", "ProductionWriteNotAuthorizedError"):
        assert forbidden not in code
