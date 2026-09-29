# M7 Execution Backend Fallback Reconciliation

Per the M7 Convergence prompt, section 7. A small policy function over
EXISTING architecture -- no new orchestration framework.

## What was built

`dv_harness/agent_execution_backend.py::resolve_execution_backend()`:

```
requested_backend, same_task, same_scope, equivalent_task_boundary,
equivalent_safe_tool_profile, equivalent_evidence_contract,
human_authority_decision_required
  -> BackendResolution(requested_backend, selected_backend, backend_status,
                       backend_block_reason, fallback_backend,
                       fallback_authorized, human_action_required)
```

Preference order: the detached Claude worker is always the REQUESTED
backend for Claude remediation. Since it is currently, evidencedly
`IMPLEMENTED_AND_TESTED_BLOCKED_BY_HOST_POLICY` (preserved verbatim from
`L5DGVA_CONTROLLED_CLAUDE_WORKER_PERMISSION_QUALIFICATION.md` -- this
function does not re-investigate that finding, only reacts to it, per the
convergence prompt's own "do not reopen" instruction), the current-session
executor is offered ONLY as an explicit, named FALLBACK -- `selected_
backend` and `requested_backend` are always distinguishable in the result,
so current-session execution can never be silently represented as
detached-worker execution.

The fallback is authorized automatically ONLY when ALL of these hold:
`same_task`, `same_scope`, an equivalent `TaskBoundary`, an equivalent Safe
Tool profile, an equivalent evidence contract, and no Human Authority
decision required. Any one missing condition (or an explicit Human
Authority requirement) routes to `WAITING_FOR_EXECUTION_BACKEND` -- a
named, specific state, never a generic "waiting for user", and never
auto-escalated to `HUMAN_AUTHORITY_REQUIRED` by this function itself (a
caller raises that on its own evidence).

## Retroactive characterization of this M7 program's own real remediation work

Every Claude-remediation action this M7 program has actually performed
(REVIEW-003/004/005/006 findings) went through the SAME real pattern this
function now names explicitly:

| Round | requested_backend | same_task/scope | equivalent TaskBoundary/profile/evidence | human_authority_required | selected_backend |
|---|---|---|---|---|---|
| REVIEW-003/004/005/006 remediation | DETACHED_CLAUDE_WORKER | YES (same repo, same findings-to-fix scope) | YES (same ALLOWED_FILES-shaped scope, same CLAUDE_IMPLEMENTATION_PROFILE-equivalent tool access, same evidence-cite discipline) | NO | CURRENT_SESSION_EXECUTOR (fallback) |

This is not a new claim -- every prior remediation report already disclosed
"performed directly by the orchestrating session" up front. What this
section adds is a real, testable, reusable POLICY FUNCTION that makes that
disclosure a structural fact of the codebase rather than only report prose,
so a future caller (or a future review round) gets a real
`BackendResolution` object instead of re-deriving the same reasoning by
hand each time.

## WORKFLOW_AUTONOMY vs PROCESS_INDEPENDENT_AUTONOMY

```
WORKFLOW_AUTONOMY = OPERATIONAL
```
The WORKFLOW itself (ingest -> validate -> consume -> classify -> next
action -> remediate -> re-handoff) proceeds with zero human scheduling
between real results -- proven live across 4 real round trips this session
and the prior task's own REVIEW-004 auto-ingestion (armed 3 days earlier,
zero manual intervention).

```
PROCESS_INDEPENDENT_AUTONOMY = PARTIAL
```
The REMEDIATION step specifically still executes inside the SAME
orchestrating Claude Code process/session, not a detached, independently-
crashable-and-recoverable worker process -- because that capability is
real, implemented, tested, and host-blocked. This is the honest, disclosed
boundary: the WORKFLOW does not require a human scheduler, but one
specific STEP within it (remediation) is not yet process-independent.

## Verification

`dv_harness_tests/test_agent_execution_backend.py`: 6 new tests --
`test_fallback_authorized_only_when_every_equivalence_condition_holds`,
`test_current_session_execution_is_never_represented_as_detached_worker`,
`test_fallback_refused_on_a_missing_equivalence_condition_routes_to_waiting`,
`test_a_required_human_authority_decision_refuses_automatic_fallback`,
`test_waiting_for_execution_backend_is_never_a_generic_waiting_state`,
`test_unsupported_requested_backend_is_rejected`. All pass, alongside the
full existing 45-test module (no regression).

## Disclosed limits

`resolve_execution_backend()` is a policy/classification function -- it
does not itself LAUNCH anything (real launch still goes through
`launch_worker()`, unchanged) and it does not itself detect the
equivalence conditions (`same_task`, `equivalent_task_boundary`, etc.) from
two real `AgentRunRequest` objects; a caller currently supplies those as
booleans. Building the real comparator (diffing two `AgentRunRequest`/
`TaskBoundary`/profile-name values automatically) was considered and
deferred as a distinct, separable next step, not required to make this
section's own required fields (`REQUESTED_BACKEND`/`SELECTED_BACKEND`/
`BACKEND_STATUS`/`BACKEND_BLOCK_REASON`/`FALLBACK_BACKEND`/
`FALLBACK_AUTHORIZED`/`HUMAN_ACTION_REQUIRED`) real and testable now.
