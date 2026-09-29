"""Anti-drift regression tests for the real root edge two independent live
ChatGPT round trips found (M7-V1-CHATGPT-ARCHITECTURE-REVIEW-001's CG-2 and,
after that fix, REVIEW-002's own live counterexample): `execution_contract.
dispatch_next_action()` existed and was fully tested, but had ZERO real
production callers -- a persisted `auto_actionable=true`/`next_action_owner=
L5DGVA` action was resolved and never actually executed by anything except a
human/interactive session manually invoking it.

The fix wires `result_ingestion.resume_after_import()` -- the real,
pre-existing, always-called auto-resume function -- as `dispatch_next_
action()`'s first genuine production caller. Every test here drives that
real function (`resume_after_import()`, or the full `poll_once`/`_settle`
import path that calls it), never a manual `dispatch_next_action()` call
standing in for it, except where a test is explicitly about the dispatcher's
own idempotency/gate behavior in isolation."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import dv_harness.execution_contract as ec
import dv_harness.model_handoff_workflow as wf
import dv_harness.result_ingestion as ri
import dv_harness.agent_execution_backend as aeb
from dv_harness.model_handoff import build_handoff
from dv_harness.model_result import ModelResultV1, to_markdown
from dv_harness.task_boundary_conformance import TaskBoundary

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")

POLICY = ri.IngestionPolicy(quiet_seconds=2.0, min_observations=2, max_import_attempts=3)


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


def _export(repo: Path, task_id: str = "T-1") -> Path:
    h = build_handoff(repo, task_id=task_id, task_type="review-route", target_model="codex", project_id="P",
                      objective="review",
                      scope=TaskBoundary(task_id=task_id, allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)
    return repo / ri._expected_path(repo, task_id).relative_to(repo)


def _place_clean_pass(repo: Path, task_id: str = "T-1") -> None:
    result = ModelResultV1(
        result_version="1.0", task_id=task_id, producer_model="codex", task_type="review-route",
        result_status="PASS", claims=["c"], findings=[],
        evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"])
    (repo / ri._expected_path(repo, task_id).relative_to(repo)).write_text(to_markdown(result), encoding="utf-8")


def _place_fail_with_findings(repo: Path, task_id: str = "T-1") -> None:
    result = ModelResultV1(
        result_version="1.0", task_id=task_id, producer_model="codex", task_type="review-route",
        result_status="FAIL", claims=["c"], findings=["a real finding"],
        evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"])
    (repo / ri._expected_path(repo, task_id).relative_to(repo)).write_text(to_markdown(result), encoding="utf-8")


def _place_malformed(repo: Path, task_id: str = "T-1") -> None:
    """A real `MALFORMED_LIST_ITEM` (a wrapped/continuation line under a
    list section) -- the exact class of rejection REVIEW-002 hit live,
    distinct from REVIEW-007's `MALFORMED_ESCAPE`."""
    malformed = (
        "# L5DGVA_MODEL_RESULT_V1\n\n<!-- L5DGVA_VALUE_ENCODING=escaped-v1 -->\n\n"
        f"## RESULT_VERSION\n1.0\n\n## TASK_ID\n{task_id}\n\n## PRODUCER_MODEL\ncodex\n\n"
        "## TASK_TYPE\nreview-route\n\n## RESULT_STATUS\nFAIL\n\n## CLAIMS\n- CLAIM: c\n\n"
        "## FINDINGS\n- FINDING: a\nthis wrapped continuation line is ambiguous\n\n"
        "## EVIDENCE_REFS\n- dv_harness/module_a.py:1\n\n"
        "## COUNTER_EVIDENCE\n(none)\n\n## UNKNOWN_ITEMS\n(none)\n\n"
        "## FILES_REFERENCED\n- dv_harness/module_a.py\n\n## VALIDATION_PERFORMED\n- v\n\n"
        "## RECOMMENDED_ACTIONS\n(none)\n\n## HUMAN_DECISIONS_REQUIRED\n(none)\n\n"
        "## SCOPE_EXCEPTIONS\n(none)\n\n## RETURNED_ARTIFACTS\n"
        f"- .dv-harness/model_handoffs/{task_id}/RESULT_V1.md\n"
    )
    (repo / ri._expected_path(repo, task_id).relative_to(repo)).write_text(malformed, encoding="utf-8")


def _dispatched_events(repo: Path, task_id: str = "T-1"):
    return [e for e in ri.read_events(repo, task_id) if e["event"] == "ACTION_DISPATCHED"]


# =========== 1: auto-resume dispatches an auto-actionable L5DGVA-owned action

def test_resume_after_import_dispatches_an_auto_actionable_l5dgva_owned_action(repo):
    """Drives ONLY the real production path -- export, place a clean PASS
    result, import it (which calls resume_after_import() internally,
    exactly like the real AUTO watcher does) -- never a manual dispatch_
    next_action() call standing in for it."""
    _export(repo)
    _place_clean_pass(repo)
    expected = repo / ri._expected_path(repo, "T-1").relative_to(repo)
    ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL")
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED

    dispatched = _dispatched_events(repo)
    assert len(dispatched) == 1
    assert dispatched[0]["dispatch_status"] == ec.DISPATCH_EXECUTED
    # Real, persisted evidence the action's own executor actually ran --
    # not merely that an event claims it did.
    assert ec.read_persisted_completion_evaluation(repo, "T-1") is not None


