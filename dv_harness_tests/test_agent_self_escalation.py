"""Agent self-escalation to more compute (mid-task low-confidence signal)
(2026-09-07, agent_self_escalation).

Two halves, matching the item's own scope:

  1. dv_harness.inference.build_deeper_investigation_signal() -- a pure
     function reusing score_confidence()'s exact result shape, returning a
     real, structured "deeper investigation needed" record ONLY when the
     already-computed confidence level is LOW, and None otherwise (a MEDIUM/
     HIGH assessment genuinely does not warrant one -- the required negative
     control).
  2. dv_harness.engine.DVHarness._record_agent_escalation_signal() -- the one
     real production caller, wired into run_stage()'s existing per-attempt
     _react_step_inference() call. Proven against the REAL production path
     (a real run_stage() driving the real shipped main_graph.json with real
     gate scripts), reusing the exact same ARCH_CALIBRATION fixture shapes
     dv_harness_tests/test_react_inference_wiring.py already established and
     already proved score LOW (missing-evidence-block scenario) and MEDIUM
     (all-blocks-supplied-one-fails scenario) -- so this suite does not
     re-derive a new confidence scenario, it reuses the two the sibling
     suite already grounded.

This is deliberately NOT a question_queue.py test: nothing here files,
answers, or reads a question, and the whole point of the vocabulary-
disjointness assertion below is that the two mechanisms never share a token.
"""
import json
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness.adapters.base import AgentResult
from dv_harness.gates import effective_stage_gates
from dv_harness.inference import (
    CONFIDENCE_LEVELS,
    DEEPER_INVESTIGATION_NEEDED_SIGNAL,
    ESCALATION_SIGNAL_DISCLOSURE,
    assert_escalation_signal_vocabulary_disjoint,
    build_deeper_investigation_signal,
    score_confidence,
)

ROOT = Path(__file__).resolve().parents[1]


# --- inference.build_deeper_investigation_signal(): pure-function tests -----

def test_low_confidence_produces_a_real_signal():
    result = score_confidence(independent_sources_count=0, evidence_refs_verified=False,
                               counter_evidence_count=0, multi_agent_consensus_count=0)
    assert result["level"] == "LOW"

    signal = build_deeper_investigation_signal(result, stage="RE_AUDIT", gap=["some_gate"])
    assert signal is not None
    assert signal["signal"] == DEEPER_INVESTIGATION_NEEDED_SIGNAL
    assert signal["stage"] == "RE_AUDIT"
    assert signal["confidence_detail"] == result
    assert signal["gap"] == ["some_gate"]
    assert signal["context_path"] is None
    assert signal["disclosure"] == ESCALATION_SIGNAL_DISCLOSURE
    assert "reason" in signal and isinstance(signal["reason"], str) and signal["reason"]


def test_medium_and_high_confidence_never_produce_a_signal():
    """The required negative control: a real MEDIUM and a real HIGH
    score_confidence() result must never be escalated -- the function must
    return None, not a fabricated low-priority signal."""
    medium = score_confidence(independent_sources_count=2, evidence_refs_verified=False,
                               counter_evidence_count=0, multi_agent_consensus_count=0)
    assert medium["level"] == "MEDIUM"
    assert build_deeper_investigation_signal(medium, stage="RE_AUDIT") is None

    high = score_confidence(independent_sources_count=3, evidence_refs_verified=True,
                             counter_evidence_count=0, multi_agent_consensus_count=2)
    assert high["level"] == "HIGH"
    assert build_deeper_investigation_signal(high, stage="RE_AUDIT") is None


def test_gap_defaults_to_empty_list_when_omitted_or_falsy():
    low = score_confidence(0, False, 0, 0)
    assert build_deeper_investigation_signal(low, stage="X")["gap"] == []
    assert build_deeper_investigation_signal(low, stage="X", gap=[])["gap"] == []
    assert build_deeper_investigation_signal(low, stage="X", gap=None)["gap"] == []


def test_context_path_and_custom_reason_are_carried_through_verbatim():
    low = score_confidence(0, False, 0, 0)
    signal = build_deeper_investigation_signal(
        low, stage="RE_AUDIT", context_path=".dv-harness/react/RE_AUDIT/iteration_001.json",
        reason="a custom, caller-supplied reason")
    assert signal["context_path"] == ".dv-harness/react/RE_AUDIT/iteration_001.json"
    assert signal["reason"] == "a custom, caller-supplied reason"


