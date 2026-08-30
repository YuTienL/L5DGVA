#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--adaptation",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.adaptation).read_text())
for k in ("reference_uvm_hash","new_dut_architecture_hash","gap_analysis_hash","adaptation_plan_hash"):
    if not d.get(k):
        print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_REFERENCE_UVM_ADAPTATION","field":k})); sys.exit(2)
if d.get("blind_copy"):
    print(json.dumps({"status":"FAIL","reason":"REFERENCE_UVM_BLIND_COPY_FORBIDDEN"})); sys.exit(3)
if not d.get("dut_specific_changes"):
    print(json.dumps({"status":"FAIL","reason":"NO_DUT_SPECIFIC_ADAPTATION_PROVEN"})); sys.exit(4)
print(json.dumps({"status":"PASS"}))
