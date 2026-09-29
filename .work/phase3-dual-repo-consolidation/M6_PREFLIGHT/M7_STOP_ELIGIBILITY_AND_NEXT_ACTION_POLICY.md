# M7 Stop Eligibility and Next Action Policy

Real code: `dv_harness/execution_contract.py::can_i_stop()`,
`resolve_next_action()`. Tests: `dv_harness_tests/test_execution_contract.py`.

## Can-I-Stop Gate (exact decision order)

```
IF human_authority_required:            STOP(HUMAN_AUTHORITY_REQUIRED)
ELSE IF human_transport_required:       STOP(HUMAN_TRANSPORT_REQUIRED)
ELSE IF safe_execution_blocked:         STOP(SAFE_EXECUTION_BLOCKED)
ELSE IF termination_policy_triggered:   STOP(TERMINATION_POLICY_TRIGGERED)
ELSE IF any REQUIRED_*_PENDING/AUTO_ACTIONABLE_PENDING: CONTINUE
ELSE IF canonical_task_complete:        STOP(TASK_COMPLETE)
ELSE:                                   CONTINUE
```

`test_higher_priority_gate_wins_when_multiple_signals_are_true` proves
the priority ordering is real (Human Authority beats Human Transport
when both are set). `canonical_task_complete` is always caller-asserted
-- never inferred from "zero known pending work" -- so completeness
claimed without real evidence cannot silently stop the loop; the default
when nothing is asserted either way is CONTINUE.

## Next Action Resolver

Table-driven (`NEXT_ACTION_TABLE`), provider-independent (keyed by
abstract event name only):

| Event | Next action | Owner | Auto-actionable |
|---|---|---|---|
| `RESULT_CONSUMED` | `AUTO_REMEDIATE_CONFIRMED_FINDINGS` | L5DGVA | Yes |
| `FIX_COMPLETE` | `RUN_FOCUSED_VALIDATION` | L5DGVA | Yes |
| `VALIDATION_PASS` | `RUN_REQUIRED_REGRESSION` | L5DGVA | Yes |
| `REGRESSION_PASS` | `PREPARE_REQUIRED_RE_REVIEW` | L5DGVA | Yes |
| `RE_REVIEW_HANDOFF_READY` | `HUMAN_TRANSPORT_REQUIRED` | HUMAN | No |

An event not in the table is a real `ValueError`
(`test_unknown_event_is_a_real_error_never_a_guessed_default`) --
this module never silently invents a plausible-sounding next action.

## Applied to the live M7 Codex case

- `M7-V1-CODEX-REVIEW-001`: `RESULT_CONSUMED` already occurred (prior
  task); `AUTO_REMEDIATE_CONFIRMED_FINDINGS` -> `FIX_COMPLETE` ->
  `RUN_FOCUSED_VALIDATION` -> `VALIDATION_PASS` -> `RUN_REQUIRED_REGRESSION`
  -> `REGRESSION_PASS` -> `PREPARE_REQUIRED_RE_REVIEW` ->
  `RE_REVIEW_HANDOFF_READY` were all real events that actually happened
  (git commits `740fbe6`/`892439d`/`713f942`/`1966fa9`), matching this
  table's own chain exactly, even though the table itself did not exist
  yet when those steps ran (same disclosed provenance as
  `M7_AUTONOMOUS_REMEDIATION_EVIDENCE.md`).
- `M7-V1-CODEX-REVIEW-002`: currently at `RE_REVIEW_HANDOFF_READY` ->
  `HUMAN_TRANSPORT_REQUIRED`, confirmed live via
  `signals_from_model_handoff_state()` + `can_i_stop()`
  (`M7_CODEX_AUTONOMOUS_REMEDIATION_TRACE.md`).

## Status

`CAN_I_STOP_GATE_STATUS=WIRED_AND_TESTED`,
`NEXT_ACTION_RESOLVER_STATUS=WIRED_AND_TESTED`,
`PRODUCTION_CALL_SITE_WIRING=PARTIAL` -- both functions were called for
real against the live M7 Codex case's actual state (not only unit
tests), but no engine/CLI call site invokes either one automatically
after every real state-changing operation yet. Wiring
`model_handoff_workflow.import_result()`'s own state transitions to
call `resolve_next_action()`/`can_i_stop()` automatically, and to
persist the result via `persist_stop()`, is the concrete next step --
registered here rather than silently left implicit, per the Methodology
Consolidation Rule.

## Addendum: REJECTED / clean / human-decision outcomes and live wiring (REVIEW-002 task)

The resolver table was missing every REJECTED outcome: after
`M7-V1-CODEX-REVIEW-002` came back `RESULT_REJECTED`, the workflow simply
stopped in that state and nothing persisted what should happen next -- a
real gap against "after every state-changing operation persist
NEXT_ACTION". Added events:

| Event | Next action | Auto |
|---|---|---|
| `RESULT_REJECTED_SCOPE_VIOLATION` | `AUTO_CLASSIFY_SCOPE_VIOLATION` | yes |
| `RESULT_REJECTED_VALIDATION` | `AUTO_DIAGNOSE_VALIDATION_FAILURE` | yes |
| `RESULT_REJECTED_MALFORMED` | `AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF` | yes |
| `RESULT_CONSUMED_CLEAN` | `EVALUATE_CANONICAL_TASK_COMPLETION` | yes |
| `RESULT_CONSUMED_HUMAN_DECISION` | `HUMAN_AUTHORITY_REQUIRED` | no (stop) |

`model_handoff_workflow.import_result()` now calls
`execution_contract.event_for_import_outcome()` +
`persist_next_action()` on every outcome (`next_action.json` beside
`state.json`); replay of a consumed FAIL keeps `AUTO_REMEDIATE_CONFIRMED_FINDINGS`.
Six tests in `test_execution_contract.py` (47 total). Status moves from
`NOT_YET_WIRED` to `WIRED_FOR_RESULT_IMPORT`; the Can-I-Stop Gate is still
applied by explicit call, not by an engine hook.
