#!/usr/bin/env python3
import argparse, json, pathlib, sys

def _is_off(v):
    return v in (0, False, "0", None) or v is False

# BUG FIX (regression-submission-override-linkage-gap, 2026-09-02): the
# WAVE/PA/Coverage default-off check below used to be satisfied by ANY
# non-empty free-text "override_reason" string, with zero correlation to a
# real prior failure -- an agent could write literally anything and bypass
# the CLAUDE.md "Simulation Observability Default: FSDB OFF" rule. A
# non-empty override_reason now also requires "prior_failure_ref": a
# testcase_id plus a reference this gate actually resolves against real
# on-disk evidence -- either a finding_id present in the real
# REGRESSION_MONITOR-maintained blackboard findings registry
# (dv_harness/blackboard.py's Blackboard.upsert_finding writes
# .dv-harness/blackboard/findings.json), or a job_id whose real prior
# JobState record (dv_harness/lsf_client.py, one file per submitted LSF job
# at .dv-harness/lsf/jobs/<job_id>.json) actually shows a failure. Read
# directly relative to this script's own cwd -- gates.run_gate() always
# subprocess.run()s every gate script with cwd=str(root) (harness-
# controlled, never agent-attested) -- rather than importing dv_harness,
# matching the self-contained-gate-script convention already used by
# environment_mode_selection_gate.py (see its own header for the same
# RULING). Missing/unresolvable prior_failure_ref now FAILs with
# WAVE_OVERRIDE_NOT_LINKED_TO_FAILURE.
FINDINGS_PATH = pathlib.Path(".dv-harness") / "blackboard" / "findings.json"
JOBS_DIR = pathlib.Path(".dv-harness") / "lsf" / "jobs"
_FAILURE_SIM_STATUSES = {"FAIL", "EXIT"}


def _finding_is_real(finding_id):
    if not FINDINGS_PATH.exists():
        return False
    try:
        payload = json.loads(FINDINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    value = payload.get("value") if isinstance(payload, dict) else None
    items = value.get("items") if isinstance(value, dict) else None
    return isinstance(items, dict) and finding_id in items


def _job_state_is_real_failure(job_id):
    p = JOBS_DIR / f"{job_id}.json"
    if not p.exists():
        return False
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(rec, dict):
        return False
    return bool(
        rec.get("sim_status") in _FAILURE_SIM_STATUSES
        or rec.get("lsf_status") == "EXIT"
        or rec.get("uvm_error_count")
        or rec.get("uvm_fatal_count")
        or rec.get("assertion_failure")
        or rec.get("simulator_crash")
    )


def _prior_failure_ref_valid(ref):
    if not isinstance(ref, dict):
        return False
    testcase_id = ref.get("testcase_id")
    if not isinstance(testcase_id, str) or not testcase_id.strip():
        return False
    finding_id = ref.get("finding_id")
    if isinstance(finding_id, str) and finding_id.strip() and _finding_is_real(finding_id.strip()):
        return True
    job_id = ref.get("job_id")
    if job_id is not None and str(job_id).strip() and _job_state_is_real_failure(str(job_id).strip()):
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.jobs).read_text())
    jobs = d.get("jobs", [])
    if not jobs:
        print(json.dumps({"status": "FAIL", "reason": "NO_JOBS_SUBMITTED"})); return 2

    seen_agents = set()
    for j in jobs:
        jid = j.get("job_id")
        agent_id = j.get("agent_id")
        if not agent_id:
            print(json.dumps({"status": "FAIL", "reason": "JOB_WITHOUT_AGENT", "job_id": jid})); return 3
        if agent_id in seen_agents:
            print(json.dumps({"status": "FAIL", "reason": "AGENT_CONTEXT_NOT_ISOLATED",
                               "job_id": jid, "agent_id": agent_id})); return 4
        seen_agents.add(agent_id)

        override_reason = j.get("override_reason")
        needs_override = False
        for field, off_name in (("wave", "WAVE"), ("pa", "PA"), ("coverage", "COVERAGE")):
            if not _is_off(j.get(field)):
                needs_override = True
                if not override_reason:
                    print(json.dumps({"status": "FAIL", "reason": f"{off_name}_DEFAULT_VIOLATION",
                                       "job_id": jid, "value": j.get(field)})); return 5

        if needs_override and override_reason and not _prior_failure_ref_valid(j.get("prior_failure_ref")):
            print(json.dumps({"status": "FAIL", "reason": "WAVE_OVERRIDE_NOT_LINKED_TO_FAILURE",
                               "job_id": jid, "prior_failure_ref": j.get("prior_failure_ref")})); return 6

    print(json.dumps({"status": "PASS", "jobs": len(jobs)}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
