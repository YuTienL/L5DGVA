# M7 Human Authority Gate Evidence

Real code: `dv_harness/execution_contract.py::human_authority_report()`,
`can_i_stop()`. Tests: `test_human_authority_requires_stop`,
`test_human_authority_report_carries_a_resume_action_never_a_dead_end`,
`test_higher_priority_gate_wins_when_multiple_signals_are_true`.

## Required report shape (verified against real function output)

```
STATE=WAITING_FOR_HUMAN_AUTHORITY
STOP_REASON=HUMAN_AUTHORITY_REQUIRED
AUTHORITY_TYPE
QUESTION
OPTIONS if applicable
EVIDENCE
IMPACT
RESUME_ACTION
```

`human_authority_report()` always requires a real `resume_action` -- a
Human Authority stop is never a dead end with no stated path forward.

## Not a generic uncertainty fallback (enforced)

`WorkflowSignals.human_authority_required` is a real, caller-supplied
boolean -- nothing in `can_i_stop()` sets it from "I am unsure" or from
a routine test failure/review finding (that is `SAFE_EXECUTION_BLOCKED`
territory, and even that "requires concrete evidence" per the contract,
never a bare "not sure"). `test_higher_priority_gate_wins_when_multiple_
signals_are_true` confirms Human Authority outranks every other gate
when it IS genuinely set, so a real authority question is never masked
by a lower-priority signal.

## Applied to the live M7 Codex case

No genuine Human Authority condition was reached during this task or
the prior one -- the GAP-V2-009/010/011/012 remediation was, in
retrospect, real `FIX_NOW_CORRECTNESS_BLOCKER` work with none of the six
`result_action_router.py` reject reasons true (see
`M7_AUTO_REMEDIATION_ELIGIBILITY.md`), so this gate correctly never
fired. This is disclosed honestly as "not yet triggered live," not
claimed as exercised against real production data the way the Human
Transport Gate was.

## Status

`HUMAN_AUTHORITY_GATE_STATUS=WIRED_AND_TESTED_NOT_YET_TRIGGERED_LIVE`.
