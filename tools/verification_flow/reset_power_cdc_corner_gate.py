#!/usr/bin/env python3
import argparse,json,pathlib,sys

REQUIRED_DOMAINS={"RESET","CLOCK","CDC"}
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--plan",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.plan).read_text())

    items=d.get("corner_items",[])
    domains={x.get("domain") for x in items}
    missing=sorted(REQUIRED_DOMAINS-domains)
    if missing:
        print(json.dumps({"status":"FAIL","reason":"MISSING_MANDATORY_CORNER_DOMAINS","missing":missing})); return 2

    for x in items:
        cid=x.get("corner_id")
        if not x.get("requirement_ids"):
            print(json.dumps({"status":"FAIL","reason":"CORNER_WITHOUT_REQUIREMENT","corner_id":cid})); return 3
        if not x.get("mechanism_ids"):
            print(json.dumps({"status":"FAIL","reason":"CORNER_WITHOUT_MECHANISM","corner_id":cid})); return 4
        if not x.get("testcase_ids"):
            print(json.dumps({"status":"FAIL","reason":"CORNER_WITHOUT_TEST","corner_id":cid})); return 5
        if x.get("domain")=="CDC" and not x.get("cdc_observation_or_assertion"):
            print(json.dumps({"status":"FAIL","reason":"CDC_WITHOUT_OBSERVATION_OR_ASSERTION","corner_id":cid})); return 6
        if x.get("domain")=="RESET" and not x.get("async_or_partial_reset_covered"):
            print(json.dumps({"status":"FAIL","reason":"RESET_CORNER_INCOMPLETE","corner_id":cid})); return 7

    if d.get("power_aware_design"):
        p=[x for x in items if x.get("domain")=="POWER"]
        if not p:
            print(json.dumps({"status":"FAIL","reason":"POWER_AWARE_WITHOUT_POWER_CORNERS"})); return 8

    print(json.dumps({"status":"PASS","corner_items":len(items)})); return 0
if __name__=="__main__":
    sys.exit(main())
