# L5DGVA M7 Structured Multi-Model Markdown Handoff Implementation Prompt

## Mission

Implement and qualify M7 V1 multi-model logical orchestration using
**structured Markdown transported manually by the human operator**
between Claude CLI, Codex, and ChatGPT.

Approved transport:

``` text
Claude ↔ Codex = HUMAN_MEDIATED_MD_HANDOFF
Claude ↔ ChatGPT = HUMAN_MEDIATED_MD_HANDOFF
DIRECT_MODEL_API = NOT_REQUIRED
```

Do not build API-based model-to-model transport. Prime Directive V2
remains authoritative. M6's qualified Golden Workflow is a frozen
non-regression baseline.

## 1. Preflight

Record PROCESS_CWD, REPO_ROOT, CURRENT_BRANCH, CURRENT_HEAD,
WORKING_TREE_STATUS.

Read completely: -
`L5DGVA_M7_STRUCTURED_MULTI_MODEL_MD_HANDOFF_ARCHITECTURE.md` - Prime
Directive V2 - M6 final qualification artifacts - prior M4.5
ChatGPT/Codex audit - existing Task Identity / Task Scope / Agent Task
Lifecycle contracts - EvidenceRefs / OpenSpec contracts - Task
Boundary - governance registry - existing issue-md/checkpoint/review
mechanisms - all M7-owned Master capability rows.

Do not repeat settled audits unless Canonical evidence changed. Verify
Parent/v50/b7a/b7b/b8 unchanged.

## 2. Freeze M6

Preserve:

``` text
M6_STATUS=CLOSED
STRUCTURAL_CONNECTED_STAGES=10/10
PRODUCTION_CONNECTED_STAGES=10/10
EVIDENCE_CONNECTED_STAGES=10/10
QUALIFIED_CONNECTED_STAGES=10/10
HITL_QUALIFICATION=PASS
CAPABILITY_ISLANDS=0
UNCONTROLLED_BYPASSES=0
```

Create/reuse an M7 M6-non-regression contract. Any M7 regression follows
FIND → FIX → VERIFY.

## 3. Reconcile Starting State

Re-verify the established state:

``` text
TOKEN_EFFICIENT_MULTI_MODEL_ORCHESTRATION=NOT_PRESENT
CHATGPT_INTEGRATION=HUMAN_MEDIATED_CHATGPT_HANDOFF
CODEX_INTEGRATION=HUMAN_MEDIATED_CODEX_REVIEW
CHATGPT_OUTPUT_CONSUMED=NO
CODEX_OUTPUT_CONSUMED=NO
STRUCTURED_AGENT_HANDOFF=PARTIAL
TASK_SCOPED_GOVERNANCE_RETRIEVAL=OPERATIONAL
MINIMUM_SUFFICIENT_CONTEXT=PARTIAL
TOKEN_USAGE_OBSERVABILITY=PARTIAL
TOKEN_REDUCTION_MEASURED=NO
```

Re-verify only facts that may have changed.

## 4. Separate Logic from Transport

Represent separately:

``` text
MULTI_MODEL_LOGICAL_ORCHESTRATION
MULTI_MODEL_TRANSPORT_AUTOMATION
```

M7 V1 target:

``` text
LOGICAL_ORCHESTRATION=OPERATIONAL
TRANSPORT=HUMAN_MEDIATED_MD
TRANSPORT_AUTOMATION_REQUIRED=NO
```

Manual copy/paste is not a failure.

## 5. Reuse Canonical Contracts

Before adding schemas, inspect/reuse Task Identity, Task Scope, Agent
Task Lifecycle, EvidenceRefs, OpenSpec, checkpoint/resume, Task
Boundary, governance retrieval, issue/result artifacts.

Do not create a second task identity, evidence system, field-resolution
authority, or Source of Truth.

## 6. Implement HANDOFF_V1

Implement `L5DGVA_MODEL_HANDOFF_V1`.

Support fields equivalent to:

``` text
HANDOFF_VERSION
TASK_ID
TASK_TYPE
SOURCE_MODEL
TARGET_MODEL
PROJECT_ID
CURRENT_HEAD
OBJECTIVE
SCOPE
ALLOWED_FILES
FORBIDDEN_FILES
INPUT_EVIDENCE_REFS
REQUIRED_GOVERNANCE_REFS
KNOWN_FACTS
OPEN_QUESTIONS
INDEPENDENCE_REQUIREMENT
EXPECTED_OUTPUT_TYPE
EXPECTED_OUTPUT_SCHEMA
VALIDATION_REQUIREMENTS
HUMAN_DECISION_REQUIRED
RETURN_CONTRACT
```

