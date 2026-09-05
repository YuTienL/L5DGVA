export const meta = {
  name: 'capability-evolution-pipeline',
  description: 'Install DV Agent Harness L5 Research/Capability-Evolution Stage 0+1 (research-ingestion Skill, research-architect Agent, ResearchEvidenceCard, CapabilityEvolutionCandidate, minimal routing, Human Gate reuse) per the master prompt, reusing existing mechanisms wherever real overlap exists -- Stage 2 (real paper analysis) and Stage 3 (approved implementation) explicitly NOT run',
  phases: [
    { title: 'Audit', detail: 'Stage 0 baseline: 6 parallel audits of current L5 vs. the master prompt checklist' },
    { title: 'Build', detail: 'Stage 1 installation: sequential, reuse-first build of the research capability' },
    { title: 'Review', detail: 'Stage 1 acceptance tests A-H + backward-compat + the master prompt\'s own PASS/FAIL report format' },
  ],
}

const CONTEXT = `
This implements Stage 0 (audit) and Stage 1 (install permanent research
capability) ONLY, from
D:/DV/Task/DV_Agent_Harness_L5/DV_Agent_Harness_L5_Research_Capability_Evolution_Master_Prompt_vLatest.md
(3236 lines, read in full before this workflow was authored -- do not
re-derive it from a summary, read the real file yourself for your own
scope's exact section if you need the verbatim wording).

The master prompt's OWN First-Run Control Instruction (section 57 and its
update in section 82) is explicit: on first execution, run Stage 0 and
Stage 1 only. Do NOT start Stage 2 (analyzing real external papers/standards
against L5) until research-ingestion and research-architect are PROVEN
OPERATIONAL through the 8 Stage-1 acceptance tests (A-H). Do NOT enter Stage
3 (implementing approved changes) without explicit separate human approval.
This workflow's scope is bounded to exactly Stage 0 + Stage 1 -- do not
build a pipeline that actually ingests or analyzes any real paper, and do
not implement any capability-evolution CHANGE to production code as part of
this pass. You are installing the MACHINERY, not yet operating it on real
content.

The master prompt's central, repeated, non-negotiable principle (section 2.2
and section 14, "MANDATORY CURRENT-L5 CHECK"): REUSE before EXTEND before
ADD. Before proposing any new Agent/Skill/Graph Node/Blackboard object/
Memory store/Evidence store/database/workflow/router/inference engine/
confidence engine, you must search the existing dv_harness/ tree and
.claude/agents//.claude/skills/ for real, already-working equivalents, and
prefer extending them. This project (DV Agent Harness L5, v50) has an
extremely strong, independently-verified history this session of exactly
this failure mode (building parallel tiered-confidence classifiers,
duplicate memory mechanisms) being caught and flagged as a real defect --
do not repeat it here.

Known-real, already-confirmed overlap points (found by a prior read-through
this session -- re-verify with your own real grep/read before relying on
any of these, do not just cite this list):
- dv_harness/inference.py: score_confidence()/identify_gap()/next_best_action()/
  promote_if_high_confidence() -- the master prompt's section 10 explicitly
  requires reusing this for research reasoning ("Do NOT create a Research
  Inference Engine").
- dv_harness/self_tuning.py (506 lines, real, wired into engine.py's
  _maybe_run_self_tuning_review()) + tools/verification_flow/
  self_tuning_proposal_gate.py + docs/superpowers/specs/
  2026-09-02-autonomous-gate-self-tuning-design.md -- a REAL, already-built,
  already-wired confidence/risk-gated propose -> classify(auto-apply vs
  defer-to-human) -> apply/defer -> record-to-Engineering-Memory -> revert
  loop, currently scoped ONLY to gate parameter/membership tuning (rollout
  step 1 of that spec's own 4-step plan; steps 2-3, refactoring real gates
  to expose get_param(), have NOT happened -- confirmed zero real callers
  outside the module itself). This is structurally the closest existing
  ancestor to the master prompt's "CapabilityEvolutionCandidate" +
  "DISCOVERED -> ... -> PROMOTE/REVISE/HOLD/REJECT" promotion policy
  (section 63/70) -- its classify_proposal()/apply_proposal()/
  record_adjustment()/gate_ids_with_recent_reverts() functions may
  generalize directly rather than needing a parallel state machine. Verify
  this concretely rather than assuming it.
- dv_harness/memory_router.py: route_and_store()/route_memory()/
  promote_to_organizational() (ORGANIZATIONAL_MIN_CONFIRMATIONS=2) -- the
  real 5-level memory promotion gate the master prompt's sections 12/71/72
  describe wanting.
- dv_harness/doc_extraction.py (DocumentIndex, sha256 identity, evidence_ref()
  with document/version/page/section/location) + .claude/skills/CORE/
  document-extraction/SKILL.md -- real, generic document-ingestion substrate
  that already does most of what research-ingestion needs structurally for
  "External Technical Document -> Structured Research Evidence" with source
  provenance; likely the right base to extend rather than a new PDF/paper
  parser.
- dv_harness/control_plane.py's ControlPlane class + replan_stage()/
  describe_stage() and .claude/skills/CORE/approval-gate,human-control-plane
  -- candidate existing Human Approval Gate machinery.
- dv_harness/gates.py's STAGE_GATES (28 real stages, including a generic
  DISCOVERY stage and an EXPERT_FEEDBACK_LOOP stage) -- check whether
  research_intake/research_extract/research_validate style responsibilities
  (master prompt section 16, explicitly "conceptual responsibilities, not
  mandatory separate nodes") can route through an EXISTING generic stage
  rather than needing new graph nodes.
- .claude/skills/CORE/ has 150+ existing skills including
  verification-inference-engine, confidence-gate, inference-confidence-gate,
  next-best-action, evidence-truth-gate, evidence-gap-analysis,
  multi-source-evidence-consensus, hypothesis-generation, hypothesis-ranking,
  memory-consolidation/-retrieval/-link/-review/-gc, organizational-memory,
  project-memory, job-memory, working-memory, engineering-memory,
  route-resolver, skill-resolver, protocol-router, vplan-core,
  requirements-traceability, verification-change-impact, regression-core,
  regression-report, failure-triage, signoff-ready-gate,
  verification-signoff, multi-agent-orchestrator, plan-and-execute,
  reference-environment, pattern-registry -- essentially every mechanism
  the master prompt's section 2.2 forbids duplicating already has a named,
  real skill. Read the relevant ones' SKILL.md before deciding anything is
  missing.
- No research/, research-ingestion, or research-architect artifact of any
  kind exists yet anywhere in this repo -- this part is genuinely new.

Global constraints for every agent in this workflow:
- Never modify production verification-oracle semantics, signoff authority,
  or the gh/git PR-only main/master protection this session already built
  (dv_harness/git_governance.py, tools/git-hooks/) -- per the master
  prompt's own section 73 "Self-Improvement Safety Boundary" and this
  project's Agent-Authored Change Accountability policy in CLAUDE.md.
- Never let this pass silently promote anything to Organizational Memory --
  a single design/build session is not "repeated, human-approved" evidence.
- Many OTHER workflows may be concurrently active in this same repo this
  session (an AI-mechanism audit, a governance-architecture reverify, an
  Obsidian-memory reverify, a verification-knowledge-assets reverify, a
  self-describing-environment/bind-connectivity reverify, a live remote USB
  build). CLAUDE.md, dv_harness/gates.py, dv_harness/memory_router.py,
  dv_harness/cli.py, and .claude/agents/ROSTER.md are exactly the kind of
  shared files those other workflows may also be touching right now. Check
  git status/git diff on any file BEFORE touching it, and use the
  hand-scoped patch technique (git diff > patch, trim to your own hunk,
  git apply --cached --check then --cached) for every file, never a broad
  git add. If a file shows unexpected concurrent changes, re-read it fresh
  before patching.
- Write real tests. Run them. Do not claim DONE without a real command's
  real passing output.
`

