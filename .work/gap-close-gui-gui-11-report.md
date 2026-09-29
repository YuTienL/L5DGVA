# GUI-11 gap close: Memory + Obsidian Knowledge Center card + GET /api/memory

NOTE ON THIS FILENAME: the task asked for `.work/gap-close-gui-gui-11:-report.md`.
Windows (NTFS) forbids `:` in a filename, so this report is at
`.work/gap-close-gui-gui-11-report.md`, matching the `gap-close-*-report.md`
convention every other report in this directory uses (and the same substitution
the GUI-09 pass already made).

**Status: DONE**

Commit `c3e9a84` on `gap-close/env-manifest-fact-sources`, 2 files,
+704 / -1 (one deletion: the page-load bootstrap line, extended with
`loadMemoryCenter();`).

## The gap

`dv_harness/dashboard.py` had no surface at all for the 5-tier Memory Hierarchy
(`memory.MEMORY_LEVELS` = working / job / project / engineering / organizational)
or for the DV-Knowledge Vault that `memory_vault.py` mirrors promoted records
into. The existing **Shared Knowledge Center** card is a different question --
it reports the cross-project broker's config and connectivity, not what THIS
project's own memory tiers hold -- so a reviewer could not answer "how much
verified knowledge does this project actually carry, at which tier" from the
GUI at all.

The backing capability was real and unsurfaced: `dv_harness/memory.py`'s
`MemoryStore` (92 real records across 4 tiers in this repo's own store),
`dv_harness/memory_vault.py`, `docs/OBSIDIAN_INTEGRATION.md`, and a real
populated vault at `.dv-harness/vault/06_Agent_Memory/Engineering/*.md`
(9 real notes).

## What was built

**Backend -- `dv_harness/dashboard.py`:**

- `_read_memory_center_state(root, *, text_query, level_filter, limit, note_id)`
  -- the whole payload. Nothing is re-derived locally:
  - per-tier counts are `MemoryStore.index_integrity()`'s own `per_level`
    figures, the SAME read-only drift report `memory_doctor`'s
    `memory_store_index` check reads. `record_files` and `index_rows` are kept
    as **two separate numbers**, because they are: a tier where they disagree
    has records that exist on disk but are invisible to
    `MemoryRetriever.search()` -- the exact lost-update drift that once hid 18
    of 31 engineering records in this project's own store (see
    `MemoryStore._index_lock()`'s comment). A card showing one number could not
    have shown that.
  - vault notes come from the real `memory_vault.get_active_provider()` through
    its own `search()` / `read()`. **No markdown and no YAML frontmatter is
    parsed anywhere in dashboard.py.**
  - the tier vocabulary is `memory.MEMORY_LEVELS` over the wire, not a copy.
- `_locally_stored_memory_levels()` -- which tiers really have a
  `.dv-harness/memory/<level>/` file store, **derived** from `memory_router`'s
  own `_TIER_STORE_CLASSES` / `_STORE_LEVEL` dispatch tables rather than
  restated. This matters: `route_and_store()` sends `ORGANIZATIONAL_MEMORY`
  straight to the shared, cross-user Knowledge Center and deliberately has no
  local organizational file store. Hardcoding that design fact in the dashboard
  would have given it a second home that could silently disagree with the
  router. The organizational tile therefore reports the shared store's real
  configured/not-configured state instead of a local `0` that a reviewer would
  read as "no organizational knowledge exists".
- `GET /api/memory` (`?q=` free text, `?level=` tier, `?limit=`, `?note=` one
  note), placed alongside the other read-only GET branches. Read-only by
  design: authoring a record or a note stays CLI-only
  (`dv-harness memory add`) and the engine's own promotion write-through --
  what enters a durable knowledge tier is gated on real verification evidence,
  never on a browser form. Same reasoning as `knowledge setup` being CLI-only.
- **Honest empty state**, matching the Coverage / AMBA / Research contract:
  a project with neither store nor vault reports `available: false` and names
  BOTH paths it looked at, never a fabricated count. Neither half is
  constructed unless its directory already exists, so polling the panel never
  materializes a memory tree in a project that has none (asserted in a test).
  A store or vault that exists but cannot be read reports its real reason
  rather than a 500.

**Frontend -- the `memoryCenterCard`**, placed immediately above the Shared
Knowledge Center card so the two related-but-distinct surfaces are adjacent and
each note says which question it answers. Follows the AMBA / Research card
conventions exactly (tiles + note line + filterable table + drill-down):
per-tier tiles, an index-vs-file drift line naming
`dv-harness memory doctor` as the repair, a real vault search (free text +
tier filter whose options are populated from the wire), and click-a-row note
drill-down rendering frontmatter + body through `provider.read()`.

One documented ruling: the card is fetched **once on page load and again on
Search**, deliberately NOT joined to `load()`'s 3s poll (unlike the AMBA and
Research cards). Durable knowledge tiers change on a promotion, not per second,
and `get_active_provider()` runs a real capability probe
(`detect_obsidian_cli()`: PATH lookups plus a `--version` subprocess when a
binary is found) that has no business firing every three seconds on an HTTP
thread. This reuses the existing fetch-once convention of the Sessions and User
Info cards rather than inventing a third pattern.

