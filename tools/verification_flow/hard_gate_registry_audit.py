#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--root",required=True); a=ap.parse_args()
root=pathlib.Path(a.root)
reg=json.loads((root/".dv-harness/workflow/hard_gate_registry.json").read_text())
tests_text="\n".join(p.read_text(encoding="utf-8",errors="ignore") for p in root.rglob("test_*.py"))
bad=[]
for g in reg.get("gates",[]):
    tool=root/g["tool"]
    if not tool.exists(): bad.append({"gate":g["gate_id"],"reason":"MISSING_TOOL"})
    elif tool.name not in tests_text: bad.append({"gate":g["gate_id"],"reason":"NO_PYTEST_REFERENCE","tool":tool.name})
if bad:
    print(json.dumps({"status":"FAIL","gaps":bad},indent=2)); sys.exit(2)
print(json.dumps({"status":"PASS","gates":len(reg.get("gates",[]))}))
