#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--build",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.build).read_text())

if d.get("compile_target_can_fall_through_to_run") and d.get("stop_after_simv") is not True:
    print(json.dumps({"status":"FAIL","reason":"STOP_AFTER_SIMV_REQUIRED"})); sys.exit(2)

if d.get("parallel_run_count",0)>1 and not d.get("compile_completed_before_parallel_runs"):
    print(json.dumps({"status":"FAIL","reason":"PARALLEL_RUNS_STARTED_BEFORE_COMPILE_COMPLETE"})); sys.exit(3)

if not d.get("build_fingerprint") or not d.get("simv_completion_marker"):
    print(json.dumps({"status":"FAIL","reason":"BUILD_COMPLETION_NOT_ATOMICALLY_PROVEN"})); sys.exit(4)

if d.get("simv_completion_marker_build_fingerprint")!=d.get("build_fingerprint"):
    print(json.dumps({"status":"FAIL","reason":"STALE_SIMV_COMPLETION_MARKER"})); sys.exit(5)

print(json.dumps({"status":"PASS"}))
