# AI Agent Harness L5 - Project Instructions

# L5DGVA Constitution

**This section is the highest product/architecture authority in this file --
above ordinary architecture rules, the Module Index, workflow rules,
migration rules, implementation rules, and agent/skill rules below.** No
`Repository Root Contract` section was found elsewhere in this file to
preserve under that name (searched, not assumed absent); if one exists in a
sibling document, this section does not supersede it. Likewise, no section
literally named `Module Index` was found elsewhere in this file (searched,
not assumed absent) -- the phrase above names where such an index would sit
in the authority ordering, should one be added later; it is not a claim that
a currently-resident section by that name exists today. Full text, rationale,
and the milestone-scoping discussion also live in the canonical,
non-resident document `docs/architecture/L5DGVA_CONSTITUTION.md` (kept in
sync with this section, never contradicting it). Enforced in code:
`dv_harness/constitution_gate.py`, tested in
`dv_harness_tests/test_l5dgva_constitution.py`.

No equivalent "L5DGVA Constitution" / "Highest Governing Principle" /
"Article 0" section existed anywhere else in this file before this update
(checked by grep, not assumed) -- this is a new top-level authority, not a
consolidation of a prior one. Several existing detailed sections already
implement pieces of what Article 0 names as the product's continuous-
evolution capability; Article 0 cross-references them below rather than
restating their content. **M4.6 CLAUDE Context Normalization update**: the
line-number citations this paragraph used before M4.6 went stale the moment
detailed sections moved out of this file into the governance registry's
task-scoped detail documents -- replaced below with document-based
citations, which do not drift the next time a section moves:
**Research Front Door** and **Research Stage Boundaries**, **Confidence
Calibration**, **Cross-Project Pattern Mining**, **Self-Learning Readiness
Matrix**, **User-Correction-Triggered Capability-Evolution Gap Detection**,
**Human Correction Learning**, and **Knowledge Conflict Resolver** all live
in `docs/architecture/canonical_detailed_governance/KNOWLEDGE_MEMORY_RESEARCH.md`;
**Cross-Loop Coupling: Repeated Failure -> Auto-Filed Capability Candidate**,
**...Coverage-Closure Stall -> ...**, **Controlled Experiments Are Executed,
Not Attested**, and **Shadow / Digital-Twin Validation** all live in
`docs/architecture/canonical_detailed_governance/EXECUTION_REMOTE_REGRESSION_RCA.md`;
**Digital Thread / Full Traceability** lives in
`docs/architecture/canonical_detailed_governance/GOVERNANCE_SAFETY_AUDIT.md`;
**Engineering Memory Policy** stays in this file, below (ALWAYS_ON). Every
document named above is registered in `dv_harness/governance_registry.json`
and retrievable via `TASK_SCOPED_GOVERNANCE_RETRIEVAL`
(`dv_harness/governance_registry.py`) -- see the **Governance Document
Routing** section below.

## Article 0 — Highest Governing Principle

L5DGVA 是一個 location-independent、evidence-grounded、knowledge-driven、
continuously evolving 的 Multi-Agent DV Platform。

它能針對 IP、Subsystem、System-Level，自動完成從 OpenSpec Intake、DV
Knowledge Retrieval、vPlan、VIP/UVM Verification Environment Generation、
Remote EDA Execution、Regression、RCA、Functional Coverage Closure、
Requirements Traceability 到 Signoff 的完整驗證閉環。

它並同時從：

1. 外部 DV Research / Papers / New Technologies

以及：

2. 內部 Project / User Interaction / Generation / Debug / RCA / Coverage
   Closure / Signoff Experience

持續萃取、驗證、晉升與重用工程知識，使下一次 Verification Generation 更準確、
更自動、更高品質。

**Normative English form:**

> L5DGVA is a location-independent, evidence-grounded, knowledge-driven,
> continuously evolving Multi-Agent DV Platform.
>
> Its purpose is to automatically support IP, Subsystem, and System-Level
> verification from OpenSpec Intake through DV Knowledge Retrieval,
> Discovery, vPlan, VIP/UVM Verification Environment Generation, Remote EDA
> Execution, Regression, RCA, Functional Coverage Closure, Requirements
> Traceability, Signoff, and Experience Consolidation.
>
> L5DGVA continuously improves by extracting, validating, promoting, and
> reusing engineering knowledge from:
>
> A. external DV research, papers, methodologies, tools, and new
>    technologies; and
> B. internal project execution, user interaction, clarification,
>    generation decisions, simulation, debug, RCA, regression, coverage
>    closure, and signoff experience.

**Every architecture, migration, implementation, agent, skill, workflow,
graph, governance, testing, and product decision SHALL be evaluated against
Article 0. No local optimization may silently weaken Article 0.**

## The Five Constitutional Dimensions

**P1 -- LOCATION_INDEPENDENT.** L5DGVA must support copy/clone/move/rename/
archive-extract, different users, different repository paths, Windows
bootstrap, WSL2, and Docker-mounted runtime. Canonical product identity must
not depend on the absolute bootstrap path, the directory basename, a
specific username, a specific gateway/remote-EDA hostname, or a specific
personal Obsidian Vault path. Host/environment identities belong in
configuration/execution profiles. (Enforced today: `dv_harness/l5dgva_repo.py`,
`dv_harness/execution_profile.py`, `dv_harness/root_hygiene_gate.py`, the
M1/M1D relocation + deployment-copy qualifications.)

**P2 -- EVIDENCE_GROUNDED.** Important verification decisions must be
grounded in evidence: Hypothesis -> Evidence -> Confidence -> Validation ->
Action. This section does not replace the Evidence Truth Rule immediately
below, which already contains this project's stronger, detailed evidence
rules -- reference/reuse them rather than restating. AI inference alone is
not sufficient evidence.

**P3 -- KNOWLEDGE_DRIVEN.** L5DGVA must retrieve and evaluate applicable
engineering knowledge before important generation/debug/coverage decisions
where the workflow supports it, from the KC Engine, M1-M5 Memory, Obsidian
integration, validated engineering knowledge, research-derived knowledge,
and project-derived experience (see the Engineering Memory Policy section
below). Knowledge is not operational merely because it is stored --
operational knowledge requires evidence of retrieval -> applicability
validation -> agent consumption -> decision/action impact -> recorded
evidence.

**P4 -- CONTINUOUS_EVOLUTION.** L5DGVA must support two learning loops:

- **EXTERNAL LEARNING LOOP**: DV Research / Paper / New Technology ->
  Research Intelligence -> Distillation -> Evidence / Provenance ->
  Applicability -> Capability Candidate -> Experiment / Validation ->
  Capability Evolution. (See Research Front Door / Research Stage
  Boundaries / Confidence Calibration sections above.)
- **INTERNAL LEARNING LOOP**: User Interaction / Project Execution ->
  Generation / Simulation / RCA / Regression / Coverage / Signoff ->
  Experience Extraction -> Evidence Grounding -> Applicability /
  Generalization -> Knowledge Promotion -> Capability Evolution. (See
  Cross-Loop Coupling / Self-Learning Readiness Matrix /
  User-Correction-Triggered Capability-Evolution Gap Detection sections
  above.)

A single project observation must NOT automatically become a universal
engineering rule.

**P5 -- END_TO_END_DV_ALIGNMENT.** L5DGVA's product goal is not merely code
generation. The intended verification lifecycle is: OpenSpec Intake -> DV
Knowledge Retrieval -> Discovery -> Minimal Structured Clarification when
necessary -> vPlan -> VIP/UVM Verification Environment Generation ->
Sequence/Scenario/Firmware integration -> Checker/Scoreboard/Assertion ->
Build/Smoke -> Local or Remote EDA Execution -> Regression -> RCA/Debug ->
Functional Coverage Analysis -> Coverage-Hole Closure -> Requirements/
Evidence Traceability -> Waiver handling where applicable -> SIGNOFF_READY
-> Signoff -> Experience Consolidation -> COMPLETE.

## Generic Verification Level Principle

The same generic L5DGVA core serves IP, SUBSYSTEM, and SYSTEM_LEVEL scope --
three independent duplicated orchestration engines must not become the
default architecture. Differences are expressed through evidence-supported
extension mechanisms (level profiles, protocol profiles, topology,
capability adapters, registries, configuration) where appropriate. The
final product must prove all three levels end-to-end.

## Maximum Verified Capability Union

The final Canonical L5DGVA is NOT a v50 copy, and NOT a Parent overwrite. It
is the **Maximum Verified Capability Union** of all approved migration
sources, followed by semantic-conflict resolution, defect correction,
useful-capability operationalization, canonical architecture improvements,
and new operational capabilities. Maximum capability union does NOT mean
maximum file union -- duplicate, obsolete, generated, inferior, or
non-operational duplicate implementations do not need to survive as
duplicate files. No verified source capability may be silently lost. (See
`.work/phase3-dual-repo-consolidation/CANONICAL_CAPABILITY_SUPERSET_MATRIX.md`
for the live tracking artifact.)

## Capability Operationalization Standard

`IMPLEMENTED` / `WIRED` / `TRIGGERED` / `CONSUMED` / `OBSERVED` / `TESTED` --
a module/file/method existing is NOT sufficient to claim an operational
capability; telemetry existing is NOT equivalent to downstream consumption;
tests existing are NOT by themselves proof of real workflow consumption.
Preserve truthful PARTIAL/DORMANT/AUDIT_TELEMETRY states. Do not inflate
completion status.

## Continuous Research Evolution

`CONTINUOUS_RESEARCH_EVOLUTION`: DV Paper / New Technology -> Research
Ingestion -> Distillation -> Claims/Method Extraction -> Evidence/Provenance
-> Applicability Analysis -> L5DGVA Capability Gap -> Capability Candidate
-> Experiment/Validation -> Accept/Reject -> Canonical Capability Evolution.
A research summary document alone does NOT qualify this capability as
operational -- research must be capable of affecting validated future
L5DGVA capability to qualify as a closed loop. (Real current status: see
`docs/architecture/canonical_detailed_governance/KNOWLEDGE_MEMORY_RESEARCH.md`
-- Research Front Door / Cross-Loop Coupling / Self-Learning Readiness
Matrix moved there during M4.6, and the capability matrix's RESEARCH_*
rows.)

**Research Front Door (kept ALWAYS_ON — discoverable without the master
prompt in hand, per the same principle this file's own routing section
states above)**: the entry point is `dv-harness research`, not
`/research` — `.claude/commands/` does not exist in this repo. The route
is fixed and it STOPS: `.claude/skills/research-ingestion/SKILL.md` ->
prior-evidence lookup -> `.claude/agents/research-architect.md` ->
Human Approval Gate. A research-capability-evolution change reaches
production code only after
`dv-harness approve RESEARCH_CAPABILITY_EVOLUTION --note ... --reviewer-id ...`
(the real `HUMAN_APPROVAL_STAGE` the code imports — never a retyped
command name). Full detail:
`docs/architecture/canonical_detailed_governance/KNOWLEDGE_MEMORY_RESEARCH.md`.

## Continuous Project Experience Learning

`CONTINUOUS_PROJECT_EXPERIENCE_LEARNING`: the system must learn, with
evidence and applicability control, from Intake, User Interaction,
Clarification, DUT/RTL/VIP/Topology Discovery, Generation Decisions, UVM
Architecture, Sequence/Scenario Generation, Firmware/IRQ Integration, Build
Failures, Simulation Failures, Debug, RCA, Fixes, Regression, Coverage
Holes, Coverage Closure, Waivers, and Signoff -- via: Project/User
Experience -> Experience Candidate -> Evidence -> Context -> Applicability
-> Confidence -> Generalization -> Knowledge Promotion -> Future Retrieval
-> Better Future Verification Generation.

**Clarification Learning**: the future ClarificationService should learn
from interaction -- question asked -> user answer -> later evidence proves
the answer was auto-discoverable -> `QUESTION_AVOIDABLE` -> improve
discovery strategy -> reduce unnecessary future clarification. This does
NOT authorize guessing; auto-discovery must remain evidence-grounded.

**Generation / RCA / Coverage learning**: preserve and evolve learning from
(generation decision -> generated environment -> result -> failure ->
correction -> successful outcome -> reusable generation experience),
(failure -> hypothesis -> evidence -> root cause -> fix -> rerun ->
validated RCA knowledge), and (vPlan feature -> coverage hole -> root cause
-> stimulus/constraint/sequence/scenario change -> coverage delta ->
closure -> reusable coverage-closure experience).

**Experience Consolidation**: `SIGNOFF_READY -> SIGNOFF ->
EXPERIENCE_CONSOLIDATION -> COMPLETE`. During execution, experience may
accumulate in M2 Job Memory; at project consolidation, M2 Job -> M3 Project;
cross-project validated engineering knowledge, M3 -> M4 Engineering;
organization-reusable knowledge, M4 -> M5 Organizational -> Obsidian. Not
claimed fully operational until M8/future qualification proves the closed
loop.

## Knowledge Authority Boundary

OpenSpec/Intake = requirement authority. Git/canonical implementation =
implementation authority. Runtime Evidence = execution truth. KC/Memory/
Obsidian = engineering knowledge/rationale. Knowledge must not silently
override authoritative requirement/runtime evidence -- a contradiction must
trigger evidence resolution/clarification.

## Canonical Platform Architecture (governance-level reference)

