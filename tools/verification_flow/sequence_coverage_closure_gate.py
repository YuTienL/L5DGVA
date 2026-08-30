#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--coverage",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.coverage).read_text())
req=set(d.get("required_sequences",[])); hit=set(d.get("hit_sequences",[]))
waived={x.get("sequence") for x in d.get("waivers",[]) if x.get("approved") and x.get("evidence")}
missing=sorted(req-hit-waived)
print(json.dumps({"status":"FAIL","reason":"SEQUENCE_COVERAGE_GAP","missing":missing}) if missing else json.dumps({"status":"PASS"}))
sys.exit(2 if missing else 0)
