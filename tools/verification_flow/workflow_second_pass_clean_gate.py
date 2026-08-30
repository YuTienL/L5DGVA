#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--closure",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.closure).read_text())
if d.get("first_workflow_complete") is not True:
    print(json.dumps({"status":"FAIL","reason":"FIRST_WORKFLOW_NOT_COMPLETE"})); sys.exit(2)
if d.get("all_first_pass_issues_fixed") is not True:
    print(json.dumps({"status":"FAIL","reason":"NOT_ALL_FIRST_PASS_ISSUES_FIXED"})); sys.exit(3)
if d.get("second_detailed_workflow_run") is not True:
    print(json.dumps({"status":"FAIL","reason":"SECOND_WORKFLOW_ANALYSIS_REQUIRED"})); sys.exit(4)
if d.get("remaining_issue_count",0)>0:
    print(json.dumps({"status":"FAIL","reason":"SECOND_PASS_STILL_HAS_ISSUES",
                      "remaining_issue_count":d.get("remaining_issue_count")})); sys.exit(5)
if d.get("push_build_verify_run_requested") and d.get("clean_second_pass") is not True:
    print(json.dumps({"status":"FAIL","reason":"PROMOTION_BEFORE_CLEAN_SECOND_PASS"})); sys.exit(6)
print(json.dumps({"status":"PASS","next":"push_build_verify_run"}))
