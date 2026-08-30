#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--fw',required=True); a=ap.parse_args(); d=json.loads(pathlib.Path(a.fw).read_text())
if not d.get('interrupt_driven'): print(json.dumps({'status':'FAIL','reason':'FW_BRANCH_NOT_INTERRUPT_DRIVEN'})); sys.exit(2)
if not d.get('interrupt_map'): print(json.dumps({'status':'FAIL','reason':'NO_INTERRUPT_MAP'})); sys.exit(3)
if not d.get('acknowledge_path'): print(json.dumps({'status':'FAIL','reason':'NO_INTERRUPT_ACK_PATH'})); sys.exit(4)
if d.get('polling_primary'): print(json.dumps({'status':'FAIL','reason':'POLLING_CANNOT_BE_PRIMARY_FW_TRIGGER'})); sys.exit(5)
print(json.dumps({'status':'PASS'}))
