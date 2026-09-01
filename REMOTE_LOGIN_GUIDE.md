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

## Architecture: Claude Code always runs on your PC, never on the Linux server

Claude Code (the `claude` CLI) is a **PC-side (Windows client) process** —
this whole harness's design assumption is that it is never installed or
run on the Linux DV server itself. "Using Claude Code to operate the
shared `/home/svcacct/AI/Agent` deployment" does not mean SSH-ing in and
running `claude` there; it means Claude Code runs locally on your machine,
and reaches the Linux server *only* through the persistent-relay bridge
described in this page, for the two things Linux is actually needed for:
real execution (VCS/Verdi/LSF/`git`) and the shared Knowledge Center. This
is exactly why `tools/remote/` exists at all — if the intended usage were
"run Claude Code directly on the Linux box," none of this relay machinery
would be necessary.

## Onboarding a new PC user onto the shared `/home/svcacct/AI/Agent` deployment

1. **Get the harness code locally.** `git clone`/checkout this same
   repository onto your own PC (or pull the same `v50` tree the shared
   deployment was built from). Run `dv-harness`/Claude Code from *this
   local copy* — never by SSH-ing into the server and trying to drive it
   from there.
2. **Pick your own `--project-root`.** Never point it at
   `/home/svcacct/AI/Agent` (that's a Linux-side path unrelated to where
   your local `dv-harness` process runs, and even if reachable it is
   shared code, not a place for your own `.dv-harness/` runtime state —
   see `USAGE_MULTI_USER_SAFETY.md`). Use your own local directory, e.g.
   `dv-harness --project-root D:\DV\<your-project> status`.
3. **Start your own relay**, from your own terminal, with your own
   account — `VCUSER` must be **your own** real Linux login, never the
   shared `svcacct` service account (see "The permission model" below for
   why: `VCUSER` is a real login, and `svcacct` has no reason to have
   access to your own home-directory tree):
   ```
   VCUSER=<your-account> VCPW=<your-password> VCHOST=vchost-b VCHOP=host-c \
     VCWORKDIR=/home/tmpacct/<your-account>/UVM/<your-project> \
     python tools/remote/remote_relay.py --start
   ```
   Every real SSH login is independent even under a shared `vchost`/`vchop`
   pair — starting your own relay does not contend with anyone else's (see
   `USAGE_MULTI_USER_SAFETY.md`'s "prefer one relay per user" guidance).
   `VCWORKDIR` may point at the shared `/home/svcacct/AI/Agent` code tree
   instead if this relay is dedicated to reading/syncing the shared engine
   (everyone reading that shared code is safe) — but for your own debug
   work, point it at your own deployment path as shown above.
4. **Point the Knowledge Center at the shared store** (one-time, per your
   local `.dv-harness/config.json`):
   ```
   dv-harness knowledge setup --remote-root /home/svcacct/AI/DB
   ```
5. **Set your own `DVWORKDIR`** to *your own* generated verification
   environment's deployment path — never the shared code tree:
   ```
   export DVWORKDIR=/home/tmpacct/<you>/UVM/<your-project>
   ```
6. **Drive the harness normally from your PC** — `dv-harness --project-root
   <yours> start --goal "..."` or the chat-layer `CREATE ENVIRONMENT` /
   `dv-harness` commands from `START_HERE.md`. Whenever a stage needs real
   Linux-side work, Claude Code calls `remote_exec.py` against *your own*
   relay, using your `DVWORKDIR` automatically.

**Common mistakes to avoid**: sharing a `--project-root` with anyone else;
sharing one relay across multiple people's concurrent work instead of each
starting their own; deploying your generated environment's output files
into `/home/svcacct/AI/Agent` instead of your own `DVWORKDIR` path.

## The permission model: `VCUSER` is a real Linux login, not a label

`remote_relay.py` performs a **real** `telnet`+`ssh` login as `VCUSER`.
Every command `remote_exec.py` sends afterward — including anything
touching `DVWORKDIR` — executes on the real Linux server **as that same
Unix account**, subject to normal Unix file permissions. There is no
separate access-control layer the harness adds or can bypass; whatever
`VCUSER` cannot read/write directly at a shell prompt, the relay cannot
read/write either.

This matters concretely: `/home/svcacct/AI/Agent` and `/home/svcacct/AI/DB`
are reachable using the shared `svcacct` service account because they are
*that account's own* directories (or made group/world-readable for the
shared deployment). A DE's own generated environment
(`DVWORKDIR=/home/tmpacct/<de-account>/UVM/<project>`) is a **different**
account's home-directory tree — normal Unix defaults do **not** grant
`svcacct` (or any other account) access to it. Concretely:

- **Debugging your own environment**: start your relay with `VCUSER=` your
  own account (not `svcacct`) — then `DVWORKDIR` pointing at your own
  `/home/.../<you>/...` path just works, no permission issue, because
  you're accessing your own files as yourself.
- **Debugging *someone else's* environment** (e.g. a DE asks for help on a
  failure in their own deployment): the relay must log in as an account
  that actually has access to that path. Real options, in order of
  preference:
  1. The other DE grants read/write access to your account on their
     environment's directory (POSIX group permissions or `setfacl`) — a
     real sysadmin action on the Linux server, not something this harness
     configures or should try to route around.
  2. You obtain and use that DE's own credentials for this session's relay
     (only if you are actually authorized to act as them — this still
     goes through the same SSH/Remote Transport Connection Intake gate,
     asking for that account's own credentials).
  3. The DE copies/hands off the specific files you need into a location
     your account can already reach (e.g. a shared scratch directory both
     accounts can access).
- **Never** try to work around a `Permission denied` by switching the
  relay to a more-privileged shared account "just to make it work" — that
  defeats the whole point of per-user accountability this harness's
  multi-user model depends on (see `USAGE_MULTI_USER_SAFETY.md`).

A `Permission denied` from any `remote_exec.py` command surfaces as
ordinary command output (real shell stderr text, same as any other command
failure) — there is no separate/hidden failure mode to worry about, just
apply the model above to diagnose which account needs which access.

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

**Setting `VCWORKDIR` and `DVWORKDIR` to the same path is supported and is
the recommended pattern for a relay dedicated to one environment** — they
are read by two different scripts with no cross-check between them, so
there is nothing to reconcile. Pointing both at
`/home/tmpacct/devuser/UVM/USB`, for example, means the relay already
starts there (`VCWORKDIR`) *and* every `remote_exec.py` call redundantly
re-confirms that cwd per request (`DVWORKDIR`) — `cd` into the directory
you're already in is a normal no-op in both bash and tcsh, so this only
adds safety (protection against cwd drift from an earlier command) with no
downside. Proven by
`test_run_op_cwd_equal_to_relays_own_startup_workdir_is_a_safe_noop` in
`dv_harness_tests/test_remote_relay.py`.

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
