#!/usr/bin/env python3
import argparse,json,pathlib,sys
ALIASES={
 "execution_mode":"execution_mode_validator",
 "system_level_identity":"system_level_validator",
 "experience_runtime_applicability":"experience_applicability_gate",
}
ap=argparse.ArgumentParser(); ap.add_argument("--root",required=True); a=ap.parse_args(); root=pathlib.Path(a.root)
m=json.loads((root/"WORKFLOW_MANIFEST.json").read_text()); f=json.loads((root/".dv-harness/workflow/verification_flow_v13.json").read_text()); r=json.loads((root/".dv-harness/workflow/hard_gate_registry.json").read_text())
flow_tools={k:v for k,v in f.items() if isinstance(v,str) and v.startswith("tools/") and v.endswith(".py")}
reg={x["gate_id"]:x["tool"] for x in r.get("gates",[])}
all_py={p.stem:str(p.relative_to(root)) for p in (root/"tools").rglob("*.py")}
issues=[]
def canonical_forms(base):
 forms={base,base+"_gate"}
 if base.endswith("_gate"): forms.add(base[:-5])
 alias=ALIASES.get(base)
 if alias: forms|={alias, alias[:-5] if alias.endswith("_gate") else alias}
 return forms
flow_keys=set(flow_tools); reg_keys=set(reg)
tool_stems={pathlib.Path(v).stem for v in list(flow_tools.values())+list(reg.values())}
for k,v in m.items():
 if k.endswith("_hard_gate") and v is True:
  base=k[:-10]; forms=canonical_forms(base)
  if not (forms&flow_keys or forms&reg_keys or forms&tool_stems or forms&set(all_py)):
   issues.append({"type":"MANIFEST_GATE_NOT_RESOLVABLE","manifest_key":k,"forms":sorted(forms)})
for gid,tool in reg.items():
 if not (root/tool).exists(): issues.append({"type":"MISSING_TOOL","gate":gid,"tool":tool})
 if f.get(gid)!=tool and tool not in flow_tools.values(): issues.append({"type":"REGISTRY_NOT_IN_FLOW","gate":gid,"tool":tool})
if issues: print(json.dumps({"status":"FAIL","issues":issues},indent=2)); sys.exit(2)
print(json.dumps({"status":"PASS","registry_gates":len(reg),"legacy_aliases":ALIASES}))
