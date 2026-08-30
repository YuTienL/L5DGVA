#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--reference",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.reference).read_text())

    if not d.get("reference_name"):
        print(json.dumps({"status":"FAIL","reason":"NO_REFERENCE_NAME"})); return 2
    if not d.get("reference_revision") or not d.get("reference_hash"):
        print(json.dumps({"status":"FAIL","reason":"UNPINNED_REFERENCE_ENV"})); return 3
    if not d.get("compatibility_analysis"):
        print(json.dumps({"status":"FAIL","reason":"NO_COMPATIBILITY_ANALYSIS"})); return 4

    required=("protocol_role","interface_mapping","config_mapping","sequence_reuse","scoreboard_checker_reuse")
    missing=[x for x in required if x not in d["compatibility_analysis"]]
    if missing:
        print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_REFERENCE_COMPATIBILITY","missing":missing})); return 5

    if d.get("reuse_decision")=="REUSE" and not d.get("adaptation_plan"):
        print(json.dumps({"status":"FAIL","reason":"REUSE_WITHOUT_ADAPTATION_PLAN"})); return 6

    print(json.dumps({"status":"PASS","reference":d["reference_name"],"reuse_decision":d.get("reuse_decision")})); return 0
if __name__=="__main__":
    sys.exit(main())
