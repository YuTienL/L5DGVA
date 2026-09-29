"""Tests for dv_harness/pattern_coverage_contribution.py (2026-09-06).

Real machinery throughout: a REAL DuckDB `EvidenceStore` populated through
its OWN real `insert_coverage_sample()` / `insert_job_state()` methods --
never a hand-written row inserted directly into its store. The module's own
central honesty rule -- a pattern with no recorded coverage-sample evidence
reports NOT_AVAILABLE for its coverage contribution, never an estimated or
zero delta -- is exercised directly, alongside the "meaningful crosses
only" helper and the real-schema absence paths (no DB at all, an empty
coverage_samples table).
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness.evidence_db import EvidenceStore
from dv_harness import pattern_coverage_contribution as pcc


def _job_row(job_id, pattern, *, runtime_seconds=None, uvm_error_count=0,
             uvm_fatal_count=0, assertion_failure=False, simulator_crash=False,
             lsf_status="DONE"):
    return {
        "job_id": job_id, "pattern": pattern, "runtime_seconds": runtime_seconds,
        "uvm_error_count": uvm_error_count, "uvm_fatal_count": uvm_fatal_count,
        "assertion_failure": assertion_failure, "simulator_crash": simulator_crash,
        "lsf_status": lsf_status, "sim_status": "SIM_DONE",
    }


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "evidence" / "evidence.duckdb"


def _seed_checkpoint(db_path, source, categories, *, timestamp=None):
    """Writes one coverage-merge checkpoint through the REAL
    `insert_coverage_sample()` -- one call per category, all sharing the
    same `source`, exactly as `dashboard._ingest_coverage_summary_to_evidence_db()`
    does in production."""
    with EvidenceStore(db_path) as store:
        for cat in categories:
            store.insert_coverage_sample(cat, timestamp=timestamp, source=source)


def _seed_job(db_path, row):
    with EvidenceStore(db_path) as store:
        store.insert_job_state(row)


# ---------------------------------------------------------------------------
# Core positive path
# ---------------------------------------------------------------------------

def test_core_positive_path_attributes_new_bins_and_real_job_evidence(db_path):
    # Checkpoint 1: baseline, produced by patternA.
    _seed_checkpoint(db_path, "run1_summary.json", [
        {"name": "cp_state", "percent": 40.0, "bins_total": 10, "bins_hit": 4},
        {"name": "cp_mode", "percent": 100.0, "bins_total": 4, "bins_hit": 4},
        {"name": "cp_state_x_mode", "percent": 20.0, "bins_total": 20, "bins_hit": 4},
    ], timestamp="2026-09-01")
    _seed_job(db_path, _job_row(1001, "patternA", runtime_seconds=120.5))

    # Checkpoint 2: produced by patternB -- moves cp_state and the cross bin.
    _seed_checkpoint(db_path, "run2_summary.json", [
        {"name": "cp_state", "percent": 70.0, "bins_total": 10, "bins_hit": 7},
        {"name": "cp_mode", "percent": 100.0, "bins_total": 4, "bins_hit": 4},
        {"name": "cp_state_x_mode", "percent": 45.0, "bins_total": 20, "bins_hit": 9},
    ], timestamp="2026-09-02")
    _seed_job(db_path, _job_row(1002, "patternB", runtime_seconds=200.0))

    attribution = [
        {"source": "run1_summary.json", "pattern": "patternA"},
        {"source": "run2_summary.json", "pattern": "patternB"},
    ]
    cross_defs = [{"cross_name": "cp_state_x_mode", "axes": ["cp_state", "cp_mode"]}]

    report = pcc.compute_pattern_coverage_contribution(
        db_path, "patternB", attribution, cross_definitions=cross_defs)

    assert report["status"] == pcc.MEASURED
    cov = report["coverage"]
    assert cov["status"] == pcc.MEASURED
    assert cov["checkpoints_attributed"] == 1
    # cp_state: 7-4=3, cp_mode: 0 (unchanged), cross: 9-4=5 -> total 8
    assert cov["new_bins_hit"] == 8
    # cp_mode (an axis) was already 100% BEFORE patternB ran, but cp_state
    # was only 40% -- not every axis fully explained -> the cross is
    # INDEPENDENTLY_MEANINGFUL and its 5 new hits count toward new_crosses_hit.
    assert cov["new_crosses_hit"] == 5
    assert cov["coverage_delta_percent"] > 0

    rt = report["runtime"]
    assert rt["status"] == pcc.MEASURED
    assert rt["jobs_considered"] == 1
    assert rt["total_seconds"] == 200.0

    fail = report["failures"]
    assert fail["status"] == pcc.MEASURED
    assert fail["failed_job_count"] == 0

    assert report["cost"]["status"] == pcc.NOT_AVAILABLE


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------

def test_pattern_with_no_attribution_and_no_jobs_is_not_available(db_path):
    """The module's headline honesty rule: a pattern with no recorded
    coverage-sample evidence AND no job evidence reports NOT_AVAILABLE,
    never an estimated or zero delta."""
    _seed_checkpoint(db_path, "run1_summary.json", [
        {"name": "cp_state", "percent": 40.0, "bins_total": 10, "bins_hit": 4},
    ])
    attribution = [{"source": "run1_summary.json", "pattern": "patternA"}]

    report = pcc.compute_pattern_coverage_contribution(db_path, "ghost_pattern", attribution)

    assert report["status"] == pcc.NOT_AVAILABLE
    assert report["coverage"]["status"] == pcc.NOT_AVAILABLE
    assert report["runtime"]["status"] == pcc.NOT_AVAILABLE
    assert report["failures"]["status"] == pcc.NOT_AVAILABLE
    # Never a fabricated zero:
    assert "new_bins_hit" not in report["coverage"]


def test_coverage_measured_but_no_job_evidence_is_partial(db_path):
    _seed_checkpoint(db_path, "run1_summary.json", [
        {"name": "cp_state", "percent": 40.0, "bins_total": 10, "bins_hit": 4},
    ])
    _seed_checkpoint(db_path, "run2_summary.json", [
        {"name": "cp_state", "percent": 60.0, "bins_total": 10, "bins_hit": 6},
    ])
    attribution = [
        {"source": "run1_summary.json", "pattern": "patternA"},
        {"source": "run2_summary.json", "pattern": "patternB"},
    ]

    report = pcc.compute_pattern_coverage_contribution(db_path, "patternB", attribution)

    assert report["status"] == pcc.PARTIALLY_MEASURED
    assert report["coverage"]["status"] == pcc.MEASURED
    assert report["coverage"]["new_bins_hit"] == 2
    assert report["runtime"]["status"] == pcc.NOT_AVAILABLE
    assert report["failures"]["status"] == pcc.NOT_AVAILABLE


def test_job_evidence_but_no_attributed_checkpoint_is_partial(db_path):
    _seed_checkpoint(db_path, "run1_summary.json", [
        {"name": "cp_state", "percent": 40.0, "bins_total": 10, "bins_hit": 4},
    ])
    _seed_job(db_path, _job_row(2001, "patternC", runtime_seconds=55.0))
    # patternC never appears in sample_attribution.
    attribution = [{"source": "run1_summary.json", "pattern": "patternA"}]

    report = pcc.compute_pattern_coverage_contribution(db_path, "patternC", attribution)

    assert report["status"] == pcc.PARTIALLY_MEASURED
    assert report["coverage"]["status"] == pcc.NOT_AVAILABLE
    assert report["runtime"]["status"] == pcc.MEASURED
    assert report["runtime"]["total_seconds"] == 55.0


def test_malformed_sample_attribution_entry_raises(db_path):
    _seed_checkpoint(db_path, "run1_summary.json", [
        {"name": "cp_state", "percent": 40.0, "bins_total": 10, "bins_hit": 4},
    ])
    with pytest.raises(pcc.PatternCoverageContributionError):
        pcc.compute_pattern_coverage_contribution(
            db_path, "patternA", [{"pattern": "patternA"}])  # missing 'source'


def test_ambiguous_attribution_same_source_two_patterns_raises(db_path):
    _seed_checkpoint(db_path, "run1_summary.json", [
        {"name": "cp_state", "percent": 40.0, "bins_total": 10, "bins_hit": 4},
    ])
    attribution = [
        {"source": "run1_summary.json", "pattern": "patternA"},
        {"source": "run1_summary.json", "pattern": "patternB"},
    ]
    with pytest.raises(pcc.PatternCoverageContributionError):
        pcc.compute_pattern_coverage_contribution(db_path, "patternA", attribution)


def test_no_evidence_database_at_all_is_not_available_never_crashes(tmp_path):
    missing = tmp_path / "does" / "not" / "exist.duckdb"
    attribution = [{"source": "run1_summary.json", "pattern": "patternA"}]

    report = pcc.compute_pattern_coverage_contribution(missing, "patternA", attribution)

    assert report["status"] == pcc.NOT_AVAILABLE
    assert report["coverage"]["status"] == pcc.NOT_AVAILABLE
    assert "could not open evidence database" in report["coverage"]["reason"]


def test_negative_delta_is_reported_honestly_and_never_counted_as_new(db_path):
    """A category whose bins_hit goes DOWN between checkpoints (a real
    coverage regression, however unusual) must never inflate new_bins_hit,
    and must be surfaced rather than silently hidden."""
    _seed_checkpoint(db_path, "run1.json", [
        {"name": "cp_state", "percent": 80.0, "bins_total": 10, "bins_hit": 8},
    ])
    _seed_checkpoint(db_path, "run2.json", [
        {"name": "cp_state", "percent": 50.0, "bins_total": 10, "bins_hit": 5},
    ])
    attribution = [
        {"source": "run1.json", "pattern": "patternA"},
        {"source": "run2.json", "pattern": "patternB"},
    ]

    report = pcc.compute_pattern_coverage_contribution(db_path, "patternB", attribution)

    assert report["coverage"]["new_bins_hit"] == 0
    assert "cp_state" in report["coverage"]["regressed_categories"]


def test_multiple_checkpoints_for_the_same_pattern_are_summed(db_path):
    _seed_checkpoint(db_path, "run1.json", [
        {"name": "cp_state", "percent": 10.0, "bins_total": 10, "bins_hit": 1},
    ])
    _seed_checkpoint(db_path, "run2.json", [
        {"name": "cp_state", "percent": 40.0, "bins_total": 10, "bins_hit": 4},
    ])
    _seed_checkpoint(db_path, "run3.json", [
        {"name": "cp_state", "percent": 70.0, "bins_total": 10, "bins_hit": 7},
    ])
    attribution = [
        {"source": "run1.json", "pattern": "patternA"},
        {"source": "run2.json", "pattern": "patternA"},
        {"source": "run3.json", "pattern": "patternA"},
    ]

    report = pcc.compute_pattern_coverage_contribution(db_path, "patternA", attribution)

    assert report["coverage"]["checkpoints_attributed"] == 3
    # 1 (baseline 0->1) + 3 (1->4) + 3 (4->7) == 7, same as the raw final delta.
    assert report["coverage"]["new_bins_hit"] == 7


# ---------------------------------------------------------------------------
# "Meaningful crosses only" helper
# ---------------------------------------------------------------------------

def test_cross_fully_explained_by_already_covered_axes():
    snapshot = {
        "cp_a": {"percent": 100.0, "bins_total": 4, "bins_hit": 4},
        "cp_b": {"percent": 100.0, "bins_total": 4, "bins_hit": 4},
    }
    result = pcc.classify_cross_coverage_meaningfulness(
        snapshot, [{"cross_name": "cp_a_x_cp_b", "axes": ["cp_a", "cp_b"]}])
    assert result[0]["verdict"] == pcc.CROSS_FULLY_EXPLAINED


def test_cross_not_meaningful_verdict_when_an_axis_is_not_fully_covered():
    snapshot = {
        "cp_a": {"percent": 100.0, "bins_total": 4, "bins_hit": 4},
        "cp_b": {"percent": 50.0, "bins_total": 4, "bins_hit": 2},
    }
    result = pcc.classify_cross_coverage_meaningfulness(
        snapshot, [{"cross_name": "cp_a_x_cp_b", "axes": ["cp_a", "cp_b"]}])
    assert result[0]["verdict"] == pcc.CROSS_MEANINGFUL


def test_cross_unknown_when_an_axis_is_absent_never_assumed_fully_explained():
    """An axis this module cannot find must never be silently treated as
    already fully explaining the cross -- that would let a cross bin be
    skipped on the strength of missing evidence."""
    snapshot = {"cp_a": {"percent": 100.0, "bins_total": 4, "bins_hit": 4}}
    result = pcc.classify_cross_coverage_meaningfulness(
        snapshot, [{"cross_name": "cp_a_x_cp_b", "axes": ["cp_a", "cp_b"]}])
    assert result[0]["verdict"] == pcc.CROSS_UNKNOWN


def test_malformed_cross_definition_raises():
    with pytest.raises(pcc.PatternCoverageContributionError):
        pcc.classify_cross_coverage_meaningfulness({}, [{"cross_name": "x", "axes": ["only_one"]}])


def test_unknown_cross_axis_still_counts_toward_new_crosses_hit(db_path):
    """UNKNOWN must never be treated as FULLY_EXPLAINED -- an un-provable
    cross bin still counts as a meaningful new-crosses contribution."""
    _seed_checkpoint(db_path, "run1.json", [
        {"name": "cp_a_x_cp_b", "percent": 20.0, "bins_total": 10, "bins_hit": 2},
    ])
    _seed_checkpoint(db_path, "run2.json", [
        {"name": "cp_a_x_cp_b", "percent": 50.0, "bins_total": 10, "bins_hit": 5},
    ])
    # cp_a/cp_b never appear as their own categories anywhere.
    attribution = [
        {"source": "run1.json", "pattern": "patternA"},
        {"source": "run2.json", "pattern": "patternB"},
    ]
    cross_defs = [{"cross_name": "cp_a_x_cp_b", "axes": ["cp_a", "cp_b"]}]

    report = pcc.compute_pattern_coverage_contribution(
        db_path, "patternB", attribution, cross_definitions=cross_defs)

    assert report["coverage"]["new_bins_hit"] == 3
    assert report["coverage"]["new_crosses_hit"] == 3
    verdicts = {c["cross_name"]: c["verdict"] for c in report["coverage"]["cross_classification"]}
    assert verdicts["cp_a_x_cp_b"] == pcc.CROSS_UNKNOWN


# ---------------------------------------------------------------------------
# Vocabulary self-check
# ---------------------------------------------------------------------------

def test_vocabulary_has_no_verification_verdict_collision():
    pcc.assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_reports_measured_exit_zero(tmp_path, db_path):
    _seed_checkpoint(db_path, "run1.json", [
        {"name": "cp_state", "percent": 40.0, "bins_total": 10, "bins_hit": 4},
    ])
    _seed_job(db_path, _job_row(1, "patternA", runtime_seconds=1.0))
    attribution_path = tmp_path / "attribution.json"
    attribution_path.write_text(json.dumps([{"source": "run1.json", "pattern": "patternA"}]))

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.pattern_coverage_contribution", "contribution",
         "--db-path", str(db_path), "--pattern", "patternA",
         "--attribution", str(attribution_path), "--json"],
        cwd=str(pcc.__file__.rsplit("dv_harness", 1)[0]),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "MEASURED"


def test_cli_reports_not_available_exit_two(tmp_path):
    missing_db = tmp_path / "nope.duckdb"
    attribution_path = tmp_path / "attribution.json"
    attribution_path.write_text(json.dumps([{"source": "run1.json", "pattern": "patternA"}]))

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.pattern_coverage_contribution", "contribution",
         "--db-path", str(missing_db), "--pattern", "ghost",
         "--attribution", str(attribution_path)],
        cwd=str(pcc.__file__.rsplit("dv_harness", 1)[0]),
        capture_output=True, text=True,
    )
    assert result.returncode == 2, result.stderr
