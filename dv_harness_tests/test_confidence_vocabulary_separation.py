"""The three trust-ranking mechanisms in this codebase are deliberately NOT
one mechanism, and this file is what keeps that a decided question instead of
something the next auditor re-derives from scratch.

A 2026-09-04 re-audit of mechanism #1 (Autonomous Inference Engine) confirmed
`dv_harness/inference.py` is wired and firing on the real production path
(`dv_harness_tests/test_react_inference_wiring.py` proves that half), and then
raised a secondary question: `connectivity.classify_bind_tier()` and
`question_queue.classify_tier()` are two more "how much can this be trusted"
classifiers, built 2026-09-03 -- the day BEFORE inference.py got its first real
caller -- and neither references inference.py at all. Is that the
reference_pattern lesson ("do not build a second X") going unlearned?

It is not, and these tests state why in executable form rather than in prose a
future reader would have to take on faith:

  - score_confidence() scores evidence QUANTITY (additive counts).
  - Both tier classifiers rank evidence KIND / decision AUTHORITY, in a strict
    priority order that no count may reorder.

test_bind_tier_ordering_is_not_expressible_as_a_confidence_score() and
test_question_queue_tier3_is_an_escalation_route_not_a_low_score() below
demonstrate the incompatibility with real calls into all three modules, so the
claim is checked, not asserted. The remaining tests keep the vocabularies
disjoint and keep the written rationale physically present in each module.
"""

import re
from pathlib import Path

from dv_harness import connectivity, inference, question_queue

_SRC = Path(__file__).resolve().parents[1] / "dv_harness"


# --- The substantive claim: the orderings genuinely disagree -----------------

def test_bind_tier_ordering_is_not_expressible_as_a_confidence_score():
    """T1 strictly outranks T2 in the real classifier, but the most generous
    honest mapping of each tier's own evidence onto score_confidence()'s four
    counts scores them IDENTICALLY -- so routing bind tiers through
    score_confidence() would erase the T1 > T2 ordering the classifier exists
    to enforce. Real calls into both modules, no mocks."""
    t1 = connectivity.classify_bind_tier(
        existing_bind={"target_instance": "chip.core.usb0", "ports": ["clk", "rst_n"]},
    )
    t2 = connectivity.classify_bind_tier(
        structural_match={"matched": True, "protocol": "usb3",
                          "matched_signals": ["utmi_clk", "utmi_data", "utmi_valid"]},
    )
    assert t1.tier is connectivity.BindTier.T1_ALREADY_DECIDED
    assert t2.tier is connectivity.BindTier.T2_STRUCTURAL_MATCH
    # The classifier's own ordering: both auto-acceptable, but T1 is
    # "already decided, no re-litigation" and T2 is "still listed for
    # visibility" -- they are not interchangeable.
    assert t1.auto_acceptable and t2.auto_acceptable
    assert t1.tier.value < t2.tier.value  # "T1_..." sorts before "T2_..."

    # One existing bind = one verified independent source.
    t1_scored = inference.score_confidence(
        independent_sources_count=1, evidence_refs_verified=True,
        counter_evidence_count=0, multi_agent_consensus_count=0,
    )
    # Three fingerprint signals from one structural match are still ONE
    # independent source -- counting each matched signal separately would be
    # inventing corroboration that does not exist.
    t2_scored = inference.score_confidence(
        independent_sources_count=1, evidence_refs_verified=True,
        counter_evidence_count=0, multi_agent_consensus_count=0,
    )
    assert t1_scored["level"] == t2_scored["level"] == "MEDIUM"
    assert t1_scored["score"] == t2_scored["score"] == 4

    # Even counting each matched signal as its own source -- the most
    # generous mapping available -- inverts the ordering rather than
    # preserving it: T2 would outrank T1.
    t2_overcounted = inference.score_confidence(
        independent_sources_count=3, evidence_refs_verified=True,
        counter_evidence_count=0, multi_agent_consensus_count=0,
    )
    assert t2_overcounted["level"] == "HIGH"
    assert t2_overcounted["score"] > t1_scored["score"]


