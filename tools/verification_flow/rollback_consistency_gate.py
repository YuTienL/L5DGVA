#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--state",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.state).read_text())
    if d.get("rollback_applied"):
        if d.get("promotion_state")=="PROMOTED":
            print(json.dumps({"status":"FAIL","reason":"ROLLBACK_BUT_STILL_PROMOTED"})); return 2
        if not d.get("rollback_reason"):
            print(json.dumps({"status":"FAIL","reason":"ROLLBACK_WITHOUT_REASON"})); return 3
        if not d.get("revalidation_required"):
            print(json.dumps({"status":"FAIL","reason":"ROLLBACK_WITHOUT_REVALIDATION"})); return 4
    print(json.dumps({"status":"PASS"}))
    return 0
if __name__=="__main__":
    sys.exit(main())
