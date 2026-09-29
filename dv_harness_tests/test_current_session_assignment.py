"""Anti-drift regression tests for the CURRENT_SESSION_EXECUTOR activation
mechanism: a real, persisted, atomically-claimable Canonical execution
assignment that lets a genuinely separate /loop wakeup -- never a human
typing continue -- discover and claim work `dispatch_next_action()`
resolved to `BACKEND_RESOLVED`/`CURRENT_SESSION_EXECUTOR`.

Real live motivation (M7-V1-CHATGPT-ARCHITECTURE-REVIEW-002, third
corrected result, RESULT_SHA256=d681587f...): dispatch_next_action()
correctly reported BACKEND_RESOLVED, but nothing let a /loop wakeup
discover and claim that resolved work -- only a human manually reading
the report and doing it by hand. Independently re-verified before writing
this module: the review's own CG2-1/CG2-2 findings ("no production caller
of dispatch_next_action") were themselves STALE -- an artifact of an
incomplete INPUT_EVIDENCE_REFS list (result_ingestion.py, which contains
the real caller, was never included), not a real current code gap; this
is why _build_remediation_objective() mandates independent re-verification
before any change, and every test here treats a "finding" as a prior
claim, never ambient truth."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import dv_harness.agent_execution_backend as aeb
import dv_harness.execution_contract as ec
import dv_harness.model_handoff_workflow as wf
import dv_harness.result_ingestion as ri
from dv_harness.model_handoff import build_handoff
from dv_harness.model_result import ModelResultV1, to_markdown
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


def _export_and_consume_fail(repo: Path, task_id: str = "T-1", findings=("f1",)) -> None:
    h = build_handoff(repo, task_id=task_id, task_type="review-route", target_model="codex", project_id="P",
                      objective="review",
                      scope=TaskBoundary(task_id=task_id, allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)
    expected = repo / ".dv-harness/model_handoffs" / task_id / "RESULT_V1.md"
    result = ModelResultV1(
        result_version="1.0", task_id=task_id, producer_model="codex", task_type="review-route",
        result_status="FAIL", claims=["c"], findings=list(findings),
        evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"],
        recommended_actions=["fix f1"])
    expected.write_text(to_markdown(result), encoding="utf-8")
    outcome = wf.import_result(repo, task_id, expected)
    assert outcome.state == wf.STATE_RESULT_CONSUMED, outcome.parse_error


# =========== 1: BACKEND_RESOLVED does not equal EXECUTED

def test_backend_resolved_does_not_equal_executed(repo):
    assert ec.DISPATCH_BACKEND_RESOLVED != ec.DISPATCH_EXECUTED
    _export_and_consume_fail(repo)
    outcome = ec.dispatch_next_action(repo, "T-1")
    assert outcome.dispatch_status == ec.DISPATCH_BACKEND_RESOLVED
    assert outcome.dispatch_status != ec.DISPATCH_EXECUTED
    # An assignment being CREATED is also never conflated with EXECUTED.
    assignment = ec.read_execution_assignment(repo, "T-1")
    assert assignment.claim_state == ec.ASSIGNMENT_READY
    assert assignment.claim_state != ec.ASSIGNMENT_EXECUTION_COMPLETED


# =========== 2: CURRENT_SESSION_EXECUTOR resolution creates a claimable assignment

def test_current_session_executor_resolution_creates_a_claimable_assignment(repo):
    _export_and_consume_fail(repo)
    rec = ec.read_next_action(repo, "T-1")
    assert rec["next_action"] == "AUTO_REMEDIATE_CONFIRMED_FINDINGS"

    outcome = ec.dispatch_next_action(repo, "T-1")
    assert outcome.detail["selected_backend"] == aeb.CURRENT_SESSION_EXECUTOR
    assert "assignment_id" in outcome.detail

    assignment = ec.read_execution_assignment(repo, "T-1")
    assert assignment is not None
    assert assignment.task_id == "T-1"
    assert assignment.next_action == "AUTO_REMEDIATE_CONFIRMED_FINDINGS"
    assert assignment.selected_backend == aeb.CURRENT_SESSION_EXECUTOR
    assert assignment.claim_state == ec.ASSIGNMENT_READY
    assert assignment.repo_root_matched is True
    # The real finding text is preserved verbatim, and re-verification is mandated.
    assert "f1" in assignment.agent_run_request["objective"]
    assert "independently re-verify" in assignment.agent_run_request["objective"].lower()


# =========== 3: a normal loop wakeup discovers eligible assigned work

def test_loop_wakeup_discovers_and_claims_eligible_work(repo):
    _export_and_consume_fail(repo)
    ec.dispatch_next_action(repo, "T-1")
    assert ec.read_execution_assignment(repo, "T-1").claim_state == ec.ASSIGNMENT_READY

    claimed = ec.loop_wakeup_check_and_claim(repo, claimant_id="loop-tick-1")
    assert claimed is not None
    assert claimed.task_id == "T-1"
    assert claimed.claim_state == ec.ASSIGNMENT_CLAIMED
    assert claimed.claimed_by == "loop-tick-1"
    assert claimed.lease_id is not None


# =========== 4: a wakeup with no assignment remains quiet

def test_wakeup_with_no_eligible_assignment_remains_quiet(repo):
    (repo / ".dv-harness").mkdir(exist_ok=True)
    result = ec.loop_wakeup_check_and_claim(repo, claimant_id="loop-tick-1")
    assert result is None
    assert ec.discover_eligible_current_session_assignments(repo) == []


# =========== 5: Human Transport/Authority gates never create executable assignments

def test_human_gates_never_create_executable_assignments(repo):
    h = build_handoff(repo, task_id="T-1", task_type="review-route", target_model="codex", project_id="P",
                      objective="o", scope=TaskBoundary(task_id="T-1", allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)
    ec.persist_next_action(repo, "T-1", ec.resolve_next_action("RE_REVIEW_HANDOFF_READY"))  # a real gate

    outcome = ec.dispatch_next_action(repo, "T-1")
    assert outcome.dispatch_status == ec.DISPATCH_GATE
    assert ec.read_execution_assignment(repo, "T-1") is None  # no assignment, no claim, no execution


# =========== 6: duplicate wakeups cannot double-claim

def test_duplicate_wakeups_cannot_double_claim(repo):
    _export_and_consume_fail(repo)
    ec.dispatch_next_action(repo, "T-1")

    first = ec.claim_execution_assignment(repo, "T-1", "loop-tick-1")
    assert first.claim_state == ec.ASSIGNMENT_CLAIMED
    with pytest.raises(ec.ExecutionAssignmentError) as exc:
        ec.claim_execution_assignment(repo, "T-1", "loop-tick-2")
    assert exc.value.reason == "NOT_READY"

    # A second real /loop wakeup finds nothing eligible either.
    assert ec.loop_wakeup_check_and_claim(repo, claimant_id="loop-tick-2") is None


# =========== 7: wrong repo identity fails closed

def test_wrong_repo_identity_fails_closed(repo, tmp_path):
    _export_and_consume_fail(repo)
    ec.dispatch_next_action(repo, "T-1")

    other = tmp_path / "not_the_same_repo"
    other.mkdir()
    _run(other, "init", "-q")
    _run(other, "config", "user.email", "t@example.com")
    _run(other, "config", "user.name", "T")
    (other / ".dv-harness" / "model_handoffs" / "T-1").mkdir(parents=True)
    # Copy the real assignment record into a DIFFERENT real repo -- its
    # own repo_root_identity now genuinely mismatches `other`.
    import shutil as _sh
    _sh.copy(repo / ".dv-harness/model_handoffs/T-1/execution_assignment.json",
             other / ".dv-harness/model_handoffs/T-1/execution_assignment.json")

    with pytest.raises(ec.ExecutionAssignmentError) as exc:
        ec.claim_execution_assignment(other, "T-1", "loop-tick-1")
    assert exc.value.reason == "REPO_IDENTITY_MISMATCH"


# =========== 8: stale runtime generation cannot claim new work

def test_stale_runtime_generation_cannot_claim(repo):
    # A real watcher generation exists BEFORE the assignment is created, so
    # runtime_generation_at_creation is genuinely recorded (1), not None.
    ri._atomic_write_json(ri._watcher_file(repo), {"runtime_generation": 1, "status": "ACTIVE"})
    _export_and_consume_fail(repo)
    ec.dispatch_next_action(repo, "T-1")
    assert ec.read_execution_assignment(repo, "T-1").runtime_generation_at_creation == 1
    # Simulate the watcher having since restarted to a newer generation.
    ri._atomic_write_json(ri._watcher_file(repo), {"runtime_generation": 99, "status": "ACTIVE"})

    with pytest.raises(ec.ExecutionAssignmentError) as exc:
        ec.claim_execution_assignment(repo, "T-1", "loop-tick-1")
    assert exc.value.reason == "STALE_RUNTIME_GENERATION"


# =========== 9: mutation lease remains enforced

def test_mutation_lease_remains_enforced_across_backends(repo):
    _export_and_consume_fail(repo)
    ec.dispatch_next_action(repo, "T-1")
    assignment = ec.read_execution_assignment(repo, "T-1")

    # A detached-worker-style holder takes the SAME Canonical Mutation
    # Lease first (simulating a real concurrent detached run).
    other_lease = aeb.acquire_mutation_lease(repo, "OTHER-TASK", "other-agent-run-id")
    assert other_lease.acquired

    with pytest.raises(ec.ExecutionAssignmentError) as exc:
        ec.claim_execution_assignment(repo, "T-1", "loop-tick-1")
    assert exc.value.reason == "MUTATION_LEASE_BUSY"

    aeb.release_mutation_lease(repo, other_lease.lease_id)
    claimed = ec.claim_execution_assignment(repo, "T-1", "loop-tick-1")  # now succeeds
    assert claimed.claim_state == ec.ASSIGNMENT_CLAIMED


# =========== 10: completion evidence returns to the Canonical workflow

def test_completion_evidence_returns_to_the_canonical_workflow(repo):
    _export_and_consume_fail(repo)
    ec.dispatch_next_action(repo, "T-1")
    ec.claim_execution_assignment(repo, "T-1", "loop-tick-1")
    ec.mark_execution_assignment_executing(repo, "T-1")

    outcome = aeb.AgentRunResult(
        agent_run_id="run-1", task_id="T-1", action_id="A:T-1:AUTO_REMEDIATE_CONFIRMED_FINDINGS",
        run_status=aeb.RUN_STATUS_PASS, start_head="abc", end_head="def",
        files_changed=("dv_harness/module_a.py",), tests_run=("test_x",),
        regression_results="12 passed", gaps_fixed=("f1",),
    ).to_dict()
    completed = ec.complete_execution_assignment(repo, "T-1", outcome, success=True)
    assert completed.claim_state == ec.ASSIGNMENT_EXECUTION_COMPLETED
    assert completed.execution_outcome["run_status"] == aeb.RUN_STATUS_PASS

    # The lease was released.
    assert aeb.lease_state(repo)["state"] != "HELD"
    # The Canonical next_action loop was closed, not left stale.
    rec = ec.read_next_action(repo, "T-1")
    assert rec["next_action"] == f"EXECUTED:{ec.ASSIGNMENT_EXECUTION_COMPLETED}"
    assert rec["auto_actionable"] is False


# =========== 11: no terminal injection mechanism exists

def test_no_terminal_injection_mechanism_exists():
    """A static, structural proof, not merely a promise: the module this
    activation mechanism lives in contains none of the forbidden
    terminal-keystroke-injection primitives (dispatch section 2's own
    explicit prohibition list) as actual invocable code -- real call/
    import syntax, not the module's own prose disclosing that it does NOT
    use them (which legitimately names them by word)."""
    import ast
    tree = ast.parse(Path(ec.__file__).read_text(encoding="utf-8"), filename=ec.__file__)
    forbidden_calls = ("sendkeys", "sendinput", "keybd_event")
    forbidden_modules = ("pyautogui", "pyperclip", "win32clipboard", "win32com.client", "win32api", "ctypes.windll")
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")).lower()
            if name in forbidden_calls:
                hits.append(f"call:{name}")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [getattr(node, "module", None)] + [a.name for a in node.names]
            for n in names:
                if n and any(n.lower().startswith(m) for m in forbidden_modules):
                    hits.append(f"import:{n}")
    assert hits == [], f"forbidden terminal-injection primitive(s) found as real code: {hits}"
