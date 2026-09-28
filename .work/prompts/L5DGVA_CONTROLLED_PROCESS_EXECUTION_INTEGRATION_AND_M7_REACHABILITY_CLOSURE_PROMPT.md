# L5DGVA Controlled Process Execution Integration and M7 Reachability Closure Prompt

## Mission

Read and adopt completely:

`docs/architecture/canonical_detailed_governance/L5DGVA_CONTROLLED_PROCESS_EXECUTION_AND_MODEL_WORKER_GOVERNANCE_REQUIREMENTS.md`

This is **CONNECT-BEFORE-EXPAND / M7 reachability closure**, not a new
wave.

## Re-verify Real State

Independently verify Canonical root, branch, HEAD, worktree, frozen
sources and current persisted state.

Expected current evidence to re-derive, not blindly trust:

``` text
TASK_ID=M7-V1-CODEX-REVIEW-007
STATE=RESULT_CONSUMED
RESULT_STATUS=PASS
ACCEPTED_RESULT_SHA256=e14c2ef27fdeb4d800b5f96c9be543f508189c8af859a162914ead3c1d2a1b28
NEXT_ACTION=EVALUATE_CANONICAL_TASK_COMPLETION
AUTO_ACTIONABLE=true
HUMAN_ACTION_REQUIRED=NO
NEXT_ACTION_OWNER=L5DGVA
STOP_REASON=null
```

No downstream completion-evaluation/branch-closure/next-gate artifact
was observed after this persisted action.

## 1. Preflight

Record:

``` text
PROCESS_CWD
REPO_ROOT
BRANCH
START_HEAD
WORKING_TREE_STATUS
```

Require authoritative Canonical repository identity; fail closed on
another repo/worktree.

Read the complete governance requirement plus relevant P1--P6, Human
Non-Scheduler, Safe Tool Execution, Agent Execution Backend, M7
convergence contract, REVIEW-007 state, routing table, action-dispatch
code, Gap Register, Master matrices and M6 Golden Path evidence.

Verify frozen sources unchanged.

## 2. Reproduce Missing Edge

Prove whether:

``` text
RESULT_CONSUMED_CLEAN
→ EVALUATE_CANONICAL_TASK_COMPLETION
```

is persisted but not executed.

Classify exact cause:

``` text
MISSING_EXECUTOR
EXECUTOR_NO_PRODUCTION_CALLER
DISPATCHER_DOES_NOT_RECOGNIZE_ACTION
DISPATCHER_NOT_RUNNING
OUTPUT_UNCONSUMED
OTHER_EVIDENCED_CAUSE
```

Do not assume.

## 3. Full Next-Action Reachability Audit

Enumerate every action the real provider-independent routing table can
produce.

For each derive:

``` text
ACTION
AUTO_ACTIONABLE
OWNER
EXECUTOR
PRODUCTION_CALLER
INPUT_CONTRACT
OUTPUT_CONTRACT
OUTPUT_CONSUMER
FAILURE_PATH
TEST_EVIDENCE
LIVE_EVIDENCE
REACHABILITY_STATUS
```

Classify only:

``` text
WIRED
FOUNDATION_ONLY
RESOLVED_BUT_NOT_EXECUTED
OUTPUT_UNCONSUMED
HUMAN_AUTHORITY_GATE
HUMAN_TRANSPORT_GATE
SAFE_EXECUTION_BLOCK
TERMINATION
UNKNOWN
```

Do not invent actions.

## 4. Fix Reachability, Not Symptoms

Fix every current-scope auto-actionable reachability gap found where no
new architecture decision is required.

Reuse existing dispatch/execution mechanisms. Do not create a second
orchestration engine.

At minimum production-connect:

``` text
EVALUATE_CANONICAL_TASK_COMPLETION
```

Preserve the live-qualified malformed-result correction path.

## 5. Completion Semantics

Completion evaluation derives from Canonical evidence and distinguishes:

``` text
TASK_COMPLETE
REVIEW_BRANCH_READY_FOR_CLOSURE
PROGRAM_OR_WAVE_COMPLETE
HUMAN_AUTHORITY_OUTSTANDING
HUMAN_TRANSPORT_OUTSTANDING
HOST_DEPENDENT_LIMITATION
CURRENT_SCOPE_BLOCKER
NEXT_APPROVED_GATE
```

Do not equate REVIEW-007 PASS with M7 completion.

Preserve R005-2/R006-4 as unresolved Human Authority unless the human
actually decides it.

## 6. Process Authority

Enforce:

``` text
L5DGVA_OWNS_PROCESS_AUTHORITY=YES
MODEL_OWNS_PROCESS_AUTHORITY=NO
```

Codex/ChatGPT/Claude may return results/hints but do not directly gain
arbitrary PowerShell or mutation authority.

Reuse existing Agent Execution Backend, Task Boundary, Safe Tool,
mutation lease, process/subprocess and evidence mechanisms before adding
anything.

Do not reopen Claude host-policy work. Preserve detached Claude worker
as implemented/tested/host-blocked.

## 7. Repository Identity

Before controlled process execution, fail closed unless Canonical repo
identity/CWD/task/head/handoff identity match.

Use the real wrong-repository REVIEW-007 incident as evidence. Do not
copy artifacts across repositories to satisfy identity.

## 8. Semantic Safe Tool Profiles

