#!/usr/bin/env python3
# NOTICE (corrected 2026-08-28): the original NOTICE below claimed this
# module was "NOT invoked by any executing code path" -- that is now STALE,
# per CLAUDE.md's own Evidence Truth Rule ("current evidence wins and this
# file must be updated"). This script is wired into dv_harness/gates.py's
# STAGE_GATES["VPLAN"]. Original NOTICE text, now superseded: "this module
# is NOT invoked by any executing code path in dv_harness/ or
# .claude/agents/*.md as of this audit -- it is standalone/orphaned code."
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--vplan',required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.vplan).read_text()); reqs=d.get('requirements',[])
if not reqs: print(json.dumps({'coverage_percent':0,'error':'no requirements'})); sys.exit(2)
credited=0; invalid=[]
for r in reqs:
 st=r.get('status')
 if st=='VERIFIED': credited+=1
 elif st=='WAIVED':
  w=r.get('waiver',{})
  if r.get('support_status')=='UNSUPPORTED_BY_DUT' and w.get('approved') and w.get('evidence'): credited+=1
  else: invalid.append({'req_id':r.get('req_id'),'reason':'invalid waiver'})
 elif st=='NOT_APPLICABLE': credited+=1
coverage=100.0*credited/len(reqs)
print(json.dumps({'total':len(reqs),'credited':credited,'coverage_percent':coverage,'invalid':invalid},indent=2))
sys.exit(0 if coverage==100.0 and not invalid else 3)
