"""Tests for dv_harness/harness_status_policy.py -- UNKNOWN / STALE /
change-only-notification / freshness policies applied to HarnessStatusIR
transitions (Global Status Bar theme, sections 422-423, 433-434).

The central negative control (`test_bare_snapshot_reports_unknown_honestly_never_zero`)
is the same Evidence Truth Rule / GF-AT-28 proof this whole item exists to
satisfy: a completely unread project's snapshot must report every critical
status field UNKNOWN, with a real, non-zero `critical_unknown_count`, never
a silently-suppressed zero and never a fabricated READY.
"""
from __future__ import annotations

import copy

import pytest

from dv_harness import harness_status as hs
from dv_harness import harness_status_ir as hir
from dv_harness import escalation_notify as en
from dv_harness import harness_status_policy as p


class _FakeTransport:
    """Same recording-fake pattern test_harness_status.py's own notification
    tests already use -- no live network call, ever."""

    def __init__(self):
        self.sent = []

    def send(self, title, body, tags=None):
        self.sent.append((title, body, tuple(tags or ())))
        return True


def _notifier(transport=None):
    transport = transport if transport is not None else _FakeTransport()
    return en.EscalationNotifier(en.EscalationConfig(enabled=True), transport=transport), transport


def _fresh_ir():
    return hs.HarnessStatusIR()


# ===========================================================================
# Section 422: UNKNOWN POLICY
# ===========================================================================

def test_critical_status_leaf_paths_are_all_governed_status_fields():
    # Re-run the same self-check import already performs -- proves it is a
    # real, callable check, not merely "did not raise once at import time".
    p._assert_critical_paths_resolvable()


def test_dget_reports_missing_for_a_real_unresolvable_path():
    # Detection-power proof for the self-check above: a field
    # CRITICAL_STATUS_LEAF_PATHS does NOT name is genuinely reported
    # unresolvable, exactly what _assert_critical_paths_resolvable() would
    # catch if a real field were renamed out from under it.
    snap = p.fresh_unknown_snapshot()
    assert p._dget(snap, "harness.this_field_does_not_exist") is p._MISSING


def test_bare_snapshot_reports_unknown_honestly_never_zero():
    """Negative control: absence of evidence must report UNKNOWN honestly."""
    snap = p.fresh_unknown_snapshot()
    count = p.critical_unknown_count(snap)
    assert count == len(p.CRITICAL_STATUS_LEAF_PATHS)
    assert count > 0
    unknown_fields = p.find_unknown_status_fields(snap)
    assert set(path for path, _ in unknown_fields) == set(p.CRITICAL_STATUS_LEAF_PATHS)
    for _, value in unknown_fields:
        assert value == "UNKNOWN"


def test_critical_unknown_count_decreases_as_fields_are_resolved():
    ir = _fresh_ir()
    baseline = p.critical_unknown_count(ir)
    ir.harness.state = "READY"
    ir.harness.readiness = "READY"
    ir.closure.requirement = "READY"
    after = p.critical_unknown_count(ir)
    assert after == baseline - 3
    remaining = {path for path, _ in p.find_unknown_status_fields(ir)}
    assert "harness.state" not in remaining
    assert "harness.readiness" not in remaining
    assert "closure.requirement" not in remaining
    assert "closure.vplan" in remaining  # still genuinely unknown


def test_critical_unknown_count_accepts_a_real_ir_instance_directly():
    ir = _fresh_ir()
    ir.harness.state = "READY"
    from_ir = p.critical_unknown_count(ir)
    from_dict = p.critical_unknown_count(ir.to_dict())
    assert from_ir == from_dict


def test_as_snapshot_refuses_an_unrecognized_shape():
    with pytest.raises(p.HarnessStatusPolicyError) as exc:
        p.critical_unknown_count(object())
    assert exc.value.reason == "UNRECOGNIZED_HARNESS_STATUS_IR_SHAPE"


def test_unknown_evidence_gaps_reuses_the_real_unknowns_list_citation():
    ir = _fresh_ir()
    ir.unknowns.append({"field": "closure.code_coverage",
                         "reason": "no distinct code-coverage row exists in "
                                   "golden_flow_readiness"})
    gaps = p.unknown_evidence_gaps(ir)
    hit = next(g for g in gaps if g["field"] == "closure.code_coverage")
    assert hit["status"] == "UNKNOWN"
    assert "no distinct code-coverage row" in hit["reason"]


