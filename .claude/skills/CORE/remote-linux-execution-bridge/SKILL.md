---
name: remote-linux-execution-bridge
description: Govern SSH/Git/build/VCS/LSF actions from local Harness to Linux DV server with full traceability.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Remote Linux Execution Bridge
Only active in REMOTE_EXECUTION.
Record planned action, server, work_dir, environment/source commands and source identity before execution.
Capture status, stdout/stderr/artifact paths after execution and update Blackboard.
No wildcard destructive commands. No hidden server access.

## Source Identity Verification (concrete recipe)

**Confirmed drift (2026-08-29):** "record ... source identity before
execution" (line 8 above) has a real, concrete implementation worth
standardizing on: fix a file list up front, `md5sum` it on both the local
and remote side, then do a three-way diff to classify every file as LOCAL
ONLY / REMOTE ONLY / BOTH-BUT-DIFFERENT before trusting a remote build:

```bash
md5sum $(cat file_list.txt) > local.md5   # run locally
ssh "$SERVER" "cd $WORK_DIR && md5sum \$(cat file_list.txt)" > remote.md5
sort local.md5 -o local.md5.sorted
sort remote.md5 -o remote.md5.sorted
comm -23 local.md5.sorted remote.md5.sorted   # LOCAL ONLY (by full line: hash+name)
comm -13 local.md5.sorted remote.md5.sorted   # REMOTE ONLY
cat local.md5.sorted remote.md5.sorted | awk '{print $2}' | sort | uniq -d
  # ^ filenames present on both sides; cross-reference against the two comm
  #   outputs above -- a name in this list NOT fully matched (same hash) in
  #   both sorted files is BOTH-BUT-DIFFERENT
```

This is the first real worked implementation of the "same source/build/
config identity" rule (CLAUDE.md's own "Same regression batch must use the
same source/build/config identity") — a concrete recipe, not just a phrase.
Not USB-specific; applies to any remote-execution sync-verification need.

## Real Transport Shape (concrete, not a generic "use SSH" placeholder)

**Confirmed drift (2026-08-29):** a real sibling project's actual working
bridge is NOT plain SSH — it is a hand-rolled two-hop telnet+ssh session,
kept in version control (it "used to live in the session scratchpad and was
lost every time" per its own header comment — the generalizable lesson:
an essential cross-session tool must live in the repo, not ephemeral
scratch). The concrete shape, re-verify against the current project before
reuse:

1. **Two-hop login**: `telnet <vc-machine>:23` login, then from inside that
   session `ssh -o StrictHostKeyChecking=no -o LogLevel=ERROR <ssh-machine>`,
   then a fixed ordered setup sequence (`source version.csh` /
   `cd <project-path>` / `source env.csh` / `cd sim` or equivalent) — this
   matches CLAUDE.md's own "vc machine name" + "ssh machine name" SSH
   intake fields, now with the real telnet-then-ssh mechanics behind them.
   Telnet's raw IAC option-negotiation had to be hand-rolled because
   Python's `telnetlib` was removed in Python 3.13 — re-check the current
   Python version before assuming a library is available.
2. **No scp/sftp on this channel** — file transfer is base64-chunked
   `echo`/`base64 -d`, verified with `md5sum` both ways after every
   transfer. A real `get` (remote→local) capability was missing for about a
   week; during that gap, files were reconstructed by hand from `cat`
   output — which silently strips blank lines and appends the shell
   prompt, corrupting the reconstructed file. Never reconstruct a file from
   terminal `cat` output as a substitute for a real transfer mechanism.
3. **Quoting must survive three layers, in order: Git Bash → tcsh → `sh -c`.**
   A real failure: an inventory command silently returned the empty-file
   MD5 (`d41d8cd9...`) for 77 files because a `$f` variable was eaten one
   layer down. Working practice: for anything non-trivial, write a script
   file and `put` + run it (one quoting layer) instead of composing
   multi-layer quoted one-liners.
4. **tcsh's exit status is `$status`, not `$?`** — a bash/sh habit that
   silently reads the wrong (or a stale) value under tcsh.
