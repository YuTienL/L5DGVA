#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--knowledge", required=True)
    ap.add_argument("--context", required=True)
    a=ap.parse_args()

    k=json.loads(pathlib.Path(a.knowledge).read_text())
    c=json.loads(pathlib.Path(a.context).read_text())

    if not k.get("expert_approved") or not k.get("evidence"):
        print(json.dumps({"status":"FAIL","reason":"KNOWLEDGE_NOT_QUALIFIED"})); return 2

    constraints=k.get("applicability_constraints",{})
    mismatches=[]
    for key,val in constraints.items():
        actual=c.get(key)
        if isinstance(val,list):
            if actual not in val:
                mismatches.append({"field":key,"expected_any":val,"actual":actual})
        else:
            if actual != val:
                mismatches.append({"field":key,"expected":val,"actual":actual})

    if mismatches:
        print(json.dumps({"status":"NOT_APPLICABLE","mismatches":mismatches},indent=2)); return 3

    print(json.dumps({"status":"APPLICABLE","knowledge_id":k.get("knowledge_id")}))
    return 0

if __name__=="__main__":
    sys.exit(main())
