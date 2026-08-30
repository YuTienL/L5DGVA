#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--results",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.results).read_text())
seen={}
for r in d.get("results",[]):
    key=(r.get("testcase_id"),r.get("run_id"))
    if None in key:
        print(json.dumps({"status":"FAIL","reason":"RESULT_WITHOUT_TEST_OR_RUN"})); sys.exit(2)
    sig=(r.get("result"),r.get("log_hash"),r.get("evidence_bundle_hash"))
    if key in seen and seen[key]!=sig:
        print(json.dumps({"status":"FAIL","reason":"CONFLICTING_DUPLICATE_RESULT","key":key,"first":seen[key],"second":sig})); sys.exit(3)
    seen[key]=sig
print(json.dumps({"status":"PASS","unique_results":len(seen)}))
