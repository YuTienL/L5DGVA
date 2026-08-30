#!/usr/bin/env python3
import argparse,json,pathlib,sys

QUALIFIED={"SMOKE_QUALIFIED","REGRESSION_QUALIFIED","PRODUCTION_QUALIFIED"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--status",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.status).read_text())

    for p in d.get("protocols",[]):
        name=p.get("name")
        state=p.get("qualification_state")
        if state in QUALIFIED:
            required=["profile_version","spec_revision","environment_manifest_hash","qualification_evidence_hash"]
            missing=[x for x in required if not p.get(x)]
            if missing:
                print(json.dumps({"status":"FAIL","reason":"QUALIFIED_PROTOCOL_WITHOUT_EVIDENCE",
                                  "protocol":name,"missing":missing})); return 2
        if p.get("generation_supported") and not p.get("profile_available"):
            print(json.dumps({"status":"FAIL","reason":"GENERATION_SUPPORT_WITHOUT_PROFILE","protocol":name})); return 3

    print(json.dumps({"status":"PASS","protocols":len(d.get("protocols",[]))})); return 0
if __name__=="__main__":
    sys.exit(main())