def test_question_queue_tier3_is_an_escalation_route_not_a_low_score():
    """Tier 3 is reached from a hard trigger about authority/blast radius, and
    corroborating evidence must never downgrade it. score_confidence() has no
    term that can express that, so expressing this decision through it would
    make a well-evidenced spec-intent question auto-assumable."""
    result = question_queue.classify_tier({
        "domain": "spec_intent",
        "affects_spec_intent": True,
        "blast_radius": "single_regression",
    })
    assert result["tier"] == question_queue.TIER3_CANNOT_ASSUME
    assert "affects_spec_intent" in result["matched_triggers"]

    # The same question, richly corroborated. score_confidence() reports HIGH;
    # the tier is unchanged, because the two answer different questions.
    scored = inference.score_confidence(
        independent_sources_count=3, evidence_refs_verified=True,
        counter_evidence_count=0, multi_agent_consensus_count=2,
    )
    assert scored["level"] == "HIGH"
    still_tier3 = question_queue.classify_tier({
        "domain": "spec_intent",
        "affects_spec_intent": True,
        "blast_radius": "single_regression",
    })
    assert still_tier3["tier"] == question_queue.TIER3_CANNOT_ASSUME


# --- The vocabularies stay disjoint -----------------------------------------

def test_no_token_is_shared_between_the_three_vocabularies():
    """Same discipline protocol_capability.py's `capability_status` keeps
    against qualification.py's tier ladder: one collapsed label that tries to
    answer two questions answers at least one of them wrongly, and a shared
    token is how the collapse starts."""
    confidence = set(inference.CONFIDENCE_LEVELS)
    bind_tiers = {t.value for t in connectivity.BindTier}
    qq_tiers = set(question_queue.TIER_NAMES.values())

    assert confidence & bind_tiers == set()
    assert confidence & qq_tiers == set()
    assert bind_tiers & qq_tiers == set()

    # Not merely disjoint as whole strings: no confidence level appears as a
    # substring of a tier name either (a "HIGH_CONFIDENCE_MATCH" tier would
    # defeat the point while passing a set-disjointness check).
    for level in confidence:
        for name in bind_tiers | qq_tiers:
            assert level not in name.upper()


def test_neither_tier_classifier_imports_the_inference_engine():
    """The audit's own verification step, kept as a test: if either module
    ever grows an `inference` import, that is a real design change and must be
    made deliberately (updating the rationale below), not by accident."""
    for module in ("connectivity.py", "question_queue.py"):
        src = (_SRC / module).read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from\s+\.?\S*inference\S*\s+import|import\s+\S*inference)",
                             src, re.MULTILINE), (
            f"{module} now imports inference.py -- see this test's docstring")


# --- The rationale cannot be silently deleted -------------------------------

def test_each_module_carries_the_written_rationale_for_the_separation():
    """A future auditor's first move is to grep for whether the distinction was
    ever considered. These three anchors are what that grep must find."""
    inference_src = (_SRC / "inference.py").read_text(encoding="utf-8")
    assert "classify_bind_tier" in inference_src
    assert "classify_tier" in inference_src
    assert "test_confidence_vocabulary_separation" in inference_src

    connectivity_src = (_SRC / "connectivity.py").read_text(encoding="utf-8")
    assert "score_confidence" in connectivity_src
    assert "test_confidence_vocabulary_separation" in connectivity_src

    qq_src = (_SRC / "question_queue.py").read_text(encoding="utf-8")
    assert "score_confidence" in qq_src
    assert "test_confidence_vocabulary_separation" in qq_src


def test_capability_evolution_is_the_counterexample_that_did_reuse_inference():
    """The separation above is a semantic judgment, not a blanket "never reuse
    inference.py". capability_evolution.py -- a genuinely non-DV-protocol
    caller whose decision IS a confidence score -- reuses the real functions
    and extended next_best_action() with `gap_action_catalog` rather than
    duplicating its matching logic. If that ever stops being true, the
    separation above loses its contrast case and should be re-examined."""
    cap_src = (_SRC / "capability_evolution.py").read_text(encoding="utf-8")
    assert re.search(r"from\s+\.inference\s+import", cap_src)
    assert "gap_action_catalog" in cap_src

    import inspect
    assert "gap_action_catalog" in inspect.signature(inference.next_best_action).parameters
