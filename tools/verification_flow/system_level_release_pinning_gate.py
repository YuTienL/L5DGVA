#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--composition", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.composition).read_text())
    subs=d.get("selected_subsystems",[])
    if len(subs)<2:
        print(json.dumps({"status":"FAIL","reason":"INSUFFICIENT_SUBSYSTEMS"})); return 2
    for s in subs:
        for k in ("name","release_sha","environment_manifest_hash","qualification_evidence_hash"):
            if not s.get(k):
                print(json.dumps({"status":"FAIL","reason":"UNPINNED_SUBSYSTEM_RELEASE","subsystem":s.get("name"),"missing":k})); return 3
    if not d.get("composition_hash"):
        print(json.dumps({"status":"FAIL","reason":"NO_COMPOSITION_HASH"})); return 4
    print(json.dumps({"status":"PASS","subsystems":len(subs)}))
    return 0

if __name__=="__main__":
    sys.exit(main())
