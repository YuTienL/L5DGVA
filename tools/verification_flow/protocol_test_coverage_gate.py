#!/usr/bin/env python3
import argparse, json, pathlib, sys

REQUIRED={"PCIe","Ethernet","MIPI_CSI2","MIPI_DSI","AMBA4","eDP","eMMC","SD_SDIO","UCIe","USB"}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--matrix",required=True); a=ap.parse_args()
    d=json.loads(pathlib.Path(a.matrix).read_text())
    fams={x.get("family"):x for x in d.get("protocols",[]) if x.get("family")}
    miss=sorted(REQUIRED-set(fams))
    if miss:
        print(json.dumps({"status":"FAIL","reason":"MISSING_PROTOCOL_FAMILY_TEST_COVERAGE","missing":miss})); return 2
    for name in sorted(REQUIRED):
        p=fams[name]
        if not p.get("testcase_ids"):
            print(json.dumps({"status":"FAIL","reason":"PROTOCOL_WITHOUT_TESTCASES","family":name})); return 3
        if not p.get("coverage_ids"):
            print(json.dumps({"status":"FAIL","reason":"PROTOCOL_WITHOUT_COVERAGE","family":name})); return 4
        if not p.get("result_evidence_ids"):
            print(json.dumps({"status":"FAIL","reason":"PROTOCOL_WITHOUT_RESULT_EVIDENCE","family":name})); return 5
    print(json.dumps({"status":"PASS","families":len(REQUIRED)})); return 0

if __name__=="__main__":
    sys.exit(main())
