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

# Claim SCOPE (2026-09-06, multi-user coordination detection, spec section 239).
# acquire() has always written exactly one kind of claim: an INTRA-PROCESS one.
# Its only production caller is engine.py's _advance_with_fanout(), which claims
# a blackboard TOPIC so two ThreadPoolExecutor branches of the same
# parallel_group inside ONE DVHarness process cannot both write it. Those topic
# names ("findings", "verification_state", ...) are identical in every project
# by construction, so comparing them ACROSS two users' project roots would
# report a conflict on every pair of sessions that ever ran a fan-out -- which
# is why the scope has to be recorded rather than inferred.
#
#   SCOPE_LOCAL  -- the pre-existing meaning: this claim is only about branches
#                   inside one process/one project root. Never compared across
#                   sessions.
#   SCOPE_SHARED -- a claim on something that genuinely exists once across ALL
#                   users of a deployment (an AMBA fabric port, a VIP instance,
#                   a scarce license feature, a farm/regression slot). These are
#                   the only claims multi_user_coordination.py compares between
#                   two users' sessions.
#
# Records written before this existed carry no "scope" key; read_reservations()
# below reads a missing scope as SCOPE_LOCAL, so no historical ownership.json
# can be reinterpreted into a cross-user conflict it never meant.
SCOPE_LOCAL = "LOCAL"
SCOPE_SHARED = "SHARED"

MODE_WRITE = "WRITE"
MODE_READ = "READ"

#: The kinds of genuinely-shared resource a SHARED claim may name. Closed set on
#: purpose: two users typing "AXI_M0" under two different free-text kinds would
#: never be seen to collide, so an unvalidated kind field would silently defeat
#: the detector it exists to feed.
SHARED_RESOURCE_KINDS = (
 "amba_fabric_port",   # one physical fabric port / bind location (amba_port_registry.py's rows)
 "vip_instance",       # one VIP agent/BFM instance (system_resource_registry.py's SAME_PHYSICAL members)
 "license_feature",    # one scarce EDA license feature (preflight.check_license()'s feature names)
 "regression_slot",    # one reserved farm/queue allocation
 "shared_path",        # one shared filesystem path (a deployed environment, a shared run dir)
)


class ResourceKindError(ValueError):
 """A SHARED claim named a resource kind outside SHARED_RESOURCE_KINDS."""


def ownership_path(root):
 """Where a project root's claim ledger lives. Read-only helper: unlike
 AgentTaskStore.__init__ it creates nothing, so a coordination scan can read
 ANOTHER user's project root without writing into it."""
 return Path(root)/'.dv-harness'/'agents'/'ownership.json'


def read_reservations(root,scope=None):
 """Every claim recorded in `root`'s ownership.json, as a list of dicts each
 carrying its own `resource` key. `scope` filters (e.g. SCOPE_SHARED). A
 missing/unreadable ledger is an empty list -- a peer session that has never
 claimed anything is not an error. A record with no `scope` key predates the
 2026-09-06 scope split and reads as SCOPE_LOCAL."""
 p=ownership_path(root)
 try:
  if not p.exists():return []
  data=json.loads(p.read_text(encoding='utf-8'))
 except Exception:
  return []
 if not isinstance(data,dict):return []
 out=[]
 for res,rec in data.items():
  if not isinstance(rec,dict):continue
  row=dict(rec);row['resource']=res
  row.setdefault('scope',SCOPE_LOCAL)
  row.setdefault('mode',MODE_WRITE)
  row.setdefault('kind',None)
  if scope is not None and row['scope']!=scope:continue
  out.append(row)
 out.sort(key=lambda r:(str(r.get('kind') or ''),str(r['resource'])))
 return out


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
 def acquire(self,res,task_id,agent,scope=SCOPE_LOCAL,kind=None,mode=MODE_WRITE):
  """Claim `res` for `task_id`. Unchanged for the pre-existing call site
  (engine.py's fan-out topic claim, which passes neither scope nor kind and
  still gets a LOCAL WRITE claim); `scope=SCOPE_SHARED` additionally records
  the resource KIND and a real claim timestamp so
  multi_user_coordination.py can compare this claim against another user's.

  A SHARED claim MUST name a kind from SHARED_RESOURCE_KINDS -- see that
  constant's own comment for why an open-ended kind would defeat the
  detector. Contention semantics are untouched: an already-claimed resource
  held by a DIFFERENT task returns (False, owner) and this store still holds
  no cross-PROCESS lock (two users on two roots have two ledgers -- that is
  exactly the situation the cross-session detector exists to report)."""
  if scope==SCOPE_SHARED and kind not in SHARED_RESOURCE_KINDS:
   raise ResourceKindError(
    f"SHARED claim on {res!r} named resource kind {kind!r}; expected one of "
    f"{', '.join(SHARED_RESOURCE_KINDS)}")
  with self._lock:
   o=json.loads(self.own.read_text(encoding='utf-8'))
   if res in o and o[res]['task_id']!=task_id:return False,o[res]
   rec={'task_id':task_id,'agent':agent,'mode':mode,'scope':scope}
   if scope==SCOPE_SHARED:rec['kind']=kind;rec['claimed_at']=time.time()
   o[res]=rec;self._write_json_atomic(self.own,o);return True,o[res]
 def release(self,res,task_id):
  """Drop `res`'s claim, but only from the task that holds it. Returns
  (True, released_record) or (False, current_owner_or_None).

  Needed by the SHARED half specifically: a LOCAL fan-out claim dies with the
  process that made it, but a SHARED reservation persists on disk, so with no
  release verb every finished reservation would keep colliding with the next
  user forever and the detector would report nothing but false positives. A
  non-holder cannot release someone else's claim -- releasing is not a way
  around the contention check above."""
  with self._lock:
   o=json.loads(self.own.read_text(encoding='utf-8'))
   cur=o.get(res)
   if cur is None:return False,None
   if cur.get('task_id')!=task_id:return False,cur
   del o[res];self._write_json_atomic(self.own,o);return True,cur
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
