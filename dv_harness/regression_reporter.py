from __future__ import annotations
import json, time
import os, signal, subprocess, sys
from dataclasses import asdict
from pathlib import Path
from datetime import datetime

from dv_harness import lsf_client
from dv_harness.sim_log_analysis import parse_sim_log_file, detect_underreporting
from dv_harness.uvm_generator.regression_list_manager import apply_verdict_to_file

def load_jobs(project_root: Path):
    d=project_root/'.dv-harness'/'lsf'/'jobs'
    jobs=[]
    if not d.exists(): return jobs
    for p in sorted(d.glob('*.json')):
        try:
            x=json.loads(p.read_text(encoding='utf-8')); x['_file']=str(p); jobs.append(x)
        except Exception: pass
    return jobs

def get_job(project_root: Path, job_id):
    """Single-job lookup on top of load_jobs() -- the one shared
    implementation dv_harness/dashboard.py's GET /api/lsf/jobs/<job_id> and
    dv_harness/cli.py's `lsf <job_id>` both call, so job-id matching (str()
    comparison -- job_id in the on-disk JSON may be an int or a str
    depending on how the LSF client wrote it, and CLI/URL job ids always
    arrive as str) lives in exactly one place. Returns None if no job with
    that id exists, never raises."""
    for j in load_jobs(project_root):
        if str(j.get('job_id')) == str(job_id):
            return j
    return None

def fmt(v, default='-'):
    if v is None or v=='': return default
    return str(v)

def render_snapshot(jobs):
    now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    counts={}
    for j in jobs:
        s=fmt(j.get('lsf_status'),'UNKNOWN'); counts[s]=counts.get(s,0)+1
    reg_ids=sorted({j.get('regression_id') for j in jobs if j.get('regression_id')})
    header=[f'DV Agent Harness L5 - Periodic Regression Snapshot',f'Snapshot Time: {now}']
    if reg_ids:
        header.append('Regression ID : '+(', '.join(reg_ids)))
    lines=header + [
           'SUMMARY: '+ ' | '.join([f'Total: {len(jobs)}']+[f'{k}: {v}' for k,v in sorted(counts.items())]),'',
           f"{'Job':<10} {'Pattern / Combination':<36} {'LSF':<10} {'DV Analysis':<18} {'UVM_ERR':<9} {'UVM_FATAL':<10} Agent Action / Note",
           '-'*130]
    attention=[]
    for j in jobs:
        jid=fmt(j.get('job_id')); pat=fmt(j.get('pattern')); lsf=fmt(j.get('lsf_status'),'UNKNOWN')
        dv=fmt(j.get('dv_analysis_status') or j.get('sim_status'),'UNKNOWN')
        ue=fmt(j.get('uvm_error_count'),'pending' if lsf=='DONE' else '-')
        uf=fmt(j.get('uvm_fatal_count'),'pending' if lsf=='DONE' else '-')
        action=fmt(j.get('agent_action') or j.get('root_cause_status') or j.get('kill_reason'),'monitoring')
        lines.append(f'{jid:<10} {pat[:35]:<36} {lsf:<10} {dv:<18} {ue:<9} {uf:<10} {action}')
        if lsf=='EXIT' or dv in ('FAIL','ROOT_CAUSE','RERUN_REQUIRED') or (isinstance(j.get('uvm_error_count'),int) and j.get('uvm_error_count',0)>0):
            attention.append(f"- {jid} {pat}: LSF={lsf}, DV={dv}, UVM_ERROR={ue}, action={action}")
    lines += ['', 'ATTENTION'] + (attention or ['- none'])
    lines += ['', 'NEXT ACTIONS','- Analyze DONE jobs whose DV result is still UNKNOWN/pending.','- Continue incremental monitoring of RUN jobs.','- Triage EXIT/FAIL jobs and rerun fixed patterns when ready.']
    return '\n'.join(lines)

def _registered_job_ids_on_disk(root: Path) -> list:
    """Every job id dv_harness has a persisted JobState for, read straight
    from `<root>/.dv-harness/lsf/jobs/*.json` filenames (no JSON parsing --
    a corrupt file must not hide the id of the job it belongs to). Returns
    [] when the directory does not exist yet."""
    d = root.joinpath(*lsf_client.JOBS_DIR_NAME)
    if not d.exists():
        return []
    ids = []
    for p in d.glob("*.json"):
        try:
            ids.append(int(p.stem))
        except ValueError:
            continue
    return sorted(ids)


