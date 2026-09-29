# CURRENT_SESSION_EXECUTOR Activation Closure Report (GAP-V2-019)

Continues `M7_NEXT_ACTION_REACHABILITY_CLOSURE_REPORT.md` and
`M7_CONTROL_PLANE_RUNTIME_HEAD_DRIFT_CLOSURE_REPORT.md`. Those closed:
(1) `dispatch_next_action()` has a real production caller
(`resume_after_import()`), and (2) a stale watcher process cannot keep
running pre-fix code silently. This closes the next real link in the
chain: `BACKEND_RESOLVED`/`CURRENT_SESSION_EXECUTOR` alone gave no
production mechanism for anything OTHER than a human manually reading the
dispatch report to discover and act on it.

## Independently re-verified, not trusted from the dispatch's own prose

```
TASK_ID = M7-V1-CHATGPT-ARCHITECTURE-REVIEW-002
RESULT_SHA256 = d681587f45267d4965e465afe9b70488c95286e3c2ff2171261e04500763587b
STATE = RESULT_CONSUMED, RESULT_STATUS = FAIL   (confirmed, state.json)
next_action.json: AUTO_REMEDIATE_CONFIRMED_FINDINGS, auto_actionable=true
Real event chain (ingestion_events.jsonl): RESULT_DETECTED ->
  RESULT_STABILITY_CONFIRMED -> AUTO_IMPORT_STARTED -> RESULT_ACCEPTED ->
  RESULT_CONSUMED -> AUTO_RESUME_STARTED -> NEXT_ACTION_RESOLVED ->
  ACTION_DISPATCHED (dispatch_status=BACKEND_RESOLVED)
Watcher runtime identity: PID=29700, RUNTIME_GENERATION=2,
  REPO_ROOT_MATCHED=true, SOURCE_HEAD_AT_START=6083ae6688a8...
```

All confirmed exactly as claimed, directly from the real persisted files.

## A critical independent finding: the real CG2-1/CG2-2 "findings" are stale

Before writing any activation code, the actual FINDINGS text in the real
consumed `RESULT_V1.md` was read (never assumed from the dispatch's own
summary):

- CG2-1/CG2-2: "no production caller of `dispatch_next_action` is
  established by the authorized REVIEW-002 implementation evidence."

`REVIEW-002`'s own `handoff.json` shows `CURRENT_HEAD = 6083ae6...` and
`INPUT_EVIDENCE_REFS` listing `execution_contract.py`, `agent_execution_
backend.py`, `model_handoff_workflow.py`, `controlled_process_executor.py`
and several docs/CSVs -- **`dv_harness/result_ingestion.py` was never
included**. `git show 6083ae6:dv_harness/result_ingestion.py` was checked
directly: line 672, `outcome = _ec.dispatch_next_action(root, task_id)`,
already existed inside `resume_after_import()` at that EXACT commit.

**The finding is a real artifact of an incomplete evidence bundle, not a
real current code gap.** ChatGPT's own `UNKNOWN_ITEMS` section is honest
about this: "Later control-plane remediation after CURRENT_HEAD 6083ae6
is not independently reviewable under this handoff because it is not
included in INPUT_EVIDENCE_REFS" -- but `result_ingestion.py` was ALREADY
present at 6083ae6 itself; it was simply never shown to the reviewer at
all, in any round.

This directly shaped the activation mechanism's own design: an assignment
built for `AUTO_REMEDIATE_CONFIRMED_FINDINGS` must never let a claiming
process blindly implement a prior finding as if it were current truth.
Every finding is quoted verbatim in the assignment's objective, but the
FIRST mandatory instruction is independent re-verification against
current evidence -- a finding that does not reproduce must be reported
`NOT_REPRODUCIBLE` with the real current evidence that shows so, never
silently "fixed" (which, for CG2-1/CG2-2 specifically, would mean adding
a redundant or conflicting second production caller to code that already
has the real one).

## Design: reuses existing architecture, no second scheduler

`dv_harness/execution_contract.py`, extending the existing Action
Dispatcher (never a new module/engine):

- `ExecutionAssignment` wraps a real `agent_execution_backend.
  AgentRunRequest` (built via the EXISTING `build_agent_run_request()` --
  never a second work-order shape), adding only what a claimable queue
  entry needs beyond that: `claim_state`, `repo_root_identity`/
  `repo_root_matched`, `source_head_at_creation`, `runtime_generation_at_
  creation`, timestamps, `claimed_by`, `lease_id`, `execution_outcome`.
