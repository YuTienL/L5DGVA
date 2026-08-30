#!/usr/bin/env python3
import argparse,json,pathlib,re
ap=argparse.ArgumentParser()
ap.add_argument('--dut-extract',required=True)
ap.add_argument('--out',required=True)
ap.add_argument('--design-spec')
ap.add_argument('--address-map')
ap.add_argument('--revision')
ap.add_argument('--evidence-revision')
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
model={
 "revision": a.revision or "UNKNOWN",
 "evidence_revision": a.evidence_revision or "UNKNOWN",
 "dut_name": dut.get("modules",[{"module":"UNKNOWN"}])[0].get("module","UNKNOWN") if dut.get("modules") else "UNKNOWN",
 "hierarchy":{"top":dut.get("modules",[{"module":"UNKNOWN"}])[0].get("module","UNKNOWN") if dut.get("modules") else "UNKNOWN","blocks":[],"subsystems":[]},
 "interfaces":ifs,
 "bus_topology":{"masters":[],"slaves":[],"interconnects":[],"address_map":[]},
 "clock_domains":[{"name":x,"source":"RTL_PORT","frequency":"UNKNOWN","consumers":[]} for x in clks],
 "reset_domains":[{"name":x,"polarity":"UNKNOWN","dependencies":[],"consumers":[]} for x in rsts],
 "power_domains":[],"interrupt_topology":[],"dma_paths":[],"data_paths":[],"control_paths":[],
 "register_blocks":[],"memory_regions":[],"feature_dependencies":[],
 "unknowns":["interface roles/boundaries require semantic evidence"] if ifs else ["protocol interfaces not inferred"],
 "evidence":[{"type":"RTL_EXTRACT","source":a.dut_extract}],
 "confidence":"LOW"
}
pathlib.Path(a.out).write_text(json.dumps(model,indent=2))
