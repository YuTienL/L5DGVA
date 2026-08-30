#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--oracles",required=True); x=a.parse_args()
d=json.loads(pathlib.Path(x.oracles).read_text())
for o in d.get("oracles",[]):
 if o.get("shares_prediction_source_with_dut") or o.get("shares_bug_prone_algorithm_with_stimulus"):
  print(json.dumps({"status":"FAIL","reason":"NON_INDEPENDENT_TEST_ORACLE","oracle_id":o.get("oracle_id")})); sys.exit(2)
 if not o.get("reference_basis") or not o.get("oracle_hash"):
  print(json.dumps({"status":"FAIL","reason":"UNPROVEN_TEST_ORACLE","oracle_id":o.get("oracle_id")})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
