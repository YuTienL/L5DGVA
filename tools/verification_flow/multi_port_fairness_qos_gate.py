#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--ports",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.ports).read_text())
for p in d.get("ports",[]):
    pid=p.get("port_id")
    if p.get("min_service_share_percent") is None: print(json.dumps({"status":"FAIL","reason":"NO_MIN_SERVICE_SHARE","port_id":pid})); sys.exit(2)
    if p.get("observed_service_share_percent",0)<p.get("min_service_share_percent"): print(json.dumps({"status":"FAIL","reason":"FAIRNESS_VIOLATION","port_id":pid})); sys.exit(3)
    if p.get("qos_enabled") and not p.get("qos_policy_verified"): print(json.dumps({"status":"FAIL","reason":"QOS_NOT_VERIFIED","port_id":pid})); sys.exit(4)
print(json.dumps({"status":"PASS"}))
