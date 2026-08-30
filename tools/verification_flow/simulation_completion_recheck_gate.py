#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--state",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.state).read_text())

ended = d.get("simulation_ended") is True
notification = d.get("background_completion_notification") is True
elapsed = float(d.get("minutes_since_last_check",0))

if ended:
    if d.get("semantic_workflow_started") is not True:
        print(json.dumps({"status":"FAIL","reason":"SIM_ENDED_BUT_SEMANTIC_WORKFLOW_NOT_STARTED"})); sys.exit(2)
    print(json.dumps({"status":"PASS","next":"semantic_postcheck"})); sys.exit(0)

# Not ended yet.
if notification:
    if d.get("recheck_performed") is not True:
        print(json.dumps({"status":"FAIL","reason":"BACKGROUND_NOTIFICATION_NOT_RECHECKED"})); sys.exit(3)
    print(json.dumps({"status":"PASS","next":"recheck_now"})); sys.exit(0)

if elapsed >= 4.0:
    if d.get("recheck_performed") is not True:
        print(json.dumps({"status":"FAIL","reason":"FOUR_MINUTE_RECHECK_MISSED"})); sys.exit(4)
    print(json.dumps({"status":"PASS","next":"recheck_now"})); sys.exit(0)

if d.get("recheck_scheduled_for_minute") != 4:
    print(json.dumps({"status":"FAIL","reason":"RECHECK_NOT_SCHEDULED_AT_FOUR_MINUTES"})); sys.exit(5)

print(json.dumps({"status":"PASS","next":"wait_for_4min_or_notification"}))