phase('Audit')

const auditAgentsSkillsGraph = agent(`${CONTEXT}

## Your scope: Stage 0 checklist items -- Agents, Skills, CLAUDE.md, router/graph, project settings

Master prompt section 4 requires inspecting: .claude/agents/, .claude/skills/, CLAUDE.md, project settings, settings.local, orchestration/router definitions, graph nodes, conditional edges. Read the relevant real files (.claude/agents/ROSTER.md, a sample of 5-10 .claude/agents/*.md files, .claude/skills/CORE/route-resolver/SKILL.md, .claude/skills/CORE/skill-resolver/SKILL.md, .claude/skills/CORE/protocol-router/SKILL.md, dv_harness/gates.py's STAGE_GATES dict, .dv-harness/graph/main_graph.json if it parses).

For each of these capabilities, classify READY / PARTIAL / MISSING / UNKNOWN with real file:line evidence: (1) a research-shaped intent router or an extensible generic router that could host one, (2) an agent role close enough to 'research-architect' in spirit (check .claude/agents/analysis-agent.md, dv-lead.md, verification-risk-experience-agent.md, protocol-corner-case-intelligence-agent.md, memory-agent.md), (3) a generic graph stage that could host research_intake/research_extract/research_validate/harness_discovery/capability_map/research_synthesis/architecture_gap/architecture_proposal/human_gate/implementation_plan/benchmark responsibilities without new nodes (check the DISCOVERY and EXPERT_FEEDBACK_LOOP stages in gates.py, and any generic intake/planning/approval node in main_graph.json), (4) whether CLAUDE.md already documents anything research/capability-evolution-shaped.

Produce a real table (Capability | Status | Relevant Files | Owning Agent | Owning Skill | Graph Node | Known Limitation | Reuse Potential) for this scope, per the master prompt's section 4 report shape. Do not modify any file -- audit only.`, {label: 'audit:agents-skills-graph', phase: 'Audit'})

