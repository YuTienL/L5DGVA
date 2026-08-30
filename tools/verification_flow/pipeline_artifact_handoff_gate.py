#!/usr/bin/env python3
import argparse,json,pathlib,sys
ORDER=['PUSH','BUILD','VERIFY','RUN_WAVE_1','FSDBREPORT_ANALYSIS']
ap=argparse.ArgumentParser(); ap.add_argument('--pipeline',required=True); a=ap.parse_args(); d=json.loads(pathlib.Path(a.pipeline).read_text()); stages=d.get('stages',[])
if [x.get('name') for x in stages]!=ORDER: print(json.dumps({'status':'FAIL','reason':'PIPELINE_STAGE_ORDER_INVALID'})); sys.exit(2)
prev=set()
for i,s in enumerate(stages):
 ins=set(s.get('inputs',[])); outs=set(s.get('outputs',[]))
 if i>0 and not ins.issubset(prev): print(json.dumps({'status':'FAIL','reason':'PIPELINE_INPUT_NOT_FROM_PREVIOUS_STAGE','stage':s.get('name'),'missing':sorted(ins-prev)})); sys.exit(3)
 if not outs: print(json.dumps({'status':'FAIL','reason':'PIPELINE_STAGE_WITHOUT_OUTPUT','stage':s.get('name')})); sys.exit(4)
 prev=outs
print(json.dumps({'status':'PASS'}))
