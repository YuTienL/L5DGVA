#!/usr/bin/env python3
# `power_domains` was hardcoded to [] here from the day this script was
# written, because nothing in this repo could produce a power domain --
# there was no UPF/power-intent reader anywhere (re-verified by grep,
# 2026-09-06). dv_harness/power_intent.py is now that reader, so --upf
# populates the field from REAL parsed power intent. Without --upf the
# field stays [] and `unknowns` says why, rather than being silently empty:
# section 224's "if low-power evidence is absent: UNSUPPORTED / UNKNOWN".
import argparse,json,pathlib,re,sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from dv_harness.power_intent import extract_power_intent, power_domains_for_architecture_model
ap=argparse.ArgumentParser()
ap.add_argument('--dut-extract',required=True)
ap.add_argument('--out',required=True)
ap.add_argument('--design-spec')
ap.add_argument('--address-map')
ap.add_argument('--revision')
ap.add_argument('--evidence-revision')
ap.add_argument('--upf',action='append',dest='upf_paths',
                help='UPF/power-intent file (repeatable, parsed in order) whose power '
                     'domains populate power_domains. Omit when the project has no '
                     'power intent -- the field then stays empty and is listed in unknowns.')
a=ap.parse_args()
dut=json.loads(pathlib.Path(a.dut_extract).read_text())
ports=dut.get("ports",[])
clks=[p["name"] for p in ports if "clk" in p.get("name","").lower()]
rsts=[p["name"] for p in ports if "rst" in p.get("name","").lower() or "reset" in p.get("name","").lower()]
names=" ".join(p.get("name","") for p in ports).lower()
ifs=[]
for proto,keys in [
 ("PCIe",["pcie","pipe"]),("USB",["usb","utmi"]),("Ethernet",["eth","xgmii","gmii"]),
 ("MIPI",["mipi","csi","dsi"]),("AMBA",["axi","ahb","apb"]),("eMMC",["emmc"]),
 ("SDIO",["sdio","sd_"]),("UCIe",["ucie"]),("eDP",["edp","aux"])
]:
    if any(k in names for k in keys):
        ifs.append({"protocol":proto,"role":"UNKNOWN","boundary":"DISCOVER","ports":[p["name"] for p in ports if any(k in p.get("name","").lower() for k in keys)]})
evidence=[{"type":"RTL_EXTRACT","source":a.dut_extract}]
unknowns=["interface roles/boundaries require semantic evidence"] if ifs else ["protocol interfaces not inferred"]
power_domains=[]
if a.upf_paths:
    _intent=extract_power_intent(a.upf_paths)
    power_domains=power_domains_for_architecture_model(_intent)
    for _f in a.upf_paths:
        evidence.append({"type":"UPF_POWER_INTENT","source":str(_f)})
    if not power_domains:
        unknowns.append("UPF supplied but declared no power domains: power intent UNKNOWN")
else:
    unknowns.append("no power intent supplied (--upf): power_domains UNSUPPORTED/UNKNOWN")
model={
 "revision": a.revision or "UNKNOWN",
 "evidence_revision": a.evidence_revision or "UNKNOWN",
 "dut_name": dut.get("modules",[{"module":"UNKNOWN"}])[0].get("module","UNKNOWN") if dut.get("modules") else "UNKNOWN",
 "hierarchy":{"top":dut.get("modules",[{"module":"UNKNOWN"}])[0].get("module","UNKNOWN") if dut.get("modules") else "UNKNOWN","blocks":[],"subsystems":[]},
 "interfaces":ifs,
 "bus_topology":{"masters":[],"slaves":[],"interconnects":[],"address_map":[]},
 "clock_domains":[{"name":x,"source":"RTL_PORT","frequency":"UNKNOWN","consumers":[]} for x in clks],
 "reset_domains":[{"name":x,"polarity":"UNKNOWN","dependencies":[],"consumers":[]} for x in rsts],
 "power_domains":power_domains,"interrupt_topology":[],"dma_paths":[],"data_paths":[],"control_paths":[],
 "register_blocks":[],"memory_regions":[],"feature_dependencies":[],
 "unknowns":unknowns,
 "evidence":evidence,
 "confidence":"LOW"
}
pathlib.Path(a.out).write_text(json.dumps(model,indent=2))
