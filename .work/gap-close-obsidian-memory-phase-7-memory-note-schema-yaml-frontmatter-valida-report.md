# Gap-close: Phase 7 — Memory Note Schema (YAML frontmatter + validation)

**Status: DONE**

**Commit**: `99c8641` — `memory(_general): give a protocol-less note the _general key, and repair the notes already on disk`
(branch `gap-close/env-manifest-fact-sources`; no push, no merge to `main`/`master`).

**Test summary**: 96 passed across `test_memory_vault.py` (53, incl. 4 new) /
`test_memory_doctor.py` (20) / `test_memory_docs_mirror_source.py` /
`test_cli_memory_commands.py`; a wider sweep over
`test_cli_memory_commands + test_memory_dedup + test_memory_search_filters +
test_memory_docs_mirror_source + test_memory_tier_completion +
test_obsidian_memory_final_integration + test_debug_flow_memory` also passed
113/113.

---

## What the audit found, and what I did with each half

### Re-confirmed as already real (no action)

Every READY-shaped claim in the audit was re-verified before touching anything:

- Schema constants are real and gating — `dv_harness/memory_vault.py:128`
  (`MEMORY_NOTE_REQUIRED_FIELDS`), `:158-161` (`MEMORY_NOTE_OPTIONAL_FIELDS`),
  `:178-180` (`MEMORY_NOTE_SPEC_RECOMMENDED_FIELDS`), `:191-194`
  (`MEMORY_NOTE_BODY_SECTIONS`).
- Validators enforce rather than merely report — `validate_note_frontmatter()`,
  `validate_note_body_sections()`, `validate_note()`, with
  `FileSystemMarkdownAdapter.create()`/`.update()` baking `schema_status` into
  the frontmatter actually written to disk.
- `memory_doctor.check_schema()` really runs both halves over every real note.
- The 10 pre-existing dedicated schema/validator tests still pass.

### Gap 1 — 7 gating fields vs. the spec's literal 16: **left as-is, deliberately**

This is a documented, in-code design decision (`memory_vault.py:150-180`), not
an oversight, and all 16 fields *are* checked — 7 gate `schema_status`, 9 are
reported as `missing_recommended` and surfaced by
`dv-harness memory doctor`/`validate`. Gating on `rtl_sha`/`vip_vendor` would
make every genuine harness-engine or process lesson permanently PARTIAL. Per
the task's own instruction not to downgrade a better existing architecture to
match spec wording literally, I did not change it.

### Gap 2 — 0 of 9 live vault notes passed validation: **closed for real**

This was the boundable half, and it turned out to be a genuine code
inconsistency, not merely dirty data.

**Root cause found.** `build_frontmatter_from_memory_record()` wrote
`protocol: mem.get("protocol")` → `null` for a record that legitimately names
no protocol. But every *other* step of the same write path already had an
honest answer for exactly that case, the registered `_general` key:

- `memory_router.py:696` — `_build_vault_commit_message()`:
  `protocol = mem.get("protocol") or "_general"`, so the vault commit that
  captured `MEM-0953BEC4D8` literally said `memory(_general): ...` while the
  note it committed said `protocol: null`.
- `memory_router.py:278,293,914-915` — `_maybe_share()` pushes the same record
  to the shared Knowledge Center under `_general`.
- `memory.py:973-974` — `SharedKnowledgeMemoryStore.add()` does the same.
- `config.py:70-73` — `_general` is a real registered
  `knowledge_center.categories` entry, not an invented sentinel.

Verified against the real records: all 30 engineering-tier JSON records except
`MEM-7A4F454771` (`USB2`) carry no `protocol` at all — they are `scope:
engine`/`process`/`architecture` harness lessons. So the notes were not missing
data; the mapper was discarding an answer the rest of the pipeline already used.

**Two changes:**

1. `memory_vault.GENERAL_PROTOCOL = "_general"` (new constant, `:130-147`), used
   by `build_frontmatter_from_memory_record()` (`:1240` area) as the `protocol`
   value when the record names none. The source record is never rewritten — the
   fallback belongs to the note. Tags still derive from the record's own
   protocol, so `_general` does not become a contentless tag on every note.

2. `memory_vault.resync_notes_from_memory_store()` + `dv-harness memory
   resync-notes [--note-id ...]` (`cli.py:1038-1046`, `cli.py:2333-2336`).
   Fixing the mapper cannot fix a note already on disk: a note is a mirror, and
   nothing re-derives it until its record is written again. The resync
   re-renders notes from the durable MemoryStore records through the same
   mapper the real write path uses — the same repair relationship
   `python -m dv_harness.memory_cli reindex` already has to `index.json`.
   It invents nothing: a note whose record is gone (`NO_SOURCE_RECORD`) or
   whose `memory_level` names no tier (`UNKNOWN_MEMORY_LEVEL`) is reported
   under `skipped` and left byte-for-byte untouched. Exits 2 if any note is
   still PARTIAL afterwards.

