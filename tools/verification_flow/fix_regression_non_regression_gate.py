#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--closure",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.closure).read_text())
if d.get("target_pre_fix_result")!="FAIL" or d.get("target_post_fix_result")!="PASS":
    print(json.dumps({"status":"FAIL","reason":"TARGET_FIX_NOT_PROVEN"})); sys.exit(2)
if d.get("replay_equivalent") is not True:
    print(json.dumps({"status":"FAIL","reason":"TARGET_RERUN_NOT_EQUIVALENT"})); sys.exit(3)
for t in d.get("critical_non_regression_tests",[]):
    if t.get("pre_fix_result")=="PASS" and t.get("post_fix_result")!="PASS":
        print(json.dumps({"status":"FAIL","reason":"FIX_CAUSED_REGRESSION","testcase_id":t.get("testcase_id")})); sys.exit(4)
    if t.get("pre_fix_result")=="PASS" and not t.get("evidence_hash"):
        print(json.dumps({"status":"FAIL","reason":"NON_REGRESSION_WITHOUT_EVIDENCE","testcase_id":t.get("testcase_id")})); sys.exit(5)
if not d.get("fix_commit_hash") or not d.get("rerun_bundle_hash"):
    print(json.dumps({"status":"FAIL","reason":"FIX_CLOSURE_WITHOUT_ARTIFACT_HASH"})); sys.exit(6)
print(json.dumps({"status":"PASS"}))
