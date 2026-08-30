#!/usr/bin/env python3
import argparse,json,pathlib,sys
ORDER=['BUILDER_AVAILABLE','EVIDENCE_READY','ENV_GENERATED','COMPILE_QUALIFIED','SMOKE_QUALIFIED','PROTOCOL_QUALIFIED','REGRESSION_QUALIFIED','PRODUCTION_QUALIFIED']
ap=argparse.ArgumentParser(); ap.add_argument('--evidence',required=True); ap.add_argument('--target',choices=ORDER,default='SMOKE_QUALIFIED'); a=ap.parse_args()
d=json.loads(pathlib.Path(a.evidence).read_text()); passed=set(d.get('passed_gates',[])); missing=[g for g in ORDER[1:ORDER.index(a.target)+1] if g not in passed]
if missing:
    print('FAIL missing:',', '.join(missing)); sys.exit(2)
print('PASS',a.target)
