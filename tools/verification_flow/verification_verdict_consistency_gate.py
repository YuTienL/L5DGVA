import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--verdict",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.verdict).read_text()); f=d.get("final_verdict")
if f=="PASS":
 ok=d.get("simulation_status")=="PASS" and d.get("semantic_status")=="TRUE_PASS" and d.get("checker_status")=="PASS" and not d.get("active_failure_ids") and d.get("signoff_credit_allowed") is True
 if not ok: print(json.dumps({"status":"FAIL","reason":"INCONSISTENT_FINAL_PASS"})); sys.exit(2)
if f=="FAIL" and d.get("failure_attribution")=="UNKNOWN" and d.get("promotion_requested"):
 print(json.dumps({"status":"FAIL","reason":"UNKNOWN_FAILURE_ATTRIBUTION_CANNOT_PROMOTE"})); sys.exit(3)
if f not in ("PASS","FAIL","BLOCKED"): print(json.dumps({"status":"FAIL","reason":"INVALID_FINAL_VERDICT"})); sys.exit(4)
print(json.dumps({"status":"PASS","final_verdict":f}))
