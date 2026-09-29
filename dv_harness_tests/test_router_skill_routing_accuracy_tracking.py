"""skill_routing_accuracy_tracking (2026-09-07): router.py's new, purely additive
`record_routing_decision()` / `record_routing_outcome()` / `skill_routing_accuracy_report()`.

WHAT THESE TESTS PROVE, not merely exercise:

  1. resolve()/resolve_protocol() are byte-for-byte untouched. Every existing test in
     test_route_resolver_protocol_fold_in.py and test_research_intent_routing.py is re-run
     unmodified alongside this file (see the integration report); this file additionally
     drives real resolve()/resolve_protocol() calls and records their REAL return values,
     never a hand-typed stand-in for either.
  2. classify_routing_outcome() is grounded in REAL literal sentinels this harness's own
     routing/dispatch machinery already writes -- protocol_router.resolve_protocol()'s own
     UNRESOLVED_NEEDS_ROUTING_QUESTION reason, protocol_profile_binding_gate.py's own real
     gate_id + PROFILE_SKILL_NOT_CONSULTED reason (reproduced here in the exact shape
     gates._evaluate_stage_evidence_core() actually builds a failing reason string in:
     f"{gate_id}: {gr.detail}"), and agent_dispatch.py's own real NOT_DISPATCHED status --
     never an invented string.
  3. The required negative controls: an empty/absent gate_reasons list is honestly
     NO_OUTCOME_YET, never guessed toward either explained or not-explained; a real gate
     failure whose text matches none of the three cited sentinels is honestly
     OUTCOME_NOT_EXPLAINED_BY_ROUTING, never silently folded into "routing was fine"; and a
     bare project with no recorded decisions reports the honest NO_ROUTING_DECISIONS_RECORDED
     empty state rather than a fabricated 100%-accurate report.
  4. Nothing here writes to any second event file -- every record round-trips through the
     real `storage.StateStore` / `.dv-harness/events.jsonl`, and `skill_routing_accuracy_
     report()` reads it back through the real, reused `loop_telemetry.read_events()` rather
     than a second parser.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dv_harness import router as r
from dv_harness.protocol_router import resolve_protocol
from dv_harness.storage import StateStore


class _Node:
    """The identical minimal graph-node stand-in test_route_resolver_protocol_fold_in.py
    already uses -- RouteResolver.resolve() reads exactly these three attributes."""

    def __init__(self, route, agent, skills):
        self.route = route
        self.agent = agent
        self.skills = list(skills)


@pytest.fixture
def root(tmp_path):
    return tmp_path


def _events(root: Path):
    f = Path(root) / ".dv-harness" / "events.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


# ==========================================================================
# 1. Vocabulary self-checks -- run at import already; proven here to have
#    real detection power, not merely to pass by construction.
# ==========================================================================
def test_import_time_guards_already_passed():
    assert r.ROUTING_TELEMETRY_EVENTS == (
        "ROUTING_DECISION_RECORDED", "ROUTING_OUTCOME_RECORDED")
    r.assert_routing_telemetry_events_total()
    r.assert_no_routing_telemetry_verdict_vocabulary_collision()


def test_events_total_guard_catches_a_duplicate(monkeypatch):
    monkeypatch.setattr(r, "ROUTING_TELEMETRY_EVENTS",
                         ("ROUTING_DECISION_RECORDED", "ROUTING_DECISION_RECORDED"))
    with pytest.raises(AssertionError):
        r.assert_routing_telemetry_events_total()


def test_events_total_guard_catches_a_wrong_count(monkeypatch):
    monkeypatch.setattr(r, "ROUTING_TELEMETRY_EVENTS", ("ROUTING_DECISION_RECORDED",))
    with pytest.raises(AssertionError):
        r.assert_routing_telemetry_events_total()


def test_verdict_collision_guard_catches_a_real_status_token(monkeypatch):
    monkeypatch.setattr(r, "ROUTING_OUTCOME_STATUSES", ("PASS",))
    with pytest.raises(AssertionError):
        r.assert_no_routing_telemetry_verdict_vocabulary_collision()


# ==========================================================================
# 2. classify_routing_outcome() -- grounded, honest, never guessed.
# ==========================================================================
def test_no_gate_reasons_at_all_is_honestly_no_outcome_yet():
    assert r.classify_routing_outcome([]) == {"status": "NO_OUTCOME_YET", "matched_statuses": []}
    assert r.classify_routing_outcome(None) == {"status": "NO_OUTCOME_YET", "matched_statuses": []}


def test_unresolved_protocol_is_matched_from_the_real_resolve_protocol_reason_text():
    """protocol_router.resolve_protocol()'s own real UNRESOLVED evidence string, produced by
    the real function -- never hand-typed -- is what classify_routing_outcome() must match."""
    decision = resolve_protocol({"protocol_hint": "please continue with the plan"})
    assert decision["resolved"] is False
    assert decision["reason"] == "UNRESOLVED_NEEDS_ROUTING_QUESTION"
    gate_reasons = [f"some_downstream_gate: {decision}"]
    out = r.classify_routing_outcome(gate_reasons)
    assert out["status"] == "OUTCOME_EXPLAINED_UNRESOLVED_PROTOCOL"
    assert out["matched_statuses"] == ["OUTCOME_EXPLAINED_UNRESOLVED_PROTOCOL"]


def test_missing_skill_is_matched_from_the_real_gate_id_and_reason_shape():
    """Reproduces exactly the shape gates._evaluate_stage_evidence_core() builds a real
    failing reason string in (f"{gate_id}: {gr.detail}") for the real, shipped
    protocol_profile_binding_gate.py's own real FAIL payload shape."""
    gate_id = "protocol_profile_binding_gate"
    detail = {"status": "FAIL", "reason": "PROFILE_SKILL_NOT_CONSULTED",
               "protocol": "usb", "missing": ["usb-profile"]}
    gate_reasons = [f"{gate_id}: {detail}"]
    out = r.classify_routing_outcome(gate_reasons)
    assert out["status"] == "OUTCOME_EXPLAINED_MISSING_SKILL"
    assert out["matched_statuses"] == ["OUTCOME_EXPLAINED_MISSING_SKILL"]


