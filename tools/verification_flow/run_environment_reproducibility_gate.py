#!/usr/bin/env python3
import argparse,json,pathlib,sys
a=argparse.ArgumentParser(); a.add_argument("--run",required=True); x=a.parse_args(); d=json.loads(pathlib.Path(x.run).read_text())
for k in ("rtl_hash","testbench_hash","simulator_version","vip_version","compile_options_hash","runtime_options_hash","env_hash"):
 if not d.get(k): print(json.dumps({"status":"FAIL","reason":"MISSING_REPRODUCIBILITY_FINGERPRINT","field":k})); sys.exit(2)
if d.get("final_verdict")=="PASS" and not d.get("replay_command"): print(json.dumps({"status":"FAIL","reason":"PASS_WITHOUT_REPLAY_COMMAND"})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
