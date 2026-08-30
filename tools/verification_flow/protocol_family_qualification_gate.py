#!/usr/bin/env python3
import argparse,json,pathlib,sys
REQ={"PCIe","Ethernet","MIPI_CSI2","MIPI_DSI","AMBA4","eDP","eMMC","SD_SDIO","UCIe","USB"}
ap=argparse.ArgumentParser(); ap.add_argument("--matrix",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.matrix).read_text()); f={x.get("family"):x for x in d.get("protocol_families",[]) if x.get("family")}
miss=sorted(REQ-set(f))
if miss: print(json.dumps({"status":"FAIL","reason":"MISSING_PROTOCOL_FAMILIES","missing":miss})); sys.exit(2)
for n in REQ:
 p=f[n]; m=[k for k in ("profile_available","spec_revision","generator_path","qualification_state","qualification_evidence_hash") if not p.get(k)]
 if m: print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_PROTOCOL_FAMILY_QUALIFICATION","family":n,"missing":m})); sys.exit(3)
if not d.get("new_interface_onboarding_supported"): print(json.dumps({"status":"FAIL","reason":"NO_NEW_INTERFACE_ONBOARDING_PATH"})); sys.exit(4)
print(json.dumps({"status":"PASS"}))
