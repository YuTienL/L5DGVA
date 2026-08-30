#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--scoreboard",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.scoreboard).read_text())
for k,reason in [("missing_expected_transactions","MISSING_EXPECTED_TRANSACTIONS"),("missing_actual_transactions","MISSING_ACTUAL_TRANSACTIONS"),("duplicate_transactions","DUPLICATE_TRANSACTIONS")]:
    if d.get(k,0)>0: print(json.dumps({"status":"FAIL","reason":reason})); sys.exit(2)
if d.get("max_transaction_latency") is None: print(json.dumps({"status":"FAIL","reason":"NO_TRANSACTION_LATENCY_BOUND"})); sys.exit(3)
if d.get("observed_max_transaction_latency",0)>d.get("max_transaction_latency"): print(json.dumps({"status":"FAIL","reason":"LATE_TRANSACTION"})); sys.exit(4)
print(json.dumps({"status":"PASS"}))
