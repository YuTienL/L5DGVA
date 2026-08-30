#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--coverage",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.coverage).read_text())
active_fail=set(d.get("active_failure_ids",[]))
for c in d.get("items",[]):
    cid=c.get("coverage_id")
    active_check=bool(c.get("active_checker_ids") or c.get("active_scoreboard_ids") or c.get("active_assertion_ids"))
    valid_waiver=bool(c.get("waived") and c.get("waiver_approved") and c.get("waiver_evidence"))
    linked_fail=active_fail & set(c.get("linked_failure_ids",[]))
    stated_credit=bool(c.get("credit"))
    # Derive whether this item actually earns credit from the raw signals
    # rather than trusting the agent's stated boolean at face value.
    derived_credit=(active_check or valid_waiver) and not linked_fail
    if c.get("waived") and active_check:
        print(json.dumps({"status":"FAIL","reason":"WAIVER_AND_ACTIVE_CHECK_CONFLICT","coverage_id":cid})); sys.exit(4)
    if not stated_credit: continue
    if not active_check and not valid_waiver:
        print(json.dumps({"status":"FAIL","reason":"CREDIT_WITHOUT_CHECK_OR_WAIVER","coverage_id":cid})); sys.exit(2)
    if linked_fail:
        print(json.dumps({"status":"FAIL","reason":"CREDIT_WITH_ACTIVE_FAILURE","coverage_id":cid,"failures":sorted(linked_fail)})); sys.exit(3)
    if stated_credit!=derived_credit:
        print(json.dumps({"status":"FAIL","reason":"CREDIT_FIELD_MISMATCH_WITH_DERIVED_EVIDENCE",
                          "coverage_id":cid,"stated_credit":stated_credit,"derived_credit":derived_credit})); sys.exit(5)
print(json.dumps({"status":"PASS"}))
