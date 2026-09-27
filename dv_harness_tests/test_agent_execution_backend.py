"""Behavioral tests for dv_harness/agent_execution_backend.py (Autonomous
Agent Execution Backend). Test names match the requirements doc's own named
anti-drift list exactly.

MOCKING BOUNDARY, disclosed: `build_worker_argv()` (the real invocation
construction) is exercised for real and checked against the exact flags this
task's own live discovery captured (see `M7_CLAUDE_WORKER_LIVE_QUALIFICATION.md`
for the real transcripts of a real `claude` subprocess launch, including a
mutation-capable one that wrote a file and one that was refused escaping its
working directory). The recurring pytest suite mocks only the OS subprocess
boundary itself (`subprocess.Popen`) -- the same class of boundary this
project's own established convention treats as safe to inject a fake for
(`monkeypatch.setattr(wf, "_append_registry", ...)` and siblings throughout
`test_result_ingestion.py`), because a real Claude Code invocation is slow,
billed, and non-deterministic to run on every test collection. Everything
around that one boundary -- lease acquisition/liveness, scope enforcement,
idempotency, recovery, audit trace, Next Action Resolver wiring, and the
read-only status contract -- runs for real against a throwaway git repo.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import os
import time
from pathlib import Path
from typing import List, Optional

import pytest

import dv_harness.agent_execution_backend as aeb
from dv_harness import execution_contract as ec
from dv_harness.safe_tool_profile import CLAUDE_IMPLEMENTATION_PROFILE, CLAUDE_READONLY_PROFILE
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
    for n in ("module_a.py", "engine.py"):
        (w / "dv_harness" / n).write_text("# x\n", encoding="utf-8")
    _run(w, "add", "-A")
    _run(w, "commit", "-q", "-m", "i")
    return w


def _scope(**kw) -> TaskBoundary:
    base = dict(task_id="T-1", allowed_path_prefixes=("dv_harness/module_a.py",),
                forbidden_paths=("dv_harness/engine.py",))
    base.update(kw)
    return TaskBoundary(**base)


def _request(repo, **kw) -> aeb.AgentRunRequest:
    return aeb.build_agent_run_request(
        repo, task_id=kw.pop("task_id", "T-1"), parent_workflow_id="M7-V1-CODEX-REVIEW-004",
        action_id=kw.pop("action_id", "A-1"), action_type="REMEDIATE_FINDINGS", role="implementation",
        objective="fix the reported findings", scope=kw.pop("scope", _scope()),
        mutation_allowed=kw.pop("mutation_allowed", True),
        human_authority_constraints=kw.pop("human_authority_constraints", ()),
        timeout_policy_seconds=kw.pop("timeout_policy_seconds", 30.0),
        tool_execution_profile=kw.pop("tool_execution_profile", CLAUDE_IMPLEMENTATION_PROFILE.name),
        **kw,
    )


class FakeProcess:
    """A `subprocess.Popen`-shaped double. `outcomes` controls poll()/exit
    behavior across successive calls, driven by an injectable clock so
    timeout tests never actually sleep in wall-clock time."""

    def __init__(self, argv, cwd=None, stdout=None, stderr=None, *, returncode=0,
                stdout_text: str = "", never_exits: bool = False, pid: int = None):
        # A genuinely-alive PID by default (this test process itself) so the
        # production code's own real _pid_alive() liveness check -- which
        # this suite deliberately does NOT mock, except in the two tests
        # about a dead process -- treats the fake worker as really running.
        pid = os.getpid() if pid is None else pid
        self.argv = argv
        self.cwd = cwd
        self.pid = pid
        self._returncode = returncode
        self._never_exits = never_exits
        self.terminated = False
        self.killed = False
        if stdout is not None:
            stdout.write(stdout_text)
            stdout.flush()

    def poll(self) -> Optional[int]:
        return None if self._never_exits else self._returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None):
        if self._never_exits and not (self.terminated or self.killed):
            raise subprocess.TimeoutExpired(self.argv, timeout or 0)
        self._never_exits = False
        return self._returncode

    @property
    def returncode(self):
        return self._returncode


def _envelope(run_status: str, **extra) -> str:
    structured = {"run_status": run_status}
    structured.update(extra)
    return json.dumps({"is_error": False, "subtype": "success", "structured_output": structured})


def _fake_popen_factory(**process_kwargs):
    def factory(argv, cwd=None, stdout=None, stderr=None):
        return FakeProcess(argv, cwd=cwd, stdout=stdout, stderr=stderr, **process_kwargs)
    return factory


def _launch_and_monitor(repo, request, *, process_kwargs=None, poll_interval=0.01):
    popen = _fake_popen_factory(**(process_kwargs or {}))
    out = aeb.launch_worker(repo, request, _popen=popen)
    assert out["launched"] is True
    outcome = aeb.monitor_and_ingest(repo, out["agent_run_id"], request, out["_process"],
                                     out["_stdout_f"], out["_stderr_f"], poll_interval=poll_interval)
    return out, outcome


# --- 1. Real CLI invocation (no mocking here) --------------------------------

def test_build_worker_argv_matches_the_real_verified_invocation_shape(repo):
    req = _request(repo)
    argv = aeb.build_worker_argv(req)
    assert argv[0] == "claude" and argv[1] == "-p"
    assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json"
    assert "--json-schema" in argv
    assert "--restricted" in argv
    assert "--tools" in argv
    assert "--permission-mode" in argv and argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert "--add-dir" in argv and argv[argv.index("--add-dir") + 1] == request_cwd(req)
    assert req.objective in argv[2]


def request_cwd(req: aeb.AgentRunRequest) -> str:
    return req.working_directory


def test_readonly_profile_uses_bypass_permissions_with_no_code_tool(repo):
    req = _request(repo, tool_execution_profile=CLAUDE_READONLY_PROFILE.name, mutation_allowed=False)
    argv = aeb.build_worker_argv(req)
    tools = argv[argv.index("--tools") + 1]
    assert "Edit" not in tools and "PowerShell" not in tools
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"


def test_unsupported_backend_is_rejected():
    with pytest.raises(aeb.AgentExecutionError):
        aeb.build_worker_argv(aeb.AgentRunRequest(
            agent_run_id="x", task_id="T", parent_workflow_id="P", action_id="A", action_type="X",
            backend="gpt5", role="implementation", objective="o", current_head="h", working_directory=".",
            task_scope=_scope()))


# --- 2/3. Controlled worker launch, never terminal injection -----------------

def test_agent_action_launches_controlled_worker(repo):
    req = _request(repo)
    out, outcome = _launch_and_monitor(repo, req, process_kwargs=dict(stdout_text=_envelope(aeb.RUN_STATUS_PASS)))
    assert out["launched"] is True
    assert outcome["run_state"] == aeb.RUN_STATE_COMPLETED
    events = [e["event"] for e in aeb.read_audit_trace(repo, out["agent_run_id"])]
    assert events[:3] == ["AGENT_RUN_REQUESTED", "BACKEND_SELECTED", "MUTATION_LEASE_REQUESTED"]
    assert "WORKER_LAUNCHED" in events and "WORKER_COMPLETED" in events and "RESULT_INGESTED" in events


def test_agent_action_does_not_inject_existing_terminal(repo):
    """The launch path never touches an interactive terminal: no keyboard
    injection, no PID search for an existing claude.exe/PowerShell -- the
    ONLY process-related call is a fresh subprocess.Popen this module owns."""
    calls = []
    popen = lambda argv, cwd=None, stdout=None, stderr=None: (calls.append((argv, cwd)), FakeProcess(argv, cwd, stdout, stderr, stdout_text=_envelope(aeb.RUN_STATUS_PASS)))[1]
    req = _request(repo)
    out = aeb.launch_worker(repo, req, _popen=popen)
    assert len(calls) == 1
    assert calls[0][1] == req.working_directory  # explicit CWD, never an ambient/attached terminal
    aeb.monitor_and_ingest(repo, out["agent_run_id"], req, out["_process"], out["_stdout_f"], out["_stderr_f"])


# --- 4/5. Read-only parallelism / mutation lease -----------------------------

def test_read_only_worker_does_not_require_mutation_lease(repo):
    req = _request(repo, mutation_allowed=False, tool_execution_profile=CLAUDE_READONLY_PROFILE.name)
    out, _ = _launch_and_monitor(repo, req, process_kwargs=dict(stdout_text=_envelope(aeb.RUN_STATUS_PASS)))
    events = [e["event"] for e in aeb.read_audit_trace(repo, out["agent_run_id"])]
    assert "MUTATION_LEASE_REQUESTED" not in events
    assert aeb.lease_state(repo)["state"] == "NONE"


def test_mutation_worker_requires_lease(repo):
    req = _request(repo)
    out, _ = _launch_and_monitor(repo, req, process_kwargs=dict(stdout_text=_envelope(aeb.RUN_STATUS_PASS)))
    events = [e["event"] for e in aeb.read_audit_trace(repo, out["agent_run_id"])]
    assert "MUTATION_LEASE_REQUESTED" in events and "MUTATION_LEASE_ACQUIRED" not in events  # acquired implicitly (no busy path)
    assert "WORKER_LAUNCHED" in events


def test_second_mutation_worker_cannot_acquire_same_lease(repo):
    first = aeb.acquire_mutation_lease(repo, "T-1", "run-a")
    assert first.acquired is True
    req2 = _request(repo, action_id="A-2")
    out = aeb.launch_worker(repo, req2, _popen=_fake_popen_factory())
    assert out["launched"] is False and out["refusal"] == "LEASE_BUSY"
    assert out["owner_agent_run_id"] == "run-a"


def test_lease_liveness_and_heartbeat(repo):
    lease = aeb.acquire_mutation_lease(repo, "T-1", "run-a")
    aeb.heartbeat_lease(repo, lease.lease_id)
    st = aeb.lease_state(repo)
    assert st["state"] == "HELD" and st["last_heartbeat_epoch"] > 0
    aeb.release_mutation_lease(repo, lease.lease_id)
    assert aeb.lease_state(repo)["state"] == "RELEASED"


def test_stale_lease_recovery_requires_liveness_evidence(repo, monkeypatch):
    lease = aeb.acquire_mutation_lease(repo, "T-1", "dead-run")
    rec = aeb._read_json(aeb._lease_path(repo))
    rec["owner_pid"] = 999999999  # a PID that does not exist
    rec["last_heartbeat_epoch"] = time.time() - 1000  # very stale
    aeb._atomic_write_json(aeb._lease_path(repo), rec)
    monkeypatch.setattr(aeb, "_pid_alive", lambda pid: pid != 999999999)
    second = aeb.acquire_mutation_lease(repo, "T-1", "run-b", liveness_grace_seconds=10.0)
    assert second.acquired is True  # stale AND dead -> real recovery


def test_stale_heartbeat_alone_is_not_enough_to_break_the_lease(repo, monkeypatch):
    lease = aeb.acquire_mutation_lease(repo, "T-1", "alive-run")
    rec = aeb._read_json(aeb._lease_path(repo))
    rec["last_heartbeat_epoch"] = time.time() - 1000  # stale heartbeat
    aeb._atomic_write_json(aeb._lease_path(repo), rec)
    monkeypatch.setattr(aeb, "_pid_alive", lambda pid: True)  # but the owner IS alive
    second = aeb.acquire_mutation_lease(repo, "T-1", "run-b", liveness_grace_seconds=10.0)
    assert second.acquired is False  # elapsed time alone never breaks the lease


def test_live_owner_within_grace_is_never_broken(repo, monkeypatch):
    lease = aeb.acquire_mutation_lease(repo, "T-1", "alive-run")
    monkeypatch.setattr(aeb, "_pid_alive", lambda pid: True)
    second = aeb.acquire_mutation_lease(repo, "T-1", "run-b", liveness_grace_seconds=90.0)
    assert second.acquired is False and second.reason == "HELD_AND_LIVE"


# --- 6/7. Scope enforcement ----------------------------------------------------

def test_worker_scope_matches_task_boundary(repo):
    req = _request(repo)
    out, outcome = _launch_and_monitor(repo, req, process_kwargs=dict(
        stdout_text=_envelope(aeb.RUN_STATUS_PASS, files_changed=["dv_harness/module_a.py"])))
    assert outcome["result"]["run_status"] == aeb.RUN_STATUS_PASS


def test_worker_cannot_modify_forbidden_path(repo):
    req = _request(repo)
    out, outcome = _launch_and_monitor(repo, req, process_kwargs=dict(
        stdout_text=_envelope(aeb.RUN_STATUS_PASS, files_changed=["dv_harness/engine.py"])))
    assert outcome["result"]["run_status"] == aeb.RUN_STATUS_ERROR
    assert any("SCOPE_VIOLATION" in e for e in outcome["result"]["errors"])


def test_worker_cannot_modify_a_frozen_source(repo):
    req = _request(repo, scope=_scope(allowed_path_prefixes=("dv_harness/module_a.py", "CLAUDE.md")))
    req = aeb.AgentRunRequest(**{**req.to_dict(), "task_scope": req.task_scope, "frozen_sources": ("CLAUDE.md",)})
    out, outcome = _launch_and_monitor(repo, req, process_kwargs=dict(
        stdout_text=_envelope(aeb.RUN_STATUS_PASS, files_changed=["CLAUDE.md"])))
    assert outcome["result"]["run_status"] == aeb.RUN_STATUS_ERROR


def test_mutation_not_allowed_forbids_every_file(repo):
    req = _request(repo, mutation_allowed=False, tool_execution_profile=CLAUDE_READONLY_PROFILE.name)
    v = aeb.enforce_worker_scope(req, ["dv_harness/module_a.py"])
    assert v and v[0]["classification"] == "MUTATION_NOT_ALLOWED"


def test_worker_uses_safe_tool_profile(repo):
    req = _request(repo)
    argv = aeb.build_worker_argv(req)
    tools = argv[argv.index("--tools") + 1].split(",")
    assert set(tools) == set(CLAUDE_IMPLEMENTATION_PROFILE.tools)
    patterns = argv[argv.index("--allowedTools") + 1:]
    assert all(p.startswith("PowerShell(") for p in patterns[:len(CLAUDE_IMPLEMENTATION_PROFILE.allowed_tool_patterns)])


# --- 8/9. Result ingestion / failure never becomes PASS -----------------------

def test_worker_result_is_ingested(repo):
    req = _request(repo)
    out, outcome = _launch_and_monitor(repo, req, process_kwargs=dict(
        stdout_text=_envelope(aeb.RUN_STATUS_PASS, files_changed=["dv_harness/module_a.py"],
                              tests_run=["pytest -q"], gaps_fixed=["N1"])))
    result = aeb._read_json(aeb._run_dir(repo, out["agent_run_id"]) / "RESULT.json")
    assert result["run_status"] == aeb.RUN_STATUS_PASS and result["gaps_fixed"] == ["N1"]
    assert outcome["next_action"]["next_action"] == "PREPARE_REQUIRED_RE_REVIEW"


def test_worker_failure_does_not_become_pass_nonzero_exit(repo):
    req = _request(repo)
    out, outcome = _launch_and_monitor(repo, req, process_kwargs=dict(returncode=1, stdout_text=_envelope(aeb.RUN_STATUS_PASS)))
    assert outcome["result"]["run_status"] == aeb.RUN_STATUS_ERROR
    assert outcome["next_action"]["next_action"] == "AUTO_RETRY_AGENT_RUN"


def test_worker_failure_does_not_become_pass_is_error_flag(repo):
    req = _request(repo)
    envelope = json.dumps({"is_error": True, "terminal_reason": "api_error"})
    out, outcome = _launch_and_monitor(repo, req, process_kwargs=dict(stdout_text=envelope))
    assert outcome["result"]["run_status"] == aeb.RUN_STATUS_ERROR


def test_worker_failure_does_not_become_pass_malformed_json(repo):
    req = _request(repo)
    out, outcome = _launch_and_monitor(repo, req, process_kwargs=dict(stdout_text="not json at all"))
    assert outcome["result"]["run_status"] == aeb.RUN_STATUS_ERROR


def test_human_decision_required_result_routes_to_authority(repo):
    req = _request(repo)
    out, outcome = _launch_and_monitor(repo, req, process_kwargs=dict(
        stdout_text=_envelope(aeb.RUN_STATUS_HUMAN_DECISION_REQUIRED, human_decisions_required=["pick an approach"])))
    assert outcome["next_action"]["stop_reason"] == "HUMAN_AUTHORITY_REQUIRED"


def test_worker_timeout_routes_to_policy(repo):
    req = _request(repo, timeout_policy_seconds=0.05)
    out, outcome = _launch_and_monitor(repo, req, process_kwargs=dict(never_exits=True), poll_interval=0.01)
    assert outcome["run_state"] == aeb.RUN_STATE_TIMEOUT
    assert out["_process"].terminated is True
    events = [e["event"] for e in aeb.read_audit_trace(repo, out["agent_run_id"])]
    assert "WORKER_TIMEOUT" in events and "MUTATION_LEASE_RELEASED" in events
    assert outcome["result"]["run_status"] == aeb.RUN_STATUS_ERROR  # timeout is never an implementation-defect PASS
    assert aeb.lease_state(repo)["state"] == "RELEASED"


# --- 10. Idempotency -----------------------------------------------------------

def test_same_action_not_double_launched(repo):
    req = _request(repo, timeout_policy_seconds=999.0)
    out1 = aeb.launch_worker(repo, req, _popen=_fake_popen_factory(never_exits=True))
    assert out1["launched"] is True
    req2 = aeb.build_agent_run_request(repo, task_id="T-1", parent_workflow_id="P", action_id="A-1",
                                       action_type="X", role="implementation", objective="retry",
                                       scope=_scope(), attempt_number=2, previous_attempt=out1["agent_run_id"])
    out2 = aeb.launch_worker(repo, req2, _popen=_fake_popen_factory())
    assert out2["launched"] is False and out2["refusal"] == "DUPLICATE_ACTIVE_RUN"
    assert out2["agent_run_id"] == out1["agent_run_id"]


# --- 11/12. Restart recovery -----------------------------------------------------

def test_restart_recovers_completed_worker(repo):
    req = _request(repo)
    out, _ = _launch_and_monitor(repo, req, process_kwargs=dict(stdout_text=_envelope(aeb.RUN_STATUS_PASS)))
    st = aeb._read_json(aeb._run_dir(repo, out["agent_run_id"]) / "STATE.json")
    st["run_state"] = aeb.RUN_STATE_RUNNING  # simulate a crash before the finalize state write landed
    aeb._atomic_write_json(aeb._run_dir(repo, out["agent_run_id"]) / "STATE.json", st)
    reports = aeb.recover_pending_runs(repo)
    assert reports[0]["recovery"] == "RESULT_INGESTED_ON_RECOVERY"
    st2 = aeb._read_json(aeb._run_dir(repo, out["agent_run_id"]) / "STATE.json")
    assert st2["run_state"] == aeb.RUN_STATE_COMPLETED


def test_restart_recovers_active_worker_state(repo):
    req = _request(repo, timeout_policy_seconds=999.0)
    out = aeb.launch_worker(repo, req, _popen=_fake_popen_factory(never_exits=True))
    reports = aeb.recover_pending_runs(repo)
    # a genuinely-alive PID is reconciled as still active, never torn down or re-launched
    assert reports == [{"agent_run_id": out["agent_run_id"], "recovery": "STILL_ACTIVE"}]
    st = aeb._read_json(aeb._run_dir(repo, out["agent_run_id"]) / "STATE.json")
    assert st["run_state"] == aeb.RUN_STATE_RUNNING


def test_restart_recovers_a_crashed_worker_with_no_result(repo):
    req = _request(repo)
    lease = aeb.acquire_mutation_lease(repo, req.task_id, req.agent_run_id)
    run_dir = aeb._run_dir(repo, req.agent_run_id)
    aeb._atomic_write_json(run_dir / "RUN_REQUEST.json", req.to_dict())
    aeb._atomic_write_json(run_dir / "STATE.json", {"run_state": aeb.RUN_STATE_RUNNING, "pid": 999999998,
                                                    "lease_id": lease.lease_id})
    reports = aeb.recover_pending_runs(repo)
    assert reports[0]["recovery"] == "CRASHED_NO_RESULT"
    assert aeb.lease_state(repo)["state"] == "RELEASED"
    rec = ec.read_next_action(repo, req.task_id)
    assert rec["next_action"] in ("AUTO_RETRY_AGENT_RUN", "HUMAN_AUTHORITY_REQUIRED")


# --- 13. Human Authority never launches a worker -------------------------------

def test_human_authority_action_does_not_launch_worker(repo):
    req = _request(repo, human_authority_constraints=("VERIFICATION_SIGNOFF_REQUIRED",))
    out = aeb.launch_worker(repo, req, _popen=_fake_popen_factory())
    assert out["launched"] is False and out["refusal"] == "HUMAN_GATE"
    assert out["authority_type"] == "VERIFICATION_SIGNOFF_REQUIRED"
    events = [e["event"] for e in aeb.read_audit_trace(repo, out["agent_run_id"])]
    assert "WORKER_LAUNCHED" not in events and "HUMAN_GATE_REFUSED_LAUNCH" in events


def test_blocking_human_gate_ignores_unrecognized_constraints(repo):
    req = _request(repo, human_authority_constraints=("SOME_OTHER_TAG",))
    assert req.blocking_human_gate() is None


# --- 14. External result triggers a worker without a user "continue" ----------

def test_external_result_can_trigger_claude_worker_without_user_continue(repo):
    """The full chain this capability exists for: a consumed FAIL result's
    resolved NEXT_ACTION is read back and used to build+launch a real
    AgentRunRequest -- no human message of any kind sits between them."""
    next_action = ec.resolve_next_action("RESULT_CONSUMED")
    assert next_action.auto_actionable is True
    req = _request(repo, action_id=next_action.next_action)
    out, outcome = _launch_and_monitor(repo, req, process_kwargs=dict(stdout_text=_envelope(aeb.RUN_STATUS_PASS)))
    assert out["launched"] is True and outcome["run_state"] == aeb.RUN_STATE_COMPLETED
    assert outcome["next_action"]["auto_actionable"] is True  # continues automatically again


# --- 15. Status reporter is read-only ------------------------------------------

def test_status_reporting_does_not_mutate_execution_state(repo):
    req = _request(repo)
    out, _ = _launch_and_monitor(repo, req, process_kwargs=dict(stdout_text=_envelope(aeb.RUN_STATUS_PASS)))
    run_dir = aeb._run_dir(repo, out["agent_run_id"])
    before = {p.name: p.stat().st_mtime_ns for p in run_dir.iterdir()}
    before_bytes = {p.name: p.read_bytes() for p in run_dir.iterdir()}
    for _ in range(3):
        aeb.status_report(repo)
    after = {p.name: p.stat().st_mtime_ns for p in run_dir.iterdir()}
    after_bytes = {p.name: p.read_bytes() for p in run_dir.iterdir()}
    assert before == after and before_bytes == after_bytes
    assert set(before) == set(after)


def test_status_report_reflects_active_and_completed_runs(repo):
    req = _request(repo, timeout_policy_seconds=999.0)
    out = aeb.launch_worker(repo, req, _popen=_fake_popen_factory(never_exits=True))
    rep = aeb.status_report(repo)
    assert out["agent_run_id"] in rep["ACTIVE_AGENT_RUNS"]
    assert rep["AGENT_BACKEND_STATUS"] == "ACTIVE"
    assert rep["MUTATION_LEASE_STATE"] == "HELD"


def test_result_ingestion_status_report_is_also_read_only(repo):
    import dv_harness.model_handoff_workflow as wf
    import dv_harness.result_ingestion as ri
    from dv_harness.model_handoff import build_handoff
    from dv_harness.model_result import to_markdown as r_to, ModelResultV1

    h = build_handoff(repo, task_id="T-STATUS", task_type="review-route", target_model="codex", project_id="P",
                      objective="x", scope=_scope(task_id="T-STATUS"), input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)
    rp = repo / ".dv-harness/model_handoffs/T-STATUS/RESULT_V1.md"
    rp.write_text(r_to(ModelResultV1(result_version="1.0", task_id="T-STATUS", producer_model="codex",
                                     task_type="review-route", result_status="FAIL", claims=["c"], findings=["f"],
                                     evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"])),
                  encoding="utf-8")
    wf.import_result(repo, "T-STATUS", rp)
    task_dir = repo / ".dv-harness/model_handoffs/T-STATUS"
    before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in task_dir.iterdir() if p.is_file()}
    for _ in range(3):
        ri.status_report(repo)
    after = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in task_dir.iterdir() if p.is_file()}
    assert before == after


# --- ownership / constants sanity ----------------------------------------------

def test_ownership_table_names_claude_as_the_worker_not_the_authority():
    assert "IMPLEMENTATION" in aeb.OWNERSHIP["CLAUDE"]
    assert "AUTHORITY" in aeb.OWNERSHIP["HUMAN"]


def test_human_gate_constraints_match_the_requirements_doc_list():
    assert set(aeb.HUMAN_GATE_CONSTRAINTS) == {
        "HUMAN_DECISION_REQUIRED", "DESIGN_AUTHORITY_REQUIRED", "VERIFICATION_AUTHORITY_REQUIRED",
        "VERIFICATION_SIGNOFF_REQUIRED", "ARCHITECTURE_AUTHORITY_REQUIRED", "SECURITY_SCOPE_EXPANSION",
        "ACCESS_AUTHORIZATION_REQUIRED",
    }
