import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--campaign',required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.campaign).read_text()); seeds=set(d.get('seeds',[])); configs=set(d.get('config_hashes',[]))
if d.get('random_corner_case_claim'):
 if len(seeds)<d.get('minimum_unique_seeds',2): print(json.dumps({'status':'FAIL','reason':'INSUFFICIENT_SEED_DIVERSITY'})); sys.exit(2)
 if len(configs)<d.get('minimum_unique_configs',1): print(json.dumps({'status':'FAIL','reason':'INSUFFICIENT_CONFIG_DIVERSITY'})); sys.exit(3)
 if not d.get('corner_case_bins_exercised'): print(json.dumps({'status':'FAIL','reason':'NO_CORNER_CASE_EVIDENCE'})); sys.exit(4)
print(json.dumps({'status':'PASS'}))
