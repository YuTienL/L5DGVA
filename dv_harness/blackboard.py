from __future__ import annotations
import json,os,tempfile,time
from pathlib import Path

# Read/write retry budget (2026-09-04). Same shape and reasoning as
# storage._atomic_replace()'s own loop -- see read() below for why a reader
# needs one too.
_READ_ATTEMPTS=10
_READ_BACKOFF_SEC=0.01

class Blackboard:
 def __init__(self,root):self.root=Path(root)/'.dv-harness'/'blackboard';self.root.mkdir(parents=True,exist_ok=True)
 def _path(self,t):return self.root/(t.strip('/').replace('/','__')+'.json')
 def read(self,t,default=None):
  """Read one topic, retrying a read that lost a race with a concurrent write.

  Concurrency here is REAL, not hypothetical: engine._advance_with_fanout()
  runs parallel_group branches through a genuine ThreadPoolExecutor inside
  ONE process, and every branch's run_stage() reads/writes topics from its
  own thread; dashboard.py additionally polls topic files straight off disk
  (_read_json_file) from an HTTP handler thread while a background run
  writes them. The engine's fan-out ownership claim
  (AgentTaskStore.acquire()) only stops two BRANCHES claiming the same
  WRITE topic -- it says nothing about a reader of an unrelated topic, and
  nothing about the file operation itself.

  Two distinct failures are retried, matching what write() below can and
  cannot rule out:
    - PermissionError -- Windows-only: a reader's CreateFile can lose the
      race with the writer's os.replace() (storage._atomic_replace()'s
      docstring describes the same window from the writer's side, and
      dashboard._read_json_file() already retries it from a reader's).
    - json.JSONDecodeError / UnicodeDecodeError -- a genuinely torn read.
      write() is atomic now, so this cannot come from THIS class any more;
      it can still come from a topic file written by an older harness
      version, hand-edited, or produced by an external tool mid-write.
  A file that stays unparseable across the whole budget raises, exactly as
  before -- silently returning `default` for a corrupt topic would present
  "no verification truth recorded" as if it were a fact, which is the one
  outcome the Blackboard must never fabricate."""
  p=self._path(t);last=None
  for attempt in range(_READ_ATTEMPTS):
   if not p.exists():return default
   try:return json.loads(p.read_text(encoding='utf-8'))
   except FileNotFoundError:return default
   except (json.JSONDecodeError,UnicodeDecodeError,PermissionError) as e:
    last=e;time.sleep(_READ_BACKOFF_SEC*(attempt+1))
  raise last
 def write(self,t,value,source='',confidence='HIGH'):
  """Write one topic ATOMICALLY: temp file in the same directory, then
  storage._atomic_replace() (2026-09-04).

  This used to be a plain p.write_text(), i.e. truncate-then-write, so any
  concurrent reader (see read()'s docstring for the three real concurrent
  readers) could observe a half-written topic file and get a
  JSONDecodeError -- and none of engine.py's ~17 self.blackboard.read/write
  call sites wraps the call in a try/except, so that exception would
  propagate straight out of run_stage() and fail an otherwise-good stage.
  tempfile was already imported by this module for a temp-file write that
  was never actually implemented; this is that write. _atomic_replace() is
  reused (not re-implemented) so the Windows os.replace()/PermissionError
  retry storage.py and question_queue.py already depend on covers this
  writer too."""
  from .storage import _atomic_replace
  payload={'topic':t,'value':value,'source':source,'confidence':confidence};p=self._path(t)
  fd,tmp=tempfile.mkstemp(prefix=p.stem+'.',suffix='.json',dir=str(self.root))
  try:
   with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False,indent=2)
   _atomic_replace(tmp,p)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
  return payload
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

 # --- CapabilityEvolutionCandidate registry (2026-09-04, Research-Capability
 # Evolution master prompt sections 63/70, Stage 1): the
 # "capability_evolution_candidates" topic's value is the ONE live record of
 # every proposed change to this harness's own capability --
 # {"items": {candidate_id: {...the full schema-valid candidate...}}}.
 # Same {"items": {...}} registry shape as `findings` above, on purpose:
 # section 11 forbids a parallel Research Blackboard, and a second shape here
 # would be one. dv_harness/capability_evolution.py's persist_candidate() is
 # the ONE real caller and therefore the sync point -- as with findings and
 # debug_loop_history, no second write path exists, so this topic cannot drift
 # from the Working Memory audit record persist_candidate() writes alongside
 # it via memory_router.route_and_store().
 #
 # A CANDIDATE lives here rather than in a Memory tier because it is live
 # current-run state, not settled knowledge: it is a DISCOVERED -> ... ->
 # PRODUCTION state machine, which is exactly what route_memory() already
 # sends to BLACKBOARD for kinds like "active_hypothesis"/"plan_state".
 # Nothing here is verification truth about a DUT: the confidence field on a
 # candidate is confidence in a PROPOSAL, and this topic must never be read as
 # evidence about a design.
 def read_capability_evolution_candidates(self):
  payload=self.read('capability_evolution_candidates');val=payload.get('value') if isinstance(payload,dict) else None
  if not isinstance(val,dict) or not isinstance(val.get('items'),dict):val={'items':{}}
  return val
 def upsert_capability_evolution_candidate(self,candidate_id,candidate,source=''):
  registry=self.read_capability_evolution_candidates();registry['items'][candidate_id]=dict(candidate)
  self.write('capability_evolution_candidates',registry,source=source);return registry
 def capability_evolution_counts(self):
  """Per-promotion-state counts. Deliberately NOT an open/closed split like
  findings_counts(): section 70's eleven states do not collapse into two
  without losing the governance distinction the policy exists to enforce."""
  items=self.read_capability_evolution_candidates().get('items',{});counts={}
  for v in items.values():counts[v.get('current_status','UNKNOWN')]=counts.get(v.get('current_status','UNKNOWN'),0)+1
  return {'total':len(items),'by_status':counts}
