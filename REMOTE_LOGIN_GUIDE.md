> See START_HERE.md for the canonical entry point and current mechanism overview; this page covers connecting to the Linux DV server specifically.

# AI Agent Harness L5 — Remote Login Guide

Real Linux execution (VCS/Verdi/LSF/`git`/the Knowledge Center broker) goes
through a **persistent relay**: one real `telnet(VCHOST) -> ssh(VCHOP) ->
cd(VCWORKDIR) -> source(VCEDAENV)` login, kept alive behind a
loopback-only TCP socket, so Claude doesn't have to re-authenticate (or
ever see the password) on every command. The three scripts involved live in
`tools/remote/` within this `v50` project:

| Script | Runs where | Ever sees `VCPW`? |
|---|---|---|
| `remote_relay.py` | **Your own interactive terminal only** — never a Claude Code tool call (see CLAUDE.md's "Remote Linux Execution" section, real 2026-08-31 incident precedent) | Yes, once, at login |
| `remote_exec.py` | Invoked by Claude via tool calls | **Never** |
| `remote_hop.py` | Library used by `remote_relay.py`'s login handshake; not run standalone | Yes (imported, not invoked directly) |

## Starting a relay

In your own terminal (never paste this into a Claude Code tool call):

```
VCUSER=<account> VCPW=<password> VCHOST=vchost-b VCHOP=host-c \
  VCWORKDIR=/home/svcacct/AI/Agent \
  python tools/remote/remote_relay.py --start
```

- `VCWORKDIR` — see "VCWORKDIR vs. `--project-root`" below; do not confuse
  the two.
- Idle timeout defaults to 24h (`DEFAULT_IDLE_TIMEOUT`, `remote_relay.py`
  — raised 2026-09-02 from 2h specifically because a shared, multi-user
  relay dying from idle forces a full re-login for *everyone* currently
  using it, not just whoever happened to trigger the idle check).
- The relay writes its connection info (loopback host/port/token, never the
  password) to `%LOCALAPPDATA%/dv_agent_harness/relay/<vchost>-<vchop>.json`
  on **your own machine** — this is per-Windows-user by construction
  (`%LOCALAPPDATA%` is a per-OS-account path), so two different engineers
  on two different machines each starting their own relay never collide on
  this file even if they happen to use the same `vchost`/`vchop` pair.

## Issuing commands (Claude-side, once a relay is READY)

```
python tools/remote/remote_exec.py --status
python tools/remote/remote_exec.py "pwd"
python tools/remote/remote_exec.py --cwd /home/svcacct/AI/Agent "git log -1"
python tools/remote/remote_exec.py --put local_file remote_file
python tools/remote/remote_exec.py --get remote_file local_file
python tools/remote/remote_exec.py --reconnect
```

If `--status` reports `DOWN`, run `--reconnect`; if that fails (relay
cannot self-reauthenticate — it has no password in this process), ask the
user to restart it in their own terminal per "Starting a relay" above.
Never attempt to start/restart `remote_relay.py` from a tool call yourself.

## `VCWORKDIR` vs. `--project-root` vs. `DVWORKDIR` — three different things

| | `VCWORKDIR` | `--project-root` | `DVWORKDIR` |
|---|---|---|---|
| Which machine | The **Linux server**, inside the relay's one persistent shell | Wherever `dv-harness` (the Python engine) is actually invoked from — typically your local Windows client | Read locally by `remote_exec.py` (the client) |
| What it controls | The relay's own default cwd, set **once at relay startup** | Which project's `.dv-harness/` **runtime state** (`state.json`, `blackboard/`, `react/`, `memory/`, `events.jsonl`, ...) `DVHarness` reads and writes (`dv_harness/cli.py:92`, `DVHarness.__init__`) | A **per-terminal/per-session default `--cwd`** — e.g. the Linux-server-side deployment path of the specific VIP-based verification environment you're working on (`/home/tmpacct/devuser/UVM/USB`) |
| Set how often | Once, when the relay is started | Once per `dv-harness` invocation (or exported once per shell) | Once per terminal session (env var), applied to every `remote_exec.py` call automatically |
| Shared safely across users? | The code tree it points at (e.g. `/home/svcacct/AI/Agent`) can be read by everyone — but the *cwd itself* is one shared mutable value for the whole relay, see the state-leakage note below | **No** — see `USAGE_MULTI_USER_SAFETY.md`; each user needs their own | Yes — it's per-caller/per-terminal, never persisted into the shared relay's own state (composed into the same non-leaking `(cd '<dir>' && <cmd>)` subshell as an explicit `--cwd` would be) |

They are unrelated to each other by design — you can point `VCWORKDIR` at
the shared deployment while every user still runs `dv-harness` with their
own separate `--project-root`, and sets their own `DVWORKDIR` to their own
generated environment's deployment path:

```
export DVWORKDIR=/home/tmpacct/devuser/UVM/USB
python tools/remote/remote_exec.py "make WAVE=1"   # runs in DVWORKDIR automatically
python tools/remote/remote_exec.py --cwd /tmp "ls" # an explicit --cwd still wins over DVWORKDIR
```

### Per-request state leakage — use `--cwd`, not a standing `cd`

The relay is **one continuous shell**, not a fresh one per `remote_exec.py`
call — a bare `cd` or `module load` issued by one command silently persists
into whatever command runs next through that same relay, even from an
unrelated caller (confirmed live this session: a `module load python/3.12`
issued mid-session caused a later, unrelated `pytest` invocation to
silently run under the wrong interpreter and fail with
`No module named pytest`). If this relay may ever be shared by more than
one logical stream of work:

- Pass `--cwd <dir>` on every `remote_exec.py` call instead of relying on a
  prior command's `cd` (implemented 2026-09-02: composes a non-leaking
  `(cd '<dir>' && <cmd>)` subshell server-side, see `remote_relay.py`'s
  `RelayServer.handle_request` `run` op — the subshell's `cd` never affects
  the outer shell's cwd for the next caller).
  ```
  python tools/remote/remote_exec.py --cwd /home/svcacct/AI/Agent "pwd"
  ```
- Prefer a command's full binary path (e.g. `/usr/local/bin/pytest`) over
  relying on a prior `module load` having put the right interpreter on
  `PATH`.

## Multi-user concurrency safety (verified, not assumed)

- **Command interleaving** — fixed 2026-09-02. `RelayServer.handle_request`
  now holds a `threading.Lock` for its entire body, so exactly one command
  ever executes against the shared session at a time regardless of how many
  callers hit the relay concurrently (proven by
  `test_handle_request_serializes_concurrent_callers_no_interleaving` in
  `dv_harness_tests/test_remote_relay.py`, which drives 6 concurrent
  callers against a slowed fake session and asserts zero overlap). The
  listen backlog was also raised from 1 to 32
  (`DEFAULT_LISTEN_BACKLOG`) so several callers connecting at nearly the
  same instant queue instead of being refused outright.
- **Shared shell state** (cwd, env, loaded modules) is *not* isolated
  between callers by the lock above — that's a different problem, solved
  per-request with `--cwd` (see above), not by serialization.
- **Best practice**: prefer each engineer running their **own** relay from
  their own machine (natural isolation — separate `%LOCALAPPDATA%`,
  separate real SSH login on the server, zero contention) over deliberately
  sharing one relay process across multiple people. Share a relay only when
  there's a real reason to (e.g. one long-lived automation account), and if
  you do, always pass `--cwd`.

See `USAGE_MULTI_USER_SAFETY.md` for the full picture across the whole
deployment (Knowledge Center + relay + `.dv-harness/` runtime state
together).
