"""Tests for dv_harness/signoff_blocker_list.py -- the Signoff Blocker List
(2026-09-07).

Every input is produced by its REAL owning module, never hand-typed to merely
look like one: waivers go through the real `waiver_store.record_waiver()`
ledger writer; coverage numbers land in a REAL DuckDB `EvidenceStore` through
`insert_coverage_sample()`; the declared coverage-goal scope is a REAL,
schema-valid `env.manifest.json` built by `env_manifest.generate_env_manifest()`
-- the identical fixture recipe `test_functional_coverage_signoff.py`'s own
suite already establishes, reused here rather than re-invented.

The central negative controls this item's own house style requires:
  * a bare project with NONE of the three natively-resolved sources present,
    and no `evidence_integrity_states` sibling module in this checkout,
    reports `signoff_blockers == []` (never a fabricated blocker) with
    `signoff_status == INCOMPLETE_EVIDENCE` (never silently CLOSED);
  * the missing `evidence_integrity_states` sibling module is reported
    NOT_AVAILABLE, never guessed clear or blocked;
  * one genuinely UNMET dimension among an otherwise-all-clean twelve still
    reads the whole rollup NOT_CLOSED (worst-wins), and is the only entry in
    `signoff_blockers`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness import env_manifest as em
from dv_harness import functional_coverage_signoff as fcs
from dv_harness import signoff_blocker_list as sbl
from dv_harness import system_closure_aggregator as sca
from dv_harness import waiver_store as ws
from dv_harness.evidence_db import EvidenceStore, default_db_path

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# helpers -- real producers only
# ---------------------------------------------------------------------------

def _insert_coverage(root: Path, categories) -> None:
    with EvidenceStore(default_db_path(root)) as store:
        for cat in categories:
            store.insert_coverage_sample(cat, timestamp="2026-09-07T00:00:00Z", source="test")


def _write_env_manifest(root: Path, bins) -> None:
    testplan = {
        "schema_version": "1.0",
        "coverage_model": [{"name": name, "kind": "covergroup"} for name in bins],
        "vplan_items": [{"id": f"VP-{name}", "coverage": [name]} for name in bins],
    }
    tp_path = root / "testplan_sources.json"
    tp_path.write_text(json.dumps(testplan), encoding="utf-8")
    manifest = em.generate_env_manifest(testplan_sources_path=tp_path)
    out_path = root / ".dv-harness" / "env.manifest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    em.save_env_manifest(manifest, out_path)


def _record_waiver(root: Path, waiver_id: str, item: str, *, expires_at: str) -> None:
    ws.record_waiver(root, {
        "waiver_id": waiver_id, "item": item, "reason": "known limitation, accepted by design",
        "evidence": "see review notes", "approver": "alice",
        "affected_version": {"spec_revision": "r1"}, "risk": "LOW",
        "created_at": "2026-01-01T00:00:00+00:00",
        "expires_at": expires_at,
        "scope": {
            "requirement_ids": ["REQ-1"], "subsystem": "usb3", "spec_revision": "r1",
            "design_evidence_hash": "abc123", "approval_id": "AP-1", "scope_hash": "hash1",
        },
    })


def _write_empty_waiver_store(root: Path) -> None:
    """A real, existing-but-empty waiver ledger -- `waiver_status` then
    derives real MET (store exists, zero waivers recorded), distinct from
    NO_WAIVER_STORE (store never created at all). Uses `_store_path()`
    directly, the same real-internal-path convention
    `test_waiver_store_gate_wiring.py`'s own suite already uses, since
    `waiver_store.py` exposes no public "create an empty store" verb."""
    path = ws._store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]", encoding="utf-8")


def _make_signoff_ready_project(root: Path) -> None:
    """A project whose functional_coverage AND waiver_status dimensions are
    both real, genuine MET -- 100% closure, no waivers."""
    root.mkdir(parents=True, exist_ok=True)
    _write_env_manifest(root, ["cov_a", "cov_b"])
    _insert_coverage(root, [
        {"name": "cov_a", "percent": 100.0, "bins_total": 10, "bins_hit": 10},
        {"name": "cov_b", "percent": 100.0, "bins_total": 5, "bins_hit": 5},
    ])
    _write_empty_waiver_store(root)


def _all_met_residual_records():
    """{dimension_name, status} MET records for every one of the nine
    BLOCKER_CATEGORIES -- so a test can isolate one dimension at a time."""
    return [{"dimension_name": name, "status": "MET"} for name in sbl.BLOCKER_CATEGORIES]


# ---------------------------------------------------------------------------
# the 9-item derivation itself
# ---------------------------------------------------------------------------

def test_blocker_categories_is_exactly_nine_real_closure_dimensions():
    assert len(sbl.BLOCKER_CATEGORIES) == 9
    assert len(set(sbl.BLOCKER_CATEGORIES)) == 9
    for name in sbl.BLOCKER_CATEGORIES:
        assert name in sca.CLOSURE_DIMENSIONS


def test_blocker_categories_excludes_exactly_the_three_natively_resolved():
    assert set(sbl.NATIVELY_RESOLVED_DIMENSIONS) == {
        "functional_coverage", "waiver_status", "evidence_integrity"}
    assert not (set(sbl.BLOCKER_CATEGORIES) & set(sbl.NATIVELY_RESOLVED_DIMENSIONS))


def test_blocker_categories_plus_natively_resolved_partitions_closure_dimensions():
    assert set(sbl.BLOCKER_CATEGORIES) | set(sbl.NATIVELY_RESOLVED_DIMENSIONS) == \
        set(sca.CLOSURE_DIMENSIONS)


def test_nine_item_derivation_guard_actually_raises_on_a_broken_partition(monkeypatch):
    monkeypatch.setattr(sbl, "BLOCKER_CATEGORIES", sbl.BLOCKER_CATEGORIES + ("bogus_dim",))
    with pytest.raises(sbl.SignoffBlockerListError):
        sbl._assert_nine_item_derivation()


def test_nine_item_derivation_guard_raises_on_a_duplicate():
    dup = sbl.BLOCKER_CATEGORIES + (sbl.BLOCKER_CATEGORIES[0],)
    orig = sbl.BLOCKER_CATEGORIES
    try:
        sbl.BLOCKER_CATEGORIES = dup
        with pytest.raises(sbl.SignoffBlockerListError):
            sbl._assert_nine_item_derivation()
    finally:
        sbl.BLOCKER_CATEGORIES = orig


# ---------------------------------------------------------------------------
# the required negative control: absence of evidence is honest, never a guess
# ---------------------------------------------------------------------------

def test_bare_project_reports_no_fabricated_blockers(tmp_path):
    """No waiver store, no evidence db, no manifest, no evidence_integrity_
    states module in this checkout, no caller-supplied residual records:
    every one of the twelve dimensions is genuinely unmeasured, so the
    honest answer is zero blockers and INCOMPLETE_EVIDENCE overall -- never
    a fabricated blocker and never a silently-CLOSED verdict."""
    root = tmp_path / "bare"
    root.mkdir()
    report = sbl.derive_signoff_blockers(root)
    assert report["signoff_blockers"] == []
    assert report["signoff_status"] == sca.CLOSURE_INCOMPLETE_EVIDENCE
    names = {d["dimension_name"] for d in report["incomplete_evidence_dimensions"]}
    assert names == set(sca.CLOSURE_DIMENSIONS)
    assert report["blocker_categories"] == list(sbl.BLOCKER_CATEGORIES)
    assert len(report["blocker_categories"]) == 9


def test_evidence_integrity_project_with_no_recorded_evidence_is_not_available(tmp_path):
    """The real sibling module (`evidence_integrity_states.py`) IS present in
    this checkout -- this proves the real, live integration path: a project
    recording no golden-scenario capsule and no signoff freeze at all reports
    NOT_AVAILABLE through the real `classify_project_evidence_integrity()`
    call, never a fabricated MET/UNMET."""
    root = tmp_path / "bare"
    root.mkdir()
    dim, detail = sbl._evidence_integrity_record(root)
    assert dim["status"] == "NOT_AVAILABLE"
    assert "NO_EVIDENCE_RECORDED" in dim["reason"]
    assert detail.get("status") == "NOT_AVAILABLE"


def test_evidence_integrity_states_import_failure_is_honestly_not_available(tmp_path, monkeypatch):
    """The required negative control for the sibling-module-unavailable
    path itself: even with the real module present on disk, any failure of
    the one real call this module makes (simulated here via monkeypatch,
    exactly the sibling-absent case this batch's task brief names) reports
    NOT_AVAILABLE -- never a guessed clear or blocked verdict."""
    root = tmp_path / "bare"
    root.mkdir()

    def _raise_import_error(_root):
        raise ImportError("simulated: evidence_integrity_states not importable")

    monkeypatch.setattr(sbl, "_call_evidence_integrity_states", _raise_import_error)
    dim, detail = sbl._evidence_integrity_record(root)
    assert dim["status"] == "NOT_AVAILABLE"
    assert "not importable" in dim["reason"]


def test_evidence_integrity_states_call_exception_is_honestly_not_available(tmp_path, monkeypatch):
    root = tmp_path / "bare"
    root.mkdir()

    def _raise(_root):
        raise RuntimeError("simulated evidence_integrity_states failure")

    monkeypatch.setattr(sbl, "_call_evidence_integrity_states", _raise)
    dim, _detail = sbl._evidence_integrity_record(root)
    assert dim["status"] == "NOT_AVAILABLE"
    assert "raised" in dim["reason"]


@pytest.mark.parametrize("eis_status,expected_dim_status", [
    ("VALID", "MET"),
    ("SUPERSEDED", "MET"),
    ("STALE", "UNMET"),
    ("CONTRADICTED", "UNMET"),
    ("CORRUPT", "UNMET"),
    ("UNKNOWN", "UNKNOWN"),
    ("NOT_AVAILABLE", "NOT_AVAILABLE"),
])
def test_evidence_integrity_states_status_mapping(tmp_path, eis_status, expected_dim_status):
    """`evidence_integrity_states.py`'s own real six-value project rollup
    vocabulary, mapped onto this module's MET/UNMET/UNKNOWN/NOT_AVAILABLE --
    one caller-supplied report per real status value, mirroring
    `classify_project_evidence_integrity()`'s own actual output shape
    exactly (never a shape this module invented)."""
    root = tmp_path / "proj"
    root.mkdir()
    report = {"schema_version": "1.0", "status": eis_status,
              "capsule_count": 1, "freeze_count": 0, "counts": {eis_status: 1}}
    dim, _detail = sbl._evidence_integrity_record(root, evidence_integrity_report=report)
    assert dim["status"] == expected_dim_status


def test_evidence_integrity_absent_never_counted_as_a_blocker(tmp_path):
    root = tmp_path / "bare"
    _make_signoff_ready_project(root)
    report = sbl.derive_signoff_blockers(
        root, residual_dimension_records=_all_met_residual_records())
    # functional_coverage + waiver_status are real MET; the nine residual are
    # forced MET; only evidence_integrity is unmeasured -- that must show up
    # as incomplete evidence, never as a blocker.
    blocker_names = {b["dimension_name"] for b in report["signoff_blockers"]}
    assert "evidence_integrity" not in blocker_names
    incomplete_names = {d["dimension_name"] for d in report["incomplete_evidence_dimensions"]}
    assert incomplete_names == {"evidence_integrity"}
    assert report["signoff_status"] == sca.CLOSURE_INCOMPLETE_EVIDENCE


# ---------------------------------------------------------------------------
# waiver_status, from the real waiver_store
# ---------------------------------------------------------------------------

def test_expired_waiver_blocks_signoff_and_names_the_waiver(tmp_path):
    root = tmp_path / "proj"
    _make_signoff_ready_project(root)
    _record_waiver(root, "W-1", "cov_a", expires_at="2020-01-01T00:00:00+00:00")
    report = sbl.derive_signoff_blockers(
        root,
        residual_dimension_records=_all_met_residual_records(),
        evidence_integrity_report={"status": "MET"},
    )
    assert report["signoff_status"] == sca.CLOSURE_NOT_CLOSED
    names = {b["dimension_name"] for b in report["signoff_blockers"]}
    assert "waiver_status" in names
    waiver_blocker = next(b for b in report["signoff_blockers"] if b["dimension_name"] == "waiver_status")
    assert "W-1" in " ".join(waiver_blocker["reasons"])
    assert any(w["waiver_id"] == "W-1" for w in waiver_blocker["detail"]["blocking_waivers"])


def test_all_valid_waivers_read_met(tmp_path):
    root = tmp_path / "proj"
    _make_signoff_ready_project(root)
    _record_waiver(root, "W-2", "cov_a", expires_at="2099-01-01T00:00:00+00:00")
    report = sbl.derive_signoff_blockers(
        root, residual_dimension_records=_all_met_residual_records(),
        evidence_integrity_report={"status": "MET"})
    dims = {d["dimension_name"]: d for d in report["dimensions"]}
    assert dims["waiver_status"]["normalized_status"] == "MET"


def test_no_waiver_store_at_all_is_not_available(tmp_path):
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    _write_env_manifest(root, ["cov_a"])
    _insert_coverage(root, [{"name": "cov_a", "percent": 100.0, "bins_total": 1, "bins_hit": 1}])
    # deliberately no waiver store at all -- distinct from an empty one
    dim, _detail = sbl._waiver_status_record(root)
    assert dim["status"] == "NOT_AVAILABLE"
    assert dim["reason"] == "NO_WAIVER_STORE"


# ---------------------------------------------------------------------------
# functional_coverage, from the real functional_coverage_signoff rollup
# ---------------------------------------------------------------------------

def test_full_closure_reads_functional_coverage_met(tmp_path):
    root = tmp_path / "proj"
    _make_signoff_ready_project(root)
    report = sbl.derive_signoff_blockers(
        root, residual_dimension_records=_all_met_residual_records(),
        evidence_integrity_report={"status": "MET"})
    dims = {d["dimension_name"]: d for d in report["dimensions"]}
    assert dims["functional_coverage"]["normalized_status"] == "MET"
    assert report["signoff_status"] == sca.CLOSURE_CLOSED
    assert report["signoff_blockers"] == []


def test_partial_closure_blocks_signoff_with_real_percent(tmp_path):
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    _write_env_manifest(root, ["cov_a"])
    _insert_coverage(root, [{"name": "cov_a", "percent": 40.0, "bins_total": 10, "bins_hit": 4}])
    report = sbl.derive_signoff_blockers(
        root, residual_dimension_records=_all_met_residual_records(),
        evidence_integrity_report={"status": "MET"})
    assert report["signoff_status"] == sca.CLOSURE_NOT_CLOSED
    names = {b["dimension_name"] for b in report["signoff_blockers"]}
    assert "functional_coverage" in names
    fc_blocker = next(b for b in report["signoff_blockers"] if b["dimension_name"] == "functional_coverage")
    assert fc_blocker["detail"]["closure_percent"] < 100.0


def test_no_evidence_database_is_honestly_not_available_for_functional_coverage(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    dim, detail = sbl._functional_coverage_record(root)
    assert dim["status"] == "NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# the nine residual BLOCKER_CATEGORIES: caller-supplied only, never invented
# ---------------------------------------------------------------------------

def test_no_source_named_for_residual_dimensions_reports_not_supplied(tmp_path):
    root = tmp_path / "proj"
    _make_signoff_ready_project(root)
    report = sbl.derive_signoff_blockers(root, evidence_integrity_report={"status": "MET"})
    incomplete_names = {d["dimension_name"] for d in report["incomplete_evidence_dimensions"]}
    assert incomplete_names == set(sbl.BLOCKER_CATEGORIES)
    for d in report["incomplete_evidence_dimensions"]:
        assert d["status"] == "NOT_SUPPLIED"


def test_one_residual_unmet_dimension_blocks_overall_worst_wins(tmp_path):
    root = tmp_path / "proj"
    _make_signoff_ready_project(root)
    records = _all_met_residual_records()
    unmet_name = sbl.BLOCKER_CATEGORIES[3]
    for r in records:
        if r["dimension_name"] == unmet_name:
            r["status"] = "FAIL"
    report = sbl.derive_signoff_blockers(
        root, residual_dimension_records=records,
        evidence_integrity_report={"status": "MET"})
    assert report["signoff_status"] == sca.CLOSURE_NOT_CLOSED
    assert [b["dimension_name"] for b in report["signoff_blockers"]] == [unmet_name]
    assert report["signoff_blockers"][0]["in_core_nine"] is True


def test_residual_record_naming_a_natively_resolved_dimension_is_forwarded_not_dropped(tmp_path):
    """A caller mistakenly (or deliberately) supplying its own record for
    `waiver_status` alongside this module's own real derivation must never
    be silently dropped -- a genuine disagreement surfaces as
    AMBIGUOUS_CONFLICTING_SUBMISSIONS via system_closure_aggregator's own
    arbitration boundary."""
    root = tmp_path / "proj"
    _make_signoff_ready_project(root)  # real waiver_status derives MET (no waivers)
    conflicting = _all_met_residual_records() + [
        {"dimension_name": "waiver_status", "status": "FAIL"}]
    report = sbl.derive_signoff_blockers(
        root, residual_dimension_records=conflicting,
        evidence_integrity_report={"status": "MET"})
    dims = {d["dimension_name"]: d for d in report["dimensions"]}
    assert dims["waiver_status"]["normalized_status"] == "AMBIGUOUS_CONFLICTING_SUBMISSIONS"


# ---------------------------------------------------------------------------
# fully clean twelve -> CLOSED, and unrecognized records pass through
# ---------------------------------------------------------------------------

def test_all_twelve_clean_is_closed_with_zero_blockers(tmp_path):
    root = tmp_path / "proj"
    _make_signoff_ready_project(root)
    report = sbl.derive_signoff_blockers(
        root, residual_dimension_records=_all_met_residual_records(),
        evidence_integrity_report={"status": "NOT_APPLICABLE"})
    assert report["signoff_status"] == sca.CLOSURE_CLOSED
    assert report["signoff_blockers"] == []
    assert report["incomplete_evidence_dimensions"] == []
    assert len(report["dimensions"]) == 12


def test_unrecognized_dimension_name_reported_not_dropped(tmp_path):
    root = tmp_path / "proj"
    _make_signoff_ready_project(root)
    records = _all_met_residual_records() + [{"dimension_name": "not_a_real_dimension", "status": "FAIL"}]
    report = sbl.derive_signoff_blockers(
        root, residual_dimension_records=records,
        evidence_integrity_report={"status": "MET"})
    assert any(u.get("dimension_name") == "not_a_real_dimension" for u in report["unrecognized_records"])


# ---------------------------------------------------------------------------
# markdown rendering
# ---------------------------------------------------------------------------

def test_render_markdown_names_status_and_blockers(tmp_path):
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    _write_env_manifest(root, ["cov_a"])
    _insert_coverage(root, [{"name": "cov_a", "percent": 10.0, "bins_total": 10, "bins_hit": 1}])
    report = sbl.derive_signoff_blockers(
        root, residual_dimension_records=_all_met_residual_records(),
        evidence_integrity_report={"status": "MET"})
    text = sbl.render_signoff_blocker_markdown(report)
    assert "SIGNOFF_STATUS: NOT_CLOSED" in text
    assert "functional_coverage" in text


def test_render_markdown_empty_blockers_notes_it(tmp_path):
    root = tmp_path / "proj"
    _make_signoff_ready_project(root)
    report = sbl.derive_signoff_blockers(
        root, residual_dimension_records=_all_met_residual_records(),
        evidence_integrity_report={"status": "MET"})
    text = sbl.render_signoff_blocker_markdown(report)
    assert "no open signoff blockers" in text


# ---------------------------------------------------------------------------
# CLI, as real subprocesses
# ---------------------------------------------------------------------------

def _run_cli(args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.signoff_blocker_list", *args],
        cwd=str(ROOT), capture_output=True, text=True)


def test_cli_bare_project_exits_2_incomplete_evidence(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    proc = _run_cli(["--project-root", str(root), "--json"])
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["signoff_status"] == "INCOMPLETE_EVIDENCE"
    assert payload["signoff_blockers"] == []


def test_cli_closed_project_exits_0(tmp_path):
    root = tmp_path / "proj"
    _make_signoff_ready_project(root)
    residual_path = tmp_path / "residual.json"
    residual_path.write_text(json.dumps(_all_met_residual_records()), encoding="utf-8")
    ei_path = tmp_path / "ei.json"
    ei_path.write_text(json.dumps({"status": "MET"}), encoding="utf-8")
    proc = _run_cli(["--project-root", str(root),
                      "--residual-dimensions", str(residual_path),
                      "--evidence-integrity", str(ei_path), "--json"])
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["signoff_status"] == "CLOSED"


def test_cli_blocked_project_exits_1(tmp_path):
    root = tmp_path / "proj"
    _make_signoff_ready_project(root)
    _record_waiver(root, "W-3", "cov_a", expires_at="2020-01-01T00:00:00+00:00")
    residual_path = tmp_path / "residual.json"
    residual_path.write_text(json.dumps(_all_met_residual_records()), encoding="utf-8")
    proc = _run_cli(["--project-root", str(root),
                      "--residual-dimensions", str(residual_path), "--json"])
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["signoff_status"] == "NOT_CLOSED"


def test_cli_markdown_flag_runs(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    proc = _run_cli(["--project-root", str(root), "--markdown"])
    assert proc.returncode == 2
    assert "SIGNOFF_STATUS" in proc.stdout


def test_cli_missing_residual_dimensions_file_reports_not_available(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    proc = _run_cli(["--project-root", str(root),
                      "--residual-dimensions", str(tmp_path / "nope.json")])
    assert proc.returncode == 2
    assert "NOT_AVAILABLE" in proc.stderr
