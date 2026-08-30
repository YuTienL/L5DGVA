#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--scoreboards',required=True); a=ap.parse_args(); d=json.loads(pathlib.Path(a.scoreboards).read_text())
for s in d.get('scoreboards',[]):
 sid=s.get('scoreboard_id')
 if not s.get('expected_source'): print(json.dumps({'status':'FAIL','reason':'NO_EXPECTED_SOURCE','scoreboard_id':sid})); sys.exit(2)
 if s.get('expected_source')=='DUT_OUTPUT': print(json.dumps({'status':'FAIL','reason':'EXPECTED_DATA_DERIVED_FROM_DUT_OUTPUT','scoreboard_id':sid})); sys.exit(3)
 if not s.get('expected_source_hash'): print(json.dumps({'status':'FAIL','reason':'UNPINNED_EXPECTED_SOURCE','scoreboard_id':sid})); sys.exit(4)
 if not s.get('prediction_method'): print(json.dumps({'status':'FAIL','reason':'NO_PREDICTION_METHOD','scoreboard_id':sid})); sys.exit(5)
print(json.dumps({'status':'PASS'}))
