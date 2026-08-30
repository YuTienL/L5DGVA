# NOTICE (superseded 2026-08-28, 12-claim re-audit): the original industrial-
# grade-audit NOTICE below claimed this module was "NOT invoked by any
# executing code path" -- that is now FALSE, per CLAUDE.md's own Evidence
# Truth Rule ("current evidence wins and this file must be updated"). Real
# caller as of this audit: dv_harness/engine.py's run_stage() calls MultiAgentOrchestrator.delegate(node, plan) before every LLM call.
# Original NOTICE text, now superseded: "this module is NOT invoked by any
# executing code path in dv_harness/ or .claude/agents/*.md as of this audit
# -- it is standalone/orphaned code."
import json,os,tempfile,threading,uuid
from pathlib import Path
from .storage import _atomic_replace
class AgentTaskStore:
 # Graph-level parallel fan-out (2026-08-29): create_task()/acquire() are now
 # genuinely called concurrently (one call per ThreadPoolExecutor-dispatched
 # branch, from engine.py's _advance_with_fanout()/run_stage()) -- previously
 # the engine only ever ran one stage at a time, so the read-modify-write on
 # tasks.json/ownership.json below was never actually raced. A plain
 # write_text() let one thread observe another thread's file mid-write
 # (confirmed by a real JSONDecodeError under the new fan-out test), and even
 # without a crash, two threads reading the same snapshot before either wrote
 # back would silently lose one thread's append. self._lock (one per
 # in-process AgentTaskStore instance -- concurrency here is only ever
 # ThreadPoolExecutor threads within a single DVHarness process, never
 # multiprocessing/separate processes, per the fan-out design) serializes the
 # whole read-modify-write section; the atomic tempfile+os.replace write is
 # the same idiom storage.StateStore.save() already uses, kept for any
 # external concurrent reader (e.g. a dashboard poll) outside this lock.
 def __init__(self,root):
  self.dir=Path(root)/'.dv-harness'/'agents';self.dir.mkdir(parents=True,exist_ok=True);self.tasks=self.dir/'tasks.json';self.own=self.dir/'ownership.json'
  self._lock=threading.Lock()
  if not self.tasks.exists():self.tasks.write_text('[]',encoding='utf-8')
  if not self.own.exists():self.own.write_text('{}',encoding='utf-8')
 def _write_json_atomic(self,path,data):
  fd,tmp=tempfile.mkstemp(prefix=path.stem+'.',suffix='.tmp',dir=str(path.parent))
  try:
   with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
   _atomic_replace(tmp,path)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
 def create_task(self,agent,route,skills,parent_plan,parallel_group=None,depends_on=None):
  with self._lock:
   ts=json.loads(self.tasks.read_text(encoding='utf-8'));t={'task_id':'TASK-'+uuid.uuid4().hex[:8].upper(),'agent':agent,'route':route,'skills':skills,'parent_plan':parent_plan,'parallel_group':parallel_group,'depends_on':depends_on or [],'status':'NOT_STARTED'};ts.append(t);self._write_json_atomic(self.tasks,ts);return t
 def acquire(self,res,task_id,agent):
  with self._lock:
   o=json.loads(self.own.read_text(encoding='utf-8'))
   if res in o and o[res]['task_id']!=task_id:return False,o[res]
   o[res]={'task_id':task_id,'agent':agent,'mode':'WRITE'};self._write_json_atomic(self.own,o);return True,o[res]
class MultiAgentOrchestrator:
 def __init__(self,root):self.store=AgentTaskStore(root)
 def delegate(self,node,plan):return self.store.create_task(node.agent,node.route,node.skills,plan['plan_id'],node.parallel_group)
