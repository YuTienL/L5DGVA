---
name: memory-review
description: 對 DV-Knowledge Vault 筆記與底層 JSON MemoryStore 做健康度複查（schema/重複 ID/壞 YAML/斷鏈/密鑰外洩/索引漂移），產出可據以行動的證據；這是 memory-gc 動作前的「檢查與判斷」步驟。
allowed-tools: Read Grep Glob PowerShell Skill
---
# memory-review
對 DV-Knowledge Vault 筆記與底層 JSON MemoryStore 做健康度複查，產出可據以行動的證據；這是 `memory-gc` 動作前的「檢查與判斷」步驟。

核心原則：Memory is prior knowledge, not current evidence -- a doctor
verdict describes the STORE's health, never whether any record's engineering
claim is still true.

## Mechanics (2026-09-04, real wiring)

**Purpose**: answer "is the memory store itself healthy, and which specific
records need action" from real files on disk, BEFORE anything is deprecated,
re-written or promoted. `memory-gc` performs lifecycle ACTIONS
(`deprecate`/`supersede`/`retract`/`flag_stale`); this skill is the read-only
REVIEW that decides which record deserves one, and it is the only skill that
covers `dv_harness/memory_doctor.py`. Also the backing for the Memory Agent's
"Validate" responsibility and its "Periodic hygiene" invocation pattern
(`.claude/agents/memory-agent.md`).

**Inputs**: none required -- both entry points sweep the whole vault
(`06_Agent_Memory/**/*.md`, resolved via `memory_vault.resolve_vault_path()`)
plus, for `doctor`, the whole vault tree and the JSON `MemoryStore` under
`.dv-harness/memory/`. Optional: a project `root` and a `cfg` dict; omitting
`cfg` loads the project's real `config.load_config(root)`.

**Outputs**: two real entry points in `dv_harness/memory_doctor.py`, each
returning `{"overall", "blocked_reasons", "partial_reasons", "note_count",
"checks": {...}}` where every `checks[...]` value carries its own `status`
plus the concrete offending paths/ids.

`run_validate(root, cfg)` (`memory_doctor.py:285`) -- the note-CORRECTNESS
subset, 5 checks, nothing about the environment:
<!-- validate-checks -->
- `schema` -- `memory_vault.validate_note()` over every note: the frontmatter
  half (`validate_note_frontmatter()`, `memory_vault.py:204`) reports
  COMPLETE vs. PARTIAL against `MEMORY_NOTE_REQUIRED_FIELDS` (`id`,
  `memory_level`, `protocol`, `status`, `confidence`, `created`, `updated`),
  and the body half (`validate_note_body_sections()`) re-checks the
  11-section shape on READ -- which is what catches an Obsidian-GUI edit that
  deleted or reordered a section. `notes_missing_recommended` is reported in
  its own list and never moves `status`.
- `duplicate_ids` -- two notes carrying the same frontmatter `id`.
- `invalid_yaml` -- a note whose frontmatter would not parse at all.
- `broken_links` -- a `[[WikiLink]]` pointing at a note id nothing owns; this
  is the periodic sweep `memory-link`'s own Failure Conditions section calls
  for, since links are never validated at write time.
- `secrets` -- `memory_security.detect_secrets()` over each note's raw
  on-disk text. Normally empty (the write path redacts first), so a hit means
  a hand-edited note or one written before that feature existed.
<!-- /validate-checks -->

`run_doctor(root, cfg)` (`memory_doctor.py:309`) -- the full sweep: those 5
plus 6 environment/store checks, 11 in total:
<!-- doctor-checks -->
- `vault_writable` -- real mkdir + write-probe + unlink against the resolved
  vault path.
- `git` -- only meaningful when `memory.git_enabled` is True; see Fallback.
- `obsidian_cli` -- `memory_vault.detect_obsidian_cli()`, never re-derived
  here; see `obsidian-cli` for why `installed: True` is still not READY.
- `filesystem_fallback` -- `FileSystemMarkdownAdapter.detect()`, the write
  path that is always available.
