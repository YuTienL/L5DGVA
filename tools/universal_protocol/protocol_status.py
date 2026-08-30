#!/usr/bin/env python3
import json, pathlib
root=pathlib.Path(__file__).resolve().parents[2]
reg=root/'.dv-harness/qualification/protocol_capability_registry.json'
d=json.loads(reg.read_text())
print(f"{'PROTOCOL':34} {'STATUS':24} QUALIFICATION")
print("-"*80)
for k,v in d.get("protocols",{}).items():
    print(f"{k:34} {v.get('status','UNKNOWN'):24} {v.get('qualification_status','BUILDER_AVAILABLE')}")
