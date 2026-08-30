#!/usr/bin/env python3
import argparse,json,pathlib
ap=argparse.ArgumentParser()
ap.add_argument('--model',required=True)
ap.add_argument('--evidence',required=True)
ap.add_argument('--out',required=True)
a=ap.parse_args()
m=json.loads(pathlib.Path(a.model).read_text())
e=json.loads(pathlib.Path(a.evidence).read_text())
changes=e.get("architecture_corrections",[])
history=m.setdefault("calibration_history",[])
unhandled=[]
for c in changes:
    history.append(c)
    path=c.get("path")
    val=c.get("value")
    proto=c.get("protocol")
    def _interfaces_matching(proto):
        return [it for it in m.get("interfaces",[]) if it.get("protocol")==proto]
    if path=="interface_role":
        for it in _interfaces_matching(proto): it["role"]=val
    elif path=="interface_boundary":
        for it in _interfaces_matching(proto): it["boundary"]=val
    elif path=="clock_reset_dependency":
        # calibration_triggers: "clock/reset dependency mismatch"
        domain=c.get("domain"); target=m.setdefault("clock_domains",[]) if c.get("kind")=="clock" else m.setdefault("reset_domains",[])
        match=next((d for d in target if d.get("name")==domain), None)
        if match is None:
            match={"name":domain}; target.append(match)
        match.update(val if isinstance(val,dict) else {"value":val})
    elif path=="address_map":
        # calibration_triggers: "address-map mismatch"
        entry=val if isinstance(val,dict) else {"value":val}
        m.setdefault("bus_topology",{}).setdefault("address_map",[]).append(entry)
    elif path=="interrupt_dma_routing":
        # calibration_triggers: "interrupt/DMA routing mismatch"
        target = m.setdefault("interrupt_topology",[]) if c.get("kind")=="interrupt" else m.setdefault("dma_paths",[])
        target.append(val if isinstance(val,dict) else {"value":val})
    elif path=="protocol_state_transition":
        # calibration_triggers: "unexpected protocol state transition"
        for it in _interfaces_matching(proto):
            it.setdefault("unexpected_state_transitions",[]).append(val)
    elif path=="scoreboard_model_error":
        # calibration_triggers: "scoreboard mismatch caused by model error"
        for it in _interfaces_matching(proto):
            it.setdefault("scoreboard_model_corrections",[]).append(val)
    elif path=="feature_dependency":
        # calibration_triggers: "coverage hole revealing missing feature dependency"
        m.setdefault("feature_dependencies",[]).append(val if isinstance(val,dict) else {"value":val})
    elif path=="waveform_contradiction":
        # calibration_triggers: "waveform contradicts architecture model"
        for it in _interfaces_matching(proto):
            it.setdefault("waveform_contradictions",[]).append(val)
    elif path in ("dut_role","topology"):
        # calibration_triggers: "wrong DUT role/topology assumption"
        m["hierarchy"] = {**m.get("hierarchy",{}), **(val if isinstance(val,dict) else {"top":val})}
    elif path in ("port_interface_behavior",):
        # calibration_triggers: "unexpected port/interface behavior"
        for it in _interfaces_matching(proto):
            it.setdefault("unexpected_behavior",[]).append(val)
    else:
        # Unknown correction path: recorded in calibration_history above but
        # never silently dropped -- flagged so the caller knows this
        # correction needs a schema update or manual model edit.
        unhandled.append({"path":path,"protocol":proto})
m.setdefault("evidence",[]).append({"type":"REGRESSION_CALIBRATION","source":a.evidence})
if unhandled:
    m["unresolved_calibration_corrections"]=unhandled
m["confidence"]="MEDIUM" if changes else m.get("confidence","LOW")
pathlib.Path(a.out).write_text(json.dumps(m,indent=2))
