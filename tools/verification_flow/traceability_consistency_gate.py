#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--trace", required=True)
    a=ap.parse_args()

    d=json.loads(pathlib.Path(a.trace).read_text())

    reqs=set(d.get("vplan_requirement_ids",[]))
    arch=set(d.get("architecture_nodes",[]))
    mechs=d.get("verification_mechanisms",[])
    tests=d.get("planned_testcases",[])
    coverage=set(d.get("coverage_ids",[]))

    if not reqs:
        print(json.dumps({"status":"FAIL","reason":"NO_REQUIREMENTS"})); return 2
    if not arch:
        print(json.dumps({"status":"FAIL","reason":"NO_ARCHITECTURE_MAPPING"})); return 3

    mech_ids=set()
    mech_req_refs=set()
    for m in mechs:
        mid=m.get("mechanism_id")
        if not mid:
            print(json.dumps({"status":"FAIL","reason":"MECHANISM_WITHOUT_ID"})); return 4
        mech_ids.add(mid)
        for r in m.get("vplan_requirement_ids",[]):
            if r not in reqs:
                print(json.dumps({"status":"FAIL","reason":"MECHANISM_UNKNOWN_REQUIREMENT","mechanism_id":mid,"requirement_id":r})); return 5
            mech_req_refs.add(r)

    seen_test_ids=set()
    test_req_refs=set()
    test_mech_refs=set()
    for tc in tests:
        tid=tc.get("testcase_id")
        if not tid:
            print(json.dumps({"status":"FAIL","reason":"TEST_WITHOUT_ID"})); return 6
        if tid in seen_test_ids:
            print(json.dumps({"status":"FAIL","reason":"DUPLICATE_TEST_ID","testcase_id":tid})); return 7
        seen_test_ids.add(tid)

        tr=tc.get("vplan_requirement_ids",[])
        if not tr:
            print(json.dumps({"status":"FAIL","reason":"TEST_WITHOUT_REQUIREMENT","testcase_id":tid})); return 8
        for r in tr:
            if r not in reqs:
                print(json.dumps({"status":"FAIL","reason":"TEST_UNKNOWN_REQUIREMENT","testcase_id":tid,"requirement_id":r})); return 9
            test_req_refs.add(r)

        mids=tc.get("mechanism_ids",[])
        if not mids and not tc.get("approved_alternate_verification_method"):
            print(json.dumps({"status":"FAIL","reason":"TEST_WITHOUT_MECHANISM","testcase_id":tid})); return 10
        for mid in mids:
            if mid not in mech_ids:
                print(json.dumps({"status":"FAIL","reason":"TEST_UNKNOWN_MECHANISM","testcase_id":tid,"mechanism_id":mid})); return 11
            test_mech_refs.add(mid)

        for cid in tc.get("coverage_ids",[]):
            if cid not in coverage:
                print(json.dumps({"status":"FAIL","reason":"TEST_UNKNOWN_COVERAGE","testcase_id":tid,"coverage_id":cid})); return 12

    uncovered=sorted(reqs - test_req_refs)
    unused_mechs=sorted(mech_ids - test_mech_refs)

    out={
      "status":"PASS" if not uncovered else "GAP",
      "uncovered_requirements":uncovered,
      "unused_mechanisms":unused_mechs,
      "requirement_count":len(reqs),
      "test_count":len(tests),
      "mechanism_count":len(mechs)
    }
    print(json.dumps(out,indent=2))
    return 0 if not uncovered else 13

if __name__=="__main__":
    sys.exit(main())
