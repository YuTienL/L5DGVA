#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--matrix",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.matrix).read_text())
    required_features=set(d.get("required_feature_combinations",[]))
    for p in d.get("ports",[]):
        pid=p.get("port_id")
        for k in ("scoreboard","checker","performance_calculator","coverage_collector"):
            if not p.get(k):
                print(json.dumps({"status":"FAIL","reason":"MISSING_PER_PORT_MECHANISM","port_id":pid,"mechanism":k})); return 2
        covered=set(p.get("covered_feature_combinations",[]))
        missing=sorted(required_features-covered)
        if missing:
            print(json.dumps({"status":"FAIL","reason":"PORT_FEATURE_MATRIX_GAP","port_id":pid,"missing":missing})); return 3
    print(json.dumps({"status":"PASS","ports":len(d.get("ports",[]))})); return 0
if __name__=="__main__": sys.exit(main())
