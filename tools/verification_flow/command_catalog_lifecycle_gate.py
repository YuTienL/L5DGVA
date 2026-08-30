#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.catalog).read_text())

    commands=d.get("commands",[])
    if not commands:
        print(json.dumps({"status":"FAIL","reason":"NO_COMMANDS"})); return 2

    seen=set()
    for c in commands:
        cid=c.get("command_id")
        if not cid:
            print(json.dumps({"status":"FAIL","reason":"COMMAND_WITHOUT_ID"})); return 3
        if cid in seen:
            print(json.dumps({"status":"FAIL","reason":"DUPLICATE_COMMAND_ID","command_id":cid})); return 4
        seen.add(cid)

        if c.get("verification_level") not in ("BLOCK_IP","SUBSYSTEM","SYSTEM_LEVEL"):
            print(json.dumps({"status":"FAIL","reason":"INVALID_VERIFICATION_LEVEL","command_id":cid})); return 5
        if not c.get("category") or not c.get("destination"):
            print(json.dumps({"status":"FAIL","reason":"UNCLASSIFIED_COMMAND","command_id":cid})); return 6

    obsolete=d.get("obsolete_directories",[])
    for od in obsolete:
        if not od.get("safe_to_delete"):
            print(json.dumps({"status":"FAIL","reason":"UNSAFE_OBSOLETE_DIRECTORY","path":od.get("path")})); return 7
        if not od.get("reference_scan_clean"):
            print(json.dumps({"status":"FAIL","reason":"OBSOLETE_DIRECTORY_STILL_REFERENCED","path":od.get("path")})); return 8

    print(json.dumps({"status":"PASS","command_count":len(commands),"obsolete_dirs":len(obsolete)}))
    return 0

if __name__=="__main__":
    sys.exit(main())
