#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--bundle",required=True); x=a.parse_args()
d=json.loads(pathlib.Path(x.bundle).read_text())
rid=d.get("run_id"); root=d.get("bundle_hash")
if not rid or not root:
    print(json.dumps({"status":"FAIL","reason":"MISSING_BUNDLE_IDENTITY"})); sys.exit(2)
seen=set()
for e in d.get("evidence",[]):
    eid=e.get("evidence_id")
    if not eid or eid in seen:
        print(json.dumps({"status":"FAIL","reason":"DUPLICATE_OR_MISSING_EVIDENCE_ID"})); sys.exit(3)
    seen.add(eid)
    if e.get("run_id")!=rid:
        print(json.dumps({"status":"FAIL","reason":"EVIDENCE_RUN_ID_MISMATCH","evidence_id":eid})); sys.exit(4)
    if not e.get("hash"):
        print(json.dumps({"status":"FAIL","reason":"UNHASHED_EVIDENCE","evidence_id":eid})); sys.exit(5)
print(json.dumps({"status":"PASS"}))
