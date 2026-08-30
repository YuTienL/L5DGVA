#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--knowledge", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.knowledge).read_text())

    required=["knowledge_id","title","pattern","root_cause","evidence","applicability_constraints","expert_approved"]
    missing=[x for x in required if x not in d]
    if missing:
        print(json.dumps({"status":"FAIL","reason":"MISSING_FIELDS","missing":missing})); return 2

    if not d.get("evidence"):
        print(json.dumps({"status":"FAIL","reason":"NO_EVIDENCE"})); return 3
    if not d.get("expert_approved"):
        print(json.dumps({"status":"FAIL","reason":"NOT_EXPERT_APPROVED"})); return 4
    if not d.get("applicability_constraints"):
        print(json.dumps({"status":"FAIL","reason":"NO_APPLICABILITY_CONSTRAINTS"})); return 5

    print(json.dumps({"status":"PROMOTABLE_TO_EXPERIENCE_DB","knowledge_id":d["knowledge_id"]}))
    return 0

if __name__=="__main__":
    sys.exit(main())