def test_missing_skill_requires_both_the_gate_id_and_its_own_reason_not_either_alone():
    """The gate id alone (e.g. a PASS from the same gate quoted in an unrelated reasons
    list) must never be mistaken for a real PROFILE_SKILL_NOT_CONSULTED failure."""
    only_gate_id = ["protocol_profile_binding_gate: {'status': 'PASS', 'protocols': 1}"]
    assert r.classify_routing_outcome(only_gate_id)["status"] == "OUTCOME_NOT_EXPLAINED_BY_ROUTING"
    only_reason_text = ["some_other_gate: PROFILE_SKILL_NOT_CONSULTED mentioned in passing"]
    assert (r.classify_routing_outcome(only_reason_text)["status"]
            == "OUTCOME_NOT_EXPLAINED_BY_ROUTING")


def test_wrong_agent_is_matched_from_the_real_not_dispatched_status():
    from dv_harness.agent_dispatch import NOT_DISPATCHED
    assert NOT_DISPATCHED == "NOT_DISPATCHED"
    gate_reasons = [f"some_gate: agent status is {NOT_DISPATCHED}"]
    out = r.classify_routing_outcome(gate_reasons)
    assert out["status"] == "OUTCOME_EXPLAINED_WRONG_AGENT"


def test_a_real_unrelated_gate_failure_is_the_required_negative_control():
    """The failure mode this whole classifier exists to avoid: a real gate failure must
    never be silently folded into 'routing was fine' just because it matched nothing."""
    gate_reasons = ["command_migration_integrity_gate: {'status': 'FAIL', "
                    "'reason': 'MISSING_MIGRATION_FILE'}"]
    out = r.classify_routing_outcome(gate_reasons)
    assert out["status"] == "OUTCOME_NOT_EXPLAINED_BY_ROUTING"
    assert out["matched_statuses"] == []


