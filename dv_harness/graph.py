# NOTICE (superseded 2026-08-28, 12-claim re-audit; further updated
# 2026-09-03, gap-close-engine cleanup): the original industrial-grade-audit
# NOTICE below claimed this module was "NOT invoked by any executing code
# path" -- that is now FALSE, per CLAUDE.md's own Evidence Truth Rule
# ("current evidence wins and this file must be updated"). Two real callers
# as of this audit:
#   - dv_harness/engine.py's DVHarness._load_graph()/run_stage(): loads
#     GraphDefinition and reads node.route/agent/skills/blackboard_read/
#     blackboard_write per stage, feeding RouteResolver/PlanStore/
#     MultiAgentOrchestrator/Blackboard before every LLM call.
#   - dv_harness/policy.py's graph_next(): the actual PASS/FAIL stage-
#     transition edge lookup now calls GraphDefinition.next_for() directly
#     (previously a separate, duplicate raw-JSON edge parser).
# GraphState previously lived below, backing the now-deleted
# dv_harness/graph_runtime.py's GraphRuntime -- reachable only via the
# documented scripts/powershell/DV_GRAPH_STATUS.ps1 script, which read/wrote a permanently-
# stale .dv-harness/graph/graph_state.json disconnected from the real
# .dv-harness/state.json HarnessState engine.py actually drives. Per the
# 2026-09-03 gap-close-engine audit, scripts/powershell/DV_GRAPH_STATUS.ps1 was retargeted to
# read the real live HarnessState (same as `dv-harness status`), and
# graph_runtime.py/GraphState/the stray graph_state.json were removed as
# nothing real referenced them any more. Original NOTICE text, now
# superseded: "this module is NOT invoked by any executing code path in
# dv_harness/ or .claude/agents/*.md as of this audit -- it is
# standalone/orphaned code."
from __future__ import annotations
import json
from dataclasses import dataclass,field
from pathlib import Path
from typing import Any,Dict,List,Optional
@dataclass
class Edge:
 source:str; target:str; condition:str='PASS'; priority:int=100
# expected_evidence/expected_outputs (2026-09-01, expected-evidence-checklist
# design pass): purely additive, OPTIONAL node fields -- absence (the default,
# empty list) means "no checklist for this stage", never an error. Each entry
# is {"item_id": str, "description": str, "kind": "file_path"|"blackboard_key"
# |"evidence_field"}. expected_evidence describes what the stage needs
# PRESENT AT ENTRY (checked by engine.build_stage_entry_checklist before the
# LLM call); expected_outputs describes what the stage should have PRODUCED
# AT EXIT (checked by engine.build_stage_exit_checklist after the gate
# verdict is known). Both are informational-only -- see those two functions'
# docstrings in engine.py for exactly how each `kind` is resolved to a
# present/absent bool. Only main_graph.json's INTAKE/BUILD/VERIFY/REGRESSION/
# COVERAGE_CLOSURE/SIGNOFF nodes populate these so far (transcribed from the
# real requirements prompts.STAGE_INSTRUCTIONS/gates.STAGE_GATES already
# state for those stages, not invented) -- every other node simply omits the
# fields, which GraphDefinition.load()'s Node(**n) already tolerates via
# these defaults.
@dataclass
class Node:
 id:str; route:str; agent:str; skills:List[str]=field(default_factory=list); planner:str='plan-and-execute'; react:bool=True; blackboard_read:List[str]=field(default_factory=list); blackboard_write:List[str]=field(default_factory=list); parallel_group:Optional[str]=None; join_group:Optional[str]=None; completion_gate:Dict[str,Any]=field(default_factory=dict); expected_evidence:List[Dict[str,Any]]=field(default_factory=list); expected_outputs:List[Dict[str,Any]]=field(default_factory=list)
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
