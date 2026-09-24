# M7 Result-to-Action Routing

Real code: `dv_harness/result_action_router.py::route_action()` /
`evaluate_auto_remediation_eligibility()`. Tests:
`dv_harness_tests/test_result_action_router.py` (30/30 pass).

## Provider independence (verified, not merely claimed)

`RemediationCandidate` has no `producer_model`/`target_model` field --
`test_router_never_branches_on_producer_model_it_never_receives_one`
asserts this structurally (`hasattr` checks), so the module cannot be
made to special-case Codex vs. ChatGPT vs. any future target model even
by accident; it only ever sees a disposition + six real booleans a
caller derived from the specific fix a finding needs.

## Routing table (as implemented)

| Disposition | Action class |
|---|---|
| `HUMAN_DECISION_REQUIRED` | `HUMAN_GATE_REQUIRED` |
| `REGISTER_AND_DEFER_WITH_OWNER` | `DEFERRED_WITH_OWNER` |
| `SUPERSEDED_WITH_EVIDENCE` | `CLOSE_WITH_EVIDENCE` |
| `NOT_APPLICABLE_WITH_EVIDENCE` | `CLOSE_WITH_EVIDENCE` |
| `FIX_NOW_SAFETY_SECURITY` | `HUMAN_GATE_REQUIRED` (always -- never a default auto candidate) |
| `FIX_NOW_CURRENT_SCOPE` / `FIX_NOW_CORRECTNESS_BLOCKER` / `FIX_NOW_CAPABILITY_LOSS` | `evaluate_auto_remediation_eligibility()` (see `M7_AUTO_REMEDIATION_ELIGIBILITY.md`) |
| (any disposition not in the closed `DISPOSITIONS` tuple) | rejected at `RemediationCandidate.__post_init__()` with `ValueError` -- never silently routed |

## Status

`RESULT_TO_ACTION_ROUTER_STATUS=WIRED_AND_TESTED`,
`PRODUCTION_CALL_SITE_WIRING=NOT_YET_WIRED` -- this task built and
tested the router as a real, importable module, but no engine/CLI call
site invokes it automatically yet on a consumed `RESULT_CONSUMED`
transition. Applying it to THIS task's own GAP-V2-009/010/011/012
remediation was done by direct, manual P5 FIND->FIX->VERIFY (the module
did not exist yet when that remediation started); see
`M7_AUTONOMOUS_REMEDIATION_EVIDENCE.md` for the honest accounting of
what ran through which mechanism.

Per the Methodology Consolidation Rule: wiring a real
`model_handoff_workflow.import_result()` call site that automatically
constructs `RemediationCandidate`s from a consumed result's `FINDINGS`
and invokes `route_action()` is the next required step to move this from
WIRED_AND_TESTED to actually driving the autonomous loop -- registered
as open work, not claimed done here.