Reuse existing field names/contracts where available.

## 7. Implement RESULT_V1

Implement `L5DGVA_MODEL_RESULT_V1`.

Support fields equivalent to:

``` text
RESULT_VERSION
TASK_ID
PRODUCER_MODEL
TASK_TYPE
RESULT_STATUS
CLAIMS
FINDINGS
EVIDENCE_REFS
COUNTER_EVIDENCE
UNKNOWN_ITEMS
FILES_REFERENCED
VALIDATION_PERFORMED
RECOMMENDED_ACTIONS
HUMAN_DECISIONS_REQUIRED
SCOPE_EXCEPTIONS
RETURNED_ARTIFACTS
```

The result must be parseable without human reinterpretation.

## 8. Handoff Builder

Build/reuse a handoff builder that derives Minimum Sufficient Context
from Canonical task/evidence/governance state.

Do not dump: - full CLAUDE.md; - full repository; - unrelated history; -
unrelated governance.

Track context-size/proxy metrics.

## 9. Human Transport UX

Support:

``` text
EXPORT HANDOFF
→ HUMAN COPY/PASTE
→ TARGET MODEL
→ HUMAN RETURNS RESULT
→ IMPORT RESULT
```

Human responsibility is transport only. L5DGVA owns task identity,
validation, scope, evidence, and consumption.

The system must be resumable and must not busy-wait for the human.

## 10. Human Pause / Resume States

Implement/reuse:

``` text
HANDOFF_READY
WAITING_FOR_HUMAN_TRANSPORT
RESULT_RETURNED
RESULT_VALIDATING
RESULT_ACCEPTED
RESULT_REJECTED
RESULT_CONSUMED
```

Persist enough task identity/state to resume safely.

Do not claim cross-session durability unless tested.

## 11. Result Parser and Validator

Implement/reuse validation for: - protocol version; - Task ID; -
expected producer/target; - task type; - CURRENT_HEAD where required; -
scope; - allowed/forbidden files; - result schema; - evidence refs; -
governance requirements; - returned artifacts.

Malformed or mismatched results must not be consumed.

## 12. Result Consumption

Implement a real Canonical consumer path.

For every supported result prove:

``` text
OUTPUT_PRODUCED
→ RESULT_RETURNED
→ PARSED
→ VALIDATED
→ CONSUMED
→ CANONICAL_ACTION_OR_DECISION
```

A result file with no consumer is a capability island.

## 13. Codex Round Trip

Qualify one real Claude→Codex→L5DGVA round trip using an appropriate
independent code-review task.

Require:

``` text
HANDOFF_GENERATED=YES
HUMAN_TRANSPORT_COMPLETED=YES
REAL_CODEX_RESULT_RETURNED=YES
RESULT_PARSED=YES
TASK_ID_VALIDATED=YES
SCOPE_VALIDATED=YES
EVIDENCE_VALIDATED=YES
CODEX_OUTPUT_CONSUMED=YES
CANONICAL_CONSUMER_REACHED=YES
```

Do not fabricate Codex output.

If the human has not returned a real Codex result:

``` text
CODEX_ROUND_TRIP=WAITING_FOR_HUMAN_TRANSPORT
```

and STOP that subflow without falsifying completion.

## 14. ChatGPT Round Trip

Qualify one real Claude→ChatGPT→L5DGVA round trip using an architecture,
requirements, decision, or independent-review task.

Apply the same requirements.

Do not fabricate ChatGPT output.

If no real ChatGPT result has been returned:

``` text
CHATGPT_ROUND_TRIP=WAITING_FOR_HUMAN_TRANSPORT
```

## 15. Independent Review

For independent-review tasks, minimize biasing context.

Record:

``` text
INDEPENDENCE_REQUIREMENT
```

Do not include the implementation model's conclusions unless necessary
for the task contract.

## 16. Model Roles

Reconcile actual project roles for Claude/Codex/ChatGPT and classify
each role:

``` text
EXISTING_REAL_USE
AUTOMATABLE_NOW
HUMAN_MEDIATED_ONLY
FUTURE_CAPABILITY
UNSUPPORTED
```

Do not create separate Claude, Codex, and ChatGPT workflows.

