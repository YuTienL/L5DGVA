#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    a=ap.parse_args()
    root=pathlib.Path(a.root)

    flow=json.loads((root/".dv-harness/workflow/verification_flow_v13.json").read_text())
    reg=json.loads((root/".dv-harness/workflow/hard_gate_registry.json").read_text())
    reg_tools={x["tool"] for x in reg.get("gates",[])}
    issues=[]

    for k,v in flow.items():
        if isinstance(v,str) and v.startswith("tools/") and v.endswith(".py"):
            if ("gate" in k or "validator" in k or "audit" in k) and v not in reg_tools:
                issues.append({"type":"FLOW_TOOL_NOT_REGISTERED","flow_key":k,"tool":v})
            if not (root/v).exists():
                issues.append({"type":"FLOW_TOOL_MISSING","flow_key":k,"tool":v})

    registered_ids=[x["gate_id"] for x in reg.get("gates",[])]
    if len(registered_ids)!=len(set(registered_ids)):
        issues.append({"type":"DUPLICATE_GATE_ID"})

    if issues:
        print(json.dumps({"status":"FAIL","issues":issues},indent=2)); return 2

    print(json.dumps({"status":"PASS","registered":len(reg.get("gates",[]))}))
    return 0

if __name__=="__main__":
    sys.exit(main())
