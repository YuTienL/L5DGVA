"""M5 Cohort 4: value resolution for intake fields
(dv_harness/intake_field_resolution.py).

Semantics under test (adapted from Parent's own owner-approved 2026-09-21
semantics, independently re-run and confirmed 24/24 passing in Parent's own
tree before being trusted -- see the module docstring's PROVENANCE section
for the two deliberate departures this migration makes):
  * The eight OpenSpec attributes are the contract's own; REQUIRED /
    APPLICABILITY / NOTES are intake CONTROL metadata and stay separate.
  * Source authority is not value precedence: every candidate and its evidence
    is preserved; one validated source becomes the EffectiveValue; agreeing
    sources are a consensus; conflicting sources are CONTRADICTED and the
    EffectiveValue stays unresolved -- confidence alone never picks a winner.
  * A blank cell means UNRESOLVED_INPUT. Autonomous discovery runs first; a
    question is only allowed when discovery could not resolve a required field.
"""
from __future__ import annotations

import json

import pytest

from dv_harness.intake_field_resolution import (
    OPENSPEC_FIELD_ATTRIBUTES,
    Candidate,
    Confidence,
    ConfirmationState,
    EffectiveValue,
    EvidenceProducer,
    FieldControl,
    ResolutionMethod,
    SourceKind,
    ValidationState,
    ValueState,
    evaluate_question_gate,
    field_is_sufficient,
    file_clarification,
    resolve_field,
    unresolved_blank,
)
from dv_harness.question_queue import QuestionQueueStore

CTL = FieldControl(field_id="command_txt_path", required=True, domain="env",
                   downstream_consumers=("COMMAND_PATTERN", "vPlan"))


def _found(value, *, kind=SourceKind.AUTO_DISCOVERED, source="existing_files", step="existing_files",
           confidence=Confidence.HIGH, refs=("cmd/command.txt",), authority=None, location="cmd/command.txt"):
    cand = Candidate(value=value, kind=kind, source=source, confidence=confidence,
                     evidence_refs=tuple(refs), location=location, authority=authority)
    return EvidenceProducer(step=step, name=source, fn=lambda field_id, ctx: [cand])


def _nothing(name="existing_files", step="existing_files"):
    return EvidenceProducer(step=step, name=name, fn=lambda field_id, ctx: [])


# ------------------------------------------------------------------ contract shape

def test_the_eight_openspec_attributes_are_the_contracts_own_and_control_metadata_is_separate():
    ev = resolve_field(CTL, declared=None, producers=[_found("cmd/command.txt")])
    rec = ev.to_openspec_record()
    assert tuple(rec) == OPENSPEC_FIELD_ATTRIBUTES
    for control_key in ("required", "applicability", "notes"):
        assert control_key not in rec


# ------------------------------------------------------------------ discovery/derivation/question basics

def test_blank_discoverable_field_is_discovered_without_a_question(tmp_path):
    ev = resolve_field(CTL, declared=None, producers=[_found("cmd/command.txt")])
    assert ev.value == "cmd/command.txt"
    assert ev.state is ValueState.CANDIDATE
    assert ev.resolution_method is ResolutionMethod.SINGLE_SOURCE
    rec = ev.to_openspec_record()
    assert rec["auto_discovered_value"] == "cmd/command.txt" and rec["declared_value"] is None
    assert rec["effective_value"] == "cmd/command.txt"
    decision = evaluate_question_gate(CTL, ev)
    assert decision.ask is False
    assert file_clarification(tmp_path, CTL, ev, decision) is None
    assert QuestionQueueStore(tmp_path).list_questions() == []


def test_blank_derivable_field_gets_a_derived_value_and_no_question(tmp_path):
    ctl = FieldControl(field_id="data_width", required=True)
    derived = _found("64", kind=SourceKind.DERIVED, source="derive:DATA_W*8", step="rtl_parameters_defines",
                     refs=("rtl/top.sv:12",), location="rtl/top.sv:12")
    ev = resolve_field(ctl, declared=None, producers=[_nothing(), derived])
    assert ev.value == "64" and ev.state is ValueState.CANDIDATE
    rec = ev.to_openspec_record()
    assert rec["derived_value"] == "64" and rec["auto_discovered_value"] is None
    assert evaluate_question_gate(ctl, ev).ask is False
    assert QuestionQueueStore(tmp_path).list_questions() == []


