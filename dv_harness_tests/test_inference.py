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


# --- ConsensusResult / score_confidence_with_consensus (additive, opt-in) ---

def test_consensus_result_basic_fields_and_totals():
    c = inf.ConsensusResult(agree_count=3, disagree_count=1, abstain_count=1)
    assert c.total_votes == 5
    assert c.is_unanimous is False
    assert c.is_split is True


def test_consensus_result_unanimous_requires_at_least_two_agreeing_votes():
    # 1 agree, 0 disagree is NOT "unanimous" by this class's own definition
    # (mirrors score_confidence()'s own multi_agent_consensus_count>=2 floor).
    assert inf.ConsensusResult(agree_count=1, disagree_count=0).is_unanimous is False
    assert inf.ConsensusResult(agree_count=2, disagree_count=0).is_unanimous is True


def test_consensus_result_rejects_negative_counts():
    with pytest.raises(ValueError):
        inf.ConsensusResult(agree_count=-1, disagree_count=0)
    with pytest.raises(ValueError):
        inf.ConsensusResult(agree_count=0, disagree_count=-1)
    with pytest.raises(ValueError):
        inf.ConsensusResult(agree_count=0, disagree_count=0, abstain_count=-1)


def test_consensus_result_dissenting_claims_cannot_exceed_disagree_count():
    claim = inf.DissentingClaim(agent="agent-b", claim="root cause is elsewhere",
                                 evidence="sim.log:42")
    with pytest.raises(ValueError):
        inf.ConsensusResult(agree_count=2, disagree_count=0, dissenting_claims=(claim,))


def test_dissenting_claim_requires_non_empty_agent_and_claim():
    with pytest.raises(ValueError):
        inf.DissentingClaim(agent="", claim="x")
    with pytest.raises(ValueError):
        inf.DissentingClaim(agent="agent-b", claim="   ")


def test_score_confidence_with_consensus_unanimous_matches_old_bonus_magnitude():
    # Same inputs as test_score_confidence_multi_agent_consensus_bonus's
    # with_bonus case, but via a real ConsensusResult: unanimous (2 agree, 0
    # disagree) must apply the identical +2 the bare-int path applies at
    # multi_agent_consensus_count=2, so score_confidence()'s own existing
    # behavior is a reachable special case of the new path, not replaced by it.
    unanimous = inf.ConsensusResult(agree_count=2, disagree_count=0)
    result = inf.score_confidence_with_consensus(
        independent_sources_count=1,
        evidence_refs_verified=False,
        counter_evidence_count=0,
        consensus_result=unanimous,
    )
    assert result["score"] == 4
    assert result["level"] == "MEDIUM"
    assert result["consensus"]["is_unanimous"] is True
    assert result["consensus"]["consensus_bonus_applied"] == 2


def test_score_confidence_with_consensus_split_vote_scores_lower_than_unanimous():
    # The whole point of this item: a split vote must never score identically
    # to a unanimous one, even with the same headline "count".
    same_base_kwargs = dict(
        independent_sources_count=1,
        evidence_refs_verified=False,
        counter_evidence_count=0,
    )
    unanimous = inf.score_confidence_with_consensus(
        consensus_result=inf.ConsensusResult(agree_count=3, disagree_count=0),
        **same_base_kwargs,
    )
    split = inf.score_confidence_with_consensus(
        consensus_result=inf.ConsensusResult(agree_count=2, disagree_count=1),
        **same_base_kwargs,
    )
    assert unanimous["consensus"]["consensus_bonus_applied"] == 2
    assert split["consensus"]["consensus_bonus_applied"] == 1
    assert split["score"] < unanimous["score"]
    # base=2, +1 split bonus = 3 -> MEDIUM; unanimous base=2, +2 = 4 -> MEDIUM
    # too here, so also prove the LOW/MEDIUM boundary actually moves:
    assert split["level"] == "MEDIUM"
    assert unanimous["level"] == "MEDIUM"


def test_score_confidence_with_consensus_split_vote_carries_dissenting_evidence():
    dissent = inf.DissentingClaim(
        agent="agent-review-2", claim="counter-evidence points to a VIP misconfig, not RTL",
        evidence="dv_harness_tests/fixtures/example.log:10",
    )
    split = inf.ConsensusResult(agree_count=2, disagree_count=1, dissenting_claims=(dissent,))
    result = inf.score_confidence_with_consensus(
        independent_sources_count=1,
        evidence_refs_verified=False,
        counter_evidence_count=0,
        consensus_result=split,
    )
    assert result["consensus"]["dissenting_claims"] == [
        {"agent": "agent-review-2",
         "claim": "counter-evidence points to a VIP misconfig, not RTL",
         "evidence": "dv_harness_tests/fixtures/example.log:10"}
    ]


def test_score_confidence_with_consensus_no_net_agreement_applies_zero_bonus():
    # A tied or disagreement-majority vote must never earn a positive bonus --
    # it is NOT the same as "no consensus data" (<2 total votes) but it must
    # score identically to that case: no real corroboration was reached.
    tied = inf.score_confidence_with_consensus(
        independent_sources_count=1, evidence_refs_verified=False, counter_evidence_count=0,
        consensus_result=inf.ConsensusResult(agree_count=2, disagree_count=2),
    )
    disagreement_majority = inf.score_confidence_with_consensus(
        independent_sources_count=1, evidence_refs_verified=False, counter_evidence_count=0,
        consensus_result=inf.ConsensusResult(agree_count=1, disagree_count=3),
    )
    no_data = inf.score_confidence_with_consensus(
        independent_sources_count=1, evidence_refs_verified=False, counter_evidence_count=0,
        consensus_result=inf.ConsensusResult(agree_count=0, disagree_count=0),
    )
    assert tied["score"] == disagreement_majority["score"] == no_data["score"] == 2
    assert tied["level"] == disagreement_majority["level"] == no_data["level"] == "LOW"
    assert tied["consensus"]["consensus_bonus_applied"] == 0
    assert disagreement_majority["consensus"]["consensus_bonus_applied"] == 0
    assert no_data["consensus"]["consensus_bonus_applied"] == 0


