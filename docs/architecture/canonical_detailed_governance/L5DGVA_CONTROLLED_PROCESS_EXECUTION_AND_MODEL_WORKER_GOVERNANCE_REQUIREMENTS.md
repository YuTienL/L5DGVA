# L5DGVA Controlled Process Execution and Model Worker Governance Requirements

## Purpose

**Models do not own process authority. L5DGVA owns process authority.**

Codex, ChatGPT, Claude and future models provide evidence, findings,
results or specialized work. L5DGVA alone converts accepted Canonical
state into authorized execution.

``` text
Model Result → Canonical Validate/Consume → Next Action Resolver
→ Action Dispatcher → Execution Backend Router
→ L5DGVA Controlled Process Executor
→ approved PowerShell / Claude / Codex / native worker
→ Structured Result/Evidence → Canonical Ingestion → Next Action
```

Reuse P1--P6, Human Non-Scheduler, Safe Tool Execution, Task Boundary,
Agent Execution Backend, lifecycle/evidence/result-ingestion mechanisms.
Do not create competing engines.

## Prime Invariants

``` text
L5DGVA_OWNS_PROCESS_AUTHORITY=YES
MODEL_OWNS_PROCESS_AUTHORITY=NO
HUMAN_IS_WORKFLOW_SCHEDULER=NO
HUMAN_IS_AUTHORITY=YES
HUMAN_TRANSPORT_ALLOWED=YES
INTERACTIVE_TERMINAL_INJECTION=FORBIDDEN
ARBITRARY_SHELL_AUTHORIZATION=FORBIDDEN
SELF_PERMISSION_ESCALATION=FORBIDDEN
CONNECT_BEFORE_EXPAND=YES
OPERATIONAL_BEFORE_CLAIMED=YES
CLOSE_THE_LOOP=YES
```

## Roles

-   L5DGVA: state, ingestion, resolution, dispatch, backend selection,
    process authority, Task Boundary, Safe Tool policy, mutation lease,
    evidence, recovery, HumanGate.
-   Claude: implementation/remediation worker.
-   Codex: independent adversarial reviewer; finding a defect grants no
    process/mutation authority.
-   ChatGPT: architecture/requirements/governance reviewer.
-   Human: transport + true authority, not routine scheduler.

## Capability Family

`L5DGVA_CONTROLLED_PROCESS_EXECUTION`, `PROCESS_EXECUTOR_ROUTER`,
`POWERSHELL_EXECUTOR`, `CLAUDE_EXECUTOR`, `CODEX_EXECUTOR`,
`NATIVE_COMMAND_EXECUTOR`, `PROCESS_RUN_REQUEST`,
`PROCESS_RUN_IDENTITY`, `PROCESS_LAUNCH_POLICY`, `PROCESS_MONITOR`,
`PROCESS_RESULT_CONTRACT`, `PROCESS_RESULT_INGESTION`,
`PROCESS_TIMEOUT`, `PROCESS_CANCEL`, `PROCESS_RECOVERY`,
`PROCESS_IDEMPOTENCY`, `PROCESS_AUDIT_TRACE`,
`CANONICAL_MUTATION_LEASE`, `PROCESS_SCOPE_ENFORCEMENT`,
`EXECUTION_BACKEND_REACHABILITY_AUDIT`.

Reuse equivalent existing mechanisms.

## Canonical Process Run Request

Every launch derives from a Canonical action and includes:

``` text
PROCESS_RUN_ID
TASK_ID
PARENT_WORKFLOW_ID
ACTION_ID
ACTION_TYPE
REQUESTED_BACKEND
SELECTED_BACKEND
ROLE
OBJECTIVE
REPO_ID
CANONICAL_REPO_ROOT_ID
CURRENT_HEAD
WORKING_DIRECTORY
TASK_SCOPE
ALLOWED_FILES
FORBIDDEN_FILES
FROZEN_SOURCES
INPUT_EVIDENCE_REFS
REQUIRED_GOVERNANCE_REFS
TOOL_EXECUTION_PROFILE
MUTATION_ALLOWED
MUTATION_LEASE_REQUIRED
EXPECTED_OUTPUT
EXPECTED_OUTPUT_SCHEMA
VALIDATION_REQUIREMENTS
TIMEOUT_POLICY
RETRY_POLICY
RECOVERY_POLICY
HUMAN_AUTHORITY_CONSTRAINTS
RESUME_CONTRACT
```

