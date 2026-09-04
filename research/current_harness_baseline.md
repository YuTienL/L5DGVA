# current_harness_baseline.md — Stage 0 pre-installation architecture audit

Research-Capability Evolution master prompt, section 4. Generated 2026-09-04
from five parallel read-only audits of this repository, each of which read the
real files and ran real commands; nothing below is transcribed from a summary of
the code. Repo root for every path here is `D:\DV\Task\DV_Agent_Harness_L5\v50`.

**No file was modified to produce this document.** Section 4 forbids modifying
production files during Stage 0, and the audits that fed it were read-only.

## How to read the Status column

| Status | Means |
|---|---|
| `READY` | Real code exists, is reachable, and is exercised by a real test. |
| `PARTIAL` | Real code exists for part of it; the rest is prose an agent is trusted to enact, or exists under a different artifact/path than its own skill documents. |
| `MISSING` | No implementation. Where this was a deliberate decision rather than an oversight, the Known Limitation column says so. |
| `UNKNOWN` | Searched, inconclusive. (Nothing in this baseline is UNKNOWN; every row below reached a conclusion. That is a statement about this audit's coverage, not a claim that the repo has no unknowns.) |

## Counts measured today, not quoted

`python` against the real files on 2026-09-04: **41 graph nodes / 58 edges** in
`.dv-harness/graph/main_graph.json`, declaring 7 routes (`analysis-route`,
`build-route`, `debug-route`, `implementation-route`, `lead-route`,
`regression-route`, `review-route`); **36 stages** in `gates.py`'s `STAGE_GATES`;
**5** memory levels (`working`/`job`/`project`/`engineering`/`organizational`);
**322** `SKILL.md` files, 132 of them directly under `.claude/skills/CORE/`;
**24** agent profiles under `.claude/agents/`; **14** `CREATE TABLE` statements
in `evidence_db.py`; `inference.CONFIDENCE_LEVELS` = `HIGH/MEDIUM/LOW`;
`memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS` = 2.

Several of these differ from numbers the contributing audits recorded hours
earlier the same day (28 stages, 95-line `blackboard.py`, 150+ CORE skills).
That is concurrent work in this repo, not an error in either reading — the
numbers above are the ones re-measured for this document, and any count in a
`.work/` report should be treated as of its own timestamp.

---

## A. Agents, Skills, Routing, Graph

| Capability | Status | Relevant Files | Owning Agent | Owning Skill | Graph Node | Blackboard/State Object | Memory Layer | Evidence Mechanism | Known Limitation | Reuse Potential |
|---|---|---|---|---|---|---|---|---|---|---|
| Route resolution (DV work) | READY | `dv_harness/router.py` `RouteResolver.resolve()`, `DEFAULT_ROUTES`; called by `engine.py` before every LLM call | dispatched per route | `CORE/route-resolver`, `CORE/skill-resolver`, `CORE/protocol-router` | every node's `route` field | `react/<stage>` | — | `test_protocol_router.py` | Free-text classification, no confidence score on the route itself | The one router. A second one is forbidden by section 2.2 and was not built. |
| Research-shaped intent routing | READY | `router.py` `resolve_research_intent()`, `research_route_plan()`; `commands.py` `cmd_research()`; `cli.py` `dv-harness research` | `research-architect` (step 3 of the plan) | reuses `route-resolver`/`skill-resolver` conceptually; no new router skill | **none, deliberately** | — | — | `test_research_intent_routing.py` | Explicit-intent only (`research_intent` field); never guesses a DV debug request into the research route | Shares `DEFAULT_ROUTES` with `resolve()` (one new pair, `research-route` → `research-architect`); not a parallel router. |
| Protocol routing | READY | `dv_harness/protocol_router.py` (318 lines) + `protocol_skill_routes()`; gated at `PROTOCOL_CAPABILITY` by `protocol_profile_binding_gate` | protocol builders | `CORE/protocol-router`, `PROTOCOL_BUILDERS/*` | `PROTOCOL_CAPABILITY` | `env_manifest` | Project | `protocol_profile_binding_gate` | — | Strongest wiring in this scope; nothing research needs to duplicate. |
| `research-architect` agent role | READY (new, justified) | `.claude/agents/research-architect.md` (242 lines); logic in `dv_harness/capability_evolution.py` | `research-architect` | declares `research-ingestion` + 9 existing CORE skills | none — `NOT_DISPATCHED` (`ROSTER.md:153`) | `capability_evolution_candidates` | Working (audit record) | `test_capability_evolution_research_architect.py` | `disallowedTools: Edit, Write` — read-only by construction | 5 candidate pre-existing agents were grepped for `research`; zero matches in all five, so ADD was correct here, not ENHANCE. |
| `research-ingestion` skill | READY (new, justified) | `.claude/skills/research-ingestion/SKILL.md` (209 lines) | `research-architect` invokes it | itself | none | — | Working | `test_research_evidence_card.py`, `test_research_stage1_acceptance_a_g.py` | REACHED (a real CLI/agent caller), not WIRED (no stage invokes it) — the skill says so in those words | Built entirely on `doc_extraction.py`; adds no parser and no second document store. |
| Generic graph stage hosting research | MISSING **by design** | `main_graph.json` (no node declares `research-route`); `gates.py` `DISCOVERY`, `ARCH_DISCOVERY`, `EXPERT_FEEDBACK_LOOP` exist but belong to `analysis-route`/`review-route` | none | none | none | — | — | `test_research_intent_routing.py` asserts `set-stage RESEARCH_CAPABILITY_EVOLUTION` still fails | Research is on-demand/human-invoked, per section 16's "conceptual responsibilities, not mandatory separate nodes" | If Stage 2 ever needs a stage-owning path, `DISCOVERY` and `EXPERT_FEEDBACK_LOOP` are the two reuse candidates — not new-node candidates. |
| CLAUDE.md documents the research capability | READY | `CLAUDE.md` "Research Front Door: `dv-harness research`" + "Research Stage Boundaries" | — | — | — | — | — | `test_research_intent_routing.py` holds the section's claims to the code | Was genuinely MISSING when the Stage-0 audit ran; closed the same day | — |

## B. Blackboard, 5-Level Memory, Evidence, Confidence, Inference, Next-Best-Action

| Capability | Status | Relevant Files | Owning Agent | Owning Skill | Graph Node | Blackboard/State Object | Memory Layer | Evidence Mechanism | Known Limitation | Reuse Potential |
|---|---|---|---|---|---|---|---|---|---|---|
| Blackboard | READY | `dv_harness/blackboard.py` (157 lines): `read`/`write`/`snapshot`, `findings`, `debug_loop_history`, `capability_evolution_candidates` | all | `CORE/verification-blackboard` (8-line pointer) | every node's `blackboard_read`/`blackboard_write` | itself | — | `test_blackboard_subsystem_wiring.py` | The CORE skill doc is a stub; the code is ground truth | The new research topic uses the SAME `{"items": {id: {...}}}` + `upsert_*`/`*_counts` shape as `findings`. No parallel Research Blackboard. |
| 5-level memory hierarchy | READY | `dv_harness/memory.py` (951 lines, 5 tier stores); `MEMORY_LEVELS` = working/job/project/engineering/organizational | `memory-agent` | `CORE/working-memory`, `job-memory`, `project-memory`, `engineering-memory`, `organizational-memory` | written from several stages | — | all 5 | `test_engineering_confirmation_accumulation.py` | — | No sixth store was added for research. Section 12's "reuse the current hierarchy" is satisfied structurally. |
| Memory routing / admission | READY | `memory_router.py` (993 lines): `route_and_store()`, `route_memory()`, `engineering_admission_gate()`, `organizational_admission_gate()`, `promote_to_organizational()`, `ORGANIZATIONAL_MIN_CONFIRMATIONS=2` | `memory-agent` | `CORE/memory-consolidation`, `memory-review` | — | — | all 5 | `test_research_memory_governance.py` | `route_memory()` is a flat `if kind == ...` chain, not a dict table | 4 research `kind` strings were added as NAMED branches in the existing function: Working by default, Job with a real `job_id`, Project only for a DECIDED `architecture_decision`. |
| Research-origin admission bar | READY | `memory_router.research_provenance_signals()` / `is_research_origin()` / `research_engineering_admission_reasons()` / `research_organizational_admission_reasons()` | `research-architect` | `CORE/engineering-memory`, `organizational-memory` | — | — | Engineering/Organizational (as a refusal) | `test_research_memory_governance.py`, acceptance test H | Recognises research origin by FIELD SHAPE, not by `kind` — closes the relabel-to-`debug_lesson` laundering path | Reuses the SAME `ORGANIZATIONAL_MIN_CONFIRMATIONS` constant; no weaker research promotion path exists. |
| Obsidian memory vault | READY (untouched) | `memory_vault.py` (1530 lines): `build_frontmatter_from_memory_record()`, `build_sections_from_memory_record()` | `memory-agent` | `CORE/memory-link`, `memory-retrieval`, `memory-gc` | — | — | all 5 | `test_memory_vault*.py` | Field-driven and generic | A research-origin record mirrors through the same generic builders; no research-specific vault code exists or was needed. |
| Evidence Engine (DuckDB) | PARTIAL, and correctly NOT extended | `evidence_db.py` (579 lines, 14 tables: jobs, job_memory_records, regression_verdicts(+history), coverage_samples, failure_signatures, rtl_*, normalized_evidence) | — | `CORE/evidence-truth-gate` | read-only via MCP | — | Job | itself | Every table mirrors a real sim/job/RTL record shape; none of them is a research document | `ResearchEvidenceCard` provenance instead reuses `doc_extraction.DocumentIndex` + `evidence_ref()`. No research table, no second database. |
| Document ingestion substrate | READY | `doc_extraction.py` (324 lines): `sha256_file()`, `DocumentIndex`, `evidence_ref()`, `build_research_evidence_card_skeleton()`, `validate_research_evidence_card()`, `research_card_missing_fields()`, `prior_research_relations()` | `research-architect` | `CORE/document-extraction`, `research-ingestion` | — | — | Working | `test_research_evidence_card.py` | **Contains no text extraction of any kind** — `SUPPORTED` is a suffix allowlist, not a parser inventory. Real PDF reading is `vip_user_guide_distill.py` (pypdf), scoped to VIP guides | `evidence_ref()`'s 5-key output seeds `source_provenance` with no adapter. This is the reuse the master prompt's section 6 asked for, exercised rather than cited. |
| Confidence scoring | READY | `inference.py` `score_confidence(independent_sources, evidence_refs_verified, counter_evidence, consensus)` → HIGH/MEDIUM/LOW | all | `CORE/confidence-gate`, `inference-confidence-gate` | RE_AUDIT/RCA_JOIN | `qualified_conclusion` | — | `test_inference.py` | Three vocabularies coexist in this repo (`inference`'s 3, `memory_router`'s +CONFIRMED, `protocol_capability`'s separate ladder) — settled as deliberately distinct, commit `4084531` | `capability_evolution.recompute_confidence()` CALLS it and `assert_confidence_recomputed()` rejects a disagreeing stored level — deliberately unlike `self_tuning.classify_proposal()`, which trusts the LLM's self-reported `"confidence": "HIGH"`. |
| Autonomous inference / gap | READY | `inference.py` `identify_gap()`, `next_best_action(..., gap_action_catalog=None)` | `debug-agent` | `CORE/verification-inference-engine`, `evidence-gap-analysis`, `next-best-action` | debug/RE_AUDIT stages | `react/<stage>` | Working (`react_reasoning_step`) | `test_inference_engine_wiring.py`, `test_react_inference_wiring.py` | — | `capability_evolution.next_actions_for_unanswered()` and `doc_extraction.research_card_missing_fields()` both call these directly. **No Research Inference Engine exists** — section 10's prohibition is honored in code. |

## C. Human Approval Gate, Session State, Remote Execution, Git Governance

| Capability | Status | Relevant Files | Owning Agent | Owning Skill | Graph Node | Blackboard/State Object | Memory Layer | Evidence Mechanism | Known Limitation | Reuse Potential |
|---|---|---|---|---|---|---|---|---|---|---|
| Human Approval Gate | READY | `control_plane.py` (464 lines) `ControlPlane.approve()`/`get_approval()`/`get_approval_history()`/`describe_stage()`; CLI `dv-harness approve --stage <S> --note --reviewer-id --reviewer-confidence` | `dv-lead`, human | `CORE/approval-gate`, `human-control-plane` | consulted every `loop()` iteration and `run_stage()` | `.dv-harness/control.json["approvals"]` | — | `test_control_plane*.py` | `stage` is an arbitrary string key, so an approval can be recorded for a stage no graph node owns | Reused VERBATIM by research: `capability_evolution.HUMAN_APPROVAL_STAGE = "RESEARCH_CAPABILITY_EVOLUTION"`. **No new gate machinery was written.** `approve` admits that id; `set-stage`/`redirect`/`correct`/`cosign` still take real graph stages only. |
| Pause / takeover / correct / cosign | READY | `cli.py:164-210`, same `ControlPlane` | human | `CORE/human-control-plane` | every loop iteration | `control.json` | — | `test_control_plane*.py` | — | Available to a research run unchanged; nothing research-specific needed. |
| Git / PR-only governance | READY | `git_governance.py` (216 lines) `evaluate_pre_push()`/`evaluate_pre_merge_commit()`; `tools/git-hooks/{pre-push,pre-merge-commit}`; `core.hooksPath` = `tools/git-hooks` (verified live) | any | `CORE/git-push-gate`, `git-workflow` | `GIT_PUSH`, `GIT_SYNC` | — | — | `test_git_hooks_e2e.py` drives a REAL push/merge and asserts git aborts | Server-side branch protection is NOT in force (`origin` is empty, so it has no branches to protect). The local hook is the only gate today | Keys only on destination branch + AI-agent env marker — it has no notion of which feature produced the push, so **Stage 3 is already covered with zero new code**. |
| Session save / restore | PARTIAL | `session_snapshot.py` (853 lines) `save_session()`/`restore_session()`, `SESSION_FILES`, `SESSION_DIRS` (includes `blackboard/`, `react/`) | any | `CORE/agent-checkpoint` | — | all snapshotted topics | excluded by design | `test_session_snapshot.py` | Directory/file-name driven, not schema-aware | A research candidate lives in the `capability_evolution_candidates` Blackboard topic, so it is captured **with zero new code**. A durable `ResearchEvidenceCard` correctly falls OUTSIDE the snapshot: it is prior knowledge, not current-run state. |
| Remote Control / remote execution | READY (transport), N/A for research | `remote_control.py`, `tools/remote/remote_exec.py`, `remote_relay.py` | any | `CORE/remote-control-readiness`, `remote-control-session-manager`, `remote-linux-execution-bridge` | — | — | — | `test_remote_control*.py` | Transport only; harness governance stays authoritative | Research-ingestion/-architect are pure LOCAL_ANALYSIS and need none of it. Driving a research run over Remote Control already works unmodified. |

## D. Capability Evolution / self-improvement

| Capability | Status | Relevant Files | Owning Agent | Owning Skill | Graph Node | Blackboard/State Object | Memory Layer | Evidence Mechanism | Known Limitation | Reuse Potential |
|---|---|---|---|---|---|---|---|---|---|---|
| Gate self-tuning (pre-existing ancestor) | PARTIAL | `self_tuning.py` (516 lines); `tools/verification_flow/self_tuning_proposal_gate.py`; wired at `engine.py:3665` `_maybe_run_self_tuning_review()` and into `gates.effective_stage_gates()` | none | — | every stage (post-verdict) | — | Engineering (adjustment records) | `test_self_tuning*.py` | **Tunes zero real gate behaviour today**: a repo-wide grep finds no non-test caller of `get_param()` outside the module itself — rollout steps 2–3 of its own design spec never happened. Trusts the LLM's self-reported `confidence` verbatim | Its PRIMITIVES generalize (mint-once/mutate-in-place persistence, index-then-filter enumeration — now the shared `MemoryStore.find()` — best-effort isolation at the call site, mechanical-gate-before-trust). Its SHAPE does not: binary AUTO_APPLY/DEFER, a closed 3-case JSON-key `change`, a 5-value status. |
| `CapabilityEvolutionCandidate` | READY (new module, justified) | `capability_evolution.py` (1384 lines): `PROMOTION_STATES` (§70's 11, verbatim), `LEGAL_TRANSITIONS`, `RECOMMENDATIONS`, `OVERLAP_STATUSES`, `derive_overlap_status()`, `decide_recommendation()`, `recompute_confidence()`, `transition()`, `assert_human_approval()`, `persist_candidate()`; `schemas/capability_evolution_candidate.schema.json` | `research-architect` | — | none | `capability_evolution_candidates` | Working (asserted, never higher) | `test_capability_evolution_research_architect.py` (acceptance B/C/D/E) | Writes nothing outside `<root>/.dv-harness/`; has no verification authority (`assert_no_verification_verdict_vocabulary()`) | A thin rename of `self_tuning` was **not** achievable: the 11-state lifecycle, the pre-experiment recommendation step, and the five `existing_*` REUSE-search fields are structural absences in a domain whose action space is closed to pre-existing JSON keys. Forcing them in would have been the bad reuse this project was already burned by. |
| Cross-card comparison (§28 / test G) | READY (new, extends the architect's own module) | `capability_evolution.py` `read_evidence_cards()`, `compare_evidence_cards()`, `link_prior_research()`, `prior_research_link()`, `persist_prior_research_links()`; vocabulary from `doc_extraction.prior_research_relations()` | `research-architect` | — | none | — | Working (`research_claim`, asserted) | `test_research_stage1_acceptance_a_g.py` | `SUPPORTS`/`SUPERSEDES` are unreachable by derivation on purpose — corroboration is a reading judgement, not a set operation, and are honored only when a document declares them | Reuses the card schema's own 7-label relation enum (no second vocabulary), an EXISTING `research_claim` memory kind (no sixth tier), and `route_and_store()` (no direct tier write). Never edits a filed card. |

## E. Verification-domain mechanisms (dv-intake … signoff)

Every row here is context for the REUSE-before-ADD decision, not something the
research capability touches. **None of these files was modified by Stage 1.**

| Capability | Status | Relevant Files | Owning Agent | Owning Skill | Graph Node | Blackboard/State Object | Memory Layer | Evidence Mechanism | Known Limitation | Reuse Potential |
|---|---|---|---|---|---|---|---|---|---|---|
| dv-intake | PARTIAL | `.claude/tools/dv-project-scan.ps1` → `.dv-workflow/inventory.json` | `dv-lead` | `CORE/dv-intake` | `INTAKE` | — | — | the inventory file | Raw bucketing is real; the DUT/VIP/UVM/vPlan authority classification is prose an agent enacts | — |
| protocol-aware env builder | PARTIAL | `uvm_generator/create_environment.py`, `environment_mode_router.py`, 5 protocol model generators; `protocol_capability.py` | protocol builders | `PROTOCOL_BUILDERS/*` | `VERIFICATION_ARCHITECTURE`, `IMPLEMENT` | `env_manifest` | Project | `test_protocol_capability.py` | Only USB is `DUT_PROVEN`; Ethernet/eDP/UCIe have no protocol-specific module at all | Its two-question split (what code EXISTS vs what has been PROVEN) is the model a research capability claim should follow. |
| vip-topology-planner | PARTIAL→MISSING | `.dv-workflow/vip_topology.csv`, `vip_binding.csv` are `.claude/templates/` blanks; nearest real code `connectivity.py`, `bind_mechanism_generator.py` | `IP_UVM_DV_Gen` | `CORE/vip-topology-planner` | `VERIFICATION_ARCHITECTURE` | `connectivity_gates` | — | `connectivity.py` T1–T4 tiers | VIP-topology DERIVATION is agent-trusted; only the bind-location sub-problem is code-gated | — |
| soc-scenario-planner | PARTIAL→MISSING | template only; `cross_protocol_scenario_gate.py` covers 1 of the skill's 6 scenario classes | `dv-lead` | `CORE/soc-scenario-planner` | `SOC_SCENARIO_PLANNER` | — | — | that gate | E2E/DMA/concurrency scenario derivation is prose-only per run | — |
| vplan-core | PARTIAL (READY under a different artifact) | `vplan_writer/writer.py` (927 lines, evidence-gated XLSX); `vplan_writer_validation_gate.py`, `spec_coverage_audit.py` | `dv-lead` | `CORE/vplan-core` | `VPLAN` | — | Project | those gates | Real capability exists at a different path/format than the skill documents — a documentation-pointer gap, not a code gap | — |
| requirements-traceability | PARTIAL | `.dv-harness/requirements.csv` (real registry, header-only here), read by `change_impact.load_trace_registry()`; 4 real gates | `dv-lead` | `CORE/requirements-traceability` | `REQUIREMENTS_TRACEABILITY`, `REQUIREMENT_CLOSURE` | — | Project | those gates | Registry is validated at 3 gates but nothing POPULATES it — an agent fills it by hand | — |
| verification-change-impact | READY | `change_impact.py` (715 lines): git-diff parsing, file→module map, `select_regression()`, writes `.dv-harness/change_impact.csv` + `regression_selection.csv` | `analysis-agent` | `CORE/verification-change-impact` | `CHANGE_IMPACT`, `SYSTEM_LEVEL` | — | Project | 3 real gates | Empty in this repo (no RTL of its own) | Best-matched existing mechanism against §15's own example. The most likely target of a real Stage-2 research finding. |
| regression core / report / monitor / LSF | READY–PARTIAL | `lsf_client.py` (1247), `regression_tiers.py` (377), `regression_reporter.py`, `sim_log_analysis.py` | `regression-agent` | `CORE/regression-core`, `regression-report`, `lsf-regression(-monitor)` | `REGRESSION`, `REGRESSION_MONITOR` | job state JSON | Job | real `JobState` per job | Cross-job failure CLUSTERING (pick one representative) is agent judgement; per-job signature extraction is real code | — |
| failure triage / recovery loop | PARTIAL / READY | `sim_log_analysis.py`; `focused_wave_debug_window_gate.py`, `rca_replay_fix_closure_gate.py`, `fix_effectiveness_gate.py` | `debug-agent` | `CORE/failure-triage`, `failure-recovery-loop` | `FAILURE_RECOVERY`, `RE_AUDIT`, `WAVE_ANALYSIS` | `findings`, `debug_loop_history` | Job → Engineering | those gates + `test_waveform_dump_scope_human_confirmation.py` | Batch-wide clustering unproven as code | Among the most robustly code-enforced mechanisms in the repo. |
| coverage | PARTIAL | `coverage_analysis.py` (600 lines): `parse_coverage_summary()`, `identify_holes()`, `classify_coverage_hole()`, `escalate_unreachable_holes()`; `per_port_verification_matrix_gate.py` | `coverage-agent` | `CORE/coverage-by-port-audit` | `COVERAGE_CLOSURE` | `coverage_samples` (evidence DB) | Project | that gate | Operates on aggregate summaries; the per-port × per-protocol-dimension matrix is agent-supplied and only its completeness is gated | — |
| signoff | READY | `signoff_export.py` (513 lines) `collect_signoff_bundle()`/`compute_bundle_hash()`; 9 real `SIGNOFF` gates; `qualified_conclusion.policy.can_signoff()` hard-stop | `signoff-agent` | `CORE/signoff-ready-gate`, `verification-signoff` | `SIGNOFF`, `PROMOTION_READINESS` | `qualified_conclusion` | Project → Engineering | `test_qualified_conclusion_closure_gate.py` | The two SKILL.md files are near-empty stubs; real capability is in the engine and undocumented at the skill layer | **The boundary research must never cross**: nothing in the research path returns, accepts, or persists any `models.Status` member. |
| subsystem → SoC | READY (unexercised here) | `environment_mode_router.py`, `create_environment.py` `compose_soc_environment()`; `subsystem_environment_registry.json` | `dv-lead` | `CORE/subsystem-to-soc-verification` | `SYSTEM_LEVEL` (11 gates) | — | Project | `test_system_level_soc_composition_wiring.py` | Has never fired on a real multi-subsystem project in this repo's own history; the registry is legitimately empty | — |

---

## Documentation-vs-implementation mismatches found (section 4's explicit ask)

Section 4 says: *"Do not rely only on documentation. Compare documentation with
actual implementation and report mismatches."* Six real ones, all confirmed by
reading both sides:

1. **`.dv-workflow/*.csv` artifacts have no generator.** Every CSV/JSON output
   the `CORE/*` planner skills declare (`vip_topology.csv`, `soc_scenarios.csv`,
   `requirements_traceability.csv`, `vplan.csv`, `tb_topology.json`,
   `regression_results.csv`, `failure_clusters.csv`, `pattern_registry.csv`, …)
   exists on disk **only** as a blank header under `.claude/templates/`. No
   Python anywhere writes any of them. An agent copies the template and fills it
   in each run. Consequence for any future reader: *"a `.dv-workflow/foo.csv`
   exists from a past run"* is evidence an agent produced it, never evidence a
   deterministic generator did.
2. **Path drift between skill and code.** `vplan-core` documents
   `.dv-workflow/vplan.csv`; the real generator is `vplan_writer/writer.py`
   emitting XLSX. `pattern-registry` documents
   `.dv-workflow/pattern_registry.csv`; the real generator is
   `uvm_generator/pattern_registry_generator.py`. `verification-change-impact`
   documents `.dv-workflow/`; the real writer targets `.dv-harness/`. Capability
   gap: none. Documentation gap: real, and it is how "MISSING" gets mis-declared.
3. **Stub skills over deep code.** `signoff-ready-gate` (7 lines) sits over
   `signoff_export.py` + 9 gates; `verification-blackboard` (8 lines) over the
   real Blackboard. These are pointers by this repo's own convention, not
   specifications — but a reader who audits skills alone will under-count the
   engine badly.
4. **`self_tuning.py` is wired but tunes nothing.** Three real wiring points
   (`engine.run_stage()`, `gates.effective_stage_gates()`,
   `gate_history.jsonl`), zero non-test callers of `get_param()`. Existing +
   wired ≠ load-bearing.
5. **`protocol_capability_registry.json` used to overstate readiness** for all
   11 protocols with one collapsed field, and that overstatement reached
   `dashboard.py`. Split into three separately-checkable facts on 2026-09-04.
6. **Counts in `.work/` reports go stale within hours** under concurrent work
   (see "Counts measured today" above). Any number quoted from a report should
   carry that report's timestamp.

## What Stage 1 added, and what it deliberately reused

| Section 2.2 mechanism | Reused / Extended / Added | Evidence |
|---|---|---|
| Inference engine, confidence, gap, next-best-action | **REUSED verbatim** | `capability_evolution.recompute_confidence()` calls `inference.score_confidence()`; `next_actions_for_unanswered()` calls `next_best_action()`; `research_card_missing_fields()` calls `identify_gap()`. No research inference module exists. |
| Blackboard | **EXTENDED** (one topic, existing shape) | `capability_evolution_candidates` mirrors `findings`'s registry shape and helper pair. |
| 5-level memory | **EXTENDED** (4 kinds in the existing dispatch) | `RESEARCH_EVIDENCE_KINDS`, `CAPABILITY_EVOLUTION_KINDS`, `ARCHITECTURE_DECISION_KIND` — no sixth tier, no second router. |
| Human Approval Gate | **REUSED verbatim** | `ControlPlane.approve(stage="RESEARCH_CAPABILITY_EVOLUTION")`. |
| Document ingestion | **EXTENDED** | `build_research_evidence_card_skeleton()` on top of `sha256_file()`/`DocumentIndex`/`evidence_ref()`. No new parser, no new document store. |
| Git/PR governance | **REUSED verbatim** | Branch-and-marker keyed; already covers Stage 3 with no research-specific code. |
| Session save/restore | **REUSED verbatim** | Candidate state is a Blackboard topic, already in `SESSION_DIRS`. |
| Evidence DB | **NOT extended, deliberately** | Cards are JSON under `research/evidence_cards/`; every DuckDB table mirrors a sim/job/RTL shape and none of them is a document. |
| `CapabilityEvolutionCandidate` state machine | **ADDED**, with the ENHANCE-insufficient reason stated | `self_tuning.py`'s action space is closed to pre-existing JSON keys and has no experiment phase; §70 needs 11 states, a pre-experiment recommendation step, and 5 REUSE-search fields it structurally lacks. |
| `research-ingestion` skill, `research-architect` agent, `research/` tree | **ADDED**, with the search shown | No `research*` artifact existed anywhere; the five nearest agents were grepped and matched zero. |

## Scope boundary of this document

This is a Stage-0 baseline. It records what exists; it does not analyze any
external paper (Stage 2) and it authorizes no change to production code
(Stage 3, which requires `dv-harness approve RESEARCH_CAPABILITY_EVOLUTION`
with a real reviewer first). Nothing in this file is verification evidence about
any DUT — see CLAUDE.md's Evidence Truth Rule and `research/README.md`.
