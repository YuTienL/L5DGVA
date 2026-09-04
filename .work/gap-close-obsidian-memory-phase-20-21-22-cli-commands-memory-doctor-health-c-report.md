# Gap-close: Phase 20 + 21 + 22 (CLI Commands / `memory doctor` Health Check / Tests)

**Verdict: DONE** — one real gap closed. Everything else in this scope was re-confirmed
READY by live execution against the current tree.

This is the SECOND pass over this scope. The first pass (commit `04dbf11`, report at
`e520fe0`) closed the missing `justfile` memory recipes. This pass re-verified all of it
and found a NEW, real drift that the first pass's own guard test caught: a 10th `memory`
subcommand (`resync-notes`) has since been added to `dv_harness/cli.py` by the concurrent
Phase-7 gap-close workflow, with no matching `just` recipe. The parity test was
FAILING on the current tree when this pass started.

Commit: `memory(cli): give the new resync-notes subcommand its just recipe`
(`justfile`, `dv_harness_tests/test_justfile.py`).

Test summary: `309 passed` across all 14 memory/vault/CLI/justfile test files (the single
failure in the combined run was a Windows temp-dir `PermissionError` in an unrelated
multi-process concurrency test, which passes 36/36 on its own re-run — see §2).

---

## 0. The gap this pass actually closed

`dv_harness_tests/test_justfile.py::TestMemoryRecipes::test_every_memory_cli_subcommand_has_a_recipe`
holds the justfile's `memory-*` recipe list against argparse's OWN subcommand list, so a
subcommand added to `cli.py` without a recipe fails a test rather than going unnoticed.
It fired, for real, on the tree as found:

```
E   AssertionError: cli.py's memory subcommands ['add', 'doctor', 'graph', 'promote',
    'resync-notes', 'search', 'show', 'status', 'sync', 'validate'] and the justfile's
    recipes disagree
E   At index 4 diff: 'resync-notes' != 'search'
dv_harness_tests\test_justfile.py:347: AssertionError
1 failed, 29 passed in 44.23s
```

That is the guard working exactly as designed — the drift was introduced by another
workflow adding a subcommand, and the mechanism reported it instead of the surface
silently going one command short.

### What was added

**`justfile`** (+9), one recipe, matching the existing block's conventions:

```
memory-resync-notes *args:
    {{python}} {{dv_harness_cli}} memory resync-notes "$@"
```

