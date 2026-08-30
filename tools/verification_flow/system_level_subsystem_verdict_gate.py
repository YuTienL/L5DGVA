import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--system",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.system).read_text())
declared=d.get("system_verdict")
if declared not in ("PASS","FAIL","BLOCKED"): print(json.dumps({"status":"FAIL","reason":"INVALID_SYSTEM_VERDICT"})); sys.exit(3)
# Derive the verdict from subsystems[] unconditionally (not only when the
# agent already claims PASS) so a declared PASS can never mask a real
# subsystem failure behind the top-level field.
masked=[s.get("name") for s in d.get("subsystems",[])
        if s.get("verdict")!="PASS" and not (s.get("isolated") and s.get("approved_waiver_id"))]
derived_verdict="FAIL" if masked else "PASS"
if declared=="PASS" and masked:
 print(json.dumps({"status":"FAIL","reason":"SYSTEM_PASS_MASKS_SUBSYSTEM_FAILURE","masked_subsystems":masked})); sys.exit(2)
print(json.dumps({"status":"PASS","declared_verdict":declared,"derived_verdict":derived_verdict}))
