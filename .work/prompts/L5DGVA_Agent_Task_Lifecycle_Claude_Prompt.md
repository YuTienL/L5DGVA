# L5DGVA --- Agent Task Lifecycle Capability Reconciliation Prompt

## Mission

Evaluate whether current **v50 + DV Agent Harness L5 / canonical
L5DGVA** needs a formal **Agent Task Lifecycle Contract**. This is
roadmap/capability/governance analysis only---not authorization to
implement a new lifecycle engine.

> Prefer extending/canonicalizing existing lifecycle, graph, evidence,
> HITL, session persistence, ExecutionService, and Knowledge Brain
> mechanisms over creating a competing engine.

## Current checkpoint

Verify all values against repository evidence before edits: - DE/DV Role
Model: `READY_FOR_APPROVAL` - M4/M4.5/M4.6: CLOSED - M5--M10: NOT
STARTED - `REFERENCE_USB_ENV_CONSUMED=NO` -
`PLATFORM_UPGRADE_STARTED=NO` - next gate:
`M5_N_WAY_CAPABILITY_SEMANTIC_MERGE` - previously reported HEAD:
`9d76dd1`

Verify HEAD, git status, milestone/status artifacts, governance and
frozen-source integrity. On material mismatch: **STOP and report; never
silently normalize.**

## Frozen architecture

Preserve:

``` text
ONE_GENERIC_DE_DV_WORKFLOW = YES
ONE_KNOWLEDGE_BRAIN = YES
ONE_CLARIFICATION_SERVICE = YES
```

DE/DV are authority roles, not pipelines. `SHARED_AUTHORITY` is only for
genuinely cross-domain decisions, never a fallback.

## Two lifecycle views

### DV Engineering Lifecycle

``` text
INTAKE → DISCOVERY → PLAN → IMPLEMENT → VERIFY → REGRESSION
→ RCA → COVERAGE → SIGNOFF → KNOWLEDGE
```

Answers: what stages must a DV project pass?

### Agent Task Lifecycle

``` text
TASK_CREATED → CONTRACT_LOADED → PREFLIGHT → SCOPE_CHECK → PLAN
→ WAITING_APPROVAL → EXECUTE → COLLECT_EVIDENCE → VALIDATE
→ WAITING_REVIEW → CLOSE / REWORK / ESCALATE
```

Answers: how is an AI engineering task governed end-to-end?

Do not create unrelated lifecycle systems. Prefer:

``` text
Existing L5DGVA Lifecycle/State Model
  ├─ DV Lifecycle State
  └─ Task Lifecycle State
       ↓
  Same State Store / Evidence / HITL / Audit
```

## Candidate capabilities

Evaluate:

``` text
AGENT_TASK_LIFECYCLE
TASK_IDENTITY
TASK_STATE_MODEL
TASK_SCOPE_CONTRACT
TASK_PREFLIGHT_GATE
TASK_APPROVAL_GATE
TASK_EVIDENCE_CONTRACT
TASK_FAILURE_RECOVERY
TASK_RESUME_REPLAY
TASK_KNOWLEDGE_PROMOTION_GATE
```

Classify each: `NEW`, `EXTEND_EXISTING`, `MERGE_WITH_EXISTING`,
`ALREADY_COVERED`, `DEFERRED`, or `REJECTED_AS_DUPLICATE`.

## Required semantic search

Before proposing new capability, inspect semantic equivalents in
lifecycle/transition history, graph orchestration, INTAKE-first,
task/job/execution state, Session Save/Restore,
checkpoint/resume/replay, evidence fields, HITL, DE/DV routing,
approvals, regression/RCA/retry/rollback, ExecutionService, Knowledge
Brain/KC, OpenSpec, Constitution, Anti-Drift, governance/master
registries, roadmap, and `.work` artifacts. Include
v50/parent/canonical/approved inputs relevant to future M5, but **do not
start M5**.

## TASK_IDENTITY

Determine whether one stable task ID can correlate Prompt/Contract,
Plan, Approvals, Execution, Evidence, Validation, Report, Commits, Human
Review and Knowledge Candidate across session restart and provider
changes.

## TASK_STATE_MODEL

Evaluate whether current lifecycle can represent:

``` text
CREATED → PREFLIGHT → WAITING_APPROVAL → APPROVED
→ EXECUTING → VALIDATING → WAITING_REVIEW → COMPLETED
```

Exceptions: `BLOCKED`, `FAILED`, `CANCELLED`, `REWORK_REQUIRED`. Reuse
canonical state names.

## TASK_SCOPE_CONTRACT

Assess machine-verifiable scope rather than prompt-only restrictions.
Conceptually:

