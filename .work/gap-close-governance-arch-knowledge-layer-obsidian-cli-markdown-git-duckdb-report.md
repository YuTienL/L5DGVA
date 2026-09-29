# Gap Close — Governance Architecture, Knowledge Layer (Obsidian CLI / Markdown+Git / DuckDB)

**Date**: 2026-09-04
**Scope**: exactly the Knowledge Layer box of the layered governance diagram and the three
sub-boxes drawn inside it. Nothing else was touched.

## Status: **DONE** (2 of 3 sub-findings closed) + **NO_ACTION_NEEDED** (1 of 3, correctly deferred)

| Sub-finding | Audit verdict | Outcome |
|---|---|---|
| 1. Obsidian CLI | PARTIALLY_REAL (real probe, deliberately zero operational wiring) | **NO_ACTION_NEEDED** — intentional, disclosed deferred state; closing it is an environment decision, not a wiring fix |
| 2. Markdown / Git | REAL_BUT_DISCONNECTED | **DONE** — config→code edge activated, live vault is now genuinely git-backed |
| 3. DuckDB | ASPIRATIONAL for the Knowledge Layer | **DONE** — real read edge wired from `memory_vault` to `evidence_db`'s `failure_signatures` |

**Test summary**: 12/12 new connection tests pass
(`dv_harness_tests/test_knowledge_layer_git_and_duckdb.py`); the full memory + evidence-db suite
(13 files, 234 tests) passes with 0 failures.

---

## Re-confirmation of the audit's evidence (done independently, before any change)

Every cited fact was re-checked live rather than trusted:

- `where obsidian-cli` / `where obsidian` — both fail on this machine.
  `detect_obsidian_cli()` returns `{"installed": false, ..., "status": "PARTIAL"}`, exactly matching
  the module's own claim.
- `'memory' in json.load(.dv-harness/config.json)` → **False**. No `memory` key at all, so
  `config.py:111`'s opt-in `git_enabled: False` default was what the live vault actually ran on.
- `.dv-harness/vault/.git` → **did not exist**. `git log --all -- .dv-harness/vault` from the repo
  root → **empty**. `git check-ignore .dv-harness/vault/` → **no match** (untracked *and* not
  ignored). 9 real Markdown notes existed on disk under
  `.dv-harness/vault/06_Agent_Memory/Engineering/`, versioned by nothing.
- `import duckdb` → 1.5.5 real and installed; `evidence_db.default_db_path(root)` →
  `.dv-harness/evidence/evidence.duckdb`, **does not exist** on this project yet.
- `grep duckdb` across `memory_vault.py` / `memory_router.py` / `memory.py` / `knowledge_center.py`
  → **zero matches**, confirming the Knowledge Layer had no DuckDB implementation of any kind.

The audit was accurate on all three points.

---

## 1. Obsidian CLI — NO_ACTION_NEEDED (correctly deferred, not an oversight)

Not closed, deliberately. Three reasons, in order of weight:

1. **It is a disclosed design decision, not a forgotten wire.** `memory_vault.py`'s
   `ObsidianAdapter` docstring states outright that this codebase has never observed a real
   `obsidian-cli`'s command syntax, and that wiring `search`/`create`/`update` against a guessed
   contract "would risk silently fabricating results". `detect_obsidian_cli()`'s docstring goes
   further and explains why `status` stays `PARTIAL` even when a binary *is* found — "a truthful
   `installed: True` at the detection layer is NOT the same claim as 'this adapter can perform real
   operations against it'".
2. **Closing it requires a machine that has the CLI.** The named fix is to capture a real release's
   `--help` contract and wire real `subprocess.run` calls to it. There is no `obsidian-cli` on this
   machine (re-confirmed above), so any implementation written here would be unverifiable
   guesswork — precisely what CLAUDE.md's Evidence Truth Rule forbids, and precisely the failure
   mode the existing docstring names.
3. **Nothing is degraded by its absence.** `HybridMemoryProvider._dispatch()` falls through to the
   fully-functional `FileSystemMarkdownAdapter` on every call, and the module's design guarantees
   the memory system never blocks on Obsidian's absence (PARTIAL, never BLOCKED).

