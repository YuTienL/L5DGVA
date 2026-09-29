"""Human-facing pre-action low-confidence checkpoint (gap-close 2026-09-07,
item id no-human-facing-preaction-low-confidence-checkpoint).

Confirmed-real gap before this closure: `dv_harness.inference.build_deeper_
investigation_signal()` was, by its own docstring, "AGENT-FACING (never
human-facing)", and its ONE real consumer -- `engine.DVHarness._record_
agent_escalation_signal()` -- only ever appended it to a Blackboard topic
("agent_escalation_signals") that grep confirmed zero graph nodes'
`blackboard_read` ever names and `dashboard.py` never reads.

Two halves, matching the new module's own scope:
  1. `dv_harness.low_confidence_human_checkpoint` -- pure-function /
     QuestionQueueStore-integration tests, proving a REAL Tier-3 blocking
     question is filed (carrying the full rendered reasoning chain) only
     for a genuine LOW confidence result, is idempotent across retries of
     the same investigation, and never fabricates a checkpoint for MEDIUM/
     HIGH confidence or malformed input.
  2. `dv_harness.engine.DVHarness._file_low_confidence_human_checkpoint()` --
     the one real production caller, wired into run_stage()'s existing
     per-attempt `_react_step_inference()` call site (directly beside
     `_record_agent_escalation_signal()`), proven against the REAL
     production path re-using the exact same ARCH_CALIBRATION fixture
     shapes `dv_harness_tests/test_agent_self_escalation.py` and
     `dv_harness_tests/test_react_inference_wiring.py` already established.
"""
import json
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness.adapters.base import AgentResult
from dv_harness.inference import build_deeper_investigation_signal, score_confidence
from dv_harness.low_confidence_human_checkpoint import (
    CHECKPOINT_CONTEXT,
    DOMAIN,
    OPTION_INVESTIGATE_FURTHER,
    OPTION_PROCEED,
    build_low_confidence_checkpoint_question_key,
    file_low_confidence_checkpoint,
    render_reasoning_chain,
)
from dv_harness.question_queue import QuestionQueueStore, TIER3_CANNOT_ASSUME

ROOT = Path(__file__).resolve().parents[1]


# --- render_reasoning_chain(): pure-function tests --------------------------

def test_render_reasoning_chain_contains_stage_confidence_and_gap():
    low = score_confidence(0, False, 0, 0)
    signal = build_deeper_investigation_signal(low, stage="RE_AUDIT",
                                                context_path="evidence/path.json",
                                                gap=["counter_evidence", "independent_sources"])
    chain = render_reasoning_chain(signal)
    assert "Stage: RE_AUDIT" in chain
    assert "Evidence path: evidence/path.json" in chain
    assert "Confidence: LOW" in chain
    assert "counter_evidence" in chain and "independent_sources" in chain
    assert signal["reason"] in chain


def test_render_reasoning_chain_reports_no_gap_honestly_rather_than_omitting_the_line():
    low = score_confidence(0, False, 0, 0)
    signal = build_deeper_investigation_signal(low, stage="RE_AUDIT")
    chain = render_reasoning_chain(signal)
    assert "Gap: none reported by identify_gap()" in chain


# --- build_low_confidence_checkpoint_question_key(): stability ---------------

def test_question_key_stable_across_identical_calls():
    k1 = build_low_confidence_checkpoint_question_key("RE_AUDIT", "path.json", ["a", "b"])
    k2 = build_low_confidence_checkpoint_question_key("RE_AUDIT", "path.json", ["b", "a"])
    assert k1 == k2  # gap order must not matter -- sorted internally


def test_question_key_differs_for_a_different_gap():
    k1 = build_low_confidence_checkpoint_question_key("RE_AUDIT", "path.json", ["a"])
    k2 = build_low_confidence_checkpoint_question_key("RE_AUDIT", "path.json", ["b"])
    assert k1 != k2


# --- file_low_confidence_checkpoint(): the real filing path -----------------

def _low_step_inference(gap=None):
    low = score_confidence(0, False, 0, 0)
    assert low["level"] == "LOW"  # grounding: this really is a LOW result
    return {"confidence_detail": low, "gap": gap or ["counter_evidence"]}


def test_no_checkpoint_filed_for_medium_or_high_confidence():
    """The required negative control: a real MEDIUM and a real HIGH
    confidence_detail must never file a checkpoint question."""
    tmp = Path(tempfile.mkdtemp())
    try:
        store = QuestionQueueStore(tmp)
        medium = score_confidence(2, False, 0, 0)
        assert medium["level"] == "MEDIUM"
        assert file_low_confidence_checkpoint(
            store, "RE_AUDIT", {"confidence_detail": medium}) is None

        high = score_confidence(3, True, 0, 2)
        assert high["level"] == "HIGH"
        assert file_low_confidence_checkpoint(
            store, "RE_AUDIT", {"confidence_detail": high}) is None

        assert store.list_questions() == []
    finally:
        shutil.rmtree(tmp)


