# L5DGVA --- Three UX Modes Roadmap Reconciliation Master Prompt

## Mission

Perform **ROADMAP / CAPABILITY / GOVERNANCE RECONCILIATION ONLY** for: -
`GUIDED_MODE` - `ENGINEER_MODE` - `EXPERT_MODE`

Do **not** implement runtime UX behavior, start M5 or later waves,
consume the reference USB environment, start platform upgrade work, or
modify frozen sources.

## Authoritative checkpoint

``` text
HEAD = 9d76dd1
DE_DV_ROLE_MODEL_STATUS = READY_FOR_APPROVAL
ROLE_BASED_HUMAN_IN_THE_LOOP = DEFINED
DESIGN_AUTHORITY = DEFINED
VERIFICATION_AUTHORITY = DEFINED
SHARED_AUTHORITY = DEFINED
QUESTION_OWNER_ROUTING = ROADMAP_DEFINED
HUMAN_GATE_CONTRACT = ROADMAP_DEFINED
RCA_ROLE_ROUTING = ROADMAP_DEFINED
ROLE_AWARE_EXPERIENCE_LEARNING = ROADMAP_DEFINED
KNOWLEDGE_DOMAIN_CLASSIFICATION = DEFINED
ROLE_AWARE_SIGNOFF_TRACEABILITY = ROADMAP_DEFINED
ROLE_BASED_ACTION_DASHBOARD = ROADMAP_DEFINED
MASTER_CAPABILITIES_ADDED_OR_RECONCILED = 12
P0_BLOCKERS_BEFORE = 7
P0_BLOCKERS_AFTER = 7
M4/M4.5/M4.6 = CLOSED
M5_STARTED = NO
M6_STARTED = NO
M7_STARTED = NO
M8_STARTED = NO
M9_STARTED = NO
M10_STARTED = NO
REFERENCE_USB_ENV_CONSUMED = NO
PLATFORM_UPGRADE_STARTED = NO
NEXT_RECOMMENDED_GATE = M5_N_WAY_CAPABILITY_SEMANTIC_MERGE
```

Before editing, verify HEAD, git status, authoritative status artifacts,
frozen-source integrity, and consistency with this checkpoint. On
material mismatch: **STOP and report; do not silently normalize.**

## Frozen architecture

Preserve:

``` text
ONE_GENERIC_DE_DV_WORKFLOW = YES
ONE_KNOWLEDGE_BRAIN = YES
ONE_CLARIFICATION_SERVICE = YES
```

DE/DV are authority roles, not pipelines:

``` text
DESIGN_AUTHORITY
VERIFICATION_AUTHORITY
SHARED_AUTHORITY
```

Never create separate DE/DV workflows, engines, Knowledge Brains, or
clarification services.

`SHARED_AUTHORITY` is not a lazy fallback. Classification must prefer
evidence-based `DESIGN_AUTHORITY` or `VERIFICATION_AUTHORITY`; use
`SHARED_AUTHORITY` only for genuinely cross-domain decisions. Otherwise
use `CLASSIFICATION_UNRESOLVED` and gather evidence/escalate.

## Mandatory semantic separation

``` text
UX_MODE != ROLE != AUTHORIZATION != AUTONOMY_LEVEL
```

Conceptual model:

``` text
ONE L5DGVA WORKFLOW
       |
Generic DV Lifecycle
       |
 +-----+--------------------+
 |                          |
UX MODE                 HUMAN ROLE
 |                          |
GUIDED                  DESIGN_AUTHORITY
ENGINEER                VERIFICATION_AUTHORITY
EXPERT                  SHARED_AUTHORITY
 |                          |
Interaction Policy      Decision Ownership
 +------------+-------------+
              |
        AUTHORIZATION
              |
        AUTONOMY POLICY
              |
 AUTO / REVIEW_REQUIRED / HUMAN_GATE / BLOCKED
```

UX mode may alter explanation depth, proactive guidance, evidence
presentation, progressive disclosure, confirmation style, educational
assistance, and advanced-control visibility. It must never alter
engineering truth, ownership, authorization, waiver authority, RTL-write
authority, or signoff authority.

## Role ownership

`DESIGN_AUTHORITY` owns design intent, architecture intent, spec
interpretation, RTL functional behavior, design assumptions,
implementation intent, and RTL functional-fix approval.

`VERIFICATION_AUTHORITY` owns verification strategy, vPlan, verification
completeness, testcase/checker strategy, coverage strategy/closure,
verification waiver, and verification signoff.

`SHARED_AUTHORITY` is only for decisions genuinely requiring both
domains.

## Authorization

Reuse the repository's canonical authorization model. Potential concepts
include `READ`, `EXECUTE`, `TB_WRITE`, `RTL_WRITE`, `WAIVER_APPROVE`,
`SIGNOFF_APPROVE`, `POLICY_OVERRIDE`; do not create competing
terminology.

