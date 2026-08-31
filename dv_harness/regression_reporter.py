from __future__ import annotations
import json, time
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

def run_reconciliation_cycle(root: Path, vcuser: str, uvm_root_path: Path) -> str:
    """One pass of Part 2's reconciliation cycle: discover every live job
    under vcuser, reconcile+analyze the ones dv_harness has a registered
    JobState for (via bsub_submit() or register_external_job()), apply
    Part 3's regression-list safety net for any job with a real PASS/FAIL
    verdict and a known pattern, then render and persist the snapshot.

    A single failed discover_live_jobs()/reconcile_batch() call is caught
    and logged rather than raised, per the spec's error-handling
    requirement -- one bad LSF poll must not kill the whole cycle."""
    try:
        live_jobs = lsf_client.discover_live_jobs(vcuser)
    except lsf_client.LsfUnavailableError as e:
        print(f"[reconciliation_cycle] discover_live_jobs failed: {e}", flush=True)
        live_jobs = []

    registered_ids = []
    for j in live_jobs:
        jid = j["job_id"]
        state = lsf_client.load_job_state(root, jid)
        if state.pattern is not None or state.sim_log is not None:
            registered_ids.append(jid)

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
            discrepancies = detect_underreporting(asdict(state), parsed)
            for d in discrepancies:
                print(f"[reconciliation_cycle] job {jid} under-reporting: {d}", flush=True)
            if verdict == "PASSED":
                state.sim_status = "PASS"
            elif verdict == "FAILED":
                state.sim_status = "FAIL"
            else:
                state.sim_status = "ANALYZED"
            lsf_client.save_job_state(root, state)

            if state.pattern and verdict in ("PASSED", "FAILED"):
                regression_list_path = Path(uvm_root_path) / "regression.list"
                apply_verdict_to_file(regression_list_path, state.pattern, verdict == "PASSED")
        except Exception as e:
            print(f"[reconciliation_cycle] job {jid} analysis failed: {e}", flush=True)
            continue

    jobs_for_snapshot = []
    for j in live_jobs:
        jid = j["job_id"]
        if jid in reconciled:
            state, _ = reconciled[jid]
            row = lsf_client.to_snapshot_row(state, agent_action="monitoring")
            row["lsf_status"] = state.lsf_status
        else:
            row = {"job_id": jid, "pattern": j.get("job_name"),
                   "lsf_status": j.get("stat"), "dv_analysis_status": "UNREGISTERED",
                   "uvm_error_count": None, "uvm_fatal_count": None,
                   "agent_action": "monitoring", "note": None}
        jobs_for_snapshot.append(row)

    snapshot = render_snapshot(jobs_for_snapshot)
    snapshot_path = root / ".dv-harness" / "lsf" / "latest_snapshot.txt"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(snapshot, encoding="utf-8")
    print(snapshot, flush=True)
    return snapshot


def main(project_root='.', once=True, interval_minutes=30, vcuser=None, uvm_root_path=None):
    root = Path(project_root).resolve()
    while True:
        if vcuser:
            uvm_root = Path(uvm_root_path) if uvm_root_path else root / 'uvm'
            run_reconciliation_cycle(root, vcuser, uvm_root)
        else:
            # No vcuser means discover_live_jobs() has nothing to query --
            # fall back to the pre-existing behavior of re-rendering
            # whatever is already registered locally, rather than crashing.
            print(render_snapshot(load_jobs(root)), flush=True)
        if once:
            break
        time.sleep(max(1, interval_minutes) * 60)

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
