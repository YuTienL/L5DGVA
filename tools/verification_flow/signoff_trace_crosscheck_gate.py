#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--signoff",required=True); a=ap.parse_args()
    d=json.loads(pathlib.Path(a.signoff).read_text())
    required=["snapshot_hash","trace_chain_hash","coverage_state_hash","result_bundle_hash","rca_bundle_hash","evidence_bundle_hash"]
    miss=[x for x in required if not d.get(x)]
    if miss:
        print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_SIGNOFF_CROSSCHECK","missing":miss})); return 2
    refs=d.get("snapshot_references",{})
    expected={
      "trace_chain_hash":d["trace_chain_hash"],
      "coverage_state_hash":d["coverage_state_hash"],
      "result_bundle_hash":d["result_bundle_hash"],
      "rca_bundle_hash":d["rca_bundle_hash"],
      "evidence_bundle_hash":d["evidence_bundle_hash"],
    }
    for k,v in expected.items():
        if refs.get(k)!=v:
            print(json.dumps({"status":"FAIL","reason":"SIGNOFF_REFERENCE_MISMATCH","field":k,
                              "expected":v,"actual":refs.get(k)})); return 3
    if d.get("active_failure_count",0)>0:
        print(json.dumps({"status":"FAIL","reason":"SIGNOFF_WITH_ACTIVE_FAILURES"})); return 4
    print(json.dumps({"status":"PASS","snapshot_hash":d["snapshot_hash"]})); return 0

if __name__=="__main__":
    sys.exit(main())
