#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--coverage",required=True); a=ap.parse_args()
    d=json.loads(pathlib.Path(a.coverage).read_text())
    for g in d.get("gates",[]):
        gid=g.get("gate_id")
        if not g.get("positive_test_ids"):
            print(json.dumps({"status":"FAIL","reason":"GATE_WITHOUT_POSITIVE_TEST","gate_id":gid})); return 2
        if not g.get("negative_test_ids"):
            print(json.dumps({"status":"FAIL","reason":"GATE_WITHOUT_NEGATIVE_TEST","gate_id":gid})); return 3
        if not g.get("tool_exists"):
            print(json.dumps({"status":"FAIL","reason":"GATE_TOOL_MISSING","gate_id":gid})); return 4
    print(json.dumps({"status":"PASS","gates":len(d.get("gates",[]))})); return 0

if __name__=="__main__":
    sys.exit(main())
