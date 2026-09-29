"""USER-CORRECTION-TRIGGERED GAP DETECTION (Research_Capability_Evolution_
Master_Prompt sections 64/66).

These tests drive dv_harness.user_correction_trigger against a REAL
dv_harness.memory.MemoryStore, using the REAL MemoryGC.retract()/supersede()
methods to produce every correction record -- never a hand-written JSON
file shaped to look like one. Everything downstream (candidate construction,
persistence, the DISCOVERED-only boundary) goes through the REAL
capability_evolution.py machinery, exactly as
test_capability_evolution_auto_discovery.py already holds the sibling
failure-pattern filer to.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import capability_evolution as ce
from dv_harness import user_correction_trigger as uct
from dv_harness.memory import MemoryGC, MemoryStore

REASON = "the agent disabled the PHY instance assuming PIPE4 replaced it entirely"


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _add_record(root: Path, level: str = "project", **overrides) -> dict:
    store = MemoryStore(root)
    record = {
        "kind": "project_fact",
        "verified": True,
        "scope": "project",
        "title": "USB3 PHY bring-up assumption",
        "summary": "Assumed PIPE4 replaced the PHY for USB3 links.",
    }
    record.update(overrides)
    return store.add(level, record)


def _retract(root: Path, memory_id: str, reason: str = REASON) -> None:
    store = MemoryStore(root)
    ok = MemoryGC(store).retract(memory_id, reason)
    assert ok


def _supersede(root: Path, memory_id: str, superseded_by: str, reason: str = REASON) -> None:
    store = MemoryStore(root)
    ok = MemoryGC(store).supersede(memory_id, superseded_by, reason)
    assert ok


# --- detection: what counts as a repeated correction of the same mistake ----

def test_one_correction_is_not_a_pattern(root):
    """Section 64's own warning, applied to corrections: a single retraction
    is one event, not a repeated pattern. It must never raise a capability
    proposal."""
    a = _add_record(root)
    _retract(root, a["memory_id"])

    assert uct.repeated_user_correction_patterns(root) == []
    assert uct.file_candidates_for_user_corrections(root, cfg={}) == []
    assert ce.read_candidates(root) == {}


def test_two_independent_corrections_sharing_one_reason_are_a_pattern(root):
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    _retract(root, a["memory_id"])
    _retract(root, b["memory_id"])

    patterns = uct.repeated_user_correction_patterns(root)
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern["signature_key"] == uct.correction_signature_key(REASON)
    assert pattern["occurrence_count"] == 2
    assert pattern["correction_status"] == "RETRACTED"
    assert pattern["memory_ids"] == sorted([a["memory_id"], b["memory_id"]])
    assert pattern["correction_reason"] == uct._norm_text(REASON)


def test_retracted_and_superseded_records_with_the_same_reason_combine(root):
    """The two real correction statuses are grouped together -- both mean
    'a human found this wrong and corrected it', per MemoryGC's own
    docstrings, regardless of which lifecycle method was used."""
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    c = _add_record(root, title="C")
    _retract(root, a["memory_id"])
    _supersede(root, b["memory_id"], superseded_by=c["memory_id"])

    patterns = uct.repeated_user_correction_patterns(root)
    assert len(patterns) == 1
    assert patterns[0]["occurrence_count"] == 2
    assert set(patterns[0]["memory_ids"]) == {a["memory_id"], b["memory_id"]}


def test_the_same_record_retracted_twice_is_still_one_correction(root):
    """retract() mutates one record file in place; re-calling it on the SAME
    memory_id must never be counted as two independent corrections."""
    a = _add_record(root)
    _retract(root, a["memory_id"], reason=REASON)
    _retract(root, a["memory_id"], reason=REASON)

    assert uct.repeated_user_correction_patterns(root) == []


def test_two_different_reasons_are_two_separate_patterns(root):
    """Grouping is exact-equality on the normalized reason text, never a
    fuzzy or keyword-overlap match -- a fuzzy join would quietly group
    unrelated corrections as 'the same kind of mistake'."""
    a1, a2 = _add_record(root, title="A1"), _add_record(root, title="A2")
    b1, b2 = _add_record(root, title="B1"), _add_record(root, title="B2")
    _retract(root, a1["memory_id"], reason=REASON)
    _retract(root, a2["memory_id"], reason=REASON)
    _retract(root, b1["memory_id"], reason="unrelated: wrong branch_a naming used")
    _retract(root, b2["memory_id"], reason="unrelated: wrong branch_a naming used")

    patterns = uct.repeated_user_correction_patterns(root)
    assert len(patterns) == 2
    assert {p["signature_key"] for p in patterns} == {
        uct.correction_signature_key(REASON),
        uct.correction_signature_key("unrelated: wrong branch_a naming used"),
    }


def test_a_deprecated_record_is_never_counted_as_a_correction(root):
    """DEPRECATED means 'retired, not refuted' (MemoryGC.deprecate()'s own
    docstring) -- it must never be read as evidence that a mistake was
    corrected."""
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    MemoryGC(MemoryStore(root)).deprecate(a["memory_id"], REASON)
    MemoryGC(MemoryStore(root)).deprecate(b["memory_id"], REASON)

    assert uct.repeated_user_correction_patterns(root) == []


def test_a_blank_correction_reason_is_never_counted(root):
    """retract()/supersede() always require a reason argument in practice,
    but a record that somehow carries an empty one must not silently be
    treated as matching every other blank-reason record."""
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    _retract(root, a["memory_id"], reason="")
    _retract(root, b["memory_id"], reason="   ")

    assert uct.repeated_user_correction_patterns(root) == []


def test_min_occurrences_below_two_is_refused(root):
    with pytest.raises(ValueError, match="at least 2"):
        uct.repeated_user_correction_patterns(root, min_occurrences=1)


def test_lesson_reference_is_informational_only_and_never_suppresses_filing(root):
    """Unlike verified_fix for the failure-pattern filer, a matching lesson
    record never closes a user-correction pattern -- see the module's own
    'NO CLOSURE CONCEPT' rule."""
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    _retract(root, a["memory_id"])
    _retract(root, b["memory_id"])

    lesson_store = MemoryStore(root)
    lesson_store.add("engineering", {
        "kind": "debug_lesson", "verified": True, "scope": "engine",
        "title": "lesson", "root_cause": REASON,
        "evidence": ["e"], "confidence": "HIGH",
    })

    patterns = uct.repeated_user_correction_patterns(root)
    assert len(patterns) == 1
    assert patterns[0]["referenced_by_lesson"] is True

    filed = uct.file_candidates_for_user_corrections(root, cfg={})
    assert len(filed) == 1 and filed[0]["filed"] is True


# --- filing: real state, at DISCOVERED, through the existing machinery -----

def test_the_filed_candidate_is_real_persisted_state_at_DISCOVERED(root):
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    _retract(root, a["memory_id"])
    _retract(root, b["memory_id"])

    results = uct.file_candidates_for_user_corrections(root, cfg={})
    assert len(results) == 1 and results[0]["filed"] is True
    cid = results[0]["candidate_id"]

    stored = ce.read_candidate(root, cid)
    assert stored is not None
    assert stored["current_status"] == "DISCOVERED"
    assert stored["promotion_status"] == "DISCOVERED"
    assert stored["trigger_type"] == "USER_CORRECTION"
    assert stored["trigger_source"] == (
        f"memory:user_correction_signature:{uct.correction_signature_key(REASON)}"
    )
    assert stored["evidence_refs"] == sorted([a["memory_id"], b["memory_id"]])
    assert stored["status_history"][0]["by"] == uct.AUTO_DISCOVERY_BY
    assert stored["status_history"][0]["from_status"] is None
    assert len(stored["status_history"]) == 1

    audit = ce.candidate_audit_records(root, cid)
    assert len(audit) == 1
    assert audit[0]["current_status"] == "DISCOVERED"
    assert audit[0]["level"] == "working"

    store = MemoryStore(root)
    for memory_id in stored["evidence_refs"]:
        assert store.get(memory_id) is not None


def test_the_filed_candidate_asserts_no_search_it_did_not_perform(root):
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    _retract(root, a["memory_id"])
    _retract(root, b["memory_id"])

    cid = uct.file_candidates_for_user_corrections(root, cfg={})[0]["candidate_id"]
    stored = ce.read_candidate(root, cid)

    assert stored["overlap_status"] == "UNKNOWN"
    assert stored["recommendation"] == "UNKNOWN"
    assert stored["exact_gap"] == ""
    assert stored["enhance_insufficient_reason"] == ""
    for slot in ce.L5_SEARCH_SLOTS:
        assert stored[slot]["matches"] == []
        assert stored[slot]["search_conclusive"] is False
        assert "NOT SEARCHED" in stored[slot]["search_basis"]


def test_the_candidate_id_is_stable_across_cycles_and_accumulates_evidence(root):
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    _retract(root, a["memory_id"])
    _retract(root, b["memory_id"])
    first = uct.file_candidates_for_user_corrections(root, cfg={})[0]
    assert first["reason"] == "DISCOVERED"

    c = _add_record(root, title="C")
    _retract(root, c["memory_id"])
    second = uct.file_candidates_for_user_corrections(root, cfg={})[0]

    assert second["candidate_id"] == first["candidate_id"]
    assert second["filed"] is True and second["reason"] == "NEW_EVIDENCE"
    assert len(ce.read_candidates(root)) == 1
    stored = ce.read_candidate(root, first["candidate_id"])
    assert len(stored["evidence_refs"]) == 3
    assert stored["current_status"] == "DISCOVERED"
    assert len(stored["status_history"]) == 1


def test_re_filing_unchanged_evidence_writes_nothing(root):
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    _retract(root, a["memory_id"])
    _retract(root, b["memory_id"])
    cid = uct.file_candidates_for_user_corrections(root, cfg={})[0]["candidate_id"]

    again = uct.file_candidates_for_user_corrections(root, cfg={})
    assert again[0]["filed"] is False
    assert again[0]["reason"] == "ALREADY_ON_FILE_UNCHANGED"
    assert len(ce.candidate_audit_records(root, cid)) == 1


def test_a_candidate_a_human_moved_on_is_never_dragged_back(root):
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    _retract(root, a["memory_id"])
    _retract(root, b["memory_id"])
    cid = uct.file_candidates_for_user_corrections(root, cfg={})[0]["candidate_id"]

    moved = ce.transition(root, ce.read_candidate(root, cid), "EVIDENCE_GATHERING",
                          by="a-real-human", reason="starting the six searches", cfg={})
    assert moved["current_status"] == "EVIDENCE_GATHERING"

    c = _add_record(root, title="C")
    _retract(root, c["memory_id"])
    result = uct.file_candidates_for_user_corrections(root, cfg={})[0]
    assert result["filed"] is False
    assert result["reason"] == "ALREADY_BEYOND_DISCOVERED"
    assert ce.read_candidate(root, cid)["current_status"] == "EVIDENCE_GATHERING"
    assert len(ce.read_candidate(root, cid)["status_history"]) == 2


def test_an_auto_filed_candidate_cannot_be_advanced_to_PROPOSED(root):
    """The wall is structural: PROPOSED requires overlap_status to have left
    UNKNOWN, which this candidate's own schema pins it against while any of
    the six searches remain search_conclusive=false."""
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    _retract(root, a["memory_id"])
    _retract(root, b["memory_id"])
    cid = uct.file_candidates_for_user_corrections(root, cfg={})[0]["candidate_id"]
    candidate = ce.read_candidate(root, cid)

    candidate = ce.transition(root, candidate, "EVIDENCE_GATHERING",
                              by="human", reason="start searches", cfg={})
    with pytest.raises(ce.CapabilityEvolutionCandidateValidationError):
        candidate["current_status"] = "PROPOSED"
        candidate["promotion_status"] = "PROPOSED"
        ce.validate_candidate(candidate)


def test_the_human_approval_gate_is_untouched_by_an_auto_filed_candidate(root):
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    _retract(root, a["memory_id"])
    _retract(root, b["memory_id"])
    cid = uct.file_candidates_for_user_corrections(root, cfg={})[0]["candidate_id"]
    candidate = ce.read_candidate(root, cid)

    with pytest.raises(ce.HumanApprovalRequiredError):
        ce.assert_human_approval(root, candidate)
    with pytest.raises(ce.ProductionWriteNotAuthorizedError):
        ce.assert_no_production_write_authorized(root, candidate)


def test_the_auto_filed_candidate_never_reaches_a_tier_above_working_memory(root):
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    _retract(root, a["memory_id"])
    _retract(root, b["memory_id"])
    result = uct.file_candidates_for_user_corrections(root, cfg={})[0]
    assert result["persisted"]["memory"]["destination"] == "WORKING_MEMORY"


# --- CLI front door ----------------------------------------------------------

def test_cli_detect_exit_codes(root, capsys):
    assert uct.execute_verb(["--root", str(root), "detect"]) == 0
    a = _add_record(root, title="A")
    b = _add_record(root, title="B")
    _retract(root, a["memory_id"])
    _retract(root, b["memory_id"])
    assert uct.execute_verb(["--root", str(root), "detect"]) == 1
    capsys.readouterr()
    assert uct.execute_verb(["--root", str(root), "file"]) == 1
    assert len(ce.read_candidates(root)) == 1
