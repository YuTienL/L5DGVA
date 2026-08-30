import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--state",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.state).read_text())
if d.get("signoff_requested"):
 if d.get("true_pass") is not True: print(json.dumps({"status":"FAIL","reason":"SIGNOFF_WITHOUT_TRUE_PASS"})); sys.exit(2)
 if d.get("active_failure_count",0)>0: print(json.dumps({"status":"FAIL","reason":"SIGNOFF_WITH_ACTIVE_FAILURES"})); sys.exit(3)
 if d.get("coverage_credit_percent",0)<100 and not d.get("approved_waivers"): print(json.dumps({"status":"FAIL","reason":"SIGNOFF_WITH_INCOMPLETE_COVERAGE"})); sys.exit(4)
 if d.get("waived_items",0)>0 and not d.get("approved_waivers"): print(json.dumps({"status":"FAIL","reason":"WAIVER_NOT_APPROVED"})); sys.exit(5)
print(json.dumps({"status":"PASS"}))
