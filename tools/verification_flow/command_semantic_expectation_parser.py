#!/usr/bin/env python3
import argparse, json, pathlib, re, sys

PROTOCOLS=["pcie","usb","ethernet","mipi","csi","dsi","amba","axi","apb","edp","emmc","sdio","sd","ucie"]
OPS=["read","write","bulk","iso","interrupt","reset","recovery","enumeration","link","ltssm",
     "timeout","error","dma","traffic","training"]

def parse_kv(raw):
    # Non-space key=value token parser. Avoids greedy cross-token matching.
    return {m.group(1):m.group(2) for m in re.finditer(r'(?<!\S)([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)', raw)}

def parse_line(line, line_no):
    raw=line.strip()
    if not raw or raw.startswith("#"):
        return None
    lower=raw.lower()
    kv=parse_kv(raw)

    protocol="UNKNOWN"
    for p in PROTOCOLS:
        if re.search(r'(?<![a-z0-9_])'+re.escape(p)+r'(?:_|(?![a-z0-9_]))', lower):
            protocol=p.upper()
            break

    operation="COMMAND"
    for op in OPS:
        if re.search(r'(?<![a-z0-9_])'+re.escape(op)+r'(?![a-z0-9_])', lower):
            operation=op.upper()
            break

    testcase_id=kv.get("testcase_id") or kv.get("tc") or kv.get("test")
    vplan_raw=kv.get("vplan") or kv.get("vplan_id") or ""
    vplan_ids=[x for x in re.split(r'[,;]',vplan_raw) if x]

    expected=[]
    forbidden=[]

    if protocol!="UNKNOWN":
        expected.append({"pattern":protocol,"match_mode":"TOKEN","evidence_type":"PROTOCOL"})
    if operation!="COMMAND":
        expected.append({"pattern":operation,"match_mode":"TOKEN","evidence_type":"OPERATION"})

    for key in ("port","addr","address","data","ep","endpoint","channel","state","expect","result"):
        if key in kv:
            expected.append({"pattern":f"{key}={kv[key]}","match_mode":"TOKEN","evidence_type":"ATTRIBUTE"})

    success_requested=any(x in lower for x in ("expect=success","expect=pass","result=success","result=pass"))
    if success_requested:
        expected.append({"pattern":"success","match_mode":"TOKEN","evidence_type":"OUTCOME"})
        for x in ("failed","timeout"):
            forbidden.append({"pattern":x,"match_mode":"TOKEN","evidence_type":"CONTRADICTION"})

    if "reset" in lower and "recovery" in lower:
        for x in ("reset","recovery"):
            expected.append({"pattern":x,"match_mode":"TOKEN","evidence_type":"STATE"})
        forbidden.append({"pattern":"recovery failed","match_mode":"SUBSTRING","evidence_type":"CONTRADICTION"})

    if "error" in lower:
        expected.append({"pattern":"error","match_mode":"TOKEN","evidence_type":"ERROR"})
        if "recovery" in lower:
            expected.append({"pattern":"recovery","match_mode":"TOKEN","evidence_type":"RECOVERY"})

    # Deduplicate by pattern/mode.
    def dedupe(xs):
        seen=set(); out=[]
        for x in xs:
            k=(x["pattern"].lower(),x["match_mode"])
            if k not in seen:
                seen.add(k); out.append(x)
        return out

    return {
        "expectation_id":f"CMD{line_no:04d}",
        "source_file":"command.txt",
        "source_line":line_no,
        "raw_command":raw,
        "testcase_id":testcase_id,
        "vplan_ids":vplan_ids,
        "protocol":protocol,
        "operation":operation,
        "required":True,
        "evidence_requirements":dedupe(expected),
        "contradiction_requirements":dedupe(forbidden),
        "evidence_patterns":[x["pattern"] for x in dedupe(expected)],
        "contradiction_patterns":[x["pattern"] for x in dedupe(forbidden)],
        "key_values":kv
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--command-file",required=True)
    ap.add_argument("--output")
    a=ap.parse_args()

    p=pathlib.Path(a.command_file)
    lines=p.read_text(encoding="utf-8",errors="ignore").splitlines()
    exps=[x for x in (parse_line(line,i) for i,line in enumerate(lines,1)) if x]
    result={"command_file":str(p),"expectations":exps}
    txt=json.dumps(result,ensure_ascii=False,indent=2)
    if a.output:
        pathlib.Path(a.output).write_text(txt,encoding="utf-8")
    print(txt)
    return 0 if exps else 2

if __name__=="__main__":
    sys.exit(main())
