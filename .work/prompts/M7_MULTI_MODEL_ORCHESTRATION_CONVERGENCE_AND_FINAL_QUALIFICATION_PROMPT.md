# M7 Multi-Model Orchestration Convergence and Final Qualification Prompt

## 0. Mission

This is a **convergence and final-qualification task**, not a
capability-expansion wave.

Drive the current Canonical M7 program from its real repository state
through:

``` text
REVIEW-006
→ Codex Branch Closure
→ R005-2 Final Disposition
→ Execution Backend Fallback Reconciliation
→ ChatGPT Real Round Trip
→ M7 Final Operational Qualification
```

Govern by:

``` text
P1 CONNECT BEFORE EXPAND
P2 OPERATIONAL BEFORE CLAIMED
P3 CLOSE THE LOOP
P4 NO CAPABILITY ISLANDS
P5 FIND → FIX → VERIFY
P6 RESULT → ACTION → AUTONOMOUS CLOSURE
```

Do not start M8. Do not consume Reference USB. Do not add another large
agent framework, transport, lifecycle, result engine, orchestration
engine, or competing control plane. Close and qualify what already
exists.

## 1. Re-verify Starting State

Do not trust summaries blindly. Record PROCESS_CWD, REPO_ROOT,
CURRENT_BRANCH, CURRENT_HEAD, WORKING_TREE_STATUS and verify frozen
sources.

Expected facts to re-derive include:

``` text
M6_STATUS=CLOSED
M6_GOLDEN_PATH_PRESERVED=YES
M7_STATUS=IN_PROGRESS
HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES
HUMAN_IS_WORKFLOW_SCHEDULER=NO
RESULT_AUTO_INGESTION=LIVE
AUTO_IMPORT=LIVE
AUTO_VALIDATION=LIVE
AUTO_CONSUMPTION=LIVE
AUTO_RESUME=LIVE
NEXT_ACTION_RESOLUTION=LIVE
NATIVE_CONTROLLED_CLAUDE_WORKER=IMPLEMENTED_AND_TESTED_BLOCKED_BY_HOST_POLICY
PRODUCTION_WORKER_AUTHORIZATION=NOT_AVAILABLE_FROM_CURRENT_SESSION
INTERACTIVE_TERMINAL_INJECTION=FORBIDDEN
GAP-V2-015=CLOSED
```

Current Codex convergence is expected around `M7-V1-CODEX-REVIEW-006`;
derive the truth from repository state.

Read relevant P1-P6 governance, Human Non-Scheduler, Automatic Result
Ingestion, Safe Tool Execution, Agent Execution Backend, M6
qualification, M7 status/roadmap, Gap Register, REVIEW-005/006 evidence,
watcher/import state, Next Action state, HumanGate/transport state,
governance registry and Master matrices.

Use structural CSV parsing:

``` text
MALFORMED_ROWS=0
DUPLICATE_CAPABILITY_IDS=0
P0_COUNT_AMBIGUITY=0
```

## 2. Convergence Taxonomy

Every new issue gets exactly one primary class:

``` text
CURRENT_SCOPE_CORRECTNESS_BLOCKER
CURRENT_SCOPE_SECURITY_OR_TRUST_BOUNDARY
CURRENT_SCOPE_CAPABILITY_LOSS
HOST_DEPENDENT_LIMITATION
FUTURE_HARDENING
FUTURE_SCALE_OR_CONCURRENCY
PRE_EXISTING_OWNED_GAP
NOT_APPLICABLE
FALSE_POSITIVE
SUPERSEDED_WITH_EVIDENCE
HUMAN_DECISION_REQUIRED
```

Only the first three and `UNKNOWN_HIGH_SEVERITY_FINDING` automatically
block M7 closure. Do not convert every improvement into a new M7
blocker. Do not hide real blockers to force closure.

## 3. Complete REVIEW-006

If the real REVIEW-006 result is absent, preserve
`WAITING_FOR_HUMAN_TRANSPORT`; do not fabricate it or start ChatGPT.

