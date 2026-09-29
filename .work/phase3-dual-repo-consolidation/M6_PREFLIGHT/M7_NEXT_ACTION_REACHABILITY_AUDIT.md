# M7 Next-Action Reachability Audit

A CONNECT-BEFORE-EXPAND (P1) audit of every distinct `NEXT_ACTION` value
`execution_contract.NEXT_ACTION_TABLE` can produce. No new actions
invented; the table itself is unchanged. Real code search (`grep`)
performed for each value's name across the whole `dv_harness` package,
never assumed.

## The real finding, first (why this audit exists)

`M7-V1-CODEX-REVIEW-007` consumed cleanly (`RESULT_STATUS=PASS`), and the
resolver correctly produced `EVALUATE_CANONICAL_TASK_COMPLETION` -- but a
full-package grep found that string in exactly ONE file:
`execution_contract.py` itself (the routing table's own definition). No
function, test, or caller anywhere executed it. This is a real, confirmed
`RESOLVED_BUT_NOT_EXECUTED` gap -- fixed this session (see below).

The SAME grep, repeated for every OTHER distinct `NEXT_ACTION` value,
found the identical pattern for three more of them
(`AUTO_CLASSIFY_SCOPE_VIOLATION`, `AUTO_DIAGNOSE_VALIDATION_FAILURE`,
`AUTO_RETRY_AGENT_RUN`) -- each exists ONLY in the routing table and its
own routing-table test, with zero real executor and zero real historical
trigger. This audit reports that honestly rather than only fixing the one
finding the triggering event named.

## Audit table

| ACTION | AUTO_ACTIONABLE | EXECUTOR | PRODUCTION_CALLER | INPUT_CONTRACT | OUTPUT_CONTRACT | OUTPUT_CONSUMER | FAILURE_PATH | TEST_EVIDENCE | LIVE_EVIDENCE | REACHABILITY_STATUS |
|---|---|---|---|---|---|---|---|---|---|---|
| `AUTO_REMEDIATE_CONFIRMED_FINDINGS` | YES | current-session executor (no dedicated function -- code-authorship judgment cannot be a pure function without a second orchestration/code-generation engine, which this audit does not build) | orchestrating Claude Code session, per `agent_execution_backend.resolve_execution_backend()`'s own real `CURRENT_SESSION_EXECUTOR` fallback | a consumed FAIL result's real findings | a real code fix + regression + remediation report | the next Codex re-review handoff | none automated -- a stuck/incorrect fix is caught by the NEXT independent re-review round (proven: REVIEW-005 and REVIEW-006 each caught a real defect in the PRIOR round's own fix) | `test_execution_contract.py` (routing only) | 3 real executions (REVIEW-004->005, 005->006, 006->007 remediation commits) | **WIRED** (via current-session executor, real repeated evidence) |
| `EVALUATE_CANONICAL_TASK_COMPLETION` | YES | `execution_contract.evaluate_canonical_task_completion()` (NEW this session) | orchestrating session, invoked directly | a `RESULT_CONSUMED` task with `result_status=PASS`/clean | `CanonicalCompletionEvaluation` (task/branch/human-authority/program/next-gate) | `persist_completion_evaluation()` -> `canonical_completion_evaluation.json`; the orchestrating session acts on `next_approved_gate` | raises `ValueError` for a not-yet-consumed task, never silently guesses | `test_canonical_task_completion_evaluator.py` (9 tests) | 1 real execution: `M7-V1-CODEX-REVIEW-007` -> `GENERATE_CHATGPT_ARCHITECTURE_GOVERNANCE_HANDOFF` -> real ChatGPT handoff exported this session | **WIRED** (fixed and live-evidenced this session) |
| `HUMAN_AUTHORITY_REQUIRED` (4 routing entries) | NO (a stop) | `execution_contract.human_authority_report()` / `can_i_stop()` | orchestrating session + real human decision | a real authority question | a `HumanGate`-shaped report | the human, who answers | N/A (a gate, not a executable action) | `test_execution_contract.py` | 2 real Human Authority Decisions this session (worker-permission question) | **HUMAN_GATE** (real, evidenced) |
| `AUTO_CLASSIFY_SCOPE_VIOLATION` | YES | none found | none | a `RESULT_REJECTED` outcome whose findings mention `SCOPE_VIOLATION` | (undefined) | (undefined) | (undefined) | routing-table test only | none -- no real `RESULT_REJECTED_SCOPE_VIOLATION` event has ever fired in this program's history | **FOUNDATION_ONLY** (defined, never triggered, not fixed this pass -- classifying a scope violation is real domain-design work, not pure state aggregation; deferred, not a current-scope blocker since it has never actually misfired) |
| `AUTO_DIAGNOSE_VALIDATION_FAILURE` | YES | none found | none | a `RESULT_REJECTED` outcome with schema/content validation findings | (undefined) | (undefined) | (undefined) | routing-table test only | none -- never triggered | **FOUNDATION_ONLY** (same reasoning as above) |
| `AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF` | YES | `model_handoff_workflow.build_correction_request_handoff()` (fixed this session, GAP-V2-016) | orchestrating session | a `RESULT_REJECTED` (`MALFORMED_ESCAPE`) task | a real `ModelHandoffV1` correction request | `export_handoff()` -> human transport -> Codex resubmission | raises `HandoffBuildError` for a non-rejected/unknown task | `test_correction_request_handoff.py` (8 tests) | 1 real execution: `M7-V1-CODEX-REVIEW-007`'s real quarantine -> real correction -> real PASS resubmission | **WIRED** (fixed and live-evidenced this session) |
| `AUTO_RETRY_INTERRUPTED_IMPORT` | YES | no dedicated function, but the underlying mechanism already exists structurally: `import_result()` is documented and tested as idempotent/replay-safe -- calling it again with the same file IS the retry | orchestrating session or the watcher's own next poll cycle | an `IMPORT_INTERRUPTED` task state | the same `ImportOutcome` a fresh call always produces | unchanged Canonical consumption path | none additional -- reuses `import_result()`'s own existing exception handling | `test_model_handoff_review003_remediation.py::test_the_lock_is_released_even_when_the_import_raises` and neighbors | none -- no real mid-import crash has occurred in this program's history | **WIRED** (real, tested, idempotent-safe mechanism; no dedicated wrapper needed or built) |
| `RUN_FOCUSED_VALIDATION` / `RUN_REQUIRED_REGRESSION` | YES | current-session executor (`pytest`, run directly) | orchestrating session | fix-complete / validation-pass state | pass/fail regression result | the next routing decision (`REGRESSION_PASS` -> `PREPARE_REQUIRED_RE_REVIEW`) | a real failure blocks the commit (proven repeatedly this session) | N/A (this IS the test-running mechanism) | every commit this session ran the real regression suite before committing | **WIRED** (current-session executor, real repeated evidence) |
| `PREPARE_REQUIRED_RE_REVIEW` | YES | current-session executor (`build_handoff()` + `export_handoff()`, called directly) | orchestrating session | a passed regression | a real `ModelHandoffV1` | `export_handoff()` -> human transport | none -- `export_handoff()` has no failure path once a valid handoff object exists | `test_model_handoff_review00[4-7]_remediation.py` (each round's own handoff export) | 4 real Codex re-review handoffs + 1 real ChatGPT handoff this session | **WIRED** (real, repeated evidence) |
| `AUTO_RETRY_AGENT_RUN` | YES | none found | none | an `AGENT_RUN_FAILED_RETRY_ELIGIBLE`/`AGENT_RUN_TIMEOUT_RETRY_ELIGIBLE` event | (undefined) | (undefined) | (undefined) | `test_agent_execution_backend.py` (routing only) | none -- no real worker run has ever actually failed/timed out requiring retry in this program's history (every real launch was a read-only qualification or a clean synthetic run) | **FOUNDATION_ONLY** (defined, never triggered, not fixed this pass -- deciding a real retry policy for a partially-failed worker run is domain-design work, deferred) |
| `HUMAN_TRANSPORT_REQUIRED` (2 routing entries) | NO (a stop) | `execution_contract.human_transport_report()` / `signals_from_model_handoff_state()` / `can_i_stop()` | orchestrating session + real human transport | a `WAITING_FOR_HUMAN_TRANSPORT` task | a `HumanGate`-shaped transport report | the human, who transports | N/A (a gate) | `test_execution_contract.py` | 5 real transport events this program (4 Codex + 1 new ChatGPT, this session) | **TRANSPORT_GATE** (real, evidenced) |

## Summary

```
WIRED                = 7  (AUTO_REMEDIATE_CONFIRMED_FINDINGS, EVALUATE_CANONICAL_TASK_COMPLETION,
                           AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF, AUTO_RETRY_INTERRUPTED_IMPORT,
                           RUN_FOCUSED_VALIDATION/RUN_REQUIRED_REGRESSION, PREPARE_REQUIRED_RE_REVIEW)
HUMAN_GATE            = 1  (HUMAN_AUTHORITY_REQUIRED)
TRANSPORT_GATE        = 1  (HUMAN_TRANSPORT_REQUIRED)
FOUNDATION_ONLY       = 3  (AUTO_CLASSIFY_SCOPE_VIOLATION, AUTO_DIAGNOSE_VALIDATION_FAILURE,
                           AUTO_RETRY_AGENT_RUN)
RESOLVED_BUT_NOT_EXECUTED = 0  (was 1 -- EVALUATE_CANONICAL_TASK_COMPLETION -- fixed this session)
OUTPUT_UNCONSUMED     = 0
UNKNOWN               = 0
```

## Fixed this session (P3/P4/P6)

1. **`EVALUATE_CANONICAL_TASK_COMPLETION`** -- the ONE genuinely current-scope
   gap (a real, live-triggered event with no executor). Fixed:
   `execution_contract.evaluate_canonical_task_completion()`, reusing the
   EXISTING `WorkflowSignals`/`can_i_stop()` Can-I-Stop Gate and
   `signals_from_model_handoff_state()` adapter -- no second orchestration
   engine.

## Deliberately NOT fixed this session (disclosed, not silently dropped)

`AUTO_CLASSIFY_SCOPE_VIOLATION`, `AUTO_DIAGNOSE_VALIDATION_FAILURE`, and
`AUTO_RETRY_AGENT_RUN` are real `FOUNDATION_ONLY` gaps, structurally
identical in shape to the one just fixed -- but each requires genuine
domain-design judgment (how to classify a scope violation; how to diagnose
a validation failure; what retry policy a partially-failed worker run
should get) that cannot be reduced to pure state-aggregation the way
`EVALUATE_CANONICAL_TASK_COMPLETION` could. Building them without a real
historical trigger to validate the design against would risk exactly the
"new architecture decision" this audit was told not to make unilaterally.
None has ever misfired or blocked real work in this program's history.
Registered here as a real, named, disclosed residual for a future,
dedicated wave -- not silently left unmentioned.
