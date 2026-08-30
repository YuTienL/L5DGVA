#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--record",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.record).read_text())
for k in ("dut_request_path","issue_id","classification","root_cause","fix_summary","risk_summary","verification_result","change_hash"):
 if not d.get(k): print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_DUT_REQUEST_RECORD","field":k})); sys.exit(2)
if pathlib.PurePath(d["dut_request_path"]).name!="dut-request.md":
 print(json.dumps({"status":"FAIL","reason":"DUT_REQUEST_WRONG_FILENAME"})); sys.exit(3)
if d.get("classification")!="REAL_ISSUE":
 print(json.dumps({"status":"FAIL","reason":"ONLY_REAL_ISSUE_CAN_CREATE_FIX_RECORD"})); sys.exit(4)
print(json.dumps({"status":"PASS"}))
