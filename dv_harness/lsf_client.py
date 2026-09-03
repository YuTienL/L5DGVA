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
from typing import Optional
try:
    from typing import Literal
except ImportError:  # pragma: no cover - exercised for real on this
    # project's real Python 3.7 remote deployment (typing.Literal was only
    # added in Python 3.8). `from __future__ import annotations` above
    # makes ANNOTATIONS lazy (never actually executed), but this file's own
    # `LsfStatus = Literal[...]` below is a plain module-level ASSIGNMENT,
    # not an annotation -- it genuinely runs at import time regardless of
    # that future import, and genuinely needs typing.Literal to exist.
    # No new dependency (e.g. typing_extensions) is assumed to be
    # installed on that remote environment either, so this degrades to a
    # plain `str` alias on old Python -- LsfStatus was never enforced at
    # runtime anyway (grep-confirmed: no isinstance/runtime check against
    # it anywhere in this codebase), only used for static type-checker
    # precision on modern Python.
    Literal = None  # type: ignore[assignment]

JOBS_DIR_NAME = (".dv-harness", "lsf", "jobs")
EARLY_FAIL_POLICY_PATH = (".dv-harness", "lsf", "early_fail_policy.json")

if Literal is not None:
    LsfStatus = Literal["PEND", "RUN", "DONE", "EXIT", "KILLED",
                         "MEMLIMIT", "TIMEOUT", "LICENSE_WAIT", "UNKNOWN"]
else:  # pragma: no cover - real fallback path, only reachable on Python < 3.8
    LsfStatus = str

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


class _BjobsBatchUnparseable(LsfUnavailableError):
    """Raised only when a bjobs -json invocation actually ran (the binary
    was found, the call did not time out) but its stdout could not be
    parsed as JSON -- e.g. one id in the batch LSF has completely forgotten
    can corrupt the whole batch's -json output. This is a strict subclass
    of LsfUnavailableError (BUG FIX, 2026-09-01
    lsf-reconcile-terminal-status-hardening full-suite regression check):
    _run_bjobs_with_fallback() must retry per-id ONLY for this specific,
    genuinely-salvageable failure, never for the plain LsfUnavailableError
    FileNotFoundError/TimeoutExpired raise when bjobs is not on PATH at all
    or hangs. Catching every LsfUnavailableError at the fallback's outer
    try/except silently swallowed a completely-unavailable LSF toolchain --
    every per-id retry would fail identically (the binary still would not
    exist), and bjobs_query_many() would return an all-empty result instead
    of propagating the real LSF_UNAVAILABLE that dv_harness.cli surfaces to
    callers, exactly the case
    test_cli_lsf_reconcile_picks_up_existing_job_state_files
    (test_engine_gates_and_routing.py) already covers and caught this."""
    pass


@dataclass
class JobState:
    job_id: Optional[int] = None
    regression_id: Optional[str] = None
    pattern: Optional[str] = None
    options: Optional[str] = None
    run_dir: Optional[str] = None
    sim_log: Optional[str] = None
    # seed / fsdb_path (session-snapshot-extension, 2026-09-01): promoted to
    # first-class fields closing the RESIDUAL GAP the memory-engine-schema-
    # completion audit (2026-09-01, see this module's own
    # extract_seed_from_options/extract_fsdb_path_from_options and
    # _write_job_tier_memory_on_terminal_reconcile below) explicitly left
    # open -- "JobState has no dedicated seed/fsdb_path field". Real writers:
    # cli.py's `lsf-submit` (--seed/--fsdb-path, explicit at the point a
    # caller submits a job -- the moment a seed is naturally known -- or
    # auto-extracted from --options text when omitted) and
    # register_external_job() below (for a job submitted outside this
    # module's own bsub_submit(), e.g. a generated environment's own
    # Makefile-native `bsub`/lsf_regress.sh, where a caller wrapping that
    # path already knows the seed it assigned). Optional and additive: a
    # JobState loaded from an older on-disk record with neither key simply
    # gets None here (load_job_state()'s _JOB_STATE_FIELDS filter already
    # handles an absent key exactly like every other optional field).
    seed: Optional[str] = None
    fsdb_path: Optional[str] = None
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
        raise _BjobsBatchUnparseable(
            f"failed to parse bjobs -json output: {e}; stdout={proc.stdout!r} stderr={proc.stderr!r}"
        ) from e
    return parsed


