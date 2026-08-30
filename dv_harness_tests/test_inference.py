"""Tests for dv_harness/inference.py -- the deterministic Hypothesis ->
Evidence -> Confidence -> Gap -> Next-Best-Action module (see poster-compliance
gap: this used to exist only as CORE skill prose, never as real code)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dv_harness import inference as inf
from dv_harness.gates import REVIEWER_CONFIDENCE_LEVELS

ROOT = Path(__file__).resolve().parents[1]


# --- score_confidence --------------------------------------------------------

def test_confidence_levels_match_gates_reviewer_confidence_levels_exactly():
    assert set(inf.CONFIDENCE_LEVELS) == set(REVIEWER_CONFIDENCE_LEVELS)
    assert len(inf.CONFIDENCE_LEVELS) == 3


def test_score_confidence_high_case():
    # 3 sources capped at 3 -> 6, +2 verified = 8, no counter-evidence.
    result = inf.score_confidence(
        independent_sources_count=3,
        evidence_refs_verified=True,
        counter_evidence_count=0,
        multi_agent_consensus_count=0,
    )
    assert result["level"] == "HIGH"
    assert result["score"] == 8
    assert result["capped_by_counter_evidence"] is False


def test_score_confidence_medium_case():
    # 1 source -> 2, +2 verified = 4 -> MEDIUM (>=3, <6).
    result = inf.score_confidence(
        independent_sources_count=1,
        evidence_refs_verified=True,
        counter_evidence_count=0,
        multi_agent_consensus_count=0,
    )
    assert result["level"] == "MEDIUM"
    assert result["score"] == 4
    assert result["capped_by_counter_evidence"] is False


def test_score_confidence_low_case():
    # 0 sources, not verified, no counter-evidence -> base 0 -> LOW.
    result = inf.score_confidence(
        independent_sources_count=0,
        evidence_refs_verified=False,
        counter_evidence_count=0,
        multi_agent_consensus_count=0,
    )
    assert result["level"] == "LOW"
    assert result["score"] == 0
    assert result["capped_by_counter_evidence"] is False


def test_score_confidence_counter_evidence_downgrades_high_to_medium():
    # 3 sources -> 6, +2 verified = 8, +2 consensus bonus = 10, then
    # -3*1 counter-evidence = 7 -- still >=6 (would-be HIGH), but
    # counter_evidence_count > 0 so the safety floor forces MEDIUM.
    result = inf.score_confidence(
        independent_sources_count=3,
        evidence_refs_verified=True,
        counter_evidence_count=1,
        multi_agent_consensus_count=2,
    )
    assert result["score"] == 7
    assert result["level"] == "MEDIUM"
    assert result["capped_by_counter_evidence"] is True


def test_score_confidence_multi_agent_consensus_bonus():
    # 1 source -> 2, no verification, no counter-evidence, +2 consensus bonus
    # = 4 -> MEDIUM. Without the bonus this would be 2 -> LOW.
    with_bonus = inf.score_confidence(
        independent_sources_count=1,
        evidence_refs_verified=False,
        counter_evidence_count=0,
        multi_agent_consensus_count=2,
    )
    without_bonus = inf.score_confidence(
        independent_sources_count=1,
        evidence_refs_verified=False,
        counter_evidence_count=0,
        multi_agent_consensus_count=1,
    )
    assert with_bonus["score"] == 4
    assert with_bonus["level"] == "MEDIUM"
    assert without_bonus["score"] == 2
    assert without_bonus["level"] == "LOW"


@pytest.mark.parametrize("kwargs", [
    dict(independent_sources_count=-1, evidence_refs_verified=True,
         counter_evidence_count=0, multi_agent_consensus_count=0),
    dict(independent_sources_count=1, evidence_refs_verified=True,
         counter_evidence_count=-1, multi_agent_consensus_count=0),
    dict(independent_sources_count=1, evidence_refs_verified=True,
         counter_evidence_count=0, multi_agent_consensus_count=-1),
])
def test_score_confidence_negative_inputs_raise_value_error(kwargs):
    with pytest.raises(ValueError):
        inf.score_confidence(**kwargs)


def test_score_confidence_non_bool_evidence_refs_verified_raises_value_error():
    with pytest.raises(ValueError):
        inf.score_confidence(
            independent_sources_count=1,
            evidence_refs_verified="yes",
            counter_evidence_count=0,
            multi_agent_consensus_count=0,
        )


def test_score_confidence_non_int_raises_value_error():
    with pytest.raises(ValueError):
        inf.score_confidence(
            independent_sources_count=1.5,
            evidence_refs_verified=True,
            counter_evidence_count=0,
            multi_agent_consensus_count=0,
        )


# --- identify_gap -------------------------------------------------------------

def test_identify_gap_basic_case():
    required = ["rtl", "waveform", "sim_log", "register_map"]
    supplied = ["waveform", "sim_log"]
    assert inf.identify_gap(required, supplied) == ["rtl", "register_map"]


def test_identify_gap_empty_when_supplied_covers_everything():
    required = ["rtl", "waveform"]
    supplied = ["waveform", "rtl", "extra_unrelated_category"]
    assert inf.identify_gap(required, supplied) == []


def test_identify_gap_preserves_required_order():
    required = ["c", "a", "b"]
    supplied = ["a"]
    assert inf.identify_gap(required, supplied) == ["c", "b"]


def test_identify_gap_case_sensitive_no_fuzzy_match():
    required = ["RTL"]
    supplied = ["rtl"]
    assert inf.identify_gap(required, supplied) == ["RTL"]


@pytest.mark.parametrize("required,supplied", [
    ("not_a_list", []),
    ([], "not_a_list"),
    ([1, 2], []),
    ([], [1, 2]),
])
def test_identify_gap_invalid_inputs_raise_value_error(required, supplied):
    with pytest.raises(ValueError):
        inf.identify_gap(required, supplied)


# --- next_best_action ---------------------------------------------------------

def test_next_best_action_matches_real_pcie_registry_item():
    registry = json.loads(
        (ROOT / ".dv-harness" / "builder" / "protocol_builder_registry.json").read_text(
            encoding="utf-8"
        )
    )
    pcie = registry["protocols"]["pcie"]
    all_items = pcie["discover"] + pcie["build"]
    assert any("LTSSM" in item for item in all_items), (
        "test assumption broken: registry no longer has an LTSSM item for pcie"
    )

    result = inf.next_best_action("pcie", ["LTSSM"], ROOT)
    assert len(result) == 1
    entry = result[0]
    assert entry["gap"] == "LTSSM"
    assert entry["source"] == "protocol_builder_registry"
    assert "LTSSM/link training" in entry["suggested_action"]


def test_next_best_action_no_match_returns_generic_honest_suggestion():
    result = inf.next_best_action("pcie", ["quantum_teleportation_widget"], ROOT)
    assert len(result) == 1
    entry = result[0]
    assert entry["gap"] == "quantum_teleportation_widget"
    assert entry["source"] == "generic"
    assert "no concrete registry item found" in entry["suggested_action"]
    # Must not fabricate a fake specific-sounding registry reference.
    assert "quantum_teleportation_widget" in entry["suggested_action"]


def test_next_best_action_preserves_gap_order_and_one_entry_per_gap():
    result = inf.next_best_action("pcie", ["LTSSM", "totally_unknown_gap", "TLP"], ROOT)
    assert [r["gap"] for r in result] == ["LTSSM", "totally_unknown_gap", "TLP"]
    assert result[0]["source"] == "protocol_builder_registry"
    assert result[1]["source"] == "generic"
    assert result[2]["source"] == "protocol_builder_registry"


# --- promote_if_high_confidence -----------------------------------------------

class _FakeKcClient:
    """Stub matching KnowledgeCenterClient's add() contract: returns a dict
    with an "ok" key, never raises."""

    def __init__(self, add_result):
        self._add_result = add_result
        self.add_calls = []

    def add(self, category, protocol, record):
        self.add_calls.append((category, protocol, record))
        return dict(self._add_result)


def test_promote_if_high_confidence_calls_add_once_with_right_args_on_high():
    kc = _FakeKcClient({"ok": True, "record_id": "abc123"})
    confidence_result = {"level": "HIGH", "score": 8, "capped_by_counter_evidence": False}
    finding = {"summary": "root cause confirmed via waveform + sim.log"}

    result = inf.promote_if_high_confidence(kc, "root_cause", "pcie", finding, confidence_result)

    assert kc.add_calls == [("root_cause", "pcie", finding)]
    assert result["promoted"] is True
    assert result["ok"] is True
    assert result["record_id"] == "abc123"


@pytest.mark.parametrize("level", ["MEDIUM", "LOW"])
def test_promote_if_high_confidence_never_calls_add_on_medium_or_low(level):
    kc = _FakeKcClient({"ok": True})
    confidence_result = {"level": level, "score": 1, "capped_by_counter_evidence": False}

    result = inf.promote_if_high_confidence(kc, "root_cause", "pcie", {}, confidence_result)

    assert kc.add_calls == []
    assert result == {"promoted": False, "reason": "CONFIDENCE_NOT_HIGH", "level": level}


def test_promote_if_high_confidence_kc_add_failure_is_not_reported_as_promoted():
    kc = _FakeKcClient({"ok": False, "error": "TIMEOUT"})
    confidence_result = {"level": "HIGH", "score": 8, "capped_by_counter_evidence": False}

    result = inf.promote_if_high_confidence(kc, "root_cause", "pcie", {}, confidence_result)

    assert kc.add_calls == [("root_cause", "pcie", {})]
    assert result["promoted"] is False
    assert result["reason"] == "KC_ADD_FAILED"
    assert result["kc_result"] == {"ok": False, "error": "TIMEOUT"}


def test_promote_if_high_confidence_uses_real_capped_by_counter_evidence_medium_result():
    # Regression guard: a would-be-HIGH score downgraded to MEDIUM by the
    # counter-evidence safety floor must never reach kc_client.add() either.
    kc = _FakeKcClient({"ok": True})
    confidence_result = inf.score_confidence(
        independent_sources_count=3,
        evidence_refs_verified=True,
        counter_evidence_count=1,
        multi_agent_consensus_count=2,
    )
    assert confidence_result["level"] == "MEDIUM"

    result = inf.promote_if_high_confidence(kc, "root_cause", "pcie", {}, confidence_result)

    assert kc.add_calls == []
    assert result["promoted"] is False
    assert result["reason"] == "CONFIDENCE_NOT_HIGH"
