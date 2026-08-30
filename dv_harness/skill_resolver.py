# NOTICE (superseded 2026-08-28, 12-claim re-audit): the original industrial-
# grade-audit NOTICE below claimed this module was "NOT invoked by any
# executing code path" -- that is now FALSE, per CLAUDE.md's own Evidence
# Truth Rule ("current evidence wins and this file must be updated"). Real
# caller as of this audit: dv_harness/engine.py's run_stage() calls SkillResolver.resolve(node.skills) before every LLM call, folded into the prompt's plan section.
# Original NOTICE text, now superseded: "this module is NOT invoked by any
# executing code path in dv_harness/ or .claude/agents/*.md as of this audit
# -- it is standalone/orphaned code."
from pathlib import Path
class SkillResolver:
 def __init__(self,root):
  self.index={p.parent.name:str(p.relative_to(root)) for p in (Path(root)/'.claude'/'skills').rglob('SKILL.md')}
 def resolve(self,names):return [{'skill':n,'path':self.index.get(n),'found':n in self.index} for n in names]
