#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--plan",required=True); x=a.parse_args()
d=json.loads(pathlib.Path(x.plan).read_text())
for r in d.get("requirements",[]):
 if r.get("status")=="WAIVED": continue
 obs=r.get("observability",[])
 if not obs: print(json.dumps({"status":"FAIL","reason":"REQUIREMENT_WITHOUT_OBSERVABILITY","requirement_id":r.get("requirement_id")})); sys.exit(2)
 if not any(o.get("type") in ("SCOREBOARD","CHECKER","ASSERTION","MONITOR","LOG_SEMANTIC") and o.get("evidence_point") for o in obs):
  print(json.dumps({"status":"FAIL","reason":"INSUFFICIENT_OBSERVABILITY","requirement_id":r.get("requirement_id")})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