def test_signal_never_recomputes_score_confidence_only_reads_its_result():
    """The returned confidence_detail is the EXACT dict object handed in --
    proving this function reuses score_confidence()'s own result rather than
    calling score_confidence() a second time (which could disagree)."""
    low = score_confidence(0, False, 0, 0)
    signal = build_deeper_investigation_signal(low, stage="RE_AUDIT")
    assert signal["confidence_detail"] is low


@pytest.mark.parametrize("bad_result", [
    None, "LOW", {}, {"score": 0}, {"level": "URGENT"}, {"level": "low"},
])
def test_invalid_confidence_result_raises(bad_result):
    with pytest.raises(ValueError):
        build_deeper_investigation_signal(bad_result, stage="RE_AUDIT")


@pytest.mark.parametrize("bad_stage", [None, "", "   ", 123])
def test_invalid_stage_raises(bad_stage):
    low = score_confidence(0, False, 0, 0)
    with pytest.raises(ValueError):
        build_deeper_investigation_signal(low, stage=bad_stage)


def test_invalid_gap_raises():
    low = score_confidence(0, False, 0, 0)
    with pytest.raises(ValueError):
        build_deeper_investigation_signal(low, stage="X", gap="not_a_list")
    with pytest.raises(ValueError):
        build_deeper_investigation_signal(low, stage="X", gap=[1, 2])


def test_invalid_context_path_and_reason_types_raise():
    low = score_confidence(0, False, 0, 0)
    with pytest.raises(ValueError):
        build_deeper_investigation_signal(low, stage="X", context_path=123)
    with pytest.raises(ValueError):
        build_deeper_investigation_signal(low, stage="X", reason=123)


# --- vocabulary disjointness: proven, not merely claimed ---------------------

def test_escalation_signal_vocabulary_is_disjoint_from_confidence_levels_by_construction():
    assert DEEPER_INVESTIGATION_NEEDED_SIGNAL not in CONFIDENCE_LEVELS
    # Running the assertion again must be a genuine no-op: it already ran once
    # at import time (module load), and calling it a second time must not
    # raise on the real, unmodified module state.
    assert_escalation_signal_vocabulary_disjoint()


def test_vocabulary_guard_has_real_detection_power(monkeypatch):
    """A monkeypatch-induced collision must actually trip the guard -- proving
    it is a real check, not a function that always passes."""
    import dv_harness.inference as inf
    monkeypatch.setattr(inf, "DEEPER_INVESTIGATION_NEEDED_SIGNAL", "LOW")
    with pytest.raises(AssertionError):
        inf.assert_escalation_signal_vocabulary_disjoint()

    monkeypatch.setattr(inf, "DEEPER_INVESTIGATION_NEEDED_SIGNAL", "CANNOT_ASSUME")
    with pytest.raises(AssertionError):
        inf.assert_escalation_signal_vocabulary_disjoint()


# --- engine.py wiring: the real production path ------------------------------