**ZONE 1 -- LOCAL_CONTROL** (WSL2): Claude CLI/Multi-Agent, Git/Worktrees,
OpenSpec/Intake, L5DGVA, Knowledge Brain, Generation, ExecutionService,
LocalBackend, Docker, RemoteEDABackend client. **ZONE 2 -- ACCESS_GATEWAY**:
access/transport only -- no L5 decision logic, no source-of-truth role.
**ZONE 3 -- REMOTE_EDA**: VCS, LSF, Verdi/FSDB, ZeBu, HAPS, Coverage --
execution plane, not implementation source of truth. Do NOT hard-code
specific gateway/remote host names into generic architecture; host
identities belong to execution profiles/configuration. This governance-only
update does not redesign or implement any missing future platform
component.

**Execution abstraction target** (not yet implemented -- do not claim
operational): L5 component -> ExecutionService -> ExecutionBackend
(LocalBackend / RemoteEDABackend); remote target: RemoteEDABackend ->
TelnetSSHTransport -> existing `remote_hop`/`remote_relay` -> Remote EDA.
The existing known-good transport is wrapped first, never unnecessarily
rewritten.

**Knowledge Brain target**: KC Engine + M1 Working + M2 Job + M3 Project +
M4 Engineering + M5 Organizational + KnowledgeService + Obsidian
Adapter/CLI/Vault integration + Multi-Agent consumers. Agents should consume
knowledge through the Knowledge architecture rather than each independently
implementing direct Obsidian behavior; Obsidian must not be a competing
requirement/implementation authority.

## Constitutional Anti-Drift Rule

No Agent, Skill, Workflow, Graph Node, Migration Wave, implementation task,
optimization, cleanup, refactor, or local test fix may silently redefine or
weaken Article 0. If a proposed change conflicts with Article 0 or one of
the five constitutional dimensions: (1) identify the conflict; (2) preserve
the current valid baseline; (3) report concrete evidence; (4) emit
`ARCHITECTURE_CONFLICT`; (5) STOP the conflicting change; (6) require
explicit architectural review. Do not weaken Article 0 merely to make
implementation or tests easier.

## Migration-Wave Compliance Reporting

Every migration wave reports `HIGHEST_PRINCIPLE_COMPLIANCE`:
`LOCATION_INDEPENDENT` / `EVIDENCE_GROUNDED` / `KNOWLEDGE_DRIVEN` /
`CONTINUOUS_EVOLUTION` / `END_TO_END_DV_ALIGNMENT`, each `PASS`/`PARTIAL`/
`FAIL` with evidence -- a wave may honestly report `PARTIAL` with a declared
future owner wave (e.g. `KNOWLEDGE_DRIVEN = PARTIAL, DEFERRED_TO = M8`).
Never report `PASS` without evidence.

## Milestone Capability Gates

`M1`: Canonical >= qualified v50 required baseline. `M8`: Canonical >=
Maximum Verified Capability Union of approved migration sources. `M13`/
Final: Canonical > Maximum Verified Capability Union of approved migration
sources. The final strict-superset gate requires `SOURCE_CAPABILITY_LOSS =
0`, `SOURCE_VERIFIED_CAPABILITIES_PRESERVED = 100%`,
`CANONICAL_NEW_OPERATIONAL_CAPABILITIES > 0`,
`CANONICAL_ENHANCED_CAPABILITIES > 0`, `CANONICAL_CAPABILITY_STRICT_SUPERSET
= PASS` -- never claimed early.

## Final Constitutional Acceptance

`L5DGVA_CONSTITUTIONAL_COMPLIANCE = PASS` is a mandatory final-product-only
acceptance requirement, additional to `CANONICAL_CAPABILITY_STRICT_SUPERSET
= PASS`. Final completion must eventually prove at least:
`LOCATION_INDEPENDENT = PASS`, `EVIDENCE_GROUNDED_DECISION_FLOW = PASS`,
`KNOWLEDGE_DRIVEN_GENERATION = PASS`, `CONTINUOUS_RESEARCH_EVOLUTION =
OPERATIONAL`, `CONTINUOUS_PROJECT_EXPERIENCE_LEARNING = OPERATIONAL`,
`IP_END_TO_END = PASS`, `SUBSYSTEM_END_TO_END = PASS`,
`SYSTEM_LEVEL_END_TO_END = PASS`, `VPLAN_TO_COVERAGE_SIGNOFF = PASS`,
`REQUIREMENTS_TRACEABILITY = PASS`, `KNOWLEDGE_PROMOTION = PASS`,
`AGENT_KNOWLEDGE_CONSUMPTION = OBSERVED`,
`CANONICAL_CAPABILITY_STRICT_SUPERSET = PASS`. Do not claim L5DGVA COMPLETE
before this constitutional gate passes. Neither this gate nor the
strict-superset gate is claimed by any intermediate wave, including M3.

## USB / PCIe Qualification Principle

USB = first Golden end-to-end qualification; the Reference USB Environment
must not be consumed before its approved qualification wave (M11). PCIe =
the genericity challenge after USB, with the criterion
`ZERO CORE ORCHESTRATION / GENERATION CHANGE` except approved protocol
profiles, adapters, data, and explicit extension points -- proving the core
is generic rather than USB-specific.

## Governance Document Routing (TASK_SCOPED_GOVERNANCE_RETRIEVAL)

Detailed, task-specific governance belongs in categorized documents, not in
this file — this file stays the compact, ALWAYS_ON router. Real registry:
`dv_harness/governance_registry.py` + `dv_harness/governance_registry.json`
(`get_entries_by_trigger()` routes a task's own keywords to the right
document; `check_reachability()` proves every registered path is real,
enforced by `dv_harness_tests/test_governance_registry.py`). Three tiers:
**ALWAYS_ON** (this file only), **TASK_SCOPED** (loaded when the task's
domain matches), **EVIDENCE_ON_DEMAND** (large source material, read only
for a specific cited question, never preloaded, never summarized into this
file). `MINIMUM_SUFFICIENT_CONTEXT` (Article 0 P3 KNOWLEDGE_DRIVEN):
retrieve only what a task's own trigger matches — knowledge-driven never
means load-all-knowledge.

**M4.6 CLAUDE Context Normalization** (canonical migration program):
this file was previously ~2.07 MB / 22,461 lines — nearly all of it
per-feature/per-module dated build narrative accreted directly into this
file rather than routed through this registry, which defeated
task-scoped retrieval's own purpose (an ALWAYS_ON file this large is
loaded on every task regardless of domain). M4.6 moved every detailed,
domain-specific section out **verbatim** (content and authority
preserved, zero deletions — every moved section is cited by its exact
original line range in `.work/phase3-dual-repo-consolidation/M4_6_.../
M4_6_CLAUDE_SECTION_INVENTORY.csv`) into 7 registered documents under
`docs/architecture/canonical_detailed_governance/`:

| Registry id | Document | Domain |
|---|---|---|
| `VIP_PROTOCOL_GENERATION` | `VIP_PROTOCOL_GENERATION.md` | VIP/UVM generation, protocol/register/RTL extraction, vPlan, coverage, AMBA, DE command.txt/pattern architecture, checker/scoreboard/signoff |
| `GUI_DASHBOARD_WEB` | `GUI_DASHBOARD_WEB.md` | Dashboard/web control plane, GUI cards/wizards, status bar, live events, REST endpoints |
| `EXECUTION_REMOTE_REGRESSION_RCA` | `EXECUTION_REMOTE_REGRESSION_RCA.md` | Remote/LSF execution, build/sim-script, waveform/FSDB, regression loop, RCA support |
| `INTAKE_CLARIFICATION_QUESTION` | `INTAKE_CLARIFICATION_QUESTION.md` | OpenSpec/intake, question queue, clarification loop |
| `KNOWLEDGE_MEMORY_RESEARCH` | `KNOWLEDGE_MEMORY_RESEARCH.md` | 5-tier Memory, Obsidian, research ingestion/distillation, confidence calibration, continuous-evolution loops |
| `GOVERNANCE_SAFETY_AUDIT` | `GOVERNANCE_SAFETY_AUDIT.md` | Safety-sandbox/rollback, dependency/supply-chain governance, change-impact/traceability, multi-agent policy |
| `HISTORICAL_AUDIT_NOTES` | `HISTORICAL_AUDIT_NOTES.md` | Retrospective `[CLOSED]`/"Already Satisfied" status markers -- provenance only, non-normative |