def test_truly_unknown_required_field_is_asked_after_discovery_was_attempted(tmp_path):
    ev = resolve_field(CTL, declared=None, producers=[_nothing("existing_files", "existing_files"),
                                                      _nothing("rtl_scan", "rtl_parameters_defines")])
    assert ev.value is None and ev.state is ValueState.UNKNOWN
    assert ev.resolution_method is ResolutionMethod.UNRESOLVED
    assert [a.producer for a in ev.attempts] == ["existing_files", "rtl_scan"]
    decision = evaluate_question_gate(CTL, ev)
    assert decision.ask is True and decision.kind == "UNKNOWN"
    q = file_clarification(tmp_path, CTL, ev, decision, context_path="intake/usb_ip_intake.xlsx")
    assert q is not None and q["id"].startswith("Q-")
    text = q["question"]
    assert "command_txt_path" in text
    assert "Attempted evidence sources: existing_files, rtl_scan" in text
    assert "Why user authority is required:" in text
    assert "Downstream impact: consumed by COMMAND_PATTERN, vPlan" in text
    assert "Exact confirmation needed:" in text


def test_asking_twice_for_the_same_field_does_not_duplicate_the_question(tmp_path):
    ev = resolve_field(CTL, declared=None, producers=[_nothing()])
    d = evaluate_question_gate(CTL, ev)
    q1 = file_clarification(tmp_path, CTL, ev, d)
    q2 = file_clarification(tmp_path, CTL, ev, d)
    assert q1["id"] == q2["id"]
    assert len(QuestionQueueStore(tmp_path).list_questions()) == 1


def test_declared_versus_discovered_conflict_is_contradicted_never_silently_overwritten(tmp_path):
    ev = resolve_field(CTL, declared="user/cmd_old.txt",
                       producers=[_found("cmd/command.txt", confidence=Confidence.HIGH)])
    assert ev.state is ValueState.CONTRADICTED
    assert ev.value is None
    assert ev.confirmation_state is ConfirmationState.CONFLICT
    assert ev.resolution_method is ResolutionMethod.UNRESOLVED
    assert {c.value for c in ev.candidates} == {"user/cmd_old.txt", "cmd/command.txt"}
    assert ev.to_openspec_record()["validation_state"] == "CONTRADICTED"
    decision = evaluate_question_gate(CTL, ev)
    assert decision.ask is True and decision.kind == "CONFLICT"
    q = file_clarification(tmp_path, CTL, ev, decision, downstream_impact="COMMAND_PATTERN reads this file")
    labels = [o["label"] for o in q["options"]]
    assert set(labels) == {"user/cmd_old.txt", "cmd/command.txt"}
    assert "cmd/command.txt" in "".join(o["rationale"] for o in q["options"])
    text = q["question"]
    for needed in ("Conflicting values:", "'user/cmd_old.txt'", "user_workbook", "'cmd/command.txt'",
                   "existing_files", "at cmd/command.txt", "Downstream impact: COMMAND_PATTERN reads this file",
                   "Exact confirmation needed:"):
        assert needed in text, needed


def test_confidence_alone_never_selects_a_winner_among_conflicting_values():
    high = _found("A", source="tool_a", confidence=Confidence.HIGH, refs=("a.log",))
    low = _found("B", source="tool_b", confidence=Confidence.MEDIUM, refs=("b.log",))
    ev = resolve_field(CTL, declared=None, producers=[high, low])
    assert ev.state is ValueState.CONTRADICTED and ev.value is None


def test_optional_or_not_applicable_blank_needs_no_question_and_is_sufficient():
    optional = FieldControl(field_id="coverage_goal", required=False)
    ev = resolve_field(optional, declared=None, producers=[_nothing()])
    assert ev.value is None
    assert evaluate_question_gate(optional, ev).ask is False
    assert field_is_sufficient(optional, ev) is True
    na = FieldControl(field_id="dma_channels", required=True, applicable=False)
    ev2 = resolve_field(na, declared=None, producers=[_nothing()])
    assert evaluate_question_gate(na, ev2).ask is False and field_is_sufficient(na, ev2) is True
    required = resolve_field(CTL, declared=None, producers=[_nothing()])
    assert field_is_sufficient(CTL, required) is False


