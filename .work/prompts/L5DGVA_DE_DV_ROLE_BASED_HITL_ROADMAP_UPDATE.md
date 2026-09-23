# L5DGVA DE/DV Role-Based Human-in-the-Loop Roadmap Update

## 0. Mission

Integrate the approved **DE/DV Role-Based Human-in-the-Loop (HITL)**
model into Canonical L5DGVA architecture, roadmap, Master Capability
control plane, E2E matrix, future-wave contracts, and acceptance
criteria.

This is **ROADMAP / ARCHITECTURE / GOVERNANCE reconciliation only**. Do
not implement the roadmap. Do not start M5--M13, C6, Platform Upgrade,
or USB Golden. Do not modify Parent/v50/b7a/b7b/b8. Do not create
separate DE/DV engines. Do not dump this detailed architecture into
`CLAUDE.md`.

## 1. Repository / Program Safety

Before changes: 1. Verify Canonical repository identity. 2. Record
PROCESS_CWD, REPO_ROOT, CURRENT_BRANCH, CURRENT_HEAD,
`git status --short`. 3. Read current CLAUDE.md, Constitution/Article 0,
MASTER_PROGRAM_STATUS, MASTER_CAPABILITY_STATUS_MATRIX,
MASTER_WAVE_OWNERSHIP_MATRIX, MASTER_BLOCKER_REGISTER,
MASTER_END_TO_END_DV_STATUS, and relevant M4/M4.5/M4.6 artifacts. 4.
Preserve qualified M4.6 context architecture. 5. Verify
Parent/v50/b7a/b7b/b8 unchanged. 6. Preserve pre-existing dirty state.

Wrong identity =\> `WRONG_L5_REPOSITORY` and STOP.

## 2. Preserve Program Control Plane

Do not create a competing roadmap/status universe. Extend the existing
Master Capability Status Matrix and roadmap. Preserve the current
evidence-based NEXT_RECOMMENDED_GATE unless this reconciliation proves a
direct contradiction. In particular, do not bypass an open M4.5
governing-contract-authority P0 merely because M6/M8/M9/M10 receive new
requirements.

## 3. Highest Architecture Decision

Freeze:

> **L5DGVA has ONE Generic Verification Workflow. DE and DV are not
> separate pipelines; they are human authority roles participating in
> the same end-to-end lifecycle.**

Canonical model:

``` text
                  L5DGVA Generic Workflow
                           |
                    Human Decision?
                           |
              +------------+------------+
              |            |            |
           DESIGN      VERIFICATION    SHARED
              |            |            |
              v            v            v
             DE            DV         DE + DV
```

Create/reconcile `ROLE_BASED_HUMAN_IN_THE_LOOP`, preserving an existing
equivalent name if present.

Prohibit default architecture from becoming DE-specific/DV-specific
orchestration engines, duplicated role-specific verification pipelines,
duplicated Knowledge Brains, or duplicated level engines.

## 4. One Common DE/DV Lifecycle

Record one Canonical lifecycle:

Create/Open Project → Select IP/Subsystem/System-Level → Provide Inputs
→ OpenSpec Intake → Automatic Discovery → Evidence/Confidence/Gap →
Minimal Clarification → Knowledge Retrieval → Verification Architecture
→ vPlan → Human Review when justified → VIP/UVM Generation →
Test/Sequence/Scenario/Firmware → Checker/Scoreboard/Assertion/Coverage
→ Build/Smoke/Execution → Regression → RCA/Fix/Rerun → Coverage Closure
→ Requirements/Evidence Traceability → Waiver → Signoff → Experience
Consolidation → Knowledge Promotion → Next Project Improvement.

DE/DV differences are authority/gate/escalation/learning differences,
not workflow differences.

## 5. Human Authority Model

### DESIGN_AUTHORITY

Primary role: DE. Covers intended DUT behavior, register semantics,
reset/IRQ/clock intent, legal states, firmware programming intent,
undocumented behavior, design limitations, protocol-mode design
configuration, RTL/spec discrepancy from design-intent perspective, and
implementation constraints affecting expected behavior.

### VERIFICATION_AUTHORITY

Primary role: DV. Covers verification architecture, vPlan, feature
mapping, scenario/test/sequence/constraint strategy,
checker/scoreboard/assertion strategy, coverage model/closure,
verification waiver, verification risk acceptance, and verification
signoff.

