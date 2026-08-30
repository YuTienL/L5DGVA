#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--coverage", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.coverage).read_text())

    for g in d.get("gates",[]):
        gid=g.get("gate_id")
        if not g.get("positive_test_ids"):
            print(json.dumps({"status":"FAIL","reason":"NO_POSITIVE_GATE_TEST","gate_id":gid})); return 2
        if not g.get("negative_test_ids"):
            print(json.dumps({"status":"FAIL","reason":"NO_NEGATIVE_GATE_TEST","gate_id":gid})); return 3
        if not g.get("positive_evidence_hash"):
            print(json.dumps({"status":"FAIL","reason":"NO_POSITIVE_TEST_EVIDENCE_HASH","gate_id":gid})); return 4
        if not g.get("negative_evidence_hash"):
            print(json.dumps({"status":"FAIL","reason":"NO_NEGATIVE_TEST_EVIDENCE_HASH","gate_id":gid})); return 5
        if not g.get("last_validated_revision"):
            print(json.dumps({"status":"FAIL","reason":"NO_GATE_VALIDATION_REVISION","gate_id":gid})); return 6

    print(json.dumps({"status":"PASS","gates":len(d.get("gates",[]))}))
    return 0

if __name__=="__main__":
    sys.exit(main())
