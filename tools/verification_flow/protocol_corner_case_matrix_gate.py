#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--matrix",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.matrix).read_text())
required=set(d.get("required_corner_cases",[])); covered=set()
for c in d.get("cases",[]):
    if c.get("covered"): covered.add(c.get("corner_id"))
    if c.get("covered") and not c.get("evidence"):
        print(json.dumps({"status":"FAIL","reason":"CORNER_COVERED_WITHOUT_EVIDENCE","corner_id":c.get("corner_id")})); sys.exit(2)
missing=sorted(required-covered)
if missing:
    print(json.dumps({"status":"FAIL","reason":"MISSING_PROTOCOL_CORNER_CASES","missing":missing})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
