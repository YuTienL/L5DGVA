#!/usr/bin/env python3
import argparse,json,pathlib,sys
BAD={'test1','test2','basic','misc','case1','tmp','new_test','scenario1'}
ap=argparse.ArgumentParser(); ap.add_argument('--tests',required=True); a=ap.parse_args(); d=json.loads(pathlib.Path(a.tests).read_text())
for t in d.get('tests',[]):
 tid=str(t.get('testcase_id','')).strip(); name=str(t.get('name','')).strip(); low=name.lower()
 if not tid or not name: print(json.dumps({'status':'FAIL','reason':'TEST_WITHOUT_ID_OR_NAME','testcase_id':tid})); sys.exit(2)
 if low in BAD or len(name)<8: print(json.dumps({'status':'FAIL','reason':'ABSTRACT_TEST_NAME','testcase_id':tid,'name':name})); sys.exit(3)
 if not any(x in low for x in ('reset','error','recovery','bulk','iso','dma','ltssm','traffic','interrupt','timeout','read','write','link','enumeration','concurrency','performance','power','clock','cdc','protocol')): print(json.dumps({'status':'FAIL','reason':'TEST_NAME_LACKS_VERIFICATION_SEMANTICS','testcase_id':tid,'name':name})); sys.exit(4)
print(json.dumps({'status':'PASS'}))
