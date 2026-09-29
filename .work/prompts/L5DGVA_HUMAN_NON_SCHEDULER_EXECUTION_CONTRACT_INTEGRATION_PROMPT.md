# L5DGVA Human Non-Scheduler Execution Contract Integration Prompt

## Mission

Adopt and implement:

`docs/architecture/canonical_detailed_governance/L5DGVA_HUMAN_NON_SCHEDULER_EXECUTION_CONTRACT.md`

as an executable platform-level L5DGVA contract.

The invariants:

``` text
HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES
HUMAN_IS_WORKFLOW_SCHEDULER=NO
```

must become runtime-enforced behavior, not documentation-only guidance.

This extends P6 `RESULT → ACTION → AUTONOMOUS CLOSURE`.

Do not start M8 or later waves. Do not consume Reference USB. Do not
modify frozen Parent/v50/b7a/b7b/b8.

## 1. Preflight

Record PROCESS_CWD, REPO_ROOT, CURRENT_BRANCH, CURRENT_HEAD,
WORKING_TREE_STATUS.

Read completely before editing: - Human Non-Scheduler Execution
Contract; - Result-Driven Autonomous Closed-Loop Requirements; - Prime
Directive V2/P6; - current M7 multi-model architecture/implementation
artifacts; - lifecycle/state persistence; - result
ingestion/consumption/action routing; - question_queue/HumanGate; - Task
Boundary; - status/dashboard/CLI state reporting; -
anti-drift/governance tests; - current Codex result and
GAP-V2-009/010/011/012; - M6 non-regression contract.

Verify frozen sources unchanged.

## 2. Reconcile; Do Not Duplicate

Reuse existing lifecycle/orchestration/persistence/action-routing
mechanisms.

Do not create a second lifecycle engine, HumanGate, result router,
task-state authority, or control plane.

Extend partial existing mechanisms.

## 3. Default Auto-Continue

Implement/reconcile:

``` text
DEFAULT_EXECUTION_POLICY=AUTO_CONTINUE
STOP_REQUIRES_EXPLICIT_REASON=YES
```

After every state-changing action resolve the next Canonical action.

Subtask/cohort/import/fix/test/regression/report completion is not a
stop condition by itself.

## 4. Canonical Stop Reasons

Represent only:

``` text
HUMAN_AUTHORITY_REQUIRED
HUMAN_TRANSPORT_REQUIRED
SAFE_EXECUTION_BLOCKED
TERMINATION_POLICY_TRIGGERED
TASK_COMPLETE
```

Every stop persists:

``` text
STATE
STOP_REASON
STOP_EVIDENCE
NEXT_REQUIRED_ACTION
HUMAN_ACTION_REQUIRED
RESUME_ACTION
```

## 5. Reject Generic Stops

Runtime policy must not stop merely for:

``` text
WAITING_FOR_USER_TO_CONTINUE
WAITING_FOR_GENERIC_REVIEW
WAITING_FOR_GENERIC_APPROVAL
ASK_USER_IF_SHOULD_FIX
ASK_USER_IF_SHOULD_TEST
ASK_USER_IF_SHOULD_RERUN
ASK_USER_IF_SHOULD_PROCEED
COHORT_COMPLETED
SUBTASK_COMPLETED
RESULT_IMPORTED
RESULT_CONSUMED
FIX_COMPLETED
TEST_COMPLETED
REGRESSION_COMPLETED
REPORT_COMPLETED
```

unless an independent approved gate maps it to a valid stop reason.

## 6. Canonical Task Completion

Implement/reconcile:

``` text
CURRENT_SUBCOMMAND_COMPLETE != CANONICAL_TASK_COMPLETE
```

TASK_COMPLETE is forbidden while pending:

``` text
AUTO_ACTIONABLE_PENDING
REQUIRED_REMEDIATION_PENDING
REQUIRED_VERIFICATION_PENDING
REQUIRED_REGRESSION_PENDING
REQUIRED_REREVIEW_PREPARATION_PENDING
```

Derive pending work from real state; do not fake counters.

## 7. Can-I-Stop Gate

Before every workflow stop execute a Canonical decision equivalent to:

``` text
IF HUMAN_AUTHORITY_REQUIRED:
    STOP(HUMAN_AUTHORITY_REQUIRED)
ELSE IF HUMAN_TRANSPORT_REQUIRED:
    STOP(HUMAN_TRANSPORT_REQUIRED)
ELSE IF SAFE_EXECUTION_BLOCKED:
    STOP(SAFE_EXECUTION_BLOCKED)
ELSE IF TERMINATION_POLICY_TRIGGERED:
    STOP(TERMINATION_POLICY_TRIGGERED)
ELSE IF AUTO_ACTIONABLE_PENDING:
    CONTINUE
ELSE IF REQUIRED_REMEDIATION_PENDING:
    CONTINUE
ELSE IF REQUIRED_VERIFICATION_PENDING:
    CONTINUE
ELSE IF REQUIRED_REGRESSION_PENDING:
    CONTINUE
ELSE IF REQUIRED_REREVIEW_PREPARATION_PENDING:
    CONTINUE
ELSE IF CANONICAL_TASK_COMPLETE:
    STOP(TASK_COMPLETE)
ELSE:
    CONTINUE
```

