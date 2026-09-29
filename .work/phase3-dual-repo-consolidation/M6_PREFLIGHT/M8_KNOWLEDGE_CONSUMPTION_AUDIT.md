# M8 Multi-Agent Knowledge Consumption Audit (CAP-M8-MAKC-001)

Preflight evidence only -- FIND, not FIX. No production code touched.
Real 5-tier trace (`dv_harness/memory.py:11`, `MEMORY_LEVELS=["working",
"job","project","engineering","organizational"]`), independently
verified this task via direct source reading and one existing passing
test, not assumed.

## Producer -> persistence -> discovery -> retrieval -> consumer -> decision/action -> evidence, per tier

| Tier | Writer (file:line) | Reader (file:line) | Cross-agent consumption |
|---|---|---|---|
| WORKING | `react.py:175-176` (`route_and_store`, every stage attempt) | `capability_evolution.py:987-992`, `prior_decision_reevaluation.py:404` | PARTIAL -- cross-run, not cross-agent-identity; audit-trail display, not a fresh decision input |
| JOB | `lsf_client.py:1222-1223`; `engine.py:3656` (`_record_debug_attempt_job_memory`, called `5478` on FAILURE_RECOVERY/RE_AUDIT) | `lsf_client.py:675-686` (display-only, explicitly documented never decision-influencing); **`capability_evolution.py:1585-1610` `repeated_unresolved_failure_patterns()`** (real decision input) | YES, bounded -- drives a real `CapabilityEvolutionCandidate` at `engine.py:5489`, capped at `DISCOVERED`, never autonomously past a human |
| PROJECT | `engine.py:3189` (`_promote_project_topology_knowledge`, called `5324` on PASS); `self_tuning.py:449` | `engine.py:4467` (`MemoryRetriever.search()`, no tier filter, single shared `.dv-harness/memory/index.json`) -> `relevant_memory` injected into the real stage prompt (`engine.py:4526`/`5596`; `prompts.py:2996-3006`) | **YES, with a real passing proof**: `test_engine_gates_and_routing.py:1107-1143` (`test_run_stage_retrieves_relevant_memory_into_the_prompt`) -- seeds a record, runs a DIFFERENT stage, asserts the seeded title appears verbatim in the prompt handed to the adapter |
| ENGINEERING | `engine.py:1944` (`_promote_experience_knowledge`, called `5313` on PASS); `engine.py:3434` (`_promote_verified_fix_knowledge`, called `5328` on PASS) | same cross-tier `engine.py:4467` retrieval; plus `gates.py:951-1052` `_ccl_reuse_verified()` wired into a real gate skip-decision at `gates.py:1052`; best-effort pushed to the remote Knowledge Center (`memory_router.py:137` `_SHAREABLE_DESTINATIONS`), retrievable cross-project via `engine.py:4472-4489` (FAILURE_RECOVERY/RE_AUDIT only) | YES structurally for same-project reuse (same mechanism as Project tier); genuine cross-project/cross-user path exists in code but is opt-in, off by default (see gap below) |
| ORGANIZATIONAL | `memory_router.py:988` `promote_to_organizational()`, called from `engine.py:3547` (itself called `2001`/`3466`) | `OrganizationalMemoryStore` (`memory.py:1106-1154`) -- **no local file backing at all**, pure passthrough to `KnowledgeCenterClient`; only real caller found (`dashboard.py:8482`) checks `.configured()` only, never reads content | **NO in practice today** -- `KnowledgeCenterClient.configured()` requires `cfg["enabled"]` and `cfg["remote_root"]`, and `remote_root` defaults to `""` (`config.py:133`); every write/read is a silent no-op absent explicit remote KC setup, none found configured in this repo |

## `route_and_store()` real production caller: EXISTS (real, tested, PASS-gated)

Multiple real call sites, all inside `engine.py`'s `run_stage()` control
flow (lines 1944, 3189, 3258, 3434, 3547, 3656) -- not dead code, not
test-only.

