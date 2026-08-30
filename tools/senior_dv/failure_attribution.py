#!/usr/bin/env python3
# NOTICE (corrected 2026-08-28): an earlier NOTICE in this file (added during
# the industrial-grade audit, also dated 2026-08-28) claimed this module was
# NOT invoked by any executing code path in dv_harness/ or .claude/agents/*.md.
# That claim is now STALE and is corrected here: this script is wired into
# dv_harness/gates.py's STAGE_GATES["FAILURE_RECOVERY"] as
# ("failure_attribution", "../senior_dv/failure_attribution.py", "--trace"),
# and dv_harness/gates.py's run_gate() treats subprocess returncode==0 as the
# sole pass signal for that gate. This same change also makes the script
# actually exit non-zero (2) when the computed classification is UNKNOWN, so
# a gate wired to it can no longer silently PASS on an unresolved RCA the way
# it previously did (previously this script always exited 0 regardless of
# classification).
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--trace',required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.trace).read_text())
stages=d.get("boundary_trace",[])
first=None
for s in stages:
    if s.get("expected") != s.get("observed"):
        first=s; break
cls="UNKNOWN"
if first:
    st=first.get("stage")
    if st in ("SEQUENCE","DRIVER","MONITOR","CHECKER","SCOREBOARD"): cls="TB_BUG"
    elif st in ("DUT_INTERNAL","INTERFACE_OUT"): cls="DUT_BUG"
    elif st=="INTERFACE_IN": cls="UNKNOWN"
out={"first_bad_event":first,"classification":cls,"confidence":"MEDIUM" if first else "LOW"}
if cls=="UNKNOWN":
    out["reason"]="ATTRIBUTION_UNRESOLVED_EXTEND_BOUNDARY_TRACE"
print(json.dumps(out,indent=2))
sys.exit(2 if cls=="UNKNOWN" else 0)