# =========== 2: a persisted Next Action cannot remain AUTO_RUNNING forever
# =========== merely because no interactive session invoked the dispatcher

def test_next_action_does_not_remain_pending_forever_after_real_auto_resume(repo):
    _export(repo)
    _place_clean_pass(repo)
    expected = repo / ri._expected_path(repo, "T-1").relative_to(repo)
    ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL")

    rec = ec.read_next_action(repo, "T-1")
    # Before this fix this record stayed EVALUATE_CANONICAL_TASK_COMPLETION/
    # auto_actionable=true forever -- indistinguishable from "never executed"
    # to any reader of next_action.json alone.
    assert rec["next_action"].startswith("EXECUTED:")
    assert rec["auto_actionable"] is False


# =========== 3: AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF executes through
# =========== the production dispatcher (via resume_after_import())

def test_auto_generate_correction_request_handoff_executes_through_production_dispatcher(repo):
    _export(repo)
    _place_malformed(repo)
    expected = repo / ri._expected_path(repo, "T-1").relative_to(repo)
    ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL")

    # Required real transition, achieved with ZERO manual dispatch_next_
    # action() call and ZERO human/interactive-session involvement:
    # RESULT_REJECTED_MALFORMED -> AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF
    # -> correction handoff generated -> WAITING_FOR_HUMAN_TRANSPORT.
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT
    handoff_md = (repo / ".dv-harness/model_handoffs/T-1/HANDOFF_V1.md").read_text(encoding="utf-8")
    assert "CORRECTION REQUIRED" in handoff_md
    assert "MALFORMED_LIST_ITEM" in handoff_md

    dispatched = _dispatched_events(repo)
    assert len(dispatched) == 1 and dispatched[0]["dispatch_status"] == ec.DISPATCH_EXECUTED

    # The action's own loop is closed too -- next_action.json reflects the
    # real outcome, never left showing the pre-dispatch pending record.
    rec = ec.read_next_action(repo, "T-1")
    assert rec["next_action"] == "EXECUTED:WAITING_FOR_HUMAN_TRANSPORT"
    assert rec["auto_actionable"] is False
    assert rec["stop_reason"] == "HUMAN_TRANSPORT_REQUIRED"


# =========== 4: AUTO_REMEDIATE_CONFIRMED_FINDINGS reaches backend
# =========== resolution through the same production dispatcher

def test_auto_remediate_confirmed_findings_reaches_backend_resolution_through_production_dispatcher(repo):
    _export(repo)
    _place_fail_with_findings(repo)
    expected = repo / ri._expected_path(repo, "T-1").relative_to(repo)
    ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL")

    dispatched = _dispatched_events(repo)
    assert len(dispatched) == 1
    assert dispatched[0]["dispatch_status"] == ec.DISPATCH_BACKEND_RESOLVED
    assert dispatched[0]["next_action"] == "AUTO_REMEDIATE_CONFIRMED_FINDINGS"


# =========== 5: a test/manual current-session call does not by itself
# =========== qualify a route as WIRED -- a real, non-test production caller
# =========== of dispatch_next_action() must exist in the shipped source

def test_dispatch_next_action_has_a_real_non_test_production_caller():
    """Codifies the corrected reachability definition itself: a route is
    WIRED only when a real PRODUCTION caller exists, not merely a test or a
    function definition. This is exactly the static check that exposed the
    original gap (`dispatch_next_action()`'s only match was its own
    definition line) -- locked in as a permanent regression guard so a
    future refactor cannot silently remove result_ingestion.py's own call
    without a test failing."""
    import ast
    src_dir = Path(ec.__file__).parent
    call_sites = []
    for path in src_dir.glob("*.py"):
        if path.name in ("execution_contract.py",):
            continue  # the definition's own module -- not a caller
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name == "dispatch_next_action":
                    call_sites.append(path.name)
    assert "result_ingestion.py" in call_sites, (
        "dispatch_next_action() has no real production caller in dv_harness/ "
        f"(found call sites: {call_sites}) -- RESOLVED_BUT_NOT_EXECUTED, not WIRED"
    )


# =========== 6: context-required actions are not falsely classified WIRED