def test_provenance_survives_serialisation_for_discovered_and_derived_values():
    for kind in (SourceKind.AUTO_DISCOVERED, SourceKind.DERIVED):
        ev = resolve_field(CTL, declared=None,
                           producers=[_found("cmd/command.txt", kind=kind, refs=("cmd/command.txt", "Makefile:41"))])
        assert ev.evidence_refs == ("cmd/command.txt", "Makefile:41")
        assert ev.confidence is Confidence.HIGH
        again = EffectiveValue.from_record(json.loads(json.dumps(ev.to_record())))
        assert again == ev
        assert again.evidence_refs == ev.evidence_refs and again.confidence is ev.confidence
        assert again.candidates == ev.candidates and again.resolution_method is ev.resolution_method


# ------------------------------------------------------------------ resolution rules

def test_a_single_declared_value_is_the_effective_value_and_user_confirmed():
    ev = resolve_field(CTL, declared="cmd/command.txt", producers=[])
    assert ev.value == "cmd/command.txt" and ev.state is ValueState.CANDIDATE
    assert ev.resolution_method is ResolutionMethod.SINGLE_SOURCE
    assert ev.confirmation_state is ConfirmationState.CONFIRMED_BY_USER
    assert ev.to_openspec_record()["declared_value"] == "cmd/command.txt"


def test_two_distinct_agreeing_sources_are_a_consensus():
    ev = resolve_field(CTL, declared="cmd/command.txt", producers=[_found("cmd/command.txt")])
    assert ev.state is ValueState.CONFIRMED and ev.resolution_method is ResolutionMethod.CONSENSUS
    assert ev.confirmation_state is ConfirmationState.CONFIRMED_BY_USER
    assert len(ev.candidates) == 2


def test_the_same_source_repeated_is_not_a_consensus():
    p = [_found("X", source="s1"), _found("X", source="s1")]
    ev = resolve_field(CTL, declared=None, producers=p)
    assert ev.resolution_method is ResolutionMethod.SINGLE_SOURCE and ev.state is ValueState.CANDIDATE


def test_an_invalid_candidate_is_kept_but_never_used():
    def validator(field_id, cand):
        return (ValidationState.INVALID, "path does not exist") if cand.value == "bad" else (ValidationState.VALID, "")
    ev = resolve_field(CTL, declared="bad", producers=[], validator=validator)
    assert ev.value is None and ev.state is ValueState.UNKNOWN
    assert [c.value for c in ev.candidates] == ["bad"]
    assert ev.candidates[0].validation is ValidationState.INVALID


def test_validation_can_dissolve_a_conflict_but_confidence_cannot():
    def validator(field_id, cand):
        return (ValidationState.INVALID, "not a file") if cand.value == "user/typo.txt" else (ValidationState.VALID, "")
    ev = resolve_field(CTL, declared="user/typo.txt", producers=[_found("cmd/command.txt")], validator=validator)
    assert ev.value == "cmd/command.txt" and ev.state is ValueState.CANDIDATE


def test_a_candidate_below_the_configured_confidence_threshold_is_not_effective():
    weak = _found("guess.txt", confidence=Confidence.LOW)
    assert resolve_field(CTL, declared=None, producers=[weak], min_confidence=Confidence.MEDIUM).value is None
    assert resolve_field(CTL, declared=None, producers=[weak], min_confidence=Confidence.LOW).value == "guess.txt"


def test_a_failing_producer_is_recorded_and_does_not_break_resolution():
    def boom(field_id, ctx):
        raise RuntimeError("scanner crashed")
    ev = resolve_field(CTL, declared=None, producers=[EvidenceProducer("existing_files", "scanner", boom),
                                                      _found("cmd/command.txt", step="design_documents", source="doc")])
    assert ev.value == "cmd/command.txt"
    assert [(a.producer, a.outcome) for a in ev.attempts] == [("scanner", "ERROR"), ("doc", "FOUND")]


def test_producers_run_in_evidence_ladder_order_regardless_of_registration_order():
    order = []
    def mk(step, name):
        def fn(field_id, ctx):
            order.append(name)
            return []
        return EvidenceProducer(step, name, fn)
    resolve_field(CTL, declared=None, producers=[mk("git_history", "git"), mk("existing_files", "files"),
                                                 mk("rtl_parameters_defines", "rtl")])
    assert order == ["files", "rtl", "git"]


# ------------------------------------------------------------------ authority vs precedence

