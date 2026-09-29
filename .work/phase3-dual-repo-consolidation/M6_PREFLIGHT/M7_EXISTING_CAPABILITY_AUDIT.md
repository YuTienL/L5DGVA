# M7 Preflight -- Existing Capability Audit

Prime Directive V2 CONNECT_BEFORE_EXPAND: reconciles all 14 existing
`PRIMARY_OWNER_WAVE = M7` rows in `MASTER_CAPABILITY_STATUS_MATRIX.csv`
(fresh `csv.DictReader` parse, not assumed), re-verifies the prior M4.5
multi-model-orchestration research (`M4_5_MULTI_MODEL_ORCHESTRATION_
AUDIT.md`, `M4_5_CHATGPT_INTEGRATION_AUDIT.md`, `M4_5_CODEX_INTEGRATION_
AUDIT.md`) against CURRENT canonical state (not re-derived from scratch),
and surfaces one real foundation that prior audit did not know to look
for: `dv_harness/model_agent_tool_router.py`.

## Prior M4.5 research re-verified fresh against current canonical

| Finding (M4.5, dated) | Re-verification method (this pass) | Still true? |
|---|---|---|
| Zero ChatGPT reference anywhere in canonical `dv_harness/`/`tools/` | `grep -rli "chatgpt" --include="*.py" .` (whole repo) | **YES, still 0 hits.** |
| Zero `codex` shell-out/API call anywhere in canonical | `grep -rli "codex" dv_harness/*.py` | **YES.** Only 2 files mention the literal word "codex," both as DATA (directive-text citations of the L5-DGVA contract's own `"V21-EXEC-018 Codex package"` step name in `l5dgva_directive_registry.py`/`l5dgva_workitem_projection.py`) -- not integration code. |
| The 3 Parent-side Codex package-assembly modules never migrated to canonical | `ls dv_harness/codex_kc_handoff_package.py dv_harness/codex_full_contract_review_package.py dv_harness/l5dgva_pre_codex_review_truth.py` | **Still true** -- none exist in canonical. (A DIFFERENT, canonical-native module happens to share a similar name pattern for an unrelated purpose -- `l5dgva_pre_codex_review_truth.py` was never actually built here; the CANONICAL module inventory has no such file.) |
| `stage_profile.py`/`stage_profile_report.py` real, Claude-only token telemetry | `ls dv_harness/stage_profile.py dv_harness/stage_profile_report.py` | **Confirmed present in canonical** (previously "presumed canonical, same lineage" in the M4.5 row -- upgraded to CONFIRMED this pass). |
| `dv_harness/governance_registry.py` (task-scoped governance retrieval) | `ls dv_harness/governance_registry.py` | **Confirmed present.** |
| No reusable model/task router existed | `find dv_harness -iname "*router*"` | **Partially superseded** -- see the new finding below. |

## New finding this pass: `dv_harness/model_agent_tool_router.py`

A real, tested, importable router (2026-09-06, post-dates the M4.5
audit) exists with almost exactly the SHAPE section 6 asks for: a
documented per-task-type fallback chain, a `RoutingDecision` dataclass
(`agent`/`model`/`tool` sub-resolutions), a worst-wins composite verdict
(`ROUTED` / `ROUTED_WITH_FALLBACK` / `BLOCKED_NEEDS_HUMAN_DECISION`), and
a machine-readable `routing_criteria()` policy dump.

**What it actually routes (read precisely, not assumed from the name)**:
task-type -> Claude Code's OWN internal sub-agent (`dv-lead`,
`analysis-agent`, `implementation-agent`, ...), that agent's OWN declared
`model:` frontmatter value (`inherit`, or a specific Claude model ID --
never a non-Claude provider), and that agent's OWN declared `tools:`
scope. **It does not, and was never designed to, route among
Claude/Codex/ChatGPT as separate PROVIDERS** -- its `model` concept is
entirely intra-Claude-agent-ecosystem.

**Scope, per its own module docstring**: "a REACHED capability (a real
importable/CLI caller exists), not a WIRED one" -- not called from
`engine.py`'s `run_stage()`.

