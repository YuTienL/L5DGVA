#!/usr/bin/env python3
"""Inventory/classify command.txt files and emit a dry-run catalog plan.
No file moves or deletions are performed by this analyzer.
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, re

LEVELS = {
    "SYSTEM": "40_SYSTEM_LEVEL_SOC",
    "MULTI": "30_MULTI_SUBSYSTEM",
    "SUBSYSTEM": "20_SUBSYSTEM",
    "IP": "10_IP_BLOCK",
    "PLATFORM": "00_PLATFORM_INFRA",
}
CATEGORY_RULES = [
    ("09_ERROR_INJECTION_NEGATIVE", [r"error injection", r"negative", r"malformed", r"bad crc", r"invalid", r"illegal"]),
    ("10_RECOVERY_ROBUSTNESS", [r"recover", r"recovery", r"retry", r"robust"]),
    ("03_BRINGUP_LINK_TRAINING", [r"link train", r"training", r"ltssm", r"bring.?up", r"phy bring"]),
    ("04_ENUM_DISCOVERY_CONFIGURATION", [r"enumerat", r"discover", r"config space", r"configuration", r"descriptor"]),
    ("08_CONCURRENCY_STRESS", [r"concurr", r"parallel", r"stress", r"multi.?master", r"multi.?slave", r"soak"]),
    ("12_PERFORMANCE_QOS", [r"performance", r"bandwidth", r"latency", r"qos", r"throughput"]),
    ("15_COVERAGE_CLOSURE", [r"coverage", r"covergroup", r"closure"]),
    ("16_REGRESSION_SOAK", [r"regression", r"soak", r"random"]),
    ("01_BUILD_COMPILE", [r"compile", r"build", r"elaborat"]),
    ("02_RESET_INIT", [r"reset", r"initiali[sz]e", r"init\b"]),
    ("06_DATA_TRANSFER_TRAFFIC", [r"read", r"write", r"transfer", r"traffic", r"packet", r"frame", r"tlp"]),
    ("20_QUALIFICATION_SIGNOFF", [r"qualification", r"signoff", r"sign.?off"]),
]
PROTOCOLS = [
    ("PCIe", [r"pcie", r"pci-e"]), ("USB", [r"usb"]), ("Ethernet", [r"ethernet", r"xgmii", r"usxgmii", r"sgmii"]),
    ("MIPI_CSI2", [r"csi-?2", r"mipi.?csi"]), ("MIPI_DSI", [r"dsi", r"mipi.?dsi"]),
    ("AMBA4", [r"amba", r"axi", r"ahb", r"apb"]), ("eDP", [r"\bedp\b", r"displayport"]),
    ("eMMC", [r"emmc"]), ("SD_SDIO", [r"sdio", r"\bsd\b"]), ("UCIe", [r"ucie"]),
]

def detect_protocol(text: str) -> str:
    low=text.lower()
    for name,pats in PROTOCOLS:
        if any(re.search(p,low) for p in pats): return name
    return "Generic"

def detect_category(text: str) -> tuple[str,list[str]]:
    low=text.lower(); hits=[]
    for cat,pats in CATEGORY_RULES:
        if any(re.search(p,low) for p in pats): hits.append(cat)
    return (hits[0] if hits else "90_MISC_REVIEW", hits[1:])

def detect_level(text: str, path: str) -> str:
    low=(text+" "+path).lower()
    if any(x in low for x in ["full soc","full-soc","system level","system-level","os boot","end-to-end","end to end"]): return LEVELS["SYSTEM"]
    if any(x in low for x in ["multi subsystem","multi-subsystem","cross subsystem","cross-subsystem"]): return LEVELS["MULTI"]
    if any(x in low for x in ["subsystem","pcie","usb","ethernet","mipi","emmc","sdio","ucie","edp"]): return LEVELS["SUBSYSTEM"]
    if any(x in low for x in ["block","unit test","ip level","ip-level"]): return LEVELS["IP"]
    if any(x in low for x in ["harness","parser","remote control","lsf","ci/cd","infrastructure"]): return LEVELS["PLATFORM"]
    return "90_UNCLASSIFIED_REVIEW"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out",default=".dv-harness/command-catalog")
    ap.add_argument("--catalog-root",default="verification_commands")
    a=ap.parse_args()
    root=pathlib.Path(a.root).resolve(); out=(root/a.out); out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for p in sorted(root.rglob("command.txt")):
        if out in p.parents: continue
        txt=p.read_text(errors="ignore")
        rel=str(p.relative_to(root)).replace("\\","/")
        protocol=detect_protocol(txt+"\n"+rel)
        category,secondary=detect_category(txt)
        level=detect_level(txt,rel)
        h=hashlib.sha256(txt.replace("\r\n","\n").strip().encode()).hexdigest()
        scenario=re.sub(r"[^A-Za-z0-9_.-]+","_",p.parent.name or "command")
        dest=f"{a.catalog_root}/{level}/{category}/{protocol}/{scenario}/command.txt"
        confidence="LOW" if level.startswith("90_") or category.startswith("90_") else "MEDIUM"
        rows.append({"source":rel,"sha256":h,"level":level,"category":category,"secondary_tags":secondary,"protocol":protocol,"proposed_destination":dest,"confidence":confidence,"action":"REVIEW" if confidence=="LOW" else "MOVE"})
    hashes={}
    for r in rows: hashes.setdefault(r["sha256"],[]).append(r["source"])
    duplicates=[{"sha256":h,"paths":ps,"type":"DUPLICATE_EXACT"} for h,ps in hashes.items() if len(ps)>1]
    (out/"inventory.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False))
    (out/"classification.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False))
    (out/"move_plan.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False))
    (out/"duplicate_report.json").write_text(json.dumps(duplicates,indent=2,ensure_ascii=False))
    print(json.dumps({"commands_scanned":len(rows),"exact_duplicate_groups":len(duplicates),"review_required":sum(r["action"]=="REVIEW" for r in rows)},ensure_ascii=False))

if __name__=="__main__": main()
