"""Signoff bundle SECOND REVIEWER mechanism (2026-09-07 gap closure, item id
"no-second-reviewer-mechanism-at-signoff-scope").

Before this: `control_plane.ControlPlane.approvals[stage]` held exactly ONE
reviewer entry per stage, overwritten (archived, but never concurrent) on
every fresh `approve()` call, and `question_queue.QuestionQueueStore.
add_decision_cosign()` co-signs one already-recorded Tier-3 intake DECISION
keyed on its own exact answer text -- a different object entirely from a
whole `signoff_export.py` evidence bundle. Neither covered a second human
independently reviewing the WHOLE signoff evidence bundle before it is
approved.

Tests here drive the REAL, persisted machinery:
`ControlPlane.add_bundle_review()`/`get_bundle_reviews()`/
`has_independent_bundle_review()`/`assert_bundle_second_review_satisfied()`
against a real `control.json` on disk, and
`signoff_export.bundle_second_review_status()` -- the pure function a
caller composes with an already-fetched `reviews` list, preserving
`signoff_export.py`'s own "touches no approval machinery" boundary. Negative
controls (missing fields, an invalid confidence level, a stale bundle_hash,
the same person reviewing and approving) are what give the positive
assertions detection power.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dv_harness.control_plane import (
    ControlPlane,
    SecondReviewerRequiredError,
)
from dv_harness import signoff_export


def _manifest(tag: str = "v1"):
    return [
        {"artifact": "manifest.json", "present": True, "bundled_path": f"manifest_{tag}.json"},
        {"artifact": "tb_source", "present": True, "bundled_path": "tb_source"},
    ]


# ---------------------------------------------------------------------------
# ControlPlane.add_bundle_review() / get_bundle_reviews()
# ---------------------------------------------------------------------------

def test_add_bundle_review_persists_a_real_additive_record(tmp_path: Path):
    cp = ControlPlane(tmp_path)
    bundle_hash = signoff_export.compute_bundle_hash(_manifest())

    entry = cp.add_bundle_review(
        "SIGNOFF", bundle_hash, reviewer_id="alice@example.com",
        note="reviewed the tb_source diff", reviewer_confidence="HIGH",
    )
    assert entry["bundle_hash"] == bundle_hash
    assert entry["reviewer_id"] == "alice@example.com"
    assert entry["reviewer_confidence"] == "HIGH"
    assert entry["reviewed_at"]

    # Real disk persistence: a FRESH ControlPlane instance over the same
    # root sees the same review, not merely an in-memory artifact of the
    # first instance.
    cp2 = ControlPlane(tmp_path)
    reviews = cp2.get_bundle_reviews("SIGNOFF", bundle_hash)
    assert len(reviews) == 1
    assert reviews[0]["reviewer_id"] == "alice@example.com"


def test_add_bundle_review_is_additive_never_overwritten(tmp_path: Path):
    """The whole point of this mechanism: a second (third, ...) reviewer's
    record must never silently replace an earlier one, unlike approve()'s
    single-slot approvals[stage]."""
    cp = ControlPlane(tmp_path)
    bundle_hash = signoff_export.compute_bundle_hash(_manifest())

    cp.add_bundle_review("SIGNOFF", bundle_hash, reviewer_id="alice@example.com")
    cp.add_bundle_review("SIGNOFF", bundle_hash, reviewer_id="bob@example.com")
    cp.add_bundle_review("SIGNOFF", bundle_hash, reviewer_id="carol@example.com")

    reviews = cp.get_bundle_reviews("SIGNOFF", bundle_hash)
    assert [r["reviewer_id"] for r in reviews] == [
        "alice@example.com", "bob@example.com", "carol@example.com",
    ]


def test_get_bundle_reviews_is_scoped_to_the_exact_bundle_hash(tmp_path: Path):
    """A bundle re-exported with different content gets a different
    bundle_hash -- a review of the OLD content must never look like a
    review of the NEW content."""
    cp = ControlPlane(tmp_path)
    hash_v1 = signoff_export.compute_bundle_hash(_manifest("v1"))
    hash_v2 = signoff_export.compute_bundle_hash(_manifest("v2"))
    assert hash_v1 != hash_v2

    cp.add_bundle_review("SIGNOFF", hash_v1, reviewer_id="alice@example.com")

    assert len(cp.get_bundle_reviews("SIGNOFF", hash_v1)) == 1
    assert cp.get_bundle_reviews("SIGNOFF", hash_v2) == []


def test_get_bundle_reviews_is_scoped_per_stage(tmp_path: Path):
    cp = ControlPlane(tmp_path)
    bundle_hash = signoff_export.compute_bundle_hash(_manifest())
    cp.add_bundle_review("SIGNOFF", bundle_hash, reviewer_id="alice@example.com")
    assert cp.get_bundle_reviews("OTHER_STAGE", bundle_hash) == []


@pytest.mark.parametrize("kwargs,message_fragment", [
    ({"stage": "", "bundle_hash": "h", "reviewer_id": "a"}, "stage is required"),
    ({"stage": "SIGNOFF", "bundle_hash": "", "reviewer_id": "a"}, "bundle_hash is required"),
    ({"stage": "SIGNOFF", "bundle_hash": "h", "reviewer_id": ""}, "reviewer_id is required"),
    ({"stage": "SIGNOFF", "bundle_hash": "h", "reviewer_id": "   "}, "reviewer_id is required"),
])
def test_add_bundle_review_refuses_missing_required_fields(tmp_path, kwargs, message_fragment):
    cp = ControlPlane(tmp_path)
    with pytest.raises(ValueError, match=message_fragment):
        cp.add_bundle_review(**kwargs)


def test_add_bundle_review_refuses_invalid_reviewer_confidence(tmp_path: Path):
    cp = ControlPlane(tmp_path)
    with pytest.raises(ValueError, match="invalid reviewer_confidence"):
        cp.add_bundle_review("SIGNOFF", "h", reviewer_id="alice@example.com",
                              reviewer_confidence="SUPER_SURE")


# ---------------------------------------------------------------------------
# ControlPlane.has_independent_bundle_review() / assert_bundle_second_review_satisfied()
# ---------------------------------------------------------------------------

def test_has_independent_bundle_review_false_when_no_reviews(tmp_path: Path):
    cp = ControlPlane(tmp_path)
    assert cp.has_independent_bundle_review("SIGNOFF", "some-hash") is False
    assert cp.has_independent_bundle_review("SIGNOFF", "some-hash", approver_id="alice") is False


def test_has_independent_bundle_review_true_with_no_approver_named(tmp_path: Path):
    cp = ControlPlane(tmp_path)
    bundle_hash = signoff_export.compute_bundle_hash(_manifest())
    cp.add_bundle_review("SIGNOFF", bundle_hash, reviewer_id="alice@example.com")
    assert cp.has_independent_bundle_review("SIGNOFF", bundle_hash) is True


def test_has_independent_bundle_review_refuses_same_person_as_approver(tmp_path: Path):
    """The one hard rule this mechanism exists to enforce: the reviewer
    about to APPROVE cannot be their own second reviewer."""
    cp = ControlPlane(tmp_path)
    bundle_hash = signoff_export.compute_bundle_hash(_manifest())
    cp.add_bundle_review("SIGNOFF", bundle_hash, reviewer_id="alice@example.com")

    assert cp.has_independent_bundle_review(
        "SIGNOFF", bundle_hash, approver_id="alice@example.com") is False
    # Case/whitespace-insensitive same-person check, mirroring
    # question_queue.add_decision_cosign()'s own rule.
    assert cp.has_independent_bundle_review(
        "SIGNOFF", bundle_hash, approver_id="  ALICE@example.com  ") is False


def test_has_independent_bundle_review_true_once_a_real_different_reviewer_exists(tmp_path: Path):
    cp = ControlPlane(tmp_path)
    bundle_hash = signoff_export.compute_bundle_hash(_manifest())
    cp.add_bundle_review("SIGNOFF", bundle_hash, reviewer_id="alice@example.com")
    cp.add_bundle_review("SIGNOFF", bundle_hash, reviewer_id="bob@example.com")

    assert cp.has_independent_bundle_review(
        "SIGNOFF", bundle_hash, approver_id="alice@example.com") is True


def test_assert_bundle_second_review_satisfied_raises_when_unmet(tmp_path: Path):
    cp = ControlPlane(tmp_path)
    bundle_hash = signoff_export.compute_bundle_hash(_manifest())
    with pytest.raises(SecondReviewerRequiredError) as exc:
        cp.assert_bundle_second_review_satisfied("SIGNOFF", bundle_hash, approver_id="alice")
    assert exc.value.stage == "SIGNOFF"
    assert exc.value.bundle_hash == bundle_hash
    assert exc.value.approver_id == "alice"


def test_assert_bundle_second_review_satisfied_passes_when_met(tmp_path: Path):
    cp = ControlPlane(tmp_path)
    bundle_hash = signoff_export.compute_bundle_hash(_manifest())
    cp.add_bundle_review("SIGNOFF", bundle_hash, reviewer_id="bob@example.com")
    # Must not raise.
    cp.assert_bundle_second_review_satisfied("SIGNOFF", bundle_hash, approver_id="alice")


# ---------------------------------------------------------------------------
# signoff_export.bundle_second_review_status() -- the pure companion
# ---------------------------------------------------------------------------

def test_bundle_second_review_status_absent_when_no_reviews():
    manifest = _manifest()
    status = signoff_export.bundle_second_review_status(manifest, None)
    assert status["independently_reviewed"] is False
    assert status["state"] == "ABSENT"
    assert status["bundle_hash"] == signoff_export.compute_bundle_hash(manifest)
    assert status["reviewers"] == []


def test_bundle_second_review_status_reviewed_by_a_different_person():
    manifest = _manifest()
    bundle_hash = signoff_export.compute_bundle_hash(manifest)
    reviews = [{"bundle_hash": bundle_hash, "reviewer_id": "bob@example.com"}]
    status = signoff_export.bundle_second_review_status(manifest, reviews, approver_id="alice@example.com")
    assert status["independently_reviewed"] is True
    assert status["state"] == "REVIEWED"
    assert status["reviewers"] == ["bob@example.com"]


def test_bundle_second_review_status_same_person_only(tmp_path: Path):
    """A review recorded by the SAME person who will approve does not
    satisfy the requirement -- distinct from ABSENT, since a real review
    record does exist, it just does not count as independent."""
    manifest = _manifest()
    bundle_hash = signoff_export.compute_bundle_hash(manifest)
    reviews = [{"bundle_hash": bundle_hash, "reviewer_id": "alice@example.com"}]
    status = signoff_export.bundle_second_review_status(manifest, reviews, approver_id="alice@example.com")
    assert status["independently_reviewed"] is False
    assert status["state"] == "SAME_PERSON_ONLY"
    assert status["reviewers"] == ["alice@example.com"]


def test_bundle_second_review_status_stale_review_never_counts_as_current(tmp_path: Path):
    """A real, human-recorded review whose own bundle_hash disagrees with
    the manifest's CURRENT hash -- the bundle's content changed since that
    human looked at it -- must be reported STALE, never silently trusted."""
    old_manifest = _manifest("v1")
    new_manifest = _manifest("v2")
    old_hash = signoff_export.compute_bundle_hash(old_manifest)
    assert old_hash != signoff_export.compute_bundle_hash(new_manifest)

    reviews = [{"bundle_hash": old_hash, "reviewer_id": "bob@example.com"}]
    status = signoff_export.bundle_second_review_status(new_manifest, reviews, approver_id="alice@example.com")
    assert status["independently_reviewed"] is False
    assert status["state"] == "PRESENT_BUT_STALE"
    assert status["reviewers"] == []
    assert status["stale_reviewers"] == ["bob@example.com"]


def test_bundle_second_review_status_mixes_current_and_stale_reviewers(tmp_path: Path):
    manifest = _manifest("current")
    current_hash = signoff_export.compute_bundle_hash(manifest)
    stale_hash = signoff_export.compute_bundle_hash(_manifest("older"))
    reviews = [
        {"bundle_hash": stale_hash, "reviewer_id": "carol@example.com"},
        {"bundle_hash": current_hash, "reviewer_id": "bob@example.com"},
    ]
    status = signoff_export.bundle_second_review_status(manifest, reviews, approver_id="alice@example.com")
    assert status["independently_reviewed"] is True
    assert status["state"] == "REVIEWED"
    assert status["reviewers"] == ["bob@example.com"]
    assert status["stale_reviewers"] == ["carol@example.com"]


# ---------------------------------------------------------------------------
# End-to-end: real ControlPlane persistence feeding the pure status function
# ---------------------------------------------------------------------------

def test_end_to_end_real_control_plane_review_feeds_the_pure_status_function(tmp_path: Path):
    manifest = _manifest()
    bundle_hash = signoff_export.compute_bundle_hash(manifest)

    cp = ControlPlane(tmp_path)
    cp.add_bundle_review("SIGNOFF", bundle_hash, reviewer_id="bob@example.com",
                          note="checked tb_source diff against RTL", reviewer_confidence="HIGH")

    # A fresh caller composes the real persisted review with the pure
    # function -- exactly signoff_export.py's own "touches no approval
    # machinery" pattern already used by freeze_acceptance_status().
    reviews = cp.get_bundle_reviews("SIGNOFF", bundle_hash)
    status = signoff_export.bundle_second_review_status(manifest, reviews, approver_id="alice@example.com")
    assert status["independently_reviewed"] is True
    assert status["state"] == "REVIEWED"

    # And ControlPlane's own assert function agrees.
    cp.assert_bundle_second_review_satisfied("SIGNOFF", bundle_hash, approver_id="alice@example.com")
