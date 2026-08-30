# Persistent Remote Relay + `remote_exec.py` — Design

Status: approved for implementation planning (2026-08-30)
Owner: peter.lin / yutien.lin01@gmail.com

## 1. Problem

`remote_hop.py` (project root, mirrored into `PACKAGE/`) drives a two-hop
`telnet <vc-host>` → `ssh <ssh-hop>` session and runs commands one shell
invocation at a time. Every invocation re-does the full login handshake,
which is slow and, more importantly, requires `VCPW` to be present in the
environment of whatever process invokes it.

`remote_hop.py`'s own docstring — and a documented real incident in
`.claude/skills/CORE/remote-linux-execution-bridge/SKILL.md` — establish
that this must never be a Claude Code tool call: a password composed into
literal command text submitted for tool-call approval gets persisted into
`.claude/settings.local.json` by Claude Code's own approval history
(observed ~967 times in one prior project). So today, every single Linux
command in a REMOTE_EXECUTION workflow requires the human to run it by hand
in their own terminal and paste the output back — even read-only commands
like `pwd` or `git status` that carry no password risk of their own once a
session is already authenticated.

Separately, real evidence gathered during this same design's `ENV_CHECK`
(2026-08-30) confirmed the actual target working directory
(`/home/svcacct/DV/temp/USB` on `host-b`) has **no git repository at all** —
it is an empty directory. This project's PC↔Linux handoff for this
workdir is not, in practice, git-based today, which motivates §4 below.

## 2. Goal

Let Claude issue individual Linux commands directly (`python remote_exec.py
"<command>"`) once a human has established one authenticated session per
work session, without `VCPW` ever being visible to, or usable by, a Claude
Code tool call at any point after that initial handshake.

This is strictly a transport optimization. It does not change, remove, or
weaken any existing governance:

- **SSH/Remote Transport Connection Intake** (`CLAUDE.md`): still asked
  once per session, before a relay is (re)established. Claude still never
  assumes or silently attempts a connection.
- **Execution Mode Gate**: still declared/re-declared as today.
- **Waveform Dump User Gate**, **PC=edit / Linux=execute split**, **no
  foreground long-running jobs** (1800s ceiling → `nohup ... &` + poll),
  **tcsh `$status` not `$?`**: all carried over unchanged from
  `remote-linux-execution-bridge` / `remote-executor` / `remote-environment`.
- **Source Identity Verification**: kept as a hard requirement (CLAUDE.md's
  "Same regression batch must use the same source/build/config identity"),
  but re-based on content hashing instead of git, per explicit user
  decision — see §4.

What changes: within an already-established, already-confirmed session,
Claude no longer asks the human to manually run each individual Linux
command and paste back output. It calls `remote_exec.py` directly. (Per
explicit user decision during design: automation is scoped to this
single-command round trip only — the per-session establishment confirmation
is not removed.)

## 3. Non-goals

- Does not build a new parallel execution-governance system. The existing
  fixed PUSH→BUILD→VERIFY→WAVE=1→fsdbreport order and the
  Blackboard-as-system-of-record model are reused as-is; only the
  mechanics of the PUSH step and of source-identity verification change
  (git → direct file transfer + md5sum, per §4).
- Does not let `remote_exec.py` re-authenticate the outer telnet hop. It
  has no password and must not acquire one.
- Does not change how long regression jobs are launched/polled (`bsub` /
  `bjobs` pattern is unchanged — still never run in the foreground through
  this transport).
- Does not touch `remote_control.py` / the Web-Mobile "Remote Control"
  session-manager subsystem — that is a different concern (controlling the
  Claude Code session itself), already real and unrelated to this SSH
  transport to the Linux DV server.

## 4. Source Identity Without Git

**Decision (2026-08-30, explicit user choice):** this project does not use
git between PC and this Linux workdir. The flow is PC edit → PUSH (direct
file transfer) → BUILD (Linux) → VERIFY (Linux) → run (Linux). Source
identity — "is the Linux side running exactly what's on the PC side right
now" — is established with the md5sum three-way-diff recipe already
documented in `remote-linux-execution-bridge/SKILL.md`, not a git commit
SHA. This keeps CLAUDE.md's "Same regression batch must use the same
source/build/config identity" rule intact; only the mechanism changes.

**PUSH mechanism** (replaces `git push` + remote `checkout`):

1. PC-side edits happen directly in the local working copy — no commit
   required.
