"""Tests for dv_harness/session_question_sequencer.py."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import intake_question_priority as iqp
from dv_harness import session_question_sequencer as sqs


def _sf(qid, blocking_value=1, downstream_impact=1, expected_confidence_gain=1, user_effort=1,
        unlocks=None):
    """Build a minimal scoreable question dict, optionally declaring unlocks."""
    q = {"question_id": qid, "blocking_value": blocking_value,
         "downstream_impact": downstream_impact,
         "expected_confidence_gain": expected_confidence_gain, "user_effort": user_effort}
    if unlocks is not None:
        q["unlocks"] = unlocks
    return q


# ===========================================================================
# ID assignment consistency (must match intake_question_priority._question_id)
# ===========================================================================

def test_question_id_matches_field_priority_and_positional_fallback():
    assert sqs._question_id({"question_id": "x"}, 5) == "x"
    assert sqs._question_id({"id": "y"}, 5) == "y"
    assert sqs._question_id({"q_id": "z"}, 5) == "z"
    assert sqs._question_id({}, 3) == "q3"


def test_sequenced_ids_correlate_with_rank_questions_own_ids():
    # Same list, same order, fed to both rank_questions() and sequence_questions()
    # without an id field -- both must assign identical positional ids.
    questions = [_sf(None), _sf(None)]
    for q in questions:
        del q["question_id"]
    ranking = iqp.rank_questions(questions)
    seq = sqs.sequence_questions(questions)
    ranked_ids = {r["question_id"] for r in ranking["ranked"]}
    seq_ids = {e["question_id"] for e in seq["sequence"]}
    assert ranked_ids == seq_ids == {"q0", "q1"}


# ===========================================================================
# build_unlock_graph
# ===========================================================================

def test_build_unlock_graph_basic_edges():
    questions = [
        _sf("a", unlocks=["b", "c"]),
        _sf("b"),
        _sf("c"),
    ]
    graph, findings = sqs.build_unlock_graph(questions)
    assert graph["a"] == ["b", "c"]
    assert graph["b"] == []
    assert graph["c"] == []
    assert findings == []


def test_build_unlock_graph_self_unlock_is_ignored_and_reported():
    questions = [_sf("a", unlocks=["a"])]
    graph, findings = sqs.build_unlock_graph(questions)
    assert graph["a"] == []
    assert len(findings) == 1
    assert findings[0]["kind"] == sqs.FINDING_SELF_UNLOCK_IGNORED
    assert findings[0]["question_id"] == "a"


def test_build_unlock_graph_unknown_target_never_fabricates_an_edge():
    # Negative control: a declared unlock target absent from the batch must
    # never be silently counted toward downstream reach -- it must be
    # reported and excluded from the graph.
    questions = [_sf("a", unlocks=["nonexistent"])]
    graph, findings = sqs.build_unlock_graph(questions)
    assert graph["a"] == []
    assert len(findings) == 1
    assert findings[0]["kind"] == sqs.FINDING_UNKNOWN_UNLOCK_TARGET
    assert "nonexistent" in findings[0]["detail"]


def test_build_unlock_graph_duplicate_declared_targets_are_deduplicated():
    questions = [_sf("a", unlocks=["b", "b", "b"]), _sf("b")]
    graph, findings = sqs.build_unlock_graph(questions)
    assert graph["a"] == ["b"]
    assert findings == []


def test_build_unlock_graph_bare_string_unlock_value_is_normalized_to_a_list():
    questions = [_sf("a", unlocks="b"), _sf("b")]
    graph, _ = sqs.build_unlock_graph(questions)
    assert graph["a"] == ["b"]


def test_build_unlock_graph_alias_field_names_are_tried_in_order():
    q_downstream = _sf("a")
    q_downstream["downstream_unlocks"] = ["b"]
    q_expected = _sf("c")
    q_expected["expected_unlocks"] = ["d"]
    questions = [q_downstream, _sf("b"), q_expected, _sf("d")]
    graph, findings = sqs.build_unlock_graph(questions)
    assert graph["a"] == ["b"]
    assert graph["c"] == ["d"]
    assert findings == []


def test_build_unlock_graph_no_declared_unlocks_is_never_guessed():
    questions = [_sf("a"), _sf("b")]
    graph, findings = sqs.build_unlock_graph(questions)
    assert graph["a"] == [] and graph["b"] == []
    assert findings == []


# ===========================================================================
# compute_downstream_reach
# ===========================================================================

def test_compute_downstream_reach_linear_chain():
    graph = {"a": ["b"], "b": ["c"], "c": []}
    reach = sqs.compute_downstream_reach(graph)
    assert reach["a"] == frozenset({"b", "c"})
    assert reach["b"] == frozenset({"c"})
    assert reach["c"] == frozenset()


def test_compute_downstream_reach_diamond_union():
    graph = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
    reach = sqs.compute_downstream_reach(graph)
    assert reach["a"] == frozenset({"b", "c", "d"})


def test_compute_downstream_reach_cycle_is_safe_and_correct():
    # A -> B -> C -> A: must not loop forever, and each node's own reach
    # must be exactly the OTHER two nodes -- never itself, never inflated.
    graph = {"a": ["b"], "b": ["c"], "c": ["a"]}
    reach = sqs.compute_downstream_reach(graph)
    assert reach["a"] == frozenset({"b", "c"})
    assert reach["b"] == frozenset({"a", "c"})
    assert reach["c"] == frozenset({"a", "b"})


def test_compute_downstream_reach_no_edges_is_empty():
    graph = {"a": [], "b": []}
    reach = sqs.compute_downstream_reach(graph)
    assert reach["a"] == frozenset() and reach["b"] == frozenset()


# ===========================================================================
# sequence_questions -- the core session-level ordering
# ===========================================================================

def test_sequence_questions_orders_by_downstream_reach_first():
    # "unlocker" has a LOWER per-question score than "loner" but unlocks two
    # others -- it must still be sequenced FIRST, per the task's own
    # "unblock the maximum downstream work first" strategy.
    questions = [
        _sf("unlocker", blocking_value=1, downstream_impact=1, expected_confidence_gain=1,
            user_effort=1, unlocks=["dep1", "dep2"]),
        _sf("loner", blocking_value=9, downstream_impact=9, expected_confidence_gain=9,
            user_effort=1),
        _sf("dep1"),
        _sf("dep2"),
    ]
    result = sqs.sequence_questions(questions)
    assert result["first_question_id"] == "unlocker"
    ids_in_order = [e["question_id"] for e in result["sequence"]]
    assert ids_in_order[0] == "unlocker"


def test_sequence_questions_ties_broken_by_reused_score_descending():
    questions = [
        _sf("low", blocking_value=1, downstream_impact=1, expected_confidence_gain=1,
            user_effort=10),
        _sf("high", blocking_value=5, downstream_impact=5, expected_confidence_gain=5,
            user_effort=1),
    ]
    result = sqs.sequence_questions(questions)
    ids_in_order = [e["question_id"] for e in result["sequence"]]
    assert ids_in_order == ["high", "low"]  # both reach 0, high score wins


def test_sequence_questions_final_tie_break_is_question_id():
    questions = [_sf("z"), _sf("a")]
    result = sqs.sequence_questions(questions)
    assert [e["question_id"] for e in result["sequence"]] == ["a", "z"]


def test_sequence_questions_reuses_scores_never_recomputes_a_different_number():
    questions = [_sf("k1", blocking_value=2, downstream_impact=3, expected_confidence_gain=4,
                      user_effort=5)]
    direct_rank = iqp.rank_questions(questions)
    seq = sqs.sequence_questions(questions)
    assert seq["sequence"][0]["base_score"] == direct_rank["ranked"][0]["score"]


def test_sequence_questions_unrankable_question_is_never_dropped_and_never_fabricates_a_score():
    # Negative control: a question rank_questions() itself could not score
    # (user_effort == 0) must stay in the sequence with an honest
    # UNVERIFIABLE status, never a guessed numeric score.
    questions = [
        _sf("scored", blocking_value=1, downstream_impact=1, expected_confidence_gain=1,
            user_effort=1),
        _sf("broken", blocking_value=1, downstream_impact=1, expected_confidence_gain=1,
            user_effort=0),
    ]
    result = sqs.sequence_questions(questions)
    ids = [e["question_id"] for e in result["sequence"]]
    assert set(ids) == {"scored", "broken"}
    broken_entry = next(e for e in result["sequence"] if e["question_id"] == "broken")
    assert broken_entry["base_score"] is None
    assert broken_entry["base_score_status"] == iqp.SCORE_STATUS_UNVERIFIABLE
    assert "user_effort" in broken_entry["base_score_reason"]
    # Equal reach count (0 for both) -- the honestly-scored question must
    # come first; the unrankable one is never treated as having zero value.
    assert ids == ["scored", "broken"]


def test_sequence_questions_unlock_graph_findings_are_carried_through():
    questions = [_sf("a", unlocks=["ghost"])]
    result = sqs.sequence_questions(questions)
    assert len(result["unlock_graph_findings"]) == 1
    assert result["unlock_graph_findings"][0]["kind"] == sqs.FINDING_UNKNOWN_UNLOCK_TARGET


def test_sequence_questions_empty_input():
    result = sqs.sequence_questions([])
    assert result["sequence"] == []
    assert result["total_questions"] == 0
    assert result["first_question_id"] is None


def test_sequence_questions_downstream_unlocks_reported_sorted_and_json_serializable():
    questions = [_sf("a", unlocks=["c", "b"]), _sf("b"), _sf("c")]
    result = sqs.sequence_questions(questions)
    a_entry = next(e for e in result["sequence"] if e["question_id"] == "a")
    assert a_entry["downstream_unlocks"] == ["b", "c"]
    json.dumps(result)  # must not raise -- no frozenset/set leaked into output


def test_sequence_questions_accepts_a_caller_supplied_ranking_and_never_recomputes():
    questions = [_sf("k1", blocking_value=2, downstream_impact=3, expected_confidence_gain=4,
                      user_effort=5)]
    ranking = iqp.rank_questions(questions)
    # Corrupt the supplied ranking's score to prove sequence_questions() uses
    # exactly what it was handed rather than silently recomputing its own.
    ranking["ranked"][0]["score"] = 999.0
    result = sqs.sequence_questions(questions, ranking=ranking)
    assert result["sequence"][0]["base_score"] == 999.0


# ===========================================================================
# sequence_session_queue -- full pipeline reuse (gate -> rank -> batch -> sequence)
# ===========================================================================

def test_sequence_session_queue_excludes_do_not_ask_from_sequencing():
    questions = [
        {"question_id": "skip", "confidence": "HIGH", "criticality": "MINOR",
         "blocking_value": 9, "downstream_impact": 9, "expected_confidence_gain": 9,
         "user_effort": 1},
        {"question_id": "keep", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 1, "downstream_impact": 1, "expected_confidence_gain": 1,
         "user_effort": 1},
    ]
    report = sqs.sequence_session_queue(questions)
    assert report["gating"]["do_not_ask"] == ["skip"]
    seq_ids = [e["question_id"] for e in report["sequencing"]["sequence"]]
    assert seq_ids == ["keep"]


def test_sequence_session_queue_reuses_analyze_pending_questions_ranking_exactly():
    questions = [
        {"question_id": "keep", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 3, "downstream_impact": 2, "expected_confidence_gain": 4,
         "user_effort": 1},
    ]
    report = sqs.sequence_session_queue(questions)
    direct = iqp.analyze_pending_questions(questions)
    assert report["ranking"] == direct["ranking"]
    assert report["gating"] == direct["gating"]
    assert report["batching"] == direct["batching"]


def test_sequence_session_queue_unlocking_a_do_not_ask_question_is_never_counted():
    # A question that would "unlock" a DO_NOT_ASK question (already excluded
    # by gating) must not fabricate downstream reach against a question that
    # is not even in the to-ask sequencing set.
    questions = [
        {"question_id": "a", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 1, "downstream_impact": 1, "expected_confidence_gain": 1,
         "user_effort": 1, "unlocks": ["skip"]},
        {"question_id": "skip", "confidence": "HIGH", "criticality": "MINOR",
         "blocking_value": 1, "downstream_impact": 1, "expected_confidence_gain": 1,
         "user_effort": 1},
    ]
    report = sqs.sequence_session_queue(questions)
    a_entry = report["sequencing"]["sequence"][0]
    assert a_entry["question_id"] == "a"
    assert a_entry["downstream_reach_count"] == 0
    findings = report["sequencing"]["unlock_graph_findings"]
    assert len(findings) == 1
    assert findings[0]["kind"] == sqs.FINDING_UNKNOWN_UNLOCK_TARGET


def test_sequence_session_queue_empty_input():
    report = sqs.sequence_session_queue([])
    assert report["sequencing"]["sequence"] == []
    assert report["gating"]["total"] == 0


def test_sequence_session_queue_multi_question_unlocker_wins_the_session():
    questions = [
        {"question_id": "unlocker", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 1, "downstream_impact": 1, "expected_confidence_gain": 1,
         "user_effort": 1, "unlocks": ["dep1", "dep2"]},
        {"question_id": "loner", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 9, "downstream_impact": 9, "expected_confidence_gain": 9,
         "user_effort": 1},
        {"question_id": "dep1", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 1, "downstream_impact": 1, "expected_confidence_gain": 1,
         "user_effort": 1},
        {"question_id": "dep2", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 1, "downstream_impact": 1, "expected_confidence_gain": 1,
         "user_effort": 1},
    ]
    report = sqs.sequence_session_queue(questions)
    assert report["sequencing"]["first_question_id"] == "unlocker"


# ===========================================================================
# render_report_text
# ===========================================================================

def test_render_report_text_produces_readable_summary():
    report = sqs.sequence_session_queue([
        {"question_id": "k1", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 1, "downstream_impact": 1, "expected_confidence_gain": 1,
         "user_effort": 1},
    ])
    text = sqs.render_report_text(report)
    assert "SESSION-LEVEL QUESTION-ORDER STRATEGY" in text
    assert "k1" in text


def test_render_report_text_shows_unrankable_reason_never_a_number():
    report = sqs.sequence_session_queue([
        {"question_id": "k1", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 1, "downstream_impact": 1, "expected_confidence_gain": 1,
         "user_effort": 0},
    ])
    text = sqs.render_report_text(report)
    assert "UNVERIFIABLE" in text


def test_render_report_text_shows_unlock_graph_findings():
    report = sqs.sequence_session_queue([
        {"question_id": "k1", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 1, "downstream_impact": 1, "expected_confidence_gain": 1,
         "user_effort": 1, "unlocks": ["ghost"]},
    ])
    text = sqs.render_report_text(report)
    assert sqs.FINDING_UNKNOWN_UNLOCK_TARGET in text


# ===========================================================================
# CLI front door
# ===========================================================================

def test_cli_runs_end_to_end_and_reports_exit_0_when_clean(tmp_path: Path):
    payload = [
        {"question_id": "k1", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 3, "downstream_impact": 2, "expected_confidence_gain": 4,
         "user_effort": 1},
    ]
    pf = tmp_path / "pending.json"
    pf.write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.session_question_sequencer",
         "--pending-questions", str(pf), "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["sequencing"]["first_question_id"] == "k1"


def test_cli_reports_exit_1_when_a_question_is_unrankable(tmp_path: Path):
    payload = [
        {"question_id": "k1", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 1, "downstream_impact": 1, "expected_confidence_gain": 1,
         "user_effort": 0},
    ]
    pf = tmp_path / "pending.json"
    pf.write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.session_question_sequencer",
         "--pending-questions", str(pf)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 1, proc.stderr


def test_cli_reports_exit_1_on_unlock_graph_finding(tmp_path: Path):
    payload = [
        {"question_id": "k1", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 1, "downstream_impact": 1, "expected_confidence_gain": 1,
         "user_effort": 1, "unlocks": ["ghost"]},
    ]
    pf = tmp_path / "pending.json"
    pf.write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.session_question_sequencer",
         "--pending-questions", str(pf)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 1, proc.stderr


def test_cli_reports_exit_2_on_malformed_input(tmp_path: Path):
    pf = tmp_path / "pending.json"
    pf.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.session_question_sequencer",
         "--pending-questions", str(pf)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 2, proc.stderr
