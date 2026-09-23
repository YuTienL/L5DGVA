"""L5DGVA V14 section 342 (`EightEngineRuntimeProofMatrix`): tests for
`dv_harness/eight_engine_runtime_proof_matrix.py`.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim. None of these
13 tests exercise the 3 memory-promotion signals dropped by this batch's production-code
adaptation (`ARCHITECTURE_DISCOVERY_PROMOTED`/`VERIFICATION_ARCHITECTURE_TOPOLOGY_PROMOTED`/
`DE_BASELINE_REPRODUCTION_PROMOTED` -- see eight_engine_runtime_proof_matrix.py's own
module docstring for the adaptation rationale), confirmed by reading this file in full
before porting -- so no test-side adaptation was needed.

WHAT THESE TESTS ARE FOR. The module's whole point is to never say PROVEN
from anything weaker than a real, named event this codebase's own
`engine.py` actually emits. So the five things worth proving are:

  1. A real event type that IS one of an engine's signals -> PROVEN, with the
     matching record surfaced in InvocationEvidence.
  2. An engine with a real producer that simply never fired in the window ->
     NOT_PROVEN (not silently upgraded, not silently hidden).
  3. An UNRELATED event -- including one that merely LOOKS adjacent (e.g. a
     graph fan-out event) -- never flips an engine's verdict to PROVEN. This
     is the one this module is built entirely around not getting wrong.
  4. A predicate-narrowed signal (Qualification/Signoff's LOOP_BLOCKED with
     reason=="SIGNOFF_GATE_REFUSED") only counts when the predicate matches,
     not on every LOOP_BLOCKED.
  5. The 3 engines with no real events.jsonl producer today
     (Multi-Agent Orchestrator, Route & Skill Resolver, ReAct) always read
     NO_RUNTIME_SIGNAL_SOURCE, never NOT_PROVEN -- they are a different,
     honestly distinct claim (no producer at all vs. a producer that stayed
     quiet).

Every event record below is a FIXTURE -- shaped like what `engine.py` really
emits (same event names, same field names, cited in
`eight_engine_runtime_proof_matrix.ENGINE_RULES[...].evidence_refs`), written
directly through the real `storage.StateStore.event()` so the module under
test reads the exact append-only file format `loop_telemetry.read_events()`
already reads in production -- never a hand-rolled JSON shape.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import eight_engine_runtime_proof_matrix as eerpm
from dv_harness.storage import StateStore


@pytest.fixture()
def project_root():
    d = Path(tempfile.mkdtemp(prefix="eight_engine_matrix_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _store(root: Path) -> StateStore:
    return StateStore(root)


def test_all_eight_engines_present_no_more_no_fewer():
    ids = {r.engine_id for r in eerpm.ENGINE_RULES}
    assert len(ids) == 8
    names = {r.engine_name for r in eerpm.ENGINE_RULES}
    assert names == {
        "Autonomous Inference Engine", "Graph Orchestrator",
        "Multi-Agent Orchestrator", "Route & Skill Resolver",
        "Plan-and-Execute / ReAct Engine", "Blackboard / Evidence Engine",
        "5-Level Memory Engine", "Qualification / Signoff Engine",
    }


def test_empty_events_file_is_not_proven_for_any_signal_engine(project_root):
    rows = eerpm.build_matrix(project_root)
    for row in rows.values():
        assert row.invoked is False
        assert row.invocation_evidence == []
    # Engines with a real producer: NOT_PROVEN (wired, silent this run).
    assert rows["autonomous_inference_engine"].verdict == eerpm.NOT_PROVEN
    assert rows["five_level_memory_engine"].verdict == eerpm.NOT_PROVEN
    assert rows["qualification_signoff_engine"].verdict == eerpm.NOT_PROVEN
    assert rows["blackboard_evidence_engine"].verdict == eerpm.NOT_PROVEN
    assert rows["graph_orchestrator"].verdict == eerpm.NOT_PROVEN
    # Engines with NO producer at all: NO_RUNTIME_SIGNAL_SOURCE, always.
    assert rows["multi_agent_orchestrator"].verdict == eerpm.NO_RUNTIME_SIGNAL_SOURCE
    assert rows["route_skill_resolver"].verdict == eerpm.NO_RUNTIME_SIGNAL_SOURCE
    assert rows["plan_execute_react_engine"].verdict == eerpm.NO_RUNTIME_SIGNAL_SOURCE
    assert eerpm.matrix_pass(rows) is False


def test_root_cause_confidence_scored_proves_inference_engine(project_root):
    """PROVEN case #1: a real ROOT_CAUSE_CONFIDENCE_SCORED record (the exact
    shape engine.py:2808 emits) proves the Inference Engine, and nothing
    else."""
    store = _store(project_root)
    store.event({
        "ts": "2026-09-16T00:00:00Z", "stage": "RE_AUDIT",
        "event": "ROOT_CAUSE_CONFIDENCE_SCORED",
        "recomputed_confidence": {"level": "HIGH", "score": 5},
        "agent_reported_confidence": "HIGH",
        "concurrent_agent_evidence_count": 2,
        "gap": [], "next_best_action": [], "promotion": {"promoted": True},
    })
    rows = eerpm.build_matrix(project_root)
    row = rows["autonomous_inference_engine"]
    assert row.verdict == eerpm.PROVEN
    assert row.invoked is True
    assert len(row.invocation_evidence) == 1
    assert row.invocation_evidence[0]["event"] == "ROOT_CAUSE_CONFIDENCE_SCORED"
    # No unrelated engine flips to PROVEN because of this one event.
    for engine_id, other in rows.items():
        if engine_id != "autonomous_inference_engine":
            assert other.verdict != eerpm.PROVEN


def test_experience_knowledge_promoted_proves_memory_engine(project_root):
    """PROVEN case #2, a distinct engine: a real *_PROMOTED record (the exact
    shape engine.py:1907 emits) proves the 5-Level Memory Engine."""
    store = _store(project_root)
    store.event({
        "ts": "2026-09-16T00:00:00Z", "stage": "DEBUG",
        "event": "EXPERIENCE_KNOWLEDGE_PROMOTED",
        "record_kind": "debug_finding",
        "promotion": {"destination": "ENGINEERING_MEMORY"},
    })
    rows = eerpm.build_matrix(project_root)
    row = rows["five_level_memory_engine"]
    assert row.verdict == eerpm.PROVEN
    assert row.invocation_evidence[0]["promotion_destination"] == "ENGINEERING_MEMORY"
    assert rows["autonomous_inference_engine"].verdict == eerpm.NOT_PROVEN


def test_unrelated_event_never_fabricates_a_proven_verdict(project_root):
    """The core refusal this module exists for: RCA_EVIDENCE_FANOUT_DISPATCHED
    without a route field is real Graph Orchestrator evidence (branch
    selection) but must NEVER be counted as Multi-Agent Orchestrator proof,
    even though multi-agent dispatch typically follows it in a real run."""
    store = _store(project_root)
    store.event({
        "ts": "2026-09-16T00:00:00Z", "stage": "ANALYSIS_G1",
        "event": "RCA_EVIDENCE_FANOUT_DISPATCHED",
        "parallel_group": "RCA_EVIDENCE_FANOUT",
        "branches": ["RTL_EVIDENCE", "LOG_EVIDENCE", "VIP_SPEC_EVIDENCE"],
        "armed_by": "REAL_ISSUE:abc123",
    })
    rows = eerpm.build_matrix(project_root)
    # This IS real Graph Orchestrator evidence (an explicit signal for it).
    assert rows["graph_orchestrator"].verdict == eerpm.PROVEN
    # Multi-Agent Orchestrator has no producer at all -- still, and only,
    # NO_RUNTIME_SIGNAL_SOURCE. Never PROVEN from this adjacent event.
    assert rows["multi_agent_orchestrator"].verdict == eerpm.NO_RUNTIME_SIGNAL_SOURCE
    assert rows["multi_agent_orchestrator"].invoked is False
    assert rows["multi_agent_orchestrator"].invocation_evidence == []
    # Also entirely unrelated to a completely different event name.
    store2root = project_root
    store.event({"ts": "2026-09-16T00:00:01Z", "stage": "IMPLEMENT",
                 "event": "SIGNOFF_BUNDLE_EXPORTED", "out_dir": "/tmp/x"})
    rows2 = eerpm.build_matrix(store2root)
    assert rows2["route_skill_resolver"].verdict == eerpm.NO_RUNTIME_SIGNAL_SOURCE


def test_loop_action_selected_without_route_does_not_prove_graph(project_root):
    """A LOOP_ACTION_SELECTED with no route (the node lookup failed / node is
    None) must not count -- the predicate genuinely gates the verdict."""
    store = _store(project_root)
    store.event({
        "ts": "2026-09-16T00:00:00Z", "stage": "GHOST_STAGE",
        "event": "LOOP_ACTION_SELECTED", "action": "run_stage",
        "route": None, "skills": [], "attempts": 1,
    })
    rows = eerpm.build_matrix(project_root)
    assert rows["graph_orchestrator"].verdict == eerpm.NOT_PROVEN


def test_loop_blocked_only_proves_qualification_on_signoff_gate_refused(project_root):
    """Predicate-narrowed signal: LOOP_BLOCKED fires for many stop reasons in
    the real engine (circuit breaker, budget exhaustion, ...). Only
    reason == SIGNOFF_GATE_REFUSED is Qualification/Signoff Engine evidence."""
    store = _store(project_root)
    store.event({
        "ts": "2026-09-16T00:00:00Z", "stage": "BUILD",
        "event": "LOOP_BLOCKED", "loop_state": "BLOCKED",
        "reason": "SOME_OTHER_STOP_REASON",
    })
    rows = eerpm.build_matrix(project_root)
    assert rows["qualification_signoff_engine"].verdict == eerpm.NOT_PROVEN

    store.event({
        "ts": "2026-09-16T00:00:01Z", "stage": "SIGNOFF",
        "event": "LOOP_BLOCKED", "loop_state": "BLOCKED",
        "reason": "SIGNOFF_GATE_REFUSED",
        "resume_condition": "close what policy.can_signoff() named, then dv-harness start --loop",
    })
    rows2 = eerpm.build_matrix(project_root)
    row = rows2["qualification_signoff_engine"]
    assert row.verdict == eerpm.PROVEN
    assert any(e.get("reason") == "SIGNOFF_GATE_REFUSED" for e in row.invocation_evidence)


def test_blackboard_topic_refresh_proves_blackboard_engine_with_disclosed_caveat(project_root):
    store = _store(project_root)
    store.event({
        "ts": "2026-09-16T00:00:00Z", "stage": "COVERAGE",
        "event": "BLACKBOARD_TOPIC_REFRESH", "topic": "coverage_state",
        "action": "REFRESHER_RAISED",
    })
    rows = eerpm.build_matrix(project_root)
    row = rows["blackboard_evidence_engine"]
    assert row.verdict == eerpm.PROVEN
    assert row.caveat  # a real, non-empty disclosed limit, not silently PASS-and-forget


def test_run_id_scoping_matches_read_loop_telemetry_semantics(project_root):
    store = _store(project_root)
    store.event({"ts": "t1", "stage": "RE_AUDIT", "event": "ROOT_CAUSE_CONFIDENCE_SCORED",
                 "run_id": "loop:A"})
    store.event({"ts": "t2", "stage": "SIGNOFF", "event": "SIGNOFF_BUNDLE_EXPORTED",
                 "run_id": "loop:B"})
    rows_a = eerpm.build_matrix(project_root, run_id="loop:A")
    assert rows_a["autonomous_inference_engine"].verdict == eerpm.PROVEN
    assert rows_a["qualification_signoff_engine"].verdict == eerpm.NOT_PROVEN

    rows_b = eerpm.build_matrix(project_root, run_id="loop:B")
    assert rows_b["autonomous_inference_engine"].verdict == eerpm.NOT_PROVEN
    assert rows_b["qualification_signoff_engine"].verdict == eerpm.PROVEN


def test_no_runtime_signal_source_engines_report_defined_implemented_wired_true(project_root):
    """These 3 engines are real, wired, called-on-the-production-path modules
    -- the gap is only that no events.jsonl producer exists for them yet.
    Defined/Implemented/Wired must stay True; only Invoked/Verdict reflect
    the missing producer."""
    rows = eerpm.build_matrix(project_root)
    for engine_id in ("multi_agent_orchestrator", "route_skill_resolver",
                      "plan_execute_react_engine"):
        row = rows[engine_id]
        assert row.defined is True
        assert row.implemented is True
        assert row.wired is True
        assert row.invoked is False
        assert row.verdict == eerpm.NO_RUNTIME_SIGNAL_SOURCE
        assert row.gap_note  # a real, non-empty disclosed reason


def test_five_columns_are_honestly_not_available(project_root):
    rows = eerpm.build_matrix(project_root)
    for row in rows.values():
        assert row.artifact_ids == eerpm.NOT_AVAILABLE
        assert row.consumer_ids == eerpm.NOT_AVAILABLE
        assert row.decision_impact == eerpm.NOT_AVAILABLE
        assert row.outcome_verified == eerpm.NOT_AVAILABLE
        assert row.regression_ids == eerpm.NOT_AVAILABLE


def test_to_dict_uses_section_342_field_names(project_root):
    rows = eerpm.build_matrix(project_root)
    d = rows["autonomous_inference_engine"].to_dict()
    for key in ("EngineId", "Defined", "Implemented", "Wired", "Trigger",
                "Invoked", "InvocationEvidence", "ArtifactIds", "ConsumerIds",
                "DecisionImpact", "OutcomeVerified", "RegressionIds",
                "Verdict", "EvidenceRefs"):
        assert key in d


def test_render_matrix_text_and_execute_verb(project_root):
    code, text = eerpm.execute_verb(project_root, "show")
    assert code == 2  # not all 8 PROVEN against an empty log -- honest failure
    assert "EightEngineRuntimeProofMatrix_PASS = False" in text
    assert "Autonomous Inference Engine" in text

    code2, payload = eerpm.execute_verb(project_root, "matrix")
    assert payload["EightEngineRuntimeProofMatrix_PASS"] is False
    assert len(payload["rows"]) == 8

    code3, payload3 = eerpm.execute_verb(project_root, "bogus")
    assert code3 == 1
    assert payload3["error"] == "UNKNOWN_VERB"
