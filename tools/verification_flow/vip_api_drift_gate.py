#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--vip",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.vip).read_text())

    if d.get("current_vip_version") != d.get("qualified_vip_version"):
        if not d.get("api_diff_analyzed"):
            print(json.dumps({"status":"FAIL","reason":"VIP_VERSION_DRIFT_WITHOUT_API_DIFF"})); return 2
        if d.get("breaking_api_changes") and not d.get("adapter_updated"):
            print(json.dumps({"status":"FAIL","reason":"BREAKING_VIP_CHANGE_WITHOUT_ADAPTER_UPDATE"})); return 3
        if not d.get("requalification_evidence"):
            print(json.dumps({"status":"FAIL","reason":"VIP_DRIFT_WITHOUT_REQUALIFICATION"})); return 4

    if not d.get("current_vip_source_or_manual_hash"):
        print(json.dumps({"status":"FAIL","reason":"UNPINNED_CURRENT_VIP_REFERENCE"})); return 5

    print(json.dumps({"status":"PASS","current_vip_version":d.get("current_vip_version")})); return 0
if __name__=="__main__":
    sys.exit(main())
