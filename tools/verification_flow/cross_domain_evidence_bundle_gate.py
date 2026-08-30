#!/usr/bin/env python3
import argparse,json,pathlib,sys
REQ={"SHARED_RESOURCE":"contention_evidence","INTERRUPT":"interrupt_evidence",
     "RESET":"recovery_evidence","POWER":"power_transition_evidence"}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--bundle",required=True); a=ap.parse_args()
    d=json.loads(pathlib.Path(a.bundle).read_text())
    for s in d.get("scenarios",[]):
        sid=s.get("scenario_id")
        domains=set(s.get("domains",[]))
        if len(domains)<2:
            print(json.dumps({"status":"FAIL","reason":"NOT_CROSS_DOMAIN","scenario_id":sid})); return 2
        for dom,field in REQ.items():
            if dom in domains and not s.get(field):
                print(json.dumps({"status":"FAIL","reason":"MISSING_DOMAIN_EVIDENCE",
                                  "scenario_id":sid,"domain":dom,"field":field})); return 3
        if not s.get("evidence_bundle_hash"):
            print(json.dumps({"status":"FAIL","reason":"NO_EVIDENCE_BUNDLE_HASH","scenario_id":sid})); return 4
        if not s.get("subsystem_release_snapshot_hash"):
            print(json.dumps({"status":"FAIL","reason":"NO_RELEASE_SNAPSHOT_HASH","scenario_id":sid})); return 5
    print(json.dumps({"status":"PASS"})); return 0

if __name__=="__main__": sys.exit(main())