def test_unknown_evidence_gaps_honest_when_no_citation_recorded():
    # closure.subsystem/closure.system default UNKNOWN with no unknowns[]
    # entry in a genuinely bare aggregation -- the gap in the aggregator's
    # own bookkeeping is itself real information this must never hide.
    ir = _fresh_ir()
    gaps = p.unknown_evidence_gaps(ir)
    hit = next(g for g in gaps if g["field"] == "closure.subsystem")
    assert hit["reason"].startswith("no recorded reason")


def test_unknown_evidence_gaps_never_reports_a_resolved_field():
    ir = _fresh_ir()
    ir.harness.state = "READY"
    gaps = p.unknown_evidence_gaps(ir)
    assert all(g["field"] != "harness.state" for g in gaps)


# ===========================================================================
# Section 423: STALE POLICY
# ===========================================================================

def test_find_stale_artifacts_detects_real_stale_leaves():
    ir = _fresh_ir()
    ir.closure.functional_coverage = "STALE"
    ir.execution.regression_state = "STALE"
    stale = p.find_stale_artifacts(ir)
    assert set(stale) == {"closure.functional_coverage", "execution.regression_state"}


def test_stale_artifact_never_blocks_when_not_claiming_signoff_ready():
    ir = _fresh_ir()
    ir.closure.functional_coverage = "STALE"
    ir.harness.signoff_state = "PARTIAL"
    # Must not raise -- the rule only fires when SIGNOFF_READY is claimed.
    p.assert_stale_artifacts_never_satisfy_signoff(ir)


def test_stale_artifact_blocks_an_unrevalidated_signoff_claim():
    ir = _fresh_ir()
    ir.closure.functional_coverage = "STALE"
    ir.harness.signoff_state = "SIGNOFF_READY"
    with pytest.raises(p.HarnessStatusPolicyError) as exc:
        p.assert_stale_artifacts_never_satisfy_signoff(ir)
    assert exc.value.reason == "STALE_ARTIFACTS_BLOCK_SIGNOFF"
    assert "closure.functional_coverage" in exc.value.detail["unrevalidated_stale_artifacts"]


def test_explicit_revalidation_with_a_real_reason_clears_the_stale_block():
    ir = _fresh_ir()
    ir.closure.functional_coverage = "STALE"
    ir.harness.signoff_state = "SIGNOFF_READY"
    # Must not raise once explicitly, honestly revalidated.
    p.assert_stale_artifacts_never_satisfy_signoff(
        ir, revalidated={"closure.functional_coverage": "re-ran coverage collection 2026-09-06, "
                                                          "confirmed still green"})


def test_revalidation_requires_a_real_non_empty_reason():
    ir = _fresh_ir()
    ir.closure.functional_coverage = "STALE"
    ir.harness.signoff_state = "SIGNOFF_READY"
    with pytest.raises(p.HarnessStatusPolicyError) as exc:
        p.assert_stale_artifacts_never_satisfy_signoff(
            ir, revalidated={"closure.functional_coverage": "   "})
    assert exc.value.reason == "REVALIDATION_REQUIRES_A_REAL_REASON"


def test_revalidation_of_an_unrelated_field_does_not_clear_a_different_stale_artifact():
    ir = _fresh_ir()
    ir.closure.functional_coverage = "STALE"
    ir.harness.signoff_state = "SIGNOFF_READY"
    with pytest.raises(p.HarnessStatusPolicyError):
        p.assert_stale_artifacts_never_satisfy_signoff(
            ir, revalidated={"closure.performance": "revalidated performance, unrelated field"})


def test_derive_stale_gated_signoff_state_downgrades_to_stale():
    ir = _fresh_ir()
    ir.closure.system = "STALE"
    ir.harness.signoff_state = "SIGNOFF_READY"
    assert p.derive_stale_gated_signoff_state(ir) == "STALE"


def test_derive_stale_gated_signoff_state_unchanged_when_revalidated():
    ir = _fresh_ir()
    ir.closure.system = "STALE"
    ir.harness.signoff_state = "SIGNOFF_READY"
    result = p.derive_stale_gated_signoff_state(
        ir, revalidated={"closure.system": "human confirmed system-integration proof re-run"})
    assert result == "SIGNOFF_READY"


def test_derive_stale_gated_signoff_state_unchanged_when_not_signoff_ready():
    ir = _fresh_ir()
    ir.closure.system = "STALE"
    ir.harness.signoff_state = "PARTIAL"
    assert p.derive_stale_gated_signoff_state(ir) == "PARTIAL"


