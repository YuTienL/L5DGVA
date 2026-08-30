#!/usr/bin/env python3
import argparse,json,pathlib,sys
ORDER=["PUSH","BUILD","VERIFY","RUN_WAVE_1","FSDBREPORT_ANALYSIS"]
ap=argparse.ArgumentParser(); ap.add_argument("--pipeline",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.pipeline).read_text()); stages=d.get("stages",[])
if [s.get("name") for s in stages]!=ORDER: print(json.dumps({"status":"FAIL","reason":"PIPELINE_ORDER_INVALID"})); sys.exit(2)
prev=None
for i,s in enumerate(stages):
    if not s.get("output_hash"): print(json.dumps({"status":"FAIL","reason":"STAGE_OUTPUT_WITHOUT_HASH","stage":s.get("name")})); sys.exit(3)
    if i and s.get("input_hash")!=prev: print(json.dumps({"status":"FAIL","reason":"PIPELINE_HASH_DISCONTINUITY","stage":s.get("name")})); sys.exit(4)
    prev=s["output_hash"]
print(json.dumps({"status":"PASS","final_hash":prev}))
