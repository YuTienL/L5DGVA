# L5DGVA Canonical Mutation Lease

Code: `dv_harness/agent_execution_backend.py::acquire_mutation_lease()`,
`heartbeat_lease()`, `release_mutation_lease()`, `lease_state()`.

## Why not `model_handoff_workflow._acquire_lock()`

That primitive (used for the M7 import lock) breaks a stale lock purely on
file mtime elapsed time. This requirement explicitly forbids that for a
mutation lease ("Do not break a lease merely by elapsed time; require
liveness evidence"). This is a deliberate, disclosed non-reuse: the O_EXCL
creation IDEA is the same lineage, the STALENESS POLICY is a real,
independent reimplementation.

## Design

One repo-wide record, `.dv-harness/agent_runs/mutation_lease.json`:

```
LEASE_ID, AGENT_RUN_ID, TASK_ID, OWNER_PID, ACQUIRED_AT,
LAST_HEARTBEAT_EPOCH, LEASE_SCOPE, STATE (HELD/RELEASED)
```

`acquire_mutation_lease()`:
1. No record, or `STATE=RELEASED` -> acquire immediately.
2. `STATE=HELD` -> recover ONLY if **both**: `now - last_heartbeat_epoch >
   liveness_grace_seconds` (default 90s) **and** `_pid_alive(owner_pid)`
   is False (a real OS-level liveness check: `OpenProcess` on Windows,
   `os.kill(pid, 0)` on POSIX). Either condition alone is insufficient --
   confirmed by two negative tests: a stale heartbeat with a live owner is
   NOT recovered (`test_stale_heartbeat_alone_is_not_enough_to_break_the_lease`);
   a live owner within the grace window is NOT recovered even when asked
   again immediately (`test_live_owner_within_grace_is_never_broken`).
3. Recovery is audited (`MUTATION_LEASE_ACQUIRED` with
   `recovered_from`/`recovery_reason=STALE_HEARTBEAT_AND_DEAD_OWNER`), never
   silent.

`monitor_and_ingest()` calls `heartbeat_lease()` on every poll tick while
the worker runs, so a genuinely-alive worker's lease never goes stale under
its own operation; the lease is only ever a signal about an ABANDONED
holder, never about a slow-but-alive one.

## Read-only parallelism

`launch_worker()` skips the entire lease path when
`request.mutation_allowed=False` -- read-only/review actions never request,
acquire, or block on the lease (`test_read_only_worker_does_not_require_mutation_lease`).
Task Boundary / tool policy still apply regardless.

## Second worker collision

`test_second_mutation_worker_cannot_acquire_same_lease`: a second
mutation-capable request while the lease is held returns
`{"launched": false, "refusal": "LEASE_BUSY", "owner_agent_run_id": ...}`
-- no queueing infrastructure was built this task (the requirements doc's
own "wait/queue/block by policy" is satisfied minimally as an immediate,
real, honest refusal the Next Action Resolver can act on, not a silent
drop); a caller wanting a queue can retry the same request later.

## Interactive Claude coexistence (honest limitation, disclosed per section 10)

A manually-opened, interactive Claude Code session is NOT a participant in
this lease -- it has no way to acquire or be blocked by
`mutation_lease.json`, because it is not code this project controls. The
requirement's own text anticipates exactly this ("Document the current
limitation if manual sessions cannot participate directly in the lease. Do
not overclaim protection."): **this lease protects only autonomous
mutation workers launched through `agent_execution_backend.py` against
EACH OTHER.** It does not, and structurally cannot, prevent a human's own
manually-opened Claude session from editing the same files concurrently.
No dirty-working-tree collision detector beyond `git status` itself was
built this task; a future extension could check `git status --porcelain`
before launch and refuse on unexpected dirty state, but that was not
implemented here and is not claimed.

## Status

`CANONICAL_MUTATION_LEASE=IMPLEMENTED_AND_TESTED` (6 dedicated tests: normal
acquire/heartbeat/release, second-worker-busy, stale+dead recovery,
stale-alone-insufficient, live-within-grace-insufficient).
