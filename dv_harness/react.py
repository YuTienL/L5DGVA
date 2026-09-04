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
#
# WORKING-MEMORY-TIER CROSS-REFERENCE (memory-engine-schema-completion audit,
# 2026-09-01): CLAUDE.md/the memory-pyramid design describe Working Memory's
# contract as a hypothesis/evidence/next-action record -- record()'s own
# reason_summary/evidence/next_action parameters below ARE that real content,
# produced once per outer stage attempt, but until now it lived ONLY under
# `.dv-harness/react/<node>/iteration_NNN.json`, completely disconnected from
# memory.py's WorkingMemoryStore (`.dv-harness/memory/working/`) -- the store
# a MemoryRetriever.search() caller actually queries for "working memory".
# The two were never reconciled.
#
# RULING: rather than teaching MemoryRetriever.search() to ALSO reach into
# react/'s file layout at read time (a second, parallel read path baked into
# memory.py that would have to know this module's private directory/filename
# shape), record() now pushes a compact projection of the SAME real step
# into the working tier through the existing memory_router.route_and_store()
# entry point at the moment it is produced -- one write path, one real
# schema, and every existing WorkingMemoryStore/MemoryRetriever reader picks
# it up for free with zero changes to memory.py's read side. This was judged
# the cleaner of the two options the task offered: memory_router.py already
# depends on nothing in react.py/react_loop.py (no cycle risk), and every
# other reconciliation of this shape in this codebase (engine.py's
# _promote_experience_knowledge/_promote_project_topology_knowledge) is
# already a write-time push through the SAME route_and_store() function,
# not a read-time cross-store search. record_reflection()'s inner-loop turns
# (signatures/menu/decision) are a structurally different shape -- not a
# hypothesis/evidence/next-action record -- and are deliberately NOT
# additionally pushed here; they stay real, inspectable evidence under
# react/ only.
#
# GAP + CONFIDENCE_DETAIL (2026-09-04, plan-and-execute/ReAct gap closure):
# CLAUDE.md's Engineering Memory Policy names the Working Memory contract as
# the full Hypothesis -> Evidence -> Confidence -> Gap -> Next-Best-Action
# chain, computed by dv_harness.inference.score_confidence()/identify_gap()/
# next_best_action(). `hypothesis`/`evidence`/`next_action`/`confidence`
# already existed; `gap` had no field at all and `confidence` arrived from a
# hardcoded status->string map in engine.py rather than from the real scorer.
# record() now additionally accepts `gap` (identify_gap()'s real list of
# still-missing evidence categories for this attempt) and `confidence_detail`
# (the exact dict score_confidence() returned -- level/score/
# capped_by_counter_evidence), persisting both into iteration_NNN.json AND
# the Working Memory projection, so a reader can trace the confidence string
# back to the real score that produced it. Both stay OPTIONAL and default to
# []/None: every pre-existing caller/test that omits them is unaffected, and
# a caller with no real gate signatures to derive them from (e.g. a bare
# unit-test record) must not be forced to invent a gap it cannot compute.
# engine.py's _react_step_inference() is the real production supplier.
#
# MEMORY_CONTEXT (2026-09-04, gap-close-obsidian-memory phase 13+14): the
# memory a stage attempt ACTUALLY consulted -- engine.run_stage()'s
# `relevant_memory` (MemoryRetriever), `vault_related_cases`
# (memory_vault.search_related_memory_for_debug) and `kc_search_results`
# (the shared Knowledge Center) -- was built fresh inside
# _gather_stage_context() on every call, folded into the prompt string, and
# then discarded. Nothing persisted it, so nothing could later answer "which
# prior knowledge was in play when this hypothesis was formed". Concretely,
# session_snapshot.save_session() had to RE-RUN a MemoryRetriever.search()
# at save time and label the result `related_memory`, which can differ from
# what the stage really cited. record() now accepts `memory_context` -- a
# REFERENCES-ONLY projection (build_memory_context_references() below: ids/
# titles/paths/scores, never record bodies) -- and persists it into the same
# iteration_NNN.json and Working Memory projection every other field of this
# record already uses, so the snapshot reads the real one instead of guessing.
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path