def _mk_smoke_project():
    """Identical fixture shape to test_react_inference_wiring.py's own
    _mk_smoke_project() -- a fresh temp project with the REAL main_graph.json,
    real .claude/agents and real tools/verification_flow gate scripts, so the
    gates genuinely subprocess-run."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        (ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    shutil.copytree(ROOT / ".claude" / "agents", tmp / ".claude" / "agents")
    shutil.copytree(ROOT / "tools", tmp / "tools")
    return tmp


# ARCH_CALIBRATION's real gates, with a block supplied for exactly ONE of the
# three -- the SAME real fixture test_react_inference_wiring.py's own
# test_run_stage_react_reasoning_step_record_carries_real_inference_output
# already proves scores a real LOW confidence.
_ONLY_CALIBRATION_GATE_SUPPLIED = (
    '```dv-harness-evidence:architecture_calibration_gate\n'
    '{"architecture_before": {"a": 1}, "architecture_after": {"a": 1}}\n```\n'
)


class _RequestEvidenceFakeAdapter:
    """Verbatim copy of test_react_inference_wiring.py's own fake adapter:
    supplies only one of ARCH_CALIBRATION's three evidence blocks on the
    first call, then picks whatever REQUEST_EVIDENCE option the real menu
    offers."""

    def __init__(self):
        self.prompts = []

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        self.prompts.append(prompt)
        if "dv-harness-react-decision" not in prompt:
            return AgentResult(ok=True, text=_ONLY_CALIBRATION_GATE_SUPPLIED,
                               raw={}, session_id="s1")
        m = re.search(r"option_id=(REQUEST_EVIDENCE:\S+)", prompt)
        chosen = m.group(1) if m else "CONVERGE_TERMINATE"
        return AgentResult(ok=True, text=(
            '```dv-harness-react-decision\n'
            + json.dumps({"chosen_option_id": chosen,
                          "conclusion": "Two configured gates received no evidence block.",
                          "params": {}}) + '\n```'
        ), raw={}, session_id="s2")


def test_real_low_confidence_stage_attempt_records_a_real_escalation_signal():
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness

        h = DVHarness(tmp)
        h.adapter = _RequestEvidenceFakeAdapter()
        h.cfg["policy"]["inner_react_max_adapter_calls"] = 1
        h.set_stage("ARCH_CALIBRATION")
        h.run_stage("calibrate architecture")

        rec = json.loads(
            (tmp / ".dv-harness" / "memory" / "working"
             / "WM-REACT-ARCH_CALIBRATION-001.json").read_text(encoding="utf-8"))
        assert rec["confidence"] == "LOW"  # grounding: the real attempt really scored LOW

        registry = h.blackboard.read_agent_escalation_signals()
        assert len(registry["items"]) == 1
        signal = registry["items"][0]
        assert signal["signal"] == DEEPER_INVESTIGATION_NEEDED_SIGNAL
        assert signal["stage"] == "ARCH_CALIBRATION"
        assert signal["sequence_number"] == 1
        assert signal["gap"] == rec["gap"]
        assert signal["confidence_detail"] == rec["confidence_detail"]
        assert signal["confidence_detail"]["level"] == "LOW"
        assert signal["context_path"] == ".dv-harness/react/ARCH_CALIBRATION/iteration_001.json"
        # The pointer names a file that really exists.
        assert (tmp / signal["context_path"]).exists()
        assert signal["disclosure"] == ESCALATION_SIGNAL_DISCLOSURE

        # A real, distinct audit event landed too -- never a second question,
        # never anything question_queue-shaped.
        events = [json.loads(l) for l in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        recorded = [e for e in events if e.get("event") == "AGENT_ESCALATION_SIGNAL_RECORDED"]
        assert len(recorded) == 1
        assert recorded[0]["stage"] == "ARCH_CALIBRATION"
        assert recorded[0]["sequence_number"] == 1

        # _record_agent_escalation_signal() itself is still not question_
        # queue-shaped (it never imports or calls question_queue.py -- see
        # its own docstring). A question store now exists in this run for a
        # different, real reason: the sibling human-facing checkpoint wired
        # at the SAME run_stage() call site (gap-close 2026-09-07,
        # no-human-facing-preaction-low-confidence-checkpoint) files a real
        # Tier-3 blocking question over this exact same LOW confidence
        # result -- see dv_harness_tests/test_low_confidence_human_
        # checkpoint.py for that mechanism's own dedicated coverage.
        assert (tmp / ".dv-harness" / "question_queue").exists()
        from dv_harness.question_queue import QuestionQueueStore, TIER3_CANNOT_ASSUME
        checkpoint_questions = QuestionQueueStore(tmp).list_questions(blocking=True)
        assert len(checkpoint_questions) == 1
        assert checkpoint_questions[0]["tier"] == TIER3_CANNOT_ASSUME
    finally:
        shutil.rmtree(tmp)


def test_real_medium_confidence_stage_attempt_records_no_escalation_signal():
    """The required negative control on the real production path: the SAME
    stage, the SAME PARTIAL status, but every configured gate supplied a
    block (one failing on content) -- test_react_inference_wiring.py's own
    test_react_reasoning_step_confidence_really_tracks_the_evidence_not_the_
    status already proves this scores a real MEDIUM, not LOW. No escalation
    signal must be recorded."""
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness
        from dv_harness.gates import evaluate_stage_evidence

        all_blocks_one_fails = (
            _ONLY_CALIBRATION_GATE_SUPPLIED
            + '```dv-harness-evidence:architecture_calibration_conflict_gate\n'
              '{"conflicts": []}\n```\n'
            + '```dv-harness-evidence:vip_api_drift_gate\n'
              '{"current_vip_version": "2.0", "qualified_vip_version": "1.0", '
              '"api_diff_analyzed": false}\n```\n'
        )
        assert evaluate_stage_evidence(tmp, "ARCH_CALIBRATION", all_blocks_one_fails)[0] == "GATE_FAIL"

        class FakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                if "dv-harness-react-decision" not in prompt:
                    return AgentResult(ok=True, text=all_blocks_one_fails, raw={},
                                       session_id="s1")
                m = re.search(r"option_id=(REROUTE:\S+)", prompt)
                chosen = m.group(1) if m else "CONVERGE_TERMINATE"
                return AgentResult(ok=True, text=(
                    '```dv-harness-react-decision\n'
                    + json.dumps({"chosen_option_id": chosen,
                                  "conclusion": "vip_api_drift_gate failed on content.",
                                  "params": {}}) + '\n```'
                ), raw={}, session_id="s2")

        h = DVHarness(tmp)
        h.adapter = FakeAdapter()
        h.set_stage("ARCH_CALIBRATION")
        h.run_stage("calibrate architecture")

        rec = json.loads(
            (tmp / ".dv-harness" / "memory" / "working"
             / "WM-REACT-ARCH_CALIBRATION-001.json").read_text(encoding="utf-8"))
        assert rec["confidence"] == "MEDIUM"  # grounding: really scored MEDIUM, not LOW

        registry = h.blackboard.read_agent_escalation_signals()
        assert registry["items"] == []

        events_path = tmp / ".dv-harness" / "events.jsonl"
        if events_path.exists():
            events = [json.loads(l) for l in events_path.read_text(encoding="utf-8").splitlines()]
            assert not any(e.get("event") == "AGENT_ESCALATION_SIGNAL_RECORDED" for e in events)
    finally:
        shutil.rmtree(tmp)


def test_multiple_low_confidence_attempts_accumulate_with_stable_sequence_numbers():
    """A best-effort registry (Blackboard.append_agent_escalation_signal())
    unit test, exercised directly rather than through a second full run_stage()
    -- proving the accumulate-not-overwrite discipline the append_debug_
    loop_round() sibling method already established."""
    tmp = Path(tempfile.mkdtemp())
    try:
        from dv_harness.blackboard import Blackboard

        bb = Blackboard(tmp)
        low = score_confidence(0, False, 0, 0)
        first = build_deeper_investigation_signal(low, stage="RE_AUDIT")
        second = build_deeper_investigation_signal(low, stage="FAILURE_RECOVERY")

        bb.append_agent_escalation_signal(first, source="RE_AUDIT")
        bb.append_agent_escalation_signal(second, source="FAILURE_RECOVERY")

        registry = bb.read_agent_escalation_signals()
        assert [item["sequence_number"] for item in registry["items"]] == [1, 2]
        assert [item["stage"] for item in registry["items"]] == ["RE_AUDIT", "FAILURE_RECOVERY"]
    finally:
        shutil.rmtree(tmp)


def test_record_agent_escalation_signal_is_best_effort_never_raises_on_malformed_input():
    """Direct unit test of DVHarness._record_agent_escalation_signal(), never
    going through a full run_stage() -- proving the best-effort contract the
    method's own docstring promises: malformed/absent confidence_detail must
    return None quietly, never raise, mirroring every sibling `_record_*`
    method in engine.py."""
    tmp = Path(tempfile.mkdtemp())
    try:
        from dv_harness.engine import DVHarness

        h = DVHarness(tmp)
        assert h._record_agent_escalation_signal("SOME_STAGE", {}) is None
        assert h._record_agent_escalation_signal("SOME_STAGE", {"confidence_detail": "not_a_dict"}) is None
        assert h._record_agent_escalation_signal("SOME_STAGE", None) is None

        # And a real MEDIUM/HIGH confidence_detail records nothing either.
        medium = score_confidence(2, False, 0, 0)
        assert medium["level"] == "MEDIUM"
        assert h._record_agent_escalation_signal("SOME_STAGE", {"confidence_detail": medium}) is None
        assert h.blackboard.read_agent_escalation_signals()["items"] == []

        # A genuine LOW confidence_detail, called directly, records for real.
        low = score_confidence(0, False, 0, 0)
        result = h._record_agent_escalation_signal("SOME_STAGE", {"confidence_detail": low, "gap": ["g1"]})
        assert result is not None
        assert result["items"][0]["stage"] == "SOME_STAGE"
        assert result["items"][0]["gap"] == ["g1"]
    finally:
        shutil.rmtree(tmp)


def test_graph_node_react_default_keeps_this_wiring_live():
    """Regression guard, matching test_react_inference_wiring.py's own
    equivalent: this call site only ever fires for a node whose react flag is
    on, and every real shipped graph node has it on by default."""
    from dv_harness.graph import GraphDefinition

    graph = GraphDefinition.load(ROOT / ".dv-harness" / "graph" / "main_graph.json")
    assert graph.nodes["ARCH_CALIBRATION"].react is True
