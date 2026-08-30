import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--model',required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.model).read_text())
if d.get('shares_dut_implementation_code'): print(json.dumps({'status':'FAIL','reason':'REFERENCE_MODEL_MIRRORS_DUT'})); sys.exit(2)
if d.get('shared_algorithm_source_hash') and d.get('shared_algorithm_source_hash')==d.get('dut_algorithm_source_hash'):
 print(json.dumps({'status':'FAIL','reason':'COMMON_MODE_DEFECT_RISK'})); sys.exit(3)
if not d.get('independent_oracle_basis'): print(json.dumps({'status':'FAIL','reason':'NO_INDEPENDENT_ORACLE_BASIS'})); sys.exit(4)
if not d.get('negative_control_detected'): print(json.dumps({'status':'FAIL','reason':'SCOREBOARD_EFFECTIVENESS_UNPROVEN'})); sys.exit(5)
print(json.dumps({'status':'PASS'}))
