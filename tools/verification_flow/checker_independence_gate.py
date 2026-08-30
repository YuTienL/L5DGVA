#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--checking",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.checking).read_text())

    for c in d.get("checkers",[]):
        cid=c.get("checker_id")
        if not c.get("implementation_source"):
            print(json.dumps({"status":"FAIL","reason":"CHECKER_WITHOUT_IMPLEMENTATION_SOURCE","checker_id":cid})); return 2
        if c.get("implementation_source")==c.get("dut_source"):
            print(json.dumps({"status":"FAIL","reason":"CHECKER_COPIES_DUT_LOGIC","checker_id":cid})); return 3
        if c.get("expected_data_source")=="DUT_OUTPUT_ONLY" and not c.get("independent_predictor"):
            print(json.dumps({"status":"FAIL","reason":"NO_INDEPENDENT_EXPECTED_MODEL","checker_id":cid})); return 4
        if c.get("checker_disabled") and c.get("signoff_credit"):
            print(json.dumps({"status":"FAIL","reason":"DISABLED_CHECKER_HAS_CREDIT","checker_id":cid})); return 5

    print(json.dumps({"status":"PASS","checkers":len(d.get("checkers",[]))})); return 0
if __name__=="__main__":
    sys.exit(main())