const auditBlackboardMemoryEvidence = agent(`${CONTEXT}

## Your scope: Stage 0 checklist items -- Blackboard, 5-Level Memory, Evidence Engine, Confidence, Autonomous Inference, Next-Best-Action

Read dv_harness/blackboard.py (real methods, real current state objects), dv_harness/memory.py + memory_router.py + memory_vault.py (5-tier stores, route_and_store()/route_memory()/promote_to_organizational(), ORGANIZATIONAL_MIN_CONFIRMATIONS), dv_harness/inference.py (score_confidence/identify_gap/next_best_action/promote_if_high_confidence -- read every function's real signature and docstring), dv_harness/evidence_db.py (DuckDB schema, real tables), and the corresponding .claude/skills/CORE/ SKILL.md files (verification-blackboard, working-memory/job-memory/project-memory/engineering-memory/organizational-memory, verification-inference-engine, confidence-gate, inference-confidence-gate, next-best-action, evidence-truth-gate, evidence-gap-analysis).

For each, classify READY / PARTIAL / MISSING / UNKNOWN with real file:line evidence, and explicitly answer: could a new Blackboard object (ResearchEvidence/ResearchClaim/ResearchHypothesis/CapabilityGap/ArchitectureCandidate/ArchitectureDecision/ImplementationExperiment/BenchmarkEvidence per master prompt section 11) be added as a real extension of the existing Blackboard's own state-object conventions (cite the real pattern an existing state object follows), or does nothing analogous exist yet? Could a new memory_router.py 'kind' value (e.g. research_evidence, capability_evolution_candidate) be added to its existing dispatch table (cite the real dispatch function/table), with what tier defaults, and what would have to be true before route_memory() lets one reach Engineering or Organizational tier?

Produce the same table format as the sibling audit. Do not modify any file -- audit only.`, {label: 'audit:blackboard-memory-evidence', phase: 'Audit'})

const auditHumanGateGovernance = agent(`${CONTEXT}

## Your scope: Stage 0 checklist items -- Human Approval Gate, session save/restore, remote execution, Git/PR governance

Read dv_harness/control_plane.py in full (ControlPlane class, replan_stage(), describe_stage()/describe_stages()), dv_harness/session_snapshot.py, dv_harness/git_governance.py + tools/git-hooks/, and the corresponding skills (.claude/skills/CORE/approval-gate, human-control-plane, restore-session, save-session, git-push-gate, git-workflow, remote-control-readiness, remote-control-session-manager).

Classify READY / PARTIAL / MISSING / UNKNOWN with real evidence for: (1) does a real, generic 'stop and wait for a human decision' mechanism already exist that a research-architect's Human Approval Gate could reuse verbatim (cite the exact function/gate/CLI verb a human uses to approve/reject), or would this need new code; (2) does CLAUDE.md's gh/git PR-Only Governance Policy (already real per this session's own work) already structurally prevent Stage 3's 'never push directly to main' requirement without any new code; (3) does session save/restore already capture enough state shape (per this session's own separate audit of Session Save/Restore) that a research-architect's in-progress analysis state could reuse it, or would it need a research-specific extension.

Produce the same table format as the sibling audits. Do not modify any file -- audit only.`, {label: 'audit:human-gate-governance', phase: 'Audit'})

const auditProtocolDomainMechanisms = agent(`${CONTEXT}

## Your scope: Stage 0 checklist items -- dv-intake, protocol-router, protocol profiles, UVM generation, VIP lookup, PSS, vPlan, scenario planner, requirements traceability, verification-change-impact, regression manager/monitor, failure triage, coverage, signoff

Read the real .claude/skills/CORE/ SKILL.md files for: dv-intake, protocol-router, protocol-aware-env-builder, vip-topology-planner, soc-scenario-planner, vplan-core, requirements-traceability, verification-change-impact, regression-core, regression-report, regression-status-reporter, lsf-regression, lsf-regression-monitor, failure-triage, failure-recovery-loop, coverage-by-port-audit, signoff-ready-gate, verification-signoff, subsystem-to-soc-verification, tb-topology-planner, pattern-registry, pattern-architecture, reference-environment. Also grep dv_harness/ for any real .py module backing verification-change-impact and regression management (e.g. tools/verification_flow/, dv_harness/lsf_client.py, dv_harness/regression_reporter.py).

This scope directly backs the master prompt's section 15 "Required Mapping Examples" (Semantic Change Impact -> ENHANCE verification-change-impact; AI Regression Selection -> inspect regression manager/monitor/coverage/failure-triage/verification-change-impact) and section 26 "Initial Research Areas." For each named mechanism, classify READY / PARTIAL / MISSING / UNKNOWN with real evidence, specifically noting whether it is a real, wired .py module or currently only a prose SKILL.md an LLM agent is trusted to follow each time (this exact distinction has been the single most common finding of every other audit this session -- do not assume 'a skill file exists' means 'real code exists').

Produce the same table format as the sibling audits. Do not modify any file -- audit only.`, {label: 'audit:protocol-domain-mechanisms', phase: 'Audit'})

