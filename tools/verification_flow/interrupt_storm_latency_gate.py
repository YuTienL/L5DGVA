#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--interrupts",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.interrupts).read_text())
for x in d.get("sources",[]):
    sid=x.get("source_id")
    if x.get("max_ack_latency_cycles") is None: print(json.dumps({"status":"FAIL","reason":"NO_ACK_LATENCY_BOUND","source_id":sid})); sys.exit(2)
    if x.get("observed_max_ack_latency_cycles",0)>x.get("max_ack_latency_cycles"): print(json.dumps({"status":"FAIL","reason":"ACK_LATENCY_VIOLATION","source_id":sid})); sys.exit(3)
    if x.get("storm_rate") and not x.get("storm_test_evidence"): print(json.dumps({"status":"FAIL","reason":"INTERRUPT_STORM_WITHOUT_EVIDENCE","source_id":sid})); sys.exit(4)
    if x.get("lost_interrupts",0)>0: print(json.dumps({"status":"FAIL","reason":"LOST_INTERRUPTS","source_id":sid})); sys.exit(5)
print(json.dumps({"status":"PASS"}))
