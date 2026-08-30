---
name: restore-session
description: Restore a DV Agent Harness L5 run-state snapshot saved by save-session, e.g. to continue exactly where a previous Claude Code session left off after re-running remote_login.sh in the same project directory.
allowed-tools: Read Grep Glob PowerShell Skill
---
# restore-session

Typical flow: the user ran `save-session` before ending a prior Claude Code
session; now, in a fresh session (often right after `source
remote_login.sh` re-establishes the Linux-server connection env vars, in
the SAME local project directory), `restore-session` brings the run-state
layer back to exactly that checkpoint so work continues where it left off.

**How to invoke:**
- CLI: `dv-harness restore-session [NAME]` -- omit `NAME` (or pass `--list`)
  to just list what is available first, same shape as the existing `lsf
  [job_id] [--list]` command.
- Web GUI: the "Session Save / Restore" card's table + per-row Restore
  button (confirms before acting).
- Both call the exact same `session_snapshot.restore_session()`.

**Safety, by default:** restoring auto-backs-up whatever state it is about
to overwrite first (as `_pre_restore_<epoch>`), so a restore is never a
one-way action -- the immediately-previous state is always one more
`restore-session` call away. Pass `--no-backup` (CLI) to skip this only if
you are certain you do not need the pre-restore state.

**`events.jsonl` is never rewound.** It is copied INTO every snapshot for
reference, but restore deliberately excludes it from what gets copied
BACK — an append-only audit log should never be destructively rewritten. A
`SESSION_RESTORED` marker (naming which snapshot, and the auto-backup name)
is appended to the live, continuous log instead, so `dv-harness audit`
still shows a complete, honest history across the restore point.

Same exclusion as `save-session`: the Memory Hierarchy / Corner-Case
Library and static policy config are never touched by a restore, whichever
snapshot is chosen.