const auditCapabilityEvolutionOverlap = agent(`${CONTEXT}

## Your scope: the Capability Evolution chapter's overlap with dv_harness/self_tuning.py

Read docs/superpowers/specs/2026-09-02-autonomous-gate-self-tuning-design.md and docs/superpowers/plans/2026-09-02-autonomous-gate-self-tuning-mechanism.md in full, and dv_harness/self_tuning.py + tools/verification_flow/self_tuning_proposal_gate.py in full (every function). Confirm independently (re-run the greps, don't trust a prior summary): is self_tuning.py really wired into engine.py's real stage-transition path (grep engine.py for self_tuning usage and read the real call site), and is it true that zero real (non-test) gate scripts currently call get_param() (i.e. rollout steps 2-3 of that spec's own plan have not happened)?

Then do the real comparison: map the master prompt's CapabilityEvolutionCandidate schema (section 63: candidate_id/trigger_source/trigger_type/source_provenance/evidence_refs/hypothesis/affected_capability/current_status/existing_agent/existing_skill/existing_graph_node/existing_state/existing_memory/exact_gap/proposed_action/recommendation/expected_verification_benefit/evidence_strength/confidence/implementation_difficulty/integration_risk/maintenance_cost/experiment_required/experiment_plan/benchmark_plan/acceptance_criteria/rollback_plan/approval_level/final_decision/promotion_status) and Promotion Policy (section 70: DISCOVERED/EVIDENCE_GATHERING/PROPOSED/EXPERIMENT_APPROVED/EXPERIMENTING/BENCHMARKED/PROMOTION_CANDIDATE/HUMAN_APPROVED/PRODUCTION/REJECTED/ROLLED_BACK) against self_tuning.py's real proposal dict shape, classify_proposal()'s real auto-apply-vs-defer logic, and record_adjustment()'s real status vocabulary. Answer concretely: which of self_tuning.py's functions genuinely generalize to a non-gate-parameter CapabilityEvolutionCandidate with only parameter/signature changes (name them), which would need real new logic because the master prompt's promotion-state vocabulary is genuinely richer (name the gap), and whether a thin new module that composes self_tuning.py's generic primitives (rather than duplicating its state-machine shape) is achievable, or whether self_tuning.py is too gate-specific to reuse and a new-but-structurally-parallel module is honestly warranted (if so, say so plainly -- do not force a bad reuse).

Produce your answer as a structured comparison, not the audit table format the other agents use (this is a design-comparison question, not a checklist).`, {label: 'audit:capability-evolution-overlap', phase: 'Audit'})

const auditDocIngestionReuse = agent(`${CONTEXT}

## Your scope: document/evidence ingestion substrate reuse for research-ingestion

Read dv_harness/doc_extraction.py in full (DocumentIndex, sha256_file, normalize_register_record, evidence_ref) and .claude/skills/CORE/document-extraction/SKILL.md in full. Also check dv_harness/vip_distill.py (normalized-evidence pipeline for sim.log/job-record/fsdbreport -> DuckDB) and dv_harness/evidence_db.py's schema for whether a generic 'external document evidence' table could hold ResearchEvidenceCard-shaped rows, or whether that store is too sim-evidence-specific to reuse.

Answer concretely: does doc_extraction.py already handle PDF (the master prompt's primary paper format) with real extraction, or only format detection/indexing with actual parsing left to the caller? Does it already produce something evidence_ref()-shaped that could seed ResearchEvidenceCard's source_provenance field directly? What exactly would research-ingestion need to add on top of doc_extraction.py (name concrete functions/fields), versus what it gets for free by calling into it?

Produce your answer as a structured comparison, not the audit table format. Do not modify any file -- audit only.`, {label: 'audit:doc-ingestion-reuse', phase: 'Audit'})

