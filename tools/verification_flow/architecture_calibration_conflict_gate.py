#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--calibration",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.calibration).read_text())
for c in d.get("conflicts",[]):
    if not c.get("resolved") and len(c.get("sources",[]))>=2:
        print(json.dumps({"status":"FAIL","reason":"UNRESOLVED_ARCHITECTURE_CONFLICT",
                          "feature":c.get("feature"),"sources":c.get("sources")})); sys.exit(2)
if d.get("architecture_locked") and d.get("unresolved_unknown_count",0)>0:
    print(json.dumps({"status":"FAIL","reason":"ARCHITECTURE_LOCK_WITH_UNRESOLVED_UNKNOWN"})); sys.exit(3)
print(json.dumps({"status":"PASS"}))