def test_score_confidence_with_consensus_safety_floor_unchanged():
    # The counter-evidence safety floor (HIGH can never coexist with
    # unaddressed counter-evidence) must still hold under the new path.
    result = inf.score_confidence_with_consensus(
        independent_sources_count=3,
        evidence_refs_verified=True,
        counter_evidence_count=1,
        consensus_result=inf.ConsensusResult(agree_count=2, disagree_count=0),
    )
    # base: 6 + 2 (verified) + 2 (unanimous) - 3 (counter-evidence) = 7 -> would
    # be HIGH, but counter_evidence_count>0 forces the MEDIUM cap.
    assert result["score"] == 7
    assert result["level"] == "MEDIUM"
    assert result["capped_by_counter_evidence"] is True


def test_score_confidence_with_consensus_rejects_non_consensus_result():
    with pytest.raises(ValueError):
        inf.score_confidence_with_consensus(
            independent_sources_count=1,
            evidence_refs_verified=False,
            counter_evidence_count=0,
            consensus_result=2,  # a bare int, not a ConsensusResult -- must be refused
        )


def test_score_confidence_with_consensus_rejects_negative_and_non_bool_inputs():
    valid_consensus = inf.ConsensusResult(agree_count=1, disagree_count=0)
    with pytest.raises(ValueError):
        inf.score_confidence_with_consensus(
            independent_sources_count=-1, evidence_refs_verified=True,
            counter_evidence_count=0, consensus_result=valid_consensus,
        )
    with pytest.raises(ValueError):
        inf.score_confidence_with_consensus(
            independent_sources_count=1, evidence_refs_verified="yes",
            counter_evidence_count=0, consensus_result=valid_consensus,
        )


def test_score_confidence_and_score_confidence_with_consensus_are_independent_paths():
    # NEGATIVE CONTROL for the whole item: score_confidence()'s own bare-int
    # signature and exact current behavior must be completely untouched by
    # the new sibling path's existence. Re-run every documented case from the
    # original test suite above and confirm byte-identical results.
    old_high = inf.score_confidence(
        independent_sources_count=3, evidence_refs_verified=True,
        counter_evidence_count=0, multi_agent_consensus_count=0,
    )
    assert old_high == {"level": "HIGH", "score": 8, "capped_by_counter_evidence": False}

    old_medium = inf.score_confidence(
        independent_sources_count=1, evidence_refs_verified=True,
        counter_evidence_count=0, multi_agent_consensus_count=0,
    )
    assert old_medium == {"level": "MEDIUM", "score": 4, "capped_by_counter_evidence": False}

    old_capped = inf.score_confidence(
        independent_sources_count=3, evidence_refs_verified=True,
        counter_evidence_count=1, multi_agent_consensus_count=2,
    )
    assert old_capped == {"level": "MEDIUM", "score": 7, "capped_by_counter_evidence": True}
    # score_confidence()'s return dict has NO "consensus" key -- proving the
    # two paths' output shapes stay genuinely distinct, not silently merged.
    assert "consensus" not in old_capped


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


# --- rank_evidence_by_information_value (NEW, additive, sibling of identify_gap) ---

def test_rank_evidence_by_information_value_empty_hypotheses_returns_empty_ranking():
    result = inf.rank_evidence_by_information_value([])
    assert result == {"hypothesis_count": 0, "ranked": []}


def test_rank_evidence_by_information_value_discriminating_category_beats_universal_one():
    # NEGATIVE CONTROL / core proof this is genuinely value-of-information
    # ranking, not a naive "how many hypotheses need it" count (which a plain
    # identify_gap()-based tally would get backwards):
    #   - "waveform" is required and missing by ALL 4 hypotheses (p=1.0):
    #     gathering it cannot discriminate which hypothesis is right, it
    #     would help every one of them equally -- discrimination must be 0.
    #   - "register_map" is required by all 4 but missing by exactly 2 of
    #     them (p=0.5): resolving it genuinely separates the two hypotheses
    #     that still lack it from the two that already have it -- maximal
    #     discrimination.
    # A naive "most hypotheses need this" ranking would rank waveform (4/4)
    # above register_map (2/4); real VOI ranking must do the opposite.
    hypotheses = [
        {
            "hypothesis_id": f"H{i}",
            "required_evidence_categories": ["waveform", "register_map"],
            "supplied_evidence_categories": ["register_map"] if i < 2 else [],
        }
        for i in range(4)
    ]
    result = inf.rank_evidence_by_information_value(hypotheses)
    ranked_by_category = {e["category"]: e for e in result["ranked"]}

    assert ranked_by_category["waveform"]["discrimination"] == 0.0
    assert ranked_by_category["waveform"]["voi_score"] == 0.0
    assert ranked_by_category["register_map"]["discrimination"] == 1.0
    assert ranked_by_category["register_map"]["voi_score"] > 0.0

    # And the ranking itself must put the discriminating category first.
    assert [e["category"] for e in result["ranked"]][0] == "register_map"


def test_rank_evidence_by_information_value_uncertainty_weight_from_confidence_level():
    # Same discrimination (missing by exactly 1 of 2 applicable hypotheses,
    # p=0.5 -> discrimination=1.0) for both categories, but the hypothesis
    # missing "low_cat" is at LOW confidence (urgency 3/3 = 1.0 weight) while
    # the hypothesis missing "high_cat" is at HIGH confidence (urgency 1/3).
    # voi_score must differ even though discrimination is identical.
    hypotheses = [
        {
            "hypothesis_id": "H_low_missing",
            "required_evidence_categories": ["low_cat"],
            "supplied_evidence_categories": [],
            "current_confidence_level": "LOW",
        },
        {
            "hypothesis_id": "H_low_has_it",
            "required_evidence_categories": ["low_cat"],
            "supplied_evidence_categories": ["low_cat"],
        },
        {
            "hypothesis_id": "H_high_missing",
            "required_evidence_categories": ["high_cat"],
            "supplied_evidence_categories": [],
            "current_confidence_level": "HIGH",
        },
        {
            "hypothesis_id": "H_high_has_it",
            "required_evidence_categories": ["high_cat"],
            "supplied_evidence_categories": ["high_cat"],
        },
    ]
    result = inf.rank_evidence_by_information_value(hypotheses)
    by_cat = {e["category"]: e for e in result["ranked"]}

    assert by_cat["low_cat"]["discrimination"] == by_cat["high_cat"]["discrimination"] == 1.0
    assert by_cat["low_cat"]["uncertainty_weight"] == 1.0
    assert by_cat["high_cat"]["uncertainty_weight"] == round(1 / 3, 4)
    assert by_cat["low_cat"]["voi_score"] > by_cat["high_cat"]["voi_score"]
    assert [e["category"] for e in result["ranked"]][0] == "low_cat"


