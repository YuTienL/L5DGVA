#!/usr/bin/env python3
import argparse,json,pathlib
ap=argparse.ArgumentParser(); ap.add_argument('--feedback',required=True); ap.add_argument('--out',required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.feedback).read_text()); evidence=d.get('evidence',{}); ok=any(bool(v) for v in evidence.values())
d['confidence']='VERIFIED' if ok else 'UNVERIFIED'; d['status']='VERIFIED' if ok else 'NEED_EVIDENCE'
pathlib.Path(a.out).write_text(json.dumps(d,ensure_ascii=False,indent=2))
