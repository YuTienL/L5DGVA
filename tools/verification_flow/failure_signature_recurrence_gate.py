#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--failures",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.failures).read_text())

    seen={}
    for f in d.get("failures",[]):
        sig=f.get("signature")
        fid=f.get("failure_id")
        if not sig:
            print(json.dumps({"status":"FAIL","reason":"FAILURE_WITHOUT_SIGNATURE","failure_id":fid})); return 2
        if sig in seen:
            if not f.get("linked_to_existing_failure"):
                print(json.dumps({"status":"FAIL","reason":"DUPLICATE_FAILURE_NOT_LINKED","failure_id":fid,"existing":seen[sig]})); return 3
            if f.get("previously_fixed") and not f.get("recurrence_escalated"):
                print(json.dumps({"status":"FAIL","reason":"RECURRENT_FIXED_BUG_NOT_ESCALATED","failure_id":fid})); return 4
        else:
            seen[sig]=fid

    print(json.dumps({"status":"PASS","unique_signatures":len(seen)})); return 0
if __name__=="__main__":
    sys.exit(main())
