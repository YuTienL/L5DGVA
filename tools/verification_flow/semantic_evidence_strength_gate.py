#!/usr/bin/env python3
import argparse,json,pathlib,sys
RANK={"GENERIC_LOG":1,"PROTOCOL_TRANSACTION":2,"ASSERTION":3,"CHECKER":4,"SCOREBOARD":5}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--evidence",required=True); a=ap.parse_args()
    d=json.loads(pathlib.Path(a.evidence).read_text())
    min_rank=int(d.get("minimum_rank",2))
    for x in d.get("expectations",[]):
        eid=x.get("expectation_id")
        ev=x.get("evidence",[])
        if not ev:
            print(json.dumps({"status":"FAIL","reason":"NO_EVIDENCE","expectation_id":eid})); return 2
        best=max((RANK.get(e.get("type"),0) for e in ev),default=0)
        if best<min_rank:
            print(json.dumps({"status":"FAIL","reason":"WEAK_SEMANTIC_EVIDENCE",
                              "expectation_id":eid,"best_rank":best,"minimum_rank":min_rank})); return 3
        if any(e.get("contradicted") for e in ev):
            print(json.dumps({"status":"FAIL","reason":"CONTRADICTED_EVIDENCE","expectation_id":eid})); return 4
    print(json.dumps({"status":"PASS"})); return 0

if __name__=="__main__": sys.exit(main())
