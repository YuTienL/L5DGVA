#!/usr/bin/env python3
import argparse,json,pathlib,sys

REQ=["release_id","release_hash","promotion_chain_hash","evidence_bundle_hash","attested_by","attested_at"]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--attestation",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.attestation).read_text())
    missing=[k for k in REQ if not d.get(k)]
    if missing:
        print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_RELEASE_ATTESTATION","missing":missing})); return 2
    if not d.get("attestation_signature"):
        print(json.dumps({"status":"FAIL","reason":"UNSIGNED_RELEASE_ATTESTATION"})); return 3
    print(json.dumps({"status":"ATTESTED","release_id":d["release_id"]})); return 0
if __name__=="__main__":
    sys.exit(main())
