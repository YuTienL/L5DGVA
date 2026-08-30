#!/usr/bin/env python3
import argparse, json, pathlib, sys

def _is_off(v):
    return v in (0, False, "0", None) or v is False

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

        for field, off_name in (("wave", "WAVE"), ("pa", "PA"), ("coverage", "COVERAGE")):
            if not _is_off(j.get(field)) and not j.get("override_reason"):
                print(json.dumps({"status": "FAIL", "reason": f"{off_name}_DEFAULT_VIOLATION",
                                   "job_id": jid, "value": j.get(field)})); return 5

    print(json.dumps({"status": "PASS", "jobs": len(jobs)}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
