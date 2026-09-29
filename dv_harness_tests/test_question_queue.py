"""Tests for dv_harness/question_queue.py -- the 3-tier ask-a-human protocol
(spec Part B): tier classification (both directions), owner routing, the
repeat-question-rate=0 persistence guarantee, digest batching, and the 4
tracking metrics.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dv_harness.question_queue import (
    DIGEST_BOUNDARY_STAGES,
    SIGNOFF_EVIDENCE_KIND_BLOCKER_LIST,
    SIGNOFF_EVIDENCE_KIND_BUNDLE,
    SIGNOFF_EVIDENCE_KIND_COVERAGE_CLOSURE,
    SIGNOFF_EVIDENCE_KIND_PROVENANCE_CAVEAT,
    SIGNOFF_EVIDENCE_KINDS,
    CosignNotApplicableError,
    DoNotAskError,
    ESCALATION_PACKAGE_FIELDS,
    HUMAN_DECISION_SOURCE,
    TIER2_AUTO_ASSUMPTION_SOURCE,
    QuestionQueueStore,
    QuestionValidationError,
    TIER1_SELF_RESOLVE,
    TIER2_SAFE_ASSUME,
    TIER3_CANNOT_ASSUME,
    assert_all_evidence_paths_present,
    build_escalation_package,
    build_multiple_choice_question,
    build_suggest_then_confirm_options,
    classify_tier,
    derive_suggested_answer_from_design_source_inventory,
    derive_suggested_answer_from_env_manifest,
    file_signoff_evidence_question,
    find_redundant_decision,
    is_cannot_assume,
    make_question_id,
    make_question_key,
    normalize_grounding_evidence,
    normalize_options,
    normalize_suggested_answer,
    render_clarification_markdown,
    render_escalation_package_markdown,
    request_clarification,
    list_clarification_requests,
    route_owner,
    validate_question,
)


def _opts():
    return [
        {"label": "Configure as bus slave/responder", "rationale": "DUT port direction at this boundary is master-only."},
        {"label": "Configure as bus master/initiator", "rationale": "fallback if DUT is actually the responder."},
    ]


# --- Tier classification: hard-coded Tier-3 trigger (both directions) --------

def test_tier3_fires_on_pass_fail_verdict_trigger():
    ctx = {"affects_pass_fail_verdict": True}
    assert is_cannot_assume(ctx) is True
    result = classify_tier(ctx)
    assert result["tier"] == TIER3_CANNOT_ASSUME
    assert "affects_pass_fail_verdict" in result["matched_triggers"]


def test_tier3_fires_on_spec_intent_trigger():
    ctx = {"affects_spec_intent": True}
    assert classify_tier(ctx)["tier"] == TIER3_CANNOT_ASSUME


def test_tier3_fires_on_read_only_file_change_trigger():
    ctx = {"affects_read_only_file_change": True}
    assert classify_tier(ctx)["tier"] == TIER3_CANNOT_ASSUME


def test_tier3_fires_when_blast_radius_exceeds_single_regression():
    # Not one of the 3 named hard triggers, but still not "safe to assume"
    # per Part B's own bar ("worst case = one wasted regression").
    ctx = {"blast_radius": "multi_regression"}
    result = classify_tier(ctx)
    assert result["tier"] == TIER3_CANNOT_ASSUME
    assert result["reason"].startswith("blast_radius_exceeds_safe_assume_bound")


def test_genuine_tier2_case_no_triggers_low_blast_radius():
    ctx = {"affects_pass_fail_verdict": False, "affects_spec_intent": False,
           "affects_read_only_file_change": False, "blast_radius": "single_regression"}
    assert is_cannot_assume(ctx) is False
    result = classify_tier(ctx)
    assert result["tier"] == TIER2_SAFE_ASSUME
    assert result["matched_triggers"] == []


def test_genuine_tier1_case_resolvable_from_manifest():
    ctx = {"resolvable_from_manifest": True, "manifest_value": "ACTIVE"}
    result = classify_tier(ctx)
    assert result["tier"] == TIER1_SELF_RESOLVE
    assert result["reason"] == "resolvable_from_manifest"


def test_prior_HUMAN_decision_overrides_hard_triggers():
    # Even a question whose context would otherwise be a slam-dunk Tier-3
    # must resolve at Tier 1 once a HUMAN's answer is already on file -- a
    # human's answer is never re-litigated. Source matters: see
    # test_prior_tier2_auto_assumption_does_NOT_override_hard_triggers.
    ctx = {"affects_pass_fail_verdict": True}
    result = classify_tier(ctx, prior_decision={"current": {"answer": "yes", "source": "human_answer"}})
    assert result["tier"] == TIER1_SELF_RESOLVE
    assert result["reason"] == "decisions_store_hit"


def test_prior_tier2_auto_assumption_does_NOT_override_hard_triggers():
    # Review defect F3-a, unit level: a decision the harness minted for
    # ITSELF is a machine guess, not an answer, and must never let the
    # harness resolve its own later escalation with it.
    ctx = {"affects_pass_fail_verdict": True}
    result = classify_tier(ctx, prior_decision={"current": {"answer": "guess",
                                                             "source": "tier2_auto_assumption"}})
    assert result["tier"] == TIER3_CANNOT_ASSUME
    assert "affects_pass_fail_verdict" in result["matched_triggers"]
    assert "overrides_prior_non_human_decision" in result["reason"]


def test_prior_decision_without_a_source_is_not_treated_as_human():
    # Fail closed: an entry with no recorded `source` (a hand-written or
    # legacy record) is not evidence a human answered, so it must not
    # shortcut a hard-trigger question.
    result = classify_tier({"affects_spec_intent": True}, prior_decision={"current": {"answer": "yes"}})
    assert result["tier"] == TIER3_CANNOT_ASSUME


def test_manifest_shortcut_is_gated_on_is_cannot_assume():
    # Review defect F3-b, unit level: the manifest shortcut must not fire
    # for a question whose own context trips a hard trigger, regardless of
    # what the lookup would return.
    ctx = {"affects_spec_intent": True, "resolvable_from_manifest": True,
           "manifest_value": {"TX_ERR": {"offset": "0x40"}}}
    result = classify_tier(ctx)
    assert result["tier"] == TIER3_CANNOT_ASSUME
    assert result["reason"].startswith("hard_trigger:")


# --- Owner routing -------------------------------------------------------------

def test_owner_routing_literal_table():
    assert route_owner("vip") == "DV-owner/Synopsys-AE"
    assert route_owner("dut") == "designer"
    assert route_owner("env") == "DV-owner"
    assert route_owner("VIP") == "DV-owner/Synopsys-AE"  # case-insensitive


def test_owner_routing_rejects_unknown_domain():
    with pytest.raises(ValueError):
        route_owner("firmware")


# --- Q-ID / question_key helpers ------------------------------------------------

def test_question_id_is_domain_prefixed_and_stable_per_key():
    key = make_question_key("vip", "Is the USB VIP a slave?", "vip.usb0.mode")
    id1 = make_question_id("vip", key)
    id2 = make_question_id("vip", key)
    assert id1 == id2
    assert id1.startswith("Q-VIP-")


# --- validate_question: recommendation must be an offered option ----------------

def test_validate_question_rejects_recommendation_not_in_options(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="vip", question="Slave or master?", context_path="vip.usb0.mode",
        options=_opts(), recommendation=_opts()[0]["label"],
        assumption_if_unanswered="Configure as bus slave/responder (DUT is master-only at this boundary).",
    )
    assert q["recommendation"] == _opts()[0]["label"]
    bad = dict(q)
    bad["recommendation"] = "Some option never offered"
    with pytest.raises(QuestionValidationError):
        validate_question(bad)


def test_validate_question_rejects_fewer_than_two_options():
    with pytest.raises(QuestionValidationError):
        validate_question({
            "schema_version": "1.0", "id": "Q-VIP-DEADBEEF", "question_key": "k",
            "blocking": True, "domain": "vip", "owner": "DV-owner/Synopsys-AE",
            "question": "q?", "context_path": "p", "options": [{"label": "only one"}],
            "recommendation": "only one", "assumption_if_unanswered": "a",
            "tier": 3, "tier_reason": "x", "status": "OPEN", "created_at": "2026-09-03T00:00:00+00:00",
        })


# --- add_question: tier routing end to end --------------------------------------

def test_add_question_tier3_is_open_and_blocking(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Does bin0 mean PASS?", context_path="dut.scoreboard.bin0",
        options=_opts(), recommendation=_opts()[0]["label"],
        assumption_if_unanswered="n/a", context={"affects_pass_fail_verdict": True},
    )
    assert q["tier"] == TIER3_CANNOT_ASSUME
    assert q["blocking"] is True
    assert q["status"] == "OPEN"
    assert q["answer"] is None
    assert q["owner"] == "designer"


def test_add_question_tier2_is_assumed_and_logged_not_blocking(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="env", question="Is monitor0 passive-only?", context_path="env.topology.monitor0",
        options=_opts(), recommendation=_opts()[0]["label"],
        assumption_if_unanswered="Treat monitor0 as passive-only.",
    )
    assert q["tier"] == TIER2_SAFE_ASSUME
    assert q["blocking"] is False
    assert q["status"] == "ASSUMED"
    assert q["answer"] == "Treat monitor0 as passive-only."
    # Tier-2 auto-assumption is persisted immediately (log-and-continue).
    decision = store.find_decision(q["question_key"])
    assert decision is not None
    assert decision["ever_tier2_assumed"] is True


def test_add_question_never_prints_or_notifies_only_persists(tmp_path, capsys):
    store = QuestionQueueStore(tmp_path)
    store.add_question(
        domain="env", question="q?", context_path="p", options=_opts(),
        recommendation=_opts()[0]["label"], assumption_if_unanswered="a",
    )
    out = capsys.readouterr().out
    assert out == ""  # no real-time ping -- digest is the only reporting path


# --- Repeat-question-rate == 0 guarantee ----------------------------------------

def test_asking_the_same_question_twice_self_resolves_the_second_time(tmp_path):
    store = QuestionQueueStore(tmp_path)
    kwargs = dict(
        domain="dut", question="Is register R0 write-1-to-clear?", context_path="dut.regs.R0",
        options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
        context={"affects_pass_fail_verdict": True},  # a genuine Tier-3 trigger the FIRST time
    )
    first = store.add_question(**kwargs)
    assert first["tier"] == TIER3_CANNOT_ASSUME
    assert first["status"] == "OPEN"

    answered = store.answer_question(first["id"], answer="Yes, W1C.", basis="RTL reg_map.sv line 42",
                                       decided_by="designer@example.com")
    assert answered["status"] == "ANSWERED"

    # Ask the EXACT same question again (same domain/question/context_path ->
    # same question_key). Even though the context still claims a Tier-3
    # hard trigger, the persisted decision must win: Tier 1, self-resolved,
    # not a fresh escalation.
    second = store.add_question(**kwargs)
    assert second["id"] == first["id"]  # same Q-ID (stable per question_key)
    assert second["tier"] == TIER1_SELF_RESOLVE
    assert second["status"] == "SELF_RESOLVED"
    assert second["answer"] == "Yes, W1C."
    assert second["resolved_from_decision_id"] == first["id"]

    metrics = store.compute_metrics()
    assert metrics["repeat_question_rate_percent"] == 0.0


def test_repeat_question_rate_is_nonzero_if_prior_decision_is_ignored(tmp_path):
    # Direct unit-level proof that the metric actually measures something
    # real (not hardcoded 0): synthesize a broken-persistence scenario by
    # hand-crafting question records where a repeat ask did NOT resolve at
    # Tier 1, and confirm compute_metrics reports it.
    store = QuestionQueueStore(tmp_path)
    data = store._load_questions()
    base = {
        "schema_version": "1.0", "domain": "dut", "owner": "designer",
        "question": "q?", "context_path": "p", "options": _opts(),
        "recommendation": _opts()[0]["label"], "assumption_if_unanswered": "a",
        "answered_at": None, "answer": None, "basis": None, "decided_by": None,
        "overturned": False, "resolved_from_decision_id": None,
        "digest_batch_id": None, "digest_emitted_at": None,
    }
    q1 = {**base, "id": "Q-DUT-00000001", "question_key": "k1", "blocking": True,
          "tier": 3, "tier_reason": "hard_trigger:affects_pass_fail_verdict",
          "status": "ANSWERED", "created_at": "2026-09-01T00:00:00+00:00"}
    # A second ask of the SAME question_key that (bug scenario) escalated
    # again as Tier 3 instead of self-resolving.
    q2 = {**base, "id": "Q-DUT-00000001", "question_key": "k1", "blocking": True,
          "tier": 3, "tier_reason": "hard_trigger:affects_pass_fail_verdict",
          "status": "OPEN", "created_at": "2026-09-02T00:00:00+00:00"}
    data["questions"] = [q1, q2]
    store._save_questions(data)
    metrics = store.compute_metrics()
    assert metrics["repeat_question_rate_percent"] == 100.0


# --- Tier-3 bypass regression tests (2026-09-03 review defects F3-a/F3-b) ---------
#
# The two reviewer repros, reproduced literally end-to-end through the same
# shipped code path (QuestionQueueStore.add_question) an agent uses. Each
# proved a genuine Tier-3 (cannot-assume, must-escalate) question resolving
# silently at Tier 1 with a machine-generated answer, with no human ever in
# the loop. If either of these ever goes green-to-red again, the harness's
# core "a cannot-assume question always stops for a human" promise is broken.

_SPEC_INTENT_Q = "Is a dropped packet flagged in TX_ERR a legal drop per spec, or a real DUT failure?"
_ALL_HARD_TRIGGERS = {
    "affects_pass_fail_verdict": True,
    "affects_spec_intent": True,
    "affects_read_only_file_change": True,
    "blast_radius": "unbounded",
}


def test_F3a_tier2_auto_assumption_does_not_suppress_a_later_genuine_tier3(tmp_path):
    """F3-a repro: ask a low-risk-looking question first (no risk flags) ->
    Tier 2, auto-assumed, decision persisted. Ask the SAME question_key
    again with every Tier-3 hard trigger set. Before the fix this returned
    Tier 1 'decisions_store_hit' and answered the escalation with the
    harness's own earlier guess."""
    store = QuestionQueueStore(tmp_path)
    common = dict(domain="dut", question=_SPEC_INTENT_Q, context_path="dut.regs.TX_ERR",
                  options=_opts(), recommendation=_opts()[0]["label"],
                  assumption_if_unanswered="Assume legal drop per spec.")

    first = store.add_question(**common, context={})
    assert first["tier"] == TIER2_SAFE_ASSUME
    assert first["status"] == "ASSUMED"
    decision = store.find_decision(first["question_key"])
    assert decision["current"]["source"] == "tier2_auto_assumption"

    second = store.add_question(**common, context=dict(_ALL_HARD_TRIGGERS))
    assert second["question_key"] == first["question_key"]  # genuinely the same question
    assert second["tier"] == TIER3_CANNOT_ASSUME
    assert second["blocking"] is True
    assert second["status"] == "OPEN"
    # Not silently resolved with the harness's own earlier guess.
    assert second["answer"] is None
    assert second["decided_by"] is None
    assert second["resolved_from_decision_id"] is None
    assert "overrides_prior_non_human_decision" in second["tier_reason"]

    # And it is genuinely escalated: OPEN/blocking means it reaches a human
    # through the digest, which a SELF_RESOLVED record never would.
    digest = store.build_digest(trigger="manual")
    assert second["id"] in [q["id"] for q in digest["questions"]]


