#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--runs",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.runs).read_text())
for r in d.get("runs",[]):
    if r.get("randomized") and r.get("seed") in (None,""):
        print(json.dumps({"status":"FAIL","reason":"RANDOM_RUN_WITHOUT_SEED","run_id":r.get("run_id")})); sys.exit(2)
    if r.get("failure") and not r.get("reproducer_command"):
        print(json.dumps({"status":"FAIL","reason":"FAILURE_WITHOUT_REPRODUCER","run_id":r.get("run_id")})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
