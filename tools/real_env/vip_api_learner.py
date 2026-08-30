#!/usr/bin/env python3
import argparse, pathlib, re, json
ap=argparse.ArgumentParser()
ap.add_argument('--roots', nargs='+', required=True)
ap.add_argument('--out', required=True)
a=ap.parse_args()
classes=[]; packages=[]; examples=[]; configs=[]
for root in a.roots:
    rp=pathlib.Path(root)
    if not rp.exists(): continue
    for p in rp.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in ['.sv','.svh','.v','.vh','.txt','.md','.html']: continue
        try: txt=p.read_text(errors='ignore')
        except: continue
        for m in re.finditer(r'\bpackage\s+([A-Za-z_][A-Za-z0-9_$]*)',txt):
            packages.append({"file":str(p),"package":m.group(1)})
        for m in re.finditer(r'\bclass\s+([A-Za-z_][A-Za-z0-9_$]*)',txt):
            classes.append({"file":str(p),"class":m.group(1)})
        if 'example' in p.name.lower() or 'test' in p.name.lower():
            examples.append(str(p))
        for key in ['lane','speed','role','active','passive','coverage','checker','trace']:
            if key in txt.lower():
                configs.append({"file":str(p),"keyword":key})
out={"packages":packages,"classes":classes,"examples":examples[:200],"config_keywords":configs[:500],
     "note":"Candidate API inventory only. Actual bindings must be confirmed against current VIP docs/examples/source/class reference."}
pathlib.Path(a.out).write_text(json.dumps(out,indent=2))
print(a.out)
