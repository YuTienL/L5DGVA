#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--coverage",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.coverage).read_text())
for x in d.get("items",[]):
    if not x.get("credit"): continue
    cid=x.get("coverage_id"); src=x.get("source",{}); typ=src.get("type")
    if typ not in ("TEST","CHECKER","ASSERTION","SCOREBOARD","WAIVER"):
        print(json.dumps({"status":"FAIL","reason":"INVALID_COVERAGE_CREDIT_SOURCE","coverage_id":cid})); sys.exit(2)
    if not src.get("source_id") or not src.get("evidence_hash"):
        print(json.dumps({"status":"FAIL","reason":"COVERAGE_CREDIT_WITHOUT_PROVENANCE","coverage_id":cid})); sys.exit(3)
    if typ=="WAIVER" and not (src.get("approved") and src.get("waiver_scope_hash")):
        print(json.dumps({"status":"FAIL","reason":"UNAPPROVED_OR_UNSCOPED_WAIVER_CREDIT","coverage_id":cid})); sys.exit(4)
print(json.dumps({"status":"PASS"}))
