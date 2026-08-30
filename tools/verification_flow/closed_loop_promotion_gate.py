#!/usr/bin/env python3
import argparse, json, pathlib, sys

REQUIRED_STAGES = [
    "INTAKE_READY",
    "VPLAN_READY",
    "ARCHITECTURE_READY",
    "MECHANISM_READY",
    "TESTS_READY",
    "EXECUTION_EVIDENCE_READY",
    "COVERAGE_QUALITY_READY",
]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.state).read_text())

    passed=set(d.get("passed_stages",[]))
    missing=[x for x in REQUIRED_STAGES if x not in passed]
    if missing:
        print(json.dumps({"status":"FAIL","reason":"MISSING_STAGES","missing":missing},indent=2))
        return 2

    if d.get("failure_detected"):
        rca=d.get("root_cause",{})
        required=["classification","first_bad_event","causal_chain","supporting_evidence","counter_evidence","confidence"]
        miss=[x for x in required if not rca.get(x)]
        if miss:
            print(json.dumps({"status":"FAIL","reason":"FAILURE_WITHOUT_VALID_RCA","missing":miss},indent=2))
            return 3
        if not d.get("calibration_or_fix_applied"):
            print(json.dumps({"status":"FAIL","reason":"FAILURE_WITHOUT_FIX_OR_CALIBRATION"}))
            return 4
        if not d.get("rerun_evidence"):
            print(json.dumps({"status":"FAIL","reason":"FIX_WITHOUT_RERUN_EVIDENCE"}))
            return 5

    if not d.get("expert_feedback_reviewed"):
        print(json.dumps({"status":"FAIL","reason":"NO_EXPERT_FEEDBACK_REVIEW"}))
        return 6

    if not d.get("experience_capture_status") in ("CAPTURED","NOT_APPLICABLE"):
        print(json.dumps({"status":"FAIL","reason":"EXPERIENCE_LOOP_NOT_CLOSED"}))
        return 7

    print(json.dumps({"status":"PROMOTABLE","passed_stages":sorted(passed)},indent=2))
    return 0

if __name__=="__main__":
    sys.exit(main())