def test_rank_evidence_by_information_value_unspecified_confidence_treated_as_medium():
    with_level = inf.rank_evidence_by_information_value([
        {"hypothesis_id": "H1", "required_evidence_categories": ["x"],
         "supplied_evidence_categories": [], "current_confidence_level": "MEDIUM"},
    ])
    without_level = inf.rank_evidence_by_information_value([
        {"hypothesis_id": "H1", "required_evidence_categories": ["x"],
         "supplied_evidence_categories": []},
    ])
    assert with_level["ranked"][0]["voi_score"] == without_level["ranked"][0]["voi_score"]


def test_rank_evidence_by_information_value_hypotheses_applicable_and_missing_lists():
    hypotheses = [
        {"hypothesis_id": "H1", "required_evidence_categories": ["reg_dump"],
         "supplied_evidence_categories": []},
        {"hypothesis_id": "H2", "required_evidence_categories": ["reg_dump"],
         "supplied_evidence_categories": ["reg_dump"]},
        {"hypothesis_id": "H3", "required_evidence_categories": ["unrelated"],
         "supplied_evidence_categories": []},
    ]
    result = inf.rank_evidence_by_information_value(hypotheses)
    entry = next(e for e in result["ranked"] if e["category"] == "reg_dump")
    assert entry["hypotheses_applicable"] == ["H1", "H2"]
    assert entry["hypotheses_missing"] == ["H1"]
    # H3 never required reg_dump, so it must never appear in either list.
    assert "H3" not in entry["hypotheses_applicable"]


def test_rank_evidence_by_information_value_fully_supplied_category_never_ranked():
    # A category every hypothesis already has is not a "gap" anywhere, so it
    # must never appear in the ranking at all (identify_gap() itself already
    # excludes it -- this proves that exclusion survives into the ranking).
    hypotheses = [
        {"hypothesis_id": "H1", "required_evidence_categories": ["sim_log"],
         "supplied_evidence_categories": ["sim_log"]},
    ]
    result = inf.rank_evidence_by_information_value(hypotheses)
    assert result["ranked"] == []
    assert result["hypothesis_count"] == 1


def test_rank_evidence_by_information_value_ties_broken_by_category_name():
    hypotheses = [
        {"hypothesis_id": "H1", "required_evidence_categories": ["zeta", "alpha"],
         "supplied_evidence_categories": []},
    ]
    result = inf.rank_evidence_by_information_value(hypotheses)
    # Both categories: p=1.0 (single applicable hypothesis, missing) ->
    # discrimination=0, voi_score=0 for both -- a genuine tie, broken by name.
    assert [e["category"] for e in result["ranked"]] == ["alpha", "zeta"]


def test_rank_evidence_by_information_value_propagates_identify_gap_validation():
    # identify_gap() itself is reused verbatim, never re-derived -- its own
    # validation must still fire through this new function.
    with pytest.raises(ValueError):
        inf.rank_evidence_by_information_value([
            {"hypothesis_id": "H1", "required_evidence_categories": "not_a_list",
             "supplied_evidence_categories": []},
        ])


@pytest.mark.parametrize("bad_hypotheses", [
    "not_a_list",
    [123],
    [{"required_evidence_categories": ["x"], "supplied_evidence_categories": []}],  # no id
    [{"hypothesis_id": "", "required_evidence_categories": ["x"],
      "supplied_evidence_categories": []}],  # blank id
    [{"hypothesis_id": "H1", "required_evidence_categories": ["x"],
      "supplied_evidence_categories": [], "current_confidence_level": "CONFIRMED"}],  # not real
])
def test_rank_evidence_by_information_value_invalid_inputs_raise_value_error(bad_hypotheses):
    with pytest.raises(ValueError):
        inf.rank_evidence_by_information_value(bad_hypotheses)


def test_rank_evidence_by_information_value_does_not_mutate_identify_gap_behavior():
    # NEGATIVE CONTROL for the whole item: identify_gap()'s own documented
    # behavior must be completely unaffected by this new sibling existing.
    required = ["rtl", "waveform", "sim_log", "register_map"]
    supplied = ["waveform", "sim_log"]
    assert inf.identify_gap(required, supplied) == ["rtl", "register_map"]


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


# --- detect_hypothesis_generation_bias (NEW, additive; hypothesis-generation-
# bias-correction) -------------------------------------------------------------

def _hyp(hid, retracted, categories=()):
    return {
        "hypothesis_id": hid,
        "retracted": retracted,
        "evidence_categories_cited": list(categories),
    }


def test_detect_hypothesis_generation_bias_empty_input_is_not_available():
    report = inf.detect_hypothesis_generation_bias([])
    assert report["status"] == inf.BIAS_STATUS_NOT_AVAILABLE
    assert report["reason"] == "NO_HYPOTHESES_SUPPLIED"
    assert report["category_findings"] == []
    assert report["shape_findings"] == []
    assert report["hypothesis_count"] == 0
    assert "ADVISORY ONLY" in report["disclosure"]


