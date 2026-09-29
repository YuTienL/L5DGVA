# L5DGVA Result-Driven Autonomous Closed-Loop Requirements

## Purpose

This is a platform-level L5DGVA requirement, not an M7-only feature.

> Once a valid result from an external model, internal agent,
> regression, RCA, coverage/formal/lint/build/signoff process, Knowledge
> Brain, research agent, or other evidence producer is validated and
> consumed, L5DGVA shall automatically classify and execute the next
> permitted action. If a current-scope issue is safely auto-remediable,
> L5DGVA shall continue RCA → Fix → Verify → Regression → Re-review
> without requiring the human to act as workflow scheduler. Human
> interaction is required only for real transport or an existing Human
> Authority/HumanGate decision.

Canonical capability: `RESULT_DRIVEN_AUTONOMOUS_CLOSED_LOOP`.

## Prime Directive V2 Extension

Add:

``` text
P6 RESULT → ACTION → AUTONOMOUS CLOSURE
```

Full sequence:

``` text
P1 CONNECT BEFORE EXPAND
P2 OPERATIONAL BEFORE CLAIMED
P3 CLOSE THE LOOP
P4 NO CAPABILITY ISLANDS
P5 FIND → FIX → VERIFY
P6 RESULT → ACTION → AUTONOMOUS CLOSURE
```

P6 removes unnecessary human scheduling; it does not weaken Human
Authority.

## Human Role

``` text
HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES
HUMAN_IS_WORKFLOW_SCHEDULER=NO
```

Human interaction is appropriate for external-model manual transport,
HUMAN_DECISION_REQUIRED, DE/DV/signoff/architecture authority,
security/scope/access approval, or another existing explicit HumanGate.

Human interaction is not required merely because a review found a normal
current-scope defect, a regression produced an actionable failure, RCA
found a bounded fix, or a consumed result is already classified
FIX_NOW_CURRENT_SCOPE / FIX_NOW_CORRECTNESS_BLOCKER.

## Producer-Independent Model

P6 applies to Claude, Codex, ChatGPT, internal agents, regression, RCA,
coverage, formal, lint, build, signoff, Knowledge Brain,
research/change-impact agents, external tools, and future providers.

``` text
Evidence Producer → Canonical Result → Validation → Consumption
→ Result-to-Action Router → Execution Policy
```

## Required Capability Family

``` text
RESULT_DRIVEN_AUTONOMOUS_CLOSED_LOOP
RESULT_TO_ACTION_ROUTING
AUTO_REMEDIATION_ELIGIBILITY
AUTONOMOUS_REMEDIATION_EXECUTION
AUTONOMOUS_REMEDIATION_VERIFICATION
AUTONOMOUS_REVIEW_LOOP
HUMAN_ESCALATION_POLICY
LOOP_TERMINATION_POLICY
LOOP_BUDGET_POLICY
LOOP_EVIDENCE_TRACEABILITY
LOOP_RESUME_RECOVERY
```

Reuse existing Canonical mechanisms where equivalent.

## Canonical Flow

``` text
RESULT PRODUCED
→ RESULT VALIDATED
→ RESULT CONSUMED
→ FINDINGS/STATUS CLASSIFIED
→ ACTION ROUTER
   ├─ AUTO_ACTIONABLE
   │   → Autonomous Remediation → Validation → Regression
   │   → Evidence Update → Re-review/Re-qualification → Continue
   ├─ HUMAN_GATE_REQUIRED
   │   → Persist → Ask Human → Resume
   ├─ REGISTER_AND_DEFER
   │   → Register Owner/Wave → Continue
   └─ CLOSE_WITH_EVIDENCE
       → Continue
```

## Disposition and Execution Class

Prime Directive dispositions remain:

``` text
FIX_NOW_CURRENT_SCOPE
FIX_NOW_CORRECTNESS_BLOCKER
FIX_NOW_CAPABILITY_LOSS
FIX_NOW_SAFETY_SECURITY
REGISTER_AND_DEFER_WITH_OWNER
SUPERSEDED_WITH_EVIDENCE
NOT_APPLICABLE_WITH_EVIDENCE
HUMAN_DECISION_REQUIRED
```

P6 execution classes:

``` text
AUTO_REMEDIATION_ELIGIBLE
HUMAN_GATE_REQUIRED
DEFERRED_WITH_OWNER
CLOSE_WITH_EVIDENCE
BLOCKED
```

