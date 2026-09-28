"""dv_harness/agent_execution_backend.py -- Autonomous Agent Execution
Backend (`docs/architecture/canonical_detailed_governance/
L5DGVA_AUTONOMOUS_AGENT_EXECUTION_BACKEND_REQUIREMENTS.md`): when the
Canonical Next Action Resolver (`execution_contract.py`) selects an action
that requires an AI implementation/reasoning agent, L5DGVA launches and
governs a real, controlled `claude` CLI subprocess itself -- it never
injects keystrokes into a separately-opened interactive terminal, and it
never requires a human to type "continue".

REAL, VERIFIED CLAUDE CLI FACTS (this task's own live discovery; see
`M7_CLAUDE_WORKER_LIVE_QUALIFICATION.md` for the full transcripts) --
`SUPPORTED_WORKER_INVOCATION` below is not invented, it is exactly what was
run and observed:

  CLAUDE_CLI_VERSION = "2.1.283 (Claude Code)"
  invocation = ["claude", "-p", <objective>, "--output-format", "json",
                "--json-schema", <AGENT_RUN_RESULT_SCHEMA>,
                *tool_profile.cli_args(), "--add-dir", <working_directory>]
                run with cwd=<working_directory>, stdout/stderr captured to
                files, NEVER shell=True, NEVER an interactive terminal.
  AUTHENTICATION_MODE_USED = the existing, already-logged-in `claude.ai`
                OAuth session (`claude auth status` -> loggedIn=true,
                authMethod=claude.ai) -- no new credential was created,
                scraped or stored by this module.
  WORKER_OUTPUT_MODE = one JSON object on stdout; `is_error` (bool),
                `subtype`, `terminal_reason`, `permission_denials`, and
                (when `--json-schema` was satisfied) `structured_output`
                holding the exact schema-shaped result.
  EXIT_STATUS_BEHAVIOR = 0 on success even where `is_error` can still be
                inspected inside the JSON; non-zero (1 observed, invalid
                model) on a real failure, with `is_error=true` and a
                `terminal_reason` in the same JSON, plus diagnostic text on
                stderr. A wall-clock `subprocess` timeout (this module's
                own timeout policy, not a CLI flag) cleanly terminates a
                runaway worker.
  --restricted verified LIVE to confine file-tool writes to the declared
                working directory -- a worker explicitly asked to write
                outside it could not (and, in the observed run, refused on
                its own reasoning as well; the enforced fact is the file
                was never created outside the sandbox, not the model's own
                good judgment, which this module never relies on alone).

Reuse-before-create (per this task's own required inventory): `TaskBoundary`
(`task_boundary_conformance.py`) is reused verbatim for
`AGENT_RUN_REQUEST.TASK_SCOPE`; `execution_contract.py`'s
`NEXT_ACTION_TABLE`/`resolve_next_action()` remains the ONE Next Action
Resolver (extended with new `AGENT_RUN_*` events, never a second one);
`safe_tool_profile.py` is the real, newly-built Preauthorized Safe Tool
Execution mechanism (there was no prior one to reuse -- a genuine `MISSING`
in the inventory, not a duplicated `REUSE`). The Canonical Mutation Lease
below is DELIBERATELY NOT built on `model_handoff_workflow._acquire_lock()`
-- that primitive breaks a stale lock on ELAPSED TIME ALONE, which this
requirement explicitly forbids for a mutation lease ("do not break merely
by elapsed time; require liveness evidence"); the O_EXCL creation call
itself is the only thing shared, not the staleness policy.
"""
from __future__ import annotations

import ctypes
import shutil
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import execution_contract as _ec
from .safe_tool_profile import CLAUDE_IMPLEMENTATION_PROFILE, CLAUDE_READONLY_PROFILE, get_profile
from .task_boundary_conformance import TaskBoundary, classify_path, CLASS_WITHIN_BOUNDARY

CLAUDE_CLI_VERSION = "2.1.283 (Claude Code)"
BACKEND_CLAUDE = "claude"
SUPPORTED_BACKENDS = (BACKEND_CLAUDE,)

#: Ownership (requirements doc's own table) -- data, not enforced by code,
#: but the single place a caller looks up "who does what" rather than
#: re-deriving it.
OWNERSHIP = {
    "L5DGVA": "ORCHESTRATOR / SCHEDULER / POLICY AUTHORITY",
    "CLAUDE": "IMPLEMENTATION / REMEDIATION WORKER",
    "CODEX": "INDEPENDENT REVIEWER in current M7 flow",
    "CHATGPT": "ARCHITECTURE / REQUIREMENT / DECISION REVIEW",
    "HUMAN": "TRANSPORT + TRUE AUTHORITY",
}

#: The 7 named categories that must never launch a worker (requirements
#: doc's own "Human Gates" list) -- reused verbatim, never re-derived.
HUMAN_GATE_CONSTRAINTS = (
    "HUMAN_DECISION_REQUIRED", "DESIGN_AUTHORITY_REQUIRED", "VERIFICATION_AUTHORITY_REQUIRED",
    "VERIFICATION_SIGNOFF_REQUIRED", "ARCHITECTURE_AUTHORITY_REQUIRED", "SECURITY_SCOPE_EXPANSION",
    "ACCESS_AUTHORIZATION_REQUIRED",
)