const auditResults = await parallel([
  () => auditAgentsSkillsGraph, () => auditBlackboardMemoryEvidence, () => auditHumanGateGovernance,
  () => auditProtocolDomainMechanisms, () => auditCapabilityEvolutionOverlap, () => auditDocIngestionReuse,
])
const [agentsSkillsGraphR, blackboardMemoryEvidenceR, humanGateGovernanceR,
  protocolDomainMechanismsR, capabilityEvolutionOverlapR, docIngestionReuseR] = auditResults

phase('Build')

const auditBundle = `
### Audit: Agents/Skills/Graph
${agentsSkillsGraphR}

### Audit: Blackboard/Memory/Evidence/Inference
${blackboardMemoryEvidenceR}

### Audit: Human Gate/Governance
${humanGateGovernanceR}

### Audit: Protocol/Domain Mechanisms
${protocolDomainMechanismsR}

### Audit: Capability-Evolution / self_tuning.py Overlap
${capabilityEvolutionOverlapR}

### Audit: Document-Ingestion Reuse
${docIngestionReuseR}
`

log('Stage 0 audit complete. Building Stage 1 sequentially (shared files: CLAUDE.md, gates.py, memory_router.py, cli.py, .claude/agents/ROSTER.md) so later steps see earlier steps\' real committed state.')

const buildDocIngestion = await agent(`${CONTEXT}

## Your task: research-ingestion Skill + ResearchEvidenceCard, built on real audit evidence

Real Stage-0 audit findings, read carefully -- ground every decision in this, not assumption:
${auditBundle}

Build, in order:
1. \`.claude/skills/research-ingestion/SKILL.md\` following this repo's real existing skill conventions (read 2-3 existing .claude/skills/CORE/*/SKILL.md files for the real frontmatter/section shape first -- Purpose/Inputs/Outputs/Preconditions/Execution Steps/Fallback/Evidence Requirements/Failure Conditions/Examples, or whatever this repo's real convention actually is). Responsibility boundary exactly per master prompt section 6: External Technical Document -> Structured Research Evidence, ONE document -> ONE independent ResearchEvidenceCard, explicitly NOT deciding final architecture / cross-paper synthesis / modifying production code / declaring PASS.
2. A ResearchEvidenceCard JSON schema (\`dv_harness/schemas/research_evidence_card.schema.json\`, following the real style of an existing schema like register_map.schema.json or question.schema.json) with the fields from master prompt section 7, and required per-claim classification (FACT/AUTHOR_CLAIM/INFERENCE/HYPOTHESIS, section 9) as a real schema-enforced structure, not free text.
3. If audit evidence shows dv_harness/doc_extraction.py is a real, reusable substrate: extend it (a new function, not a parallel parser) to build a ResearchEvidenceCard skeleton (document_id/title/source/document_type/source_provenance populated from real DocumentIndex/evidence_ref() output) from a supplied document path, explicitly leaving the LLM-authored analytical fields (problem_statement, core_method, claim_set, candidate_l5_mapping, etc.) for the skill/agent to fill in -- this function's job is ONLY the mechanical identity/provenance part doc_extraction.py already does well, not the extraction Claude does by reading the document.
4. Storage location \`research/evidence_cards/\` (create the directory with a README noting the naming convention from master prompt section 27) and \`research/README.md\` (master prompt section 48's first artifact).
5. Real tests proving: the schema rejects a card missing a required field or with an invalid claim_type; the doc_extraction extension produces a real, correct skeleton for a real (or synthetic) test document with correct sha256/evidence_ref values.

Check git status/diff before touching any shared file. Run the new tests and the existing doc_extraction/document-index test suite to confirm no regression. Commit your real, scoped change.

Write a report to .work/gap-close-capability-evolution-research-ingestion-report.md. Report DONE (with what changed and commit hash) / BLOCKED, with a one-line test summary.`, {label: 'build:research-ingestion', phase: 'Build', model: 'claude-opus-5'})

