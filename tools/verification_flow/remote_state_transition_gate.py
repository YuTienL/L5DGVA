#!/usr/bin/env python3
import argparse,json,pathlib,sys

ALLOWED={
 "RUNNING":{"PAUSE":"PAUSED","STOP":"STOPPED","TAKEOVER":"TAKEOVER","STATUS":"RUNNING","WHY":"RUNNING","EVIDENCE":"RUNNING","REVIEW":"RUNNING","HYPOTHESIS":"RUNNING"},
 "PAUSED":{"RESUME":"RUNNING","STOP":"STOPPED","TAKEOVER":"TAKEOVER","STATUS":"PAUSED","WHY":"PAUSED","EVIDENCE":"PAUSED","REVIEW":"PAUSED","REDIRECT":"PAUSED","HYPOTHESIS":"PAUSED"},
 "TAKEOVER":{"RESUME":"RUNNING","STOP":"STOPPED","STATUS":"TAKEOVER","WHY":"TAKEOVER","EVIDENCE":"TAKEOVER","REVIEW":"TAKEOVER","REDIRECT":"TAKEOVER","HYPOTHESIS":"TAKEOVER"},
 "STOPPED":{"STATUS":"STOPPED","EVIDENCE":"STOPPED","REVIEW":"STOPPED","HYPOTHESIS":"STOPPED"}
}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--request",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.request).read_text())
    state=d.get("current_state"); cmd=d.get("command")
    nxt=ALLOWED.get(state,{}).get(cmd)
    if not nxt:
        print(json.dumps({"status":"FAIL","reason":"ILLEGAL_REMOTE_STATE_TRANSITION","current_state":state,"command":cmd})); return 2
    print(json.dumps({"status":"PASS","next_state":nxt}))
    return 0
if __name__=="__main__":
    sys.exit(main())
