import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--evidence',required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.evidence).read_text())
for x in d.get('checks',[]):
 if not x.get('positive_passed'): print(json.dumps({'status':'FAIL','reason':'POSITIVE_CONTROL_FAILED','id':x.get('id')})); sys.exit(2)
 if not x.get('negative_mutation_applied'): print(json.dumps({'status':'FAIL','reason':'NO_NEGATIVE_MUTATION','id':x.get('id')})); sys.exit(3)
 if x.get('negative_control_result')!='FAIL': print(json.dumps({'status':'FAIL','reason':'VACUOUS_TEST_OR_CHECKER','id':x.get('id')})); sys.exit(4)
print(json.dumps({'status':'PASS'}))
