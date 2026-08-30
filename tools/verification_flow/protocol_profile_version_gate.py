#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--profile",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.profile).read_text())
    for k in ("protocol_name","profile_version","spec_revision","profile_hash","qualification_state"):
        if not d.get(k):
            print(json.dumps({"status":"FAIL","reason":"UNVERSIONED_PROTOCOL_PROFILE","missing":k})); return 2
    if d.get("qualification_state")=="QUALIFIED" and not d.get("qualification_evidence_hash"):
        print(json.dumps({"status":"FAIL","reason":"QUALIFIED_PROFILE_WITHOUT_EVIDENCE_HASH"})); return 3
    if d.get("supersedes") and not d.get("change_summary"):
        print(json.dumps({"status":"FAIL","reason":"PROFILE_SUPERSESSION_WITHOUT_CHANGE_SUMMARY"})); return 4
    print(json.dumps({"status":"PASS","protocol":d["protocol_name"],"version":d["profile_version"]}))
    return 0
if __name__=="__main__":
    sys.exit(main())
