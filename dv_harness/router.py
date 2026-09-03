# NOTICE (superseded 2026-08-28, 12-claim re-audit): the original industrial-
# grade-audit NOTICE below claimed this module was "NOT invoked by any
# executing code path" -- that is now FALSE, per CLAUDE.md's own Evidence
# Truth Rule ("current evidence wins and this file must be updated"). Real
# caller as of this audit: dv_harness/engine.py's run_stage() calls RouteResolver.resolve(node, protocol_decision=...) before every LLM call, feeding agent_profile.load_agent_profile(), SkillResolver.resolve(), MultiAgentOrchestrator.delegate() and the adapter's --agent flag.
# Original NOTICE text, now superseded: "this module is NOT invoked by any
# executing code path in dv_harness/ or .claude/agents/*.md as of this audit
# -- it is standalone/orphaned code."
#
# NOTICE (2026-09-04, AI-mechanism re-audit gap #4 "Route & Skill Resolver"):
# resolve() previously took only `node` and returned node.route/node.agent/
# node.skills verbatim, so a stage's skill set was 100% determined by the
# design-time table in .dv-harness/graph/main_graph.json -- byte-for-byte
# identical no matter what protocol/evidence THIS run carried. The real
# evidence-driven decision (protocol_router.resolve_protocol(), fed by
# engine._protocol_router_evidence()'s live user_goal/failing test/git-modified
# files/INTAKE subsystem boundary) already existed and already fired, but its
# result was stored beside the static answer as audit-only telemetry and never
# read back into it. resolve() now accepts that decision and folds the
# protocol's real skills into the returned `skills`, which run_stage() then
# resolves to paths and delegates -- i.e. the classification is now an INPUT
# to routing, the same "classify from real evidence, then look up" shape
# question_queue.route_owner() and connectivity.py's T1-T4 tiering use.
from .protocol_router import protocol_skill_routes

DEFAULT_ROUTES={'analysis-route':'analysis-agent','implementation-route':'implementation-agent','build-route':'build-agent','debug-route':'debug-agent','regression-route':'regression-agent','review-route':'review-agent','lead-route':'dv-lead'}

# A graph node that declares the `protocol-router` skill has, by its own
# design-time declaration, said "which skills I actually need depends on which
# protocol this run is about" -- .claude/skills/CORE/protocol-router/SKILL.md
# is precisely the routing table resolve_protocol() executes, and its
# "Profile/VIP-Lookup Binding" section instructs that stage to go read the
# resolved protocol's profile/vip-lookup skills. Those are exactly the nodes
# whose skill list is widened here (DISCOVERY and PROTOCOL_CAPABILITY in the
# current main_graph.json; PROTOCOL_CAPABILITY is also where the real
# protocol_profile_binding_gate checks that those same skills were consulted).
# Deliberately NOT every node: appending `USB/usb-profile` to GIT_SYNC or
# SIGNOFF would be noise, not routing.
PROTOCOL_SENSITIVE_SKILLS=frozenset({'protocol-router'})

class RouteResolver:
 def __init__(self,root=None):
  # `root` is only needed to read .dv-harness/builder/protocol_builder_registry.json
  # for the resolved protocol's profile/vip-lookup skills; RouteResolver(None)
  # still resolves the static route/agent/skills exactly as before.
  self.root=root
 def _is_protocol_sensitive(self,node):
  return bool(PROTOCOL_SENSITIVE_SKILLS.intersection(node.skills or []))
 def resolve(self,node,protocol_decision=None):
  """Resolves route/agent/skills for one graph node.

  `protocol_decision` is protocol_router.resolve_protocol()'s real output for
  THIS run. When it resolved AND this node declared itself protocol-sensitive
  (see PROTOCOL_SENSITIVE_SKILLS), the protocol's real skills are appended to
  the node's static ones -- so two runs of the SAME node with different
  evidence genuinely get different skills. `route`/`agent` stay the static
  table's answer on purpose: resolve_protocol()'s `route` is a SKILL route
  (`USB/usb-profile`), not a graph route, and no evidence source anywhere in
  this harness maps a protocol onto a different agent -- inventing one would
  be fabrication, not routing.

  Static skills always come first and are never dropped; the returned
  `static_skills` preserves the pre-fold list so a caller can tell exactly
  what the dynamic decision added."""
  static_skills=list(node.skills or [])
  skills=list(static_skills)
  added_routes=[]
  if self._is_protocol_sensitive(node):
   for route in protocol_skill_routes(self.root,protocol_decision):
    name=route.rsplit('/',1)[-1]
    if name not in skills:
     skills.append(name);added_routes.append(route)
  return {'route':node.route,'agent':node.agent or DEFAULT_ROUTES.get(node.route),
          'skills':skills,'static_skills':static_skills,
          'protocol_skill_routes':added_routes}
