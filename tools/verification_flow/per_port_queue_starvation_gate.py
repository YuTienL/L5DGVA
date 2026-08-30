#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--queues',required=True); a=ap.parse_args(); d=json.loads(pathlib.Path(a.queues).read_text())
for q in d.get('ports',[]):
 pid=q.get('port_id')
 if not q.get('independent_queue'): print(json.dumps({'status':'FAIL','reason':'PORT_NOT_INDEPENDENT_QUEUE','port_id':pid})); sys.exit(2)
 if q.get('max_wait_cycles') is None: print(json.dumps({'status':'FAIL','reason':'NO_STARVATION_BOUND','port_id':pid})); sys.exit(3)
 if q.get('observed_wait_cycles',0)>q.get('max_wait_cycles'): print(json.dumps({'status':'FAIL','reason':'PORT_STARVATION_DETECTED','port_id':pid})); sys.exit(4)
 if not q.get('forward_progress_evidence'): print(json.dumps({'status':'FAIL','reason':'NO_FORWARD_PROGRESS_EVIDENCE','port_id':pid})); sys.exit(5)
print(json.dumps({'status':'PASS'}))
