#!/usr/bin/env python3
import argparse,json,pathlib,sys
ALLOWED={"DUT","TB","VIP","TOOL","INFRA","SPEC","UNKNOWN"}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--rca",required=True); a=ap.parse_args()
    d=json.loads(pathlib.Path(a.rca).read_text())
    owner=d.get("attribution")
    if owner not in ALLOWED:
        print(json.dumps({"status":"FAIL","reason":"INVALID_ATTRIBUTION"})); return 2
    if owner=="UNKNOWN":
        if d.get("promotion_requested"):
            print(json.dumps({"status":"FAIL","reason":"UNKNOWN_RCA_CANNOT_PROMOTE"})); return 3
        print(json.dumps({"status":"PASS","classification":"UNKNOWN_BLOCKED"})); return 0
    required=["first_bad_event","causal_chain","supporting_evidence","counter_evidence"]
    miss=[k for k in required if not d.get(k)]
    if miss:
        print(json.dumps({"status":"FAIL","reason":"RCA_ATTRIBUTION_WITHOUT_CAUSAL_EVIDENCE","missing":miss})); return 4
    if d.get("attribution_confidence") not in ("HIGH","VERIFIED"):
        print(json.dumps({"status":"FAIL","reason":"ATTRIBUTION_CONFIDENCE_TOO_LOW"})); return 5
    print(json.dumps({"status":"PASS","attribution":owner})); return 0

if __name__=="__main__": sys.exit(main())
