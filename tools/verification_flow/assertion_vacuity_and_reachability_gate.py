import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--assertions',required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.assertions).read_text())
for x in d.get('assertions',[]):
 if x.get('signoff_credit'):
  if not x.get('antecedent_reached'): print(json.dumps({'status':'FAIL','reason':'ASSERTION_UNREACHABLE','id':x.get('id')})); sys.exit(2)
  if x.get('attempt_count',0)<=0: print(json.dumps({'status':'FAIL','reason':'ASSERTION_VACUOUS','id':x.get('id')})); sys.exit(3)
  if not x.get('negative_control_failed'): print(json.dumps({'status':'FAIL','reason':'ASSERTION_EFFECTIVENESS_UNPROVEN','id':x.get('id')})); sys.exit(4)
print(json.dumps({'status':'PASS'}))