@pytest.mark.parametrize("bad_step_inference", [
    None, {}, {"confidence_detail": None}, {"confidence_detail": "LOW"}, {"confidence_detail": []},
])
def test_no_checkpoint_filed_for_malformed_step_inference(bad_step_inference):
    tmp = Path(tempfile.mkdtemp())
    try:
        store = QuestionQueueStore(tmp)
        assert file_low_confidence_checkpoint(store, "RE_AUDIT", bad_step_inference) is None
        assert store.list_questions() == []
    finally:
        shutil.rmtree(tmp)


def test_low_confidence_files_a_real_tier3_blocking_question_with_the_reasoning_chain():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = QuestionQueueStore(tmp)
        record = file_low_confidence_checkpoint(
            store, "RE_AUDIT", _low_step_inference(),
            context_path=".dv-harness/react/RE_AUDIT/iteration_001.json")
        assert record is not None
        assert record["tier"] == TIER3_CANNOT_ASSUME
        assert record["blocking"] is True
        assert record["status"] == "OPEN"
        assert record["domain"] == DOMAIN
        labels = {opt["label"] for opt in record["options"]}
        assert labels == {OPTION_PROCEED, OPTION_INVESTIGATE_FURTHER}
        assert record["recommendation"] == OPTION_INVESTIGATE_FURTHER
        # The full reasoning chain really landed in the question text a human reads.
        assert "Confidence: LOW" in record["question"]
        assert "counter_evidence" in record["question"]
        assert "RE_AUDIT" in record["question"]

        # And it is really persisted -- a second, independent read of the
        # store confirms it, never trusted only from the in-memory return.
        reread = QuestionQueueStore(tmp)
        persisted = reread.list_questions()
        assert len(persisted) == 1
        assert persisted[0]["id"] == record["id"]
    finally:
        shutil.rmtree(tmp)


def test_repeated_calls_for_the_same_investigation_are_idempotent():
    """A stage retry re-computing the identical LOW-confidence signal must
    never mint a second, duplicate blocking question -- mirroring
    source_authority.escalate_conflict()'s own dedup-before-add discipline."""
    tmp = Path(tempfile.mkdtemp())
    try:
        store = QuestionQueueStore(tmp)
        step = _low_step_inference()
        first = file_low_confidence_checkpoint(store, "RE_AUDIT", step, context_path="p.json")
        second = file_low_confidence_checkpoint(store, "RE_AUDIT", step, context_path="p.json")
        assert first["id"] == second["id"]
        assert len(store.list_questions()) == 1
    finally:
        shutil.rmtree(tmp)


def test_a_different_gap_on_the_same_stage_files_a_genuinely_new_question():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = QuestionQueueStore(tmp)
        first = file_low_confidence_checkpoint(
            store, "RE_AUDIT", _low_step_inference(gap=["a"]), context_path="p.json")
        second = file_low_confidence_checkpoint(
            store, "RE_AUDIT", _low_step_inference(gap=["b"]), context_path="p.json")
        assert first["id"] != second["id"]
        assert len(store.list_questions()) == 2
    finally:
        shutil.rmtree(tmp)


def test_once_a_human_answers_a_later_identical_signal_self_resolves_at_tier1():
    """A human answering the filed checkpoint is a real recorded decision;
    QuestionQueueStore.add_question()'s own classify_tier() rule (a human
    answer on file always wins over the hard trigger) means a LATER call
    for the identical investigation must self-resolve rather than
    re-escalate -- proving this checkpoint really rides the project's one
    real ask-a-human protocol rather than a parallel one."""
    tmp = Path(tempfile.mkdtemp())
    try:
        store = QuestionQueueStore(tmp)
        step = _low_step_inference()
        opened = file_low_confidence_checkpoint(store, "RE_AUDIT", step, context_path="p.json")
        assert opened["status"] == "OPEN"

        store.answer_question(opened["id"], answer=OPTION_PROCEED,
                               basis="reviewed the reasoning chain; safe to proceed",
                               decided_by="a.human")

        # A brand-new store handle to prove the state is really persisted, not
        # cached in-process.
        store2 = QuestionQueueStore(tmp)
        again = file_low_confidence_checkpoint(store2, "RE_AUDIT", step, context_path="p.json")
        assert again["id"] == opened["id"]
        # dedup-before-add returns the EXISTING (now-answered) record verbatim.
        assert again["status"] == "ANSWERED"
        assert again["answer"] == OPTION_PROCEED
        assert len(store2.list_questions()) == 1
    finally:
        shutil.rmtree(tmp)


