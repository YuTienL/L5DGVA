#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--baseline",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.baseline).read_text())
for k in ("de_local_sim_path","original_command_hash","rtl_hash","build_recipe_hash","environment_hash"):
    if not d.get(k):
        print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_DE_BASELINE_IDENTITY","field":k})); sys.exit(2)
if d.get("original_de_result")!="PASS":
    print(json.dumps({"status":"FAIL","reason":"SOURCE_DE_BASELINE_NOT_KNOWN_GOOD"})); sys.exit(3)
if d.get("harness_reproduced_result")!="PASS":
    print(json.dumps({"status":"FAIL","reason":"DE_BASELINE_NOT_REPRODUCED"})); sys.exit(4)
if d.get("original_command_hash")!=d.get("reproduced_command_hash"):
    print(json.dumps({"status":"FAIL","reason":"BASELINE_COMMAND_CHANGED_DURING_REPRODUCTION"})); sys.exit(5)
if d.get("rtl_hash")!=d.get("reproduced_rtl_hash"):
    print(json.dumps({"status":"FAIL","reason":"BASELINE_RTL_CHANGED_DURING_REPRODUCTION"})); sys.exit(6)
if not d.get("sim_log_hash"):
    print(json.dumps({"status":"FAIL","reason":"BASELINE_WITHOUT_SIM_LOG_EVIDENCE"})); sys.exit(7)
print(json.dumps({"status":"PASS","baseline_state":"BASELINE_LOCKED"}))
