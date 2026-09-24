# L5DGVA M7 Structured Multi-Model Markdown Handoff Architecture

## Purpose

M7 V1 formalizes cooperation among Claude CLI, Codex, and ChatGPT using
the real current transport: **structured Markdown moved by human
copy/paste**. Direct model-to-model APIs, API tokens, MCP transport,
plugins, and automated routing are not required for V1.

``` text
L5DGVA → HANDOFF_V1.md → Human Copy/Paste → Codex / ChatGPT
→ RESULT_V1.md → Human Copy/Paste → L5DGVA Ingestion
→ Validation → Canonical Consumer → Golden Workflow
```

Prime Directive V2 and the M6 qualified Golden Workflow remain
authoritative.

## Governing Invariants

``` text
ONE_GOLDEN_WORKFLOW=YES
PARALLEL_MODEL_WORKFLOWS=NO
MODEL_IS_SOURCE_OF_TRUTH=NO
HUMAN_MEDIATED_MD_TRANSPORT=SUPPORTED
DIRECT_MODEL_API_REQUIRED=NO
STRUCTURED_HANDOFF=REQUIRED
STRUCTURED_RESULT=REQUIRED
RESULT_VALIDATION=REQUIRED
RESULT_CONSUMPTION=REQUIRED
MINIMUM_SUFFICIENT_CONTEXT=REQUIRED
HUMAN_AUTHORITY_PRESERVED=YES
M6_GOLDEN_PATH_PRESERVED=YES
```

Apply P1 CONNECT BEFORE EXPAND, P2 OPERATIONAL BEFORE CLAIMED, P3 CLOSE
THE LOOP, P4 NO CAPABILITY ISLANDS, P5 FIND → FIX → VERIFY.

## Transport vs Logical Orchestration

`MULTI_MODEL_LOGICAL_ORCHESTRATION != MULTI_MODEL_TRANSPORT_AUTOMATION`.

M7 V1 target:

``` text
MULTI_MODEL_LOGICAL_ORCHESTRATION=OPERATIONAL
MULTI_MODEL_TRANSPORT=HUMAN_MEDIATED_MD
TRANSPORT_AUTOMATION_REQUIRED=NO
```

Future API/MCP/plugin/CLI transports must reuse the same
handoff/result/validation/consumption semantics.

## Logical Architecture

``` text
L5DGVA Golden Workflow
        ↓
Canonical Task
        ↓
Handoff Builder
        ↓
Minimum Sufficient Context
        ↓
HANDOFF_V1.md
        ↓
Human Transport
   ┌────┴────┐
   ↓         ↓
 Codex    ChatGPT
   ↓         ↓
RESULT_V1  RESULT_V1
   └────┬────┘
        ↓
Human Transport
        ↓
Result Ingestion
        ↓
Task / Scope / Schema / Evidence / Governance Validation
        ↓
Canonical Consumer
        ↓
Golden Workflow
```

## Model Roles

Roles are evidence-derived, not based on generic reputation.

**Claude CLI candidates:** repository-local implementation, multi-file
changes, project execution, interactive clarification, regression/fix
loops, Canonical updates.

**Codex candidates:** independent code review, defect discovery,
diff/implementation analysis, implementation comparison, issue/result
generation.

**ChatGPT candidates:** architecture analysis, requirements
reconciliation, research synthesis, decision analysis, independent
reasoning/review, structured human decision support.

Classify each role as: `EXISTING_REAL_USE`, `AUTOMATABLE_NOW`,
`HUMAN_MEDIATED_ONLY`, `FUTURE_CAPABILITY`, or `UNSUPPORTED`.

## HANDOFF_V1

Canonical protocol: `L5DGVA_MODEL_HANDOFF_V1`.

Required logical fields:

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

Reuse existing Task Identity, Task Scope, EvidenceRefs, OpenSpec,
checkpoint and governance contracts where equivalent.

## Minimum Sufficient Context

Preferred context:

``` text
Task Identity + Objective + Exact Scope + Required Governance
+ Relevant Evidence + Relevant Source References
+ Questions + Expected Result Contract
```

Avoid full CLAUDE.md, repository dumps, unrelated historical reports,
and unbounded chat history. Prefer task-scoped governance retrieval.

## RESULT_V1

Canonical protocol: `L5DGVA_MODEL_RESULT_V1`.

Required logical fields:

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

Free-form prose may exist inside defined sections; the outer contract
remains parseable.

## Round-Trip Integrity

Require:

``` text
HANDOFF_TASK_ID == RESULT_TASK_ID
EXPECTED_TARGET_MODEL == RESULT_PRODUCER_MODEL
RESULT_TASK_TYPE compatible with HANDOFF_TASK_TYPE
```

Validate current-head and scope where applicable. Mismatches must not
silently enter Canonical state.

## Human Transport Contract

Human responsibility is transport only:

``` text
Export/Copy HANDOFF → Paste to target model
→ Receive RESULT → Copy/Save RESULT → Import to L5DGVA
```

