"""Regression tests for `execution_contract.evaluate_canonical_task_
completion()` -- the real producer for `EVALUATE_CANONICAL_TASK_
COMPLETION`, a named `NEXT_ACTION_TABLE` target (`RESULT_CONSUMED_CLEAN`'s
own route) with no implementation anywhere in the codebase until a real
M7-V1-CODEX-REVIEW-007 consumed cleanly (PASS, zero findings) and exposed
the gap live (P3 CLOSE THE LOOP / P4 NO CAPABILITY ISLANDS)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import dv_harness.execution_contract as ec
import dv_harness.model_handoff_workflow as wf
from dv_harness.model_handoff import build_handoff
from dv_harness.model_result import ModelResultV1, to_markdown as r_to
from dv_harness.question_queue import QuestionQueueStore
from dv_harness.task_boundary_conformance import TaskBoundary

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")


def _run(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    w = tmp_path / "work"
    w.mkdir()
    _run(w, "init", "-q")
    _run(w, "config", "user.email", "t@example.com")
    _run(w, "config", "user.name", "T")
    (w / "dv_harness").mkdir()
    (w / "dv_harness" / "module_a.py").write_text("# x\n", encoding="utf-8")
    _run(w, "add", "-A")
    _run(w, "commit", "-q", "-m", "i")
    return w


def _export_and_consume(repo: Path, task_id: str, *, target_model: str = "codex",
                        result_status: str = "PASS", findings=()) -> None:
    h = build_handoff(repo, task_id=task_id, task_type="review-route", target_model=target_model,
                      project_id="P", objective="o",
                      scope=TaskBoundary(task_id=task_id, allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)
    expected = repo / ".dv-harness/model_handoffs" / task_id / "RESULT_V1.md"
    result = ModelResultV1(
        result_version="1.0", task_id=task_id, producer_model=target_model, task_type="review-route",
        result_status=result_status, claims=["c"], findings=list(findings),
        evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"])
    expected.write_text(r_to(result), encoding="utf-8")
    outcome = wf.import_result(repo, task_id, expected)
    assert outcome.state == wf.STATE_RESULT_CONSUMED, outcome.parse_error


def test_clean_pass_is_task_complete_and_branch_ready(repo):
    _export_and_consume(repo, "T-1", result_status="PASS", findings=())
    ev = ec.evaluate_canonical_task_completion(repo, "T-1")
    assert ev.task_completion == ec.TASK_COMPLETE
    assert ev.branch_closure_readiness == ec.BRANCH_READY_FOR_CLOSURE


def test_fail_with_findings_is_not_task_complete_and_needs_remediation(repo):
    _export_and_consume(repo, "T-1", result_status="FAIL", findings=["a real finding"])
    ev = ec.evaluate_canonical_task_completion(repo, "T-1")
    assert ev.task_completion == ec.TASK_FAILED_REMEDIATION_PENDING
    assert ev.branch_closure_readiness == ec.BRANCH_NOT_READY
    assert ev.next_approved_gate == ec.GATE_REMEDIATE_FINDINGS


def test_a_single_clean_task_pass_never_claims_m7_program_complete(repo):
    """The dispatch's own explicit requirement: completion evaluation must
    not equate one task's PASS with the whole program's completion."""
    _export_and_consume(repo, "T-1", result_status="PASS", findings=())
    ev = ec.evaluate_canonical_task_completion(repo, "T-1")
    assert "M7_NOT_COMPLETE" in ev.program_completion
    assert ev.program_completion != "M7_COMPLETE"


def test_branch_ready_with_no_chatgpt_round_trip_recommends_generating_the_chatgpt_handoff(repo):
    _export_and_consume(repo, "T-1", result_status="PASS", findings=())
    ev = ec.evaluate_canonical_task_completion(repo, "T-1")
    assert ev.next_approved_gate == ec.GATE_GENERATE_CHATGPT_HANDOFF
    assert "CHATGPT_ROUND_TRIP_NOT_CONSUMED" in ev.program_completion


def test_branch_ready_with_a_real_consumed_chatgpt_round_trip_advances_past_that_gate(repo):
    """A completed Codex branch can advance to the next approved M7 gate
    once the ChatGPT round trip is genuinely, evidently consumed -- never
    inferred, only from a real second consumed task."""
    _export_and_consume(repo, "T-1", result_status="PASS", findings=())
    _export_and_consume(repo, "T-CHATGPT", target_model="chatgpt", result_status="PASS", findings=())
    ev = ec.evaluate_canonical_task_completion(repo, "T-1")
    assert ev.next_approved_gate == ec.GATE_M7_FULL_CLOSURE_REVIEW_REQUIRED
    assert ev.program_completion != ec.TASK_COMPLETE  # never a bare task-completion string reused as program status


def test_an_outstanding_human_authority_item_is_preserved_not_dropped(repo):
    _export_and_consume(repo, "T-1", result_status="PASS", findings=())
    store = QuestionQueueStore(repo)
    q = store.add_question(
        domain="env", question="risk-acceptance question", context_path="doc.md",
        options=["A", "B"], recommendation="A", assumption_if_unanswered="B",
        question_key="test:outstanding-item",
        context={"affects_pass_fail_verdict": True},
    )
    assert q["status"] == "OPEN"

    ev = ec.evaluate_canonical_task_completion(repo, "T-1")
    assert q["id"] in ev.outstanding_human_authority_items
    # Preserved, but NOT force-closed and NOT blocking the branch's own readiness.
    assert ev.branch_closure_readiness == ec.BRANCH_READY_FOR_CLOSURE
    assert ev.next_approved_gate == ec.GATE_GENERATE_CHATGPT_HANDOFF


def test_raises_for_a_task_that_has_not_actually_been_consumed(repo):
    h = build_handoff(repo, task_id="T-PENDING", task_type="review-route", target_model="codex",
                      project_id="P", objective="o",
                      scope=TaskBoundary(task_id="T-PENDING", allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)
    with pytest.raises(ValueError):
        ec.evaluate_canonical_task_completion(repo, "T-PENDING")


def test_persisted_evaluation_round_trips(repo):
    _export_and_consume(repo, "T-1", result_status="PASS", findings=())
    ev = ec.evaluate_canonical_task_completion(repo, "T-1")
    path = ec.persist_completion_evaluation(repo, "T-1", ev)
    assert path.is_file()
    back = ec.read_persisted_completion_evaluation(repo, "T-1")
    assert back == ev.to_dict()


def test_record_completion_evaluation_next_action_closes_the_source_task_loop(repo):
    """P3 CLOSE THE LOOP: found live -- the completion evaluation itself
    was persisted, but the SOURCE task's own next_action.json was left
    stale, still showing EVALUATE_CANONICAL_TASK_COMPLETION as
    auto_actionable=true even after it had genuinely been executed and
    acted on. This must never happen again."""
    _export_and_consume(repo, "T-1", result_status="PASS", findings=())
    before = ec.read_next_action(repo, "T-1")
    assert before["next_action"] == "EVALUATE_CANONICAL_TASK_COMPLETION"
    assert before["auto_actionable"] is True

    ev = ec.evaluate_canonical_task_completion(repo, "T-1")
    ec.persist_completion_evaluation(repo, "T-1", ev)
    ec.record_completion_evaluation_next_action(repo, "T-1", ev, downstream_task_id="T-CHATGPT")

    after = ec.read_next_action(repo, "T-1")
    assert after["next_action"] != "EVALUATE_CANONICAL_TASK_COMPLETION"
    assert after["next_action"].startswith("EXECUTED:")
    assert after["auto_actionable"] is False  # a terminal record, not a fresh pending action
    assert "T-CHATGPT" in after["next_action_reason"]


def test_no_generic_continue_needed_the_transport_gate_after_generating_a_handoff_is_a_real_stop(repo):
    """Proves the full real chain: EVALUATE_CANONICAL_TASK_COMPLETION's own
    recommendation, once acted on (a real ChatGPT handoff exported), feeds
    the EXISTING signals_from_model_handoff_state()/can_i_stop() Can-I-Stop
    Gate to a real, named HUMAN_TRANSPORT_REQUIRED stop -- never a generic
    "continue?" -- reusing the existing gate, not a second one."""
    _export_and_consume(repo, "T-1", result_status="PASS", findings=())
    ev = ec.evaluate_canonical_task_completion(repo, "T-1")
    assert ev.next_approved_gate == ec.GATE_GENERATE_CHATGPT_HANDOFF

    # Act on the recommendation via the real production mechanism.
    h = build_handoff(repo, task_id="T-CHATGPT", task_type="architecture-governance-review",
                      target_model="chatgpt", project_id="P", objective="review architecture",
                      scope=TaskBoundary(task_id="T-CHATGPT", allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)

    signals = ec.signals_from_model_handoff_state(repo, "T-CHATGPT")
    decision = ec.can_i_stop(signals)
    assert decision.should_continue is False
    assert decision.stop_reason == "HUMAN_TRANSPORT_REQUIRED"
    assert decision.human_action_required == "YES"
    assert signals.target_model == "chatgpt"
