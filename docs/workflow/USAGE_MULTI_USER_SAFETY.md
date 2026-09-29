> See START_HERE.md for the canonical entry point. This page is the single
> place that answers "is it safe for multiple people to use
> `/home/svcacct/AI/Agent` at the same time?" — it exists because that
> question was asked directly (2026-09-02) and deserved a durable,
> evidence-grounded answer rather than a one-off chat reply.

# AI Agent Harness L5 — Multi-User Safety on the Shared Deployment

The full system is deployed once, shared, at:

```
/home/svcacct/AI/Agent      (code + engine — the harness itself)
/home/svcacct/AI/DB         (Knowledge Center — shared memory)
```

Both paths were confirmed and 固化 (solidified) as standing policy this
session: every harness update must sync to `/home/svcacct/AI/Agent`, and
every confirmed gap/lesson must be distilled into a permanent
skill/capability and written back to `/home/svcacct/AI/DB`.

Multiple people using this deployment concurrently is **safe in some parts
and unsafe in others** — this page is the honest breakdown, verified from
the actual source (`tools/knowledge_center/broker.py`,
`tools/remote/remote_relay.py`, `dv_harness/memory.py`,
`dv_harness/blackboard.py`), not assumed.

## The three layers, and their real concurrency safety

| Layer | Path | Safe for concurrent multi-user access? | Why |
|---|---|---|---|
| **Knowledge Center** | `/home/svcacct/AI/DB` | **Yes** | `broker.py`'s `_ShardLock` (`fcntl.flock(LOCK_EX)` per `<category>__<protocol>` shard) + `_atomic_write_json()` (`os.replace()`). See `docs/knowledge/KNOWLEDGE_CENTER_GUIDE.md`. |
| **Persistent relay** (per `vchost`/`vchop` pair) | one shared shell, reached via `remote_exec.py` | **Command execution: yes** (fixed 2026-09-02). **Shared shell state (cwd/env/`module load`): no, unless every caller uses `--cwd`** | `RelayServer.handle_request` now holds a lock (no interleaving); the underlying shell is still one continuous process whose `cd`/env changes persist across callers. See `docs/remote/REMOTE_LOGIN_GUIDE.md`. |
| **`.dv-harness/` runtime state** (per project — `state.json`, `blackboard/`, `react/`, `memory/`, `events.jsonl`, `control.json`) | wherever `--project-root` points | **No** | Plain read-modify-write, no locking at all — a real lost-update race for two concurrent writers on the same `--project-root`. This is *by design* the opposite of the Knowledge Center's design (see `dv_harness/memory.py`/`blackboard.py`'s own docstrings, which exist precisely because `broker.py` closes the class of bug they don't). |

## The concrete rule

- **Share the code tree.** `/home/svcacct/AI/Agent` as a checked-out copy of
  the harness engine is fine for everyone to read from and run
  `dv-harness`/`remote_exec.py` against.
- **Share the Knowledge Center.** Everyone's `knowledge_center.remote_root`
  should point at the same `/home/svcacct/AI/DB` — that's the whole point
  of it, and it's genuinely safe.
- **Never share a `--project-root`.** Each user must drive `dv-harness`
  against their **own** runtime-state directory:
  ```
  dv-harness --project-root /home/<your-account>/<your-own-project-copy> status
  dv-harness --project-root /home/<your-account>/<your-own-project-copy> start --goal "..."
  ```
  Two people both running `dv-harness` with the default `--project-root .`
  inside the same shared `/home/svcacct/AI/Agent` checkout **will** corrupt
  each other's `state.json`/`blackboard/`/`events.jsonl` — there is no lock
  protecting that path, unlike the Knowledge Center.
- **Never deploy your generated VIP verification environment into the
  shared code tree.** The engine (`/home/svcacct/AI/Agent`) and the
  Knowledge Center (`/home/svcacct/AI/DB`) are the only two things meant to
  be shared. The actual generated deliverable (e.g. a USB VIP-based UVM
  environment) is a per-project artifact and belongs at its own dedicated
  path (e.g. `/home/tmpacct/devuser/UVM/USB`) — set your own `DVWORKDIR`
  env var to that path so every `remote_exec.py` call defaults into it
  automatically without needing `--cwd` on every invocation:
  ```
  export DVWORKDIR=/home/tmpacct/devuser/UVM/USB
  python tools/remote/remote_exec.py "make WAVE=1"
  ```
  This is a third, separate concept from `VCWORKDIR` (the relay's own
  shared shell cwd) and `--project-root` (the harness's own runtime-state
  location) — see `docs/remote/REMOTE_LOGIN_GUIDE.md`'s three-way comparison table.
