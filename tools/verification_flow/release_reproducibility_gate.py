#!/usr/bin/env python3
import argparse, json, pathlib, sys

REQ=["rtl_revision","tb_revision","vip_version","tool_versions","config_hash","testlist_hash","seed_policy","evidence_bundle_hash"]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--release", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.release).read_text())
    missing=[x for x in REQ if not d.get(x)]
    if missing:
        print(json.dumps({"status":"FAIL","reason":"NON_REPRODUCIBLE_RELEASE","missing":missing})); return 2
    if d.get("qualification_state")=="PRODUCTION_QUALIFIED" and not d.get("promotion_chain_hash"):
        print(json.dumps({"status":"FAIL","reason":"PRODUCTION_RELEASE_WITHOUT_PROMOTION_CHAIN_HASH"})); return 3
    print(json.dumps({"status":"REPRODUCIBLE","release_id":d.get("release_id")}))
    return 0

if __name__=="__main__":
    sys.exit(main())
