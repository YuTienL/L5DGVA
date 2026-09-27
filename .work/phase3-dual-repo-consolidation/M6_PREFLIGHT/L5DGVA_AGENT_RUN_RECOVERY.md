# L5DGVA Agent Run Recovery

Code: `dv_harness/agent_execution_backend.py::recover_pending_runs()`.

## Startup recovery flow (exactly the required sequence)

```
LOAD RUNS (scan .dv-harness/agent_runs/*/STATE.json for run_state=RUNNING)
-> RECONCILE PROCESS/LEASE/RESULT (real PID-liveness check per run)
-> INGEST COMPLETED RESULT (RESULT.json exists but was never finalized -> ingest now)
-> RECOVER ACTIVE/FAILED RUN (alive -> report STILL_ACTIVE; dead+no result -> CRASHED, release lease)
-> NEXT ACTION RESOLVER (same table, same function, called for every non-active outcome)
```

## The three real outcomes, each tested

| Scenario | `recovery` value | What happens |
|---|---|---|
| Process still alive | `STILL_ACTIVE` | State left at `RUNNING`; nothing torn down or re-launched (`test_restart_recovers_active_worker_state`) |
| Process dead, `RESULT.json` already written (crashed between worker exit and finalize) | `RESULT_INGESTED_ON_RECOVERY` | State moved to `COMPLETED`; the real `AGENT_RUN_SUCCEEDED`/`AGENT_RUN_FAILED_ESCALATE` event resolved and persisted for the task (`test_restart_recovers_completed_worker`) |
| Process dead, no result at all | `CRASHED_NO_RESULT` | State moved to `CRASHED`; lease released (`MUTATION_LEASE_RELEASED`, reason `CRASH_RECOVERY`); next action resolved to a real retry-eligible or escalate event from `RUN_REQUEST.json`'s own `attempt_number`/`retry_policy_max_attempts` (`test_restart_recovers_a_crashed_worker_with_no_result`) |

Liveness uses the same real, OS-level `_pid_alive()` check the mutation
lease uses -- never a heuristic like "no recent log line" or low CPU
(explicitly forbidden by the requirements doc: "Do not infer hang from low
CPU alone").

## Idempotency interaction

`active_run_for_action()` (the idempotency check `launch_worker()` runs
before every new launch) ALSO uses `_pid_alive()`, so a crashed run's stale
`RUNNING` record never blocks a legitimate retry attempt -- idempotency
protects against a genuinely-active duplicate, recovery is what reconciles
a dead one; they share the same liveness primitive so the two mechanisms
can never disagree about whether a given run is "really still going".

## What was NOT built this task

- No automatic recovery daemon/cron -- `recover_pending_runs()` is a real,
  callable function a caller (a session startup, a watcher-style loop) must
  invoke; nothing currently calls it automatically on process start. Same
  honest `WIRED_NOT_TRIGGERED`-class disclosure as the rest of this
  session's backend work.
- No cross-machine recovery -- `_pid_alive()` only makes sense for a PID on
  the same machine `agent_execution_backend.py` runs on, matching this
  requirement's own single-host worker model (a future distributed backend
  is explicitly out of scope, per "Backend Interface... keep future backend
  extension possible without building unused providers now").

## Status

`AGENT_RUN_RECOVERY=IMPLEMENTED_AND_TESTED` (3 dedicated scenario tests, all
real file-state reconciliation against a throwaway git repo).
