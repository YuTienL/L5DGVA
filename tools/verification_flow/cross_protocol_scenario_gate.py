#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--scenarios",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.scenarios).read_text())
for s in d.get("scenarios",[]):
    sid=s.get("scenario_id")
    prots=set(s.get("protocols",[]))
    if len(prots)<2:
        print(json.dumps({"status":"FAIL","reason":"NOT_CROSS_PROTOCOL","scenario_id":sid})); sys.exit(2)
    for k in ("requirement_ids","mechanism_ids","coverage_ids","evidence"):
        if not s.get(k):
            print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_CROSS_PROTOCOL_TRACE","scenario_id":sid,"missing":k})); sys.exit(3)
    if not s.get("interaction_point"):
        print(json.dumps({"status":"FAIL","reason":"NO_PROTOCOL_INTERACTION_POINT","scenario_id":sid})); sys.exit(4)
print(json.dumps({"status":"PASS","scenarios":len(d.get("scenarios",[]))}))
