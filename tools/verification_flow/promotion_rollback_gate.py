#!/usr/bin/env python3
import argparse,json,pathlib,sys

ROLLBACK_TRIGGERS={"STALE_EVIDENCE","NEW_CRITICAL_FAILURE","COVERAGE_REGRESSION","INVALID_WAIVER","SUBSYSTEM_RELEASE_CHANGED"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--state",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.state).read_text())
    if d.get("promotion_state")!="PROMOTED":
        print(json.dumps({"status":"PASS","reason":"NOT_PROMOTED"})); return 0
    triggers=set(d.get("detected_triggers",[]))
    if triggers & ROLLBACK_TRIGGERS:
        if not d.get("rollback_applied"):
            print(json.dumps({"status":"FAIL","reason":"ROLLBACK_REQUIRED","triggers":sorted(triggers & ROLLBACK_TRIGGERS)})); return 2
        print(json.dumps({"status":"ROLLED_BACK","triggers":sorted(triggers & ROLLBACK_TRIGGERS)})); return 0
    print(json.dumps({"status":"PASS","reason":"NO_ROLLBACK_TRIGGER"})); return 0

if __name__=="__main__":
    sys.exit(main())