def test_F3b_manifest_lookup_cannot_resolve_a_hard_trigger_question(tmp_path):
    """F3-b repro: a pure spec-intent question, asked against a store with a
    manifest_lookup wired in that returns an unrelated register dict. Before
    the fix the manifest shortcut ran ahead of the hard-trigger check and
    resolved this at Tier 1, answering 'is this drop legal per spec?' with a
    register's offset/width/access."""
    unrelated_fact = {"TX_ERR": {"offset": "0x40", "width": 32, "access": "RW"}}
    lookups = []

    def lookup(context_path):
        lookups.append(context_path)
        return unrelated_fact

    store = QuestionQueueStore(tmp_path, manifest_lookup=lookup)
    q = store.add_question(
        domain="dut", question=_SPEC_INTENT_Q, context_path="dut.regs.TX_ERR",
        options=_opts(), recommendation=_opts()[0]["label"],
        assumption_if_unanswered="Assume legal drop per spec.",
        context={"affects_pass_fail_verdict": True, "affects_spec_intent": True,
                 "blast_radius": "unbounded"},
    )
    assert q["tier"] == TIER3_CANNOT_ASSUME
    assert q["blocking"] is True
    assert q["status"] == "OPEN"
    assert q["answer"] is None
    assert q["tier_reason"].startswith("hard_trigger:")
    # The lookup is not merely overruled -- it is never consulted at all for
    # a cannot-assume question.
    assert lookups == []


def test_manifest_lookup_still_resolves_a_genuinely_low_risk_question(tmp_path):
    # The F3-b gate must not disable the legitimate Tier-1 manifest path.
    store = QuestionQueueStore(tmp_path, manifest_lookup=lambda p: "ACTIVE")
    q = store.add_question(
        domain="env", question="Is agent0 active or passive?", context_path="env.agents.agent0.is_active",
        options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="a",
    )
    assert q["tier"] == TIER1_SELF_RESOLVE
    assert q["tier_reason"] == "resolvable_from_manifest"
    assert q["answer"] == "ACTIVE"
    assert q["decided_by"] == "env.manifest.json"


def test_schema_rejects_a_tier3_record_that_is_not_blocking():
    # The review's proof case: a hand-built non-blocking, self-resolved
    # Tier-3 record used to pass validate_question() cleanly.
    with pytest.raises(QuestionValidationError):
        validate_question({
            "schema_version": "1.0", "id": "Q-DUT-DEADBEEF", "question_key": "k",
            "blocking": False, "domain": "dut", "owner": "designer",
            "question": "q?", "context_path": "p", "options": _opts(),
            "recommendation": _opts()[0]["label"], "assumption_if_unanswered": "a",
            "tier": 3, "tier_reason": "hand-built", "status": "SELF_RESOLVED",
            "created_at": "2026-09-03T00:00:00+00:00",
        })


def test_schema_still_accepts_a_blocking_tier3_record():
    validate_question({
        "schema_version": "1.0", "id": "Q-DUT-DEADBEEF", "question_key": "k",
        "blocking": True, "domain": "dut", "owner": "designer",
        "question": "q?", "context_path": "p", "options": _opts(),
        "recommendation": _opts()[0]["label"], "assumption_if_unanswered": "a",
        "tier": 3, "tier_reason": "hard_trigger:affects_spec_intent", "status": "OPEN",
        "created_at": "2026-09-03T00:00:00+00:00",
    })


# --- revoke: the sanctioned undo for a persisted decision ---------------------------

def test_revoke_clears_an_auto_assumed_decision_so_the_next_ask_reclassifies(tmp_path):
    store = QuestionQueueStore(tmp_path)
    common = dict(domain="env", question="Is monitor3 passive-only?", context_path="env.topology.monitor3",
                  options=_opts(), recommendation=_opts()[0]["label"],
                  assumption_if_unanswered="Treat monitor3 as passive-only.")
    q = store.add_question(**common)
    assert q["tier"] == TIER2_SAFE_ASSUME
    assert store.find_decision(q["question_key"]) is not None

    revocation = store.revoke_decision(q["question_key"], reason="assumption was wrong per topology print",
                                         revoked_by="dv_owner@example.com")
    assert revocation["question_key"] == q["question_key"]
    assert revocation["revoked_by"] == "dv_owner@example.com"
    assert revocation["revoked_decision"]["current"]["source"] == "tier2_auto_assumption"
    # Gone from the live store -- it can no longer shortcut anything.
    assert store.find_decision(q["question_key"]) is None
    # But preserved as an audit record, in both the JSON and decisions.md.
    assert store._load_decisions()["revoked"][0]["reason"] == "assumption was wrong per topology print"
    md = store.decisions_md_path.read_text(encoding="utf-8")
    assert "Revoked decisions" in md
    assert "assumption was wrong per topology print" in md


def test_revoke_lets_a_human_answer_be_re_asked(tmp_path):
    store = QuestionQueueStore(tmp_path)
    common = dict(domain="dut", question="Is R1 W1C?", context_path="dut.regs.R1",
                  options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
                  context={"affects_pass_fail_verdict": True})
    first = store.add_question(**common)
    store.answer_question(first["id"], answer="Yes, W1C.", basis="RTL line 42", decided_by="designer@example.com")
    assert store.add_question(**common)["tier"] == TIER1_SELF_RESOLVE

    store.revoke_decision(first["question_key"], reason="RTL changed in rev B", revoked_by="designer@example.com")
    after = store.add_question(**common)
    assert after["tier"] == TIER3_CANNOT_ASSUME
    assert after["status"] == "OPEN"
    # A deliberately revoked key is not counted as a persistence failure.
    assert store.compute_metrics()["repeat_question_rate_percent"] == 0.0


def test_revoke_unknown_question_key_raises(tmp_path):
    store = QuestionQueueStore(tmp_path)
    with pytest.raises(KeyError):
        store.revoke_decision("no-such-key", reason="x")


# --- decisions.md persistence ----------------------------------------------------

def test_decisions_md_is_generated_and_contains_the_answer(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="vip", question="Is the VIP a slave here?", context_path="vip.axi0.role",
        options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
        context={"affects_spec_intent": True},
    )
    store.answer_question(q["id"], answer="Yes, slave/responder.", basis="DUT AXI port is master-only.",
                            decided_by="dv_owner@example.com")
    text = store.decisions_md_path.read_text(encoding="utf-8")
    assert "vip.axi0.role" in text
    assert "Yes, slave/responder." in text
    assert "dv_owner@example.com" in text


# --- Assumption-overturned-rate ---------------------------------------------------

def test_assumption_overturned_rate_reflects_a_real_overturn(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="env", question="Is monitor1 active or passive?", context_path="env.topology.monitor1",
        options=_opts(), recommendation=_opts()[0]["label"],
        assumption_if_unanswered="Treat monitor1 as passive-only.",
    )
    assert q["tier"] == TIER2_SAFE_ASSUME
    before = store.compute_metrics()["assumption_overturned_rate_percent"]
    assert before == 0.0

    # Human later provides a genuinely different real answer -- this is the
    # Tier-2 assumption being overturned.
    store.answer_question(q["id"], answer="Actually active -- it also drives.",
                            basis="waveform shows monitor1 driving AWVALID", decided_by="dv_owner@example.com")
    after = store.compute_metrics()["assumption_overturned_rate_percent"]
    assert after == 100.0


def test_assumption_confirmed_unchanged_is_not_counted_as_overturned(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="env", question="Is monitor2 active or passive?", context_path="env.topology.monitor2",
        options=_opts(), recommendation=_opts()[0]["label"],
        assumption_if_unanswered="Treat monitor2 as passive-only.",
    )
    store.answer_question(q["id"], answer="Treat monitor2 as passive-only.",
                            basis="confirmed via topology print", decided_by="dv_owner@example.com")
    assert store.compute_metrics()["assumption_overturned_rate_percent"] == 0.0


# --- Digest batching --------------------------------------------------------------

def test_digest_manual_trigger_emits_pending_and_groups_by_owner(tmp_path):
    store = QuestionQueueStore(tmp_path)
    store.add_question(domain="vip", question="q1?", context_path="p1", options=_opts(),
                         recommendation=_opts()[0]["label"], assumption_if_unanswered="a",
                         context={"affects_pass_fail_verdict": True})
    store.add_question(domain="dut", question="q2?", context_path="p2", options=_opts(),
                         recommendation=_opts()[0]["label"], assumption_if_unanswered="a",
                         context={"affects_spec_intent": True})
    digest = store.build_digest(trigger="manual")
    assert digest["emitted"] is True
    assert len(digest["questions"]) == 2
    assert "DV-owner/Synopsys-AE" in digest["by_owner"]
    assert "designer" in digest["by_owner"]


def test_digest_does_not_reemit_already_batched_questions(tmp_path):
    store = QuestionQueueStore(tmp_path)
    store.add_question(domain="vip", question="q1?", context_path="p1", options=_opts(),
                         recommendation=_opts()[0]["label"], assumption_if_unanswered="a",
                         context={"affects_pass_fail_verdict": True})
    first = store.build_digest(trigger="manual")
    assert first["emitted"] is True
    second = store.build_digest(trigger="manual")
    assert second["emitted"] is False  # nothing NEW pending


def test_digest_stage_boundary_trigger_only_fires_on_known_boundary_stages(tmp_path):
    store = QuestionQueueStore(tmp_path)
    store.add_question(domain="env", question="q?", context_path="p", options=_opts(),
                         recommendation=_opts()[0]["label"], assumption_if_unanswered="a",
                         context={"affects_read_only_file_change": True})
    not_a_boundary = store.build_digest(trigger="stage_boundary", stage="VERIFY")
    assert not_a_boundary["emitted"] is False
    assert "REGRESSION_MONITOR" in DIGEST_BOUNDARY_STAGES
    is_a_boundary = store.build_digest(trigger="stage_boundary", stage="REGRESSION_MONITOR")
    assert is_a_boundary["emitted"] is True


def test_digest_scheduled_trigger_respects_min_hours_since_last(tmp_path):
    store = QuestionQueueStore(tmp_path)
    t0 = datetime(2026, 9, 3, 8, 0, 0, tzinfo=timezone.utc)
    store.add_question(domain="env", question="q1?", context_path="p1", options=_opts(),
                         recommendation=_opts()[0]["label"], assumption_if_unanswered="a",
                         context={"affects_read_only_file_change": True}, now=t0)
    first = store.build_digest(trigger="scheduled", now=t0, min_hours_since_last=24.0)
    assert first["emitted"] is True

    store.add_question(domain="env", question="q2?", context_path="p2", options=_opts(),
                         recommendation=_opts()[0]["label"], assumption_if_unanswered="a",
                         context={"affects_read_only_file_change": True}, now=t0 + timedelta(hours=1))
    too_soon = store.build_digest(trigger="scheduled", now=t0 + timedelta(hours=2), min_hours_since_last=24.0)
    assert too_soon["emitted"] is False

    later = store.build_digest(trigger="scheduled", now=t0 + timedelta(hours=25), min_hours_since_last=24.0)
    assert later["emitted"] is True


# --- Metrics ------------------------------------------------------------------------