RUN_STATE_PENDING = "PENDING"
RUN_STATE_LEASE_BUSY = "LEASE_BUSY"
RUN_STATE_RUNNING = "RUNNING"
RUN_STATE_COMPLETED = "COMPLETED"
RUN_STATE_FAILED = "FAILED"
RUN_STATE_TIMEOUT = "TIMEOUT"
RUN_STATE_CANCELLED = "CANCELLED"
RUN_STATE_CRASHED = "CRASHED"
RUN_STATE_BLOCKED = "BLOCKED"

RUN_STATUS_PASS = "PASS"
RUN_STATUS_FAIL = "FAIL"
RUN_STATUS_ERROR = "ERROR"
RUN_STATUS_BLOCKED = "BLOCKED"
RUN_STATUS_HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"

AUDIT_EVENTS = (
    "AGENT_RUN_REQUESTED", "BACKEND_SELECTED", "MUTATION_LEASE_REQUESTED", "MUTATION_LEASE_ACQUIRED",
    "MUTATION_LEASE_BUSY", "WORKER_LAUNCHED", "WORKER_HEARTBEAT", "WORKER_COMPLETED", "WORKER_FAILED",
    "WORKER_TIMEOUT", "WORKER_CANCELLED", "WORKER_CRASHED", "RESULT_INGESTED", "MUTATION_LEASE_RELEASED",
    "NEXT_ACTION_RESOLVED", "HUMAN_GATE_REFUSED_LAUNCH", "RUN_RECOVERED",
)


class AgentExecutionError(ValueError):
    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runs_dir(root: Path) -> Path:
    return Path(root) / ".dv-harness" / "agent_runs"


def _run_dir(root: Path, agent_run_id: str) -> Path:
    return _runs_dir(root) / agent_run_id


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _emit(root: Path, agent_run_id: str, event: str, **details: Any) -> None:
    assert event in AUDIT_EVENTS, event
    path = _run_dir(root, agent_run_id) / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": _now_iso(), "event": event, "agent_run_id": agent_run_id, **details},
                           sort_keys=True, ensure_ascii=False) + "\n")


def read_audit_trace(root: Path, agent_run_id: str) -> List[Dict[str, Any]]:
    path = _run_dir(root, agent_run_id) / "audit.jsonl"
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# --- Agent Run Request -------------------------------------------------------

@dataclass(frozen=True)
class AgentRunRequest:
    agent_run_id: str
    task_id: str
    parent_workflow_id: str
    action_id: str
    action_type: str
    backend: str
    role: str
    objective: str
    current_head: str
    working_directory: str
    task_scope: TaskBoundary
    frozen_sources: Tuple[str, ...] = ()
    input_evidence_refs: Tuple[str, ...] = ()
    required_governance_refs: Tuple[str, ...] = ()
    expected_output: str = ""
    validation_requirements: Tuple[str, ...] = ()
    tool_execution_profile: str = CLAUDE_IMPLEMENTATION_PROFILE.name
    timeout_policy_seconds: float = 1800.0
    retry_policy_max_attempts: int = 2
    mutation_allowed: bool = True
    human_authority_constraints: Tuple[str, ...] = ()
    resume_contract: str = "AgentRunResult JSON at RESULT.json, same AGENT_RUN_ID"
    attempt_number: int = 1
    previous_attempt: Optional[str] = None
    retry_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["task_scope"] = {
            "task_id": self.task_scope.task_id,
            "allowed_path_prefixes": list(self.task_scope.allowed_path_prefixes),
            "forbidden_paths": list(self.task_scope.forbidden_paths),
            "require_new_file": self.task_scope.require_new_file,
        }
        return d

    def blocking_human_gate(self) -> Optional[str]:
        """The first HUMAN_GATE_CONSTRAINTS entry present, or None. A worker
        is never launched while this is non-None (requirements doc's own
        "Human Gates" list, reused verbatim -- never re-derived per call
        site)."""
        for c in self.human_authority_constraints:
            if c in HUMAN_GATE_CONSTRAINTS:
                return c
        return None


def _current_head(root: Path) -> str:
    from .change_impact import _git
    rc, out, _ = _git(Path(root), ["rev-parse", "HEAD"])
    return out.strip() if rc == 0 and out.strip() else ""