def test_authorised_evidence_resolves_a_conflict_by_source_authority_and_says_so():
    rtl = _found("8", source="rtl_scan", authority="dut_rtl", refs=("rtl/top.sv:30",), location="rtl/top.sv:30")
    doc = _found("16", source="ug_scan", authority="ip_user_guide", refs=("doc/ug.pdf:p7",), location="doc/ug.pdf:p7")
    ev = resolve_field(CTL, declared=None, producers=[rtl, doc])
    assert ev.value == "8" and ev.state is ValueState.CONFIRMED
    assert ev.resolution_method is ResolutionMethod.AUTHORIZED_EVIDENCE
    assert ev.confirmation_state is ConfirmationState.CONFIRMED_BY_EVIDENCE
    assert {c.value for c in ev.candidates} == {"8", "16"}, "the losing candidate stays on record"
    assert "dut_rtl" in ev.notes and "ip_user_guide" in ev.notes


def test_equal_authority_disagreement_stays_contradicted():
    a = _found("1", source="rtl_a", authority="dut_rtl", refs=("a.sv:1",))
    b = _found("2", source="rtl_b", authority="dut_rtl", refs=("b.sv:1",))
    ev = resolve_field(CTL, declared=None, producers=[a, b])
    assert ev.state is ValueState.CONTRADICTED and ev.value is None


def test_a_declared_value_has_no_authority_rank_so_it_can_only_be_resolved_by_a_human():
    rtl = _found("8", source="rtl_scan", authority="dut_rtl", refs=("rtl/top.sv:30",))
    ev = resolve_field(CTL, declared="16", producers=[rtl])
    assert ev.state is ValueState.CONTRADICTED and ev.value is None


def test_a_human_answer_resolves_a_contradiction_and_keeps_every_candidate():
    ev = resolve_field(CTL, declared="user/cmd_old.txt", producers=[_found("cmd/command.txt")],
                       human_answer="cmd/command.txt")
    assert ev.value == "cmd/command.txt" and ev.state is ValueState.CONFIRMED
    assert ev.resolution_method is ResolutionMethod.HUMAN_CONFIRMED
    assert ev.confirmation_state is ConfirmationState.CONFIRMED_BY_USER
    assert len(ev.candidates) == 2 and "human_answer" in ev.evidence_refs


# ------------------------------------------------------------------ the question gate

def test_a_blank_that_never_went_through_discovery_may_not_reach_the_question_queue(tmp_path):
    ev = unresolved_blank(CTL)
    d = evaluate_question_gate(CTL, ev)
    assert d.ask is False and "DISCOVERY_NOT_ATTEMPTED" in d.reasons
    assert file_clarification(tmp_path, CTL, ev, d) is None
    assert QuestionQueueStore(tmp_path).list_questions() == []


def test_a_confirmation_required_field_asks_even_when_only_discovered():
    ctl = FieldControl(field_id="verification_scope", required=True, confirmation_required=True)
    ev = resolve_field(ctl, declared=None, producers=[_found("IP", refs=("lifecycle.json",))])
    d = evaluate_question_gate(ctl, ev)
    assert d.ask is True and d.kind == "CONFIRMATION"
    confirmed = resolve_field(ctl, declared="IP", producers=[_found("IP", refs=("lifecycle.json",))])
    assert evaluate_question_gate(ctl, confirmed).ask is False


def test_a_conflict_with_more_than_three_sides_is_refused_rather_than_truncated(tmp_path):
    prods = [_found(str(i), source=f"s{i}", refs=(f"f{i}",)) for i in range(4)]
    ev = resolve_field(CTL, declared=None, producers=prods)
    d = evaluate_question_gate(CTL, ev)
    with pytest.raises(ValueError):
        file_clarification(tmp_path, CTL, ev, d)


# ------------------------------------------------------------------ canonical-specific: KNOWN_TECHNICAL_GAPS

def test_structured_clarification_context_gap_is_open_not_closed_in_canonical():
    """This Cohort's own deliberate departure from Parent (module docstring,
    PROVENANCE point 2): Parent's closure of this gap depends on
    intake_clarification.py/intake_resume.py, neither of which exists in
    canonical -- so it must be tracked here as an open gap, not silently
    imported as already-closed."""
    from dv_harness import intake_field_resolution as ifr
    assert "STRUCTURED_CLARIFICATION_CONTEXT_NOT_PERSISTED" in ifr.KNOWN_TECHNICAL_GAPS
    assert "STRUCTURED_CLARIFICATION_CONTEXT_NOT_PERSISTED" not in ifr.CLOSED_TECHNICAL_GAPS
