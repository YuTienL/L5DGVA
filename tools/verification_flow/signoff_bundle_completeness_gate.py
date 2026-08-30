#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--bundle",required=True); x=a.parse_args(); d=json.loads(pathlib.Path(x.bundle).read_text())
required={"SPEC_TRACE","BUILD","TEST","ASSERTION","SCOREBOARD","COVERAGE","REGRESSION","RCA_FIX","ENV_FINGERPRINT"}
got={e.get("class") for e in d.get("evidence",[]) if e.get("hash")}; missing=sorted(required-got)
if missing: print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_SIGNOFF_BUNDLE","missing":missing})); sys.exit(2)
if not d.get("bundle_hash") or d.get("final_verdict")!="PASS": print(json.dumps({"status":"FAIL","reason":"INVALID_FINAL_SIGNOFF_BUNDLE"})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
