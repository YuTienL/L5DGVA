#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--state",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.state).read_text())
if not d.get("rtl_source_available"):
    print(json.dumps({"status":"FAIL","reason":"RTL_SOURCE_REQUIRED_FOR_STEP5"})); sys.exit(2)
if d.get("architecture_document_required"):
    print(json.dumps({"status":"FAIL","reason":"ARCHITECTURE_DOCUMENT_MUST_BE_OPTIONAL"})); sys.exit(3)
auto=set(d.get("auto_discovered_fields",[]))
minimum={"TOP","HIERARCHY","INTERFACE","CLOCK_RESET","PARAM_DEFINE","PORT_CHANNEL"}
if not minimum.issubset(auto):
    print(json.dumps({"status":"FAIL","reason":"RTL_DISCOVERY_TOO_SHALLOW","missing":sorted(minimum-auto)})); sys.exit(4)
if d.get("asked_user_before_rtl_analysis"):
    print(json.dumps({"status":"FAIL","reason":"USER_ASKED_BEFORE_RTL_EVIDENCE_SEARCH"})); sys.exit(5)
for item in d.get("unknown_items",[]):
    if item.get("confidence") in ("LOW","UNKNOWN") and not item.get("next_action"):
        print(json.dumps({"status":"FAIL","reason":"UNKNOWN_ARCHITECTURE_WITHOUT_CALIBRATION_ACTION","item":item.get("name")})); sys.exit(6)
if not d.get("architecture_evidence_db_generated"):
    print(json.dumps({"status":"FAIL","reason":"NO_ARCHITECTURE_EVIDENCE_DATABASE"})); sys.exit(7)
if d.get("lock_requested") and not d.get("calibration_complete"):
    print(json.dumps({"status":"FAIL","reason":"ARCHITECTURE_LOCK_BEFORE_CALIBRATION"})); sys.exit(8)
print(json.dumps({"status":"PASS"}))