def test_detect_hypothesis_generation_bias_too_few_samples_is_insufficient_history():
    # Real evidence-category imbalance, but every group is far below
    # min_group_size -- must never be silently promoted into a finding.
    hyps = [
        _hyp("H0", True, ["symptom_register"]),
        _hyp("H1", False, ["symptom_register", "control_register"]),
    ]
    report = inf.detect_hypothesis_generation_bias(hyps)
    assert report["status"] == inf.BIAS_STATUS_INSUFFICIENT_HISTORY
    assert report["reason"] == "NO_CATEGORY_OR_SHAPE_HAS_ENOUGH_OBSERVATIONS_IN_BOTH_GROUPS"
    assert report["category_findings"] == []
    assert report["shape_findings"] == []
    # transparency: the under-powered comparisons are still reported, not
    # silently dropped.
    assert any(c["category"] == "symptom_register" for c in report["categories_insufficient"])


def _biased_corpus():
    """5 hypotheses missing 'control_register' that were retracted, 6 that
    were not (11 total missing it, well above min_group_size); 1 hypothesis
    citing it that was retracted, 6 that were not (7 total citing it) --
    the absence group is retracted materially more often than the citing
    group, exactly the item's own worked example ("hypotheses citing only a
    symptom register and never a control register are wrong more often")."""
    hyps = []
    for i in range(5):
        hyps.append(_hyp(f"MISS-BAD-{i}", True, ["symptom_register"]))
    for i in range(6):
        hyps.append(_hyp(f"MISS-OK-{i}", False, ["symptom_register"]))
    hyps.append(_hyp("HIT-BAD-0", True, ["symptom_register", "control_register"]))
    for i in range(6):
        hyps.append(_hyp(f"HIT-OK-{i}", False, ["symptom_register", "control_register"]))
    return hyps


def test_detect_hypothesis_generation_bias_surfaces_the_absence_pattern():
    report = inf.detect_hypothesis_generation_bias(_biased_corpus())
    assert report["status"] == inf.BIAS_STATUS_BIAS_DETECTED
    assert report["reason"] == "FINDINGS_PRESENT"

    findings = {f["category"]: f for f in report["category_findings"]}
    assert "control_register" in findings
    finding = findings["control_register"]
    assert finding["kind"] == inf.FINDING_EVIDENCE_CATEGORY_BIAS
    assert finding["direction"] == inf.DIRECTION_ABSENCE_CORRELATES
    assert finding["absent_count"] == 11
    assert finding["citing_count"] == 7
    assert round(finding["absent_retraction_rate"], 2) == round(5 / 11, 2)
    assert round(finding["citing_retraction_rate"], 2) == round(1 / 7, 2)
    assert finding["margin_observed"] > inf.HYPOTHESIS_BIAS_MARGIN
    assert "control_register" in finding["detail"]

    # 'symptom_register' is cited by EVERY hypothesis in this corpus, so the
    # "absent" group is empty and it must be reported insufficient, never a
    # spuriously computed 0%-vs-something rate.
    insufficient = {c["category"] for c in report["categories_insufficient"]}
    assert "symptom_register" in insufficient


def test_detect_hypothesis_generation_bias_citing_direction_is_also_detected():
    # The opposite direction: citing a noisy/unreliable category correlates
    # with MORE retractions -- must be reported as CITING_CORRELATES, not
    # silently folded into (or confused with) the absence direction.
    hyps = []
    for i in range(6):
        hyps.append(_hyp(f"C-BAD-{i}", True, ["noisy_log_grep"]))
    for i in range(1):
        hyps.append(_hyp(f"C-OK-{i}", False, ["noisy_log_grep"]))
    for i in range(6):
        hyps.append(_hyp(f"N-OK-{i}", False, []))
    for i in range(1):
        hyps.append(_hyp(f"N-BAD-{i}", True, []))

    report = inf.detect_hypothesis_generation_bias(hyps)
    finding = next(f for f in report["category_findings"] if f["category"] == "noisy_log_grep")
    assert finding["direction"] == inf.DIRECTION_CITING_CORRELATES
    assert finding["citing_retraction_rate"] > finding["absent_retraction_rate"]


def test_detect_hypothesis_generation_bias_no_finding_when_rates_are_close():
    # Same category distribution on both sides, well above min_group_size,
    # but the two retraction rates sit within `margin` of each other --
    # must NOT manufacture a finding out of noise.
    hyps = []
    for i in range(5):
        hyps.append(_hyp(f"A{i}", i % 2 == 0, ["reg_x"]))
    for i in range(5):
        hyps.append(_hyp(f"B{i}", i % 2 == 0, []))
    report = inf.detect_hypothesis_generation_bias(hyps)
    assert report["status"] == inf.BIAS_STATUS_NO_BIAS_DETECTED
    assert report["reason"] == "NO_FINDINGS"
    assert report["category_findings"] == []
    assert report["shape_findings"] == []


def test_detect_hypothesis_generation_bias_exact_shape_finding():
    # A precise combination ('a' AND 'b' together, nothing else) is riskier
    # than every other shape in the corpus -- the per-category view alone
    # would not surface this as cleanly as the exact-shape view does.
    hyps = []
    for i in range(6):
        hyps.append(_hyp(f"SB{i}", True, ["a", "b"]))
    for i in range(6):
        hyps.append(_hyp(f"SO{i}", False, ["a"]))
    for i in range(6):
        hyps.append(_hyp(f"SG{i}", False, ["b"]))
    report = inf.detect_hypothesis_generation_bias(hyps)
    shape_finding = next(
        (s for s in report["shape_findings"] if s["evidence_categories_cited"] == ["a", "b"]),
        None,
    )
    assert shape_finding is not None
    assert shape_finding["kind"] == inf.FINDING_HYPOTHESIS_SHAPE_BIAS
    assert shape_finding["matching_retraction_rate"] == 1.0
    assert shape_finding["other_retraction_rate"] == 0.0