def test_self_resolve_rate_and_blocking_per_week(tmp_path):
    store = QuestionQueueStore(tmp_path)
    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    # 1 tier-1 (resolvable from manifest), 1 tier-2, 2 tier-3 -> self_resolve = 1/4 = 25%
    store.add_question(domain="env", question="q1?", context_path="p1", options=_opts(),
                         recommendation=_opts()[0]["label"], assumption_if_unanswered="a",
                         context={"resolvable_from_manifest": True, "manifest_value": "ACTIVE"}, now=now)
    store.add_question(domain="env", question="q2?", context_path="p2", options=_opts(),
                         recommendation=_opts()[0]["label"], assumption_if_unanswered="a", now=now)
    store.add_question(domain="dut", question="q3?", context_path="p3", options=_opts(),
                         recommendation=_opts()[0]["label"], assumption_if_unanswered="a",
                         context={"affects_pass_fail_verdict": True}, now=now)
    store.add_question(domain="vip", question="q4?", context_path="p4", options=_opts(),
                         recommendation=_opts()[0]["label"], assumption_if_unanswered="a",
                         context={"affects_spec_intent": True}, now=now)
    metrics = store.compute_metrics(now=now, window_days=7)
    assert metrics["self_resolve_rate_percent"] == 25.0
    assert metrics["tier3_count"] == 2
    assert metrics["blocking_questions_per_week"] == 2.0
    assert metrics["open_blocking_count"] == 2


def test_metrics_on_empty_store_are_well_defined(tmp_path):
    store = QuestionQueueStore(tmp_path)
    metrics = store.compute_metrics()
    assert metrics["total_questions"] == 0
    assert metrics["self_resolve_rate_percent"] == 0.0
    assert metrics["repeat_question_rate_percent"] == 0.0
    assert metrics["assumption_overturned_rate_percent"] == 0.0


# --- options normalization: the spec's literal flat-string shape ----------------
# Before this, add_question() indexed `o["label"]` directly, so the spec's own
# ["option a", "option b"] example shape died on a raw
# `TypeError: string indices must be integers` -- not a QuestionValidationError
# a caller could act on -- and three separate call sites each carried their own
# `o if isinstance(o, dict) else {"label": str(o)}` copy to work around it.

def test_add_question_accepts_plain_string_options_and_persists_canonical_shape(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="vip", question="8b10b or 128b130b?", context_path="vip.usb0.encoding",
        options=["keep 8b10b", "switch to 128b130b"], recommendation="keep 8b10b",
        assumption_if_unanswered="keep 8b10b",
    )
    # Accepted as input, but stored in the ONE canonical object shape.
    assert q["options"] == [{"label": "keep 8b10b"}, {"label": "switch to 128b130b"}]
    validate_question(q)
    # And it round-trips through the real store, not just the return value.
    assert store.get_question(q["id"])["options"] == q["options"]


def test_add_question_still_accepts_object_options_with_rationale(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="vip", question="Slave or master?", context_path="vip.usb0.mode",
        options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="a",
    )
    assert q["options"][0]["rationale"].startswith("DUT port direction")
    validate_question(q)


def test_mixed_string_and_object_options_normalize_together(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="env", question="Which topology?", context_path="env.top",
        options=["flat", {"label": "hierarchical", "rationale": "matches the config_db trace"}],
        recommendation="hierarchical", assumption_if_unanswered="flat",
    )
    assert q["options"] == [
        {"label": "flat"},
        {"label": "hierarchical", "rationale": "matches the config_db trace"},
    ]
    validate_question(q)


def test_normalize_options_is_the_single_definition_used_by_add_question():
    # The helper's own contract, independent of a store.
    assert normalize_options(["a", "b"]) == [{"label": "a"}, {"label": "b"}]
    # A falsy/absent rationale is dropped rather than persisted as null --
    # question.schema.json's options.items has additionalProperties:false and
    # no null-typed rationale, so emitting one would fail validation.
    assert normalize_options([{"label": "a", "rationale": ""}]) == [{"label": "a"}]


@pytest.mark.parametrize("bad, needle", [
    ([{"lable": "typo"}, "b"], "label"),          # misspelled key caught at the door
    ([{"label": "a", "why": "x"}, "b"], "unknown key"),
    ([123, "b"], "must be a string"),
    (["", "b"], "empty label"),
    ("not-a-list", "must be a list"),
])
def test_normalize_options_raises_validation_error_never_typeerror(bad, needle):
    with pytest.raises(QuestionValidationError) as exc:
        normalize_options(bad)
    assert needle in str(exc.value)


def test_add_question_rejects_malformed_options_before_persisting_anything(tmp_path):
    store = QuestionQueueStore(tmp_path)
    with pytest.raises(QuestionValidationError):
        store.add_question(
            domain="vip", question="q?", context_path="p",
            options=[{"lable": "typo"}, "other"], recommendation="other",
            assumption_if_unanswered="a",
        )
    # Nothing was written -- the raise happens before the append/save.
    assert store.list_questions() == []


# =================================================================================
# (a) Do-not-ask enforcement: find_redundant_decision() + add_question(enforce_do_not_ask=True)
# =================================================================================

def test_find_redundant_decision_none_when_no_prior():
    assert find_redundant_decision(None, {}) is None


def test_find_redundant_decision_human_answer_is_always_redundant():
    # A human answer makes a re-ask redundant regardless of the new ask's
    # own context -- even one that would otherwise be a slam-dunk Tier-3 --
    # mirroring classify_tier()'s own step 2 ("a human answer on file DOES
    # still win over a hard trigger").
    prior = {"current": {"source": HUMAN_DECISION_SOURCE, "answer": "yes",
                          "decided_by": "designer@example.com", "decided_at": "2026-09-01T00:00:00+00:00"}}
    assert find_redundant_decision(prior, {"affects_pass_fail_verdict": True}) is prior
    assert find_redundant_decision(prior, {}) is prior


def test_find_redundant_decision_tier2_auto_assumption_redundant_when_no_new_hard_trigger():
    prior = {"current": {"source": TIER2_AUTO_ASSUMPTION_SOURCE, "answer": "guess"}}
    assert find_redundant_decision(prior, {}) is prior
    assert find_redundant_decision(prior, {"blast_radius": "single_regression"}) is prior


def test_find_redundant_decision_tier2_auto_assumption_NOT_redundant_over_a_hard_trigger():
    # F3-a, restated as a do-not-ask negative control: a machine's own
    # earlier guess must never suppress a later, genuinely Tier-3-triggering
    # re-ask of the same question_key. If this ever returned the prior
    # decision here, do-not-ask enforcement would resurrect F3-a under a new
    # name.
    prior = {"current": {"source": TIER2_AUTO_ASSUMPTION_SOURCE, "answer": "guess"}}
    assert find_redundant_decision(prior, {"affects_pass_fail_verdict": True}) is None
    assert find_redundant_decision(prior, {"affects_spec_intent": True}) is None
    assert find_redundant_decision(prior, {"affects_read_only_file_change": True}) is None


def test_find_redundant_decision_unrecognized_source_is_not_redundant():
    # Fail closed, same discipline classify_tier()'s _is_human_decision()
    # already applies: a legacy/hand-written record with no recognizable
    # `current.source` is not positively identified as a real resolution, so
    # it must not silently swallow a fresh ask.
    assert find_redundant_decision({"current": {"answer": "yes"}}, {}) is None
    assert find_redundant_decision({"current": {"source": "something_else", "answer": "yes"}}, {}) is None


def test_add_question_enforce_do_not_ask_off_by_default_preserves_existing_behavior(tmp_path):
    # The disclosed default: enforce_do_not_ask=False (the implicit default)
    # must file a fresh record every time, byte-identically to every
    # existing caller's behavior before this change (see
    # test_asking_the_same_question_twice_self_resolves_the_second_time).
    store = QuestionQueueStore(tmp_path)
    kwargs = dict(domain="dut", question="Is R9 W1C?", context_path="dut.regs.R9",
                   options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
                   context={"affects_pass_fail_verdict": True})
    first = store.add_question(**kwargs)
    store.answer_question(first["id"], answer="Yes.", basis="RTL", decided_by="designer@example.com")
    second = store.add_question(**kwargs)  # enforce_do_not_ask omitted -> False
    assert second["status"] == "SELF_RESOLVED"
    assert len(store.list_questions()) == 2


def test_add_question_enforce_do_not_ask_refuses_a_duplicate_of_a_human_answered_key(tmp_path):
    store = QuestionQueueStore(tmp_path)
    kwargs = dict(domain="dut", question="Is R10 W1C?", context_path="dut.regs.R10",
                   options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
                   context={"affects_pass_fail_verdict": True})
    first = store.add_question(**kwargs)
    store.answer_question(first["id"], answer="Yes, W1C.", basis="RTL reg_map.sv line 9",
                            decided_by="designer@example.com")

    with pytest.raises(DoNotAskError) as exc:
        store.add_question(**kwargs, enforce_do_not_ask=True)
    err = exc.value
    assert err.question_key == first["question_key"]
    assert err.decision["current"]["answer"] == "Yes, W1C."
    assert err.decision["current"]["source"] == HUMAN_DECISION_SOURCE
    assert "already has a live decision" in str(err)
    # Refused BEFORE persisting -- no second record was appended.
    assert len(store.list_questions()) == 1


def test_add_question_enforce_do_not_ask_refuses_a_duplicate_tier2_assumption_with_no_new_trigger(tmp_path):
    store = QuestionQueueStore(tmp_path)
    kwargs = dict(domain="env", question="Is monitor9 passive-only?", context_path="env.topology.monitor9",
                   options=_opts(), recommendation=_opts()[0]["label"],
                   assumption_if_unanswered="Treat monitor9 as passive-only.")
    first = store.add_question(**kwargs)  # no hard trigger -> Tier 2, auto-assumption persisted
    assert first["tier"] == TIER2_SAFE_ASSUME

    with pytest.raises(DoNotAskError) as exc:
        store.add_question(**kwargs, enforce_do_not_ask=True)
    assert exc.value.decision["current"]["source"] == TIER2_AUTO_ASSUMPTION_SOURCE
    assert len(store.list_questions()) == 1


def test_add_question_enforce_do_not_ask_still_escalates_a_genuine_tier3_over_a_tier2_guess(tmp_path):
    # The critical negative control: enforce_do_not_ask=True must NOT
    # resurrect F3-a. A prior tier2_auto_assumption decision must never
    # block a later ask of the same question_key whose OWN context trips a
    # real Tier-3 hard trigger -- that ask must still be FILED (and escalate
    # for real), never refused as "redundant".
    store = QuestionQueueStore(tmp_path)
    common = dict(domain="dut", question=_SPEC_INTENT_Q, context_path="dut.regs.TX_ERR2",
                   options=_opts(), recommendation=_opts()[0]["label"],
                   assumption_if_unanswered="Assume legal drop per spec.")
    first = store.add_question(**common, context={}, enforce_do_not_ask=True)
    assert first["tier"] == TIER2_SAFE_ASSUME

    second = store.add_question(**common, context=dict(_ALL_HARD_TRIGGERS), enforce_do_not_ask=True)
    assert second["question_key"] == first["question_key"]
    assert second["tier"] == TIER3_CANNOT_ASSUME
    assert second["status"] == "OPEN"
    assert second["blocking"] is True
    assert len(store.list_questions()) == 2  # genuinely filed, not refused


def test_add_question_enforce_do_not_ask_allows_a_first_ask_with_no_prior_decision(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="env", question="Is agent9 active?", context_path="env.agents.agent9",
        options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="a",
        enforce_do_not_ask=True,
    )
    assert q["status"] == "ASSUMED"


# =================================================================================
# (b) build_multiple_choice_question(): the N-ary generalization of
# source_authority.escalate_conflict()'s exactly-2-option shape
# =================================================================================

def _candidates(n=3):
    labels = ["Configure as bus slave/responder", "Configure as bus master/initiator",
              "Configure as passive monitor only"]
    paths = ["dut.rtl:usb3_link_ctrl.v:120", "dut.rtl:usb3_link_ctrl.v:145", "env.topology.monitor0"]
    return [{"label": labels[i], "evidence_path": paths[i], "rationale": f"candidate {i}"}
            for i in range(n)]