- Created inside `dispatch_next_action()`'s own CURRENT_SESSION_EXECUTOR
  branch, only when `resolve_execution_backend()` genuinely authorizes the
  fallback -- `dispatch_status` stays `DISPATCH_BACKEND_RESOLVED`
  unchanged; the assignment id/claim_state are additive `detail` fields.
- `claim_execution_assignment()`: atomic (reuses `model_handoff_
  workflow._acquire_lock()`/`_release_lock()`, the exact primitive
  `_task_lock()`/the watcher role lock already reuse) and additionally
  acquires the real, pre-existing **Canonical Mutation Lease**
  (`agent_execution_backend.acquire_mutation_lease()`/`release_mutation_
  lease()`) -- the SAME lease a detached worker run already holds, so a
  current-session claim and a detached worker can never mutate
  concurrently. Fails closed on: not found, not READY (no double-claim),
  repo-identity mismatch, or a stale watcher `runtime_generation`
  (the control plane may have changed since the assignment was created).
- `discover_eligible_current_session_assignments()` /
  `loop_wakeup_check_and_claim()`: the read-only discovery and the atomic
  claim a `/loop` wakeup calls. Returns `None` and does nothing when
  nothing is eligible -- never invents work. A Human Authority/Transport
  gate task never produces an assignment at all: assignments are only
  ever created inside the `CURRENT_SESSION_EXECUTOR` branch, a code path
  `DISPATCH_GATE` actions never reach.
- `complete_execution_assignment()`: persists a real `agent_execution_
  backend.AgentRunResult`-shaped outcome (never a second result schema),
  releases the mutation lease, and closes the Canonical next-action loop
  the same way `EVALUATE_CANONICAL_TASK_COMPLETION`/`AUTO_GENERATE_
  CORRECTION_REQUEST_HANDOFF` already do -- never left stale for a manual
  follow-up.

No terminal keystroke injection, SendKeys, PowerShell-window automation,
clipboard injection, self-modifying permissions or host-policy bypass
anywhere in this mechanism -- purely Canonical-state-based (a JSON record
+ two existing lock primitives), verified structurally (AST-parsed, not
substring-matched, since the module's own prose legitimately NAMES the
forbidden mechanisms to disclose that it does not use them) by
`test_no_terminal_injection_mechanism_exists`.

## Claim discipline (dispatch section 9, never collapsed)

```
PRODUCTION_ACTION_DISPATCH   = WIRED (resume_after_import() -> dispatch_next_action(), proven prior task)
BACKEND_RESOLUTION           = WIRED (resolve_execution_backend() -> CURRENT_SESSION_EXECUTOR, proven live)
CURRENT_SESSION_ASSIGNMENT   = WIRED (this task: a real ExecutionAssignment is created and persisted)
CURRENT_SESSION_WORK_CLAIM   = WIRED (this task: loop_wakeup_check_and_claim() atomically claims it)
CURRENT_SESSION_EXECUTION    = PENDING a genuinely separate /loop wakeup's own claim+verify+remediate pass
PROCESS_INDEPENDENT_AUTONOMY = STILL NATIVE_CONTROLLED_CLAUDE_WORKER=IMPLEMENTED_AND_TESTED_BLOCKED_BY_HOST_POLICY;
                                CURRENT_SESSION_EXECUTOR activation is a fallback mechanism, not a claim
                                that detached process independence is solved
```

## Live qualification status

Code, tests and regression are complete this turn. Per the dispatch's own
explicit instruction ("Require the current Claude session, on its next
normal /loop wakeup, to discover and claim the real assignment
automatically... No human continue. No manual action dispatch"), the
actual claim+verify+remediate pass against the real REVIEW-002 assignment
is deliberately NOT performed manually in this same interactive turn --
it is scheduled for the next genuinely separate `/loop` wakeup, which will
call `loop_wakeup_check_and_claim()` for real, find the real REVIEW-002
assignment, claim it, independently re-verify CG2-1..CG2-4 against current
evidence, and report either a real fix (for a finding that reproduces) or
`NOT_REPRODUCIBLE` (for a finding that does not, as CG2-1/CG2-2 are
independently confirmed to be).