@pytest.mark.parametrize("bad_hypotheses", [
    "not-a-list",
    [1, 2],
    [{"hypothesis_id": "", "retracted": False}],
    [{"hypothesis_id": "H0", "retracted": "yes"}],
    [{"hypothesis_id": "H0", "retracted": True, "evidence_categories_cited": "not-a-list"}],
    [{"hypothesis_id": "H0", "retracted": True}, {"hypothesis_id": "H0", "retracted": False}],
])
def test_detect_hypothesis_generation_bias_invalid_inputs_raise_value_error(bad_hypotheses):
    with pytest.raises(ValueError):
        inf.detect_hypothesis_generation_bias(bad_hypotheses)


def test_detect_hypothesis_generation_bias_invalid_min_group_size_and_margin_raise():
    with pytest.raises(ValueError):
        inf.detect_hypothesis_generation_bias([], min_group_size=0)
    with pytest.raises(ValueError):
        inf.detect_hypothesis_generation_bias([], margin=1.5)
    with pytest.raises(ValueError):
        inf.detect_hypothesis_generation_bias([], margin=True)


def test_detect_hypothesis_generation_bias_never_mutates_score_confidence():
    # Negative control for the module docstring's own "never touches
    # score_confidence()'s formula" claim: run the bias detector, then prove
    # score_confidence() still computes byte-identically to its own
    # documented HIGH-case example.
    inf.detect_hypothesis_generation_bias(_biased_corpus())
    result = inf.score_confidence(
        independent_sources_count=3,
        evidence_refs_verified=True,
        counter_evidence_count=0,
        multi_agent_consensus_count=0,
    )
    assert result == {"level": "HIGH", "score": 8, "capped_by_counter_evidence": False}


# --- hypothesis_shape_from_record / collect_hypothesis_shapes (real
# dv_harness.memory MemoryStore/MemoryGC integration) -------------------------

def test_hypothesis_shape_from_record_reads_real_retracted_status():
    record = {
        "memory_id": "MEM-ABC123",
        "status": "RETRACTED",
        "root_cause": "bad clock domain crossing",
        "evidence": {"symptom_register": "STATUS.err=1", "control_register": ""},
    }
    shape = inf.hypothesis_shape_from_record(record)
    assert shape["hypothesis_id"] == "MEM-ABC123"
    assert shape["retracted"] is True
    # falsy dict values (control_register="") must never count as "cited".
    assert shape["evidence_categories_cited"] == ["symptom_register"]


def test_hypothesis_shape_from_record_supersede_is_never_counted_as_retracted():
    record = {
        "memory_id": "MEM-DEF456",
        "status": "SUPERSEDED",
        "root_cause": "fifo overflow",
        "evidence": "free text evidence, not a category dict",
    }
    shape = inf.hypothesis_shape_from_record(record)
    assert shape["retracted"] is False
    # a non-dict evidence field is an honestly EMPTY category set, never a
    # guess at what it might mean.
    assert shape["evidence_categories_cited"] == []


def test_hypothesis_shape_from_record_requires_memory_id():
    with pytest.raises(ValueError):
        inf.hypothesis_shape_from_record({"status": "ACTIVE"})


def test_collect_hypothesis_shapes_reads_real_memorystore_records(tmp_path):
    from dv_harness.memory import MemoryStore, MemoryGC

    store = MemoryStore(tmp_path)
    mem1 = store.add("engineering", {
        "kind": "root_cause",
        "root_cause": "bad clock domain crossing",
        "evidence": {"symptom_register": "STATUS.err=1", "control_register": ""},
        "confidence": "HIGH",
    })
    mem2 = store.add("engineering", {
        "kind": "verified_fix",
        "root_cause": "fifo overflow",
        "evidence": {"symptom_register": "FIFO.full=1", "control_register": "CTRL.mode=2"},
        "confidence": "HIGH",
    })
    # A "job_failure" record must be ignored -- not a root-cause-shaped kind
    # at all (memory_router.py never routes it as reusable engineering
    # knowledge), and it carries no `root_cause` field either.
    store.add("job", {"kind": "job_failure", "title": "attempt 1 failed"})

    gc = MemoryGC(store)
    gc.retract(mem1["memory_id"], "found wrong: real cause was elsewhere",
               evidence={"note": "re-derived"})

    shapes = inf.collect_hypothesis_shapes(tmp_path, store=store)
    by_id = {s["hypothesis_id"]: s for s in shapes}

    assert set(by_id) == {mem1["memory_id"], mem2["memory_id"]}
    assert by_id[mem1["memory_id"]]["retracted"] is True
    assert by_id[mem1["memory_id"]]["evidence_categories_cited"] == ["symptom_register"]
    assert by_id[mem2["memory_id"]]["retracted"] is False
    assert by_id[mem2["memory_id"]]["evidence_categories_cited"] == [
        "control_register", "symptom_register",
    ]

    # feeds straight into the bias detector with no adaptation.
    report = inf.detect_hypothesis_generation_bias(shapes)
    assert report["status"] == inf.BIAS_STATUS_INSUFFICIENT_HISTORY
    assert report["hypothesis_count"] == 2


def test_collect_hypothesis_shapes_constructs_its_own_store_when_none_supplied(tmp_path):
    from dv_harness.memory import MemoryStore

    store = MemoryStore(tmp_path)
    store.add("engineering", {"kind": "debug_lesson", "root_cause": "reset ordering bug",
                               "evidence": "plain text"})

    shapes = inf.collect_hypothesis_shapes(tmp_path)
    assert len(shapes) == 1
    assert shapes[0]["evidence_categories_cited"] == []


# ---------------------------------------------------------------------------
# Meta-reasoning: recommend_evidence_gathering_effort() and its two real
# signals (2026-09-07, meta_reasoning_effort_sizing)
# ---------------------------------------------------------------------------

