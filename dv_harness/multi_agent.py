# NOTICE (superseded 2026-08-28, 12-claim re-audit): the original industrial-
# grade-audit NOTICE below claimed this module was "NOT invoked by any
# executing code path" -- that is now FALSE, per CLAUDE.md's own Evidence
# Truth Rule ("current evidence wins and this file must be updated"). Real
# caller as of this audit: dv_harness/engine.py's run_stage() calls MultiAgentOrchestrator.delegate(node, plan, route_info=...) before every LLM call.
# Original NOTICE text, now superseded: "this module is NOT invoked by any
# executing code path in dv_harness/ or .claude/agents/*.md as of this audit
# -- it is standalone/orphaned code."
#
# NOTICE (2026-09-01, multi-agent-timing-reconciliation pass): create_task()
# previously produced a task dict with ZERO timing fields and there was no
# complete_task()-style method at all -- this store was completely
# disconnected from stage_profile.py's real timing/token machinery, even
# though engine.py's run_stage() delegates a real task here before every LLM
# call. start_task()/complete_task() below now give every delegated task a
# real started_at/completed_at/duration_sec, and run_stage() wires real calls
# into both around its adapter.run() call (see engine.py's own comment at
# that call site for the exact lifecycle boundary and the reconciliation
# ruling into stage_profile.py).
import json,os,tempfile,threading,time,uuid
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
   ts=json.loads(self.tasks.read_text(encoding='utf-8'))
   # started_at/completed_at/duration_sec (2026-09-01, multi-agent-timing-
   # reconciliation pass): null/not-yet-started by construction -- a task is
   # only ever timed by a real start_task()/complete_task() call below, never
   # backfilled with a guessed value here.
   t={'task_id':'TASK-'+uuid.uuid4().hex[:8].upper(),'agent':agent,'route':route,'skills':skills,'parent_plan':parent_plan,'parallel_group':parallel_group,'depends_on':depends_on or [],'status':'NOT_STARTED','started_at':None,'completed_at':None,'duration_sec':None}
   ts.append(t);self._write_json_atomic(self.tasks,ts);return t
 def _find_task(self,ts,task_id):
  for t in ts:
   if t['task_id']==task_id:return t
  raise KeyError(f"AgentTaskStore: unknown task_id {task_id!r}")
 def start_task(self,task_id):
  """Marks a delegated task RUNNING with a real wall-clock started_at
  (time.time(), same epoch-float convention stage_profile.py's
  start_time_epoch already uses) -- called by engine.py's run_stage()
  immediately before the adapter.run() call this task was delegated for."""
  with self._lock:
   ts=json.loads(self.tasks.read_text(encoding='utf-8'))
   t=self._find_task(ts,task_id)
   t['status']='RUNNING';t['started_at']=time.time()
   self._write_json_atomic(self.tasks,ts);return t
 def complete_task(self,task_id,status,duration_sec=None):
  """Marks a delegated task finished with a real completed_at and a real
  duration_sec. duration_sec is computed from this task's own
  started_at/completed_at (time.time() diff) unless the caller passes one
  explicitly (e.g. a caller with its own higher-resolution perf_counter
  span for the exact same work). A task completed without ever going
  through start_task() (defensive case, not the real engine.py call path)
  backfills started_at=completed_at so duration_sec is still a real
  measurement (0.0) rather than None/negative/fabricated."""
  with self._lock:
   ts=json.loads(self.tasks.read_text(encoding='utf-8'))
   t=self._find_task(ts,task_id)
   t['completed_at']=time.time()
   if t.get('started_at') is None:t['started_at']=t['completed_at']
   t['duration_sec']=float(duration_sec) if duration_sec is not None else max(0.0,t['completed_at']-t['started_at'])
   t['status']=status
   self._write_json_atomic(self.tasks,ts);return t
 def acquire(self,res,task_id,agent):
  with self._lock:
   o=json.loads(self.own.read_text(encoding='utf-8'))
   if res in o and o[res]['task_id']!=task_id:return False,o[res]
   o[res]={'task_id':task_id,'agent':agent,'mode':'WRITE'};self._write_json_atomic(self.own,o);return True,o[res]
class MultiAgentOrchestrator:
 def __init__(self,root):self.store=AgentTaskStore(root)
 def delegate(self,node,plan,route_info=None):
  """Creates the real AgentTaskStore record for one stage's delegated work.

  `route_info` is router.RouteResolver.resolve()'s output for this node. Until
  2026-09-04 this method read node.agent/node.route/node.skills directly, so
  the task actually delegated carried the design-time skill list even when the
  run's evidence-driven protocol decision had widened it -- the delegated task
  and the resolved route disagreed. Taking route_info makes the delegated task
  the resolved one. Falls back to the node's own fields when no route_info is
  supplied (defensive; engine.run_stage() always supplies one)."""
  ri=route_info or {}
  agent=ri.get('agent') or node.agent
  route=ri.get('route') or node.route
  skills=ri['skills'] if ri.get('skills') is not None else node.skills
  return self.store.create_task(agent,route,skills,plan['plan_id'],node.parallel_group)
