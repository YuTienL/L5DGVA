# NOTICE (superseded 2026-08-28, 12-claim re-audit): the original industrial-
# grade-audit NOTICE below claimed this module was "NOT invoked by any
# executing code path" -- that is now FALSE, per CLAUDE.md's own Evidence
# Truth Rule ("current evidence wins and this file must be updated"). Two
# real callers as of this audit:
#   - dv_harness/engine.py's DVHarness._load_graph()/run_stage(): loads
#     GraphDefinition and reads node.route/agent/skills/blackboard_read/
#     blackboard_write per stage, feeding RouteResolver/PlanStore/
#     MultiAgentOrchestrator/Blackboard before every LLM call.
#   - dv_harness/policy.py's graph_next(): the actual PASS/FAIL stage-
#     transition edge lookup now calls GraphDefinition.next_for() directly
#     (previously a separate, duplicate raw-JSON edge parser).
# GraphState (below) remains genuinely unused outside dv_harness/
# graph_runtime.py, which is itself still not invoked by any executing path
# (see graph_runtime.py's own NOTICE) -- .dv-harness/graph/graph_state.json
# on disk is a stray artifact of a standalone GraphRuntime invocation,
# disconnected from the real .dv-harness/state.json HarnessState that
# engine.py actually drives. Original NOTICE text, now superseded:
# "this module is NOT invoked by any executing code path in dv_harness/ or
# .claude/agents/*.md as of this audit -- it is standalone/orphaned code."
from __future__ import annotations
import json
from dataclasses import dataclass,field
from pathlib import Path
from typing import Any,Dict,List,Optional
@dataclass
class Edge:
 source:str; target:str; condition:str='PASS'; priority:int=100
@dataclass
class Node:
 id:str; route:str; agent:str; skills:List[str]=field(default_factory=list); planner:str='plan-and-execute'; react:bool=True; blackboard_read:List[str]=field(default_factory=list); blackboard_write:List[str]=field(default_factory=list); parallel_group:Optional[str]=None; join_group:Optional[str]=None; completion_gate:Dict[str,Any]=field(default_factory=dict)
class GraphDefinition:
 def __init__(self,nodes,edges): self.nodes={n.id:n for n in nodes}; self.edges=edges
 @classmethod
 def load(cls,path):
  r=json.loads(Path(path).read_text(encoding='utf-8'));return cls([Node(**n) for n in r['nodes']],[Edge(**e) for e in r['edges']])
 def outgoing(self,n):return sorted([e for e in self.edges if e.source==n],key=lambda x:x.priority)
 def next_for(self,n,result):
  for e in self.outgoing(n):
   if e.condition in (result,'ANY'):return e.target
  return None
 def next_frontier(self,n,result):
  # Superset of next_for(): returns EVERY matching-condition outgoing
  # target from n, not just the first. For any node with a single matching
  # edge (every node in main_graph.json except a parallel_group fan-out
  # source like PROTOCOL_CAPABILITY) this returns a single-element list
  # carrying the exact same target next_for() would -- next_for() itself is
  # left untouched so its existing callers (policy.graph_next(), etc.) are
  # unaffected.
  return [e.target for e in self.outgoing(n) if e.condition in (result,'ANY')]
class GraphState:
 def __init__(self,path):
  self.path=Path(path);self.data=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'active_nodes':[],'completed_nodes':[],'blocked_nodes':[],'node_results':{},'iteration':0};self.save()
 def save(self):self.path.parent.mkdir(parents=True,exist_ok=True);self.path.write_text(json.dumps(self.data,ensure_ascii=False,indent=2),encoding='utf-8')
 def set_active(self,n):self.data['active_nodes']=[n];self.save()
 def result(self,n,status,evidence=None):
  self.data['node_results'][n]={'status':status,'evidence':evidence or []}
  if status in ('PASS','CLOSED') and n not in self.data['completed_nodes']:self.data['completed_nodes'].append(n)
  if status in ('BLOCKED','WAIT_USER') and n not in self.data['blocked_nodes']:self.data['blocked_nodes'].append(n)
  self.save()