### SHARED_AUTHORITY

Role: DE + DV. Use only for genuine cross-domain decisions such as
Spec/RTL contradiction, feature interpretation affecting closure, design
limitation requiring verification waiver, or requirement interpretation
affecting signoff. Do not use SHARED as fallback for poor
classification.

## 6. Roles Are Logical, Not User Identity

Roles must not depend on username, OS account, workstation, repository
path, gateway host, or remote EDA host. Future project configuration may
map people to roles, but core architecture operates on logical authority
roles.

## 7. Generic HumanGate Contract

Define/reconcile a future HumanGate supporting: GATE_ID, PROJECT_ID,
VERIFICATION_LEVEL, WORKFLOW_STAGE, DECISION_TYPE, AUTHORITY_ROLE,
REQUESTED_BY, EVIDENCE_REFS, CONFIDENCE, QUESTION_OR_DECISION, OPTIONS,
RECOMMENDATION, HUMAN_DECISION, DECISION_RATIONALE, RESOLUTION_STATE,
PROVENANCE.

AUTHORITY_ROLE: DESIGN / VERIFICATION / SHARED.

Human gates occur only when justified by insufficient evidence, low
confidence, contradiction, design/verification intent, architecture
decision, waiver, risk acceptance, signoff, or governance policy.

Target: `MINIMUM_NECESSARY_HUMAN_INTERRUPTION`, coexisting with
`AUTO_DISCOVERY_FIRST` and `MINIMAL_STRUCTURED_CLARIFICATION`.

## 8. Question Owner Contract

Future Clarification architecture must support
`QUESTION_OWNER = DESIGN | VERIFICATION | SHARED` and fields equivalent
to QUESTION_TYPE, QUESTION_REASON, EVIDENCE_ALREADY_CHECKED, CONFIDENCE,
TARGET_HUMAN_ROLE, ANSWER, ANSWER_EVIDENCE, RESOLUTION_STATE,
QUESTION_AVOIDABLE.

Flow: Clarification Candidate → Auto-Discovery/Evidence Search →
unresolved? → classify → DESIGN/VERIFICATION/SHARED → DE/DV/DE+DV.

Do not implement during this task.

## 9. M6 --- ClarificationService

Preserve M-1 D2: **ONE Canonical ClarificationService** preserving
maximum verified capabilities of `question_queue` +
`intake_clarification`. Do not reopen pick-one.

M6 explicitly owns: - VerificationLevel - ClarificationService -
Role-Based Human-in-the-Loop - Question Owner Routing - HumanGate
Contract - RCA Role Routing

Clarification remains evidence-first; blank data alone is not
justification to ask a human if authoritative evidence can discover it.

## 10. Clarification Learning

Future loop: Question → QUESTION_OWNER → DE/DV answer → later evidence
proves auto-discoverable → QUESTION_AVOIDABLE → Experience Candidate →
discovery improvement → future interruption avoided.

M6 owns routing mechanics; M8 owns learning/promotion. Never authorize
guessing.

## 11. RCA Human Role Routing

Future RCA escalation: - RTL/DESIGN_BEHAVIOR → DESIGN/DE -
SPEC_INTENT_AMBIGUITY → SHARED where appropriate -
TB/TEST/SEQUENCE/CONSTRAINT → VERIFICATION/DV -
CHECKER/SCOREBOARD/ASSERTION → VERIFICATION/DV - VIP_CONFIGURATION →
VERIFICATION/DV - COVERAGE_MODEL → VERIFICATION/DV -
EDA/LSF/TOOL/ENVIRONMENT → automatic handling first, then appropriate
escalation

Reuse existing classification/registry mechanisms; do not create a
competing system.

## 12. Responsibility by Stage

INTAKE: DE design information/intent; DV verification
requirements/assets. DISCOVERY: DE design-fact confirmation; DV
verification-fact confirmation. CLARIFICATION: DE Design Intent
Authority; DV Verification Intent Authority; DE+DV Shared Authority.
VERIFICATION ARCHITECTURE: DE feasibility/intent review; DV primary
approval. vPLAN: DE feature/design-intent confirmation; DV primary
approval. GENERATION: DE design-specific escalation; DV
verification-specific escalation. REGRESSION/RCA: DE RTL/design
escalation; DV TB/test/VIP/checker/coverage escalation. COVERAGE: DE
design/feature confirmation where needed; DV coverage-closure owner.
WAIVER: DE design-limitation evidence where relevant; DV
verification-waiver authority. SIGNOFF: DE design closure/unresolved
design-risk confirmation; DV verification-signoff authority.

