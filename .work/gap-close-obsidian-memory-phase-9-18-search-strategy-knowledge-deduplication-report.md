> This file holds TWO passes over the same scope. Pass 2 (below, current) closed
> Phase 18's write-path enforcement and Phase 9's `protocol` soft-filter. Pass 1 is
> retained verbatim in the appendix at the end: it closed a different Phase 9 gap
> (the `rg` prefilter changing results rather than only speed), and its Phase 18
> "READY, no change" verdict was right about the MECHANISM but did not examine the
> automatic write path, which the later audit this pass acted on did.

# Gap-close pass 2: Phase 9 (Search Strategy) + Phase 18 (Knowledge Deduplication)

**Scope**: Obsidian+Git/Markdown Hybrid Engineering Memory, 25-phase STRUCTURAL
spec, phases 9 and 18 only.
**Mode**: LOCAL_ANALYSIS + local code change (no server, no VCS, no simulation).
**Date**: 2026-09-04

## Verdict: **DONE**

Phase 9's ten filter types were re-confirmed READY as audited and were left
alone, with ONE bounded exception fixed (`protocol` was a soft/ranking filter
on the JSON backend). Phase 18's mechanism was READY; its production-path
enforcement was a real, closeable gap and is now closed.

**Test summary**: the two phase suites plus the new file
(`test_memory_dedup_write_path.py` 11 new + `test_memory_dedup.py` +
`test_memory_search_filters.py`) → **50 passed**; the wider
memory/vault/dedup/CLI/debug-flow/tier/doctor/security/knowledge-layer set
(12 files) → **253 passed**; the doc-mirror / doc-citation / memory-review /
research-memory-governance set → **80 passed**;
`python -m dv_harness.doc_citation_check --memory-docs` → 8 OK, 0 drifted.

---

## Phase 9 — Search Strategy: re-confirmed READY (one sub-item completed)

Re-confirmed against the source, not the audit text:

- `FileSystemMarkdownAdapter.search()` (`dv_harness/memory_vault.py`) really
  applies `exact` / `tag` / `linked_to` / `property` as HARD filters and folds
  `protocol` / `project` / `memory_level` / `confidence` / `status` into the
  same `property_filters` dict — every one of them a `continue`, not a score
  bonus. Free text is tokenized overlap. `rg` is a candidate prefilter only,
  and every filter still re-parses real frontmatter in Python.
- `MemoryRetriever.search()` (`dv_harness/memory.py`) really applies
  `level` / `confidence` / `status` / `property` as hard filters, with the
  documented `ANY`/`*` status sentinel and the finding-I2 relevance floor.
- Both CLI surfaces are real: `dv-harness memory search --protocol --tag
  --level --exact --property --linked-to --project --confidence --status
  --limit`, and `python -m dv_harness.memory_cli search ...`.
- No embedding/vector DB anywhere, as the spec allows. `MemoryProvider` is a
  real ABC and `HybridMemoryProvider` already dispatches per call across two
  implementations, so an embedding-backed adapter remains a drop-in third.

**The one sub-item completed** — the audit flagged it inside an otherwise-READY
phase, and it was small and boundable, so it was fixed rather than left:

`MemoryRetriever.search()`'s `protocol` was a RANKING signal only (`+3`
relevance). It therefore excluded a non-matching record only when nothing else
in the query cleared the relevance floor: `--protocol USB3 --level engineering`
returned every engineering-tier record regardless of protocol, while the vault
mirror's own `search()` has always treated `protocol` as a hard filter. It is
now a hard filter on both backends (`dv_harness/memory.py`,
`MemoryRetriever.search()`), keeping its `+3` ranking weight so a
protocol-only query still clears the floor. A record with NO protocol is also
no longer matchable by the literal string `"None"` (the old code compared
`str(row.get("protocol",""))`, which renders `None` as `"None"`).

`scope` deliberately stays a ranking signal: it is not one of the spec's named
filter types, and the vault side has no scope filter either. That asymmetry is
now stated in the code rather than left to be rediscovered.

## Phase 18 — Knowledge Deduplication: PARTIAL -> DONE

**Mechanism (re-confirmed READY, unchanged)**: `dv_harness/memory_dedup.py`
computes the spec's exact 5-field fingerprint, treats `protocol` as a hard gate
and the other four as a weighted Jaccard similarity with an exact-hash
short-circuit, and produces all four required classes
(NEW / RELATED / DUPLICATE / UPDATE_EXISTING).

