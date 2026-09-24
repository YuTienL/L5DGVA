# L5DGVA Human Non-Scheduler Execution Contract

## Purpose

This is a platform-level executable requirement that operationalizes P6
`RESULT → ACTION → AUTONOMOUS CLOSURE`.

``` text
HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES
HUMAN_IS_WORKFLOW_SCHEDULER=NO
DEFAULT_EXECUTION_POLICY=AUTO_CONTINUE
STOP_REQUIRES_EXPLICIT_REASON=YES
```

The contract is not satisfied by documentation alone. It must exist in
runtime policy, persisted state, next-action resolution, stop
eligibility, status/reporting, anti-drift tests, and qualification
evidence.

> Continue automatically whenever a safe, authorized, machine-actionable
> next step exists. Stop only for real Human Authority, real human
> transport, a safe-execution blocker, a termination-policy trigger, or
> true Canonical task completion.

## Valid Stop Reasons

Only:

``` text
HUMAN_AUTHORITY_REQUIRED
HUMAN_TRANSPORT_REQUIRED
SAFE_EXECUTION_BLOCKED
TERMINATION_POLICY_TRIGGERED
TASK_COMPLETE
```

Every stop persists STATE, STOP_REASON, STOP_EVIDENCE,
NEXT_REQUIRED_ACTION, HUMAN_ACTION_REQUIRED, RESUME_ACTION.

## Invalid Generic Stops

Not valid by themselves:

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

"Waiting for your review/approval" is invalid unless a real authority
gate independently requires it.

## Canonical Task Completion

`CURRENT_SUBCOMMAND_COMPLETE != CANONICAL_TASK_COMPLETE`.

TASK_COMPLETE requires:

``` text
AUTO_ACTIONABLE_PENDING=0
REQUIRED_REMEDIATION_PENDING=0
REQUIRED_VERIFICATION_PENDING=0
REQUIRED_REGRESSION_PENDING=0
REQUIRED_REREVIEW_PREPARATION_PENDING=0
```

A prepared external handoff means HUMAN_TRANSPORT_REQUIRED, not
TASK_COMPLETE.

## Can-I-Stop Gate

Before every stop:

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

Reuse existing lifecycle/policy infrastructure; do not create a second
orchestration engine.

## Next Action Resolver

After every state-changing operation persist:

``` text
NEXT_ACTION
NEXT_ACTION_REASON
NEXT_ACTION_OWNER
AUTO_ACTIONABLE
HUMAN_ACTION_REQUIRED
STOP_REASON if any
```

It must be provider-independent and accept events/results from models,
agents, regression, RCA, coverage, formal, lint, build, signoff,
Knowledge Brain, research/change-impact, and future producers.

## Result Import Auto-Resume

Required:

``` text
RESULT_IMPORTED → RESULT_VALIDATED → RESULT_CONSUMED
→ AUTO_RESUME_ACTION_ROUTING
AUTO_RESUME_AFTER_RESULT_IMPORT=YES
```

A consumed `FAIL` with `HUMAN_DECISION_REQUIRED=NO` and
`FIX_NOW_CORRECTNESS_BLOCKER` routes to AUTO_REMEDIATION, not to
"waiting for instruction".

## Human Transport Gate

At transport stop report:

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

Human moves the artifact; human does not decide the post-import next
action.

## Human Authority Gate

At a real authority stop report:

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

Human Authority is not a generic uncertainty escape hatch.

## Safe Execution Blocker

SAFE_EXECUTION_BLOCKED requires concrete evidence such as an unavailable
mandatory dependency, unrecoverable state, unavailable mandatory
environment, unresolved contract ambiguity needing authority, or
required tool failure with no authorized fallback. A routine test
failure/review finding is not automatically a blocker.

## Termination Policy

Autonomous loops must be bounded through configurable/evidence-backed
policy for:

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

Termination never becomes PASS.

## Auto-Remediation Eligibility

Eligible when scope is already authorized, no protected
authority/security/access expansion is needed, frozen sources remain
untouched, and a validation path exists.

Typical eligible:

``` text
FIX_NOW_CURRENT_SCOPE
FIX_NOW_CORRECTNESS_BLOCKER
FIX_NOW_CAPABILITY_LOSS
```

