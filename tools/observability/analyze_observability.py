#!/usr/bin/env python3
import argparse,json,pathlib
ap=argparse.ArgumentParser()
ap.add_argument('--architecture',required=True)
ap.add_argument('--out',required=True)
ap.add_argument('--vplan')
ap.add_argument('--regression')
a=ap.parse_args()

arch=json.loads(pathlib.Path(a.architecture).read_text())
vplan=json.loads(pathlib.Path(a.vplan).read_text()) if a.vplan else {}
reg=json.loads(pathlib.Path(a.regression).read_text()) if a.regression else {}

targets=[]; idx=1
for it in arch.get("interfaces",[]):
    proto=it.get("protocol","OTHER"); role=it.get("role","UNKNOWN")
    mechs=[{
      "type":"CHECKER","placement":f"{proto} interface boundary",
      "purpose":f"Validate {proto} protocol/state/config semantics for role {role}",
      "inputs":it.get("ports",[]),"expected_model":"protocol semantic model / VIP analysis",
      "trigger_or_sampling":"transaction/state event","severity":"ERROR",
      "implementation_strategy":"transaction-level semantic checker",
      "traceability":{"vplan_requirement_ids":[],"feature_ids":[],"coverage_ids":[]}
    }]
    if proto in ["PCIe","USB","Ethernet","MIPI","eDP","eMMC","SDIO","UCIe","AMBA"]:
        mechs.append({
          "type":"ASSERTION","placement":f"{proto} local signal boundary",
          "purpose":"Validate local handshake/state/reset timing invariants",
          "inputs":it.get("ports",[]),"expected_model":"current spec + RTL evidence",
          "trigger_or_sampling":"clocked/local temporal sampling","severity":"ERROR",
          "implementation_strategy":"SVA property set",
          "traceability":{"vplan_requirement_ids":[],"feature_ids":[],"coverage_ids":[]}
        })
    targets.append({"target_id":f"OBS-{idx:03d}","architecture_nodes":[it.get("name",proto)],
                    "feature_ids":[],"requirement_ids":[],"risk":"HIGH" if role=="UNKNOWN" else "MEDIUM",
                    "failure_modes":["protocol/state/config mismatch"],"recommended_mechanisms":mechs,"status":"PLANNED"})
    idx+=1

for key in ["data_paths","dma_paths"]:
    for p in arch.get(key,[]):
        name=p.get("name") if isinstance(p,dict) else str(p)
        targets.append({"target_id":f"OBS-{idx:03d}","architecture_nodes":[name],"feature_ids":[],"requirement_ids":[],
                        "risk":"HIGH","failure_modes":["data corruption","routing mismatch","ordering mismatch"],
                        "recommended_mechanisms":[{
                          "type":"SCOREBOARD","placement":f"{key} end-to-end boundary",
                          "purpose":"Track source transactions/data and compare with destination observations",
                          "inputs":[name],"expected_model":"reference transaction/data model",
                          "trigger_or_sampling":"source enqueue / destination observe","severity":"ERROR",
                          "implementation_strategy":"UVM analysis ports + reference queue/model + compare",
                          "traceability":{"vplan_requirement_ids":[],"feature_ids":[],"coverage_ids":[]}
                        }],"status":"PLANNED"})
        idx+=1

bt=arch.get("bus_topology",{})
if bt.get("masters") or bt.get("slaves"):
    targets.append({"target_id":f"OBS-{idx:03d}","architecture_nodes":["bus_topology"],"feature_ids":[],"requirement_ids":[],
                    "risk":"HIGH","failure_modes":["wrong route","response mismatch","ordering violation"],
                    "recommended_mechanisms":[
                      {"type":"SCOREBOARD","placement":"interconnect transaction boundary",
                       "purpose":"Match master requests to slave transactions/responses",
                       "inputs":["master monitor","slave monitor"],"expected_model":"address decode + ordering/outstanding model",
                       "trigger_or_sampling":"transaction events","severity":"ERROR",
                       "implementation_strategy":"multi-port UVM scoreboard",
                       "traceability":{"vplan_requirement_ids":[],"feature_ids":[],"coverage_ids":[]}},
                      {"type":"CHECKER","placement":"address/response semantic boundary",
                       "purpose":"Validate decode, response and configuration semantics",
                       "inputs":["address","ID","response"],"expected_model":"address map / semantic model",
                       "trigger_or_sampling":"transaction completion","severity":"ERROR",
                       "implementation_strategy":"semantic transaction checker",
                       "traceability":{"vplan_requirement_ids":[],"feature_ids":[],"coverage_ids":[]}}
                    ],"status":"PLANNED"})

out={"scope":vplan.get("scope","UNKNOWN"),"analysis_revision":"1.0","targets":targets,
     "regression_evidence_used":bool(reg),"unknowns":arch.get("unknowns",[])}
pathlib.Path(a.out).write_text(json.dumps(out,indent=2))