Reconcile bounded semantic profiles, including `SAFE_TEST_TEMP_CLEANUP`,
so registered task-owned temp cleanup can execute without repeated human
scheduling.

Do not blanket-authorize PowerShell.

## 9. Replay the Real REVIEW-007 State

After wiring the missing edge, resume/replay from the real persisted
accepted REVIEW-007 state, not a fabricated result.

Require:

``` text
EVALUATE_CANONICAL_TASK_COMPLETION
→ real completion evaluation
→ persisted evidence
→ next Canonical action
→ action execution
```

If the Codex branch is genuinely ready, close/reconcile it under the
approved M7 convergence contract.

If the next approved gate is ChatGPT architecture-governance review,
generate the real ChatGPT handoff automatically through production
mechanisms.

Do not ask whether to start ChatGPT.

Expected legitimate stop if reached:

``` text
STOP_REASON=HUMAN_TRANSPORT_REQUIRED
TARGET_MODEL=chatgpt
TASK_TYPE=architecture-governance-review
HANDOFF_FILE=<real generated path>
EXPECTED_RESULT_FILE=<real registered path>
HUMAN_ACTION_REQUIRED=Transport only
```

## 10. Do Not Automate Model Transport Yet

For current M7, retain human-mediated Codex/ChatGPT transport unless
already supported by approved mechanisms.

Controlled Codex/ChatGPT process automation is future/optional; do not
expand M7 merely to remove transport.

## 11. Anti-Drift Tests

Add/reconcile tests proving at least:

``` text
every auto-actionable route has executor or valid gate
completion evaluation actually executes
malformed correction action actually executes
no human continue required
repo identity gate
semantic PowerShell profile
mutation lease
old owner cannot release successor lock
release retry revalidates ownership
duplicate event does not double-launch
status reporter remains read-only
safe temp cleanup is bounded
Codex result cannot directly gain process authority
ChatGPT result cannot directly gain process authority
worker result returns to Canonical ingestion
PASS task != whole-program completion
Human Authority preserved
Human Transport != scheduler intervention
```

Run focused tests then required M7/M6 regression. Classify failures and
require unknown regression failures = 0. Preserve Constitution gate and
frozen sources.

## 12. Required Artifacts

Produce/reconcile in approved existing artifact areas:

``` text
L5DGVA_CONTROLLED_PROCESS_EXECUTION_ADOPTION_REPORT.md
L5DGVA_NEXT_ACTION_REACHABILITY_MATRIX.csv
L5DGVA_PROCESS_EXECUTOR_ARCHITECTURE.md
L5DGVA_PROCESS_RUN_REQUEST_CONTRACT.md
L5DGVA_PROCESS_EXECUTION_AUDIT_EVIDENCE.md
M7_NEXT_ACTION_REACHABILITY_CLOSURE_REPORT.md
M7_COMPLETION_EVALUATION_EVIDENCE.md
```

Do not put reports in repo root. Keep CLAUDE.md compact.

## 13. Required Final Report

Report honestly:

``` text
CONTROLLED_PROCESS_EXECUTION=<status>
L5DGVA_OWNS_PROCESS_AUTHORITY=YES/NO
MODEL_OWNS_PROCESS_AUTHORITY=NO/YES

NEXT_ACTION_REACHABILITY_AUDITED=YES/NO
AUTO_ACTIONABLE_ACTIONS=<count>
AUTO_ACTIONABLE_WIRED=<count>
AUTO_ACTIONABLE_GATES=<count>
AUTO_ACTIONABLE_UNREACHABLE=<count>

EVALUATE_CANONICAL_TASK_COMPLETION=<status>
ACTION_DISPATCH=<status>
POWERSHELL_EXECUTOR=<status>
SAFE_TEST_TEMP_CLEANUP=<status>
REPOSITORY_IDENTITY_GATE=<status>
CANONICAL_MUTATION_LEASE=<status>

WORKFLOW_AUTONOMY=<status>
ACTION_EXECUTION_AUTONOMY=<status>
PROCESS_INDEPENDENT_AUTONOMY=<status>
MODEL_TRANSPORT_AUTOMATION=<status>

CODEX_BRANCH=<status>
CHATGPT_HANDOFF=<status>
HUMAN_SCHEDULER_INTERVENTIONS=<count>

R005_2_R006_4=<status>
M6_GOLDEN_PATH_PRESERVED=YES/NO
UNKNOWN_REGRESSION_FAILURES=<count>
SOURCE_CAPABILITY_LOSS=<count>
CONSTITUTION_GATE=<status>
REFERENCE_USB_ENV_CONSUMED=NO
NEXT_RECOMMENDED_GATE=<gate>
```

## 14. Stop Policy

Continue automatically through safe machine-actionable audit, fix, test,
regression, replay and closure.

Apply Can-I-Stop after each Canonical action.

Stop only for:

``` text
HUMAN_AUTHORITY_REQUIRED
HUMAN_TRANSPORT_REQUIRED
SAFE_EXECUTION_BLOCKED
TERMINATION_POLICY_TRIGGERED
TASK_COMPLETE
```

Do not stop for continue/fix/tests/regression/next-review approval.

Do not start M8. Do not consume Reference USB. Do not reopen Claude
host-permission work.

## Final Objective

Close the current M7 action-execution gap so that L5DGVA---not Codex,
ChatGPT, Claude, or the human---owns the transition from accepted
Canonical Next Action to governed execution.
