# Gap-close: Phase 20 + 21 + 22 (CLI Commands / `memory doctor` Health Check / Tests)

**Verdict: DONE** — one real gap closed (the missing `justfile` memory recipes), plus a
real quoting defect found and fixed while building it. Everything else in this scope was
re-confirmed READY against its cited evidence, unchanged.

Scope: audit-only re-confirmation of Phases 20/21/22, then close whatever was genuinely
closeable. No file in this scope was modified except the two named below.

Commit: `04dbf11` — `memory(cli): give the vault CLI a just recipe per subcommand`
(`justfile`, `dv_harness_tests/test_justfile.py`; +252 / -5).

Test summary: `374 passed in 313.78s` across all 15 memory/session test files plus
`test_justfile.py` and `test_run_profile_to_justfile.py` — 0 failed, 0 skipped, including
8 new tests.

---

## 1. Re-confirmation of the audit's READY verdicts

Every verdict was re-derived from the current tree, not taken from the audit text.

### Phase 20 — CLI Commands: **READY** (confirmed)

All 9 subcommands live under `python -m dv_harness memory <sub>`, integrated into the
existing `dv_harness/cli.py` rather than a separate CLI. Confirmed both by source and by a
live `--help` run, whose argparse choice list is exactly
`{status,search,show,add,promote,graph,validate,sync,doctor}`:

| Subcommand | `dv_harness/cli.py` |
|---|---|
| command group | `:906` |
| status | `:911` |
| search | `:914` (positional `query` + `--protocol --tag --level --exact --property --linked-to --project --confidence --status --limit`) |
| show | `:938` |
| add | `:941` |
| promote | `:958` |
| graph | `:970` |
| validate | `:975` |
| sync | `:980` |
| doctor | `:984` |

Note: the audit's line citations for this file were 3–5 lines low (it cited `:879-959`;
the block is actually `:906-987`). The content is exactly as described — the drift is
almost certainly concurrent edits above the block by other in-flight workflows, not an
error of substance.

### Phase 21 — `memory doctor`: **READY** (confirmed)

`dv_harness/memory_doctor.py` `run_doctor()` at `:309`, wiring 11 real checks at `:322-334`,
aggregated by `_aggregate()` (`:278-283`, BLOCKED > PARTIAL > READY). All 12 spec items map
onto real check functions — `check_vault_writable` `:93`, `check_git` `:104`,
`check_obsidian` `:133`, `check_filesystem_fallback` `:147`, `check_schema` `:153` (which
also covers "missing required metadata" via its per-note `missing_required` list),
`check_duplicate_ids` `:188`, `check_invalid_yaml` `:201`, `check_broken_links` `:206`,
`check_large_files` `:220`, `check_secrets` `:243`, plus the beyond-spec
`check_memory_store_index` `:254`.

Live run this pass, real and non-hardcoded:
`overall="PARTIAL"`, `blocked_reasons=[]`, `partial_reasons=["obsidian_cli","schema"]`,
with all 11 check keys present. `obsidian_cli` PARTIAL is the correct, disclosed
filesystem-fallback boundary (no Obsidian binary on this machine), not a gap.

Same note as above: the audit's line citations here were uniformly off by one
(`:92-100` for a function at `:93-100`, etc.). Content confirmed identical.

### Phase 22 — Tests: **READY** (confirmed)

`dv_harness_tests/test_obsidian_memory_final_integration.py` — all 14 spec cases present,
one function per case, confirmed by enumerating the file's own `def test_case_*` symbols:
`:91`, `:114`, `:153`, `:172`, `:192`, `:213`, `:242`, `:263`, `:336`, `:365`, `:386`,
`:414`, `:445`, `:473`. Case 02's SIMULATED label is honest and correct — it monkeypatches
`shutil.which`/`subprocess.run` because no real Obsidian binary exists here, and says so in
its own name. 14/14 present, 0 missing.

---

## 2. What was built

The audit's one named closeable gap: **no `justfile` recipe wrapped any memory subcommand**
(`grep -n memory justfile` previously matched only a comment on line 60).

This is worth closing rather than waving off as cosmetic because of what the justfile
itself is for. Its own header states its purpose — *"This exists to reduce ad hoc command
construction (`Claude 不需要自己拼長 command，降低誤操作`) — every remote command below is
one fixed recipe, not something composed free-hand per invocation."* It already wraps other
purely-local CLI groups on exactly that reasoning (`connectivity-check`,
`regression-tier-status`). The memory surface is the one an agent reaches for *mid-debug*,
which is precisely when a hand-typed
`python -m dv_harness.cli --project-root "…" memory search --property subsystem=… --limit 5`
is most likely to be composed wrong. So the gap was real and in-convention to close.

### `justfile` — one recipe per subcommand (`:369-414`)

`memory-status` `:369`, `memory-doctor` `:375`, `memory-validate` `:380`,
`memory-search` `:387`, `memory-show` `:391`, `memory-graph` `:395`, `memory-add` `:401`,
`memory-promote` `:407`, `memory-sync` `:413`.

Design decisions, all recorded as comments in the file:

- **None is `preflight`-gated.** Every one is local — the project's own vault plus its own
  `.dv-harness/` store. No LSF job, no license, no remote server. Gating them the way
  `build`/`verify`/`run` are gated would make an offline `just memory-doctor` fail for no
  reason.
