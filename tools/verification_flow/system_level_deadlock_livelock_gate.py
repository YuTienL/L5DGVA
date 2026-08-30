#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--analysis",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.analysis).read_text())
if d.get("deadlock_detected"): print(json.dumps({"status":"FAIL","reason":"SYSTEM_DEADLOCK_DETECTED","cycle":d.get("deadlock_cycle",[])})); sys.exit(2)
if d.get("livelock_detected"): print(json.dumps({"status":"FAIL","reason":"SYSTEM_LIVELOCK_DETECTED"})); sys.exit(3)
if not d.get("forward_progress_assertions"): print(json.dumps({"status":"FAIL","reason":"NO_FORWARD_PROGRESS_ASSERTIONS"})); sys.exit(4)
if not d.get("stress_scenario_evidence"): print(json.dumps({"status":"FAIL","reason":"NO_STRESS_SCENARIO_EVIDENCE"})); sys.exit(5)
print(json.dumps({"status":"PASS"}))