**Classification**: `FOUNDATION_AVAILABLE` for the M7 Model Task
Router's own STRUCTURAL PATTERN (fallback chains, worst-wins verdict,
documented-not-implicit criteria, `to_dict()`-serializable decisions) --
reuse this design, do not reinvent a second routing-decision shape.
`IMPLEMENTATION_MISSING` for the actual cross-PROVIDER dimension (Claude
vs. Codex vs. ChatGPT) this specific module was never built to answer.

## Full reconciliation of the 14 existing M7-owned rows

| CAPABILITY_ID | Name | Current state (re-verified) | Classification |
|---|---|---|---|
| `CAP-M4.5-005` | CHATGPT_PLANNING_OFFLOAD | `IMPLEMENTED=YES (Parent only)`, `WIRED=NO`, `CONSUMED=NO` -- re-confirmed unchanged, zero ChatGPT code in canonical | `IMPLEMENTATION_MISSING` (canonical has none of this; Parent's own version is also a dead-end pipeline, never completed a round-trip) |
| `CAP-M4.5-006` | CODEX_REVIEW_OFFLOAD (3 self-blocking package modules) | Re-confirmed: not migrated to canonical; what the Parent-side modules do is refuse to fabricate a review, not perform one | `IMPLEMENTATION_MISSING` (canonical) / `OUTPUT_CONSUMPTION_MISSING` (even in Parent, nothing CONSUMES a real review because none is ever produced) |
| `CAP-M4.5-007` | STRUCTURED_AGENT_HANDOFF (review-handoff schema) | Prose schema exists (`CODEX_L5_DGVA_Knowledge_Brain_Independent_Adversarial_Review_Prompt_v19.md`), zero real `issue.md` instance produced, ever, on either tree | `WIRING_MISSING` -- the schema itself is a real, reusable design (see `M7_STRUCTURED_HANDOFF_CONTRACT.md`), never operationalized into an actual producer/consumer |
| `CAP-M4.5-008` | CONTEXT_DISTILLATION (multi-model-handoff-specific) | Real distillers exist for DUT/VIP content (unrelated purpose); none for ChatGPT/Codex handoff content specifically | `IMPLEMENTATION_MISSING` (the multi-model-specific distiller does not exist; the DUT/VIP distillers are a real, reusable PATTERN to follow, not a ready-made solution) |
| `CAP-M4.5-009` | SESSION_RESUME | `UNKNOWN` across the board in the M4.5 row (out of that audit's own search scope) | Re-investigated this pass: `dv_harness/agent_checkpoint_check.py` (real, CLI-wired: `dv-harness agent-checkpoint-check`, `check_resume_state_artifact()`) is a real session/checkpoint-resume primitive already in canonical -- `FOUNDATION_AVAILABLE`, closing the prior `UNKNOWN` |
| `CAP-M4.5-010` | TOKEN_USAGE_OBSERVABILITY (Claude-only) | Confirmed present in canonical this pass (`stage_profile.py`/`stage_profile_report.py`), real per-stage token counts, never combined with any multi-model handoff | `FOUNDATION_AVAILABLE` (Claude-side telemetry is real) / `MEASUREMENT_MISSING` (no cross-model comparison exists) |
| `CAP-POOL-007` | autonomous_resume_next_action_arbitration.py + independent_work_continuation.py | Re-confirmed absent from canonical (`ls` -> not found); its own dependency (`inference.arbitrate_next_best_evidence`) also confirmed absent from canonical's real `inference.py` | `IMPLEMENTATION_MISSING`, blocked on a dependency this project's own `inference.py` never carried over (a real, disclosed prior migration gap, not an M7 defect) |
| `CAP-M4.5-012` | CLAUDE_FOCUSED_IMPLEMENTATION | The Claude-CLI-does-repo-local-implementation role is real and IS this project's own normal operating mode (every task this session performed IS this role) -- but no AUTOMATED hand-off TO or FROM it exists (a human/dispatcher always supplies the task, always reads the result) | `EXISTING_REAL_USE` for the role itself; `WIRING_MISSING` for automated hand-off in/out |
| `CAP-M4.5-013` | TOKEN_EFFICIENT_MULTI_MODEL_ORCHESTRATION (composite) | Composite of the 8 sub-findings above -- re-confirmed `NOT_PRESENT` as a working automated mechanism | `IMPLEMENTATION_MISSING` (composite) |
| `CAP-M14-004` | BENCHMARK_TELEMETRY_FOUNDATION | Confirmed still absent (`NO` across every column) | `IMPLEMENTATION_MISSING`, correctly owned by M14 not M7 per `MASTER_PROGRAM_STATUS.md`'s own existing "M7 measures orchestration efficiency, not Junior-vs-L5DGVA productivity; M14 remains after M13" distinction -- **not pulled into M7's own scope by this preflight**, listed here only because the Master matrix's own `PRIMARY_OWNER_WAVE` column currently says M7; flagged as a bookkeeping question for a human, not silently reassigned |
| `CAP-M3-002` | debug_evidence_behavioral_firewall_gate.py | `IMPLEMENTED=YES`, `WIRED=NO`, no caller yet | Unrelated to multi-model orchestration -- a debug-governance capability mis-filed under M7's own wave column (pre-existing, not created by this preflight) |
| `CAP-M3-003` | l5dgva_v5_ss86_understanding_plan_contradiction_taxonomy.py | same shape | Unrelated to multi-model orchestration, same mis-filing |
| `CAP-M3-004` | diagnostic_bound_compatibility.py | same shape | Unrelated to multi-model orchestration, same mis-filing |
| `CAP-M3-005` | coverage_hole_generation_candidate_queue.py | `IMPLEMENTED=YES`, not wired into coverage-closure flow | Unrelated to multi-model orchestration, same mis-filing |

**Disclosed, not silently fixed**: `CAP-M3-002/003/004/005` and
`CAP-M14-004` carry `PRIMARY_OWNER_WAVE = M7` in the CURRENT Master
matrix but have NOTHING to do with multi-model orchestration (they are
debug-governance/benchmark capabilities). Per this task's own instruction
("Do not add capability rows merely to make the plan look complete" --
the mirror-image error would be silently reassigning or dropping rows to
make the plan look TIGHTER), these are flagged as a likely pre-existing
Master-matrix bookkeeping mis-tag for a human to correct, not
reinterpreted or moved by this preflight task itself.

## Summary counts (feeds the Final Report)

```
M7_CAPABILITIES_REVIEWED = 14 (all pre-existing M7-owned rows)
  + 1 newly-discovered foundation (model_agent_tool_router.py, not yet
    a Master-matrix row -- see M7_MODEL_ROLE_MATRIX.csv)
M7_FOUNDATIONS_AVAILABLE = 4
  (model_agent_tool_router.py's routing PATTERN; agent_checkpoint_
  check.py for session resume; stage_profile.py/stage_profile_report.py
  for Claude-side token telemetry; governance_registry.py for
  task-scoped governance retrieval)
M7_IMPLEMENTATION_GAPS = 6
  (CHATGPT_PLANNING_OFFLOAD; CODEX_REVIEW_OFFLOAD in canonical;
  CONTEXT_DISTILLATION for multi-model content; autonomous_resume_
  next_action_arbitration.py's own dependency chain; TOKEN_EFFICIENT_
  MULTI_MODEL_ORCHESTRATION composite; the cross-provider dimension of
  model_agent_tool_router.py)
M7_WIRING_GAPS = 2
  (STRUCTURED_AGENT_HANDOFF schema never operationalized;
  CLAUDE_FOCUSED_IMPLEMENTATION has no automated hand-off in/out)
M7_OUTPUT_CONSUMPTION_GAPS = 1
  (CODEX_REVIEW_OFFLOAD: even where wired/triggered, nothing is ever
  actually consumed because nothing real is ever produced)
M7_MEASUREMENT_GAPS = 1
  (no cross-model token/context comparison exists)
M7_HUMAN_DECISIONS_REQUIRED = 1
  (the CAP-M3-*/CAP-M14-004 Master-matrix wave-mis-tag question)
```