2. Whole-directory transfer reuses `remote_hop.py`'s own already-documented
   guidance (its module docstring, "For uploading a whole directory..."):
   `tar czf package.tgz -C <parent> <dir>` locally, `remote_exec.py --put
   package.tgz <remote>/package.tgz`, then `remote_exec.py "tar xzf
   <remote>/package.tgz -C <remote-dir>"`. Single-file changes may use
   `remote_exec.py --put <local> <remote>` directly.

**Source-identity verification** (replaces "verify remote HEAD equals
expected hash"):

1. Fix a file list up front (the files that matter for the build/run being
   verified).
2. `md5sum` it on both sides: locally, and via `remote_exec.py "md5sum
   $(cat file_list.txt)"` on the Linux side.
3. Run the existing three-way diff (`comm`-based LOCAL ONLY / REMOTE ONLY /
   BOTH-BUT-DIFFERENT classification) already written up in
   `remote-linux-execution-bridge/SKILL.md` §"Source Identity Verification
   (concrete recipe)" — unchanged, it was already git-independent.
4. Collapse the per-file manifest into one comparable token — `SOURCE_ID =
   sha256(sorted "path:md5" lines)` — so a single string can be compared
   the same way a git SHA would be, without needing git history. This is
   the new field `remote_exec.py`/the calling skill records to the
   Blackboard in place of `git_sha`/`server_sha` for this project (those
   two fields stay `null`, as `dv-harness status` already shows today,
   rather than being force-filled with a meaningless value).

This is scoped to *this* project's git-less workdir. A future project that
does have a real git remote between PC and Linux keeps using git SHA
comparison exactly as `remote-executor`/`remote-linux-execution-bridge`
already describe — this design doesn't remove that path, it adds the
git-free alternative alongside it, selected per-project by whether a git
repo is actually present.

## 5. Architecture

```
User's own terminal (has VCPW)              Claude Code tool calls (never has VCPW)
        |                                             |
        v                                             v
  remote_relay.py --start              remote_exec.py --status | "<cmd>" | --reconnect | --put | --get
        |                                             |
        | one telnet(VCHOST)+ssh(VCHOP) handshake     | loopback TCP only, auth'd by a
        | then WORKDIR cd + VCEDAENV source           | per-run token read from a local
        | then listens on 127.0.0.1:<port>            | file — no secret ever in this path
        +---------------------+-----------------------+
                               v
                    Linux working directory
         (files pushed via tar+put, no git; VCS/bsub/bjobs/sim.log/fsdbreport)
```

`remote_relay.py` is a new sibling file to `remote_hop.py`, at the project
root (and mirrored to `PACKAGE/`, same as `remote_hop.py` is today). It
imports and reuses `remote_hop.py`'s `Session` class unchanged (telnet IAC
negotiation, `put`/`get` base64+md5 transfer, tcsh-aware `run()`) rather
than re-implementing the transport.

`remote_exec.py` is a new, separate, small client file. It is the only one
of the three files Claude is ever expected to invoke via a tool call.

## 6. `remote_relay.py` (human-run only)

```
VCUSER=... VCPW=... VCHOST=vchost-b VCHOP=host-b VCWORKDIR=... VCEDAENV=... \
  python remote_relay.py --start [--idle-timeout 7200] [--bind-port 0]
```

Same required/optional environment variables as `remote_hop.py`, same
`_setup_reminder` behavior when they're missing. On start it:

1. Performs the existing telnet→ssh→cd→source handshake via `Session`
   (verbatim reuse — no changes to that logic).
2. Binds a TCP socket to `127.0.0.1` only (never `0.0.0.0` — a non-loopback
   bind is treated as a bug, not a configuration option). Port 0 (OS-chosen
   ephemeral) is the default; `--bind-port` can pin one for reruns.
3. Generates a random 32-byte token (`secrets.token_hex(32)`).
4. Writes `{"host": "127.0.0.1", "port": <port>, "token": "<hex>", "pid":
   <pid>, "started": "<iso8601>"}` to a local JSON file at
   `%LOCALAPPDATA%\dv_agent_harness\relay\<VCHOST>-<VCHOP>.json` (created
   with default Windows user-owned ACLs — no world/other access). This file
   contains **no password**.
5. Enters an accept loop, servicing one client connection at a time
   (DV command sessions are inherently serial — no concurrency needed).
6. Auto-exits (and cleanly closes the remote session with `exit`/`exit`)
   after `--idle-timeout` seconds (default 7200 = 2h) with no client
   activity — a live authenticated session to a production DV server must
   not sit open indefinitely unattended.
7. On any request whose token doesn't match, the relay closes that
   connection immediately and logs a warning to its own stderr — it does
   not leak whether the token was "close."

The wire protocol between client and relay is newline-delimited JSON, one
request/response pair per connection:

Request: `{"token": "...", "op": "status"|"run"|"put"|"get"|"reconnect_hop", "cmd": "...", ...}`
Response: `{"ok": true|false, "exit_code": <int|null>, "stdout": "...", "error": "..."}`

## 7. `remote_exec.py` (Claude-invoked)

```
python remote_exec.py --status
python remote_exec.py "pwd"
python remote_exec.py "git status"
python remote_exec.py --timeout 1800 "make WAVE=1"
python remote_exec.py "bjobs"
python remote_exec.py --reconnect
python remote_exec.py --put local_file remote_file
python remote_exec.py --get remote_file local_file
```

Behavior:

- Locates the relay's info file the same way the relay named it — via
  `VCHOST`/`VCHOP` env vars (still required, but **not** `VCPW` — this
  script never reads `VCPW` and errors out helpfully if only that one is
  set and no relay info file exists, so a stray `VCPW` in the environment
  is never even touched by this code path).
- Opens a loopback connection to `{host, port}` from that file, sends the
  token it read from the same file (never printed, never included in
  Claude-visible stdout).
- Prints a structured result block so exit-code branching is mechanical for
  the calling skill/agent, not regex-on-prose:

```
REMOTE_HOST=host-b
EXIT_CODE=0
STATUS=PASS
<command stdout...>
```

  `STATUS=FAIL` when `exit_code != 0`; `STATUS=DOWN` when the relay info
  file is missing or the connection is refused (stale/dead relay). For a
  PUSH or BUILD invocation specifically, the calling skill additionally
  records `SOURCE_ID=<sha256>` (§4) to the Blackboard alongside this block
  — `remote_exec.py` itself stays a generic transport and does not compute
  `SOURCE_ID` internally; that's the calling skill's job, same separation
  of concerns as today's git-based flow where `remote_exec.py`'s
  equivalent (`remote_hop.py`) doesn't know about git either.

- `--status` performs a lightweight `run("echo alive")` round trip and
  reports `STATUS=READY` / `STATUS=DOWN` plus the relay's `pid`/`started`
  time from the info file, without needing the caller to know relay
  internals.

## 8. Reconnect semantics (the credential-boundary edge case)

`remote_exec.py --reconnect` does **not** mean "re-run the full login."
`remote_exec.py` has no password and must not be given one. Two cases:

1. **Inner ssh hop dropped, outer telnet-to-VCHOST still alive**: the relay
   can redo `ssh -o StrictHostKeyChecking=no -o LogLevel=ERROR -o
   BatchMode=yes <VCHOP>` on its own, because that hop is key-based
   (`BatchMode=yes` in `remote_hop.py` already assumes/requires this). This
   is exposed as the `reconnect_hop` op above and `remote_exec.py
   --reconnect` tries this first.
2. **Outer telnet session itself is dead** (relay process crashed, network
   dropped, idle-timeout fired): there is no password available anywhere
   in this path to recover it. `remote_exec.py --reconnect` detects
   `STATUS=DOWN`, and instead of failing silently or hanging, prints an
   explicit instruction:

   ```
   [remote_exec] relay is DOWN and cannot self-reauthenticate (no password
   in this process). Ask the user to run, in their OWN terminal:
     VCUSER=... VCPW=... VCHOST=... VCHOP=... VCWORKDIR=... \
       python remote_relay.py --start
   ```

   This is a deliberate limitation, not a gap: it is the direct, correct
   consequence of the credential boundary this design exists to enforce.
   The calling skill/agent must surface this to the human and stop —
   consistent with the existing SSH intake rule's "do not assume or
   silently attempt a connection."

## 9. Long-running jobs

Unchanged from today's documented practice: `remote_exec.py "make
regression"` run in the foreground is still wrong. The relay's `run()`
inherits `remote_hop.py`'s existing hard ceiling behavior (default 1800s,
overridable per-call via `remote_exec.py --timeout N "<cmd>"`), but a
build/regression must instead be launched with `bsub`/`nohup ... &` and
polled with short separate `remote_exec.py "bjobs <id>"` /
`remote_exec.py "tail -100 sim.log"` calls, exactly as
`remote-executor`/`remote-linux-execution-bridge` already prescribe.

## 10. Security considerations

- Loopback-only bind; a non-127.0.0.1 bind is a bug, enforced in code (hard
  assertion at bind time, not just a doc comment).
- Token is generated fresh per relay start, never derived from or related
  to `VCPW`, never written anywhere but the one local info file, and never
  printed by either script in normal operation.
- Relay auto-idles out (default 2h) rather than staying authenticated
  indefinitely.
