#!/usr/bin/env python3
import argparse, json, pathlib, sys

REQUIRED={
 "SYSTEM_LEVEL":["composition","traceability","release_pinning","change_impact","deadlock_livelock"],
 "REMOTE":["supervisory","state_transition","action_audit","replay"],
 "LSF":["per_job_monitor"],
 "COMMAND_LIFECYCLE":["catalog","migration","reference_scan"]
}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--coverage",required=True); a=ap.parse_args()
    d=json.loads(pathlib.Path(a.coverage).read_text())
    groups=d.get("groups",{})
    for grp,features in REQUIRED.items():
        if grp not in groups:
            print(json.dumps({"status":"FAIL","reason":"MISSING_CONTROL_PLANE_GROUP","group":grp})); return 2
        for feat in features:
            x=groups[grp].get(feat,{})
            if not x.get("positive_test"):
                print(json.dumps({"status":"FAIL","reason":"CONTROL_FEATURE_WITHOUT_POSITIVE_TEST","group":grp,"feature":feat})); return 3
            if not x.get("negative_test"):
                print(json.dumps({"status":"FAIL","reason":"CONTROL_FEATURE_WITHOUT_NEGATIVE_TEST","group":grp,"feature":feat})); return 4
    print(json.dumps({"status":"PASS"})); return 0

if __name__=="__main__":
    sys.exit(main())