def test_build_multiple_choice_files_one_tier3_blocking_question_with_all_candidates(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = build_multiple_choice_question(
        store, domain="dut", subject="usb3_link_ctrl boundary role",
        candidates=_candidates(3),
    )
    assert q["tier"] == TIER3_CANNOT_ASSUME
    assert q["blocking"] is True
    assert q["status"] == "OPEN"
    assert [o["label"] for o in q["options"]] == [c["label"] for c in _candidates(3)]
    for c in _candidates(3):
        assert c["evidence_path"] in q["question"] or any(
            c["evidence_path"] in o.get("rationale", "") for o in q["options"])
    assert q["recommendation"] == _candidates(3)[0]["label"]
    validate_question(q)


def test_build_multiple_choice_requires_at_least_two_candidates(tmp_path):
    store = QuestionQueueStore(tmp_path)
    with pytest.raises(QuestionValidationError):
        build_multiple_choice_question(store, domain="dut", subject="x", candidates=_candidates(1))
    assert store.list_questions() == []


def test_build_multiple_choice_refuses_a_candidate_missing_label_or_evidence_path(tmp_path):
    store = QuestionQueueStore(tmp_path)
    bad = [{"label": "a", "evidence_path": "p1"}, {"label": "b"}]  # missing evidence_path
    with pytest.raises(QuestionValidationError):
        build_multiple_choice_question(store, domain="dut", subject="x", candidates=bad)
    assert store.list_questions() == []


def test_assert_all_evidence_paths_present_is_the_real_guard_build_multiple_choice_relies_on(tmp_path):
    # build_multiple_choice_question ALWAYS embeds each candidate's own
    # evidence_path into its own option's rationale ("evidence: <path>"),
    # mirroring source_authority._option_for()'s identical, unconditional
    # behavior -- so a missing-evidence-path failure can never be triggered
    # through the public API's normal candidate/question_text inputs alone
    # (proven positively by
    # test_build_multiple_choice_default_question_text_cites_every_evidence_path).
    # assert_all_evidence_paths_present() is therefore a regression safety
    # net against a FUTURE edit to that option-construction internal, not a
    # path reachable today -- proven directly here by calling it exactly as
    # build_multiple_choice_question would, with one candidate's option
    # rationale deliberately NOT carrying its evidence path (the mutation
    # this guard exists to catch).
    cands = _candidates(2)
    options_missing_one_citation = [
        {"label": cands[0]["label"], "rationale": f"evidence: {cands[0]['evidence_path']}"},
        {"label": cands[1]["label"], "rationale": "no evidence cited here"},
    ]
    with pytest.raises(QuestionValidationError) as exc:
        assert_all_evidence_paths_present(
            f"Multiple candidates for x: {cands[0]['label']}; {cands[1]['label']}",
            options_missing_one_citation, [c["evidence_path"] for c in cands],
        )
    assert cands[1]["evidence_path"] in str(exc.value)
    # And a store never even sees a call in this scenario -- nothing to assert.
    store = QuestionQueueStore(tmp_path)
    assert store.list_questions() == []


def test_build_multiple_choice_default_question_text_cites_every_evidence_path(tmp_path):
    # Positive control: the auto-generated question_text (no override) must
    # itself satisfy assert_all_evidence_paths_present -- proven by the fact
    # that add_question does not raise.
    store = QuestionQueueStore(tmp_path)
    q = build_multiple_choice_question(store, domain="dut", subject="x", candidates=_candidates(3))
    for c in _candidates(3):
        assert c["evidence_path"] in q["question"]


def test_build_multiple_choice_recommendation_must_be_an_offered_candidate(tmp_path):
    store = QuestionQueueStore(tmp_path)
    with pytest.raises(QuestionValidationError):
        build_multiple_choice_question(
            store, domain="dut", subject="x", candidates=_candidates(2),
            recommendation_label="never offered",
        )
    assert store.list_questions() == []


def test_build_multiple_choice_recommendation_defaults_to_first_candidate_when_undecidable(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = build_multiple_choice_question(store, domain="dut", subject="x", candidates=_candidates(3))
    assert q["recommendation"] == _candidates(3)[0]["label"]


def test_build_multiple_choice_is_idempotent_on_question_key(tmp_path):
    store = QuestionQueueStore(tmp_path)
    first = build_multiple_choice_question(store, domain="dut", subject="idempotent case",
                                            candidates=_candidates(2))
    second = build_multiple_choice_question(store, domain="dut", subject="idempotent case",
                                             candidates=_candidates(2))
    assert second["id"] == first["id"]
    assert len(store.list_questions()) == 1  # not re-filed as a duplicate


def test_build_multiple_choice_refuses_more_candidates_than_the_real_schema_cap(tmp_path):
    store = QuestionQueueStore(tmp_path)
    four = _candidates(3) + [{"label": "Configure as bridge", "evidence_path": "env.topology.bridge0"}]
    with pytest.raises(QuestionValidationError) as exc:
        build_multiple_choice_question(store, domain="dut", subject="x", candidates=four)
    assert "3" in str(exc.value)  # the real question.schema.json options.maxItems value
    assert store.list_questions() == []


def test_assert_all_evidence_paths_present_matches_source_authority_rule():
    # Disclosed-residual proof: this module's generalized N-ary validator is
    # a SEPARATE implementation from source_authority.
    # assert_both_evidence_paths_present() (that function, and
    # escalate_conflict(), live in source_authority.py, outside this
    # change's declared scope of question_queue.py -- see the module-level
    # comment above build_multiple_choice_question()). What is checked here
    # is that the two enforce the IDENTICAL rule rather than having quietly
    # drifted into two different ones: both accept a question that carries
    # every evidence path, and both reject one missing any.
    from dv_harness import source_authority
    from dv_harness.question_queue import assert_all_evidence_paths_present

    conflict = {
        "claims": [
            {"source": "rtl", "claim": "0x1000", "evidence_path": "rtl/decoder.v:88"},
            {"source": "doc", "claim": "0x2000", "evidence_path": "docs/regmap.md:14"},
        ],
    }
    options = [
        {"label": "0x1000 (rtl)", "rationale": "evidence: rtl/decoder.v:88"},
        {"label": "0x2000 (doc)", "rationale": "evidence: docs/regmap.md:14"},
    ]
    complete_text = "Address disagreement: rtl says 0x1000 [rtl/decoder.v:88]; doc says 0x2000 [docs/regmap.md:14]."
    incomplete_text = "Address disagreement: rtl says 0x1000 [rtl/decoder.v:88]."

    # Both PASS when every evidence path is present.
    source_authority.assert_both_evidence_paths_present(complete_text, options, conflict)
    assert_all_evidence_paths_present(
        complete_text, options, [c["evidence_path"] for c in conflict["claims"]])

    # Both REJECT the identical incomplete text/options.
    with pytest.raises(source_authority.SourceAuthorityError):
        source_authority.assert_both_evidence_paths_present(incomplete_text, options[:1], conflict)
    with pytest.raises(QuestionValidationError):
        assert_all_evidence_paths_present(
            incomplete_text, options[:1], [c["evidence_path"] for c in conflict["claims"]])


# =================================================================================
# (c) build_escalation_package() / get_escalation_package(): the 9-field
# Question Escalation Package view (spec section 32), reusing add_question()'s
# and build_multiple_choice_question()'s existing filing mechanism rather than
# a parallel one.
# =================================================================================

def test_escalation_package_has_exactly_the_9_named_fields_in_order(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Is this DUT boundary master or slave?",
        context_path="rtl/usb3_link_ctrl.v:120", options=_opts(),
        recommendation="Configure as bus slave/responder",
        assumption_if_unanswered="assume slave",
        context={"affects_pass_fail_verdict": True},  # Tier-3
    )
    pkg = build_escalation_package(q)
    assert tuple(pkg.keys()) == ESCALATION_PACKAGE_FIELDS
    assert len(ESCALATION_PACKAGE_FIELDS) == 9


def test_escalation_package_fields_trace_1to1_to_the_real_persisted_record(tmp_path):
    # Every field must be the REAL persisted value -- never re-derived or
    # independently computed -- except urgency, which is a documented
    # deterministic function of the record's own tier (checked separately
    # below).
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="vip", question="Which VIP config field applies?",
        context_path="env.manifest.json#/vip_config/instances/0",
        options=_opts(), recommendation="Configure as bus slave/responder",
        assumption_if_unanswered="assume slave (single regression)",
        context={"affects_pass_fail_verdict": True},
    )
    pkg = build_escalation_package(q)
    assert pkg["question_id"] == q["id"]
    assert pkg["category"] == q["domain"]
    assert pkg["context"] == q["context_path"]
    assert pkg["question_text"] == q["question"]
    assert pkg["options"] is q["options"]  # the SAME real options, not a copy/rebuild
    assert pkg["recommended_option"] == q["recommendation"]
    assert pkg["default_if_unanswered"] == q["assumption_if_unanswered"]
    assert pkg["owner"] == q["owner"]


def test_escalation_package_urgency_reflects_the_records_real_tier(tmp_path):
    store = QuestionQueueStore(tmp_path)

    tier3 = store.add_question(
        domain="dut", question="q3", context_path="p3", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a3",
        context={"affects_pass_fail_verdict": True},
    )
    assert tier3["tier"] == TIER3_CANNOT_ASSUME
    assert build_escalation_package(tier3)["urgency"] == "BLOCKING_AWAITING_HUMAN_ANSWER"

    tier2 = store.add_question(
        domain="env", question="q2", context_path="p2", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a2",
        context={},  # no hard trigger, low blast radius -> Tier 2
    )
    assert tier2["tier"] == TIER2_SAFE_ASSUME
    assert build_escalation_package(tier2)["urgency"] == "NON_BLOCKING_TIME_BOXED_ASSUMPTION_LOGGED"

    tier1 = store.add_question(
        domain="env", question="q1", context_path="p1", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a1",
        context={"resolvable_from_manifest": True, "manifest_value": "SLAVE"},
    )
    assert tier1["tier"] == TIER1_SELF_RESOLVE
    assert build_escalation_package(tier1)["urgency"] == "INFORMATIONAL_ALREADY_SELF_RESOLVED"


def test_escalation_package_refuses_to_fabricate_from_an_incomplete_record():
    # Negative control: no evidence, no package -- the property this house
    # style is graded on. A record missing real fields must be refused, never
    # silently completed with a guessed/default value.
    with pytest.raises(QuestionValidationError) as exc:
        build_escalation_package({"id": "Q-DUT-DEADBEEF", "domain": "dut"})
    msg = str(exc.value)
    for missing_key in ("context_path", "question", "options", "recommendation",
                          "assumption_if_unanswered", "owner", "tier"):
        assert missing_key in msg


def test_escalation_package_refuses_a_non_dict_record():
    with pytest.raises(QuestionValidationError):
        build_escalation_package(["not", "a", "dict"])  # type: ignore[arg-type]


def test_escalation_package_refuses_an_unrecognized_tier(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True},
    )
    q["tier"] = 99  # corrupt, as if hand-edited -- never a real classify_tier() output
    with pytest.raises(QuestionValidationError) as exc:
        build_escalation_package(q)
    assert "99" in str(exc.value)


def test_get_escalation_package_reuses_add_questions_own_filing_mechanism(tmp_path):
    # No parallel filing path: get_escalation_package() is a lookup through
    # the SAME get_question() read path plus build_escalation_package(),
    # never a second store or a second record.
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True},
    )
    pkg_via_store = store.get_escalation_package(q["id"])
    pkg_via_function = build_escalation_package(q)
    assert pkg_via_store == pkg_via_function


def test_get_escalation_package_unknown_id_raises_keyerror(tmp_path):
    store = QuestionQueueStore(tmp_path)
    with pytest.raises(KeyError):
        store.get_escalation_package("Q-DUT-00000000")


def test_escalation_package_reuses_build_multiple_choice_questions_filing(tmp_path):
    # The other half of "reusing build_multiple_choice_question()'s existing
    # filing mechanism rather than a parallel one": a question filed through
    # the N-way builder is escalation-package-able exactly like any other.
    store = QuestionQueueStore(tmp_path)
    q = build_multiple_choice_question(store, domain="dut", subject="x", candidates=_candidates(2))
    pkg = store.get_escalation_package(q["id"])
    assert pkg["question_id"] == q["id"]
    assert pkg["urgency"] == "BLOCKING_AWAITING_HUMAN_ANSWER"  # multiple-choice is always Tier 3
    assert [o["label"] for o in pkg["options"]] == [c["label"] for c in _candidates(2)]


def test_escalation_package_is_never_persisted_into_questions_json(tmp_path):
    # A pure read-side projection -- never written back into the store, so
    # question.schema.json's additionalProperties:false contract on the real
    # persisted record is never touched and no schema_version bump is needed.
    import json

    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True},
    )
    store.get_escalation_package(q["id"])  # build (and discard) a package
    on_disk = json.loads(store.questions_path.read_text(encoding="utf-8"))
    persisted = on_disk["questions"][0]
    assert "escalation_package" not in persisted
    assert set(persisted.keys()).isdisjoint(
        {"question_id", "category", "recommended_option", "default_if_unanswered", "urgency"}
    )
    validate_question(persisted)  # still a schema-valid record, untouched


def test_render_escalation_package_markdown_contains_every_field(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Is this master or slave?", context_path="rtl/x.v:1",
        options=_opts(), recommendation="Configure as bus slave/responder",
        assumption_if_unanswered="assume slave",
        context={"affects_pass_fail_verdict": True},
    )
    pkg = store.get_escalation_package(q["id"])
    text = render_escalation_package_markdown(pkg)
    assert pkg["question_id"] in text
    assert pkg["question_text"] in text
    assert pkg["recommended_option"] in text
    assert pkg["default_if_unanswered"] in text
    assert pkg["owner"] in text
    assert pkg["urgency"] in text
    for opt in pkg["options"]:
        assert opt["label"] in text


# =================================================================================
# (d) request_clarification(): re-render an existing question with more
# context / simpler phrasing, grounded in already-found evidence -- never a
# second filing mechanism (question_rephrase_clarification_loop).
# =================================================================================

def test_request_clarification_returns_the_real_package_grounded_in_the_record(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Is this DUT boundary master or slave?",
        context_path="rtl/usb3_link_ctrl.v:120", options=_opts(),
        recommendation="Configure as bus slave/responder",
        assumption_if_unanswered="assume slave (single regression)",
        context={"affects_pass_fail_verdict": True},  # Tier-3
    )
    result = request_clarification(store, q["id"], reason="I don't understand this", record=False)
    assert result["question_id"] == q["id"]
    assert result["package"] == build_escalation_package(q)
    assert any(line == f"Question: {q['question']}" for line in result["plain_summary"])
    assert any(line == f"Where this comes from: {q['context_path']}" for line in result["plain_summary"])
    # The hard-trigger reason is translated into a plain-English clause, not
    # left as the raw "hard_trigger:affects_pass_fail_verdict" token.
    assert any("PASS or FAIL" in line for line in result["plain_summary"])
    assert q["tier_reason"] not in "\n".join(result["plain_summary"])
    # Tier-3: the exact fallback assumption is restated, never omitted.
    assert any(q["assumption_if_unanswered"] in line for line in result["plain_summary"])


