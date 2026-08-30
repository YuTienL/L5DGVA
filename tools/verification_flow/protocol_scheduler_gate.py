#!/usr/bin/env python3
import argparse,json,pathlib,sys

SERIAL_ONLY={"APB","APB2","APB3"}
PARALLEL={"USB","USB2","USB3","PCIe","AXI","AXI3","AXI4","AXIS","AXI-Stream"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--scheduler",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.scheduler).read_text())
    proto=d.get("protocol")
    mode=d.get("mode")
    if proto in SERIAL_ONLY and mode!="N_TO_1_SERIAL":
        print(json.dumps({"status":"FAIL","reason":"APB_MUST_SERIALIZE","protocol":proto})); return 2
    if proto in PARALLEL and mode not in ("N_TO_M_PARALLEL","M_TO_N_PARALLEL","M_TO_N_PARALLEL_INDEPENDENT_PORTS"):
        print(json.dumps({"status":"FAIL","reason":"PARALLEL_PROTOCOL_NOT_PARALLEL","protocol":proto})); return 3
    if d.get("cross_port_global_lock"):
        print(json.dumps({"status":"FAIL","reason":"CROSS_PORT_GLOBAL_LOCK_FORBIDDEN"})); return 4
    if proto in PARALLEL and not d.get("independent_port_queues"):
        print(json.dumps({"status":"FAIL","reason":"PARALLEL_PROTOCOL_NEEDS_INDEPENDENT_PORT_QUEUES"})); return 5
    print(json.dumps({"status":"PASS","protocol":proto,"mode":mode})); return 0
if __name__=="__main__": sys.exit(main())