Required semantics:

``` text
EXPERT_MODE != RTL_WRITE
EXPERT_MODE != WAIVER_APPROVE
EXPERT_MODE != SIGNOFF_APPROVE
EXPERT_MODE != POLICY_OVERRIDE
```

unless separately authorized.

## Autonomy

Future autonomy policy may use:

``` text
UX Mode + Role + Authorization + Task Risk + Evidence Quality
+ Confidence + Impact + Reversibility + Signoff Impact
```

to produce:

``` text
AUTO / REVIEW_REQUIRED / HUMAN_GATE / BLOCKED
```

Do not implement a new production autonomy engine in this task.

# GUIDED_MODE

Target: junior/new DV, users new to a protocol/project, first-time
L5DGVA users, or experienced engineers intentionally requesting
guidance.

Do **not** equate `GUIDED_MODE` with `JUNIOR`.

Principle: \> The user should not need to know what question to ask.
L5DGVA discovers first, identifies gaps, explains why clarification is
required, presents evidence, recommends the owner, and recommends the
next action.

Future question contract:

``` text
Question
Why am I asking?
Observed Evidence
Engineering Impact
Confidence
Recommended Owner
Recommended Action
```

Required response concepts:

``` text
YES
NO
NOT_SURE
I_DONT_KNOW
SHOW_EVIDENCE
ASK_DE
ASK_SENIOR_DV
```

`I_DONT_KNOW` is valid engineering input, not workflow failure.
Conceptual handling:

``` text
I_DONT_KNOW
 -> Evidence Search
 -> ONE Knowledge Brain
 -> Project Evidence
 -> Spec / RTL / VIP / Docs / Tests
 -> Previous RCA / KC / history
 -> still unresolved?
 -> QUESTION_OWNER_ROUTING
 -> DESIGN_AUTHORITY / VERIFICATION_AUTHORITY /
    genuine SHARED_AUTHORITY / CLASSIFICATION_UNRESOLVED
```

GUIDED_MODE should eventually act as an AI mentor by explaining the
reasoning path, not merely returning answers.

# ENGINEER_MODE

Target: experienced DV engineers and normal daily operation.

Principle: \> AI performs routine engineering work while the engineer
supervises exceptions and meaningful decisions.

Default presentation:

``` text
Current State
Action Taken
Result
Evidence Summary
Confidence
Next Action
```

Semantics: concise interaction; low-risk routine execution when policy
permits; no repetitive basic teaching; evidence summary by default;
details on demand; ambiguity escalation; governed high-risk/signoff
decisions.

# EXPERT_MODE

Target: senior DV, DV leads, verification architects, authorized
advanced users.

Principle: \> Maximum permitted engineering efficiency with direct
visibility into state, evidence, and advanced controls.

Potential future visibility: `Graph State`, `Lifecycle State`,
`Agent Routing`, `Skill Routing`, `Execution Profile`, `Evidence Graph`,
`Confidence`, `Regression`, `Coverage`, `RCA Hypotheses`,
`Knowledge Brain State`, `Human Gate State`.

Potential future controls: `continue`, `pause`, `retry`, `replan`,
`kill`, `rollback`, `reroute agent`, `reroute skill`,
`refresh evidence`.

These are roadmap concepts only. `EXPERT_MODE` never means unrestricted
permission.

## Same engineering truth

Required invariant:

``` text
SAME_INPUT + SAME_EXECUTION_EVIDENCE = SAME_ENGINEERING_STATE
```

for all three modes.

UX mode must not change requirement/design/RTL truth,
simulation/regression/coverage results, evidence validity,
`ValidationState`, `ConfirmationState`, or signoff truth.

## Evidence model

Preserve canonical fields where applicable:

``` text
DeclaredValue
AutoDiscoveredValue
DerivedValue
EffectiveValue
Confidence
ValidationState
ConfirmationState
EvidenceRefs
```

One evidence truth, different presentation:

``` text
GUIDED   -> explanation / teaching
ENGINEER -> concise engineering summary
EXPERT   -> detailed evidence / state
```

## DE/DV HITL integration

UX mode consumes the existing role-based HITL roadmap.
Owner/gate/evidence/state do not change with UX mode.

Example: RTL `NUM_EP=4` versus Spec `EP0-EP2` may classify as
`DESIGN_INTENT_AMBIGUITY` owned by `DESIGN_AUTHORITY`. GUIDED explains
why; ENGINEER summarizes; EXPERT exposes gate/state/evidence. Ownership
is identical.

## RCA routing

Reconcile with `RCA_ROLE_ROUTING`:

``` text
TB/VIP/Test/Coverage methodology -> VERIFICATION_AUTHORITY
RTL/Design Intent/Functional Behavior -> DESIGN_AUTHORITY
Genuine cross-domain -> SHARED_AUTHORITY
Insufficient evidence -> CLASSIFICATION_UNRESOLVED -> evidence/clarification
```

## Experience learning

Reconcile with `ROLE_AWARE_EXPERIENCE_LEARNING`. Valid examples:

``` text
Senior DV + GUIDED_MODE
Junior DV + ENGINEER_MODE
```

subject to role, authorization, risk and autonomy policy. Experience
must never silently grant authority/authorization.

## Knowledge Brain

Keep exactly one Knowledge Brain. Never create Junior/Engineer/Expert or
DE/DV Knowledge Brains.

## Signoff

Reconcile with `ROLE_AWARE_SIGNOFF_TRACEABILITY`. UX mode does not
determine signoff ownership. `EXPERT_MODE` does not grant
`SIGNOFF_APPROVE`.

## Dashboard

Reconcile future semantics with `ROLE_BASED_ACTION_DASHBOARD`.

Potential dimensions: `UX Mode`, `Role`, `Authorization`,
`Autonomy State`, `Current Human Gate`, `Question Owner`,
`Evidence Confidence`, `Lifecycle State`.

GUIDED emphasizes what/why/evidence/next action/owner. ENGINEER
emphasizes state/exceptions/evidence/next action. EXPERT emphasizes
graph/agents/skills/execution/evidence/coverage/RCA/controls.

Do not implement runtime dashboard behavior now.

## AI-provider independence

Never bind modes to providers:

``` text
GUIDED_MODE != ChatGPT
ENGINEER_MODE != Claude
EXPERT_MODE != Codex
```

Correct abstraction:

``` text
UX Policy -> L5DGVA Workflow -> Agent Router
          -> ChatGPT / Claude / Codex / Gemini / Future Agent
```

## Candidate master capabilities

Assess and reconcile:

``` text
UX_MODE_MODEL
GUIDED_MODE
ENGINEER_MODE
EXPERT_MODE
UX_POLICY_ENGINE
UX_ROLE_ORTHOGONALITY
EXPERIENCE_AWARE_INTERACTION
PROGRESSIVE_EVIDENCE_DISCLOSURE
```

For each: search canonical registry, roadmap/status,
architecture/governance docs, and semantic equivalents. Do not
duplicate. Classify as:

``` text
NEW
MERGED
ALREADY_COVERED
DEFERRED
REJECTED_AS_DUPLICATE
```

## Anti-drift semantics

Assess canonical governance coverage for:

``` text
ONE_GENERIC_DE_DV_WORKFLOW = YES
ONE_KNOWLEDGE_BRAIN = YES
ONE_CLARIFICATION_SERVICE = YES
UX_MODE_COUNT = 3
GUIDED_MODE_IS_NOT_A_WORKFLOW = YES
ENGINEER_MODE_IS_NOT_A_WORKFLOW = YES
EXPERT_MODE_IS_NOT_A_WORKFLOW = YES
UX_MODE_DOES_NOT_GRANT_AUTHORITY = YES
UX_MODE_DOES_NOT_CHANGE_ENGINEERING_TRUTH = YES
UX_MODE_DOES_NOT_BYPASS_HUMAN_GATES = YES
SHARED_AUTHORITY_IS_NOT_DEFAULT_FALLBACK = YES
```

Use repository-native naming if different, preserving semantics.

## Existing roadmap capabilities to reconcile

``` text
QUESTION_OWNER_ROUTING
HUMAN_GATE_CONTRACT
RCA_ROLE_ROUTING
ROLE_AWARE_EXPERIENCE_LEARNING
KNOWLEDGE_DOMAIN_CLASSIFICATION
ROLE_AWARE_SIGNOFF_TRACEABILITY
ROLE_BASED_ACTION_DASHBOARD
```

Do not create parallel replacements.

## Strict scope restrictions

DO NOT: - start M5/M6/M7/M8/M9/M10; - start an implementation wave; -
modify production runtime behavior; - create DE/DV or per-mode workflow
engines; - create multiple Knowledge Brains/clarification services; -
consume reference USB environment; - start platform upgrade; - modify
frozen sources; - silently change unrelated roadmap items or P0
counts; - weaken Constitution/Anti-Drift; - treat SHARED as fallback; -
grant authority via UX mode; - claim runtime implementation; - claim
validation without evidence.

Preserve `CLAUDE.md` unless existing governance explicitly requires a
roadmap-only update.

## Allowed changes

Only minimum roadmap/governance/master-capability documentation needed
for reconciliation. Establish authority/relevance before editing each
file. No broad cleanup, opportunistic refactor, or production code
changes.

## Validation

Validate:

