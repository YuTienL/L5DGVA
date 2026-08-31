"""lsf_client.py — subprocess wrappers around bsub/bjobs/bkill plus
reconciliation between agent-reported per-job JSON state and live LSF truth.

Field names/types follow .dv-harness/lsf/job_state_schema.json exactly.
Per-job state files live at .dv-harness/lsf/jobs/<JOB_ID>.json (one file
per submitted LSF job = one isolated Job Agent context, per
regression-agent.md v16.1/v19.1 and CLAUDE.md core rules).
"""

from __future__ import annotations
import subprocess, json, hashlib, re, time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Literal

JOBS_DIR_NAME = (".dv-harness", "lsf", "jobs")
EARLY_FAIL_POLICY_PATH = (".dv-harness", "lsf", "early_fail_policy.json")

LsfStatus = Literal["PEND", "RUN", "DONE", "EXIT", "KILLED",
                     "MEMLIMIT", "TIMEOUT", "LICENSE_WAIT", "UNKNOWN"]

_BJOBS_STAT_MAP = {
    "PEND": "PEND", "PROV": "PEND", "WAIT": "PEND",
    "PSUSP": "PEND", "USUSP": "PEND", "SSUSP": "PEND",
    "RUN": "RUN",
    "DONE": "DONE",
    "EXIT": "EXIT",
    "UNKWN": "UNKNOWN", "ZOMBI": "UNKNOWN",
}

_JOB_STATE_FIELDS = None  # populated below JobState definition


class LsfUnavailableError(RuntimeError):
    pass


