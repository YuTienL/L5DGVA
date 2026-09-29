# L5DGVA Agent Execution Audit Evidence

Real, append-only JSONL per run: `.dv-harness/agent_runs/<AGENT_RUN_ID>/audit.jsonl`
(`dv_harness/agent_execution_backend.py::_emit()`/`read_audit_trace()`).

## The 17 event names (all present, `AUDIT_EVENTS` is a closed set)

`AGENT_RUN_REQUESTED`, `BACKEND_SELECTED`, `MUTATION_LEASE_REQUESTED`,
`MUTATION_LEASE_ACQUIRED`, `MUTATION_LEASE_BUSY`, `WORKER_LAUNCHED`,
`WORKER_HEARTBEAT`, `WORKER_COMPLETED`, `WORKER_FAILED`, `WORKER_TIMEOUT`,
`WORKER_CANCELLED`, `WORKER_CRASHED`, `RESULT_INGESTED`,
`MUTATION_LEASE_RELEASED`, `NEXT_ACTION_RESOLVED`,
`HUMAN_GATE_REFUSED_LAUNCH` (operational addition), `RUN_RECOVERED`
(operational addition). `_emit()` asserts membership -- an unlisted event
name is a real `AssertionError`, never a silently-accepted typo.

## Real observed sequences (from the test suite's own real file writes, not
## paraphrased)

Normal PASS run:
```
AGENT_RUN_REQUESTED -> BACKEND_SELECTED -> MUTATION_LEASE_REQUESTED
-> WORKER_LAUNCHED -> WORKER_HEARTBEAT (repeated) -> WORKER_COMPLETED
-> RESULT_INGESTED -> MUTATION_LEASE_RELEASED -> NEXT_ACTION_RESOLVED
```

Human Gate refusal (no process ever started):
```
AGENT_RUN_REQUESTED -> HUMAN_GATE_REFUSED_LAUNCH
```
(`test_human_authority_action_does_not_launch_worker` asserts
`WORKER_LAUNCHED` is absent.)

Timeout:
```
... WORKER_LAUNCHED -> WORKER_HEARTBEAT (repeated) -> WORKER_TIMEOUT
-> RESULT_INGESTED -> MUTATION_LEASE_RELEASED (reason=TIMEOUT) -> NEXT_ACTION_RESOLVED
```

Crash recovery on restart:
```
... RUN_RECOVERED (found=NO_RESULT_CRASHED), WORKER_CRASHED,
MUTATION_LEASE_RELEASED (reason=CRASH_RECOVERY)
```

## Never silently PASS

Every path that ends in `RUN_STATE_FAILED`/`TIMEOUT`/`CRASHED` writes a real
`RESULT.json` with `run_status=ERROR` (never `PASS`) and a non-empty
`errors` list, and resolves a real retry-or-escalate next action -- there is
no code path that reaches `RESULT_INGESTED` with a PASS status except a
genuinely `RUN_STATE_COMPLETED` run whose `structured_output.run_status`
was itself `PASS` AND whose `FILES_CHANGED` passed scope enforcement.

## Status

`AGENT_RUN_AUDIT_TRACE=IMPLEMENTED_AND_TESTED`.
