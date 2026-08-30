#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--state",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.state).read_text())
if d.get("questions_asked_in_batch",1)>1 and not d.get("user_requested_batch_mode"):
    print(json.dumps({"status":"FAIL","reason":"NOT_STEP_BY_STEP_INTERACTION"})); sys.exit(2)
if d.get("evidence_answer_available") and d.get("asked_user_anyway"):
    print(json.dumps({"status":"FAIL","reason":"ASKED_USER_BEFORE_EVIDENCE_SEARCH"})); sys.exit(3)
if d.get("confidence")=="HIGH" and d.get("asked_user_for_same_fact"):
    print(json.dumps({"status":"FAIL","reason":"REDUNDANT_USER_QUESTION"})); sys.exit(4)
if d.get("confidence") in ("LOW","UNKNOWN") and not (d.get("ask_user") or d.get("continue_evidence_search")):
    print(json.dumps({"status":"FAIL","reason":"UNRESOLVED_AMBIGUITY_WITHOUT_ACTION"})); sys.exit(5)
if d.get("status") not in ("READY","PARTIAL","BLOCKED"):
    print(json.dumps({"status":"FAIL","reason":"INVALID_READINESS_STATE"})); sys.exit(6)
print(json.dumps({"status":"PASS"}))
