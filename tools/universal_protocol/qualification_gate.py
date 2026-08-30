#!/usr/bin/env python3
import argparse,json,pathlib,sys
ORDER=["BUILDER_AVAILABLE","EVIDENCE_READY","ENV_GENERATED","COMPILE_QUALIFIED","SMOKE_QUALIFIED","PROTOCOL_QUALIFIED","REGRESSION_QUALIFIED","PRODUCTION_QUALIFIED"]
ap=argparse.ArgumentParser()
ap.add_argument('--evidence',required=True,help='qualification evidence JSON')
ap.add_argument('--target',default='PRODUCTION_QUALIFIED',choices=ORDER)
a=ap.parse_args()
d=json.loads(pathlib.Path(a.evidence).read_text())
passed=set(d.get("passed_gates",[]))
target_i=ORDER.index(a.target)
missing=[x for x in ORDER[1:target_i+1] if x not in passed]
if missing:
 print("QUALIFICATION FAIL; missing:",", ".join(missing)); sys.exit(2)
print("QUALIFICATION PASS:",a.target)