Role presence does not imply mandatory gate.

## 13. M8 --- Role-Aware Experience Learning

M8 must include Knowledge Brain operationalization, Continuous Research
Evolution, Continuous Project Experience Learning, Role-Aware Experience
Learning, DE/DV interaction learning, clarification learning, RCA
role-aware learning, coverage/signoff learning, and Knowledge Domain
Classification.

Use ONE Knowledge Brain.

## 14. Knowledge Domain Classification

Add/reconcile `KNOWLEDGE_DOMAIN = DESIGN | VERIFICATION | SHARED`.

DESIGN examples: register side effects, reset sequence, IRQ behavior,
clocks, FW requirements, design limitations. VERIFICATION examples:
architecture, stimulus/sequence/constraint patterns,
scoreboard/checker/assertion, RCA, coverage closure, waiver/signoff
lessons. SHARED examples: Spec/RTL resolution, feature interpretation,
design limitation + verification strategy.

This is applicability metadata, not separate storage.

## 15. Role-Aware Experience Record

Future model must support equivalent fields: EXPERIENCE_ID,
SOURCE_PROJECT, VERIFICATION_LEVEL, PROTOCOL, KNOWLEDGE_DOMAIN,
HUMAN_ROLE, WORKFLOW_STAGE, OBSERVATION, QUESTION_OR_DECISION,
EVIDENCE_REFS, DECISION, OUTCOME, CONFIDENCE, APPLICABILITY_SCOPE,
COUNTEREXAMPLES, GENERALIZATION_STATE, PROMOTION_STATE.

Reuse existing schema fields where equivalent.

## 16. Role-Aware RCA Learning

Regression Failure → Automatic RCA → DESIGN/VERIFICATION/SHARED
classification → human escalation if needed → validated root cause → fix
→ rerun → experience extraction → knowledge promotion → future RCA
improvement.

Promotion requires evidence/applicability; one project result does not
automatically become universal.

## 17. M9 --- Generic Verification-Level Qualification

Same HITL model must work for IP, SUBSYSTEM, SYSTEM_LEVEL. Do not create
IP_DE_FLOW/IP_DV_FLOW/etc.

Use Generic Workflow + VerificationLevel + HumanRole + QuestionOwner +
profiles + topology + protocol configuration.

## 18. Preserve Current E2E Blockers

Unless newer accepted evidence supersedes: - IP first blocker = Stage
1/router entry; owner M6. - Subsystem reaches Intake, first blocker =
Clarification; owner M6. - System-Level reaches Intake, first blocker =
Clarification; owner M6.

Do not implement in this task.

## 19. M10 --- Coverage / Waiver / Signoff

Coverage Closure primary authority = VERIFICATION/DV; DESIGN/DE
consulted where interpretation depends on design intent. Waiver primary
verification authority = DV; design limitation may require DE
confirmation. Signoff: DV owns Verification Signoff; DE
owns/participates in Design Closure and unresolved design-risk
confirmation.

Preserve evidence of who approved what, authority role, evidence, and
rationale.

## 20. Role-Aware Signoff Traceability

Future traceability: Requirement → OpenSpec → vPlan → Test/Scenario →
Checker/Assertion/Scoreboard → Coverage → Regression Evidence → Waiver →
Human Decision → Authority Role → Signoff.

Add/reconcile equivalents of AUTHORITY_ROLE and HUMAN_DECISION_REF. Do
not implement M10 now.

## 21. M7 --- AI Roles Are Orthogonal

Human roles: DE, DV. AI/model roles: ChatGPT, Claude CLI, Codex, L5DGVA
Agents.

M7 owns ChatGPT Planning Offload, Claude Focused Implementation, Codex
Review Offload, Structured Handoff, Context Distillation, Session
Resume, Token Observability.

M6/M8/M9/M10 own DE/DV behavior. Never model ChatGPT as DE or Codex as
DV.

## 22. Dashboard / UX Requirement

Future dashboard routes: DESIGN ACTION REQUIRED → DE VERIFICATION ACTION
REQUIRED → DV SHARED ACTION REQUIRED → DE+DV

