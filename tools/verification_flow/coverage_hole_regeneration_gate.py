#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--holes",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.holes).read_text())

    holes=d.get("coverage_holes",[])
    for h in holes:
        hid=h.get("coverage_id")
        if h.get("waived"):
            if not (h.get("waiver_approved") and h.get("waiver_evidence")):
                print(json.dumps({"status":"FAIL","reason":"INVALID_COVERAGE_HOLE_WAIVER","coverage_id":hid})); return 2
            continue
        if not h.get("root_cause_classification"):
            print(json.dumps({"status":"FAIL","reason":"UNCLASSIFIED_COVERAGE_HOLE","coverage_id":hid})); return 3
        if h.get("root_cause_classification") in ("MISSING_TEST","INSUFFICIENT_CONSTRAINT","UNREACHABLE_STIMULUS"):
            if not h.get("regenerated_testcase_ids"):
                print(json.dumps({"status":"FAIL","reason":"COVERAGE_HOLE_WITHOUT_TEST_REGENERATION","coverage_id":hid})); return 4
            if not h.get("rerun_evidence"):
                print(json.dumps({"status":"FAIL","reason":"REGENERATED_TEST_WITHOUT_RERUN","coverage_id":hid})); return 5

    print(json.dumps({"status":"PASS","holes":len(holes)})); return 0
if __name__=="__main__":
    sys.exit(main())
