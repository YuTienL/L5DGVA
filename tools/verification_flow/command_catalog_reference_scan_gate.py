#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--scan",required=True); a=ap.parse_args(); d=json.loads(pathlib.Path(a.scan).read_text())
for x in d.get("obsolete_directories",[]):
 if x.get("references"): print(json.dumps({"status":"FAIL","reason":"OBSOLETE_DIR_STILL_REFERENCED","path":x.get("path"),"references":x.get("references")})); sys.exit(2)
 if not x.get("all_commands_migrated"): print(json.dumps({"status":"FAIL","reason":"OBSOLETE_DIR_COMMANDS_NOT_FULLY_MIGRATED","path":x.get("path")})); sys.exit(3)
 if not x.get("hash_integrity_verified"): print(json.dumps({"status":"FAIL","reason":"MIGRATION_HASH_NOT_VERIFIED","path":x.get("path")})); sys.exit(4)
print(json.dumps({"status":"PASS"}))