5. **Never run a build/simulation in the foreground through this
   transport** — the socket itself can die mid-build and take the remote
   job with it, and there is a hard practical ceiling (~1800s observed) on
   any single foreground call. Launch with `nohup ... &`, then poll with
   short, separate invocations (e.g. a `pgrep`/`sleep 20` loop) — distinct
   from, and complementary to, `usb-regression/SKILL.md`'s own
   LSF-log-polling drift note (that one covers polling an LSF job's log;
   this one covers polling that the remote *shell/transport itself* is
   still alive).
6. **A jump-host can be renamed mid-project while quietly still mounting
   the same home directory** (a real case: `host-b` → `host-d`) — infra
   identity can drift even when the underlying files didn't move; don't
   assume a hostname is stable for the life of a project.
7. **A same-named "decoy" file can exist at a second, unexpected remote
   path** — before trusting any single file, check whether an
   identically-named file exists somewhere else too (md5sum + timestamp
   compare both), not just the LOCAL/REMOTE pair from a fixed file list —
   an extension of this file's own three-way-diff recipe above.

### Credential-handling gap this transport exposed (ties directly to CLAUDE.md's SSH intake rule)

**Confirmed drift (2026-08-29):** the transport script's own docstring
claims its password "comes from the environment: never written to disk,
never echoed" — but in real practice, the password assignment
(`VCPW=...`) was composed inline into the literal shell command text
submitted for Claude Code's own tool-approval flow, and Claude Code's own
approval history persists that literal string into
`.claude/settings.local.json` (observed ~967 times in one real project).
The value was also separately round-tripped through a *persistent*
Windows user-level environment variable. This is a real, observed instance
of exactly the failure CLAUDE.md's SSH intake rule exists to prevent, via a
persistence sink ("Claude Code's own permission/approval log", "a
persistent OS-level env var") the rule's current text doesn't name.
**Concrete rule to add going forward: never compose a password into the
literal command text Claude itself submits for approval — have the human
`export` it in their own interactive shell first, so the value never
appears in any string Claude Code's approval history could persist.**

**Confirmed drift (2026-08-31): a persistent env var can defeat a
script's own "missing credentials = safe no-op" check, even when the
password is never typed into the command at all.** While smoke-testing
the persistent-relay scripts below, an agent invoked `remote_relay.py
--start` via its own tool call to exercise the "required env vars
missing" early-exit path — expecting it to be safe because it never
composed `VCPW` (or `VCUSER`/`VCHOST`/`VCHOP`) into the command text.
But all four were already set as *persistent Windows user-level
environment variables* (from earlier legitimate manual use in the same
session), so the early-exit check never triggered: the script proceeded
to actually attempt a real telnet+ssh login to the real server, from
inside the tool call. The agent noticed, killed the process, and
disclosed the incident — but could not confirm from buffered/truncated
output whether the password had already been transmitted before the
kill. **Concrete rule: a script whose docstring says "never invoke me
from an AI agent tool call" must never be invoked from one at all, even
to test its own argument-validation/error paths — "the vars aren't in my
command" is not the same guarantee as "the vars aren't in my
environment." Test such a script's logic via unit tests against extracted
pure functions (e.g. a `handle_request()`/`RelayServer` class with no
socket I/O), never via a live `--start`/subprocess invocation of the
credential-consuming entry point itself.**

## Persistent Relay (remote_relay.py + remote_exec.py)

Per `docs/superpowers/specs/2026-08-30-persistent-remote-relay-design.md`
(2026-08-31, implemented): the two-hop telnet+ssh transport above now has
a persistent-session variant, in `tools/remote/` within the `v50` project,
next to `remote_hop.py` (mirrored to `industrial/tools/remote/` and
`PACKAGE/tools/remote/`):

- **`remote_relay.py`** (human-run only, same credential-boundary rule as
  `remote_hop.py` — never invoke from a Claude Code tool call): performs
  the telnet→ssh→cd→source handshake ONCE using `remote_hop.py`'s own
  `Session` class unchanged, then listens on a loopback-only
  (`127.0.0.1`) TCP socket, auth'd by a random per-run token written to
  `%LOCALAPPDATA%\dv_agent_harness\relay\<VCHOST>-<VCHOP>.json` (no
  password in that file). Auto-exits after an idle timeout (default
  7200s) so an authenticated session never sits open indefinitely.
- **`remote_exec.py`** (the file Claude actually invokes): a thin client
  that never reads `VCPW`, talks only to the loopback relay, and prints a
  structured `REMOTE_HOST=/EXIT_CODE=/STATUS=` block so exit-code
  branching is mechanical. `--reconnect` can redo the inner `ssh` hop on
  its own (key-based, `BatchMode=yes`, no password needed) if only that
  hop dropped; if the outer telnet session itself is dead, it prints
  instructions for the human to restart `remote_relay.py` in their own
  terminal — it cannot and must not self-reauthenticate.
- **`source_identity.py`**: the md5sum three-way-diff recipe above,
  collapsed into one comparable `SOURCE_ID = sha256(sorted "path:md5"
  lines)` token — used in place of a git commit SHA for projects with no
  git remote between PC and the Linux workdir (see
  `remote-executor/SKILL.md`'s git-free PUSH variant).

This does not remove the per-session SSH/Remote Transport Connection
Intake confirmation (CLAUDE.md) — establishing or re-establishing a relay
still requires that confirmation and is still done by the human, in their
own terminal. It only removes the per-command "ask the user to manually
run this and paste back the output" fallback once a relay is confirmed
READY (`remote_exec.py --status`).

`remote_execution_provenance_gate.py` independently verifies a real
`remote_exec.py` transcript (its `REMOTE_HOST=`/`EXIT_CODE=`/`STATUS=`
output) rather than trusting self-attested BUILD/VERIFY evidence.

### Four-layer credential boundary (2026-08-31, hardened after the drift above)

A docstring saying "never invoke me from an AI agent" is not an
enforceable boundary — it is prose. After the 2026-08-31 incident above,
the boundary between "Claude can drive remote execution" and "Claude can
never obtain the credential" is enforced at four independent layers:

1. **Operational**: `VCPW` (and the other three required vars) should be
   set only in the terminal that runs `remote_relay.py --start` — not in
   whatever terminal/environment then launches `claude`. If both must
   share a machine, `Remove-Item Env:VCPW` (or `unset VCPW`) before
   starting the Claude Code process, so its process tree never inherits
   it in the first place. This is the primary defense; the rest are
   defense-in-depth for when this one is imperfectly followed.
2. **Environment-marker guard** (secondary defense — an env var is not a
   security primitive and can be unset/spoofed, but catches the common
   case): `remote_relay.py`'s `main()` calls `running_inside_ai_agent()`,
   which checks for `CLAUDECODE`/`CLAUDE_CODE`/`CLAUDE_CODE_ENTRYPOINT`/
   `CLAUDE_CODE_SESSION_ID`/`ANTHROPIC_API_KEY` (all confirmed real,
   actually-set markers in a live Claude Code environment) and refuses to
   start (`exit 126`) before any networking if any are present. This is
   exactly the check that would have caught the 2026-08-31 incident —
   verified by re-running `remote_relay.py --start` from inside a real
   Claude Code tool call after the fix landed: blocked immediately, no
   connection attempted.
3. **Zero-credential client**: `remote_exec.py` (the file Claude actually
   invokes) contains no code path that reads `VCPW` at all — verified by
   a source-scan test (`test_remote_exec_source_never_reads_vcpw_env_var`)
   asserting `os.environ.get('VCPW'`/`os.environ['VCPW']` never appears in
   its source. Claude's only capability is the localhost JSON protocol in
   §7 above (`{"op": "run", "cmd": "..."}` etc.) — it never sees, sends,
   or could construct the credential.
4. **Credential-inspection command DENY list**: `RelayServer.handle_request`'s
   `run` op refuses (`CREDENTIAL_INSPECTION_DENIED`, before touching the
   session at all) any command matching `env`/`printenv`/`set`/`export`
   (bare, no assignment) / `$VCPW`/`${VCPW}` / `os.environ` / a
   `getenv('VCPW'...)`-shaped call — so even a fully-compromised or
   confused caller cannot use the "run arbitrary remote command" surface
   to read back the credential this whole boundary protects. This is
   deliberately narrow (credential-inspection only) — it is not a general
   destructive-command policy, which remains a human/skill-level review
   responsibility per this design's own scope.