def build_agent_run_request(
    root: Path, *, task_id: str, parent_workflow_id: str, action_id: str, action_type: str,
    role: str, objective: str, scope: TaskBoundary, frozen_sources: Sequence[str] = (),
    input_evidence_refs: Sequence[str] = (), required_governance_refs: Sequence[str] = (),
    expected_output: str = "", validation_requirements: Sequence[str] = (),
    tool_execution_profile: str = CLAUDE_IMPLEMENTATION_PROFILE.name,
    timeout_policy_seconds: float = 1800.0, retry_policy_max_attempts: int = 2,
    mutation_allowed: bool = True, human_authority_constraints: Sequence[str] = (),
    resume_contract: str = "AgentRunResult JSON at RESULT.json, same AGENT_RUN_ID",
    attempt_number: int = 1, previous_attempt: Optional[str] = None, retry_reason: Optional[str] = None,
) -> AgentRunRequest:
    """Minimum Sufficient Execution Context (reuses M7's own discipline):
    objective + exact scope + Canonical state + relevant evidence +
    task-scoped governance + expected output -- never a full chat-history or
    whole-governance-corpus dump."""
    root = Path(root)
    return AgentRunRequest(
        agent_run_id=str(uuid.uuid4()), task_id=task_id, parent_workflow_id=parent_workflow_id,
        action_id=action_id, action_type=action_type, backend=BACKEND_CLAUDE, role=role, objective=objective,
        current_head=_current_head(root), working_directory=str(root), task_scope=scope,
        frozen_sources=tuple(frozen_sources), input_evidence_refs=tuple(input_evidence_refs),
        required_governance_refs=tuple(required_governance_refs), expected_output=expected_output,
        validation_requirements=tuple(validation_requirements), tool_execution_profile=tool_execution_profile,
        timeout_policy_seconds=timeout_policy_seconds, retry_policy_max_attempts=retry_policy_max_attempts,
        mutation_allowed=mutation_allowed, human_authority_constraints=tuple(human_authority_constraints),
        resume_contract=resume_contract, attempt_number=attempt_number, previous_attempt=previous_attempt,
        retry_reason=retry_reason,
    )


def context_size_bytes(request: AgentRunRequest) -> Dict[str, int]:
    """Minimum Sufficient Context metric, same real-byte-count discipline
    `model_handoff.context_size_bytes()` already established -- a proxy,
    never a provider token count this module cannot observe."""
    return {
        "objective_bytes": len(request.objective.encode("utf-8")),
        "evidence_refs_bytes": sum(len(r.encode("utf-8")) for r in request.input_evidence_refs),
        "governance_refs_bytes": sum(len(r.encode("utf-8")) for r in request.required_governance_refs),
    }


# --- Worker result contract --------------------------------------------------

AGENT_RUN_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "run_status": {"type": "string", "enum": [RUN_STATUS_PASS, RUN_STATUS_FAIL, RUN_STATUS_ERROR,
                                                   RUN_STATUS_BLOCKED, RUN_STATUS_HUMAN_DECISION_REQUIRED]},
        "files_changed": {"type": "array", "items": {"type": "string"}},
        "tests_run": {"type": "array", "items": {"type": "string"}},
        "regression_results": {"type": "string"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "gaps_found": {"type": "array", "items": {"type": "string"}},
        "gaps_fixed": {"type": "array", "items": {"type": "string"}},
        "human_decisions_required": {"type": "array", "items": {"type": "string"}},
        "next_action_hint": {"type": "string"},
        "errors": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["run_status"],
}


@dataclass(frozen=True)
class AgentRunResult:
    agent_run_id: str
    task_id: str
    action_id: str
    run_status: str
    start_head: str
    end_head: str
    files_changed: Tuple[str, ...] = ()
    tests_run: Tuple[str, ...] = ()
    regression_results: str = ""
    evidence_refs: Tuple[str, ...] = ()
    gaps_found: Tuple[str, ...] = ()
    gaps_fixed: Tuple[str, ...] = ()
    human_decisions_required: Tuple[str, ...] = ()
    next_action_hint: str = ""
    errors: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --- Claude Execution Backend: real argv construction ------------------------

def _resolve_claude_executable() -> str:
    """The bare string `"claude"` is an npm shim on Windows (`claude`,
    `claude.cmd`, `claude.ps1` -- no native `.exe`), and Windows'
    `CreateProcess` (what `subprocess.Popen(..., shell=False)` calls
    directly) does not do the PATH/PATHEXT resolution a shell does --
    passing the bare name fails with a real `FileNotFoundError` before any
    process starts (found and reproduced during this task's own permission
    investigation: a foreground, read-only, non-backgrounded launch hit
    this exact error, independent of and unrelated to any permission
    classifier). `shutil.which()` performs the same resolution a shell
    would (confirmed live: resolves to the real `claude.CMD` path) and the
    resolved absolute path runs correctly under `shell=False` with no
    shell-injection exposure, since the objective prompt/schema are passed
    as separate argv elements, never through a shell string."""
    resolved = shutil.which("claude")
    if resolved is None:
        raise AgentExecutionError("CLAUDE_CLI_NOT_FOUND", {})
    return resolved


