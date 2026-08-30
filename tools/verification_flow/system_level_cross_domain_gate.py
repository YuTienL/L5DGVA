#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--plan",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.plan).read_text())
for s in d.get("scenarios",[]):
    sid=s.get("scenario_id")
    domains=set(s.get("domains",[]))
    if len(domains)<2:
        print(json.dumps({"status":"FAIL","reason":"NOT_CROSS_DOMAIN","scenario_id":sid})); sys.exit(2)
    if "SHARED_RESOURCE" in domains and not s.get("contention_policy"):
        print(json.dumps({"status":"FAIL","reason":"SHARED_RESOURCE_WITHOUT_POLICY","scenario_id":sid})); sys.exit(3)
    if "INTERRUPT" in domains and not s.get("interrupt_latency_or_loss_check"):
        print(json.dumps({"status":"FAIL","reason":"INTERRUPT_DOMAIN_WITHOUT_CHECK","scenario_id":sid})); sys.exit(4)
    if ("RESET" in domains or "POWER" in domains) and not s.get("recovery_or_reinit_check"):
        print(json.dumps({"status":"FAIL","reason":"RESET_POWER_DOMAIN_WITHOUT_RECOVERY_CHECK","scenario_id":sid})); sys.exit(5)
    if not s.get("evidence"):
        print(json.dumps({"status":"FAIL","reason":"CROSS_DOMAIN_WITHOUT_EVIDENCE","scenario_id":sid})); sys.exit(6)
print(json.dumps({"status":"PASS"}))
