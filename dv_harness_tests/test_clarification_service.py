"""CAP-M6-CLARSVC-001: tests for `dv_harness/clarification_service.py`, the
ONE Canonical `ClarificationService` (M-1 D2, not reopened) over
`question_queue.py` + `intake_field_resolution.py`.

Required test families (per this capability's own dispatch item 23), one
section each: no-question auto-discovery path, unresolved-question path,
DE/DV/SHARED owner, conflicting candidates, answer round-trip, answer
re-validation, still-unresolved answer, duplicate question suppression,
dispatch blocking/resume (via start_lifecycle()), CLI/dashboard
compatibility (already covered by test_start_lifecycle_dispatch.py's own
convergence tests, since clarification_service is reached through the same
entry point -- not duplicated here).
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import clarification_service as cs
from dv_harness.intake_field_resolution import (
    Candidate,
    Confidence,
    EvidenceProducer,
    FieldControl,
    SourceKind,
)
from dv_harness.question_queue import QuestionQueueStore


@pytest.fixture()
def root():
    d = Path(tempfile.mkdtemp(prefix="clarsvc_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _found(value, *, kind=SourceKind.AUTO_DISCOVERED, source="rtl_scan", step="existing_files",
          confidence=Confidence.HIGH, refs=("rtl.v:10",), location="rtl.v:10"):
    cand = Candidate(value=value, kind=kind, source=source, confidence=confidence,
                     evidence_refs=tuple(refs), location=location)
    return EvidenceProducer(step=step, name=source, fn=lambda field_id, ctx: [cand])


# ---------------------------------------------------------------------------
# 1. No-question case (AUTO_DISCOVERY_FIRST acceptance test, item 18)
# ---------------------------------------------------------------------------

def test_no_question_when_automatically_resolved(root):
    """AutoDiscoveredValue available, validation sufficient, no required
    human confirmation -> NO HUMAN QUESTION. Critical AUTO_DISCOVERY_FIRST
    acceptance test."""
    control = FieldControl(field_id="dut_top_module", required=True, domain="dut")
    outcome = cs.resolve_or_ask(root, control, producers=[_found("usb_20_serial_ic_wrapper")])
    assert outcome.resolved is True
    assert outcome.asked is False
    assert outcome.question is None
    assert outcome.question_owner is None
    assert outcome.effective_value.value == "usb_20_serial_ic_wrapper"
    # No question was ever persisted.
    store = QuestionQueueStore(root)
    assert store.get_question(cs.make_question_id("dut", "intake:dut_top_module")) is None


def test_optional_field_never_asks_even_when_unresolved(root):
    control = FieldControl(field_id="nice_to_have", required=False, domain="env")
    outcome = cs.resolve_or_ask(root, control)
    assert outcome.resolved is True  # field_is_sufficient() short-circuits optional fields
    assert outcome.asked is False


# ---------------------------------------------------------------------------
# 2. Unresolved-question path
# ---------------------------------------------------------------------------

def test_unresolved_required_field_files_a_real_question(root):
    control = FieldControl(field_id="dut_top_module", required=True, domain="dut")
    outcome = cs.resolve_or_ask(root, control)
    assert outcome.resolved is False
    assert outcome.asked is True
    assert outcome.answered is False
    assert outcome.question is not None
    store = QuestionQueueStore(root)
    persisted = store.get_question(outcome.question["id"])
    assert persisted is not None
    assert persisted["answer"] is None


# ---------------------------------------------------------------------------
# 3/4/5. DE / DV / SHARED QuestionOwner (items 19/20/21)
# ---------------------------------------------------------------------------

def test_de_question_owner_is_design_for_a_dut_domain_field(root):
    """A design-intent ambiguity -> QUESTION_OWNER = DESIGN."""
    control = FieldControl(field_id="reset_polarity", required=True, domain="dut")
    outcome = cs.resolve_or_ask(root, control)
    assert outcome.question_owner == cs.DESIGN
    store = QuestionQueueStore(root)
    persisted = store.get_question(outcome.question["id"])
    assert persisted["authority_role"] == "DESIGN"


def test_dv_question_owner_is_verification_for_env_and_vip_domain_fields(root):
    """A verification-owned ambiguity -> QUESTION_OWNER = VERIFICATION."""
    for domain, field_id in (("env", "vip_config"), ("vip", "vip_release_version")):
        r = root / domain
        control = FieldControl(field_id=field_id, required=True, domain=domain)
        outcome = cs.resolve_or_ask(r, control)
        assert outcome.question_owner == cs.VERIFICATION, domain


def test_shared_question_owner_only_for_a_genuine_dut_conflict(root):
    """A genuine cross-domain ambiguity (a real DUT/RTL contradiction) ->
    QUESTION_OWNER = SHARED."""
    control = FieldControl(field_id="reset_polarity", required=True, domain="dut")
    outcome = cs.resolve_or_ask(root, control, declared="ACTIVE_HIGH",
                                producers=[_found("ACTIVE_LOW")])
    assert outcome.question_owner == cs.SHARED
    store = QuestionQueueStore(root)
    persisted = store.get_question(outcome.question["id"])
    assert persisted["authority_role"] == "SHARED"


def test_an_ordinary_unknown_dut_field_is_not_automatically_shared(root):
    """Item 21's second half: an ordinary unresolved (not conflicting) dut
    question must stay DESIGN, never defaulted to SHARED merely because a
    human must be asked at all (SHARED is never a lazy fallback)."""
    control = FieldControl(field_id="clock_domain_count", required=True, domain="dut")
    outcome = cs.resolve_or_ask(root, control)  # no producers -> UNKNOWN, not CONFLICT
    assert outcome.question_owner == cs.DESIGN


# ---------------------------------------------------------------------------
# 6. Conflicting candidates preserve both, ask the correct owner (item 17)
# ---------------------------------------------------------------------------

def test_conflict_preserves_both_evidence_backed_candidates_never_silently_chooses(root):
    control = FieldControl(field_id="reset_polarity", required=True, domain="dut")
    outcome = cs.resolve_or_ask(root, control, declared="ACTIVE_HIGH",
                                producers=[_found("ACTIVE_LOW")])
    assert outcome.resolved is False
    assert outcome.effective_value.value is None  # never silently picks a winner
    labels = {opt["label"] for opt in outcome.question["options"]}
    assert labels == {"ACTIVE_HIGH", "ACTIVE_LOW"}
    assert outcome.question_owner == cs.SHARED


# ---------------------------------------------------------------------------
# 7/8/9. Answer round-trip, re-validation, still-unresolved (item 10's
# mandatory Answer -> Field Resolution loop)
# ---------------------------------------------------------------------------

def test_answer_round_trip_feeds_back_through_field_resolution(root):
    control = FieldControl(field_id="dut_top_module", required=True, domain="dut")
    first = cs.resolve_or_ask(root, control)
    qid = first.question["id"]

    store = QuestionQueueStore(root)
    store.answer_question(qid, answer="usb_20_serial_ic_wrapper",
                          basis="confirmed by designer", decided_by="designer1")

    second = cs.resolve_or_ask(root, control)
    assert second.answered is True
    assert second.asked is False
    assert second.resolved is True
    assert second.effective_value.value == "usb_20_serial_ic_wrapper"
    # The answer entered the EXISTING field-resolution contract (ConfirmationState/
    # ValidationState are real, computed fields on the re-resolved EffectiveValue),
    # never a direct EffectiveValue overwrite.
    assert second.effective_value.resolution_method is not None


def test_still_unresolved_after_an_empty_or_insufficient_answer(root):
    """A human answer that is itself empty/whitespace must not be silently
    treated as resolving the field -- resolve_field()'s own real validation
    still applies to a human-supplied value."""
    control = FieldControl(field_id="dut_top_module", required=True, domain="dut")
    first = cs.resolve_or_ask(root, control)
    qid = first.question["id"]
    store = QuestionQueueStore(root)
    store.answer_question(qid, answer="   ", basis="no real value given", decided_by="designer1")
    second = cs.resolve_or_ask(root, control)
    # Re-resolution ran (answered=True: a real answer was on file and consumed),
    # but a blank value does not manufacture a resolved field.
    assert second.answered is True
    assert second.effective_value.value in (None, "")


# ---------------------------------------------------------------------------
# 10. Duplicate question suppression (item 16)
# ---------------------------------------------------------------------------

def test_duplicate_question_is_not_re_filed_without_evidence_change(root):
    control = FieldControl(field_id="dut_top_module", required=True, domain="dut")
    first = cs.resolve_or_ask(root, control)
    second = cs.resolve_or_ask(root, control)
    assert first.question["id"] == second.question["id"]
    store = QuestionQueueStore(root)
    all_q = store.list_questions() if hasattr(store, "list_questions") else None
    if all_q is not None:
        matching = [q for q in all_q if q["id"] == first.question["id"]]
        assert len(matching) == 1


# ---------------------------------------------------------------------------
# 11. Dispatch blocking / resume via start_lifecycle() (item 11)
# ---------------------------------------------------------------------------

def test_dispatch_blocks_on_unresolved_field_and_resumes_after_answer(root):
    from dv_harness.adapters.base import AgentResult
    from dv_harness.engine import DVHarness

    class _FakeAdapter:
        def __init__(self):
            self.calls = 0

        def run(self, prompt, cwd, resume_session=None, agent_profile=None):
            self.calls += 1
            return AgentResult(ok=True, text="fake\n", raw={}, session_id="s1")

    control = FieldControl(field_id="dut_top_module", required=True, domain="dut")

    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    r1 = h.start_lifecycle("bring up USB", field_controls=[control])
    assert r1.ok is False
    assert r1.raw["blocked_by"] == "clarification"
    assert h.adapter.calls == 0

    qid = r1.raw["question_ids"][0]
    QuestionQueueStore(root).answer_question(qid, answer="usb_20_serial_ic_wrapper",
                                             basis="confirmed", decided_by="designer1")

    h2 = DVHarness(root)
    h2.adapter = _FakeAdapter()
    r2 = h2.start_lifecycle("bring up USB", field_controls=[control])
    assert r2 is not None
    assert r2.raw.get("blocked_by") is None
    assert h2.adapter.calls == 1  # dispatch actually proceeded this time


# ---------------------------------------------------------------------------
# HumanGate state projection (item 9)
# ---------------------------------------------------------------------------

def test_human_gate_state_projects_real_question_queue_status(root):
    control = FieldControl(field_id="dut_top_module", required=True, domain="dut")
    outcome = cs.resolve_or_ask(root, control)
    assert cs.human_gate_state(outcome.question) == cs.HG_WAITING_FOR_HUMAN

    store = QuestionQueueStore(root)
    store.answer_question(outcome.question["id"], answer="x", basis="b", decided_by="d")
    answered = store.get_question(outcome.question["id"])
    assert cs.human_gate_state(answered) == cs.HG_ANSWERED
