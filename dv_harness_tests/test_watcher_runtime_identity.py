"""Anti-drift regression tests for the real CONTROL_PLANE_RUNTIME_HEAD_DRIFT
defect: a long-running `result_ingestion.watch()` process (real, live
evidence: PID 19536, started 2026-09-24, five days before commit 6083ae6)
held an in-memory copy of `result_ingestion.py` -- and everything it
imports -- loaded at start. It kept correctly ingesting and resolving
REVIEW-002's rejected result, but never dispatched it: editing the .py
files on disk after start has zero effect on an already-running
interpreter. Confirmed live: `AUTO_RESUME_STARTED`/`NEXT_ACTION_RESOLVED`
fired for the new result, but no `ACTION_DISPATCHED`/`ACTION_DISPATCH_
FAILED` event ever appeared.

Every test here drives the real `watch()` / `control_plane_dependency_
set()` / `runtime_restart_status()` / `startup_recovery()` /
`restart_watcher()` production functions against a real throwaway git
repo -- never a mock of git or the workflow."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import dv_harness.execution_contract as ec
import dv_harness.model_handoff_workflow as wf
import dv_harness.result_ingestion as ri
from dv_harness.model_handoff import build_handoff
from dv_harness.model_result import ModelResultV1, to_markdown
from dv_harness.task_boundary_conformance import TaskBoundary

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")

FAST_POLICY = ri.IngestionPolicy(quiet_seconds=0.0, min_observations=1, poll_interval_seconds=0.01,
                                 idle_exit_seconds=0.0, lock_stale_seconds=5.0)


def _run(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return p.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    w = tmp_path / "work"
    w.mkdir()
    _run(w, "init", "-q")
    _run(w, "config", "user.email", "t@example.com")
    _run(w, "config", "user.name", "T")
    (w / "dv_harness").mkdir()
    (w / "dv_harness" / "module_a.py").write_text("# x\n", encoding="utf-8")
    (w / ".dv-harness").mkdir()
    _run(w, "add", "-A")
    _run(w, "commit", "-q", "-m", "i")
    return w


def _head(repo: Path) -> str:
    return _run(repo, "rev-parse", "HEAD")


def _export(repo: Path, task_id: str = "T-1") -> Path:
    h = build_handoff(repo, task_id=task_id, task_type="review-route", target_model="codex", project_id="P",
                      objective="review",
                      scope=TaskBoundary(task_id=task_id, allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)
    return repo / ri._expected_path(repo, task_id).relative_to(repo)


def _place_malformed(repo: Path, task_id: str = "T-1") -> None:
    """A real MALFORMED_LIST_ITEM -- the exact rejection class REVIEW-002's
    UNEXPECTED_PREAMBLE/MALFORMED_LIST_ITEM history hit live."""
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


# =========== 1: watcher records runtime/source identity

def test_watch_records_real_runtime_identity(repo):
    ri.watch(repo, policy=FAST_POLICY, max_iterations=1, sleep=lambda s: None)
    rec = json.loads(ri._watcher_file(repo).read_text(encoding="utf-8"))
    assert rec["source_head_at_start"] == _head(repo)
    assert rec["python_executable"]
    assert rec["repo_root_matched"] is True
    assert rec["repo_root_identity"] == str(repo.resolve())
    assert rec["runtime_generation"] == 1


# =========== 2: control-plane-affecting changes mark restart required

def test_control_plane_change_since_watcher_start_marks_restart_required(repo):
    ri.watch(repo, policy=FAST_POLICY, max_iterations=1, sleep=lambda s: None)
    (repo / "dv_harness" / "execution_contract.py").write_text("# changed\n", encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "touch control-plane file")
    status = ri.runtime_restart_status(repo)
    assert status["WATCHER_RESTART_REQUIRED"] == "YES"
    assert "execution_contract.py" in status["WATCHER_RESTART_REASON"]


# =========== 3: documentation-only/non-runtime changes do not force restart

def test_non_control_plane_change_does_not_force_restart(repo):
    ri.watch(repo, policy=FAST_POLICY, max_iterations=1, sleep=lambda s: None)
    (repo / "README.md").write_text("docs only\n", encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "docs")
    status = ri.runtime_restart_status(repo)
    assert status["WATCHER_RESTART_REQUIRED"] == "NO"
    assert status["WATCHER_RESTART_REASON"] is None


# =========== 4: a stale (pre-identity-capture) watcher cannot be reported as current

def test_watcher_with_no_recorded_source_head_is_unknown_not_current(repo):
    """Simulates the REAL REVIEW-002 case exactly: a watcher started before
    this capability existed at all has no source_head_at_start recorded."""
    ri._atomic_write_json(ri._watcher_file(repo), {
        "pid": 999999, "started_at_epoch": time.time(), "last_heartbeat_epoch": time.time(),
        "poll_interval_seconds": 5.0, "iterations": 1, "status": "ACTIVE"})
    status = ri.runtime_restart_status(repo)
    assert status["WATCHER_RESTART_REQUIRED"] == "UNKNOWN"
    assert status["WATCHER_RESTART_REQUIRED"] != "NO"  # never silently reported as confirmed-current


# =========== 5: restart preserves registrations and ingestion state

def test_restart_never_touches_registrations_or_ingestion_state(repo, monkeypatch):
    _export(repo)
    _place_malformed(repo)
    ri.ingest_result_file(repo, "T-1", repo / ri._expected_path(repo, "T-1").relative_to(repo), trigger="MANUAL")
    before_ing = (repo / ".dv-harness/model_handoffs/T-1/ingestion_state.json").read_text(encoding="utf-8")
    before_reg = (repo / ".dv-harness/model_handoffs/T-1/expected_result.json").read_text(encoding="utf-8")
    before_next_action = ec.read_next_action(repo, "T-1")

    ri._atomic_write_json(ri._watcher_file(repo), {
        "pid": 999999, "started_at_epoch": time.time(), "last_heartbeat_epoch": time.time(),
        "poll_interval_seconds": 5.0, "iterations": 1, "status": "ACTIVE"})
    monkeypatch.setenv("L5DGVA_RESULT_WATCHER", "off")  # never a real subprocess in this test
    result = ri.restart_watcher(repo, wait_seconds=1.0)
    # The fake pid 999999 never actually stops -- restart correctly fails
    # closed rather than starting a second concurrent watcher.
    assert result["RESTART_STATUS"] == "RESTART_FAILED_OLD_WATCHER_DID_NOT_STOP"

    after_ing = (repo / ".dv-harness/model_handoffs/T-1/ingestion_state.json").read_text(encoding="utf-8")
    after_reg = (repo / ".dv-harness/model_handoffs/T-1/expected_result.json").read_text(encoding="utf-8")
    assert after_ing == before_ing
    assert after_reg == before_reg
    assert ec.read_next_action(repo, "T-1") == before_next_action


# =========== 6: startup recovery resumes a persisted auto-actionable action

def test_startup_recovery_resumes_a_persisted_auto_actionable_action(repo):
    """Reproduces the REAL gap directly: ingestion/rejection resolved via
    the Canonical workflow import alone (never resume_after_import()) --
    exactly what a STALE pre-dispatch-fix runtime would have left behind."""
    _export(repo)
    _place_malformed(repo)
    expected = repo / ri._expected_path(repo, "T-1").relative_to(repo)
    outcome = wf.import_result(repo, "T-1", expected)
    assert outcome.state == wf.STATE_RESULT_REJECTED
    event = ec.event_for_import_outcome(outcome.state, parse_error=outcome.parse_error)
    ec.persist_next_action(repo, "T-1", ec.resolve_next_action(event))
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_REJECTED  # stuck, like the real stale-watcher case

    results = ri.startup_recovery(repo)

    assert any(r["task_id"] == "T-1" and r["recovered"] for r in results)
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT


# =========== 6b: startup recovery never overwrites an already-CLOSED
# =========== task's real execution-contract state

def test_startup_recovery_never_overwrites_an_already_complete_execution_contract_state(repo):
    """Real, live-reproduced damage this test locks in against regressing
    again: M7-V1-CODEX-REVIEW-003/004 each had a genuinely stale
    `next_action.json` (auto_actionable=true, predating any dispatcher) but
    had ALREADY been separately marked STATE=COMPLETE/STOP_REASON=
    TASK_COMPLETE with a real, human-meaningful STOP_EVIDENCE narrative via
    a different mechanism. The first version of `startup_recovery()` called
    `resume_after_import()` on them anyway and silently overwrote that real
    completion record with a generic AUTO_RUNNING/empty-evidence one."""
    _export(repo)
    _place_malformed(repo)
    expected = repo / ri._expected_path(repo, "T-1").relative_to(repo)
    outcome = wf.import_result(repo, "T-1", expected)
    assert outcome.state == wf.STATE_RESULT_REJECTED
    event = ec.event_for_import_outcome(outcome.state, parse_error=outcome.parse_error)
    ec.persist_next_action(repo, "T-1", ec.resolve_next_action(event))  # stale, auto_actionable=true

    # A real, human-meaningful completion record, exactly the REVIEW-003/004
    # shape -- written by a mechanism other than can_i_stop()/persist_stop().
    real_completion = {
        "HUMAN_ACTION_REQUIRED": "NO", "NEXT_REQUIRED_ACTION": "", "RESUME_ACTION": "",
        "STATE": "COMPLETE", "STOP_REASON": "TASK_COMPLETE",
        "STOP_EVIDENCE": "real, human-authored narrative -- must never be silently overwritten",
    }
    ec_state_path = repo / ".dv-harness/model_handoffs/T-1/execution_contract_state.json"
    ec_state_path.write_text(json.dumps(real_completion, indent=2), encoding="utf-8")

    results = ri.startup_recovery(repo)

    assert not any(r["task_id"] == "T-1" for r in results)  # never even attempted
    assert json.loads(ec_state_path.read_text(encoding="utf-8")) == real_completion  # byte-for-byte preserved
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_REJECTED  # workflow state untouched too


# =========== 7: duplicate watcher ownership is prevented

def test_duplicate_watcher_ownership_is_prevented(repo):
    token = wf._acquire_lock(ri._watcher_role_lock(repo), 60.0)
    assert token is not None
    try:
        rc = ri.watch(repo, policy=FAST_POLICY, max_iterations=1, sleep=lambda s: None)
        assert rc == 1
        assert not ri._watcher_file(repo).exists()  # never even got past the role-lock gate
    finally:
        wf._release_lock(ri._watcher_role_lock(repo), token)


# =========== 8: restart (startup recovery) does not double-consume a result

def test_startup_recovery_does_not_double_consume_a_result(repo):
    _export(repo)
    result = ModelResultV1(result_version="1.0", task_id="T-1", producer_model="codex", task_type="review-route",
                           result_status="PASS", claims=["c"], findings=[],
                           evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"])
    expected = repo / ri._expected_path(repo, "T-1").relative_to(repo)
    expected.write_text(to_markdown(result), encoding="utf-8")
    ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL")
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED
    ing_before = json.loads((repo / ".dv-harness/model_handoffs/T-1/ingestion_state.json").read_text(encoding="utf-8"))

    ri.startup_recovery(repo)  # a new watcher's own startup pass, e.g. immediately after a restart

    ing_after = json.loads((repo / ".dv-harness/model_handoffs/T-1/ingestion_state.json").read_text(encoding="utf-8"))
    assert ing_after["results"] == ing_before["results"]  # never re-imported/re-hashed


# =========== 9: restart (startup recovery) does not double-dispatch an action

def test_startup_recovery_does_not_double_dispatch(repo):
    _export(repo)
    _place_malformed(repo)
    expected = repo / ri._expected_path(repo, "T-1").relative_to(repo)
    ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL")  # real dispatch #1, via resume_after_import
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT
    dispatched_before = [e for e in ri.read_events(repo, "T-1") if e["event"] == "ACTION_DISPATCHED"]
    assert len(dispatched_before) == 1

    ri.startup_recovery(repo)  # simulates a restart's own recovery pass running right after

    dispatched_after = [e for e in ri.read_events(repo, "T-1") if e["event"] == "ACTION_DISPATCHED"]
    assert len(dispatched_after) == 1  # still exactly one


# =========== 10: repo identity mismatch fails closed

def test_watch_refuses_to_start_against_a_non_repo_directory(tmp_path):
    bogus = tmp_path / "not_a_repo"
    bogus.mkdir()
    rc = ri.watch(bogus, policy=FAST_POLICY, max_iterations=1, sleep=lambda s: None)
    assert rc == 2
    assert not ri._watcher_file(bogus).exists()  # refused before ever writing a heartbeat/identity record


# =========== 11: status reporter remains read-only

def test_status_report_is_read_only(repo):
    _export(repo)
    before = {p: p.stat().st_mtime_ns for p in repo.rglob("*") if p.is_file()}
    ri.status_report(repo)
    after = {p: p.stat().st_mtime_ns for p in repo.rglob("*") if p.is_file()}
    assert before == after