@pytest.mark.parametrize("event,action", [
    ("RESULT_REJECTED_SCOPE_VIOLATION", "AUTO_CLASSIFY_SCOPE_VIOLATION"),
    ("RESULT_REJECTED_VALIDATION", "AUTO_DIAGNOSE_VALIDATION_FAILURE"),
    ("AGENT_RUN_FAILED_RETRY_ELIGIBLE", "AUTO_RETRY_AGENT_RUN"),
])
def test_context_required_actions_are_never_falsely_classified_wired(repo, event, action):
    """dispatch_next_action() cannot derive a real ValidationOutcome or
    AgentRunRequest from root+task_id alone -- these three actions must stay
    honestly REQUIRES_CALLER_CONTEXT, never fabricated to force a WIRED
    classification (the user's own explicit instruction)."""
    _export(repo)
    rec = ec.resolve_next_action(event)
    assert rec.next_action == action
    ec.persist_next_action(repo, "T-1", rec)

    outcome = ec.dispatch_next_action(repo, "T-1")
    assert outcome.dispatch_status == ec.DISPATCH_REQUIRES_CALLER_CONTEXT


# =========== 7: BACKEND_RESOLVED is never reported as EXECUTED

def test_backend_resolved_is_never_reported_as_executed(repo):
    assert ec.DISPATCH_BACKEND_RESOLVED != ec.DISPATCH_EXECUTED
    _export(repo)
    _place_fail_with_findings(repo)
    expected = repo / ri._expected_path(repo, "T-1").relative_to(repo)
    ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL")
    outcome = ec.dispatch_next_action(repo, "T-1")  # re-dispatch: still only ever resolves, never executes
    assert outcome.dispatch_status == ec.DISPATCH_BACKEND_RESOLVED
    assert outcome.dispatch_status != ec.DISPATCH_EXECUTED


# =========== 8: duplicate watcher events do not double-dispatch an action

def test_duplicate_resume_after_import_does_not_double_dispatch(repo):
    """Simulates a duplicate watcher poll calling the real production
    resume path twice for the same already-resolved action."""
    _export(repo)
    _place_malformed(repo)
    expected = repo / ri._expected_path(repo, "T-1").relative_to(repo)
    ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL")  # first real import + auto-resume
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT
    assert len(_dispatched_events(repo)) == 1
    first_handoff_text = (repo / ".dv-harness/model_handoffs/T-1/HANDOFF_V1.md").read_text(encoding="utf-8")

    # A duplicate watcher poll re-resuming the SAME task (e.g. a redundant
    # filesystem event) must never re-dispatch: next_action.json's own
    # auto_actionable is already False after the first real dispatch, so
    # resume_after_import()'s own guard never even attempts a second call.
    ri.resume_after_import(repo, "T-1")
    assert len(_dispatched_events(repo)) == 1  # still exactly one -- no double dispatch
    assert (repo / ".dv-harness/model_handoffs/T-1/HANDOFF_V1.md").read_text(encoding="utf-8") == first_handoff_text


def test_dispatcher_idempotency_when_a_second_dispatch_is_attempted_directly(repo):
    """A second line of defense below resume_after_import()'s own
    auto_actionable guard, for the narrower race that guard alone does not
    cover: two concurrent resume events both reading next_action.json's
    still-pending AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF record before
    either one's own dispatch has updated it. Reproduced directly: a
    duplicate/racing event re-persists the SAME pending record after the
    real export already happened -- dispatch_next_action()'s own
    NOT_REJECTED precondition catch must still refuse a second export."""
    _export(repo)
    _place_malformed(repo)
    expected = repo / ri._expected_path(repo, "T-1").relative_to(repo)
    ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL")
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT

    # Simulate the race: a duplicate/racing watcher event re-surfaces the
    # pre-dispatch pending record (state.json is untouched -- still
    # WAITING_FOR_HUMAN_TRANSPORT from the real first dispatch above).
    ec.persist_next_action(repo, "T-1", ec.resolve_next_action("RESULT_REJECTED_MALFORMED"))

    outcome = ec.dispatch_next_action(repo, "T-1")  # the SAME action name, dispatched again directly
    assert outcome.dispatch_status == ec.DISPATCH_EXECUTED
    assert outcome.detail.get("already_dispatched") is True


# =========== 9: Human Authority/Transport gates are never auto-executed

def test_human_gate_next_actions_are_never_auto_dispatched(repo, monkeypatch):
    _export(repo)
    calls = {"n": 0}
    real_dispatch = ec.dispatch_next_action

    def _tracking_dispatch(*a, **kw):
        calls["n"] += 1
        return real_dispatch(*a, **kw)

    # result_ingestion.py calls this via `from . import execution_contract as
    # _ec` -- the same module object as `ec` here, so patching the attribute
    # on `ec` is visible through `ri`'s own reference too.
    monkeypatch.setattr(ec, "dispatch_next_action", _tracking_dispatch)

    gate_rec = ec.resolve_next_action("RE_REVIEW_HANDOFF_READY")
    assert gate_rec.auto_actionable is False and gate_rec.next_action_owner == "HUMAN"
    ec.persist_next_action(repo, "T-1", gate_rec)

    decision = ri.resume_after_import(repo, "T-1")
    assert calls["n"] == 0  # dispatch_next_action() was never even attempted for a gate
    assert decision["STOP_REASON"] == "HUMAN_TRANSPORT_REQUIRED"
    assert decision["HUMAN_ACTION_REQUIRED"] == "YES"
