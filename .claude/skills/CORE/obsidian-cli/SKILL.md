---
name: obsidian-cli
description: 真實 Obsidian CLI 能力偵測與安全降級 -- 永遠不因 Obsidian 未安裝而阻擋 Memory 寫入，FileSystemMarkdownAdapter 永遠是真正的寫入路徑。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# obsidian-cli
真實 Obsidian CLI 能力偵測與安全降級（`dv_harness/memory_vault.py`）-- 永遠不因 Obsidian 未安裝而阻擋 Memory 寫入，`FileSystemMarkdownAdapter` 永遠是真正的寫入路徑。

核心原則：a truthful `installed: True` is not the same claim as "this adapter can perform real operations" -- keep detection and capability separate.

## Mechanics (2026-09-03, real wiring)

**Purpose**: let the memory system opportunistically use a real, installed
Obsidian CLI when one is genuinely available and wired, WITHOUT ever making
Obsidian's absence (the confirmed, permanent reality on this development
machine) a blocker for any memory write.

**Inputs**: nothing from the caller -- detection is a real probe of the
current machine (`shutil.which("obsidian-cli"/"obsidian")`, then well-known
per-OS install paths, then a real `--version`/`-v` subprocess call).

**Outputs**: `detect_obsidian_cli()` -> `{"installed": bool, "version":
str|None, "executable": str|None, "vault_access": bool, "search"/"read"/
"create"/"update"/"properties"/"tags"/"links": "NOT_AVAILABLE" (always,
today), "status": "PARTIAL"|"BLOCKED"}`. `ObsidianAdapter(vault_path).status()`
wraps this as `{"provider": "obsidian_cli", "status": ..., "detail": ...}`.
Confirmed live result on this development machine: `installed: false,
status: "PARTIAL"`.

**Preconditions**: none -- safe to call unconditionally, including on a
machine with no Obsidian anywhere on it (the common, expected case).

**Execution Steps**:
1. Never call `ObsidianAdapter` directly from application code. Use
   `dv_harness.memory_vault.get_active_provider(project_root, cfg)` --
   it returns `HybridMemoryProvider(ObsidianAdapter, FileSystemMarkdownAdapter)`
   by default, or a bare `FileSystemMarkdownAdapter` when
   `cfg["memory"]["obsidian_cli"] == "disabled"` (explicit opt-out; skips
   probing Obsidian entirely).
2. `HybridMemoryProvider` tries Obsidian PER CALL (`_dispatch()`), only
   when `ObsidianAdapter.status()` currently reports `"READY"` -- as of
   this workstream, that never happens (every operational method is a
   deliberate, honest `NOT_AVAILABLE` -- see below), so every real call
   today falls through to `FileSystemMarkdownAdapter`, which performs the
   actual Markdown+YAML file operation.
3. If a future obsidian-cli install's exact command contract is confirmed
   on a real machine, extend `ObsidianAdapter`'s methods to shell out to it
   -- do NOT guess at command syntax in the meantime; a wrong guess risks
   silently fabricating a result instead of honestly degrading.

**Fallback**: `FileSystemMarkdownAdapter` is not a degraded fallback in the
weak sense -- it is the real, fully-functional implementation
(search/read/create/update/delete/tags/links against actual files,
`rg`-accelerated with a correct pure-Python fallback). Obsidian, when
wired, would only ever be an alternate transport to the same note schema,
never a capability the filesystem adapter lacks.

**Evidence Requirements**: `detect_obsidian_cli()`'s `installed`/`version`
must come from a genuine `shutil.which` + subprocess `--version` call --
never hardcode `installed: True` to make a status check pass. This was
verified genuine (not hardcoded) by simulating an installed CLI via mocks
during the foundational workstream and confirming the report flips
correctly.

**Failure Conditions**: treating `ObsidianAdapter`'s `installed: True` (on
some future machine) as equivalent to `status: "READY"` would be wrong --
`status` stays `PARTIAL` even with a real binary found, specifically
because no operation is wired against it yet. Do not "fix" this by making
`status()` report READY without first confirming and implementing the real
command contract.

**Example**:
```python
from dv_harness.memory_vault import detect_obsidian_cli, get_active_provider
detect_obsidian_cli()
# -> {"installed": False, "version": None, "executable": None,
#     "vault_access": False, "search": "NOT_AVAILABLE", ..., "status": "PARTIAL"}
provider = get_active_provider(root, cfg)  # HybridMemoryProvider; writes land on FileSystemMarkdownAdapter today
provider.create({"id": "NOTE-1", "memory_level": "engineering", "protocol": "USB",
                  "status": "ACTIVE", "confidence": "HIGH"})
```
