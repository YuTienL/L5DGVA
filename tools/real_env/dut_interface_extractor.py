#!/usr/bin/env python3
import argparse, pathlib, re, json
ap=argparse.ArgumentParser()
ap.add_argument('--rtl', nargs='+', required=True)
ap.add_argument('--out', required=True)
a=ap.parse_args()
mods=[]
ports=[]
params=[]
for fn in a.rtl:
    p=pathlib.Path(fn)
    txt=p.read_text(errors='ignore')
    for m in re.finditer(r'\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)',txt):
        mods.append({"file":str(p),"module":m.group(1)})
    for m in re.finditer(r'\b(parameter|localparam)\s+(?:\w+\s+)?([A-Za-z_][A-Za-z0-9_$]*)\s*=\s*([^,;\n\)]+)',txt):
        params.append({"file":str(p),"name":m.group(2),"value":m.group(3).strip()})
    for m in re.finditer(r'\b(input|output|inout)\b\s*(?:wire|logic|reg)?\s*(\[[^\]]+\])?\s*([A-Za-z_][A-Za-z0-9_$]*)',txt):
        ports.append({"file":str(p),"dir":m.group(1),"width":m.group(2) or "1","name":m.group(3)})
out={"modules":mods,"ports":ports,"parameters":params,"note":"Regex extractor; final interface semantics require Evidence Synthesis."}
pathlib.Path(a.out).write_text(json.dumps(out,indent=2))
print(a.out)
