#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--trace",required=True); x=a.parse_args()
d=json.loads(pathlib.Path(x.trace).read_text())
for r in d.get("requirements",[]):
 if r.get("status")=="WAIVED": continue
 for k in ("requirement_id","testcase_id","run_id","runtime_evidence_hash","semantic_verdict"):
  if not r.get(k): print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_REQUIREMENT_RUNTIME_TRACE","field":k,"requirement_id":r.get("requirement_id")})); sys.exit(2)
 if r.get("semantic_verdict")!="TRUE_PASS":
  print(json.dumps({"status":"FAIL","reason":"REQUIREMENT_NOT_RUNTIME_PROVEN","requirement_id":r.get("requirement_id")})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