const buildResearchArchitect = await agent(`${CONTEXT}

## Your task: research-architect Agent, reusing real Autonomous Inference + memory

Real Stage-0 audit findings:
${auditBundle}

The research-ingestion Skill + ResearchEvidenceCard schema were just built in the previous step -- read what actually landed (.claude/skills/research-ingestion/SKILL.md, dv_harness/schemas/research_evidence_card.schema.json, any doc_extraction.py extension) before designing against it, don't assume the plan text above is exactly what got built.

Build, in order:
1. \`.claude/agents/research-architect.md\` following this repo's real existing agent conventions (read 2-3 existing .claude/agents/*.md files first, and .claude/agents/ROSTER.md for how agents are registered -- check git status/diff on ROSTER.md before editing it, it is a very likely concurrent-edit collision point). Role: Principal Verification Research Architect, per master prompt section 13. Its responsibility: given ResearchEvidenceCards + actual current L5 implementation + prior validated research, produce a KEEP/ENHANCE/ADD/EXPERIMENT/REJECT decision per master prompt section 14's exact 10-question mandatory-current-L5-check sequence.
2. Wire its confidence/decision reasoning to REUSE dv_harness/inference.py's real score_confidence()/identify_gap()/next_best_action() (per master prompt section 10's explicit "do NOT create a Research Inference Engine") -- if the audit found these functions' real signatures need a small compatible extension (e.g. a new evidence category name) to fit research evidence rather than DV simulation evidence, make that minimal extension in inference.py itself rather than duplicating its math in a new module. Show the real before/after signature if you change it, and confirm every existing caller still passes.
3. A CapabilityEvolutionCandidate JSON schema (\`dv_harness/schemas/capability_evolution_candidate.schema.json\`) with the fields from master prompt section 63, with a status vocabulary matching section 70's Promotion Policy (DISCOVERED/EVIDENCE_GATHERING/PROPOSED/EXPERIMENT_APPROVED/EXPERIMENTING/BENCHMARKED/PROMOTION_CANDIDATE/HUMAN_APPROVED/PRODUCTION/REJECTED/ROLLED_BACK). Per the audit's self_tuning.py comparison: if self_tuning.py's classify_proposal()/apply_proposal()/record_adjustment() genuinely generalize (per that audit's own concrete finding), wire this schema's records to flow through those same functions with minimal parameterization; if the audit concluded self_tuning.py is too gate-specific, build the minimal new equivalent it identified as genuinely needed -- follow whichever the audit concretely recommended, do not re-litigate it yourself without new evidence.
4. Wire research-architect's KEEP/ENHANCE/ADD/EXPERIMENT/REJECT decision and any CapabilityEvolutionCandidate it creates to real Blackboard/Memory writes (per the audit's Blackboard/Memory findings) -- a decision must be real, persisted state, not just the agent's own conversational output.
5. Wire a real Human Approval Gate stop (per the audit's Human-Gate findings -- reuse the real mechanism it found, or build the minimal missing piece it identified) such that research-architect's output STOPS before any production file is touched, exactly matching master prompt section 43's required stop-report format.
6. Real tests proving: a synthetic ResearchEvidenceCard describing a technique that clearly overlaps an existing dv_harness mechanism (name a real one from the audit) produces ENHANCE, not ADD (Stage 1 Acceptance Test B); a synthetic card with insufficient repository evidence to determine overlap produces UNKNOWN, not a fabricated MISSING (Test C); running the decision logic never itself modifies any file under dv_harness/ or .claude/ (Test D); nothing in this agent's own code path can produce a verification-oracle 'PASS' from LLM reasoning alone (Test E) -- if your design has any code path resembling that, remove it.

Check git status/diff before touching any shared file (.claude/agents/ROSTER.md especially). Run the new tests and confirm the existing inference.py test suite still fully passes after any signature change. Commit your real, scoped change.

Write a report to .work/gap-close-capability-evolution-research-architect-report.md. Report DONE (with what changed and commit hash) / BLOCKED, with a one-line test summary.`, {label: 'build:research-architect', phase: 'Build', model: 'claude-opus-5'})

const buildRoutingAndCommand = await agent(`${CONTEXT}

## Your task: minimal research intent routing + optional /research entry point

Real Stage-0 audit findings:
${auditBundle}

The research-ingestion Skill and research-architect Agent were just built -- read what actually landed before wiring routing to them.

Build, in order:
1. Minimal research intent recognition (master prompt section 17: RESEARCH_ANALYSIS/RESEARCH_COMPARE/RESEARCH_ARCHITECTURE_IMPACT/RESEARCH_DEEP_ANALYSIS/RESEARCH_MULTI_DOCUMENT) wired into whatever real router/intake mechanism the audit found (protocol-router / dv-intake / route-resolver / skill-resolver) as an EXTENSION of its existing dispatch logic, not a new parallel router. Default routing per section 17: research intent -> research-ingestion -> prior evidence lookup if applicable -> research-architect -> Human Approval Gate. Must not interfere with existing DV/USB/PCIe/Ethernet/AMBA/MIPI/CAN-FD/regression/failure-triage/coverage/signoff routing -- add a real test proving an existing non-research routing test case is unaffected.
2. IF this repository has a real, working project-command mechanism (check for .claude/commands/ or an equivalent the audit should have surfaced) that supports a thin front-door without duplicating logic: add a \`/research\` entry point per master prompt section 19/53 (default + --compare/--impact/--deep/--focus variants), routing into the same installed Skill/Agent logic, never containing its own business logic. If no such mechanism exists in this repo, do NOT invent one just to satisfy this requirement -- document in your report that this sub-item is honestly N/A for this repository's actual command architecture, per the master prompt's own section 19 fallback instruction ("If project command conventions differ, implement equivalent behavior using the repository's native mechanism rather than forcing this exact syntax").
3. Real tests proving: a synthetic "Analyze this new paper through the existing DV Agent Harness L5 research workflow..." style natural-language request (master prompt section 18's canonical form) routes to research-ingestion -> research-architect without needing to name any agent explicitly (Stage 1 Acceptance Test F); an existing non-research intent (pick a real one from this repo's own router tests) still routes exactly as before.

Check git status/diff before touching any shared router/intake file. Run the new tests plus the existing router/intake test suite to confirm zero regression. Commit your real, scoped change.

Write a report to .work/gap-close-capability-evolution-routing-report.md. Report DONE (with what changed and commit hash) / BLOCKED, with a one-line test summary.`, {label: 'build:routing-command', phase: 'Build', model: 'claude-opus-5'})

