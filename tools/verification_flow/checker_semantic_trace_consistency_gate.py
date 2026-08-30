import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--trace",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.trace).read_text())
for x in d.get("items",[]):
 eid=x.get("expectation_id")
 if x.get("semantic_status")!="MATCH": print(json.dumps({"status":"FAIL","reason":"CHECKER_CREDIT_WITHOUT_SEMANTIC_MATCH"})); sys.exit(2)
 if x.get("checker_status")!="PASS": print(json.dumps({"status":"FAIL","reason":"SEMANTIC_MATCH_WITHOUT_CHECKER_PASS"})); sys.exit(3)
 if not x.get("testcase_id") or not x.get("vplan_ids"): print(json.dumps({"status":"FAIL","reason":"CHECKER_SEMANTIC_TRACE_INCOMPLETE"})); sys.exit(4)
 if x.get("checker_expectation_id")!=eid: print(json.dumps({"status":"FAIL","reason":"CHECKER_EXPECTATION_ID_MISMATCH"})); sys.exit(5)
print(json.dumps({"status":"PASS"}))
