#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.plan).read_text())

    required_top=["vplan_requirement_ids","architecture_nodes","verification_mechanisms","planned_testcases"]
    missing=[x for x in required_top if x not in d]
    if missing:
        print(json.dumps({"status":"FAIL","reason":"MISSING_FIELDS","missing":missing}))
        return 2

    reqs=d.get("vplan_requirement_ids") or []
    arch=d.get("architecture_nodes") or []
    mechs=d.get("verification_mechanisms") or []
    tests=d.get("planned_testcases") or []

    if not reqs:
        print(json.dumps({"status":"FAIL","reason":"NO_VPLAN_REQUIREMENTS"})); return 3
    if not arch:
        print(json.dumps({"status":"FAIL","reason":"NO_ARCHITECTURE_MAPPING"})); return 4
    if tests and not mechs:
        print(json.dumps({"status":"FAIL","reason":"TESTS_EXIST_BEFORE_MECHANISM"})); return 5

    valid_types={"MONITOR","PREDICTOR","REFERENCE_MODEL","SCOREBOARD","CHECKER","ASSERTION","COVERAGE","OTHER_APPROVED"}
    bad=[m for m in mechs if m.get("type") not in valid_types]
    if bad:
        print(json.dumps({"status":"FAIL","reason":"INVALID_MECHANISM_TYPE","bad":bad})); return 6

    # Each planned testcase must reference at least one mechanism unless approved alternate method
    mech_ids={m.get("mechanism_id") for m in mechs if m.get("mechanism_id")}
    for tc in tests:
        mids=tc.get("mechanism_ids",[])
        alt=tc.get("approved_alternate_verification_method")
        if not mids and not alt:
            print(json.dumps({"status":"FAIL","reason":"TEST_WITHOUT_MECHANISM","testcase_id":tc.get("testcase_id")})); return 7
        unknown=[x for x in mids if x not in mech_ids]
        if unknown:
            print(json.dumps({"status":"FAIL","reason":"UNKNOWN_MECHANISM_REFERENCE","testcase_id":tc.get("testcase_id"),"unknown":unknown})); return 8

    print(json.dumps({"status":"READY_FOR_TEST_GENERATION","requirements":len(reqs),"mechanisms":len(mechs),"tests":len(tests)}))
    return 0

if __name__=="__main__":
    sys.exit(main())
