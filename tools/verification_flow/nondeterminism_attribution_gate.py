#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--analysis",required=True); x=a.parse_args()
d=json.loads(pathlib.Path(x.analysis).read_text())
if d.get("deterministic") is True:
    print(json.dumps({"status":"PASS","classification":"DETERMINISTIC"})); sys.exit(0)
owner=d.get("attribution")
if owner not in ("DUT","TB","VIP","TOOL","ENVIRONMENT","UNKNOWN"):
    print(json.dumps({"status":"FAIL","reason":"INVALID_NONDETERMINISM_ATTRIBUTION"})); sys.exit(2)
if owner=="UNKNOWN":
    print(json.dumps({"status":"FAIL","reason":"UNRESOLVED_NONDETERMINISM"})); sys.exit(3)
for k in ("first_divergence","supporting_evidence","counter_evidence","reproduction_matrix_hash"):
    if not d.get(k):
        print(json.dumps({"status":"FAIL","reason":"NONDETERMINISM_ATTRIBUTION_WITHOUT_EVIDENCE","missing":k})); sys.exit(4)
print(json.dumps({"status":"PASS","attribution":owner}))
