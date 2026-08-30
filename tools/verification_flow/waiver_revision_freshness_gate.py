#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--state",required=True); x=a.parse_args()
d=json.loads(pathlib.Path(x.state).read_text()); cur=d.get("current",{})
for w in d.get("waivers",[]):
    wid=w.get("waiver_id")
    if w.get("spec_revision")!=cur.get("spec_revision") or w.get("rtl_hash")!=cur.get("rtl_hash"):
        if not (w.get("revalidated") and w.get("revalidation_evidence_hash")):
            print(json.dumps({"status":"FAIL","reason":"STALE_WAIVER_AFTER_REVISION_CHANGE","waiver_id":wid})); sys.exit(2)
    if w.get("expired") is True:
        print(json.dumps({"status":"FAIL","reason":"EXPIRED_WAIVER","waiver_id":wid})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
