#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--assertions",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.assertions).read_text())
for x in d.get("assertions",[]):
    aid=x.get("assertion_id")
    if not x.get("enabled"): continue
    if x.get("antecedent_attempts",0)==0:
        print(json.dumps({"status":"FAIL","reason":"VACUOUS_ASSERTION","assertion_id":aid})); sys.exit(2)
    if x.get("unknown_xz_masked_without_justification"):
        print(json.dumps({"status":"FAIL","reason":"ASSERTION_XZ_MASKING_UNJUSTIFIED","assertion_id":aid})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