class TestDomainHypothesisShapeFromRecord:
    def test_reads_real_protocol_and_retracted_status(self):
        record = {"memory_id": "MEM-1", "status": "RETRACTED", "root_cause": "x",
                  "protocol": "USB3"}
        shape = inf.domain_hypothesis_shape_from_record(record)
        assert shape == {"hypothesis_id": "MEM-1", "retracted": True, "domain": "USB3"}

    def test_no_protocol_is_honestly_none_never_guessed(self):
        record = {"memory_id": "MEM-2", "status": "ACTIVE", "root_cause": "y"}
        shape = inf.domain_hypothesis_shape_from_record(record)
        assert shape["domain"] is None

    def test_superseded_is_never_counted_as_retracted(self):
        record = {"memory_id": "MEM-3", "status": "SUPERSEDED", "protocol": "PCIe"}
        shape = inf.domain_hypothesis_shape_from_record(record)
        assert shape["retracted"] is False
        assert shape["domain"] == "PCIe"

    def test_requires_memory_id(self):
        with pytest.raises(ValueError):
            inf.domain_hypothesis_shape_from_record({"status": "ACTIVE"})


class TestCollectDomainHypothesisShapes:
    def test_reads_real_memorystore_records_preserving_protocol(self, tmp_path):
        from dv_harness.memory import MemoryStore, MemoryGC

        store = MemoryStore(tmp_path)
        mem1 = store.add("engineering", {
            "kind": "root_cause", "root_cause": "bad clock domain crossing",
            "protocol": "USB3", "confidence": "HIGH",
        })
        mem2 = store.add("engineering", {
            "kind": "verified_fix", "root_cause": "fifo overflow",
            "protocol": "PCIe", "confidence": "HIGH",
        })
        gc = MemoryGC(store)
        gc.retract(mem1["memory_id"], "found wrong: real cause was elsewhere",
                   evidence={"note": "re-derived"})

        shapes = inf.collect_domain_hypothesis_shapes(tmp_path, store=store)
        by_id = {s["hypothesis_id"]: s for s in shapes}
        assert by_id[mem1["memory_id"]] == {
            "hypothesis_id": mem1["memory_id"], "retracted": True, "domain": "USB3",
        }
        assert by_id[mem2["memory_id"]] == {
            "hypothesis_id": mem2["memory_id"], "retracted": False, "domain": "PCIe",
        }

    def test_bare_project_with_no_memory_store_returns_empty_and_creates_nothing(self, tmp_path):
        """A pure read for a project's own domain track record must never bring a memory
        store into existence merely by asking about it (the same guard confidence_
        calibration.py/cross_project_mining.py already apply for the identical reason)."""
        shapes = inf.collect_domain_hypothesis_shapes(tmp_path)
        assert shapes == []
        assert not (tmp_path / ".dv-harness").exists()

    def test_constructs_its_own_store_when_one_already_exists(self, tmp_path):
        from dv_harness.memory import MemoryStore

        store = MemoryStore(tmp_path)
        store.add("engineering", {"kind": "debug_lesson", "root_cause": "reset ordering bug",
                                   "protocol": "AMBA"})

        shapes = inf.collect_domain_hypothesis_shapes(tmp_path)
        assert len(shapes) == 1
        assert shapes[0]["domain"] == "AMBA"


class TestDomainWrongHypothesisTrackRecord:
    @staticmethod
    def _shapes(domain_and_retracted):
        return [
            {"hypothesis_id": f"H{i}", "retracted": retracted, "domain": domain}
            for i, (domain, retracted) in enumerate(domain_and_retracted)
        ]

    def test_no_hypotheses_supplied_is_honestly_not_available(self):
        report = inf.domain_wrong_hypothesis_track_record([], "USB3")
        assert report["status"] == inf.BIAS_STATUS_NOT_AVAILABLE
        assert report["reason"] == "NO_HYPOTHESES_SUPPLIED"

    def test_insufficient_history_when_either_group_is_too_small(self):
        # only 2 USB3 hypotheses (below the reused min_group_size floor of 5),
        # even though the "other" group is comfortably large.
        shapes = self._shapes(
            [("USB3", True), ("USB3", False)]
            + [("PCIe", False)] * 10
        )
        report = inf.domain_wrong_hypothesis_track_record(shapes, "USB3")
        assert report["status"] == inf.BIAS_STATUS_INSUFFICIENT_HISTORY
        assert report["matching_count"] == 2
        assert report["other_count"] == 10
        assert report["matching_wrong_rate"] is None

    def test_bias_detected_when_domain_is_meaningfully_worse_than_the_rest(self):
        # USB3: 4/5 retracted (0.8) vs. every other domain combined: 0/10 (0.0).
        # gap 0.8 > the reused 0.2 margin -> BIAS_DETECTED.
        shapes = self._shapes(
            [("USB3", True)] * 4 + [("USB3", False)]
            + [("PCIe", False)] * 10
        )
        report = inf.domain_wrong_hypothesis_track_record(shapes, "USB3")
        assert report["status"] == inf.BIAS_STATUS_BIAS_DETECTED
        assert report["matching_wrong_rate"] == 0.8
        assert report["other_wrong_rate"] == 0.0
        assert "USB3" in report["reason"]

    def test_no_bias_detected_when_rates_are_close(self):
        # USB3: 1/5 retracted (0.2) vs. the rest: 2/10 (0.2) -- identical rate, no gap.
        shapes = self._shapes(
            [("USB3", True)] + [("USB3", False)] * 4
            + [("PCIe", True)] * 2 + [("PCIe", False)] * 8
        )
        report = inf.domain_wrong_hypothesis_track_record(shapes, "USB3")
        assert report["status"] == inf.BIAS_STATUS_NO_BIAS_DETECTED
        assert report["margin_observed"] == 0.0

    def test_a_domain_scoring_better_than_average_is_also_no_bias_detected(self):
        """This function only ever flags a domain WORSE than the rest -- a domain that is
        BETTER than average is never read as a reason to increase effort either."""
        # USB3: 0/5 retracted (0.0) vs. the rest: 8/10 (0.8).
        shapes = self._shapes(
            [("USB3", False)] * 5
            + [("PCIe", True)] * 8 + [("PCIe", False)] * 2
        )
        report = inf.domain_wrong_hypothesis_track_record(shapes, "USB3")
        assert report["status"] == inf.BIAS_STATUS_NO_BIAS_DETECTED

    def test_hypotheses_with_no_recorded_domain_are_excluded_from_both_groups(self):
        """A hypothesis with domain=None (no recorded protocol at all) contributes to
        NEITHER comparison group -- it must never silently pad the "other" group's count
        or dilute its rate."""
        shapes = (
            self._shapes([("USB3", True)] * 4 + [("USB3", False)] + [("PCIe", False)] * 10)
            + [{"hypothesis_id": "H-none-1", "retracted": True, "domain": None},
               {"hypothesis_id": "H-none-2", "retracted": False, "domain": None}]
        )
        report = inf.domain_wrong_hypothesis_track_record(shapes, "USB3")
        assert report["matching_count"] == 5
        assert report["other_count"] == 10
        assert report["status"] == inf.BIAS_STATUS_BIAS_DETECTED

    def test_domain_matching_is_case_insensitive(self):
        shapes = self._shapes([("usb3", True)] * 4 + [("USB3", False)] + [("PCIe", False)] * 10)
        report = inf.domain_wrong_hypothesis_track_record(shapes, "USB3")
        assert report["matching_count"] == 5

    def test_rejects_non_list_input(self):
        with pytest.raises(ValueError):
            inf.domain_wrong_hypothesis_track_record("not a list", "USB3")

    def test_rejects_a_non_dict_entry(self):
        with pytest.raises(ValueError):
            inf.domain_wrong_hypothesis_track_record(["not a dict"], "USB3")

    def test_rejects_a_non_bool_retracted_field(self):
        with pytest.raises(ValueError):
            inf.domain_wrong_hypothesis_track_record(
                [{"hypothesis_id": "H1", "retracted": "yes", "domain": "USB3"}], "USB3",
            )

    def test_rejects_a_blank_domain(self):
        with pytest.raises(ValueError):
            inf.domain_wrong_hypothesis_track_record([], "   ")

    def test_rejects_invalid_min_group_size(self):
        with pytest.raises(ValueError):
            inf.domain_wrong_hypothesis_track_record([], "USB3", min_group_size=0)
        with pytest.raises(ValueError):
            inf.domain_wrong_hypothesis_track_record([], "USB3", min_group_size=True)

    def test_rejects_invalid_margin(self):
        with pytest.raises(ValueError):
            inf.domain_wrong_hypothesis_track_record([], "USB3", margin=1.5)
        with pytest.raises(ValueError):
            inf.domain_wrong_hypothesis_track_record([], "USB3", margin=False)


