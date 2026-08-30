#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--feedback",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.feedback).read_text())
for f in d.get("items",[]):
    fid=f.get("feedback_id"); disp=f.get("disposition")
    if disp not in ("ACCEPTED","REJECTED","DEFERRED"):
        print(json.dumps({"status":"FAIL","reason":"FEEDBACK_WITHOUT_DISPOSITION","feedback_id":fid})); sys.exit(2)
    if not f.get("expert_id") or not f.get("rationale"):
        print(json.dumps({"status":"FAIL","reason":"FEEDBACK_WITHOUT_EXPERT_OR_RATIONALE","feedback_id":fid})); sys.exit(3)
    if disp=="ACCEPTED" and not (f.get("action_id") and f.get("closure_evidence_hash")):
        print(json.dumps({"status":"FAIL","reason":"ACCEPTED_FEEDBACK_NOT_CLOSED","feedback_id":fid})); sys.exit(4)
    if disp=="REJECTED" and not f.get("counter_evidence_hash"):
        print(json.dumps({"status":"FAIL","reason":"REJECTED_FEEDBACK_WITHOUT_COUNTER_EVIDENCE","feedback_id":fid})); sys.exit(5)
    if disp=="DEFERRED" and not f.get("tracking_issue_id"):
        print(json.dumps({"status":"FAIL","reason":"DEFERRED_FEEDBACK_NOT_TRACKED","feedback_id":fid})); sys.exit(6)
print(json.dumps({"status":"PASS"}))
