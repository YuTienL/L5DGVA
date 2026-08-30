#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    a=ap.parse_args()
    root=pathlib.Path(a.root)

    schema_dir=root/".dv-harness/workflow"
    schemas=list(schema_dir.glob("*.schema.json"))
    refs="\n".join([
        (root/".dv-harness/workflow/verification_flow_v13.json").read_text(encoding="utf-8",errors="ignore"),
        (root/"WORKFLOW_MANIFEST.json").read_text(encoding="utf-8",errors="ignore"),
    ])
    # Also accept schemas explicitly catalogued by schema_catalog.json
    catalog_path=schema_dir/"schema_catalog.json"
    catalog=set()
    if catalog_path.exists():
        d=json.loads(catalog_path.read_text())
        catalog=set(d.get("schemas",[]))

    orphan=[]
    for s in schemas:
        stem=s.name.replace(".schema.json","")
        if stem not in refs and s.name not in catalog:
            orphan.append(s.name)

    if orphan:
        print(json.dumps({"status":"FAIL","reason":"ORPHAN_SCHEMAS","schemas":sorted(orphan)})); return 2

    print(json.dumps({"status":"PASS","schemas":len(schemas)}))
    return 0

if __name__=="__main__":
    sys.exit(main())