class TestRecommendEvidenceGatheringEffort:
    def test_no_signals_at_all_stays_at_the_neutral_standard_baseline(self):
        """Absence of real history is never read as license to use fewer agents."""
        result = inf.recommend_evidence_gathering_effort()
        assert result["recommended_evidence_gathering_effort"] == "STANDARD"
        assert result["recommended_min_independent_agents"] == 2
        assert "disclosure" in result and "ADVISORY ONLY" in result["disclosure"]

    def test_diverging_source_authority_history_recommends_thorough(self):
        result = inf.recommend_evidence_gathering_effort(
            source_authority_report={
                "status": "ORDER_DIVERGES_FROM_PRACTICE", "mismatches": 3, "evaluable_cases": 5,
            }
        )
        assert result["recommended_evidence_gathering_effort"] == "THOROUGH"
        assert result["recommended_min_independent_agents"] == 3
        assert result["signals"]["source_authority_contentiousness"]["effort_level"] == "THOROUGH"

    def test_matching_source_authority_history_recommends_minimal(self):
        # the source-authority signal itself resolves to MINIMAL; the OTHER (unsupplied)
        # signal stays at the neutral STANDARD baseline, so the fold's overall result is
        # STANDARD -- absence of the second signal is never read as "safe", it only ever
        # holds the recommendation at neutral, never drags it down to match the clean one.
        result = inf.recommend_evidence_gathering_effort(
            source_authority_report={
                "status": "ORDER_MATCHES_PRACTICE", "mismatches": 0, "evaluable_cases": 4,
            }
        )
        assert result["signals"]["source_authority_contentiousness"]["effort_level"] == "MINIMAL"
        assert result["recommended_evidence_gathering_effort"] == "STANDARD"

    def test_overall_minimal_requires_both_signals_to_independently_agree(self):
        result = inf.recommend_evidence_gathering_effort(
            source_authority_report={
                "status": "ORDER_MATCHES_PRACTICE", "mismatches": 0, "evaluable_cases": 4,
            },
            domain_track_record={
                "status": inf.BIAS_STATUS_NO_BIAS_DETECTED, "domain": "USB3",
                "matching_wrong_rate": 0.2, "other_wrong_rate": 0.2,
            },
        )
        assert result["recommended_evidence_gathering_effort"] == "MINIMAL"
        assert result["recommended_min_independent_agents"] == 1

    def test_no_evaluable_cases_report_stays_at_standard(self):
        result = inf.recommend_evidence_gathering_effort(
            source_authority_report={"status": "NO_EVALUABLE_CASES"}
        )
        assert result["recommended_evidence_gathering_effort"] == "STANDARD"

    def test_domain_bias_detected_recommends_thorough(self):
        result = inf.recommend_evidence_gathering_effort(
            domain_track_record={
                "status": inf.BIAS_STATUS_BIAS_DETECTED, "domain": "USB3",
                "reason": "hypotheses for domain 'USB3' were retracted 80% of the time",
                "matching_wrong_rate": 0.8, "other_wrong_rate": 0.0,
            }
        )
        assert result["recommended_evidence_gathering_effort"] == "THOROUGH"
        assert result["signals"]["domain_wrong_hypothesis_track_record"]["effort_level"] == "THOROUGH"

    def test_domain_no_bias_recommends_minimal(self):
        # again, the domain signal itself resolves to MINIMAL; the overall recommendation
        # stays at the neutral STANDARD baseline because the OTHER signal was not supplied
        # (see test_overall_minimal_requires_both_signals_to_independently_agree above).
        result = inf.recommend_evidence_gathering_effort(
            domain_track_record={
                "status": inf.BIAS_STATUS_NO_BIAS_DETECTED, "domain": "USB3",
                "matching_wrong_rate": 0.2, "other_wrong_rate": 0.2,
            }
        )
        assert result["signals"]["domain_wrong_hypothesis_track_record"]["effort_level"] == "MINIMAL"
        assert result["recommended_evidence_gathering_effort"] == "STANDARD"

    def test_insufficient_domain_history_stays_at_standard(self):
        result = inf.recommend_evidence_gathering_effort(
            domain_track_record={
                "status": inf.BIAS_STATUS_INSUFFICIENT_HISTORY, "domain": "USB3",
                "reason": "matching_count=2, other_count=10",
            }
        )
        assert result["recommended_evidence_gathering_effort"] == "STANDARD"

    def test_worst_wins_never_averaged_across_the_two_signals(self):
        """One THOROUGH-worthy signal must outrank an otherwise-clean MINIMAL signal --
        never averaged into something in between."""
        result = inf.recommend_evidence_gathering_effort(
            source_authority_report={
                "status": "ORDER_MATCHES_PRACTICE", "mismatches": 0, "evaluable_cases": 4,
            },
            domain_track_record={
                "status": inf.BIAS_STATUS_BIAS_DETECTED, "domain": "USB3",
                "reason": "elevated wrong-hypothesis rate",
            },
        )
        assert result["recommended_evidence_gathering_effort"] == "THOROUGH"
        assert result["recommended_min_independent_agents"] == 3
        assert result["signals"]["source_authority_contentiousness"]["effort_level"] == "MINIMAL"
        assert result["signals"]["domain_wrong_hypothesis_track_record"]["effort_level"] == "THOROUGH"

    def test_never_dispatches_or_writes_anything(self):
        """A pure recommendation -- calling it repeatedly with the same inputs must never
        touch a filesystem or a memory/question-queue store."""
        import inspect

        source = inspect.getsource(inf.recommend_evidence_gathering_effort)
        for forbidden in ("subprocess", "Popen", "run_stage", "add_question", "MemoryGC(",
                          "store.add(", "answer_question("):
            assert forbidden not in source

    def test_domain_omitted_never_computes_a_domain_signal_even_with_a_real_root(self, tmp_path):
        from dv_harness.memory import MemoryStore

        store = MemoryStore(tmp_path)
        store.add("engineering", {"kind": "root_cause", "root_cause": "x", "protocol": "USB3"})
        result = inf.recommend_evidence_gathering_effort(root=tmp_path)
        assert result["signals"]["domain_wrong_hypothesis_track_record"]["report"] is None

    def test_end_to_end_over_a_bare_project_root_stays_neutral_and_creates_nothing(self, tmp_path):
        """No pre-built reports, a real (but bare) project root, and a domain: both real
        signals are computed from scratch and both honestly report absence of history --
        the recommendation stays STANDARD, and nothing is created on disk."""
        result = inf.recommend_evidence_gathering_effort(root=tmp_path, domain="USB3")
        assert result["recommended_evidence_gathering_effort"] == "STANDARD"
        assert not (tmp_path / ".dv-harness").exists()

    def test_end_to_end_real_source_authority_history_drives_the_recommendation(self, tmp_path):
        """Real source_authority_order_validation machinery, never a hand-shaped stand-in:
        a real escalate_conflict() + a real human override answer must actually be picked
        up by build_report(root) and drive this function's recommendation to THOROUGH."""
        from dv_harness import question_queue as qq
        from dv_harness import source_authority as sa

        qq.QuestionQueueStore(tmp_path)
        conflict = sa.resolve_conflict([
            sa.SourceClaim("dut_rtl", "base = 0x1272_0000", "rtl/decoder.sv:118"),
            sa.SourceClaim("controller_doc", "base = 0x1272_8000", "Doc/regs.md:88"),
        ])
        rec = sa.escalate_conflict(tmp_path, conflict, domain="dut", subject="base address")
        qq.QuestionQueueStore(tmp_path).answer_question(
            rec["id"], answer="per Doc/regs.md:88 the doc is right, RTL had a known bug",
            basis="human review", decided_by="reviewer",
        )

        result = inf.recommend_evidence_gathering_effort(root=tmp_path)
        assert result["recommended_evidence_gathering_effort"] == "THOROUGH"
        report = result["signals"]["source_authority_contentiousness"]["report"]
        assert report["status"] == "ORDER_DIVERGES_FROM_PRACTICE"

    def test_end_to_end_real_domain_track_record_drives_the_recommendation(self, tmp_path):
        """Real MemoryStore/MemoryGC machinery: a real, elevated per-domain retraction rate
        must actually be picked up by collect_domain_hypothesis_shapes()/domain_wrong_
        hypothesis_track_record() and drive this function's recommendation to THOROUGH."""
        from dv_harness.memory import MemoryStore, MemoryGC

        store = MemoryStore(tmp_path)
        gc = MemoryGC(store)
        usb3_ids = []
        for i in range(5):
            mem = store.add("engineering", {
                "kind": "root_cause", "root_cause": f"usb3 hypothesis {i}",
                "protocol": "USB3", "confidence": "HIGH",
            })
            usb3_ids.append(mem["memory_id"])
        for i in range(10):
            store.add("engineering", {
                "kind": "root_cause", "root_cause": f"pcie hypothesis {i}",
                "protocol": "PCIe", "confidence": "HIGH",
            })
        for mid in usb3_ids[:4]:
            gc.retract(mid, "found wrong", evidence={"note": "re-derived"})

        result = inf.recommend_evidence_gathering_effort(root=tmp_path, domain="USB3")
        assert result["recommended_evidence_gathering_effort"] == "THOROUGH"
        report = result["signals"]["domain_wrong_hypothesis_track_record"]["report"]
        assert report["status"] == inf.BIAS_STATUS_BIAS_DETECTED
        assert report["matching_wrong_rate"] == 0.8
