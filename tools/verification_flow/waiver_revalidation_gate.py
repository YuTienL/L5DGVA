#!/usr/bin/env python3
import argparse,json,pathlib,sys,datetime

def parse(s): return datetime.datetime.fromisoformat(s.replace("Z","+00:00"))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--waivers",required=True)
    ap.add_argument("--now",required=True)
    ap.add_argument("--current-revision",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.waivers).read_text())
    now=parse(a.now)

    for w in d.get("waivers",[]):
        wid=w.get("waiver_id")
        if not (w.get("approved") and w.get("evidence")):
            print(json.dumps({"status":"FAIL","reason":"INVALID_WAIVER","waiver_id":wid})); return 2
        if w.get("revision")!=a.current_revision and not w.get("revalidated_for_revision"):
            print(json.dumps({"status":"FAIL","reason":"WAIVER_REVISION_STALE","waiver_id":wid})); return 3
        if w.get("expires_at") and now > parse(w["expires_at"]):
            print(json.dumps({"status":"FAIL","reason":"WAIVER_EXPIRED","waiver_id":wid})); return 4
        if w.get("trigger_conditions_changed"):
            print(json.dumps({"status":"FAIL","reason":"WAIVER_REVALIDATION_REQUIRED","waiver_id":wid})); return 5

    print(json.dumps({"status":"PASS","waivers":len(d.get("waivers",[]))}))
    return 0

if __name__=="__main__":
    sys.exit(main())
