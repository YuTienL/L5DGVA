#!/usr/bin/env python3
import argparse,json,pathlib,re,sys

def _has_marker(log, marker):
    return marker.lower() in re.sub(r"\s+"," ",str(log)).lower()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--jobs",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.jobs).read_text())
    jobs=d.get("jobs",[])
    if not jobs:
        print(json.dumps({"status":"FAIL","reason":"NO_JOBS"})); return 2
    for j in jobs:
        jid=j.get("job_id")
        if not j.get("agent_id"):
            print(json.dumps({"status":"FAIL","reason":"JOB_WITHOUT_AGENT","job_id":jid})); return 3
        sim_log=j.get("sim_log")
        if not sim_log:
            print(json.dumps({"status":"FAIL","reason":"JOB_WITHOUT_SIM_LOG","job_id":jid})); return 4

        # CLAUDE.md: "LSF DONE is not equal to DV PASS" -- grep the log itself
        # rather than trusting the agent's uvm_error_detected/fatal_detected
        # self-report; a real UVM_ERROR/UVM_FATAL in the log must not be
        # silently under-declared as no-failure.
        log_has_error=_has_marker(sim_log, "UVM_ERROR")
        log_has_fatal=_has_marker(sim_log, "UVM_FATAL")
        declared_error=bool(j.get("uvm_error_detected"))
        declared_fatal=bool(j.get("fatal_detected"))
        if (log_has_error or log_has_fatal) and not (declared_error or declared_fatal):
            print(json.dumps({"status":"FAIL","reason":"SIM_LOG_ERROR_UNDECLARED","job_id":jid,
                              "log_has_error":log_has_error,"log_has_fatal":log_has_fatal})); return 7

        if declared_error or declared_fatal:
            if not j.get("evidence_captured"):
                print(json.dumps({"status":"FAIL","reason":"FAILURE_WITHOUT_EVIDENCE_CAPTURE","job_id":jid})); return 5
            if j.get("kill_requested") and not j.get("kill_reason"):
                print(json.dumps({"status":"FAIL","reason":"KILL_WITHOUT_REASON","job_id":jid})); return 6
    print(json.dumps({"status":"PASS","jobs":len(jobs)}))
    return 0
if __name__=="__main__":
    sys.exit(main())
