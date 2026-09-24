# M7 Loop Termination and Budget Policy

Real code: `dv_harness/result_action_router.py::LoopBudget`,
`LoopTerminationPolicy`, `check_loop_termination()`. Tests:
`dv_harness_tests/test_result_action_router.py` (loop-termination
section, 10 tests covering every named stop reason plus the
"budget OK, no signatures supplied" continue path).

## Budget (measured, real counters)

`LoopBudget`: `iteration_count`, `model_invocations`, `test_run_count`,
`regression_run_count`, `wall_time_seconds`, `context_bytes`,
`token_usage` (left `None`, never fabricated as `0`, when a caller
cannot measure it), `retry_count`.

## Policy (configurable, evidence-backed thresholds)

`LoopTerminationPolicy`: `max_remediation_iterations` (default 10),
`max_retry_per_finding` (default 3), `max_wall_time_seconds` (default
3600), `max_context_bytes` (default `None` = no context ceiling
enforced). Defaults are conservative starting points, not claimed as
tuned-from-evidence for any specific task class yet -- a caller adopting
this for a real autonomous loop should override them with real,
documented rationale for that loop's own risk profile.

## Termination reasons (every stop path is named, never a bare `False`)

`BUDGET_OK` (continue), `MAX_REMEDIATION_ITERATIONS_EXCEEDED`,
`MAX_RETRY_PER_FINDING_EXCEEDED`, `WALL_TIME_EXCEEDED`,
`CONTEXT_BUDGET_EXCEEDED`, `REPEATED_FAILURE_SIGNATURE`,
`REPEATED_FINDING_SIGNATURE`, `REGRESSION_EXPANSION_DETECTED`,
`SCOPE_EXPANSION_DETECTED`, `EVIDENCE_STAGNATION`. `NO_PROGRESS_DETECTED`
is a defined constant (`REASON_NO_PROGRESS`) reserved for a future
caller-supplied no-progress signal distinct from the repeated-signature
checks; no current code path emits it yet -- disclosed here rather than
silently defined-but-dead.

Every stop path sets `requires_human_escalation=True` -- this module
never lets budget exhaustion or loop pathology resolve to a silent PASS
(Prime Directive V2 P6's own `AUTO_PASS_ON_BUDGET_EXHAUSTION=NO`
invariant).

## Status

`LOOP_TERMINATION_POLICY_STATUS=WIRED_AND_TESTED`,
`PRODUCTION_CALL_SITE_WIRING=NOT_YET_WIRED` -- same honest status as the
router/eligibility functions in the same module; no autonomous
remediation loop in this codebase calls `check_loop_termination()` yet.
This task's own remediation of GAP-V2-009/010/011/012 was six findings
across two commits, well inside any reasonable default threshold, so the
absence of live wiring did not affect its own outcome -- but no claim is
made that this policy was actually exercised for real during that work.
