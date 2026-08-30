#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--waivers",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.waivers).read_text())
for w in d.get("waivers",[]):
    wid=w.get("waiver_id")
    for k in ("requirement_ids","subsystem","spec_revision","design_evidence_hash","approval_id","scope_hash"):
        if not w.get(k):
            print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_WAIVER_SCOPE","waiver_id":wid,"missing":k})); sys.exit(2)
    if w.get("active_failure_ids"):
        print(json.dumps({"status":"FAIL","reason":"WAIVER_ATTEMPTS_TO_HIDE_ACTIVE_FAILURE","waiver_id":wid})); sys.exit(3)
    if w.get("applied_requirement_ids") and set(w["applied_requirement_ids"])-set(w["requirement_ids"]):
        print(json.dumps({"status":"FAIL","reason":"WAIVER_APPLIED_OUTSIDE_SCOPE","waiver_id":wid})); sys.exit(4)
print(json.dumps({"status":"PASS"}))
