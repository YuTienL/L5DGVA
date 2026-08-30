# NOTICE (added during industrial-grade audit, 2026-08-28): this module is
# NOT invoked by any executing code path in dv_harness/ or .claude/agents/*.md
# as of this audit -- it is standalone/orphaned code. Any WORKFLOW_MANIFEST.json
# capability flag referencing this file's feature is aspirational, not a
# statement that this code actually runs in the pipeline. See
# CHANGELOG_v0_to_v50.md and the industrial-grade-deep-audit findings for detail.
from pathlib import Path
from .graph import GraphDefinition,GraphState
from .blackboard import Blackboard
from .router import RouteResolver
from .planner import PlanStore,default_plan
from .multi_agent import MultiAgentOrchestrator
from .react import ReactRecorder
from .skill_resolver import SkillResolver
class GraphRuntime:
 def __init__(self,root):
  self.root=Path(root).resolve();self.gdef=GraphDefinition.load(self.root/'.dv-harness'/'graph'/'main_graph.json');self.gstate=GraphState(self.root/'.dv-harness'/'graph'/'graph_state.json');self.bb=Blackboard(self.root);self.router=RouteResolver();self.plans=PlanStore(self.root);self.agents=MultiAgentOrchestrator(self.root);self.react=ReactRecorder(self.root);self.skills=SkillResolver(self.root)
 def prepare_node(self,node_id,goal):
  n=self.gdef.nodes[node_id];r=self.router.resolve(n);rs=self.skills.resolve(n.skills);p=self.plans.create(node_id,goal,default_plan(n));t=self.agents.delegate(n,p);snap=self.bb.snapshot(n.blackboard_read);self.gstate.set_active(node_id);return {'node':node_id,'route':r,'skills':rs,'plan':p,'task':t,'blackboard':snap}
 def complete_node(self,node_id,result,evidence=None):
  self.gstate.result(node_id,result,evidence or []);n=self.gdef.next_for(node_id,result);self.gstate.set_active(n) if n else None;return n
