#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--graph",required=True); x=a.parse_args(); d=json.loads(pathlib.Path(x.graph).read_text()); arts={z.get("artifact_id"):z for z in d.get("artifacts",[])}
for aid,z in arts.items():
 if not z.get("hash"): print(json.dumps({"status":"FAIL","reason":"UNHASHED_ARTIFACT","artifact_id":aid})); sys.exit(2)
 for parent in z.get("depends_on",[]):
  if parent not in arts: print(json.dumps({"status":"FAIL","reason":"MISSING_ARTIFACT_DEPENDENCY","artifact_id":aid,"parent":parent})); sys.exit(3)
  if arts[parent].get("stale"): print(json.dumps({"status":"FAIL","reason":"STALE_ARTIFACT_DEPENDENCY"})); sys.exit(4)
print(json.dumps({"status":"PASS"}))
