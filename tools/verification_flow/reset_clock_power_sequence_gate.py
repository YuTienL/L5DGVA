#!/usr/bin/env python3
import argparse,json,pathlib,sys

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--sequence',required=True); a=ap.parse_args(); d=json.loads(pathlib.Path(a.sequence).read_text()); ev=d.get('events',[])
 if not ev: print(json.dumps({'status':'FAIL','reason':'NO_SEQUENCE_EVENTS'})); return 2
 seen={e.get('event'):i for i,e in enumerate(ev)}
 for r in d.get('ordering_rules',[]):
  b=r.get('before'); af=r.get('after')
  if b not in seen or af not in seen: print(json.dumps({'status':'FAIL','reason':'ORDERING_RULE_EVENT_MISSING'})); return 3
  if seen[b]>=seen[af]: print(json.dumps({'status':'FAIL','reason':'SEQUENCE_ORDER_VIOLATION','before':b,'after':af})); return 4
 if d.get('power_aware_design') and not d.get('isolation_or_retention_checked'): print(json.dumps({'status':'FAIL','reason':'POWER_SEQUENCE_WITHOUT_ISOLATION_RETENTION_CHECK'})); return 5
 print(json.dumps({'status':'PASS'})); return 0
if __name__=='__main__': sys.exit(main())