Full inventory, per-section classification, and evidence:
`.work/phase3-dual-repo-consolidation/M4_5_MASTER_RECONCILIATION/` sibling
directory `M4_6_...` artifacts (see that directory's `M4_6_FINAL_REPORT.md`).
`TOKEN_REDUCTION_MEASURED = NO` — the byte/line reduction above is a real,
measured file-size fact, not a claimed Claude-token saving (no token
telemetry combining this change with real usage exists yet).


## Core Operating Rules
- Graph is the global workflow authority.
- Blackboard stores current verification truth.
- Verification Memory stores historical verified engineering knowledge.
- Claude project/native memory may store stable project instructions, conventions, workflow rules and user preferences.
- Memory is prior knowledge, not current evidence.
- Any current root cause must be revalidated with current evidence.
- Human Override is always valid.
- Same regression batch must use the same source/build/config identity.
- LSF DONE is not equal to DV PASS.
- One submitted LSF job = one isolated Job Agent context.
- Important DUT/PHY/Register/VIP changes require Multi-Agent evidence acquisition plus independent synthesis.
- All actionable findings must close before Final Deep Audit.
- Any process/method/workflow validated in a session must be consolidated into the Harness's permanent engine/agent/skill assets, not left as one-off conversation state.
- Once a real deficiency/weakness/gap is confirmed by evidence (e.g. an audit pass), it must be closed by launching multi-agent implementation work on all currently-known confirmed gaps together, not queued one-at-a-time waiting for individual re-asks.


## Evidence Truth Rule

CLAUDE.md is project guidance, not verification evidence.

Never treat any statement in this file as proof of a current DUT behavior, bug, root cause or pass/fail condition.

Before accepting an engineering conclusion:
- inspect the current RTL/source when relevant,
- inspect/measure current waveform/FSDB when relevant,
- analyze current sim.log/checker/assertion evidence,
- verify current register/programming state when relevant.

If CLAUDE.md conflicts with current evidence, current evidence wins and this file must be updated.


## Engineering Memory Policy (2026-09-03)

Concrete before/during/after mechanics for the 5-tier Memory system
(`dv_harness/memory.py`, routed by `dv_harness/memory_router.py`, mirrored
into the DV-Knowledge Vault by `dv_harness/memory_vault.py` -- see
`docs/MEMORY_ARCHITECTURE.md`). This operationalizes the Core Operating
Rules' "Memory is prior knowledge, not current evidence" and the Evidence
Truth Rule above; it does not restate them.

**Before debugging**: Search relevant Project Memory and Engineering Memory
for the current protocol/scope/symptom before forming a first hypothesis
(`python -m dv_harness.memory_cli search --protocol <p> --text <symptom>`,
or the `memory-retrieval` skill). Any hit is a candidate hypothesis to rank
higher, never an accepted root cause -- validate it against current
RTL/VIP/sim.log/waveform evidence exactly as the Evidence Truth Rule
requires, and as `memory-confidence-gate` keeps historical-memory
confidence and current root-cause-evidence confidence from being conflated
into one number.

**During debugging**: Maintain Hypothesis -> Evidence -> Confidence -> Gap ->
Next-Best-Action for every open failure (`dv_harness.inference.score_confidence()`
/ `identify_gap()` / `next_best_action()` -- see debug-agent.md's "v20
Autonomous Inference"). Each stage transition is a real, persisted Working
Memory record (`memory_router.route_memory()` routes `kind="react_reasoning_step"`
there), not only conversation state.

**After verified PASS**: Record root cause, evidence, fix, verification, and
confidence together as one Engineering Memory record (`kind` one of
`root_cause`/`verified_fix`/`debug_lesson`, `verified: true`), then evaluate
promotion:
- Engineering -> Organizational happens ONLY through
  `memory_router.promote_to_organizational()`, never a direct write. It
  requires all three: the qualitative CLOSED/VERIFIED + single PASS +
  regression PASS/NOT_REQUIRED + re-audit CLEAN gate (`memory-consolidation`
  skill), a HIGH `inference.score_confidence()` result, and
  `confirmation_count >= ORGANIZATIONAL_MIN_CONFIRMATIONS` (2, i.e. a second
  independent run re-deriving the same root_cause/protocol -- not the same
  run reported twice). That third gate became reachable from the REAL
  writers only on 2026-09-04: the confirm-on-re-derivation dedup keys on
  (protocol, root_cause), but no gate's `JUDGMENT_FIELDS` ever judged
  `protocol`, so engine.py's two Engineering-tier writers wrote it as None
  on 30 of 31 real records and every re-derivation minted a fresh record
  instead of a confirmation -- the tier was unreachable by its own intended
  organic route, and only a test calling `MemoryGC.confirm()` directly had
  ever cleared it. Both writers now key on this run's canonical
  `protocol_router.resolve_protocol()` value, and
  `MemoryConsolidator.from_closed_finding()` confirms rather than duplicates
  on a re-derived closed finding. See `docs/MEMORY_ARCHITECTURE.md` and
  `dv_harness_tests/test_engineering_confirmation_accumulation.py`, which
  proves it end-to-end through real `run_stage()` gate-verified PASSes.
  Since 2026-09-04 "ONLY through" is enforced at the
  write boundary rather than trusted from callers:
  `memory_router.organizational_admission_gate()` re-reads the promotion
  provenance (`source_engineering_memory_id`) off the durable store -- the
  source record must be ACTIVE, engineering-tier, gate-validated, and carry
  an EARNED on-disk `confirmation_count` -- and demotes anything else to
  Working Memory with `organizational_admission_rejected`, before it can
  reach the shared Knowledge Center or mint an approval commit.
- A record failing any one gate stays at Engineering tier (or lower). Do not
  re-word the qualitative gate's inputs to force a pass.
- Reaching the Engineering tier at all is itself gated
  (`memory_router.engineering_admission_gate()`, 2026-09-03): a
  `verified: true` flag alone is not enough. The record must ALSO carry real
  `evidence` (or a gate-validated `verification` block), `confidence`
  HIGH/CONFIRMED (or that same gate-validated block), and a reusable claim
  (`root_cause`/`fix`/`lesson`, with `reusable` not `false`). A record
  failing any of those is written to Working Memory instead, carrying
  `engineering_admission_rejected` — this is the "Never promote an unverified
  hypothesis straight to Engineering" rule below as enforced code, not
  trusted prose. Do not pad an `evidence` field to clear it.

**Never**:
- Store secrets/passwords/tokens/credentials in any memory tier or vault
  note -- `memory_router.route_memory()` already hard-`REJECT`s any record
  whose `kind` is `credential`/`password`/`token`/`secret`; this is enforced
  code, not policy prose.
- Store giant logs or raw FSDB content in a memory record or vault note --
  cite a path/offset/signature only, per the Waveform Dump User Gate and
  Simulation Observability Default above.
- Promote an unverified hypothesis straight to Engineering or Organizational
  Memory -- it belongs in Working Memory (or Blackboard, for current-run
  state) until it clears verification.

**Debug-flow / regression / git-integration mechanics (2026-09-03,
obsidian-memory-debugflow, Workstream 3)**: `dv_harness.engine.DVHarness.
run_stage()`'s FAILURE_RECOVERY/RE_AUDIT stages, and `dv_harness.lsf_client
._write_job_tier_memory_on_terminal_reconcile()` (real UVM_ERROR/UVM_FATAL/
abnormal-termination signal), both call the same shared interface --
`dv_harness.memory_vault.build_failure_signature()` /
`search_related_memory_for_debug()` -- to surface Vault matches as prior
evidence BEFORE a debug attempt (never an assumed root cause: 不得直接假設
previous root cause == current root cause). AFTER a debug attempt: FAIL/
PARTIAL updates Job Memory only, no promotion; a RE_AUDIT PASS records
symptom/root_cause/evidence/fix/verification/confidence/git SHA/test/result
and always triggers (not always succeeds) the `promote_to_organizational()`
evaluation. Vault git commits (`memory.git_enabled`, opt-in) fire only on a
verified Job result, a Project Memory update, an Engineering Memory
promotion, or an Organizational Memory approval -- never on a Working Memory
update -- with message format `memory(<protocol>): <short description>`; a
real commit's SHA is written back onto the underlying JSON MemoryStore
record as `knowledge_commit_sha`, alongside its existing `rtl_sha`/`tb_sha`.
See `.work/obsidian-memory-debugflow-report.md` for full detail.

**Knowledge deduplication runs on the AUTOMATIC write path too (2026-09-04)**:
`memory_dedup.classify_note_candidate()` had exactly one caller, the manual
`dv-harness memory add` verb. The path that actually populates this project's
vault -- `memory_router._maybe_write_vault_note()`, which every real
ENGINEERING_MEMORY/ORGANIZATIONAL_MEMORY promotion goes through -- decided
create-vs-update from `memory_id` identity alone, so a second record with a new
id but the same root cause minted a second note (the spec's own
`USB3_LFPS_issue1/issue2/issue3` shape), and all 9 notes then on disk had
reached the vault without passing the gate once. The gate now runs on the
CREATE path: NEW creates a note, RELATED creates one AND writes real
`[[WikiLink]]`s to what it overlaps, DUPLICATE/UPDATE_EXISTING create nothing
and instead APPEND one recurrence line (carrying the real `memory_id`, and for
UPDATE_EXISTING the differing configuration/symptom) to the matched note's
`Related Knowledge` -- no existing section is ever rewritten. The corpus is
restricted to the candidate's OWN tier, because an Engineering ->
Organizational promotion is the same knowledge written again BY DESIGN and a
tier-blind gate would make the Organizational tier unwritable; Job/Project
notes are never gated at all. A dedup failure never blocks the write. See
`docs/MEMORY_ARCHITECTURE.md` and
`dv_harness_tests/test_memory_dedup_write_path.py`.


# AI Agent Harness L5 Canonical Identity

This directory is the canonical AI Agent Harness L5 baseline.
Do not rely on legacy version labels in older reference markdown files.

Core policy:
- Graph is global workflow authority.
- Blackboard is current truth.
- Memory is prior knowledge.
- Current evidence wins.
- Human Override is always valid.


## Execution Mode Gate

Every workflow must begin by explicitly declaring whether it is:
- LOCAL_ANALYSIS: 「這個是純本地讀檔分析（不碰伺服器、不跑 VCS）。」
- REMOTE_EXECUTION: 「這個需要連伺服器/跑模擬。」

Mixed workflows must be split into phases and the mode must be re-declared at every phase transition.
Local static findings must never be described as runtime/simulation evidence.


## SSH/Remote Transport Connection Intake

When a workflow declares REMOTE_EXECUTION and requires SSH/network transport to a Linux DV server
(real server credentials are involved), first ask the user whether SSH/network transport should be
established this session. Do not assume or silently attempt a connection.

If the user confirms, request these required fields before attempting any connection:
- user account
- password
- vc machine name (e.g. vchost-a, vchost-b)
- ssh machine name (e.g. host-a, host-b)
- DV Agent's working path/directory on the Linux server

The password must never be written into any evidence block, gate payload, state file, log, or
long-term/native memory. It is used only at the moment of the actual interactive connection and must
never be persisted by the harness — consistent with Remote Control Mode below ("Never expose SSH
private keys or credentials to Web/App or long-term memory"). The other four fields (account, vc
machine name, ssh machine name, working path) may be recorded as connection evidence since they are
not secrets by themselves.


## Remote Linux Execution (Persistent Relay)

`remote_hop.py`, `remote_relay.py`, `remote_exec.py`, and `source_identity.py` live in
`tools/remote/` within this `v50` project (not at the repo/project root).

Once a Linux DV server session has been established this session per the SSH/Remote Transport
Connection Intake gate above (user confirmed, relay started by the user in their own terminal), do
not ask the user to manually run and paste back individual Linux commands. Use:

  python tools/remote/remote_exec.py "<command>"

Check readiness first with `python tools/remote/remote_exec.py --status`. If READY, issue commands
directly. If DOWN, run `python tools/remote/remote_exec.py --reconnect`; if that reports the relay
cannot self-reauthenticate, ask the user to restart it in their own terminal (never embed VCPW in
any Claude-issued command) and stop until they confirm it is back up.

This does not remove the SSH/Remote Transport Connection Intake gate itself — establishing or
re-establishing a relay for the first time in a session still requires that confirmation. It only
removes the per-command manual-paste fallback once a relay is already confirmed READY.

`remote_relay.py` (which actually performs the login) must never be invoked from a Claude Code tool
call, including to test its own error paths — not even when the invocation doesn't type a password
into the command text. A persistent OS-level environment variable can supply required credentials
silently, defeating a "missing env vars" safety check without any password ever appearing in the
command itself (confirmed real incident, 2026-08-31 — see
`remote-linux-execution-bridge/SKILL.md`'s corresponding drift note). Test `remote_relay.py`'s logic
via unit tests against its pure `RelayServer.handle_request()` function, never via a live `--start`.

**2026-09-03 amendment (explicit user decision, single-user machine)**: on this specific machine,
confirmed single-user by the project owner, the user has explicitly decided to relax the prohibition
above: when `remote_exec.py --status`/`--reconnect` reports the relay is down mid-session, Claude
Code MAY automatically source a local, never-committed credential script (e.g. `replay.csh`, kept
outside version control and outside any path Claude reads or echoes) and invoke
`remote_relay.py --start` to reconnect, without asking the user each time. This is a deliberate
override of the 2026-08-31 incident's original blanket prohibition — the user judged that a
single-user machine reduces credential-exposure risk enough to accept fully autonomous reconnect in
exchange for not being interrupted. This amendment covers only mid-session RECONNECTION; the
SSH/Remote Transport Connection Intake gate above (asking before the FIRST connection of a session)
is unchanged and still applies.

Even under this amendment:
1. The password itself must still never be printed, echoed, quoted, or written into any evidence
   block, log, gate payload, or memory record.
2. Claude may source and invoke the credential script, but must never read or print the script's
   own contents.
3. This amendment is scoped to this machine/project only. If this harness is ever deployed to a
   shared or multi-user environment, this decision must be explicitly re-confirmed before it still
   applies there.

**2026-09-06 correction (Evidence Truth Rule -- current evidence overrides the paragraph above):**
this amendment describes a PROJECT-LEVEL policy decision, and it was never actually exercised. A
repo-wide check found zero `RELAY`-related events in `.dv-harness/events.jsonl` and an explicit prior
gap-close report (`.work/ai-debug-closed-loop-counter-implementation-report.md`) stating outright
that invoking `remote_relay.py` "remains a deliberate, policy-mandated human step... and was
deliberately NOT automated." So before this date, no Claude Code session -- in this project or
otherwise, so far as this project's own artifacts show -- had ever actually attempted the literal
"source the credential script, then run `remote_relay.py --start`" action this amendment describes.

On 2026-09-06 it was attempted for the first time, from an interactive Claude Code session with the
user's explicit real-time confirmation each time. The first two attempts (before, and after adding a
matching `PowerShell(. .\replay.ps1*)` entry to `.claude/settings.local.json` `permissions.allow`) were
both refused, with identical text, by Claude Code's own **auto mode classifier** -- a product-level
safety layer that sits BELOW and BEFORE this file's own project governance. The classifier's own
denial message names a remediation ("add a Bash permission rule to their settings") that did NOT work
on its own: `permissions.allow` is a different, lower-priority gate than the classifier itself checks.

**The actual working fix is a separate settings key: `autoMode.allow`** (Claude Code's own classifier-
configuration block, documented in its settings schema alongside `soft_deny`/`hard_deny`/
`environment`), not `permissions.allow`. Editing `.claude/settings.local.json` to add this key was
itself refused by the classifier when Claude attempted the edit directly -- the same self-modification
guard that blocks Claude from ever expanding its own permission surface unattended, regardless of the
user's in-conversation confirmation. Once the user made the edit THEMSELVES (adding
`"autoMode": {"allow": ["$defaults", "PowerShell(. .\replay.ps1*)"]}`), a subsequent Claude-issued
retry of the identical relay-start command PASSED the classifier -- confirming `autoMode.allow` (never
`permissions.allow` alone) is the real, working mechanism, and that this action is a `soft_deny` a
matching allow-rule genuinely clears, not an unconditional `hard_deny` as this section first
(incorrectly) concluded.

That first classifier-cleared attempt then hung indefinitely with no output and no successful
connection (`remote_exec.py --status` still reported DOWN after several minutes) -- a DIFFERENT,
NOT-yet-root-caused problem, since by that point the classifier had already let the command run. The
user separately ran the equivalent command in their own terminal and connected immediately (`vc8`/
`icr93`, real relay `READY`), which also surfaced a genuine path-shape issue: Claude Code's own default
working directory for this session is the PARENT of this project (`D:\DV\Task\DV_Agent_Harness_L5`),
not `v50` itself, so `replay.ps1` must be referenced as `./v50/replay.ps1` (or an equivalent explicit
path) rather than assuming a bare `. .\replay.ps1` always resolves correctly -- both forms are now
covered in `permissions.allow` and `autoMode.allow`. Whether that path mismatch, or something else
(a transient network stall), caused Claude's own hung attempt is NOT yet confirmed either way.

**Net honest status**: the classifier-level blocker is real, understood, and has a real, working,
user-applied fix (`autoMode.allow`). A full end-to-end autonomous reconnect -- Claude issuing the
command AND it actually reaching `READY` -- has not yet been observed; only a human-run reconnect has
succeeded so far. Treat autonomous reconnect as PARTIALLY_PROVEN: the permission layer is confirmed
clearable, the network/path layer is not yet confirmed to complete successfully end-to-end when Claude
itself issues the command. Continue to allow the user's own terminal as the reliable fallback until an
actual Claude-issued reconnect is observed reaching `READY`.

Source identity (PC vs. Linux) is verified per-project: git SHA comparison where a git remote exists
between PC and Linux, or the md5sum-based `SOURCE_ID` token (`source_identity.py`, see
`remote-linux-execution-bridge`) where it does not — never skipped outright.

Never request or print passwords, tokens, or credentials in any `remote_exec.py` invocation or
output.


## Background Job/Log Monitor Auto-Start

There is no Python code path that fires automatically the moment
REMOTE_EXECUTION_REQUIRED is declared -- that declaration is agent-supplied
evidence (an `execution_mode_validator` block embedded in the agent's own
message text), not an engine event with a hookable call site. "Automatic"
here means the same thing it means for the SSH/Remote Transport Connection
Intake gate above: a required action the agent takes as part of following
this protocol, not something the engine does on its own.

Once REMOTE_EXECUTION_REQUIRED has been declared and any needed SSH/Remote
Transport Connection Intake has completed, run:

    dv-harness lsf-watch-start --vcuser <account>

before submitting or expecting visibility into any LSF job this session.
This starts (or confirms already-running) a detached background process
that discovers every live job under that account, reconciles/analyzes any
job this harness has a registered `JobState` for, and maintains the
`regression.list` safety net (see `apply_verdict_to_file()` in
`dv_harness/uvm_generator/regression_list_manager.py`) for jobs that bypass
the generated environment's own Makefile-native `RECORD=1` mechanism. It is
a no-op if a watcher is already running for this project (tracked via a PID
file). Stop it with `dv-harness lsf-watch-stop` on a clean session end, or
when execution mode transitions back to `PURE_LOCAL_READ_ANALYSIS`.

**Cadence.** The watcher is a fixed-interval polling loop, not event-driven:
`regression_reporter.main()` runs one reconciliation cycle then sleeps
`--interval-minutes`. The default is **5 minutes**
(`regression_reporter.DEFAULT_INTERVAL_MINUTES`, the cadence the 2026-09-01
sim-output-layout design doc committed to). `self_check_list.md` #41 requires
job/simulation-log state to be re-confirmed at least every **10 minutes**
(`regression_reporter.SPEC_MAX_INTERVAL_MINUTES`), so 5 is inside the ceiling.
A slower `--interval-minutes` is still permitted but never silent:
`interval_compliance()` makes `lsf-watch-start` print a stderr warning and the
watcher log its real cadence on the first line.


## Waveform Dump User Gate

Before any waveform-enabled simulation, ask the user to confirm dump scope and dump level/depth.
Prefer minimum sufficient waveform based on the current failure cone.
Do not silently default to full-chip/full-depth dumping.

**Enforced against a real human answer, not a self-attested string (2026-09-04).** This rule had a
real gate since 2026-08-28 (`tools/verification_flow/focused_wave_debug_window_gate.py`, mandatory
on `WAVE_ANALYSIS` and `FAILURE_RECOVERY`), but it only required
`dump_scope_confirmed.confirmed_by` to be a NON-EMPTY STRING — a field the agent writing the
evidence block fills in itself. On the interactive path a human really was asked, so the string was
honest. On the autonomous path it cannot be: `engine.loop()` dispatches a headless
`claude -p --dangerously-skip-permissions` subprocess (`dv_harness/adapters/cli.py`) with the prompt
piped once through stdin and no live channel back to a human, so an in-flight AskUserQuestion is
unanswerable and the only way past the check was the LLM filling the field in — the gate passed
precisely when nobody had been asked. That is now closed:

- The gate re-derives the question_key from the DECLARED SCOPE and requires a persisted
  question-queue decision whose `current.source` is `question_queue.HUMAN_DECISION_SOURCE`
  (`dv_harness/waveform_dump_gate.py`). That is the same single sanctioned "a human really decided
  this" source `connectivity.enforce_bind_tier_policy()` / `apply_answered_questions()` already use
  for T3 binds — reused deliberately, so the harness cannot answer its own waveform escalation with
  its own earlier Tier-2 guess, and so there is one notion of "confirmed" in this codebase, not two.
  `confirmed_by` must additionally NAME that human (`current.decided_by`): a real decision cited
  with a false attribution is not a confirmation. A different scope is a different decision.
- The ask half is `dv-harness waveform-dump-scope ask --scope <scope> --level-or-depth <level>`,
  which files one canonically-keyed Tier-3 blocking question through the real `QuestionQueueStore`;
  a human answers it with the existing `dv-harness question-queue answer <Q-ID>`. There is no
  separate "waveform confirm" verb, because a second way to record a confirmation would be a second
  thing the gate has to trust. `dv-harness waveform-dump-scope status --scope <scope>` reports the
  same check (exit 2 when unconfirmed).
- **The engine files that question ITSELF on the autonomous path (2026-09-04, same-day gap
  close).** `ask_dump_scope_confirmation()` had exactly ONE caller in the repo — the human-typed
  `waveform-dump-scope ask` verb above. Nothing in `engine.py` called it, so a headless `claude -p`
  run that did not happen to shell out to that verb parked at WAIT_USER over an EMPTY queue:
  `question-queue list --blocking-only` showed nothing, `build_digest()` had nothing to report, and
  the human returning to the parked run had to read a Q-ID out of a `blocking_reason` string and
  hand-reconstruct the ask (scope AND level/depth) before `answer` had anything to answer. The loop
  opened and left behind no artifact capable of closing it — which made this section's own
  "parks at WAIT_USER with a real Q-ID" claim true only on the interactive path.
  `engine._file_waveform_dump_scope_question()` now runs at the exact point `run_stage()` assigns
  WAIT_USER, reading the scope and proposed level/depth off the SAME
  `focused_wave_debug_window_gate` evidence block the gate just rejected, and appends the real
  `question-queue answer <Q-ID> ...` command to the `blocking_reason`. It files a QUESTION and never
  a DECISION — only `answer_question()`, i.e. a human, writes one — so the human checkpoint is
  unchanged; what changed is that the human is handed an answerable Q-ID instead of an instruction
  to file one. It files nothing when the block declares no scope/level (that is agent error with its
  own remedy, not a missing human decision), nothing for a non-waveform NEEDS_USER_INPUT, and
  nothing when a question for that scope is already on file (`add_question()` appends rather than
  deduping, so re-filing would grow duplicates and re-arm `digest_batch_id` on a question a human is
  already sitting on). Every outcome is a real `WAVEFORM_DUMP_SCOPE_QUESTION_FILED` /
  `..._FILE_FAILED` event in `.dv-harness/events.jsonl`, and the filing is best-effort — a queue
  failure must never turn an already-correct WAIT_USER park into a crash.
- An unconfirmed dump scope now STOPS the autonomous loop instead of failing it. `gates.py` maps
  the gate's confirmation failures to the `NEEDS_USER_INPUT` verdict INTAKE already used, which
  `run_stage()` turns into `Status.WAIT_USER` and `loop()` returns on — so the question is not
  re-dispatched at a subprocess that cannot answer it until `max_stage_retries` is burned and the
  graph's FAIL edge is taken with the question still open. An UNRELATED failure of the same gate (a
  bad FSDB window, a missing evidence hash) stays an ordinary retry-worthy `GATE_FAIL`.
- Proven on the real path — the real gate subprocess, the real shipped graph, a real
  `QuestionQueueStore` on disk, and a real `loop()` that stops at WAIT_USER after exactly one
  dispatch and then gets through once a human answers — by
  `dv_harness_tests/test_waveform_dump_scope_human_confirmation.py`.

**Disclosed residual**, in the same spirit as `require_tier`'s and `require_qualified_conclusion`'s:
this closes the gate on the WAVEFORM decision specifically. The broader "a headless autonomous run
has no channel to ask a human anything mid-flight" limitation is unchanged — the fix is that such a
run now parks at WAIT_USER with a real Q-ID the ENGINE filed for a human to answer, not that the
subprocess gained a way to ask. The round-trip is still asynchronous and still requires a human to
come back to it: the run stops, and only `dv-harness question-queue answer` followed by a fresh
`dv-harness start --loop` resumes it.


## Simulation Observability Default

Normal simulation/regression defaults to FSDB OFF.
VIP trace/report may be enabled independently when supported by the current VIP/project.
Escalate to FSDB only when signal-level waveform evidence is needed.
FSDB enablement must pass the user-confirmed waveform scope/level gate.


## First-Failure Waveform Rerun

Initial simulation defaults to FSDB OFF.

If the simulation fails and signal-level evidence is required:
- rerun the failing testcase with targeted waveform enabled,
- confirm dump scope and level/depth,
- terminate at the first relevant failure/error/fatal/missing/mismatch,
- optionally retain only a minimal post-failure margin,
- do not run the full testcase unless later evidence is explicitly needed.

Regression-batch pipeline shape: push -> build -> verify -> run. The first pass runs the full batch
with FSDB OFF (per Simulation Observability Default). Only the subset of simulations that produced
a real UVM_ERROR or terminated abnormally (fatal/crash/timeout, not a clean UVM_FATAL-free PASS)
get selectively rerun with WAVE=1 (targeted waveform per First-Failure Waveform Rerun above) --
never blanket-rerun the whole batch with waveform on just because some tests failed.


## No Golden-Reference Content Mining

Forbidden methodology: "mine content from a completed reference environment -> have the generator
reproduce it -> verify it matches." This is not genuine generation, it is copying a finished answer
and relabeling the copy as if the harness had produced it from first principles. Even when a real,
locally-available reference environment exists (e.g. USB_UVM_Handoff) and even when the goal is
explicitly "100% parity" with it, protocol-behavior CONTENT — virtual sequence/pattern logic,
scoreboard checking logic, coverage bin/covergroup content, vPlan entries, command.txt scenario
content — must be derived from PRIMARY sources: VIP examples/user manual/source code/class
reference for branch-B/VIP-driven content, DUT RTL/PHY documents/programming guide for
branch-A/branch_fw-driven content (same sourcing already required by `vip-scenario-branch` and
`interrupt-event-dispatch` for any branch-B or branch-A/branch_fw modification — this rule makes
explicit that "modification" includes original content generation, not just edits to existing
files).

A completed reference environment may still be used AFTER independent generation, to measure and
report fidelity/gap (structural comparison, "how close did the independently-generated content
get") — that is legitimate verification, not generation. It must never be the source the generator
reads FROM to produce the content in the first place.


## Generated Content Language

Conversational replies to the user follow the user's own language preference (Traditional Chinese,
technical terms stay English). This is independent from generated deliverable content: all UVM
environment/testbench files, generator output, code comments, and any other artifact written into
the verification environment itself must be in English, regardless of what language the
conversation is conducted in.


## gh CLI + PR-Only Governance Policy (2026-09-03)

L5 governance requirement: an agent (Claude Code or any other automated
caller) may `git branch` / `git commit` / open a PR (`gh pr create`), but
must **never merge or push directly into a protected branch** (`main` or
`master`). Human review via PR is the only path onto those branches. This
is additive to, not a replacement for, the existing git-safety language in
`CORE/git-push-gate` (secret/scope/diff/commit-message discipline before
any push) and `CORE/git-workflow` (the full SYNC->...->PUSH lifecycle,
including its own "禁止自動 force push" rule) -- this section adds the
specific main/master-protection rule those two skills did not yet state.

**Real current state of this repo (re-checked 2026-09-04, kept honest
rather than assumed -- the 2026-09-03 wording below it was already stale
within a day, which is exactly why this paragraph is dated)**:
- A GitHub remote now EXISTS: `remote.origin.url =
  https://github.com/YuTienL/DV_Agent_Harness.git`, reachable
  (`git ls-remote origin` exits 0) but currently **empty** -- it returns no
  refs, and `master` has no upstream. So there is still no live PR workflow
  and, with no branches on the remote, no server-side branch-protection
  rule can exist on it yet. What HAS changed since 2026-09-03 is that a
  `git push origin master` from this repo is now a real, reachable
  operation rather than `fatal: No configured push destination.` -- i.e.
  the local hook gate below is now the thing that actually stands between
  an agent and a direct write to `master`.
- The local hooks below are **INSTALLED and live** (see enforcement item 2).
- `gh.exe` v2.99.0 is installed at `C:\Program Files\GitHub CLI\gh.exe` but
  is **not on PATH**, including in a fresh shell -- invoke it by full path
  until that is fixed. (An earlier build report claimed "a new terminal
  will see `gh` on PATH"; that claim was false and is corrected here.)

**Layered enforcement**:
1. **Primary (still ASPIRATIONAL here): server-side branch protection** on
   `main`/`master` requiring PR review before merge, disallowing direct
   pushes. This is the authoritative gate -- it holds even if a local hook
   is missing or bypassed. Not in force today: the `origin` repo is empty,
   so it has no branches to protect yet. Set this up as soon as the first
   branch is pushed; until then layer 2 is the only gate.
2. **Secondary (INSTALLED AND LIVE, verified 2026-09-04 --
   `git config --get core.hooksPath` returns `tools/git-hooks`; it was
   activated on 2026-09-03 *after* the original build task's own report was
   written, which is why that report and this section both used to say
   "NOT YET INSTALLED"): local
   `tools/git-hooks/pre-push` and
   `tools/git-hooks/pre-merge-commit`**, backed by
   `dv_harness/git_governance.py` (`dv-harness git-guard`). These detect an
   AI-agent execution environment using the same env-marker pattern
   `tools/remote/remote_relay.py`'s own Layer 2 guard already established
   (`AI_AGENT_ENV_MARKERS`, reused via import -- not duplicated) and BLOCK
   (non-zero exit, which git treats as hook failure) a direct push/merge
   into `main`/`master` from that environment. A human pushing/merging from
   their own interactive terminal (no agent marker present) is never
   blocked by this gate -- see `tools/git-hooks/README.md` for install
   (`git config core.hooksPath tools/git-hooks`; note git does NOT clone
   `core.hooksPath`, so every fresh clone must re-run that one line) and
   the deliberate fail-open behavior when Python is unavailable.
   This gate is proven end-to-end by `dv_harness_tests/test_git_hooks_e2e.py`,
   which drives a REAL `git push` and a REAL `git merge --no-ff` in a
   throwaway repo using these same hook scripts and asserts git itself
   aborts the operation, nothing lands on the remote, and a
   `GIT_GUARD_DECISION` reaches `dv-harness audit` -- so the claim in this
   section is a tested claim, not a description. Those tests also assert
   this repo's own `core.hooksPath` is still set, so the "INSTALLED AND
   LIVE" statement above cannot silently go stale again.
3. **Change-budget / blast-radius gate (2026-09-06, ADDITIVE — it never
   relaxes layers 1-2)**: `dv_harness/change_blast_radius.py`, run by the
   SAME `dv-harness git-guard` invocation as layer 2, but only on a
   push/merge layer 2 already ALLOWED — so it can turn an allow into a
   block and never a block into an allow. Layers 1-2 ask WHERE a change
   lands; this asks HOW FAR IT REACHES, from three measured (never
   self-declared) signals: files touched in the real diff (via
   `change_impact.changed_files()`), the transitive importer closure of the
   changed `dv_harness/*` modules from a real `ast` parse of the package's
   own imports, and whether the change edits a file that IS a gate (derived
   from `autonomy_levels.LEVEL_C_ENFORCEMENT`'s checked `cites` table, plus
   `tools/git-hooks/`). Over threshold (`WIDE`, or any `GOVERNANCE` file) an
   AGENT push is blocked until a human records a real approval under
   `dv-harness approve CHANGE_BLAST_RADIUS` whose note carries that
   assessment's `digest` — the pin is what stops it degrading into a
   permanent blanket bypass, since growing the change moves the digest and
   retires the approval. A human's own push is never gated on change size,
   same rule as layer 2. No real diff (no git, new branch with no
   merge-base) ⇒ `NOT_ASSESSABLE` and allowed: an environment problem must
   not masquerade as a policy finding. Inspect any range without pushing via
   `dv-harness blast-radius --base <rev> [--head <rev>]`. Decisions land as
   `BLAST_RADIUS_DECISION` in the same `.dv-harness/events.jsonl` trail.
   Proven by `dv_harness_tests/test_change_blast_radius.py`, which drives a
   REAL `git push` of a governance-file change in a throwaway repo, asserts
   git aborts it and nothing reaches the remote, then records the real
   approval and asserts the identical push now succeeds — and separately
   asserts a `CHANGE_BLAST_RADIUS` approval CANNOT unlock a protected-branch
   push, i.e. that this layer cannot be used to get around layer 2.

Every `git-guard` decision that touched a protected branch is logged as a
`GIT_GUARD_DECISION` event in `.dv-harness/events.jsonl` -- the same real
audit trail `dv-harness audit` already surfaces (see
`.claude/agents/audit-change-governance-agent.md`, the agent responsible
for reading this trail back and answering "what changed, by what/whom,
when, with what evidence, is it reversible" from real sources only).

`gh` (GitHub CLI) is the sanctioned tool for opening/inspecting PRs
(`gh pr create`, `gh pr view`, `gh pr checks`) once a remote exists. An
agent may run any read-only or PR-creating `gh`/`git` command freely; it
must never run `gh pr merge` (or an equivalent `git push`/`git merge`
straight onto `main`/`master`) itself -- that action is reserved for a
human, per this section's own rule and `git-guard`'s enforcement of it.


## Remote Control Mode
Claude Web/App may control this local Claude Code session through Remote Control.
Remote Control is transport only; Harness governance remains authoritative.
Never expose SSH private keys or credentials to Web/App or long-term memory.


## Environment Generation Mode

Before CREATE ENVIRONMENT, select:
- SUBSYSTEM_MODE: build a protocol/subsystem environment.
- SYSTEM_LEVEL_MODE: select/reuse completed subsystem environments and compose Full-SoC/System-Level environment.

If a required subsystem is missing in SYSTEM_LEVEL_MODE, build it through SUBSYSTEM_MODE then return to composition.

**Dispatched in code at the generation entry point (2026-09-04), not left to the agent.**
`environment_mode_router.resolve_environment_mode()` had computed this decision on every stage
since 2026-09-01, but its result landed only in `route_info["environment_mode_decision"]` — the
prompt and the ReAct record. Nothing branched on it: the one official CREATE ENVIRONMENT entry
point, `tools/generate_protocol_uvm_environment.py` (the script all ten
`.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` invoke), called `ProtocolEnvGenerator`
unconditionally, so a genuine two-subsystem request silently produced ONE subsystem environment
and `soc_environment_composer.compose_soc_environment()` fired only if an agent happened to know
to hand-assemble a `system_level_validator` evidence block for the SYSTEM_LEVEL stage instead.
That script now routes through `dv_harness/uvm_generator/create_environment.py`, which:
- resolves the mode with the real router and dispatches to `ProtocolEnvGenerator` (SUBSYSTEM_MODE)
  or `compose_soc_environment()` (SYSTEM_LEVEL_MODE) — a branch in FRONT of the existing path, so
  a single-protocol manifest still generates byte-identically;
- composes only from the REAL registry (`read_registered_subsystem_entries()`, written solely by
  `engine.py`'s `_persist_subsystem_registry_entry()` on a gate-validated SIGNOFF PASS), never
  from what the caller claims;
- REFUSES with `SubsystemModeRequiredError` naming the missing subsystems rather than composing
  the registered subset — the "build it through SUBSYSTEM_MODE then return to composition" rule
  above as enforced code, not trusted prose;
- raises `EnvironmentModeUnresolvedError` on a request that names nothing, honoring
  `environment_mode_policy.json`'s `mode_must_be_explicit_before_generation` instead of defaulting.

The SYSTEM_LEVEL stage half is now proven through the REAL entry point too: the composer's only
prior test called the private `_compose_soc_environment_files()` directly, so the chain gate
evidence → `gates.py` verdict → PASS branch → `compose_soc_environment` → blackboard → event log
had never been executed end to end. `dv_harness_tests/test_system_level_soc_composition_wiring.py`
drives a real `DVHarness.run_stage("SYSTEM_LEVEL")` through all 14 real
`STAGE_GATES["SYSTEM_LEVEL"]` scripts to a real PASS and asserts the real `SOC_ENVIRONMENT_COMPOSED`
event and real generated `soc_tb_top.sv` content, plus the negative case (an unregistered
subsystem fails the stage and composes nothing).

**Two limits, disclosed rather than implied closed.** (1) `cross_subsystem_scenarios()` /
`end_to_end_scoreboard()` / `system_coverage()` still raise `NotImplementedError` on purpose:
that is protocol-BEHAVIOR content, which "No Golden-Reference Content Mining" requires be sourced
from primary per-subsystem VIP/DUT evidence, and a registry entry carries only identity/
qualification metadata. Closing them needs a real cross-subsystem topology descriptor
(address/interrupt/DMA maps) that does not exist yet. (2) This harness repo's own
`subsystem_environment_registry.json` is still legitimately EMPTY and mechanism #14 has never
fired in its production history — it has no multi-subsystem project of its own. The mechanism is
proven to fire when a real project supplies real registered subsystems; it was not made to "have
fired" here by writing fabricated registry entries into this project's real audit trail.

**The SYSTEM_LEVEL verdict now stands on the REAL cross-subsystem analysis, not only on
agent-typed evidence (2026-09-05).** Two disconnected tracks had been built for Flow B and never
joined. Track A (`environment_mode_router` → `create_environment.py` →
`soc_environment_composer.compose_soc_environment()`) was engine-wired but composed blind: its only
import was `.generator`. Track B (the `SYS-1..40` family — `subsystem_discovery.py`,
`system_resource_inventory.py`, `system_readiness.py`, `system_topology_analysis.py`, ...) does the
real evidence-grounded work — shared-resource conflict detection, active-driver-ownership blocking,
address/clock-reset reconciliation — but was reachable ONLY from human-typed `dv-harness system-*`
CLI verbs. Most seriously, `grep -rln dv_harness tools/verification_flow/system_level_*.py` matched
NOTHING: every one of the gates that actually decides SYSTEM_LEVEL PASS/FAIL was a pure JSON-shape
check over the agent's own evidence text, so a composed system environment could pass every one of
them on hand-typed evidence with zero real cross-subsystem verification.

`system_resource_inventory.real_cross_subsystem_findings()` is the wire — it calls the existing
`analyze_selected_subsystem_resources()` front door (so SYS-1's refusal to analyze an unselected
set is not bypassed) and flattens the result for a verdict. Three real consumers now use it:
- `system_level_resource_contention_gate.py` FAILs `ACTIVE_DRIVER_CONFLICT_UNRESOLVED` when the
  real analysis stopped/held automatic integration, and `SHARED_RESOURCES_CONTRADICTED` when the
  plan declares no shared resources at all while the real analysis found
  SAME_PHYSICAL/SHARED_LOGICAL relationships — the hand-typed "all clear" case.
- `system_level_composition_gate.py` FAILs `ACTIVE_DRIVER_CONFLICT_UNRESOLVED` when the subsystems
  the composition NAMES carry an unresolved ownership conflict, whatever its per-subsystem
  `interface_compatibility`/`clock_reset_compatibility` "PASS" strings claim.
- `compose_soc_environment(entries, manifest, root)` consults the same analysis BEFORE composing
  and raises `CrossSubsystemIntegrationBlockedError` rather than emitting a `soc_tb_top.sv` that
  instantiates two subsystems whose ACTIVE agents both drive one SoC port; what the analysis said
  is recorded in `soc_composition_manifest.json`'s `cross_subsystem_analysis`.

DETECTION is what was wired; ARBITRATION is untouched. A DRIVER_CONFLICT still STOPS at BLOCKED
and still needs a human to decide which subsystem owns the interface — SYS-12's
`SYS12_PREFERRED_MODEL` is carried through as text for that human, and nothing added here picks a
winner, resolves a conflict, or crosses SYS-39/40's approval boundary. Where the real analysis
cannot run over real evidence (no registry, fewer than two subsystems, environments not on disk)
every consumer reports an explicit `TRACK_B_ANALYSIS_UNAVAILABLE`/`SKIPPED_ANALYSIS_UNAVAILABLE`
with its concrete reason and changes no verdict — never a silent "clear". Proven end to end by
`dv_harness_tests/test_system_level_track_b_gate_crosscheck.py`, which drives the REAL gate scripts
as subprocesses over REAL synthetic environments and asserts a hand-typed "all clear" block is
REJECTED when the real analysis over the same subsystems finds two ACTIVE AXI masters on one port.


## Methodology Consolidation Rule

A process/method/workflow used in a session is not "done" once it produces a result once.
It only counts as done once it has been consolidated into a permanent Harness asset so future
sessions get it automatically, without needing the user to re-explain it:

- A validated evidence-gathering/verification METHOD (e.g. how many agents, how to keep them
  blind, what counts as a real disagreement, how to resolve one) is consolidated into the
  relevant `.claude/skills/**/SKILL.md` file — with concrete mechanics and a worked real example,
  not a restated abstract mandate.
- A validated multi-phase ORCHESTRATION SHAPE (e.g. Parallel Evidence Gathering -> Consensus
  Synthesis -> Implement -> Re-verify) is consolidated into a reusable, parameterized script under
  `.claude/workflows/`, callable by name via the Workflow tool — not left as a one-off ad-hoc
  scratchpad script that only this conversation can re-run.
- A validated code-level capability (a new generator schema field, gate, check) is consolidated
  into the actual engine source under `dv_harness/`, with regression tests, exactly as already
  practiced this session — never left as a hand-edited one-off file outside the engine.
- After every consolidation: sync `.claude/` (skills + workflows) to the `industrial` and
  `PACKAGE` deliverable trees, same as any other engine change.

This rule itself is Human-Override-able like everything else, but by default applies with no
need for the user to ask for it every time.

This applies at every level, not only surface-level skills/workflows: an AI-architecture decision
(e.g. inference confidence scoring, memory-tier design, routing/dispatch semantics, iterative
reasoning-loop design) must land as real, wired, tested code inside `dv_harness/` — never stay as a
standalone module nothing in the real engine flow calls, and never stay as prose-only skill
guidance describing a desired mechanism an LLM subagent is merely trusted to enact each time. Per
[[dv_harness_poster_gap_reaudit_2026_08_29]] (verify this memory is still current before trusting
it), several past "done" claims at exactly this level (inference math, memory-tier stores, the
ReAct loop, route/skill resolution) turned out to be real-but-unwired or hardcoded/non-evidence-
driven — re-check wiring, not just existence, before declaring an AI-mechanism item complete.


## Engineering Discipline Rules (2026-08-29)

Cross-cutting rules that apply to every file modification, in addition to the domain-specific
mechanics already codified in `.claude/skills/CORE/*`:

- **Comment hygiene**: every file edit must also remove any comment/description in that file that
  is now outdated, redundant, or unrelated to the current content — never leave stale explanations
  behind as edits accumulate.
- **No overly abstract naming**: identifiers, files, signals, IDs must name the concrete real
  thing they represent (protocol/port/register/branch/purpose) — never a vague generic label a
  reader would have to guess the meaning of.
- **branch-B / VIP pattern changes**: query VIP examples, VIP user manual, VIP source code and
  class/API reference FIRST — already codified in `vip-scenario-branch` (do not invent VIP
  API/class/sequence by guessing).
- **branch-A / branch_fw changes**: query DUT RTL source, PHY documents and any programming
  guide/register documentation FIRST — already codified in `interrupt-event-dispatch`.
- **Event/control register hierarchy**: any RTL instance/signal hierarchy path for an event or
  control register must be verified against current RTL evidence, never assumed/reused from a
  stale path — already codified in `interrupt-event-dispatch` (`SOURCE_HIER` field).
- **Real FW pattern is interrupt-driven, not polling**: understand the trigger register/config,
  CPU WRITE task to arm it, then event-driven wait on the resulting interrupt — never periodic
  CPU READ-task polling as the primary detection mechanism — already codified in
  `interrupt-event-dispatch` ("CPU Task 層級實作模式").
- **Concurrent bus arbitration**: APB/AXI transactions that can execute concurrently across
  `block` / `branch_a0` / `branch_a1` / other `branch_a*` against a shared resource must have an
  explicit, RTL-evidence-based arbitration policy modeled — already codified in `branch-mapper`
  ("AMBA M×N Mapping"). Unrelated resources must stay independently parallel.
- **command.txt change-impact check**: every file/generator-schema modification must be checked
  against `.dv-workflow/command_inventory.csv` for which existing command.txt/scenario cases it
  could affect, and the affected set re-verified after the change — already codified in
  `command-inventory` ("Change-Impact Check").
- **Architecture-conformance audit**: every generated/modified environment and file must be
  checked against the current canonical naming architecture —
  `block + branch_a0/1/2/3... + branch_fw (supports parallel Port1/2/3...) + branch_b0/1/2/3...
  (VIPs)` — legacy/pre-v8 naming (non-underscore `branch_a{i}` forms, missing `branch_fw`,
  non-parallel-port assumptions) found during any review must be flagged and corrected, not
  silently left in place. Term semantics: `block` = SoC global initial tasks; `branch_a*` =
  DUT+PHY initial tasks, one parallel branch per DUT port; `branch_fw` = the FW service loop,
  one parallel branch per port; `branch_b*` = VIP-driven parallel tasks. Port numbering (whether
  a given DUT's ports start at 0 or at 1) must be verified against that DUT's actual RTL port
  numbering for the current project, never assumed from this doc's own `Port1/2/3` example
  text or copied from a prior project.
  `D:\DV\Task\DV_Agent_Harness_L5\USB_UVM_Handoff` is the canonical structural template for
  DV Agent Harness L5's VIP-based verification environment generation, at both SUBSYSTEM_MODE
  and SYSTEM_LEVEL_MODE — subject to the same "No Golden-Reference Content Mining" rule above:
  use it to check structural/organizational conformance, never as a source to mine
  protocol-behavior content from for a different project.
  **Consolidation status (audited 2026-09-02, see MEM-7F2DCD9E83/MEM-53FCE2C191/MEM-1669464837
  for full evidence):** file structure, verification-environment composition (env/agent/scoreboard
  wiring), and VIP-examples grounding are real, code-consolidated assets in
  `dv_harness/uvm_generator/*.py` (20+ line-cited references) and
  `dv_harness/uvm_generator/templates/sim_scripts/` (a real, now chip-configured copy of
  `USB_UVM_Handoff/sim/scripts/`), enforced against direct golden-reference citation by the real
  `protocol_isolation_gate`. The command.txt/pattern content architecture gap (`block`/
  `branch_a`/`branch_fw`/`branch_b` task composition, fork/join semantics, named
  arbitration/ordering traps) was closed 2026-09-03: distilled, generalized (USB kept only
  as clearly-labeled illustration, never as vocabulary) into a new
  `.claude/skills/CORE/pattern-architecture/SKILL.md` — the five-layer shape, the
  join-vs-join_any rule and why the "every branch guaranteed to run forever" justification
  expires, six recurring trap classes, and what varies vs. stays fixed by test intent
  (see `.work/gap-close-command-txt-report.md`). `command-generator/SKILL.md` now
  cross-references it (which command IDs must exist vs. how a pattern's internal task
  composition must be built) rather than duplicating it. The Makefile/sim-scripts migration gap
  (2026-09-02 audit: 5 files never carried over) was closed 2026-09-03: `analyze_sim.sh`,
  `apb_timing_report.sh`, `dpdm_report.sh`, `irq_report.sh` (the latter three sharing one
  `fsdb_signal_report.sh` engine, per-question wrappers only) and `check/gen_scaledown.py` are
  now genericized templates in `dv_harness/uvm_generator/templates/sim_scripts/` (see
  `.work/gap-close-makefile-report.md`). The consolidated part of this directory still goes
  unused unless an agent is explicitly told to survey
  `dv_harness/uvm_generator/templates/sim_scripts/` before hand-authoring build infrastructure —
  citing one sibling file in this directory (as this document previously did for
  `regression_list_manager.py`) is not sufficient for a dispatched agent to discover the rest.
- **Non-USB topology variants (2026-09-01, UNTESTED placeholder guidance)**: the canonical
  `block/branch_a*/branch_fw/branch_b*` naming above was reverse-distilled from, and has only
  ever been validated against, USB. Two topology-shape variants have since been added as
  clearly-labeled, explicitly UNTESTED generic guidance for a future non-USB pilot to start
  from — neither has been validated end-to-end and neither changes any protocol's
  genericity_status from untested/structurally-incompatible to working: (1) a **simplex
  streaming `branch_fw` variant** (RX-only/TX-only DUT, e.g. MIPI CSI-2/DSI-shaped) in
  `interrupt-event-dispatch/SKILL.md` — "Simplex Streaming branch_fw Variant" section; (2) an
  **AMBA-as-primary-DUT master/slave redefinition** of `branch_a*`/`branch_b*` (fabric IS the
  DUT, not an overlay on top of pre-existing ports) in `branch-mapper/SKILL.md` — "AMBA-as-
  Primary-DUT Master/Slave Redefinition" section. A future agent building a non-USB environment
  (CSI-2/DSI, or an AMBA-fabric-as-DUT/`SYSTEM_LEVEL_MODE` environment) should read these
  sections first rather than starting from zero.


## Agent-Authored Change Accountability (2026-09-03)

Explicit, written policy so this is settled before it becomes a real incident, per the user's
own reasoning: without this stated up front, no human feels safe clicking Approve on an
agent-authored change, and the harness stays permanently stuck below L5 regardless of how good
its technical output is.

- **The agent is a tool, not an accountable party.** Claude Code (or any automated caller)
  proposes; it never bears responsibility for a merged/pushed change's consequences.
- **The human approver of a PR/merge carries the same responsibility as if they had authored the
  change by hand.** Approving an agent-authored PR is not a lower-scrutiny action than approving
  a colleague's PR — the approver is the accountable party for any escape that change causes,
  exactly as with any other PR they approve.
- This is why `gh CLI + PR-Only Governance Policy` above exists as a hard technical gate (agent
  proposes via PR, never merges/pushes to `main`/`master` directly): the accountability model
  above only works if there really is always a human decision point in between an agent's
  proposal and a protected branch. Removing or bypassing that gate would also remove the
  precondition this accountability policy depends on.
- This policy does not change any existing evidence/verification requirement in this file (the
  Evidence Truth Rule, stage-gate checklists, etc.) — those still apply in full before a change
  reaches PR stage. It only settles the separate question of who is accountable once a human
  clicks Approve.


## Trust Progression for Autonomous/Semi-Autonomous Work (2026-09-03)

Real-world adoption should climb by task risk, not jump straight to the riskiest category:

1. **Start with near-zero-risk tasks**: log/failure triage, report generation, coverage
   summarization. A wrong output here costs a few minutes of a human's attention, not a bad
   tapeout decision.
2. **Only after a track record accumulates on tier 1** (accuracy data the team has actually
   looked at, not an assumption) should autonomy extend toward stimulus/pattern modification —
   the tier where a wrong output can silently produce a false PASS.
3. This is a recommended adoption ordering for the humans operating this harness, not a
   mechanically enforced gate in the engine — record it here so it is a deliberate team decision
   each time scope expands, not a default that happens by not thinking about it.

**Deliberately preserved knowledge asymmetry**: as this harness gets better at autonomous
debug, new engineers get fewer chances to debug a real failure by hand — which is a genuine
long-term cost to the team's own capability, not merely a short-term efficiency tradeoff. Teams
adopting this harness should deliberately route some fraction of real failures to a human for
hands-on debug rather than letting the harness resolve every one it technically could, treating
this as an investment in the team's future capability rather than lost efficiency today.


## Bind-Location Rules (2026-09-03)

Five hard project rules for every `bind` statement an agent proposes or reviews — not
suggestions, and not judgment calls left to per-instance discretion. Backed by real code in
`dv_harness/connectivity.py` (the 4-tier bind-confidence classifier, existing-bind grep, and the
3-gate connectivity pipeline — see `.work/mcp-bind-connectivity-report.md`),
`dv_harness/phy_boundary.py` (the mount-layer decision, Rule 5) and
`dv_harness/uvm_generator/bind_mechanism_generator.py` (evidence-gated `bind`/hook-skeleton
emission, already real — this section adds the location rules that generator's own output
must satisfy; it does not re-implement that generator's emission logic here).

1. **Bare module name vs. full instance path.** Binding to a bare module name applies to
   **every** instance of that module. Appropriate at IP-level (one DUT instance, one intended
   bind target). Usually **wrong** at SoC level — a bare-module-name bind against a module
   instantiated more than once silently binds all of them. SoC-level work must always bind by
   full instance path (`chip.core.subsys0.usb0`, not `usb3_subsystem`).
2. **Centralized `*_bind.sv` files under `tb/`.** Every bind statement lives in a centralized
   `*_bind.sv` file under `tb/` (matches the existing `<ip>_uvm_bind_inst.sv` — "every bind, in
   ONE file" — convention already documented in `ip-uvm-dv-gen/SKILL.md`'s directory table). RTL
   files are **read-only**: an agent must never insert a `bind` statement directly into RTL.
3. **Clock/reset through the bind's own port list.** Clock and reset must be passed explicitly
   through the bind instance's own port connections, never grabbed via a cross-level
   hierarchical reference (`chip.core.clk` reached through an XMR from inside the bound module).
   A hierarchical grab breaks at gate-level netlists and after any wrapper swap — the bind's own
   port list is the only connection method that survives both.
4. **No generate/for-loop bind targets.** Any bind-target path containing a generate-block or
   for-loop construct must be expanded to explicit literal indices in the actual bind statement
   (`chip.core.phy_array[0].u_phy`, `chip.core.phy_array[1].u_phy`, ... — never
   `chip.core.phy_array[*].u_phy` or an unrolled-loop placeholder). No wildcard/loop-based bind
   target is accepted, precisely because a generate-loop bind path is one of the two situations
   `connectivity.py`'s T3 tier explicitly flags as most error-prone (the other being inconsistent
   wrapper depth across a hierarchy).
5. **The PHY model decides the mount LAYER first; only then is the hierarchy path a question.**
   Rules 1–4 all assume the layer is already settled and ask *where inside it* to bind. Rule 5 is
   the step before them, and it is an ORDERING rule: decide from the PHY model's existence and
   type which layer a monitor may mount at, and only after that layer is fixed go looking for the
   instance path. Choosing a target path first — typically by recognising a familiar module or
   signal name in the RTL — and asking afterwards whether a PHY sits in between is the backwards
   order, and it is not a harmless reordering. It is how a bind lands on line-rate serial lanes: a
   protocol VIP monitor there decodes nothing without a PHY model, so it **elaborates (Gate 1
   PASS), sees a toggling clock and a released reset (Gate 2 PASS), and only fails at Gate 3, as a
   silent monitor** — the most expensive place in the pipeline to discover a mount-layer mistake.
   Note the tier classifier cannot catch this: a serial-lane bind target can be a perfectly clean
   T1 structural match, because layer-correctness and path-correctness are independent properties.
   That is why this is a separate gate rather than another tier.
   The confirmed real drift this rule is written from (2026-08-31, recorded in
   `.claude/agents/IP_UVM_DV_Gen.md:541-649`): an agent disabled a whole PHY instance for USB3 on
   the assumption that PIPE4 replaced it, and was corrected by the user — 「USB3 也是要經過 PHY，
   不是 PIPE 介面」. The agent had reasoned from interface naming instead of from whether a PHY
   model was actually in the path.
   **Enforced in code (2026-09-04), not by review**: `dv_harness/phy_boundary.py` derives the
   serial/parallel boundary from the same verible-parsed port table `env_manifest.py` produces,
   and `bind_mechanism_generator.assert_phy_boundary_decided_first()` runs that decision as a gate
   **before** the tier gate inside `validate_bind_entries()`/`emit_bind_sv()` — a SERIAL-only or
   UNDECIDABLE boundary raises `PhyBoundaryValidationError` and nothing is written. An entry may
   declare the boundary signals it connects through as `phy_boundary_signals`, which additionally
   refuses binding the serial lanes of a MIXED boundary (a boundary whose document says
   `bindable: true`, so the layer check alone would pass it). `tools/generate_bind_mechanism.py`
   takes `--phy-boundary <phy_boundary.json>` and `--require-phy-boundary`.
   **Disclosed residual**, mirroring `require_tier`'s: `require_phy_boundary` defaults to False, so
   a caller that supplies no boundary document at all still emits. That default is deliberate — an
   IP-level DUT with no PHY sub-block genuinely has no boundary to decide — and it means Rule 5 is
   hard-enforced whenever a boundary is in scope and known, not universally. Pass
   `--require-phy-boundary` for the strict contract.

Rules 1–4 (the path rules) are enforced by review, not (yet) by a standalone lint gate — Rule 5
is the exception and hard-blocks in code, per its own paragraph above. `connectivity.py`'s
T1–T4 tier classifier and its `grep_existing_binds()`/matrix output make a violation visible (a
bare-module-name target at SoC scope, or a generate-index-bearing bind target, shows up directly
in the connectivity matrix's `bind_target` column for a human reviewer to catch), but does not
yet hard-block generation on one. See the report referenced above for what is real/tested today
versus NOT_AVAILABLE-by-honest-design (anything requiring a live `simv`, a licensed VCS install,
or `slang`, none of which are present in this environment as of this writing).

**The bind-CONFIDENCE tier, like Rule 5 but unlike path rules 1–4, DOES hard-block generation
(2026-09-04).** It is the second of the two independent gates `validate_bind_entries()` runs, and
runs after Rule 5's: layer first, then path confidence. `connectivity.assert_t3_never_auto_accepted()` previously had no caller anywhere
in the repo — its own docstring named a "downstream consumer" that did not exist — so the real
emission path (`tools/generate_bind_mechanism.py` → `uvm_generator.bind_mechanism_generator.
emit_bind_sv()`) would write a naming-heuristic-only bind into a `.sv` file with no tier check at
all. `validate_bind_entries()` now calls `connectivity.enforce_bind_tier_policy()` before emitting
anything, which refuses, as a hard `BindTierError` and before any file is written:
- **T4** (`T4_BIND_MUST_GO_TO_QUESTION_QUEUE`) — never emittable; it belongs in the question queue
  via `build_t4_question_queue_entry()`, not in a bind file.
- **T3 without a real human confirmation** (`T3_BIND_REQUIRES_HUMAN_CONFIRMATION`) — the entry must
  carry `human_confirmation: {source, confirmed_by, basis}` whose `source` is
  `question_queue.HUMAN_DECISION_SOURCE`. That is the same single sanctioned decision source the
  question queue already uses to stop the harness answering its own Tier-3 escalation with its own
  earlier guess — deliberately reused, not a second parallel notion of "confirmed".
- an unrecognized tier string, and (under `--require-tier` / `require_tier=True`) an entry carrying
  no tier at all.

**Disclosed residual**: `require_tier` defaults to False, so an entry carrying NO tier is still
emittable. This keeps the existing 3-field entry contract (`target_instance`/`ports`/`reason`,
documented in every PROTOCOL_BUILDERS skill and used by the real
`examples/generated_usb_real_evidence_v1/manifest_inputs/usb_bind_topology.json`, re-verified
working) unbroken. What is closed hard is the dangerous case: an entry the pipeline already
classified as unconfirmed or undecidable being emitted anyway. Pass `--require-tier` for the
strict contract.

Two matrix-level guarantees were wired at the same time, both previously uncalled primitives:
`write_connectivity_manifest()` now runs `verify_matrix_self_check_identity()` (Part C's
sum(verified interfaces) == sum(VIP instances) + sum(exemptions), with both terms read off the
real matrix rather than caller-supplied) and `assert_role_provenance()` BEFORE writing, so a
manifest on disk is one that reconciled — an uncovered no-VIP interface or a hand-typed
naming-derived `role` raises instead of producing an authoritative-looking artifact.
`ConnectivityRow.from_dut_port()` is the sanctioned row constructor that derives `role` through
`determine_role_from_port_direction()` instead of accepting a typed-in string.

**The 3 machine gates are a REQUIRED workflow checkpoint, not merely available tooling
(2026-09-03, Gap #2 closure).** `connectivity.py`'s 3-gate standard (elaboration / static
zero-time connectivity / transaction activity) existing and being importable is not sufficient —
it must actually be RUN. This was confirmed as a real gap: the live `usb31_dev_uvm` build reached
first successful compile and moved on through later build steps without the 3-gate standard ever
being applied to it, because the standard was built mid-session by a separate concurrent effort
and nothing retroactively flagged that in-flight build against new verification infrastructure.
Concretely, for every IP_UVM_DV_Gen build from this point forward (full mechanics in
`.claude/agents/IP_UVM_DV_Gen.md`'s "Mandatory bind-verification checkpoint" subsection under Step
9):
- Running Gate 1 (`run_gate1_elaboration_check()`) and Gate 2 (`evaluate_zero_time_connectivity()`
  / `run_gate2_against_live_simv()`) is REQUIRED immediately after the first successful
  compile/elaboration — an honest NOT_AVAILABLE result (no `slang`/`vcs`/trace present) satisfies
  this checkpoint; never invoking either gate at all does not.
- Gate 3 (transaction activity) cannot PASS or FAIL until a real pattern actually completes. That
  is expected and must be tracked explicitly as **PENDING**
  (`evaluate_transaction_activity_status(pattern_completed=False)`) — `connectivity.py`'s
  `GateStatus` enum now carries `NOT_YET_RUN` and `PENDING` alongside `PASS`/`FAIL`/
  `NOT_AVAILABLE` specifically so this state is never conflated with FAILED, with "not
  applicable", or silently omitted from a report.
- Every build-status report produced from that checkpoint onward must explicitly carry Gate
  1/2/3's current status (`render_bind_verification_status_markdown()` /
  `bind_verification_status_block()`) — a report that omits this section is a defect in the
  report. `python -m dv_harness.uvm_generator.bind_verification_lint <report_path>` is a real,
  standalone check that flags exactly this against any build tree's own status-report artifact
  (markdown or JSON), independent of which agent or code path produced it.
- `assert_bind_gates_checkpoint(first_compile_succeeded, gate_report)` is the corresponding
  code-level assertion (raises `BindGateCheckpointError`, never a silently-ignorable bool) for any
  future code path that comes to drive this build mechanically instead of via agent-followed
  prose. See `.work/gap-close-mandatory-gates-report.md` for the full evidence and verification.

**The gates are also a STANDING recipe re-run on every RTL update (2026-09-04).** The checkpoint
above fires once, at first successful compile. `connectivity.py`'s own
`run_gate3_against_live_simv()` docstring additionally called for the gates as "a standing
`just connectivity-check` recipe re-run on every RTL update" — a recipe that did not exist
anywhere (no justfile target, no CI job, no hook; `connectivity.py` was imported by nothing but
itself and `bind_verification_lint.py`). It now does:
- `just connectivity-check` runs all 3 gates through `connectivity.run_machine_gates()` (never a
  subset) via the real `dv_harness/connectivity_check.py` runner, and records the resulting
  statuses **together with a content fingerprint of the RTL they were produced against**
  (`.dv-harness/connectivity_check_state.json`, plus a lint-clean
  `.dv-harness/connectivity_check_report.md` rendered by the same
  `render_bind_verification_status_markdown()`).
- `just connectivity-check-status` (= `python -m dv_harness.connectivity_check --check-only`) is
  the automatic TRIGGER: it runs no gate, only re-computes that fingerprint and exits **2** when
  the RTL moved since the last real gate run, or when no run was ever recorded. Wired as a CI
  step in `.github/workflows/dv-harness-ci.yml`, so "RTL changed but nobody re-ran connectivity"
  becomes a real failure instead of something a reviewer has to notice. Content-hash based, not
  mtime — a no-op touch does not fire it, and a content change that preserves mtime does.
- Inputs are declared once per project in `.dv-harness/connectivity_check.json` (`rtl_sources`
  globs, `filelists`, `top_module`, optional `signal_trace_path`, monitor transaction counts,
  `pattern_completed`). A project without that file reports NOT_CONFIGURED rather than a silent
  pass; a config whose `rtl_sources` match zero files is a hard config error, never a vacuous
  constant fingerprint that would compare equal forever. **This harness repo itself has no RTL
  tree, so its own CI step is honestly a no-op today** — the mechanism is real and tested
  (`dv_harness_tests/test_connectivity_check.py`), the RTL it watches is per-project.


## Context Budget: 3 Tiers + MCP-First Routing (2026-09-03)

An agent's context window is a finite verification resource and is budgeted like one. The tiers
below are not advice — tier 1 is a real `PreToolUse` deny and tier 2 is a real `SessionStart`
injection. Policy lives as data in `dv_harness/context_budget.policy.json` (validated against
`dv_harness/schemas/context_budget.schema.json`); logic lives in `dv_harness/context_budget.py`;
enforcement is `.claude/hooks/context-budget-guard.ps1` (registered for
`Read|Grep|Bash|PowerShell|NotebookRead`) and `.claude/hooks/context-resident-pack.ps1`. Extend the
policy JSON for a project's own DUT/VIP roots — never the Python.

**Tier 1 — NEVER into context** (denied; four content classes, `NEVER-*` rule ids):
VIP source full text, raw PDF originals (user guides/protocol specs/programming guides),
whole-chip design·waveform·evidence databases (`.fsdb`/`.vpd`/`.vcd`/`simv.daidir`/the evidence
SQLite store), and complete simulation/regression logs. Every denial names its route forward — a
fixed MCP verb and/or the distiller that turns that content class into a bounded artifact
(`vip_user_guide_distill.py` for PDFs — corrected 2026-09-04 from `doc_extraction.py`, which only
LISTS `.pdf` in a suffix set and contains no PDF text extraction at all, so that route named a
script that could not perform it; `fsdb_report.py` for waveforms, `sim_log_analysis.py` for logs).
There is deliberately **no** distiller cited for VIP source: none exists — `vip_distill.py` is named
suggestively but normalises sim-log/job/fsdb evidence envelopes and never reads VIP source, so that
rule routes to `get_vip_config` and says so rather than sending you after a script nobody wrote.
Deliberate
carve-outs: VIP `Examples/` reference testbenches and `.f` filelists stay readable, because
denying the sanctioned reference material is the false positive that gets a gate switched off.

**Tier 2 — ALWAYS resident**: `CLAUDE.md` (this file — resident because the agent harness
auto-loads it), plus `.dv-harness/env.manifest.json`, `.dv-harness/run_profile.json`,
`.dv-workflow/hierarchy.json`, `.dv-workflow/phy_boundary.json`, injected as a size-capped summary
pack (`MAX_PACK_BYTES`, JSON summarised by shape, never inlined). Run
`python -m dv_harness.context_budget resident` to see current residency; it exits 2 while any
declared artifact is MISSING and prints the real command that would produce it. Residency in this
repo is still only `CLAUDE.md` (this harness has no RTL tree or VIP of its own to extract from),
but the extractor situation changed on 2026-09-04: **`phy_boundary.json` now HAS a real extractor**,
`dv_harness/phy_boundary.py`, which derives the PHY↔controller serial/parallel boundary from the
same verible-parsed port table `env_manifest.py` already produces and turns it into an explicit
bind-location decision (a SERIAL-only boundary is reported NOT bindable, because a protocol monitor
bound there passes Gates 1–2 and fails Gate 3 as a silent monitor). `hierarchy.json` is unchanged:
it still has a declared producer (`.claude/skills/CORE/hierarchy-discovery/SKILL.md`) but no
non-agent extractor. That is reported, not hidden.

**Tier 3 — LOAD ON DEMAND**: single-register/regmap lookups via `get_register` (never a whole
system regmap), the distilled per-protocol `docs/vip_ref/<protocol>.md`, and `docs/intent.md`.
Read one when a specific question needs it; never preload. As of 2026-09-04 both of those
distilled artifacts have real generators: `dv_harness/vip_symbol_index.py` indexes a VIP source
tree to declarations and `file:line` locations ONLY — never method bodies, which is what makes it
legitimate against tier 1's own `NEVER-VIP-SOURCE` denial — and renders `vip_ref/<protocol>.md`
from that index; `dv_harness/design_intent.py` renders `intent.md` and `constraints.md` from
schema-validated structured sources in which every legal-drop/backpressure condition REQUIRES a
document+section citation, so an uncited (i.e. possibly invented) condition cannot validate. The
matching `sys_regmap.json` / `init_seq.yaml` pair (`dv_harness/sys_regmap.py`,
`dv_harness/init_seq.py`) supplies the Gate-2 mode-bit precondition connectivity.py never had, so
a dead clock caused by an unwritten clock-enable reads as `PRECONDITION_NOT_MET` rather than as a
connectivity failure against a bind that was correct all along. See
`.work/gap-close-asset-table-asset-processing-table-14-rows-hierarchy-report.md`.

**MCP-first routing.** `dv_harness/mcp` exposes exactly 5 fixed, read-only verbs —
`get_vip_config`, `get_dut_port`, `get_register`, `get_topology`, `query_regression` — dispatched
through one `dispatch()` with no free-text fallback and no caller-supplied SQL. Anything those
verbs answer must be asked of them rather than read raw. Three honest limits, all covered by named
tests: the guard classifies literal paths only, so a shell-variable-indirected read
(`sed -n "1,50p" $M`) or a directory-indirected one (`ls <dir> | xargs cat`) still gets through;
`ls`/`find`/`stat`/`wc`/`file` may name a tier-1 file without reading it; and the guard fails open
if Python is unavailable. It is a large reduction in bypass surface, not a seal. A genuinely necessary tier-1 read gets a reasoned entry in the policy's `exemptions` array
(the rule still fires and is recorded in the decision) — never a silent retry.


## MCP Query Interface: the 5 Verbs (index) (2026-09-04)

The section above says routing goes through MCP first. This is the index that makes that
actionable: which verb answers which question, and which two files on disk this server is allowed
to touch. It is an index, not a manual — every verb's real parameter/result schema lives in
`dv_harness/mcp/schema.py` and the design writeup in `.work/mcp-server-report.md`; read those on
demand, never preemptively.

**The rule.** If one of these 5 verbs can answer your question, ask it — do not read the underlying
file. There are exactly 5, dispatched through one `dispatch()` with no free-text fallback, no
caller-supplied SQL, and no write verb of any kind; asking for a 6th name raises rather than
falling through to something general.

| verb | ask it when | required args |
|---|---|---|
| `get_vip_config` | you need a VIP instance's already-resolved config value (from a real zero-time elaboration dump, never a document) | *(none — omit both filters to list every captured instance)* |
| `get_dut_port` | you need one RTL module's ports or parameters, verible-parsed, with the source sha256 | `module_name` |
| `get_register` | you need one register's fields/offset/absolute address — never a whole regmap | *(none — omit all filters to list every register)* |
| `get_topology` | you need the UVM component hierarchy or the raw config_db SET/GET trace under some path | *(none)* |
| `query_regression` | you need regression evidence, via one of a fixed set of shapes — never raw SQL | `query_shape`, one of `latest` / `by_pattern` / `by_verdict` / `by_date_range` |

**Read-only fact sources.** This server reads exactly two things and writes neither. The manifest is
opened with `Path.read_text()` and the package has no writer; the evidence DB is opened
`read_only=True`, which DuckDB itself enforces at the engine level:

- `.dv-harness/env.manifest.json` — the 3-layer generated fact file (`vip_config` / `dut_facts` /
  `env_topology`), written only by `dv_harness/env_manifest.py`. Backs the first four verbs.
- `.dv-harness/evidence/evidence.duckdb` — the regression evidence store. Backs `query_regression`.

**Which protocols exist is deliberately not listed here.** Which protocols/VIPs an environment
actually contains is a manifest fact that changes per environment, not a rule that belongs in this
file — call `get_vip_config` with no arguments and read the `vip_type` of each captured instance. A
hardcoded protocol list here would be stale the day a second environment is built.

Run it against a real environment:

```
python -m dv_harness.mcp.server --manifest .dv-harness/env.manifest.json --evidence-db .dv-harness/evidence/evidence.duckdb
```

This section is **parsed and checked against the code on every test run**
(`dv_harness/mcp/claude_md_index.py`, `python -m dv_harness.mcp.claude_md_index`): the verb rows
must equal `verbs.VERBS`, each row's required args must equal that verb's real
`PARAM_SCHEMAS[...]["required"]`, the shapes must equal `regression_queries.QUERY_SHAPES`, the two
paths must equal the code-owned ones, and the invocation's flags must be flags `server.py` really
defines. Adding a verb without indexing it here fails a test. Moving the index into code without
holding the prose to it would only have created a second place to be wrong.


## Source Authority Order: 9 Levels, Enforced (2026-09-04)

When two sources disagree about the same fact, which one is true is decided by a fixed 9-level
order, highest first — not by which one an agent happened to read last, and not by judgment:

1. elaboration / actual simulation result
2. the reference Makefile/command.txt itself
3. DUT RTL
4. register file (DUT then Global)
5. existing testbench binds
6. controller doc/programming guide
7. IP user guide
8. VIP example
9. VIP document

This lived only as a paragraph in `docs/RUN_PROFILE.md` until 2026-09-04 — a repo-wide grep for
its own distinctive terms found zero hits outside that one paragraph, so it was a convention an
agent was trusted to have read, the exact failure class the Engineering Discipline Rules name. It
is now real code: `dv_harness/source_authority.py` (`AUTHORITY_ORDER`, `authority_rank()`,
`resolve_conflict()`) and `dv-harness authority order|check-doc|resolve`. The markdown paragraph is
PARSED and compared against the code on every test run (`assert_doc_matches_code()`), so the two
cannot drift apart in either direction — moving a rule into code is only an improvement if the
prose it came from is then held to it. The "(DUT then Global)" clause tier 4 carries is a real
sub-ordering (`REGISTER_FILE_SUBORDER`), not a parenthetical.

**It is not `tools/verification_flow/evidence_source_priority_gate.py`'s `ORDER`.** Both lists are
9 items long, which has already caused one mis-identification. That one is a DISCOVERY order (which
source to consult first for a fact you do not have yet, ending at `ASK_USER`); this one is a
CONFLICT order (which source wins when two you already read disagree). Separate mechanisms, kept
separate on purpose.

**A mismatch is escalated, not just reported.** `resolve_conflict()` deciding which VALUE to use
never means the losing artifact is fine to leave wrong, and two claims at the SAME tier cannot be
decided by the order at all. Both cases go to the real question queue through
`source_authority.escalate_conflict()`, which files a Tier-3 (`affects_spec_intent`) entry whose
two options ARE the two sides and whose per-option `rationale` is that side's evidence path.
`assert_both_evidence_paths_present()` runs BEFORE the record is persisted, so a conflict question
that names a disagreement without citing where both halves of it live can never reach the queue.

Two real detectors are wired into it. Both previously terminated at report text — the detectors
were real, the queue was real, the wire between them did not exist:
- `reference_pattern_audit.audit_directory(..., question_store=)`, i.e. `dv-harness
  reference-audit --escalate` — a host/DUT register-write asymmetry. Both halves come from the
  same tier-2 source (the reference pattern file), so the order returns
  UNDECIDABLE_SAME_AUTHORITY and escalating is mandatory rather than advisory. The missing side is
  cited AS an absence ("no DUT-side write to base BB00 offset 0020 in this file"), which is what
  makes an absence checkable by the person who receives it.
- `uvm_generator/address_map_verifier.verify_address_map(..., question_store=)` — a register
  document whose base address disagrees with the decoder. **This does not make committal
  blocking.** The decoder (tier 3) still wins over the doc (tier 6) mechanically, and the verified
  entry plus its `` `define `` are byte-identical with or without the store. What was missing is
  the OTHER question — which of the two artifacts is stale — which nothing asked anybody, and
  which a `//` comment inside generated Verilog is not an escalation of.

Both escalations are idempotent: the Q-ID is derived from the finding, so re-running a detector
over unchanged sources re-mints the same id instead of growing the queue. Proven end to end
against a real `QuestionQueueStore` (never a mock) by `dv_harness_tests/test_source_authority.py`.


## Source Authority Order Validation: Does the Fixed 9-Level Order Match Practice? (2026-09-07)

`source_authority.py`'s own module docstring already states the 9-level order's whole point: "which
of two already-read sources is TRUE" is decided by a fixed authority order, "not by which one an
agent happened to read last, and not by judgment." `escalate_conflict()` already files every real
mismatch as a Tier-3 blocking question carrying both sides' evidence and an AUTHORITY_ORDER-derived
`recommendation`, and a human answering that question is real, cited ground truth about which side
actually turned out to be correct. Nothing in this repo ever compared the two -- whether the fixed
order's own recommendation agrees with what humans keep actually deciding was a real, checkable
question with no answer. `dv_harness/source_authority_order_validation.py` is that answer, and it is
deliberately **report-only**: it reads `source_authority.py`'s real `AUTHORITY_ORDER` plus
`question_queue.py`'s real, answered Tier-3 escalation records and never edits `AUTHORITY_ORDER`
itself -- a weight/threshold-shaped finding from this module is exactly the kind of proposal this
project's Evidence Truth Rule requires be routed through a human, never applied directly to
production scoring.

**Shape recognition, not a domain/key guess.** `escalate_conflict()`'s own `domain` argument is
caller-chosen free text with no fixed value across this project's real detectors (the reference-
pattern-audit and address-map-verifier wires both file through it under different domains), so this
module never trusts `domain`/`question_key` to identify a real conflict escalation. It instead
recognises the SAME real text `SourceClaim.label`/`_option_for()` already produce for every
`escalate_conflict()`-filed question -- `"Trust the {doc_phrase}{qualifier} (tier {rank}): {claim}"`
for the label, `"evidence: {evidence_path}"` for the rationale -- and only accepts a record whose
every 2-3 options carry BOTH shapes AND resolve, unambiguously, to one of the 9 real `AUTHORITY_ORDER`
entries. Proven not to false-positive on `build_multiple_choice_question()`'s own similarly-shaped
(Tier-3, 2-3 option) but differently-labelled N-way questions, and not to false-positive on an
ordinary Tier-1/2 question.

**The Evidence Truth Rule, applied to "which side did the human pick".** A human's real answer
(`QuestionQueueStore.answer_question(answer=...)`) is genuinely free text -- confirmed against this
project's own real test fixture, `answer="the doc is stale; RTL is right"` -- never constrained to
echo an offered option's label verbatim. This module therefore never guesses: it looks for real,
literal evidence in the human's own answer/basis text, in a fixed, disclosed order of decreasing
certainty -- (1) a literal citation of one candidate's own `evidence_path` (the strongest possible
signal); (2) a whole-word, case-insensitive mention of one candidate's own canonical source id,
`doc_phrase`, or one of `AUTHORITY_ORDER`'s own already-registered aliases (the SAME alias table
`source_authority.normalize_source()` uses, never a second one built here). Two or more candidates
matching at either tier is honestly `AMBIGUOUS`; no candidate matching is honestly
`UNRESOLVED_NO_MATCH`. Neither is ever collapsed into a guessed pick, and neither counts toward the
overall match/mismatch tally -- only a case where BOTH the authority order predicts a real
(non-tied) winner AND the human's real answer resolves to exactly one candidate is
`MATCH`/`MISMATCH`-evaluable.

**A same-tier pair predicts nothing, honestly.** `source_authority.resolve_conflict()` itself already
says "the order cannot break a tie inside one level" for `UNDECIDABLE_SAME_AUTHORITY`; the persisted
question record's own `tier` figure inside each option's label carries only the coarse
`AuthoritySource.rank`, never the finer tier-4 `REGISTER_FILE_SUBORDER` DUT-vs-Global subrank (which
the persisted label text does not encode). Two candidates sharing one rank -- whether a genuine
cross-tier tie or a real tier-4 DUT-vs-Global subordering this module cannot recover from the
persisted record alone -- are reported `TIE_NO_AUTHORITY_PREDICTION`, a disclosed, honest limitation
rather than a fabricated prediction either candidate could satisfy for free.

**The report.** Per real conflict-escalation question: a `ConflictCase` naming its authority
prediction, its human pick (with the real matched evidence/tokens that identified it), and one of six
outcomes (`MATCH`/`MISMATCH`/`TIE_NO_AUTHORITY_PREDICTION`/`HUMAN_PICK_AMBIGUOUS`/
`HUMAN_PICK_UNRESOLVED`/`PENDING_UNANSWERED` for a still-open escalation). Rolled up into a real,
computed `match_rate_percent` (never fabricated when there is nothing evaluable -- `None` with status
`NO_EVALUABLE_CASES`), a per-`AUTHORITY_ORDER`-level track record (`LevelStats`: how often each level
was the predicted winner, confirmed, overridden, or chosen by a human over a higher-authority level),
and `override_pairs` -- every real `(authority_predicted, human_picked)` reversal with its real
occurrence count, the most directly actionable evidence in the report: exactly which lower-authority
source keeps winning over exactly which higher-authority one, and how often.

**Deliberately bounded, and stated rather than implied closed.** It never files or answers a
question, never picks a winner for an open escalation, and never arbitrates or resolves a real
divergence between the fixed order and human practice -- a real override is reported, per-level and
per-pair, for a human to review; changing `AUTHORITY_ORDER` in response stays a separate, explicit,
human-approved production-behavior change, exactly like every other weight/threshold proposal in this
project. There is deliberately no stage gate and no `dv-harness` CLI verb (`cli.py`/`gates.py`
untouched, matching this project's own house convention for a standalone module) -- the front door is
this module's own Python API plus `python -m dv_harness.source_authority_order_validation
[--root <dir>] [--json]` (exit 0 `ORDER_MATCHES_PRACTICE`, 1 `ORDER_DIVERGES_FROM_PRACTICE`, 2
`NO_EVALUABLE_CASES`).

Proven by `dv_harness_tests/test_source_authority_order_validation.py` (40 tests) against the REAL
`source_authority.resolve_conflict()`/`escalate_conflict()` and `question_queue.QuestionQueueStore`
machinery throughout -- never a hand-shaped question record standing in for what they would produce,
except where a test's own point is to prove this module refuses to be fooled by a record that merely
looks similar (a Tier-2 record, an unrecognized source name, a mismatched doc_phrase/tier pairing).
Covers every one of the six case outcomes (including a real tier-4 register-file DUT-vs-Global tie
and a real multi-case mixed scenario whose per-level stats and override-pair counts are checked
exactly), the word-boundary alias-matching negative control ("RTL" must not match inside
"PORTLAND"), a read-only guarantee (a byte-for-byte, mtime-for-mtime snapshot proves `build_report()`
writes nothing to `.dv-harness/`), a direct proof `AUTHORITY_ORDER` itself is never mutated, both
`Path`-and-`store` call conventions, a minimal duck-typed store double, the vocabulary-collision
guard's real detection power (mutation-tested against `dv_harness.models.Status`), and the real CLI
driven as subprocesses across all three documented exit codes. `dv_harness_tests/
test_source_authority.py` (37 tests) and `dv_harness_tests/test_question_queue.py` (109 tests) were
re-run in full before and after this addition and stay green throughout -- this item touches neither
file.

