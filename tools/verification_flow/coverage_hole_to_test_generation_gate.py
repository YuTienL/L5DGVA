import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--holes',required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.holes).read_text())
for x in d.get('items',[]):
 if x.get('covered') or x.get('approved_waiver_id'): continue
 if not x.get('generated_test_ids'): print(json.dumps({'status':'FAIL','reason':'UNCOVERED_ITEM_WITHOUT_TEST_GENERATION','id':x.get('id')})); sys.exit(2)
 if not x.get('closure_owner'): print(json.dumps({'status':'FAIL','reason':'COVERAGE_HOLE_WITHOUT_OWNER','id':x.get('id')})); sys.exit(3)
 if not x.get('trace_to_vplan'): print(json.dumps({'status':'FAIL','reason':'COVERAGE_HOLE_WITHOUT_VPLAN_TRACE','id':x.get('id')})); sys.exit(4)
print(json.dumps({'status':'PASS'}))