def test_request_clarification_unknown_id_raises_keyerror(tmp_path):
    store = QuestionQueueStore(tmp_path)
    with pytest.raises(KeyError):
        request_clarification(store, "Q-DUT-00000000", record=False)


def test_request_clarification_lists_every_options_own_rationale_as_evidence(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True},
    )
    result = request_clarification(store, q["id"], record=False)
    for opt in q["options"]:
        assert any(opt["label"] in line and opt["rationale"] in line for line in result["evidence"])


def test_request_clarification_never_fabricates_a_missing_option_rationale(tmp_path):
    # Negative control: an option with no rationale on file must be reported
    # as honestly absent, never filled in with an invented explanation.
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p",
        options=["bare label a", "bare label b"],  # normalize_options() carries no rationale
        recommendation="bare label a", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True},
    )
    result = request_clarification(store, q["id"], record=False)
    assert "bare label a: (no additional rationale on file)" in result["evidence"]
    assert "bare label b: (no additional rationale on file)" in result["evidence"]


def test_request_clarification_never_files_a_second_question_or_mutates_the_record(tmp_path):
    import json

    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True},
    )
    before = store.questions_path.read_text(encoding="utf-8")
    request_clarification(store, q["id"], record=False)
    request_clarification(store, q["id"], record=True)
    after = store.questions_path.read_text(encoding="utf-8")
    assert before == after  # byte-identical: no second question filed, no field mutated
    assert len(json.loads(after)["questions"]) == 1
    assert store.list_questions()[0]["id"] == q["id"]


def test_request_clarification_tier2_notes_it_is_a_machine_guess_not_a_human_answer(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="env", question="q2", context_path="p2", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a2",
        context={},  # no hard trigger, low blast radius -> Tier 2
    )
    assert q["tier"] == TIER2_SAFE_ASSUME
    result = request_clarification(store, q["id"], record=False)
    assert any("machine guess, not a human answer" in line and q["answer"] in line
               for line in result["plain_summary"])


def test_request_clarification_tier1_notes_it_was_already_resolved(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="env", question="q1", context_path="p1", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a1",
        context={"resolvable_from_manifest": True, "manifest_value": "SLAVE"},
    )
    assert q["tier"] == TIER1_SELF_RESOLVE
    result = request_clarification(store, q["id"], record=False)
    assert any("Already resolved automatically" in line and "SLAVE" in line
               for line in result["plain_summary"])


def test_request_clarification_includes_the_exemption_citation_when_present(tmp_path, monkeypatch):
    store = QuestionQueueStore(tmp_path)
    fake_exemption = {
        "id": "EXEMPT-1", "check_id": "CHK-1", "reason": "known limitation, documented",
        "basis_document": "doc.md#s2", "owner": "designer", "valid_until": "2099-01-01",
    }
    monkeypatch.setattr(store, "find_exemption", lambda check_id, as_of=None: fake_exemption)
    q = store.add_question(
        domain="dut", question="q", context_path="p", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True, "check_id": "CHK-1"},
    )
    assert q["exemption"]["id"] == "EXEMPT-1"
    result = request_clarification(store, q["id"], record=False)
    joined = "\n".join(result["plain_summary"])
    assert "EXEMPT-1" in joined and "designer" in joined and "2099-01-01" in joined
    assert "does not by itself answer this specific question" in joined


def test_request_clarification_surfaces_an_unrecognized_tier_reason_verbatim(tmp_path):
    # Negative control: a tier_reason this module's lookup table does not
    # (yet) know about is never dropped or guessed at -- it is surfaced
    # verbatim, exactly the "unearned guess" the Evidence Truth Rule forbids
    # in the other direction (never silently discarding real evidence).
    import json

    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True},
    )
    data = json.loads(store.questions_path.read_text(encoding="utf-8"))
    data["questions"][0]["tier_reason"] = "some_future_rule_this_module_does_not_know_about"
    store.questions_path.write_text(json.dumps(data), encoding="utf-8")

    result = request_clarification(store, q["id"], record=False)
    assert any("some_future_rule_this_module_does_not_know_about" in line
               for line in result["plain_summary"])


def test_request_clarification_multiple_hard_triggers_are_each_explained(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True, "affects_spec_intent": True},
    )
    assert q["tier_reason"].startswith("hard_trigger:affects_pass_fail_verdict,affects_spec_intent")
    result = request_clarification(store, q["id"], record=False)
    joined = "\n".join(result["plain_summary"])
    assert "PASS or FAIL" in joined
    assert "spec actually intends" in joined


def test_request_clarification_record_false_never_writes_the_clarifications_file(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True},
    )
    result = request_clarification(store, q["id"], record=False)
    assert result["clarification_id"] is None
    assert not store.clarifications_path.exists()
    assert list_clarification_requests(store) == []


def test_request_clarification_record_true_persists_and_list_reads_it_back(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True},
    )
    result = request_clarification(store, q["id"], requested_by="alice",
                                     reason="not sure what this means", record=True)
    assert result["clarification_id"] is not None
    assert store.clarifications_path.exists()

    all_reqs = list_clarification_requests(store)
    assert len(all_reqs) == 1
    rec = all_reqs[0]
    assert rec["clarification_id"] == result["clarification_id"]
    assert rec["question_id"] == q["id"]
    assert rec["question_key"] == q["question_key"]
    assert rec["requested_by"] == "alice"
    assert rec["reason"] == "not sure what this means"

    filtered = list_clarification_requests(store, question_id=q["id"])
    assert filtered == all_reqs
    assert list_clarification_requests(store, question_id="Q-DUT-00000000") == []


def test_request_clarification_second_request_appends_not_overwrites(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True},
    )
    first = request_clarification(store, q["id"], record=True)
    second = request_clarification(store, q["id"], record=True)
    assert first["clarification_id"] != second["clarification_id"]
    assert len(list_clarification_requests(store, question_id=q["id"])) == 2


def test_request_clarification_defaults_requested_by_to_unknown(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True},
    )
    request_clarification(store, q["id"], record=True)
    assert list_clarification_requests(store)[0]["requested_by"] == "unknown"


def test_render_clarification_markdown_contains_plain_summary_evidence_and_id(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Is this master or slave?", context_path="rtl/x.v:1",
        options=_opts(), recommendation="Configure as bus slave/responder",
        assumption_if_unanswered="assume slave",
        context={"affects_pass_fail_verdict": True},
    )
    result = request_clarification(store, q["id"], record=True)
    text = render_clarification_markdown(result)
    assert q["id"] in text
    assert q["question"] in text
    for opt in q["options"]:
        assert opt["label"] in text
        assert opt["rationale"] in text
    assert result["clarification_id"] in text


# --- "Why am I being asked this" grounding_evidence -------------------------

def _ge():
    return {"summary": "register CTRL_REG appears in the Excel register map but is absent from "
                         "the RTL port list", "evidence_path": "reg_map.xlsx#CTRL_REG"}


def test_normalize_grounding_evidence_none_stays_none():
    assert normalize_grounding_evidence(None) is None


def test_normalize_grounding_evidence_valid_dict_round_trips():
    ge = _ge()
    result = normalize_grounding_evidence(ge)
    assert result == ge
    assert result is not ge  # a fresh dict, not the caller's own object


def test_normalize_grounding_evidence_rejects_non_dict():
    with pytest.raises(QuestionValidationError):
        normalize_grounding_evidence("register X is missing from RTL")


def test_normalize_grounding_evidence_rejects_unknown_key():
    with pytest.raises(QuestionValidationError):
        normalize_grounding_evidence({"summary": "x", "evidence_path": "y", "confidence": "high"})


def test_normalize_grounding_evidence_rejects_summary_with_no_citation():
    # A bare narrative with nowhere to check it is exactly the unsupported
    # claim this field exists to prevent -- the negative control this
    # module refuses to fabricate a partial grounding for.
    with pytest.raises(QuestionValidationError):
        normalize_grounding_evidence({"summary": "register X is missing from RTL"})


def test_normalize_grounding_evidence_rejects_evidence_path_with_no_reason():
    with pytest.raises(QuestionValidationError):
        normalize_grounding_evidence({"evidence_path": "reg_map.xlsx#CTRL_REG"})


def test_normalize_grounding_evidence_rejects_blank_strings():
    with pytest.raises(QuestionValidationError):
        normalize_grounding_evidence({"summary": "   ", "evidence_path": "reg_map.xlsx#CTRL_REG"})
    with pytest.raises(QuestionValidationError):
        normalize_grounding_evidence({"summary": "real reason", "evidence_path": ""})


def test_add_question_default_grounding_evidence_is_none(tmp_path):
    # The honest default: no caller-supplied evidence, so the field is
    # persisted as null -- never invented from the question/context_path.
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Is CTRL_REG real?", context_path="reg_map.xlsx#CTRL_REG",
        options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
        context={"affects_pass_fail_verdict": True},
    )
    assert q["grounding_evidence"] is None
    validate_question(q)  # schema-valid with the field null


def test_add_question_persists_real_caller_supplied_grounding_evidence(tmp_path):
    store = QuestionQueueStore(tmp_path)
    ge = _ge()
    q = store.add_question(
        domain="dut", question="Is CTRL_REG real?", context_path="reg_map.xlsx#CTRL_REG",
        options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
        context={"affects_pass_fail_verdict": True}, grounding_evidence=ge,
    )
    assert q["grounding_evidence"] == ge
    validate_question(q)
    # Persisted to disk, and readable back through the ordinary query path.
    reloaded = store.get_question(q["id"])
    assert reloaded["grounding_evidence"] == ge


def test_add_question_refuses_malformed_grounding_evidence_and_persists_nothing(tmp_path):
    # The required negative control: a partial grounding (a WHY with no
    # cited WHERE) must never be silently accepted or fabricated into a
    # complete one -- add_question() refuses before anything is written.
    store = QuestionQueueStore(tmp_path)
    with pytest.raises(QuestionValidationError):
        store.add_question(
            domain="dut", question="Is CTRL_REG real?", context_path="reg_map.xlsx#CTRL_REG",
            options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
            context={"affects_pass_fail_verdict": True},
            grounding_evidence={"summary": "no citation for this claim"},
        )
    assert store.list_questions() == []


def test_build_multiple_choice_question_threads_grounding_evidence_through(tmp_path):
    store = QuestionQueueStore(tmp_path)
    ge = _ge()
    q = build_multiple_choice_question(
        store, domain="dut", subject="CTRL_REG existence",
        candidates=[
            {"label": "real register", "evidence_path": "rtl/ctrl.v:12"},
            {"label": "spreadsheet typo", "evidence_path": "reg_map.xlsx#CTRL_REG"},
        ],
        grounding_evidence=ge,
    )
    assert q["grounding_evidence"] == ge


def test_build_multiple_choice_question_default_grounding_evidence_is_none(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = build_multiple_choice_question(
        store, domain="dut", subject="CTRL_REG existence",
        candidates=[
            {"label": "real register", "evidence_path": "rtl/ctrl.v:12"},
            {"label": "spreadsheet typo", "evidence_path": "reg_map.xlsx#CTRL_REG"},
        ],
    )
    assert q["grounding_evidence"] is None


# --- Second-human co-sign of a recorded Tier-3 decision (2026-09-07) --------
#
# Additive, distinct from control_plane.ControlPlane's JUDGMENT_FIELDS
# cosign mechanism (gates.py Tier-5) -- this one co-signs a question_queue
# decisions.json record, never a gate evidence field.

def _human_answered_decision(tmp_path, *, decided_by="designer@example.com", answer="Yes, W1C."):
    """A real Tier-3-escalated, human-answered decision -- the only kind of
    decision `add_decision_cosign()` may ever be applied to."""
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Is register R0 write-1-to-clear?", context_path="dut.regs.R0",
        options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
        context={"affects_pass_fail_verdict": True},
    )
    assert q["tier"] == TIER3_CANNOT_ASSUME
    store.answer_question(q["id"], answer=answer, basis="RTL reg_map.sv line 42", decided_by=decided_by)
    return store, q["question_key"]


def test_add_decision_cosign_records_a_real_second_reviewer(tmp_path):
    store, key = _human_answered_decision(tmp_path)
    assert store.is_decision_cosigned(key) is False  # not co-signed yet
    cosign = store.add_decision_cosign(
        key, reviewer_id="reviewer2@example.com", basis="independently re-derived from the same RTL",
    )
    assert cosign["reviewer_id"] == "reviewer2@example.com"
    assert cosign["cosigns_answer"] == "Yes, W1C."
    assert cosign["basis"] == "independently re-derived from the same RTL"
    assert store.is_decision_cosigned(key) is True
    cosigns = store.get_decision_cosigns(key)
    assert len(cosigns) == 1
    assert cosigns[0]["reviewer_id"] == "reviewer2@example.com"


def test_cosign_never_weakens_or_bypasses_the_existing_human_decision_rule(tmp_path):
    # The decision's own `current`/`history` -- what classify_tier() and
    # every other reader actually consult -- must be byte-identical before
    # and after a co-sign, and a repeat ask must still self-resolve at
    # Tier 1 off the SAME human answer, cosign or not.
    store, key = _human_answered_decision(tmp_path)
    before = store.find_decision(key)
    store.add_decision_cosign(key, reviewer_id="reviewer2@example.com")
    after = store.find_decision(key)
    assert after["current"] == before["current"]
    assert after["history"] == before["history"]

    kwargs = dict(
        domain="dut", question="Is register R0 write-1-to-clear?", context_path="dut.regs.R0",
        options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
        context={"affects_pass_fail_verdict": True},
    )
    second = store.add_question(**kwargs)
    assert second["tier"] == TIER1_SELF_RESOLVE
    assert second["answer"] == "Yes, W1C."


