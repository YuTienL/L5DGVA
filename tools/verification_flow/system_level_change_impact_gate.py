#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--impact",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.impact).read_text())

    changed=set(d.get("changed_subsystems",[]))
    selected=set(d.get("selected_subsystems",[]))
    if not changed:
        print(json.dumps({"status":"PASS","reason":"NO_SUBSYSTEM_CHANGE"})); return 0
    if not changed.issubset(selected):
        print(json.dumps({"status":"FAIL","reason":"UNKNOWN_CHANGED_SUBSYSTEM","unknown":sorted(changed-selected)})); return 2

    impacted=set()
    for sc in d.get("system_scenarios",[]):
        parts=set(sc.get("participating_subsystems",[]))
        if parts & changed:
            impacted.add(sc.get("scenario_id"))
    planned=set(d.get("rerun_scenarios",[]))
    missing=sorted(impacted-planned)
    if missing:
        print(json.dumps({"status":"FAIL","reason":"MISSING_IMPACTED_RERUN_SCENARIOS","missing":missing})); return 3
    print(json.dumps({"status":"PASS","impacted_scenarios":sorted(impacted)})); return 0

if __name__=="__main__":
    sys.exit(main())
