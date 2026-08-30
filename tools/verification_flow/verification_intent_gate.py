#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--intent",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.intent).read_text())
    reqs={x["req_id"] for x in d.get("requirements",[]) if x.get("req_id")}
    mechs={x["mechanism_id"] for x in d.get("mechanisms",[]) if x.get("mechanism_id")}
    covs={x["coverage_id"] for x in d.get("coverage",[]) if x.get("coverage_id")}
    tests=d.get("tests",[])
    if not reqs: print(json.dumps({"status":"FAIL","reason":"NO_REQUIREMENTS"})); return 2
    if not mechs: print(json.dumps({"status":"FAIL","reason":"NO_MECHANISMS"})); return 3
    if not tests: print(json.dumps({"status":"FAIL","reason":"NO_TESTS"})); return 4
    if not covs: print(json.dumps({"status":"FAIL","reason":"NO_COVERAGE"})); return 5

    covered=set()
    for t in tests:
        tid=t.get("testcase_id")
        tr=set(t.get("requirement_ids",[]))
        tm=set(t.get("mechanism_ids",[]))
        tc=set(t.get("coverage_ids",[]))
        if not tr or not tm or not tc:
            print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_TEST_INTENT","testcase_id":tid})); return 6
        if not tr.issubset(reqs):
            print(json.dumps({"status":"FAIL","reason":"TEST_UNKNOWN_REQUIREMENT","testcase_id":tid})); return 7
        if not tm.issubset(mechs):
            print(json.dumps({"status":"FAIL","reason":"TEST_UNKNOWN_MECHANISM","testcase_id":tid})); return 8
        if not tc.issubset(covs):
            print(json.dumps({"status":"FAIL","reason":"TEST_UNKNOWN_COVERAGE","testcase_id":tid})); return 9
        covered |= tr
    missing=sorted(reqs-covered)
    if missing:
        print(json.dumps({"status":"FAIL","reason":"REQUIREMENT_WITHOUT_TEST_INTENT","missing":missing})); return 10
    print(json.dumps({"status":"PASS","requirements":len(reqs),"tests":len(tests)}))
    return 0
if __name__=="__main__":
    sys.exit(main())
