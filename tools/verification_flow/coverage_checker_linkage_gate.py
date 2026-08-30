#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--coverage',required=True); a=ap.parse_args(); d=json.loads(pathlib.Path(a.coverage).read_text())
for c in d.get('items',[]):
 cid=c.get('coverage_id'); active=(c.get('active_checker_ids') or c.get('active_scoreboard_ids') or c.get('active_assertion_ids')); valid=c.get('waived') and c.get('waiver_approved') and c.get('waiver_evidence')
 if c.get('credit') and not active and not valid: print(json.dumps({'status':'FAIL','reason':'COVERAGE_CREDIT_WITHOUT_ACTIVE_CHECK_OR_VALID_WAIVER','coverage_id':cid})); sys.exit(2)
 if c.get('waived') and not valid: print(json.dumps({'status':'FAIL','reason':'INVALID_COVERAGE_WAIVER','coverage_id':cid})); sys.exit(3)
print(json.dumps({'status':'PASS'}))