## Repository Identity Gate

Before launch verify repo/root/task/head/CWD/handoff identity. Fail
closed on Parent, v50, b7a/b7b/b8, stale worktree or another repo.
Matching relative `.dv-harness` paths are insufficient.

## Action-to-Executor Reachability

Any routing-table action with `AUTO_ACTIONABLE=true` and
`NEXT_ACTION_OWNER=L5DGVA` must have one of:

``` text
PRODUCTION_REACHABLE_EXECUTOR
VALID_HUMAN_AUTHORITY_GATE
VALID_HUMAN_TRANSPORT_GATE
EXPLICIT_SAFE_EXECUTION_BLOCK
EXPLICIT_TERMINATION_POLICY
```

Never leave it `RESOLVED_BUT_NOT_EXECUTED`.

Audit every real routing-table action for executor, production caller,
input/output contracts, output consumer, failure path, tests/live
evidence. Classify `WIRED`, `FOUNDATION_ONLY`,
`RESOLVED_BUT_NOT_EXECUTED`, `OUTPUT_UNCONSUMED`,
`HUMAN_AUTHORITY_GATE`, `HUMAN_TRANSPORT_GATE`, `SAFE_EXECUTION_BLOCK`,
`TERMINATION`, or `UNKNOWN`.

## Process Executor Router

``` text
NEXT_ACTION → classify execution requirement → select backend
→ validate policy → acquire mutation lease if needed → launch
```

Persist requested/selected backend, status/block reason, fallback,
authorization and human-action requirement.

## PowerShell Executor

PowerShell is implementation, not authority. Only L5DGVA may launch it
through a valid request, approved executable/CWD/profile, Task Boundary,
required mutation lease and audit. Never blanket-authorize arbitrary
PowerShell.

## Semantic Execution Profiles

Initial profiles may include:

``` text
SAFE_STATUS
SAFE_READ
SAFE_TEST
SAFE_TEST_TEMP_CLEANUP
SAFE_HANDOFF_GENERATION
SAFE_RESULT_VALIDATION
SAFE_REGRESSION
CLAUDE_REMEDIATION
CODEX_REVIEW
CHATGPT_HANDOFF_PREPARATION
NATIVE_CANONICAL_MAINTENANCE
```

## Safe Test Temp Cleanup

Preauthorize only if target is canonicalized, registered to task, within
approved temp root, approved name, no traversal/reparse escape, not
production and not frozen. Do not use remembered REVIEW-specific command
strings as Canonical policy.

## Claude Executor

Preferred:

``` text
L5DGVA → CLAUDE_EXECUTOR → controlled Claude worker
→ remediation → structured result → Canonical ingestion
```

Preserve:

``` text
NATIVE_CONTROLLED_CLAUDE_WORKER=IMPLEMENTED_AND_TESTED_BLOCKED_BY_HOST_POLICY
```

No host-classifier bypass or self-permission modification.
Current-session fallback is not detached-worker qualification.

## Codex Executor

Future optional:

``` text
L5DGVA → CODEX_EXECUTOR → controlled independent review
→ HANDOFF → RESULT → Canonical ingestion
```

Codex remains reviewer. Current M7 may retain human-mediated Codex
transport.

## ChatGPT Transport

Current M7 may retain human-mediated ChatGPT architecture/governance
transport. Future automation remains L5DGVA-owned. Do not invent
unsupported local ChatGPT CLI behavior.

## Canonical Mutation Lease

Mutation-capable processes require an ownership-safe lease. Persist
lease/run/task/action/owner/acquired/liveness/scope/state. An old owner
must never delete a successor lock. Release retries must revalidate
ownership immediately before deletion or use equivalent atomic
semantics.

## Idempotency

`ACTION_ID + CANONICAL_STATE → at most one active mutation-capable process`.
Duplicate watcher/status/resume/restart events cannot double-launch.
Retries have explicit attempt identity.

## Monitoring

Track run/task/action/backend/PID,
start/elapsed/state/exit/timeout/result/lease/heartbeat. Never infer
hang from low CPU alone.

## Worker Result Contract