## Real evidence, run on the live vault

Before:
```
$ python -m dv_harness memory doctor
schema.status: PARTIAL | complete_count: 0 | partial: 9
first partial: {"note_id": "MEM-0953BEC4D8", "missing_required": ["protocol"],
                "missing_sections": [], "body_out_of_order": false}
```

Repair:
```
$ python -m dv_harness memory resync-notes
"repaired": ["MEM-0953BEC4D8","MEM-39D26913D7","MEM-3A1B305C69","MEM-45A3DEAE45",
             "MEM-809B74A548","MEM-8E2A6EAC7D","MEM-ACB5537F4C","MEM-E56E11470A",
             "MEM-FBE07D023A"],
"skipped": [], "still_partial": []          EXIT=0
```

After:
```
$ python -m dv_harness memory doctor
schema.status: READY | complete_count: 9 | partial: 0
vault_writable READY | git READY | filesystem_fallback READY | schema READY |
duplicate_ids READY | invalid_yaml READY | broken_links READY |
large_files READY | secrets READY | memory_store_index READY
obsidian_cli PARTIAL  <- the deliberate, disclosed boundary (CLI not installed)

$ python -m dv_harness memory search --protocol _general --limit 20
hits: 9      (previously unreachable: null matches no filter)
```

`MEM-0953BEC4D8.md` on disk now reads `protocol: _general`,
`schema_status: COMPLETE`.

## Tests written (4 new, all real behavior)

In `dv_harness_tests/test_memory_vault.py`:

- `test_build_frontmatter_uses_the_general_protocol_key_for_a_protocol_less_record`
  — mapper fills `_general`, validates COMPLETE, does **not** add it as a tag;
  a record naming `USB3` keeps `USB3` and still tags `usb3`.
- `test_route_and_store_writes_a_schema_complete_note_for_a_protocol_less_record`
  — end-to-end through the **real** `route_and_store()`, not the mapper alone:
  the note on disk says `schema_status: COMPLETE` and re-validates COMPLETE
  after being re-parsed from the file.
- `test_resync_notes_repairs_a_legacy_protocol_null_note_from_its_source_record`
  — writes a real note the pre-fix way (`protocol: null`, PARTIAL), asserts it
  really validates PARTIAL on `protocol`, resyncs, asserts COMPLETE with the
  body preserved, and asserts the **source record was not rewritten**.
- `test_resync_notes_preserves_a_real_protocol_and_never_invents_one`
  — a USB2 note keeps USB2; an orphan note with no MemoryStore record is
  reported `NO_SOURCE_RECORD` and its file is byte-identical afterwards.

## Docs / comment hygiene

- `docs/MEMORY_SCHEMA.md` — documents the `_general` fallback (with the
  measured defect it closes and why it is not a fabricated protocol name) and
  adds a "Repairing a note left PARTIAL by an older mapper" section for
  `resync-notes`. The doc-mirror guard
  (`test_memory_docs_mirror_source.py`) still passes.
- `memory_vault.py:121-127` — the `MEMORY_NOTE_REQUIRED_FIELDS` comment said a
  note "that cannot say WHICH protocol" is not reusable knowledge; that wording
  became inaccurate once "applies to no particular protocol" got its own value,
  so it was corrected rather than left stale.

## Boundaries left standing (correct as-is)

- `obsidian_cli: PARTIAL` — Obsidian CLI is genuinely not installed; the
  filesystem adapter is the real write path. Deliberate, disclosed fallback.
- The 7-vs-16 gating decision (Gap 1 above) — deliberate and documented.
- No JSON Schema artifact under `dv_harness/schemas/`; the schema is Python
  constants that the real write path and the doctor both consume, and the docs
  are held to those constants by a test. Adding a parallel JSON file would be a
  second place to be wrong, not a closure.

## Concurrency discipline

`git status` was checked before every edit. The four files touched
(`dv_harness/memory_vault.py`, `dv_harness/cli.py`,
`dv_harness_tests/test_memory_vault.py`, `docs/MEMORY_SCHEMA.md`) carried no
other agent's changes; `git diff --cached --stat` confirmed the commit contains
exactly those four and nothing else. Nothing under `.dv-harness/memory/`
(records) was modified; the repaired vault notes live under the gitignored
`.dv-harness/vault/` and are local data, not part of the commit.

Note: two `test_memory_doctor.py` git tests failed transiently during this pass
purely because I had two `pytest` processes running concurrently against git;
both pass 20/20 when the file is run alone, and again in the final 96-test run.
