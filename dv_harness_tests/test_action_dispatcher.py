"""Regression tests for `execution_contract.dispatch_next_action()` and
its real executors -- the missing Action Dispatcher edge ChatGPT REVIEW-001
(M7-V1-CHATGPT-ARCHITECTURE-REVIEW-001, CG-1/CG-2) found live:
NEXT_ACTION_TABLE resolves and persists an action, but nothing in
production code consumed it and routed to a real executor."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import dv_harness.execution_contract as ec
import dv_harness.model_handoff_workflow as wf
import dv_harness.agent_execution_backend as aeb
from dv_harness.model_handoff import build_handoff
from dv_harness.model_result import ModelResultV1, to_markdown as r_to
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


def _export_and_consume(repo: Path, task_id: str, *, result_status: str = "PASS", findings=()) -> None:
    h = build_handoff(repo, task_id=task_id, task_type="review-route", target_model="codex",
                      project_id="P", objective="o",
                      scope=TaskBoundary(task_id=task_id, allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)
    expected = repo / ".dv-harness/model_handoffs" / task_id / "RESULT_V1.md"
    result = ModelResultV1(
        result_version="1.0", task_id=task_id, producer_model="codex", task_type="review-route",
        result_status=result_status, claims=["c"], findings=list(findings),
        evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"])
    expected.write_text(r_to(result), encoding="utf-8")
    outcome = wf.import_result(repo, task_id, expected)
    assert outcome.state == wf.STATE_RESULT_CONSUMED, outcome.parse_error


# ================================================================ dispatch_next_action

def test_evaluate_canonical_task_completion_cannot_remain_resolved_but_not_executed(repo):
    """The exact real defect this dispatch found: RESULT_CONSUMED_CLEAN ->
    EVALUATE_CANONICAL_TASK_COMPLETION persisted but nothing executed it."""
    _export_and_consume(repo, "T-1", result_status="PASS", findings=())
    before = ec.read_next_action(repo, "T-1")
    assert before["next_action"] == "EVALUATE_CANONICAL_TASK_COMPLETION"

    outcome = ec.dispatch_next_action(repo, "T-1")
    assert outcome.dispatch_status == ec.DISPATCH_EXECUTED
    assert outcome.detail["task_completion"] == ec.TASK_COMPLETE
    # Real, persisted evidence -- not just a return value.
    assert ec.read_persisted_completion_evaluation(repo, "T-1") == outcome.detail


def test_auto_remediate_confirmed_findings_resolves_a_real_backend_not_nothing(repo):
    """AUTO_REMEDIATE_CONFIRMED_FINDINGS inherently requires code-
    authorship judgment (never a pure function without a second,
    competing code-fixing engine) -- but dispatch must never leave it
    silently unexecuted. It resolves the real execution backend instead,
    giving resolve_execution_backend() its first genuine production
    caller (ChatGPT REVIEW-001 CG-2's own specific finding)."""
    _export_and_consume(repo, "T-1", result_status="FAIL", findings=["a real finding"])
    rec = ec.read_next_action(repo, "T-1")
    assert rec["next_action"] == "AUTO_REMEDIATE_CONFIRMED_FINDINGS"

    outcome = ec.dispatch_next_action(repo, "T-1")
    assert outcome.dispatch_status == ec.DISPATCH_BACKEND_RESOLVED
    assert outcome.detail["requested_backend"] == aeb.DETACHED_CLAUDE_WORKER
    assert outcome.detail["selected_backend"] == aeb.CURRENT_SESSION_EXECUTOR
    assert outcome.detail["backend_block_reason"] == aeb.NATIVE_CONTROLLED_CLAUDE_WORKER_STATUS


def test_auto_generate_correction_request_handoff_is_actually_executed(repo):
    expected = repo / ".dv-harness/model_handoffs/T-1/RESULT_V1.md"
    h = build_handoff(repo, task_id="T-1", task_type="review-route", target_model="codex", project_id="P",
                      objective="o", scope=TaskBoundary(task_id="T-1", allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)
    bad = "D:" + chr(92) + "DV" + chr(92) + "single" + chr(92) + "backslash"
    malformed = (
        "# L5DGVA_MODEL_RESULT_V1\n\n<!-- L5DGVA_VALUE_ENCODING=escaped-v1 -->\n\n"
        "## RESULT_VERSION\n1.0\n\n## TASK_ID\nT-1\n\n## PRODUCER_MODEL\ncodex\n\n"
        "## TASK_TYPE\nreview-route\n\n## RESULT_STATUS\nFAIL\n\n## CLAIMS\n- CLAIM: c\n\n"
        f"## FINDINGS\n- FINDING: path is {bad}\n\n## EVIDENCE_REFS\n- dv_harness/module_a.py:1\n\n"
        "## COUNTER_EVIDENCE\n(none)\n\n## UNKNOWN_ITEMS\n(none)\n\n"
        "## FILES_REFERENCED\n- dv_harness/module_a.py\n\n## VALIDATION_PERFORMED\n- v\n\n"
        "## RECOMMENDED_ACTIONS\n(none)\n\n## HUMAN_DECISIONS_REQUIRED\n(none)\n\n"
        "## SCOPE_EXCEPTIONS\n(none)\n\n## RETURNED_ARTIFACTS\n- .dv-harness/model_handoffs/T-1/RESULT_V1.md\n"
    )
    expected.write_text(malformed, encoding="utf-8")
    wf.import_result(repo, "T-1", expected)
    assert ec.read_next_action(repo, "T-1")["next_action"] == "AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF"

    outcome = ec.dispatch_next_action(repo, "T-1")
    assert outcome.dispatch_status == ec.DISPATCH_EXECUTED
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT


def test_a_real_stop_gate_is_reported_as_a_gate_never_silently_executed(repo):
    h = build_handoff(repo, task_id="T-1", task_type="review-route", target_model="codex", project_id="P",
                      objective="o", scope=TaskBoundary(task_id="T-1", allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)
    assert ec.read_next_action(repo, "T-1") is None  # export_handoff doesn't persist a next_action record itself
    ec.persist_next_action(repo, "T-1", ec.resolve_next_action("RE_REVIEW_HANDOFF_READY"))

    outcome = ec.dispatch_next_action(repo, "T-1")
    assert outcome.dispatch_status == ec.DISPATCH_GATE
    assert outcome.detail["stop_reason"] == "HUMAN_TRANSPORT_REQUIRED"


def test_an_action_needing_caller_context_is_reported_honestly_not_silently_skipped(repo):
    _export_and_consume(repo, "T-1", result_status="PASS", findings=())
    ec.persist_next_action(repo, "T-1", ec.resolve_next_action("RESULT_REJECTED_SCOPE_VIOLATION"))

    outcome = ec.dispatch_next_action(repo, "T-1")
    assert outcome.dispatch_status == ec.DISPATCH_REQUIRES_CALLER_CONTEXT


def test_dispatch_raises_for_a_task_with_no_persisted_next_action(repo):
    with pytest.raises(ValueError):
        ec.dispatch_next_action(repo, "NO-SUCH-TASK")


def test_no_human_scheduler_intervention_required_for_a_machine_actionable_path(repo):
    """Human Scheduler intervention is not required: dispatch_next_action()
    itself needs no human input to resolve either a real EXECUTED outcome
    or a real BACKEND_RESOLVED outcome."""
    _export_and_consume(repo, "T-1", result_status="PASS", findings=())
    outcome = ec.dispatch_next_action(repo, "T-1")  # no human involved in this call at all
    assert outcome.dispatch_status == ec.DISPATCH_EXECUTED


# ================================================================ classify_scope_violation / diagnose_validation_failure

class _FakeValidation:
    def __init__(self, **kw):
        self.task_id_validated = kw.get("task_id_validated", True)
        self.producer_validated = kw.get("producer_validated", True)
        self.task_type_validated = kw.get("task_type_validated", True)
        self.scope_validated = kw.get("scope_validated", True)
        self.schema_validated = kw.get("schema_validated", True)
        self.evidence_validated = kw.get("evidence_validated", True)
        self.governance_validated = kw.get("governance_validated", True)
        self.governance_validation_status = kw.get("governance_validation_status", "NOT_APPLICABLE")
        self.findings = kw.get("findings", [])
        self.scope_violations = kw.get("scope_violations", [])


def test_classify_scope_violation_extracts_the_real_already_computed_violations():
    validation = _FakeValidation(scope_violations=[
        {"field": "EVIDENCE_REFS", "path": "dv_harness/forbidden.py", "classification": "FORBIDDEN"}])
    result = ec.classify_scope_violation(validation)
    assert result["classification"] == "SCOPE_VIOLATION"
    assert result["violation_count"] == 1
    assert result["violations"][0]["path"] == "dv_harness/forbidden.py"


def test_classify_scope_violation_reports_none_when_there_are_none():
    result = ec.classify_scope_violation(_FakeValidation())
    assert result["classification"] == "NO_SCOPE_VIOLATION"
    assert result["violation_count"] == 0


def test_diagnose_validation_failure_extracts_the_real_failed_checks():
    validation = _FakeValidation(schema_validated=False, evidence_validated=False,
                                 findings=["FABRICATED_EVIDENCE_PATH"])
    result = ec.diagnose_validation_failure(validation)
    assert set(result["failed_checks"]) == {"schema_validated", "evidence_validated"}
    assert "FABRICATED_EVIDENCE_PATH" in result["findings"]


# ================================================================ build_retry_agent_run_request

def _agent_request(repo: Path, **kw) -> aeb.AgentRunRequest:
    return aeb.build_agent_run_request(
        repo, task_id="T-1", parent_workflow_id="T-1", action_id="A:T-1", action_type="REMEDIATE",
        role="implementation", objective="o",
        scope=TaskBoundary(task_id="T-1", allowed_path_prefixes=("dv_harness/module_a.py",)),
        retry_policy_max_attempts=kw.pop("retry_policy_max_attempts", 2), **kw,
    )


def test_retry_agent_run_request_increments_attempt_and_carries_scope_forward(repo):
    original = _agent_request(repo)
    retry = aeb.build_retry_agent_run_request(original, retry_reason="AGENT_RUN_FAILED_RETRY_ELIGIBLE")
    assert retry.attempt_number == original.attempt_number + 1
    assert retry.previous_attempt == original.agent_run_id
    assert retry.retry_reason == "AGENT_RUN_FAILED_RETRY_ELIGIBLE"
    assert retry.agent_run_id != original.agent_run_id
    assert retry.task_scope == original.task_scope
    assert retry.tool_execution_profile == original.tool_execution_profile


def test_retry_agent_run_request_refuses_once_policy_is_exhausted(repo):
    original = _agent_request(repo, retry_policy_max_attempts=1, attempt_number=1)
    with pytest.raises(aeb.AgentExecutionError) as exc:
        aeb.build_retry_agent_run_request(original, retry_reason="AGENT_RUN_TIMEOUT_RETRY_ELIGIBLE")
    assert exc.value.reason == "RETRY_POLICY_EXHAUSTED"


# ================================================================ Codex/ChatGPT results cannot directly gain process authority

# ================================================================ Duplicate HumanGate reconciliation

def test_a_result_citing_an_existing_question_id_reuses_it_not_a_duplicate(repo):
    """The exact real defect ChatGPT REVIEW-001 CG-5 exposed: a result's
    own HUMAN_DECISIONS_REQUIRED text cited an already-tracked question by
    id (Q-ENV-57D420FA); the pre-fix consumer filed a second, new,
    lower-tier question anyway. Reproduced here with a real question_queue
    entry and a real result citing it."""
    from dv_harness.question_queue import QuestionQueueStore

    store = QuestionQueueStore(repo)
    existing = store.add_question(
        domain="env", question="Accept risk X or block?", context_path="doc.md",
        options=["ACCEPT", "BLOCK"], recommendation="ACCEPT", assumption_if_unanswered="BLOCK",
        question_key="test:pre-existing-tier3-decision",
        context={"affects_pass_fail_verdict": True},
    )
    assert existing["status"] == "OPEN"

    _export_and_consume(repo, "T-CITES", result_status="PASS", findings=())
    # Manually construct the exact citing scenario: a result declaring
    # HUMAN_DECISIONS_REQUIRED text that quotes the existing question id.
    from dv_harness.model_handoff import build_handoff
    from dv_harness.task_boundary_conformance import TaskBoundary as _TB
    handoff = wf._load_handoff(repo, "T-CITES")
    result = ModelResultV1(
        result_version="1.0", task_id="T-CITES", producer_model="codex", task_type="review-route",
        result_status="HUMAN_DECISION_REQUIRED", claims=["c"], findings=[],
        evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"],
        human_decisions_required=[f"{existing['id']}: Project owner must choose ACCEPT or BLOCK."])

    question_id = wf._consume_result(repo, handoff, result, "R.md")
    assert question_id == existing["id"]  # reused, not a new duplicate

    all_questions = store.list_questions()
    matching = [q for q in all_questions if q["question_key"] == "test:pre-existing-tier3-decision"]
    assert len(matching) == 1  # still exactly one record for the real decision -- no duplicate filed
    # The real decision itself is untouched -- never auto-answered.
    refreshed = [q for q in all_questions if q["id"] == existing["id"]][0]
    assert refreshed["status"] == "OPEN"
    assert refreshed["answer"] is None


def test_codex_or_chatgpt_result_content_never_directly_launches_a_process(repo, monkeypatch):
    """A result's own content (however it phrases NEXT_ACTION_HINT/
    findings) can never cause import_result() itself to spawn a worker --
    Canonical ingestion only ever persists state and a next-action
    recommendation; L5DGVA (the orchestrating session, via
    dispatch_next_action()) remains the one that decides whether/how to
    act on it."""
    calls = {"launch": 0}
    monkeypatch.setattr(aeb, "launch_worker", lambda *a, **kw: calls.__setitem__("launch", calls["launch"] + 1))
    _export_and_consume(repo, "T-1", result_status="FAIL", findings=["f"])
    assert calls["launch"] == 0  # import_result() itself never calls launch_worker()
