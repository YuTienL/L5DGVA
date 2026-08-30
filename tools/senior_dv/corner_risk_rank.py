#!/usr/bin/env python3
# NOTICE (corrected 2026-08-28): the original NOTICE below claimed this
# module was "NOT invoked by any executing code path" -- that is now STALE,
# per CLAUDE.md's own Evidence Truth Rule ("current evidence wins and this
# file must be updated"). This script is wired into dv_harness/gates.py's
# STAGE_GATES["SOC_SCENARIO_PLANNER"]. Original NOTICE text, now superseded: "this module
# is NOT invoked by any executing code path in dv_harness/ or
# .claude/agents/*.md as of this audit -- it is standalone/orphaned code."
import argparse,json,pathlib
ap=argparse.ArgumentParser(); ap.add_argument('--cases',required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.cases).read_text())
weights={"reset":3,"cdc":3,"concurrency":3,"error_recovery":3,"ordering":2,"backpressure":2,"resource_limit":2,"new_rtl":3,"spec_ambiguity":3,"coverage_gap":2,"historical_bug":4}
out=[]
for c in d.get("cases",[]):
    score=sum(weights.get(x,1) for x in c.get("risk_factors",[]))
    risk="P0" if score>=9 else "P1" if score>=6 else "P2" if score>=3 else "P3"
    out.append({"corner_id":c["corner_id"],"score":score,"risk":risk})
print(json.dumps({"ranked":sorted(out,key=lambda x:-x["score"])},indent=2))
