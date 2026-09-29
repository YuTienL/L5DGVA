"""L5DGVA V14 section 374 ("Runtime Telemetry / Audit"): tests for
`dv_harness/eight_engine_telemetry_rollup.py`.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim, with one
factual docstring correction (see `test_per_signal_counts_distinguish_multiple_signal_names`
below): canonical's `five_level_memory_engine` rule carries 5 signal names, not
Parent's 8 (see `eight_engine_runtime_proof_matrix.py`'s own adaptation docstring).
All 3 signal names this test actually asserts on are in canonical's retained 5, so
no assertion changed -- only the prose describing the fixture's own scope.

Distinct from `test_eight_engine_runtime_proof_matrix.py` (section 342's
binary PROVEN/NOT_PROVEN/NO_RUNTIME_SIGNAL_SOURCE verdict): this file proves
the CONTINUOUS rollup -- invocation counts, per-signal breakdown, distinct
run-id frequency, first/last timestamps -- computed over the same events.jsonl
window and the same section-339 engine-to-signal mapping.

Every event record below is a FIXTURE shaped like what `engine.py` really
emits (same event names/fields cited in
`eight_engine_runtime_proof_matrix.ENGINE_RULES[...].evidence_refs`), written
through the real `storage.StateStore.event()`.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import eight_engine_telemetry_rollup as rollup_mod
from dv_harness.storage import StateStore


@pytest.fixture()
def project_root():
    d = Path(tempfile.mkdtemp(prefix="eight_engine_rollup_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _store(root: Path) -> StateStore:
    return StateStore(root)


def test_empty_events_file_all_zero_or_not_available(project_root):
    rows = rollup_mod.build_rollup(project_root)
    assert len(rows) == 8
    for engine_id in ("multi_agent_orchestrator", "route_skill_resolver",
                      "plan_execute_react_engine"):
        row = rows[engine_id]
        assert row.has_signal_source is False
        assert row.invocation_count == rollup_mod.NOT_AVAILABLE
        assert row.per_signal_counts == rollup_mod.NOT_AVAILABLE
        assert row.distinct_run_ids == rollup_mod.NOT_AVAILABLE
    for engine_id in ("autonomous_inference_engine", "graph_orchestrator",
                      "blackboard_evidence_engine", "five_level_memory_engine",
                      "qualification_signoff_engine"):
        row = rows[engine_id]
        assert row.has_signal_source is True
        assert row.invocation_count == 0
        assert row.distinct_run_ids == []
        assert row.first_seen_ts is None
        assert row.last_seen_ts is None
    assert rollup_mod.rollup_pass(rows) is False


def test_repeated_events_increment_invocation_count(project_root):
    store = _store(project_root)
    for i in range(3):
        store.event({
            "ts": f"2026-09-16T00:0{i}:00Z", "stage": "RE_AUDIT",
            "event": "ROOT_CAUSE_CONFIDENCE_SCORED",
            "recomputed_confidence": {"level": "HIGH", "score": 5},
        })
    rows = rollup_mod.build_rollup(project_root)
    row = rows["autonomous_inference_engine"]
    assert row.invocation_count == 3
    assert row.per_signal_counts == {"ROOT_CAUSE_CONFIDENCE_SCORED": 3}
    assert row.first_seen_ts == "2026-09-16T00:00:00Z"
    assert row.last_seen_ts == "2026-09-16T00:02:00Z"


def test_per_signal_counts_distinguish_multiple_signal_names(project_root):
    """5-Level Memory Engine has 5 distinct signal names in canonical (8 in
    Parent, before this batch's disclosed 3-signal adaptation) -- prove the
    breakdown counts each independently, not just a flat total."""
    store = _store(project_root)
    store.event({"ts": "t1", "stage": "DEBUG", "event": "EXPERIENCE_KNOWLEDGE_PROMOTED",
                 "promotion": {"destination": "ENGINEERING_MEMORY"}})
    store.event({"ts": "t2", "stage": "DEBUG", "event": "EXPERIENCE_KNOWLEDGE_PROMOTED",
                 "promotion": {"destination": "ENGINEERING_MEMORY"}})
    store.event({"ts": "t3", "stage": "IMPLEMENT", "event": "VERIFIED_FIX_PROMOTED",
                 "promotion": {"destination": "ENGINEERING_MEMORY"}})
    rows = rollup_mod.build_rollup(project_root)
    row = rows["five_level_memory_engine"]
    assert row.invocation_count == 3
    assert row.per_signal_counts["EXPERIENCE_KNOWLEDGE_PROMOTED"] == 2
    assert row.per_signal_counts["VERIFIED_FIX_PROMOTED"] == 1
    assert row.per_signal_counts["PROJECT_TOPOLOGY_PROMOTED"] == 0


def test_distinct_run_ids_is_a_frequency_signal_not_a_raw_count(project_root):
    """3 matched events across only 2 distinct run_ids -- distinct_run_ids
    must report 2, a materially different claim than invocation_count's 3."""
    store = _store(project_root)
    store.event({"ts": "t1", "stage": "RE_AUDIT", "event": "ROOT_CAUSE_CONFIDENCE_SCORED",
                 "run_id": "loop:A"})
    store.event({"ts": "t2", "stage": "RE_AUDIT", "event": "ROOT_CAUSE_CONFIDENCE_SCORED",
                 "run_id": "loop:A"})
    store.event({"ts": "t3", "stage": "RE_AUDIT", "event": "ROOT_CAUSE_CONFIDENCE_SCORED",
                 "run_id": "loop:B"})
    rows = rollup_mod.build_rollup(project_root)
    row = rows["autonomous_inference_engine"]
    assert row.invocation_count == 3
    assert row.distinct_run_ids == ["loop:A", "loop:B"]


def test_run_id_scoping_matches_proof_matrix_semantics(project_root):
    store = _store(project_root)
    store.event({"ts": "t1", "stage": "RE_AUDIT", "event": "ROOT_CAUSE_CONFIDENCE_SCORED",
                 "run_id": "loop:A"})
    store.event({"ts": "t2", "stage": "SIGNOFF", "event": "SIGNOFF_BUNDLE_EXPORTED",
                 "run_id": "loop:B"})
    rows_a = rollup_mod.build_rollup(project_root, run_id="loop:A")
    assert rows_a["autonomous_inference_engine"].invocation_count == 1
    assert rows_a["qualification_signoff_engine"].invocation_count == 0

    rows_b = rollup_mod.build_rollup(project_root, run_id="loop:B")
    assert rows_b["autonomous_inference_engine"].invocation_count == 0
    assert rows_b["qualification_signoff_engine"].invocation_count == 1


def test_predicate_narrowed_signal_only_counts_matching_records(project_root):
    store = _store(project_root)
    store.event({"ts": "t1", "stage": "BUILD", "event": "LOOP_BLOCKED",
                 "reason": "SOME_OTHER_STOP_REASON"})
    store.event({"ts": "t2", "stage": "SIGNOFF", "event": "LOOP_BLOCKED",
                 "reason": "SIGNOFF_GATE_REFUSED"})
    rows = rollup_mod.build_rollup(project_root)
    row = rows["qualification_signoff_engine"]
    assert row.invocation_count == 1
    assert row.per_signal_counts["LOOP_BLOCKED"] == 1


def test_unrelated_event_never_inflates_a_different_engines_count(project_root):
    store = _store(project_root)
    store.event({"ts": "t1", "stage": "ANALYSIS_G1", "event": "RCA_EVIDENCE_FANOUT_DISPATCHED",
                 "branches": ["RTL_EVIDENCE"]})
    rows = rollup_mod.build_rollup(project_root)
    assert rows["graph_orchestrator"].invocation_count == 1
    assert rows["multi_agent_orchestrator"].has_signal_source is False
    assert rows["multi_agent_orchestrator"].invocation_count == rollup_mod.NOT_AVAILABLE


def test_all_eight_engines_present_no_more_no_fewer(project_root):
    rows = rollup_mod.build_rollup(project_root)
    assert {r for r in rows.keys()} == {
        "autonomous_inference_engine", "graph_orchestrator",
        "multi_agent_orchestrator", "route_skill_resolver",
        "plan_execute_react_engine", "blackboard_evidence_engine",
        "five_level_memory_engine", "qualification_signoff_engine",
    }


def test_to_dict_field_names(project_root):
    rows = rollup_mod.build_rollup(project_root)
    d = rows["autonomous_inference_engine"].to_dict()
    for key in ("EngineId", "EngineName", "HasSignalSource", "InvocationCount",
                "PerSignalCounts", "DistinctRunIds", "FirstSeenTs", "LastSeenTs",
                "GapNote"):
        assert key in d


def test_render_rollup_text_and_execute_verb(project_root):
    code, text = rollup_mod.execute_verb(project_root, "show")
    assert code == 2  # honest failure against an empty log, same as the proof matrix
    assert "EightEngineRuntimeTelemetryRollup_PASS = False" in text
    assert "Autonomous Inference Engine" in text

    code2, payload = rollup_mod.execute_verb(project_root, "rollup")
    assert payload["EightEngineRuntimeTelemetryRollup_PASS"] is False
    assert len(payload["rows"]) == 8

    code3, payload3 = rollup_mod.execute_verb(project_root, "bogus")
    assert code3 == 1
    assert payload3["error"] == "UNKNOWN_VERB"


def test_rollup_pass_requires_every_engine_to_have_fired(project_root):
    """Even if all 5 signal-bearing engines fire, rollup_pass stays False
    because 3 engines have no signal source at all -- the honest, disclosed
    current ceiling, same reasoning as eight_engine_runtime_proof_matrix's
    matrix_pass()."""
    store = _store(project_root)
    for event_name, extra in (
        ("ROOT_CAUSE_CONFIDENCE_SCORED", {}),
        ("LOOP_ACTION_SELECTED", {"route": "some_route"}),
        ("BLACKBOARD_TOPIC_REFRESH", {}),
        ("EXPERIENCE_KNOWLEDGE_PROMOTED", {"promotion": {"destination": "X"}}),
        ("QUALIFIED_CONCLUSION_BUILT", {}),
    ):
        store.event({"ts": "t", "stage": "X", "event": event_name, **extra})
    rows = rollup_mod.build_rollup(project_root)
    for engine_id in ("autonomous_inference_engine", "graph_orchestrator",
                      "blackboard_evidence_engine", "five_level_memory_engine",
                      "qualification_signoff_engine"):
        assert rows[engine_id].invocation_count >= 1
    assert rollup_mod.rollup_pass(rows) is False
