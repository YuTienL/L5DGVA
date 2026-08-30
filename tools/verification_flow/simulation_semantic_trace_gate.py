#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--result",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.result).read_text())

    if d.get("final_state")!="TRUE_PASS" or not d.get("signoff_credit_allowed"):
        print(json.dumps({"status":"FAIL","reason":"SEMANTIC_RESULT_NOT_TRUE_PASS"}))
        return 2

    for r in d.get("results",[]):
        if r.get("status")!="MATCH":
            print(json.dumps({"status":"FAIL","reason":"NON_MATCH_EXPECTATION",
                              "expectation_id":r.get("expectation_id")}))
            return 3
        if r.get("source_line") is None:
            print(json.dumps({"status":"FAIL","reason":"MISSING_COMMAND_SOURCE_PROVENANCE",
                              "expectation_id":r.get("expectation_id")}))
            return 4
        if not r.get("evidence_source"):
            print(json.dumps({"status":"FAIL","reason":"MISSING_EVIDENCE_PROVENANCE",
                              "expectation_id":r.get("expectation_id")}))
            return 5

    print(json.dumps({"status":"PASS","signoff_credit_allowed":True}))
    return 0

if __name__=="__main__":
    sys.exit(main())
