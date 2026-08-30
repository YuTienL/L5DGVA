#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--readiness',required=True); a=ap.parse_args(); d=json.loads(pathlib.Path(a.readiness).read_text()); scores=d.get('scores',{}); status=d.get('status')
required=['DUT','ProtocolConfig','VIP','BuildFlow','Testbench','Specification','vPlan','Regression','Coverage']; missing=[x for x in required if x not in scores]
if missing: print(json.dumps({'status':'FAIL','reason':'MISSING_READINESS_DIMENSIONS','missing':missing})); sys.exit(2)
vals=list(scores.values())
if any((not isinstance(v,(int,float)) or v<0 or v>100) for v in vals): print(json.dumps({'status':'FAIL','reason':'INVALID_READINESS_SCORE'})); sys.exit(3)
overall=sum(vals)/len(vals); expected='READY' if all(scores[x]>=90 for x in ('DUT','ProtocolConfig','VIP','BuildFlow')) and overall>=85 else ('BLOCKED' if any(scores[x]<50 for x in ('DUT','ProtocolConfig','VIP','BuildFlow')) else 'PARTIAL')
if status!=expected: print(json.dumps({'status':'FAIL','reason':'READINESS_STATUS_MISMATCH','expected':expected,'actual':status,'overall':overall})); sys.exit(4)
print(json.dumps({'status':'PASS','overall':overall,'readiness':status}))
