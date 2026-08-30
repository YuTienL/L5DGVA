#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--runs",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.runs).read_text())
    runs=d.get("runs",[])
    if len(runs)<2:
        print(json.dumps({"status":"FAIL","reason":"NEED_AT_LEAST_TWO_RUNS"})); return 2

    baseline=runs[0]
    invariant_fields=["rtl_revision","tb_revision","vip_version","config_hash","testlist_hash"]
    for r in runs[1:]:
        for f in invariant_fields:
            if r.get(f)!=baseline.get(f):
                print(json.dumps({"status":"FAIL","reason":"RUN_CONTEXT_DRIFT","field":f,
                                  "baseline":baseline.get(f),"actual":r.get(f),"run_id":r.get("run_id")}))
                return 3
    if any(not r.get("evidence_bundle_hash") for r in runs):
        print(json.dumps({"status":"FAIL","reason":"RUN_WITHOUT_EVIDENCE_BUNDLE_HASH"})); return 4

    print(json.dumps({"status":"PASS","runs":len(runs)}))
    return 0

if __name__=="__main__":
    sys.exit(main())