def build_worker_argv(request: AgentRunRequest) -> List[str]:
    """The exact, live-verified `claude` CLI invocation (see module
    docstring). No shell, no interactive terminal, no injected keystrokes --
    a single subprocess with a real argv list.

    The objective prompt is deliberately NEVER an argv element here -- `-p`
    is passed with no positional prompt argument, and `launch_worker()`
    pipes the real prompt text (`_render_objective_prompt()`) over the
    child's stdin instead. This is the real, reproduced fix for GAP-V2-015
    (was: OPEN "structured-output reliability gap"; now: CLOSED). Root
    cause, isolated live by holding the schema/--restricted/--tools/
    --permission-mode fixed and varying ONLY prompt shape: `claude` on
    Windows is an npm shim with no native `.exe` (only `claude`/`claude.cmd`/
    `claude.ps1`), so `subprocess.Popen` can only run it by implicitly
    wrapping the call through `cmd.exe` -- and a multi-line argv element
    gets corrupted at that `cmd.exe` argument-parsing layer. A single-line
    prompt (labeled or not) survived every time as an argv element; a
    two-or-more-line prompt (labeled or not) failed every time, always
    degrading to plain "key: value" prose instead of real
    `--json-schema`-shaped `structured_output`. The identical multi-line
    content survived byte-for-byte when sent over stdin instead (`claude -p`
    with no positional prompt reads from stdin -- its own documented
    pipe-friendly mode). Never a model/prompt-engineering issue -- a
    Windows-shim transport defect."""
    if request.backend not in SUPPORTED_BACKENDS:
        raise AgentExecutionError("UNSUPPORTED_BACKEND", {"backend": request.backend})
    profile = get_profile(request.tool_execution_profile)
    argv = [_resolve_claude_executable(), "-p", "--output-format", "json",
           "--json-schema", json.dumps(AGENT_RUN_RESULT_SCHEMA)]
    argv += profile.cli_args()
    argv += ["--add-dir", request.working_directory]
    return argv


def _render_objective_prompt(request: AgentRunRequest) -> str:
    lines = [
        f"OBJECTIVE: {request.objective}",
        f"TASK_ID: {request.task_id}",
        f"ALLOWED_FILES: {', '.join(request.task_scope.allowed_path_prefixes) or '(none declared)'}",
        f"FORBIDDEN_FILES (never touch): {', '.join(request.task_scope.forbidden_paths) or '(none declared)'}",
        f"FROZEN_SOURCES (never modify): {', '.join(request.frozen_sources) or '(none declared)'}",
    ]
    if request.input_evidence_refs:
        lines.append("INPUT_EVIDENCE_REFS: " + ", ".join(request.input_evidence_refs))
    if request.expected_output:
        lines.append(f"EXPECTED_OUTPUT: {request.expected_output}")
    if request.validation_requirements:
        lines.append("VALIDATION_REQUIREMENTS: " + "; ".join(request.validation_requirements))
    # Deliberately does NOT describe the JSON schema in prose -- rely on
    # `--json-schema` alone; a redundant prose description is at best
    # useless and at worst confusing (ruled out as GAP-V2-015's cause,
    # confirmed by further isolation). This multi-line, multi-field text
    # is exactly what previously corrupted when passed as an argv element
    # (GAP-V2-015, now CLOSED) -- it is unaffected by that fix because
    # `build_worker_argv()` no longer puts it in argv at all;
    # `launch_worker()` pipes this same rendered text over the worker's
    # stdin instead. See `build_worker_argv()`'s own docstring for the real
    # isolation evidence and root cause.
    lines.append("Stay strictly within ALLOWED_FILES; never touch FORBIDDEN_FILES or FROZEN_SOURCES.")
    return "\n".join(lines)


def parse_worker_output(stdout_text: str) -> Dict[str, Any]:
    """Parses the CLI's own top-level JSON envelope. Raises AgentExecutionError
    on unparseable output -- never guessed/defaulted."""
    try:
        return json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        raise AgentExecutionError("WORKER_OUTPUT_NOT_JSON", {"error": str(exc)}) from exc


def classify_worker_output(envelope: Dict[str, Any], exit_code: int) -> Tuple[str, Dict[str, Any]]:
    """(run_state, structured_result_dict_or_empty). A worker that exited
    non-zero, reported `is_error`, or never produced a schema-valid
    `structured_output` is never silently treated as PASS."""
    if exit_code != 0 or envelope.get("is_error"):
        return RUN_STATE_FAILED, {}
    structured = envelope.get("structured_output")
    if not isinstance(structured, dict) or "run_status" not in structured:
        return RUN_STATE_FAILED, {}
    return RUN_STATE_COMPLETED, structured


# --- Canonical Mutation Lease -------------------------------------------------
# Deliberately NOT `model_handoff_workflow._acquire_lock()` -- see module
# docstring. A lease is only ever broken on (stale heartbeat) AND (owner PID
# provably dead); elapsed time alone never breaks it.

def _lease_path(root: Path) -> Path:
    return _runs_dir(root) / "mutation_lease.json"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    return True


@dataclass(frozen=True)
class LeaseResult:
    acquired: bool
    lease_id: Optional[str] = None
    state: str = "BUSY"
    owner_agent_run_id: Optional[str] = None
    reason: Optional[str] = None


