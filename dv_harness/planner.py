# NOTICE (superseded 2026-08-28, 12-claim re-audit): the original industrial-
# grade-audit NOTICE below claimed this module was "NOT invoked by any
# executing code path" -- that is now FALSE, per CLAUDE.md's own Evidence
# Truth Rule ("current evidence wins and this file must be updated"). Real
# caller as of this audit: dv_harness/engine.py's run_stage() calls PlanStore.create()/_find_latest_plan (via control_plane) and default_plan(node) before every LLM call, folding the plan into the prompt via _build_plan_section().
# Original NOTICE text, now superseded: "this module is NOT invoked by any
# executing code path in dv_harness/ or .claude/agents/*.md as of this audit
# -- it is standalone/orphaned code."
import json,uuid
from pathlib import Path
class PlanStore:
 def __init__(self,root):self.dir=Path(root)/'.dv-harness'/'plans';self.dir.mkdir(parents=True,exist_ok=True)
 def create(self,node_id,goal,tasks):
  pid='PLAN-'+uuid.uuid4().hex[:8].upper();p={'plan_id':pid,'node_id':node_id,'goal':goal,'status':'RUNNING','steps':tasks,'revision':1};self.save(p);return p
 def save(self,p):(self.dir/(p['plan_id']+'.json')).write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8')
 def replan(self,p,reason,evidence,new_steps):
  with (self.dir/'replans.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'plan_id':p['plan_id'],'revision':p['revision'],'reason':reason,'evidence':evidence},ensure_ascii=False)+'\n')
  p['revision']+=1;p['steps']=new_steps;self.save(p);return p
def default_plan(node):
 return [{'step_id':f'P{i:02d}','name':sk,'route':node.route,'agent':node.agent,'skill':sk,'status':'NOT_STARTED'} for i,sk in enumerate(node.skills,1)] or [{'step_id':'P01','name':node.id,'route':node.route,'agent':node.agent,'status':'NOT_STARTED'}]
