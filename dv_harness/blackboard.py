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

 # --- Debug-loop round history (2026-09-01, ai-debug-closed-loop-counter-
 # implementation task): the "debug_loop_history" topic's value is the ONE
 # real, persisted, cross-cycle record of every full Fix->Push->Build->
 # Verify pass a failure has gone through -- distinct from
 # state.stages[stage]['attempts'] (models.py/engine.py), which is
 # node-scoped RETRY bookkeeping for ONE graph node, capped by
 # policy.max_stage_retries, and reset the moment current_stage moves on.
 # It cannot answer "how many full passes has this failure gone through
 # across the whole run" because a single logical debug-loop round can span
 # several different graph nodes (e.g. BUILD -> FAILURE_RECOVERY ->
 # CHANGE_IMPACT -> ... -> BUILD again). engine.py's DVHarness.
 # _record_debug_loop_round() appends one entry here every time loop()/
 # _advance_with_fanout() actually call policy.graph_next(stage,
 # Status.FAIL.value, ...) to route a stage whose retries are exhausted
 # onto its graph FAIL edge -- each entry records
 # {round_number, timestamp, failing_stage, target_fail_edge,
 # attempt_number, node_route, health_monitor_check}; health_monitor_check
 # is the real subprocess-checked `dv-harness lsf-watch-status` result for a
 # remote/LSF-route stage (engine.py's REMOTE_LSF_ROUTES), or None when the
 # failing stage's route never submits a build/regression job.
 def read_debug_loop_history(self):
  payload=self.read('debug_loop_history');val=payload.get('value') if isinstance(payload,dict) else None
  if not isinstance(val,dict) or not isinstance(val.get('entries'),list):val={'entries':[]}
  return val
 def append_debug_loop_round(self,entry,source=''):
  registry=self.read_debug_loop_history();entry=dict(entry);entry['round_number']=len(registry['entries'])+1
  registry['entries'].append(entry);self.write('debug_loop_history',registry,source=source);return registry
 def debug_loop_round_count(self,failing_stage=None):
  entries=self.read_debug_loop_history().get('entries',[])
  return len(entries) if failing_stage is None else sum(1 for e in entries if e.get('failing_stage')==failing_stage)