Typical HumanGate:

``` text
HUMAN_DECISION_REQUIRED
DESIGN_AUTHORITY_REQUIRED
VERIFICATION_AUTHORITY_REQUIRED
VERIFICATION_SIGNOFF_REQUIRED
ARCHITECTURE_AUTHORITY_REQUIRED
SECURITY_SCOPE_EXPANSION
ACCESS_AUTHORIZATION_REQUIRED
```

## Automatic Remediation Chain

``` text
REPRODUCE → ROOT CAUSE → MINIMAL FIX → FOCUSED TEST
→ CONTRACT VALIDATION → PRODUCER/CONSUMER VALIDATION
→ E2E VALIDATION where applicable → REGRESSION
→ EVIDENCE UPDATE → RE-REVIEW PREPARATION
```

No routine permission stop between these stages.

## Re-Review Preparation

``` text
REMEDIATION_VERIFIED
→ GENERATE_RE_REVIEW_HANDOFF
→ RE_REVIEW_HANDOFF_READY
→ HUMAN_TRANSPORT_REQUIRED
```

After returned RESULT import/consumption, action routing resumes
automatically.

## Persist / Resume

``` text
STOP → PERSIST STATE → HUMAN/EXTERNAL ACTION
→ IMPORT/ANSWER → RESUME → NEXT ACTION RESOLVER → CONTINUE
```

The human must not reconstruct workflow state.

## Status Contract

Expose:

``` text
AUTO_RUNNING
WAITING_FOR_HUMAN_TRANSPORT
WAITING_FOR_HUMAN_AUTHORITY
BLOCKED
COMPLETE
```

When auto-running: `HUMAN_ACTION_REQUIRED=NO`. Never expose a generic
"waiting for user" state.

## Anti-Drift Tests

Require machine-checkable runtime tests equivalent to:

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

## Current M7 Codex Case

For `M7-V1-CODEX-REVIEW-001`:

``` text
CODEX_ROUND_TRIP=QUALIFIED
CODEX_OUTPUT_CONSUMED=YES
RESULT_STATUS=FAIL
HUMAN_DECISION_REQUIRED=NO
GAP-V2-009/010/011/012=FIX_NOW_CORRECTNESS_BLOCKER
```

Correct state: `AUTO_REMEDIATION_RUNNING`, not
WAITING_FOR_USER_TO_CONTINUE.

Continue reproduction → RCA → eligible fixes → tests → regression →
evidence → Codex re-review handoff. First legitimate human stop is real
re-review transport unless a genuine HumanGate/blocker occurs earlier.

## Full L5DGVA and Native Claude

Applies to Full L5DGVA and Native Claude Fast Maintenance while
fast-path eligible:

``` text
SAFE + AUTHORIZED + MACHINE_ACTIONABLE → AUTO_CONTINUE
```

## Governance Placement

Detailed authority belongs under:
`docs/architecture/canonical_detailed_governance/`

CLAUDE.md gets only compact ALWAYS_ON discoverability/reference.
Register task-scoped retrieval for orchestration, autonomous
remediation, result ingestion, review loops, HumanGate, stop/resume,
workflow status, and relevant M7+ execution.

## Required Invariants

``` text
HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES
HUMAN_IS_WORKFLOW_SCHEDULER=NO
DEFAULT_EXECUTION_POLICY=AUTO_CONTINUE
STOP_REQUIRES_EXPLICIT_REASON=YES
AUTO_RESUME_AFTER_RESULT_IMPORT=YES
INVALID_GENERIC_CONTINUE_STOPS=0
AUTO_ACTIONABLE_STOPPED_FOR_USER=0
```

## Qualification

Prove both: 1. A consumed auto-actionable result reaches
remediation/verification/re-review preparation without a user scheduling
prompt. 2. A real Human Transport or Human Authority condition stops
with explicit reason, required action, persisted state, and resumable
next action.

Documentation-only adoption is insufficient.

## Final Objective

> Humans provide transport where transport is manual and judgment where
> human authority is required. L5DGVA owns workflow progression. A safe,
> authorized, machine-actionable next step shall continue automatically.
