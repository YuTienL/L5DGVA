#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--plan",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.plan).read_text())
req=set(d.get("required_error_classes",[])); covered=set()
for t in d.get("tests",[]):
    if not t.get("checker_ids") and not t.get("assertion_ids"):
        print(json.dumps({"status":"FAIL","reason":"ERROR_TEST_WITHOUT_CHECK","testcase_id":t.get("testcase_id")})); sys.exit(2)
    covered |= set(t.get("error_classes",[]))
missing=sorted(req-covered)
if missing:
    print(json.dumps({"status":"FAIL","reason":"MISSING_ERROR_INJECTION_CLASSES","missing":missing})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