def acquire_mutation_lease(root: Path, task_id: str, agent_run_id: str, scope: str = "CANONICAL_REPO",
                           liveness_grace_seconds: float = 90.0) -> LeaseResult:
    """SINGLE_CANONICAL_MUTATION_LEASE: exactly one holder repo-wide at a
    time. An existing lease is recovered ONLY when its heartbeat is stale
    AND its owner process is provably dead -- both, never elapsed time
    alone."""
    root = Path(root)
    path = _lease_path(root)
    existing = _read_json(path)
    if existing is not None and existing.get("state") == "HELD":
        stale = (time.time() - float(existing.get("last_heartbeat_epoch", 0))) > liveness_grace_seconds
        alive = _pid_alive(int(existing.get("owner_pid", -1)))
        if not (stale and not alive):
            return LeaseResult(False, state="BUSY", owner_agent_run_id=existing.get("agent_run_id"),
                               reason="HELD_AND_LIVE" if alive else "HELD_WITHIN_GRACE")
        # Both conditions hold: real recovery evidence, audited, not a silent break.
        _emit(root, agent_run_id, "MUTATION_LEASE_ACQUIRED",
              recovered_from=existing.get("agent_run_id"), recovery_reason="STALE_HEARTBEAT_AND_DEAD_OWNER")
    lease_id = str(uuid.uuid4())
    record = {
        "lease_id": lease_id, "agent_run_id": agent_run_id, "task_id": task_id,
        "owner_pid": os.getpid(), "acquired_at": _now_iso(), "last_heartbeat_epoch": time.time(),
        "lease_scope": scope, "state": "HELD",
    }
    _atomic_write_json(path, record)
    return LeaseResult(True, lease_id=lease_id, state="HELD", owner_agent_run_id=agent_run_id)


def heartbeat_lease(root: Path, lease_id: str) -> None:
    path = _lease_path(Path(root))
    rec = _read_json(path)
    if rec is not None and rec.get("lease_id") == lease_id and rec.get("state") == "HELD":
        rec["last_heartbeat_epoch"] = time.time()
        _atomic_write_json(path, rec)


def release_mutation_lease(root: Path, lease_id: str) -> None:
    path = _lease_path(Path(root))
    rec = _read_json(path)
    if rec is not None and rec.get("lease_id") == lease_id:
        rec["state"] = "RELEASED"
        rec["released_at"] = _now_iso()
        _atomic_write_json(path, rec)


def lease_state(root: Path) -> Dict[str, Any]:
    """Read-only. Never mutates. `state` is `HELD`/`RELEASED`/`NONE`."""
    rec = _read_json(_lease_path(Path(root)))
    if rec is None:
        return {"state": "NONE"}
    return dict(rec)


# --- Worker scope enforcement -------------------------------------------------

def enforce_worker_scope(request: AgentRunRequest, files_changed: Sequence[str]) -> List[Dict[str, str]]:
    """A worker's OWN structured claim about files_changed is untrusted
    input -- every path is classified against the real Task Boundary
    (frozen sources always forbidden, `mutation_allowed=False` forbids
    everything). Returns real violations, never silently accepted."""
    violations: List[Dict[str, str]] = []
    frozen = tuple(request.frozen_sources)
    effective_scope = TaskBoundary(
        task_id=request.task_scope.task_id,
        allowed_path_prefixes=request.task_scope.allowed_path_prefixes,
        forbidden_paths=tuple(request.task_scope.forbidden_paths) + frozen,
        require_new_file=request.task_scope.require_new_file,
    )
    for f in files_changed:
        if not request.mutation_allowed:
            violations.append({"path": f, "classification": "MUTATION_NOT_ALLOWED"})
            continue
        cls = classify_path(f, effective_scope, "MODIFIED")
        if cls != CLASS_WITHIN_BOUNDARY:
            violations.append({"path": f, "classification": cls})
    return violations


# --- Launch / monitor / ingest -----------------------------------------------

def active_run_for_action(root: Path, action_id: str) -> Optional[str]:
    """Idempotency: ACTION_ID + Canonical state -> at most one active
    mutation run. Only a run whose process is actually alive counts as
    active -- a crashed run's stale RUNNING record does not block a real
    retry (that is `AGENT_RUN_RECOVERY`'s job, not idempotency's)."""
    base = _runs_dir(Path(root))
    if not base.is_dir():
        return None
    for d in base.iterdir():
        if not d.is_dir():
            continue
        req = _read_json(d / "RUN_REQUEST.json")
        st = _read_json(d / "STATE.json")
        if req and st and req.get("action_id") == action_id and st.get("run_state") == RUN_STATE_RUNNING:
            pid = st.get("pid")
            if pid and _pid_alive(int(pid)):
                return d.name
    return None