## Tests

`dv_harness_tests/test_dashboard_memory_card.py` -- 8 tests, driving the REAL
dashboard server on a free local port over REAL HTTP, reusing
`test_dashboard_interactive.py`'s helpers (no second harness). Fixtures are
written through the REAL writers -- `MemoryStore.add()` for records,
`build_frontmatter_from_memory_record()` + `provider.create()` for notes -- so a
fixture that drifted from the real record/note schema fails at write time
rather than quietly proving the endpoint against a shape the real pipeline
never produces (the same convention `test_dashboard_amba_card.py` uses).

1. honest empty state when nothing exists -- **and that reading the endpoint
   creates neither store**
2. real per-tier counts, asserted equal to `index_integrity()`'s own figures
3. the organizational tier reported as shared-backed, never as a local zero
   (asserting `_locally_stored_memory_levels()` derives it, not a literal)
4. real index-vs-file **drift** surfaced (an orphan record file with no index
   row: `record_files == 2`, `index_rows == 1`, `ok is False`)
5. real vault note list + free-text search + tier filter, with per-tier vault
   counts bucketed off the notes' own frontmatter, and a no-match search
   returning empty rather than a fabricated hit
6. real single-note body read, plus honest `NOT_FOUND` for a missing note
7. unknown tier -> a real `UNKNOWN_MEMORY_LEVEL` reason, not a 500
8. the card is served AND really wired into the page (the PARTIALLY_WIRED shape
   this gap-close exists to avoid)

**Test summary:** 8/8 new tests pass; full dashboard suite
(`test_dashboard_*.py`) 94/94 pass; memory/vault-adjacent suites
(`test_memory_vault`, `test_memory_doctor`, `test_memory_tier_completion`,
`test_memory_tier_integrity_and_admission`,
`test_obsidian_memory_final_integration`, `test_cli_memory_commands`) 158/158
pass. The served page's JavaScript additionally passes `node --check`.

## Deferred / not built

- **No write path.** Authoring a memory record or a vault note from the GUI was
  not built and is not a gap left half-open -- it is a deliberate exclusion,
  stated in the card itself and in the endpoint comment, for the same reason
  `dv-harness knowledge setup` is CLI-only.
- **Wiki-link graph traversal.** `FileSystemMarkdownAdapter.search()` supports a
  `linked_to` filter and `list_links()`; the card exposes free-text and tier
  filters only. A real `[[WikiLink]]` graph view is a genuine further feature,
  not a half-built part of this one.
- Scope stayed bounded to GUI-11. The 7 PARTIALLY_WIRED items from the wider
  audit were not touched.

## Concurrency handling

`dv_harness/dashboard.py` was verified clean at start (GUI-09 `27009a3` and
GUI-10 `6e011f9` were already committed). The commit was hand-scoped:
`git diff dashboard.py > patch` -> `git apply --cached --check` -> `--cached`,
plus a path-scoped `git add` of the new test file only. One incident worth
recording: an initial `git commit --amend` (to fix a shell-mangled message)
swept in five files another concurrent pass had left STAGED
(`CLAUDE.md`, `capability_evolution.py`, `engine.py`, and two new files). That
was undone with `git reset --soft HEAD~1`, the five paths unstaged, the scoped
commit re-made, and their staged state restored byte-identically (verified:
index-vs-worktree diff empty before unstaging, and the same 165/105/456/81/580
line counts after re-adding). `--amend` takes the whole index and is therefore
NOT safe under the hand-scoped patch technique -- use `git commit <paths>` or
re-stage explicitly.
