# NOTICE (superseded 2026-08-28, 12-claim re-audit): the original industrial-
# grade-audit NOTICE below claimed this module was "NOT invoked by any
# executing code path" -- that is now FALSE, per CLAUDE.md's own Evidence
# Truth Rule ("current evidence wins and this file must be updated"). Real
# caller as of this audit: dv_harness/engine.py's run_stage() calls ReactRecorder.record(...) once per stage attempt, after every adapter call.
# Original NOTICE text, now superseded: "this module is NOT invoked by any
# executing code path in dv_harness/ or .claude/agents/*.md as of this audit
# -- it is standalone/orphaned code."
#
# record_reflection() (2026-08-29, genuine-react-loop design pass): additive,
# non-breaking method -- record() above keeps its exact prior signature/file
# shape/call site (still ONE call per outer stage attempt). This is the
# separate, ONE-CALL-PER-INNER-ITERATION record react_loop.InnerReactLoop
# writes for its own Reason->Act->Observe->Reflect turns, so a single outer
# attempt that ran the inner loop 2-3 times leaves both an iteration_NNN.json
# (the outer, ReactRecorder.record() summary) AND one reflect_NNN.json per
# inner turn under the same node/attempt directory -- a full audit trail of
# what menu was actually offered and which real option was actually chosen,
# without ever persisting free-form chain-of-thought (only the structured
# conclusion/chosen_option_id/params fields exist in either file).
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
class ReactRecorder:
 def __init__(self,root):self.root=Path(root)/'.dv-harness'/'react';self.root.mkdir(parents=True,exist_ok=True)
 def record(self,node,iteration,reason_summary,action,tool,observation,evidence,confidence,next_action):
  d=self.root/node;d.mkdir(parents=True,exist_ok=True);r={'iteration':iteration,'node':node,'reason_summary':reason_summary,'action':action,'tool':tool,'observation':observation,'evidence':evidence,'confidence':confidence,'next_action':next_action};(d/f'iteration_{iteration:03d}.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');return r

 def record_reflection(self, node, attempt, inner_iter, signatures, menu, decision):
  """Persists one inner-loop turn: the real GateSignature list the reflection
  call actually observed, the real constrained MenuOption list it was
  actually offered, and the ReactDecision it actually returned -- accepts
  either dataclass instances (dv_harness.react_loop.GateSignature/MenuOption/
  ReactDecision) or plain dicts, so this module never needs to import
  react_loop (which itself imports this module for observability -- keeping
  the dependency one-directional)."""
  def _plain(x):
   return asdict(x) if is_dataclass(x) else x
  d = self.root / node / f'attempt_{attempt:03d}'
  d.mkdir(parents=True, exist_ok=True)
  r = {
   'signatures': [_plain(s) for s in signatures],
   'menu': [_plain(m) for m in menu],
   'decision': _plain(decision),
  }
  (d / f'reflect_{inner_iter:03d}.json').write_text(
   json.dumps(r, ensure_ascii=False, indent=2), encoding='utf-8')
  return r