Disposition and execution class are distinct.

## Auto-Remediation Eligibility

Default candidates: FIX_NOW_CURRENT_SCOPE, FIX_NOW_CORRECTNESS_BLOCKER,
FIX_NOW_CAPABILITY_LOSS, provided the fix stays in approved scope, does
not change protected architecture authority, does not require
DE/DV/signoff authority, does not expand security/access scope, does not
modify frozen sources, does not require a new human decision, and has an
evidence-backed validation path.

FIX_NOW_SAFETY_SECURITY requires an explicit policy check and may
auto-remediate only when already authorized.

## Mandatory Human Escalation

Require HumanGate for:

``` text
HUMAN_DECISION_REQUIRED
DESIGN_AUTHORITY_REQUIRED
VERIFICATION_AUTHORITY_REQUIRED
VERIFICATION_SIGNOFF_REQUIRED
ARCHITECTURE_AUTHORITY_REQUIRED
SECURITY_SCOPE_EXPANSION
ACCESS_AUTHORIZATION_REQUIRED
AMBIGUOUS_HIGH_IMPACT_DECISION
POLICY_REQUIRES_HUMAN_APPROVAL
```

Multi-model consensus never bypasses these gates.

## Automatic Remediation Lifecycle

``` text
REPRODUCE → ROOT CAUSE → PLAN MINIMAL FIX → IMPLEMENT
→ FOCUSED TEST → CONTRACT VALIDATION → PRODUCER/CONSUMER VALIDATION
→ E2E VALIDATION where applicable → REGRESSION → EVIDENCE UPDATE
→ RE-REVIEW / RE-QUALIFICATION
```

Prime Directive V2 FIND → FIX → VERIFY remains mandatory.

## Automatic Re-review

After remediation determine whether independent re-review is required.

Examples:

``` text
Codex review FAIL → Claude remediation → Codex re-review
ChatGPT review FAIL → Claude remediation → ChatGPT re-review
Regression failure → Claude remediation → regression rerun
```

If re-review requires human-mediated external-model transport:
`RE_REVIEW_HANDOFF_READY → WAITING_FOR_HUMAN_TRANSPORT` is a legitimate
stop.

The human transports the artifact; after the returned result is
consumed, L5DGVA resumes automatically unless a HumanGate is reached.

## Result-Driven State Machine

``` text
RESULT_AVAILABLE
RESULT_VALIDATING
RESULT_REJECTED
RESULT_ACCEPTED
RESULT_CONSUMED
ACTION_CLASSIFYING
AUTO_REMEDIATION_READY
AUTO_REMEDIATION_RUNNING
AUTO_REMEDIATION_VERIFYING
RE_REVIEW_REQUIRED
RE_REVIEW_HANDOFF_READY
WAITING_FOR_HUMAN_TRANSPORT
HUMAN_GATE_REQUIRED
WAITING_FOR_HUMAN_DECISION
RESUMING
CLOSED
BLOCKED
```

Persist state where existing lifecycle persistence supports it.

## Loop Termination

Autonomy must not create infinite loops. Required policy inputs:

``` text
MAX_REMEDIATION_ITERATIONS
MAX_RETRY_PER_FINDING
NO_PROGRESS_DETECTION
REPEATED_FAILURE_SIGNATURE
REPEATED_FINDING_SIGNATURE
REGRESSION_EXPANSION_DETECTION
SCOPE_EXPANSION_DETECTION
EVIDENCE_STAGNATION
HUMAN_ESCALATION_THRESHOLD
```

Thresholds should be configurable/evidence-derived, not arbitrary
constants added only to satisfy this requirement.

## Loop Budget

Where measurable track ITERATION_COUNT, MODEL_INVOCATIONS,
TEST_RUN_COUNT, REGRESSION_RUN_COUNT, WALL_TIME, CONTEXT_BYTES,
TOKEN_USAGE_IF_AVAILABLE, RETRY_COUNT. Budget exhaustion never becomes
PASS; use BLOCKED_REQUIRES_HUMAN with evidence when appropriate.

## No-Progress Detection

Detect repeated findings/failures, no reduction in open findings,
equivalent regressions, or materially identical re-review blockers. When
policy determines no progress, escalate with preserved evidence/history.

## Evidence Traceability

Every autonomous iteration preserves:

``` text
SOURCE_RESULT_ID
FINDING_ID
GAP_ID
ACTION_CLASSIFICATION
ELIGIBILITY_DECISION
ROOT_CAUSE
FILES_CHANGED
TESTS_RUN
REGRESSION_SIGNATURE
EVIDENCE_REFS
RE_REVIEW_TASK_ID
ITERATION_NUMBER
FINAL_DISPOSITION
```

No autonomous fix becomes an untraceable mutation.

## Resume / Recovery

If stopped for human transport/decision, process restart, external-model
unavailability, or recoverable tool failure:

``` text
STOP → Persist → External/Human Action → Resume → Continue Canonical State Machine
```

The human should not reconstruct workflow state manually.

## External-Model Transport

M7 V1 uses HUMAN_MEDIATED_MD for Claude↔Codex and Claude↔ChatGPT. Manual
transport is an allowed pause. After RESULT_V1
import/validation/consumption, L5DGVA resumes automatically unless a
real HumanGate is reached.

## M7 Application

M7 must implement:

``` text
HANDOFF → External Model → RESULT → INGEST → VALIDATE → CONSUME
→ RESULT_TO_ACTION_ROUTING → AUTO_REMEDIATION or HUMAN_GATE
→ VERIFY → RE_REVIEW
```

M7 is not complete if it only implements message exchange.

## Current Codex Case

The real consumed result:

``` text
TASK_ID=M7-V1-CODEX-REVIEW-001
CODEX_ROUND_TRIP=QUALIFIED
CODEX_OUTPUT_CONSUMED=YES
RESULT_STATUS=FAIL
HUMAN_DECISION_REQUIRED=NO
```

registered GAP-V2-009/010/011/012 as FIX_NOW_CORRECTNESS_BLOCKER. Under
P6 they are auto-remediation candidates unless independent reproduction
changes disposition or reveals a real HumanGate.

## Native Claude Fast Maintenance

P6 also applies where Native Claude Fast Maintenance remains within
fast-path eligibility. Bounded failure → RCA → auto-actionable fix →
rerun needs no human "continue?". Design/spec conflict, cross-scope,
signoff-sensitive or otherwise ineligible work escalates under existing
policy.

## Knowledge Brain

Successful closure may feed:

``` text
Finding → RCA → Fix → Validation → Re-review PASS
→ Experience → KC Candidate → Promotion Gate → Knowledge Brain
```

Learning claims require actual retrieval/consumption evidence.

## Safety / Correctness Invariants

``` text
AUTO_FIX_WITHOUT_VALIDATION=NO
AUTO_FIX_OUTSIDE_SCOPE=NO
AUTO_FIX_FROZEN_SOURCE=NO
AUTO_BYPASS_HUMAN_AUTHORITY=NO
AUTO_PASS_ON_BUDGET_EXHAUSTION=NO
AUTO_PASS_ON_MODEL_FAILURE=NO
AUTO_PASS_ON_VALIDATION_FAILURE=NO
```

## Platform Completion

Operational proof requires:

``` text
VALID_RESULT → CONSUMED → ACTION_CLASSIFIED
→ AUTO_REMEDIATION_ELIGIBILITY_DECIDED → ACTION_EXECUTED
→ RESULT_VERIFIED → RE_REVIEW_OR_CLOSURE
```

without a human scheduler prompt between machine-authorized stages. Also
prove a real HumanGate stops correctly.

## Core Requirements

``` text
RESULT_DRIVEN_AUTONOMOUS_CLOSED_LOOP=REQUIRED
RESULT_TO_ACTION_ROUTING=REQUIRED
AUTO_REMEDIATION_ELIGIBILITY=REQUIRED
AUTONOMOUS_REMEDIATION_EXECUTION=REQUIRED
AUTONOMOUS_REMEDIATION_VERIFICATION=REQUIRED
AUTONOMOUS_REVIEW_LOOP=REQUIRED
HUMAN_ESCALATION_POLICY=REQUIRED
LOOP_TERMINATION_POLICY=REQUIRED
LOOP_BUDGET_POLICY=REQUIRED
LOOP_EVIDENCE_TRACEABILITY=REQUIRED
LOOP_RESUME_RECOVERY=REQUIRED
HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES
HUMAN_IS_WORKFLOW_SCHEDULER=NO
```

## Final Objective

> L5DGVA shall autonomously drive validated machine-actionable results
> to verified closure, while stopping only for real transport,
> authority, scope, safety, or policy gates---keeping humans responsible
> for judgment and authority rather than repetitive workflow scheduling.