**The gap that was real**: the gate had exactly one caller —
`dv-harness memory add`. `memory_router._maybe_write_vault_note()`, the
automatic write-through that `route_and_store()` runs on every real
ENGINEERING_MEMORY / JOB_MEMORY / PROJECT_MEMORY / ORGANIZATIONAL_MEMORY
promotion (i.e. the path engine.py's RE_AUDIT-PASS/promotion flow actually
uses, and the only path that has ever populated this project's vault), decided
create-vs-update from `provider.read(note_id)` alone. That catches a re-write
of the SAME `memory_id` and nothing else, so a second record with a new id but
the same root cause minted a second note — the spec's own
`USB3_LFPS_issue1/issue2/issue3` shape.

### What was built

`dv_harness/memory_router.py` — the gate now runs on the CREATE path (never on
the same-`memory_id` update path, where a record updating its own note is not a
duplicate of anything):

- **NEW** -> the note is created, exactly as before.
- **RELATED** -> the note is created AND real `[[WikiLink]]`s to the notes it
  overlaps with (at or above `memory_dedup.RELATED_THRESHOLD`) are written into
  its `Related Knowledge` section. This is what makes
  `dv-harness memory search --linked-to` reach auto-written notes at all —
  before this, only hand-authored notes carried links.
- **DUPLICATE / UPDATE_EXISTING** -> no second note. The candidate is folded
  into the matched note by APPENDING one recurrence line to that note's
  `Related Knowledge`. Append-only, into that one section: no existing section
  content is ever rewritten, so the absorbing note cannot lose the root
  cause/fix an earlier run or a human put in it. The line carries the real
  `memory_id` (the per-tier JSON record is still written and is still the
  system of record — a fold that dropped the id would deduplicate the
  knowledge by destroying its traceability), and UPDATE_EXISTING additionally
  carries the candidate's own configuration/symptom, bounded to 240 chars,
  because that difference IS the new knowledge. Re-running the same record
  finds its own line and re-commits nothing.
- `vault_write` now carries `dedup_classification` plus either
  `note_created: true` or `folded_into: <note_id>`, so a skipped create is
  visible in `route_and_store()`'s result rather than silent. A fold's git
  commit SHA still flows into `_write_back_knowledge_commit_sha()`.
- A dedup failure never blocks the write: an unclassifiable candidate is
  written normally. Real verified knowledge must never be lost to a dedup
  problem.

`dv_harness/memory_dedup.py`:

- `_extract_note_fields()` -> public `extract_note_fields()`, because the
  router now builds its candidate through it. Candidate and corpus must be
  derived by ONE function, or the gate compares a note against a
  differently-shaped version of itself.
- `classify_note_candidate(..., memory_levels=...)` and
  `DEDUP_SCOPE_MEMORY_LEVELS`; `_iter_dedup_scope_notes()` now reads the folder
  layout from `memory_vault._MEMORY_LEVEL_FOLDER` instead of a second
  hand-maintained copy of it.

### Two scope decisions worth stating, both proven by a test

1. **Only ENGINEERING_MEMORY / ORGANIZATIONAL_MEMORY are gated.** Those are the
   two tiers `memory_dedup` compares against. A JOB_MEMORY or PROJECT_MEMORY
   note is inherently per-run/per-project, so folding one into an Engineering
   note would erase a separately-scoped record rather than deduplicate reusable
   knowledge. Two identical job records still produce two job notes.
2. **The comparison corpus is restricted to the candidate's OWN tier.** An
   Engineering -> Organizational promotion writes the same knowledge a second
   time BY DESIGN; compared across tiers it is a textbook DUPLICATE of its own
   engineering note, and a tier-blind gate would have folded every promotion
   back into Engineering and made the Organizational tier unwritable. This was
   found while building, not after — the test
   `test_an_organizational_candidate_is_not_folded_into_its_own_engineering_note`
   holds it.

### Tests (new file: `dv_harness_tests/test_memory_dedup_write_path.py`, 11)

Every test drives the REAL `route_and_store()` against a REAL vault on disk and
asserts what is on the filesystem afterwards — never that the classifier merely
returned a string.

- a duplicate promotion folds into the note already on file (one note on disk,
  `folded_into` set, the absorbing note names the absorbed `memory_id`, the
  JSON record is still written)
- folding the same record twice appends only one recurrence line
- UPDATE_EXISTING extends the note with the new configuration and symptom
- a fold never overwrites the absorbing note's own Root Cause / Fix / Evidence
- a different protocol is never folded and gets its own note
- a RELATED candidate creates its own note and wiki-links the overlap — proven
  by a real `provider.search({"linked_to": ...})` finding it
- the gate never fires for Job or Project memory
- an organizational candidate is not folded into its own engineering note
- a re-write of the same `memory_id` still updates its own note
- a dedup failure never stops the note from being written
- (Phase 9) `protocol` filters rather than only ranks, alongside another filter

### Docs

- `docs/MEMORY_ARCHITECTURE.md` — new subsection "Knowledge deduplication
  before a note is created", covering the four classifications, the
  append-only fold, the tier restriction, and the result keys.
- `CLAUDE.md` — one paragraph in the Engineering Memory Policy section, since
  that is the always-resident file a future agent reads.
- `.claude/agents/memory-agent.md` — the "Deduplicate" bullet was stale the
  moment this change landed: it told the agent that paraphrased `root_cause`
  wording is something the dedup path "cannot catch" and must be merged by
  hand. It now names both real gates (the JSON store's exact-match confirm,
  and the vault note's similarity gate) and narrows the manual case to what is
  genuinely still manual (a Corner Case Library entry, a JSON-record merge).
- `docs/MEMORY_ARCHITECTURE.md` / `docs/MEMORY_SCHEMA.md` — three `file:line`
  citations repaired that my own line-number shifts had drifted;
  `python -m dv_harness.doc_citation_check` now reports 8 OK, 0 drifted.

## What was NOT done, and why

- No embedding/vector index was added. The spec explicitly allows string/set
  similarity here, and the existing `MemoryProvider` ABC keeps that door open.
- `scope` was not converted to a hard filter (see Phase 9 above).
- No new config knob was added for the dedup gate. The whole vault
  write-through is already gated on `cfg`, and `cfg={}` still opts out of every
  cfg-driven additive behaviour at once.

---

# Appendix - Pass 1 report (2026-09-04, earlier this session), retained verbatim

**Date**: 2026-09-04
**Scope**: Obsidian+Git/Markdown Hybrid Engineering Memory, 25-phase structural spec, phases 9 and 18 only.
**Execution mode**: LOCAL_ANALYSIS (pure local read + local pytest; no server, no VCS, no simulation).

## Verdict

**DONE** — one real gap found and closed in Phase 9. Phase 18 confirmed READY with no change.

The incoming audit reported both phases READY. Re-confirming its cited evidence surfaced one
claim in it that was **false**, and the falsity was a real defect in shipped behavior, not a
documentation slip.

---

## Phase 18 — Knowledge Deduplication: **READY** (no change made)

Every cited item re-verified against the current file, no edits:

- `FINGERPRINT_FIELDS` is exactly the spec's 5 fields — `dv_harness/memory_dedup.py:36`.
- `compute_fingerprint()` — per-field token sets + normalized SHA256 exact-match hash,
  `memory_dedup.py:62-73`.
- `_jaccard()` scores empty∩empty as `0.0`, not `1.0`, so two sparse records cannot falsely
  inflate — `memory_dedup.py:76-85`.
- `_similarity()` weighted over 4 fields (`root_cause` .35 / `failure_signature` .30 /
  `error_pattern` .20 / `configuration` .15) — `memory_dedup.py:108-118`; `protocol` is a hard
  gate rather than a weighted term — `memory_dedup.py:152,167-169`.
- All four buckets in `_classify()` — `memory_dedup.py:195-205`.
- Scope restricted to Engineering+Organizational — `_iter_dedup_scope_notes()`,
  `memory_dedup.py:121-130`.
- Wired into the real write path, not merely a library: `dv-harness memory add` classifies first
  and refuses a `DUPLICATE` without `--force` — `dv_harness/cli.py:2056-2062` (re-read this
  session, still present and still ahead of the `provider.create()` call).

`pytest dv_harness_tests/test_memory_dedup.py` — all 11 tests pass, covering all four
classification outcomes, the protocol hard-gate, the tier-scope restriction, the no-protocol broad
comparison, and `exclude_note_id`.

No gap. Nothing rebuilt.

---

## Phase 9 — Search Strategy: was PARTIAL, now **READY**

All 10 required filter/search types exist and are wired end-to-end as the audit described —
`FileSystemMarkdownAdapter.search()` (`dv_harness/memory_vault.py:813+`), CLI flags at
`dv_harness/cli.py:887-909` with dispatch at `cli.py:2019-2042`, JSON-store equivalents at
`dv_harness/memory.py:425-450`, `parse_property_filters()` shared by both CLIs at
`memory.py:54-68`. Those were all re-confirmed and left untouched.

### The gap: `rg` was a second, undeclared filter, not an accelerator

`FileSystemMarkdownAdapter`'s own docstring claimed `rg` is "used only as a candidate-file
prefilter ... so a missing/broken `rg` never changes correctness, only speed", and the incoming
audit repeated that claim. **It was not true.** `_candidate_paths()` passed the whole free-text
query to `rg -F` as one contiguous literal pattern, and it did so whenever any text was present,
including when text was combined with a structural filter.

Because `rg` **is** installed in this environment (`/c/Users/.../WinGet/Links/rg`), the shipped
behavior on this machine was the broken one. Measured directly against a real two-note vault,
before the fix:

| query shape | with `rg` (real behavior here) | without `rg` (correct) |
|---|---|---|
| `{"text": "underrun descriptor"}` | `[]` | `['MEM-A', 'MEM-B']` |
| `{"text": "underrun", "protocol": "USB3"}` | `['MEM-A']` | `['MEM-A', 'MEM-B']` |
| `{"text": "underrun", "tag": "usb3"}` | `['MEM-A']` | `['MEM-A', 'MEM-B']` |
| `{"text": "underrun"}` | `['MEM-A']` | `['MEM-A']` |
| `{"exact": "lfps underrun"}` | `['MEM-A']` | `['MEM-A']` |

Two independent defects:

1. **Multi-word keyword search returned nothing.** The Python scorer matches by TOKEN OVERLAP
   (`memory_vault.py:828,851-853`), but the prefilter demanded the entire phrase appear
   contiguously. Any multi-word query — the normal way an engineer searches, and the exact shape
   `CLAUDE.md`'s own Engineering Memory Policy prescribes
   (`memory_cli search --text <symptom>`) — silently returned zero notes.
2. **Text plus a structural filter dropped filter-only matches.** A note matching a
   `tag`/`property`/`protocol`/`linked_to` filter alone still scores above the relevance floor
   (`memory_vault.py:849-852` awards 3.0/2.0 for structural matches independent of text) and must
   be returned; the prefilter removed it for not containing a query token.

This is a genuine, closeable Phase 9 gap — the "Keyword search" requirement was not met on any
machine with ripgrep installed — and it was small and boundable, so it was closed in this pass.

Why it went unnoticed: the pre-existing coverage,
`test_filesystem_adapter_search_degrades_correctly_without_rg`
(`dv_harness_tests/test_memory_vault.py:427`), uses a **single-token** query, which is the one
shape of the five that never diverged.

### The fix

`dv_harness/memory_vault.py`:

- `_candidate_paths(text_q, exact_q, text_is_mandatory)` replaces `_candidate_paths(term)`. It now
  narrows only on terms that are **mandatory constraints on the result**:
  - `exact` is a hard `continue` in `search()` and always prefilters. `rg -i` against a
    case-SENSITIVE Python check makes it deliberately over-inclusive — the safe direction, since
    Python still rejects and `rg` can never over-prune.
  - free text prefilters as the **union** of its tokens (one `-F -e` per token), and only when no
    structural filter accompanies it.
  - otherwise, full scan.
- `search()` computes `structural_filter` once and passes `text_is_mandatory=not structural_filter`
  (`memory_vault.py:824-827`); `any_filter` is now derived from it rather than recomputing the same
  disjunction.
- The class docstring's false "never changes correctness" claim is corrected to state the actual
  invariant and point at the method that maintains it (per this project's comment-hygiene rule —
  the stale claim is removed, not merely supplemented).

No public interface changed; `_candidate_paths` has exactly one caller (verified repo-wide).

### Tests

9 new tests in `dv_harness_tests/test_memory_search_filters.py` (section 4). Each runs the same
query twice — once with `rg` available, once with `shutil.which` forced to `None` — and asserts the
two results are **equal**, so the accelerator can never again change what a search means:

- `test_multi_word_text_query_matches_on_token_overlap_not_a_literal_phrase`
- `test_text_combined_with_a_property_filter_does_not_drop_filter_only_matches`
- `test_text_combined_with_a_tag_filter_does_not_drop_filter_only_matches`
- `test_text_combined_with_a_linked_to_filter_does_not_drop_filter_only_matches`
- `test_single_token_text_query_still_narrows_and_agrees_both_ways`
- `test_exact_query_still_narrows_and_agrees_both_ways`
- `test_exact_query_prefilter_survives_a_case_difference`
- `test_stopword_only_text_query_agrees_both_ways`
- `test_the_rg_prefilter_is_actually_exercised_when_it_is_sound`

The last one matters: result-parity alone would also pass if the fix simply disabled `rg`
entirely. It counts real `parse_note_markdown` calls and asserts a third, non-matching note was
excluded from the parsed candidate set — proving the accelerator is still doing its job.

All 5 behavioral tests were confirmed **failing before** the fix and passing after.

---

## Test summary

`pytest dv_harness_tests/test_memory_search_filters.py test_memory_dedup.py test_memory_vault.py -q`
→ **88 passed** (was 79 pre-change: 30 in the two phase suites, plus test_memory_vault.py).

Full memory-keyword suite (`pytest dv_harness_tests/ -k memory`) → **277 passed, 2 failed**,
against a pre-change baseline of **268 passed, 2 failed** on the same selection. The +9 is exactly
the new tests; the 2 failures are the same pre-existing pair both before and after (see below).

Remaining memory suites that exercise the vault adapter
(`test_cli_memory_commands.py test_memory_doctor.py test_memory_security.py
test_obsidian_memory_final_integration.py test_debug_flow_memory.py`) → **83 passed**.

## Out of scope, reported not fixed — **NEEDS_SEPARATE_EFFORT**

`dv_harness_tests/test_doc_citation_check.py` has 2 failing tests, **pre-existing and unrelated**:

```
DRIFT  docs/MEMORY_ARCHITECTURE.md:90   cites memory_router.py:571  -> really 91, 445, 578
DRIFT  docs/MEMORY_ARCHITECTURE.md:189  cites memory.py:783-789     -> really 840
DRIFT  docs/MEMORY_SCHEMA.md:58         cites memory.py:576         -> really 633
```

Confirmed identical before and after this pass's change (`python -m dv_harness.doc_citation_check
--memory-docs`, run both ways: 3 drifted in each case, none in `memory_vault.py`). The drift is in
`memory.py` / `memory_router.py` line numbers, moved by other concurrent workflows still editing
those two files this session. Correcting the citations now would race those edits and be stale
again on their next commit, so it is left for a pass taken after they land.

## Commit

`24c0870` — `memory(search): rg prefilter must never change results, only speed`.
Exactly two files: `dv_harness/memory_vault.py` (+42/-11) and
`dv_harness_tests/test_memory_search_filters.py` (+127). No shared file under concurrent edit
(`cli.py`, `memory.py`, `memory_router.py`, `memory_dedup.py`, `CLAUDE.md`) was touched — each was
re-checked with `git status` and confirmed to need no change for this scope.

## Boundaries and non-actions

- No Obsidian CLI is installed; `ObsidianAdapter` correctly reports `NOT_AVAILABLE` with a named
  fallback (`memory_vault.py:738-747`) and the `FileSystemMarkdownAdapter` filesystem path carries
  every phase-9 capability. That is the disclosed, deliberate boundary — left as-is, correct.
- No embedding/vector DB in either phase, deliberately (`memory_vault.py:79-83`,
  `memory_dedup.py:19-24`) and per the spec's own instruction. `MemoryProvider` is an ABC and
  `HybridMemoryProvider` already dispatches per call, so a future embedding adapter slots in behind
  the same `search(query, limit)` contract without an interface break. Not a gap.
- `MemoryRetriever.search()` deliberately omits `tag`/`linked_to` (`memory.py:431-435`) because
  MemoryStore records carry neither concept. Architecturally correct, not a gap. Left as-is.
- No remote/credentialed execution was needed or attempted.