@dataclass
class JobState:
    job_id: Optional[int] = None
    regression_id: Optional[str] = None
    pattern: Optional[str] = None
    options: Optional[str] = None
    run_dir: Optional[str] = None
    sim_log: Optional[str] = None
    lsf_status: str = "UNKNOWN"
    sim_status: str = "UNKNOWN"
    last_log_offset: int = 0
    uvm_error_count: int = 0
    uvm_fatal_count: int = 0
    assertion_failure: bool = False
    simulator_crash: bool = False
    terminal_signature: Optional[str] = None
    early_kill: bool = False
    kill_reason: Optional[str] = None
    root_cause_status: str = "NOT_STARTED"
    fix_proposal_status: str = "NOT_STARTED"
    git_sha: Optional[str] = None
    server_sha: Optional[str] = None
    last_change_time: Optional[str] = None
    state_fingerprint: Optional[str] = None

    def fingerprint(self) -> str:
        d = asdict(self)
        d.pop("state_fingerprint", None)
        d.pop("last_change_time", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


_JOB_STATE_FIELDS = set(JobState.__dataclass_fields__.keys())


@dataclass
class Discrepancy:
    job_id: int
    field: str
    reported: object
    live: object
    severity: Literal["INFO", "WARN", "CRITICAL"]


def _jobs_dir(root: Path) -> Path:
    return root.joinpath(*JOBS_DIR_NAME)


def _validate_job_id(job_id) -> int:
    if isinstance(job_id, bool) or not isinstance(job_id, int):
        raise ValueError(f"job_id must be int, got {job_id!r}")
    return job_id


def bsub_submit(command: str, *, queue: str, cores: int = 1,
                mem_mb: Optional[int] = None, run_dir: Optional[str] = None,
                extra_args: Optional[list[str]] = None) -> int:
    argv = ["bsub", "-q", queue, "-n", str(cores)]
    if mem_mb is not None:
        argv += ["-R", f"rusage[mem={mem_mb}]"]
    if run_dir:
        argv += ["-cwd", run_dir]
    if extra_args:
        argv += list(extra_args)
    argv.append(command)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as e:
        raise LsfUnavailableError(f"bsub not found on PATH: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise LsfUnavailableError(f"bsub timed out: {e}") from e
    m = re.search(r"Job <(\d+)>", proc.stdout or "")
    if not m:
        raise LsfUnavailableError(
            f"could not parse job id from bsub output: stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    return int(m.group(1))


def _run_bjobs(job_ids: list[int]) -> dict:
    argv = ["bjobs", "-json", "-o",
            "jobid stat exit_code exec_host queue run_time submit_time job_name",
            *[str(_validate_job_id(j)) for j in job_ids]]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as e:
        raise LsfUnavailableError(f"bjobs not found on PATH: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise LsfUnavailableError(f"bjobs timed out: {e}") from e
    try:
        parsed = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError) as e:
        raise LsfUnavailableError(
            f"failed to parse bjobs -json output: {e}; stdout={proc.stdout!r} stderr={proc.stderr!r}"
        ) from e
    return parsed


def bjobs_query(job_id: int) -> dict:
    parsed = _run_bjobs([job_id])
    records = parsed.get("RECORDS") or []
    if not records:
        return {"JOBID": str(job_id), "STAT": None}
    return records[0]


def bjobs_query_many(job_ids: list[int]) -> dict:
    if not job_ids:
        return {}
    parsed = _run_bjobs(job_ids)
    records = parsed.get("RECORDS") or []
    result = {jid: {} for jid in job_ids}
    for rec in records:
        try:
            jid = int(rec.get("JOBID"))
        except (TypeError, ValueError):
            continue
        result[jid] = rec
    return result


def discover_live_jobs(vcuser: str) -> list[dict]:
    """Real LSF status for every job under `vcuser`, independent of whether
    any of them were ever submitted via this module's own bsub_submit() or
    registered via register_external_job(). Used by Part 2's reconciliation
    cycle for baseline visibility -- a job with no registered JobState still
    shows up here with RUN/DONE/EXIT/PEND status."""
    argv = ["bjobs", "-u", vcuser, "-json", "-o",
            "jobid stat queue exec_host job_name submit_time"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as e:
        raise LsfUnavailableError(f"bjobs not found on PATH: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise LsfUnavailableError(f"bjobs timed out: {e}") from e
    try:
        parsed = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError) as e:
        raise LsfUnavailableError(
            f"failed to parse bjobs -json output: {e}; stdout={proc.stdout!r} stderr={proc.stderr!r}"
        ) from e
    records = parsed.get("RECORDS") or []
    result = []
    for rec in records:
        try:
            jid = int(rec.get("JOBID"))
        except (TypeError, ValueError):
            continue
        result.append({
            "job_id": jid,
            "stat": rec.get("STAT") or "",
            "queue": rec.get("QUEUE") or "",
            "exec_host": rec.get("EXEC_HOST") or "",
            "job_name": rec.get("JOB_NAME") or "",
            "submit_time": rec.get("SUBMIT_TIME") or "",
        })
    return result


def map_bjobs_stat_to_lsf_status(raw_stat: Optional[str]) -> str:
    if not raw_stat:
        return "UNKNOWN"
    return _BJOBS_STAT_MAP.get(raw_stat, "UNKNOWN")


def bkill_job(job_id: int, *, verify: bool = True, poll_timeout_s: int = 30) -> bool:
    jid = _validate_job_id(job_id)
    try:
        proc = subprocess.run(["bkill", str(jid)], capture_output=True, text=True, timeout=30)
    except FileNotFoundError as e:
        raise LsfUnavailableError(f"bkill not found on PATH: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise LsfUnavailableError(f"bkill timed out: {e}") from e
    if proc.returncode != 0:
        return False
    if not verify:
        return True
    deadline = time.monotonic() + poll_timeout_s
    while time.monotonic() < deadline:
        rec = bjobs_query(jid)
        status = map_bjobs_stat_to_lsf_status(rec.get("STAT"))
        if status in ("EXIT", "DONE", "UNKNOWN"):
            return True
        time.sleep(2)
    return False


def load_early_fail_policy(root: Path) -> dict:
    """Read .dv-harness/lsf/early_fail_policy.json (see EARLY_FAIL_POLICY_PATH).

    Missing/unreadable file returns {} rather than raising -- evaluate_auto_kill()
    treats every kill_on_* toggle as disabled (via dict.get(key, False)) when the
    key is absent, so an empty policy is the conservative "auto-kill fires on
    nothing" state, never a fabricated default policy.
    """
    path = root.joinpath(*EARLY_FAIL_POLICY_PATH)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def evaluate_auto_kill(state: JobState, policy: dict) -> dict:
    """Decide whether a RUNNING LSF job should be auto-killed, per the real
    .dv-harness/lsf/early_fail_policy.json schema (uvm_error_threshold,
    kill_on_uvm_fatal, kill_on_uvm_error_above_threshold, kill_on_fatal_assertion,
    kill_on_simulator_crash, kill_on_explicit_fail_marker, allowlist) -- see
    LSF_PER_JOB_AGENT_MONITORING_v16_1.md's "Early-Fail" section and the
    lsf-early-fail-stop skill for the documented terminal triggers this mirrors.

    Reads only fields already on JobState (uvm_fatal_count, uvm_error_count,
    assertion_failure, simulator_crash, terminal_signature) -- the same
    marker-derived state job_state_schema.json already defines and that some
    other stage (e.g. the per-job monitor gate) is responsible for populating
    from real sim.log evidence. This function does not itself grep log text.

    Deliberately NOT implemented: a stall/no-progress-for-N-seconds trigger.
    early_fail_policy.json defines no elapsed-runtime/last-progress threshold
    key as of this writing, and this function must never kill on a guessed
    default -- so stall-based auto-kill stays off until the policy schema
    actually grows such a key; only an unambiguous per-job marker/flag already
    present in JobState can trigger a kill here.

    Returns {"should_kill": bool, "reason": str} -- reason is always populated,
    including the negative case ("NO_AUTO_KILL_TRIGGER_CONDITION_MET").
    """
    if state.lsf_status != "RUN":
        return {"should_kill": False, "reason": f"JOB_NOT_RUNNING (lsf_status={state.lsf_status})"}

    allowlist = policy.get("allowlist") or []
    if state.pattern is not None and state.pattern in allowlist:
        return {"should_kill": False, "reason": f"PATTERN_ALLOWLISTED ({state.pattern})"}

    if policy.get("kill_on_uvm_fatal", False) and state.uvm_fatal_count > 0:
        return {"should_kill": True,
                "reason": f"UVM_FATAL_DETECTED (uvm_fatal_count={state.uvm_fatal_count})"}

    if policy.get("kill_on_fatal_assertion", False) and state.assertion_failure:
        return {"should_kill": True, "reason": "FATAL_ASSERTION_DETECTED"}

    if policy.get("kill_on_simulator_crash", False) and state.simulator_crash:
        return {"should_kill": True, "reason": "SIMULATOR_CRASH_DETECTED"}

    if policy.get("kill_on_explicit_fail_marker", False) and state.terminal_signature:
        return {"should_kill": True,
                "reason": f"EXPLICIT_FAIL_MARKER (terminal_signature={state.terminal_signature!r})"}

    if policy.get("kill_on_uvm_error_above_threshold", False):
        threshold = policy.get("uvm_error_threshold", 0)
        if state.uvm_error_count > threshold:
            return {"should_kill": True,
                    "reason": f"UVM_ERROR_COUNT_ABOVE_THRESHOLD "
                              f"(uvm_error_count={state.uvm_error_count} > threshold={threshold})"}

    return {"should_kill": False, "reason": "NO_AUTO_KILL_TRIGGER_CONDITION_MET"}


def load_job_state(root: Path, job_id: int) -> JobState:
    jid = _validate_job_id(job_id)
    path = _jobs_dir(root) / f"{jid}.json"
    if not path.exists():
        return JobState(job_id=jid)
    data = json.loads(path.read_text(encoding="utf-8"))
    kwargs = {k: v for k, v in data.items() if k in _JOB_STATE_FIELDS}
    kwargs["job_id"] = jid
    return JobState(**kwargs)


def save_job_state(root: Path, state: JobState) -> None:
    # BUG FIX (2026-08-28, gui-cli-completeness-audit / test_lsf_client.py):
    # the previous version only assigned state.state_fingerprint /
    # last_change_time inside the `if new_fp != old_fp` branch. On an
    # UNCHANGED save, state.state_fingerprint stayed at whatever the passed-in
    # (often freshly-constructed) JobState object's own field happened to be
    # -- typically None -- which then got written to disk, silently
    # overwriting the real prior fingerprint. The very next save would then
    # always see old_fp=None and treat every future save as "changed",
    # permanently defeating the idempotency this function exists for. Now the
    # correct fingerprint is always written; only last_change_time depends on
    # whether anything actually changed.
    jid = _validate_job_id(state.job_id)
    d = _jobs_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{jid}.json"
    new_fp = state.fingerprint()
    old_fp = None
    old_change_time = None
    if path.exists():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
            old_fp = prior.get("state_fingerprint")
            old_change_time = prior.get("last_change_time")
        except (json.JSONDecodeError, OSError):
            old_fp = None
            old_change_time = None
    if new_fp != old_fp:
        state.last_change_time = datetime.now(timezone.utc).isoformat()
    else:
        state.last_change_time = old_change_time
    state.state_fingerprint = new_fp
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def to_snapshot_row(state: JobState, *, agent_action: str, note: Optional[str] = None) -> dict:
    return {
        "job_id": state.job_id,
        "pattern": state.pattern,
        "lsf_status": state.lsf_status,
        "dv_analysis_status": state.sim_status,
        "uvm_error": state.uvm_error_count,
        "uvm_fatal": state.uvm_fatal_count,
        "agent_action": agent_action,
        "note": note,
    }


def reconcile_job(state: JobState, live_bjobs_record: dict, *,
                   require_exact_job_id: bool = True,
                   require_log_job_match: bool = True) -> tuple[JobState, list]:
    discrepancies: list[Discrepancy] = []
    changed = False

    raw_live_id = live_bjobs_record.get("JOBID")
    if raw_live_id is not None:
        try:
            live_id = int(raw_live_id)
        except (TypeError, ValueError):
            live_id = None
        if require_exact_job_id and live_id is not None and live_id != state.job_id:
            raise ValueError(
                f"live bjobs record job id {live_id} does not match state.job_id {state.job_id}"
            )

    live_status = map_bjobs_stat_to_lsf_status(live_bjobs_record.get("STAT"))
    if live_status != state.lsf_status:
        discrepancies.append(Discrepancy(
            job_id=state.job_id, field="lsf_status",
            reported=state.lsf_status, live=live_status, severity="WARN",
        ))
        state.lsf_status = live_status
        changed = True

    if live_status in ("DONE", "EXIT") and state.sim_status in ("UNKNOWN", "RUNNING"):
        discrepancies.append(Discrepancy(
            job_id=state.job_id, field="sim_status",
            reported=state.sim_status, live="ANALYSIS_OWED", severity="CRITICAL",
        ))

    if require_log_job_match and state.sim_log and state.job_id is not None:
        if str(state.job_id) not in state.sim_log:
            discrepancies.append(Discrepancy(
                job_id=state.job_id, field="sim_log",
                reported=state.sim_log, live=None, severity="WARN",
            ))

    if changed:
        state.state_fingerprint = state.fingerprint()
        state.last_change_time = datetime.now(timezone.utc).isoformat()

    return state, discrepancies


def _write_job_tier_memory_on_terminal_reconcile(root: Path, jid: int, state: JobState,
                                                  discrepancies: list) -> None:
    """Job-tier memory wiring (Task 9, 2026-08-31 poster-gap-closing round 2):
    reconcile_job()'s own CRITICAL "sim_status"->"ANALYSIS_OWED" discrepancy
    is the real, structurally-guaranteed signal that a submitted LSF job has
    just reached a terminal live LSF status (DONE/EXIT) with DV analysis not
    yet recorded against it -- never a fabricated trigger. Per CLAUDE.md's
    "LSF DONE is not equal to DV PASS", this persists the real LSF-level
    completion fact (never a DV verdict this function has no evidence for);
    the job_result/job_failure kind split below is itself derived only from
    real evidence already present on `state` at reconcile time (a live EXIT
    status, or an already-recorded uvm_fatal_count/assertion_failure/
    simulator_crash signal), never guessed. Naturally stops recurring once
    something downstream advances state.sim_status off UNKNOWN/RUNNING (the
    same condition that stops the CRITICAL discrepancy itself from firing).
    Best-effort, mirrors engine.py's _promote_experience_knowledge pattern:
    a persistence failure here must never break an already-completed
    reconciliation.

    IDEMPOTENCY (2026-08-31 fix wave, finding I3): unlike
    _promote_experience_knowledge (fires once per stage PASS),
    lsf-reconcile is DESIGNED to be polled repeatedly, and this CRITICAL
    discrepancy keeps firing on every reconcile_batch() call while a job
    stays stuck at sim_status UNKNOWN/RUNNING with a terminal live LSF
    status -- exactly the stuck-job case this write exists to record.
    Without a stable key, each poll minted a fresh memory_id via
    route_and_store (MemoryStore.add() only reuses an ID the caller already
    supplies -- see memory.py's `mid=mem.get("memory_id") or f"MEM-..."`),
    so 3 reconciles of the same stuck job produced 3 duplicate Job-tier
    records. Keying `memory_id` deterministically on `job_id` makes repeat
    polls of the SAME stuck job update the SAME record in place (add() is an
    upsert-by-memory_id: it overwrites the file at
    `<level>/<memory_id>.json` and replaces, not appends, that id's row in
    index.json) instead of minting a new one -- no store-API change needed,
    this only supplies the id the existing upsert behavior already keys on.
    """
    if not any(d.field == "sim_status" and d.severity == "CRITICAL" for d in discrepancies):
        return
    kind = "job_failure" if (
        state.lsf_status == "EXIT" or state.uvm_fatal_count > 0
        or state.assertion_failure or state.simulator_crash
    ) else "job_result"
    record = {
        "memory_id": f"JOB-{jid}-TERMINAL-RECONCILE",
        "kind": kind,
        "job_id": jid,
        "pattern": state.pattern,
        "scope": "regression",
        "title": f"LSF job {jid} reached {state.lsf_status} (dv_analysis_status=ANALYSIS_OWED)",
        "lsf_status": state.lsf_status,
        "dv_analysis_status": "ANALYSIS_OWED",
        "uvm_error_count": state.uvm_error_count,
        "uvm_fatal_count": state.uvm_fatal_count,
        "terminal_signature": state.terminal_signature,
    }
    try:
        from .memory_router import route_and_store
        route_and_store(root, record)
    except Exception:
        pass


def reconcile_batch(root: Path, job_ids: list[int]) -> dict:
    states = {jid: load_job_state(root, jid) for jid in job_ids}
    live = bjobs_query_many(job_ids)
    result = {}
    for jid in job_ids:
        state = states[jid]
        rec = live.get(jid, {})
        try:
            state, discrepancies = reconcile_job(state, rec)
        except ValueError as e:
            discrepancies = [Discrepancy(
                job_id=jid, field="job_id", reported=jid, live=rec.get("JOBID"),
                severity="CRITICAL",
            )]
            result[jid] = (state, discrepancies)
            continue
        save_job_state(root, state)
        _write_job_tier_memory_on_terminal_reconcile(root, jid, state, discrepancies)
        result[jid] = (state, discrepancies)
    return result
