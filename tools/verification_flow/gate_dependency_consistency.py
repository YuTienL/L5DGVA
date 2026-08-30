#!/usr/bin/env python3
import argparse, json, pathlib, sys

DEPS={
 "VPLAN_READY":["INTAKE_READY"],
 "ARCHITECTURE_READY":["VPLAN_READY"],
 "MECHANISM_READY":["ARCHITECTURE_READY"],
 "TESTS_READY":["MECHANISM_READY"],
 "TRACEABILITY_READY":["TESTS_READY"],
 "EXECUTION_EVIDENCE_READY":["TRACEABILITY_READY"],
 "COVERAGE_QUALITY_READY":["EXECUTION_EVIDENCE_READY"],
 "RCA_READY":["EXECUTION_EVIDENCE_READY"],
 "RERUN_READY":["RCA_READY"],
 "EXPERT_REVIEW_READY":["COVERAGE_QUALITY_READY"],
 "EXPERIENCE_READY":["EXPERT_REVIEW_READY"],
 "PROMOTABLE":["EXPERIENCE_READY"]
}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    a=ap.parse_args()
    passed=set(json.loads(pathlib.Path(a.state).read_text()).get("passed_stages",[]))
    bad=[]
    for stage,deps in DEPS.items():
        if stage in passed:
            for dep in deps:
                if dep not in passed:
                    bad.append({"stage":stage,"missing_dependency":dep})
    if bad:
        print(json.dumps({"status":"FAIL","violations":bad},indent=2)); return 2
    print(json.dumps({"status":"PASS","passed_count":len(passed)}))
    return 0

if __name__=="__main__":
    sys.exit(main())
