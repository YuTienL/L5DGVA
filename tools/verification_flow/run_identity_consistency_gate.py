#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--bundle",required=True); x=a.parse_args()
d=json.loads(pathlib.Path(x.bundle).read_text())
rid=d.get("canonical_run_id"); bid=d.get("canonical_build_hash")
if not rid or not bid:
    print(json.dumps({"status":"FAIL","reason":"MISSING_CANONICAL_RUN_IDENTITY"})); sys.exit(2)
for e in d.get("evidence",[]):
    if e.get("run_id")!=rid or e.get("build_hash")!=bid:
        if not (e.get("merge_approved") and e.get("merge_policy_id")):
            print(json.dumps({"status":"FAIL","reason":"CROSS_RUN_EVIDENCE_WITHOUT_APPROVED_MERGE","evidence_id":e.get("evidence_id")})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
