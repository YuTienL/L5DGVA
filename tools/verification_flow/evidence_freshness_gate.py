#!/usr/bin/env python3
import argparse,json,pathlib,sys

ap=argparse.ArgumentParser()
ap.add_argument("--evidence",required=True)
ap.add_argument("--current-revision")
a=ap.parse_args()
d=json.loads(pathlib.Path(a.evidence).read_text())

# Backward-compatible v20 schema:
# {"evidence_items":[{"revision":"new","content_hash":"..."}]}, --current-revision new
if "evidence_items" in d:
    if not a.current_revision:
        print(json.dumps({"status":"FAIL","reason":"MISSING_CURRENT_REVISION"})); sys.exit(2)
    for e in d.get("evidence_items",[]):
        if e.get("revision")!=a.current_revision:
            print(json.dumps({"status":"FAIL","reason":"STALE_EVIDENCE",
                              "evidence_id":e.get("evidence_id"),
                              "expected_revision":a.current_revision,
                              "actual_revision":e.get("revision")})); sys.exit(3)
        if not e.get("content_hash"):
            print(json.dumps({"status":"FAIL","reason":"UNHASHED_SIGNOFF_EVIDENCE",
                              "evidence_id":e.get("evidence_id")})); sys.exit(4)
    print(json.dumps({"status":"PASS"})); sys.exit(0)

# v44+ schema:
# {"current":{"rtl_hash":...,"build_hash":...,"spec_revision":...},"items":[...]}
cur=d.get("current",{})
for e in d.get("items",[]):
    for k in ("rtl_hash","build_hash","spec_revision"):
        if e.get(k)!=cur.get(k):
            print(json.dumps({"status":"FAIL","reason":"STALE_SIGNOFF_EVIDENCE",
                              "evidence_id":e.get("evidence_id"),"field":k})); sys.exit(5)
    if not e.get("evidence_hash"):
        print(json.dumps({"status":"FAIL","reason":"UNHASHED_SIGNOFF_EVIDENCE",
                          "evidence_id":e.get("evidence_id")})); sys.exit(6)

print(json.dumps({"status":"PASS"}))