def _run_bjobs_with_fallback(job_ids: list[int]) -> dict:
    """Wraps _run_bjobs() with a per-id retry when the batch call itself
    fails. A single job id LSF has completely forgotten can make the whole
    batch's -json output unparseable (BUG, 2026-09-01
    lsf-reconcile-terminal-status-hardening) -- without this, every OTHER,
    perfectly healthy job in that batch loses one full analysis cycle. This
    function never changes bjobs_query_many()'s return contract: on success
    it returns exactly what _run_bjobs() would have returned; on batch
    failure it merges the per-id fallback results into the same
    {"RECORDS": [...]} shape, and an id that still fails its own individual
    call contributes no entry to RECORDS (bjobs_query_many()'s own
    default-to-{} handling for a missing id already covers that case
    correctly, unchanged).

    Design boundary: only a _BjobsBatchUnparseable batch failure (stdout ran
    but did not parse as JSON) triggers the per-id retry -- NOT the plain
    LsfUnavailableError _run_bjobs() raises for FileNotFoundError (bjobs not
    on PATH at all) or a timeout (BUG FIX, 2026-09-01 full-suite regression
    check: an earlier version of this function caught every
    LsfUnavailableError here, which silently downgraded a completely
    unavailable LSF toolchain into an all-empty result instead of
    propagating LSF_UNAVAILABLE -- see _BjobsBatchUnparseable's own
    docstring and test_cli_lsf_reconcile_picks_up_existing_job_state_files).
    A real LSF invocation that returns a nonzero exit code but still emits
    valid, parseable JSON (e.g. some requested ids known, others long
    forgotten) never raises at all in the first place -- it already flows
    through the normal happy path, and a genuinely-missing id in that JSON
    is already handled correctly by bjobs_query_many()'s existing per-id
    default-to-{} logic, with no fallback call needed. This codebase has no
    access to a real LSF instance to confirm the exact real-world
    nonzero-but-parseable behavior beyond that (per this project's
    evidence-before-conclusion discipline, not assumed either way) -- but
    no additional handling is required here regardless of which way it
    goes, since that case never reaches this except block at all.

    Cost, stated plainly: only on a genuine batch parse failure does this
    become up to len(job_ids) additional real bjobs calls. The healthy-batch
    path (the common case) is exactly as fast as before -- one call, no
    change; and a completely-unavailable LSF toolchain still fails fast
    with a single call, exactly as it did before this function existed."""
    try:
        return _run_bjobs(job_ids)
    except _BjobsBatchUnparseable:
        pass
    records = []
    for jid in job_ids:
        try:
            single = _run_bjobs([jid])
        except LsfUnavailableError:
            continue
        records.extend(single.get("RECORDS") or [])
    return {"RECORDS": records}


def bjobs_query(job_id: int) -> dict:
    parsed = _run_bjobs([job_id])
    records = parsed.get("RECORDS") or []
    if not records:
        return {"JOBID": str(job_id), "STAT": None}
    return records[0]