def test_checkpoint_context_asserts_the_pass_fail_hard_trigger_honestly():
    assert CHECKPOINT_CONTEXT == {"affects_pass_fail_verdict": True}


def test_accepts_a_project_root_path_as_well_as_an_already_built_store():
    tmp = Path(tempfile.mkdtemp())
    try:
        record = file_low_confidence_checkpoint(tmp, "RE_AUDIT", _low_step_inference())
        assert record is not None
        assert record["tier"] == TIER3_CANNOT_ASSUME
    finally:
        shutil.rmtree(tmp)


# --- engine.py wiring: direct unit test of the best-effort contract ---------

def test_engine_checkpoint_method_is_best_effort_never_raises_on_malformed_input():
    tmp = Path(tempfile.mkdtemp())
    try:
        from dv_harness.engine import DVHarness

        h = DVHarness(tmp)
        assert h._file_low_confidence_human_checkpoint("SOME_STAGE", {}) is None
        assert h._file_low_confidence_human_checkpoint(
            "SOME_STAGE", {"confidence_detail": "not_a_dict"}) is None
        assert h._file_low_confidence_human_checkpoint("SOME_STAGE", None) is None

        medium = score_confidence(2, False, 0, 0)
        assert medium["level"] == "MEDIUM"
        assert h._file_low_confidence_human_checkpoint(
            "SOME_STAGE", {"confidence_detail": medium}) is None

        low = score_confidence(0, False, 0, 0)
        result = h._file_low_confidence_human_checkpoint(
            "SOME_STAGE", {"confidence_detail": low, "gap": ["g1"]})
        assert result is not None
        assert result["tier"] == TIER3_CANNOT_ASSUME
        assert "g1" in result["question"]

        # A real, distinct audit event landed too.
        events = [json.loads(l) for l in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        recorded = [e for e in events if e.get("event") == "LOW_CONFIDENCE_HUMAN_CHECKPOINT_FILED"]
        assert len(recorded) == 1
        assert recorded[0]["stage"] == "SOME_STAGE"
        assert recorded[0]["question_id"] == result["id"]
    finally:
        shutil.rmtree(tmp)


# --- engine.py wiring: the real production path (run_stage()) --------------

def _mk_smoke_project():
    """Identical fixture shape to test_agent_self_escalation.py's own
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
# three -- the SAME real fixture test_agent_self_escalation.py's own
# test_real_low_confidence_stage_attempt_records_a_real_escalation_signal
# already proves scores a real LOW confidence.
_ONLY_CALIBRATION_GATE_SUPPLIED = (
    '```dv-harness-evidence:architecture_calibration_gate\n'
    '{"architecture_before": {"a": 1}, "architecture_after": {"a": 1}}\n```\n'
)


class _RequestEvidenceFakeAdapter:
    """Verbatim copy of test_agent_self_escalation.py's own fake adapter."""

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
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


def test_real_low_confidence_stage_attempt_files_a_real_human_checkpoint():
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
        assert rec["confidence"] == "LOW"  # grounding: really scored LOW

        # The real agent-facing signal still fired too (untouched sibling).
        assert len(h.blackboard.read_agent_escalation_signals()["items"]) == 1

        # And now: a REAL, human-facing, blocking question queue record.
        store = QuestionQueueStore(tmp)
        questions = store.list_questions(blocking=True)
        assert len(questions) == 1
        q = questions[0]
        assert q["tier"] == TIER3_CANNOT_ASSUME
        assert q["status"] == "OPEN"
        assert "ARCH_CALIBRATION" in q["question"]
        assert "Confidence: LOW" in q["question"]
        assert q["context_path"] == ".dv-harness/react/ARCH_CALIBRATION/iteration_001.json"
        assert (tmp / q["context_path"]).exists()

        events = [json.loads(l) for l in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        recorded = [e for e in events if e.get("event") == "LOW_CONFIDENCE_HUMAN_CHECKPOINT_FILED"]
        assert len(recorded) == 1
        assert recorded[0]["question_id"] == q["id"]
    finally:
        shutil.rmtree(tmp)


def test_real_medium_confidence_stage_attempt_files_no_human_checkpoint():
    """The required negative control on the real production path: the SAME
    stage, but every configured gate supplied a block (one failing on
    content) -- test_agent_self_escalation.py's own equivalent test already
    proves this scores a real MEDIUM, not LOW. No checkpoint question must
    be filed."""
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

        # No question_queue tree at all was ever created by this run.
        assert not (tmp / ".dv-harness" / "question_queue").exists()

        events_path = tmp / ".dv-harness" / "events.jsonl"
        if events_path.exists():
            events = [json.loads(l) for l in events_path.read_text(encoding="utf-8").splitlines()]
            assert not any(e.get("event") == "LOW_CONFIDENCE_HUMAN_CHECKPOINT_FILED" for e in events)
    finally:
        shutil.rmtree(tmp)
