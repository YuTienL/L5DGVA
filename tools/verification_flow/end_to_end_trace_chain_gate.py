#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--trace", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.trace).read_text())

    reqs={x.get("req_id") for x in d.get("requirements",[]) if x.get("req_id")}
    mechs={x.get("mechanism_id") for x in d.get("mechanisms",[]) if x.get("mechanism_id")}
    tests={x.get("testcase_id") for x in d.get("tests",[]) if x.get("testcase_id")}
    covs={x.get("coverage_id") for x in d.get("coverage",[]) if x.get("coverage_id")}
    results={x.get("result_id") for x in d.get("results",[]) if x.get("result_id")}
    rcas={x.get("rca_id") for x in d.get("rcas",[]) if x.get("rca_id")}

    if not all([reqs,mechs,tests,covs,results]):
        print(json.dumps({"status":"FAIL","reason":"TRACE_CHAIN_DOMAIN_EMPTY"})); return 2

    covered_reqs=set()
    for link in d.get("links",[]):
        rid=link.get("req_id"); mid=link.get("mechanism_id"); tid=link.get("testcase_id")
        cid=link.get("coverage_id"); resid=link.get("result_id"); rcaid=link.get("rca_id")
        if rid not in reqs or mid not in mechs or tid not in tests or cid not in covs or resid not in results:
            print(json.dumps({"status":"FAIL","reason":"BROKEN_TRACE_LINK","link":link})); return 3
        result=next(x for x in d["results"] if x.get("result_id")==resid)
        if result.get("result")=="FAIL":
            if not rcaid or rcaid not in rcas:
                print(json.dumps({"status":"FAIL","reason":"FAILED_RESULT_WITHOUT_RCA","result_id":resid})); return 4
        covered_reqs.add(rid)

    missing=sorted(reqs-covered_reqs)
    if missing:
        print(json.dumps({"status":"FAIL","reason":"REQUIREMENTS_WITHOUT_FULL_TRACE_CHAIN","missing":missing})); return 5

    print(json.dumps({"status":"PASS","requirements":len(reqs)}))
    return 0

if __name__=="__main__":
    sys.exit(main())
