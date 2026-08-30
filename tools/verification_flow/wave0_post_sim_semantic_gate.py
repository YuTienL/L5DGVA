#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--result",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.result).read_text())
if d.get("wave_mode")!=0:
    print(json.dumps({"status":"FAIL","reason":"DEFAULT_POSTCHECK_REQUIRES_WAVE0"})); sys.exit(2)
for k in ("command_hash","sim_log_hash","command_intent","observed_semantics"):
    if not d.get(k):
        print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_WAVE0_SEMANTIC_EVIDENCE","field":k})); sys.exit(3)
if d.get("simulation_ended") is not True:
    print(json.dumps({"status":"FAIL","reason":"SIMULATION_NOT_ENDED"})); sys.exit(4)
if d.get("command_intent")!=d.get("observed_semantics"):
    if d.get("first_error_time_us") is None:
        print(json.dumps({"status":"FAIL","reason":"SEMANTIC_MISMATCH_WITHOUT_ERROR_TIMESTAMP"})); sys.exit(5)
    print(json.dumps({"status":"PASS","semantic_result":"NEEDS_DEEP_DEBUG",
                      "first_error_time_us":d.get("first_error_time_us")})); sys.exit(0)
if d.get("unexpected_error") or d.get("uvm_error_count",0)>0 or d.get("uvm_fatal_count",0)>0:
    if d.get("first_error_time_us") is None:
        print(json.dumps({"status":"FAIL","reason":"ERROR_WITHOUT_TIMESTAMP"})); sys.exit(6)
    print(json.dumps({"status":"PASS","semantic_result":"TRUE_FAIL",
                      "first_error_time_us":d.get("first_error_time_us")})); sys.exit(0)
print(json.dumps({"status":"PASS","semantic_result":"TRUE_PASS"}))