def test_cosign_refuses_when_no_live_decision_exists(tmp_path):
    store = QuestionQueueStore(tmp_path)
    with pytest.raises(CosignNotApplicableError):
        store.add_decision_cosign("dut::dut.regs.R0::never asked", reviewer_id="reviewer2@example.com")


def test_cosign_refuses_a_tier2_auto_assumption_never_fabricates_human_trust(tmp_path):
    # The required negative control: a Tier-2 auto-assumption is only the
    # harness's own machine guess (see _is_human_decision()'s own
    # docstring) -- co-signing it must never become a backdoor into
    # HUMAN_DECISION_SOURCE-level trust for something no human ever
    # actually decided.
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="env", question="Is monitor0 passive-only?", context_path="env.topology.monitor0",
        options=_opts(), recommendation=_opts()[0]["label"],
        assumption_if_unanswered="Treat monitor0 as passive-only.",
    )
    assert q["tier"] == TIER2_SAFE_ASSUME
    decision = store.find_decision(q["question_key"])
    assert decision["current"]["source"] == TIER2_AUTO_ASSUMPTION_SOURCE
    with pytest.raises(CosignNotApplicableError):
        store.add_decision_cosign(q["question_key"], reviewer_id="reviewer2@example.com")
    assert store.is_decision_cosigned(q["question_key"]) is False
    assert store.get_decision_cosigns(q["question_key"]) == []


def test_cosign_requires_a_real_reviewer_id(tmp_path):
    store, key = _human_answered_decision(tmp_path)
    with pytest.raises(ValueError):
        store.add_decision_cosign(key, reviewer_id="")
    with pytest.raises(ValueError):
        store.add_decision_cosign(key, reviewer_id="   ")
    assert store.is_decision_cosigned(key) is False


def test_cosign_refuses_the_original_decider_cosigning_their_own_answer(tmp_path):
    store, key = _human_answered_decision(tmp_path, decided_by="designer@example.com")
    with pytest.raises(ValueError):
        store.add_decision_cosign(key, reviewer_id="designer@example.com")
    assert store.is_decision_cosigned(key) is False


def test_cosign_becomes_stale_once_the_decision_is_re_answered_differently(tmp_path):
    store, key = _human_answered_decision(tmp_path, answer="Yes, W1C.")
    original_qid = store.find_decision(key)["current"]["question_id_of_answer"]
    store.add_decision_cosign(key, reviewer_id="reviewer2@example.com")
    assert store.is_decision_cosigned(key) is True

    # make_question_id() is derived from question_key alone, so re-answering
    # the SAME Q-ID with a genuinely different answer (a real correction) is
    # the case a cosign staleness check must actually catch.
    store.answer_question(original_qid, answer="No, RW.", basis="revised RTL reading",
                            decided_by="designer2@example.com")

    assert store.is_decision_cosigned(key) is False  # stale: does not cover the new answer
    cosigns = store.get_decision_cosigns(key)
    assert len(cosigns) == 1  # kept for the audit trail, not deleted
    assert cosigns[0]["cosigns_answer"] == "Yes, W1C."
    assert store.find_decision(key)["current"]["answer"] == "No, RW."


def test_cosign_does_not_survive_revoke_and_reanswer(tmp_path):
    store, key = _human_answered_decision(tmp_path)
    store.add_decision_cosign(key, reviewer_id="reviewer2@example.com")
    assert store.is_decision_cosigned(key) is True
    store.revoke_decision(key, reason="turned out to be wrong", revoked_by="designer@example.com")
    assert store.find_decision(key) is None
    with pytest.raises(CosignNotApplicableError):
        store.add_decision_cosign(key, reviewer_id="reviewer2@example.com")


def test_decisions_md_and_blackboard_topic_report_the_cosign_honestly(tmp_path):
    store, key = _human_answered_decision(tmp_path)
    store.add_decision_cosign(key, reviewer_id="reviewer2@example.com")
    md = store.decisions_md_path.read_text(encoding="utf-8")
    assert "reviewer2@example.com" in md
    assert "Second-human co-sign" in md

    from dv_harness.blackboard import Blackboard
    board = Blackboard(tmp_path)
    topic = board.read("open_questions_decisions")
    assert topic["value"]["decisions"][key]["cosigned"] is True


def test_decisions_md_reports_a_stale_cosign_as_not_covering_the_current_answer(tmp_path):
    store, key = _human_answered_decision(tmp_path, answer="Yes, W1C.")
    original_qid = store.find_decision(key)["current"]["question_id_of_answer"]
    store.add_decision_cosign(key, reviewer_id="reviewer2@example.com")
    store.answer_question(original_qid, answer="No, RW.", basis="revised RTL reading",
                            decided_by="designer2@example.com")
    md = store.decisions_md_path.read_text(encoding="utf-8")
    assert "none cover the CURRENT answer" in md


# ===========================================================================
# Suggest-then-confirm mode (2026-09-07, item proactive_answer_suggestion)
# ===========================================================================

def _real_suggestion():
    return {
        "value": "R-2020.12", "source_module": "env_manifest",
        "source_path": "env.manifest.json#vip_config.vip_release.packages.1.version",
        "rationale": "newest scanned package under $DESIGNWARE_HOME",
    }


class TestNormalizeSuggestedAnswer:
    def test_none_stays_none(self):
        assert normalize_suggested_answer(None) is None

    def test_valid_suggestion_round_trips(self):
        s = _real_suggestion()
        assert normalize_suggested_answer(s) == s

    def test_valid_suggestion_without_rationale(self):
        s = {"value": "v3", "source_module": "design_source_inventory",
             "source_path": "design_source_inventory#usb3_regmap.version"}
        assert normalize_suggested_answer(s) == s

    def test_non_dict_raises(self):
        with pytest.raises(QuestionValidationError, match="must be a"):
            normalize_suggested_answer("R-2020.12")

    def test_unknown_key_raises(self):
        s = dict(_real_suggestion(), extra="nope")
        with pytest.raises(QuestionValidationError, match="unknown key"):
            normalize_suggested_answer(s)

    @pytest.mark.parametrize("missing", ["value", "source_module", "source_path"])
    def test_missing_required_key_raises(self, missing):
        s = _real_suggestion()
        del s[missing]
        with pytest.raises(QuestionValidationError, match="missing required key"):
            normalize_suggested_answer(s)

    def test_blank_value_raises(self):
        s = dict(_real_suggestion(), value="   ")
        with pytest.raises(QuestionValidationError, match="value.*non-empty"):
            normalize_suggested_answer(s)

    def test_unrecognized_source_module_raises(self):
        """The negative control the Evidence Truth Rule requires: a
        suggestion must always cite one of the two REAL evidence producers
        this mode derives an answer from -- an open-ended module name is
        refused outright, never silently accepted as a citation nobody could
        actually go check."""
        s = dict(_real_suggestion(), source_module="my_own_guess")
        with pytest.raises(QuestionValidationError, match="source_module"):
            normalize_suggested_answer(s)

    def test_blank_source_path_raises(self):
        s = dict(_real_suggestion(), source_path="")
        with pytest.raises(QuestionValidationError, match="source_path"):
            normalize_suggested_answer(s)

    def test_non_string_rationale_raises(self):
        s = dict(_real_suggestion(), rationale=42)
        with pytest.raises(QuestionValidationError, match="rationale"):
            normalize_suggested_answer(s)


class TestDeriveSuggestedAnswerFromEnvManifest:
    """`derive_suggested_answer_from_env_manifest()` walks a real
    env.manifest.json-shaped dict; the fixtures here mirror
    dv_harness.env_manifest.build_vip_config_layer()'s own real, documented
    field shapes (status/reason/packages[].name/version) rather than a
    made-up structure -- see that module's own real
    build_vip_release()/scan_designware_home() docstrings for the shape."""

    def _manifest(self, vip_release_status="SCANNED"):
        return {
            "vip_config": {
                # This dump-level status is DELIBERATELY the opposite of
                # vip_release's own status below -- the real composite-layer
                # case build_vip_config_layer() produces (vip_config's own
                # top status describes only its zero-time config dump, a
                # DIFFERENT fact from vip_release's real $DESIGNWARE_HOME
                # scan result merged into the same dict).
                "status": "NOT_AVAILABLE", "reason": "no dump", "vip_instances": [],
                "vip_release": {
                    "status": vip_release_status, "reason": None,
                    "designware_home": "/dw",
                    "packages": [
                        {"name": "amba_svt", "version": "Q-2019.06"},
                        {"name": "usb_svt", "version": "R-2020.12"},
                    ],
                },
            },
        }

    def test_real_evidence_present_suggests_the_real_value(self):
        r = derive_suggested_answer_from_env_manifest(
            self._manifest(), ["vip_config", "vip_release", "packages", 1, "version"])
        assert r == {
            "value": "R-2020.12", "source_module": "env_manifest",
            "source_path": "env.manifest.json#vip_config.vip_release.packages.1.version",
        }

    def test_composite_layers_own_unrelated_status_does_not_gate_a_sibling_sub_layer(self):
        """The headline correctness proof: vip_config's own status is
        NOT_AVAILABLE (no config dump), yet vip_release -- a genuinely
        separate, real, SCANNED sub-layer merged into the same dict -- must
        still be suggestible. Gating on every ancestor blindly would wrongly
        refuse this real evidence."""
        manifest = self._manifest(vip_release_status="SCANNED")
        assert manifest["vip_config"]["status"] == "NOT_AVAILABLE"
        r = derive_suggested_answer_from_env_manifest(
            manifest, ["vip_config", "vip_release", "packages", 0, "version"])
        assert r is not None and r["value"] == "Q-2019.06"

    def test_a_sub_layers_own_not_available_status_is_still_honored(self):
        """The converse of the above -- vip_release's OWN status must still
        gate its own facts, even while its sibling vip_instances (gated by
        the parent) is separately available/unavailable."""
        manifest = self._manifest(vip_release_status="NOT_AVAILABLE")
        r = derive_suggested_answer_from_env_manifest(
            manifest, ["vip_config", "vip_release", "packages", 0, "version"])
        assert r is None

    def test_parent_status_still_gates_a_plain_non_status_bearing_child(self):
        """vip_instances is a plain list with no status of its own, so
        vip_config's own (here NOT_AVAILABLE) status is the correct, most
        specific fact available and must gate it."""
        manifest = self._manifest()
        manifest["vip_config"]["vip_instances"] = [{"instance_path": "u0", "vip_type": "usb3"}]
        r = derive_suggested_answer_from_env_manifest(
            manifest, ["vip_config", "vip_instances", 0, "vip_type"])
        assert r is None

    def test_negative_control_no_evidence_at_all_refuses_to_fabricate(self):
        """The mandatory negative control: a genuinely absent layer must
        never produce a guessed answer."""
        bare = {"vip_config": {"status": "NOT_AVAILABLE", "reason": "no dump", "vip_instances": []}}
        r = derive_suggested_answer_from_env_manifest(
            bare, ["vip_config", "vip_release", "packages", 0, "version"])
        assert r is None

    def test_missing_path_segment_returns_none(self):
        r = derive_suggested_answer_from_env_manifest(
            self._manifest(), ["vip_config", "vip_release", "does_not_exist"])
        assert r is None

    def test_out_of_range_index_returns_none(self):
        r = derive_suggested_answer_from_env_manifest(
            self._manifest(), ["vip_config", "vip_release", "packages", 99, "version"])
        assert r is None

    def test_empty_string_value_returns_none(self):
        manifest = self._manifest()
        manifest["vip_config"]["vip_release"]["packages"][1]["version"] = "   "
        r = derive_suggested_answer_from_env_manifest(
            manifest, ["vip_config", "vip_release", "packages", 1, "version"])
        assert r is None

    def test_non_dict_manifest_returns_none(self):
        assert derive_suggested_answer_from_env_manifest("not a dict", ["vip_config"]) is None

    def test_non_string_leaf_value_is_json_encoded(self):
        manifest = self._manifest()
        r = derive_suggested_answer_from_env_manifest(
            manifest, ["vip_config", "vip_release", "packages", 0])
        assert r is not None
        assert '"name": "amba_svt"' in r["value"]
        assert '"version": "Q-2019.06"' in r["value"]

    def test_derived_suggestion_normalizes_cleanly(self):
        r = derive_suggested_answer_from_env_manifest(
            self._manifest(), ["vip_config", "vip_release", "packages", 1, "version"],
            rationale="latest scanned release")
        assert normalize_suggested_answer(r) == r
        assert r["rationale"] == "latest scanned release"