``` yaml
allowed: [roadmap, governance, capability_registry]
forbidden: [production_code, frozen_sources, reference_usb_env]
milestone_ceiling: M4.6
next_gate: M5_N_WAY_CAPABILITY_SEMANTIC_MERGE
```

Format is illustrative. Integrate with Constitution, Anti-Drift,
frozen-source policy, milestone gates, authorization, execution
permissions and git-diff validation.

## TASK_PREFLIGHT_GATE

Formal semantics should verify HEAD, git status, checkpoint, scope,
dependencies, frozen sources, milestone state and required tools.
Contradiction must lead to `BLOCKED → REPORT → HUMAN`; no silent repair.

## TASK_APPROVAL_GATE

Reuse HITL:

``` text
PREFLIGHT_COMPLETE → WAITING_APPROVAL
→ ROLE/AUTHORIZATION CHECK → HUMAN_GATE
→ APPROVE / REJECT
```

An Agent must never self-approve a mandatory gate.

## TASK_EVIDENCE_CONTRACT

Completion cannot mean "Agent says PASS." Evaluate capture of input,
preflight, plan, modification, execution, test, validation, git, human
approval and final-report evidence. Preserve canonical fields:
`DeclaredValue`, `AutoDiscoveredValue`, `DerivedValue`,
`EffectiveValue`, `Confidence`, `ValidationState`, `ConfirmationState`,
`EvidenceRefs`.

## TASK_FAILURE_RECOVERY

Evaluate distinctions such as `FAILED_AGENT`, `FAILED_TOOL`,
`FAILED_ENVIRONMENT`, `FAILED_VALIDATION`, `BLOCKED_HUMAN`,
`BLOCKED_EVIDENCE`, `BLOCKED_DEPENDENCY`, `SCOPE_VIOLATION`, reusing
existing taxonomy. Determine support for `RETRY`, `REPLAN`, `ROLLBACK`,
`ESCALATE`, `HUMAN_GATE`, `CANCEL`.

## TASK_RESUME_REPLAY

Determine whether interrupted work can resume from persisted `TASK_ID`,
status, contract, plan, completed/current steps, evidence, gate, next
action, start/current HEAD---without conversation memory. Evaluate
overlap with Session Save/Restore, lifecycle persistence and replay.

## TASK_KNOWLEDGE_PROMOTION_GATE

Preserve:

``` text
Task Result → Candidate Knowledge → Evidence Validation
→ Human/Governance Gate → KC → Canonical Knowledge
```

Invariant: `TASK_COMPLETED != CANONICAL_KNOWLEDGE`.

## `.work` artifact model

Inspect current conventions before proposing changes. Possible future
structure:

``` text
.work/
├── prompts/
├── plans/
├── issues/
├── evidence/
├── reports/
└── checkpoints/
```

Task artifacts may correlate by TASK_ID. **Do not broadly restructure
`.work` now.**

## UX modes

`GUIDED_MODE`, `ENGINEER_MODE`, `EXPERT_MODE` share the same task
truth/state. UX only changes presentation. Never create per-mode task
lifecycles.

## DE/DV HITL

Reuse `DESIGN_AUTHORITY`, `VERIFICATION_AUTHORITY`, `SHARED_AUTHORITY`,
`QUESTION_OWNER_ROUTING`, `HUMAN_GATE_CONTRACT`, `RCA_ROLE_ROUTING`, and
signoff traceability. Do not create Agent-specific authority.

## Provider independence

Correct abstraction:

``` text
L5DGVA Task Contract → Agent Router
→ Claude / Codex / ChatGPT / Gemini / Future Agent
```

Provider changes must not lose task identity, scope, evidence, approvals
or state.

## ExecutionService

Evaluate:

``` text
Task Lifecycle → Execution Request → ExecutionService
→ LocalBackend / RemoteEDABackend → Tool Result
→ Task Evidence → State Transition
```

Preserve location independence.

## Graph

Determine whether task lifecycle is best represented as existing
lifecycle metadata, graph nodes, reusable subgraph, or contracts around
current execution. Do not assume a new graph is necessary.

## M5 relationship

Do not start `M5_N_WAY_CAPABILITY_SEMANTIC_MERGE`. Prepare semantic
candidates/evidence so M5 can later compare v50, Parent, canonical
L5DGVA and approved inputs, and determine overlap with Lifecycle,
Session Save/Restore, Evidence, HITL, ExecutionService and Knowledge
governance.

## No-new-engine default

``` text
AGENT_TASK_LIFECYCLE SHOULD EXTEND EXISTING_LIFECYCLE
```

Do not create `agent_task_engine.py` merely because the capability has a
name. `Capability != engine`; `Contract != service`;
`State model != new state store`.

## Candidate invariants

Assess semantics equivalent to:

``` text
ONE_CANONICAL_LIFECYCLE_MODEL = YES
ONE_CANONICAL_EVIDENCE_MODEL = YES
TASK_HAS_STABLE_IDENTITY = YES
TASK_SCOPE_IS_EXPLICIT = YES
MANDATORY_PREFLIGHT_CANNOT_BE_SKIPPED = YES
MANDATORY_HUMAN_GATE_CANNOT_BE_SELF_APPROVED = YES
TASK_COMPLETION_REQUIRES_EVIDENCE = YES
TASK_CAN_RESUME_FROM_PERSISTED_STATE = YES
TASK_COMPLETED_DOES_NOT_IMPLY_CANONICAL_KNOWLEDGE = YES
AGENT_PROVIDER_DOES_NOT_OWN_TASK_TRUTH = YES
```

Use repository-native naming where different.

## Strict scope restrictions

DO NOT start M5--M10; implement a new task lifecycle engine; create
parallel lifecycle/state/evidence/HITL systems; create
per-provider/per-UX/per-DE-DV lifecycle systems; create multiple
Knowledge Brains/clarification services; consume USB reference; start
platform upgrade; modify frozen sources; silently change P0 counts;
weaken Constitution/Anti-Drift; broadly restructure `.work`; or claim
runtime capability without evidence.

## Required analysis table

Produce: \| Candidate \| Existing Evidence \| Existing Capability \| Gap
\| Decision \| Recommended M5 Action \| \|---\|---\|---\|---\|---\|---\|
for all ten candidate capabilities.

## Required verdict

Explicitly answer:

``` text
DOES_L5DGVA_NEED_A_NEW_AGENT_TASK_LIFECYCLE_ENGINE = YES/NO
DOES_L5DGVA_NEED_A_CANONICAL_AGENT_TASK_LIFECYCLE_CONTRACT = YES/NO
CAN_EXISTING_LIFECYCLE_BE_EXTENDED = YES/NO
CAN_EXISTING_EVIDENCE_MODEL_BE_REUSED = YES/NO
CAN_EXISTING_HITL_BE_REUSED = YES/NO
CAN_EXISTING_SESSION_SAVE_RESTORE_BE_REUSED = YES/NO/PARTIAL
CAN_EXISTING_EXECUTION_SERVICE_BE_REUSED = YES/NO/PARTIAL
CAN_EXISTING_KNOWLEDGE_GOVERNANCE_BE_REUSED = YES/NO/PARTIAL
```

Evidence is authoritative; do not force an expected answer.

## Required final report

``` text
L5DGVA AGENT TASK LIFECYCLE CAPABILITY REVIEW

START_HEAD =
END_HEAD =
GIT_STATUS_BEFORE =
GIT_STATUS_AFTER =

AGENT_TASK_LIFECYCLE =
TASK_IDENTITY =
TASK_STATE_MODEL =
TASK_SCOPE_CONTRACT =
TASK_PREFLIGHT_GATE =
TASK_APPROVAL_GATE =
TASK_EVIDENCE_CONTRACT =
TASK_FAILURE_RECOVERY =
TASK_RESUME_REPLAY =
TASK_KNOWLEDGE_PROMOTION_GATE =

NEW_CAPABILITIES =
EXTENDED_CAPABILITIES =
MERGED_CAPABILITIES =
ALREADY_COVERED =
DEFERRED =
REJECTED_AS_DUPLICATE =

NEW_ENGINE_REQUIRED = YES/NO
EXISTING_LIFECYCLE_REUSABLE = YES/NO/PARTIAL
EXISTING_EVIDENCE_REUSABLE = YES/NO/PARTIAL
EXISTING_HITL_REUSABLE = YES/NO/PARTIAL
SESSION_RESTORE_REUSABLE = YES/NO/PARTIAL
EXECUTION_SERVICE_REUSABLE = YES/NO/PARTIAL
KNOWLEDGE_GOVERNANCE_REUSABLE = YES/NO/PARTIAL

ONE_GENERIC_DE_DV_WORKFLOW = YES/NO
ONE_KNOWLEDGE_BRAIN = YES/NO
ONE_CLARIFICATION_SERVICE = YES/NO

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
FILES_CHANGED =
VALIDATIONS_RUN =
VALIDATIONS_PASS =
VALIDATIONS_FAIL =
P0_BLOCKERS_BEFORE =
P0_BLOCKERS_AFTER =
NEW_P0_BLOCKERS =

RECOMMENDED_M5_CANDIDATES =
OPEN_GAPS =
KNOWN_LIMITATIONS =
NEXT_RECOMMENDED_GATE =
```

## Stop condition

After analysis/reconciliation, validation and final report:

**STOP.**

Do not start M5. Do not implement Agent Task Lifecycle runtime behavior.
Wait for explicit human review/approval.