# ===========================================================================
# Section 434: STATUS FRESHNESS
# ===========================================================================

def test_freshness_gate_downgrades_stale_ready_to_stale():
    ir = _fresh_ir()
    ir.harness.state = "READY"
    ir.freshness.state = "STALE"
    assert p.apply_freshness_gate(ir) == "STALE"


def test_freshness_gate_downgrades_unmeasured_ready_to_unknown():
    ir = _fresh_ir()
    ir.harness.state = "READY"
    ir.freshness.state = "UNKNOWN"
    assert p.apply_freshness_gate(ir) == "UNKNOWN"


def test_freshness_gate_never_downgrades_a_genuinely_fresh_ready():
    ir = _fresh_ir()
    ir.harness.state = "READY"
    ir.freshness.state = "READY"
    assert p.apply_freshness_gate(ir) == "READY"


def test_freshness_gate_never_upgrades_a_worse_real_state():
    # A fresh freshness signal must not paper over an independently worse
    # real harness.state -- worst-wins applies in both directions.
    ir = _fresh_ir()
    ir.harness.state = "BLOCKED"
    ir.freshness.state = "READY"
    assert p.apply_freshness_gate(ir) == "BLOCKED"


def test_freshness_gated_snapshot_adds_effective_state_without_mutating_raw():
    ir = _fresh_ir()
    ir.harness.state = "READY"
    ir.freshness.state = "STALE"
    original = ir.to_dict()
    gated = p.freshness_gated_snapshot(ir)
    assert gated["effective_harness_state"] == "STALE"
    # The raw computed harness.state must remain independently inspectable.
    assert gated["harness"]["state"] == "READY"
    # The function must not have mutated the IR it was handed.
    assert ir.to_dict() == original


# ===========================================================================
# Section 433: CHANGE-ONLY STATUS NOTIFICATION
# ===========================================================================

def test_classify_transition_no_change_on_equal_values():
    assert p.classify_transition("PASS", "PASS") == p.NO_CHANGE


def test_classify_transition_categorical_change_is_notify():
    assert p.classify_transition("RUNNING", "FAILED") == p.NOTIFY
    assert p.classify_transition("PARTIAL", "READY") == p.NOTIFY


def test_classify_transition_improving_count_is_update():
    # UNKNOWN 3 -> UNKNOWN 2 (section 433's own worked example)
    assert p.classify_transition(3, 2) == p.UPDATE


def test_classify_transition_worsening_count_is_notify():
    # GATE 0 -> GATE 1 (section 433's own worked example)
    assert p.classify_transition(0, 1) == p.NOTIFY


def test_classify_transition_first_observation_is_notify():
    assert p.classify_transition(None, "READY") == p.NOTIFY
    assert p.classify_transition(None, 0) == p.NOTIFY


def test_classify_transition_none_to_none_is_no_change():
    assert p.classify_transition(None, None) == p.NO_CHANGE


def test_classify_transition_bools_are_never_treated_as_numeric_counts():
    # bool is an int subclass in Python -- must not silently take the
    # numeric-count branch (False < True would misclassify a boolean flip
    # as a "count improved" UPDATE rather than a real state change).
    assert p.classify_transition(False, True) == p.NOTIFY


# --- evaluate_status_transition: reuses harness_status_ir.notify_status_change() ---

def test_evaluate_status_transition_no_change_never_touches_transport():
    notifier, transport = _notifier()
    result = p.evaluate_status_transition("harness.state", "READY", "READY", notifier)
    assert result["classification"] == p.NO_CHANGE
    assert result["notification"] is None
    assert transport.sent == []


def test_evaluate_status_transition_update_never_touches_transport():
    notifier, transport = _notifier()
    result = p.evaluate_status_transition("blockers.critical_unknown", 3, 2, notifier)
    assert result["classification"] == p.UPDATE
    assert result["notification"] is None
    assert transport.sent == []


def test_evaluate_status_transition_notify_fires_through_the_real_notifier():
    notifier, transport = _notifier()
    result = p.evaluate_status_transition("blockers.human_gates", 0, 1, notifier)
    assert result["classification"] == p.NOTIFY
    assert result["notification"]["fired"] is True
    assert result["notification"]["delivered"] is True
    assert len(transport.sent) == 1
    title, body, tags = transport.sent[0]
    assert "blockers.human_gates" in tags


