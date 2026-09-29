"""Wiring gap-close: rca_ontology.classify_root_cause_category_checked(),
inference.score_confidence_checked(), and source_authority.resolve_conflict_checked()
each now check human_correction_lesson.has_prior_correction() for the EXACT
judgment they are about to recompute and re-emit, before recomputing it.

Every fixture writes a REAL structured correction record through the REAL
record_human_correction_lesson() -> memory_router.route_and_store() ->
dv_harness.memory.MemoryStore chain -- never a hand-written JSON file shaped
to look like one, matching test_human_correction_lesson.py's own established
discipline.

Negative controls prove the mechanism actually checks rather than merely
being present: an unrelated text/judgment/subject with no prior correction
on file must never report `found`, and a corrected judgment must never have
its own recomputed value silently overridden -- only `prior_human_correction`
is attached; the deterministic computation itself is untouched.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness.human_correction_lesson import record_human_correction_lesson
from dv_harness.inference import (
    CONFIDENCE_SCORE_MISTAKE_CATEGORY,
    score_confidence,
    score_confidence_checked,
)
from dv_harness.rca_ontology import (
    CATEGORY_CLASSIFICATION_MISTAKE_CATEGORY,
    classify_root_cause_category,
    classify_root_cause_category_checked,
)
from dv_harness.source_authority import (
    CONFLICT_RESOLUTION_MISTAKE_CATEGORY,
    SourceClaim,
    resolve_conflict,
    resolve_conflict_checked,
)


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _record(root, *, before_claim, mistake_category, after_claim="corrected value",
            evidence="doc.md:1", corrected_by="reviewer"):
    return record_human_correction_lesson(
        root,
        before_claim=before_claim,
        after_claim=after_claim,
        correction_evidence=evidence,
        corrected_by=corrected_by,
        mistake_category=mistake_category,
        cfg={},
    )


# ---------------------------------------------------------------------------
# rca_ontology.classify_root_cause_category_checked()
# ---------------------------------------------------------------------------

def test_classify_checked_matches_plain_function_when_no_correction_on_file(root):
    text = "rtl bug found in the FSM"
    checked = classify_root_cause_category_checked(text, root)
    plain = classify_root_cause_category(text)
    assert checked.category == plain.category == "DUT_RTL_DEFECT"
    assert checked.prior_human_correction is None


def test_classify_checked_surfaces_a_real_prior_correction_for_the_exact_text(root):
    text = "rtl bug found in the FSM"
    result = _record(
        root, before_claim=text, mistake_category=CATEGORY_CLASSIFICATION_MISTAKE_CATEGORY,
        after_claim="this was actually a testbench monitor bug, not RTL",
    )
    assert result["destination"] == "ENGINEERING_MEMORY"

    checked = classify_root_cause_category_checked(text, root)
    # the deterministic recomputation is NEVER overridden by the correction
    assert checked.category == "DUT_RTL_DEFECT"
    assert checked.prior_human_correction is not None
    assert checked.prior_human_correction["found"] is True
    assert checked.prior_human_correction["count"] == 1
    matches = checked.prior_human_correction["matches"]
    assert matches[0]["correction"]["after"]["claim"] == "this was actually a testbench monitor bug, not RTL"


def test_classify_checked_negative_control_unrelated_text_never_flagged(root):
    # A correction exists, but for a DIFFERENT text -- must never bleed over.
    _record(
        root, before_claim="rtl bug found in the FSM",
        mistake_category=CATEGORY_CLASSIFICATION_MISTAKE_CATEGORY,
    )
    checked = classify_root_cause_category_checked("vip bug in the sequence library", root)
    assert checked.category == "VIP_DEFECT_OR_MISCONFIGURATION"
    assert checked.prior_human_correction is None


def test_classify_checked_negative_control_wrong_mistake_category_never_flagged(root):
    # Same before_claim text, but filed under a DIFFERENT mistake_category
    # (e.g. a human correction of some OTHER judgment about this text) --
    # the exact-match key must not cross categories.
    text = "rtl bug found in the FSM"
    _record(root, before_claim=text, mistake_category="some_other_unrelated_judgment")
    checked = classify_root_cause_category_checked(text, root)
    assert checked.prior_human_correction is None


def test_classify_checked_empty_text_never_queries(root):
    checked = classify_root_cause_category_checked("", root)
    assert checked.category == "UNCLASSIFIED"
    assert checked.prior_human_correction is None
    checked_none = classify_root_cause_category_checked(None, root)
    assert checked_none.category == "UNCLASSIFIED"
    assert checked_none.prior_human_correction is None


# ---------------------------------------------------------------------------
# inference.score_confidence_checked()
# ---------------------------------------------------------------------------

def test_score_confidence_checked_matches_plain_function_when_no_correction_on_file(root):
    checked = score_confidence_checked(3, True, 0, 2, root=root, judgment_key="usb3/lfps_timeout")
    plain = score_confidence(3, True, 0, 2)
    assert checked["level"] == plain["level"] == "HIGH"
    assert checked["score"] == plain["score"]
    assert "prior_human_correction" not in checked


def test_score_confidence_checked_surfaces_a_real_prior_correction(root):
    judgment_key = "usb3/lfps_timeout"
    # score_confidence(3, True, 0, 2) -> level HIGH, so the before-claim the
    # checked function will look up is exactly this string.
    before_claim = f"{judgment_key}: confidence=HIGH"
    _record(
        root, before_claim=before_claim, mistake_category=CONFIDENCE_SCORE_MISTAKE_CATEGORY,
        after_claim="the counter-evidence was never actually addressed; this should be MEDIUM",
    )
    checked = score_confidence_checked(3, True, 0, 2, root=root, judgment_key=judgment_key)
    # the deterministic recomputation is NEVER overridden by the correction
    assert checked["level"] == "HIGH"
    assert checked["score"] == 10
    assert checked["prior_human_correction"]["found"] is True
    assert checked["prior_human_correction"]["count"] == 1


def test_score_confidence_checked_negative_control_different_judgment_key_never_flagged(root):
    before_claim = "usb3/lfps_timeout: confidence=HIGH"
    _record(root, before_claim=before_claim, mistake_category=CONFIDENCE_SCORE_MISTAKE_CATEGORY)
    checked = score_confidence_checked(
        3, True, 0, 2, root=root, judgment_key="pcie/ltssm_stuck_recovery",
    )
    assert "prior_human_correction" not in checked


def test_score_confidence_checked_negative_control_different_recomputed_level_never_flagged(root):
    # Correction on file is keyed to a HIGH-level assertion for this exact
    # judgment_key; a call whose inputs recompute to a DIFFERENT level must
    # not match it (the before_claim text embeds the level).
    judgment_key = "usb3/lfps_timeout"
    _record(
        root, before_claim=f"{judgment_key}: confidence=HIGH",
        mistake_category=CONFIDENCE_SCORE_MISTAKE_CATEGORY,
    )
    checked = score_confidence_checked(0, False, 2, 0, root=root, judgment_key=judgment_key)
    assert checked["level"] == "LOW"
    assert "prior_human_correction" not in checked


# ---------------------------------------------------------------------------
# source_authority.resolve_conflict_checked()
# ---------------------------------------------------------------------------

def _conflicting_claims():
    return [
        SourceClaim(source="dut_rtl", claim="reset is active-low", evidence_path="rtl/top.v:42"),
        SourceClaim(source="controller_doc", claim="reset is active-high", evidence_path="doc.md:9"),
    ]


def test_resolve_conflict_checked_matches_plain_function_when_no_correction_on_file(root):
    claims = _conflicting_claims()
    checked = resolve_conflict_checked(claims, root=root, subject="top-level reset polarity")
    plain = resolve_conflict(claims)
    assert checked["verdict"] == plain["verdict"] == "RESOLVED"
    assert checked["winner"]["source"] == plain["winner"]["source"] == "dut_rtl"
    assert "prior_human_correction" not in checked


def test_resolve_conflict_checked_surfaces_a_real_prior_correction(root):
    subject = "top-level reset polarity"
    before_claim = "top-level reset polarity: resolved to dut_rtl claim: reset is active-low"
    _record(
        root, before_claim=before_claim, mistake_category=CONFLICT_RESOLUTION_MISTAKE_CATEGORY,
        after_claim="the RTL comment was stale; the doc was actually right this time",
    )
    checked = resolve_conflict_checked(_conflicting_claims(), root=root, subject=subject)
    # the ranked verdict is NEVER overridden by the correction
    assert checked["verdict"] == "RESOLVED"
    assert checked["winner"]["source"] == "dut_rtl"
    assert checked["prior_human_correction"]["found"] is True
    assert checked["prior_human_correction"]["count"] == 1


def test_resolve_conflict_checked_negative_control_different_subject_never_flagged(root):
    before_claim = "top-level reset polarity: resolved to dut_rtl claim: reset is active-low"
    _record(root, before_claim=before_claim, mistake_category=CONFLICT_RESOLUTION_MISTAKE_CATEGORY)
    checked = resolve_conflict_checked(
        _conflicting_claims(), root=root, subject="a completely different fact",
    )
    assert "prior_human_correction" not in checked


def test_resolve_conflict_checked_never_queries_when_verdict_has_no_winner(root):
    # UNDECIDABLE_SAME_AUTHORITY (both claims at the same tier) has no
    # winner, so there is no single judgment for a human to have corrected.
    same_tier_claims = [
        SourceClaim(source="vip_document", claim="A", evidence_path="a.pdf:1"),
        SourceClaim(source="vip_document", claim="B", evidence_path="b.pdf:1"),
    ]
    checked = resolve_conflict_checked(same_tier_claims, root=root, subject="whatever")
    assert checked["verdict"] == "UNDECIDABLE_SAME_AUTHORITY"
    assert "prior_human_correction" not in checked
