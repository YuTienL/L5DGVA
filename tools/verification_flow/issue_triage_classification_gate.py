#!/usr/bin/env python3
import argparse,json,pathlib,sys
A={"MISCLASSIFIED","KNOWN","REAL_ISSUE","BLOCKED"}
ap=argparse.ArgumentParser(); ap.add_argument("--issue",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.issue).read_text())
c=d.get("classification")
if c not in A: print(json.dumps({"status":"FAIL","reason":"INVALID_ISSUE_CLASSIFICATION"})); sys.exit(2)
if not d.get("classification_reason") or not d.get("evidence_hash"):
 print(json.dumps({"status":"FAIL","reason":"CLASSIFICATION_WITHOUT_EVIDENCE"})); sys.exit(3)
if c=="KNOWN" and not (d.get("known_issue_id") or d.get("waiver_id") or d.get("prior_rca_id")):
 print(json.dumps({"status":"FAIL","reason":"KNOWN_WITHOUT_REFERENCE"})); sys.exit(4)
if c=="REAL_ISSUE" and d.get("deep_rca_triggered") is not True:
 print(json.dumps({"status":"FAIL","reason":"REAL_ISSUE_WITHOUT_DEEP_RCA"})); sys.exit(5)
if c in ("MISCLASSIFIED","KNOWN") and d.get("deep_rca_triggered") and not d.get("contradictory_new_evidence"):
 print(json.dumps({"status":"FAIL","reason":"UNNECESSARY_DEEP_RCA"})); sys.exit(6)
print(json.dumps({"status":"PASS"}))
