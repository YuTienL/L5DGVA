"""dv_harness/coverage_stall_capability_discovery.py -- the section-64
COVERAGE_HOLE sibling to capability_evolution.py's REPEATED-FAILURE auto-filing
coupling.

WHAT THESE TESTS ARE FOR:

  1. A real PLATEAU verdict from loop_convergence.classify_loop_convergence()
     actually files a real, persisted DISCOVERED candidate -- not merely a
     dict this module hands back.
  2. Every OTHER real verdict (CONVERGING, and the honest UNKNOWN a project
     with no series/evidence reports) never files anything. This is the
     negative control the task specifically asks for: with evidence absent,
     the module refuses to fabricate a plateau finding, not merely refuses to
     recommend from one.
  3. The filed candidate performs no repository search of its own (all six
     existing_* slots are honestly NOT SEARCHED), so overlap_status and
     recommendation come back UNKNOWN -- never a guessed MISSING/ADD.
  4. The three-outcome filing discipline
     (DISCOVERED / ALREADY_ON_FILE_UNCHANGED / ALREADY_BEYOND_DISCOVERED)
     matches capability_evolution.file_repeated_failure_candidate()'s own
     shape: re-filing an unchanged plateau does not grow the audit trail, and
     a candidate a human has already moved on is never dragged back.
  5. Confidence is RECOMPUTED from its own stored inputs, never trusted.
  6. One real end-to-end pass drives the REAL production coverage write path
     (dashboard.append_coverage_history_sample(), the exact function
     engine.py calls on a real COVERAGE_CLOSURE PASS) into a REAL DuckDB
     evidence store, through daily_rollup(), to a real PLATEAU verdict, to a
     real persisted candidate -- so the whole chain is proven at least once,
     not only against a caller-supplied synthetic series.

Nothing here runs a build, a regression or an LSF submission.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import capability_evolution as ce
from dv_harness import coverage_stall_capability_discovery as csd
from dv_harness import inference
from dv_harness import loop_convergence as lcv


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def series(values):
    """A ProgressPoint series with real, distinct labels -- the same helper
    shape test_loop_convergence.py uses."""
    return [lcv.ProgressPoint(label=f"2026-09-{i + 1:02d}", value=float(v))
            for i, v in enumerate(values)]


PLATEAU_VALUES = [90.0, 90.2, 89.9, 90.1, 90.0]
CONVERGING_VALUES = [10.0, 25.0, 40.0, 55.0]


# ==========================================================================
# 1. The negative control: absent/non-plateau evidence never fabricates a
#    finding, and never files anything.
# ==========================================================================
def test_a_bare_project_with_no_series_and_no_evidence_db_files_nothing(root):
    """No evidence at all -> loop_convergence itself reports UNKNOWN
    (INSUFFICIENT_HISTORY / NO_EVIDENCE_DATABASE), never a guessed PLATEAU.
    This module must inherit that honesty rather than paper over it: the
    pattern is None, and the whole coupling stays a no-op."""
    pattern = csd.coverage_stall_pattern(root)
    assert pattern is None

    results = csd.file_candidates_for_coverage_stall(root, cfg={})
    assert results == []
    assert ce.read_candidates(root) == {}


def test_a_converging_series_never_files_a_candidate(root):
    """Real progress is not a stall. Confirms the module does not fire on
    every real verdict -- only on the real PLATEAU one."""
    v = lcv.classify_convergence(series(CONVERGING_VALUES))
    assert v.verdict == lcv.CONVERGING  # sanity: this really is not a plateau

    pattern = csd.coverage_stall_pattern(root, points=series(CONVERGING_VALUES))
    assert pattern is None
    assert csd.file_candidates_for_coverage_stall(
        root, points=series(CONVERGING_VALUES), cfg={}
    ) == []
    assert ce.read_candidates(root) == {}


def test_too_short_a_series_is_UNKNOWN_never_a_fabricated_plateau(root):
    """Fewer than two points is section 88's own UNKNOWN/INSUFFICIENT_HISTORY
    floor -- reused here, not re-derived. One sample must never be read as
    evidence of a stall."""
    v = lcv.classify_convergence(series([90.0]))
    assert v.verdict == lcv.UNKNOWN

    pattern = csd.coverage_stall_pattern(root, points=series([90.0]))
    assert pattern is None


# ==========================================================================
# 2. A real PLATEAU verdict really files a real, persisted candidate.
# ==========================================================================
def test_a_real_plateau_files_a_real_persisted_DISCOVERED_candidate(root):
    v = lcv.classify_convergence(series(PLATEAU_VALUES))
    assert v.verdict == lcv.PLATEAU  # sanity: this really is a plateau

    pattern = csd.coverage_stall_pattern(root, points=series(PLATEAU_VALUES))
    assert pattern is not None
    assert pattern["verdict"] == lcv.PLATEAU
    assert pattern["metric"] == lcv.COVERAGE_PERCENT_METRIC

    results = csd.file_candidates_for_coverage_stall(
        root, points=series(PLATEAU_VALUES), cfg={}
    )
    assert len(results) == 1
    result = results[0]
    assert result["filed"] is True
    assert result["reason"] == "DISCOVERED"
    cid = result["candidate_id"]

    stored = ce.read_candidate(root, cid)
    assert stored is not None
    assert stored["current_status"] == "DISCOVERED"
    assert stored["trigger_type"] == "COVERAGE_HOLE"
    assert stored["affected_capability"] == csd.AFFECTED_CAPABILITY
    # No search was performed, so build_candidate()'s own decide_recommendation()
    # can only have derived UNKNOWN -- never a guessed MISSING/ADD.
    assert stored["overlap_status"] == "UNKNOWN"
    assert stored["recommendation"] == "UNKNOWN"

    audit = ce.candidate_audit_records(root, cid)
    assert len(audit) == 1
    assert audit[0]["kind"] == ce.CANDIDATE_MEMORY_KIND


def test_the_filed_candidate_asserts_no_search_it_did_not_perform(root):
    pattern = csd.coverage_stall_pattern(root, points=series(PLATEAU_VALUES))
    cid = csd.file_candidates_for_coverage_stall(
        root, points=series(PLATEAU_VALUES), cfg={}
    )[0]["candidate_id"]
    stored = ce.read_candidate(root, cid)
    assert stored["overlap_status"] == "UNKNOWN"
    assert stored["recommendation"] == "UNKNOWN"
    assert stored["exact_gap"] == ""
    assert stored["enhance_insufficient_reason"] == ""
    for slot in ce.L5_SEARCH_SLOTS:
        entry = stored[slot]
        assert entry["search_conclusive"] is False
        assert entry["matches"] == []
        assert "NOT SEARCHED" in entry["search_basis"]
    # The basis names the real next action for that slot's own question,
    # quoted out of the existing RESEARCH_GAP_ACTION_CATALOG rather than
    # reinvented -- the same real text file_repeated_failure_candidate()'s
    # own slots quote.
    assert "ROSTER.md" in stored["existing_agent"]["search_basis"]
    assert "route_memory()" in stored["existing_memory"]["search_basis"]


def test_confidence_is_recomputed_from_its_own_stored_inputs_not_trusted(root):
    cid = csd.file_candidates_for_coverage_stall(
        root, points=series(PLATEAU_VALUES), cfg={}
    )[0]["candidate_id"]
    stored = ce.read_candidate(root, cid)
    recomputed = inference.score_confidence(**stored["confidence"]["inputs"])
    assert stored["confidence"]["level"] == recomputed["level"]
    assert stored["confidence"]["score"] == recomputed["score"]
    ce.assert_confidence_recomputed(stored)  # raises on any mismatch


# ==========================================================================
# 3. The three-outcome filing discipline, mirroring
#    file_repeated_failure_candidate()'s own shape.
# ==========================================================================
def test_refiling_an_unchanged_plateau_does_not_grow_the_audit_trail(root):
    first = csd.file_candidates_for_coverage_stall(
        root, points=series(PLATEAU_VALUES), cfg={}
    )
    assert first[0]["filed"] is True
    cid = first[0]["candidate_id"]

    second = csd.file_candidates_for_coverage_stall(
        root, points=series(PLATEAU_VALUES), cfg={}
    )
    assert len(second) == 1
    assert second[0]["filed"] is False
    assert second[0]["reason"] == "ALREADY_ON_FILE_UNCHANGED"
    assert second[0]["candidate_id"] == cid

    assert len(ce.candidate_audit_records(root, cid)) == 1


def test_the_candidate_id_is_stable_across_repeated_detections(root):
    """Re-detecting the same stall (under the same plateau thresholds) must
    land on the SAME candidate, mirroring capability_evolution's own
    content-derived candidate_id discipline -- never forking a duplicate."""
    a = csd.file_candidates_for_coverage_stall(
        root, points=series(PLATEAU_VALUES), cfg={}
    )[0]["candidate_id"]
    # A slightly different but still-plateaued series (same thresholds).
    b = csd.file_candidates_for_coverage_stall(
        root, points=series([80.0, 80.2, 79.9, 80.1, 80.0]), cfg={}
    )[0]["candidate_id"]
    assert a == b


def test_a_candidate_already_moved_past_DISCOVERED_is_left_alone(root):
    """A human (or a research-architect pass) advancing this candidate must
    never be silently dragged back to DISCOVERED by a later re-detection."""
    pattern = csd.coverage_stall_pattern(root, points=series(PLATEAU_VALUES))
    cid = csd.file_coverage_stall_candidate(root, pattern, cfg={})["candidate_id"]
    stored = ce.read_candidate(root, cid)

    advanced = ce.transition(
        root, stored, "EVIDENCE_GATHERING",
        by="a-human-reviewer", reason="starting the real current-L5 check",
    )
    assert advanced["current_status"] == "EVIDENCE_GATHERING"

    result = csd.file_coverage_stall_candidate(root, pattern, cfg={})
    assert result["filed"] is False
    assert result["reason"] == "ALREADY_BEYOND_DISCOVERED"
    assert result["current_status"] == "EVIDENCE_GATHERING"

    still = ce.read_candidate(root, cid)
    assert still["current_status"] == "EVIDENCE_GATHERING"


def test_genuinely_new_evidence_refiles_without_resetting_status_history(root):
    """A DIFFERENT evidence source (a different evidence-database path) is
    genuinely new information and should be re-persisted -- but the existing
    status_history must be carried forward untouched, since no state actually
    changed."""
    pattern = csd.coverage_stall_pattern(root, points=series(PLATEAU_VALUES))
    first = csd.file_coverage_stall_candidate(root, pattern, cfg={})
    cid = first["candidate_id"]
    stored_before = ce.read_candidate(root, cid)
    history_before = list(stored_before["status_history"])

    # Same candidate identity (same metric/thresholds), but a genuinely
    # different evidence source: a real evidence-database path now backs the
    # observation instead of a caller-supplied series, which changes the
    # cited document in evidence_refs -- genuinely new information.
    other_pattern = dict(pattern)
    other_pattern["sources"] = dict(pattern["sources"])
    other_pattern["sources"]["evidence_db"] = str(
        root / ".dv-harness" / "evidence" / "evidence.duckdb"
    )
    result = csd.file_coverage_stall_candidate(root, other_pattern, cfg={})
    assert result["filed"] is True
    assert result["reason"] == "NEW_EVIDENCE"
    assert result["candidate_id"] == cid

    stored_after = ce.read_candidate(root, cid)
    assert stored_after["status_history"] == history_before


# ==========================================================================
# 4. Every gate above EVIDENCE_GATHERING is untouched.
# ==========================================================================
def test_the_auto_filed_candidate_cannot_reach_human_approval_or_production(root):
    pattern = csd.coverage_stall_pattern(root, points=series(PLATEAU_VALUES))
    cid = csd.file_coverage_stall_candidate(root, pattern, cfg={})["candidate_id"]
    stored = ce.read_candidate(root, cid)

    with pytest.raises(ce.HumanApprovalRequiredError):
        ce.assert_human_approval(root, stored)
    with pytest.raises(ce.ProductionWriteNotAuthorizedError):
        ce.assert_no_production_write_authorized(root, stored)


# ==========================================================================
# 5. The whole chain, once, over the REAL production write path.
# ==========================================================================
def _write_coverage_summary(root, percent):
    p = Path(root) / ".dv-harness" / "coverage" / "summary.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"categories": [
        {"name": "functional", "percent": percent, "bins_total": 1000,
         "bins_hit": int(round(1000 * percent / 100.0))}]}),
        encoding="utf-8")


def _ingest_coverage_day(root, percent, day, *, dashboard, _store, default_db_path):
    watermark = 0
    if default_db_path(root).exists():
        with _store(root) as store:
            rows = store.query("SELECT max(id) FROM coverage_samples")
        watermark = int((rows and rows[0][0]) or 0)
    _write_coverage_summary(root, percent)
    dashboard.append_coverage_history_sample(root, percent)
    with _store(root) as store:
        store.query(f"UPDATE coverage_samples SET ingested_at = TIMESTAMP "
                    f"'{day} 12:00:00' WHERE id > {watermark}")


def test_a_real_evidence_database_plateau_files_a_real_candidate(root):
    """The exact real production write path
    (dashboard.append_coverage_history_sample()), through the exact real
    reader (trend_analysis.daily_rollup(), via loop_convergence's own
    classify_loop_convergence()), files a real candidate -- proving the whole
    chain end to end rather than only against a caller-supplied series."""
    duckdb = pytest.importorskip("duckdb")
    from dv_harness import dashboard
    from dv_harness.evidence_db import EvidenceStore, default_db_path

    def _store(root):
        return EvidenceStore(default_db_path(root))

    for day, percent in [
        ("2026-09-01", 90.0), ("2026-09-02", 90.2), ("2026-09-03", 89.9),
        ("2026-09-04", 90.1), ("2026-09-05", 90.0),
    ]:
        _ingest_coverage_day(root, percent, day, dashboard=dashboard,
                              _store=_store, default_db_path=default_db_path)

    pattern = csd.coverage_stall_pattern(root)
    assert pattern is not None
    assert pattern["verdict"] == lcv.PLATEAU
    assert pattern["sources"]["evidence_db"] == str(default_db_path(root))

    results = csd.file_candidates_for_coverage_stall(root, cfg={})
    assert len(results) == 1
    assert results[0]["filed"] is True
    stored = ce.read_candidate(root, results[0]["candidate_id"])
    assert stored["current_status"] == "DISCOVERED"
    # The real evidence-db path is cited, not a caller-supplied-series
    # placeholder -- a reader must be able to re-derive this from disk.
    assert str(default_db_path(root)) in stored["source_provenance"][0]["document"]