If present, use the existing automatic ingestion path. Do not rewrite
the result and do not require manual import.

Verify:

``` text
RESULT_DETECTED
→ PUBLICATION/STABILITY CHECK
→ SHA256
→ AUTO_IMPORT
→ VALIDATE
→ CONSUME_OR_REJECT
→ AUTO_RESUME
→ NEXT_ACTION_RESOLUTION
```

Preserve the original result as immutable evidence.

For each finding record FINDING_ID, SEVERITY, CLAIM, REPRODUCTION,
EXPECTED_BEHAVIOR, ACTUAL_BEHAVIOR, ROOT_CAUSE, PRIMARY_CLASS, GAP_ID,
DISPOSITION, BLOCKS_M7, AUTO_REMEDIATION_ELIGIBLE and EVIDENCE_REFS.
Independently reproduce before accepting Codex's claim.

## 4. Codex Branch Closure

Set `CODEX_BRANCH_READY_FOR_CLOSURE=YES` only when:

``` text
CURRENT_SCOPE_CORRECTNESS_BLOCKERS=0
CURRENT_SCOPE_SECURITY_BLOCKERS=0
CURRENT_SCOPE_CAPABILITY_LOSS=0
UNKNOWN_HIGH_SEVERITY_FINDINGS=0
CODEX_RESULT_CONSUMPTION=LIVE
CODEX_REVIEW_INDEPENDENCE=PROVEN
CODEX_FINDINGS_TRACEABLE=YES
M6_GOLDEN_PATH_PRESERVED=YES
```

Host limitations, future hardening/scale items and pre-existing owned
gaps may remain only with explicit owner/disposition and only when they
are not current-scope blockers.

Do not start another Codex review merely because a future-hardening idea
exists. Start another re-review only when a current-scope blocker was
remediated and independent re-review is required.

## 5. R005-2 Final Truthful Disposition

Do not force-close R005-2. Re-verify the actual transport path.

Distinguish:

``` text
SEALED_PUBLICATION
LEGACY_UNSEALED_PUBLICATION
```

A quiet interval alone is not proof that a writer finished.

A qualified publication contract may use an equivalent of:

``` text
partial/temp result
→ complete write/close
→ digest
→ seal/manifest or equivalent completion evidence
→ atomic publication
→ watcher ingestion
```

If actual human transport remains unsealed, report honestly:

``` text
LEGACY_UNSEALED_PUBLICATION=COMPATIBILITY_MODE
QUALIFIED_ATOMIC_PUBLICATION=NO
```

If non-blocking for M7 under the approved contract, give explicit
owner/wave/disposition. Do not claim CLOSED without evidence.

## 6. Execution Backend Freeze

Do not reopen the host-permission workaround investigation.

Preserve:

``` text
NATIVE_CONTROLLED_CLAUDE_WORKER=IMPLEMENTED_AND_TESTED_BLOCKED_BY_HOST_POLICY
PRODUCTION_WORKER_AUTHORIZATION=NOT_AVAILABLE_FROM_CURRENT_SESSION
```

Do not bypass the classifier, self-modify permission scope, use terminal
injection, or claim detached-worker live qualification.

## 7. Execution Backend Fallback

Reconcile a small backend-resolution policy using existing architecture,
not a new orchestration framework.

Represent:

``` text
REQUESTED_BACKEND
SELECTED_BACKEND
BACKEND_STATUS
BACKEND_BLOCK_REASON
FALLBACK_BACKEND
FALLBACK_AUTHORIZED
HUMAN_ACTION_REQUIRED
```

For Claude remediation prefer detached worker; if host-blocked, evaluate
current-session executor.

Current-session fallback may be automatic only when SAME_TASK,
SAME_SCOPE, equivalent Task Boundary, equivalent Safe Tool profile,
equivalent evidence contract, and no Human Authority decision is
required.

Do not represent current-session execution as detached-worker execution.

Report separately:

``` text
WORKFLOW_AUTONOMY
PROCESS_INDEPENDENT_AUTONOMY
```

