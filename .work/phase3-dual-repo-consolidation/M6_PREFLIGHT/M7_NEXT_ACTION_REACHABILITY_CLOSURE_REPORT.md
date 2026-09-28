# M7 Next-Action Reachability Closure Report

Continues (does not replace) the prior turn's own
`M7_NEXT_ACTION_REACHABILITY_AUDIT.md`, reconciled into
`L5DGVA_CONTROLLED_PROCESS_EXECUTION_AND_MODEL_WORKER_GOVERNANCE_
REQUIREMENTS.md`'s own exact classification vocabulary in
`docs/architecture/canonical_detailed_governance/
L5DGVA_NEXT_ACTION_REACHABILITY_MATRIX.csv`.

## Independently re-verified, not blindly trusted

```
TASK_ID = M7-V1-CODEX-REVIEW-007
STATE = RESULT_CONSUMED           (real, re-read from state.json)
RESULT_STATUS = PASS              (real, re-read)
ACCEPTED_RESULT_SHA256 = e14c2ef27fdeb4d800b5f96c9be543f508189c8af859a162914ead3c1d2a1b28  (matches exactly)
```

`next_action.json` at the start of this dispatch STILL showed
`EVALUATE_CANONICAL_TASK_COMPLETION`/`auto_actionable=true` -- confirming
the dispatch's own premise: "no downstream completion-evaluation/branch-
closure/next-gate artifact was observed after this persisted action" was
partially accurate. `canonical_completion_evaluation.json` (the real
evaluation) DID already exist, persisted by the prior turn's own fix --
but `next_action.json` had never been updated to reflect that the action
was executed. This is the real gap this closure report exists to record
and fix.

## Reproduce: exact classified cause

```
RESULT_CONSUMED_CLEAN -> EVALUATE_CANONICAL_TASK_COMPLETION
```

Classified: `OUTPUT_UNCONSUMED` (a narrower, more precise classification
than a bare `RESOLVED_BUT_NOT_EXECUTED` for the specific state found this
dispatch) -- the action WAS executed (a real `canonical_completion_
evaluation.json` existed, produced by the prior turn) and its
recommendation WAS acted on (the real ChatGPT handoff was already
exported) -- but the execution's own outcome was never written back to
the SOURCE task's own `next_action.json`, so a reader of that one file
alone could not tell the difference between "never executed" and
"executed, but not recorded." Fixed this dispatch:
`execution_contract.record_completion_evaluation_next_action()`.

## Full reachability audit -- UPDATED, ChatGPT REVIEW-001 (CG-1/CG-2) gap-close

ChatGPT's own real architecture-governance round trip
(`M7-V1-CHATGPT-ARCHITECTURE-REVIEW-001`) independently re-derived this
audit and found it self-inconsistent: `AUTO_ACTIONABLE_UNREACHABLE=0` was
claimed while 3 `FOUNDATION_ONLY` actions genuinely had no executor
(CG-1), and `WORKFLOW_AUTONOMY=OPERATIONAL` overclaimed a route as
reachable merely because the interactive session could manually execute
it, while `resolve_execution_backend()` had no real production caller at
all (CG-2). Both findings independently re-verified and fixed -- see
`M7_CHATGPT_REVIEW_001_FINDINGS_REMEDIATION_REPORT.md`. Real new
executors: `execution_contract.classify_scope_violation()`/`diagnose_
validation_failure()`, `agent_execution_backend.build_retry_agent_run_
request()`, and a real, minimal `execution_contract.dispatch_next_
action()` Action Dispatcher giving `resolve_execution_backend()` its
first genuine production call site.

See `docs/architecture/canonical_detailed_governance/
L5DGVA_NEXT_ACTION_REACHABILITY_MATRIX.csv` (13 rows, the governance
doc's own exact vocabulary). Summary, corrected:

```
AUTO_ACTIONABLE_ACTIONS   = 9  (9 WIRED + 0 FOUNDATION_ONLY)
AUTO_ACTIONABLE_WIRED     = 9
AUTO_ACTIONABLE_GATES     = 3  (2 HUMAN_AUTHORITY_GATE + 1 HUMAN_TRANSPORT_GATE)
AUTO_ACTIONABLE_UNREACHABLE = 0   (RESOLVED_BUT_NOT_EXECUTED + OUTPUT_UNCONSUMED +
                                   FOUNDATION_ONLY, all now 0 after this update)
FOUNDATION_ONLY (disclosed, deferred, never live-triggered) = 0
```

No `RESOLVED_BUT_NOT_EXECUTED`, `OUTPUT_UNCONSUMED`, `FOUNDATION_ONLY`, or
`UNKNOWN` action remains. The 3 actions previously `FOUNDATION_ONLY`
(`AUTO_CLASSIFY_SCOPE_VIOLATION`, `AUTO_DIAGNOSE_VALIDATION_FAILURE`,
`AUTO_RETRY_AGENT_RUN`) each now have a real, callable, tested executor
that performs genuinely mechanical work (extraction of already-computed
`ValidationOutcome` fields, or bounded reuse of the existing
`AgentRunRequest`/`launch_worker()` primitives) -- never invented
domain-design judgment. None has ever misfired or been live-triggered by
a real result in this program's history; that remains honestly disclosed.

## Fixed this dispatch (this turn)

1. `execution_contract.classify_scope_violation()` / `diagnose_
   validation_failure()`, `agent_execution_backend.build_retry_agent_
   run_request()`: real executors for the 3 previously `FOUNDATION_ONLY`
   actions (ChatGPT REVIEW-001 CG-1).
2. `execution_contract.dispatch_next_action()`: the real, minimal Action
   Dispatcher, giving `resolve_execution_backend()` its first genuine
   production call site (ChatGPT REVIEW-001 CG-2). Live-verified against
   both `M7-V1-CODEX-REVIEW-007` and `M7-V1-CHATGPT-ARCHITECTURE-
   REVIEW-001`.
3. `model_handoff_workflow._cited_existing_question_id()`: prevents a
   duplicate HumanGate question for an already-tracked decision (ChatGPT
   REVIEW-001 CG-5).

## Fixed the prior turn (unchanged, carried forward)

1. `controlled_process_executor.py` (new module): Repository Identity
   Gate, Semantic Execution Profiles, `SAFE_TEST_TEMP_CLEANUP`.
2. `execution_contract.record_completion_evaluation_next_action()`: closes
   the real `OUTPUT_UNCONSUMED` gap found above, applied live to
   `M7-V1-CODEX-REVIEW-007`'s own record.

## Replay result

See `M7_COMPLETION_EVALUATION_EVIDENCE.md` for the full real replay.
Summary: `TASK_COMPLETE`, `BRANCH_READY_FOR_CLOSURE`, 1 outstanding
non-blocking Human Authority item (Q-ENV-57D420FA, R005-2/R006-4,
unchanged), `M7_NOT_COMPLETE:CHATGPT_ROUND_TRIP_NOT_CONSUMED`, next
approved gate `GENERATE_CHATGPT_ARCHITECTURE_GOVERNANCE_HANDOFF` --
already real and exported (`M7-V1-CHATGPT-ARCHITECTURE-REVIEW-001`,
`WAITING_FOR_HUMAN_TRANSPORT`), confirmed idempotent and unchanged by this
dispatch's fresh re-evaluation.
