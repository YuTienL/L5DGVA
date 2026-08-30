#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--binding", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.binding).read_text())

    for p in d.get("protocols",[]):
        name=p.get("protocol")
        required=["profile_version","profile_hash","spec_revision","generator_version","generator_hash","qualification_evidence_hash"]
        missing=[x for x in required if not p.get(x)]
        if missing:
            print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_PROTOCOL_GENERATOR_BINDING",
                              "protocol":name,"missing":missing})); return 2
        if p.get("qualified_generator_version") and p.get("qualified_generator_version") != p.get("generator_version"):
            if not p.get("requalification_evidence_hash"):
                print(json.dumps({"status":"FAIL","reason":"GENERATOR_VERSION_DRIFT_WITHOUT_REQUALIFICATION",
                                  "protocol":name})); return 3

    print(json.dumps({"status":"PASS","protocols":len(d.get("protocols",[]))}))
    return 0

if __name__=="__main__":
    sys.exit(main())
