#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--requirements',required=True); a=ap.parse_args(); d=json.loads(pathlib.Path(a.requirements).read_text())
items=d.get('requirements',[])
if not items: print(json.dumps({'status':'FAIL','reason':'NO_REQUIREMENTS'})); sys.exit(2)
for r in items:
 rid=r.get('req_id')
 for k in ('spec_ref','feature','expected_behavior','verification_method','coverage_goal'):
  if not r.get(k): print(json.dumps({'status':'FAIL','reason':'INCOMPLETE_VPLAN_REQUIREMENT','req_id':rid,'missing':k})); sys.exit(3)
 if r.get('ambiguity') and not r.get('ambiguity_resolution_or_question'): print(json.dumps({'status':'FAIL','reason':'UNRESOLVED_REQUIREMENT_AMBIGUITY','req_id':rid})); sys.exit(4)
 # waiver_candidate is derived from support_status, not separately self-asserted:
 # UNSUPPORTED_BY_DUT already implies "this is a waiver candidate" by definition.
 if r.get('support_status')=='UNSUPPORTED_BY_DUT' and not r.get('design_evidence'): print(json.dumps({'status':'FAIL','reason':'UNSUPPORTED_WITHOUT_DESIGN_EVIDENCE','req_id':rid})); sys.exit(5)
print(json.dumps({'status':'PASS','requirements':len(items)}))
