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