def run_reconciliation_cycle(root: Path, vcuser: str, uvm_root_path: Path) -> str:
    """One pass of Part 2's reconciliation cycle: discover every live job
    under vcuser, MERGE that set with every job dv_harness already has a
    registered JobState for on disk, reconcile+analyze the registered ones,
    apply Part 3's regression-list safety net for any job with a real
    PASS/FAIL verdict and a known pattern, then render and persist the
    snapshot.

    BUG FIX (2026-09-01 whole-branch review): the job set was previously an
    INTERSECTION -- only jobs that appeared in discover_live_jobs()'s output
    AND had a registered JobState were reconciled -- which silently violated
    the spec's own "Merge both sets" wording (Part 2 step 3). A registered
    job that has aged out of the `bjobs -u` listing then never got
    reconciled or analyzed again, so it could never be observed reaching
    DONE/EXIT and Part 3's safety net never fired for it. reconcile_batch()
    queries LSF by explicit job id, not by account, so it still returns a
    real, current status for a registered job that is absent from this
    poll's live_jobs list for any reason.

    A single failed discover_live_jobs()/reconcile_batch() call is caught
    and logged rather than raised, per the spec's error-handling
    requirement -- one bad LSF poll must not kill the whole cycle."""
    try:
        live_jobs = lsf_client.discover_live_jobs(vcuser)
    except lsf_client.LsfUnavailableError as e:
        print(f"[reconciliation_cycle] discover_live_jobs failed: {e}", flush=True)
        live_jobs = []

    registered_id_set = set(_registered_job_ids_on_disk(root))
    for j in live_jobs:
        jid = j["job_id"]
        state = lsf_client.load_job_state(root, jid)
        if state.pattern is not None or state.sim_log is not None:
            registered_id_set.add(jid)
    registered_ids = sorted(registered_id_set)

    if registered_ids:
        try:
            reconciled = lsf_client.reconcile_batch(root, registered_ids)
        except Exception as e:
            print(f"[reconciliation_cycle] reconcile_batch failed: {e}", flush=True)
            reconciled = {}
    else:
        reconciled = {}

    for jid, (state, _discrepancies) in reconciled.items():
        if state.lsf_status not in ("DONE", "EXIT"):
            continue
        if not state.sim_log:
            continue
        try:
            parsed = parse_sim_log_file(state.sim_log)
        except OSError as e:
            print(f"[reconciliation_cycle] could not read {state.sim_log}: {e}", flush=True)
            continue
        epilogue = parsed.get("epilogue")
        if epilogue:
            state.uvm_error_count = epilogue.get("uvm_error") or 0
            state.uvm_fatal_count = epilogue.get("uvm_fatal") or 0
        verdict = (epilogue or {}).get("verdict")
        try:
            # NOTE on which detect_underreporting() branches are live HERE:
            # state.uvm_error_count/uvm_fatal_count were just overwritten
            # FROM this same epilogue a few lines above, so at this specific
            # call site the "declared" values can never disagree with the
            # epilogue's -- the UNDER_REPORTED_EPILOGUE_UVM_FATAL/
            # _UVM_ERROR/_VERDICT branches are structurally unable to fire.
            # That is intentional, not broken: the branch that matters here
            # is the one comparing the log BODY's raw marker/signature
            # counts against what the epilogue declared, which catches a
            # simulation whose final tally under-reports its own log
            # content. detect_underreporting() keeps the epilogue branches
            # for its other callers (e.g. an agent-populated JobState that
            # was never derived from the epilogue at all).
            discrepancies = detect_underreporting(asdict(state), parsed)
            for d in discrepancies:
                print(f"[reconciliation_cycle] job {jid} under-reporting: {d}", flush=True)
            if verdict == "PASSED":
                state.sim_status = "PASS"
            elif verdict == "FAILED":
                state.sim_status = "FAIL"
            # BUG FIX (2026-09-01 whole-branch review): an INDETERMINATE
            # verdict (no epilogue, or an epilogue with no PASSED/FAILED)
            # must NOT advance sim_status. Stamping "ANALYZED" here left the
            # job looking analyzed while its verdict was never actually
            # determined, and permanently silenced reconcile_job()'s
            # CRITICAL sim_status -> ANALYSIS_OWED discrepancy (which only
            # fires while sim_status is UNKNOWN/RUNNING, and is the sole
            # trigger for the Job-tier memory write). Per CLAUDE.md's "LSF
            # DONE is not equal to DV PASS", an unparseable/truncated log
            # must keep raising the analysis-owed alarm on every later
            # reconciliation pass, never be silently guessed at.
            lsf_client.save_job_state(root, state)

            if state.pattern and verdict in ("PASSED", "FAILED"):
                regression_list_path = Path(uvm_root_path) / "regression.list"
                apply_verdict_to_file(regression_list_path, state.pattern, verdict == "PASSED")
        except Exception as e:
            print(f"[reconciliation_cycle] job {jid} analysis failed: {e}", flush=True)
            continue

    jobs_for_snapshot = []
    seen_ids = set()
    for j in live_jobs:
        jid = j["job_id"]
        seen_ids.add(jid)
        if jid in reconciled:
            state, _ = reconciled[jid]
            jobs_for_snapshot.append(lsf_client.to_snapshot_row(state, agent_action="monitoring"))
        else:
            # An unregistered row's status goes through the SAME
            # map_bjobs_stat_to_lsf_status() normalization a registered row
            # gets via to_snapshot_row()/reconcile_job(); otherwise one
            # column would mix raw LSF codes (PSUSP/USUSP/UNKWN/ZOMBI) with
            # normalized ones (PEND/RUN/DONE/EXIT/UNKNOWN) row by row.
            jobs_for_snapshot.append({
                "job_id": jid, "pattern": j.get("job_name"),
                "lsf_status": lsf_client.map_bjobs_stat_to_lsf_status(j.get("stat")),
                "dv_analysis_status": "UNREGISTERED",
                "uvm_error_count": None, "uvm_fatal_count": None,
                "agent_action": "monitoring", "note": None})

    # Registered jobs that this poll's live_jobs did not list (see the
    # union in the docstring) still belong in the snapshot -- they were
    # reconciled against LSF by explicit job id and carry a real status.
    for jid in registered_ids:
        if jid in seen_ids or jid not in reconciled:
            continue
        state, _ = reconciled[jid]
        jobs_for_snapshot.append(lsf_client.to_snapshot_row(state, agent_action="monitoring"))

    snapshot = render_snapshot(jobs_for_snapshot)
    snapshot_path = root / ".dv-harness" / "lsf" / "latest_snapshot.txt"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(snapshot, encoding="utf-8")
    print(snapshot, flush=True)
    return snapshot


