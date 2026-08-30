#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--plan",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.plan).read_text())
for k in ("root_cause_id","fix_plan","risk_assessment","affected_scope","regression_plan","rollback_plan"):
 if not d.get(k): print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_FIX_RISK_PLAN","field":k})); sys.exit(2)
if d.get("root_cause_confidence") not in ("HIGH","VERIFIED"):
 print(json.dumps({"status":"FAIL","reason":"FIX_WITHOUT_HIGH_CONFIDENCE_RCA"})); sys.exit(3)
if d.get("risk_level")=="HIGH" and d.get("high_risk_reviewed") is not True:
 print(json.dumps({"status":"FAIL","reason":"HIGH_RISK_FIX_NOT_REVIEWED"})); sys.exit(4)
if d.get("approved_for_modify") is not True:
 print(json.dumps({"status":"FAIL","reason":"FIX_NOT_APPROVED_FOR_MODIFICATION"})); sys.exit(5)
print(json.dumps({"status":"PASS"}))