- No wildcard/destructive command handling is added by this layer —
  `remote_exec.py` is a transparent pass-through to `run()`, so the
  existing "no wildcard destructive commands, no hidden server access"
  rule in `remote-linux-execution-bridge` applies exactly as it does to
  today's manual/`remote_hop.py` path. This design does not add new
  command filtering; that stays a human/skill-level review responsibility,
  unchanged from today.
- The relay's info file directory (`%LOCALAPPDATA%\dv_agent_harness\relay\`)
  must never be added to `PACKAGE/` or committed — it's per-machine runtime
  state, analogous to how `.claude/settings.local.json` is already
  excluded from that kind of syncing.

## 11. File layout / consolidation

Per this project's Methodology Consolidation Rule:

- `remote_relay.py`, `remote_exec.py` — new files at the project root,
  next to `remote_hop.py`, mirrored into `PACKAGE/` the same way
  `remote_hop.py` already is.
- `.claude/skills/CORE/remote-linux-execution-bridge/SKILL.md` — gains a
  new section documenting the persistent-relay mechanics, the reconnect
  nuance in §8 above, and promotes the existing md5sum three-way-diff
  recipe to also serve as the primary git-free source-identity mechanism
  (§4) for projects with no git remote between PC and Linux.
- `.claude/skills/CORE/remote-executor/SKILL.md` — updated to call
  `remote_exec.py "<cmd>"` instead of describing raw SSH steps, for each of
  its fixed pipeline stages, and its "PC PUSH" / "Server exact-commit sync"
  steps get a git-free variant (tar+put, `SOURCE_ID` diff) alongside the
  existing git-based one, selected per-project.
- `CLAUDE.md` — gains a scoped **Remote Linux Execution** section (see
  draft below), narrower than the user's original draft: it keeps the
  existing SSH/Remote Transport Connection Intake gate as a one-time
  per-session step, and only removes the per-command "ask the user to run
  this manually" fallback once a relay is confirmed READY.

Draft `CLAUDE.md` addition:

```
## Remote Linux Execution (Persistent Relay)

Once a Linux DV server session has been established this session per the
SSH/Remote Transport Connection Intake gate above (user confirmed, relay
started by the user in their own terminal), do not ask the user to
manually run and paste back individual Linux commands. Use:

  python remote_exec.py "<command>"

Check readiness first with `python remote_exec.py --status`. If READY,
issue commands directly. If DOWN, run `python remote_exec.py --reconnect`;
if that reports the relay cannot self-reauthenticate, ask the user to
restart it in their own terminal (never embed VCPW in any Claude-issued
command) and stop until they confirm it is back up.

This does not remove the SSH/Remote Transport Connection Intake gate
itself — establishing or re-establishing a relay for the first time in a
session still requires that confirmation. It only removes the per-command
manual-paste fallback once a relay is already confirmed READY.

Source identity (PC vs. Linux) is verified per-project: git SHA comparison
where a git remote exists between PC and Linux, or the md5sum-based
SOURCE_ID token (see remote-linux-execution-bridge) where it does not —
never skipped outright.

Never request or print passwords, tokens, or credentials in any
remote_exec.py invocation or output.
```

## 12. Testing plan

- Unit tests for `remote_relay.py`'s token-mismatch rejection and
  loopback-only bind assertion (can run without real network access).
- Unit tests for `remote_exec.py`'s structured-output parsing
  (`REMOTE_HOST=`/`EXIT_CODE=`/`STATUS=`) against a fake local socket
  server standing in for the relay — no real telnet/ssh needed for this
  layer.
- Unit tests for the `SOURCE_ID` computation (§4) against a fixed
  synthetic file-list/md5 fixture — deterministic, no network needed.
- Manual end-to-end verification against a real `VCHOST`/`VCHOP` (human
  runs `remote_relay.py --start` themselves, per the credential-boundary
  rule this design exists to uphold) is out of scope for automated CI and
  is a manual sign-off step, same as today's `remote_hop.py`.

## 13. Open questions carried into implementation planning

- Exact idle-timeout default (2h proposed) — confirm with user if a
  different value fits their actual session length.
- Whether `remote_exec.py --status` should also surface the last N
  commands run through the relay (small ring buffer) for audit/debugging,
  or whether that belongs to the Blackboard integration instead of the
  relay itself.
- Exact file-list scope for `SOURCE_ID` per pipeline stage (whole project
  vs. changed-files-only) — likely mirrors whatever
  `command_inventory.csv`'s change-impact check already narrows a change
  down to, rather than always hashing the whole tree.