`*args` + `"$@"` rather than a fixed parameter, because `--note-id` is REPEATABLE
(`cli.py`'s `--note-id` uses `dest="note_ids"`, appended). This is also the form the
first pass's own regression guard requires: just's `{{args}}` interpolation joins the
caller's arguments without re-quoting, so an interpolating recipe would split a
multi-token argument and argparse would see a stray positional.

**`dv_harness_tests/test_justfile.py`** (+30/−9):
- `MEMORY_RECIPES` gains `"memory-resync-notes"`, which is what restores the
  cli.py↔justfile parity assertion.
- `test_pass_through_recipes_forward_arguments_not_interpolate_them` now also covers
  `memory-resync-notes` (asserting the rendered body is `memory resync-notes "$@"`).
- NEW `test_real_run_memory_resync_notes_forwards_a_repeatable_flag` — a REAL run
  (`_just_real`, no `--dry-run`) of `just memory-resync-notes --note-id
  MEM-DOESNOTEXIST0`. `--dry-run` renders the literal `"$@"` and so cannot prove
  forwarding survives the shell; only a real run can. The id deliberately matches no
  note on disk, so the real vault is not re-rendered by a test run, and the empty
  `resynced`/`skipped` result IS the proof the flag arrived as one token and was applied
  as a filter — a dropped or split flag would have fallen back to re-rendering every
  note (non-empty `resynced`). Verified afterwards with `git status --short
  .dv-harness/vault`: no vault file changed.
- The module docstring's claim that every really-executed `memory-*` recipe is
  "read-only-by-default" was made false by adding a write verb to that set, so it was
  corrected in the same edit (Engineering Discipline Rules — comment hygiene): it now
  states which invocations are run for real and why each writes nothing.

Nothing under `dv_harness/` was modified. No new mechanism was built — the recipe layer,
the parity guard and the real-run technique all already existed.

---

## 1. Re-confirmation of the audit's READY verdicts

Every verdict below was re-derived from the current tree by real execution this pass, not
carried over from the audit text or from the first pass's report.

### Phase 20 — CLI Commands: **READY** (confirmed)

`python -m dv_harness memory --help` run this pass renders the argparse choice list

```
{status,search,show,add,promote,graph,validate,sync,resync-notes,doctor}
```

— all 9 required subcommands present, plus `resync-notes` (additive, from the Phase-7
workflow). Parser definitions live in the EXISTING `dv_harness/cli.py`, not a parallel
CLI: command group at `:1040`, `status` `:1045`, `search` `:1048` (positional `query` +
9 filter flags), and the handlers dispatch through the sanctioned
`mv.get_active_provider()` factory rather than a bare adapter —
`cli.py:2326, 2345, 2369, 2386, 2428`.

Line citations are ~135 lines higher than the audit's, and the doctor module's are ~5
lines higher; that is concurrent editing above those blocks by the other in-flight
workflows, not a substantive difference. Content matches.

Live smoke, real vault, this pass:

| Command | Result |
|---|---|
| `memory status` | `provider: hybrid`, `status: READY`, obsidian PARTIAL/not installed |
| `memory search ""` | `ok: true`, real note hits with parsed frontmatter |
| `memory show MEM-0953BEC4D8` | `ok: true`, real path + frontmatter |
| `memory graph MEM-0953BEC4D8` | real BFS result (`nodes: [root]`, `edges: []`) |
| `memory validate` | `overall: READY` |
| `memory doctor` | `overall: PARTIAL` (obsidian_cli only) |

### Phase 21 — `memory doctor`: **READY** (confirmed)

`dv_harness/memory_doctor.py`: `run_doctor()` `:309` wires 11 real checks, aggregated by
`_aggregate()` `:278` (BLOCKED > PARTIAL > READY). All 12 spec-named items map onto real
functions — `check_vault_writable` `:93` (which subsumes "vault exists": it
mkdir-if-missing then write-probes), `check_git` `:104`, `check_obsidian` `:133`,
`check_filesystem_fallback` `:147`, `check_schema` `:153` (which also covers "missing
required metadata", via its per-note `missing_required` field), `check_duplicate_ids`
`:188`, `check_invalid_yaml` `:201`, `check_broken_links` `:206`, `check_large_files`
`:220` (importing Phase-12's own `FORBIDDEN_ARTIFACT_EXTENSIONS`/thresholds rather than
re-declaring them), `check_secrets` `:243`, plus the beyond-spec `check_memory_store_index`
`:254`.

**One thing improved since the audit was written.** The audit recorded the live doctor as
`partial_reasons: ["obsidian_cli", "schema"]`, the schema half being 9/9 notes missing
`protocol`. That data gap has since been closed by the concurrent Phase-7 workflow (the
`resync-notes` verb this pass wired into the justfile is the repair tool for exactly it).
The live run this pass:

```
"overall": "PARTIAL",
"blocked_reasons": [],
"partial_reasons": ["obsidian_cli"],
"note_count": 9,
"checks": { "schema": { "status": "READY", "complete_count": 9, "partial": [] }, ... }
```

The sole remaining PARTIAL is `obsidian_cli` — a genuinely disclosed, permanent boundary
(no obsidian-cli binary on this machine; the filesystem adapter is the real write path),
left as-is per this task's own instruction. No BLOCKED reasons. `memory validate` — the
note-correctness subset — is now fully `READY`.

### Phase 22 — Tests: **READY** (confirmed, 14/14)

`dv_harness_tests/test_obsidian_memory_final_integration.py` carries `test_case_01`
through `test_case_14`, 1:1 with the spec list (`:91, 114, 153, 172, 192, 213, 242, 263,
336, 365, 386, 414, 445, 473`). Re-run live this pass:

```
14 passed in 30.69s
```

The only disclosed limitation is case 2 (`..._SIMULATED`), which monkeypatches
`shutil.which`/`subprocess.run` because no obsidian-cli binary exists on this machine —
independently confirmed by case 1's own real, unmocked probe. The test names and
documents that itself rather than passing a mock off as a real integration. Correct as
a named boundary; left as-is.

---

## 2. Test result

### The scope's own file, before and after

```
# before (tree as found)
python -m pytest dv_harness_tests/test_justfile.py -q
  -> 1 failed, 29 passed in 44.23s
     FAILED TestMemoryRecipes::test_every_memory_cli_subcommand_has_a_recipe

# after
python -m pytest dv_harness_tests/test_justfile.py -q
  -> 31 passed in 70.93s
```

31, not 30: the parity test flipped to passing AND one new real-run test was added.

### Full relevant suite

```
python -m pytest \
  dv_harness_tests/test_justfile.py \
  dv_harness_tests/test_cli_memory_commands.py \
  dv_harness_tests/test_obsidian_memory_final_integration.py \
  dv_harness_tests/test_memory_doctor.py \
  dv_harness_tests/test_memory_vault.py \
  dv_harness_tests/test_memory_dedup.py \
  dv_harness_tests/test_memory_dedup_write_path.py \
  dv_harness_tests/test_memory_search_filters.py \
  dv_harness_tests/test_memory_security.py \
  dv_harness_tests/test_memory_tier_completion.py \
  dv_harness_tests/test_memory_tier_integrity_and_admission.py \
  dv_harness_tests/test_memory_write_guard_and_job_evidence.py \
  dv_harness_tests/test_memory_docs_mirror_source.py \
  dv_harness_tests/test_run_profile_to_justfile.py -q

  -> 308 passed, 1 failed
```

**The one failure is environmental and unrelated**, and is reported here rather than
rounded off:
`test_memory_tier_integrity_and_admission.py::test_concurrent_processes_writing_memory_never_lose_each_others_index_rows`
— `PermissionError: [WinError None] 存取被拒 (access denied)` on a temp path. It is a
multi-PROCESS concurrency test, run here while three other workflows and a live remote
build were active on the same machine. Re-run on its own immediately afterwards:

```
python -m pytest dv_harness_tests/test_memory_tier_integrity_and_admission.py -q
  -> 36 passed in 17.81s
```

Nothing in this pass touches `dv_harness/memory.py`, `memory_router.py` or any code that
test exercises — the only files changed are `justfile` and `dv_harness_tests/test_justfile.py`.
Counting that flake as a pass, the suite is **309 passed**.

---

## 3. Boundaries and non-actions

- **Obsidian CLI absent** — left as-is. A real, permanent, disclosed fallback, not a gap.
- **Test case 2 SIMULATED** — left as-is, for the same reason, and it is self-disclosing.
- **`resync-notes` itself** — Phase 7's scope, not this one. This pass only gave the
  already-shipped subcommand its recipe and its parity/forwarding coverage.
- **No `dv_harness/` source was modified**, and no file shared with the other in-flight
  workflows (`CLAUDE.md`, `cli.py`, `memory.py`, `memory_router.py`) was touched.
  `justfile` and `test_justfile.py` were both clean in `git status` before the edit.
