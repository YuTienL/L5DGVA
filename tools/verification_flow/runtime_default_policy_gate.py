#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--runtime",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.runtime).read_text())
    if d.get("WAVE")!=1:
        print(json.dumps({"status":"FAIL","reason":"WAVE_DEFAULT_MUST_BE_1"})); return 2
    if d.get("COVERAGE") not in (0,False):
        print(json.dumps({"status":"FAIL","reason":"COVERAGE_DEFAULT_MUST_BE_OFF"})); return 3
    if d.get("FSDB_START") not in (0,"0","time0"):
        print(json.dumps({"status":"FAIL","reason":"FSDB_START_DEFAULT_MUST_BE_TIME0"})); return 4
    if d.get("FSDB_STOP") not in ("SIM_END","simulation_end","end"):
        print(json.dumps({"status":"FAIL","reason":"FSDB_STOP_DEFAULT_MUST_BE_SIM_END"})); return 5
    if not d.get("supports_timeout"):
        print(json.dumps({"status":"FAIL","reason":"TIMEOUT_CONTROL_REQUIRED"})); return 6
    print(json.dumps({"status":"PASS"})); return 0
if __name__=="__main__": sys.exit(main())