If no authorized backend is available, use
`WAITING_FOR_EXECUTION_BACKEND`, not generic waiting-for-user and not
automatically Human Authority.

## 8. Human Scheduler KPI

Track:

``` text
HUMAN_TRANSPORT_EVENTS
HUMAN_AUTHORITY_EVENTS
HUMAN_SCHEDULER_INTERVENTIONS
```

Scheduler interventions include manual "continue", telling Claude to fix
an already auto-actionable result, manually scheduling required
regression/re-review, or manual normal-result import.

Transport and true authority are not scheduler interventions.

Final target:

``` text
HUMAN_SCHEDULER_INTERVENTIONS=0
```

## 9. GAP-V2-014

Preserve the known pre-existing question-queue failure with explicit
OWNER, WAVE, REPRODUCTION, DISPOSITION, BLOCKS_M7 and DEFER_REASON where
applicable.

Do not close it because it predates M7. Do not expand this convergence
task into unrelated remediation unless P1-P6 evidence makes it a
current-scope blocker.

## 10. Real ChatGPT Round Trip

Only after Codex branch closure, create a real ChatGPT review:

``` text
TASK_TYPE=architecture-governance-review
TARGET_MODEL=chatgpt
```

ChatGPT is not a duplicate Codex code reviewer.

The handoff asks, with evidence:

1.  Are Human Transport, Human Authority, orchestration authority and
    execution-backend authority correctly separated?
2.  Does `HUMAN_IS_WORKFLOW_SCHEDULER=NO` hold under live evidence?
3.  Are any M7 capabilities still islands?
4.  Are any OPERATIONAL/LIVE/QUALIFIED/CLOSED claims stronger than
    evidence?
5.  Does current-session fallback preserve workflow autonomy while
    detached worker remains host-blocked?
6.  Which remaining issues truly block M7 versus later
    hardening/host-dependent/pre-existing items?
7.  Is the M6 Golden Path preserved?

## 11. Minimum Sufficient ChatGPT Context

Do not transport full history/CLAUDE.md by default. Generate bounded
context:

``` text
OBJECTIVE
CURRENT_M7_ARCHITECTURE
P1-P6
M6_GOLDEN_PATH_INVARIANTS
M7_CAPABILITY_STATUS
CODEX_BRANCH_CONCLUSIONS
KNOWN_LIMITATIONS
SELECTED_EVIDENCE_REFS
EXACT_REVIEW_QUESTIONS
EXPECTED_RESULT_SCHEMA
HUMAN_DECISION_CONTRACT
```

Measure context bytes. Do not claim token reduction without actual token
measurements.

## 12. ChatGPT Transport and Result

Current transport remains human-mediated unless an approved integration
exists:

``` text
CHATGPT_HANDOFF_READY
→ HUMAN_TRANSPORT_REQUIRED
→ REAL_CHATGPT_RESULT
→ EXPECTED_RESULT_PATH
→ WATCHER
→ AUTO_IMPORT
→ VALIDATE
→ CONSUME
→ AUTO_RESUME
```

The ChatGPT result must use the same provider-independent Canonical
result pipeline. Do not manually reinterpret it outside the pipeline.

`FAIL + no human decision` routes to classification/eligible
remediation. `HUMAN_DECISION_REQUIRED` routes to HumanGate. Invalid
result uses rejection/quarantine/next-action semantics.

## 13. Provider Independence

Demonstrate Codex and ChatGPT results both traverse:

``` text
PARSE → VALIDATE → CONSUME → CLASSIFY → NEXT_ACTION
```

without provider-specific orchestration forks beyond transport/backend
adapters.

## 14. Final Qualification Matrix

Build a real matrix with:

``` text
CAPABILITY
STRUCTURAL
PRODUCTION_CONNECTED
EVIDENCE_CONNECTED
LIVE_OPERATIONAL
HITL_APPLICABLE
HITL_QUALIFIED
KNOWN_LIMITATION
EVIDENCE_REFS
```