## 17. Evidence and Disagreement

A model result is not evidence merely because a model produced it.

Preserve:

``` text
CLAIM
EVIDENCE
COUNTER_EVIDENCE
UNKNOWN
INFERENCE
```

Do not majority-vote disagreements.

Use existing validation/evidence/human-decision mechanisms.

## 18. Human Authority

Preserve:

``` text
DESIGN_AUTHORITY=DE
VERIFICATION_AUTHORITY=DV
VERIFICATION_SIGNOFF_AUTHORITY=DV
```

Multi-model consensus is not signoff.

## 19. Scope and Task Boundary

Delegated context must respect allowed/forbidden scope.

Reuse M6 Task Boundary where applicable.

Track:

``` text
ALLOWED_CONTEXT
FORBIDDEN_CONTEXT
FILES_SHARED
GOVERNANCE_SHARED
EVIDENCE_SHARED
```

Out-of-scope returned content must be rejected or explicitly escalated.

## 20. Failure and Fallback

Test: - missing result; - malformed Markdown; - wrong Task ID; - wrong
producer; - incompatible task type; - invalid schema; - forbidden file
reference; - missing evidence; - unavailable target model; -
disagreement; - human copy/paste error.

No failure silently becomes PASS.

Fallback may regenerate handoff, request correction, return to
Claude-only execution, escalate to human, or mark BLOCKED.

## 21. Minimum Sufficient Context

Measure structured handoff against an equivalent baseline.

Track at least:

``` text
HANDOFF_BYTES
RESULT_BYTES
GOVERNANCE_CONTEXT_BYTES
FILES_REFERENCED
FILES_READ where measurable
MODEL_INVOCATIONS
RETRY_COUNT
WALL_TIME
```

Add provider token counts only if actually observable.

Label byte/file/context measures as proxies.

## 22. Token Reduction Claims

Do not claim token reduction until measured against an equivalent
baseline.

Report separately:

``` text
CONTEXT_REDUCTION_MEASURED
TOKEN_REDUCTION_MEASURED
TOKEN_REDUCTION_EFFECT
```

File-size reduction alone is not token reduction.

## 23. Prime Directive V2

Any current M7-scope defect discovered during implementation follows:

``` text
DISCOVER → RCA → FIX → TEST → CONSUMPTION/E2E → REGRESSION → EVIDENCE VERIFIED
```

True future transport automation remains deferred.

Do not pull API/MCP/plugin transport into M7 V1.

## 24. Cohort Discipline

Implement in dependency order.

Preferred plan, subject to evidence:

``` text
C1 HANDOFF_V1 + RESULT_V1 contracts
C2 Ingestion + Validation + Canonical Consumption
C3 Claude ↔ Codex Human-Mediated Round Trip
C4 Claude ↔ ChatGPT Human-Mediated Round Trip
C5 Minimum Sufficient Context + Observability
C6 Logical Orchestration Qualification
```

Do not start a later cohort until prerequisites are real.

## 25. M6 Non-Regression

After each implementation cohort re-verify the applicable M6
preservation contract.

Before M7 closure require:

``` text
M6_GOLDEN_PATH_PRESERVED=YES
STRUCTURAL_CONNECTED_STAGES=10/10
PRODUCTION_CONNECTED_STAGES=10/10
EVIDENCE_CONNECTED_STAGES=10/10
QUALIFIED_CONNECTED_STAGES=10/10
HITL_QUALIFICATION=PASS
CAPABILITY_ISLANDS=0
UNCONTROLLED_BYPASSES=0
```

## 26. Required Tests

At minimum cover: - valid HANDOFF_V1; - invalid/missing required handoff
fields; - valid RESULT_V1; - malformed result; - Task ID mismatch; -
producer mismatch; - scope violation; - forbidden file reference; -
missing evidence; - valid result consumption; - rejected result not
consumed; - human wait/resume; - Codex round-trip state; - ChatGPT
round-trip state; - independent-review context; - fallback; - M6
non-regression.

## 27. Required Artifacts

