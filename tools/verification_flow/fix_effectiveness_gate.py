#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--fix",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.fix).read_text())

    required=["failure_signature_before","root_cause_id","fix_revision","rerun_evidence"]
    miss=[x for x in required if not d.get(x)]
    if miss:
        print(json.dumps({"status":"FAIL","reason":"MISSING_FIELDS","missing":miss})); return 2

    if d.get("failure_signature_after") == d.get("failure_signature_before"):
        print(json.dumps({"status":"FAIL","reason":"FAILURE_SIGNATURE_PERSISTS"})); return 3
    if not d.get("targeted_reproducer_passed"):
        print(json.dumps({"status":"FAIL","reason":"TARGETED_REPRODUCER_NOT_PASS"})); return 4
    if not d.get("broader_regression_passed"):
        print(json.dumps({"status":"FAIL","reason":"BROADER_REGRESSION_NOT_PASS"})); return 5
    if d.get("new_failures_introduced"):
        print(json.dumps({"status":"FAIL","reason":"FIX_INTRODUCED_NEW_FAILURES"})); return 6

    print(json.dumps({"status":"FIX_EFFECTIVE","root_cause_id":d["root_cause_id"]}))
    return 0

if __name__=="__main__":
    sys.exit(main())
