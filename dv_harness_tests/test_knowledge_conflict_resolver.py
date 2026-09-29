"""Tests for dv_harness.knowledge_conflict_resolver -- resolving a conflict
between an Engineering-tier MEMORY record and an Organizational-tier MEMORY
record, distinct from source_authority.py's DOCUMENT-source conflict order.

Real machinery throughout: a real `dv_harness.memory.MemoryStore` writes both
sides' records exactly the way `engine.py`'s `_promote_verified_fix_
knowledge()` and `memory_router.promote_to_organizational()` shape them, and
every escalation test drives a real `question_queue.QuestionQueueStore` on
tmp_path and reads the persisted question back out of it -- nothing here is
a mock.

The negative controls this module is graded on:
  * a genuine claim disagreement is NEVER resolved to a winner -- there is
    no "winner"/"resolved_value" field on a MEMORY_TIER_CONFLICT result, and
    tier order (Organizational > Engineering) is never applied as an
    authority rule the way source_authority.py applies its 9-level order;
  * a record missing a subject or a reusable claim is refused rather than
    silently compared as if it were empty/agreeing;
  * two records about genuinely different subjects are reported
    NOT_COMPARABLE, never fabricated into a conflict;
  * agreement and non-comparability both ask nothing (escalate_memory_
    conflict returns None), so a human is never bothered with a non-issue;
  * re-escalating the same conflict never grows the queue.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dv_harness import knowledge_conflict_resolver as kcr
from dv_harness import question_queue
from dv_harness.memory import MemoryStore


def _engineering_record(store: MemoryStore, *, protocol="USB3", root_cause="Clock domain crossing on TX FIFO empty flag") -> dict:
    return store.add("engineering", {
        "kind": "verified_fix",
        "verified": True,
        "protocol": protocol,
        "root_cause": root_cause,
        "confidence": "HIGH",
        "status": "ACTIVE",
    })


def _organizational_record(store: MemoryStore, *, protocol="USB3", root_cause="Race condition in LTSSM recovery handshake") -> dict:
    return store.add("organizational", {
        "kind": "root_cause",
        "verified": True,
        "protocol": protocol,
        "root_cause": root_cause,
        "confidence": "CONFIRMED",
        "status": "ACTIVE",
        "confirmation_count": 2,
    })


# ---- extract_memory_claim ----------------------------------------------------

def test_extract_memory_claim_reads_the_real_record_shape(tmp_path):
    store = MemoryStore(tmp_path)
    rec = _engineering_record(store)
    claim = kcr.extract_memory_claim(rec)
    assert claim.level == "engineering"
    assert claim.memory_id == rec["memory_id"]
    assert claim.subject == "USB3"
    assert claim.claim_field == "root_cause"
    assert claim.claim == "Clock domain crossing on TX FIFO empty flag"
    assert claim.memory_id in claim.evidence_path
    assert "memory_cli" in claim.evidence_path


def test_extract_memory_claim_prefers_root_cause_over_fix_and_lesson(tmp_path):
    store = MemoryStore(tmp_path)
    rec = store.add("engineering", {
        "kind": "verified_fix", "protocol": "PCIe",
        "root_cause": "the real root cause", "fix": "a fix text", "lesson": "a lesson text",
        "status": "ACTIVE",
    })
    claim = kcr.extract_memory_claim(rec)
    assert claim.claim_field == "root_cause"
    assert claim.claim == "the real root cause"


def test_extract_memory_claim_falls_back_to_fix_then_lesson(tmp_path):
    store = MemoryStore(tmp_path)
    fix_only = store.add("engineering", {"kind": "verified_fix", "protocol": "PCIe",
                                          "fix": "apply patch X", "status": "ACTIVE"})
    lesson_only = store.add("organizational", {"kind": "debug_lesson", "protocol": "PCIe",
                                                "lesson": "always check retimer config",
                                                "status": "ACTIVE"})
    assert kcr.extract_memory_claim(fix_only).claim_field == "fix"
    assert kcr.extract_memory_claim(lesson_only).claim_field == "lesson"


# ---- negative controls: refuse rather than fabricate -------------------------

def test_extract_memory_claim_refuses_a_record_with_no_level(tmp_path):
    with pytest.raises(kcr.KnowledgeConflictResolverError) as exc:
        kcr.extract_memory_claim({"memory_id": "MEM-X", "protocol": "USB3", "root_cause": "y"})
    assert exc.value.reason == "MEMORY_RECORD_MISSING_OR_UNKNOWN_LEVEL"


def test_extract_memory_claim_refuses_a_record_with_no_subject(tmp_path):
    store = MemoryStore(tmp_path)
    rec = store.add("engineering", {"kind": "verified_fix", "root_cause": "some cause",
                                     "status": "ACTIVE"})
    with pytest.raises(kcr.KnowledgeConflictResolverError) as exc:
        kcr.extract_memory_claim(rec)
    assert exc.value.reason == "MEMORY_RECORD_MISSING_SUBJECT"


def test_extract_memory_claim_refuses_a_record_with_no_reusable_claim(tmp_path):
    store = MemoryStore(tmp_path)
    rec = store.add("engineering", {"kind": "job_failure", "protocol": "USB3",
                                     "status": "ACTIVE"})
    with pytest.raises(kcr.KnowledgeConflictResolverError) as exc:
        kcr.extract_memory_claim(rec)
    assert exc.value.reason == "MEMORY_RECORD_MISSING_CLAIM"
    assert "root_cause" in exc.value.detail["checked_fields"]


def test_extract_memory_claim_refuses_a_non_dict():
    with pytest.raises(kcr.KnowledgeConflictResolverError) as exc:
        kcr.extract_memory_claim("not a dict")
    assert exc.value.reason == "MEMORY_RECORD_MUST_BE_A_DICT"


# ---- resolve_memory_conflict --------------------------------------------------

def test_no_conflict_when_claims_agree(tmp_path):
    store = MemoryStore(tmp_path)
    eng = _engineering_record(store, root_cause="Same root cause, worded identically")
    org = _organizational_record(store, root_cause="  Same root cause, worded identically  ")
    result = kcr.resolve_memory_conflict(eng, org)
    assert result["verdict"] == kcr.VERDICT_NO_CONFLICT
    assert "winner" not in result


def test_no_conflict_is_case_and_whitespace_insensitive(tmp_path):
    store = MemoryStore(tmp_path)
    eng = _engineering_record(store, root_cause="Race Condition   in the FSM")
    org = _organizational_record(store, root_cause="race condition in the fsm")
    result = kcr.resolve_memory_conflict(eng, org)
    assert result["verdict"] == kcr.VERDICT_NO_CONFLICT


def test_not_comparable_when_subjects_differ(tmp_path):
    store = MemoryStore(tmp_path)
    eng = _engineering_record(store, protocol="USB3")
    org = _organizational_record(store, protocol="PCIe")
    result = kcr.resolve_memory_conflict(eng, org)
    assert result["verdict"] == kcr.VERDICT_NOT_COMPARABLE
    assert result["subject_engineering"] == "USB3"
    assert result["subject_organizational"] == "PCIe"


def test_real_conflict_is_reported_and_never_resolved_to_a_winner(tmp_path):
    """The headline negative control: a genuine disagreement between the two
    tiers must never be silently resolved by picking a tier -- there is no
    'winner' field, and the rule text must not assert one tier outranks the
    other (contrast source_authority.resolve_conflict(), whose RESOLVED
    verdict legitimately does exactly that for document sources)."""
    store = MemoryStore(tmp_path)
    eng = _engineering_record(store)
    org = _organizational_record(store)
    result = kcr.resolve_memory_conflict(eng, org)
    assert result["verdict"] == kcr.VERDICT_CONFLICT
    assert result["subject"] == "USB3"
    assert "winner" not in result
    assert "losers" not in result
    assert len(result["claims"]) == 2
    claims_by_level = {c["level"]: c for c in result["claims"]}
    assert claims_by_level["engineering"]["claim"] == "Clock domain crossing on TX FIFO empty flag"
    assert claims_by_level["organizational"]["claim"] == "Race condition in LTSSM recovery handshake"
    # the rule text must explicitly say neither tier is trusted mechanically
    assert "must decide" in result["rule"]
    assert "not current evidence" in result["rule"]


def test_wrong_tier_pair_is_refused(tmp_path):
    store = MemoryStore(tmp_path)
    a = _engineering_record(store)
    b = _engineering_record(store, root_cause="a different engineering claim")
    with pytest.raises(kcr.KnowledgeConflictResolverError) as exc:
        kcr.resolve_memory_conflict(a, b)
    assert exc.value.reason == "WRONG_TIER_PAIR"


def test_wrong_tier_pair_order_is_refused_too(tmp_path):
    store = MemoryStore(tmp_path)
    eng = _engineering_record(store)
    org = _organizational_record(store)
    # swapped: organizational passed as the "engineering" argument
    with pytest.raises(kcr.KnowledgeConflictResolverError) as exc:
        kcr.resolve_memory_conflict(org, eng)
    assert exc.value.reason == "WRONG_TIER_PAIR"


# ---- escalate_memory_conflict: real question-queue reuse ---------------------

def test_no_conflict_asks_nothing(tmp_path):
    store = MemoryStore(tmp_path)
    eng = _engineering_record(store, root_cause="agreed cause")
    org = _organizational_record(store, root_cause="agreed cause")
    conflict = kcr.resolve_memory_conflict(eng, org)
    assert kcr.escalate_memory_conflict(tmp_path, conflict, domain="env") is None
    assert question_queue.QuestionQueueStore(tmp_path).list_questions() == []


def test_not_comparable_asks_nothing(tmp_path):
    store = MemoryStore(tmp_path)
    eng = _engineering_record(store, protocol="USB3")
    org = _organizational_record(store, protocol="PCIe")
    conflict = kcr.resolve_memory_conflict(eng, org)
    assert kcr.escalate_memory_conflict(tmp_path, conflict, domain="env") is None
    assert question_queue.QuestionQueueStore(tmp_path).list_questions() == []


def test_real_conflict_files_a_real_blocking_question(tmp_path):
    store = MemoryStore(tmp_path)
    eng = _engineering_record(store)
    org = _organizational_record(store)
    conflict = kcr.resolve_memory_conflict(eng, org)

    rec = kcr.escalate_memory_conflict(tmp_path, conflict, domain="env")
    assert rec is not None
    assert rec["status"] == "OPEN"
    assert rec["tier"] == question_queue.TIER3_CANNOT_ASSUME

    qstore = question_queue.QuestionQueueStore(tmp_path)
    persisted = qstore.get_question(rec["id"])
    assert persisted is not None
    labels = {o["label"] for o in persisted["options"]}
    assert any(eng["memory_id"] in lbl for lbl in labels)
    assert any(org["memory_id"] in lbl for lbl in labels)
    # both sides' evidence paths must be present somewhere in the record
    blob = persisted["question"] + " " + " ".join(
        o.get("rationale", "") + o.get("label", "") for o in persisted["options"])
    assert f"memory_cli get {eng['memory_id']}" in blob
    assert f"memory_cli get {org['memory_id']}" in blob


def test_re_escalating_the_same_conflict_does_not_grow_the_queue(tmp_path):
    store = MemoryStore(tmp_path)
    eng = _engineering_record(store)
    org = _organizational_record(store)
    conflict = kcr.resolve_memory_conflict(eng, org)

    qstore = question_queue.QuestionQueueStore(tmp_path)
    first = kcr.escalate_memory_conflict(qstore, conflict, domain="env")
    second = kcr.escalate_memory_conflict(qstore, conflict, domain="env")
    assert first["id"] == second["id"]
    assert len(question_queue.QuestionQueueStore(tmp_path).list_questions()) == 1


def test_escalate_accepts_a_prebuilt_store_and_a_path_identically(tmp_path):
    store = MemoryStore(tmp_path)
    eng = _engineering_record(store)
    org = _organizational_record(store)
    conflict = kcr.resolve_memory_conflict(eng, org)

    via_path = kcr.escalate_memory_conflict(tmp_path, conflict, domain="env")
    via_store = kcr.escalate_memory_conflict(question_queue.QuestionQueueStore(tmp_path),
                                              conflict, domain="env")
    assert via_path["id"] == via_store["id"]


def test_escalate_refuses_an_unrecognized_verdict(tmp_path):
    with pytest.raises(kcr.KnowledgeConflictResolverError) as exc:
        kcr.escalate_memory_conflict(tmp_path, {"verdict": "SOMETHING_ELSE"}, domain="env")
    assert exc.value.reason == "UNKNOWN_CONFLICT_VERDICT"


# ---- find_tier_conflicts: whole-store detection -------------------------------

def test_find_tier_conflicts_over_a_real_store(tmp_path):
    store = MemoryStore(tmp_path)
    _engineering_record(store, protocol="USB3", root_cause="cause A")
    _organizational_record(store, protocol="USB3", root_cause="cause B (disagrees)")
    _engineering_record(store, protocol="PCIe", root_cause="matching cause")
    _organizational_record(store, protocol="PCIe", root_cause="matching cause")

    conflicts = kcr.find_tier_conflicts(store)
    assert len(conflicts) == 1
    assert conflicts[0]["subject"] == "USB3"
    assert conflicts[0]["verdict"] == kcr.VERDICT_CONFLICT


def test_find_tier_conflicts_skips_malformed_records_without_crashing(tmp_path):
    store = MemoryStore(tmp_path)
    # a real Engineering record with no reusable claim -- extract_memory_claim
    # would raise on it; the whole-store scan must not crash because of it.
    store.add("engineering", {"kind": "job_failure", "protocol": "USB3", "status": "ACTIVE"})
    _organizational_record(store, protocol="USB3", root_cause="a claim")
    conflicts = kcr.find_tier_conflicts(store)
    assert conflicts == []


def test_find_tier_conflicts_reports_nothing_when_stores_are_empty(tmp_path):
    store = MemoryStore(tmp_path)
    assert kcr.find_tier_conflicts(store) == []
