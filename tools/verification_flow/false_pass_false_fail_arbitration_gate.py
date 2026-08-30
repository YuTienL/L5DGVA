#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--input",required=True); a=ap.parse_args()
    d=json.loads(pathlib.Path(a.input).read_text())

    sim=d.get("simulation_status")
    sem=d.get("semantic_status")
    checker=d.get("checker_status")
    fatal=bool(d.get("fatal_or_uvm_error"))

    if sim=="PASS" and (sem!="TRUE_PASS" or checker=="FAIL" or fatal):
        print(json.dumps({"status":"FAIL","classification":"FALSE_PASS",
                          "reason":"SIM_PASS_CONTRADICTED_BY_VERIFICATION_EVIDENCE"})); return 2

    if sim=="FAIL" and sem=="TRUE_PASS" and checker=="PASS" and not fatal:
        if not d.get("infrastructure_failure_evidence"):
            print(json.dumps({"status":"FAIL","classification":"UNRESOLVED_FALSE_FAIL",
                              "reason":"SIM_FAIL_WITHOUT_VERIFICATION_FAILURE_EVIDENCE"})); return 3
        print(json.dumps({"status":"PASS","classification":"INFRASTRUCTURE_FAIL_NOT_DUT_FAIL"})); return 0

    if sim=="PASS" and sem=="TRUE_PASS" and checker=="PASS" and not fatal:
        print(json.dumps({"status":"PASS","classification":"TRUE_PASS"})); return 0

    if sim=="FAIL" and (checker=="FAIL" or fatal or d.get("design_failure_evidence")):
        print(json.dumps({"status":"PASS","classification":"TRUE_FAIL"})); return 0

    print(json.dumps({"status":"FAIL","classification":"INSUFFICIENT_EVIDENCE"})); return 4

if __name__=="__main__": sys.exit(main())