- `schema`
- `duplicate_ids`
- `invalid_yaml`
- `broken_links`
- `large_files` -- the POST-HOC half of Phase 12's artifact policy, scoped to
  the WHOLE vault tree (an FSDB/VPD/coverage DB can land anywhere), using
  `memory_artifact_policy`'s own thresholds. The WRITE-TIME half is
  `enforce_record_artifact_policy()` inside `MemoryStore.add()`.
- `secrets`
- `memory_store_index` -- JSON `MemoryStore` index-vs-files drift. A record
  file with no `index.json` row is invisible to `MemoryRetriever.search()`
  while looking perfectly healthy in the vault.
<!-- /doctor-checks -->

Per-check status is one of `READY` / `PARTIAL` / `BLOCKED` (plus `DISABLED`,
which only `git` produces). `overall` aggregates them with BLOCKED trumping
PARTIAL trumping READY; `DISABLED` and `READY` never drag it down
(`_aggregate()`, `memory_doctor.py:278`).

**Preconditions**: none -- every check is read-only apart from
`vault_writable`'s own probe file, which it removes. Safe to run at any time,
including mid-debug.

**Execution Steps**:
1. `python -m dv_harness memory validate` -- note correctness only, JSON to
   stdout, exit 1 only when `overall` is BLOCKED (`cli.py:2208`).
2. `python -m dv_harness memory doctor` -- the full 11-check sweep, same
   output contract and same exit rule (`cli.py:2237`).
3. Read `checks` for the specific ids/paths, never just `overall`: a PARTIAL
   `schema` names each note's `missing_required` / `missing_sections` /
   `body_out_of_order`, and a PARTIAL `memory_store_index` names each drifted
   record.
4. Act on what it names, always through the real API -- a schema-PARTIAL note
   is repaired with `provider.update()` (never by hand-editing the `.md`), a
   stale/wrong record via `memory-gc`, index drift via
   `python -m dv_harness.memory_cli reindex`. Re-run step 1 or 2 afterwards
   as the evidence that the repair landed.

**Fallback**: two states look like defects and are not. `git` reports
`DISABLED` when `memory.git_enabled` is False -- this project's documented
default, informational only, and deliberately excluded from `overall`
(`check_git()`, `memory_doctor.py:104`). `obsidian_cli` reports PARTIAL on
every machine confirmed so far because Obsidian CLI is genuinely absent and
the filesystem adapter is the real write path -- which is why an honest empty
vault's `overall` is PARTIAL, never BLOCKED. Neither is a gap to close.

**Evidence Requirements**: the doctor/validate JSON IS the evidence -- cite
the check key plus the specific note path/id it named, never a bare "doctor
says PARTIAL". A claim that the memory store is healthy needs a real run of
one of these two commands, not an inspection of a few notes by eye.

**Failure Conditions**:
- Treating `git: DISABLED` or `obsidian_cli: PARTIAL` as a defect and
  "fixing" it -- that is the disclosed fallback working as designed.
- Deleting a note or a record file to clear `duplicate_ids` / a stale record:
  audit history is never deleted, status changes go through `memory-gc`.
- Hand-editing a note's frontmatter to flip `schema_status` to COMPLETE. That
  field is written by the adapter from `validate_note_frontmatter()`'s real
  result; editing it only makes the note lie about itself, and the next
  `validate` run recomputes it from the fields anyway.
- Running `validate` (5 checks) and reporting it as a full health check --
  it deliberately runs none of the environment or index checks.

**Example**:
```
$ python -m dv_harness memory doctor
{
  "overall": "PARTIAL",
  "blocked_reasons": [],
  "partial_reasons": ["obsidian_cli", "schema"],
  "note_count": 12,
  "checks": {
    "obsidian_cli": {"status": "PARTIAL", "installed": false, ...},
    "schema": {"status": "PARTIAL", "complete_count": 11,
               "partial": [{"note_id": "MEM-1A2B3C4D5E",
                            "missing_required": ["confidence"],
                            "missing_sections": [], "body_out_of_order": false}]}
  }
}
```
