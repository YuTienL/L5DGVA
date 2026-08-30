#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--closure",required=True); x=a.parse_args()
d=json.loads(pathlib.Path(x.closure).read_text())
for k in ("command_id","command_hash","expected_semantics","observed_semantics","sim_log_hash"):
 if not d.get(k): print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_COMMAND_INTENT_EVIDENCE","field":k})); sys.exit(2)
if d.get("simulation_result")!="PASSED": print(json.dumps({"status":"FAIL","reason":"SIMULATION_NOT_PASSED"})); sys.exit(3)
if d["expected_semantics"]!=d["observed_semantics"]:
 print(json.dumps({"status":"FAIL","reason":"SIM_PASS_BUT_COMMAND_INTENT_MISMATCH"})); sys.exit(4)
print(json.dumps({"status":"PASS"}))