class TestDeriveSuggestedAnswerFromDesignSourceInventory:
    """Uses the REAL dv_harness.design_source_inventory.evaluate_source()
    pipeline (a real temp file, really hashed) rather than a hand-typed row,
    so this proves the two real modules actually compose."""

    def _current_row(self, tmp_path, *, content='{"schema_version":"1.0"}', version="v3"):
        from dv_harness import design_source_inventory as dsi
        p = tmp_path / "regmap.json"
        p.write_text(content, encoding="utf-8")
        probe = dsi.evaluate_source(dsi.SourceEntry(source_id="usb3_regmap", type="register_map",
                                                       path=str(p), version=version))
        row = dsi.evaluate_source(dsi.SourceEntry(source_id="usb3_regmap", type="register_map",
                                                     path=str(p), version=version,
                                                     recorded_hash=probe["hash"]))
        assert row["status"] == dsi.STATUS_CURRENT
        return row, p

    def test_real_current_row_is_suggested(self, tmp_path):
        row, _p = self._current_row(tmp_path)
        r = derive_suggested_answer_from_design_source_inventory([row], "usb3_regmap")
        assert r == {
            "value": "v3", "source_module": "design_source_inventory",
            "source_path": "design_source_inventory#usb3_regmap.version",
        }

    def test_negative_control_a_stale_source_is_never_suggested(self, tmp_path):
        """The mandatory negative control on this half: a source whose
        content has moved since it was last checked must never be suggested
        as if it still described reality."""
        row, p = self._current_row(tmp_path)
        p.write_text('{"schema_version":"1.1"}', encoding="utf-8")
        from dv_harness import design_source_inventory as dsi
        stale_row = dsi.evaluate_source(dsi.SourceEntry(source_id="usb3_regmap", type="register_map",
                                                            path=str(p), version="v3",
                                                            recorded_hash=row["hash"]))
        assert stale_row["status"] == dsi.STATUS_STALE
        r = derive_suggested_answer_from_design_source_inventory([stale_row], "usb3_regmap")
        assert r is None

    def test_unknown_status_no_recorded_hash_is_never_suggested(self, tmp_path):
        from dv_harness import design_source_inventory as dsi
        p = tmp_path / "regmap.json"
        p.write_text("{}", encoding="utf-8")
        row = dsi.evaluate_source(dsi.SourceEntry(source_id="usb3_regmap", type="register_map", path=str(p)))
        assert row["status"] == dsi.STATUS_UNKNOWN
        assert derive_suggested_answer_from_design_source_inventory([row], "usb3_regmap") is None

    def test_no_matching_source_id_returns_none(self, tmp_path):
        row, _p = self._current_row(tmp_path)
        assert derive_suggested_answer_from_design_source_inventory([row], "some_other_source") is None

    def test_empty_rows_returns_none(self):
        assert derive_suggested_answer_from_design_source_inventory([], "usb3_regmap") is None
        assert derive_suggested_answer_from_design_source_inventory(None, "usb3_regmap") is None

    def test_missing_field_returns_none(self, tmp_path):
        row, _p = self._current_row(tmp_path)
        assert derive_suggested_answer_from_design_source_inventory(
            [row], "usb3_regmap", field="does_not_exist") is None

    def test_custom_field_is_honored(self, tmp_path):
        row, _p = self._current_row(tmp_path)
        r = derive_suggested_answer_from_design_source_inventory([row], "usb3_regmap", field="type")
        assert r["value"] == "register_map"
        assert r["source_path"] == "design_source_inventory#usb3_regmap.type"


class TestBuildSuggestThenConfirmOptions:
    def test_builds_options_and_recommendation(self):
        built = build_suggest_then_confirm_options(_real_suggestion(), alternative_labels=["R-2019.06"])
        assert built["recommendation"] == "R-2020.12"
        assert built["options"][0]["label"] == "R-2020.12"
        assert "Suggested from env_manifest" in built["options"][0]["rationale"]
        assert "newest scanned package" in built["options"][0]["rationale"]
        assert built["suggested_answer"]["value"] == "R-2020.12"

    def test_default_produces_exactly_two_options_via_a_synthetic_alternative_free_form(self):
        # No alternative_labels supplied -> only the suggested value itself
        # would form ONE option, below the schema's own 2-option minimum;
        # this must be refused rather than silently accepted as a 1-option
        # question (an open-ended question suggest-then-confirm mode still
        # must never file).
        with pytest.raises(QuestionValidationError, match="2-3"):
            build_suggest_then_confirm_options(_real_suggestion(), alternative_labels=[])

    def test_with_one_alternative_produces_two_options(self):
        built = build_suggest_then_confirm_options(_real_suggestion(), alternative_labels=["R-2019.06"])
        assert [o["label"] for o in built["options"]] == ["R-2020.12", "R-2019.06"]

    def test_too_many_alternatives_raises(self):
        with pytest.raises(QuestionValidationError, match="2-3"):
            build_suggest_then_confirm_options(_real_suggestion(),
                                                 alternative_labels=["A", "B", "C"])

    def test_alternative_repeating_the_suggested_value_raises(self):
        with pytest.raises(QuestionValidationError, match="repeats the suggested value"):
            build_suggest_then_confirm_options(_real_suggestion(), alternative_labels=["R-2020.12"])

    def test_invalid_suggested_answer_raises(self):
        with pytest.raises(QuestionValidationError):
            build_suggest_then_confirm_options({"value": "x"})  # missing source_module/source_path


class TestValidateQuestionSuggestedAnswerCrossCheck:
    def _minimal_question(self, **overrides):
        q = {
            "schema_version": "1.0", "id": "Q-VIP-00000000", "question_key": "k",
            "blocking": False, "domain": "vip", "owner": "DV-owner/Synopsys-AE",
            "question": "Which VIP release?", "context_path": "env.manifest.json#vip_config",
            "options": [{"label": "R-2020.12"}, {"label": "R-2019.06"}],
            "recommendation": "R-2020.12", "assumption_if_unanswered": "assume newest",
            "tier": 2, "tier_reason": "no_hard_trigger_low_blast_radius", "status": "ASSUMED",
            "created_at": "2026-09-07T00:00:00+00:00", "suggested_answer": None,
        }
        q.update(overrides)
        return q

    def test_agreeing_suggested_answer_passes(self):
        q = self._minimal_question(suggested_answer=_real_suggestion())
        validate_question(q)  # must not raise

    def test_absent_suggested_answer_passes(self):
        validate_question(self._minimal_question())  # must not raise

    def test_mismatched_suggested_answer_raises(self):
        """The house rule this whole mode rests on: a suggestion IS the
        recommendation, cited -- it must never silently diverge from it."""
        bad = self._minimal_question(
            suggested_answer=dict(_real_suggestion(), value="SOMETHING_ELSE"))
        with pytest.raises(QuestionValidationError, match="must equal recommendation"):
            validate_question(bad)


class TestAddQuestionSuggestThenConfirmIntegration:
    """End-to-end: real derivation from a real env_manifest-shaped dict,
    through build_suggest_then_confirm_options(), through a real
    QuestionQueueStore.add_question() call, round-tripped back out."""

    def test_full_suggest_then_confirm_round_trip(self, tmp_path):
        store = QuestionQueueStore(tmp_path)
        manifest = TestDeriveSuggestedAnswerFromEnvManifest()._manifest()
        derived = derive_suggested_answer_from_env_manifest(
            manifest, ["vip_config", "vip_release", "packages", 1, "version"],
            rationale="newest scanned package")
        assert derived is not None
        built = build_suggest_then_confirm_options(derived, alternative_labels=["Q-2019.06"])

        rec = store.add_question(
            domain="vip", question="Which VIP release is this environment built against?",
            context_path="env.manifest.json#vip_config.vip_release",
            options=built["options"], recommendation=built["recommendation"],
            assumption_if_unanswered="Assume the newest scanned VIP release until confirmed.",
            suggested_answer=built["suggested_answer"],
        )
        assert rec["suggested_answer"] == derived
        assert rec["recommendation"] == rec["suggested_answer"]["value"] == "R-2020.12"

        # round-trips through the real persisted store, not just the return value
        fetched = store.get_question(rec["id"])
        assert fetched["suggested_answer"]["source_path"].startswith("env.manifest.json#")

        # a human CONFIRMS the suggestion by answering with the same value
        answered = store.answer_question(rec["id"], answer="R-2020.12", basis="confirmed by DV owner",
                                           decided_by="alice")
        assert answered["status"] == "ANSWERED"
        assert answered["answer"] == "R-2020.12"

    def test_add_question_without_suggested_answer_is_unaffected(self, tmp_path):
        """The disclosed-default guarantee: every pre-existing caller that
        never passes suggested_answer= behaves byte-for-byte as before --
        the field is simply None."""
        store = QuestionQueueStore(tmp_path)
        rec = store.add_question(
            domain="env", question="What is the top module name?",
            context_path="env.manifest.json#dut_facts.rtl",
            options=["usb3_top", "usb3_dev_top"], recommendation="usb3_top",
            assumption_if_unanswered="assume usb3_top",
        )
        assert rec["suggested_answer"] is None
        validate_question(rec)  # schema still accepts the (absent) field

    def test_negative_control_no_real_evidence_files_an_ordinary_open_question(self, tmp_path):
        """When the harness cannot derive a suggestion (evidence genuinely
        absent), the caller falls back to filing an ordinary, un-suggested
        question rather than fabricating one -- proving the mode never
        forces a guess through when there is nothing real to suggest."""
        store = QuestionQueueStore(tmp_path)
        bare_manifest = {"vip_config": {"status": "NOT_AVAILABLE", "reason": "no dump",
                                          "vip_instances": []}}
        derived = derive_suggested_answer_from_env_manifest(
            bare_manifest, ["vip_config", "vip_release", "packages", 0, "version"])
        assert derived is None

        rec = store.add_question(
            domain="vip", question="Which VIP release is this environment built against?",
            context_path="env.manifest.json#vip_config.vip_release",
            options=["R-2020.12", "unknown -- ask vendor"],
            recommendation="R-2020.12",
            assumption_if_unanswered="Assume R-2020.12 until confirmed.",
            suggested_answer=derived,  # None -- never fabricated
        )
        assert rec["suggested_answer"] is None


class TestFileSignoffEvidenceQuestion:
    """dv_harness_tests coverage for question_queue.file_signoff_evidence_
    question() (2026-09-07 gap closure: "signoff-reviewer-cannot-ask-
    question-about-specific-evidence"): the reachable path a human reviewing
    signoff-stage evidence uses to file a NEW clarifying question tied to
    one specific evidence item, reusing add_question()'s own Tier-3/routing/
    grounding-evidence machinery unmodified."""

    def test_files_a_real_tier3_question_citing_the_named_evidence(self, tmp_path):
        store = QuestionQueueStore(tmp_path)
        rec = file_signoff_evidence_question(
            store,
            evidence_kind=SIGNOFF_EVIDENCE_KIND_BUNDLE,
            evidence_path="manifest.json#manifest[artifact='tb_source']",
            evidence_summary="tb_source reported absent in the exported signoff bundle",
            question="Is tb_source genuinely absent, or was generation skipped by mistake?",
            options=["Genuinely absent -- IP-level project, no TB generated",
                     "Mistake -- generation must be re-run before signoff"],
            recommendation="Mistake -- generation must be re-run before signoff",
            raised_by="dv-reviewer",
        )
        assert rec["tier"] == TIER3_CANNOT_ASSUME
        assert rec["blocking"] is True
        assert rec["status"] == "OPEN"
        assert rec["domain"] == "env"
        assert rec["owner"] == route_owner("env")
        assert rec["grounding_evidence"]["evidence_path"] == (
            "manifest.json#manifest[artifact='tb_source']")
        assert "dv-reviewer" in rec["grounding_evidence"]["summary"]
        assert "tb_source reported absent" in rec["grounding_evidence"]["summary"]
        validate_question(rec)  # a real, schema-valid persisted record

        # the store actually holds it, not merely the return value
        [only] = store.list_questions()
        assert only["id"] == rec["id"]

    def test_evidence_kind_vocabulary_is_closed_and_named(self):
        assert SIGNOFF_EVIDENCE_KINDS == {
            SIGNOFF_EVIDENCE_KIND_BUNDLE, SIGNOFF_EVIDENCE_KIND_BLOCKER_LIST,
            SIGNOFF_EVIDENCE_KIND_COVERAGE_CLOSURE, SIGNOFF_EVIDENCE_KIND_PROVENANCE_CAVEAT,
        }

    def test_unrecognized_evidence_kind_is_refused_never_silently_accepted(self, tmp_path):
        store = QuestionQueueStore(tmp_path)
        with pytest.raises(QuestionValidationError):
            file_signoff_evidence_question(
                store, evidence_kind="some_made_up_kind",
                evidence_path="x", evidence_summary="y",
                question="q?", options=["a", "b"], recommendation="a",
            )
        assert store.list_questions() == []  # the refused attempt persisted nothing

    def test_missing_evidence_citation_is_refused_by_the_reused_grounding_check(self, tmp_path):
        """Negative control proving this is REUSE, not a second, looser
        validation path: an empty evidence_path is refused by
        normalize_grounding_evidence()'s own existing rule, unmodified."""
        store = QuestionQueueStore(tmp_path)
        with pytest.raises(QuestionValidationError):
            file_signoff_evidence_question(
                store, evidence_kind=SIGNOFF_EVIDENCE_KIND_COVERAGE_CLOSURE,
                evidence_path="", evidence_summary="a coverage bin closure claim",
                question="q?", options=["a", "b"], recommendation="a",
            )
        assert store.list_questions() == []

    def test_idempotent_on_question_key_never_grows_the_queue(self, tmp_path):
        """A human re-reviewing the SAME evidence item (a dashboard
        re-render, a re-run signoff pass) must get back the already-filed
        record, never a duplicate -- the same dedup escalate_conflict() and
        build_multiple_choice_question() already apply, reused here."""
        store = QuestionQueueStore(tmp_path)
        kwargs = dict(
            evidence_kind=SIGNOFF_EVIDENCE_KIND_BLOCKER_LIST,
            evidence_path="signoff_blocker_list#waiver_status",
            evidence_summary="waiver_status dimension reports UNMET",
            question="Is this expired waiver a real blocker, or should it be renewed first?",
            options=["Real blocker -- signoff must wait", "Renew the waiver, then re-check"],
            recommendation="Renew the waiver, then re-check",
        )
        first = file_signoff_evidence_question(store, **kwargs)
        second = file_signoff_evidence_question(store, **kwargs)
        assert first["id"] == second["id"]
        assert len(store.list_questions()) == 1

    def test_two_different_evidence_items_never_collide_on_one_question_key(self, tmp_path):
        store = QuestionQueueStore(tmp_path)
        one = file_signoff_evidence_question(
            store, evidence_kind=SIGNOFF_EVIDENCE_KIND_BUNDLE,
            evidence_path="manifest.json#manifest[artifact='tb_source']",
            evidence_summary="tb_source absent",
            question="q?", options=["a", "b"], recommendation="a",
        )
        other = file_signoff_evidence_question(
            store, evidence_kind=SIGNOFF_EVIDENCE_KIND_BUNDLE,
            evidence_path="manifest.json#manifest[artifact='vplan']",
            evidence_summary="vplan present",
            question="q?", options=["a", "b"], recommendation="a",
        )
        assert one["id"] != other["id"]
        assert len(store.list_questions()) == 2

    def test_context_fires_the_real_pass_fail_hard_trigger_never_asserted_directly(self, tmp_path):
        store = QuestionQueueStore(tmp_path)
        rec = file_signoff_evidence_question(
            store, evidence_kind=SIGNOFF_EVIDENCE_KIND_PROVENANCE_CAVEAT,
            evidence_path="evidence_provenance#deadlock_freedom",
            evidence_summary="AGENT_SELF_ATTESTED deadlock-freedom claim on the composed system",
            question="Has anyone independently re-derived this self-attested claim?",
            options=["Yes -- treat as reliable", "No -- treat as unverified"],
            recommendation="No -- treat as unverified",
        )
        # classify_tier() reached Tier 3 through its own ordinary hard-trigger
        # evaluation of SIGNOFF_EVIDENCE_QUESTION_CONTEXT -- this function
        # never asserts the tier directly, proven by reading the real reason
        # classify_tier() itself recorded.
        assert "affects_pass_fail_verdict" in rec["tier_reason"]

    def test_extra_context_can_add_but_not_silently_drop_the_default_trigger(self, tmp_path):
        store = QuestionQueueStore(tmp_path)
        rec = file_signoff_evidence_question(
            store, evidence_kind=SIGNOFF_EVIDENCE_KIND_COVERAGE_CLOSURE,
            evidence_path="functional_coverage_signoff#usb3_lfps",
            evidence_summary="closure claims 100% but the underlying bin count looks stale",
            question="q?", options=["a", "b"], recommendation="a",
            extra_context={"affects_spec_intent": True},
        )
        assert rec["tier"] == TIER3_CANNOT_ASSUME
        assert "affects_pass_fail_verdict" in rec["tier_reason"]
        assert "affects_spec_intent" in rec["tier_reason"]

    def test_raised_by_is_never_confused_with_a_recorded_decisions_decided_by(self, tmp_path):
        store = QuestionQueueStore(tmp_path)
        rec = file_signoff_evidence_question(
            store, evidence_kind=SIGNOFF_EVIDENCE_KIND_BUNDLE,
            evidence_path="manifest.json#manifest[artifact='vplan']",
            evidence_summary="vplan/ directory bundled",
            question="q?", options=["a", "b"], recommendation="a",
            raised_by="qa-reviewer",
        )
        # raised_by never writes an answer/decision by itself.
        assert rec["decided_by"] is None
        assert rec["answered_at"] is None
        answered = store.answer_question(rec["id"], answer="a", basis="reviewed manifest by hand",
                                           decided_by="dv-lead")
        # only the real, sanctioned answer_question() path may record a
        # decider -- and it is a materially different person than raised_by.
        assert answered["decided_by"] == "dv-lead"