def test_a_stage_that_hits_more_than_one_real_signal_reports_every_one():
    gate_reasons = [
        "protocol_profile_binding_gate: {'reason': 'PROFILE_SKILL_NOT_CONSULTED'}",
        "some_other_gate: agent NOT_DISPATCHED",
    ]
    out = r.classify_routing_outcome(gate_reasons)
    assert out["status"] == "OUTCOME_EXPLAINED_MISSING_SKILL"  # first in fixed order
    assert out["matched_statuses"] == [
        "OUTCOME_EXPLAINED_MISSING_SKILL", "OUTCOME_EXPLAINED_WRONG_AGENT"]


# ==========================================================================
# 3. record_routing_decision() -- purely additive, resolve()/resolve_protocol() untouched.
# ==========================================================================
def test_records_a_real_route_resolution_decision_verbatim(root):
    store = StateStore(root)
    node = _Node("analysis-route", "analysis-agent", ["protocol-router"])
    resolver = r.RouteResolver(root)
    protocol_decision = resolve_protocol({"protocol_hint": "USB3 enumeration failure"})
    decision = resolver.resolve(node, protocol_decision=protocol_decision)

    record = r.record_routing_decision(
        store, decision, kind=r.ROUTING_DECISION_KIND_ROUTE,
        stage="ANALYSIS", run_id="run-1", source="test")

    assert record["event"] == "ROUTING_DECISION_RECORDED"
    assert record["kind"] == "route_resolution"
    assert record["decision"] == decision  # the REAL resolve() output, verbatim
    assert record["stage"] == "ANALYSIS"
    assert record["run_id"] == "run-1"
    assert record["source"] == "test"
    assert record["decision_id"]

    on_disk = _events(root)
    assert len(on_disk) == 1
    assert on_disk[0] == record


def test_records_a_real_protocol_resolution_decision_verbatim(root):
    store = StateStore(root)
    decision = resolve_protocol({"failing_test_name": "test_pcie_link_train"})
    assert decision["resolved"] is True

    record = r.record_routing_decision(
        store, decision, kind=r.ROUTING_DECISION_KIND_PROTOCOL, stage="PROTOCOL_CAPABILITY")

    assert record["kind"] == "protocol_resolution"
    assert record["decision"]["protocol"] == "pcie"
    on_disk = _events(root)
    assert on_disk == [record]


def test_two_decisions_for_different_stages_never_collide_on_decision_id(root):
    store = StateStore(root)
    decision = {"route": "analysis-route", "agent": "analysis-agent", "skills": []}
    r1 = r.record_routing_decision(store, decision, kind=r.ROUTING_DECISION_KIND_ROUTE,
                                    stage="ANALYSIS")
    r2 = r.record_routing_decision(store, decision, kind=r.ROUTING_DECISION_KIND_ROUTE,
                                    stage="IMPLEMENT")
    assert r1["decision_id"] != r2["decision_id"]


def test_many_decisions_in_one_process_never_collide_on_decision_id(root):
    """The real monotonic per-process counter closes the timestamp-collision edge case
    outright, regardless of how fast engine.now() ticks."""
    store = StateStore(root)
    decision = {"route": "analysis-route", "agent": "analysis-agent", "skills": []}
    ids = [r.record_routing_decision(store, decision, kind=r.ROUTING_DECISION_KIND_ROUTE,
                                      stage="ANALYSIS")["decision_id"]
           for _ in range(50)]
    assert len(set(ids)) == 50


def test_record_routing_decision_refuses_an_unknown_kind(root):
    store = StateStore(root)
    with pytest.raises(r.RoutingTelemetryError):
        r.record_routing_decision(store, {"route": "x"}, kind="not_a_real_kind")
    assert _events(root) == []