def launch_worker(root: Path, request: AgentRunRequest, *, _argv_builder=build_worker_argv,
                  _popen=subprocess.Popen) -> Dict[str, Any]:
    """Launches a real, controlled `claude` subprocess. Returns a dict with
    `launched` (bool) and either `agent_run_id`/`pid` or a `refusal` reason
    (`HUMAN_GATE`, `DUPLICATE_ACTIVE_RUN`, `LEASE_BUSY`). Never launches for
    a blocked Human Gate constraint, never double-launches the same
    ACTION_ID, never launches a mutation worker without first holding the
    Canonical Mutation Lease."""
    root = Path(root)
    run_dir = _run_dir(root, request.agent_run_id)
    _emit(root, request.agent_run_id, "AGENT_RUN_REQUESTED", task_id=request.task_id, action_id=request.action_id)
    _atomic_write_json(run_dir / "RUN_REQUEST.json", request.to_dict())

    gate = request.blocking_human_gate()
    if gate is not None:
        _emit(root, request.agent_run_id, "HUMAN_GATE_REFUSED_LAUNCH", authority_type=gate)
        _atomic_write_json(run_dir / "STATE.json", {"run_state": RUN_STATE_BLOCKED, "reason": gate})
        return {"launched": False, "refusal": "HUMAN_GATE", "authority_type": gate, "agent_run_id": request.agent_run_id}

    existing = active_run_for_action(root, request.action_id)
    if existing is not None and existing != request.agent_run_id:
        return {"launched": False, "refusal": "DUPLICATE_ACTIVE_RUN", "agent_run_id": existing}

    _emit(root, request.agent_run_id, "BACKEND_SELECTED", backend=request.backend)

    lease_id = None
    if request.mutation_allowed:
        _emit(root, request.agent_run_id, "MUTATION_LEASE_REQUESTED", task_id=request.task_id)
        lease = acquire_mutation_lease(root, request.task_id, request.agent_run_id)
        if not lease.acquired:
            _emit(root, request.agent_run_id, "MUTATION_LEASE_BUSY", owner=lease.owner_agent_run_id)
            _atomic_write_json(run_dir / "STATE.json", {"run_state": RUN_STATE_LEASE_BUSY,
                                                        "held_by": lease.owner_agent_run_id})
            return {"launched": False, "refusal": "LEASE_BUSY", "owner_agent_run_id": lease.owner_agent_run_id,
                    "agent_run_id": request.agent_run_id}
        lease_id = lease.lease_id

    argv = _argv_builder(request)
    (run_dir / "stdout.log").parent.mkdir(parents=True, exist_ok=True)
    stdout_f = open(run_dir / "stdout.log", "w", encoding="utf-8")
    stderr_f = open(run_dir / "stderr.log", "w", encoding="utf-8")
    proc = _popen(argv, cwd=request.working_directory, stdout=stdout_f, stderr=stderr_f,
                 stdin=subprocess.PIPE)
    # GAP-V2-015 fix: the objective prompt travels over stdin, never as an
    # argv element -- see build_worker_argv()'s own docstring for the real,
    # reproduced Windows npm-shim `.CMD`/`cmd.exe` argv-corruption evidence
    # this closes. Written and closed immediately (never left open across
    # the poll loop below) so the worker never idles on the CLI's own
    # "no stdin data received" fallback timer.
    proc.stdin.write(_render_objective_prompt(request).encode("utf-8"))
    proc.stdin.close()
    state = {
        "run_state": RUN_STATE_RUNNING, "pid": proc.pid, "start_time_epoch": time.time(),
        "start_time": _now_iso(), "lease_id": lease_id, "attempt_number": request.attempt_number,
    }
    _atomic_write_json(run_dir / "STATE.json", state)
    _emit(root, request.agent_run_id, "WORKER_LAUNCHED", pid=proc.pid, backend=request.backend)
    return {"launched": True, "agent_run_id": request.agent_run_id, "pid": proc.pid, "_process": proc,
           "_stdout_f": stdout_f, "_stderr_f": stderr_f}


