"""Tests for dv_harness/intake_baseline.py -- the INTAKE-domain freeze/
baseline (content-hash based, worst-wins, "we could not check" is never
VALID) mirroring signoff_export.py's SIGNOFF FREEZE / BASELINE pattern.

Every fact in these tests is a plain Python value the caller declares --
this module accepts all twelve intake facts as generic/duck-typed parameters
rather than discovering them from a real project, so there is no fixture
project tree here, only real facts dicts and a real throwaway freeze
directory under `tmp_path`. The one real dependency exercised throughout is
`source_identity.aggregate_source_id()`, imported through the identical
sys.path convention `harness_deploy.py`/`signoff_export.py` already use --
`test_multi_file_field_uses_the_real_aggregate_source_id` proves that
directly rather than trusting the import happened.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dv_harness import intake_baseline as ib  # noqa: E402


# --- fixtures --------------------------------------------------------------

def _complete_facts():
    """Every one of the twelve fields populated with a real, distinct
    value, exercising every captor shape at once."""
    return {
        "dut_top_boundary": {"top_module": "usb3_link_top",
                             "boundary": "phy_serdes_if"},
        "dut_sha": {"rtl/usb3_link_ctrl.v": "a" * 32,
                    "rtl/usb3_phy_wrap.v": "b" * 32},
        "tb_sha": "c" * 64,
        "source_file_hashes": {"src/env/usb3_env.sv": "content of usb3_env.sv"},
        "vip_declaration": {"vip_type": "usb3", "vip_release": "S-2024.06"},
        "bind_topology_hash": "d" * 40,
        "reference_uvm_hash": {"ref/usb3_ref_env.sv": "reference content"},
        "de_command_txt_hash": "command.txt raw content here",
        "known_test_list": ["usb3_smoke_test", "usb3_lfps_test"],
        "unresolved_critical_unknowns_count": 2,
        "unresolved_conflicts_count": 0,
        "recorded_user_decisions_count": 5,
    }


# --- capture: positive path --------------------------------------------

def test_complete_facts_capture_every_field():
    baseline = ib.capture_intake_baseline(_complete_facts())
    assert baseline["captured_field_count"] == len(ib.INTAKE_FIELDS)
    assert baseline["not_available_field_count"] == 0
    for name in ib.INTAKE_FIELDS:
        f = baseline["fields"][name]
        assert f["status"] == ib.CAPTURED, f"{name}: {f}"
        assert f["digest"], f"{name} captured with no digest"


def test_none_facts_reports_all_twelve_not_available():
    baseline = ib.capture_intake_baseline(None)
    assert baseline["captured_field_count"] == 0
    assert baseline["not_available_field_count"] == len(ib.INTAKE_FIELDS)
    for name in ib.INTAKE_FIELDS:
        f = baseline["fields"][name]
        assert f["status"] == ib.NOT_AVAILABLE
        assert f["reason"]
        assert f["digest"] is None


def test_facts_must_be_a_dict():
    with pytest.raises(TypeError):
        ib.capture_intake_baseline(["not", "a", "dict"])


# --- capture: declared-fact captor negative controls -----------------------

def test_declared_fact_empty_string_is_not_available():
    f = ib.capture_intake_baseline({"dut_top_boundary": "   "})["fields"]["dut_top_boundary"]
    assert f["status"] == ib.NOT_AVAILABLE
    assert f["reason"] == "EMPTY_FACT_SUPPLIED"


def test_declared_fact_empty_dict_is_not_available():
    f = ib.capture_intake_baseline({"vip_declaration": {}})["fields"]["vip_declaration"]
    assert f["status"] == ib.NOT_AVAILABLE
    assert f["reason"] == "EMPTY_FACT_SUPPLIED"


def test_declared_fact_is_order_independent_over_dict_keys():
    a = ib.capture_intake_baseline(
        {"vip_declaration": {"vip_type": "usb3", "vip_release": "S-2024.06"}})
    b = ib.capture_intake_baseline(
        {"vip_declaration": {"vip_release": "S-2024.06", "vip_type": "usb3"}})
    assert a["fields"]["vip_declaration"]["digest"] == b["fields"]["vip_declaration"]["digest"]


def test_declared_fact_different_content_gives_different_digest():
    a = ib.capture_intake_baseline({"dut_top_boundary": {"top_module": "top_a"}})
    b = ib.capture_intake_baseline({"dut_top_boundary": {"top_module": "top_b"}})
    da = a["fields"]["dut_top_boundary"]["digest"]
    db = b["fields"]["dut_top_boundary"]["digest"]
    assert da != db


# --- capture: hash-or-files captor ---------------------------------------

def test_hash_or_files_accepts_precomputed_hex_digest_as_is():
    f = ib.capture_intake_baseline({"tb_sha": "f" * 64})["fields"]["tb_sha"]
    assert f["status"] == ib.CAPTURED
    assert f["reason"] == "ALREADY_COMPUTED_HASH_ACCEPTED"
    assert f["digest"] == "f" * 64


def test_hash_or_files_hashes_a_raw_content_string():
    f = ib.capture_intake_baseline(
        {"de_command_txt_hash": "task main(); ... endtask"})["fields"]["de_command_txt_hash"]
    assert f["status"] == ib.CAPTURED
    assert f["reason"] == "SINGLE_VALUE_CONTENT_HASHED"
    assert f["digest"] == hashlib.sha256(b"task main(); ... endtask").hexdigest()


def test_hash_or_files_empty_mapping_is_not_available():
    f = ib.capture_intake_baseline({"source_file_hashes": {}})["fields"]["source_file_hashes"]
    assert f["status"] == ib.NOT_AVAILABLE
    assert f["reason"] == "EMPTY_FILE_MAP_SUPPLIED"


def test_hash_or_files_unsupported_shape_is_not_available():
    f = ib.capture_intake_baseline({"dut_sha": 12345})["fields"]["dut_sha"]
    assert f["status"] == ib.NOT_AVAILABLE
    assert f["reason"] == "UNSUPPORTED_FACT_SHAPE"
    assert f["detail"]["python_type"] == "int"


def test_hash_or_files_mapping_is_order_independent():
    a = ib.capture_intake_baseline(
        {"dut_sha": {"a.v": "1" * 32, "b.v": "2" * 32}})
    b = ib.capture_intake_baseline(
        {"dut_sha": {"b.v": "2" * 32, "a.v": "1" * 32}})
    assert a["fields"]["dut_sha"]["digest"] == b["fields"]["dut_sha"]["digest"]


def test_hash_or_files_mapping_changes_digest_when_one_file_hash_changes():
    a = ib.capture_intake_baseline({"dut_sha": {"a.v": "1" * 32}})
    b = ib.capture_intake_baseline({"dut_sha": {"a.v": "9" * 32}})
    assert a["fields"]["dut_sha"]["digest"] != b["fields"]["dut_sha"]["digest"]


def test_multi_file_field_uses_the_real_aggregate_source_id():
    """Proves reuse rather than a second hashing scheme: the module's own
    digest for a {path: hash} mapping must equal calling
    source_identity.aggregate_source_id() directly over the SAME normalized
    mapping -- independently imported here, not through the module under
    test."""
    sys.path.insert(0, str(ROOT / "tools" / "remote"))
    from source_identity import aggregate_source_id  # noqa: E402
    mapping = {"src/a.sv": "1" * 32, "src/b.sv": "2" * 32}
    expected = aggregate_source_id(mapping)
    got = ib.capture_intake_baseline({"dut_sha": mapping})["fields"]["dut_sha"]["digest"]
    assert got == expected


# --- capture: list captor ------------------------------------------------

def test_known_test_list_captured_and_order_independent():
    a = ib.capture_intake_baseline(
        {"known_test_list": ["test_a", "test_b"]})["fields"]["known_test_list"]
    b = ib.capture_intake_baseline(
        {"known_test_list": ["test_b", "test_a"]})["fields"]["known_test_list"]
    assert a["status"] == ib.CAPTURED
    assert a["digest"] == b["digest"]
    assert a["detail"]["count"] == 2


def test_known_test_list_empty_list_is_not_available():
    f = ib.capture_intake_baseline({"known_test_list": []})["fields"]["known_test_list"]
    assert f["status"] == ib.NOT_AVAILABLE
    assert f["reason"] == "EMPTY_FACT_SUPPLIED"


def test_known_test_list_wrong_shape_is_not_available():
    f = ib.capture_intake_baseline({"known_test_list": "test_a,test_b"})["fields"]["known_test_list"]
    assert f["status"] == ib.NOT_AVAILABLE
    assert f["reason"] == "UNSUPPORTED_FACT_SHAPE"


def test_known_test_list_adding_a_test_changes_digest():
    a = ib.capture_intake_baseline({"known_test_list": ["test_a"]})
    b = ib.capture_intake_baseline({"known_test_list": ["test_a", "test_b"]})
    assert a["fields"]["known_test_list"]["digest"] != b["fields"]["known_test_list"]["digest"]


# --- capture: count captor negative controls -----------------------------

@pytest.mark.parametrize("field_name", [
    "unresolved_critical_unknowns_count",
    "unresolved_conflicts_count",
    "recorded_user_decisions_count",
])
def test_count_field_rejects_bool(field_name):
    f = ib.capture_intake_baseline({field_name: True})["fields"][field_name]
    assert f["status"] == ib.NOT_AVAILABLE
    assert f["reason"] == "INVALID_COUNT_VALUE"


@pytest.mark.parametrize("field_name", [
    "unresolved_critical_unknowns_count",
    "unresolved_conflicts_count",
    "recorded_user_decisions_count",
])
def test_count_field_rejects_negative(field_name):
    f = ib.capture_intake_baseline({field_name: -1})["fields"][field_name]
    assert f["status"] == ib.NOT_AVAILABLE
    assert f["reason"] == "INVALID_COUNT_VALUE"


@pytest.mark.parametrize("field_name", [
    "unresolved_critical_unknowns_count",
    "unresolved_conflicts_count",
    "recorded_user_decisions_count",
])
def test_count_field_rejects_non_int(field_name):
    f = ib.capture_intake_baseline({field_name: "3"})["fields"][field_name]
    assert f["status"] == ib.NOT_AVAILABLE
    assert f["reason"] == "INVALID_COUNT_VALUE"


def test_count_field_zero_is_captured_not_not_available():
    f = ib.capture_intake_baseline(
        {"unresolved_conflicts_count": 0})["fields"]["unresolved_conflicts_count"]
    assert f["status"] == ib.CAPTURED
    assert f["digest"]


def test_count_field_changes_digest_with_value():
    a = ib.capture_intake_baseline({"unresolved_conflicts_count": 1})
    b = ib.capture_intake_baseline({"unresolved_conflicts_count": 2})
    fa = a["fields"]["unresolved_conflicts_count"]["digest"]
    fb = b["fields"]["unresolved_conflicts_count"]["digest"]
    assert fa != fb


# --- field-table integrity -------------------------------------------------

def test_field_captor_table_matches_declared_fields():
    assert set(ib.INTAKE_FIELDS) == set(ib.FIELD_CAPTORS)


def test_assert_intake_fields_have_captors_detects_drift(monkeypatch):
    monkeypatch.setattr(ib, "INTAKE_FIELDS", ib.INTAKE_FIELDS + ("a_new_undeclared_field",))
    with pytest.raises(AssertionError):
        ib.assert_intake_fields_have_captors()


# --- freeze / list / load --------------------------------------------------

def test_freeze_requires_frozen_by(tmp_path):
    with pytest.raises(ValueError):
        ib.freeze_intake_baseline(tmp_path, _complete_facts(), frozen_by="")


def test_freeze_writes_one_record_under_dot_dv_harness_intake_baselines(tmp_path):
    rec = ib.freeze_intake_baseline(tmp_path, _complete_facts(), frozen_by="dv-lead")
    assert rec["frozen_by"] == "dv-lead"
    assert rec["freeze_id"]
    fdir = ib.freeze_dir(tmp_path)
    files = list(fdir.glob("*.json"))
    assert len(files) == 1
    on_disk = json.loads(files[0].read_text(encoding="utf-8"))
    assert on_disk["freeze_id"] == rec["freeze_id"]


def test_list_and_load_freeze_round_trip(tmp_path):
    r1 = ib.freeze_intake_baseline(tmp_path, {"unresolved_conflicts_count": 1},
                                   frozen_by="alice")
    r2 = ib.freeze_intake_baseline(tmp_path, {"unresolved_conflicts_count": 2},
                                   frozen_by="bob")
    rows = ib.list_intake_freezes(tmp_path)
    assert {r["freeze_id"] for r in rows} == {r1["freeze_id"], r2["freeze_id"]}
    assert ib.load_intake_freeze(tmp_path, r1["freeze_id"])["frozen_by"] == "alice"
    assert ib.load_intake_freeze(tmp_path, "nonexistent") is None
    # no --freeze-id: the most recently frozen (by frozen_at, not mtime)
    latest = ib.load_intake_freeze(tmp_path)
    assert latest["freeze_id"] in (r1["freeze_id"], r2["freeze_id"])
    assert latest["frozen_at"] == max(r1["frozen_at"], r2["frozen_at"])


def test_list_intake_freezes_on_a_bare_root_is_empty(tmp_path):
    assert ib.list_intake_freezes(tmp_path) == []
    assert ib.load_intake_freeze(tmp_path) is None


# --- evaluate_intake_freeze_invalidation: the central proof ---------------

def test_unchanged_facts_are_valid(tmp_path):
    facts = _complete_facts()
    rec = ib.freeze_intake_baseline(tmp_path, facts, frozen_by="dv-lead")
    report = ib.evaluate_intake_freeze_invalidation(rec, facts)
    assert report["status"] == ib.INTAKE_FREEZE_VALID
    assert report["findings"] == []


def test_changed_dut_sha_after_freeze_is_invalidated(tmp_path):
    facts = _complete_facts()
    rec = ib.freeze_intake_baseline(tmp_path, facts, frozen_by="dv-lead")
    changed = dict(facts)
    changed["dut_sha"] = {"rtl/usb3_link_ctrl.v": "z" * 32,
                          "rtl/usb3_phy_wrap.v": "b" * 32}
    report = ib.evaluate_intake_freeze_invalidation(rec, changed)
    assert report["status"] == ib.INTAKE_FREEZE_INVALIDATED
    codes = {f["code"] for f in report["findings"] if f["field"] == "dut_sha"}
    assert "BASELINE_FIELD_CHANGED" in codes
    assert report["invalidating_count"] >= 1


def test_evidence_disappearing_after_freeze_is_invalidated_not_indeterminate(tmp_path):
    facts = _complete_facts()
    rec = ib.freeze_intake_baseline(tmp_path, facts, frozen_by="dv-lead")
    changed = dict(facts)
    del changed["bind_topology_hash"]
    report = ib.evaluate_intake_freeze_invalidation(rec, changed)
    assert report["status"] == ib.INTAKE_FREEZE_INVALIDATED
    finding = next(f for f in report["findings"] if f["field"] == "bind_topology_hash")
    assert finding["code"] == "BASELINE_EVIDENCE_DISAPPEARED"
    assert finding["severity"] == ib.SEV_INVALIDATING


def test_new_evidence_after_freeze_is_indeterminate_not_invalidated(tmp_path):
    facts = {"unresolved_conflicts_count": 0}  # everything else NOT_AVAILABLE at freeze
    rec = ib.freeze_intake_baseline(tmp_path, facts, frozen_by="dv-lead")
    changed = dict(facts)
    changed["known_test_list"] = ["usb3_smoke_test"]  # newly supplied
    report = ib.evaluate_intake_freeze_invalidation(rec, changed)
    # "we could not check" is never VALID: an appearing fact is real change,
    # so the report is UNKNOWN, but the specific finding must be
    # indeterminate, never treated as an invalidating one.
    assert report["status"] == ib.INTAKE_FREEZE_UNKNOWN
    finding = next(f for f in report["findings"] if f["field"] == "known_test_list")
    assert finding["code"] == "NEW_EVIDENCE_AFTER_FREEZE"
    assert finding["severity"] == ib.SEV_INDETERMINATE
    assert report["invalidating_count"] == 0


def test_tampered_frozen_record_is_invalidated(tmp_path):
    facts = _complete_facts()
    rec = ib.freeze_intake_baseline(tmp_path, facts, frozen_by="dv-lead")
    tampered = json.loads(json.dumps(rec))
    tampered["baseline"]["fields"]["dut_sha"]["digest"] = "0" * 64  # hand-edited
    report = ib.evaluate_intake_freeze_invalidation(tampered, facts)
    assert report["status"] == ib.INTAKE_FREEZE_INVALIDATED
    assert report["record_integrity"] == "FROZEN_RECORD_TAMPERED"


def test_malformed_frozen_record_reports_unknown_never_valid():
    report = ib.evaluate_intake_freeze_invalidation({"freeze_id": "x"}, {})
    assert report["status"] == ib.INTAKE_FREEZE_UNKNOWN
    assert report["record_integrity"] == "FROZEN_BASELINE_MALFORMED_OR_EMPTY"


def test_empty_frozen_record_never_reads_as_valid_even_with_matching_empty_facts():
    """The degenerate case: a frozen record with an empty baseline compared
    against no current facts. Even though there is literally nothing to
    disagree about, "we could not check" must never be reported as VALID."""
    report = ib.evaluate_intake_freeze_invalidation({}, {})
    assert report["status"] != ib.INTAKE_FREEZE_VALID
    assert report["status"] == ib.INTAKE_FREEZE_UNKNOWN


def test_evaluate_all_intake_freezes_no_freeze_recorded_is_not_available(tmp_path):
    report = ib.evaluate_all_intake_freezes(tmp_path, {})
    assert report["status"] == "NOT_AVAILABLE"
    assert report["reason"] == "NO_FROZEN_INTAKE_BASELINE"


def test_evaluate_all_intake_freezes_worst_wins(tmp_path):
    facts = _complete_facts()
    ib.freeze_intake_baseline(tmp_path, facts, frozen_by="alice")  # will stay VALID
    changed = dict(facts)
    changed["tb_sha"] = "9" * 64
    ib.freeze_intake_baseline(tmp_path, changed, frozen_by="bob")  # will diverge later

    # Evaluate everyone against the ORIGINAL facts: bob's freeze (frozen
    # against `changed`) now disagrees with `facts` on tb_sha -> INVALIDATED,
    # while alice's freeze (frozen against `facts`) stays VALID. The worst
    # across both freezes must be INVALIDATED.
    report = ib.evaluate_all_intake_freezes(tmp_path, facts)
    assert report["status"] == ib.INTAKE_FREEZE_INVALIDATED
    assert report["freeze_count"] == 2
    assert report["counts"][ib.INTAKE_FREEZE_VALID] == 1
    assert report["counts"][ib.INTAKE_FREEZE_INVALIDATED] == 1


# --- CLI: real subprocess ---------------------------------------------------

def _run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_baseline", *args],
        cwd=str(cwd or ROOT), capture_output=True, text=True, timeout=60)


def test_cli_fields_lists_all_twelve():
    r = _run_cli("fields")
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert set(doc["intake_fields"]) == set(ib.INTAKE_FIELDS)


def test_cli_baseline_requires_facts():
    r = _run_cli("baseline")
    assert r.returncode == 2
    assert json.loads(r.stdout)["reason"] == "FACTS_REQUIRED"


def test_cli_baseline_over_a_real_facts_file(tmp_path):
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(_complete_facts()), encoding="utf-8")
    r = _run_cli("baseline", "--facts", str(facts_path))
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["captured_field_count"] == len(ib.INTAKE_FIELDS)


def test_cli_freeze_requires_frozen_by(tmp_path):
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(_complete_facts()), encoding="utf-8")
    r = _run_cli("freeze", "--facts", str(facts_path), "--root", str(tmp_path))
    assert r.returncode == 2
    assert json.loads(r.stdout)["reason"] == "FROZEN_BY_REQUIRED"


def test_cli_freeze_then_status_end_to_end(tmp_path):
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(_complete_facts()), encoding="utf-8")
    r = _run_cli("freeze", "--facts", str(facts_path), "--frozen-by", "dv-lead",
                 "--root", str(tmp_path))
    assert r.returncode == 0, r.stderr

    r = _run_cli("list", "--root", str(tmp_path))
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert len(rows) == 1

    r = _run_cli("status", "--facts", str(facts_path), "--root", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["status"] == ib.INTAKE_FREEZE_VALID

    # now change one field's fact and re-check status -> INVALIDATED, exit 1
    changed = _complete_facts()
    changed["reference_uvm_hash"] = {"ref/usb3_ref_env.sv": "a totally different file"}
    changed_path = tmp_path / "changed_facts.json"
    changed_path.write_text(json.dumps(changed), encoding="utf-8")
    r = _run_cli("status", "--facts", str(changed_path), "--root", str(tmp_path))
    assert r.returncode == 1
    assert json.loads(r.stdout)["status"] == ib.INTAKE_FREEZE_INVALIDATED


def test_cli_status_refuses_without_current_facts(tmp_path):
    r = _run_cli("status", "--root", str(tmp_path))
    assert r.returncode == 2
    assert json.loads(r.stdout)["reason"] == "CURRENT_FACTS_REQUIRED"


def test_cli_status_no_freeze_recorded_is_not_available(tmp_path):
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps({}), encoding="utf-8")
    r = _run_cli("status", "--facts", str(facts_path), "--root", str(tmp_path))
    assert r.returncode == 2
    assert json.loads(r.stdout)["status"] == "NOT_AVAILABLE"


def test_cli_list_on_bare_root_exits_2(tmp_path):
    r = _run_cli("list", "--root", str(tmp_path))
    assert r.returncode == 2
    assert json.loads(r.stdout) == []