def build_memory_context_references(relevant_memory=None, kc_search_results=None,
                                    vault_related_cases=None):
 """Compact, references-only projection of the three memory sources a stage
 attempt consulted. Deliberately never carries a record BODY: local hits
 keep memory_id/level/title/root_cause/confidence (the exact five keys
 session_snapshot's own `related_memory` reference shape already uses, so a
 recorded context and a recomputed one are interchangeable to every
 reader), vault/evidence-DB cases keep note_id/path/protocol/score/source,
 and shared Knowledge Center hits keep memory_id/title/protocol. A caller
 that consulted nothing gets an empty dict, not a dict of empty lists --
 "no memory was in play" and "this stage predates the field" then stay
 distinguishable at read time.

 A vault case from the Evidence Layer's DuckDB store (source="evidence_db",
 see memory_vault.search_evidence_db_failure_signatures) carries a
 signature_key rather than a note_id/path; both shapes are projected here
 rather than only the Markdown-note one, so an evidence-DB match is not
 silently dropped from the record."""
 def _local(m):
  m = m or {}
  return {"memory_id": m.get("memory_id"), "level": m.get("level"), "title": m.get("title"),
          "root_cause": m.get("root_cause"), "confidence": m.get("confidence")}

 def _vault(c):
  c = c or {}
  return {"note_id": c.get("note_id") or c.get("signature_key"),
          "path": c.get("path"),
          "protocol": (c.get("frontmatter") or {}).get("protocol") if isinstance(c.get("frontmatter"), dict)
                      else c.get("protocol"),
          "score": c.get("score"), "source": c.get("source")}

 def _kc(r):
  r = r or {}
  return {"memory_id": r.get("memory_id"), "title": r.get("title"), "protocol": r.get("protocol")}

 out = {}
 if relevant_memory:
  out["related_memory"] = [_local(m) for m in relevant_memory]
 if vault_related_cases:
  out["vault_related_cases"] = [_vault(c) for c in vault_related_cases]
 if kc_search_results:
  out["kc_search_results"] = [_kc(r) for r in kc_search_results]
 return out


class ReactRecorder:
 def __init__(self,root):
  self.project_root=Path(root)
  self.root=self.project_root/'.dv-harness'/'react';self.root.mkdir(parents=True,exist_ok=True)
 def record(self,node,iteration,reason_summary,action,tool,observation,evidence,confidence,next_action,gap=None,confidence_detail=None,memory_context=None):
  d=self.root/node;d.mkdir(parents=True,exist_ok=True);r={'iteration':iteration,'node':node,'reason_summary':reason_summary,'action':action,'tool':tool,'observation':observation,'evidence':evidence,'confidence':confidence,'next_action':next_action,'gap':list(gap) if gap is not None else [],'confidence_detail':confidence_detail if isinstance(confidence_detail,dict) else None,'memory_context':memory_context if isinstance(memory_context,dict) else None};(d/f'iteration_{iteration:03d}.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
  self._write_working_memory_tier_record(node, iteration, reason_summary, evidence, confidence, next_action,
                                          gap=r['gap'], confidence_detail=r['confidence_detail'],
                                          memory_context=r['memory_context'])
  return r

 def _write_working_memory_tier_record(self, node, iteration, reason_summary, evidence, confidence, next_action,
                                        gap=None, confidence_detail=None, memory_context=None):
  """Best-effort push of this same record() call's real hypothesis/evidence/
  next-action content into memory.py's WorkingMemoryStore tier, via the
  real memory_router.route_and_store() entry point -- see the module-level
  RULING comment above record() for why this exists and why it lives here
  rather than as a MemoryRetriever.search()-side reconciliation. `memory_id`
  is deterministic on (node, iteration) -- the same pair record() already
  uses as the on-disk iteration_NNN.json key -- so MemoryStore.add()'s
  upsert-by-memory_id behavior naturally replaces-in-place rather than
  duplicating if this exact stage attempt is ever recorded twice, mirroring
  lsf_client._write_job_tier_memory_on_terminal_reconcile's identical
  deterministic-id idempotency rationale. A persistence failure here must
  never break an already-completed record() call -- local import plus a
  bare try/except, the same pattern engine.py's _promote_* methods use for
  every other route_and_store() call site."""
  record = {
   "memory_id": f"WM-REACT-{node}-{iteration:03d}",
   "kind": "react_reasoning_step",
   "node": node,
   "iteration": iteration,
   "hypothesis": reason_summary,
   "evidence": evidence,
   "gap": list(gap) if gap is not None else [],
   "next_action": next_action,
   "confidence": confidence,
   "confidence_detail": confidence_detail if isinstance(confidence_detail, dict) else None,
   "memory_context": memory_context if isinstance(memory_context, dict) else None,
  }
  try:
   from .memory_router import route_and_store
   route_and_store(self.project_root, record)
  except Exception:
   pass

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