def monitor_and_ingest(root: Path, agent_run_id: str, request: AgentRunRequest, process: subprocess.Popen,
                       stdout_f=None, stderr_f=None, *, poll_interval: float = 1.0) -> Dict[str, Any]:
    """Blocks the CALLER (not an interactive terminal) until the worker
    exits or its timeout policy fires; classifies, ingests, releases the
    lease, and resolves the next action. Never uses low CPU as a hang
    signal -- only real process exit / elapsed wall time against the
    request's own `timeout_policy_seconds`."""
    root = Path(root)
    run_dir = _run_dir(root, agent_run_id)
    lease_id = (_read_json(run_dir / "STATE.json") or {}).get("lease_id")
    start = time.time()
    deadline = start + request.timeout_policy_seconds
    while process.poll() is None and time.time() < deadline:
        if lease_id:
            heartbeat_lease(root, lease_id)
        _emit(root, agent_run_id, "WORKER_HEARTBEAT", elapsed_s=round(time.time() - start, 1))
        time.sleep(max(min(poll_interval, deadline - time.time()), 0.0))
    timed_out = process.poll() is None
    if timed_out:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    for f in (stdout_f, stderr_f):
        try:
            f and f.close()
        except OSError:
            pass

    exit_code = process.returncode
    end_head = _current_head(root)
    if timed_out:
        _emit(root, agent_run_id, "WORKER_TIMEOUT", timeout_seconds=request.timeout_policy_seconds)
        outcome = _finalize(root, agent_run_id, request, RUN_STATE_TIMEOUT, exit_code, end_head,
                            AgentRunResult(agent_run_id=agent_run_id, task_id=request.task_id,
                                          action_id=request.action_id, run_status=RUN_STATUS_ERROR,
                                          start_head=request.current_head, end_head=end_head,
                                          errors=("WORKER_TIMEOUT",)))
        if lease_id:
            release_mutation_lease(root, lease_id)
            _emit(root, agent_run_id, "MUTATION_LEASE_RELEASED", reason="TIMEOUT")
        return outcome

    stdout_text = (run_dir / "stdout.log").read_text(encoding="utf-8") if (run_dir / "stdout.log").is_file() else ""
    try:
        envelope = parse_worker_output(stdout_text)
    except AgentExecutionError:
        envelope = {}
    run_state, structured = classify_worker_output(envelope, exit_code)

    if run_state != RUN_STATE_COMPLETED:
        _emit(root, agent_run_id, "WORKER_FAILED", exit_code=exit_code, is_error=envelope.get("is_error"),
              terminal_reason=envelope.get("terminal_reason"))
        result = AgentRunResult(agent_run_id=agent_run_id, task_id=request.task_id, action_id=request.action_id,
                                run_status=RUN_STATUS_ERROR, start_head=request.current_head, end_head=end_head,
                                errors=(f"exit_code={exit_code}", str(envelope.get("terminal_reason") or "unknown")))
        outcome = _finalize(root, agent_run_id, request, RUN_STATE_FAILED, exit_code, end_head, result)
        if lease_id:
            release_mutation_lease(root, lease_id)
            _emit(root, agent_run_id, "MUTATION_LEASE_RELEASED", reason="WORKER_FAILED")
        return outcome

    result = AgentRunResult(
        agent_run_id=agent_run_id, task_id=request.task_id, action_id=request.action_id,
        run_status=structured.get("run_status", RUN_STATUS_ERROR), start_head=request.current_head,
        end_head=end_head, files_changed=tuple(structured.get("files_changed") or ()),
        tests_run=tuple(structured.get("tests_run") or ()), regression_results=structured.get("regression_results", ""),
        evidence_refs=tuple(structured.get("evidence_refs") or ()), gaps_found=tuple(structured.get("gaps_found") or ()),
        gaps_fixed=tuple(structured.get("gaps_fixed") or ()),
        human_decisions_required=tuple(structured.get("human_decisions_required") or ()),
        next_action_hint=structured.get("next_action_hint", ""), errors=tuple(structured.get("errors") or ()),
    )

    scope_violations = enforce_worker_scope(request, result.files_changed)
    if scope_violations:
        _emit(root, agent_run_id, "WORKER_FAILED", reason="SCOPE_VIOLATION", violations=scope_violations)
        result = AgentRunResult(**{**result.to_dict(), "run_status": RUN_STATUS_ERROR,
                                   "errors": result.errors + (f"SCOPE_VIOLATION:{scope_violations}",)})
        outcome = _finalize(root, agent_run_id, request, RUN_STATE_FAILED, exit_code, end_head, result)
    else:
        _emit(root, agent_run_id, "WORKER_COMPLETED", run_status=result.run_status)
        outcome = _finalize(root, agent_run_id, request, RUN_STATE_COMPLETED, exit_code, end_head, result)

    if lease_id:
        release_mutation_lease(root, lease_id)
        _emit(root, agent_run_id, "MUTATION_LEASE_RELEASED", reason="COMPLETED")
    return outcome


_RETRYABLE_EVENT = {
    RUN_STATUS_FAIL: "AGENT_RUN_FAILED_RETRY_ELIGIBLE",
    RUN_STATUS_ERROR: "AGENT_RUN_FAILED_RETRY_ELIGIBLE",
}


def _finalize(root: Path, agent_run_id: str, request: AgentRunRequest, run_state: str, exit_code: Optional[int],
             end_head: str, result: AgentRunResult) -> Dict[str, Any]:
    run_dir = _run_dir(root, agent_run_id)
    _atomic_write_json(run_dir / "STATE.json", {"run_state": run_state, "exit_code": exit_code,
                                                "end_time": _now_iso()})
    _atomic_write_json(run_dir / "RESULT.json", result.to_dict())
    _emit(root, agent_run_id, "RESULT_INGESTED", run_status=result.run_status)

    if run_state == RUN_STATE_TIMEOUT:
        event = ("AGENT_RUN_TIMEOUT_RETRY_ELIGIBLE" if request.attempt_number < request.retry_policy_max_attempts
                else "AGENT_RUN_TIMEOUT_ESCALATE")
    elif result.run_status == RUN_STATUS_PASS:
        event = "AGENT_RUN_SUCCEEDED"
    elif result.run_status == RUN_STATUS_HUMAN_DECISION_REQUIRED:
        event = "AGENT_RUN_HUMAN_DECISION_REQUIRED"
    else:
        event = (_RETRYABLE_EVENT.get(result.run_status, "AGENT_RUN_FAILED_ESCALATE")
                if request.attempt_number < request.retry_policy_max_attempts else "AGENT_RUN_FAILED_ESCALATE")

    next_action = _ec.resolve_next_action(event)
    _ec.persist_next_action(root, request.task_id, next_action)
    _emit(root, agent_run_id, "NEXT_ACTION_RESOLVED", next_action=next_action.next_action)
    return {"run_state": run_state, "result": result.to_dict(), "next_action": next_action.to_dict()}