def test_record_routing_decision_refuses_a_non_dict_decision(root):
    store = StateStore(root)
    with pytest.raises(r.RoutingTelemetryError):
        r.record_routing_decision(store, "not-a-dict", kind=r.ROUTING_DECISION_KIND_ROUTE)
    assert _events(root) == []


def test_record_routing_decision_refuses_a_non_json_serializable_decision(root):
    store = StateStore(root)
    bad = {"route": "x", "skills": {"not", "json", "serializable", "as", "a", "set"}}
    with pytest.raises(r.RoutingTelemetryError):
        r.record_routing_decision(store, bad, kind=r.ROUTING_DECISION_KIND_ROUTE)
    assert _events(root) == []


def test_resolve_and_resolve_protocol_are_completely_unaffected_by_recording(root):
    """The mandated proof that this addition changed nothing about the two existing
    functions: calling record_routing_decision() in between two identical resolve() calls
    must not alter what the second call returns."""
    store = StateStore(root)
    node = _Node("analysis-route", "analysis-agent", ["protocol-router"])
    resolver = r.RouteResolver(root)
    protocol_decision = resolve_protocol({"protocol_hint": "USB3 enumeration failure"})

    before = resolver.resolve(node, protocol_decision=protocol_decision)
    r.record_routing_decision(store, before, kind=r.ROUTING_DECISION_KIND_ROUTE)
    after = resolver.resolve(node, protocol_decision=protocol_decision)

    assert before == after


# ==========================================================================
# 4. record_routing_outcome() -- joined by decision_id, honest classification.
# ==========================================================================
def test_records_and_joins_a_real_outcome_to_its_decision(root):
    store = StateStore(root)
    decision = {"route": "analysis-route", "agent": "analysis-agent", "skills": []}
    dec_record = r.record_routing_decision(store, decision, kind=r.ROUTING_DECISION_KIND_ROUTE,
                                            stage="ANALYSIS")
    gate_reasons = ["protocol_profile_binding_gate: {'reason': 'PROFILE_SKILL_NOT_CONSULTED'}"]

    out_record = r.record_routing_outcome(store, dec_record["decision_id"], gate_reasons,
                                           stage="ANALYSIS")

    assert out_record["event"] == "ROUTING_OUTCOME_RECORDED"
    assert out_record["decision_id"] == dec_record["decision_id"]
    assert out_record["status"] == "OUTCOME_EXPLAINED_MISSING_SKILL"
    assert out_record["gate_reasons"] == gate_reasons
    on_disk = _events(root)
    assert on_disk == [dec_record, out_record]


def test_record_routing_outcome_refuses_a_blank_decision_id(root):
    store = StateStore(root)
    with pytest.raises(r.RoutingTelemetryError):
        r.record_routing_outcome(store, "", ["some gate failure"])
    with pytest.raises(r.RoutingTelemetryError):
        r.record_routing_outcome(store, None, ["some gate failure"])
    assert _events(root) == []


def test_record_routing_outcome_with_no_gate_reasons_is_honestly_no_outcome_yet(root):
    store = StateStore(root)
    out = r.record_routing_outcome(store, "some-real-decision-id")
    assert out["status"] == "NO_OUTCOME_YET"
    assert out["gate_reasons"] == []


# ==========================================================================
# 5. skill_routing_accuracy_report() -- honest aggregation, never fabricated.
# ==========================================================================
def test_a_bare_project_reports_the_honest_empty_state(root):
    report = r.skill_routing_accuracy_report(root)
    assert report == {
        "available": False,
        "reason": r.NO_ROUTING_DECISIONS_RECORDED,
        "events_scanned": 0,
        "scan_truncated": False,
    }


def test_a_bare_project_report_mints_no_dv_harness_tree(root):
    r.skill_routing_accuracy_report(root)
    assert not (Path(root) / ".dv-harness").exists()


