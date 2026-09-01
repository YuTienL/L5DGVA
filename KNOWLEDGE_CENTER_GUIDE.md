> See START_HERE.md for the canonical entry point and current mechanism overview; this page covers the shared Knowledge Center specifically.

# AI Agent Harness L5 — Knowledge Center Guide

The Knowledge Center is the cross-user, cross-session shared store of
Engineering/Organizational Memory + Corner-Case Library, hosted on a fixed
Linux-server path. As of 2026-09, the real deployment is:

```
remote_root = /home/svcacct/AI/DB
```

on `vchost=vchost-b` / `vchop=host-c` (routed through the persistent relay — see
REMOTE_LOGIN_GUIDE.md). This path was confirmed and 固化 (solidified) as a
standing policy this session: any confirmed harness gap/lesson must be
distilled into a permanent skill/capability AND written back here so future
sessions inherit it automatically, not just this conversation.

## Is it safe for multiple people to use at the same time?

**Yes.** This was verified directly from `tools/knowledge_center/broker.py`
(the real server-side script every client call invokes), not assumed:

- **Real cross-process lock per shard** — `_ShardLock` uses
  `fcntl.flock(fileno, fcntl.LOCK_EX)`, an OS-level exclusive lock, scoped
  to `locks/<category>__<protocol>.lock`. Two different (category, protocol)
  shards never block each other; the same shard is fully serialized across
  every concurrent user/process.
- **Atomic writes** — `_atomic_write_json()` writes to a tempfile then
  `os.replace()`s it into place (atomic POSIX rename). A reader can never
  observe a torn/partial write, only a fully-old or fully-new record.
- **The lock covers the whole read-modify-write** — index lookup, record
  write, and index update all happen inside the same critical section, so
  there is no window where two concurrent writers can silently clobber each
  other's update (the exact race class `dv_harness/memory.py` and
  `dv_harness/blackboard.py` have *not* solved — see the Comparison section
  below).

This holds only because every write goes through the one server-side
`broker.py` process invoked per call (via the relay) — never through a
network-mounted directory written to directly by multiple machines, which
would not have reliable cross-machine lock semantics. Every client this
harness ships (`dv_harness/knowledge_center.py`'s `KnowledgeCenterClient`)
already goes through the broker; nothing bypasses it.

## Comparison — what is NOT safe for concurrent multi-writer use

| Store | Concurrency safety | Why |
|---|---|---|
| Knowledge Center (`/home/svcacct/AI/DB`, `broker.py`) | **Safe** | `fcntl.flock` per shard + atomic `os.replace()` write |
| `.dv-harness/state.json`, `blackboard/`, `react/`, `events.jsonl` (per-project runtime state) | **Not safe for concurrent writers** | Plain read-modify-write, no locking — "safe for one process, a silent lost-update race for two" (per `dv_harness/memory.py`/`blackboard.py`'s own design) |

This is why the Knowledge Center and a project's own `.dv-harness/` runtime
state are treated completely differently in the multi-user pattern below —
one is a real shared database, the other is per-session/per-project scratch
state that was never designed to be written by two processes at once.

## Recommended multi-user pattern

- **Knowledge Center**: share freely. Every user's harness instance should
  point `knowledge_center.remote_root` at the same
  `/home/svcacct/AI/DB` — that is the entire point of it being a shared
  store, and it is safe by construction (see above).
- **`.dv-harness/` runtime state**: never share. Each user must run the
  harness with their **own `--project-root`**
  (`dv-harness --project-root /home/<user>/<own-project-copy> ...`,
  see `dv_harness/cli.py`'s `--project-root` / `DVHarness.__init__`) — never
  multiple people driving `dv-harness` commands directly inside the one
  shared `/home/svcacct/AI/Agent` deployment tree at the same time. See
  `USAGE_MULTI_USER_SAFETY.md` for the full reasoning and the concrete
  recommended layout.

## Setup

```
dv-harness knowledge setup --remote-root /home/svcacct/AI/DB
```

This is the only code path allowed to fill in `remote_root` — it always
prompts interactively (never guesses/hardcodes another user's server path,
per CLAUDE.md's SSH/Remote Transport Connection Intake gate). Requires
`VCHOST`/`VCHOP` env vars (or `knowledge_center.vchost`/`vchop` in
`.dv-harness/config.json`) pointing at an already-running relay — see
REMOTE_LOGIN_GUIDE.md.

## Everyday commands

```
dv-harness knowledge status                       # ping the broker, show enabled/remote_root
dv-harness knowledge add --category usb --protocol usb ...
dv-harness knowledge search --category usb --protocol usb --query "..."
dv-harness knowledge confirm --category usb --protocol usb --id <record-id>
dv-harness knowledge db-info --category usb --limit 100   # DB-wide activity log: who added/updated/retracted what, and when
```

`db-info` is the DB-wide audit trail (across every user of the shared
store), distinct from any single record's own history.