# --- M8 Cohort 2 (CAP-M8-EXPLOOP-002 / GAP-M8-002): CLARIFICATION_LEARNING
# real producer, hooked into answer_question() itself ------------------------

def _events(tmp_path):
    ev_file = tmp_path / ".dv-harness" / "events.jsonl"
    if not ev_file.exists():
        return []
    import json as _json
    return [_json.loads(l) for l in ev_file.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_answer_question_promotes_clarification_learning_experience(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Is register R0 write-1-to-clear?", context_path="dut.regs.R0",
        options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
    )
    store.answer_question(q["id"], answer="Yes, W1C.", basis="RTL reg_map.sv line 42",
                            decided_by="designer@example.com")

    events = [e for e in _events(tmp_path) if e.get("event") == "CLARIFICATION_LEARNING_PROMOTED"]
    assert len(events) == 1, events
    assert events[0]["question_id"] == q["id"]
    assert events[0]["promotion"]["destination"] == "ENGINEERING_MEMORY", events[0]

    # KNOWLEDGE_DISCOVERABLE/RETRIEVED via the real, pre-existing
    # MemoryRetriever -- search()'s own text match is title/root_cause only
    # (memory.py:636); this producer's title includes the real domain.
    from dv_harness.memory import MemoryStore, MemoryRetriever
    hits = MemoryRetriever(MemoryStore(tmp_path)).search({"text": "clarification answered"})
    assert any(h["memory"].get("memory_id") == events[0]["promotion"]["memory_id"] for h in hits), hits


def test_answer_question_promotion_failure_never_breaks_the_real_answer(tmp_path, monkeypatch):
    # No false success / persistence-failure isolation: a route_and_store()
    # failure inside the new best-effort hook must never break the real,
    # already-succeeded answer-persistence flow above it -- answer_question()
    # still returns the answered record exactly as before this producer
    # existed, matching every engine.py _promote_* call site's own
    # try/except-wrapped, never-downgrade-a-real-result discipline.
    import dv_harness.memory_router as mr_mod

    def _boom(*a, **kw):
        raise RuntimeError("disk full")

    # answer_question() does `from .memory_router import route_and_store`
    # LOCALLY, at call time -- patching the memory_router module's own
    # attribute is what a fresh local import actually resolves against.
    monkeypatch.setattr(mr_mod, "route_and_store", _boom)

    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Is register R1 write-1-to-clear?", context_path="dut.regs.R1",
        options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
    )
    answered = store.answer_question(q["id"], answer="Yes, W1C.", basis="RTL reg_map.sv line 9",
                                       decided_by="designer@example.com")
    assert answered["status"] == "ANSWERED"
    assert answered["answer"] == "Yes, W1C."

    events = [e for e in _events(tmp_path) if e.get("event") == "CLARIFICATION_LEARNING_PROMOTED"]
    assert len(events) == 1
    assert events[0]["promotion"]["destination"] == "PROMOTION_FAILED"
    assert "disk full" in events[0]["promotion"]["error"]


def test_answer_question_clarification_learning_does_not_cross_project_correlate(tmp_path):
    # Wrong-project correlation guard, mirroring the engine.py producers:
    # two separate QuestionQueueStore roots stay fully independent.
    root_a = tmp_path / "project_a"
    root_b = tmp_path / "project_b"
    root_a.mkdir()
    root_b.mkdir()
    store_a = QuestionQueueStore(root_a)
    q = store_a.add_question(
        domain="dut", question="Is register R2 write-1-to-clear?", context_path="dut.regs.R2",
        options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
    )
    store_a.answer_question(q["id"], answer="Yes.", basis="RTL", decided_by="designer@example.com")
    assert not (root_b / ".dv-harness" / "events.jsonl").exists()
    events_a = [e for e in _events(root_a) if e.get("event") == "CLARIFICATION_LEARNING_PROMOTED"]
    assert len(events_a) == 1


# --- M8 Cohort 4 (CAP-HITL-008 ROLE_AWARE_EXPERIENCE_LEARNING): role
# information preserved from the real authority_role signal through to
# the CLARIFICATION_LEARNING experience record -----------------------------

def test_answer_question_preserves_real_authority_role_into_experience_record(tmp_path):
    # THE GAP THIS CLOSES: a question filed with a real, already-classified
    # authority_role (CAP-M6-CLARSVC-001's own existing, wired production
    # chain: clarification_service.classify_question_owner() -> file_
    # clarification(authority_role=owner) -> add_question()) previously had
    # that role information discarded the moment it reached the
    # Experience-learning loop. It must now survive onto the promoted
    # record's own knowledge_domain/human_role fields.
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Is this reset polarity active-low by design intent?",
        context_path="dut.regs.RESET_CTRL", options=_opts(),
        recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
        authority_role="DESIGN",
    )
    assert q["authority_role"] == "DESIGN"
    store.answer_question(q["id"], answer="Yes, active-low.", basis="RTL reset_ctrl.sv",
                            decided_by="designer@example.com")

    promoted = [e for e in _events(tmp_path) if e.get("event") == "CLARIFICATION_LEARNING_PROMOTED"]
    assert len(promoted) == 1
    memory_id = promoted[0]["promotion"]["memory_id"]

    from dv_harness.memory import MemoryStore
    mem = MemoryStore(tmp_path).get(memory_id)
    assert mem["knowledge_domain"] == "DESIGN"
    assert mem["human_role"] == "DESIGN"


def test_answer_question_unclassified_when_authority_role_never_set(tmp_path):
    # Backward compatibility: a question filed through an older/
    # uninstrumented caller (authority_role never supplied, the default)
    # must not be silently dropped or falsely classified -- it gets the
    # explicit UNCLASSIFIED sentinel, exactly like Cohort 1/2/3's own
    # existing questions predating this cohort would.
    from dv_harness.experience_record import UNCLASSIFIED
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Is register R9 write-1-to-clear?", context_path="dut.regs.R9",
        options=_opts(), recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
    )
    assert q["authority_role"] is None
    store.answer_question(q["id"], answer="Yes.", basis="RTL", decided_by="designer@example.com")

    promoted = [e for e in _events(tmp_path) if e.get("event") == "CLARIFICATION_LEARNING_PROMOTED"]
    memory_id = promoted[0]["promotion"]["memory_id"]

    from dv_harness.memory import MemoryStore
    mem = MemoryStore(tmp_path).get(memory_id)
    assert mem["knowledge_domain"] == UNCLASSIFIED
    assert mem["human_role"] == UNCLASSIFIED


def test_role_aware_retrieval_distinguishes_design_from_verification(tmp_path):
    # LIVE_QUALIFICATION (Cohort 4's own required "real retrieval scenario
    # distinguishing at least 2 roles/domains with different results"):
    # zero new retrieval code -- memory.py's own pre-existing, generic
    # `property` filter (MemoryRetriever.search()'s property_filters/
    # _record_field()) already supports this once the field exists on the
    # record, proven here for real.
    store = QuestionQueueStore(tmp_path)
    q_design = store.add_question(
        domain="dut", question="Is this register's reset value 0x0 by design intent?",
        context_path="dut.regs.CTRL", options=_opts(),
        recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
        authority_role="DESIGN",
    )
    store.answer_question(q_design["id"], answer="Yes.", basis="RTL", decided_by="designer@example.com")

    q_verif = store.add_question(
        domain="env", question="Should the scoreboard treat this as a golden-model mismatch?",
        context_path="tb.scoreboard", options=_opts(),
        recommendation=_opts()[0]["label"], assumption_if_unanswered="n/a",
        authority_role="VERIFICATION",
    )
    store.answer_question(q_verif["id"], answer="Yes.", basis="scoreboard spec",
                            decided_by="dv-lead@example.com")

    from dv_harness.memory import MemoryStore, MemoryRetriever
    retriever = MemoryRetriever(MemoryStore(tmp_path))
    design_hits = retriever.search({"text": "clarification", "property": {"knowledge_domain": "DESIGN"}})
    verification_hits = retriever.search({"text": "clarification", "property": {"knowledge_domain": "VERIFICATION"}})

    design_titles = {h["memory"]["title"] for h in design_hits}
    verification_titles = {h["memory"]["title"] for h in verification_hits}
    assert design_titles == {f"Clarification answered: {q_design['domain']}"}
    assert verification_titles == {f"Clarification answered: {q_verif['domain']}"}
    assert design_titles != verification_titles


def test_role_scoped_search_excludes_pre_cohort_4_historical_records(tmp_path):
    # Compatibility with existing unclassified historical knowledge: a
    # record written BEFORE this cohort (no knowledge_domain/human_role
    # key at all, not even the UNCLASSIFIED sentinel -- exactly the shape
    # every ENGINEERING_MEMORY record from the 5 pre-Cohort-4 promotion
    # call sites already has) must not crash the property filter and must
    # not falsely match a role/domain-scoped query -- memory.py's own
    # pre-existing _property_matches()/_record_field() already handle an
    # absent key as a real "no match", proven here rather than assumed.
    from dv_harness.memory import MemoryStore, MemoryRetriever
    store = MemoryStore(tmp_path)
    store.add("engineering", {
        "title": "Pre-Cohort-4 legacy engineering lesson", "kind": "debug_lesson",
        "verified": True, "root_cause": "legacy root cause, no role/domain field at all",
        "confidence": "HIGH",
    })
    retriever = MemoryRetriever(store)
    hits = retriever.search({"text": "legacy engineering lesson", "property": {"knowledge_domain": "DESIGN"}})
    assert hits == []
    # The same record IS found by an unscoped (no property filter) query --
    # historical knowledge stays fully discoverable, just not role/domain-
    # filterable.
    unscoped = retriever.search({"text": "legacy engineering lesson"})
    assert len(unscoped) == 1