The human should not need to rewrite scope, reinterpret evidence, merge
model conclusions, or decide whether malformed results are valid.

## Independent Review

Independent-review handoffs provide only necessary
task/scope/governance/evidence context and avoid unnecessary
implementation conclusions that bias the reviewer. Results independently
report claims, defects, evidence, counter-evidence, and unknowns.

## Result Ingestion

``` text
RESULT_RETURNED
→ PARSED
→ TASK_ID_VALIDATED
→ PRODUCER_VALIDATED
→ SCOPE_VALIDATED
→ SCHEMA_VALIDATED
→ EVIDENCE_VALIDATED
→ GOVERNANCE_VALIDATED
→ RESULT_CLASSIFIED
→ CANONICAL_CONSUMER
```

Only then is `MODEL_OUTPUT_CONSUMED=YES`.

## Canonical Consumers

Consumers may include issue/gap register, implementation task, review
gate, RCA, decision packet, evidence store, KC candidate, human decision
gate, or capability-status update. A returned result with no consumer is
a capability island.

## Result Status

Recommended statuses:

``` text
PASS
FAIL
PARTIAL
BLOCKED
HUMAN_DECISION_REQUIRED
INSUFFICIENT_EVIDENCE
INVALID_SCOPE
INVALID_RESULT
```

Model confidence alone is not acceptance authority.

## Evidence and Disagreement

Material findings distinguish:

``` text
CLAIM
EVIDENCE
COUNTER_EVIDENCE
UNKNOWN
INFERENCE
```

Model text is not evidence merely because a model produced it. Do not
resolve disagreement by majority vote; preserve competing
claims/evidence and human escalation when required.

## Human Authority

Multi-model agreement never replaces:

``` text
DESIGN_AUTHORITY=DE
VERIFICATION_AUTHORITY=DV
VERIFICATION_SIGNOFF_AUTHORITY=DV
```

## Scope and Security

Track:

``` text
ALLOWED_FILES
FORBIDDEN_FILES
FILES_SHARED
GOVERNANCE_SHARED
EVIDENCE_SHARED
```

M7 must not bypass M6 Task Boundary. Out-of-scope result content is
rejected or explicitly escalated.

## Failure and Fallback

Handle missing/malformed result, wrong Task ID/model, invalid
schema/scope, missing evidence, disagreement, unavailable model, and
human transport error. Safe fallback may regenerate handoff, request
corrected result, return to Claude-only path, escalate to human, or mark
BLOCKED. No failure silently becomes PASS.

## Token / Context Efficiency

Measure where observable:

``` text
HANDOFF_BYTES
RESULT_BYTES
PROMPT_BYTES
GOVERNANCE_CONTEXT_BYTES
FILES_REFERENCED
FILES_READ
MODEL_INVOCATIONS
RETRY_COUNT
WALL_TIME
```

Use provider token counts only when actually exposed. Otherwise label
byte/file/context metrics as proxies. Never infer token-reduction
percentage from file-size reduction alone.

## Baseline

Establish representative Claude-only/human-mediated baseline tasks and
compare equivalent structured-handoff tasks. M7 measures
orchestration/context efficiency; M14 remains the post-M13 Junior DV
productivity benchmark.

## M7 Cohorts

Preferred evidence-adjustable sequence:

``` text
C1 Structured Handoff + Result Contracts
C2 Result Ingestion + Validation + Canonical Consumption
C3 Claude ↔ Codex Human-Mediated Round Trip
C4 Claude ↔ ChatGPT Human-Mediated Round Trip
C5 Minimum Sufficient Context + Observability
C6 Multi-Model Logical Orchestration Qualification
```

Automated transport is not required for M7 V1.

## M6 Non-Regression

Preserve:

``` text
STRUCTURAL_CONNECTED_STAGES=10/10
PRODUCTION_CONNECTED_STAGES=10/10
EVIDENCE_CONNECTED_STAGES=10/10
QUALIFIED_CONNECTED_STAGES=10/10
HITL_QUALIFICATION=PASS
CAPABILITY_ISLANDS=0
UNCONTROLLED_BYPASSES=0
```

Any M7-caused regression follows FIND → FIX → VERIFY.

## M7 Completion

Markdown existence is insufficient. Required round trip:

``` text
HANDOFF_GENERATED
→ HUMAN_TRANSPORT_COMPLETED
→ RESULT_RETURNED
→ RESULT_PARSED
→ TASK_ID_VALIDATED
→ SCOPE_VALIDATED
→ EVIDENCE_VALIDATED
→ RESULT_CONSUMED
→ CANONICAL_ACTION_OR_DECISION_PRODUCED
```

## Final Objective

> Allow Claude CLI, Codex, and ChatGPT to cooperate through a
> transport-independent, structured, evidence-grounded protocol in which
> human copy/paste is a valid V1 transport, while L5DGVA---not the human
> courier and not any individual model---owns task identity, scope,
> validation, evidence, and result consumption.
