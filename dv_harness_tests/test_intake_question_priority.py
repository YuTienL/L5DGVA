"""Tests for dv_harness/intake_question_priority.py."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import intake_question_priority as iqp


# ===========================================================================
# (a) Confidence x Criticality gating table
# ===========================================================================

def test_gating_table_has_all_16_cells_and_only_two_axis_values_gate_do_not_ask():
    assert len(iqp.GATING_TABLE) == 16
    do_not_ask_cells = [k for k, (d, _r) in iqp.GATING_TABLE.items() if d == iqp.DECISION_DO_NOT_ASK]
    assert set(do_not_ask_cells) == {("HIGH", "MINOR"), ("HIGH", "MAJOR"), ("MEDIUM", "MINOR")}


def test_worked_example_high_confidence_non_critical_do_not_ask():
    result = iqp.gate_question("HIGH", "MINOR")
    assert result["decision"] == iqp.DECISION_DO_NOT_ASK
    result2 = iqp.gate_question("high", "major")  # case-insensitive
    assert result2["decision"] == iqp.DECISION_DO_NOT_ASK


def test_worked_example_medium_confidence_critical_ask():
    result = iqp.gate_question("MEDIUM", "BLOCKER")
    assert result["decision"] == iqp.DECISION_ASK


def test_blocker_criticality_always_asks_regardless_of_confidence():
    for confidence in iqp.CONFIDENCE_LEVELS:
        result = iqp.gate_question(confidence, "BLOCKER")
        assert result["decision"] == iqp.DECISION_ASK, confidence


def test_unknown_criticality_always_asks_never_read_as_safe():
    for confidence in iqp.CONFIDENCE_LEVELS:
        result = iqp.gate_question(confidence, "UNKNOWN")
        assert result["decision"] == iqp.DECISION_ASK, confidence


def test_unknown_confidence_always_asks_never_read_as_sure():
    for criticality in iqp.CRITICALITY_LEVELS:
        result = iqp.gate_question("UNKNOWN", criticality)
        assert result["decision"] == iqp.DECISION_ASK, criticality


def test_unrecognized_raw_value_normalizes_to_unknown_and_is_flagged_not_a_guess():
    result = iqp.gate_question("super-sure", "MINOR")
    assert result["confidence"] == "UNKNOWN"
    assert result["confidence_recognized"] is False
    # UNKNOWN x MINOR -> ASK per the table (never silently assumed HIGH).
    assert result["decision"] == iqp.DECISION_ASK


def test_missing_values_normalize_to_unknown():
    result = iqp.gate_question(None, None)
    assert result["confidence"] == "UNKNOWN" and result["criticality"] == "UNKNOWN"
    assert result["decision"] == iqp.DECISION_ASK


def test_gate_pending_questions_splits_to_ask_and_do_not_ask():
    questions = [
        {"question_id": "q-a", "confidence": "HIGH", "criticality": "MINOR"},
        {"question_id": "q-b", "confidence": "LOW", "criticality": "BLOCKER"},
        {"question_id": "q-c", "confidence": "MEDIUM", "criticality": "MINOR"},
    ]
    result = iqp.gate_pending_questions(questions)
    assert result["to_ask"] == ["q-b"]
    assert set(result["do_not_ask"]) == {"q-a", "q-c"}
    assert result["total"] == 3


def test_gate_pending_questions_assigns_positional_id_when_missing():
    result = iqp.gate_pending_questions([{"confidence": "LOW", "criticality": "BLOCKER"}])
    assert result["gated"][0]["question_id"] == "q0"


# ===========================================================================
# (b) Next-best-question ranking
# ===========================================================================

def test_score_question_computes_the_exact_formula():
    factors = {"blocking_value": 2.0, "downstream_impact": 3.0,
               "expected_confidence_gain": 4.0, "user_effort": 5.0}
    result = iqp.score_question(factors)
    assert result["status"] == iqp.SCORE_STATUS_SCORED
    assert result["score"] == pytest.approx(2.0 * 3.0 * 4.0 / 5.0)


def test_rank_questions_orders_by_score_descending():
    questions = [
        {"question_id": "low", "blocking_value": 1, "downstream_impact": 1,
         "expected_confidence_gain": 1, "user_effort": 10},
        {"question_id": "high", "blocking_value": 5, "downstream_impact": 5,
         "expected_confidence_gain": 5, "user_effort": 1},
        {"question_id": "mid", "blocking_value": 2, "downstream_impact": 2,
         "expected_confidence_gain": 2, "user_effort": 2},
    ]
    result = iqp.rank_questions(questions)
    ids = [r["question_id"] for r in result["ranked"]]
    assert ids == ["high", "mid", "low"]
    assert result["next_best_question_id"] == "high"
    assert result["ranked"][0]["rank"] == 1
    assert not result["unrankable"]


def test_rank_questions_tie_break_is_deterministic_by_question_id():
    questions = [
        {"question_id": "z", "blocking_value": 1, "downstream_impact": 1,
         "expected_confidence_gain": 1, "user_effort": 1},
        {"question_id": "a", "blocking_value": 1, "downstream_impact": 1,
         "expected_confidence_gain": 1, "user_effort": 1},
    ]
    result = iqp.rank_questions(questions)
    assert [r["question_id"] for r in result["ranked"]] == ["a", "z"]


# --- negative controls: ambiguous/unverifiable inputs must never guess a score ---

def test_missing_factor_is_unverifiable_not_defaulted():
    result = iqp.score_question({"blocking_value": 1, "downstream_impact": 1,
                                  "expected_confidence_gain": 1})
    assert result["status"] == iqp.SCORE_STATUS_UNVERIFIABLE
    assert result["score"] is None
    assert "user_effort" in result["reason"]


def test_non_numeric_factor_is_unverifiable():
    result = iqp.score_question({"blocking_value": "high", "downstream_impact": 1,
                                  "expected_confidence_gain": 1, "user_effort": 1})
    assert result["status"] == iqp.SCORE_STATUS_UNVERIFIABLE
    assert "blocking_value" in result["reason"]


def test_boolean_factor_is_rejected_as_non_numeric():
    # bool is a subclass of int in Python; must not silently score as 0/1.
    result = iqp.score_question({"blocking_value": True, "downstream_impact": 1,
                                  "expected_confidence_gain": 1, "user_effort": 1})
    assert result["status"] == iqp.SCORE_STATUS_UNVERIFIABLE


def test_zero_user_effort_is_unverifiable_never_divides_by_zero():
    result = iqp.score_question({"blocking_value": 1, "downstream_impact": 1,
                                  "expected_confidence_gain": 1, "user_effort": 0})
    assert result["status"] == iqp.SCORE_STATUS_UNVERIFIABLE
    assert "user_effort" in result["reason"]


def test_negative_user_effort_is_unverifiable():
    result = iqp.score_question({"blocking_value": 1, "downstream_impact": 1,
                                  "expected_confidence_gain": 1, "user_effort": -3})
    assert result["status"] == iqp.SCORE_STATUS_UNVERIFIABLE


def test_negative_weight_factor_is_unverifiable():
    result = iqp.score_question({"blocking_value": -1, "downstream_impact": 1,
                                  "expected_confidence_gain": 1, "user_effort": 1})
    assert result["status"] == iqp.SCORE_STATUS_UNVERIFIABLE
    assert "blocking_value" in result["reason"]


def test_rank_questions_reports_unrankable_alongside_ranked_never_dropped():
    questions = [
        {"question_id": "good", "blocking_value": 1, "downstream_impact": 1,
         "expected_confidence_gain": 1, "user_effort": 1},
        {"question_id": "bad", "blocking_value": 1, "downstream_impact": 1,
         "expected_confidence_gain": 1, "user_effort": 0},
    ]
    result = iqp.rank_questions(questions)
    assert [r["question_id"] for r in result["ranked"]] == ["good"]
    assert [u["question_id"] for u in result["unrankable"]] == ["bad"]


# ===========================================================================
# (c) Batching
# ===========================================================================

def test_classify_batch_risk_only_minor_is_low():
    assert iqp.classify_batch_risk({"criticality": "MINOR"})[0] == iqp.BATCH_RISK_LOW
    assert iqp.classify_batch_risk({"criticality": "MAJOR"})[0] == iqp.BATCH_RISK_HIGH
    assert iqp.classify_batch_risk({"criticality": "BLOCKER"})[0] == iqp.BATCH_RISK_HIGH
    assert iqp.classify_batch_risk({"criticality": "UNKNOWN"})[0] == iqp.BATCH_RISK_HIGH
    assert iqp.classify_batch_risk({})[0] == iqp.BATCH_RISK_HIGH  # absent -> HIGH, never guessed LOW


def test_classify_batch_risk_architecture_defining_flag_overrides_minor():
    risk, reason = iqp.classify_batch_risk({"criticality": "MINOR", "architecture_defining": True})
    assert risk == iqp.BATCH_RISK_HIGH
    assert "architecture_defining" in reason


def test_build_question_batches_groups_related_low_risk_questions():
    questions = [
        {"question_id": "m1", "criticality": "MINOR", "topic": "clock-gating"},
        {"question_id": "m2", "criticality": "MINOR", "topic": "clock-gating"},
        {"question_id": "m3", "criticality": "MINOR", "topic": "reset-polarity"},
    ]
    result = iqp.build_question_batches(questions)
    batches_by_topic = {b["topic"]: b for b in result["batches"]}
    assert set(batches_by_topic["clock-gating"]["question_ids"]) == {"m1", "m2"}
    assert batches_by_topic["reset-polarity"]["question_ids"] == ["m3"]
    assert result["grouped_batch_count"] == 1
    assert result["solo_batch_count"] == 1


def test_build_question_batches_never_merges_a_blocker_question_with_anything():
    questions = [
        {"question_id": "arch1", "criticality": "BLOCKER", "topic": "clock-gating"},
        {"question_id": "m1", "criticality": "MINOR", "topic": "clock-gating"},
        {"question_id": "m2", "criticality": "MINOR", "topic": "clock-gating"},
    ]
    result = iqp.build_question_batches(questions)
    arch_batch = next(b for b in result["batches"] if "arch1" in b["question_ids"])
    assert arch_batch["question_ids"] == ["arch1"]
    assert arch_batch["risk"] == iqp.BATCH_RISK_HIGH
    minor_batch = next(b for b in result["batches"] if "m1" in b["question_ids"])
    assert "arch1" not in minor_batch["question_ids"]
    assert set(minor_batch["question_ids"]) == {"m1", "m2"}


def test_build_question_batches_never_merges_architecture_defining_flag_even_if_same_topic():
    questions = [
        {"question_id": "flagged", "criticality": "MINOR", "architecture_defining": True,
         "topic": "shared"},
        {"question_id": "ordinary", "criticality": "MINOR", "topic": "shared"},
    ]
    result = iqp.build_question_batches(questions)
    flagged_batch = next(b for b in result["batches"] if "flagged" in b["question_ids"])
    assert flagged_batch["question_ids"] == ["flagged"]


def test_build_question_batches_low_risk_with_no_topic_is_solo_never_merged_by_guess():
    questions = [
        {"question_id": "m1", "criticality": "MINOR"},
        {"question_id": "m2", "criticality": "MINOR"},
    ]
    result = iqp.build_question_batches(questions)
    ids_per_batch = [set(b["question_ids"]) for b in result["batches"]]
    assert {"m1"} in ids_per_batch and {"m2"} in ids_per_batch
    assert {"m1", "m2"} not in ids_per_batch


def test_build_question_batches_major_and_unknown_never_grouped_even_with_shared_topic():
    questions = [
        {"question_id": "maj1", "criticality": "MAJOR", "topic": "shared"},
        {"question_id": "maj2", "criticality": "MAJOR", "topic": "shared"},
        {"question_id": "unk1", "topic": "shared"},
    ]
    result = iqp.build_question_batches(questions)
    for b in result["batches"]:
        assert b["size"] == 1
    assert result["solo_batch_count"] == 3
    assert result["grouped_batch_count"] == 0


def test_build_question_batches_max_batch_size_splits_oversized_group():
    questions = [
        {"question_id": f"m{i}", "criticality": "MINOR", "topic": "shared"} for i in range(5)
    ]
    result = iqp.build_question_batches(questions, max_batch_size=2)
    shared_batches = [b for b in result["batches"] if b["topic"] == "shared"]
    assert len(shared_batches) == 3  # 2 + 2 + 1
    assert sum(b["size"] for b in shared_batches) == 5
    all_ids = [qid for b in shared_batches for qid in b["question_ids"]]
    assert all_ids == [f"m{i}" for i in range(5)]  # original order preserved


def test_build_question_batches_rejects_non_positive_max_batch_size():
    with pytest.raises(iqp.IntakeQuestionPriorityError):
        iqp.build_question_batches([{"criticality": "MINOR"}], max_batch_size=0)


# ===========================================================================
# Integrated pipeline
# ===========================================================================

def test_analyze_pending_questions_excludes_do_not_ask_from_ranking_and_batching():
    questions = [
        {"question_id": "skip", "confidence": "HIGH", "criticality": "MINOR",
         "topic": "x", "blocking_value": 9, "downstream_impact": 9,
         "expected_confidence_gain": 9, "user_effort": 1},
        {"question_id": "keep", "confidence": "LOW", "criticality": "BLOCKER",
         "topic": "x", "blocking_value": 1, "downstream_impact": 1,
         "expected_confidence_gain": 1, "user_effort": 1},
    ]
    report = iqp.analyze_pending_questions(questions)
    assert report["gating"]["to_ask"] == ["keep"]
    assert report["gating"]["do_not_ask"] == ["skip"]
    ranked_ids = [r["question_id"] for r in report["ranking"]["ranked"]]
    assert ranked_ids == ["keep"]
    batch_ids = [qid for b in report["batching"]["batches"] for qid in b["question_ids"]]
    assert batch_ids == ["keep"]  # "skip" never reaches batching either


def test_analyze_pending_questions_empty_input():
    report = iqp.analyze_pending_questions([])
    assert report["gating"]["total"] == 0
    assert report["ranking"]["ranked"] == []
    assert report["batching"]["batches"] == []


def test_render_report_text_produces_readable_summary():
    report = iqp.analyze_pending_questions([
        {"question_id": "k1", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 1, "downstream_impact": 1, "expected_confidence_gain": 1,
         "user_effort": 1},
    ])
    text = iqp.render_report_text(report)
    assert "INTAKE QUESTION PRIORITY" in text
    assert "k1" in text


# ===========================================================================
# CLI front door
# ===========================================================================

def test_cli_runs_end_to_end_and_reports_exit_0_when_clean(tmp_path: Path):
    payload = [
        {"question_id": "k1", "confidence": "LOW", "criticality": "BLOCKER",
         "topic": "a", "blocking_value": 3, "downstream_impact": 2,
         "expected_confidence_gain": 4, "user_effort": 1},
    ]
    pf = tmp_path / "pending.json"
    pf.write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_question_priority",
         "--pending-questions", str(pf), "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["gating"]["to_ask"] == ["k1"]


def test_cli_reports_exit_1_when_a_question_is_unrankable(tmp_path: Path):
    payload = [
        {"question_id": "k1", "confidence": "LOW", "criticality": "BLOCKER",
         "blocking_value": 1, "downstream_impact": 1, "expected_confidence_gain": 1,
         "user_effort": 0},
    ]
    pf = tmp_path / "pending.json"
    pf.write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_question_priority",
         "--pending-questions", str(pf)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 1, proc.stderr


def test_cli_reports_exit_2_on_malformed_input(tmp_path: Path):
    pf = tmp_path / "pending.json"
    pf.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_question_priority",
         "--pending-questions", str(pf)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 2, proc.stderr


# ===========================================================================
# "Why am I being asked this" -- grounding_evidence carried through, never
# invented (the same optional {"summary": ..., "evidence_path": ...} shape
# dv_harness.question_queue.add_question() accepts).
# ===========================================================================

def _ge():
    return {"summary": "register CTRL_REG is in the Excel map but absent from RTL",
            "evidence_path": "reg_map.xlsx#CTRL_REG"}


def test_gate_pending_questions_carries_grounding_evidence_through_when_present():
    questions = [
        {"question_id": "k1", "confidence": "LOW", "criticality": "MAJOR",
         "grounding_evidence": _ge()},
    ]
    result = iqp.gate_pending_questions(questions)
    assert result["gated"][0]["grounding_evidence"] == _ge()


def test_gate_pending_questions_never_fabricates_grounding_evidence_when_absent():
    # The negative control: a question dict with no grounding_evidence key
    # at all must never gain a fabricated one on the way through gating.
    questions = [{"question_id": "k1", "confidence": "LOW", "criticality": "MAJOR"}]
    result = iqp.gate_pending_questions(questions)
    assert "grounding_evidence" not in result["gated"][0]


def test_rank_questions_carries_grounding_evidence_through_for_ranked_entry():
    questions = [
        {"question_id": "k1", "blocking_value": 2, "downstream_impact": 2,
         "expected_confidence_gain": 2, "user_effort": 1, "grounding_evidence": _ge()},
    ]
    result = iqp.rank_questions(questions)
    assert result["ranked"][0]["grounding_evidence"] == _ge()


def test_rank_questions_carries_grounding_evidence_through_for_unrankable_entry():
    questions = [
        {"question_id": "k1", "user_effort": 0, "grounding_evidence": _ge()},
    ]
    result = iqp.rank_questions(questions)
    assert result["unrankable"][0]["grounding_evidence"] == _ge()


def test_rank_questions_never_fabricates_grounding_evidence_when_absent():
    questions = [
        {"question_id": "k1", "blocking_value": 2, "downstream_impact": 2,
         "expected_confidence_gain": 2, "user_effort": 1},
    ]
    result = iqp.rank_questions(questions)
    assert "grounding_evidence" not in result["ranked"][0]