**Reconciliation against older background evidence (Evidence Truth
Rule)**: `CANONICAL_CAPABILITY_SUPERSET_MATRIX.md:72` (an M3-era
document) states *"`memory_router.route_and_store()` has no caller in
the prompt/gate pipeline"*. Current `engine.py` evidence directly
contradicts a literal reading of that sentence. Two readings reconciled:
(a) the M3-era audit predates these real call sites (most likely, given
this session's own extensive KC-harvest work landed well after M3), or
(b) "the prompt/gate pipeline" narrowly means `gates.py`'s `STAGE_GATES`/
`prompts.py`'s `STAGE_INSTRUCTIONS` machinery specifically, distinct from
`engine.py`'s own post-verdict side effects -- a narrower claim that
could still be literally true. Either way, **current evidence governs**:
`route_and_store()` DOES have real, tested production callers today. The
OTHER half of the same M3-era finding -- `promotion_chain_audit_gate.py`'s
hard-required `EXPERIENCE_READY` event -- remains independently confirmed
real and broken (see `M8_EXPERIENCE_LOOP_TRACE.md`); these are two
distinct mechanisms and must not be conflated.

## Knowledge stored vs. knowledge consumed

**Verdict: PARTIAL, genuinely tier-dependent -- not "stored only" and not
"fully consumed."**

1. Strongest CONSUMED evidence: `test_run_stage_retrieves_relevant_
   memory_into_the_prompt` -- a real, passing, code-level proof a
   Project-tier write is later retrieved by a DIFFERENT stage's prompt-
   build and appears verbatim in the text handed to the agent.
2. Strongest CONSUMED evidence #2: `repeated_unresolved_failure_
   patterns()` reading Job Memory across >=2 independent runs, driving a
   real `CapabilityEvolutionCandidate` write -- a genuine cross-run
   decision, capped at `DISCOVERED` pending human approval (never
   silently autonomous).
3. Strongest STORED-ONLY-IN-PRACTICE evidence: Organizational Memory's
   sole persistence path is the remote Knowledge Center, disabled by
   default -- the one tier explicitly meant for true cross-user/cross-
   project consumption is architecturally real but operationally inert
   absent explicit remote setup, none found configured here.

## Multi-agent reliance mechanism: mixed, and the two halves diverge sharply

- `.claude/agents/memory-agent.md` is a real, EXPLICIT Canonical
  contract: names the real API (`route_and_store()`, `promote_to_
  organizational()`, `MemoryGC`, `MemoryRetriever`/`CornerCaseLibrary.
  search()`), explicitly forbids hand-editing memory files (bypasses
  dedup/confirmation/promotion gates).
- `.claude/agents/debug-agent.md:121-122` -- the agent that actually
  performs real debug/RCA work -- has only VAGUE prose guidance ("may
  search similar verified memory before triage"), with NO named API, no
  CLI invocation, no mandated retrieval call. Its declared tools (`Read,
  Grep, Glob, PowerShell`) permit it to either use the real `memory_cli`/
  `MemoryRetriever` path, OR simply `Grep`/`Read` raw JSON under
  `.dv-harness/memory/**` directly -- the exact "shared filesystem +
  model intuition" failure mode the dispatch asked to distinguish. No
  evidence found that `debug-agent.md` delegates to `memory-agent` or
  names the real retrieval API.
- Distinct from, and must not be conflated with: the Claude-Code-native
  Agent/Task-tool subagent dispatch mechanism this very Preflight uses
  (a separate, harness-level mechanism) -- only `engine.py`'s own
  internal `run_stage()` -> `delegate()` -> adapter path is what the
  memory-injection-into-prompt evidence above actually covers.

## CAP-M8-MAKC-001 real gaps (evidence-cited, not fixed)

1. Organizational Memory has zero local persistence and is a silent
   no-op without explicit, unconfigured-by-default remote Knowledge
   Center setup (`config.py:133`, `knowledge_center.py:218-219`) -- the
   one tier meant to prove genuine cross-agent/cross-session/cross-
   project consumption cannot be verified operating at all today.
2. `debug-agent.md`'s memory-retrieval instruction is prose-only, unlike
   `memory-agent.md`'s explicit contract -- a real risk that a dispatched
   debug-agent reads raw memory files instead of the redaction/ranking-
   aware retrieval path; not confirmed either way by static evidence
   (depends on the executing model's own runtime choice each time).
3. The M3-era `CANONICAL_CAPABILITY_SUPERSET_MATRIX.md` citation behind
   CAP-M8-MAKC-001's own `NOT_VERIFIED` classification needs
   reconciliation -- current `engine.py` evidence contradicts a literal
   reading of its "no caller" claim (see reconciliation above).
4. Job Memory's only "reporting" reader is explicitly non-decision-
   influencing by design -- most Job Memory reads are display, not
   consumption; only the repeated-failure path is real consumption.
5. `promotion_chain_audit_gate.py`'s `EXPERIENCE_READY` event remains
   unemitted anywhere in `engine.py`/`gates.py` -- confirmed independently
   by this audit too, consistent with `M8_EXPERIENCE_LOOP_TRACE.md`.

## Verdict

`CAP-M8-MAKC-001` status: **PARTIAL, not simply `NOT_VERIFIED`** -- this
Preflight pass constitutes the first real audit of this capability (the
Capability Matrix's own `BLOCKER` text, "out of M3's leaf-capability
scope; not re-audited this wave either," is now stale and should be
updated when M8 Implementation reconciles the Capability Matrix). Real,
tested, cross-agent-proven consumption exists for 2 of 5 tiers (Project,
partially Job); Organizational tier is architecturally real but
operationally inert; the multi-agent reliance mechanism is a genuine
Canonical contract for one real agent profile (`memory-agent`) and prose-
only for another (`debug-agent`), a real, disclosed inconsistency.
