#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--root",required=True); ap.add_argument("--required",required=True); a=ap.parse_args()
root=pathlib.Path(a.root)
d=json.loads(pathlib.Path(a.required).read_text())
missing=[]
for rel in d.get("required_paths",[]):
    if not (root/rel).exists():
        missing.append(rel)
if missing:
    print(json.dumps({"status":"FAIL","reason":"FEATURE_CONTINUITY_REGRESSION","missing":missing})); sys.exit(2)
print(json.dumps({"status":"PASS","required_paths":len(d.get("required_paths",[]))}))