The honest description of this box is "a real capability probe with an explicit, documented refusal
to fabricate operations", which is what the code already both is and says it is. **No file was
modified for this sub-finding.**

---

## 2. Markdown / Git — DONE

### What was actually broken

The code→git edge was real and tested. The **config→code edge that activates it for this project
did not exist**: `.dv-harness/config.json` had no `memory` block, so the live vault silently
inherited `git_enabled: False`. Result: 9 real memory notes, versioned by neither the vault's own
git (no `.git`) nor the parent repo (untracked). "Real git-commit-backed markdown notes", as drawn,
was simply not true here.

### What changed

**`.dv-harness/config.json`** — added the explicit `memory` block with `git_enabled: true` (the
whole block is spelled out rather than relying on `load_config()`'s one-level merge, so a human
reading the file sees the real settings):

```json
"memory": { "provider": "hybrid", "vault_path": "", "obsidian_cli": "auto", "git_enabled": true }
```

`config.py`'s coded default was left at `False` on purpose. Its own comment documents a real,
measured regression: defaulting it True makes every `route_and_store()` call `git init`+commit
inside the vault, and on Windows `shutil.rmtree()` of a directory containing a git tree raises
PermissionError on git's read-only object files — that broke 10 pre-existing tests. Opt-in-per-
project is the correct design; **this project simply had never opted in**. That is what changed.

**`.gitignore`** — added `.dv-harness/vault/`. The vault is now its own git repository, and it was
previously untracked-but-not-ignored (verified with `git check-ignore` *before* adding the line, so
nothing is being untracked by it). Leaving it merely untracked would let a `git add -A` embed it in
the parent repo as a bare gitlink — a commit pointing at a SHA no clone can resolve. This follows
the reasoning already written into that file's own `.dv-harness/` runtime-state block.

### Real evidence that the edge now carries traffic

Activated through the real code path (`get_active_provider()` → `FileSystemMarkdownAdapter.__init__`
→ `_ensure_git_repo()`), not by hand-running `git init`:

```
merged git_enabled: True
provider: HybridMemoryProvider  fs.git_enabled: True
vault: D:\DV\Task\DV_Agent_Harness_L5\v50\.dv-harness\vault
.git now exists: True
```

Then a baseline commit through the sanctioned mechanism (`memory_vault._commit_vault_change`),
bringing the 9 pre-existing real notes under version control:

```
$ git -C .dv-harness/vault log --oneline
6a701b6 memory(_general): baseline commit of pre-existing vault notes on enabling memory.git_enabled

$ git -C .dv-harness/vault ls-files
06_Agent_Memory/Engineering/MEM-0953BEC4D8.md   (+ 8 more real notes)
```

No memory content was fabricated to trigger this — the commit captures notes that already existed.

The project's own health check now agrees, where it previously reported `DISABLED`:

```
git check: {"status": "READY", "enabled": true, "uncommitted_changes": 0, "reason": null}
```

---

## 3. DuckDB — DONE

### What was actually broken

Stronger than "one shared store worth noting": the Knowledge Layer's DuckDB box had **no
implementation touching it at all, in either direction**. `evidence_db.py`'s `failure_signatures`
table is written exclusively from the Execution/Evidence side
(`EvidenceStore.insert_job_memory_record()`, fed by `lsf_client.py`/`regression_reporter.py` from
real JobState/sim.log evidence), and nothing on the Knowledge side ever read it back. The
accumulated `occurrence_count`/`first_seen`/`last_seen` history — "we have hit this exact failure
shape N times before", which the Markdown vault genuinely cannot know — was invisible to every
debug-time prior-evidence lookup.

### What changed

Wired the two **existing real** pieces together; built no parallel mechanism.

**`dv_harness/memory_vault.py`** — new `search_evidence_db_failure_signatures(root,
failure_signature, limit)`:

- Opens `EvidenceStore(default_db_path(root), read_only=True)`. Per that class's own docstring this
  skips `mkdir()` and all schema DDL entirely, and DuckDB's read-only connection refuses writes at
  the engine level. A Knowledge-Layer prior-evidence lookup can never create or migrate the
  Evidence Layer's database.
