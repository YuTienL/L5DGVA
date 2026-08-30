from __future__ import annotations
import json,os,tempfile
from pathlib import Path
class Blackboard:
 def __init__(self,root):self.root=Path(root)/'.dv-harness'/'blackboard';self.root.mkdir(parents=True,exist_ok=True)
 def _path(self,t):return self.root/(t.strip('/').replace('/','__')+'.json')
 def read(self,t,default=None):
  p=self._path(t);return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default
 def write(self,t,value,source='',confidence='HIGH'):
  payload={'topic':t,'value':value,'source':source,'confidence':confidence};p=self._path(t);p.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');return payload
 def snapshot(self,topics):return {t:self.read(t) for t in topics}

 # --- Findings registry (2026-08-29 reconciliation): the "findings" topic's
 # value is the ONE real structured record of open/closed findings --
 # {"items": {finding_id: {"status": "open"|"closed", ...}}, "last_report": {...}}.
 # engine.py's DVHarness._sync_findings_state() reads findings_counts() below
 # and mirrors it into state.findings_total/open/closed on every load and
 # every write here, so those two records cannot diverge -- there is no
 # second write path for the counts any more.
 def read_findings(self):
  payload=self.read('findings');val=payload.get('value') if isinstance(payload,dict) else None
  if not isinstance(val,dict) or not isinstance(val.get('items'),dict):val={'items':{}}
  return val
 def upsert_finding(self,finding_id,status,meta=None,source=''):
  registry=self.read_findings();item=dict(registry['items'].get(finding_id,{}));item.update(meta or {});item['status']=status
  registry['items'][finding_id]=item;self.write('findings',registry,source=source);return registry
 def findings_counts(self):
  items=self.read_findings().get('items',{});total=len(items);closed=sum(1 for v in items.values() if v.get('status')=='closed')
  return {'total':total,'open':total-closed,'closed':closed}
