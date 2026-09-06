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
    DoNotAskError,
    HUMAN_DECISION_SOURCE,
    TIER2_AUTO_ASSUMPTION_SOURCE,
    QuestionQueueStore,
    QuestionValidationError,
    TIER1_SELF_RESOLVE,
    TIER2_SAFE_ASSUME,
    TIER3_CANNOT_ASSUME,
    assert_all_evidence_paths_present,
    build_multiple_choice_question,
    classify_tier,
    find_redundant_decision,
    is_cannot_assume,
    make_question_id,
    make_question_key,
    normalize_options,
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
