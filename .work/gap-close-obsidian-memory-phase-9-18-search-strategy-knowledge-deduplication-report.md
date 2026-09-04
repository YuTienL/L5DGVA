# Gap-close: Phase 9 (Search Strategy) + Phase 18 (Knowledge Deduplication)

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
