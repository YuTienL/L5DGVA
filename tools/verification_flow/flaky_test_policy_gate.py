#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--flaky",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.flaky).read_text())
    for t in d.get("tests",[]):
        tid=t.get("testcase_id")
        rate=float(t.get("failure_rate_percent",0))
        if rate>0:
            if not t.get("classified"):
                print(json.dumps({"status":"FAIL","reason":"UNCLASSIFIED_FLAKY_TEST","testcase_id":tid})); return 2
            if not t.get("owner"):
                print(json.dumps({"status":"FAIL","reason":"FLAKY_TEST_WITHOUT_OWNER","testcase_id":tid})); return 3
            if t.get("quarantined") and not t.get("quarantine_reason"):
                print(json.dumps({"status":"FAIL","reason":"QUARANTINE_WITHOUT_REASON","testcase_id":tid})); return 4
            if t.get("retry_count",0)>t.get("max_allowed_retry",1):
                print(json.dumps({"status":"FAIL","reason":"EXCESSIVE_RETRY_MASKING_FAILURE","testcase_id":tid})); return 5
            if t.get("credit_allowed") and t.get("quarantined"):
                print(json.dumps({"status":"FAIL","reason":"QUARANTINED_TEST_HAS_SIGNOFF_CREDIT","testcase_id":tid})); return 6
    print(json.dumps({"status":"PASS"})); return 0
if __name__=="__main__":
    sys.exit(main())
