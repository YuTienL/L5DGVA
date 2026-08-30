#!/usr/bin/env python3
import argparse,json,pathlib,sys

REQUIRED=[
 "protocol_name","spec_sources","dut_mapping","vip_strategy",
 "state_model","transaction_model","error_recovery_model",
 "verification_mechanism_plan","vplan_mapping","test_generation_strategy",
 "coverage_model","qualification_plan"
]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--profile",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.profile).read_text())
    missing=[x for x in REQUIRED if not d.get(x)]
    if missing:
        print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_PROTOCOL_ONBOARDING","missing":missing},indent=2))
        return 2
    if not d.get("evidence_refs"):
        print(json.dumps({"status":"FAIL","reason":"NO_PROTOCOL_EVIDENCE"})); return 3
    print(json.dumps({"status":"READY_FOR_PROTOCOL_QUALIFICATION","protocol":d["protocol_name"]}))
    return 0
if __name__=="__main__":
    sys.exit(main())