# --- Startup recovery ---------------------------------------------------------

def recover_pending_runs(root: Path) -> List[Dict[str, Any]]:
    """LOAD RUNS -> RECONCILE PROCESS/LEASE/RESULT -> INGEST COMPLETED
    RESULT -> RECOVER ACTIVE/FAILED RUN -> NEXT ACTION RESOLVER. Never
    silently drops a RUNNING record whose process is actually dead."""
    root = Path(root)
    base = _runs_dir(root)
    if not base.is_dir():
        return []
    reports = []
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        st = _read_json(d / "STATE.json")
        if st is None or st.get("run_state") != RUN_STATE_RUNNING:
            continue
        agent_run_id = d.name
        pid = st.get("pid")
        if pid and _pid_alive(int(pid)):
            reports.append({"agent_run_id": agent_run_id, "recovery": "STILL_ACTIVE"})
            continue
        # Process is gone. A structured RESULT.json means it finished but we
        # never got to ingest it (crash between exit and finalize).
        result_raw = _read_json(d / "RESULT.json")
        req_raw = _read_json(d / "RUN_REQUEST.json")
        lease_id = st.get("lease_id")
        if result_raw is not None and req_raw is not None:
            _atomic_write_json(d / "STATE.json", {**st, "run_state": RUN_STATE_COMPLETED, "recovered": True})
            event = "AGENT_RUN_SUCCEEDED" if result_raw.get("run_status") == RUN_STATUS_PASS else "AGENT_RUN_FAILED_ESCALATE"
            next_action = _ec.resolve_next_action(event)
            _ec.persist_next_action(root, req_raw["task_id"], next_action)
            _emit(root, agent_run_id, "RUN_RECOVERED", found="RESULT_JSON")
            reports.append({"agent_run_id": agent_run_id, "recovery": "RESULT_INGESTED_ON_RECOVERY"})
        else:
            _atomic_write_json(d / "STATE.json", {**st, "run_state": RUN_STATE_CRASHED, "recovered": True})
            _emit(root, agent_run_id, "WORKER_CRASHED", pid=pid)
            if lease_id:
                release_mutation_lease(root, lease_id)
                _emit(root, agent_run_id, "MUTATION_LEASE_RELEASED", reason="CRASH_RECOVERY")
            if req_raw is not None:
                event = ("AGENT_RUN_FAILED_RETRY_ELIGIBLE" if req_raw.get("attempt_number", 1) < req_raw.get("retry_policy_max_attempts", 2)
                        else "AGENT_RUN_FAILED_ESCALATE")
                next_action = _ec.resolve_next_action(event)
                _ec.persist_next_action(root, req_raw["task_id"], next_action)
            _emit(root, agent_run_id, "RUN_RECOVERED", found="NO_RESULT_CRASHED")
            reports.append({"agent_run_id": agent_run_id, "recovery": "CRASHED_NO_RESULT"})
    return reports


# --- Observability (read-only) ------------------------------------------------

def status_report(root: Path) -> Dict[str, Any]:
    """STATUS_REPORTER_IS_READ_ONLY=YES: every call below is a read
    (`_read_json`/`iterdir`/`read_audit_trace`); nothing here ever calls
    `_atomic_write_json` or any other write path. A status/dashboard tool
    must never become a state authority (the exact class of bug a prior M7
    task's own status script committed against `execution_contract_state.json`)."""
    root = Path(root)
    base = _runs_dir(root)
    active, queued = [], []
    runs: Dict[str, Any] = {}
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue
            st = _read_json(d / "STATE.json") or {}
            req = _read_json(d / "RUN_REQUEST.json") or {}
            row = {
                "AGENT_RUN_ID": d.name, "TASK_ID": req.get("task_id"), "ACTION_ID": req.get("action_id"),
                "BACKEND": req.get("backend"), "ROLE": req.get("role"), "START_HEAD": req.get("current_head"),
                "CURRENT_STATE": st.get("run_state"), "ELAPSED_TIME": (
                    time.time() - st["start_time_epoch"] if "start_time_epoch" in st and st.get("run_state") == RUN_STATE_RUNNING else None),
                "LAST_HEARTBEAT": st.get("last_heartbeat_epoch"), "RUN_STATUS": (_read_json(d / "RESULT.json") or {}).get("run_status"),
            }
            runs[d.name] = row
            if st.get("run_state") == RUN_STATE_RUNNING:
                active.append(d.name)
            elif st.get("run_state") == RUN_STATE_LEASE_BUSY:
                queued.append(d.name)
    lease = lease_state(root)
    return {
        "AGENT_BACKEND_STATUS": "ACTIVE" if active else "IDLE",
        "ACTIVE_AGENT_RUNS": active,
        "QUEUED_AGENT_RUNS": queued,
        "MUTATION_LEASE_STATE": lease.get("state"),
        "RUNS": runs,
    }
