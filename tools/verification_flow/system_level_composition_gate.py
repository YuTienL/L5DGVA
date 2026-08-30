#!/usr/bin/env python3
import argparse, json, pathlib, sys

REQUIRED_SUBSYSTEM_FIELDS = [
    "name","environment_manifest","release_sha","qualification_state",
    "interface_compatibility","clock_reset_compatibility"
]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--composition", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.composition).read_text())

    subs=d.get("selected_subsystems",[])
    if len(subs) < 2:
        print(json.dumps({"status":"FAIL","reason":"NEED_AT_LEAST_TWO_SUBSYSTEMS"}))
        return 2

    names=set()
    for s in subs:
        missing=[k for k in REQUIRED_SUBSYSTEM_FIELDS if not s.get(k)]
        if missing:
            print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_SUBSYSTEM_IDENTITY","subsystem":s.get("name"),"missing":missing}))
            return 3
        if s["name"] in names:
            print(json.dumps({"status":"FAIL","reason":"DUPLICATE_SUBSYSTEM","subsystem":s["name"]}))
            return 4
        names.add(s["name"])
        if s["qualification_state"] not in ("REGRESSION_QUALIFIED","PRODUCTION_QUALIFIED","SMOKE_QUALIFIED"):
            print(json.dumps({"status":"FAIL","reason":"INVALID_QUALIFICATION_STATE","subsystem":s["name"]}))
            return 5
        if s["interface_compatibility"] != "PASS" or s["clock_reset_compatibility"] != "PASS":
            print(json.dumps({"status":"FAIL","reason":"SUBSYSTEM_COMPATIBILITY_FAIL","subsystem":s["name"]}))
            return 6

    scenarios=d.get("system_level_scenarios",[])
    if not scenarios:
        print(json.dumps({"status":"FAIL","reason":"NO_SYSTEM_LEVEL_SCENARIOS"}))
        return 7

    for sc in scenarios:
        participants=set(sc.get("participating_subsystems",[]))
        if not participants:
            print(json.dumps({"status":"FAIL","reason":"SCENARIO_WITHOUT_PARTICIPANTS","scenario":sc.get("scenario_id")}))
            return 8
        unknown=participants-names
        if unknown:
            print(json.dumps({"status":"FAIL","reason":"SCENARIO_UNKNOWN_SUBSYSTEM","scenario":sc.get("scenario_id"),"unknown":sorted(unknown)}))
            return 9
        if len(participants) < 2:
            print(json.dumps({"status":"FAIL","reason":"NOT_CROSS_SUBSYSTEM_SCENARIO","scenario":sc.get("scenario_id")}))
            return 10

    print(json.dumps({"status":"READY_FOR_SYSTEM_LEVEL","subsystem_count":len(subs),"scenario_count":len(scenarios)}))
    return 0

if __name__=="__main__":
    sys.exit(main())
