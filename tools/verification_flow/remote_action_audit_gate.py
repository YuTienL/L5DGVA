#!/usr/bin/env python3
import argparse, json, pathlib, sys

MUTATING={"REDIRECT","APPROVE","REJECT","STOP","TAKEOVER"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--audit", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.audit).read_text())

    entries=d.get("actions",[])
    if not entries:
        print(json.dumps({"status":"FAIL","reason":"NO_REMOTE_ACTIONS"})); return 2

    for e in entries:
        cmd=e.get("command")
        if not e.get("timestamp") or not e.get("actor"):
            print(json.dumps({"status":"FAIL","reason":"UNAUDITABLE_ACTION","command":cmd})); return 3
        if cmd in MUTATING:
            if not e.get("target_stage"):
                print(json.dumps({"status":"FAIL","reason":"MUTATING_ACTION_WITHOUT_TARGET","command":cmd})); return 4
            if not e.get("reason"):
                print(json.dumps({"status":"FAIL","reason":"MUTATING_ACTION_WITHOUT_REASON","command":cmd})); return 5
            if not e.get("evidence_snapshot"):
                print(json.dumps({"status":"FAIL","reason":"MUTATING_ACTION_WITHOUT_EVIDENCE_SNAPSHOT","command":cmd})); return 6

    print(json.dumps({"status":"PASS","actions":len(entries)}))
    return 0

if __name__=="__main__":
    sys.exit(main())
