#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--migration",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.migration).read_text())
    items=d.get("commands",[])
    if not items:
        print(json.dumps({"status":"FAIL","reason":"NO_COMMAND_MIGRATIONS"})); return 2
    for x in items:
        cid=x.get("command_id")
        if not x.get("source_hash") or not x.get("destination_hash"):
            print(json.dumps({"status":"FAIL","reason":"MISSING_COMMAND_HASH","command_id":cid})); return 3
        if x["source_hash"]!=x["destination_hash"] and not x.get("approved_transform"):
            print(json.dumps({"status":"FAIL","reason":"COMMAND_CONTENT_CHANGED","command_id":cid})); return 4
    print(json.dumps({"status":"PASS","commands":len(items)}))
    return 0
if __name__=="__main__":
    sys.exit(main())
