#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--trace", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.trace).read_text())

    # Escape hatch (added 2026-08-28, same convention as
    # system_level_subsystem_set_completeness_gate/system_level_validator):
    # this gate previously had no way for a pure IP-level (non-multi-subsystem)
    # flow to legitimately decline it -- it always demanded >=2 selected
    # subsystems even when SYSTEM_LEVEL composition genuinely does not apply.
    if d.get("system_level_applicable") is False:
        reason = d.get("system_level_not_applicable_reason")
        if not reason:
            print(json.dumps({"status":"FAIL","reason":"NOT_APPLICABLE_WITHOUT_JUSTIFICATION"})); return 11
        print(json.dumps({"status":"SKIPPED_NOT_APPLICABLE","reason":reason})); return 0

    selected=set(d.get("selected_subsystems",[]))
    reqs=set(d.get("system_requirement_ids",[]))
    scenarios=d.get("scenarios",[])
    if len(selected) < 2:
        print(json.dumps({"status":"FAIL","reason":"INSUFFICIENT_SELECTED_SUBSYSTEMS"})); return 2
    if not reqs:
        print(json.dumps({"status":"FAIL","reason":"NO_SYSTEM_REQUIREMENTS"})); return 3
    if not scenarios:
        print(json.dumps({"status":"FAIL","reason":"NO_SCENARIOS"})); return 4

    covered=set()
    for sc in scenarios:
        sid=sc.get("scenario_id")
        parts=set(sc.get("participating_subsystems",[]))
        if len(parts) < 2:
            print(json.dumps({"status":"FAIL","reason":"SCENARIO_NOT_CROSS_SUBSYSTEM","scenario_id":sid})); return 5
        unknown=parts-selected
        if unknown:
            print(json.dumps({"status":"FAIL","reason":"SCENARIO_UNKNOWN_SUBSYSTEM","scenario_id":sid,"unknown":sorted(unknown)})); return 6

        rids=set(sc.get("system_requirement_ids",[]))
        unknown_req=rids-reqs
        if unknown_req:
            print(json.dumps({"status":"FAIL","reason":"SCENARIO_UNKNOWN_REQUIREMENT","scenario_id":sid,"unknown":sorted(unknown_req)})); return 7
        covered |= rids

        if not sc.get("mechanism_ids"):
            print(json.dumps({"status":"FAIL","reason":"SCENARIO_WITHOUT_MECHANISM","scenario_id":sid})); return 8
        if not sc.get("coverage_ids"):
            print(json.dumps({"status":"FAIL","reason":"SCENARIO_WITHOUT_COVERAGE","scenario_id":sid})); return 9

    uncovered=sorted(reqs-covered)
    if uncovered:
        print(json.dumps({"status":"FAIL","reason":"UNCOVERED_SYSTEM_REQUIREMENTS","uncovered":uncovered})); return 10

    print(json.dumps({"status":"PASS","requirements":len(reqs),"scenarios":len(scenarios)}))
    return 0

if __name__=="__main__":
    sys.exit(main())
