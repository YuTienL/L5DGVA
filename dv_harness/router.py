# NOTICE (superseded 2026-08-28, 12-claim re-audit): the original industrial-
# grade-audit NOTICE below claimed this module was "NOT invoked by any
# executing code path" -- that is now FALSE, per CLAUDE.md's own Evidence
# Truth Rule ("current evidence wins and this file must be updated"). Real
# caller as of this audit: dv_harness/engine.py's run_stage() calls RouteResolver.resolve(node) before every LLM call, feeding agent_profile.load_agent_profile() and the adapter's --agent flag.
# Original NOTICE text, now superseded: "this module is NOT invoked by any
# executing code path in dv_harness/ or .claude/agents/*.md as of this audit
# -- it is standalone/orphaned code."
DEFAULT_ROUTES={'analysis-route':'analysis-agent','implementation-route':'implementation-agent','build-route':'build-agent','debug-route':'debug-agent','regression-route':'regression-agent','review-route':'review-agent','lead-route':'dv-lead'}
class RouteResolver:
 def resolve(self,node):return {'route':node.route,'agent':node.agent or DEFAULT_ROUTES.get(node.route),'skills':node.skills}
