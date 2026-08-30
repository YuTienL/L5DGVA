#!/usr/bin/env python3
import argparse,json,pathlib,sys

EXPECTED=["PUSH","BUILD","VERIFY","RUN_WAVE_1","FSDBREPORT_ANALYSIS"]
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--pipeline",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.pipeline).read_text())
    steps=d.get("steps",[])
    if steps!=EXPECTED:
        print(json.dumps({"status":"FAIL","reason":"PIPELINE_ORDER_MISMATCH","expected":EXPECTED,"actual":steps})); return 2
    if not d.get("stop_on_failure"):
        print(json.dumps({"status":"FAIL","reason":"PIPELINE_MUST_STOP_ON_FAILURE"})); return 3
    if not d.get("fsdbreport_requires_wave_evidence"):
        print(json.dumps({"status":"FAIL","reason":"FSDBREPORT_WITHOUT_WAVE_EVIDENCE_CONTRACT"})); return 4
    print(json.dumps({"status":"PASS"})); return 0
if __name__=="__main__": sys.exit(main())