- **`memory-doctor` / `memory-validate` are usable directly as CI or pre-commit gates**,
  because `cli.py` already exits non-zero only on a BLOCKED overall verdict. PARTIAL exits
  0 on purpose: an absent Obsidian CLI is a disclosed fallback, not a failure.
- **`memory-sync` omits `--message` entirely when none is given**, rather than passing
  `--message ""`. These are different requests — the CLI substitutes its own default commit
  message only for the former.

### A real defect found and fixed during the build

`just --dry-run` on the first draft rendered
`just memory-add USB --failure "enum timeout"` as `… memory add --protocol "USB" --failure enum timeout`.
just's `*variadic` interpolation (`{{args}}`) joins the caller's arguments with spaces and
**does not re-quote them**, so argparse would have received a stray positional. Confirmed
against the real CLI: the split form exits 2 with
`dv-harness: error: unrecognized arguments: training`.

Fixed with just's own documented idiom for this — `set positional-arguments := true`
(`justfile:45-56`) plus `"$@"` in every pass-through recipe, which forwards each argument
as one word with its quoting intact. That setting is purely additive: it binds shell
positionals that no pre-existing recipe references, and all 22 pre-existing
`test_justfile.py` tests still pass unchanged.

---

## 3. Tests written

Extended `dv_harness_tests/test_justfile.py` (the existing suite for this file) rather than
adding a parallel one. 8 new tests in a new `TestMemoryRecipes` class; 22 → 30 in the file.

These are behavioral, not parse-only:

- **`test_every_memory_cli_subcommand_has_a_recipe`** — cross-checks the recipe set against
  **argparse's own subcommand list**, read from a live `memory --help` subprocess. A
  subcommand added to `cli.py` without a recipe now fails a test instead of being noticed
  by nobody.
- **`test_real_run_memory_search_preserves_a_multi_word_query`** — **really runs** the
  recipe (no `--dry-run`) with `"link training"` and parses the resulting JSON. This is the
  only way to prove the `"$@"` forwarding survives the shell, since `--dry-run` renders the
  literal `"$@"` and can't see the expansion.
- **`test_negative_control_the_unquoted_split_form_really_fails`** — proves the test above
  is testing something: the same query as two bare words is rejected by argparse with
  `unrecognized arguments: training`. Without this control, the positive test would still
  pass under a broken implementation that happened to match on `"link"` alone.
- **`test_real_run_memory_doctor_reports_a_real_verdict`** — really runs the Phase-21 health
  check through the recipe and asserts the check *names* are present, rather than a fixed
  overall verdict, so it does not become a test of this one machine's vault contents.
- **`test_pass_through_recipes_forward_arguments_not_interpolate_them`** — regression guard
  pinning `"$@"` over `{{args}}` for search/add/promote, so the quoting fix cannot silently
  revert.
- Plus recipe-rendering tests for the no-arg trio, `show`/`graph` note-id quoting and depth
  default/override, `sync`'s conditional `--message`, and the never-preflight-gated property.

Stale-content cleanup in the same file, per the project's Engineering Discipline Rules: the
module docstring claimed *"Never executes a recipe body for real"* and *"`just` itself is
the only subprocess these tests spawn"* — both now false, so the docstring was rewritten to
state exactly which recipes are executed for real and why only those are safe. The file's
previously-unused `import sys` (dead since it was written) is now genuinely used by the
negative-control test.

---

## 4. Verification

```
python -m pytest dv_harness_tests/test_cli_memory_commands.py \
  dv_harness_tests/test_debug_flow_memory.py \
  dv_harness_tests/test_job_memory_evidence_mirror.py \
  dv_harness_tests/test_memory_dedup.py dv_harness_tests/test_memory_doctor.py \
  dv_harness_tests/test_memory_review_skill.py \
  dv_harness_tests/test_memory_search_filters.py \
  dv_harness_tests/test_memory_security.py \
  dv_harness_tests/test_memory_tier_completion.py \
  dv_harness_tests/test_memory_tier_integrity_and_admission.py \
  dv_harness_tests/test_memory_vault.py \
  dv_harness_tests/test_memory_write_guard_and_job_evidence.py \
  dv_harness_tests/test_obsidian_memory_final_integration.py \
  dv_harness_tests/test_react_working_memory_bridge.py \
  dv_harness_tests/test_session_and_info.py \
  dv_harness_tests/test_justfile.py dv_harness_tests/test_run_profile_to_justfile.py -q
```

→ **`374 passed in 313.78s (0:05:13)`**, 0 failed, 0 skipped.

Confirmed no side effects from the real recipe runs: `git status --porcelain .dv-harness/vault`
is empty afterward (the doctor's writability probe cleans up after itself).

Concurrency discipline: another workflow committed `2c0e841` between my staging and my
commit. The commit was hand-scoped to the two files I own (`git add` of exact paths, then
`git diff --cached --stat` verified to be exactly those two before committing), so nothing
of theirs was swept in. Neither `CLAUDE.md`, `cli.py`, `memory.py`, nor `memory_router.py`
was touched by this pass.

---

## 5. Remaining state of this scope

No BLOCKED items. No PARTIAL items other than the one deliberate, disclosed boundary:
`obsidian_cli` reports PARTIAL because no Obsidian binary exists on this machine, and the
filesystem fallback carries the load — correct as designed, and honestly labeled in both
`memory doctor`'s output and integration test case 02. Left as-is.
