---
name: memory-link
description: 建立與追蹤 DV-Knowledge Vault 筆記間的 [[WikiLink]] 關聯圖（forward links/backlinks），讓相關 finding/memory 可被追溯而不需重新搜尋。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# memory-link
建立與追蹤 DV-Knowledge Vault 筆記間的 `[[WikiLink]]` 關聯圖（forward links/backlinks），讓相關 finding/memory 可被追溯而不需重新搜尋。

核心原則：Memory is prior knowledge, not current evidence -- a link only says two records are related, never that one confirms the other.

## Mechanics (2026-09-03, real wiring)

**Purpose**: turn the DV-Knowledge Vault (`dv_harness/memory_vault.py`)
from a flat set of notes into a real graph -- a promoted record's "Related
Knowledge" section already carries `[[SOURCE_ID]]` links back to whatever
finding/prior memory it was derived from
(`build_sections_from_memory_record()`), and this skill is how an agent
reads and extends that graph deliberately, not by accident of prose.

**Inputs**: a `note_id` (e.g. `MEM-ABCDEF0123`, `NOTE-1234567890`, or a
`ccl_id`) to link FROM or traverse links FOR.

**Outputs**:
- `list_links(note_id)` -> `{"ok": true, "note_id", "forward_links": [...],
  "backlinks": [...]}` -- forward_links are every `[[OTHER_ID]]` found in
  this note's body; backlinks are every OTHER note in the vault that links
  TO this one. Both are computed live from real file content, never cached
  separately from it.
- `search({"linked_to": note_id})` -> every note that links to `note_id`
  (same data as `backlinks`, reachable through the general search API).

**Preconditions**: both notes must already exist in the vault
(`FileSystemMarkdownAdapter._find_note_path()` resolves by sanitized
filename first, then by frontmatter `id` for a hand-renamed file).

**Execution Steps**:
1. Get the active provider: `provider = dv_harness.memory_vault.get_active_provider(root, cfg)`.
2. To add a link: `provider.update(note_id, sections_patch={"Related Knowledge":
   "- [[OTHER_NOTE_ID]]\n- existing text..."})` -- a `sections_patch` only
   overwrites the named section (`_body_to_sections()` preserves every
   other section untouched), so append to the section's existing content
   rather than replacing it outright.
3. To traverse: `provider.list_links(note_id)` for both directions in one
   call, or `provider.search({"linked_to": note_id})` to reuse the general
   search/filter machinery (combine with `protocol`/`tag`/`property`
   filters in the same call).
4. Link a NEW promotion to its source automatically by populating
   `source_finding_id` / `source_engineering_memory_id` on the record
   passed to `route_and_store()` -- `build_sections_from_memory_record()`
   already turns either into a `[[...]]` link with no extra step required.

**Fallback**: a note with no links yet shows `"Related Knowledge":
"_None linked yet._"` (the render placeholder) -- `list_links()` still
returns cleanly with empty lists, never an error.

**Evidence Requirements**: link only records that are ACTUALLY related
(same root cause family, a promotion's real source, a corner case's real
resolution) -- a link is a traceability aid, not evidence that either note
is correct; the linked note's own status/confidence still apply
independently (see `memory-confidence-gate`).

**Failure Conditions**: linking to a `note_id` that does not exist creates
a dangling reference invisible to `list_links()` (it only scans real
`[[...]]` occurrences in body text, it does not validate targets exist at
write time) -- verify the target note_id is real before writing the link,
and periodically `search()` for suspiciously-named links if migrating/
renaming notes.

**Example**:
```python
from dv_harness.memory_vault import get_active_provider
provider = get_active_provider(root, cfg)
provider.list_links("MEM-ABCDEF0123")
# -> {"ok": True, "note_id": "MEM-ABCDEF0123",
#     "forward_links": ["FINDING-2026-09-03-017"],
#     "backlinks": ["MEM-9988776655"]}
```
