#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--rca",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.rca).read_text())
conf=d.get("confidence")
rank={"LOW":1,"MEDIUM":2,"HIGH":3,"VERIFIED":4}
if conf not in rank:
    print(json.dumps({"status":"FAIL","reason":"INVALID_RCA_CONFIDENCE"})); sys.exit(2)
if not d.get("first_bad_event") or not d.get("causal_chain") or not d.get("supporting_evidence"):
    print(json.dumps({"status":"FAIL","reason":"RCA_EVIDENCE_INCOMPLETE"})); sys.exit(3)
if conf in ("HIGH","VERIFIED") and not d.get("counter_evidence"):
    print(json.dumps({"status":"FAIL","reason":"HIGH_CONFIDENCE_WITHOUT_COUNTER_EVIDENCE"})); sys.exit(4)
if conf=="VERIFIED" and not d.get("fix_effectiveness_evidence"):
    print(json.dumps({"status":"FAIL","reason":"VERIFIED_RCA_WITHOUT_FIX_EFFECTIVENESS"})); sys.exit(5)
if d.get("promotion_requested") and rank[conf] < rank["HIGH"]:
    print(json.dumps({"status":"FAIL","reason":"RCA_CONFIDENCE_TOO_LOW_FOR_PROMOTION"})); sys.exit(6)
print(json.dumps({"status":"PASS","confidence":conf}))