Primary UI exposes project status/evidence/blockers/human decisions, not
Agent/Skill internals. Assign to existing UI/productization owner if
present; otherwise M12. Do not implement UI now.

## 23. Automation Principle

Role routing must not reduce automation. Default: AUTO_DISCOVERY_FIRST.
Human interaction only when evidence/confidence/governance requires it.
Target: MINIMUM_NECESSARY_HUMAN_INTERRUPTION, not approval at every
stage.

## 24. Article 0 Alignment

LOCATION_INDEPENDENT: logical roles, not usernames/hosts.
EVIDENCE_GROUNDED: escalation carries evidence/confidence.
KNOWLEDGE_DRIVEN: retrieve relevant knowledge before asking.
CONTINUOUS_EVOLUTION: DE/DV interactions become evidence-grounded
experience candidates. END_TO_END_DV_ALIGNMENT: same role model spans
Intake→Signoff.

## 25. Master Capability Matrix Update

Add/reconcile without duplicates: ROLE_BASED_HUMAN_IN_THE_LOOP
DESIGN_AUTHORITY VERIFICATION_AUTHORITY SHARED_AUTHORITY
QUESTION_OWNER_ROUTING HUMAN_GATE_CONTRACT RCA_ROLE_ROUTING
ROLE_AWARE_EXPERIENCE_LEARNING KNOWLEDGE_DOMAIN_CLASSIFICATION
ROLE_AWARE_SIGNOFF_TRACEABILITY ROLE_BASED_ACTION_DASHBOARD

For each record CURRENT_STATE, PRIMARY_OWNER_WAVE, PRIORITY, BLOCKER,
EVIDENCE, ARTICLE0_DIMENSION.

Suggested owners: ROLE_BASED_HUMAN_IN_THE_LOOP → M6
QUESTION_OWNER_ROUTING → M6 HUMAN_GATE_CONTRACT → M6 RCA_ROLE_ROUTING →
M6 ROLE_AWARE_EXPERIENCE_LEARNING → M8 KNOWLEDGE_DOMAIN_CLASSIFICATION →
M8 generic three-level role qualification → M9
ROLE_AWARE_SIGNOFF_TRACEABILITY → M10 ROLE_BASED_ACTION_DASHBOARD →
existing UI owner, otherwise M12

Adjust only with stronger existing roadmap evidence.

## 26. E2E Matrix Update

Update existing 17-stage × 3-level E2E matrix with: AUTOMATION_OWNER
HUMAN_ROLE HUMAN_GATE_REQUIRED QUESTION_OWNER CURRENT_STATUS BLOCKER
PRIMARY_OWNER_WAVE

Do not set HUMAN_GATE_REQUIRED=YES merely because a human role exists.

## 27. Global Discoverability / M4.6

Determine whether this role model needs a compact
GLOBAL_DISCOVERABILITY_CONTRACT. If yes, add only minimum routing facts
to ALWAYS_ON governance; detailed DE/DV architecture remains
TASK_SCOPED.

Preserve: TASK_SCOPED_GOVERNANCE_RETRIEVAL = OPERATIONAL M4.6 qualified
context behavior GOVERNANCE_DUMP = prohibited

Do not expand CLAUDE.md with this entire specification.

## 28. Roadmap Update

Update roadmap explicitly:

M5 --- N-Way Capability Semantic Merge; no duplicated DE/DV engines.

M6 --- Core Semantic Merge + VerificationLevel + ClarificationService +
Role-Based HITL + Question Owner + HumanGate + RCA Role Routing.

M7 --- ChatGPT/Claude/Codex operationalization + Structured Handoff +
Context Distillation + Token Observability.

M8 --- Knowledge Brain + Continuous Research Evolution + Continuous
Project Experience Learning + Role-Aware Experience +
DESIGN/VERIFICATION/SHARED knowledge domain.

M9 --- Generic IP/Subsystem/System-Level + same DE/DV role model across
levels.

M10 --- vPlan → Coverage Closure → Traceability → Waiver → Signoff +
role-aware signoff evidence.

M11 --- USB Golden Qualification.

M12 --- Canonical Cutover/Productization + Role-Based Dashboard if
accepted owner.

M13 --- PCIe Zero-Core-Change + Strict Superset + Constitutional
Compliance.

Do not change current NEXT_RECOMMENDED_GATE merely because roadmap is
updated. Preserve an open M4.5 P0 gate if still authoritative.

## 29. Required Outputs

