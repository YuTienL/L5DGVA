#!/usr/bin/env python3
import argparse, json, pathlib, sys

ORDER = [
    "INTAKE_READY",
    "VPLAN_READY",
    "ARCHITECTURE_READY",
    "MECHANISM_READY",
    "TESTS_READY",
    "TRACEABILITY_READY",
    "EXECUTION_EVIDENCE_READY",
    "COVERAGE_QUALITY_READY",
    "RCA_READY",
    "RERUN_READY",
    "EXPERT_REVIEW_READY",
    "EXPERIENCE_READY",
    "PROMOTABLE"
]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--audit", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.audit).read_text())
    events=d.get("events",[])
    if not events:
        print(json.dumps({"status":"FAIL","reason":"NO_EVENTS"})); return 2

    seen=[]
    names=set()
    for e in events:
        stage=e.get("stage")
        if stage not in ORDER:
            print(json.dumps({"status":"FAIL","reason":"UNKNOWN_STAGE","stage":stage})); return 3
        if stage in names:
            print(json.dumps({"status":"FAIL","reason":"DUPLICATE_STAGE","stage":stage})); return 4
        if not e.get("evidence"):
            print(json.dumps({"status":"FAIL","reason":"STAGE_WITHOUT_EVIDENCE","stage":stage})); return 5
        names.add(stage)
        seen.append(stage)

    # Enforce monotonic order
    idx=[ORDER.index(x) for x in seen]
    if idx != sorted(idx):
        print(json.dumps({"status":"FAIL","reason":"NON_MONOTONIC_PROMOTION_CHAIN","events":seen})); return 6

    # PROMOTABLE requires all mandatory stages before it, RCA/RERUN may be omitted only if no failure
    failure=d.get("failure_detected", False)
    mandatory = ORDER[:8] + ["EXPERT_REVIEW_READY","EXPERIENCE_READY","PROMOTABLE"]
    if failure:
        mandatory = ORDER
    missing=[x for x in mandatory if x not in names]
    if missing:
        print(json.dumps({"status":"FAIL","reason":"MISSING_PROMOTION_STAGES","missing":missing})); return 7

    print(json.dumps({"status":"PASS","stages":seen,"failure_detected":failure}))
    return 0

if __name__=="__main__":
    sys.exit(main())
