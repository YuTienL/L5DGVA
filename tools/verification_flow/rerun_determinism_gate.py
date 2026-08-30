#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--reruns",required=True); x=a.parse_args(); d=json.loads(pathlib.Path(x.reruns).read_text()); runs=d.get("runs",[])
if len(runs)<2: print(json.dumps({"status":"FAIL","reason":"INSUFFICIENT_EQUIVALENT_RERUNS"})); sys.exit(2)
base=runs[0]
for r in runs[1:]:
 if r.get("input_fingerprint")!=base.get("input_fingerprint"): print(json.dumps({"status":"FAIL","reason":"NON_EQUIVALENT_RERUN_INPUT"})); sys.exit(3)
 if r.get("semantic_verdict")!=base.get("semantic_verdict") or r.get("critical_checker_hash")!=base.get("critical_checker_hash"): print(json.dumps({"status":"FAIL","reason":"NON_DETERMINISTIC_VERIFICATION_RESULT"})); sys.exit(4)
print(json.dumps({"status":"PASS"}))
