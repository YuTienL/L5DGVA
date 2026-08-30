#!/usr/bin/env python3
import argparse,json,pathlib,sys
ORDER=['EXISTING_PROJECT_FILES','RTL_PARAMETERS_DEFINES','EXISTING_UVM_VIP_CONFIG','EXISTING_TESTS_SEQUENCES','DESIGN_DOCS','VPLAN_TEST_TABLE','BUILD_REGRESSION_SCRIPTS','GIT_HISTORY_COMMENTS','ASK_USER']
ap=argparse.ArgumentParser(); ap.add_argument('--trace',required=True); a=ap.parse_args(); d=json.loads(pathlib.Path(a.trace).read_text()); used=d.get('attempted_sources',[])
if any(x not in ORDER for x in used): print(json.dumps({'status':'FAIL','reason':'UNKNOWN_EVIDENCE_SOURCE'})); sys.exit(2)
idx=[ORDER.index(x) for x in used]
if idx!=sorted(idx): print(json.dumps({'status':'FAIL','reason':'EVIDENCE_PRIORITY_VIOLATION','attempted_sources':used})); sys.exit(3)
if 'ASK_USER' in used and not d.get('higher_priority_sources_exhausted'): print(json.dumps({'status':'FAIL','reason':'ASKED_USER_TOO_EARLY'})); sys.exit(4)
print(json.dumps({'status':'PASS'}))
