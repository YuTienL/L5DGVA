#!/usr/bin/env python3
import argparse,json,pathlib,sys
KEYS=["testcase_id","seed","config_hash","build_hash","artifact_hash","command_hash"]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--replay",required=True); a=ap.parse_args()
    d=json.loads(pathlib.Path(a.replay).read_text())
    orig=d.get("original",{}); replay=d.get("replay",{})
    mismatch={}
    for k in KEYS:
        if orig.get(k)!=replay.get(k):
            mismatch[k]={"original":orig.get(k),"replay":replay.get(k)}
    if mismatch:
        print(json.dumps({"status":"FAIL","reason":"REPLAY_NOT_EQUIVALENT","mismatch":mismatch})); return 2
    if orig.get("result")!=replay.get("result"):
        print(json.dumps({"status":"FAIL","reason":"NON_REPRODUCIBLE_RESULT",
                          "original":orig.get("result"),"replay":replay.get("result")})); return 3
    print(json.dumps({"status":"PASS"})); return 0

if __name__=="__main__": sys.exit(main())
