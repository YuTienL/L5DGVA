#!/usr/bin/env python3
import argparse,json,pathlib,sys

REQ=["testcase_id","run_id","rtl_revision","tb_revision","vip_version","tool_version",
     "seed","config_hash","result","log_hash","evidence_bundle_hash"]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--results",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.results).read_text())
    items=d.get("results",[])
    if not items:
        print(json.dumps({"status":"FAIL","reason":"NO_RESULTS"})); return 2
    seen=set()
    for r in items:
        missing=[k for k in REQ if r.get(k) in (None,"")]
        if missing:
            print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_RESULT_PROVENANCE",
                              "testcase_id":r.get("testcase_id"),"missing":missing})); return 3
        key=(r["testcase_id"],r["run_id"])
        if key in seen:
            print(json.dumps({"status":"FAIL","reason":"DUPLICATE_RESULT_RECORD","key":list(key)})); return 4
        seen.add(key)
    print(json.dumps({"status":"PASS","results":len(items)}))
    return 0
if __name__=="__main__":
    sys.exit(main())
