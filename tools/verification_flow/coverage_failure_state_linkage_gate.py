#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--state",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.state).read_text()); active=set(d.get("active_failure_ids",[]))
for c in d.get("coverage_items",[]):
    bad=active & set(c.get("linked_failure_ids",[]))
    if c.get("credit") and bad:
        print(json.dumps({"status":"FAIL","reason":"COVERAGE_CREDIT_WITH_ACTIVE_FAILURE","coverage_id":c.get("coverage_id"),"active_failures":sorted(bad)})); sys.exit(2)
print(json.dumps({"status":"PASS"}))
