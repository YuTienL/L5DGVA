#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--proof",required=True); x=a.parse_args()
d=json.loads(pathlib.Path(x.proof).read_text())
req=("positive_test_pass","negative_test_detects_fault","checker_detects_injected_fault","semantic_log_match","oracle_independent")
for k in req:
 if d.get(k) is not True: print(json.dumps({"status":"FAIL","reason":"FALSE_PASS_RESISTANCE_NOT_PROVEN","field":k})); sys.exit(2)
if not d.get("proof_bundle_hash"): print(json.dumps({"status":"FAIL","reason":"FALSE_PASS_PROOF_UNHASHED"})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
