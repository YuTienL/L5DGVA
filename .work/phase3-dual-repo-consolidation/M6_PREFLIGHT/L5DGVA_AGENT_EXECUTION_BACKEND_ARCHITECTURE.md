# L5DGVA Agent Execution Backend Architecture

Code: `dv_harness/agent_execution_backend.py`, `dv_harness/safe_tool_profile.py`.

## Canonical loop (as implemented, no second engine)

```
Result -> Validate/Consume (model_handoff_workflow.import_result, unchanged)
       -> Next Action Resolver (execution_contract.resolve_next_action, SAME table, new events)
       -> ACTION_REQUIRES_AGENT? (caller decides from the resolved next_action)
            NO  -> existing executor / HumanGate / transport (unchanged)
            YES -> build_agent_run_request()
                -> launch_worker()            [Human Gate check, idempotency check, mutation lease]
                -> real `claude` subprocess (Controlled Claude Worker)
                -> monitor_and_ingest()        [timeout, classify, scope-enforce, ingest, release lease]
                -> execution_contract.resolve_next_action(AGENT_RUN_*)
                -> (loops back to the SAME Next Action Resolver)
```

## Reuse-before-create inventory (as required)

| Component | Classification | What |
|---|---|---|
| Next Action Resolver | REUSE | `execution_contract.resolve_next_action()` -- 6 new `AGENT_RUN_*` events added to the SAME `NEXT_ACTION_TABLE`, no second resolver |
| Task Boundary | REUSE | `task_boundary_conformance.TaskBoundary`/`classify_path()` -- `AgentRunRequest.task_scope` IS a real `TaskBoundary`; `enforce_worker_scope()` re-classifies the worker's own claimed `FILES_CHANGED` against it plus `frozen_sources` |
| Lifecycle/checkpoint state persistence | REUSE (pattern) | Same per-entity JSON + append-only JSONL convention as `model_handoff_workflow.py`/`result_ingestion.py` (`STATE.json`, `RUN_REQUEST.json`, `RESULT.json`, `audit.jsonl`) |
| Lock primitive (O_EXCL) | ADAPT, not REUSE | The creation call is the same idea as `model_handoff_workflow._acquire_lock()`, but the STALENESS POLICY is deliberately different and reimplemented: `_acquire_lock()` breaks a stale lock on elapsed time alone, which the Canonical Mutation Lease requirement explicitly forbids ("do not break merely by elapsed time; require liveness evidence") |
| Preauthorized Safe Tool Execution | MISSING -> BUILT | No such mechanism existed anywhere in the repo (`grep` found none) before `safe_tool_profile.py` |
| Subprocess/process runner | MISSING -> BUILT | No existing "launch and monitor an external CLI worker" mechanism existed; `remote_exec.py`/`remote_relay.py` (the `v1` migration track's own remote-Linux-execution bridge) is a DIFFERENT concern (an SSH relay to a Linux DV server) and was not reused or modified |
| Multi-agent orchestration | NOT REUSED (documented why) | `dv_harness/multi_agent.py`'s `MultiAgentOrchestrator`/`AgentTaskStore` delegates ONE LLM call inside THIS harness's own `engine.py.run_stage()`, and its `acquire()` claims are INTRA-PROCESS blackboard-topic locks for parallel fan-out branches of one process -- not a subprocess-launching mechanism and not a repo-wide mutation lease; a different resource entirely |
| Worktree isolation | DEFERRED per requirements | "Dedicated worker worktrees are a future/optional extension... first operational backend requires a strong single Canonical mutation lease" -- not built this task |

## Agent Run Request / Result

`AgentRunRequest` (frozen dataclass) carries every required logical field
(`AGENT_RUN_ID` .. `RESUME_CONTRACT`); `to_dict()` is the persisted
`RUN_REQUEST.json` shape. `build_agent_run_request()` derives
`CURRENT_HEAD` from real `git rev-parse HEAD` (never a caller-supplied
literal) and `AGENT_RUN_ID` from a real UUID4, matching the Minimum
Sufficient Context discipline `model_handoff.build_handoff()` already
established (never a full chat-history or governance-corpus dump; see
`context_size_bytes()`).

`AgentRunResult` mirrors the worker's own structured output
(`RUN_STATUS`, `FILES_CHANGED`, `TESTS_RUN`, `REGRESSION_RESULTS`,
`EVIDENCE_REFS`, `GAPS_FOUND`, `GAPS_FIXED`, `HUMAN_DECISIONS_REQUIRED`,
`NEXT_ACTION_HINT` advisory only, `ERRORS`) plus identity fields
(`AGENT_RUN_ID`/`TASK_ID`/`ACTION_ID`/`START_HEAD`/`END_HEAD`) this module
fills in itself, never trusting the worker for its own identity.

## Persistence layout

```
.dv-harness/agent_runs/
  mutation_lease.json                 (the ONE repo-wide lease record)
  <AGENT_RUN_ID>/
    RUN_REQUEST.json
    STATE.json          (run_state, pid, lease_id, start/end time, exit_code)
    stdout.log / stderr.log
    RESULT.json
    audit.jsonl          (append-only, the 17 AUDIT_EVENTS)
```

Matches the requirements doc's own recommended convention exactly. No
secrets are ever written (the worker's own auth is the ambient `claude.ai`
session; nothing about it is captured into these files).

## Human Gates

`AgentRunRequest.blocking_human_gate()` checks `human_authority_constraints`
against the 7 named categories verbatim
(`HUMAN_DECISION_REQUIRED`/`DESIGN_AUTHORITY_REQUIRED`/
`VERIFICATION_AUTHORITY_REQUIRED`/`VERIFICATION_SIGNOFF_REQUIRED`/
`ARCHITECTURE_AUTHORITY_REQUIRED`/`SECURITY_SCOPE_EXPANSION`/
`ACCESS_AUTHORIZATION_REQUIRED`); `launch_worker()` refuses (never queues,
never asks a generic question) and emits `HUMAN_GATE_REFUSED_LAUNCH`
before any process is started.

## Status

`AUTONOMOUS_AGENT_EXECUTION_BACKEND=IMPLEMENTED_AND_TESTED`;
`PRODUCTION_CALL_SITE_WIRING=NOT_YET_WIRED` for the automatic
"Next-Action-says-agent-required -> caller builds+launches a request"
step -- that decision (which resolved next actions actually require an
agent, versus routine local test/regression the working session already
performs directly) is left to the orchestrating caller for now, same
honest status this project has recorded for every prior "wired into the
table, not yet an automatic trigger" capability this session built
(`result_action_router.py`, the Human Non-Scheduler contract's own
`can_i_stop()`). See `M7_CLAUDE_WORKER_LIVE_QUALIFICATION.md` for why no
live M7-triggered run occurred this task (REVIEW-004 has not returned).
