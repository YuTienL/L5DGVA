"""Human Correction Learning (section 227): a structured before/after shape
for a memory.py kind="debug_lesson" record, so a future session can query
"has a human corrected this exact mistake before".

Every write in this suite goes through the REAL, existing
memory_router.route_and_store() (via record_human_correction_lesson()) and
lands on a REAL dv_harness.memory.MemoryStore on disk -- never a hand-written
JSON record file shaped to look like one. cfg={} is passed throughout so
every write is local-only (no Knowledge Center network push attempt),
exactly the escape hatch memory_router.route_and_store()'s own docstring
documents.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness.human_correction_lesson import (
    HumanCorrectionLessonValidationError,
    build_human_correction_lesson,
    execute_verb,
    find_prior_corrections,
    has_prior_correction,
    mistake_signature_key,
    record_human_correction_lesson,
    validate_human_correction_lesson,
)
from dv_harness.memory import MemoryStore


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


BEFORE_CLAIM = "USB3 also goes through PIPE4, so the PHY instance can be disabled entirely"
AFTER_CLAIM = "USB3 still goes through a real PHY; PIPE4 is not a PHY replacement"
EVIDENCE = "USB_UVM_Handoff/doc/phy_interconnect.md section 3.2, RTL: usb3_phy_wrapper.v:118"
CORRECTED_BY = "senior-dv-reviewer"
MISTAKE_CATEGORY = "phy_boundary_misassumption"


def _build(**overrides):
    kwargs = dict(
        before_claim=BEFORE_CLAIM,
        after_claim=AFTER_CLAIM,
        correction_evidence=EVIDENCE,
        corrected_by=CORRECTED_BY,
        mistake_category=MISTAKE_CATEGORY,
    )
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# build_human_correction_lesson() -- structured shape, schema-validated
# ---------------------------------------------------------------------------

def test_build_produces_a_schema_valid_structured_before_after_record():
    record = build_human_correction_lesson(**_build())
    assert record["kind"] == "debug_lesson"
    assert record["verified"] is True
    assert record["reusable"] is True
    assert record["confidence"] == "HIGH"
    assert record["correction"]["correction_source"] == "human"
    assert record["correction"]["before"]["claim"] == BEFORE_CLAIM
    assert record["correction"]["after"]["claim"] == AFTER_CLAIM
    assert record["correction"]["after"]["evidence"] == EVIDENCE
    assert record["correction"]["after"]["corrected_by"] == CORRECTED_BY
    assert isinstance(record["correction"]["after"]["corrected_at"], float)
    assert record["mistake_category"] == MISTAKE_CATEGORY
    # Real, reusable content -- satisfies memory_router.engineering_admission_gate()'s
    # ENGINEERING_REUSABLE_CLAIM_FIELDS ("root_cause","fix","lesson") requirement.
    assert BEFORE_CLAIM in record["lesson"]
    assert AFTER_CLAIM in record["lesson"]
    assert record["evidence"] == EVIDENCE
    # Does not raise -- the record this function returns already passed validation.
    validate_human_correction_lesson(record)


def test_build_carries_optional_context_fields_through():
    record = build_human_correction_lesson(
        **_build(protocol="USB3", scope="phy_boundary", title="Custom Title",
                  before_reasoning="assumed PIPE4 supersedes the PHY layer")
    )
    assert record["protocol"] == "USB3"
    assert record["scope"] == "phy_boundary"
    assert record["title"] == "Custom Title"
    assert record["correction"]["before"]["reasoning"] == "assumed PIPE4 supersedes the PHY layer"


@pytest.mark.parametrize("field", [
    "before_claim", "after_claim", "correction_evidence", "corrected_by", "mistake_category",
])
def test_build_refuses_to_fabricate_a_lesson_when_a_required_field_is_empty(field):
    """The Evidence Truth Rule, enforced: an empty/whitespace-only claim,
    evidence citation, corrected-by identity, or mistake category must never
    silently become a placeholder lesson record -- it must raise."""
    kwargs = _build(**{field: "   "})
    with pytest.raises(HumanCorrectionLessonValidationError):
        build_human_correction_lesson(**kwargs)


def test_validate_rejects_a_hand_shaped_record_missing_the_correction_block():
    bad = {
        "kind": "debug_lesson", "mistake_category": "x", "mistake_signature_key": "0" * 64,
        "lesson": "x", "evidence": "x", "confidence": "HIGH", "verified": True, "reusable": True,
    }
    with pytest.raises(HumanCorrectionLessonValidationError):
        validate_human_correction_lesson(bad)


def test_validate_rejects_verified_false_and_wrong_confidence():
    record = build_human_correction_lesson(**_build())
    record["verified"] = False
    with pytest.raises(HumanCorrectionLessonValidationError):
        validate_human_correction_lesson(record)

    record2 = build_human_correction_lesson(**_build())
    record2["confidence"] = "MEDIUM"
    with pytest.raises(HumanCorrectionLessonValidationError):
        validate_human_correction_lesson(record2)


# ---------------------------------------------------------------------------
# mistake_signature_key() -- exact match only, never fuzzy
# ---------------------------------------------------------------------------

def test_signature_key_is_stable_under_whitespace_and_case_normalization():
    k1 = mistake_signature_key("  USB3 Also Goes  Through PIPE4 ", "PHY_Boundary")
    k2 = mistake_signature_key("usb3 also goes through pipe4", "phy_boundary")
    assert k1 == k2


def test_signature_key_differs_for_a_genuinely_different_mistake():
    k1 = mistake_signature_key(BEFORE_CLAIM, MISTAKE_CATEGORY)
    k2 = mistake_signature_key("the DUT never asserts an interrupt on port 1", "interrupt_dispatch")
    assert k1 != k2


def test_signature_key_never_matches_a_paraphrased_claim_no_fuzzy_matching():
    """Section 227's own accepted trade, restated as a test: two claims a
    human would call 'the same mistake' but worded differently must NOT
    collapse to one signature -- under-detection, never fabricated
    over-detection."""
    k1 = mistake_signature_key(BEFORE_CLAIM, MISTAKE_CATEGORY)
    k2 = mistake_signature_key(
        "the reviewer disabled the USB3 PHY on the assumption PIPE4 covers it",
        MISTAKE_CATEGORY,
    )
    assert k1 != k2


# ---------------------------------------------------------------------------
# record_human_correction_lesson() -- real ENGINEERING_MEMORY write, through
# the real, unmodified memory_router.route_and_store()
# ---------------------------------------------------------------------------

def test_record_writes_to_real_engineering_memory_through_the_real_router(root):
    result = record_human_correction_lesson(root, cfg={}, **_build())
    assert result["destination"] == "ENGINEERING_MEMORY"
    assert result["level"] == "engineering"
    memory_id = result["memory_id"]

    store = MemoryStore(root)
    persisted = store.get(memory_id)
    assert persisted is not None
    assert persisted["kind"] == "debug_lesson"
    assert persisted["correction"]["after"]["corrected_by"] == CORRECTED_BY
    assert persisted["level"] == "engineering"


def test_record_is_idempotent_in_shape_across_two_independent_corrections(root):
    """Two INDEPENDENT humans correcting the identical mistake both land as
    real, separately-addressable engineering-tier records (this module never
    merges/dedupes writes -- find_prior_corrections() is the read-side query
    that surfaces both)."""
    r1 = record_human_correction_lesson(root, cfg={}, **_build(corrected_by="reviewer-a"))
    r2 = record_human_correction_lesson(root, cfg={}, **_build(corrected_by="reviewer-b"))
    assert r1["memory_id"] != r2["memory_id"]
    assert r1["destination"] == "ENGINEERING_MEMORY"
    assert r2["destination"] == "ENGINEERING_MEMORY"


# ---------------------------------------------------------------------------
# find_prior_corrections() / has_prior_correction() -- the "has a human
# corrected this exact mistake before" query, and its negative control
# ---------------------------------------------------------------------------

def test_has_prior_correction_reports_honestly_absent_before_anything_is_recorded(root):
    """THE Evidence Truth Rule negative control this item's own house style
    requires: querying a mistake nobody has ever corrected must report an
    honest absence, never a fabricated match."""
    report = has_prior_correction(root, before_claim=BEFORE_CLAIM, mistake_category=MISTAKE_CATEGORY)
    assert report["found"] is False
    assert report["count"] == 0
    assert report["matches"] == []
    assert len(report["mistake_signature_key"]) == 64

    matches = find_prior_corrections(root, before_claim=BEFORE_CLAIM, mistake_category=MISTAKE_CATEGORY)
    assert matches == []


def test_has_prior_correction_finds_the_real_recorded_correction_after_it_is_written(root):
    result = record_human_correction_lesson(root, cfg={}, **_build())
    report = has_prior_correction(root, before_claim=BEFORE_CLAIM, mistake_category=MISTAKE_CATEGORY)
    assert report["found"] is True
    assert report["count"] == 1
    assert report["matches"][0]["memory_id"] == result["memory_id"]
    assert report["matches"][0]["correction"]["after"]["evidence"] == EVIDENCE


def test_has_prior_correction_never_matches_a_different_before_claim(root):
    record_human_correction_lesson(root, cfg={}, **_build())
    report = has_prior_correction(
        root,
        before_claim="the DUT never asserts an interrupt on port 1",
        mistake_category="interrupt_dispatch",
    )
    assert report["found"] is False
    assert report["count"] == 0


def test_has_prior_correction_accumulates_independent_corrections_of_the_same_mistake(root):
    record_human_correction_lesson(root, cfg={}, **_build(corrected_by="reviewer-a"))
    record_human_correction_lesson(root, cfg={}, **_build(corrected_by="reviewer-b"))
    report = has_prior_correction(root, before_claim=BEFORE_CLAIM, mistake_category=MISTAKE_CATEGORY)
    assert report["found"] is True
    assert report["count"] == 2
    correctors = {m["correction"]["after"]["corrected_by"] for m in report["matches"]}
    assert correctors == {"reviewer-a", "reviewer-b"}


def test_find_prior_corrections_ignores_unrelated_debug_lesson_records(root):
    """A different, non-human-correction debug_lesson record (the shape
    engine._promote_experience_knowledge() already writes -- free-text
    root_cause/fix, no `correction` block, no matching signature key) must
    never be mistaken for a match on an unrelated mistake."""
    store = MemoryStore(root)
    store.add("engineering", {
        "kind": "debug_lesson", "verified": True, "confidence": "HIGH",
        "root_cause": "an unrelated timeout misclassification",
        "evidence": "sim.log:42", "reusable": True,
    })
    report = has_prior_correction(root, before_claim=BEFORE_CLAIM, mistake_category=MISTAKE_CATEGORY)
    assert report["found"] is False


# ---------------------------------------------------------------------------
# Standalone `python -m dv_harness.human_correction_lesson` front door
# ---------------------------------------------------------------------------

def test_cli_record_then_query_round_trip_in_process(root, capsys):
    argv = [
        "--root", str(root), "record",
        "--before-claim", BEFORE_CLAIM,
        "--after-claim", AFTER_CLAIM,
        "--correction-evidence", EVIDENCE,
        "--corrected-by", CORRECTED_BY,
        "--mistake-category", MISTAKE_CATEGORY,
    ]
    assert execute_verb(argv) == 0
    capsys.readouterr()

    query_before = execute_verb([
        "--root", str(root), "query",
        "--before-claim", "a totally different mistake nobody made",
    ])
    assert query_before == 1

    query_found = execute_verb([
        "--root", str(root), "query",
        "--before-claim", BEFORE_CLAIM,
        "--mistake-category", MISTAKE_CATEGORY,
    ])
    assert query_found == 0


def test_cli_query_before_any_record_exits_1_real_subprocess(root):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.human_correction_lesson",
         "--root", str(root), "query", "--before-claim", BEFORE_CLAIM],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "found=False" in proc.stdout


def test_cli_record_then_query_real_subprocess(root):
    rec = subprocess.run(
        [sys.executable, "-m", "dv_harness.human_correction_lesson",
         "--root", str(root), "--json", "record",
         "--before-claim", BEFORE_CLAIM, "--after-claim", AFTER_CLAIM,
         "--correction-evidence", EVIDENCE, "--corrected-by", CORRECTED_BY,
         "--mistake-category", MISTAKE_CATEGORY],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True,
    )
    assert rec.returncode == 0, rec.stderr
    assert '"ENGINEERING_MEMORY"' in rec.stdout

    query = subprocess.run(
        [sys.executable, "-m", "dv_harness.human_correction_lesson",
         "--root", str(root), "query", "--before-claim", BEFORE_CLAIM,
         "--mistake-category", MISTAKE_CATEGORY],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True,
    )
    assert query.returncode == 0
    assert "found=True" in query.stdout