def test_report_reads_back_and_joins_multiple_real_decisions_and_outcomes(root):
    store = StateStore(root)

    d1 = r.record_routing_decision(
        store, {"route": "analysis-route"}, kind=r.ROUTING_DECISION_KIND_ROUTE, stage="ANALYSIS")
    r.record_routing_outcome(
        store, d1["decision_id"],
        ["protocol_profile_binding_gate: {'reason': 'PROFILE_SKILL_NOT_CONSULTED'}"])

    d2 = r.record_routing_decision(
        store, {"route": "implementation-route"}, kind=r.ROUTING_DECISION_KIND_ROUTE,
        stage="IMPLEMENT")
    r.record_routing_outcome(
        store, d2["decision_id"], ["some_other_gate: {'reason': 'UNRELATED_FAILURE'}"])

    d3 = r.record_routing_decision(
        store, {"route": "regression-route"}, kind=r.ROUTING_DECISION_KIND_ROUTE,
        stage="REGRESSION")
    # d3 has no observed outcome recorded at all yet.

    report = r.skill_routing_accuracy_report(root)

    assert report["available"] is True
    assert report["decisions_recorded"] == 3
    assert report["decisions_with_outcome_recorded"] == 2
    assert report["status_counts"]["OUTCOME_EXPLAINED_MISSING_SKILL"] == 1
    assert report["status_counts"]["OUTCOME_NOT_EXPLAINED_BY_ROUTING"] == 1
    assert report["status_counts"]["NO_OUTCOME_YET"] == 1
    # rate is computed only over the 2 decisions with an OBSERVED outcome:
    assert report["explains_failure_rate"] == pytest.approx(0.5)
    assert report["explains_failure_rate_reason"] is None

    by_id = {d["decision_id"]: d for d in report["decisions"]}
    assert by_id[d1["decision_id"]]["status"] == "OUTCOME_EXPLAINED_MISSING_SKILL"
    assert by_id[d3["decision_id"]]["status"] == "NO_OUTCOME_YET"


def test_report_never_fabricates_a_rate_when_no_outcome_has_ever_been_observed(root):
    store = StateStore(root)
    r.record_routing_decision(store, {"route": "analysis-route"},
                               kind=r.ROUTING_DECISION_KIND_ROUTE)
    report = r.skill_routing_accuracy_report(root)
    assert report["decisions_recorded"] == 1
    assert report["decisions_with_outcome_recorded"] == 0
    assert report["explains_failure_rate"] is None
    assert "never fabricated" in report["explains_failure_rate_reason"]


def test_report_uses_the_latest_outcome_when_one_decision_is_re_observed(root):
    store = StateStore(root)
    d = r.record_routing_decision(store, {"route": "analysis-route"},
                                   kind=r.ROUTING_DECISION_KIND_ROUTE)
    r.record_routing_outcome(store, d["decision_id"], [])  # first: NO_OUTCOME_YET
    r.record_routing_outcome(
        store, d["decision_id"],
        ["some_gate: agent NOT_DISPATCHED"])  # later, real: WRONG_AGENT

    report = r.skill_routing_accuracy_report(root)
    assert report["decisions_recorded"] == 1
    by_id = {row["decision_id"]: row for row in report["decisions"]}
    assert by_id[d["decision_id"]]["status"] == "OUTCOME_EXPLAINED_WRONG_AGENT"


def test_report_reuses_loop_telemetrys_own_public_reader(root, monkeypatch):
    """Proves reuse rather than a second independent events.jsonl parser: patching
    loop_telemetry.read_events must change what this report sees."""
    from dv_harness import loop_telemetry as lt

    store = StateStore(root)
    r.record_routing_decision(store, {"route": "analysis-route"},
                               kind=r.ROUTING_DECISION_KIND_ROUTE)

    calls = []
    real_read = lt.read_events

    def _spy(root_arg, **kwargs):
        calls.append(root_arg)
        return real_read(root_arg, **kwargs)

    monkeypatch.setattr(lt, "read_events", _spy)
    report = r.skill_routing_accuracy_report(root)
    assert report["available"] is True
    assert calls == [root]
