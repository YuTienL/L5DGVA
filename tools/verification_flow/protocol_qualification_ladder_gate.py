#!/usr/bin/env python3
import argparse, json, pathlib, sys

REQUIRED={"PCIe","Ethernet","MIPI_CSI2","MIPI_DSI","AMBA4","eDP","eMMC","SD_SDIO","UCIe","USB"}
ORDER=["UNQUALIFIED","SMOKE_QUALIFIED","REGRESSION_QUALIFIED","PRODUCTION_QUALIFIED"]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--matrix", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.matrix).read_text())
    fams={x.get("family"):x for x in d.get("protocols",[]) if x.get("family")}

    missing=sorted(REQUIRED-set(fams))
    if missing:
        print(json.dumps({"status":"FAIL","reason":"MISSING_PROTOCOL_FAMILY","missing":missing})); return 2

    for name in sorted(REQUIRED):
        p=fams[name]
        state=p.get("qualification_state")
        if state not in ORDER:
            print(json.dumps({"status":"FAIL","reason":"INVALID_QUALIFICATION_STATE","family":name})); return 3
        history=p.get("qualification_history",[])
        if state!="UNQUALIFIED":
            if not history:
                print(json.dumps({"status":"FAIL","reason":"QUALIFIED_WITHOUT_HISTORY","family":name})); return 4
            hist_states=[x.get("state") for x in history]
            if "SMOKE_QUALIFIED" not in hist_states:
                print(json.dumps({"status":"FAIL","reason":"MISSING_SMOKE_QUALIFICATION","family":name})); return 5
            if state in ("REGRESSION_QUALIFIED","PRODUCTION_QUALIFIED") and "REGRESSION_QUALIFIED" not in hist_states:
                print(json.dumps({"status":"FAIL","reason":"MISSING_REGRESSION_QUALIFICATION","family":name})); return 6
            if state=="PRODUCTION_QUALIFIED" and "PRODUCTION_QUALIFIED" not in hist_states:
                print(json.dumps({"status":"FAIL","reason":"MISSING_PRODUCTION_QUALIFICATION","family":name})); return 7
            if not all(x.get("evidence_hash") for x in history):
                print(json.dumps({"status":"FAIL","reason":"QUALIFICATION_HISTORY_WITHOUT_EVIDENCE","family":name})); return 8

    print(json.dumps({"status":"PASS","families":len(REQUIRED)}))
    return 0

if __name__=="__main__":
    sys.exit(main())