Produce/update in approved M7 work area: - `M7_HANDOFF_V1_CONTRACT.md` -
`M7_RESULT_V1_CONTRACT.md` - `M7_MODEL_ROLE_MATRIX.csv` -
`M7_RESULT_INGESTION_AND_CONSUMPTION.md` -
`M7_HUMAN_TRANSPORT_WORKFLOW.md` -
`M7_FAILURE_AND_FALLBACK_CONTRACT.md` -
`M7_MINIMUM_SUFFICIENT_CONTEXT_BASELINE.md` -
`M7_CODEX_ROUND_TRIP_EVIDENCE.md` -
`M7_CHATGPT_ROUND_TRIP_EVIDENCE.md` -
`M7_M6_NON_REGRESSION_EVIDENCE.md` - `M7_FINAL_QUALIFICATION_REPORT.md`

Do not place reports in repository root.

## 28. Master Control Plane

Use structural CSV parsing.

Require:

``` text
MALFORMED_ROWS=0
DUPLICATE_CAPABILITY_IDS=0
P0_COUNT_AMBIGUITY=0
```

Update existing M7 capability rows and wave ownership. Do not create a
second roadmap/control plane.

## 29. M7 Closure Conditions

M7 may become READY_FOR_APPROVAL only if:

``` text
MULTI_MODEL_LOGICAL_ORCHESTRATION=OPERATIONAL
MULTI_MODEL_TRANSPORT=HUMAN_MEDIATED_MD
TRANSPORT_AUTOMATION_REQUIRED=NO

STRUCTURED_HANDOFF=OPERATIONAL
STRUCTURED_RESULT=OPERATIONAL
RESULT_INGESTION=OPERATIONAL
RESULT_VALIDATION=OPERATIONAL
RESULT_CONSUMPTION=OPERATIONAL

CODEX_ROUND_TRIP=QUALIFIED
CHATGPT_ROUND_TRIP=QUALIFIED

CODEX_OUTPUT_CONSUMED=YES
CHATGPT_OUTPUT_CONSUMED=YES

MINIMUM_SUFFICIENT_CONTEXT=OPERATIONAL
M6_GOLDEN_PATH_PRESERVED=YES

UNKNOWN_RUNTIME_CALLERS=0
UNCONTROLLED_BYPASSES=0
UNKNOWN_REGRESSION_FAILURES=0
SOURCE_CAPABILITY_LOSS=0
REFERENCE_USB_ENV_CONSUMED=NO
```

Do not weaken closure merely because manual transport requires human
action.

## 30. Final Report

Report:

``` text
M7_STATUS=READY_FOR_APPROVAL / IN_PROGRESS / BLOCKED

MULTI_MODEL_LOGICAL_ORCHESTRATION=<status>
MULTI_MODEL_TRANSPORT=HUMAN_MEDIATED_MD
TRANSPORT_AUTOMATION_REQUIRED=NO

STRUCTURED_HANDOFF=<status>
STRUCTURED_RESULT=<status>
RESULT_INGESTION=<status>
RESULT_VALIDATION=<status>
RESULT_CONSUMPTION=<status>

CODEX_ROUND_TRIP=<status>
CHATGPT_ROUND_TRIP=<status>
CODEX_OUTPUT_CONSUMED=YES/NO
CHATGPT_OUTPUT_CONSUMED=YES/NO

MINIMUM_SUFFICIENT_CONTEXT=<status>
CONTEXT_REDUCTION_MEASURED=YES/NO
TOKEN_USAGE_OBSERVABILITY=<status>
TOKEN_REDUCTION_MEASURED=YES/NO
TOKEN_REDUCTION_EFFECT=<measured result or NOT_MEASURED>

M6_GOLDEN_PATH_PRESERVED=YES/NO

CURRENT_SCOPE_GAPS_FOUND=<count>
CURRENT_SCOPE_GAPS_FIXED=<count>
CURRENT_SCOPE_GAPS_OPEN=<count>

UNKNOWN_RUNTIME_CALLERS=<count>
UNCONTROLLED_BYPASSES=<count>
UNKNOWN_REGRESSION_FAILURES=<count>
SOURCE_CAPABILITY_LOSS=<count>

AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT=<count>
REFERENCE_USB_ENV_CONSUMED=NO

NEXT_RECOMMENDED_GATE=<exact M7 cohort / human transport action / M8 if M7 qualified>
```

## 31. STOP / Human Transport

When a real Codex or ChatGPT round trip requires the human to carry a
Markdown file:

1.  generate the exact handoff artifact;
2.  report its path;
3.  set state to `WAITING_FOR_HUMAN_TRANSPORT`;
4.  STOP that execution path;
5.  wait for the real returned RESULT_V1.

Do not fabricate a target-model result and do not claim the round trip
completed.

Do not automatically start M8 or later waves.
