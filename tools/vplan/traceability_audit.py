#!/usr/bin/env python3
# NOTICE (corrected 2026-08-28): the original NOTICE below claimed this
# module was "NOT invoked by any executing code path" -- that is now STALE,
# per CLAUDE.md's own Evidence Truth Rule ("current evidence wins and this
# file must be updated"). This script is wired into dv_harness/gates.py's
# STAGE_GATES["REQUIREMENT_CLOSURE (via the 2026-08-28 multi-payload run_gate() extension)"]. Original NOTICE text, now superseded: "this module
# is NOT invoked by any executing code path in dv_harness/ or
# .claude/agents/*.md as of this audit -- it is standalone/orphaned code."
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--vplan',required=True); ap.add_argument('--tests',required=True); a=ap.parse_args()
v=json.loads(pathlib.Path(a.vplan).read_text()); t=json.loads(pathlib.Path(a.tests).read_text())
req={r['req_id'] for r in v.get('requirements',[])}; orphan=[]
for tc in t.get('testcases',[]):
 ids=tc.get('vplan_requirement_ids',[])
 if not ids: orphan.append({'testcase':tc.get('testcase_id'),'reason':'no vplan trace'})
 for rid in ids:
  if rid not in req: orphan.append({'testcase':tc.get('testcase_id'),'reason':'unknown '+rid})
print(json.dumps({'orphan_testcases':orphan},indent=2))
sys.exit(0 if not orphan else 2)
