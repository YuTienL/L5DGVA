#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--coverage", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.coverage).read_text())

    items=d.get("coverage_items",[])
    if not items:
        print(json.dumps({"status":"FAIL","reason":"NO_COVERAGE_ITEMS"})); return 2

    bad=[]
    for c in items:
        cid=c.get("coverage_id")
        if not c.get("requirement_ids"):
            bad.append({"coverage_id":cid,"reason":"NO_REQUIREMENT_TRACE"})
        if c.get("hit") and not (c.get("checker_ids") or c.get("scoreboard_ids") or c.get("assertion_ids") or c.get("approved_alternate_evidence")):
            bad.append({"coverage_id":cid,"reason":"HIT_WITHOUT_CHECKING_EVIDENCE"})
        if c.get("credit") and not c.get("execution_evidence"):
            bad.append({"coverage_id":cid,"reason":"CREDIT_WITHOUT_EXECUTION_EVIDENCE"})
        if c.get("credit") and not c.get("hit"):
            bad.append({"coverage_id":cid,"reason":"CREDIT_WITHOUT_HIT"})

    if bad:
        print(json.dumps({"status":"FAIL","bad":bad},indent=2)); return 3

    print(json.dumps({"status":"PASS","coverage_items":len(items)},indent=2))
    return 0

if __name__=="__main__":
    sys.exit(main())
