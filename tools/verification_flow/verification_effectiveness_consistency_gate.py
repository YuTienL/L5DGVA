#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--state",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.state).read_text())
if d.get("final_verdict")=="PASS":
    req=[d.get("semantic_status")=="TRUE_PASS",d.get("checker_status")=="PASS",
         d.get("negative_test_effective") is True,d.get("assertion_effective") is True,
         d.get("scoreboard_independent") is True]
    if not all(req):
        print(json.dumps({"status":"FAIL","reason":"PASS_WITH_UNPROVEN_VERIFICATION_EFFECTIVENESS"})); sys.exit(2)
if d.get("negative_test_effective") is False and d.get("coverage_credit_allowed"):
    print(json.dumps({"status":"FAIL","reason":"COVERAGE_CREDIT_WITH_VACUOUS_NEGATIVE_TEST"})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
