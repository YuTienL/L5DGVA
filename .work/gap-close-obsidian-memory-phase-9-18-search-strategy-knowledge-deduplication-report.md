# Gap-close: Phase 9 (Search Strategy) + Phase 18 (Knowledge Deduplication)

**Date**: 2026-09-04
**Scope**: `gap-close-obsidian-memory-phase-9-18-search-strategy-knowledge-deduplication`
**Verdict**: **DONE** (Phase 9 closed for real) / **NO_ACTION_NEEDED** (Phase 18 re-confirmed READY)
**Test summary**: `pytest dv_harness_tests/test_memory_search_filters.py` -> **19 passed**;
the 11 memory suites together -> **198 passed**; `test_engine_gates_and_routing.py`
(the other real `MemoryRetriever.search()` consumer) -> **239 passed**. No pre-existing test changed.

Mode: `LOCAL_ANALYSIS` (pure local read/edit/test; no server, no VCS, no simulation).

---

## Phase 18 (Knowledge Deduplication) — NO_ACTION_NEEDED, re-confirmed READY

The audit's READY verdict was re-verified independently, not assumed:

| Claim | Re-confirmed at |
|---|---|
| Exactly the 5 spec fingerprint fields | `dv_harness/memory_dedup.py:36` — `FINGERPRINT_FIELDS = ["protocol", "failure_signature", "root_cause", "configuration", "error_pattern"]` |
| Fixed, inspectable thresholds (no learned model) | `memory_dedup.py:53-55` — `DUPLICATE_THRESHOLD = 0.90`, `UPDATE_EXISTING_ROOT_CAUSE_THRESHOLD = 0.80`, `RELATED_THRESHOLD = 0.35` |
| All four required outcomes | `_classify()` at `memory_dedup.py:195-205` returns DUPLICATE / UPDATE_EXISTING / RELATED / NEW |
| Exact-hash short-circuit | `compute_fingerprint()` at `memory_dedup.py:62-73` |
| Wired into the real write path, not a standalone library | `dv_harness/cli.py` `memory add` handler calls `classify_note_candidate()` before `provider.create()` and exits non-zero with `DUPLICATE_KNOWLEDGE` unless `--force` |
| One test per required outcome + edge cases | `dv_harness_tests/test_memory_dedup.py` — 11 tests, all named and present |

Re-ran the suites: `test_memory_dedup.py` + `test_cli_memory_commands.py` both pass inside
the 198-test memory run below. **No code change made for Phase 18.**

---

## Phase 9 (Search Strategy) — DONE, both closeable gaps closed

The audit's engine-layer READY finding was re-confirmed
(`memory_vault.FileSystemMarkdownAdapter.search()` genuinely implements exact / keyword /
tag / arbitrary YAML property / wiki-link traversal / protocol / project / memory_level /
confidence / status through one query dict, no embedding or vector DB). Both PARTIAL causes
were surface-level and boundable, so both were completed for real in this pass.

### Gap 1 — CLI surface narrower than the engine: **CLOSED**

`dv-harness memory search` previously exposed only `--protocol`, `--tag`, `--level` and free
text; `exact` / `property` / `linked_to` / `confidence` / `status` / `project` were reachable
only from the Python API, i.e. not from an agent or shell invocation at all.

**Changed** (`dv_harness/cli.py`, argparse + handler wiring only — no engine change):

```
usage: dv-harness memory search [-h] [--protocol PROTOCOL] [--tag TAG]
                                [--level {working,job,project,engineering,organizational}]
                                [--exact EXACT] [--property KEY=VALUE]
                                [--linked-to NOTE_ID] [--project PROJECT]
                                [--confidence {CONFIRMED,HIGH,MEDIUM,LOW,UNKNOWN}]
                                [--status STATUS] [--limit LIMIT]
                                [query]
```

`--property` is repeatable and AND-ed; a malformed value prints
`{"ok": false, "error": "BAD_PROPERTY_FILTER", ...}` and exits 2 rather than silently
dropping the filter.

### Gap 2 — the primary JSON `MemoryStore` search was much narrower than its vault mirror: **CLOSED**

`MemoryRetriever.search()` (`dv_harness/memory.py`) supported only `protocol` / `scope` /
`symptoms` / `text`. This matters specifically because **Working Memory is deliberately never
mirrored into the vault** (`memory_router.py`), so working-tier records were only ever
reachable through this narrower path.

Added, reusing the existing index/record structures rather than a parallel mechanism:

- **`level`** — one tier or a list of tiers (`_index_row()` already persists `level`).
- **`confidence`** — a real filter. Previously confidence only *added to the score*
  (`memory.py`'s `{"CONFIRMED":2,"HIGH":1.5,...}` bonus), so a LOW record still came back for
  a HIGH-only question.
- **`status`** — previously hardcoded to ACTIVE-only. Now defaults to ACTIVE (every existing
  caller's behavior is unchanged), accepts an explicit status (e.g. `DEPRECATED`, so
  `MemoryGC.deprecate()`'d records are reachable at all), and accepts an `ANY`/`*` sentinel
  for every status at once.
- **`property`** — arbitrary record-field dict. `_index_row()` persists only a fixed subset,
  so for a key the index row does not carry (`kind`, `subsystem`, `project`, `verified`, …)
  the full record file is read, cached at most once per candidate row. List-valued fields
  match on membership.

**Relevance-floor interaction, handled deliberately**: the 2026-08-31 finding-I2 floor drops
any record with zero query overlap, which would have emptied out a filter-only query such as
"list every engineering-tier record". An **explicitly passed** structural filter now counts
toward relevance — a record that survives an explicit filter genuinely matched a stated part
of the query, unlike a recency/confidence ranking bonus. A query passing *no* structural
filter is unaffected, and there is a test asserting the original finding-I2 guarantee still
holds (`test_the_relevance_floor_still_rejects_an_unfiltered_zero_overlap_query`).

**Deliberately NOT added to `MemoryRetriever`**: `tag` and `linked_to`. A JSON `MemoryStore`
record carries neither tags nor wiki-links (both are Markdown-note concepts owned by
`memory_vault.py`), so such a filter could only ever match nothing. Building them there would
have been dead code, not closure. This is stated in the code comment, the skill and the docs
rather than left as an unexplained asymmetry.

`python -m dv_harness.memory_cli search` gained the matching `--level` (repeatable),
`--confidence`, `--status`, `--property KEY=VALUE` and `--limit` flags.
`parse_property_filters()` / `PropertyFilterError` live in `memory.py` and are imported by
both CLIs, so the two cannot drift on how `KEY=VALUE` is spelled.

---

## Files changed

| File | What |
|---|---|
| `dv_harness/memory.py` | `parse_property_filters()` + `PropertyFilterError`; `MemoryRetriever` gains `STATUS_ANY`, `_record_field()`, `_property_matches()`, and level/confidence/status/property filtering inside `search()` |
| `dv_harness/cli.py` | `memory search`: 6 new argparse flags + handler wiring (hand-scoped patch — this file is shared with concurrently-running workflows) |
| `dv_harness/memory_cli.py` | `search`: `--level`/`--confidence`/`--status`/`--property`/`--limit` |
| `dv_harness_tests/test_memory_search_filters.py` | **new**, 19 tests |
| `docs/MEMORY_OPERATIONS.md` | stale preamble claiming "there is no dedicated `dv-harness memory ...` CLI subcommand" replaced with the real two-surface split; new search examples; `## Vault … (Python, no CLI wrapper yet)` heading corrected — a CLI wrapper now exists |
| `.claude/skills/CORE/memory-retrieval/SKILL.md` | no longer documents property/exact/linked_to as Python-API-only; records that `MemoryRetriever` is the *only* path to Working Memory |

Committed as `memory(phase-9): expose every search filter on both memory CLIs, add structural
filters to MemoryRetriever`, scoped by pathspec so concurrently-staged work from other
workflows in this tree was not swept in.

## Tests

`dv_harness_tests/test_memory_search_filters.py` — 19 tests, all against real records, real
vault notes and real CLI invocations (no parse/import smoke tests):

- `parse_property_filters` splits on the first `=` only; rejects an argument with no `=`.
- `MemoryRetriever`: unfiltered baseline unchanged; `level` (single + list); `confidence`
  filters rather than only ranking; `property` reaches `kind`/`subsystem`, which are proven
  absent from `index.json`'s rows in the test itself, so the record-file fallback is what is
  actually exercised; list-valued property membership; `status` default/explicit/`ANY`;
  a structural filter alone clears the relevance floor; an unfiltered zero-overlap query
  still returns nothing.
- `memory_cli search`: `--level`/`--confidence`/`--property` combined; `--status DEPRECATED`
  reaches a `MemoryGC.deprecate()`'d record; malformed `--property` exits 2.
- `dv-harness memory search`: `--confidence`/`--status` over real notes; `--exact` literal
  substring hit and miss; `--property` repeatable and AND-ed; malformed `--property` exits 2;
  `--linked-to` traverses a real `[[MEM-…]]` wiki-link written through the same provider;
  `--project` filters on the `project` frontmatter field.

Runs (all local, this pass):

```
pytest dv_harness_tests/test_memory_search_filters.py                      -> 19 passed
pytest <11 memory suites: search_filters, vault, dedup, cli_memory_commands,
        tier_completion, tier_integrity_and_admission, doctor, security,
        debug_flow, obsidian_final_integration, react_working_memory_bridge>
                                                                            -> 198 passed
pytest dv_harness_tests/test_engine_gates_and_routing.py                    -> 239 passed
```

## Boundaries / not done here

- **No Obsidian CLI on this machine** — every vault operation above ran through
  `FileSystemMarkdownAdapter`, the disclosed and correct filesystem fallback. This is a
  deliberate boundary, not a gap.
- **No semantic/embedding search added.** The spec forbids a vector DB, and the
  `MemoryProvider` abstract interface already keeps that door open for a future adapter.
- **`DV_MEMORY_SEARCH.ps1`** still passes only protocol/scope/symptom/text through to
  `memory_cli`. It was not in the audit's gap and was not touched; the new flags are reachable
  via `python -m dv_harness.memory_cli search` directly. Extending the PowerShell wrapper is a
  small, separate, optional follow-up, not a blocker.