WATCHER_PID_FILE = ('.dv-harness', 'lsf', 'watcher.pid')


def _pid_file_path(root: Path) -> Path:
    return root.joinpath(*WATCHER_PID_FILE)


def _pid_is_running(pid: int) -> bool:
    if os.name == "nt":
        # BUG FIX (2026-09-01, found while wiring up the `lsf-watch-*` CLI
        # commands): os.kill(pid, 0) on Windows is implemented via
        # GenerateConsoleCtrlEvent, which only succeeds when called by the
        # process that originally spawned the target's console/process
        # group (or one of that process's still-live descendants) -- a
        # relationship real usage never has, since every dv-harness CLI
        # invocation (including the one that spawned the watcher via
        # ensure_watcher_running()) is a separate, short-lived process
        # that exits right after spawning/checking. A LATER, unrelated
        # process checking the pid (e.g. every real `lsf-watch-status`
        # call) got OSError WinError 87 from the os.kill(pid, 0) call
        # below, which the `except OSError: return False` branch then
        # silently mistook for "not running" even while the watcher was
        # genuinely alive. Query the OS directly via OpenProcess/
        # GetExitCodeProcess instead, which has no such console-lineage
        # restriction.
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        # restype/argtypes are mandatory here, not cosmetic: ctypes defaults
        # every unprototyped return value to C int, which TRUNCATES a 64-bit
        # HANDLE to 32 bits on 64-bit Windows -- the truncated value can be
        # a bogus handle (and is then passed to GetExitCodeProcess/
        # CloseHandle) or can even come back as 0 and be misread as "process
        # not running".
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p,
                                                 ctypes.POINTER(ctypes.c_ulong)]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by a different user/UID -- alive,
        # just not signalable by us. Must not be conflated with "not
        # running", or ensure_watcher_running()/stop_watcher() would treat
        # a live watcher as dead.
        return True
    except OSError:
        return False
    except AttributeError:
        # os.kill(pid, 0) is not universally available; treat as unknown
        # rather than crash -- caller falls through to "start a new one".
        return False
    return True