const buildMemoryGovernance = await agent(`${CONTEXT}

## Your task: 5-Level Memory governance for research/capability-evolution records + the Three Autonomy Levels

Real Stage-0 audit findings:
${auditBundle}

Build, in order:
1. New memory_router.py 'kind' values for research-related records (e.g. research_evidence, capability_evolution_candidate, architecture_decision) wired into its real existing dispatch table (per the audit's Blackboard/Memory findings -- extend the real function, do not add a parallel routing path). Enforce per master prompt section 12: a single paper claim / single research evidence card must NOT automatically become Engineering or Organizational Memory -- it starts at Working or Job tier, and promotion to Engineering requires the same rigor as promote_to_organizational() already requires elsewhere (real evidence, real confirmation_count, never a single occurrence). Real test proving a single freshly-ingested ResearchEvidenceCard-shaped record cannot reach Organizational tier through this new routing (Stage 1 Acceptance Test H).
2. Document (in a real docstring/comment at the actual enforcement point, not only in a separate markdown file) the master prompt's Three Autonomy Levels (section 61): LEVEL A (research: fully automatable, must not modify production), LEVEL B (experiment: may automate within existing security/resource/license/remote-execution/repository policy, must never bypass existing human-approval requirements for consequential actions), LEVEL C (production promotion: always human-governed, listed examples include merging to main, changing signoff/verification-oracle semantics, changing regression-selection-for-signoff policy, changing security/remote-execution policy). For LEVEL C specifically: confirm and cite the REAL existing enforcement this project already has for each listed example (git_governance.py's main/master push block for 'merging to main'; gates.py's PROMOTION_READINESS/SIGNOFF stage-gates for signoff changes; self_tuning_proposal_gate.py's protected list for gate/policy changes) rather than building new enforcement for things already covered -- name explicitly any LEVEL C item that has NO real existing enforcement today, as a flagged, NOT-closed-in-this-pass gap (do not attempt to build brand-new production-safety enforcement in this same pass; report it for a separate, dedicated effort).
3. Real tests for the above.

Check git status/diff before touching memory_router.py/CLAUDE.md. Run the new tests plus the full memory_router test suite. Commit your real, scoped change.

Write a report to .work/gap-close-capability-evolution-memory-governance-report.md. Report DONE (with what changed and commit hash) / BLOCKED, with a one-line test summary, and an explicit list of any LEVEL C item found to have no real existing enforcement.`, {label: 'build:memory-governance', phase: 'Build', model: 'claude-opus-5'})

const buildAcceptanceTestsAndDocs = await agent(`${CONTEXT}

## Your task: Stage 1 acceptance tests A-H (whichever weren't already covered by earlier build steps) + Stage 0/1 required artifacts + CLAUDE.md consolidation

Real Stage-0 audit findings:
${auditBundle}

All prior Build-phase steps (research-ingestion, research-architect, routing, memory-governance) are committed -- read their real reports (.work/gap-close-capability-evolution-*-report.md) to know exactly what landed and which acceptance tests (A-H, master prompt section 23) they already covered with a real test (B/C/D/E/F/H per the earlier steps' own instructions) versus which remain uncovered (likely A: research-ingestion produces a valid, provenance-carrying, no-invented-evidence ResearchEvidenceCard for one real/synthetic input document end-to-end; G: a new card overlapping an existing evidence card is correctly linked with an overlap/new/contradiction status).

Build, in order:
1. Any of Tests A-H not yet covered by a real, passing test from an earlier build step -- add them now, end-to-end (actually invoking the real installed skill/agent/schema chain on a synthetic input, not a mocked unit test of one function in isolation).
2. \`research/current_harness_baseline.md\` -- generate this for real from the actual Stage-0 audit findings above (the Capability/Status/Relevant Files/Owning Agent/Owning Skill/Graph Node/Blackboard-State/Memory Layer/Evidence Mechanism/Known Limitation/Reuse Potential table, master prompt section 4), not a fabricated/generic version.
3. A short CLAUDE.md addition (a few sentences, per this project's own Methodology Consolidation Rule -- point at research/README.md and the new skill/agent for detail, do not inline the whole design here) noting the new permanent research-ingestion + research-architect capability exists, and that Stage 2 (analyzing real external documents) and Stage 3 (implementing approved capability changes) require explicit separate invocation, not automatic follow-on. Check git status/diff on CLAUDE.md first -- it is a very likely concurrent-edit collision point this session; use the hand-scoped patch technique.
4. Run the FULL project test suite (python -m pytest dv_harness_tests/ -q) and confirm no regression versus its pre-existing pass/fail baseline (report the real before/after counts if you can determine the prior baseline from a recent commit's own CI record or a fresh clean-tree run comparison; at minimum report today's real full-suite result).

Write a report to .work/gap-close-capability-evolution-acceptance-tests-report.md, including the literal A-H test-by-test present/passing table and the real full-suite pytest result. Report DONE / BLOCKED.`, {label: 'build:acceptance-tests-docs', phase: 'Build', model: 'claude-opus-5'})