def bjobs_query_many(job_ids: list[int]) -> dict:
    if not job_ids:
        return {}
    parsed = _run_bjobs_with_fallback(job_ids)
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
    shows up here with RUN/DONE/EXIT/PEND status.

    `-a` is REQUIRED, not optional (BUG FIX, 2026-09-01 whole-branch review):
    plain `bjobs -u <user>` lists only PEND/RUN/SUSPENDED jobs, so a job that
    finishes between two poll cycles vanishes from this output entirely
    instead of ever being observed in a terminal DONE/EXIT state. Since Part
    2's reconciliation cycle gates its whole log-analysis branch on
    lsf_status in ("DONE", "EXIT"), omitting `-a` meant Part 3's
    regression-list safety net structurally never fired in production. `-a`
    keeps finished jobs in the listing so that terminal transition is
    actually observable.

    TRANSPORT (deliberate, confirmed architectural assumption -- NOT a
    deviation from the spec's original `remote_exec.py` wording): this
    function, like every other subprocess call in this module
    (bsub_submit(), _run_bjobs(), bkill_job()), invokes the LSF client
    binaries LOCALLY, because dv_harness itself runs server-side on the
    Linux DV server where bsub/bjobs/bkill are natively on PATH.
    tools/remote/remote_exec.py is a different transport entirely -- it lets
    an interactive Claude Code session on a separate Windows PC reach that
    server -- and has no bearing on dv_harness's own server-side Python
    code.
    """
    argv = ["bjobs", "-u", vcuser, "-a", "-json", "-o",
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


def register_external_job(root: Path, job_id: int, *, log_path: str,
                           pattern: Optional[str] = None,
                           seed: Optional[str] = None,
                           fsdb_path: Optional[str] = None) -> None:
    """Register a job that was submitted OUTSIDE this module's own
    bsub_submit() -- e.g. a generated environment's own Makefile-native
    `bsub` -- so reconcile_batch()/save_job_state() treat it identically to
    a bsub_submit()-originated job. Writes a fresh JobState with
    lsf_status="UNKNOWN" (the next reconcile_batch() call fills in the real
    status from a live bjobs poll).

    `seed`/`fsdb_path` (session-snapshot-extension, 2026-09-01): optional,
    structural pass-throughs onto the new JobState fields -- populated only
    when the caller wrapping the external submission genuinely knows them
    (e.g. the same value it assigned to the generated environment's own
    lsf_regress.sh $SEED before invoking it), never guessed here."""
    jid = _validate_job_id(job_id)
    state = JobState(job_id=jid, pattern=pattern, sim_log=log_path,
                      seed=seed, fsdb_path=fsdb_path)
    save_job_state(root, state)


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
        "uvm_error_count": state.uvm_error_count,
        "uvm_fatal_count": state.uvm_fatal_count,
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
    # BUG FIX (2026-09-01, lsf-reconcile-terminal-status-hardening): a real,
    # previously-confirmed terminal status must outlive LSF's own retention
    # window. bjobs_query_many() returns {} (no "STAT" key at all) for a job
    # id LSF has completely forgotten -- that is an ABSENCE of information,
    # not new evidence that the job's outcome changed. Downgrading an
    # already-recorded DONE/EXIT/KILLED to UNKNOWN here previously destroyed
    # real evidence for no reason other than the tool's own bookkeeping
    # lifetime expiring -- exactly the decay CLAUDE.md's "LSF DONE is not
    # equal to DV PASS" rule exists to prevent. Scoped precisely to the
    # absent-record case: a live call that explicitly reports an ambiguous
    # real status (e.g. UNKWN/ZOMBI) for a job IS new evidence and is not
    # protected here.
    record_absent = live_bjobs_record.get("STAT") is None
    already_terminal = state.lsf_status in ("DONE", "EXIT", "KILLED")
    if record_absent and already_terminal:
        discrepancies.append(Discrepancy(
            job_id=state.job_id, field="lsf_status",
            reported=state.lsf_status, live=live_status, severity="INFO",
        ))
    elif live_status != state.lsf_status:
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


# seed/fsdb_path FALLBACK extraction (memory-engine-schema-completion audit,
# 2026-09-01; JobState/job_state_schema.json gained first-class seed/
# fsdb_path fields in the session-snapshot-extension follow-up the same
# day -- see JobState's own docstring comment). These two regexes remain as
# a fallback for a JobState whose structural field was never populated
# (an older on-disk record, or a caller that never passed --seed/
# --fsdb-path/register_external_job(seed=...)) but whose free-text
# `options` -- the string a caller passes straight through to the
# underlying `bsub`/simulator invocation, e.g.
# "+ntb_random_seed=1234 +fsdb_file=/path/run.fsdb" -- still happens to
# carry one of these markers. Extracts a value ONLY when the text genuinely
# contains one of these real, already-documented markers (the seed pattern
# mirrors gates.py's own log-scrubbing regex for the same marker vocabulary;
# the fsdb pattern mirrors the uvm_generator Makefile template's own
# `+fsdb_file=$(PAT_FSDB)` RUN_FLAGS convention) -- never guessed, never a
# fabricated default.
_SEED_IN_OPTIONS_RE = re.compile(r"\b(?:ntb_random_)?seed\s*[:=]\s*(\d+)\b", re.IGNORECASE)
_FSDB_FILE_IN_OPTIONS_RE = re.compile(r"\+fsdb_file[:=](\S+)", re.IGNORECASE)


def extract_seed_from_options(options: Optional[str]) -> Optional[str]:
    if not options:
        return None
    m = _SEED_IN_OPTIONS_RE.search(options)
    return m.group(1) if m else None


def extract_fsdb_path_from_options(options: Optional[str]) -> Optional[str]:
    if not options:
        return None
    m = _FSDB_FILE_IN_OPTIONS_RE.search(options)
    return m.group(1) if m else None


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

    SEED/FSDB_PATH (memory-engine-schema-completion audit, 2026-09-01;
    CLOSED by session-snapshot-extension, 2026-09-01): JobState now has
    first-class `seed`/`fsdb_path` fields (see JobState's own docstring
    comment), populated at submission time by cli.py's `lsf-submit`
    (explicit --seed/--fsdb-path, or auto-extracted from --options) and by
    register_external_job()'s optional kwargs. Those first-class fields are
    used here when present; `extract_seed_from_options`/
    `extract_fsdb_path_from_options` remain as a fallback ONLY for a
    JobState that never got the structural field populated (an older
    on-disk record predating this change, or a caller of
    register_external_job()/`lsf-submit` that genuinely never supplied
    either) but whose free-text `options` still happens to carry one of the
    documented markers. Rather than writing `"seed": None` /
    `"fsdb_path": None` (a null placeholder that LOOKS like the schema
    captured this data when it did not), the keys are simply omitted from
    the record when neither the field nor the fallback extraction finds
    anything, so a reader can tell "not captured" apart from "captured as
    null".
    """
    if not any(d.field == "sim_status" and d.severity == "CRITICAL" for d in discrepancies):
        return
    _upsert_job_tier_memory_record(root, jid, state)


def _upsert_job_tier_memory_record(root: Path, jid: int, state: JobState) -> None:
    """The real persistence body behind `_write_job_tier_memory_on_terminal_
    reconcile()` above, factored out (Phase 11, 2026-09-03, obsidian-memory-
    debugflow task -- Regression Integration) so a SECOND real caller can
    upsert the SAME deterministic `JOB-{jid}-TERMINAL-RECONCILE` record once
    it has BETTER evidence, without re-deriving the CRITICAL-discrepancy gate
    (which only ever reflects the coarse `lsf_status` bjobs already knew,
    BEFORE any real sim.log epilogue has been parsed).

    THE GAP THIS CLOSES: `reconcile_job()`'s CRITICAL "sim_status"->
    "ANALYSIS_OWED" discrepancy fires the FIRST time a job reaches a
    terminal live LSF status with DV analysis not yet recorded -- at that
    exact moment, `state.uvm_error_count`/`uvm_fatal_count` are whatever
    they were BEFORE this cycle's real sim.log epilogue parse (typically
    still 0/unset for a job whose failure only shows up in the log body,
    e.g. `lsf_status=="DONE"` with a real UVM_FATAL inside). The gated
    wrapper above, called from `reconcile_batch()`, can therefore
    legitimately write `kind="job_result"` (not yet knowing better) for a
    job that a moment later, in the SAME reconciliation cycle, turns out to
    be a real failure once `regression_reporter.run_reconciliation_cycle()`
    parses its epilogue (real `UVM_ERROR`/`UVM_FATAL` counts, or a `verdict`
    of `FAILED`). That real epilogue-parse call site calls this function
    directly (no discrepancy re-derivation needed -- the epilogue itself,
    already reflected onto `state.uvm_error_count`/`uvm_fatal_count` by that
    caller, IS the newer, better evidence), upserting the same
    `memory_id` -- MemoryStore.add()'s existing upsert-by-memory_id behavior
    (see this function's own idempotency note above) replaces the earlier,
    premature `job_result` classification with the accurate `job_failure`
    one, complete with a real failure_signature/prior_related_knowledge
    search this time. Never invents a new record for the same job."""
    # `state.sim_status == "FAIL"` (added Phase 11, 2026-09-03): the ORIGINAL
    # `is_failure` definition below only ever looked at LSF-level/UVM-marker
    # evidence -- never the real DV verdict itself. That was harmless at the
    # gated call site above (state.sim_status is guaranteed UNKNOWN/RUNNING
    # there, by the very CRITICAL discrepancy that gates this function), but
    # left a real gap at the SECOND call site
    # (regression_reporter.run_reconciliation_cycle(), called once
    # state.sim_status has just been set from a real sim.log epilogue
    # verdict): a "FAILED" epilogue with BOTH uvm_error/uvm_fatal counts
    # genuinely zero (a real, parser-permitted combination -- a timeout, or
    # an objection/phase-declared failure that raised neither) would
    # otherwise never be classified `is_failure` here despite being a real,
    # confirmed DV FAIL. Included unconditionally rather than only at that
    # second call site so both callers share one honest definition.
    is_failure = (
        state.lsf_status == "EXIT" or state.uvm_fatal_count > 0
        or state.assertion_failure or state.simulator_crash
        or state.sim_status == "FAIL"
    )
    kind = "job_failure" if is_failure else "job_result"
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
    seed = state.seed or extract_seed_from_options(state.options)
    if seed is not None:
        record["seed"] = seed
    fsdb_path = state.fsdb_path or extract_fsdb_path_from_options(state.options)
    if fsdb_path is not None:
        record["fsdb_path"] = fsdb_path

    # Phase 11 (2026-09-03, obsidian-memory-debugflow task -- Regression
    # Integration): on a real UVM_ERROR/UVM_FATAL/abnormal-termination signal
    # (the exact same `is_failure` evidence this function already derives
    # above, never a second definition), extract a failure signature and
    # search prior knowledge via the SAME shared Phase 10/11 interface
    # engine.py's FAILURE_RECOVERY debug flow calls
    # (memory_vault.build_failure_signature()/search_related_memory_for_debug()
    # -- see their own docstrings). The result is attached to this SAME
    # job_failure record as `prior_related_knowledge`, so the Debug Agent
    # that later picks this job up (a separate, pre-existing agent role) has
    # it without a second search -- but per CLAUDE.md's Evidence Truth Rule,
    # this is candidate prior evidence only: the Debug Agent must always
    # independently re-verify against current RTL/VIP/log/waveform evidence
    # and never copy a previous fix verbatim, exactly as the user's spec
    # requires. Never attempted for a plain job_result (no failure signal to
    # search against) -- searching would just be noise.
    if is_failure:
        try:
            from .memory_vault import build_failure_signature, search_related_memory_for_debug
            failure_signature = build_failure_signature(
                pattern=state.pattern,
                # `extra_text=state.pattern`: the real testcase/pattern name
                # is the one text signal this low-level reconcile hook
                # genuinely has for a prior-knowledge search (no protocol/
                # symptom text is available at this layer) -- a recurring
                # testcase name across vault notes is meaningful search
                # signal, not noise.
                extra_text=state.pattern,
                uvm_error_count=state.uvm_error_count, uvm_fatal_count=state.uvm_fatal_count,
                assertion_failure=state.assertion_failure, simulator_crash=state.simulator_crash,
                terminal_signature=state.terminal_signature, lsf_status=state.lsf_status,
            )
            search = search_related_memory_for_debug(root, None, failure_signature, limit=5)
            record["failure_signature"] = failure_signature
            if search.get("related_cases"):
                record["prior_related_knowledge"] = search["related_cases"]
        except Exception:
            pass  # a memory-search problem must never block the real job-memory write below

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
