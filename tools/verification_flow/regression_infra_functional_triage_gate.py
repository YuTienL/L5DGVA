#!/usr/bin/env python3
import argparse, json, pathlib, sys

CLASSES = {"INFRASTRUCTURE", "FUNCTIONAL"}
INFRA_SYMPTOMS = {"LSF", "LICENSE", "COMPUTE", "TOOLCHAIN"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--triage", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.triage).read_text())

    c = d.get("classification")
    if c not in CLASSES:
        print(json.dumps({"status": "FAIL", "reason": "INVALID_CLASSIFICATION"})); return 2
    if not d.get("classification_reason") or not d.get("evidence_hash"):
        print(json.dumps({"status": "FAIL", "reason": "CLASSIFICATION_WITHOUT_EVIDENCE"})); return 3

    if c == "INFRASTRUCTURE":
        if d.get("infra_symptom") not in INFRA_SYMPTOMS:
            print(json.dumps({"status": "FAIL", "reason": "INVALID_INFRA_SYMPTOM"})); return 4
        if not (d.get("infra_fix_applied") and d.get("infra_fix_description")
                and d.get("rerun_target_stage") == "REGRESSION_SELECT"):
            print(json.dumps({"status": "FAIL", "reason": "INFRA_FIX_INCOMPLETE"})); return 5
    else:  # FUNCTIONAL
        if not (d.get("routed_to_failure_recovery") and d.get("failure_recovery_finding_id")):
            print(json.dumps({"status": "FAIL", "reason": "FUNCTIONAL_NOT_ROUTED"})); return 6

    print(json.dumps({"status": "PASS", "classification": c}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
