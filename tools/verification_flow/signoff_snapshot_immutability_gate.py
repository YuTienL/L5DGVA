#!/usr/bin/env python3
import argparse, json, pathlib, sys, hashlib

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.snapshot).read_text())

    required=["release_hash","promotion_chain_hash","evidence_bundle_hash","manifest_hash","attestation_signature","snapshot_hash"]
    missing=[x for x in required if not d.get(x)]
    if missing:
        print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_SIGNOFF_SNAPSHOT","missing":missing})); return 2

    material={
        "release_hash":d["release_hash"],
        "promotion_chain_hash":d["promotion_chain_hash"],
        "evidence_bundle_hash":d["evidence_bundle_hash"],
        "manifest_hash":d["manifest_hash"],
        "attestation_signature":d["attestation_signature"],
    }
    calc=hashlib.sha256(json.dumps(material,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    if calc != d["snapshot_hash"]:
        print(json.dumps({"status":"FAIL","reason":"SIGNOFF_SNAPSHOT_HASH_MISMATCH",
                          "expected":d["snapshot_hash"],"calculated":calc})); return 3
    if d.get("post_signoff_mutation_detected"):
        print(json.dumps({"status":"FAIL","reason":"POST_SIGNOFF_MUTATION_DETECTED"})); return 4

    print(json.dumps({"status":"PASS","snapshot_hash":calc}))
    return 0

if __name__=="__main__":
    sys.exit(main())
