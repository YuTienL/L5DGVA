"""Tests for dv_harness/coverage_hole_generation_candidate_queue.py -- the SS205
(L5DGVA V9 "Autonomous Hole-Driven Test Generation") DETECTION/RANKING-only join layer
over coverage_analysis.classify_coverage_hole() + coverage_closure_action_utility.
rank_coverage_closure_actions(). Never exercises test-content generation (there is none to
exercise) -- only eligibility partitioning and utility ranking of the eligible subset."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.coverage_analysis import (
    ROOT_CAUSE_INSUFFICIENT_CONSTRAINT,
    ROOT_CAUSE_INSUFFICIENT_SEED_ATTEMPTS,
    ROOT_CAUSE_MISSING_TEST,
    ROOT_CAUSE_UNREACHABLE_STIMULUS,
)
from dv_harness.coverage_hole_generation_candidate_queue import (
    GenerationCandidateQueueError,
    build_generation_candidate_queue,
    format_candidate_queue_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _write_requirements_csv(root: Path, rows) -> None:
    """Mirrors test_coverage_analysis.py's helper of the same name -- the real
    requirements.csv shape change_impact.load_trace_registry()/patterns_for_coverage_id()
    read."""
    d = root / ".dv-harness"
    d.mkdir(parents=True, exist_ok=True)
    header = ["REQ_ID", "SOURCE", "SCOPE", "VPLAN_ID", "SCENARIO_ID", "COMMAND_ID",
              "PATTERN_ID", "CHECKER_ID", "COVERAGE_ID", "RESULT", "STATUS", "EVIDENCE"]
    lines = [",".join(header)]
    for r in rows:
        lines.append(",".join(str(r.get(h, "")) for h in header))
    (d / "requirements.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- build_generation_candidate_queue(): eligibility partition --------------------------

def test_missing_test_hole_is_eligible_no_registry_entry(tmp_path):
    holes = [{"coverage_id": "cov_missing"}]
    queue = build_generation_candidate_queue(tmp_path, holes)
    assert queue.eligible_count == 1
    assert queue.not_eligible == []
    # No utility factors declared -> UNRANKABLE, never a fabricated score.
    assert len(queue.ranking.unrankable) == 1
    assert queue.ranking.unrankable[0].action_id == "cov_missing"


def test_unreachable_stimulus_hole_is_not_eligible(tmp_path):
    _write_requirements_csv(tmp_path, [
        {"REQ_ID": "REQ-1", "PATTERN_ID": "pat_unreach", "COVERAGE_ID": "cov_unreach"},
    ])
    # A companion MISSING_TEST hole so the ineligible one has somewhere to be reported
    # alongside (an all-ineligible set is covered separately by test_no_eligible_hole_raises).
    holes = [{"coverage_id": "cov_missing_companion"},
             {"coverage_id": "cov_unreach", "root_cause_classification": "UNREACHABLE_STIMULUS"}]
    queue = build_generation_candidate_queue(
        tmp_path, holes, seed_counts={"pat_unreach": 25}, history_available=True)
    assert len(queue.not_eligible) == 1
    assert queue.not_eligible[0].coverage_id == "cov_unreach"
    assert queue.not_eligible[0].classification == ROOT_CAUSE_UNREACHABLE_STIMULUS
    assert "design-owner confirmation" in queue.not_eligible[0].reason
    assert queue.not_eligible[0].verdict["requires_human_escalation"] is True


def test_insufficient_seed_attempts_hole_is_not_eligible(tmp_path):
    _write_requirements_csv(tmp_path, [
        {"REQ_ID": "REQ-1", "PATTERN_ID": "pat_seed", "COVERAGE_ID": "cov_seed"},
    ])
    holes = [{"coverage_id": "cov_missing_companion"}, {"coverage_id": "cov_seed"}]
    queue = build_generation_candidate_queue(
        tmp_path, holes, seed_counts={"pat_seed": 2}, history_available=True)
    assert len(queue.not_eligible) == 1
    assert queue.not_eligible[0].classification == ROOT_CAUSE_INSUFFICIENT_SEED_ATTEMPTS
    assert "more seeds" in queue.not_eligible[0].reason


def test_insufficient_constraint_hole_is_eligible(tmp_path):
    _write_requirements_csv(tmp_path, [
        {"REQ_ID": "REQ-1", "PATTERN_ID": "pat_constraint", "COVERAGE_ID": "cov_constraint"},
    ])
    holes = [{
        "coverage_id": "cov_constraint", "root_cause_classification": "INSUFFICIENT_CONSTRAINT",
        "expected_coverage_gain": 10, "requirement_priority": 5, "risk_coverage": 2, "cost": 3,
    }]
    queue = build_generation_candidate_queue(
        tmp_path, holes, seed_counts={"pat_constraint": 25}, history_available=True)
    assert queue.eligible_count == 1
    assert queue.not_eligible == []
    assert len(queue.ranking.ranked) == 1
    assert queue.ranking.ranked[0].action_id == "cov_constraint"
    assert queue.ranking.ranked[0].status == "RANKED"


def test_mixed_set_ranks_eligible_and_names_ineligible(tmp_path):
    _write_requirements_csv(tmp_path, [
        {"REQ_ID": "REQ-1", "PATTERN_ID": "pat_a", "COVERAGE_ID": "cov_a"},
        {"REQ_ID": "REQ-2", "PATTERN_ID": "pat_b", "COVERAGE_ID": "cov_b"},
        {"REQ_ID": "REQ-3", "PATTERN_ID": "pat_c", "COVERAGE_ID": "cov_c"},
    ])
    holes = [
        # cov_missing: no registry entry at all -> MISSING_TEST -> eligible, high utility.
        {"coverage_id": "cov_missing", "expected_coverage_gain": 20,
         "requirement_priority": 10, "risk_coverage": 5, "cost": 1},
        # cov_a: INSUFFICIENT_CONSTRAINT, adequately sampled -> eligible, low utility (high cost).
        {"coverage_id": "cov_a", "root_cause_classification": "INSUFFICIENT_CONSTRAINT",
         "expected_coverage_gain": 5, "requirement_priority": 1, "risk_coverage": 1, "cost": 50},
        # cov_b: UNREACHABLE_STIMULUS -> not eligible.
        {"coverage_id": "cov_b", "root_cause_classification": "UNREACHABLE_STIMULUS"},
        # cov_c: under-sampled -> INSUFFICIENT_SEED_ATTEMPTS -> not eligible.
        {"coverage_id": "cov_c"},
    ]
    queue = build_generation_candidate_queue(
        tmp_path, holes,
        seed_counts={"pat_a": 25, "pat_b": 25, "pat_c": 3},
        history_available=True)

    assert queue.eligible_count == 2
    assert [r.action_id for r in queue.ranking.ranked] == ["cov_missing", "cov_a"]
    assert {h.coverage_id for h in queue.not_eligible} == {"cov_b", "cov_c"}

    report = format_candidate_queue_report(queue)
    assert "cov_missing" in report and "cov_a" in report
    assert "NOT SS205-ELIGIBLE (2)" in report
    assert "cov_b" in report and "cov_c" in report


def test_waived_hole_still_classified_missing_test_and_eligible(tmp_path):
    # classify_coverage_hole() itself does not read `waived` -- only
    # escalate_unreachable_holes() does, which this module deliberately does not call (it
    # never escalates; that stays coverage_analysis.py's own job). Confirms this module does
    # not silently duplicate that unrelated behavior.
    holes = [{"coverage_id": "cov_waived", "waived": True}]
    queue = build_generation_candidate_queue(tmp_path, holes)
    assert queue.eligible_count == 1
    assert queue.not_eligible == []


def test_empty_holes_raises():
    with pytest.raises(GenerationCandidateQueueError):
        build_generation_candidate_queue("ignored", [])
    with pytest.raises(GenerationCandidateQueueError):
        build_generation_candidate_queue("ignored", None)


def test_no_eligible_hole_raises(tmp_path):
    _write_requirements_csv(tmp_path, [
        {"REQ_ID": "REQ-1", "PATTERN_ID": "pat_x", "COVERAGE_ID": "cov_x"},
    ])
    holes = [{"coverage_id": "cov_x", "root_cause_classification": "UNREACHABLE_STIMULUS"}]
    with pytest.raises(GenerationCandidateQueueError):
        build_generation_candidate_queue(
            tmp_path, holes, seed_counts={"pat_x": 25}, history_available=True)


def test_non_dict_hole_entries_are_skipped(tmp_path):
    holes = [{"coverage_id": "cov_ok"}, "not_a_dict", 42, None]
    queue = build_generation_candidate_queue(tmp_path, holes)
    assert queue.eligible_count == 1


def test_never_writes_generated_test_ids_or_closure_owner(tmp_path):
    """This module's whole point is that it never authors test content or the gate fields
    coverage_hole_to_test_generation_gate.py verifies -- confirm the ranking/queue records
    carry no such field anywhere in their serialized form."""
    holes = [{"coverage_id": "cov_check", "expected_coverage_gain": 1,
              "requirement_priority": 1, "risk_coverage": 1, "cost": 1}]
    queue = build_generation_candidate_queue(tmp_path, holes)
    dumped = json.dumps(queue.to_dict())
    assert "generated_test_ids" not in dumped
    assert "closure_owner" not in dumped
    assert "trace_to_vplan" not in dumped


# ---- CLI -------------------------------------------------------------------------------

def test_cli_json_and_exit_code(tmp_path):
    holes_file = tmp_path / "holes.json"
    holes_file.write_text(json.dumps({"coverage_holes": [
        {"coverage_id": "cov_cli", "expected_coverage_gain": 1,
         "requirement_priority": 1, "risk_coverage": 1, "cost": 1},
    ]}), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.coverage_hole_generation_candidate_queue",
         "--holes-file", str(holes_file), "--root", str(tmp_path), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["eligible_count"] == 1
    assert out["ranking"]["ranked"][0]["action_id"] == "cov_cli"


def test_cli_unrankable_exit_code(tmp_path):
    holes_file = tmp_path / "holes.json"
    holes_file.write_text(json.dumps([{"coverage_id": "cov_bare"}]), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.coverage_hole_generation_candidate_queue",
         "--holes-file", str(holes_file), "--root", str(tmp_path)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 1
    assert "NOT SS205-ELIGIBLE" in r.stdout