- Ranks with the **same** scoring `FileSystemMarkdownAdapter.search()` already uses rather than a
  second, divergent notion of relevance: `protocol` is a hard filter worth 3.0, and each shared
  query token adds 1.0 via the same `_tokenize` this module already imports from `memory.py`. That
  is what makes one merged `score`-descending sort meaningful across both stores.
- Stringifies DuckDB's `datetime` values for `first_seen`/`last_seen` — `related_cases` is embedded
  into real job-memory records (`lsf_client`'s `prior_related_knowledge`) and JSON-serialised.
- Best-effort and honest about absence: no DB file, no `duckdb` package, or a locked/corrupt file
  each return a distinct `reason` with empty results — never a raise, never a fabricated row. A
  missing evidence DB is a normal state (this project has none yet), not an error a debug attempt
  should feel.

`search_related_memory_for_debug()` now merges both sources into one ranked `related_cases`, each
entry tagged `source: "vault" | "evidence_db"`, and additionally reports `vault_count`,
`evidence_db_count` and an `evidence_db` sub-dict carrying that read's own ok/reason — so "the
evidence DB had nothing" and "there is no evidence DB" stay distinguishable rather than both
looking like an empty result.

**`dv_harness/prompts.py`** — `build_stage_prompt`'s `vault_related_cases` renderer. This was a
real would-be dead end at the far side of the new edge: an `evidence_db` row has no `frontmatter`
and no `note_id`, so the existing vault-shaped accessor would have rendered every one of them as a
content-free `- [?]` line. The case would have reached the Debug agent's prompt and said nothing.
Extracted `_format_vault_related_case()`, which formats an evidence_db row on its own terms (its
`signature_key` plus the aggregated `occurrence_count` — exactly what the Evidence Layer knows and
the vault does not) and falls back to the unchanged vault shape for any row with no `source`.

### Deliberately NOT done

`memory_vault`/`memory_router` still never **write** to DuckDB. That direction is correct as-is:
the Evidence Layer owns those tables and is their single writer, and adding a second writer from
the Knowledge side would create exactly the drift the `signature_key` dedup design exists to
prevent. The diagram's Knowledge-Layer DuckDB box is now a real **read** of the shared store,
which is the "one shared DuckDB, Knowledge Layer reads what Evidence Layer wrote" design the audit
itself named as valid.

---

## Tests — real connection tests, not per-component tests

New file: `dv_harness_tests/test_knowledge_layer_git_and_duckdb.py` (12 tests). These deliberately
prove the **edges**, since `test_memory_vault.py` already proved the Markdown adapter writes files
and `test_evidence_db.py` already proved `EvidenceStore` stores signatures — each piece working in
isolation was never the gap.

Knowledge Layer → Git:
1. `test_this_projects_live_config_actually_activates_vault_git` — asserts against **this
   repository's real `.dv-harness/config.json`**, not a fixture. A fixture would prove nothing about
   whether the live vault is git-backed, which was precisely the finding. Inheriting the `False`
   default fails it.
2. `test_live_config_makes_get_active_provider_hand_back_a_git_backed_adapter` — the concrete link
   from "config says true" to "the adapter will commit", through the one function every real vault
   caller goes via.
3. `test_route_and_store_end_to_end_produces_a_real_vault_git_commit` — the whole drawn chain in one
   call: `route_and_store()` → Markdown note → real commit → `knowledge_commit_sha` written back
   onto the JSON MemoryStore record. Asserts the returned SHA is really in `git log`, that the note
   is inside that commit (`git show --name-only`), and the exact `memory(USB2): ...` message — an
   initialised-but-never-committed repo would pass a weaker `.git`-exists check while leaving the
   edge dead.
4. `test_git_disabled_config_still_writes_markdown_but_never_a_repo` — the flag is genuinely the
   switch, not a decorative field.

Knowledge Layer → DuckDB:
5. `test_debug_search_merges_vault_notes_and_evidence_db_signatures` — one search surfaces **both**
   stores for the same failure, correctly tagged; seeded through the **real** Evidence-Layer write
   path (`EvidenceStore.insert_job_memory_record()`, what `lsf_client` calls) rather than a
   hand-written INSERT, so the test breaks if that path stops populating the table. Also asserts the
   merged result stays JSON-serialisable.
6. `test_evidence_db_occurrence_count_reaches_the_debug_search` — two real job failures with the
   same signature arrive as one row with `occurrence_count: 2`: the value the vault cannot supply.
7. `test_debug_search_does_not_surface_a_different_protocols_signature` — protocol is a hard filter
   on the DuckDB side exactly as on the vault side.
8. `test_missing_evidence_db_is_reported_honestly_and_never_created` — truthful reason, unaffected
   vault half, and **no database conjured into existence**.
9. `test_evidence_db_read_is_read_only_and_leaves_no_new_tables` — compares the real table list and
   the file's own bytes before/after a search.
10. `test_search_never_raises_when_the_evidence_db_is_corrupt` — degrades, never breaks a debug
    attempt.
11. `test_stage_prompt_renders_an_evidence_db_case_with_real_content` — the far end of the edge:
    asserts `- [?]` is absent and the signature key, root-cause hint and occurrence count all reach
    the prompt.
12. `test_stage_prompt_still_renders_untagged_vault_cases_unchanged` — backward compatibility for
    the pre-2026-09-04 row shape.

### Results

```
dv_harness_tests/test_knowledge_layer_git_and_duckdb.py            12 passed
memory + evidence-db suite (13 files: test_memory_vault, test_debug_flow_memory,
  test_memory_tier_completion, test_memory_tier_integrity_and_admission,
  test_memory_dedup, test_memory_doctor, test_memory_security,
  test_cli_memory_commands, test_obsidian_memory_final_integration,
  test_evidence_db, test_evidence_db_wiring, test_knowledge_layer_git_and_duckdb,
  test_react_working_memory_bridge)                                234 passed in 428.32s
```

**One transient failure, investigated and cleared**: the first combined run reported
`test_memory_doctor.py::test_doctor_reports_git_ready_when_everything_committed` as PARTIAL-not-
READY. It was **not** caused by this change — nothing here touches `memory_doctor.py`, `_run_git()`,
`_commit_vault_change()` or `check_git()`. It passed in isolation, passed with its own whole file,
and passed on an identical re-run of the same 13-file command (234/234). Cause is `_run_git()`'s
10-second subprocess timeout losing a `git commit` under load — that session had a concurrent
20-minute suite plus other agents' work running on the same machine, and a lost commit leaves
`git status --porcelain` dirty, which is exactly PARTIAL. Load-induced flake, not a regression.

---

## Concurrent-edit disclosure

Other agents were actively editing this repo throughout (a 14-AI-mechanism audit workflow and a live
remote USB build). `git status`/`git diff` was checked before touching anything. Files modified by
those agents and **not** touched here: `dv_harness/evidence_db.py`, `cli.py`, `dashboard.py`,
`lsf_client.py`, `connectivity.py`, `regression_reporter.py`, `engine.py`, `models.py`, `gates.py`
and their tests. `evidence_db.py` is read from but never modified — only its stable public API
(`default_db_path`, `EvidenceStore(..., read_only=True)`, `.query()`) is used. The commit was staged
hunk-by-hunk (`git diff` → trim → `git apply --cached`) rather than with a broad `git add`, so only
this work's own hunks are included.

## Files touched

- `.dv-harness/config.json` — added the `memory` block with `git_enabled: true` (+6 lines)
- `.gitignore` — ignore `.dv-harness/vault/`, now its own git repo (+13 lines, with rationale)
- `dv_harness/memory_vault.py` — new `search_evidence_db_failure_signatures()`; merged, source-tagged
  `related_cases` in `search_related_memory_for_debug()`
- `dv_harness/prompts.py` — `_format_vault_related_case()` so evidence_db rows render real content
- `dv_harness_tests/test_knowledge_layer_git_and_duckdb.py` — **new**, 12 connection tests

Not committed (generated, and now ignored): `.dv-harness/vault/.git` and its baseline commit — that
is the live vault's own repository, browsable with `git -C .dv-harness/vault log --oneline`.
