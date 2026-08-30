#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--audit", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.audit).read_text())
    seen=set()
    for x in d.get("actions",[]):
        nonce=x.get("nonce")
        if not nonce:
            print(json.dumps({"status":"FAIL","reason":"ACTION_WITHOUT_NONCE"})); return 2
        if nonce in seen:
            print(json.dumps({"status":"FAIL","reason":"REPLAYED_REMOTE_ACTION","nonce":nonce})); return 3
        seen.add(nonce)
    print(json.dumps({"status":"PASS","actions":len(seen)}))
    return 0

if __name__=="__main__":
    sys.exit(main())
