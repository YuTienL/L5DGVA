#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--failure",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.failure).read_text())

    if d.get("classification")!="UNKNOWN":
        print(json.dumps({"status":"PASS","reason":"CLASSIFIED"})); return 0

    required=["missing_evidence","next_evidence_actions","owner","blocking_scope"]
    missing=[x for x in required if not d.get(x)]
    if missing:
        print(json.dumps({"status":"FAIL","reason":"UNKNOWN_WITHOUT_ESCALATION_PLAN","missing":missing})); return 2
    if d.get("promotion_allowed"):
        print(json.dumps({"status":"FAIL","reason":"UNKNOWN_FAILURE_CANNOT_PROMOTE"})); return 3

    print(json.dumps({"status":"BLOCKED_PENDING_EVIDENCE","owner":d["owner"]})); return 0
if __name__=="__main__":
    sys.exit(main())
