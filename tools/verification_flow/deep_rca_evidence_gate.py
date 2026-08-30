#!/usr/bin/env python3
import argparse,json,pathlib,sys
REQ={"SIM_LOG","TRACE","RTL","TESTBENCH","COMMAND","SCOREBOARD","PHY_MODEL","STANDARD_SPEC","VIP_EXAMPLE","VIP_SOURCE","VIP_DOCUMENT"}
ap=argparse.ArgumentParser(); ap.add_argument("--rca",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.rca).read_text())
p={x.get("source") for x in d.get("evidence_sources",[]) if x.get("checked") and x.get("evidence_hash")}
m=sorted(REQ-p)
if m: print(json.dumps({"status":"FAIL","reason":"DEEP_RCA_EVIDENCE_INCOMPLETE","missing":m})); sys.exit(2)
if not d.get("first_bad_event"): print(json.dumps({"status":"FAIL","reason":"NO_FIRST_BAD_EVENT"})); sys.exit(3)
if len(d.get("causal_chain",[]))<2: print(json.dumps({"status":"FAIL","reason":"NO_CAUSAL_CHAIN"})); sys.exit(4)
if d.get("confidence") not in ("HIGH","VERIFIED","BLOCKED"):
 print(json.dumps({"status":"FAIL","reason":"RCA_CONFIDENCE_TOO_LOW"})); sys.exit(5)
if d.get("confidence")=="BLOCKED" and not (d.get("missing_evidence") and d.get("next_action")):
 print(json.dumps({"status":"FAIL","reason":"BLOCKED_WITHOUT_NEXT_ACTION"})); sys.exit(6)
print(json.dumps({"status":"PASS"}))