def test_evaluate_status_transition_reuses_notify_status_change_verbatim(monkeypatch):
    """Proof of reuse, not reinvention: this module must call
    harness_status_ir.notify_status_change() itself, never a re-implemented
    copy of its condition/transport logic."""
    calls = []
    real = hir.notify_status_change

    def spy(notifier, *, dimension, previous, current, title, body):
        calls.append((dimension, previous, current))
        return real(notifier, dimension=dimension, previous=previous, current=current,
                    title=title, body=body)

    monkeypatch.setattr(p.hir, "notify_status_change", spy)
    notifier, transport = _notifier()
    p.evaluate_status_transition("harness.signoff_state", "PARTIAL", "BLOCKED", notifier)
    assert calls == [("harness.signoff_state", "PARTIAL", "BLOCKED")]


def test_evaluate_status_transition_notify_without_a_notifier_records_no_notification():
    result = p.evaluate_status_transition("harness.state", "RUNNING", "FAILED", notifier=None)
    assert result["classification"] == p.NOTIFY
    assert result["notification"] is None


# --- evaluate_status_bar_change: the whole snapshot-pair walk ---

def test_evaluate_status_bar_change_classifies_every_default_dimension():
    prev = _fresh_ir()
    prev.harness.state = "RUNNING"
    prev.harness.signoff_state = "PARTIAL"
    prev.freshness.state = "READY"
    prev.blockers.critical_failures = 0
    prev.blockers.critical_unknown = 3
    prev.blockers.human_gates = 0

    curr = copy.deepcopy(prev)
    curr.harness.state = "FAILED"          # categorical -> NOTIFY
    curr.blockers.critical_unknown = 2     # improving count -> UPDATE
    curr.blockers.human_gates = 1          # worsening count -> NOTIFY
    # signoff_state/freshness.state/critical_failures unchanged -> NO_CHANGE

    notifier, transport = _notifier()
    results = p.evaluate_status_bar_change(prev, curr, notifier=notifier)
    by_dim = {r["dimension"]: r for r in results}

    assert by_dim["harness.state"]["classification"] == p.NOTIFY
    assert by_dim["harness.signoff_state"]["classification"] == p.NO_CHANGE
    assert by_dim["freshness.state"]["classification"] == p.NO_CHANGE
    assert by_dim["blockers.critical_failures"]["classification"] == p.NO_CHANGE
    assert by_dim["blockers.critical_unknown"]["classification"] == p.UPDATE
    assert by_dim["blockers.human_gates"]["classification"] == p.NOTIFY

    # Exactly the NOTIFY-classified dimensions reached the transport.
    notified_dims = {r["dimension"] for r in results if r["classification"] == p.NOTIFY}
    assert notified_dims == {"harness.state", "blockers.human_gates"}
    assert len(transport.sent) == len(notified_dims)


def test_evaluate_status_bar_change_includes_synthetic_critical_unknown_count():
    prev = _fresh_ir()
    prev.harness.state = "READY"  # resolve one critical field
    curr = _fresh_ir()
    curr.harness.state = "READY"
    curr.harness.readiness = "READY"  # resolve a second one -> count improves

    results = p.evaluate_status_bar_change(prev, curr)
    hit = next(r for r in results if r["dimension"] == "critical_unknown_count")
    assert hit["previous"] == p.critical_unknown_count(prev)
    assert hit["current"] == p.critical_unknown_count(curr)
    assert hit["current"] < hit["previous"]
    assert hit["classification"] == p.UPDATE


def test_evaluate_status_bar_change_reports_unresolved_for_a_missing_dimension():
    prev = p.fresh_unknown_snapshot()
    curr = p.fresh_unknown_snapshot()
    results = p.evaluate_status_bar_change(
        prev, curr, dimensions=("harness.state", "this.does.not.exist"))
    hit = next(r for r in results if r["dimension"] == "this.does.not.exist")
    assert hit["classification"] == "UNRESOLVED"
    assert hit["notification"] is None


def test_evaluate_status_bar_change_accepts_real_ir_instances_directly():
    prev = _fresh_ir()
    curr = _fresh_ir()
    curr.harness.state = "READY"
    results = p.evaluate_status_bar_change(prev, curr)
    hit = next(r for r in results if r["dimension"] == "harness.state")
    assert hit["previous"] == "UNKNOWN"
    assert hit["current"] == "READY"
    assert hit["classification"] == p.NOTIFY