Produce/update under approved Canonical work area, not repo root: -
DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md - DE_DV_AUTHORITY_MATRIX.csv -
HUMAN_GATE_CONTRACT.md - QUESTION_OWNER_ROUTING.md -
RCA_ROLE_ROUTING.md - ROLE_AWARE_EXPERIENCE_REQUIREMENTS.md -
ROLE_AWARE_SIGNOFF_REQUIREMENTS.md - DE_DV_E2E_ROLE_MATRIX.csv -
DE_DV_ROADMAP_IMPACT.md

Update existing: - MASTER_CAPABILITY_STATUS_MATRIX -
MASTER_WAVE_OWNERSHIP_MATRIX - MASTER_END_TO_END_DV_STATUS -
MASTER_PROGRAM_STATUS

Do not create competing authority if equivalent files already exist.

## 30. Validation

Verify: ONE_GENERIC_DE_DV_WORKFLOW = YES SEPARATE_DE_ENGINE_CREATED = NO
SEPARATE_DV_ENGINE_CREATED = NO DESIGN_AUTHORITY = DEFINED
VERIFICATION_AUTHORITY = DEFINED SHARED_AUTHORITY = DEFINED
QUESTION_OWNER_CONTRACT = DEFINED CLARIFICATION_TARGET_ARCHITECTURE =
ONE_CANONICAL_CLARIFICATION_SERVICE ROLE_AWARE_EXPERIENCE_MODEL =
DEFINED KNOWLEDGE_BRAIN_COUNT = 1 IP_SUBSYSTEM_SYSTEM_ROLE_MODEL =
GENERIC ROLE_AWARE_SIGNOFF_MODEL = DEFINED
M7_AI_MODEL_ROLES_SEPARATE_FROM_HUMAN_ROLES = YES
M4_6_CONTEXT_ARCHITECTURE_PRESERVED = YES CLAUDE_MD_GOVERNANCE_DUMP = NO
SOURCE_CAPABILITY_LOSS = 0 REFERENCE_USB_ENV_CONSUMED = NO

Run applicable Constitution/Anti-Drift and governance consistency tests.
Do not run a full product regression unless existing governance requires
it for roadmap/document/matrix-only changes.

## 31. Required Final Report

Report:

DE_DV_ROLE_MODEL_STATUS = READY_FOR_APPROVAL / PARTIAL / BLOCKED
ROLE_BASED_HUMAN_IN_THE_LOOP = DEFINED / PARTIAL / NOT_DEFINED
DESIGN_AUTHORITY = DEFINED / NOT_DEFINED VERIFICATION_AUTHORITY =
DEFINED / NOT_DEFINED SHARED_AUTHORITY = DEFINED / NOT_DEFINED
QUESTION_OWNER_ROUTING = DEFINED / PARTIAL / NOT_DEFINED
HUMAN_GATE_CONTRACT = DEFINED / PARTIAL / NOT_DEFINED RCA_ROLE_ROUTING =
DEFINED / PARTIAL / NOT_DEFINED ROLE_AWARE_EXPERIENCE_LEARNING =
ROADMAP_DEFINED / PARTIAL / NOT_DEFINED KNOWLEDGE_DOMAIN_CLASSIFICATION
= DEFINED / PARTIAL / NOT_DEFINED ROLE_AWARE_SIGNOFF_TRACEABILITY =
ROADMAP_DEFINED / PARTIAL / NOT_DEFINED ROLE_BASED_ACTION_DASHBOARD =
ROADMAP_DEFINED / EXISTING / NOT_DEFINED
MASTER_CAPABILITIES_ADDED_OR_RECONCILED = `<count>`{=html}
P0_BLOCKERS_BEFORE = `<count>`{=html} P0_BLOCKERS_AFTER =
`<count>`{=html} CURRENT_PROGRAM_POSITION = `<position>`{=html}
NEXT_RECOMMENDED_GATE = `<gate>`{=html}

M5_STARTED = NO M6_STARTED = NO M7_STARTED = NO M8_STARTED = NO
M9_STARTED = NO M10_STARTED = NO REFERENCE_USB_ENV_CONSUMED = NO
PLATFORM_UPGRADE_STARTED = NO

## 32. STOP

After roadmap, matrices, contracts, and reports are reconciled and
validated, STOP.

Do not implement the roadmap. Do not start the next wave. Wait for
explicit approval.