Use real state, not prose heuristics.

## 8. Next Action Resolver

After every state-changing action persist:

``` text
NEXT_ACTION
NEXT_ACTION_REASON
NEXT_ACTION_OWNER
AUTO_ACTIONABLE
HUMAN_ACTION_REQUIRED
STOP_REASON if any
```

Provider-independent routing is required.

Examples:

``` text
RESULT_CONSUMED → AUTO_REMEDIATE_CONFIRMED_FINDINGS
FIX_COMPLETE → RUN_FOCUSED_VALIDATION
VALIDATION_PASS → RUN_REQUIRED_REGRESSION
REGRESSION_PASS → PREPARE_REQUIRED_RE_REVIEW
RE_REVIEW_HANDOFF_READY → HUMAN_TRANSPORT_REQUIRED
```

## 9. Result Import Auto-Resume

Implement:

``` text
RESULT_IMPORTED
→ VALIDATED
→ CONSUMED
→ AUTO_RESUME_ACTION_ROUTING

AUTO_RESUME_AFTER_RESULT_IMPORT=YES
```

Do not require a user message such as continue/fix/proceed/rerun.

## 10. Human Transport

At transport stop report exactly:

``` text
STATE=WAITING_FOR_HUMAN_TRANSPORT
STOP_REASON=HUMAN_TRANSPORT_REQUIRED
TASK_ID
TARGET_MODEL
HANDOFF_FILE
EXPECTED_RESULT_FILE
IMPORT_COMMAND
NEXT_ACTION_AFTER_IMPORT=AUTO_RESUME
```

Do not ask the human to decide the post-import action.

## 11. Human Authority

At true authority stop report:

``` text
STATE=WAITING_FOR_HUMAN_AUTHORITY
STOP_REASON=HUMAN_AUTHORITY_REQUIRED
AUTHORITY_TYPE
QUESTION
OPTIONS if applicable
EVIDENCE
IMPACT
RESUME_ACTION
```

Do not use Human Authority as a generic uncertainty fallback.

## 12. Safe Blocker and Termination

SAFE_EXECUTION_BLOCKED requires concrete evidence.

Implement/reconcile bounded-loop policy for:

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

Use configurable/evidence-backed thresholds. Budget/termination never
becomes PASS.

## 13. Auto-Remediation Eligibility

Automatically continue eligible FIX_NOW_CURRENT_SCOPE,
FIX_NOW_CORRECTNESS_BLOCKER, FIX_NOW_CAPABILITY_LOSS when already
authorized and safely bounded.

Escalate protected authority/security/access/scope/frozen-source cases.

## 14. Automatic Remediation Chain

For eligible findings automatically execute:

``` text
REPRODUCE
→ ROOT CAUSE
→ MINIMAL FIX
→ FOCUSED TEST
→ CONTRACT VALIDATION
→ PRODUCER/CONSUMER VALIDATION
→ E2E VALIDATION where applicable
→ REGRESSION
→ EVIDENCE UPDATE
→ RE-REVIEW PREPARATION
```

No routine permission stop.

## 15. Re-Review Preparation

After verified remediation:

``` text
GENERATE_RE_REVIEW_HANDOFF
→ RE_REVIEW_HANDOFF_READY
→ HUMAN_TRANSPORT_REQUIRED
```

After returned result import/consumption, automatically resume.

## 16. Persist / Resume

Use existing persistent lifecycle infrastructure to support:

``` text
STOP → PERSIST → HUMAN/EXTERNAL ACTION
→ IMPORT/ANSWER → RESUME → NEXT ACTION RESOLVER → CONTINUE
```

## 17. Status / Dashboard / CLI

Expose:

``` text
AUTO_RUNNING
WAITING_FOR_HUMAN_TRANSPORT
WAITING_FOR_HUMAN_AUTHORITY
BLOCKED
COMPLETE
```

When auto-running: `HUMAN_ACTION_REQUIRED=NO`.

Do not expose generic WAITING_FOR_USER.

## 18. Anti-Drift Tests

Add runtime/state tests equivalent to:

``` text
test_auto_actionable_result_does_not_stop_for_user
test_fix_now_correctness_blocker_auto_continues
test_required_validation_auto_continues
test_required_regression_auto_continues
test_rereview_preparation_auto_continues
test_result_import_auto_resumes
test_human_transport_requires_stop
test_human_authority_requires_stop
test_waiting_for_review_is_not_valid_stop_reason
test_waiting_for_continue_is_not_valid_stop_reason
test_task_complete_rejected_with_pending_auto_actions
test_subtask_complete_does_not_equal_canonical_task_complete
test_transport_resume_restores_next_action
```

Verify behavior, not strings alone.

## 19. Apply Immediately to Current Codex Case

For:

``` text
TASK_ID=M7-V1-CODEX-REVIEW-001
CODEX_ROUND_TRIP=QUALIFIED
CODEX_OUTPUT_CONSUMED=YES
RESULT_STATUS=FAIL
HUMAN_DECISION_REQUIRED=NO
GAP-V2-009/010/011/012=FIX_NOW_CORRECTNESS_BLOCKER
```

the correct state is:

``` text
AUTO_REMEDIATION_RUNNING
```

not WAITING_FOR_USER_TO_CONTINUE.

Automatically continue through: - independent reproduction of Codex
findings; - RCA; - eligible remediation; - adversarial/focused tests; -
ingestion/consumption/replay validation; - broader M7/M6 regression; -
evidence update; - Codex re-review handoff generation.

Do not assume Codex findings are correct; reproduce them.

Preserve the original Codex RESULT_V1 verbatim.

## 20. Current Gap Remediation Requirements

Reconcile/fix as supported by evidence: - GAP-V2-009 validation
correctness, including honest governance N/A vs validated semantics; -
GAP-V2-010 identity/scope mismatch before normalization; - GAP-V2-011
malformed input, atomicity, replay and duplicate-consumption safety; -
GAP-V2-012 Markdown round-trip fidelity.

Apply Prime Directive V2/P6 FIND → FIX → VERIFY.

## 21. Original Result Replay

After remediation replay the exact original Codex result in a controlled
context.

Require: - same Task ID attribution; - original FAIL verdict
preserved; - findings preserved; - corrected validation behavior; -
deterministic replay; - zero duplicate semantic consumption.

## 22. M6 Non-Regression

Require:

``` text
M6_GOLDEN_PATH_PRESERVED=YES
STRUCTURAL_CONNECTED_STAGES=10/10
PRODUCTION_CONNECTED_STAGES=10/10
EVIDENCE_CONNECTED_STAGES=10/10
QUALIFIED_CONNECTED_STAGES=10/10
HITL_QUALIFICATION=PASS
```

## 23. Governance Placement

Keep detailed contract under:
`docs/architecture/canonical_detailed_governance/`

Keep CLAUDE.md compact and register task-scoped retrieval.

Reconcile Prime Directive P6, governance registry, Master
capability/wave/E2E/program artifacts and M7 roadmap as required.

Use structural CSV parsing; require malformed=0, duplicate IDs=0, P0
ambiguity=0.

## 24. Required Artifacts

Produce/update in approved work/governance locations: -
`L5DGVA_HUMAN_NON_SCHEDULER_EXECUTION_CONTRACT_ADOPTION_REPORT.md` -
`M7_STOP_ELIGIBILITY_AND_NEXT_ACTION_POLICY.md` -
`M7_AUTO_RESUME_EVIDENCE.md` - `M7_HUMAN_TRANSPORT_GATE_EVIDENCE.md` -
`M7_HUMAN_AUTHORITY_GATE_EVIDENCE.md` -
`M7_NON_SCHEDULER_ANTI_DRIFT_TEST_EVIDENCE.md` -
`M7_CODEX_AUTONOMOUS_REMEDIATION_TRACE.md` -
`M7_CODEX_RE_REVIEW_HANDOFF_EVIDENCE.md`

Do not place reports in repo root.

## 25. Required Final Invariants

Require:

``` text
HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES
HUMAN_IS_WORKFLOW_SCHEDULER=NO
DEFAULT_EXECUTION_POLICY=AUTO_CONTINUE
STOP_REQUIRES_EXPLICIT_REASON=YES
AUTO_RESUME_AFTER_RESULT_IMPORT=YES
INVALID_GENERIC_CONTINUE_STOPS=0
AUTO_ACTIONABLE_STOPPED_FOR_USER=0
```

Also report:

``` text
CAN_I_STOP_GATE=<status>
NEXT_ACTION_RESOLVER=<status>
HUMAN_TRANSPORT_GATE=<status>
HUMAN_AUTHORITY_GATE=<status>
AUTO_RESUME=<status>
ANTI_DRIFT_TESTS=<pass/total>
CURRENT_SCOPE_GAPS_OPEN=<count>
M6_GOLDEN_PATH_PRESERVED=YES/NO
UNKNOWN_REGRESSION_FAILURES=<count>
SOURCE_CAPABILITY_LOSS=<count>
```

## 26. STOP Condition

Proceed automatically through contract adoption, runtime implementation,
current Codex finding reproduction/remediation, tests, regression,
evidence update, and Codex re-review handoff generation.

Do not stop to ask whether to continue.

STOP only if: 1. a genuine Human Authority gate is reached; 2. a real
external-model handoff is ready and human transport is required; 3. safe
execution is blocked; 4. termination policy triggers; or 5. the
Canonical task is truly complete.

For Codex transport stop, report exactly:

``` text
TASK_ID
TARGET_MODEL
HANDOFF_FILE
EXPECTED_RESULT_FILE
IMPORT_COMMAND
NEXT_ACTION_AFTER_IMPORT=AUTO_RESUME
```

Do not start ChatGPT round trip automatically. Do not start M8. Do not
consume Reference USB.