phase('Review')

const buildBundle = `
### Build: research-ingestion
${buildDocIngestion}

### Build: research-architect
${buildResearchArchitect}

### Build: routing + /research command
${buildRoutingAndCommand}

### Build: memory governance + autonomy levels
${buildMemoryGovernance}

### Build: acceptance tests + docs + CLAUDE.md
${buildAcceptanceTestsAndDocs}
`

const review = await agent(`${CONTEXT}

Independently review this entire Stage 0 (audit) + Stage 1 (install permanent research/capability-evolution capability) installation for DV Agent Harness L5, against the master prompt's OWN required Stage 1 report format (section 24) and OWN Stage 1 Acceptance Tests (section 23, A-H). Do not accept any build report's own DONE claim without independently re-running something real yourself.

Full audit-phase findings:
${auditBundle}

Full build-phase reports:
${buildBundle}

Read every real .work/gap-close-capability-evolution-*-report.md file in full first.

Independently verify:
1. For each of Tests A-H: actually run it yourself (the real test file/command each build report should have named) and confirm it genuinely passes, and confirm it tests what the master prompt actually asks (not a weaker proxy).
2. Confirm Test D concretely: run 'git log --oneline' for this workflow's commits and confirm zero production dv_harness/*.py *behavior* changed in a way that could affect a verification PASS/FAIL determination -- the only production-adjacent changes allowed are the reuse-extensions this workflow's own build steps made deliberately (inference.py's evidence-category extension, memory_router.py's new 'kind' dispatch entries) -- confirm these are additive/backward-compatible, not behavior-changing for any existing caller (run the full pre-existing test suite and confirm every previously-passing test still passes).
3. Confirm the REUSE-before-ADD principle was actually honored: for each of research-ingestion/research-architect/ResearchEvidenceCard/CapabilityEvolutionCandidate/routing, was a real existing mechanism actually reused/extended (cite it) rather than a parallel one invented? Flag anything that looks like an unnecessary duplicate.
4. Confirm Stage 2 and Stage 3 were correctly NOT started -- no real external document was analyzed against L5 in this pass, no production capability change was implemented/promoted, nothing was pushed to main/master.
5. Run the full project test suite yourself (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
6. Check git hygiene across every commit this pass made -- given how many other workflows are concurrently touching this repo, confirm no commit accidentally swept in unrelated concurrent work, and confirm CLAUDE.md/.claude/agents/ROSTER.md end up internally coherent (no duplicated/contradictory sections from a concurrent-edit collision).

Produce the master prompt's EXACT required Stage 1 report (section 24), filled with real values:

RESEARCH CAPABILITY INSTALLATION: PASS / FAIL

- files added
- files modified
- Agent added
- Skill added
- router changes
- command/front-door changes if any
- graph nodes reused
- graph nodes added
- conditional edges added
- Blackboard/state changes
- memory integration
- evidence/confidence integration
- tests executed (the real A-H table)
- short-invocation test result
- backward compatibility
- rollback strategy

Then also explicitly answer, per master prompt section 47's "Before/After Graph Report": BEFORE and AFTER counts of Agent/Skill/Graph-node/conditional-edge, with a real reason for each net-new item and why an existing one could not be reused instead.

If FAIL: say so plainly and name exactly what would need to change for a re-run to pass -- do not soften a genuine FAIL into an inflated PASS.`, {label: 'review', phase: 'Review', model: 'claude-opus-5'})

return { auditBundle, buildBundle, review }
