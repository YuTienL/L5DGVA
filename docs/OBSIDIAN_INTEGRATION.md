> See MEMORY_ARCHITECTURE.md for how this fits into the overall Memory system. This page covers the Obsidian-compatible Vault specifically.

# AI Agent Harness L5 — Obsidian Integration

## Honest current status (checked 2026-09-03, this development machine)

**Obsidian CLI is NOT installed.** `where obsidian-cli` and `where obsidian`
both fail. This is treated as the PERMANENT expected reality for most
users, not a temporary gap: the design goal is honest detection + graceful
degradation, never a requirement that Obsidian be installed for Memory to
work. Every real memory operation already works today with zero Obsidian
install, via `FileSystemMarkdownAdapter` — the real, fully-functional
implementation.

Run the probe yourself:
```
python -c "from dv_harness.memory_vault import detect_obsidian_cli; import json; print(json.dumps(detect_obsidian_cli(), indent=2))"
```
Expected on a machine with no Obsidian CLI:
```json
{
  "installed": false, "version": null, "executable": null, "vault_access": false,
  "search": "NOT_AVAILABLE", "read": "NOT_AVAILABLE", "create": "NOT_AVAILABLE",
  "update": "NOT_AVAILABLE", "properties": "NOT_AVAILABLE", "tags": "NOT_AVAILABLE",
  "links": "NOT_AVAILABLE", "status": "PARTIAL"
}
```
This is a REAL probe (PATH lookup via `shutil.which`, well-known per-OS
install paths, a genuine `--version`/`-v` subprocess call) — not
hardcoded. It will correctly report `installed: true` and a real version
string on any machine that genuinely has `obsidian-cli`/`obsidian` on PATH
or in a known install location.

## Why `status` stays `PARTIAL` even if a binary is found

`ObsidianAdapter`'s `search`/`read`/`create`/`update`/`properties`/`tags`/
`links` are ALWAYS `NOT_AVAILABLE`, regardless of `installed` — this
codebase has never observed a real `obsidian-cli`'s exact command syntax
on an actual installed instance, so no method guesses at one. `status`
therefore never reports `READY` until a future revision confirms and
wires a real command contract. This is a deliberate, honest design choice:
a truthful `installed: true` is not the same claim as "this adapter can
perform real operations against it."

## What actually writes the Vault today: `FileSystemMarkdownAdapter`

Real Markdown+YAML file operations against `.dv-harness/vault/` (or your
configured `memory.vault_path`) — search, read, create, update, delete,
tags, wiki-links. No vector database, no embeddings: `search()` is real
keyword/tag/YAML-property/wiki-link filtering over an on-demand filesystem
scan, optionally accelerated by `rg` (a missing `rg` only changes speed,
never correctness).

`HybridMemoryProvider` is what every real caller (the promotion
write-through, the Memory Agent) actually holds — it composes both
adapters and, PER CALL, tries Obsidian first only when its `status()`
currently reports `READY` (today: never), falling back to
`FileSystemMarkdownAdapter` otherwise. This is a per-call decision, not a
one-time pick, so a future machine where Obsidian's CLI happens to be
installed does not silently stop real writes just because detection
starts reporting `installed: true` — operations stay routed to the
filesystem adapter until they are genuinely wired.

## The Vault directory structure

Bootstrapped additively (never overwrites existing content) by
`bootstrap_vault()` on first use, at `resolve_vault_path(project_root, cfg)`
— empty `memory.vault_path` in config resolves to a project-relative
`.dv-harness/vault`:

```
.dv-harness/vault/
├── 00_Inbox/
├── 01_Projects/
├── 02_Protocols/{USB,PCIe,Ethernet,AMBA,MIPI,CAN-FD}/
├── 03_Verification/{UVM,VIP,vPlan,Coverage,Regression}/
├── 04_Debug/{Known_Issues,Failure_Patterns,Root_Cause}/
├── 05_Tools/{VCS,Verdi,ZeBu,HAPS,LSF}/
├── 06_Agent_Memory/{Working,Job,Project,Engineering,Organizational}/   <- memory-router write-through lands here
└── 07_Signoff/{Requirements,Traceability,Coverage,Reports}/
```

`06_Agent_Memory/<Level>/` is where an ENGINEERING_MEMORY or
ORGANIZATIONAL_MEMORY promotion actually lands
(`_MEMORY_LEVEL_FOLDER` in `memory_vault.py`); everything else is
scaffolding for future/manual use (protocol notes, vPlan notes, tool
notes) that this workstream creates the folders for but does not
auto-populate.

Bootstrap it explicitly:
```
python -c "from dv_harness.memory_vault import resolve_vault_path, bootstrap_vault; from dv_harness.config import load_config; from pathlib import Path; root=Path('.'); print(bootstrap_vault(resolve_vault_path(root, load_config(root))))"
```

## Opening the Vault in the real Obsidian app

Nothing here requires the Obsidian CLI to use the real Obsidian
application manually: `.dv-harness/vault/` is a plain folder of
Markdown files with standard `key: value` YAML frontmatter — open it in
Obsidian as "Open folder as vault" and every note's Properties panel,
tags, and `[[WikiLink]]` graph view work exactly as they would for any
other Obsidian vault, with zero code changes needed on this side. This is
the intended human-facing use of the Vault; the harness's own Python code
never depends on the app being open.

## Configuration (`.dv-harness/config.json`)

```json
"memory": {
    "provider": "hybrid",
    "vault_path": "",
    "obsidian_cli": "auto",
    "git_enabled": false
}
```

- `obsidian_cli: "auto"` — probe for a real CLI on every
  `get_active_provider()` call, safely falling back when (as always so
  far) none is found or wired.
- `obsidian_cli: "disabled"` — skip probing Obsidian entirely, always use
  `FileSystemMarkdownAdapter` directly (a bare adapter, not wrapped in
  `HybridMemoryProvider`). Use this if you want to guarantee zero
  Obsidian-related subprocess calls, e.g. in a locked-down CI environment.
- `git_enabled: false` (default, opt-in) — set `true` to have every vault
  write auto-`git init` (repo-local identity only, never touches your
  global git config) and commit. See MEMORY_OPERATIONS.md for the
  Windows caveat that motivated this defaulting to `false`.
- `vault_path` — leave empty for the project-relative default, or set an
  absolute/relative path to point at a Vault you already keep elsewhere
  (e.g. a personal Obsidian vault you already sync/back up).

## YAML frontmatter subset — what it does and does not support

`memory_vault.py`'s frontmatter reader/writer is intentionally NOT a
general YAML parser (no PyYAML dependency — stdlib only, matching this
harness's "core uses Python standard library only" convention). It
supports exactly what the note schema needs: scalars (`str`/`int`/
`float`/`bool`/`None`) and flat lists of scalars (used for `tags`). It
round-trips correctly with itself and with simple hand-edited Obsidian
frontmatter using the same plain `key: value` / `key:\n  - item` shapes.
Do not add nested maps, multi-line block scalars, or YAML anchors to a
vault note frontmatter block by hand — they are out of this parser's
scope and will not round-trip correctly.
