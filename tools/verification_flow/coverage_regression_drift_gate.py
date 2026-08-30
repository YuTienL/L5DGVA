#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--coverage",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.coverage).read_text())
    threshold=float(d.get("allowed_drop_percent",0.0))
    bad=[]
    for c in d.get("items",[]):
        prev=float(c.get("previous_credit",0))
        cur=float(c.get("current_credit",0))
        if prev<=0: continue
        drop=(prev-cur)/prev*100.0
        if drop>threshold and not c.get("approved_drop"):
            bad.append({"coverage_id":c.get("coverage_id"),"drop_percent":drop})
    if bad:
        print(json.dumps({"status":"FAIL","reason":"COVERAGE_REGRESSION_DRIFT","items":bad},indent=2)); return 2
    print(json.dumps({"status":"PASS"})); return 0

if __name__=="__main__":
    sys.exit(main())
