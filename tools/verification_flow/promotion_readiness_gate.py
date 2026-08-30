#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--state",required=True); x=a.parse_args()
d=json.loads(pathlib.Path(x.state).read_text())
critical=d.get("critical_dimensions",{})
bad={k:v for k,v in critical.items() if v in ("BLOCKED","UNKNOWN","FAIL","INCOMPLETE")}
if bad:
    print(json.dumps({"status":"FAIL","reason":"PROMOTION_NOT_READY","dimensions":bad})); sys.exit(2)
if d.get("active_failure_count",0)>0:
    print(json.dumps({"status":"FAIL","reason":"PROMOTION_WITH_ACTIVE_FAILURES"})); sys.exit(3)
if d.get("signoff_bundle_complete") is not True or d.get("evidence_fresh") is not True:
    print(json.dumps({"status":"FAIL","reason":"PROMOTION_WITH_INCOMPLETE_OR_STALE_SIGNOFF"})); sys.exit(4)
print(json.dumps({"status":"PASS"}))
