#!/usr/bin/env python3
import argparse,json,pathlib,sys
GENERATED={"BUILD","REGRESSION","VPLAN","CHECKER","SCOREBOARD","ASSERTION","WAVEFORM","LOGS","SYSTEM_LEVEL","HISTORY"}
ap=argparse.ArgumentParser(); ap.add_argument("--inventory",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.inventory).read_text())
for x in d.get("artifacts",[]):
    cls=x.get("class")
    if cls in GENERATED and x.get("required_from_user"):
        print(json.dumps({"status":"FAIL","reason":"HARNESS_OUTPUT_REQUIRED_FROM_USER","artifact":cls})); sys.exit(2)
    if cls in GENERATED and x.get("owner")!="HARNESS":
        print(json.dumps({"status":"FAIL","reason":"GENERATED_ARTIFACT_OWNER_MISMATCH","artifact":cls})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
