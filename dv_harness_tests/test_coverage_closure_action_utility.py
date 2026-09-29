"""Real tests for dv_harness/coverage_closure_action_utility.py.

Core positive path: a clean set of candidates ranks correctly by the utility formula. Negative
controls prove the central rule this module exists to enforce -- a cheap-but-wrong (or
cheap-but-high-risk) action is EXCLUDED entirely, never merely penalized, and the gate runs before
cost (or any other factor) ever influences ranking -- plus the honest-absence/invalid-declaration
handling every factor requires.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.coverage_closure_action_utility import (
    CoverageClosureActionUtilityError,
    CandidateActionUtility,
    UtilityFactorResult,
    rank_coverage_closure_actions,
    format_ranking_report,
    declared_utility_factor,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _clean(action_id, gain=10.0, priority=2.0, risk_coverage=3.0, cost=5.0, **extra):
    d = {
        "action_id": action_id,
        "expected_coverage_gain": gain,
        "requirement_priority": priority,
        "risk_coverage": risk_coverage,
        "cost": cost,
    }
    d.update(extra)
    return d


# --------------------------------------------------------------------------------------------
# Core positive path
# --------------------------------------------------------------------------------------------

def test_core_positive_path_ranks_by_utility_descending():
    candidates = [
        _clean("ACT-LOW", gain=2.0, priority=1.0, risk_coverage=1.0, cost=10.0),   # utility=0.2
        _clean("ACT-HIGH", gain=10.0, priority=3.0, risk_coverage=2.0, cost=2.0),  # utility=30.0
        _clean("ACT-MID", gain=5.0, priority=2.0, risk_coverage=2.0, cost=4.0),    # utility=5.0
    ]
    ranking = rank_coverage_closure_actions(candidates)

    assert [r.action_id for r in ranking.ranked] == ["ACT-HIGH", "ACT-MID", "ACT-LOW"]
    assert ranking.ranked[0].rank == 1
    assert ranking.ranked[0].utility_score == pytest.approx(30.0)
    assert ranking.ranked[1].utility_score == pytest.approx(5.0)
    assert ranking.ranked[2].utility_score == pytest.approx(0.2)
    assert ranking.excluded == []
    assert ranking.unrankable == []

    # every factor is DECLARED, never MEASURED
    for r in ranking.ranked:
        for name in ("expected_coverage_gain", "requirement_priority", "risk_coverage", "cost"):
            f = r.factors[name]
            assert f.status == "DECLARED"
            assert f.source == "caller declaration (not self-measured)"


def test_default_gate_status_is_unverified_and_not_excluded():
    candidates = [_clean("ACT-1")]  # no correctness_status/risk_status declared at all
    ranking = rank_coverage_closure_actions(candidates)
    assert len(ranking.ranked) == 1
    r = ranking.ranked[0]
    assert r.correctness_status == "UNVERIFIED"
    assert r.risk_status == "UNVERIFIED"
    assert r.status == "RANKED"


def test_explicitly_confirmed_correct_and_acceptable_risk_still_ranks():
    candidates = [_clean("ACT-1", correctness_status="CONFIRMED_CORRECT",
                          risk_status="ACCEPTABLE_RISK")]
    ranking = rank_coverage_closure_actions(candidates)
    assert ranking.ranked[0].status == "RANKED"
    assert ranking.ranked[0].correctness_status == "CONFIRMED_CORRECT"
    assert ranking.ranked[0].risk_status == "ACCEPTABLE_RISK"


# --------------------------------------------------------------------------------------------
# THE headline rule: a cheap-but-wrong (or cheap-but-high-risk) action never outranks a correct
# one, regardless of cost -- because it is EXCLUDED entirely, not merely penalized.
# --------------------------------------------------------------------------------------------

def test_flagged_incorrect_action_never_outranks_a_correct_one_even_with_huge_utility():
    # If gating did NOT run before utility computation, this "wrong" action's utility would be
    # enormous (huge gain/priority/risk_coverage, tiny cost) and would rank #1.
    candidates = [
        _clean("ACT-WRONG-BUT-CHEAP", gain=1000.0, priority=100.0, risk_coverage=100.0,
               cost=0.001, correctness_status="FLAGGED_INCORRECT"),
        _clean("ACT-CORRECT-MODEST", gain=5.0, priority=1.0, risk_coverage=1.0, cost=5.0),
    ]
    ranking = rank_coverage_closure_actions(candidates)

    assert [r.action_id for r in ranking.ranked] == ["ACT-CORRECT-MODEST"]
    assert ranking.ranked[0].rank == 1
    excluded_ids = {r.action_id for r in ranking.excluded}
    assert excluded_ids == {"ACT-WRONG-BUT-CHEAP"}
    wrong = ranking.excluded[0]
    assert wrong.utility_score is None  # never scored, not merely penalized
    assert wrong.rank is None
    assert any("FLAGGED_INCORRECT" in reason for reason in wrong.exclusion_reasons)
    # its declared factors are still reported for audit -- excluded is not "hidden"
    assert wrong.factors["cost"].status == "DECLARED"
    assert wrong.factors["cost"].value == pytest.approx(0.001)


def test_high_risk_action_never_outranks_a_correct_one_even_with_huge_utility():
    candidates = [
        _clean("ACT-RISKY-BUT-CHEAP", gain=1000.0, priority=100.0, risk_coverage=100.0,
               cost=0.001, risk_status="HIGH_RISK"),
        _clean("ACT-SAFE-MODEST", gain=5.0, priority=1.0, risk_coverage=1.0, cost=5.0),
    ]
    ranking = rank_coverage_closure_actions(candidates)

    assert [r.action_id for r in ranking.ranked] == ["ACT-SAFE-MODEST"]
    excluded_ids = {r.action_id for r in ranking.excluded}
    assert excluded_ids == {"ACT-RISKY-BUT-CHEAP"}
    risky = ranking.excluded[0]
    assert risky.utility_score is None
    assert any("HIGH_RISK" in reason for reason in risky.exclusion_reasons)


def test_both_flags_together_reports_both_exclusion_reasons():
    candidates = [_clean("ACT-BOTH", correctness_status="FLAGGED_INCORRECT",
                          risk_status="HIGH_RISK")]
    ranking = rank_coverage_closure_actions(candidates)
    assert ranking.ranked == []
    assert len(ranking.excluded) == 1
    reasons = " ".join(ranking.excluded[0].exclusion_reasons)
    assert "FLAGGED_INCORRECT" in reasons
    assert "HIGH_RISK" in reasons


# --------------------------------------------------------------------------------------------
# Cost is ONLY a tie-breaker among candidates that already cleared the gate and already have a
# real utility score -- never a primary ranking signal, never consulted before the gate.
# --------------------------------------------------------------------------------------------

def test_cost_breaks_a_genuine_utility_tie_only_after_the_gate():
    # Both have identical utility (gain*priority*risk_coverage/cost == 5.0); cheaper cost wins.
    candidates = [
        _clean("ACT-EXPENSIVE-TIE", gain=10.0, priority=1.0, risk_coverage=1.0, cost=2.0),  # 5.0
        _clean("ACT-CHEAP-TIE", gain=5.0, priority=1.0, risk_coverage=1.0, cost=1.0),        # 5.0
    ]
    ranking = rank_coverage_closure_actions(candidates)
    assert ranking.ranked[0].utility_score == pytest.approx(ranking.ranked[1].utility_score)
    assert [r.action_id for r in ranking.ranked] == ["ACT-CHEAP-TIE", "ACT-EXPENSIVE-TIE"]


def test_action_id_is_the_final_deterministic_tiebreak():
    candidates = [
        _clean("ACT-Z", gain=1.0, priority=1.0, risk_coverage=1.0, cost=1.0),
        _clean("ACT-A", gain=1.0, priority=1.0, risk_coverage=1.0, cost=1.0),
    ]
    ranking = rank_coverage_closure_actions(candidates)
    assert [r.action_id for r in ranking.ranked] == ["ACT-A", "ACT-Z"]


# --------------------------------------------------------------------------------------------
# Negative controls: missing / invalid utility factors -> NOT_AVAILABLE / UNRANKABLE, never a
# fabricated default.
# --------------------------------------------------------------------------------------------

def test_missing_factor_reports_unrankable_never_a_guessed_default():
    candidates = [{"action_id": "ACT-MISSING-COST", "expected_coverage_gain": 5.0,
                   "requirement_priority": 2.0, "risk_coverage": 1.0}]  # no `cost`
    ranking = rank_coverage_closure_actions(candidates)
    assert ranking.ranked == []
    assert len(ranking.unrankable) == 1
    r = ranking.unrankable[0]
    assert r.utility_score is None
    assert r.rank is None
    assert "cost" in r.missing_factors
    assert r.factors["cost"].status == "NOT_AVAILABLE"


@pytest.mark.parametrize("bad_value", [0, -5.0, True, "not-a-number", float("nan"), float("inf")])
def test_invalid_factor_value_reports_not_available(bad_value):
    candidates = [{"action_id": "ACT-BAD", "expected_coverage_gain": bad_value,
                   "requirement_priority": 2.0, "risk_coverage": 1.0, "cost": 5.0}]
    ranking = rank_coverage_closure_actions(candidates)
    assert ranking.ranked == []
    assert len(ranking.unrankable) == 1
    assert "expected_coverage_gain" in ranking.unrankable[0].missing_factors


def test_invalid_correctness_status_string_reports_unrankable_not_a_silent_default():
    candidates = [_clean("ACT-BAD-STATUS", correctness_status="MAYBE_FINE_I_GUESS")]
    ranking = rank_coverage_closure_actions(candidates)
    assert ranking.ranked == []
    assert ranking.excluded == []
    assert len(ranking.unrankable) == 1
    assert any("correctness_status" in m for m in ranking.unrankable[0].missing_factors)


def test_invalid_risk_status_string_reports_unrankable_not_a_silent_default():
    candidates = [_clean("ACT-BAD-RISK", risk_status="SORT_OF_RISKY")]
    ranking = rank_coverage_closure_actions(candidates)
    assert ranking.ranked == []
    assert len(ranking.unrankable) == 1
    assert any("risk_status" in m for m in ranking.unrankable[0].missing_factors)


def test_empty_candidate_list_raises_rather_than_returning_a_vacuous_ranking():
    with pytest.raises(CoverageClosureActionUtilityError):
        rank_coverage_closure_actions([])
    with pytest.raises(CoverageClosureActionUtilityError):
        rank_coverage_closure_actions(None)


def test_action_id_falls_back_to_id_then_to_a_positional_placeholder():
    candidates = [{"id": "LEGACY-ID", "expected_coverage_gain": 1.0, "requirement_priority": 1.0,
                   "risk_coverage": 1.0, "cost": 1.0}, {"expected_coverage_gain": 1.0}]
    ranking = rank_coverage_closure_actions(candidates)
    ids = {r.action_id for r in ranking.ranked} | {r.action_id for r in ranking.unrankable}
    assert "LEGACY-ID" in ids
    assert any(i.startswith("UNKNOWN-") for i in ids)


def test_duck_typed_attribute_object_is_accepted_not_only_dicts():
    class Candidate:
        action_id = "ATTR-OBJ"
        expected_coverage_gain = 4.0
        requirement_priority = 2.0
        risk_coverage = 1.0
        cost = 2.0

    ranking = rank_coverage_closure_actions([Candidate()])
    assert ranking.ranked[0].action_id == "ATTR-OBJ"
    assert ranking.ranked[0].utility_score == pytest.approx(4.0)


def test_declared_utility_factor_carries_optional_rationale():
    candidate = {"expected_coverage_gain": 7.0, "expected_coverage_gain_rationale": "3 new bins"}
    result = declared_utility_factor(candidate, "expected_coverage_gain")
    assert result.status == "DECLARED"
    assert "3 new bins" in result.evidence


def test_format_ranking_report_mentions_all_three_buckets():
    candidates = [
        _clean("ACT-OK"),
        _clean("ACT-WRONG", correctness_status="FLAGGED_INCORRECT"),
        {"action_id": "ACT-INCOMPLETE", "expected_coverage_gain": 1.0},
    ]
    ranking = rank_coverage_closure_actions(candidates)
    text = format_ranking_report(ranking)
    assert "ACT-OK" in text
    assert "ACT-WRONG" in text
    assert "ACT-INCOMPLETE" in text
    assert "RANKED" in text
    assert "EXCLUDED" in text
    assert "UNRANKABLE" in text


# --------------------------------------------------------------------------------------------
# Real subprocess CLI run
# --------------------------------------------------------------------------------------------

def test_cli_runs_end_to_end_and_reports_correct_exit_code(tmp_path):
    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text(json.dumps([
        _clean("ACT-A", gain=10.0, priority=2.0, risk_coverage=1.0, cost=1.0),
        _clean("ACT-B", correctness_status="FLAGGED_INCORRECT"),
    ]), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.coverage_closure_action_utility",
         "--candidates-file", str(candidates_file), "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert [r["action_id"] for r in payload["ranked"]] == ["ACT-A"]
    assert [r["action_id"] for r in payload["excluded"]] == ["ACT-B"]


def test_cli_exits_1_when_something_is_unrankable(tmp_path):
    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text(json.dumps([{"action_id": "ACT-INCOMPLETE"}]), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.coverage_closure_action_utility",
         "--candidates-file", str(candidates_file)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)

    assert proc.returncode == 1, proc.stderr
    assert "UNRANKABLE" in proc.stdout