Cover at least Structured Handoff/Result, Minimum Sufficient Context,
Codex transport/review, ChatGPT transport/review, Result Arrival, Auto
Import, Validation, Consumption, Rejection/Quarantine, Auto Resume,
Result-to-Action, Human Transport, Human Authority, Human Non-Scheduler,
Execution Backend Resolution, Current-Session Remediation, Detached
Claude Worker and M6 preservation.

Never infer one dimension from another.

## 15. M7 Closure Requirements

M7 may become `READY_FOR_APPROVAL` only with real evidence:

``` text
MULTI_MODEL_LOGICAL_ORCHESTRATION=OPERATIONAL
CODEX_ROUND_TRIP=LIVE_QUALIFIED
CHATGPT_ROUND_TRIP=LIVE_QUALIFIED
STRUCTURED_HANDOFF=OPERATIONAL
STRUCTURED_RESULT=OPERATIONAL
RESULT_VALIDATION=OPERATIONAL
RESULT_CONSUMPTION=OPERATIONAL
RESULT_AUTO_INGESTION=LIVE_QUALIFIED
RESULT_TO_ACTION=LIVE_QUALIFIED
WORKFLOW_AUTO_RESUME=LIVE_QUALIFIED
HUMAN_NON_SCHEDULER=PASS
HUMAN_SCHEDULER_INTERVENTIONS=0
CURRENT_SCOPE_CORRECTNESS_BLOCKERS=0
CURRENT_SCOPE_SECURITY_BLOCKERS=0
CURRENT_SCOPE_CAPABILITY_LOSS=0
UNKNOWN_HIGH_SEVERITY_FINDINGS=0
CURRENT_SCOPE_CAPABILITY_ISLANDS=0
M6_GOLDEN_PATH_PRESERVED=YES
UNKNOWN_REGRESSION_FAILURES=0
SOURCE_CAPABILITY_LOSS=0
REFERENCE_USB_ENV_CONSUMED=NO
```

Allowed honest limitations include:

``` text
PROCESS_INDEPENDENT_AUTONOMY=PARTIAL
CLAUDE_DETACHED_WORKER=IMPLEMENTED_AND_TESTED_BLOCKED_BY_HOST_POLICY
TOKEN_REDUCTION=NOT_MEASURED
```

only with explicit evidence/owner/disposition and only when not
current-scope blockers.

## 16. Context/Token Reporting

Report separately:

``` text
HANDOFF_CONTEXT_BYTES
BASELINE_CONTEXT_BYTES if evidenced
CONTEXT_BYTES_REDUCTION
TOKEN_USAGE if available
TOKEN_REDUCTION_MEASURED=YES/NO
```

Never convert byte reduction into token reduction without evidence.

## 17. Regression

Run focused tests first, then required M7/M6 populations. Do not infer
hang from low CPU.

Classify every failure:

``` text
REGRESSION_CAUSED_BY_M7
PRE_EXISTING
ENVIRONMENT_DEPENDENT
UNKNOWN
```

Require `UNKNOWN_REGRESSION_FAILURES=0` for approval readiness. Preserve
Constitution gate and frozen sources.

## 18. Status Reporter

Preserve:

``` text
STATUS_REPORTER_IS_READ_ONLY=YES
```

If status/report/dashboard code is touched, re-run the before/after
anti-drift proof.

## 19. Capability Island Audit

Audit M7 for capabilities that exist without production caller, produce
unconsumed output, are documentation/test-only, or bypass Canonical
result/action flow.

Classify:

``` text
CONNECTED
INTENTIONALLY_NON_PRODUCTION
HOST_BLOCKED_WITH_OWNER
DEFERRED_WITH_OWNER
CURRENT_SCOPE_ISLAND
```

Final:

``` text
CURRENT_SCOPE_CAPABILITY_ISLANDS=0
```

## 20. Required Artifacts

Produce/update in approved existing artifact areas:

``` text
M7_CODEX_BRANCH_CLOSURE_REPORT.md
M7_R005_2_FINAL_DISPOSITION.md
M7_EXECUTION_BACKEND_FALLBACK_RECONCILIATION.md
M7_CHATGPT_ARCHITECTURE_REVIEW_HANDOFF_EVIDENCE.md
M7_CHATGPT_RESULT_CONSUMPTION_EVIDENCE.md
M7_PROVIDER_INDEPENDENCE_QUALIFICATION.md
M7_HUMAN_NON_SCHEDULER_QUALIFICATION.md
M7_FINAL_OPERATIONAL_QUALIFICATION_MATRIX.csv
M7_FINAL_QUALIFICATION_REPORT.md
```

Do not place reports in repo root. Reuse existing artifact families
instead of duplicating them.

## 21. Final Report

Report at minimum:

``` text
M7_STATUS=<IN_PROGRESS|READY_FOR_APPROVAL|BLOCKED>
M7_QUALIFIED_CHECKPOINT_SHA=<sha>

MULTI_MODEL_LOGICAL_ORCHESTRATION=<status>
CODEX_ROUND_TRIP=<status>
CHATGPT_ROUND_TRIP=<status>
PROVIDER_INDEPENDENCE=<status>

STRUCTURED_HANDOFF=<status>
STRUCTURED_RESULT=<status>
MINIMUM_SUFFICIENT_CONTEXT=<status>

RESULT_AUTO_INGESTION=<status>
RESULT_VALIDATION=<status>
RESULT_CONSUMPTION=<status>
RESULT_TO_ACTION=<status>
WORKFLOW_AUTO_RESUME=<status>

HUMAN_NON_SCHEDULER=<status>
HUMAN_TRANSPORT_EVENTS=<count>
HUMAN_AUTHORITY_EVENTS=<count>
HUMAN_SCHEDULER_INTERVENTIONS=<count>

WORKFLOW_AUTONOMY=<status>
PROCESS_INDEPENDENT_AUTONOMY=<status>

CLAUDE_CURRENT_SESSION_EXECUTOR=<status>
CLAUDE_DETACHED_WORKER=IMPLEMENTED_AND_TESTED_BLOCKED_BY_HOST_POLICY

R005_2=<final disposition>
GAP_V2_014=<status/owner/disposition>

CURRENT_SCOPE_CORRECTNESS_BLOCKERS=<count>
CURRENT_SCOPE_SECURITY_BLOCKERS=<count>
CURRENT_SCOPE_CAPABILITY_LOSS=<count>
UNKNOWN_HIGH_SEVERITY_FINDINGS=<count>
CURRENT_SCOPE_CAPABILITY_ISLANDS=<count>

HANDOFF_CONTEXT_BYTES=<value>
CONTEXT_BYTES_REDUCTION=<value/status>
TOKEN_REDUCTION_MEASURED=YES/NO

M6_GOLDEN_PATH_PRESERVED=YES/NO
REGRESSION_CAUSED_BY_M7=<count>
UNKNOWN_REGRESSION_FAILURES=<count>
SOURCE_CAPABILITY_LOSS=<count>
CONSTITUTION_GATE=<status>
REFERENCE_USB_ENV_CONSUMED=NO

NEXT_RECOMMENDED_GATE=<gate>
```

Do not report `READY_FOR_APPROVAL` merely because tests pass.

## 22. Stop Policy

Apply the Human Non-Scheduler Can-I-Stop Gate after each Canonical
action.

Do not stop for generic review, approval, continuation, remediation,
testing, regression or next-review permission.

Legitimate stops only:

``` text
HUMAN_AUTHORITY_REQUIRED
HUMAN_TRANSPORT_REQUIRED
SAFE_EXECUTION_BLOCKED
TERMINATION_POLICY_TRIGGERED
TASK_COMPLETE
```

During the ChatGPT round trip, `HUMAN_TRANSPORT_REQUIRED` is expected
and legitimate.

If M7 final criteria are satisfied, stop at
`M7_STATUS=READY_FOR_APPROVAL`; do not start M8.

## 23. Prime Directive

The most important instruction for this task is:

> **Do not expand M7 to make it look more complete. Connect, qualify,
> classify, close, and report limitations honestly.**
