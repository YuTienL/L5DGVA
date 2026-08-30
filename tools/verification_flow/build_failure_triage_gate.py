#!/usr/bin/env python3
import argparse, json, pathlib, sys

CLASSES = {"QUICK_FIX", "DESIGN_ISSUE"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--triage", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.triage).read_text())

    if not d.get("build_log_excerpt"):
        print(json.dumps({"status": "FAIL", "reason": "NO_BUILD_LOG_EVIDENCE"})); return 2

    c = d.get("classification")
    if c not in CLASSES:
        print(json.dumps({"status": "FAIL", "reason": "INVALID_CLASSIFICATION"})); return 3
    if not d.get("classification_reason"):
        print(json.dumps({"status": "FAIL", "reason": "CLASSIFICATION_WITHOUT_REASON"})); return 4

    if c == "QUICK_FIX":
        if not (d.get("quick_fix_applied") and d.get("quick_fix_description")
                and d.get("rerun_target_stage") == "CHANGE_IMPACT"):
            print(json.dumps({"status": "FAIL", "reason": "QUICK_FIX_INCOMPLETE"})); return 5
    else:  # DESIGN_ISSUE
        if not (d.get("routed_to_failure_recovery") and d.get("failure_recovery_finding_id")):
            print(json.dumps({"status": "FAIL", "reason": "DESIGN_ISSUE_NOT_ROUTED"})); return 6

    print(json.dumps({"status": "PASS", "classification": c}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