def ensure_watcher_running(root: Path, vcuser: str, uvm_root_path,
                            interval_minutes: int = 5) -> dict:
    """Start the --watch loop as a detached background process if one is
    not already running for this project, tracked via a PID file. A stale
    PID file (process no longer alive) is detected and cleaned up
    automatically rather than blocking a fresh start.

    The child's stdio is redirected to `.dv-harness/lsf/watcher.log`
    (append) with stdin on DEVNULL. This is load-bearing on both platforms
    (BUG FIX, 2026-09-01 whole-branch review): on POSIX the child would
    otherwise inherit the launching agent's own stdout pipe and hold its
    write end open forever -- hanging whatever ran `dv-harness
    lsf-watch-start` -- and would die with an uncaught BrokenPipeError out
    of its own print() calls once the reader went away; on Windows
    DETACHED_PROCESS gives the child no console at all, so every log line,
    including the reconciliation cycle's under-reporting findings and its
    failure logging, was silently discarded. The log file also gives those
    findings a durable, discoverable home."""
    pid_path = _pid_file_path(root)
    if pid_path.exists():
        try:
            existing_pid = int(pid_path.read_text().strip())
        except ValueError:
            existing_pid = None
        if existing_pid is not None and _pid_is_running(existing_pid):
            return {"started": False, "pid": existing_pid}
        pid_path.unlink()

    argv = [sys.executable, "-m", "dv_harness.regression_reporter",
            "--project-root", str(root), "--watch",
            "--interval-minutes", str(interval_minutes),
            "--vcuser", vcuser, "--uvm-root-path", str(uvm_root_path)]
    popen_kwargs = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
    else:
        popen_kwargs["start_new_session"] = True

    log_path = root / ".dv-harness" / "lsf" / "watcher.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log_fh:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                 stdout=log_fh, stderr=subprocess.STDOUT,
                                 **popen_kwargs)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(proc.pid))
    return {"started": True, "pid": proc.pid}


def stop_watcher(root: Path) -> dict:
    """Terminate the running watcher (if any) and remove its PID file.
    A missing PID file is a no-op, not an error -- nothing was running.

    `stopped` is honest about what actually happened: True only when a live
    process was found and signaled. A tracked PID that was already dead
    yields {"stopped": False} with the stale PID file still cleaned up --
    cleaning up a stale file is not the same as stopping a running
    watcher, and reporting it as such (the pre-2026-09-01 behavior) hid
    watchers that had crashed on their own."""
    pid_path = _pid_file_path(root)
    if not pid_path.exists():
        return {"stopped": False}
    try:
        pid = int(pid_path.read_text().strip())
    except ValueError:
        pid_path.unlink()
        return {"stopped": False}
    was_running = _pid_is_running(pid)
    if was_running:
        os.kill(pid, signal.SIGTERM if os.name != "nt" else 15)
    pid_path.unlink()
    return {"stopped": was_running}


def watcher_status(root: Path) -> dict:
    pid_path = _pid_file_path(root)
    if not pid_path.exists():
        return {"running": False, "pid": None}
    try:
        pid = int(pid_path.read_text().strip())
    except ValueError:
        return {"running": False, "pid": None}
    return {"running": _pid_is_running(pid), "pid": pid if _pid_is_running(pid) else None}


def main(project_root='.', once=True, interval_minutes=30, vcuser=None, uvm_root_path=None):
    """Last-resort exception guard around each cycle (2026-09-01
    whole-branch review): run_reconciliation_cycle() isolates only
    discover_live_jobs()'s LsfUnavailableError and the per-job analysis
    block. Other real exceptions can still escape -- load_job_state()'s bare
    json.JSONDecodeError on a corrupt jobs/<id>.json, PermissionError/other
    OSError subtypes out of reconcile_batch()'s subprocess.run calls, an
    OSError from the snapshot mkdir/write_text -- and any one of them would
    permanently kill a background watcher meant to run unattended for hours.
    The guard belongs HERE, at the loop level, not inside
    run_reconciliation_cycle(): one bad cycle must log and fall through to
    the next time.sleep(), while a single-shot (`once=True`) caller still
    gets its exception surfaced by the re-raise below."""
    root = Path(project_root).resolve()
    while True:
        try:
            _run_one_cycle(root, vcuser, uvm_root_path)
        except Exception as e:
            if once:
                raise
            print(f"[watch loop] cycle failed: {e}", flush=True)
        if once:
            break
        time.sleep(max(1, interval_minutes) * 60)


def _run_one_cycle(root: Path, vcuser, uvm_root_path) -> None:
    if vcuser:
        uvm_root = Path(uvm_root_path) if uvm_root_path else root / 'uvm'
        run_reconciliation_cycle(root, vcuser, uvm_root)
    else:
        # No vcuser means discover_live_jobs() has nothing to query --
        # fall back to the pre-existing behavior of re-rendering
        # whatever is already registered locally, rather than crashing.
        print(render_snapshot(load_jobs(root)), flush=True)


if __name__=='__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--project-root', default='.')
    ap.add_argument('--watch', action='store_true')
    ap.add_argument('--interval-minutes', type=int, default=30)
    ap.add_argument('--vcuser', default=None,
                     help='LSF account to discover live jobs under; omit for legacy local-only mode')
    ap.add_argument('--uvm-root-path', default=None,
                     help='UVM_ROOT_PATH for regression.list; defaults to <project-root>/uvm')
    a = ap.parse_args()
    main(a.project_root, not a.watch, a.interval_minutes, a.vcuser, a.uvm_root_path)
