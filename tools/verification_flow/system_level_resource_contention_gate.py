#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--plan',required=True); a=ap.parse_args(); d=json.loads(pathlib.Path(a.plan).read_text()); shared=set(d.get('shared_resources',[]))
for sc in d.get('scenarios',[]):
 sid=sc.get('scenario_id'); cont=set(sc.get('resources',[])) & shared
 if cont and not sc.get('arbitration_or_contention_policy'): print(json.dumps({'status':'FAIL','reason':'SHARED_RESOURCE_WITHOUT_CONTENTION_POLICY','scenario_id':sid})); sys.exit(2)
 if cont and not sc.get('contention_testcase_ids'): print(json.dumps({'status':'FAIL','reason':'NO_CONTENTION_TESTS','scenario_id':sid})); sys.exit(3)
print(json.dumps({'status':'PASS'}))