- **Prefer one relay per user.** A relay started from your own machine
  (`%LOCALAPPDATA%` is already per-Windows-account) gives you your own real
  SSH login on the server with zero contention. If a relay genuinely must
  be shared (e.g. one long-lived automation account), the 2026-09-02 fix
  makes command *execution* safe (no interleaving) but shared shell *state*
  is still one global value — pass `--cwd` on every `remote_exec.py` call
  in that scenario (see `docs/remote/REMOTE_LOGIN_GUIDE.md`).

## What changed 2026-09-02 (this fix)

Prompted by the concern: *"一組 relay = 一個真實的 telnet+ssh session,多人
共用同一組帳號/主機會讓指令互相插隊"* (one relay is one real shell;
multiple people sharing it could make commands cut in line).

1. `RelayServer.handle_request()` (`tools/remote/remote_relay.py`) now
   holds a `threading.Lock()` for its full body — command execution against
   the shared session is now a self-enforced invariant of the class, not an
   accident of `serve()`'s current single-threaded shape. Proven by a new
   concurrency test that fires 6 threads at once against a slowed fake
   session and asserts zero time-overlap between any two `run()` calls.
2. `bind_loopback()`'s listen backlog raised from `1` to `32`
   (`DEFAULT_LISTEN_BACKLOG`) — several callers connecting at nearly the
   same instant now queue instead of some being refused outright.
3. `run` requests accept an optional `cwd` field, composed server-side into
   a non-leaking `(cd '<dir>' && <cmd>)` subshell — the actual mechanism of
   harm this session hit live (a `module load`/`cd` from one command
   silently affecting a later, unrelated command) is now avoidable per
   request instead of being an unavoidable property of sharing one shell.
   Exposed client-side as `remote_exec.py --cwd`.
4. `DEFAULT_IDLE_TIMEOUT` raised from 2h to 24h — a shared relay dying from
   idle forces a full re-login for every current user of it, not just
   whoever triggered the check.
5. `remote_exec.py` reads a `DVWORKDIR` env var as a default `--cwd` so a
   user doesn't have to repeat `--cwd` on every call — set once per
   terminal session to that user's own generated environment's deployment
   path (e.g. `/home/tmpacct/devuser/UVM/USB`). An explicit `--cwd` still
   overrides it.
6. A separate, pre-existing bug surfaced live while verifying this fix
   against the real deployment: `Session.put()`
   (`tools/remote/remote_hop.py`) used a generic prompt regex to detect
   when its rapid-fire base64 chunk-upload had finished — a real tcsh
   redraws its prompt after every single command, so that pattern could
   match after just the first of many chunks, corrupting the next
   command's own output capture. Fixed by switching to the same
   unique-marker completion-detection technique `run()` already used.
   Proven with a real socket-backed fake-tcsh-server test
   (`dv_harness_tests/test_remote_hop.py`) that deliberately redraws a
   prompt after every chunk.

Regression tests: `dv_harness_tests/test_remote_relay.py` (new tests under
the "Multi-user concurrency safety (2026-09-02)" section),
`dv_harness_tests/test_remote_exec.py` (DVWORKDIR tests),
`dv_harness_tests/test_remote_hop.py` (new file, put() flush-marker fix).

## What is still an open, unavoidable limitation

Serializing command *execution* does not turn one shared shell into N
isolated shells. If two users need genuinely independent, simultaneous
long-running remote sessions (e.g. two different multi-hour regressions
each needing their own live shell state), the correct answer is **two
relays** (two separate `remote_relay.py --start` invocations, naturally
possible since each real SSH login to the server is independent), not one
relay serving both. This page's "prefer one relay per user" rule above is
the practical resolution, not a code-level guarantee — nothing forces two
people to actually start separate relays.