``` text
ONE_GENERIC_DE_DV_WORKFLOW = YES
ONE_KNOWLEDGE_BRAIN = YES
ONE_CLARIFICATION_SERVICE target preserved
No separate DE/DV engines
No Guided/Engineer/Expert workflow engines
UX_MODE_COUNT = 3
UX mode orthogonal to role
UX mode orthogonal to authorization
UX mode does not alter engineering truth
UX mode does not bypass human gates
SHARED is not fallback
All existing DE/DV HITL roadmap capabilities remain compatible
M5_STARTED = NO
M6_STARTED = NO
M7_STARTED = NO
M8_STARTED = NO
M9_STARTED = NO
M10_STARTED = NO
REFERENCE_USB_ENV_CONSUMED = NO
PLATFORM_UPGRADE_STARTED = NO
```

Also validate Constitution, Anti-Drift, governance registry, master
capability registry, master program status, reference graph and
frozen-source integrity. Run dedicated governance/roadmap validators if
present.

## P0 policy

Checkpoint says `P0_BLOCKERS_BEFORE=7`, `P0_BLOCKERS_AFTER=7`. Do not
force this if evidence proves a genuine blocker, but do not invent or
silently alter blockers. Preferred clean result: zero new P0 items.

## Completion status

Do not claim any UX mode or `UX_POLICY_ENGINE` is runtime `IMPLEMENTED`
unless pre-existing repository evidence independently proves it.
Expected result is roadmap/capability/governance status such as
`ROADMAP_DEFINED`, `DEFINED`, or `RECONCILED`.

## Required final report

Return:

``` text
L5DGVA THREE UX MODES ROADMAP RECONCILIATION

START_HEAD =
END_HEAD =
GIT_STATUS_BEFORE =
GIT_STATUS_AFTER =

UX_MODE_MODEL_STATUS =
GUIDED_MODE_STATUS =
ENGINEER_MODE_STATUS =
EXPERT_MODE_STATUS =
UX_POLICY_ENGINE_STATUS =
UX_ROLE_ORTHOGONALITY_STATUS =
EXPERIENCE_AWARE_INTERACTION_STATUS =
PROGRESSIVE_EVIDENCE_DISCLOSURE_STATUS =

MASTER_CAPABILITIES_ADDED_OR_RECONCILED =
NEW_CAPABILITIES =
MERGED_CAPABILITIES =
ALREADY_COVERED =
DEFERRED =
REJECTED_AS_DUPLICATE =

P0_BLOCKERS_BEFORE =
P0_BLOCKERS_AFTER =
NEW_P0_BLOCKERS =

ONE_GENERIC_DE_DV_WORKFLOW = YES/NO
ONE_KNOWLEDGE_BRAIN = YES/NO
ONE_CLARIFICATION_SERVICE = YES/NO
UX_MODE_COUNT =
UX_MODE_ROLE_ORTHOGONAL = YES/NO
UX_MODE_AUTHORIZATION_ORTHOGONAL = YES/NO
UX_MODE_CHANGES_ENGINEERING_TRUTH = YES/NO
UX_MODE_CAN_BYPASS_HUMAN_GATES = YES/NO
SHARED_AUTHORITY_DEFAULT_FALLBACK = YES/NO

QUESTION_OWNER_ROUTING_COMPATIBLE = YES/NO
HUMAN_GATE_CONTRACT_COMPATIBLE = YES/NO
RCA_ROLE_ROUTING_COMPATIBLE = YES/NO
ROLE_AWARE_EXPERIENCE_LEARNING_COMPATIBLE = YES/NO
KNOWLEDGE_DOMAIN_CLASSIFICATION_COMPATIBLE = YES/NO
ROLE_AWARE_SIGNOFF_TRACEABILITY_COMPATIBLE = YES/NO
ROLE_BASED_ACTION_DASHBOARD_COMPATIBLE = YES/NO

M5_STARTED = YES/NO
M6_STARTED = YES/NO
M7_STARTED = YES/NO
M8_STARTED = YES/NO
M9_STARTED = YES/NO
M10_STARTED = YES/NO
REFERENCE_USB_ENV_CONSUMED = YES/NO
PLATFORM_UPGRADE_STARTED = YES/NO

PRODUCTION_FILES_MODIFIED =
FROZEN_SOURCES_MODIFIED =
CLAUDE_MD_MODIFIED =

VALIDATIONS_RUN =
VALIDATIONS_PASS =
VALIDATIONS_FAIL =

FILES_CHANGED =
COMMITS_CREATED =

NEXT_RECOMMENDED_GATE =
OPEN_QUESTIONS =
KNOWN_LIMITATIONS =
```

## Stop condition

After roadmap reconciliation, validation, and final report:

**STOP.**

Do not start `M5_N_WAY_CAPABILITY_SEMANTIC_MERGE`.

Do not begin implementation of the UX modes.

Wait for explicit human review/approval.