``` text
PROCESS_RUN_ID
TASK_ID
ACTION_ID
RUN_STATUS
START_HEAD
END_HEAD
FILES_CHANGED
TESTS_RUN
REGRESSION_RESULTS
EVIDENCE_REFS
GAPS_FOUND
GAPS_FIXED
HUMAN_DECISIONS_REQUIRED
NEXT_ACTION_HINT
ERRORS
```

Hints are advisory; Canonical resolver remains authoritative.

## Result Loop

``` text
PROCESS COMPLETE → structured result → validate → consume
→ evidence → release lease → Next Action → Action Dispatch
```

External model results:

``` text
Detect → publication/stability → hash → parse → validate
→ consume/quarantine → Next Action
```

Malformed:

``` text
RESULT_REJECTED_MALFORMED
→ AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF
→ Action Executor → Correction Handoff → transport
→ corrected result → changed-hash retry
```

## Completion Evaluation

`EVALUATE_CANONICAL_TASK_COMPLETION` must be a real executable action.
It distinguishes task completion, review-branch closure, wave/program
completion, Human Authority, transport, host limitation, current
blockers and next approved gate. One PASS never means the entire M7
program is complete.

## Human Non-Scheduler

Track:

``` text
HUMAN_TRANSPORT_EVENTS
HUMAN_AUTHORITY_EVENTS
HUMAN_SCHEDULER_INTERVENTIONS
PROVIDER_TOOL_PERMISSION_EVENTS
```

Routine continue/fix/import/regression/review scheduling counts as
scheduler intervention; transport and true authority do not. Target
`HUMAN_SCHEDULER_INTERVENTIONS=0`.

## Stop Policy

Legitimate only:

``` text
HUMAN_AUTHORITY_REQUIRED
HUMAN_TRANSPORT_REQUIRED
SAFE_EXECUTION_BLOCKED
TERMINATION_POLICY_TRIGGERED
TASK_COMPLETE
```

No generic continue/fix/test/start-next-review stops.

## Current M7 Scope

First close Next Action→Executor reachability. Preserve approved
human-mediated model transport. Do not start M8, consume Reference USB,
reopen Claude host-permission work, or build unsupported provider
automation merely for elegance.

## Anti-Drift Tests

Require behavioral equivalents:

``` text
test_every_auto_actionable_route_has_executor_or_valid_gate
test_evaluate_canonical_task_completion_is_executed
test_auto_correction_handoff_is_executed
test_action_dispatch_does_not_require_human_continue
test_process_launch_requires_canonical_action
test_process_launch_requires_repo_identity_match
test_powershell_executor_requires_profile
test_mutation_process_requires_lease
test_old_owner_cannot_release_successor_lock
test_retry_revalidates_lock_ownership
test_duplicate_event_does_not_double_launch
test_status_reporter_does_not_launch_or_mutate
test_safe_temp_cleanup_rejects_out_of_scope_target
test_codex_result_does_not_directly_gain_process_authority
test_chatgpt_result_does_not_directly_gain_process_authority
test_worker_result_returns_to_canonical_ingestion
test_completion_pass_does_not_equal_program_complete
test_human_authority_is_preserved
test_human_transport_is_not_scheduler_intervention
```

## Observability

Expose current task/action/owner/action status, requested/selected
backend/block reason, active/queued runs, run/PID/elapsed, mutation
lease, next action, human action, stop reason and human event counters.

## Qualification

Do not claim fully operational until real evidence proves:

``` text
Canonical Next Action → Action Dispatcher → Controlled Process Executor
→ bounded real action → structured result → Canonical ingestion → next action
```

For M7, prove all current-scope auto-actionable actions reachable or
legitimate gates.

Report separately:

``` text
WORKFLOW_AUTONOMY
ACTION_EXECUTION_AUTONOMY
PROCESS_INDEPENDENT_AUTONOMY
MODEL_TRANSPORT_AUTOMATION
```

## Governance Placement

Place detailed requirements under
`docs/architecture/canonical_detailed_governance/`; keep CLAUDE.md
compact and use task-scoped retrieval.

## Final Objective

> L5DGVA is the control plane. Models provide evidence and specialized
> work. L5DGVA alone converts accepted Canonical state into authorized
> process execution. Every auto-actionable Next Action is executed
> through a governed backend or routed to a legitimate gate. Humans
> provide transport and true authority, not routine scheduling.
